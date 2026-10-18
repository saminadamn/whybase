"""Load data/seed.json (Kettle Labs) into FalkorDB. Idempotent: wipes the graph first.

Run with:  python -m backend.seed
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend import db

SEED_FILE = Path(__file__).resolve().parent.parent / "data" / "seed.json"

# (label, property) pairs to index. Fixed in code, never from input.
INDEXES: list[tuple[str, str]] = [
    ("Person", "name"), ("Team", "name"), ("System", "name"),
    ("Project", "name"), ("Source", "id"), ("Decision", "id"),
]


def load_seed() -> dict[str, Any]:
    return json.loads(SEED_FILE.read_text(encoding="utf-8"))


def _pairs(items: list[dict], key: str, field: str) -> list[list[str]]:
    return [[item[key], target] for item in items for target in item[field]]


def seed() -> dict[str, int]:
    """Wipe the graph, recreate indexes and load every fixture. Returns node counts."""
    data = load_seed()
    db.drop_graph()
    g = db.graph()
    for label, prop in INDEXES:
        g.create_node_range_index(label, prop)

    systems = [{**s, "team": t["name"]} for t in data["teams"] for s in data["systems"] if s["name"] in t["owns"]]

    db.run_rw("seed_teams", teams=data["teams"])
    db.run_rw("seed_systems", systems=systems)
    db.run_rw("seed_people", people=data["people"])
    db.run_rw("seed_projects", projects=data["projects"])
    db.run_rw("seed_sources", sources=data["sources"])
    db.run_rw("seed_decisions", decisions=data["decisions"])
    db.run_rw("seed_supersedes", pairs=_pairs(data["decisions"], "id", "supersedes"))
    db.run_rw("seed_decision_relies", pairs=_pairs(data["decisions"], "id", "relies_on"))
    db.run_rw("seed_project_relies", pairs=_pairs(data["projects"], "name", "relies_on"))
    db.run_rw("seed_assumes", pairs=_pairs(data["sources"], "id", "assumes"))

    rows, _ = db.run_ro("stats")
    return {r["label"]: r["c"] for r in rows}


def ensure_seeded() -> bool:
    """Seed only if the graph is empty. Returns True if it seeded."""
    rows, _ = db.run_ro("count_nodes")
    if rows and rows[0]["c"] > 0:
        return False
    seed()
    return True


if __name__ == "__main__":
    counts = seed()
    print(f"Seeded graph '{db.graph_name()}':", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
