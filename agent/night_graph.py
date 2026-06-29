"""The night-train map reader for Dormio.

Loads the curated night-train services from data/night_trains.json and treats
them as an undirected graph: nodes are cities, edges are night-train services. A
Wien to Roma night train also means Roma to Wien.

Everything here is deterministic and offline. No live router, so no buses, no
morning-first surprises, and an honest "no night train" when there is none.

Queries:
- direct(a, b)      one night train connecting a and b
- chain(a, b)       a -> x -> b with one change between two night trains
- from_city(a)      every night train leaving a
- all_services()    the whole map, for the Night Train Explorer
"""
from __future__ import annotations

import heapq
import json
import os
import unicodedata
from collections import defaultdict

_DATA = os.path.join(os.path.dirname(__file__), "..", "data")
_PATH = os.path.join(_DATA, "night_trains.json")
_COORDS_PATH = os.path.join(_DATA, "stop_coords.json")

with open(_PATH, encoding="utf-8") as _fh:
    _SERVICES = json.load(_fh)

# Folded city / station name -> [lat, lon], cached at ingestion so the app never
# needs the 11 MB source stop table to draw a route on the map.
try:
    with open(_COORDS_PATH, encoding="utf-8") as _fh:
        _COORDS: dict[str, list[float]] = json.load(_fh)
except FileNotFoundError:
    _COORDS = {}

# Each operator's own booking site, so a "Book PKP Intercity" button links to
# intercity.pl and not the route's source, which on a joint train can be the other
# operator's site. The night-train booking page wins where it differs from the corporate one.
_OPERATORS_PATH = os.path.join(_DATA, "operators.json")
_BOOKING_OVERRIDES = {"oebb": "https://www.nightjet.com"}
try:
    with open(_OPERATORS_PATH, encoding="utf-8") as _fh:
        _OP_BOOKING = {o["operator_id"]: _BOOKING_OVERRIDES.get(o["operator_id"], o.get("booking_url", ""))
                       for o in json.load(_fh)}
except FileNotFoundError:
    _OP_BOOKING = {}


def operator_booking_url(operator_id: str) -> str:
    """The operator's own booking site, so the link matches the button label."""
    return _OP_BOOKING.get(operator_id, "")


def _fold(text: str) -> str:
    """Lowercase, strip diacritics and surrounding noise, so spellings match."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower().strip()


# English exonym (folded) -> the local city as used in the data (folded).
CITY_ALIASES = {
    "vienna": "wien", "prague": "praha", "rome": "roma", "munich": "munchen",
    "muenchen": "munchen", "cologne": "koln", "koeln": "koln", "brussels": "bruxelles",
    "warsaw": "warszawa", "bucharest": "bucuresti", "belgrade": "beograd",
    "copenhagen": "kobenhavn", "gothenburg": "goteborg", "geneva": "geneve",
    "milan": "milano", "florence": "firenze", "venice": "venezia", "turin": "torino",
    "antwerp": "antwerpen",
}

# Local city (folded) -> friendly English display name.
_DISPLAY = {
    "wien": "Vienna", "praha": "Prague", "roma": "Rome", "munchen": "Munich",
    "koln": "Cologne", "bruxelles": "Brussels", "warszawa": "Warsaw",
    "bucuresti": "Bucharest", "beograd": "Belgrade", "kobenhavn": "Copenhagen",
    "goteborg": "Gothenburg", "geneve": "Geneva", "milano": "Milan",
    "firenze": "Florence", "venezia": "Venice", "torino": "Turin",
    "antwerpen": "Antwerp",
}


def display_city(city: str) -> str:
    """Friendly display name, English exonym where there is one."""
    return _DISPLAY.get(_fold(city), city)


def stops(svc: dict) -> list:
    """Every boarding point of a service, in order: from, via..., to."""
    return [svc["from_city"]] + list(svc.get("via", [])) + [svc["to_city"]]


# Build the graph once. Every stop on a service is a node, so you can board at a
# via city (Amsterdam on the Brussels to Prague sleeper, for example), not only
# at the endpoints.
_NODES: dict[str, str] = {}                 # folded key -> display name
_ADJ: dict[str, list] = defaultdict(list)   # folded key -> services touching it

for _svc in _SERVICES:
    for _stop in stops(_svc):
        _k = _fold(_stop)
        _NODES.setdefault(_k, display_city(_stop))
        if _svc not in _ADJ[_k]:
            _ADJ[_k].append(_svc)


def resolve(city: str) -> str | None:
    """Folded node key for a typed city, via exonyms, or None if not on the map."""
    key = _fold(city)
    key = CITY_ALIASES.get(key, key)
    if key in _NODES:
        return key
    # Last resort: a unique prefix match, so "Krak" finds Krakow.
    matches = [k for k in _NODES if k.startswith(key)] if key else []
    return matches[0] if len(matches) == 1 else None


def _other(svc: dict, key: str) -> str:
    """The far endpoint of a service relative to `key`, as a display name."""
    if _fold(svc["to_city"]) != key:
        return display_city(svc["to_city"])
    return display_city(svc["from_city"])


def is_on_map(city: str) -> bool:
    return resolve(city) is not None


def direct(a: str, b: str) -> list:
    """Night trains that directly connect a and b, either direction."""
    ka, kb = resolve(a), resolve(b)
    if not ka or not kb:
        return []
    out = []
    for svc in _ADJ.get(ka, []):
        keys = {_fold(s) for s in stops(svc)}
        if ka in keys and kb in keys and svc not in out:
            out.append(svc)
    return out


def chain(a: str, b: str, limit: int = 4) -> list:
    """One-change night-train journeys: a -> x -> b on two night trains."""
    ka, kb = resolve(a), resolve(b)
    if not ka or not kb or ka == kb:
        return []
    direct_ids = {s["id"] for s in direct(a, b)}
    out, seen = [], set()
    for s1 in _ADJ.get(ka, []):
        if s1["id"] in direct_ids:
            continue
        x = _fold(_other_key(s1, ka))
        if x in (ka, kb):
            continue
        for s2 in _ADJ.get(x, []):
            if s2 is s1:
                continue
            keys2 = {_fold(s) for s in stops(s2)}
            if kb in keys2:
                key = (x, s1["id"], s2["id"])
                if key in seen:
                    continue
                seen.add(key)
                out.append({"via": _NODES[x], "leg1": s1, "leg2": s2})
                if len(out) >= limit:
                    return out
    return out


def _other_key(svc: dict, key: str) -> str:
    """The far endpoint (raw) of a service relative to `key`."""
    return svc["to_city"] if _fold(svc["to_city"]) != key else svc["from_city"]


def _duration_min(svc: dict) -> int:
    """A service's duration in minutes, 0 when unknown so it does not dominate ranking."""
    parts = (svc.get("duration") or "").split(":")
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except (ValueError, IndexError):
        return 0


def _route_obj(legs: list) -> dict:
    total = sum(_duration_min(leg["service"]) for leg in legs)
    return {"legs": legs, "changes": len(legs) - 1, "duration_min": total,
            "from": legs[0]["board"], "to": legs[-1]["alight"]}


_UNKNOWN_LEG_MIN = 840  # a leg with no duration data is treated as ~14h for ranking


def plan_routes(a: str, b: str, k: int = 3, pref: str = "changes", max_legs: int = 3) -> list:
    """Up to k ranked journeys from a to b, each up to two changes.

    A weighted k-shortest-paths search over the network. Cities are nodes, a leg rides
    one service between two of its stops, and the weight is the leg's travel time. A
    best-first search finds the quickest journeys, then a cap keeps only the sensible
    ones (within twice the best, or twelve hours longer), so a real Berlin to Munich to
    Vienna to Bucharest survives but a forty-hour detour is dropped. Deterministic, no
    model. One note, a leg uses the whole service duration, since the open data only has
    endpoint times, which slightly overcounts a partial leg and usefully penalises odd
    detours. The next step is per-stop times, not yet in the cleaned data.
    """
    ka, kb = resolve(a), resolve(b)
    if not ka or not kb or ka == kb:
        return []

    endpoints = {ka.split()[0], kb.split()[0]}  # block transfers at another station of A or B
    found, seen = [], set()
    heap = [(0, 0, ka, [], frozenset([ka]))]  # (rank_min, counter, city, legs, visited)
    counter, budget = 1, 0
    while heap and len(found) < 30 and budget < 15000:
        budget += 1
        rank_min, _, cur, legs, visited = heapq.heappop(heap)
        if len(legs) >= max_legs:
            continue
        last_id = legs[-1]["service"]["id"] if legs else None
        for svc in _ADJ.get(cur, []):
            if svc["id"] == last_id:
                continue
            keys = {_fold(s) for s in stops(svc)}
            if cur not in keys:
                continue
            leg_min = _duration_min(svc) or _UNKNOWN_LEG_MIN
            for sk in keys:
                if sk == cur or sk in visited:
                    continue
                if sk != kb and sk.split()[0] in endpoints:
                    continue  # do not change trains at another station of the origin or destination
                new_legs = legs + [{"service": svc, "board": _NODES[cur], "alight": _NODES[sk]}]
                if sk == kb:
                    sig = tuple((_fold(l["board"]), _fold(l["alight"])) for l in new_legs)
                    if sig not in seen:
                        seen.add(sig)
                        found.append((rank_min + leg_min, new_legs))
                else:
                    heapq.heappush(heap, (rank_min + leg_min, counter, sk, new_legs, visited | {sk}))
                    counter += 1

    if not found:
        return []
    best = min(rm for rm, _ in found)
    cap = min(best * 2 + 120, best + 720)
    by_path = {}  # one route per distinct city path, keep the quickest
    for rank_min, legs in found:
        if rank_min > cap:
            continue
        sig = tuple((_fold(l["board"]), _fold(l["alight"])) for l in legs)
        if sig not in by_path or rank_min < by_path[sig][0]:
            by_path[sig] = (rank_min, legs)

    routes = []
    for rank_min, legs in by_path.values():
        obj = _route_obj(legs)
        obj["_rank"] = rank_min
        routes.append(obj)
    if pref == "time":
        routes.sort(key=lambda r: (r["_rank"], r["changes"]))
    else:
        routes.sort(key=lambda r: (r["changes"], r["_rank"]))
    for r in routes:
        r.pop("_rank", None)
    return routes[:k]


def from_city(a: str) -> list:
    """Every night train touching a, as {service, destination} sorted by destination."""
    ka = resolve(a)
    if not ka:
        return []
    out, seen = [], set()
    for svc in _ADJ.get(ka, []):
        dest = _other(svc, ka)
        key = (dest, svc["operator_id"])
        if key in seen:
            continue
        seen.add(key)
        out.append({"service": svc, "destination": dest})
    return sorted(out, key=lambda r: r["destination"].lower())


def all_services() -> list:
    """The whole map, for the Explorer."""
    return list(_SERVICES)


def route_geometry(svc: dict) -> list[dict]:
    """Ordered stops of a service as {name, lat, lon}, for drawing it on the map.

    Prefers the coordinates baked into the service at ingestion; falls back to the
    coordinate cache by folded name so a service still maps if its stops are sparse.
    """
    points = []
    for entry in svc.get("stops", []):
        if isinstance(entry, (list, tuple)) and len(entry) == 3:
            name, lat, lon = entry
            points.append({"name": name, "lat": lat, "lon": lon})
    if points:
        return points
    for city in [svc.get("from_city", ""), *svc.get("via", []), svc.get("to_city", "")]:
        c = city_coord(city)
        if c:
            points.append({"name": city, "lat": c[0], "lon": c[1]})
    return points


def city_coord(city: str) -> list[float] | None:
    """[lat, lon] for a city name, via the cached coordinates and exonym folding."""
    key = _fold(city)
    return _COORDS.get(key) or _COORDS.get(CITY_ALIASES.get(key, key))


def service_endpoints(svc: dict) -> tuple:
    """[lat, lon] for the first and last stop of a service.

    Tries the city name first, then the coordinates baked into the service at
    ingestion. The fallback matters for places the name lookup misses, such as
    the Ukrainian network, so every service can still be drawn on the map.
    """
    stops = svc.get("stops") or []

    def resolve(city: str, baked):
        c = city_coord(city)
        if c:
            return c
        if isinstance(baked, (list, tuple)) and len(baked) == 3:
            return [baked[1], baked[2]]
        return None

    first = stops[0] if stops else None
    last = stops[-1] if stops else None
    return resolve(svc.get("from_city", ""), first), resolve(svc.get("to_city", ""), last)


def night_countries() -> list:
    """Country codes that actually have at least one night train."""
    return sorted({c for s in _SERVICES for c in s.get("countries", [])})


def operators() -> list:
    """Operator display names present on the map, sorted."""
    return sorted({s["operator"] for s in _SERVICES})


COUNTRY_NAMES = {
    "AT": "Austria", "BE": "Belgium", "BG": "Bulgaria", "CH": "Switzerland",
    "CZ": "Czechia", "DE": "Germany", "DK": "Denmark", "ES": "Spain",
    "FI": "Finland", "FR": "France", "GB": "United Kingdom", "HR": "Croatia",
    "HU": "Hungary", "IT": "Italy", "LI": "Liechtenstein", "MD": "Moldova",
    "ME": "Montenegro", "NL": "Netherlands", "NO": "Norway", "PL": "Poland",
    "RO": "Romania", "RS": "Serbia", "SE": "Sweden", "SI": "Slovenia",
    "SK": "Slovakia", "TR": "Türkiye", "UA": "Ukraine",
}


def country_names(codes) -> list:
    """Map country codes to friendly names."""
    return [COUNTRY_NAMES.get(c, c) for c in (codes or [])]


# Spoken or written forms that are not the exact name in COUNTRY_NAMES, so a traveller
# can say UK or Holland and still land on the right country.
_COUNTRY_ALIASES = {
    "uk": "GB", "britain": "GB", "great britain": "GB", "england": "GB",
    "turkey": "TR", "czech republic": "CZ", "czech": "CZ", "holland": "NL",
}
# Folded country name, ISO code, or alias -> ISO code, so "Poland", "poland", and "PL"
# all resolve to the same place.
_COUNTRY_KEYS: dict[str, str] = {_fold(name): code for code, name in COUNTRY_NAMES.items()}
_COUNTRY_KEYS.update({_fold(code): code for code in COUNTRY_NAMES})
_COUNTRY_KEYS.update({_fold(alias): code for alias, code in _COUNTRY_ALIASES.items()})


def resolve_country(name: str) -> str | None:
    """ISO code for a country named in free text, or None when it is not one we know.

    The country-level twin of resolve() for cities. Folds case and diacritics and
    accepts the name, the ISO code, or a common alias, so "Poland", "poland", and "PL"
    all give "PL".
    """
    return _COUNTRY_KEYS.get(_fold(name))


def routes_in_country(code: str) -> list:
    """Every night-train service that runs in or through a country, by ISO code.

    Reads the same countries field the Night Map filters on (ui/night_trains.py), so the
    chat and the map always agree on the set. Sorted by origin then destination for a
    stable, readable order.
    """
    if not code:
        return []
    hits = [s for s in _SERVICES if code in s.get("countries", [])]
    return sorted(hits, key=lambda s: (display_city(s["from_city"]).lower(),
                                       display_city(s["to_city"]).lower()))


if __name__ == "__main__":
    print("services:", len(_SERVICES), "| nodes:", len(_NODES))
    print("Vienna to Rome direct:", [s["operator"] for s in direct("Vienna", "Rome")])
    print("Krakow from-only:", [(r["destination"], r["service"]["operator"]) for r in from_city("Krakow")])
    print("Gdynia to Vienna chain:", [(c["via"], c["leg1"]["operator"], c["leg2"]["operator"]) for c in chain("Gdynia", "Vienna")])
    print("Berlin to Rome chain:", [(c["via"]) for c in chain("Berlin", "Rome")])
    assert direct("Vienna", "Rome"), "expected a direct Vienna-Rome nightjet"
    assert from_city("Krakow"), "expected night trains from Krakow"
    print("night_graph self-test passed")
