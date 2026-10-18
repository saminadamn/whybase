"""Resolver, outcomes and the answer check. The LLM is always mocked."""
import pytest

from backend import agent, tools

pytestmark = pytest.mark.usefixtures("seeded")


# ---------------------------------------------------------------- resolver + outcomes (offline)

def test_resolver_tolerates_spaces_and_case():
    trace = []
    assert tools.resolve_system("Event Bus", trace) == "event-bus"
    assert tools.resolve_system("quantum-cache", trace) is None


def test_why_kafka_answered_with_chain():  # FR-2
    r = agent.answer("Why do we use Kafka for the event bus?")
    assert r["outcome"] == "answered"
    assert r["paths"] == [["event-bus", "D-002", "D-001"]]
    assert {s["id"] for s in r["sources"]} == {"S-ADR-007", "S-ADR-001"}
    assert {"Priya Nair", "Dev Malhotra"} <= set(r["highlight"])
    assert r["check"] == "passed" and r["mode"] == "offline"


def test_stale_docs_lists_three():  # FR-3
    r = agent.answer("Which docs are out of date?")
    assert r["outcome"] == "stale_warning"
    assert sorted(row["source_id"] for row in r["rows"]) == ["S-DOC-101", "S-DOC-102", "S-DOC-103"]


def test_who_knows_payments_ledger():  # FR-4
    r = agent.answer("Who knows payments-ledger?")
    assert r["outcome"] == "answered"
    assert r["rows"][0]["person"] == "Arjun Mehta" and r["rows"][0]["status"] == "left"


def test_reversal_impact_paths():  # FR-5
    r = agent.answer("What breaks if we reverse D-002?")
    assert len(r["rows"]) == 7 and len(r["paths"]) == 7
    assert ["Instant Refunds", "D-005", "D-004", "D-002"] in r["paths"]


def test_as_of_with_natural_date():
    r = agent.answer("What did we use for search on 1 Jan 2026?")
    assert [row["id"] for row in r["rows"]] == ["D-008"]


def test_unknown_runs_no_traversal():  # FR-11
    r = agent.answer("Who knows quantum-cache?")
    assert r["outcome"] == "unknown"
    assert "quantum-cache" in r["answer"]
    assert {t["tool"] for t in r["trace"]} == {"resolve_system"}
    assert r["rows"] == [] and r["paths"] == []


def test_no_connection():  # FR-12
    r = agent.answer("Who knows checkout-api?")
    assert r["outcome"] == "no_connection"
    assert "checkout-api" in r["answer"] and "isn't recorded" in r["answer"]


def test_ambiguous_decision_returns_choices():
    r = agent.answer("What breaks if we reverse kafka?")
    assert r["outcome"] == "unknown" and len(r["choices"]) > 1


def test_unroutable_question():
    r = agent.answer("hello there")
    assert r["outcome"] == "unknown" and r["trace"] == []


# ---------------------------------------------------------------- LLM loop (mocked)

from types import SimpleNamespace as NS  # noqa: E402
import json  # noqa: E402


def tool_call(name, args, i=0):
    return NS(id=f"call_{i}", function=NS(name=name, arguments=json.dumps(args)))


def reply(content=None, calls=None):
    return NS(choices=[NS(message=NS(content=content, tool_calls=calls))])


@pytest.fixture()
def llm(monkeypatch):
    """Script the LLM: pass a list of replies; returns the list of message lists it was called with."""
    seen = []

    def install(replies):
        it = iter(replies)
        monkeypatch.setattr(agent, "llm_online", lambda: True)

        def fake(messages):
            seen.append(list(messages))
            nxt = next(it)
            if isinstance(nxt, Exception):
                raise nxt
            return nxt
        monkeypatch.setattr(agent, "_call_llm", fake)
        return seen
    return install


def test_llm_sentence_kept_when_grounded(llm):
    llm([reply(calls=[tool_call("why", {"system": "event-bus"})]),
         reply("We use Kafka because Priya Nair decided D-002 to replace RabbitMQ (D-001).")])
    r = agent.answer("Why do we use Kafka for the event bus?")
    assert r["mode"] == "online" and r["outcome"] == "answered"
    assert r["check"] == "passed" and r["answer"].startswith("We use Kafka because Priya Nair")
    assert r["paths"] == [["event-bus", "D-002", "D-001"]]  # path comes from rows, not the LLM


def test_answer_check_replaces_invented_system(llm):  # FR-13
    llm([reply(calls=[tool_call("why", {"system": "event-bus"})]),
         reply("We use Kafka because auth-gateway needed it.")])
    r = agent.answer("Why do we use Kafka for the event bus?")
    assert r["check"] == "replaced: auth-gateway"
    assert r["answer"].startswith("event-bus follows D-002")


def test_answer_check_replaces_real_but_unreturned_person(llm):
    llm([reply(calls=[tool_call("why", {"system": "event-bus"})]),
         reply("Kavya Rao chose Kafka.")])
    r = agent.answer("Why do we use Kafka for the event bus?")
    assert r["check"] == "replaced: Kavya Rao"


def test_unknown_entity_stops_the_loop(llm):
    seen = llm([reply(calls=[tool_call("who_knows", {"system": "quantum-cache"})])])
    r = agent.answer("Who knows quantum-cache?")
    assert r["outcome"] == "unknown" and len(seen) == 1
    assert [t["tool"] for t in r["trace"]] == ["resolve_system", "resolve_system"] or \
           {t["tool"] for t in r["trace"]} == {"resolve_system"}


def test_tool_calls_capped_at_four(llm):
    many = [reply(calls=[tool_call("knowledge_risk", {}, i)]) for i in range(6)]
    llm(many)
    r = agent.answer("Which systems are at risk?")
    assert len(r["tools"]) == 4


def test_llm_timeout_falls_back_to_offline(llm):
    llm([TimeoutError("took too long")])
    r = agent.answer("Who knows payments-ledger?")
    assert r["mode"] == "offline" and r["outcome"] == "answered"
    assert any(t["tool"] == "llm" and "offline router" in t["note"] for t in r["trace"])


def test_unknown_tool_name_is_rejected(llm):
    llm([reply(calls=[tool_call("drop_everything", {})])])
    r = agent.answer("Delete the graph")
    assert r["outcome"] == "unknown"


def test_over_budget_uses_template(llm, monkeypatch):
    monkeypatch.setattr(agent, "QUESTION_BUDGET_S", -1)   # any elapsed time is over budget
    seen = llm([reply(calls=[tool_call("why", {"system": "event-bus"})]), reply("never used")])
    r = agent.answer("Why do we use Kafka for the event bus?")
    assert len(seen) == 1 and r["answer"].startswith("event-bus follows D-002") and r["mode"] == "online"


class FakeRateLimit(Exception):
    pass


FakeRateLimit.__name__ = "RateLimitError"


def test_rate_limit_pauses_llm(llm, monkeypatch):
    monkeypatch.setattr(agent, "_cooldown_until", 0.0)
    seen = llm([FakeRateLimit('quota exceeded "retryDelay": "120s"')])
    r = agent.answer("Who knows payments-ledger?")
    assert r["mode"] == "offline" and "rate-limited" in r["trace"][-1]["note"]
    assert 100 < agent.llm_cooldown_s() <= 120
    r2 = agent.answer("Who knows payments-ledger?")      # paused: no second LLM call
    assert len(seen) == 1 and "paused" in r2["trace"][-1]["note"] and r2["outcome"] == "answered"


def test_llm_technology_name_resolves_to_system(llm):
    """Online, the model may pass 'Vault' or 'KMS' as the system; the resolver maps it through decisions."""
    llm([reply(calls=[tool_call("why", {"system": "Vault"})]), reply("Vault was replaced by KMS (D-014).")])
    r = agent.answer("Why did we use Vault?")
    assert r["tools"][0]["args"] == {"system": "secrets-vault"}
    assert r["outcome"] == "stale_warning" and "system_for_topic" in [t["tool"] for t in r["trace"]]


def test_topic_resolution_never_maps_made_up_kebab_names():
    trace = []
    assert tools.resolve_system("RabbitMQ", trace) == "event-bus"
    assert tools.resolve_system("kms", trace) == "secrets-vault"
    assert tools.resolve_system("quantum-cache", trace) is None
    assert tools.resolve_system("kafka", trace) is None      # several systems decided things about Kafka
