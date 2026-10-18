# AI-assistant disclosure

Hackathon rules ask us to state how AI assistants were used.

## While building

- **Claude Code** (Anthropic, Claude Opus 5.5) generated this repository from our written specification (product, graph model, Cypher catalogue, agent rules, API, UI and tests). That includes the backend, frontend, Cypher files, the synthetic Kettle Labs seed text, tests and these docs.
- The team wrote the specification, ran the app and tests, and is responsible for the result. Every part of the code is meant to be small enough for any of us to explain.
- Claude Code also drove a headless browser (Playwright) to screenshot the demo flow and check layouts. Playwright is a dev-only tool and isn't part of the app.

## At runtime

- WhyBase can call an LLM through **LiteLLM** (any provider, chosen with `LLM_MODEL`). The model only **chooses tools** from a fixed catalogue, fills their arguments, and writes a 1–3 sentence answer. It never writes Cypher. Every entity it names is resolved against the graph before a query runs. Its sentence is checked against the returned rows and replaced with a template sentence if it names anything the rows don't contain.
- With no LLM key, the app runs fully offline: a keyword router picks the tool and template sentences are used.

## Data

All people, teams, systems and documents belong to the fictional company Kettle Labs. No real people or private data are used.
