# Dormio

Night trains across Europe, planned in plain language by an assistant that does not make things up.

Try it live at [dormio.streamlit.app](https://dormio.streamlit.app).

Dormio is a conversational planner for Europe's night trains. A traveller asks for a trip the way they would ask a friend who knows the network, something like Vienna to Rome, or night trains from Krakow, and gets real routes, real departure times, the sleeping options, and a clean way to book. The routes come from a graph over the actual network rather than from a language model, so the answer is correct and the app cannot put anyone on a train that does not exist. I built it because night trains are returning across Europe while the information about them stays scattered across dozens of operators, with no single calm place to plan one. Dormio pulls the whole network into one conversation, one map, and one honest answer.

## The problem

Night trains are quietly coming back. A traveller lies down in Vienna and wakes up in Rome, skips the airport, saves a hotel night, and travels on a fraction of the carbon of a flight. The trouble is planning one. Every country has its own operator, every operator has its own website, and no single place says which sleeper routes exist, what the sleeping options are, and how to book. The general journey planners make it worse, because a request for an overnight train comes back as a night bus or a cheap flight, since they return whatever moves next.

I wanted one place that answers the real questions. Is there a night train from here to there. What can I sleep in. How do I book it. And when there is no night train, it should say so plainly instead of inventing one.

## What it does

Dormio has three tabs.

Ask Dormio is the conversation. The user types a trip in plain words and keeps talking, and it remembers the thread. Ask for a route and it ranks the best night trains, a direct sleeper or a journey with one or two changes, and it shows the real alternatives, Berlin to Bucharest by way of Budapest or by way of Vienna. Ask about a whole country and it lists every night train that runs there, the same set the map shows, so night trains in Poland brings back all 28. Ask a how-does-it-work question, like whether an Interrail pass covers a couchette, and it answers from real guides and operator notes and shows the sources. When a trip runs off the edge of the network, like the last stretch from Nice down to Monaco, it searches the web for that one leg and labels the part that came from a search.

The Night Map is the whole network on one map. Every night train in Europe drawn as an arc, with a switch between Night Train Routes and Night Train Operators. Filter by country, sort by duration or by when a train leaves or arrives, narrow to trains that carry bikes, and the map and the list move together. Each card shows the times, the cities the train calls at, and the CO2 for the trip.

How It Works explains the design in plain words, lists the coverage, and sets out the ethics and privacy of the app, so a curious visitor can see exactly how an answer is produced.

## How it works under the hood

Every message runs through the same small pipeline.

```
a question
   -> input safety (rate limit, prompt-injection filter, Mistral moderation)
   -> router (route, knowledge, both, or chitchat, plus any cities or a country it can read)
        route      -> the night-train graph, a deterministic lookup over 204 routes, by city pair, from one city, or across a country
        knowledge  -> ChromaDB retrieval over guides and operator notes, with sources
        off the map-> a web search for the overland last mile, trains first
   -> synthesis, one grounded answer written only from what the tools returned
   -> answer, booking links, web links, cited sources
```

The rule that holds the whole thing together is simple. The model never decides a route and never states a fact the tools did not return. Routing comes from the graph, know-how comes from cited documents, the web is used only for the gaps and always labelled. I think of it as the model being on tap, not on top.

## The design decisions, and why I went this way

Routing comes from a graph, not the model. A language model asked to plan a night train will invent one, a plausible train number, a believable time, a route that does not run. So routing is a deterministic search over the real network. Cities are nodes, services are edges, and a weighted k-shortest-paths search returns the best few journeys. The same question always gives the same answer, the app cannot hallucinate a train, and an honest no night train is a valid result. A country question runs through the same data, so night trains in Poland filters the network to every route that runs there rather than asking the model to recall them. This is also the part anyone can read and check line by line, which is the point.

Knowledge comes from retrieval, with citations. The stable questions, how to book, whether a pass is valid, what a couchette is, do not belong in a graph. They belong in documents. I embed a small corpus of guides and operator notes into a vector store and retrieve the closest chunks, then the answer cites them. I chunk one document per operator or per topic, never one per route, because the per-route version I tried earlier produced duplicates and gave the model room to blur facts together.

The web fills only the last mile, and it leads with trains. Some trips sit just outside the network. Monaco has no night train, but Paris has one to Nice and a short day train finishes the journey. For that gap, and only that gap, Dormio runs a live search and labels the result. Because this is about travelling without flying, the search asks for overland options and sorts trains and buses ahead of flights, so a flight never leads and shows up only when nothing else does.

One agent decides which tool answers. A LangGraph router reads the message and the recent thread, classifies the intent, and pulls out any cities, then the right tool runs and a synthesis step writes the answer. Without a model, or in the tests, the router falls back to a deterministic heuristic, so the whole pipeline runs offline.

Streamlit, not React. The work worth the effort here is the AI, the graph, the retrieval, the agent, and the map. A React front end would have doubled the build for no gain in any of that. Streamlit gave me a clean chat, a real deck.gl map, and a deployable app in one language.

An in-memory vector store, not a hosted database. The knowledge corpus is small and rarely changes, so I build the ChromaDB collection once when the app starts and keep it in memory, with the small embedding model that ships with it, so there is no separate service to run and nothing heavy to install. A hosted vector database would have been weight this project does not need, and choosing a graph over a database for the routing is the stronger engineering story anyway.

Three models, one per integration pattern. The sidebar offers Claude Haiku through an aggregator, Mistral Large through a direct European API, and the open-weight GPT-OSS through a local runtime. One of each pattern shows the range without cluttering the choice, and since the model only writes the words, switching it changes the voice, never the routes.

Resilience over cleverness. Tracing is best effort, so if it ever breaks a run the agent retries without it. The tool steps degrade to empty instead of crashing. The prompt is built without string formatting, so a stray brace in a document or a message cannot break it. The traveller should always get an answer.

## The data

Routes and operators come from the Back-on-Track Open Night Train Database, a community project that keeps a careful open record of Europe's night trains, licensed CC BY-NC-ND 4.0. The ingestion script joins the published views, resolves a coordinate for almost every stop from the open stop table, cleans the operator list, derives the city sequences the graph needs, and writes three small files the app reads at startup. The current coverage is 204 night-train routes, 27 operators, and 26 countries that run a sleeper.

Open data carries the occasional error. A reader pointed out that a Stockholm to Berlin train was tagged with the wrong operator, and they were right. I keep a small hand-curated corrections map in the ingestion, keyed by route id, so a fix is one line. I will be honest that there is no fully automatic way to catch this class of mistake, because a wrong operator can still plausibly serve a country on the route, so the realistic answer is a corrections layer for the ones that get reported plus a web cross-check when something looks off.

Every route also carries a CO2 figure. Where the source has one, Dormio shows it. Where it does not, Dormio estimates it from the distance using the median intensity of the routes that do report both, and marks that number as an estimate, so a traveller always sees the carbon cost and always knows which figures are measured.

## Honesty and ethics

No data about the user is kept. There is no account and no tracking. A question is screened, answered, and forgotten, and the only stored data is the open night-train dataset.

The same answer goes to everyone. Routes come from the deterministic graph, not the model, so there is no model bias in what gets suggested and nobody is quietly shown a different train.

The app does not make a train up. Every route, time, and fact comes from the graph, a cited document, or a labelled web search, and an honest no night train here is a valid answer.

It is hard to misuse. Every message passes a rate limit, a prompt-injection filter, and a moderation check before any model runs.

## How I measured it

A golden set of 27 questions, each tagged with the tool it should reach and the outcome it should produce, scores the router, the graph, and retrieval, and an optional judge step scores groundedness, an automated check that every answer is supported by the facts the tools returned. The latest run shows routing accuracy at 100 percent live and 96 percent on the offline heuristic, route correctness at 100 percent, retrieval hit-rate at 90 percent, and groundedness around 4 out of 5, where a point comes off for a connective phrase the model adds around the facts rather than for an invented one. On top of that, 67 offline tests cover the graph, the retrieval layer, the agent, safety, the data integrity, and the failure paths, including a deliberately broken trace and a throwing tool that must still return an answer.

## The stack

Streamlit for the app and the chat, because it gave me a real map and a deployable app in one language. LangGraph for the agent, an explicit state machine I can trace. ChromaDB as the vector store for retrieval, in memory with the small embedding model it ships with. deck.gl for the map on a token-free basemap, so it needs no map key. Langfuse for optional tracing. Mistral for input moderation, kept separate from the chat model. The chat model is whichever of the three is selected in the sidebar.

## Run it locally

Python 3.10 or newer is required.

```bash
pip install -r requirements.txt
cp .env.template .env
streamlit run app.py
```

There is no build step and the data files are committed, so it runs with no keys, falling back to the deterministic heuristic and skipping the web search. Add keys to unlock the models, tracing, and the last-mile search. Rebuild the data from a fresh copy of the open database with `python scripts/ingest_open_db.py`. Run the checks with `pytest tests/` and the evaluation with `python eval/run_eval.py`.

## Roadmap

Mixed day and night routing, so the grand tour across the continent can chain a daytime leg between two sleepers instead of stopping at the edge of the network. This is the deliberate boundary today, and it is the most requested next step.

Per-stop times, so a partial leg is weighted by its own schedule rather than the whole service, which sharpens the ranking.

Live disruption notes for the busiest corridors, drawn from the operators that publish them.

Wider coverage as the open database grows, refreshed on the December timetable change.

A small API over the night-train graph, so other apps can ask it the same questions.

The fuller list, with why each piece is not in the build yet, is in [ROADMAP.md](ROADMAP.md).

## Credits and licence

Route and operator data from the Back-on-Track [Open Night Train Database](https://github.com/Back-on-Track-eu/night-train-data), licensed CC BY-NC-ND 4.0, described at [back-on-track.eu](https://back-on-track.eu/open-night-train-database). Built by Avishek Chatterjee. Feedback is welcome on [LinkedIn](https://www.linkedin.com/in/avishek-chatterjee/). The deeper design is in [ARCHITECTURE.md](ARCHITECTURE.md), and the working notes for anyone in the code are in [CLAUDE.md](CLAUDE.md).
