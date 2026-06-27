"""Web search for the gaps the curated night-train data does not cover.

Some questions sit just outside the night-train network. Monaco has no night train,
but Paris has one to Nice and a short day train finishes the trip. The curated graph
cannot answer that last mile, so a web search fills it, and the answer says plainly
that the extra detail came from the web, not from the verified data.

Resilient by design: it tries Serper first (Google results give the real booking
links), falls back to SerpApi, then Tavily, using whichever key is set. If one
provider is down or empty it moves to the next, so the last mile never errors out.
Every provider is optional and the whole thing degrades to an empty list with no key.
"""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)


def _serper(query: str, k: int) -> list[dict]:
    key = os.getenv("SERPER_API_KEY")
    if not key:
        return []
    resp = httpx.post("https://google.serper.dev/search",
                      headers={"X-API-KEY": key, "Content-Type": "application/json"},
                      json={"q": query, "num": k}, timeout=8.0)
    resp.raise_for_status()
    return [{"title": i.get("title", ""), "snippet": i.get("snippet", ""), "url": i.get("link", "")}
            for i in (resp.json().get("organic") or [])[:k]]


def _serpapi(query: str, k: int) -> list[dict]:
    key = os.getenv("SERPAPI_API_KEY")
    if not key:
        return []
    resp = httpx.get("https://serpapi.com/search.json",
                     params={"engine": "google", "q": query, "num": k, "api_key": key}, timeout=10.0)
    resp.raise_for_status()
    return [{"title": i.get("title", ""), "snippet": i.get("snippet", ""), "url": i.get("link", "")}
            for i in (resp.json().get("organic_results") or [])[:k]]


def _tavily(query: str, k: int) -> list[dict]:
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        return []
    resp = httpx.post("https://api.tavily.com/search",
                      json={"api_key": key, "query": query, "max_results": k}, timeout=10.0)
    resp.raise_for_status()
    return [{"title": i.get("title", ""), "snippet": i.get("content", ""), "url": i.get("url", "")}
            for i in (resp.json().get("results") or [])[:k]]


# Tried in order; the first provider that returns results wins.
_PROVIDERS = (("Serper", _serper), ("SerpApi", _serpapi), ("Tavily", _tavily))

# This is a night-train app, so the last mile should be trains first, then buses, and a
# flight only as a last resort. We never drop flight results, we just sink them to the
# bottom so they never lead.
_FLIGHT_HINTS = ("flight", "flights", "fly ", "airfare", "airline", "skyscanner",
                 "kayak", "ryanair", "easyjet", "wizz", "airport", "cheap flights")


def _is_flighty(result: dict) -> bool:
    blob = (result.get("title", "") + " " + result.get("url", "") + " "
            + result.get("snippet", "")).lower()
    return any(h in blob for h in _FLIGHT_HINTS)


def available() -> bool:
    if os.getenv("TEST_MODE", "false").lower() == "true":
        return False
    return any(os.getenv(k) for k in ("SERPER_API_KEY", "SERPAPI_API_KEY", "TAVILY_API_KEY"))


def search(query: str, k: int = 4) -> list[dict]:
    """Top web results as {title, snippet, url}, from the first provider that answers."""
    if os.getenv("TEST_MODE", "false").lower() == "true":
        return []
    for name, provider in _PROVIDERS:
        try:
            results = provider(query, k)
            if results:
                results.sort(key=_is_flighty)  # trains and buses first, flights last
                return results
        except Exception as exc:  # provider down, quota, or shape change: try the next
            logger.warning("web search via %s failed, trying the next: %s", name, exc)
    return []


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for hit in search("how to travel by train from Nice to Monaco", k=3):
        print(f"- {hit['title']}: {hit['snippet'][:80]} ({hit['url']})")
