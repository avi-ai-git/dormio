# Architecture

How Dormio is built, and the reasoning behind each choice. Read README.md first for the product. This file is for the engineer who wants the why.

## The problem in three beats

Situation. Night trains are returning across Europe. Travelling overnight saves a hotel night, skips the airport, and uses far less carbon than flying, and new sleeper routes open most years.

Complication. The information is scattered. Dozens of operators, each on its own site, with no shared place to see which routes exist, what you can sleep in, and how to book. The general planners answer an overnight request with a night bus or a flight, because a live router returns whatever moves next rather than the train you wanted.

Resolution. Dormio is scoped to night trains and sends each kind of question to the tool that fits. A route question goes to a deterministic graph over the real network. A how-it-works question goes to retrieval over real documents that the answer cites. A trip that falls off the network goes to a web search for the overland last mile, clearly labelled. The model only puts the found facts into words.

## Who it is for

The traveller planning one specific overnight trip who wants a straight answer. The climate-conscious traveller who would rather sleep on a train than fly. The backpacker chaining overnight hops and checking a pass. The rail-curious who want to see the whole network on one map.

## The shape of a request

```
your message
   -> input safety (rate limit, prompt-injection filter, Mistral moderation)
   -> router node (intent, any cities, and any country)
        route / both -> route tool node -> the night-train graph
        knowledge    -> knowledge tool node -> ChromaDB retrieval
        off the map  -> web search for the overland last mile
   -> synthesis node (one grounded answer from the tool outputs)
   -> answer, booking links, web links, cited sources
```

## The agent, agent/agent.py

A small LangGraph with a router, two tool nodes, and a synthesis node. The router reads the latest message and the recent thread, decides between route, knowledge, both, and chitchat, and pulls out any cities or a country. With a model it uses a short few-shot prompt that returns JSON. Without a model, or under test, it falls back to a deterministic heuristic that reads the text around the word to and checks each candidate city against the graph, so the pipeline runs with no keys at all.

Synthesis writes one answer from the tool outputs only, in the context of the thread, so a follow-up like how do I book it resolves against the previous turn. The prompt allows clean bullet points for a multi-leg itinerary, bans invented trains, times, and prices, bans headings and long dashes, and tells the model to favour trains then buses and never to lead with a flight.

Two engineering decisions live here and both exist because of a real bug. First, prompts are filled with plain replacement, not Python string formatting, because a single stray brace in a retrieved document or a user message used to crash the run. Second, the run is resilient. Tracing is attached as a best-effort callback, and if a traced run throws the agent retries once without tracing, so an observability hiccup can never cost a traveller an answer. Both tool nodes catch their own errors and return empty results rather than propagating, and the entry point returns a graceful message instead of ever raising.

## The routing tool, the graph, agent/night_graph.py

The network is an undirected graph. Cities are nodes, night-train services are edges, and every stop on a service is a node, so you can board in the middle, Amsterdam on the Brussels to Prague sleeper, not only at the ends. City matching folds diacritics and resolves exonyms, so Vienna finds Wien and Krakow finds Kraków.

The core is plan_routes, a weighted k-shortest-paths search.

A leg is one ride on one service between two of its stops. The weight of a leg is the service duration, with a fixed penalty for an unknown time so a route with missing data sorts behind one with real data. The search is best-first over a heap, popping the cheapest partial journey, extending it by every service leaving the current city, and stopping a journey at two changes. It collects up to three finished journeys to the destination, ranked by the chosen preference, fewest changes first by default or shortest time when the message asks for the fastest.

Two guards keep the alternatives sensible. A cost cap keeps only journeys within twice the best total or twelve hours longer, so Berlin to Munich to Vienna to Bucharest survives while a forty-hour detour is dropped. A same-city transfer guard blocks changes that only swap stations inside one city, which removes artifacts like a pointless change at a second Vienna station. Results are de-duplicated by their city path, keeping the fastest of any duplicates. This is how the assistant offers a real choice, by way of Budapest or by way of Vienna, with nobody hardcoding the via city.

One honest limit. A leg counts the whole service duration, because the open data carries only endpoint times, which slightly overcounts a partial leg and, usefully, penalises odd detours. Per-stop times are the upgrade and are in the roadmap. Around plan_routes sit from_city for the discovery mode, all_services for the map, route_geometry and service_endpoints for drawing, and the direct and chain building blocks. A country question takes a parallel path, where resolve_country reads a name or a code and routes_in_country returns every service that runs through it, the same field the map filters on, so the chat and the map never disagree on what runs in Poland. Everything is deterministic and offline, so the same question always gives the same answer and an honest no night train is a real result.

## The knowledge tool, retrieval, agent/knowledge.py

This answers the stable questions a graph cannot, how to book, whether a pass is valid, what a couchette is, whether a bike is allowed. The corpus is one chunk per operator or per topic, never per route, because the per-route version produced duplicates and let the model blur facts. It is built from a set of written guides and the operator registry, embedded into an in-memory ChromaDB collection with the small embedding model it ships with, built once when the app starts and cached, so retrieval needs no separate service and nothing heavy to install. If the vector store is ever unavailable a keyword retriever stands in, so retrieval degrades rather than disappears. Today the corpus is 98 documents, 5 guides and 93 operator profiles.

## The web search, for the gaps, agent/websearch.py

Some trips sit just outside the network, so for a route that is off the map or has no night train, Dormio runs a live search and uses it only for the missing leg, labelled as a search the traveller should confirm. It tries three providers in order, Serper, then SerpApi, then Tavily, and the first that answers wins, so one provider being down or out of quota does not break the last mile. Each provider is optional and the whole thing returns nothing without a key. Because this is a night-train app, the results are sorted to put trains and buses ahead of flights, so a flight never leads and appears only when there is no overland option.

## The data pipeline, scripts/ingest_open_db.py

Routes and operators come from the Back-on-Track Open Night Train Database, licensed CC BY-NC-ND 4.0. The ingestion joins the published views on route id, resolves a coordinate for almost every stop from the open stop table, cleans the operator list, derives the city sequences the graph needs, and writes three small files, the night-train map, the operator registry, and a coordinate cache so a rebuild does not need the large stop table. Amenities are read from the GTFS-style codes, where one means yes and anything else is treated as no, which is the conservative reading after an earlier version counted a no as a yes. The data is refreshed on the timetable change, since night trains change twice a year, not by the minute.

Correcting the data is a corrections map keyed by route id, one line per fix. There is no fully automatic way to catch an operator-substitution error, because the wrong operator can still plausibly serve a country on the route, so reported fixes plus a web cross-check is the honest approach, not a magic script.

CO2 is shown for every route. Where the source reports it, that figure is used. Where it does not, the figure is estimated from the distance using the median intensity of the routes that report both numbers, and shown as an estimate, with a great-circle distance standing in when even the distance is missing.

## The map, ui/map_view.py

The Night Map draws the network with deck.gl through pydeck. Each route is one curved arc. Endpoints resolve by city name first and fall back to the coordinates baked into each service, which is what lets the whole Ukrainian network draw even though those station names are not in the name table. Only the city points are hoverable, so the tooltip does not flicker across a hundred crossing arcs. The view frames Europe by default with room to scroll out a little, and the basemap is a token-free Carto dark style, so it works anywhere without a Mapbox key.

## The models and safety, config.py and agent/safety.py

The sidebar offers three chat models, Claude Haiku 4.5 through OpenRouter as the default, Mistral Large through its direct API, and the open-weight GPT-OSS 120B on Ollama, one per integration pattern. The model runs the router and the synthesis only. It never selects a route and never states a fact the tools did not return, so switching it changes the wording, never the routes. Input is rate limited, screened for prompt injection, and run through Mistral moderation, separate from the chat model, before any model call. Every run is traced in Langfuse when a key is set, the router decision, the tool used, the latency, and what the model was given.

## Evaluation, eval/run_eval.py

A golden set of 27 questions, each tagged with the tool it should reach and the outcome it should produce, scores whether the router picks the right tool, whether the graph returns the right kind of result including the country mode, and whether retrieval finds the right guide. A judge flag adds groundedness, an automated check that each answer is supported by the facts the tools returned. The latest numbers are routing 100 percent live and 96 percent offline, route correctness 100 percent, retrieval 90 percent, and groundedness around 4 out of 5. Alongside the eval, 67 offline tests cover the graph, retrieval, the agent, safety, data integrity, and the failure paths.

## What I deliberately left out

This began as a broad live planner and it returned buses, because a live router is the wrong tool for a curated-knowledge domain, so I replaced it with the graph. A later pass stripped retrieval entirely and went too far the other way, so the app could not answer the how-it-works questions people actually ask. The version here keeps both tools, each scoped to what it is good at, with an agent to choose between them and a web search only for the gaps. The grand tour across the whole continent, chaining daytime legs between sleepers, is out of scope on purpose, because filling those gaps means day trains and buses, which is the multimodal planner this project deliberately is not. It is named in the roadmap as the next direction.

## What is next

Mixed day and night routing for the grand tour. Per-stop times to sharpen the ranking. Live disruption notes for the busiest corridors. Wider coverage on each timetable change. A small API over the graph so other apps can query it.
