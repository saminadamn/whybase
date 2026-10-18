"""Turn a pasted message into a proposed decision, and record it only after confirmation.

propose(): extract system, summary and author (LLM or regex), then let the LLM pick which
           existing active decision it replaces *from the graph's candidate list only*.
           Nothing is written.
confirm(): validate everything against the graph again, run ingest_decision, then
           stale_for_decision to report which sources just went out of date.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any

import litellm

from backend import agent, db, router_offline

log = logging.getLogger("whybase.ingest")
SIGNATURE = re.compile(r"[—–-]+\s*([A-Z][\w'-]+(?:\s+[A-Z][\w'-]+)?)\s*\.?\s*$")
MOVE_FROM_TO = re.compile(r"\b(mov(?:e|ing)|switch(?:ing)?|migrat(?:e|ing)|replac(?:e|ing))\s+(?:the\s+)?"
                          r"([\w-]+(?:\s[\w-]+)?)\s+from\s+([\w.-]+)\s+to\s+([\w.-]+)", re.I)
MOVE_TO = re.compile(r"\b(mov(?:e|ing)|switch(?:ing)?|migrat(?:e|ing))\s+(?:the\s+)?([\w-]+(?:\s[\w-]+)?)\s+(?:over\s+)?to\s+([\w.-]+)", re.I)
VERBS = (("mov", "Move"), ("switch", "Switch"), ("migrat", "Migrate"), ("replac", "Replace"))


class IngestError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------- extraction

def _people(entities: list[dict]) -> list[str]:
    return [e["name"] for e in entities if e["kind"] == "Person" and e["status"] == "active"]


def find_author(text: str, entities: list[dict]) -> str | None:
    """From a trailing signature like '— Priya Nair' or '— Priya'."""
    m = SIGNATURE.search(text.strip())
    if not m:
        return None
    sig = m[1].strip().lower()
    people = _people(entities)
    exact = [p for p in people if p.lower() == sig]
    firsts = [p for p in people if p.split()[0].lower() == sig.split()[0]]
    return exact[0] if exact else (firsts[0] if len(firsts) == 1 else None)


def _verb(word: str) -> str:
    """'moving' -> 'Move', 'switching' -> 'Switch', 'migrating' -> 'Migrate', 'replacing' -> 'Replace'."""
    return next(v for k, v in VERBS if word.lower().startswith(k))


def summarise(text: str, system: str | None) -> str:
    """A ≤12-word decision summary without an LLM."""
    if m := MOVE_FROM_TO.search(text):
        summary = f"{_verb(m[1])} {system or m[2]} from {m[3]} to {m[4]}"
    elif m := MOVE_TO.search(text):
        summary = f"{_verb(m[1])} {system or m[2]} to {m[3]}"
    else:
        body = SIGNATURE.sub("", text).strip()
        body = re.sub(r"^[^:]{1,30}:\s*", "", body)          # drop "Team call today:"
        summary = re.split(r"(?<=[.!?;—])\s", body)[0].rstrip(".;—- ")
        summary = summary[:1].upper() + summary[1:]
    return " ".join(summary.rstrip(".,;").split()[:12])


def _extract_offline(text: str, entities: list[dict]) -> dict[str, str | None]:
    system = router_offline.find_system(text, entities) or router_offline.system_from_topic(text, entities)
    return {"system": system, "summary": summarise(text, system), "author": find_author(text, entities)}


def _forced_call(prompt: str, name: str, properties: dict[str, Any]) -> dict[str, Any]:
    tool = {"type": "function", "function": {"name": name, "description": "Record the extracted fields.",
                                             "parameters": {"type": "object", "properties": properties,
                                                            "required": list(properties)}}}
    resp = litellm.completion(model=agent.llm_model(), temperature=0, timeout=agent.LLM_TIMEOUT_S,
                              messages=[{"role": "user", "content": prompt}], tools=[tool],
                              tool_choice={"type": "function", "function": {"name": name}})
    return json.loads(resp.choices[0].message.tool_calls[0].function.arguments or "{}")


def _extract_llm(text: str, entities: list[dict]) -> dict[str, str | None]:
    systems = [e["name"] for e in entities if e["kind"] == "System"]
    out = _forced_call(
        "A Kettle Labs teammate posted this message. Extract the decision it announces.\n"
        f"Message:\n{text}\n\nsummary: at most 12 words, imperative, e.g. 'Move event-bus from Kafka to Redpanda'.",
        "record_change", {
            "system": {"type": "string", "enum": systems + ["none"]},
            "summary": {"type": "string"},
            "author": {"type": "string", "enum": _people(entities) + ["unknown"]},
        })
    return {"system": out.get("system") if out.get("system") in systems else None,
            "summary": " ".join(str(out.get("summary", "")).split()[:12]).rstrip(".;,") or None,
            "author": out.get("author") if out.get("author") in _people(entities) else None}


def _pick_replaced_llm(text: str, candidates: list[dict]) -> str | None:
    ids = [c["id"] for c in candidates]
    listing = "\n".join(f"{c['id']}: {c['summary']} ({c['at']})" for c in candidates)
    out = _forced_call(f"Message:\n{text}\n\nWhich one of these current decisions does the message replace?\n{listing}",
                       "pick_replaced", {"decision": {"type": "string", "enum": ids}})
    return out.get("decision") if out.get("decision") in ids else None


# ---------------------------------------------------------------- propose / confirm

def candidates_for(system: str | None) -> list[dict[str, Any]]:
    return db.run_ro("candidates_for_system", system=system)[0] if system else []


def propose(text: str, author: str | None = None) -> dict[str, Any]:
    """Build a proposal. Writes nothing."""
    entities = router_offline.load_entities()
    mode = "offline"
    fields = _extract_offline(text, entities)
    if agent.llm_online():
        try:
            llm_fields = _extract_llm(text, entities)
            fields = {k: llm_fields.get(k) or fields.get(k) for k in fields}
            mode = "online"
        except Exception as exc:  # noqa: BLE001 - fall back to the regex extraction
            log.warning("LLM extraction failed (%s); using offline extraction", type(exc).__name__)
    if author:
        picked = db.run_ro("resolve_person", name=author)[0]
        fields["author"] = picked[0]["name"] if picked else fields["author"]

    candidates = candidates_for(fields["system"])
    old = candidates[0]["id"] if candidates else None
    if mode == "online" and len(candidates) > 1:
        try:
            old = _pick_replaced_llm(text, candidates) or old
        except Exception as exc:  # noqa: BLE001
            log.warning("LLM candidate pick failed (%s); using most recent", type(exc).__name__)

    problems = {}
    if not fields["system"]:
        problems["system"] = "I couldn't match a system. Pick one:"
    elif not candidates:
        problems["old"] = "There is no active decision about this system to replace."
    if not fields["author"]:
        problems["author"] = "Pick who decided this."
    return {"proposal": {**fields, "old": old, "text": text}, "candidates": candidates,
            "systems": [e["name"] for e in entities if e["kind"] == "System"],
            "people": _people(entities), "problems": problems, "mode": mode, "written": False}


def _next_ids() -> tuple[str, str]:
    row = db.run_ro("next_ids")[0][0]
    d = int((row["max_decision"] or "D-000").split("-")[1]) + 1
    s = int((row["max_chat"] or "S-CHAT-200").split("-")[2]) + 1
    return f"D-{d:03d}", f"S-CHAT-{s}"


def confirm(text: str, system: str, summary: str, old: str, author: str) -> dict[str, Any]:
    """Re-validate against the graph, then write the new decision and report newly stale sources."""
    sys_rows = db.run_ro("resolve_system", name=system)[0]
    person_rows = db.run_ro("resolve_person", name=author)[0]
    if not sys_rows:
        raise IngestError(400, f"{system} isn't a system in the graph.")
    if not person_rows:
        raise IngestError(400, f"{author} isn't a person in the graph.")
    system, author = sys_rows[0]["name"], person_rows[0]["name"]
    if old not in {c["id"] for c in candidates_for(system)}:
        raise IngestError(409, f"{old} isn't a current decision about {system}.")

    did, sid = _next_ids()
    at = date.today().isoformat()
    summary = " ".join(summary.split()[:12])
    db.run_rw("ingest_decision", system=system, old=old, author=author, sid=sid,
              title=f"Note from {author}: {summary}"[:120], text=text, at=at, did=did, summary=summary)
    stale_rows, _ = db.run_ro("stale_for_decision", did=did)
    total = len(db.run_ro("stale_all")[0])
    return {
        "decision": {"id": did, "summary": summary, "system": system, "replaces": old, "author": author,
                     "at": at, "source_id": sid},
        "stale": stale_rows, "stale_total": total,
        "highlight": [did, old, system, sid] + [r["source_id"] for r in stale_rows],
    }
