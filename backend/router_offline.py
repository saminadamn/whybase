"""Keyword router used when no LLM is configured (or the LLM fails).

It maps a question to one catalogue tool and pulls entity names out of the text by
matching against names that are actually in the graph. It never touches Cypher.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from backend import db
from backend.tools import tokens

KEBAB = re.compile(r"\b[a-z][a-z0-9]*(?:-[a-z0-9]+)+\b")
# Ordinary hyphenated English, never treated as a system name.
PLAIN_HYPHENATED = {"load-bearing", "out-of-date", "up-to-date", "point-in-time", "double-entry", "in-house"}
DECISION_ID = re.compile(r"\bD-?(\d{1,3})\b", re.I)
MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), start=1)}

ROUTES: list[tuple[str, re.Pattern[str]]] = [
    ("reversal_impact", re.compile(r"\b(revers\w*|revert\w*|undo|roll ?back|break|breaks|impact|relies on|depends? on)\b", re.I)),
    ("stale_docs", re.compile(r"out of date|outdated|\bstale\b|\bwrong\b|obsolete|no longer (true|accurate|valid)", re.I)),
    ("load_bearing", re.compile(r"load[- ]?bearing|\bimportant\b|critical decision|pagerank", re.I)),
    ("knowledge_risk", re.compile(r"\brisk|bus factor|single point|only one person", re.I)),
    ("as_of", re.compile(r"\bas of\b|\bback in\b", re.I)),
    ("who_knows", re.compile(r"who knows|who understands|who wrote|\bexperts?\b|who (can|should) i ask", re.I)),
    ("why", re.compile(r"\bwhy\b|\breason|rationale|how come", re.I)),
]


@dataclass
class Route:
    tool: str | None
    args: dict[str, Any]
    problem: str = ""       # set when we know the tool but cannot even find an argument


def load_entities() -> list[dict[str, Any]]:
    rows, _ = db.run_ro("entities")
    return rows


def find_date(text: str) -> str | None:
    """ISO dates, '1 Jan 2026', 'Jan 1, 2026'."""
    if m := re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
        parts = int(m[1]), int(m[2]), int(m[3])
    elif m := re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3})[a-z]*\.?,?\s+(\d{4})\b", text, re.I):
        parts = int(m[3]), MONTHS.get(m[2].lower(), 0), int(m[1])
    elif m := re.search(r"\b([a-z]{3})[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", text, re.I):
        parts = int(m[3]), MONTHS.get(m[1].lower(), 0), int(m[2])
    else:
        return None
    try:
        return date(*parts).isoformat()
    except ValueError:
        return None


def _word_in(phrase: str, text: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(phrase)}(?![\w-])", text) is not None


def find_system(text: str, entities: list[dict]) -> str | None:
    """Full name ('event-bus'), spaced name ('event bus'), or a unique first word ('search')."""
    low = text.lower()
    systems = sorted((e["name"] for e in entities if e["kind"] == "System"), key=len, reverse=True)
    for name in systems:
        if _word_in(name, low) or _word_in(name.replace("-", " "), low):
            return name
    firsts = [n.split("-")[0] for n in systems]
    for name, first in zip(systems, firsts):
        if len(first) >= 4 and firsts.count(first) == 1 and _word_in(first, low):
            return name
    return None


def system_from_topic(text: str, entities: list[dict]) -> str | None:
    """'Why do we use Redis?' -> the one system whose decisions mention Redis."""
    words = tokens(text)
    hits = {e["about"] for e in entities if e["kind"] == "Decision" and e["about"] and words & tokens(e["summary"] or "")}
    return hits.pop() if len(hits) == 1 else None


def raw_system_guess(text: str) -> str | None:
    """Something that looks like a system name even if the graph doesn't know it."""
    if m := KEBAB.search(text):
        return m[0]
    if m := re.search(r"(?:who knows|who understands|experts? (?:on|in|for)|why (?:do|did|does) we use)\s+(?:about\s+)?(?:the\s+)?([\w .-]{2,40}?)\s*\??$", text, re.I):
        return m[1].strip()
    return None


def find_decision(text: str) -> str | None:
    if m := DECISION_ID.search(text):
        return f"D-{int(m[1]):03d}"
    if m := re.search(r"(?:revers\w*|revert\w*|undo|roll ?back)\s+(?:the\s+)?(?:decision\s+)?(?:to\s+|about\s+)?(.{3,60}?)\s*\??$", text, re.I):
        return m[1].strip()
    return None


def pick_tool(text: str) -> str | None:
    if find_date(text):
        return "as_of"
    return next((tool for tool, pattern in ROUTES if pattern.search(text)), None)


def route(question: str, entities: list[dict] | None = None) -> Route:
    """Choose one tool and its raw arguments. Arguments are resolved later by tools.execute."""
    tool = pick_tool(question)
    if tool is None:
        return Route(None, {}, "I couldn't turn that into a graph question. Try asking why we use a system, "
                               "who knows it, which docs are out of date, or what breaks if a decision is reversed.")
    entities = entities if entities is not None else load_entities()
    if tool in ("stale_docs", "knowledge_risk"):
        return Route(tool, {})
    if tool == "load_bearing":
        n = re.search(r"\btop\s+(\d+)\b", question, re.I)
        return Route(tool, {"limit": int(n[1]) if n else 5})
    if tool == "reversal_impact":
        ref = find_decision(question)
        return Route(tool, {"decision": ref}) if ref else Route(tool, {}, "I couldn't tell which decision you mean.")
    # An explicit kebab-case name the graph doesn't know ("blockchain-ledger") wins over a topic guess,
    # so it is reported as unknown instead of being swapped for a lookalike system.
    named = next((k for k in KEBAB.findall(question) if k not in PLAIN_HYPHENATED), None)
    system = (find_system(question, entities)
              or named
              or (system_from_topic(question, entities) if tool in ("why", "as_of") else None)
              or raw_system_guess(question))
    if not system:
        return Route(tool, {}, "I couldn't find a system name in that question, so no query was run.")
    args: dict[str, Any] = {"system": system}
    if tool == "as_of":
        args["date"] = find_date(question) or date.today().isoformat()
    return Route(tool, args)
