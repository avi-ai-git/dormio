"""Tests for the RAG knowledge layer. Works offline on the ChromaDB vector backend
or the keyword fallback, since both should rank the right document for a clear query."""
import os

os.environ.setdefault("TEST_MODE", "true")

import pytest

from agent import knowledge

# A clear question and the guide that should be retrieved for it.
RETRIEVAL_CASES = [
    ("is my interrail pass valid on a sleeper", "interrail-and-eurail-passes.md"),
    ("difference between a couchette and a sleeper", "accommodation-classes.md"),
    ("can I take my bicycle on the night train", "night-train-travel-tips.md"),
    ("how far ahead do night-train bookings open", "seasons-and-booking-windows.md"),
]


def test_corpus_builds_with_guides_and_operators():
    stats = knowledge.corpus_stats()
    assert stats["documents"] >= 30
    assert stats["guides"] >= 5
    assert stats["operators"] >= 20


@pytest.mark.parametrize("query,expected_source", RETRIEVAL_CASES)
def test_retrieve_ranks_the_right_guide(query, expected_source):
    hits = knowledge.retrieve(query, k=4)
    assert hits, "retrieval returned nothing"
    assert expected_source in {h["source"] for h in hits}


def test_retrieve_returns_sources_and_scores():
    hits = knowledge.retrieve("how do I book a night train", k=3)
    assert len(hits) <= 3
    for h in hits:
        assert h["title"] and h["source"]
        assert "text" in h and h["text"]


def test_operator_chunk_is_retrievable():
    hits = knowledge.retrieve("ÖBB Nightjet booking", k=5)
    assert any(h["kind"] == "operator" or "nightjet" in h["text"].lower() for h in hits)


if __name__ == "__main__":
    import sys
    sys.exit(__import__("pytest").main([__file__, "-q"]))
