# Decisions made during the build

Where the spec was ambiguous, we picked the simplest option that keeps the §12 demo working. Each entry says what we chose and why.

## Data and queries

1. **Small additions to spec queries.** `who_knows` also returns `via_ids`, and `as_of` also returns `status` and `source_id`, so answers can carry real source ids in their paths. `stale_for_decision` also returns `kind`, `old_id` and `now_id`, so the Desk can render new rows without another call.
2. **Deterministic `fix_by`.** When a stale source's author has left, `stale_all` and `stale_for_decision` rank active teammates by how many sources they wrote about the same systems, then by seed order. Without this, `collect()` order is undefined. For the ledger guide (S-DOC-105, author Arjun Mehta, who left) this gives **Rohan Das, Ishaan Kapoor**, matching the demo script.
3. **Extra catalogue queries.** `current_head` (what replaced a superseded decision), `next_ids` (mint `D-0NN` / `S-CHAT-2NN`), `entities` (names for autocomplete, the answer check and the offline router), `sources_by_ids` (source chip details), `full_graph` ("Show everything"), `count_nodes` (auto-seed check) and the `seed_*` loaders. These are all hand-written files in `backend/queries/` and take only parameters.
4. **Indexes** are created with the client's `create_node_range_index(label, prop)`. This is equivalent to `CREATE INDEX FOR (n:Label) ON (n.prop)`. The (label, prop) pairs come from a fixed list in `seed.py`.
5. **Auto-seed on startup** if the graph is empty, so `docker compose up` alone gives a working app. `make seed` and `POST /api/reset` still wipe the graph and reload it.

## Agent behaviour

6. **When an answer counts as `stale_warning`**, per tool:
   - `why`: the question names something (e.g. "Kafka") whose decision is now superseded. That decision is the earliest one in the chain whose summary shares a content word with the question. Before the Redpanda change, "Why Kafka?" gets `answered`. After it, the same question gets `stale_warning` and points to D-013.
   - `stale_docs`: whenever it returns rows.
   - `reversal_impact`: the decision being reversed is already superseded.
   - `as_of`: the belief on that date has since been replaced.
   - `load_bearing`: the top-ranked decision is superseded.
7. **An ambiguous `DecisionRef`** (e.g. "reverse kafka" matches 3 decisions) returns outcome `unknown`, with the candidates in `choices` as clickable chips. No traversal runs.
8. **Tools with no entity argument that return 0 rows** (e.g. no stale docs) get `answered`, with an "all clear" sentence. `no_connection` is only used when a named entity resolved but the traversal found nothing.
9. **The resolver** first tries the literal string (case-insensitive), then the same string with spaces turned into hyphens ("event bus" → `event-bus`). Both lookups appear in the trace.
10. **Resolver calls are part of the trace**, so FR-11 shows exactly one `resolve_system` row and no traversal.
11. **The answer check also runs on template sentences.** A few plain hyphenated English words ("load-bearing", "in-house"…) are not treated as system names.
12. **Responses carry three extra fields:** `steps` (paths with node kinds and edge types, used for the path line and the Path tab), `tools` and `mode`.
13. **Offline `as_of` without a date** uses today.

## Ingest

14. The LLM extracts `system`, `summary` and `author` through a forced function call. `system` and `author` are JSON-schema enums of names that exist in the graph, and the confirm step resolves them again anyway. A second forced call picks the replaced decision from an enum of `candidates_for_system` ids. Offline, a regex handles "moving X from A to B" plus the `— Name` signature, and the most recent active decision is the one replaced.
15. The new source is a `chat` titled `Note from <author>: <summary>` and dated today.
16. When the user changes the system in the proposal card, the candidate list is built in the browser from `/api/entities`, so no extra endpoint is needed.

## API and UI

17. Added `GET /api/graph/all` for "Show everything", and `GET /api/queries/{name}` (read-only, whitelisted to catalogue names) for "Copy Cypher".
18. **CORS:** no CORS middleware is installed, so browsers only allow same-origin calls.
19. **Cytoscape labels:** decisions and sources are labelled by id to keep the canvas readable; the drawer shows full titles. Cytoscape has no `text-decoration`, so superseded labels are struck through with the U+0336 combining character.
20. Time travel defaults to today's date. The Load-bearing panel loads when it is first opened.

## Process

21. The project lives in `whybase/` (the repo root).
22. Tests use a separate graph (`whybase_test`), so running them never touches the demo graph.
23. UI milestones M7–M9 were committed together because the panels share one state module (`app.js`).
24. `make` isn't available on Windows by default, so the README lists the equivalent commands.

## Running for real (added after first end-to-end runs)

25. **Default LLM: `gemini/gemini-3.1-flash-lite`.** It answers in about 1–3 s and has its own free-tier quota. `gemini-3.8-flash` also works, but its free tier allows only 20 requests a day, which runs out in a few demo runs. Google has retired `gemini-2.5-flash` for new keys.
26. **`mcp>=2.3` is a dependency.** LiteLLM 1.106 imports it on the tool-calling path. Older `mcp` versions break with pydantic 2.14.
27. **LiteLLM is imported at module load,** not inside request threads. Failures in `llm_online()` are logged rather than silently treated as offline mode.
28. **Question budget of 20 s** on top of the 15 s per-call timeout. Once a question passes it, the agent stops calling the model and uses the template sentence for the tool results it already has. A slow or rate-limited model can't stall the UI.
29. **A read query that hits FalkorDB's 1 s query timeout is retried once.** Any other FalkorDB error returns JSON `{error: {code: "graph_error"}}` with status 500, never a plain-text 500.
30. **Offline Docker builds.** `requirements.lock` pins the Linux packages, taken from `pip freeze` in the container. `make wheels` downloads those exact wheels with `--no-deps`, because `pip download` on Windows evaluates platform markers as Windows. The Dockerfile installs from `./wheels` and falls back to PyPI. The wheel files themselves are gitignored.
31. **Rate-limit cooldown.** After a 429 the agent stops calling the LLM for the retry delay the provider asks for (capped at 1 h) and answers with the offline router. Retrying would fail on every question anyway. `/api/health` reports `llm: "rate_limited"` with `llm_retry_in`, the header pill shows "LLM quota hit · offline", and the answer footer says "rate-limited" instead of "failed".

## Bigger dataset and examples

32. **Extended Kettle Labs.** The seed now has 2 more teams (Mobile, Security), 5 more systems, 8 more people, 4 more projects, 9 more decisions and 22 more sources. The new data is designed so every §5 property still holds: 3 stale docs at the start, the same 3 at-risk systems, reversing D-002 hits exactly 7 items, D-002 ranks first by PageRank, time travel is unchanged, and checkout-api has no sources. The one visible difference: new seeded decisions take D-013 to D-021, so the live Redpanda change records **D-022** (the spec says D-013).
33. **Sources can be seeded as already reviewed** (`reviewed_at` / `reviewed_by`). The Vault → KMS and native → React Native chains show what a doc looks like after **Mark reviewed**.
34. **`data/examples.json`** is the single list of sample questions and changes, each with its expected result. It's served at `GET /api/examples` for the UI, checked by `tests/test_examples.py`, and turned into `docs/TESTING_GUIDE.md`.
35. **The reversal sentence counts distinct items.** When several paths reach the same project, the item is listed once, at its shortest hop count. Every path still appears in the Path tab.
36. **A kebab-case name the graph doesn't know beats a topic guess.** "Why do we use blockchain-ledger?" is reported as unknown rather than answered about `payments-ledger`.
37. **The "why" topic rule prefers words outside the system's name.** It falls back to the name's own words only when the question doesn't name the system ("Why did we use Vault?" → the Vault decision).
38. **Offline ingest keeps the message's verb** (Move, Switch, Migrate or Replace) in the summary.
39. **A missing graph reads as empty.** On a brand-new FalkorDB, read queries return no rows instead of an error, so the startup auto-seed works.
40. **The resolver understands technology names.** If a system argument isn't a system name, `system_for_topic` looks for it as a whole word in decision summaries. When those decisions all concern one system, the name resolves to that system ("KMS" → `secrets-vault`, "RabbitMQ" → `event-bus`). Kebab-case names are never mapped this way, so made-up systems stay unknown. Names shared by several systems ("Kafka") don't resolve. The LLM's instructions also list each system with its decisions, so it usually passes the right name directly.
