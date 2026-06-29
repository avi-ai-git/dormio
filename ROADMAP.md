# Roadmap

Dormio is intentionally lean for now. These are the ideas I want to keep, gathered from testing and from feedback, roughly in the order I would build them. Most are passion-project scope rather than things the core needs.

## Recently shipped

These closed real gaps found in testing, each reading the same data the map already used.

- Country lookup, so night trains in Poland lists every route that runs there, the set the map shows.
- Operator lookup, so routes on RegioJet lists the trains an operator runs, with a booking link, instead of the model guessing.
- A tighter web search, used only when retrieval finds nothing or the question is about a live price, so a how-it-works answer stays grounded in the cited guides.

## Routing

- Constrained journeys, where you say you want to pass through a city, like Berlin to Madrid by way of Paris, and the search honours it instead of only finding the quickest path.
- A short preference step, where the agent asks whether you want the fastest, the fewest changes, or the most scenic, and ranks for that.
- Mixed night and day legs, so a trip with no night train end to end can be stitched from a day train to a hub and a night train onward, with the day part clearly marked.
- Sharper timing once the data carries per-stop times, so a partial leg is timed exactly and the ranking gets more accurate.

## The map

- A live route map inside the chat, drawing the chosen journey and its alternatives in different colours, the way Waze shows two or three ways to go, with the time difference on each.
- The ability to tap an alternative on the map and have the chat switch to it.

## Knowledge and the web

- Deeper web validation, checking live times and prices against the operator sites and flagging when the curated data has drifted, so corrections almost write themselves.
- Retrieval for themed trips, a wine route through France, Oktoberfest by way of Munich, the most scenic line north, planned from a small set of destination guides rather than just the practical ones.

## Coverage and reach

- More of the network, beyond night trains into the day connections that finish a journey, and more countries as the open data grows.
- Live disruption notes for the busiest corridors.
- Saved and shareable trips that outlast a single session.
- A small API over the night-train graph, so other apps can ask it for a route.

## Why these are not in the build yet

Dormio is meant to do one job well, and piling on features works against that. The graph routing, the retrieval, the agent, the safety, and the evaluation already stand on their own. Everything above makes Dormio a richer product, but none of it is needed to answer honestly which night train you can take and how to book it.
