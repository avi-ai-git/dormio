"""Night Train Explorer tab: the whole night-train network on a map, then the routes as cards."""
import logging
import math

import streamlit as st

from agent import night_graph
from ui.map_view import render_overview_map

logger = logging.getLogger(__name__)

_STATUS_BADGE = {
    "active": ":green[Active]",
    "seasonal": ":orange[Seasonal]",
    "announced": ":blue[Announced]",
}
_AMENITY_LABELS = [
    ("bikes", "🚲 Bikes"),
    ("catering", "🍽️ Catering"),
    ("wheelchair", "♿ Step-free"),
    ("car_transport", "🚗 Car transport"),
]


@st.cache_data(show_spinner=False)
def _services():
    """The night-train map, cached so it is read once per session."""
    return night_graph.all_services()


def _classes(svc: dict) -> str:
    return " · ".join(c.capitalize() for c in svc.get("classes", []))


def _times(svc: dict) -> str:
    depart, arrive, duration = svc.get("depart"), svc.get("arrive"), svc.get("duration")
    if depart and arrive:
        line = f"{depart} → {arrive}"
        return f"{line} ({duration}h)" if duration else line
    return f"Departs {depart}" if depart else ""


def _amenities(svc: dict) -> str:
    am = svc.get("amenities", {})
    return "  ".join(label for key, label in _AMENITY_LABELS if am.get(key))


@st.cache_data(show_spinner=False)
def _co2_rate() -> float:
    """Median kg of CO2 per km, learned from the routes that report both numbers.

    Used to fill in the CO2 for routes the source data leaves blank, so the figure
    is consistent and always marked as an estimate.
    """
    both = [(s["emissions_kg"], s["distance_km"]) for s in night_graph.all_services()
            if s.get("emissions_kg") and s.get("distance_km")]
    rates = sorted(e / d for e, d in both if d)
    return rates[len(rates) // 2] if rates else 0.019


def _haversine(a: list, b: list) -> float:
    """Great-circle km between two [lat, lon] points."""
    r = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _route_co2(svc: dict):
    """(kg, is_estimate) for a service, or None if there is nothing to go on."""
    if svc.get("emissions_kg"):
        return round(svc["emissions_kg"]), False
    dist = svc.get("distance_km")
    if not dist:
        a, b = night_graph.service_endpoints(svc)
        if a and b:
            dist = _haversine(a, b) * 1.2  # rail follows the land, not the straight line
    if dist:
        return round(dist * _co2_rate()), True
    return None


def _route_card(svc: dict):
    frm = night_graph.display_city(svc["from_city"])
    to = night_graph.display_city(svc["to_city"])
    badge = _STATUS_BADGE.get(svc.get("status", "active"), "")
    with st.container(border=True):
        st.markdown(f"**🌙 {frm} → {to}**  {badge}")
        line = svc["operator"]
        if svc.get("name"):
            line += f"  ·  {svc['name']}"
        st.caption(line)
        if svc.get("classes"):
            st.caption(f"Sleeping options: {_classes(svc)}")
        times = _times(svc)
        if times:
            st.caption(f"🕑 {times}")
        if svc.get("frequency"):
            st.caption(f"Runs: {svc['frequency']}")
        if svc.get("via"):
            via = [night_graph.display_city(v) for v in svc["via"]]
            shown = ", ".join(via[:5])
            more = f", and {len(via) - 5} more" if len(via) > 5 else ""
            st.caption(f"Via {shown}{more}")
        if svc.get("countries"):
            st.caption(f"Passes through: {', '.join(night_graph.country_names(svc['countries']))}")
        amenities = _amenities(svc)
        if amenities:
            st.caption(amenities)
        co2 = _route_co2(svc)
        if co2:
            kg, est = co2
            st.caption(f"🌱 About {kg} kg CO2 for the whole route{' (estimated)' if est else ''}")
        if svc.get("booking_url"):
            st.link_button(f"Book on {svc['operator']}", svc["booking_url"])


def _duration_minutes(svc: dict) -> int:
    parts = (svc.get("duration") or "").split(":")
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except (ValueError, IndexError):
        return 10 ** 6  # unknown durations sort last


_UNKNOWN = 10 ** 6

# Sorts only. No hard duration or time-of-day filter, because a cap can hide every
# route for a country at once and read like missing data. Unknown values always
# sort last, so a route with a missing time never jumps the queue.
_SORTS = {
    "Duration, shortest first": lambda s: (_duration_minutes(s),),
    "Duration, longest first": lambda s: (_duration_minutes(s) == _UNKNOWN, -_duration_minutes(s)),
    "Departure time": lambda s: (not s.get("depart"), s.get("depart") or ""),
    "Arrival time": lambda s: (not s.get("arrive"), s.get("arrive") or ""),
}


def render_routes_view():
    st.caption(
        "Every night train in Europe on one map. Each arc is a route, from origin to destination. "
        "Pick a country, choose how to sort, and the map and the list move together."
    )

    services = _services()
    name_by_code = {c: night_graph.COUNTRY_NAMES.get(c, c) for c in night_graph.night_countries()}
    code_by_name = {v: k for k, v in name_by_code.items()}

    col1, col2 = st.columns(2)
    with col1:
        sel_countries = st.multiselect("Countries served (pick one or more)", sorted(code_by_name),
                                       key="nt_country", placeholder="All countries")
    with col2:
        sort_by = st.selectbox("Sort by", list(_SORTS), key="nt_sort")

    t1, t2, _spacer = st.columns([1.3, 1.3, 4])
    with t1:
        include_extra = st.toggle("Include seasonal", value=True, key="nt_extra")
    with t2:
        bikes_only = st.toggle("🚲 Carries bikes", value=False, key="nt_bikes")

    sel_codes = [code_by_name[n] for n in sel_countries]

    def _keep(svc):
        if sel_codes and not any(code in svc.get("countries", []) for code in sel_codes):
            return False
        if not include_extra and svc.get("status") != "active":
            return False
        if bikes_only and not svc.get("amenities", {}).get("bikes"):
            return False
        return True

    filtered = sorted([s for s in services if _keep(s)], key=_SORTS[sort_by])

    if not render_overview_map(filtered):
        st.info("No night trains match these filters. Try another country, or turn seasonal back on.")
        return
    st.caption(
        f"Showing {len(filtered)} of {len(services)} night-train routes. Hover a city dot for its name, "
        "scroll or use plus and minus to zoom, and the expand icon for full screen."
    )

    cols = st.columns(2)
    for idx, svc in enumerate(filtered):
        with cols[idx % 2]:
            _route_card(svc)


if __name__ == "__main__":
    render_routes_view  # referenced so linters keep the public name
    print("ui/night_trains.py imports cleanly")
