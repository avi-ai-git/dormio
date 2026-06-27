"""The night-train knowledge layer: retrieval-augmented answers about how night
trains actually work.

This is the RAG half of the assistant. It does NOT answer routing questions, that
is the deterministic graph's job. It answers the stable, descriptive questions a
traveller asks around a trip: how do I book, is my Interrail pass valid, what is a
couchette, can I take a bike, which season does a route run.

The corpus is built from two sources, one chunk per operator or topic, never per
route, so there is nothing to duplicate and nothing for the model to stitch into a
fake train:

  data/knowledge/*.md      hand-written guides (booking, passes, classes, tips)
  data/operators.json      one chunk per operator (booking quirks, pass validity)

Documents are embedded into an in-memory ChromaDB collection with the small embedding
model it ships with, built once per process, so retrieval needs no separate service.
If the vector store is unavailable, a keyword-overlap retriever stands in so the app
still answers.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

_DATA = os.path.join(os.path.dirname(__file__), "..", "data")
_KNOWLEDGE_DIR = os.path.join(_DATA, "knowledge")
_OPERATORS_PATH = os.path.join(_DATA, "operators.json")
_COLLECTION_NAME = "nighttrain_knowledge"


def _yes_no(value: Any) -> str:
    return "yes" if value else "no"


def _operator_document(op: dict) -> str:
    """A compact, retrieval-friendly paragraph about one operator."""
    parts = [f"{op.get('canonical_name', op.get('operator_id'))} ({op.get('short_name', '')})."]
    aliases = [a for a in op.get("aliases", []) if a]
    if aliases:
        parts.append("Also known as " + ", ".join(aliases) + ".")
    countries = ", ".join(op.get("countries", []))
    if countries:
        parts.append(f"A {op.get('type', 'rail')} operator based in {op.get('hq_country', '')}, serving {countries}.")
    parts.append(f"Runs night trains: {_yes_no(op.get('runs_night_trains'))}.")
    if "interrail_accepted" in op:
        parts.append(
            f"Interrail and Eurail accepted: {_yes_no(op.get('interrail_accepted'))}, "
            f"seat or berth reservation required: {_yes_no(op.get('interrail_reservation_required'))}."
        )
    if op.get("booking_url"):
        parts.append(f"Book at {op['booking_url']}.")
    for field in ("booking_notes", "notes", "fare_conditions"):
        if op.get(field):
            parts.append(str(op[field]))
    if op.get("gauge"):
        parts.append(f"Track gauge: {op['gauge']}.")
    return " ".join(parts)


def build_documents() -> list[dict]:
    """The full corpus as {id, text, title, source, operator_id, kind} records."""
    docs: list[dict] = []

    for path in sorted(glob.glob(os.path.join(_KNOWLEDGE_DIR, "*.md"))):
        text = open(path, encoding="utf-8").read().strip()
        if not text:
            continue
        first = text.splitlines()[0]
        title = first.lstrip("# ").strip() or os.path.basename(path)
        docs.append({
            "id": f"guide::{os.path.basename(path)}",
            "text": text,
            "title": title,
            "source": os.path.basename(path),
            "operator_id": "",
            "kind": "guide",
        })

    if os.path.exists(_OPERATORS_PATH):
        operators = json.load(open(_OPERATORS_PATH, encoding="utf-8"))
        for op in operators:
            # Keep the corpus focused: include operators that run night trains or
            # carry real curated notes travellers ask about.
            if not (op.get("runs_night_trains") or op.get("booking_notes") or op.get("notes")):
                continue
            docs.append({
                "id": f"op::{op['operator_id']}",
                "text": _operator_document(op),
                "title": op.get("canonical_name", op["operator_id"]),
                "source": "operator registry",
                "operator_id": op["operator_id"],
                "kind": "operator",
            })
    return docs


# --- ChromaDB-backed retriever (preferred) -------------------------------------

_collection = None
_documents: list[dict] = []
_backend = "uninitialised"


def _build_collection():
    global _backend
    import chromadb
    from chromadb.utils import embedding_functions

    client = chromadb.EphemeralClient()
    ef = embedding_functions.DefaultEmbeddingFunction()  # small built-in model, no separate service
    col = client.get_or_create_collection(_COLLECTION_NAME, embedding_function=ef)
    docs = build_documents()
    col.add(
        ids=[d["id"] for d in docs],
        documents=[d["text"] for d in docs],
        metadatas=[{"title": d["title"], "source": d["source"],
                    "operator_id": d["operator_id"], "kind": d["kind"]} for d in docs],
    )
    _backend = "chromadb"
    logger.info("knowledge: built ChromaDB collection with %d documents", len(docs))
    return col, docs


def _ensure_ready() -> None:
    global _collection, _documents, _backend
    if _collection is not None or _backend == "keyword":
        return
    try:
        _collection, _documents = _build_collection()
    except Exception as exc:  # chromadb or model unavailable: degrade gracefully
        logger.warning("knowledge: ChromaDB unavailable (%s); using keyword fallback", exc)
        _documents = build_documents()
        _backend = "keyword"


def _keyword_retrieve(query: str, k: int) -> list[dict]:
    """A simple word-overlap fallback so retrieval works without embeddings."""
    terms = {t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 2}
    scored = []
    for d in _documents:
        words = set(re.findall(r"[a-z0-9]+", d["text"].lower()))
        overlap = len(terms & words)
        if overlap:
            scored.append((overlap, d))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{"text": d["text"], "title": d["title"], "source": d["source"],
             "operator_id": d["operator_id"], "kind": d["kind"], "score": float(s)}
            for s, d in scored[:k]]


def retrieve(query: str, k: int = 4) -> list[dict]:
    """Top-k knowledge chunks for a query, each with its source for citation."""
    _ensure_ready()
    if _backend == "keyword":
        return _keyword_retrieve(query, k)
    res = _collection.query(query_texts=[query], n_results=k)
    out = []
    for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
        out.append({
            "text": doc,
            "title": meta.get("title", ""),
            "source": meta.get("source", ""),
            "operator_id": meta.get("operator_id", ""),
            "kind": meta.get("kind", ""),
            "score": round(1.0 - float(dist), 3),  # cosine similarity, higher is closer
        })
    return out


def corpus_stats() -> dict:
    """Counts for the About tab and the eval report."""
    docs = _documents or build_documents()
    return {
        "documents": len(docs),
        "guides": sum(1 for d in docs if d["kind"] == "guide"),
        "operators": sum(1 for d in docs if d["kind"] == "operator"),
        "backend": _backend,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for q in ["is my interrail pass valid on nightjet",
              "what is the difference between a couchette and a sleeper",
              "how early can I book ÖBB nightjet",
              "can I take my bike on a night train"]:
        hits = retrieve(q, k=2)
        print(f"\nQ: {q}")
        for h in hits:
            print(f"  [{h['score']}] {h['title']} ({h['source']}): {h['text'][:90]}...")
    print("\nstats:", corpus_stats())
