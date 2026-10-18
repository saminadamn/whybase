"""The fixed tool catalogue: schemas for the LLM, argument validation, the resolver step,
query execution, and everything derived from rows (paths, sources, highlights, template sentences).

The LLM only ever picks a tool name and fills arguments. Each tool maps to exactly one
hand-written query in backend/queries/. Entity arguments are resolved against the graph
before the traversal runs; if they do not resolve, nothing else runs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from backend import db

STOPWORDS = set("""
a an and are as at be by did do does for from how in is it its of on or our the this that to
use used uses using was we were what when where which who why with you they run runs running
have has had still now ever kettle labs company decide decided choose chose pick picked
all any every everyone everybody team today tomorrow monday let lets should will would going can could
our out about into over just also more most some there their them then than been being get got make
""".split())


# ---------------------------------------------------------------- data shapes

@dataclass
class ToolResult:
    """Everything one tool call produced. Built only from graph rows."""
    tool: str
    args: dict[str, Any]
    status: str = "ok"                 # ok | empty | unknown | choices
    rows: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    paths: list[list[str]] = field(default_factory=list)
    steps: list[list[dict[str, Any]]] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    highlight: list[str] = field(default_factory=list)
    stale: bool = False
    sentence: str = ""
    subject: str = ""                  # the resolved entity, for "nothing connects"
    choices: list[dict[str, Any]] = field(default_factory=list)
    needs_entity: bool = True


def step(node: str, kind: str, rel: str | None = None, direction: str | None = None,
         status: str | None = None, at: str | None = None) -> dict[str, Any]:
    """One node in a displayed path; rel/direction describe the edge from the previous node."""
    return {"id": node, "kind": kind, "rel": rel, "dir": direction, "status": status, "at": at}


def fmt_date(iso: str | None) -> str:
    if not iso:
        return "an unknown date"
    d = date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%b %Y')}"


def short_source(title: str | None) -> str:
    """'ADR-007: Migrate event bus to Kafka' -> 'ADR-007'."""
    if not title:
        return "no source"
    return title.split(":")[0] if title.startswith("ADR-") else f"“{title}”"


def tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 2 and t not in STOPWORDS}


def _uniq(items: list[str | None]) -> list[str]:
    return list(dict.fromkeys(i for i in items if i))


# ---------------------------------------------------------------- tool schemas (LLM-facing)

TOOL_SPECS: dict[str, dict[str, Any]] = {
    "why": {
        "description": "Explain why a system works the way it does: the active decision(s) about it and the chain of decisions they superseded, with sources and deciders.",
        "parameters": {"system": {"type": "string", "description": "System name, e.g. event-bus"}},
        "required": ["system"],
    },
    "stale_docs": {
        "description": "List sources (docs, chats, tickets) that assume a decision which has since been superseded, and who should fix each.",
        "parameters": {}, "required": [],
    },
    "who_knows": {
        "description": "Rank people by how many sources they wrote about a system, including people who left.",
        "parameters": {"system": {"type": "string", "description": "System name, e.g. payments-ledger"}},
        "required": ["system"],
    },
    "knowledge_risk": {
        "description": "Systems whose knowledge depends on one active person or fewer.",
        "parameters": {}, "required": [],
    },
    "reversal_impact": {
        "description": "Everything (decisions and projects) that relies on a decision, up to 3 hops, i.e. what breaks if it is reversed.",
        "parameters": {"decision": {"type": "string", "description": "Decision id like D-002, or words from its summary"}},
        "required": ["decision"],
    },
    "load_bearing": {
        "description": "Most load-bearing decisions by PageRank over RELIES_ON.",
        "parameters": {"limit": {"type": "integer", "minimum": 1, "maximum": 10, "description": "How many (default 5)"}},
        "required": [],
    },
    "as_of": {
        "description": "What the company believed about a system on a given date (point-in-time view).",
        "parameters": {
            "system": {"type": "string", "description": "System name, e.g. search-index"},
            "date": {"type": "string", "description": "ISO date YYYY-MM-DD"},
        },
        "required": ["system", "date"],
    },
}

TOOL_QUERY = {"why": "why", "stale_docs": "stale_all", "who_knows": "who_knows", "knowledge_risk": "knowledge_risk",
              "reversal_impact": "reversal_impact", "load_bearing": "load_bearing", "as_of": "as_of"}


def llm_tools() -> list[dict[str, Any]]:
    """Tool definitions in OpenAI/LiteLLM function-calling format."""
    return [{"type": "function", "function": {
        "name": name, "description": spec["description"],
        "parameters": {"type": "object", "properties": spec["parameters"], "required": spec["required"]},
    }} for name, spec in TOOL_SPECS.items()]


# ---------------------------------------------------------------- resolver

def _traced(trace: list[dict], name: str, /, **params: Any) -> list[dict[str, Any]]:
    rows, ms = db.run_ro(name, **params)
    trace.append({"tool": name, "query": name, "args": params, "rows": len(rows), "ms": ms})
    return rows


def resolve_system(raw: str, trace: list[dict]) -> str | None:
    """Exact (case-insensitive) match, then the same with spaces turned into hyphens, then a technology
    named in decisions about exactly one system ("KMS" -> secrets-vault). Kebab-case names are never
    mapped by topic, so a made-up system like "quantum-cache" stays unknown."""
    for candidate in _uniq([raw.strip(), raw.strip().lower().replace(" ", "-")]):
        rows = _traced(trace, "resolve_system", name=candidate)
        if rows:
            return rows[0]["name"]
    word = raw.strip()
    if len(word) < 3 or "-" in word or len(word.split()) > 2:
        return None
    rows = _traced(trace, "system_for_topic", q=word)
    pattern = re.compile(rf"(?<![\w-]){re.escape(word.lower())}(?![\w-])")
    systems = {r["name"] for r in rows if pattern.search(r["summary"].lower())}
    return systems.pop() if len(systems) == 1 else None


def resolve_decision(raw: str, trace: list[dict]) -> tuple[dict | None, list[dict]]:
    """Return (decision, []) when it resolves to one, (None, candidates) when ambiguous."""
    rows = _traced(trace, "resolve_decision", q=raw.strip())
    exact = [r for r in rows if r["id"] == raw.strip().upper()]
    if exact:
        return exact[0], []
    if len(rows) == 1:
        return rows[0], []
    return None, rows


class ArgError(Exception):
    def __init__(self, message: str, subject: str = "", choices: list[dict] | None = None):
        super().__init__(message)
        self.subject = subject
        self.choices = choices or []


def _resolve_args(tool: str, raw: dict[str, Any], trace: list[dict]) -> dict[str, Any]:
    args: dict[str, Any] = {}
    if "system" in TOOL_SPECS[tool]["parameters"]:
        name = str(raw.get("system") or "").strip()[:80]
        if not name:
            raise ArgError("I couldn't find a system name in that question, so no query was run.")
        resolved = resolve_system(name, trace)
        if not resolved:
            raise ArgError(f"`{name}` isn't in the graph, so no query was run.", subject=name)
        args["system"] = resolved
    if tool == "reversal_impact":
        ref = str(raw.get("decision") or "").strip()[:80]
        if not ref:
            raise ArgError("I couldn't tell which decision you mean, so no query was run.")
        decision, candidates = resolve_decision(ref, trace)
        if decision is None and candidates:
            raise ArgError(f"`{ref}` matches {len(candidates)} decisions. Which one did you mean?", ref, candidates)
        if decision is None:
            raise ArgError(f"`{ref}` isn't in the graph, so no query was run.", subject=ref)
        args["decision"], args["_status"] = decision["id"], decision["status"]
    if tool == "as_of":
        value = str(raw.get("date") or "")
        try:
            args["date"] = date.fromisoformat(value).isoformat()
        except ValueError:
            raise ArgError(f"`{value}` isn't a date I can read (use YYYY-MM-DD), so no query was run.", subject=value)
    if tool == "load_bearing":
        try:
            args["limit"] = max(1, min(10, int(raw.get("limit") or 5)))
        except (TypeError, ValueError):
            args["limit"] = 5
    return args


# ---------------------------------------------------------------- per-tool builders (rows -> answer parts)

def _topic_decision(question: str, rows: list[dict], system: str) -> dict | None:
    """The earliest decision in the chain whose summary shares a content word with the question.
    'Why do we use Kafka…' -> the decision that introduced Kafka."""
    # Prefer words that aren't part of the system's name ("Kafka" in "...Kafka for the event bus").
    # If the question doesn't name the system, its words can be the topic ("Why did we use Vault?").
    named = system in question.lower() or system.replace("-", " ") in question.lower()
    words = tokens(question)
    specific = words - tokens(system.replace("-", " "))
    words = specific if (named or specific) else words
    seen = {r["id"]: r for r in sorted(rows, key=lambda r: r["at"])}
    return next((r for r in seen.values() if words & tokens(r["decision"])), None)


def _build_why(res: ToolResult, question: str) -> None:
    system = res.args["system"]
    chains: dict[str, list[dict]] = {}
    for r in res.rows:
        chains.setdefault(r["head"], []).append(r)
    for chain in chains.values():
        res.paths.append([system] + [r["id"] for r in chain])
        res.steps.append([step(system, "System")] + [
            step(r["id"], "Decision", "SUPERSEDES" if i else "ABOUT", "→" if i else "←", r["status"], r["at"])
            for i, r in enumerate(chain)])
    res.sources = _uniq([r["source_id"] for r in res.rows])
    res.highlight = _uniq([system] + [r["id"] for r in res.rows] + res.sources + [r["by"] for r in res.rows])

    topic = _topic_decision(question, res.rows, system)
    if topic and topic["status"] == "superseded":
        res.stale = True
        head = next(c[0] for c in chains.values() if topic["id"] in {r["id"] for r in c})
        res.sentence = (f"Out of date: {topic['id']} ({topic['decision']}) no longer holds. {system} now follows "
                        f"{head['id']}: {head['decision']}, decided by {head['by']} on {fmt_date(head['at'])}.")
        return
    focus = [c for c in chains.values() if topic and topic["id"] in {r["id"] for r in c}] or list(chains.values())
    if len(focus) > 1:
        res.sentence = f"{system} has {len(focus)} active decisions: " + "; ".join(
            f"{c[0]['id']} {c[0]['decision']} ({c[0]['by']}, {short_source(c[0]['source'])})" for c in focus) + "."
        return
    head, *older = focus[0]
    text = (f"{system} follows {head['id']}: {head['decision']}, decided by {head['by']} on "
            f"{fmt_date(head['at'])} ({short_source(head['source'])}).")
    for r in older:
        text += f" It replaced {r['id']}: {r['decision']} ({r['by']}, {fmt_date(r['at'])}, {short_source(r['source'])})."
    res.sentence = text


def _build_stale(res: ToolResult, question: str) -> None:
    for r in res.rows:
        res.paths.append([r["source_id"], r["old_id"], r["now_id"]])
        res.steps.append([step(r["source_id"], "Source"),
                          step(r["old_id"], "Decision", "ASSUMES", "→", "superseded"),
                          step(r["now_id"], "Decision", "SUPERSEDES", "←", "active", r.get("changed_at"))])
    res.sources = _uniq([r["source_id"] for r in res.rows])
    res.highlight = _uniq([x for p in res.paths for x in p] + [n for r in res.rows for n in r["fix_by"]])
    res.stale = bool(res.rows)
    if not res.rows:
        res.sentence = "No sources are out of date. Every doc matches current decisions."
        return
    items = "; ".join(f"“{r['stale_doc']}” ({r['old_id']} → {r['now_id']})" for r in res.rows)
    res.sentence = (f"{len(res.rows)} sources assume a decision that has since been replaced: {items}. "
                    "The Out of date list says who should fix each.")


def _build_who(res: ToolResult, question: str) -> None:
    system = res.args["system"]
    for r in res.rows:
        via = (r.get("via_ids") or [None])[0]
        res.paths.append([system, via, r["person"]] if via else [system, r["person"]])
        res.steps.append([step(system, "System"), step(via, "Source", "MENTIONS", "←"),
                          step(r["person"], "Person", "AUTHORED_BY", "→", r["status"])])
    res.sources = _uniq([i for r in res.rows for i in r.get("via_ids", [])])
    res.highlight = _uniq([system] + [r["person"] for r in res.rows] + res.sources)
    if not res.rows:
        return
    top = res.rows[0]
    active = [r["person"] for r in res.rows if r["status"] == "active"]
    text = (f"{top['person']}{' (left the company)' if top['status'] == 'left' else ''} has the most evidence on "
            f"{system}: {top['evidence']} source{'s' if top['evidence'] != 1 else ''}.")
    if not active:
        text += " Nobody active has written about it."
    elif len(active) == 1:
        text += f" {active[0]} is the only active person with evidence, so this knowledge is at risk."
    else:
        text += f" Active people with evidence: {', '.join(active)}."
    res.sentence = text


def _build_risk(res: ToolResult, question: str) -> None:
    for r in res.rows:
        people = r["active"] + r["gone"]
        res.paths.append([r["system"]] + people)
        res.steps.append([step(r["system"], "System")] + [
            step(p, "Person", "AUTHORED SOURCES ON", "←", "active" if p in r["active"] else "left") for p in people])
    res.highlight = _uniq([x for p in res.paths for x in p])
    if not res.rows:
        res.sentence = "No system depends on a single person."
        return
    parts = []
    for r in res.rows:
        who = ", ".join(r["active"]) or "nobody active"
        parts.append(f"{r['system']} ({who}{'; ' + ', '.join(r['gone']) + ' left' if r['gone'] else ''})")
    res.sentence = f"{len(res.rows)} systems depend on one active person or fewer: {'; '.join(parts)}."


def _build_reversal(res: ToolResult, question: str) -> None:
    did = res.args["decision"]
    for r in res.rows:
        res.paths.append(r["via"])
        res.steps.append([step(n, r["kind"] if i == 0 else "Decision", "RELIES_ON" if i else None, "→" if i else None)
                          for i, n in enumerate(r["via"])])
    res.highlight = _uniq([x for p in res.paths for x in p] + [did])
    res.subject = did
    if not res.rows:
        return
    nearest: dict[str, int] = {}                      # one entry per affected item, at its shortest distance
    for r in res.rows:
        nearest[r["affected"]] = min(r["hops"], nearest.get(r["affected"], r["hops"]))
    by_hops: dict[int, list[str]] = {}
    for name, hops in nearest.items():
        by_hops.setdefault(hops, []).append(name)
    spread = "; ".join(f"{', '.join(sorted(names))} at {h} hop{'s' if h > 1 else ''}" for h, names in sorted(by_hops.items()))
    n, far = len(nearest), max(r["hops"] for r in res.rows)
    if res.args.get("_status") == "superseded":
        res.stale = True
        heads = _traced(res.trace, "current_head", id=did)
        now = f" by {heads[0]['id']}" if heads else ""
        if heads:
            res.args["superseded_by"] = heads[0]["id"]
        res.highlight += [h["id"] for h in heads]
        res.sentence = f"{did} is already superseded{now}, yet {n} things still rely on it: {spread}."
    else:
        res.sentence = f"Reversing {did} would affect {n} things up to {far} hop{'s' if far > 1 else ''} away: {spread}."


def _build_load(res: ToolResult, question: str) -> None:
    for r in res.rows:
        res.paths.append([r["id"]])
        res.steps.append([step(r["id"], "Decision", status=r["status"])])
        r["score"] = round(float(r["score"]), 4)
    res.highlight = [r["id"] for r in res.rows]
    if not res.rows:
        res.sentence = "No decision relies on another yet."
        return
    top, rest = res.rows[0], [r["id"] for r in res.rows[1:3]]
    res.sentence = f"The most load-bearing decision is {top['id']} ({top['decision']})"
    res.sentence += f", followed by {' and '.join(rest)}." if rest else "."
    if top["status"] == "superseded":
        res.stale = True
        res.sentence += f" {top['id']} is superseded, but other decisions still rely on it."


def _build_as_of(res: ToolResult, question: str) -> None:
    system, when = res.args["system"], res.args["date"]
    for r in res.rows:
        res.paths.append([system, r["id"]] + ([r["source_id"]] if r["source_id"] else []))
        res.steps.append([step(system, "System"), step(r["id"], "Decision", "ABOUT", "←", r["status"], r["since"])]
                         + ([step(r["source_id"], "Source", "RECORDED_IN", "→")] if r["source_id"] else []))
    res.sources = _uniq([r["source_id"] for r in res.rows])
    res.highlight = _uniq([x for p in res.paths for x in p])
    if not res.rows:
        return
    beliefs = "; ".join(f"{r['believed']} ({r['id']}, since {fmt_date(r['since'])} · {short_source(r['source'])})"
                        for r in res.rows)
    res.sentence = f"On {fmt_date(when)}, Kettle Labs believed: {beliefs}."
    if any(r["status"] == "superseded" for r in res.rows):
        res.stale = True
        res.sentence += " That has since been replaced."


BUILDERS: dict[str, Callable[[ToolResult, str], None]] = {
    "why": _build_why, "stale_docs": _build_stale, "who_knows": _build_who, "knowledge_risk": _build_risk,
    "reversal_impact": _build_reversal, "load_bearing": _build_load, "as_of": _build_as_of,
}
NO_ENTITY_TOOLS = {"stale_docs", "knowledge_risk", "load_bearing"}


def _query_params(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    if tool == "reversal_impact":
        return {"id": args["decision"]}
    return {k: v for k, v in args.items() if not k.startswith("_")}


# ---------------------------------------------------------------- executor

def execute(tool: str, raw_args: dict[str, Any] | None, question: str = "") -> ToolResult:
    """Validate + resolve args, run the tool's catalogue query read-only, build the answer parts."""
    if tool not in TOOL_SPECS:
        return ToolResult(tool=tool, args={}, status="unknown",
                          sentence=f"`{tool}` isn't a WhyBase tool, so no query was run.", subject=tool)
    res = ToolResult(tool=tool, args={}, needs_entity=tool not in NO_ENTITY_TOOLS)
    try:
        res.args = _resolve_args(tool, raw_args or {}, res.trace)
    except ArgError as err:
        res.status = "choices" if err.choices else "unknown"
        res.sentence, res.subject = str(err), err.subject
        res.choices = [{"id": c["id"], "label": f"{c['id']} · {c['summary']}", "status": c["status"]} for c in err.choices]
        return res
    query = TOOL_QUERY[tool]
    rows, ms = db.run_ro(query, **_query_params(tool, res.args))
    res.trace.append({"tool": tool, "query": query, "args": _query_params(tool, res.args), "rows": len(rows), "ms": ms})
    res.rows = rows
    res.subject = res.args.get("system", res.args.get("decision", ""))
    BUILDERS[tool](res, question)
    if not rows:
        res.status = "empty"
    return res


def public_args(args: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in args.items() if not k.startswith("_")}
