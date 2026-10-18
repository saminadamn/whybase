"""Shared fixtures. Tests run against a separate graph so they never touch the demo graph."""
import os

os.environ["GRAPH_NAME"] = "whybase_test"
os.environ["LLM_MODEL"] = ""  # force offline mode unless a test mocks the LLM

import pytest  # noqa: E402

from backend import db, seed  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _require_falkordb():
    if not db.ping():
        pytest.exit("FalkorDB is not reachable on FALKOR_HOST:FALKOR_PORT. Run `make up` first.", returncode=2)


@pytest.fixture()
def fresh():
    """A freshly seeded graph for tests that write."""
    seed.seed()
    yield


@pytest.fixture(scope="module")
def seeded():
    """A seeded graph shared by read-only tests in a module."""
    seed.seed()
    yield
