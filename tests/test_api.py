"""Endpoints: happy paths, the live-change demo (FR-8..FR-10, FR-15) and error paths."""
import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError

from backend import db
from backend.main import app

REDPANDA = ("Team call today: we're moving event-bus from Kafka to Redpanda — Kafka ops cost is too high "
            "and Redpanda speaks the Kafka API. — Priya Nair")


@pytest.fixture()
def client(fresh):
    with TestClient(app) as c:
        yield c


def test_health_stats_entities(client):
    assert client.get("/api/health").json()["falkordb"] == "ok"
    assert client.get("/api/stats").json() == {"people": 23, "systems": 13, "sources": 47, "decisions": 21,
                                                "teams": 6, "projects": 10}
    ents = client.get("/api/entities").json()
    assert len(ents["systems"]) == 13 and len(ents["decisions"]) == 21


def test_index_page_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "WhyBase" in r.text


def test_chat_shape(client):
    r = client.post("/api/chat", json={"question": "Why do we use Kafka for the event bus?"}).json()
    for key in ("outcome", "answer", "paths", "rows", "sources", "highlight", "trace", "check", "choices"):
        assert key in r
    assert r["outcome"] == "answered"


def test_desk_endpoints(client):
    assert len(client.get("/api/stale").json()) == 3
    assert [r["system"] for r in client.get("/api/risk").json()][:2] == ["payments-ledger", "data-warehouse"]
    assert client.get("/api/load-bearing?limit=5").json()[0]["id"] == "D-002"  # FR-6
    early = client.get("/api/as-of", params={"system": "event-bus", "date": "2025-01-01"}).json()
    later = client.get("/api/as-of", params={"system": "event-bus", "date": "2025-06-01"}).json()
    assert early["rows"][0]["id"] == "D-001" and later["rows"][0]["id"] == "D-002"  # FR-7


def test_live_change_flow(client):  # FR-8, FR-9, FR-10, FR-15
    prop = client.post("/api/ingest/propose", json={"text": REDPANDA}).json()
    p = prop["proposal"]
    assert (p["system"], p["old"], p["author"]) == ("event-bus", "D-002", "Priya Nair")
    assert p["summary"] == "Move event-bus from Kafka to Redpanda" and prop["written"] is False
    assert client.get("/api/stats").json()["decisions"] == 21  # nothing written yet

    done = client.post("/api/ingest/confirm", json={k: p[k] for k in ("text", "system", "summary", "old", "author")}).json()
    assert done["decision"]["id"] == "D-022"
    assert sorted(r["source_id"] for r in done["stale"]) == ["S-DOC-104", "S-DOC-105", "S-DOC-106"]
    assert done["stale_total"] == 6
    d002 = db.run_ro("resolve_decision", q="D-002")[0][0]
    assert d002["status"] == "superseded"

    why = client.post("/api/chat", json={"question": "Why do we use Kafka for the event bus?"}).json()
    assert why["outcome"] == "stale_warning" and "D-022" in why["answer"]

    rev = client.post("/api/stale/S-DOC-104/review", json={"old_id": "D-002", "by": "Kavya Rao"}).json()
    assert rev["now_assumes"] == ["D-022"]
    assert "S-DOC-104" not in {r["source_id"] for r in client.get("/api/stale").json()}

    client.post("/api/reset")
    assert len(client.get("/api/stale").json()) == 3
    assert client.get("/api/stats").json()["decisions"] == 21


def test_propose_without_system_reports_problem(client):
    prop = client.post("/api/ingest/propose", json={"text": "We should all drink more water. — Priya"}).json()
    assert prop["proposal"]["system"] is None and "system" in prop["problems"]
    assert prop["proposal"]["author"] == "Priya Nair"


def test_confirm_rejects_bad_input(client):
    base = {"text": "x", "system": "event-bus", "summary": "Move to Redpanda", "old": "D-002", "author": "Priya Nair"}
    assert client.post("/api/ingest/confirm", json={**base, "old": "D-003"}).status_code == 409
    assert client.post("/api/ingest/confirm", json={**base, "system": "quantum-cache"}).status_code == 400
    assert client.post("/api/ingest/confirm", json={**base, "author": "Nobody"}).status_code == 400


def test_validation_and_not_found_errors(client):
    r = client.post("/api/chat", json={"question": "x" * 501})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"
    assert client.post("/api/ingest/propose", json={"text": "x" * 2001}).status_code == 422
    assert client.post("/api/stale/S-DOC-999/review", json={"old_id": "D-001", "by": "Kavya Rao"}).status_code == 404
    assert client.get("/api/as-of", params={"system": "event-bus", "date": "soon"}).status_code == 400
    assert client.get("/api/queries/why").text.startswith("MATCH")
    assert client.get("/api/queries/nope").status_code == 404


def test_graph_endpoints(client):
    g = client.post("/api/graph", json={"names": ["event-bus"]}).json()
    ids = {n["id"] for n in g["nodes"]}
    assert "event-bus" in ids and "D-002" in ids and g["edges"]
    assert len(client.get("/api/graph/all").json()["nodes"]) == 120


def test_graph_down_returns_503(client, monkeypatch):
    class Down:
        def ro_query(self, *a, **k):
            raise RedisConnectionError("refused")
        query = ro_query
    monkeypatch.setattr(db, "graph", lambda: Down())
    r = client.get("/api/stale")
    assert r.status_code == 503
    assert r.json()["error"]["message"] == "Graph database is not reachable. Run `make up`."


def test_graph_query_error_is_json(client, monkeypatch):
    from redis.exceptions import ResponseError

    class Broken:
        def ro_query(self, *a, **k):
            raise ResponseError("Query timed out")
        query = ro_query
    monkeypatch.setattr(db, "graph", lambda: Broken())
    r = client.get("/api/stale")
    assert r.status_code == 500 and r.json()["error"]["code"] == "graph_error"


def test_startup_seeds_a_missing_graph(monkeypatch):
    """A brand-new FalkorDB has no graph at all; startup must seed it rather than crash."""
    monkeypatch.setenv("GRAPH_NAME", "whybase_test_fresh")
    db.drop_graph()
    try:
        with TestClient(app) as c:
            assert c.get("/api/stats").json()["decisions"] == 21
    finally:
        db.drop_graph()
