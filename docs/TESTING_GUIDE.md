# Testing guide

Everything here works in **offline mode** (no LLM key). With an LLM configured, the model writes the sentence, but the outcome, path and sources are the same, because they come from the graph.

> Use **Reset demo** in the header (or `POST /api/reset`) to return to a fresh graph. The expected results below assume a fresh graph. In the app, the **Examples** button next to the question box lists the same questions, and **Try an example…** in *Something changed?* fills in the sample messages.

Every example below is checked automatically by `tests/test_examples.py`.

## What's in the graph

Kettle Labs (fictional): **23 people**, 6 teams, **13 systems**, 10 projects, **47 sources** (docs, chats, tickets, ADRs) and **21 decisions**.

| Team | Systems | People (⚑ = left the company) |
|---|---|---|
| Platform | `event-bus`, `auth-service`, `data-warehouse`, `api-gateway` | Aditi Bose, Priya Nair, Kavya Rao, Neha Joshi, Dev Malhotra ⚑, Manav Shah |
| Payments | `payments-ledger`, `checkout-api`, `fraud-engine` | Rohan Das, Arjun Mehta ⚑, Ishaan Kapoor, Farhan Ali, Pooja Reddy |
| Growth | `notification-service`, `feature-flags` | Sana Qureshi, Ananya Ghosh, Kabir Sethi, Ira Sen |
| Search | `search-index` | Meera Pillai, Vikram Iyer, Tara Menon |
| Mobile | `mobile-app` | Rhea Kulkarni, Siddharth Bhat, Zoya Khan ⚑ |
| Security | `secrets-vault`, `audit-log` | Nikhil Verma, Leela Fernandes |

Decision chains worth knowing:

- **D-001** `event-bus`: Use RabbitMQ as the event bus *(superseded)*
- **D-002** `event-bus`: Move the event bus from RabbitMQ to Kafka (replaces D-001)
- **D-003** `payments-ledger`: Store ledger entries as double-entry rows in Postgres
- **D-004** `payments-ledger`: Publish ledger events to the Kafka topic ledger.events (relies on D-002, D-003)
- **D-005** `payments-ledger`: Refunds service consumes ledger.events for instant refunds (relies on D-004)
- **D-006** `auth-service`: Use JWT access tokens with 15-minute expiry *(superseded)*
- **D-007** `auth-service`: Switch to opaque session tokens backed by Redis (replaces D-006)
- **D-008** `search-index`: Use Elasticsearch for the search index *(superseded)*
- **D-009** `notification-service`: Trigger notifications from a Kafka consumer group (relies on D-002)
- **D-010** `search-index`: Move search from Elasticsearch to OpenSearch (replaces D-008)
- **D-011** `feature-flags`: Run feature flags on an in-house flag service
- **D-012** `data-warehouse`: Load event-bus data into the warehouse in a daily batch (relies on D-002)
- **D-013** `secrets-vault`: Store service secrets in HashiCorp Vault *(superseded)*
- **D-014** `secrets-vault`: Move secrets from Vault to cloud KMS with short-lived credentials (replaces D-013)
- **D-015** `audit-log`: Write audit events to an append-only log in object storage (relies on D-014, D-007)
- **D-016** `api-gateway`: Route all public traffic through an Envoy-based API gateway (relies on D-007)
- **D-017** `api-gateway`: Rate-limit public APIs per API key at the gateway (relies on D-016)
- **D-018** `fraud-engine`: Score payments with a gradient-boosted fraud model (relies on D-003)
- **D-019** `mobile-app`: Build the mobile apps natively in Swift and Kotlin *(superseded)*
- **D-020** `mobile-app`: Rebuild the mobile app in React Native (replaces D-019; relies on D-011)
- **D-021** `mobile-app`: Gate mobile releases behind feature flags (relies on D-011, D-020)

## Questions to ask

### Why

| Ask | Expect | What it shows |
|---|---|---|
| Why do we use Kafka for the event bus? | ✓ Answered via `why` | The SUPERSEDES chain D-002 → D-001 with ADRs and deciders. |
| Why did we use RabbitMQ? | ⚠ Out of date via `why` | RabbitMQ was replaced, so the answer is flagged out of date and points to the current decision. |
| Why do we use KMS for secrets? | ✓ Answered via `why` | D-014 replaced the Vault decision D-013. |
| Why did we use Vault? | ⚠ Out of date via `why` | The system is found from the word 'Vault' alone; Vault is superseded. |
| Why does the mobile app use React Native? | ✓ Answered via `why` | D-020 replaced native apps (D-019) after the Android lead left. |
| Why do we use OpenSearch? | ✓ Answered via `why` | D-010 replaced Elasticsearch. |
| Why do we have an API gateway? | ✓ Answered via `why` | A system with two active decisions (D-016, D-017). |

### Out of date

| Ask | Expect | What it shows |
|---|---|---|
| Which docs are out of date? | ⚠ Out of date via `stale_docs` | 3 docs on a fresh seed, each with who should fix it. Departed authors are routed to teammates. |

### Who knows

| Ask | Expect | What it shows |
|---|---|---|
| Who knows payments-ledger? | ✓ Answered via `who_knows` | The top expert has left; only one active person remains. |
| Who knows mobile-app? | ✓ Answered via `who_knows` | Zoya Khan (left) wrote the native ADR; two active engineers remain. |
| Who knows secrets-vault? | ✓ Answered via `who_knows` | Security team members ranked by evidence. |
| Which systems are at risk? | ✓ Answered via `knowledge_risk` | payments-ledger, data-warehouse and notification-service each depend on one active person. |
| Who knows checkout-api? | ∅ Nothing connects via `who_knows` | The system exists but no source mentions it: nothing connects. |

### What breaks

| Ask | Expect | What it shows |
|---|---|---|
| What breaks if we reverse D-002? | ✓ Answered via `reversal_impact` | 7 items up to 3 hops, including Instant Refunds via D-005 → D-004. |
| What breaks if we reverse D-007? | ✓ Answered via `reversal_impact` | Session tokens hold up the API gateway, audit log, Enterprise SSO, SOC 2 and the Public API. |
| What breaks if we reverse D-011? | ✓ Answered via `reversal_impact` | Several paths reach Mobile Relaunch; each item is counted once. |
| What breaks if we reverse D-013? | ∅ Nothing connects via `reversal_impact` | The old Vault decision: nothing relies on it any more. |
| Which decisions are most load-bearing? | ✓ Answered via `load_bearing` | PageRank over RELIES_ON; D-002 ranks first. |

### Time travel

| Ask | Expect | What it shows |
|---|---|---|
| What did we use for search on 1 Jan 2026? | ⚠ Out of date via `as_of` | Elasticsearch then; it has since been replaced. |
| What did we use for secrets on 1 Jan 2026? | ⚠ Out of date via `as_of` | Vault then; KMS now. |
| What did we believe about mobile-app as of 2025-01-01? | ⚠ Out of date via `as_of` | Native Swift and Kotlin apps. |
| What was the event bus on 2023-06-01? | ∅ Nothing connects via `as_of` | Before any recorded decision. |

### Guardrails

| Ask | Expect | What it shows |
|---|---|---|
| Who knows quantum-cache? | ✕ Unknown via `who_knows` | Not in the graph, so only the resolver runs. No traversal. |
| Why do we use blockchain-ledger? | ✕ Unknown via `why` | A made-up system name is never queried. |
| What breaks if we reverse kafka? | ✕ Unknown via `reversal_impact` | 'kafka' matches several decisions, so WhyBase asks which one. |
| Tell me a joke | ✕ Unknown | Not a graph question; nothing runs. |

## Changes to record (Something changed?)

Paste a message, click **Read it**, check the proposal (nothing is written yet), then **Confirm & record**. Try each on a fresh graph. The new decision takes the next free id (D-022 on a fresh graph).

| Message | Proposal | Newly out of date |
|---|---|---|
| Team call today: we're moving event-bus from Kafka to Redpanda — Kafka ops cost is too high and Redpanda speaks the Kafka API. — Priya Nair | `event-bus`, replaces D-002, by Priya Nair: *Move event-bus from Kafka to Redpanda* | S-DOC-104, S-DOC-105, S-DOC-106 |
| Growth sync: moving feature-flags from in-house to LaunchDarkly — running our own flag service costs too much. — Sana Qureshi | `feature-flags`, replaces D-011, by Sana Qureshi: *Move feature-flags from in-house to LaunchDarkly* | S-DOC-110 |
| Security review: moving auth-service from Redis to WebAuthn passkeys so sign-in survives device changes. — Kavya Rao | `auth-service`, replaces D-007, by Kavya Rao: *Move auth-service from Redis to WebAuthn* | S-DOC-113 |
| API council: switching api-gateway from per-key to per-account rate limits from 1 November. — Kavya | `api-gateway`, replaces D-017, by Kavya Rao: *Switch api-gateway from per-key to per-account* | S-DOC-112 |
| Let's all use dark mode in Slack from Monday. — Ira Sen | No system matched, so WhyBase asks you to pick one (author Ira Sen) | — |

### Things to try after recording a change

- Ask the matching *Why* question again. It now comes back **⚠ Out of date** and names the new decision.
- Ask *What breaks if we reverse* the replaced decision. It's flagged as already superseded, with everything that still relies on it.
- In **Out of date**, click a row to see `source → ASSUMES → old ← SUPERSEDES ← new` in the graph, then **Mark reviewed** to re-point the doc to the new decision.
- Open the **Trace** tab: every tool call, the rows it returned, timing, and **Copy Cypher**.

## Guardrails to check

- Made-up names (`quantum-cache`, `blockchain-ledger`) are never queried. Only the resolver runs.
- A vague decision reference ("reverse kafka") gets **Did you mean** choices instead of a guess.
- With an LLM on, the answer check replaces any sentence that names something not in the results. The footer says *check replaced the model's sentence*.
- Stop FalkorDB (`docker compose stop falkordb`): the app shows a *Graph down* banner and returns 503s instead of crashing.
