"""Every sample in data/examples.json behaves as documented (offline mode, fresh seed)."""
import json
from pathlib import Path

import pytest

from backend import agent, ingest, seed

EXAMPLES = json.loads((Path(__file__).resolve().parent.parent / "data" / "examples.json").read_text(encoding="utf-8"))


@pytest.mark.usefixtures("seeded")
@pytest.mark.parametrize("ex", EXAMPLES["questions"], ids=lambda e: e["q"])
def test_question(ex):
    r = agent.answer(ex["q"])
    want = ex["expect"]
    tools_run = [t["tool"] for t in r["tools"] if t["tool"] != "none"]
    assert tools_run == ([want["tool"]] if want["tool"] else []), r["answer"]
    assert r["outcome"] == want["outcome"], r["answer"]
    assert bool(r["choices"]) == want.get("choices", False)
    if r["outcome"] in ("answered", "stale_warning"):
        assert r["check"] == "passed" and r["paths"]


@pytest.mark.parametrize("ex", EXAMPLES["changes"], ids=lambda e: e["label"])
def test_change(ex, fresh):
    want = ex["expect"]
    prop = ingest.propose(ex["text"])
    p = prop["proposal"]
    assert p["system"] == want["system"] and p["author"] == want["author"]
    if want.get("problem"):
        assert want["problem"] in prop["problems"]
        return
    assert (p["old"], p["summary"]) == (want["old"], want["summary"])
    done = ingest.confirm(p["text"], p["system"], p["summary"], p["old"], p["author"])
    assert sorted(r["source_id"] for r in done["stale"]) == want["stale"]
    seed.seed()
