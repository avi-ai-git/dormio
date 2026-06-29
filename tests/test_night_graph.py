"""Tests for the night-train graph and the routing tool. Deterministic and offline."""
import os

os.environ.setdefault("TEST_MODE", "true")

from agent import night_graph as ng
from agent.agent import plan_night, route_lookup


def test_direct_vienna_rome():
    res = ng.direct("Vienna", "Rome")
    assert res and any("Nightjet" in s["operator"] for s in res)


def test_exonyms_and_diacritics_resolve_together():
    assert ng.resolve("Vienna") == ng.resolve("Wien")
    assert ng.resolve("Prague") == ng.resolve("Praha")
    assert ng.resolve("Krakow") == ng.resolve("Kraków")
    assert ng.resolve("Munich") == ng.resolve("München")


def test_from_city_krakow_lists_destinations():
    dests = {r["destination"] for r in ng.from_city("Krakow")}
    assert "Prague" in dests and len(dests) >= 3


def test_chain_gdynia_vienna_exists_with_one_change():
    res = ng.chain("Gdynia", "Vienna")
    assert res, "expected a one-change night-train chain from Gdynia to Vienna"
    assert ng.resolve(res[0]["via"]) is not None
    assert res[0]["leg1"]["id"] != res[0]["leg2"]["id"]


def test_via_city_is_boardable():
    assert ng.is_on_map("Amsterdam")
    assert ng.direct("Amsterdam", "Prague")


def test_offmap_city_returns_nothing():
    assert not ng.is_on_map("Atlantis")
    assert ng.direct("Atlantis", "Rome") == []


def test_no_invented_direct_paris_warsaw():
    assert ng.direct("Paris", "Warsaw") == []


def test_map_has_breadth():
    assert len(ng.all_services()) >= 150
    assert "AT" in ng.night_countries() and "IT" in ng.night_countries()


def test_route_geometry_has_coordinates():
    svc = ng.direct("Vienna", "Rome")[0]
    geo = ng.route_geometry(svc)
    assert len(geo) >= 2
    assert all(-90 <= p["lat"] <= 90 and -180 <= p["lon"] <= 180 for p in geo)


def test_city_coord_resolves_via_exonym():
    assert ng.city_coord("Vienna") is not None
    assert ng.city_coord("Atlantis") is None


def test_route_lookup_modes():
    assert route_lookup("Vienna", "Rome")["mode"] == "routes"
    assert route_lookup("Krakow", "")["mode"] == "from"
    assert route_lookup("", "Rome")["mode"] == "to"
    assert route_lookup("Gdynia", "Vienna")["mode"] == "routes"
    assert route_lookup("Atlantis", "Rome")["mode"] == "offmap"
    assert route_lookup("", "")["mode"] == "need_input"
    assert route_lookup("", "", country="PL")["mode"] == "country"
    assert route_lookup("", "", operator="regiojet")["mode"] == "operator"


def test_plan_routes_ranks_and_is_sensible():
    routes = ng.plan_routes("Vienna", "Rome", k=3)
    assert routes and routes[0]["changes"] == 0  # a direct exists and ranks first
    changes = [r["changes"] for r in routes]
    assert changes == sorted(changes)  # fewest changes first
    assert ng.plan_routes("Atlantis", "Rome") == []  # off-map gives nothing


def test_plan_night_summary_is_grounded_text():
    out = plan_night("Vienna", "Rome")
    assert out["result"]["mode"] == "routes"
    assert "Rome" in out["summary"]


def test_resolve_country_by_name_code_and_alias():
    assert ng.resolve_country("Poland") == "PL"
    assert ng.resolve_country("poland") == "PL"
    assert ng.resolve_country("PL") == "PL"
    assert ng.resolve_country("finland") == "FI"
    assert ng.resolve_country("UK") == "GB"
    assert ng.resolve_country("Narnia") is None


def test_routes_in_country_matches_the_map_filter():
    routes = ng.routes_in_country("PL")
    assert routes, "Poland should have night trains in the data"
    assert all("PL" in s.get("countries", []) for s in routes)
    # The chat helper and the Night Map read the same field, so the counts agree.
    same = [s for s in ng.all_services() if "PL" in s.get("countries", [])]
    assert len(routes) == len(same)


def test_resolve_operator_by_name_and_alias():
    assert ng.resolve_operator("RegioJet") == "regiojet"
    assert ng.resolve_operator("regiojet") == "regiojet"
    assert ng.resolve_operator("RJ") == "regiojet"
    assert ng.resolve_operator("MÁV-START") == "mav_start"
    assert ng.resolve_operator("Nonesuch Rail") is None


def test_routes_by_operator_lists_real_services():
    routes = ng.routes_by_operator("regiojet")
    assert routes, "RegioJet runs night trains in the data"
    assert all(s.get("operator_id") == "regiojet"
               or any("regio" in str(o).lower() for o in s.get("operators", [])) for s in routes)
    # The Przemysl to Prague night train is a RegioJet service, and it touches Poland.
    pairs = {(s["from_city"], s["to_city"]) for s in routes}
    assert any(a.startswith("Przemy") and b in ("Praha", "Prague") for a, b in pairs)


if __name__ == "__main__":
    import sys
    sys.exit(__import__("pytest").main([__file__, "-q"]))
