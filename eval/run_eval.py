"""Evaluate Dormio against a golden set.

Three metrics, each tied to a part of the system:

  routing accuracy   the router sends each query to the right tool (route, knowledge,
                     both, or chitchat)
  route correctness  the graph returns the correct kind of result (direct, chain,
                     from, none, offmap) for a routing query
  retrieval hit-rate the RAG layer retrieves the right guide for a knowledge query

With --judge it also scores groundedness: an LLM judge checks that each final answer
is supported by the facts the tools returned, the key safety property of the design.

Usage:
  python eval/run_eval.py            # uses the live router if API keys are set
  python eval/run_eval.py --offline  # forces the deterministic heuristic router
  python eval/run_eval.py --judge    # also score answer groundedness (uses the model)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))


def _pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.1f}%)" if d else "n/a"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="force the heuristic router")
    ap.add_argument("--judge", action="store_true", help="also score answer groundedness")
    ap.add_argument("--model", default=None, help="model key for router and judge")
    args = ap.parse_args()

    if args.offline:
        os.environ["TEST_MODE"] = "true"

    from agent import agent, knowledge

    cases = json.load(open(os.path.join(HERE, "golden.json"), encoding="utf-8"))["cases"]

    routing_ok = routing_total = 0
    route_ok = route_total = 0
    retrieval_ok = retrieval_total = 0
    misses: list[str] = []

    for c in cases:
        query, want_intent = c["query"], c["intent"]
        cls = agent.classify(query, model_key=args.model)
        routing_total += 1
        if cls["intent"] == want_intent:
            routing_ok += 1
        else:
            misses.append(f'routing: "{query}" expected {want_intent}, got {cls["intent"]}')

        if "mode" in c:
            route_total += 1
            res = agent.route_lookup(cls.get("from_city", ""), cls.get("to_city", ""),
                                     country=cls.get("country", ""), operator=cls.get("operator", ""))
            if res.get("mode") == c["mode"]:
                route_ok += 1
            else:
                misses.append(f'route: "{query}" expected {c["mode"]}, got {res.get("mode")}')

        if "sources" in c:
            retrieval_total += 1
            hits = knowledge.retrieve(query, k=4)
            got = {h["source"] for h in hits}
            if any(s in got for s in c["sources"]):
                retrieval_ok += 1
            else:
                misses.append(f'retrieval: "{query}" expected one of {c["sources"]}, got {sorted(got)}')

    stats = knowledge.corpus_stats()
    router_mode = "heuristic (offline)" if args.offline else f"live model ({args.model or 'default'})"
    print("\nDormio, evaluation")
    print("=" * 44)
    print(f"Router:            {router_mode}")
    print(f"Knowledge backend: {stats['backend']}, {stats['documents']} documents")
    print("-" * 44)
    print(f"Routing accuracy:   {_pct(routing_ok, routing_total)}")
    print(f"Route correctness:  {_pct(route_ok, route_total)}")
    print(f"Retrieval hit-rate: {_pct(retrieval_ok, retrieval_total)}")

    if args.judge:
        score, judged = _groundedness(cases, args.model)
        print(f"Groundedness:       {score:.2f}/5 over {judged} answers")

    if misses:
        print("-" * 44)
        print("Misses:")
        for m in misses:
            print(f"  - {m}")
    print()


def _groundedness(cases: list, model_key) -> tuple[float, int]:
    """LLM-judge each answer for support by the tool facts. Returns (avg, count)."""
    from agent import agent
    from agent.agent import _get_llm, _knowledge_facts, _route_facts

    llm = _get_llm(model_key)
    if llm is None:
        return 0.0, 0
    from langchain_core.messages import HumanMessage

    total, n = 0.0, 0
    for c in cases:
        if c["intent"] == "chitchat":
            continue
        out = agent.answer_query(c["query"], model_key=model_key)
        facts = _route_facts(out.get("route_result", {})) + "\n" + _knowledge_facts(out.get("knowledge", []))
        prompt = (
            "Score from 1 to 5 how fully the answer is supported by the facts, where 5 means every "
            "claim is in the facts and nothing is invented, and 1 means it invents trains, times, or "
            "prices. Reply with only the number.\n\n"
            f"Facts:\n{facts}\n\nAnswer:\n{out['answer']}"
        )
        try:
            raw = (llm.invoke([HumanMessage(content=prompt)]).content or "").strip()
            total += float(next(ch for ch in raw if ch in "12345"))
            n += 1
        except (StopIteration, ValueError):
            continue
    return (total / n if n else 0.0), n


if __name__ == "__main__":
    main()
