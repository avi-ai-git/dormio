"""Tests for the agent: the router's intent classification and the grounded answer.

Offline and deterministic: in TEST_MODE the router falls back to the heuristic and
the synthesis falls back to the tool facts, so no model is needed."""
import os

os.environ.setdefault("TEST_MODE", "true")

import pytest

from agent import agent

# Representative messages and the tool the router should pick.
ROUTING_CASES = [
    ("Vienna to Rome", "route"),
    ("night trains from Krakow", "route"),
    ("Amsterdam to Prague by sleeper", "route"),
    ("is my interrail pass valid on nightjet", "knowledge"),
    ("what is the difference between a couchette and a sleeper", "knowledge"),
    ("can I take my bike on a night train", "knowledge"),
    ("how do I get from Gdynia to Vienna and can I take a bike", "both"),
]


@pytest.mark.parametrize("query,expected_intent", ROUTING_CASES)
def test_router_picks_the_right_tool(query, expected_intent):
    assert agent.classify(query)["intent"] == expected_intent


def test_router_extracts_cities():
    out = agent.classify("how do I get from Gdynia to Vienna")
    assert out["from_city"].lower().startswith("gdynia")
    assert out["to_city"].lower().startswith("vienna")


def test_answer_route_is_grounded_and_has_geometry():
    out = agent.answer_query("Vienna to Rome")
    assert out["intent"] == "route"
    assert out["route_result"]["mode"] == "routes"
    assert "Rome" in out["answer"]
    # The best option is a direct train and its service carries map geometry.
    options = out["route_result"]["options"]
    assert options and options[0]["changes"] == 0
    from agent import night_graph
    geo = night_graph.route_geometry(options[0]["legs"][0]["service"])
    assert len(geo) >= 2


def test_route_offers_ranked_options():
    out = agent.route_lookup("Amsterdam", "Prague")
    assert out["mode"] == "routes"
    # Options are ranked by fewest changes first.
    changes = [o["changes"] for o in out["options"]]
    assert changes == sorted(changes)


def test_answer_knowledge_cites_sources():
    out = agent.answer_query("is my interrail pass valid on a sleeper")
    assert out["intent"] == "knowledge"
    assert out["sources"], "knowledge answer should carry sources"


def test_offmap_is_honest_not_invented():
    out = agent.answer_query("Atlantis to Rome")
    assert out["route_result"]["mode"] == "offmap"
    assert out["route_result"]["options"] == []


def test_chitchat_redirects_to_night_trains():
    out = agent.answer_query("hello there")
    assert out["intent"] == "chitchat"
    assert "night train" in out["answer"].lower()


if __name__ == "__main__":
    import sys
    sys.exit(__import__("pytest").main([__file__, "-q"]))
