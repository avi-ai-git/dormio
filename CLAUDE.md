# CLAUDE.md

Working notes for Dormio, an agentic assistant for Europe's night trains. Read README.md for the product and ARCHITECTURE.md for the design. This file is the map for anyone, human or model, working in the code.

## What it is

A Streamlit app. An agent answers in plain language, a map shows the network, and the routes come from a graph over a curated dataset, not from a model. The model only explains what the tools found.

## Layout

app.py wires the page, the sidebar with the logo, the model picker, the coverage metrics, the cycling trivia, and three tabs named Ask Dormio, The Night Map, and How It Works.

config.py holds the model registry, the moderation model, the Langfuse switch, the rate limits, and the app name, all read once from the environment.

agent/agent.py is the LangGraph agent, a router, a route tool node, a knowledge tool node, and a synthesis node. answer_query is the entry point and takes the conversation history, route_lookup is the deterministic routing tool, and classify exposes the router for the eval. Prompts are filled with _fill, a plain replacement that is safe against stray braces. _run_graph retries without tracing if a traced run fails.

agent/night_graph.py is the routing tool, an undirected graph over data/night_trains.json. plan_routes is a weighted k-shortest-paths search that returns up to three ranked journeys, up to two changes, capped by travel time so the alternatives stay sensible. from_city, all_services, route_geometry, service_endpoints, and the direct and chain building blocks sit alongside it. Every stop is a node, and city matching folds diacritics and resolves exonyms.

agent/knowledge.py is the retrieval layer. It builds a corpus from the guides in data/knowledge and the operator registry, embeds it into an in-memory ChromaDB collection with the small model it ships with, and exposes retrieve. It falls back to a keyword retriever if the vector store is missing.

agent/websearch.py is the last-mile web search, used only for the gap the curated data does not cover. It tries Serper, then SerpApi, then Tavily, returns the first non-empty result, and sorts trains and buses ahead of flights. It is gated on TEST_MODE and safe to run with no key.

agent/safety.py screens input with a rate limit, a prompt-injection filter, and Mistral moderation. agent/observability.py wires Langfuse and degrades quietly without a key.

ui/ holds the tabs. route_planner for the conversation, with pinned trips that each keep their own thread and memory. explore for the network, a switch between Night Train Routes and Night Train Operators over night_trains and operator_directory. about for How It Works. map_view for the deck.gl network map.

data/ holds the generated data files, the knowledge guides, and the vendored source views. scripts/ingest_open_db.py builds the data files from the Back-on-Track open database. eval/ holds the golden set and the runner. tests/ covers the graph, the knowledge layer, the agent, safety, the UI helpers, and the failure paths, all offline.

## How to run

```bash
pip install -r requirements.txt
cp .env.template .env
streamlit run app.py
```

Tests with `pytest tests/`, evaluation with `python eval/run_eval.py`. The app runs with no keys, falling back to the heuristic router and skipping the web search.

## Where the data comes from

Routes and operators come from the Back-on-Track Open Night Train Database, licensed CC BY-NC-ND 4.0. The data and the pipeline are at https://github.com/Back-on-Track-eu/night-train-data and the project is described at https://back-on-track.eu/open-night-train-database. The committed data files are enough to run the app. Re-run the ingestion only to refresh from the source. Known data errors are corrected in a small route-id-keyed map at the top of the ingestion, since there is no automatic way to catch an operator-substitution mistake.

## How I kept the code lean

I worked from the lazy-senior-dev idea that the best code is the code you never write. Before adding anything I checked whether the repo, the standard library, or an installed dependency already did it, and whether a deletion would do instead. Several rounds of this app got smaller, not bigger. A single-route map and a duplicate tab were removed once they stopped earning their place. Intentional shortcuts are marked with a comment that names the ceiling.

## Conventions

Commits use progressive phase numbers, phase 0, phase 1, phase 2 and so on, told as one story.

Prose in comments, the README, and commits avoids em dashes, en dashes, colons in sentences, and filler. Write plainly, in the active voice.

The model is the explainer only. It never decides a route. Routes come from the graph, knowledge comes from cited documents, the web is used only for the gaps and always labelled, so an answer can never invent a train.

One chunk per operator or topic in the knowledge corpus, never per route.

Verify with the tests and the eval before committing.

## Known limits

The data covers the scheduled night trains in the open database, refreshed twice a year, so a rare or charter service can be missing. Departure times are shown where they are known, so always confirm on the operator's site. Web results are a live search and should be confirmed on the linked site. A leg is weighted by the whole service duration, since the open data carries only endpoint times, which per-stop times will fix.

## Good next steps

Refresh data/ from the open database on the December timetable change, then run the tests and the eval. Add mixed day and night routing so a grand tour can chain a daytime leg between sleepers. Add live disruption notes for the busiest corridors. Open a small API over the night-train graph for other clients.
