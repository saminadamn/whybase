"""Every catalogue query against the seeded Kettle Labs graph (fixture properties from spec §5)."""
from backend import db
from backend.seed import seed

pytestmark = __import__("pytest").mark.usefixtures("seeded")


def ro(name, /, **params):
    rows, ms = db.run_ro(name, **params)
    assert ms < 50, f"{name} took {ms} ms"
    return rows


def test_stats_counts():
    counts = {r["label"]: r["c"] for r in ro("stats")}
    assert counts == {"Person": 23, "Team": 6, "System": 13, "Project": 10, "Source": 47, "Decision": 21}


def test_indexes_exist():
    labels = {row[0] for row in db.graph().list_indices().result_set}
    assert labels == {"Person", "Team", "System", "Project", "Source", "Decision"}


def test_resolvers():
    assert ro("resolve_system", name="Event-Bus") == [{"name": "event-bus"}]
    assert ro("resolve_system", name="quantum-cache") == []
    assert ro("resolve_person", name="priya nair") == [{"name": "Priya Nair"}]
    assert ro("resolve_project", name="instant refunds") == [{"name": "Instant Refunds"}]
    assert [r["id"] for r in ro("resolve_decision", q="d-002")] == ["D-002"]
    assert {r["id"] for r in ro("resolve_decision", q="kafka")} >= {"D-002", "D-009"}


def test_why_event_bus_chain():
    rows = ro("why", system="event-bus")
    assert [(r["head"], r["step"], r["id"]) for r in rows] == [("D-002", 0, "D-002"), ("D-002", 1, "D-001")]
    assert [r["source_id"] for r in rows] == ["S-ADR-007", "S-ADR-001"]
    assert [r["by"] for r in rows] == ["Priya Nair", "Dev Malhotra"]


def test_stale_all_initial():
    rows = ro("stale_all")
    assert sorted(r["source_id"] for r in rows) == ["S-DOC-101", "S-DOC-102", "S-DOC-103"]
    by_id = {r["source_id"]: r for r in rows}
    assert by_id["S-DOC-101"]["old_id"] == "D-001" and by_id["S-DOC-101"]["now_id"] == "D-002"
    # Dev Malhotra left: the fix goes to two active Platform teammates, not to him.
    assert by_id["S-DOC-101"]["author_status"] == "left"
    assert len(by_id["S-DOC-101"]["fix_by"]) == 2 and "Dev Malhotra" not in by_id["S-DOC-101"]["fix_by"]
    assert by_id["S-DOC-102"]["fix_by"] == ["Neha Joshi"]


def test_who_knows_payments_ledger():
    rows = ro("who_knows", system="payments-ledger")
    assert rows[0]["person"] == "Arjun Mehta" and rows[0]["status"] == "left"
    active = [r["person"] for r in rows if r["status"] == "active"]
    assert active == ["Rohan Das"]


def test_knowledge_risk():
    rows = ro("knowledge_risk")
    assert [(r["system"], r["active"], r["gone"]) for r in rows] == [
        ("payments-ledger", ["Rohan Das"], ["Arjun Mehta"]),
        ("data-warehouse", ["Neha Joshi"], []),
        ("notification-service", ["Kabir Sethi"], []),
    ]


def test_reversal_impact_d002():
    rows = ro("reversal_impact", id="D-002")
    got = {(r["affected"], r["hops"]) for r in rows}
    assert got == {("D-004", 1), ("D-009", 1), ("D-012", 1), ("D-005", 2),
                   ("Smart Notifications", 2), ("Growth Experiments", 2), ("Instant Refunds", 3)}
    refunds = next(r for r in rows if r["affected"] == "Instant Refunds")
    assert refunds["via"] == ["Instant Refunds", "D-005", "D-004", "D-002"]


def test_load_bearing_ranks_d002_first():
    rows = ro("load_bearing", limit=5)
    assert rows[0]["id"] == "D-002" and len(rows) == 5


def test_as_of_event_bus():
    assert [r["id"] for r in ro("as_of", system="event-bus", date="2025-01-01")] == ["D-001"]
    assert [r["id"] for r in ro("as_of", system="event-bus", date="2025-06-01")] == ["D-002"]
    assert ro("as_of", system="event-bus", date="2023-01-01") == []


def test_candidates_and_next_ids():
    assert [r["id"] for r in ro("candidates_for_system", system="event-bus")] == ["D-002"]
    ids = ro("next_ids")[0]
    assert ids == {"max_decision": "D-021", "max_chat": "S-CHAT-205"}


def test_current_head():
    assert ro("current_head", id="D-001")[0]["id"] == "D-002"
    assert ro("current_head", id="D-002") == []


def test_subgraph_and_full_graph():
    rows = ro("subgraph", names=["event-bus", "D-002"])
    assert rows and all(r["n"]["_labels"] for r in rows)
    assert len(db.run_ro("full_graph")[0]) >= 120


def test_entities_and_sources_by_ids():
    kinds = {r["kind"] for r in ro("entities")}
    assert kinds == {"System", "Person", "Project", "Decision"}
    src = ro("sources_by_ids", ids=["S-ADR-007"])[0]
    assert src["author"] == "Priya Nair" and src["kind"] == "adr"


def test_writes_ingest_stale_and_review():
    """ingest_decision + stale_for_decision + mark_reviewed, then restore the shared seed."""
    try:
        db.run_rw("ingest_decision", system="event-bus", old="D-002", author="Priya Nair", sid="S-CHAT-206",
                  title="t", text="x", at="2026-10-18", did="D-022", summary="Move event-bus from Kafka to Redpanda")
        new_stale = ro("stale_for_decision", did="D-022")
        assert sorted(r["source_id"] for r in new_stale) == ["S-DOC-104", "S-DOC-105", "S-DOC-106"]
        ledger = next(r for r in new_stale if r["source_id"] == "S-DOC-105")
        assert ledger["fix_by"] == ["Rohan Das", "Ishaan Kapoor"]
        assert len(ro("stale_all")) == 6

        rows, _ = db.run_rw("mark_reviewed", sid="S-DOC-104", old_id="D-002", now="2026-10-18", by="Kavya Rao")
        assert rows == [{"source_id": "S-DOC-104", "now_assumes": "D-022"}]
        assert "S-DOC-104" not in {r["source_id"] for r in ro("stale_all")}
    finally:
        seed()
