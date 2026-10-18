"""WhyBase FastAPI app: JSON API under /api and the static frontend at /.

No CORS middleware is installed, so browsers only allow same-origin calls.
"""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from backend import agent, db, ingest, seed
from backend.models import ChatRequest, ChatResponse, ConfirmRequest, GraphRequest, ProposeRequest, ReviewRequest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("whybase")
FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
EXAMPLES = Path(__file__).resolve().parent.parent / "data" / "examples.json"
LABEL_PLURALS = {"Person": "people", "System": "systems", "Source": "sources", "Decision": "decisions",
                 "Team": "teams", "Project": "projects"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        if seed.ensure_seeded():
            log.info("Graph '%s' was empty; loaded Kettle Labs seed.", db.graph_name())
    except db.GraphUnavailable:
        log.warning(db.UNREACHABLE)
    yield


app = FastAPI(title="WhyBase", lifespan=lifespan)


# ---------------------------------------------------------------- errors

def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


@app.exception_handler(db.GraphUnavailable)
async def _graph_down(_: Request, exc: db.GraphUnavailable) -> JSONResponse:
    return _error(503, "graph_unavailable", str(exc))


@app.exception_handler(db.GraphError)
async def _graph_error(_: Request, exc: db.GraphError) -> JSONResponse:
    log.error("%s", exc)
    return _error(500, "graph_error", "The graph query failed. Try again.")


@app.exception_handler(ingest.IngestError)
async def _ingest_error(_: Request, exc: ingest.IngestError) -> JSONResponse:
    return _error(exc.status, "conflict" if exc.status == 409 else "bad_request", str(exc))


@app.exception_handler(HTTPException)
async def _http_error(_: Request, exc: HTTPException) -> JSONResponse:
    code = {400: "bad_request", 404: "not_found", 409: "conflict"}.get(exc.status_code, "error")
    return _error(exc.status_code, code, str(exc.detail))


@app.exception_handler(RequestValidationError)
async def _invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    where = ".".join(str(p) for p in first.get("loc", []) if p != "body")
    return _error(422, "invalid_request", f"{where}: {first.get('msg', 'invalid input')}".strip(": "))


# ---------------------------------------------------------------- read endpoints

@app.get("/api/health")
def health() -> dict[str, Any]:
    online = agent.llm_online()
    llm = ("rate_limited" if agent.llm_cooldown_s() else "online") if online else "offline"
    return {"falkordb": "ok" if db.ping() else "err", "llm": llm, "model": agent.llm_model() if online else "",
            "llm_retry_in": agent.llm_cooldown_s(), "graph": db.graph_name()}


@app.get("/api/stats")
def stats() -> dict[str, int]:
    rows, _ = db.run_ro("stats")
    counts = {LABEL_PLURALS.get(r["label"], r["label"]): r["c"] for r in rows}
    return {k: counts.get(k, 0) for k in LABEL_PLURALS.values()}


@app.get("/api/entities")
def entities() -> dict[str, list]:
    rows, _ = db.run_ro("entities")
    out: dict[str, list] = {"systems": [], "people": [], "projects": [], "decisions": []}
    for r in rows:
        if r["kind"] == "Decision":
            out["decisions"].append({"id": r["name"], "summary": r["summary"], "status": r["status"], "about": r["about"]})
        else:
            key = {"System": "systems", "Person": "people", "Project": "projects"}[r["kind"]]
            out[key].append({"name": r["name"], "status": r["status"]})
    return out


@app.get("/api/examples")
def examples() -> dict[str, Any]:
    """Sample questions and changes (with expected outcomes) for anyone testing the app."""
    return json.loads(EXAMPLES.read_text(encoding="utf-8"))


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> dict[str, Any]:
    return agent.answer(req.question)


@app.get("/api/stale")
def stale() -> list[dict[str, Any]]:
    return db.run_ro("stale_all")[0]


@app.post("/api/stale/{source_id}/review")
def review(source_id: str, req: ReviewRequest) -> dict[str, Any]:
    if not db.run_ro("resolve_person", name=req.by)[0]:
        raise HTTPException(400, f"{req.by} isn't a person in the graph.")
    rows, _ = db.run_rw("mark_reviewed", sid=source_id, old_id=req.old_id, now=date.today().isoformat(), by=req.by)
    if not rows:
        raise HTTPException(404, f"{source_id} doesn't assume {req.old_id}, or it has no current replacement.")
    return {"source_id": source_id, "now_assumes": [r["now_assumes"] for r in rows], "reviewed_by": req.by}


@app.get("/api/risk")
def risk() -> list[dict[str, Any]]:
    return db.run_ro("knowledge_risk")[0]


@app.get("/api/load-bearing")
def load_bearing(limit: int = Query(5, ge=1, le=10)) -> list[dict[str, Any]]:
    rows, _ = db.run_ro("load_bearing", limit=limit)
    return [{**r, "score": round(float(r["score"]), 4)} for r in rows]


@app.get("/api/as-of")
def as_of(system: str = Query(..., max_length=80), on: str = Query(..., alias="date")) -> dict[str, Any]:
    resolved = db.run_ro("resolve_system", name=system)[0]
    if not resolved:
        raise HTTPException(404, f"{system} isn't in the graph.")
    try:
        when = date.fromisoformat(on).isoformat()
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")
    name = resolved[0]["name"]
    return {"system": name, "date": when, "rows": db.run_ro("as_of", system=name, date=when)[0]}


@app.post("/api/ingest/propose")
def ingest_propose(req: ProposeRequest) -> dict[str, Any]:
    return ingest.propose(req.text, req.author)


@app.post("/api/ingest/confirm")
def ingest_confirm(req: ConfirmRequest) -> dict[str, Any]:
    return ingest.confirm(req.text, req.system, req.summary, req.old, req.author)


def _node_key(node: dict[str, Any]) -> str:
    return node.get("name") or node.get("id") or str(node["_id"])


def _to_cytoscape(rows: list[dict[str, Any]]) -> dict[str, list]:
    """Convert (n, r, m) rows into {nodes, edges} keyed by each node's name or id."""
    nodes: dict[int, dict] = {}
    for row in rows:
        for key in ("n", "m"):
            node = row.get(key)
            if node and node["_id"] not in nodes:
                props = {k: v for k, v in node.items() if not k.startswith("_")}
                nodes[node["_id"]] = {"id": _node_key(node), "label": _node_key(node),
                                      "kind": node["_labels"][0], "status": node.get("status"), "props": props}
    edges: dict[tuple, dict] = {}
    for row in rows:
        rel = row.get("r")
        if rel and rel["_src"] in nodes and rel["_dst"] in nodes:
            src, dst = nodes[rel["_src"]]["id"], nodes[rel["_dst"]]["id"]
            edges[(src, dst, rel["_type"])] = {"source": src, "target": dst, "type": rel["_type"]}
    return {"nodes": list(nodes.values()), "edges": list(edges.values())}


@app.post("/api/graph")
def subgraph(req: GraphRequest) -> dict[str, list]:
    rows, _ = db.run_ro("subgraph", names=[n[:120] for n in req.names])
    return _to_cytoscape(rows)


@app.get("/api/graph/all")
def full_graph() -> dict[str, list]:
    return _to_cytoscape(db.run_ro("full_graph")[0])


@app.get("/api/queries/{name}", response_class=PlainTextResponse)
def query_text(name: str) -> str:
    """Read-only: the Cypher text of a catalogue query (for the Trace tab's Copy Cypher)."""
    if name not in db.QUERIES:
        raise HTTPException(404, f"No query named {name}.")
    return db.QUERIES[name]


@app.post("/api/reset")
def reset() -> dict[str, Any]:
    return {"reset": True, "counts": seed.seed()}


app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
