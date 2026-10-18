"""FalkorDB connection and the only two ways the app touches the graph: run_ro and run_rw.

Every query is loaded by name from backend/queries/*.cypher. Values are always passed
as parameters; nothing is ever concatenated into a Cypher string.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from falkordb import FalkorDB, Node, Edge
from redis.exceptions import ConnectionError as RedisConnectionError, ResponseError, TimeoutError as RedisTimeoutError

load_dotenv()
log = logging.getLogger("whybase.db")

QUERY_DIR = Path(__file__).parent / "queries"
UNREACHABLE = "Graph database is not reachable. Run `make up`."


class GraphUnavailable(Exception):
    """Raised when FalkorDB cannot be reached."""


class GraphError(Exception):
    """Raised when FalkorDB rejects or fails a query."""


def load_queries() -> dict[str, str]:
    """Read every .cypher file into {name: text}."""
    return {p.stem: p.read_text(encoding="utf-8").strip() for p in sorted(QUERY_DIR.glob("*.cypher"))}


QUERIES: dict[str, str] = load_queries()
_client: FalkorDB | None = None


def graph_name() -> str:
    return os.getenv("GRAPH_NAME", "whybase")


def _db() -> FalkorDB:
    global _client
    if _client is None:
        _client = FalkorDB(
            host=os.getenv("FALKOR_HOST", "localhost"),
            port=int(os.getenv("FALKOR_PORT", "6379")),
            username=os.getenv("FALKOR_USERNAME") or None,
            password=os.getenv("FALKOR_PASSWORD") or None,
            ssl=os.getenv("FALKOR_SSL", "").lower() in ("1", "true", "yes"),   # hosted FalkorDB may need TLS
            socket_timeout=5,
            socket_connect_timeout=3,
        )
    return _client


def graph():
    return _db().select_graph(graph_name())


def ping() -> bool:
    try:
        return bool(_db().connection.ping())
    except Exception:  # noqa: BLE001 - any failure means "not reachable"
        return False


def _convert(value: Any) -> Any:
    """Turn FalkorDB Node/Edge objects into plain dicts so results are JSON-safe."""
    if isinstance(value, Node):
        return {"_id": value.id, "_labels": list(value.labels or []), **(value.properties or {})}
    if isinstance(value, Edge):
        return {"_type": value.relation, "_src": value.src_node, "_dst": value.dest_node, **(value.properties or {})}
    if isinstance(value, list):
        return [_convert(v) for v in value]
    return value


def _execute(name: str, params: dict[str, Any], read_only: bool) -> tuple[list[dict[str, Any]], float]:
    cypher = QUERIES[name]
    g = graph()
    start = time.perf_counter()
    attempts = 2 if read_only else 1   # a read that hits FalkorDB's query timeout is retried once
    for attempt in range(attempts):
        try:
            result = g.ro_query(cypher, params) if read_only else g.query(cypher, params)
            break
        except (RedisConnectionError, RedisTimeoutError, ConnectionRefusedError, OSError) as exc:
            raise GraphUnavailable(UNREACHABLE) from exc
        except ResponseError as exc:
            if read_only and "empty key" in str(exc).lower():   # the graph doesn't exist yet: no rows
                return [], round((time.perf_counter() - start) * 1000, 2)
            if "timed out" in str(exc).lower() and attempt + 1 < attempts:
                log.warning("query %s timed out; retrying once", name)
                continue
            raise GraphError(f"The graph query '{name}' failed: {exc}") from exc
    ms = round((time.perf_counter() - start) * 1000, 2)
    cols = [h[1] for h in result.header]
    rows = [dict(zip(cols, (_convert(v) for v in row))) for row in result.result_set]
    return rows, ms


def run_ro(name: str, /, **params: Any) -> tuple[list[dict[str, Any]], float]:
    """Run a read-only catalogue query (graph.ro_query). Returns (rows, ms)."""
    return _execute(name, params, read_only=True)


def run_rw(name: str, /, **params: Any) -> tuple[list[dict[str, Any]], float]:
    """Run a write catalogue query (graph.query). Returns (rows, ms)."""
    return _execute(name, params, read_only=False)


def drop_graph() -> None:
    """Delete the whole graph (used by seed/reset). Missing graph is fine."""
    try:
        graph().delete()
    except (RedisConnectionError, RedisTimeoutError, OSError) as exc:
        raise GraphUnavailable(UNREACHABLE) from exc
    except Exception:  # noqa: BLE001 - "empty key" when the graph does not exist yet
        pass
