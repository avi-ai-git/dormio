"""Ingest the Back-on-Track Open Night Train Database into Dormio's clean schema.

Source: the public Back-on-Track night-train database (CC-BY-NC-ND 4.0), exported
from Google Sheets as GTFS-adjacent JSON. We read the pre-joined views, resolve
real coordinates for every stop, clean the operator list, and emit three small,
committed data files the app reads at runtime:

  data/night_trains.json   one record per night-train route (205), with the
                           ordered stop list and coordinates baked in for the map
  data/operators.json      the operator registry (curated rich notes preserved,
                           merged with the open-DB night-train agencies)
  data/stop_coords.json    folded city/station name -> [lat, lon], a coordinate
                           cache so re-ingestion does not need the 11 MB stops.json

Run:  python scripts/ingest_open_db.py
The large source files stay outside the repo. Point SRC_DIR at a local checkout of
Back-on-Track-eu/night-train-data (data/latest). The small view files are vendored
into data/source/bot/ so a re-run only needs stops.json for fresh coordinates;
without it, the committed stop_coords.json cache is used.

Attribution: route and operator data (c) Back-on-Track, CC-BY-NC-ND 4.0.
"""
from __future__ import annotations

import json
import os
import shutil
import unicodedata
from datetime import datetime, timezone
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
DATA = os.path.join(APP, "data")
VENDOR = os.path.join(DATA, "source", "bot")

# Source for a rebuild. A local checkout of the Back-on-Track open database when one is
# set or present, otherwise the small view files vendored in the repo, so a fresh clone
# can rebuild the data with no external download.
_LOCAL_SRC = os.environ.get(
    "BOT_SRC_DIR",
    os.path.join(APP, "..", "night-train-data-main", "night-train-data-main", "data", "latest"),
)
SRC_DIR = _LOCAL_SRC if os.path.isdir(_LOCAL_SRC) else VENDOR

# Clean display names for the 30 night-train agencies (brand-aware).
OPERATOR_DISPLAY = {
    "ATC": "Astra Trans Carpatic", "BDŽ": "BDŽ", "ČD": "ČD (České dráhy)",
    "CFM": "CFM (Moldova)", "CFR": "CFR Călători", "CS": "Caledonian Sleeper",
    "ES": "European Sleeper", "FS": "Trenitalia", "GA": "Go-Ahead Nordic",
    "GWR": "Great Western Railway", "HŽPP": "HŽPP (Croatia)", "MÁV": "MÁV-START",
    "MT": "Midnight Trains", "ÖBB": "ÖBB Nightjet", "OTE": "Optima Tours",
    "PKP": "PKP Intercity", "RDC": "RDC / Alpen-Sylt Nachtexpress", "RJ": "RegioJet",
    "SJ": "SJ", "SJN": "SJ Nord", "SNCF": "SNCF Intercités de Nuit",
    "ST": "Snälltåget", "TCDD": "TCDD", "UEX": "Urlaubs-Express",
    "UZ": "Ukrzaliznytsia", "VR": "VR (Finland)", "VY": "Vy",
    "ŽPCG": "ŽPCG (Montenegro)", "ŽS": "Srbija Voz", "ZSSK": "ZSSK",
}

# Curated operator ids that have announced a night-train service but are not yet in
# the timetable, so they are not in the open agency list. Flagged as night-train
# operators so the directory can show them as upcoming.
ANNOUNCED_NIGHT_OPERATORS = {"nox_mobility"}

# Manual corrections over the upstream open data, keyed by route_id. The source
# mislabels the second Stockholm to Berlin night train as RDC; it is Snälltåget.
# A small hand-curated override map. Add a line per confirmed error.
OPERATOR_CORRECTIONS = {
    "78": {"operator": "Snälltåget", "operator_id": "snalltaget", "name": "Snälltåget EN 345 + EN 346"},
}

# Map an open-DB agency_id to a curated operators.json operator_id where one exists,
# so a route links to the rich, hand-written operator notes used by the RAG layer.
AGENCY_TO_OPERATOR = {
    "BDŽ": "bdz", "ČD": "cd", "CFM": "cfm", "CFR": "cfr_calatori",
    "FS": "trenitalia", "HŽPP": "hz", "MÁV": "mav_start", "ÖBB": "oebb",
    "PKP": "pkp_intercity", "RJ": "regiojet", "SJ": "sj", "SNCF": "sncf",
    "ST": "snalltaget", "TCDD": "tcdd", "UZ": "ukrzaliznytsia", "VR": "vr",
    "VY": "vy", "ŽPCG": "zpcg", "ŽS": "srbija_voz", "ZSSK": "zssk",
}


def fold(text: str) -> str:
    """Lowercase and strip diacritics so spellings match across sources."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower().strip()


def load(name: str) -> Any:
    with open(os.path.join(SRC_DIR, name), encoding="utf-8") as fh:
        return json.load(fh)


def split_alt(name: str) -> list[str]:
    """A station like 'Liège Guillemins / Luik Guillemins' yields both spellings."""
    return [p.strip() for p in name.split(" / ") if p.strip()]


def build_coord_index(stops: dict) -> dict[str, list[float]]:
    """Folded station / city / name -> [lat, lon] from the 28k-stop table."""
    coord: dict[str, list[float]] = {}
    for stop in stops.values():
        lat, lon = stop.get("stop_lat"), stop.get("stop_lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue
        for key in (stop.get("stop_id"), stop.get("stop_name"), stop.get("stop_cityname")):
            if key:
                coord.setdefault(fold(key), [round(float(lat), 5), round(float(lon), 5)])
    return coord


def build_station_city(cities: dict) -> dict[str, str]:
    """Folded station id -> clean romanized city name (Wien Meidling -> Wien)."""
    out: dict[str, str] = {}
    for row in cities.values():
        sid = row.get("stop_id")
        city = row.get("stop_cityname_romanized")  # blank means "no real city here"
        if sid and city:
            out[fold(sid)] = city
    return out


def ordered_sequence(route: dict, direction: str) -> list[str]:
    """The full ordered station list for a direction: origin, via..., destination."""
    origin = route.get(f"origin_trip_{direction}", "")
    via = route.get(f"via_{direction}", "")
    dest = route.get(f"destination_trip_{direction}", "")
    parts = [origin] + [p.strip() for p in via.split(" - ")] + [dest]
    seq: list[str] = []
    for p in parts:
        p = p.strip()
        if p and p.lower() != "non-stop" and (not seq or seq[-1] != p):
            seq.append(p)
    return seq


def resolve_coord(station: str, coord: dict[str, list[float]]) -> list[float] | None:
    for cand in split_alt(station):
        hit = coord.get(fold(cand))
        if hit:
            return hit
    return None


# Trailing station words to drop when a station is missing from the city index,
# so 'Koblenz Hbf' shows as 'Koblenz'. Conservative on purpose.
_SUFFIXES = (" hauptbahnhof", " hbf", " centraal", " hlavní nádraží", " hlavni nadrazi",
             " główny", " glowny", " centrale", " termini")


def clean_city(station: str, station_city: dict[str, str]) -> str:
    """Best clean city name for a station: the curated city index, else light strip."""
    name = split_alt(station)[0]
    city = station_city.get(fold(station)) or station_city.get(fold(name))
    if city:
        return city
    low = name.lower()
    for suf in _SUFFIXES:
        if low.endswith(suf):
            return name[: -len(suf)].strip()
    return name.split(" (")[0].strip()


def parse_duration(value: str) -> str:
    """The sheet stores durations on the 1899-12-30 epoch; return H:MM total."""
    if not value or not isinstance(value, str):
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        epoch = datetime(1899, 12, 30, tzinfo=timezone.utc)
        minutes = int(round((dt - epoch).total_seconds() / 60))
        return f"{minutes // 60}:{minutes % 60:02d}"
    except (ValueError, TypeError):
        return ""


def parse_date(value: Any) -> datetime | None:
    if value in ("", None):
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.strptime(str(int(value)), "%Y%m%d")
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def clean_frequency(service_id: str) -> str:
    """'2026: Mon, Wed, Fri' -> 'Mon, Wed, Fri'; keep season hints intact."""
    if not service_id:
        return ""
    label = service_id.split(":", 1)[1].strip() if ":" in service_id else service_id
    return label.strip(" -") or service_id.strip()


def day_flags(detail: dict, direction: str) -> list[int]:
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    out = []
    for d in days:
        v = detail.get(f"{d}_{direction}", 0)
        out.append(1 if v in (1, "1", 1.0) else 0)
    return out


def is_seasonal(detail: dict, frequency: str) -> bool:
    start = parse_date(detail.get("start_date_0"))
    end = parse_date(detail.get("end_date_0"))
    if start and end and 0 < (end - start).days < 330:
        return True
    hint = frequency.lower()
    return any(w in hint for w in ("may", "jun", "jul", "aug", "sep", "oct", "summer", "season"))


def amenity_bool(value: Any) -> bool:
    # The open data uses GTFS-style codes: 1 means yes, 2 means no, 0 or empty means no
    # information. Counting 2 as yes wrongly put car transport on almost every train, so
    # only an explicit yes counts now.
    return str(value).strip().lower() in ("1", "yes", "true", "y")


def build_routes(vmap, vdet, vlist, coord, station_city) -> list[dict]:
    routes = []
    for rid, m in vmap.items():
        d = vdet.get(rid, {})
        li = vlist.get(rid, {})

        seq = ordered_sequence(m, "0")
        if not seq:
            continue  # skip blank separator rows in the source sheet

        stops = []
        for st in seq:
            c = resolve_coord(st, coord)
            if c:
                stops.append([st, c[0], c[1]])

        origin_city = (d.get("origin_city") or clean_city(seq[0], station_city)).strip()
        dest_city = (d.get("destination_city") or clean_city(seq[-1], station_city)).strip()
        if not origin_city or not dest_city:
            continue

        # Intermediate city names for the routing graph (deduped, endpoints removed).
        via_cities: list[str] = []
        ends = {fold(origin_city), fold(dest_city)}
        for st in seq[1:-1]:
            city = clean_city(st, station_city)
            if fold(city) not in ends and (not via_cities or via_cities[-1] != city):
                via_cities.append(city)

        agency_id = m.get("agency_id", "")
        operator_ids = [a for a in (d.get("agency_id_1"), d.get("agency_id_2"), d.get("agency_id_3")) if a]
        operators = [OPERATOR_DISPLAY.get(a, a) for a in (operator_ids or [agency_id])]
        # For a joint service the map encodes a combo like "CFR/MÁV"; link the primary
        # to the first individual agency so it resolves to a curated operator entry.
        primary_agency = operator_ids[0] if operator_ids else agency_id

        frequency = clean_frequency(m.get("service_id_0", ""))
        classes = [c.strip() for c in str(d.get("classes", "")).split(",") if c.strip()]
        countries = [c.strip() for c in str(d.get("countries", "")).split(",") if c.strip()]
        seasonal = is_seasonal(d, frequency)
        corr = OPERATOR_CORRECTIONS.get(str(rid), {})

        # Some source rows carry no real schedule, which shows up as 00:00 to 00:00.
        # Treat that as unknown rather than printing a fake 24 hour journey.
        depart = m.get("origin_departure_time_0", "") or ""
        arrive = m.get("destination_arrival_time_0", "") or ""
        duration = parse_duration(d.get("duration_0", ""))
        if depart in ("", "00:00") and arrive in ("", "00:00"):
            depart = arrive = duration = ""

        routes.append({
            "id": str(rid),
            "name": corr.get("name", li.get("night_train", "").strip()),
            "operator": corr.get("operator", OPERATOR_DISPLAY.get(primary_agency, primary_agency)),
            "operator_id": corr.get("operator_id", AGENCY_TO_OPERATOR.get(primary_agency, fold(primary_agency))),
            "operators": operators,
            "from_city": origin_city,
            "to_city": dest_city,
            "via": via_cities,
            "countries": countries,
            "classes": classes,
            "depart": depart,
            "arrive": arrive,
            "duration": duration,
            "frequency": frequency,
            "days": day_flags(d, "0"),
            "seasonal": seasonal,
            "status": "seasonal" if seasonal else "active",
            "amenities": {
                "bikes": amenity_bool(d.get("bikes_allowed")),
                "catering": amenity_bool(d.get("catering")),
                "wheelchair": amenity_bool(d.get("wheelchair_accessible")),
                "car_transport": amenity_bool(d.get("car_transport")),
                "plugs": amenity_bool(d.get("plugs")),
            },
            "distance_km": d.get("distance") or None,
            "emissions_kg": d.get("emissions") or None,
            "booking_url": (li.get("source") or d.get("source") or "").strip(),
            "picture": (m.get("picture") or "").strip(),
            "connection": (d.get("connection") or "").strip(),
            "stops": stops,
        })
    return routes


def build_operators(agencies: dict) -> list[dict]:
    """Curated rich operators (notes for RAG) merged with open-DB night-train agencies."""
    curated_path = os.path.join(DATA, "operators.json")
    curated = []
    if os.path.exists(curated_path):
        with open(curated_path, encoding="utf-8") as fh:
            curated = json.load(fh)
    by_id = {op["operator_id"]: op for op in curated}

    for aid, a in agencies.items():
        op_id = AGENCY_TO_OPERATOR.get(aid, fold(aid))
        display = OPERATOR_DISPLAY.get(aid, a.get("agency_name", aid))
        entry = by_id.get(op_id)
        if entry:
            entry["runs_night_trains"] = True
            entry.setdefault("logo_url", a.get("agency_logo_url", ""))
            entry.setdefault("booking_url", a.get("agency_url", ""))
            if a.get("agency_conditions_groups"):
                entry["fare_conditions"] = a["agency_conditions_groups"].strip()
        else:
            by_id[op_id] = {
                "operator_id": op_id,
                "canonical_name": display,
                "short_name": aid,
                "aliases": [a.get("agency_name", ""), a.get("agency_name_romanized", "")],
                "type": "state",
                "status": "active",
                "countries": [a.get("agency_state", "")] if a.get("agency_state") else [],
                "hq_country": a.get("agency_state", ""),
                "booking_url": a.get("agency_url", ""),
                "logo_url": a.get("agency_logo_url", ""),
                "runs_night_trains": True,
                "notes": f"{display} runs night trains in the Back-on-Track database.",
            }

    # Mark announced night-train newcomers (not yet in the timetable) as night operators.
    for op_id in ANNOUNCED_NIGHT_OPERATORS:
        if op_id in by_id:
            by_id[op_id]["runs_night_trains"] = True

    return list(by_id.values())


def vendor_sources() -> None:
    """Copy the small view files into the repo so re-ingestion is reproducible."""
    if os.path.abspath(SRC_DIR) == os.path.abspath(VENDOR):
        return  # already reading the vendored copy, nothing to copy onto itself
    os.makedirs(VENDOR, exist_ok=True)
    for name in ("view_ontd_map.json", "view_ontd_details.json", "view_ontd_list.json",
                 "view_ontd_cities.json", "agencies.json", "classes.json"):
        src = os.path.join(SRC_DIR, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(VENDOR, name))


def main() -> None:
    print(f"Reading open database from: {SRC_DIR}")
    vmap, vdet, vlist = load("view_ontd_map.json"), load("view_ontd_details.json"), load("view_ontd_list.json")
    cities, agencies = load("view_ontd_cities.json"), load("agencies.json")

    coords_path = os.path.join(DATA, "stop_coords.json")
    stops_file = os.path.join(SRC_DIR, "stops.json")
    if os.path.exists(stops_file):
        print("Building coordinate index from stops.json ...")
        coord = build_coord_index(load("stops.json"))
    elif os.path.exists(coords_path):
        print("stops.json not found; using cached stop_coords.json")
        with open(coords_path, encoding="utf-8") as fh:
            coord = json.load(fh)
    else:
        raise SystemExit("Need either stops.json (source) or a committed stop_coords.json cache.")

    station_city = build_station_city(cities)
    routes = build_routes(vmap, vdet, vlist, coord, station_city)
    operators = build_operators(agencies)

    # Trim the coordinate cache to names that actually appear in routes.
    used = set()
    for r in routes:
        for name, _lat, _lon in r["stops"]:
            for cand in split_alt(name):
                used.add(fold(cand))
        for city in [r["from_city"], r["to_city"], *r["via"]]:
            used.add(fold(city))
    coord_cache = {k: coord[k] for k in used if k in coord}

    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, "night_trains.json"), "w", encoding="utf-8") as fh:
        json.dump(routes, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(DATA, "operators.json"), "w", encoding="utf-8") as fh:
        json.dump(operators, fh, ensure_ascii=False, indent=2)
    with open(coords_path, "w", encoding="utf-8") as fh:
        json.dump(coord_cache, fh, ensure_ascii=False, indent=2)
    vendor_sources()

    mapped = sum(1 for r in routes if r["stops"])
    seasonal = sum(1 for r in routes if r["seasonal"])
    print(f"Wrote {len(routes)} routes ({mapped} with map geometry, {seasonal} seasonal), "
          f"{len(operators)} operators, {len(coord_cache)} cached coordinates.")


if __name__ == "__main__":
    main()
