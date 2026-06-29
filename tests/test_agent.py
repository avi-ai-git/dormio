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
    ("what night trains run in Poland", "route"),
    ("night trains in Finland", "route"),
    ("routes on RegioJet", "route"),
    ("what trains does PKP Intercity run", "route"),
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


def test_classify_extracts_country():
    out = agent.classify("what night trains run in Poland")
    assert out["intent"] == "route"
    assert out["country"] == "PL"


def test_country_answer_lists_real_routes_not_a_hedge():
    out = agent.answer_query("night trains in Poland")
    assert out["route_result"]["mode"] == "country"
    assert out["route_result"]["country_routes"], "Poland should list real routes"
    answer = out["answer"].lower()
    assert "poland" in answer
    # The old behaviour wrongly claimed Poland was not mapped. Guard against the hedge.
    assert "not mapped" not in answer
    assert "not covered" not in answer
    assert "isn't covered" not in answer


def test_classify_extracts_operator():
    out = agent.classify("routes on RegioJet")
    assert out["intent"] == "route"
    assert out["operator"] == "regiojet"


def test_operator_answer_lists_real_routes_not_a_hallucination():
    out = agent.answer_query("which trains does RegioJet run")
    assert out["route_result"]["mode"] == "operator"
    assert out["route_result"]["operator_routes"], "RegioJet runs real night trains"
    answer = out["answer"].lower()
    assert "regiojet" in answer
    # The live app once invented that RegioJet was a daytime coach, not a night train
    # operator. Guard against that hallucination.
    assert "coach" not in answer
    assert "not a night train" not in answer


if __name__ == "__main__":
    import sys
    sys.exit(__import__("pytest").main([__file__, "-q"]))
