"""The question-answering agent.

Online: the LLM (via LiteLLM) picks tools from the fixed catalogue and writes one short sentence.
Offline: router_offline picks the tool and the template sentence is used.
Either way the structured answer (outcome, paths, sources, highlight, trace) comes from graph rows,
and the final sentence passes an answer check against those rows.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

import litellm

from backend import db, router_offline, tools
from backend.router_offline import PLAIN_HYPHENATED
from backend.tools import ToolResult

log = logging.getLogger("whybase.agent")
MAX_TOOL_CALLS = 4
LLM_TIMEOUT_S = 15
QUESTION_BUDGET_S = 20   # after this, answer from the tool results already fetched
MAX_COOLDOWN_S = 3600    # after a rate limit, skip the LLM for the provider's retry delay (capped)
_cooldown_until = 0.0
KEBAB = re.compile(r"\b[a-z][a-z0-9]*(?:-[a-z0-9]+)+\b")
NO_CONNECTION = ("The graph knows {x}, but nothing links it the way the question assumes. "
                 "That may mean the link isn't recorded.")

SYSTEM_PROMPT = """You are WhyBase, the company brain for Kettle Labs (a fictional company).
WhyBase stores people, teams, systems, projects, sources (docs, chats, tickets, ADRs) and decisions
in a graph. You answer questions only by calling the provided tools, which run fixed graph queries.

Rules:
- Call a tool for every factual claim. Never answer from memory.
- Never invent names, systems, decisions or dates. Use only names that appear in tool results.
- System names are kebab-case, e.g. event-bus, payments-ledger, search-index. Decisions look like D-002.
- When the question names a technology (Kafka, Vault, KMS, React Native) instead of a system, pass the system
  it belongs to from the list below; if unsure, pass the technology word and WhyBase will look it up.
- Dates for as_of must be YYYY-MM-DD.
- After the tool results arrive, answer in 1-3 short, plain sentences. No lists, no markdown, no exclamation marks.
- If a tool returns nothing, say plainly that the graph has nothing for that.
- Use at most 4 tool calls."""


# ---------------------------------------------------------------- mode

def llm_model() -> str:
    return os.getenv("LLM_MODEL", "").strip()


def llm_cooldown_s() -> int:
    """Seconds left before the LLM is tried again after a rate limit (0 = not paused)."""
    return max(0, round(_cooldown_until - time.time()))


def _start_cooldown(exc: Exception) -> None:
    """Pause LLM calls for the retry delay the provider asked for (default 60 s)."""
    global _cooldown_until
    found = re.search(r"retry(?:Delay\"?:\s*\"| in )(\d+(?:\.\d+)?)s", str(exc))
    delay = float(found[1]) if found else 60.0
    _cooldown_until = time.time() + min(delay, MAX_COOLDOWN_S)


def llm_online() -> bool:
    """True when a model is configured and LiteLLM can see its API key."""
    model = llm_model()
    if not model:
        return False
    try:
        return bool(litellm.validate_environment(model).get("keys_in_environment"))
    except Exception as exc:  # noqa: BLE001 - unknown provider etc. means offline
        log.warning("LLM %s unavailable (%s); running offline", model, exc)
        return False


# ---------------------------------------------------------------- answer check

def entity_names() -> list[str]:
    rows, _ = db.run_ro("entities")
    return [r["name"] for r in rows]


def check_sentence(sentence: str, results: list[ToolResult], names: list[str]) -> list[str]:
    """Names mentioned in the sentence that are not in the returned rows (or resolved args).
    A few plain English hyphenated words are not treated as names."""
    blob = json.dumps([[r.rows, tools.public_args(r.args)] for r in results], default=str).lower()
    low = sentence.lower()
    mentioned = {n for n in names if re.search(rf"(?<![\w-]){re.escape(n.lower())}(?![\w-])", low)}
    mentioned |= {t for t in KEBAB.findall(sentence) if t not in PLAIN_HYPHENATED}
    return sorted(m for m in mentioned if m.lower() not in blob)


# ---------------------------------------------------------------- response assembly

def _source_details(ids: list[str]) -> list[dict[str, Any]]:
    if not ids:
        return []
    rows, _ = db.run_ro("sources_by_ids", ids=ids)
    by_id = {r["id"]: r for r in rows}
    return [by_id[i] for i in ids if i in by_id]


def _outcome(results: list[ToolResult]) -> tuple[str, str]:
    """(outcome, template sentence)."""
    blocked = next((r for r in results if r.status in ("unknown", "choices")), None)
    if blocked:
        return "unknown", blocked.sentence
    with_rows = [r for r in results if r.rows]
    if not with_rows:
        entity = next((r for r in results if r.needs_entity), None)
        if entity:
            return "no_connection", NO_CONNECTION.format(x=entity.subject)
        return "answered", " ".join(r.sentence for r in results)
    outcome = "stale_warning" if any(r.stale for r in results) else "answered"
    return outcome, " ".join(r.sentence for r in with_rows)


def finalize(question: str, results: list[ToolResult], llm_sentence: str | None,
             extra_trace: list[dict] | None = None, mode: str = "offline") -> dict[str, Any]:
    outcome, template = _outcome(results)
    answer, check = template, "passed"
    if outcome in ("answered", "stale_warning"):
        names = entity_names()
        if llm_sentence and llm_sentence.strip():
            missing = check_sentence(llm_sentence, results, names)
            if missing:
                check = "replaced: " + ", ".join(missing)
            else:
                answer = llm_sentence.strip()
        elif check_sentence(template, results, names):
            check = "template unchecked"
    elif outcome == "unknown" or outcome == "no_connection":
        check = "not needed"

    trace = [t for r in results for t in r.trace] + (extra_trace or [])
    source_ids = list(dict.fromkeys(s for r in results for s in r.sources))
    response = {
        "outcome": outcome,
        "answer": answer,
        "paths": [p for r in results for p in r.paths],
        "steps": [s for r in results for s in r.steps],
        "rows": [row for r in results for row in r.rows],
        "sources": _source_details(source_ids),
        "highlight": list(dict.fromkeys(h for r in results for h in r.highlight)),
        "trace": trace,
        "check": check,
        "choices": [c for r in results for c in r.choices],
        "tools": [{"tool": r.tool, "args": tools.public_args(r.args), "rows": len(r.rows)} for r in results],
        "mode": mode,
    }
    for t in trace:
        log.info("tool=%s args=%s rows=%s ms=%s outcome=%s", t["tool"], t.get("args"), t.get("rows"), t.get("ms"), outcome)
    return response


def _blocked(sentence: str, mode: str, extra_trace: list[dict] | None = None) -> dict[str, Any]:
    return finalize("", [ToolResult(tool="none", args={}, status="unknown", sentence=sentence)], None, extra_trace, mode)


# ---------------------------------------------------------------- offline

def answer_offline(question: str, extra_trace: list[dict] | None = None) -> dict[str, Any]:
    route = router_offline.route(question)
    if route.tool is None or route.problem:
        return _blocked(route.problem, "offline", extra_trace)
    result = tools.execute(route.tool, route.args, question)
    return finalize(question, [result], None, extra_trace, "offline")


# ---------------------------------------------------------------- online

def _compact(result: ToolResult) -> str:
    """What the LLM sees from a tool call: status, rows (truncated) and the template sentence."""
    payload = {"status": result.status, "args": tools.public_args(result.args),
               "rows": result.rows[:12], "summary": result.sentence}
    return json.dumps(payload, default=str)[:6000]


def _call_llm(messages: list[dict]) -> Any:
    return litellm.completion(model=llm_model(), messages=messages, tools=tools.llm_tools(),
                              tool_choice="auto", temperature=0, timeout=LLM_TIMEOUT_S)


def _system_prompt() -> str:
    """The fixed prompt plus the systems (and what each decided) that exist in the graph right now."""
    rows, _ = db.run_ro("entities")
    systems = sorted(r["name"] for r in rows if r["kind"] == "System")
    decided = {s: [r["summary"] for r in rows if r["kind"] == "Decision" and r["about"] == s] for s in systems}
    listing = "\n".join(f"- {s}: {'; '.join(decided[s]) or 'no decisions recorded'}" for s in systems)
    return f"{SYSTEM_PROMPT}\n\nSystems in the graph and their decisions:\n{listing}"


def answer_online(question: str) -> dict[str, Any]:
    messages: list[dict] = [{"role": "system", "content": _system_prompt()}, {"role": "user", "content": question}]
    results: list[ToolResult] = []
    sentence: str | None = None
    start = time.perf_counter()
    for _ in range(MAX_TOOL_CALLS + 1):
        if results and time.perf_counter() - start > QUESTION_BUDGET_S:
            log.warning("LLM over the %ss budget; using the template sentence", QUESTION_BUDGET_S)
            break
        msg = _call_llm(messages).choices[0].message
        calls = list(getattr(msg, "tool_calls", None) or [])
        if not calls or len(results) >= MAX_TOOL_CALLS:
            sentence = msg.content if not calls else None
            break
        messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [
            {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments or "{}"}}
            for c in calls]})
        for call in calls[: MAX_TOOL_CALLS - len(results)]:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = tools.execute(call.function.name, args, question)
            results.append(result)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": _compact(result)})
            if result.status in ("unknown", "choices"):
                return finalize(question, results, None, mode="online")
    if not results:
        return _blocked("I couldn't turn that into a graph question, so no query was run. Try asking why we use a "
                        "system, who knows it, or what breaks if a decision is reversed.", "online")
    return finalize(question, results, sentence, mode="online")


def answer(question: str) -> dict[str, Any]:
    """Entry point for /api/chat. Falls back to the offline router if the LLM fails."""
    question = question.strip()
    if not llm_online():
        return answer_offline(question)
    if llm_cooldown_s():
        note = {"tool": "llm", "query": None, "args": {"model": llm_model()}, "rows": 0, "ms": 0,
                "note": f"LLM rate-limited; paused for {llm_cooldown_s()} s more, answered with the offline router"}
        return answer_offline(question, extra_trace=[note])
    start = time.perf_counter()
    try:
        return answer_online(question)
    except (db.GraphUnavailable, db.GraphError):
        raise
    except Exception as exc:  # noqa: BLE001 - any LLM failure falls back to the offline router
        ms = round((time.perf_counter() - start) * 1000, 1)
        rate_limited = "RateLimit" in type(exc).__name__ or "RESOURCE_EXHAUSTED" in str(exc)
        if rate_limited:
            _start_cooldown(exc)
        log.warning("LLM failed (%s: %s); falling back to offline router", type(exc).__name__, str(exc).splitlines()[0][:160])
        reason = f"LLM rate-limited (paused {llm_cooldown_s()} s)" if rate_limited else f"LLM error ({type(exc).__name__})"
        note = {"tool": "llm", "query": None, "args": {"model": llm_model()}, "rows": 0, "ms": ms,
                "note": f"{reason}; answered with the offline router"}
        return answer_offline(question, extra_trace=[note])
