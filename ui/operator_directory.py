"""The operators view inside Explore: who runs Europe's night trains, and where.

Browse the operators behind the trains. Filter by the countries a service passes
through, see each operator's lines on the map and as a list, with its booking site
and notes. Kept simple, no operator-type or status jargon.
"""
import json
import os
import re
import unicodedata

import streamlit as st

from agent import night_graph
from ui.map_view import render_overview_map

COUNTRY_NAMES = {
    "AL": "Albania", "AM": "Armenia", "AT": "Austria", "AZ": "Azerbaijan",
    "BA": "Bosnia and Herzegovina", "BE": "Belgium", "BG": "Bulgaria", "BY": "Belarus",
    "CH": "Switzerland", "CZ": "Czechia", "DE": "Germany", "DK": "Denmark",
    "EE": "Estonia", "ES": "Spain", "FI": "Finland", "FR": "France",
    "GB": "United Kingdom", "GE": "Georgia", "GR": "Greece", "HR": "Croatia",
    "HU": "Hungary", "IE": "Ireland", "IT": "Italy", "KZ": "Kazakhstan",
    "LI": "Liechtenstein", "LT": "Lithuania", "LU": "Luxembourg", "LV": "Latvia",
    "MD": "Moldova", "ME": "Montenegro", "MK": "North Macedonia", "NL": "Netherlands",
    "NO": "Norway", "PL": "Poland", "PT": "Portugal", "RO": "Romania", "RS": "Serbia",
    "RU": "Russia", "SE": "Sweden", "SI": "Slovenia", "SK": "Slovakia",
    "TR": "Türkiye", "UA": "Ukraine", "UK": "United Kingdom", "XK": "Kosovo",
}


@st.cache_data(show_spinner=False)
def _load_operators() -> list:
    path = os.path.join(os.path.dirname(__file__), "..", "data", "operators.json")
    with open(path, encoding="utf-8") as fh:
        ops = json.load(fh)
    # Some operators have two profiles, for example European Sleeper, where the one
    # tied to a service lists fewer countries than the fuller profile. Merge by name so
    # the card and the country filter show the operator's real reach.
    by_name: dict = {}
    for op in ops:
        by_name.setdefault(op.get("canonical_name", ""), []).append(op)
    for name, group in by_name.items():
        if not name or len(group) < 2:
            continue
        countries = sorted({c for op in group for c in op.get("countries", [])})
        notes = next((op.get("notes") for op in group if op.get("notes")), "")
        booking = next((op.get("booking_url") for op in group if op.get("booking_url")), "")
        bnotes = next((op.get("booking_notes") for op in group if op.get("booking_notes")), "")
        for op in group:
            op["countries"] = countries
            op["notes"] = op.get("notes") or notes
            op["booking_url"] = op.get("booking_url") or booking
            op["booking_notes"] = op.get("booking_notes") or bnotes
    return ops


@st.cache_data(show_spinner=False)
def _night_ids() -> set:
    return {s["operator_id"] for s in night_graph.all_services()}


@st.cache_data(show_spinner=False)
def _routes_by_operator() -> dict:
    out: dict = {}
    for s in night_graph.all_services():
        out.setdefault(s["operator_id"], []).append(s)
    return out


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower().strip()


def _no_prices(text: str) -> str:
    """Drop specific fares from a note, since prices change and we do not verify them."""
    if not text:
        return text
    text = re.sub(r"(?:\bfrom\s+)?[€£$]\s?\d[\d.,]*(?:\s+(?:advance|onwards?|return|each way))?",
                  "", text, flags=re.I)
    text = re.sub(r"\b\d[\d.,]*\s?(?:euros?|eur|pounds?|gbp|sek|czk|pln|kr)\b", "", text, flags=re.I)
    text = re.sub(r"\bfrom\s*(?=[.,;])", "", text, flags=re.I)  # leftover "from ."
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+([.,;])", r"\1", text)
    text = re.sub(r"([.,;])\s*\1", r"\1", text)
    return text.strip()


def _cname(code: str) -> str:
    return COUNTRY_NAMES.get(code, code)


def _render_card(op: dict, selected_codes: list, routes: list):
    with st.container(border=True):
        upcoming = "  :blue[Upcoming]" if op.get("status") == "announced" else ""
        st.markdown(f"🌙 **{op.get('canonical_name', '')}** ({op.get('short_name', '')}){upcoming}")
        if op.get("hq_country"):
            st.caption(f"Based in {_cname(op['hq_country'])}")
        served = ", ".join(_cname(c) for c in op.get("countries", []))
        if served:
            st.caption(f"Serves: {served}")
        for code in selected_codes:
            if code == op.get("hq_country"):
                st.markdown(f":green[● Based in {_cname(code)}]")
            elif code in op.get("countries", []):
                st.markdown(f":grey[○ Passes through {_cname(code)}]")
        aliases = [a for a in op.get("aliases", []) if a]
        if aliases:
            st.caption(f"Also known as: {', '.join(aliases)}")
        ir = "Interrail accepted" if op.get("interrail_accepted") else "No Interrail"
        res = " (reservation needed)" if op.get("interrail_reservation_required") else ""
        st.caption(f"{ir}{res}")
        if op.get("booking_url"):
            st.link_button("Visit booking site", op["booking_url"])
        with st.expander("Lines and notes"):
            if routes:
                st.markdown("**Night-train lines**")
                st.markdown("\n".join(
                    f"- {night_graph.display_city(r['from_city'])} to {night_graph.display_city(r['to_city'])}"
                    for r in routes[:10]))
            if op.get("booking_notes"):
                st.markdown(f"**Booking**: {_no_prices(op['booking_notes'])}")
            if op.get("notes"):
                st.markdown(f"**Notes**: {_no_prices(op['notes'])}")
            st.caption("Fares are dynamic. Check the operator's site for current prices.")


def render_operators_view():
    st.caption(
        "Who runs Europe's night trains, including newcomers that have announced services. Pick the "
        "countries a train passes through, or pick an operator by name, and the map follows along."
    )

    operators = _load_operators()
    night_ids, routes_by_op = _night_ids(), _routes_by_operator()
    # Only the operators that actually run night trains, and only countries they reach.
    night_ops = sorted((op for op in operators
                        if op["operator_id"] in night_ids or op.get("runs_night_trains")),
                       key=lambda o: o.get("canonical_name", "").lower())
    code_by_name = {_cname(c): c for c in night_graph.night_countries()}
    id_by_name = {op.get("canonical_name", ""): op["operator_id"] for op in night_ops}

    col1, col2 = st.columns(2)
    with col1:
        countries_sel = st.multiselect("Countries the train passes through (pick one or more)",
                                       sorted(code_by_name), key="op_countries",
                                       placeholder="All countries")
    with col2:
        ops_sel = st.multiselect("Or pick an operator", sorted(id_by_name),
                                 key="op_names", placeholder="All operators")

    selected_codes = [code_by_name[n] for n in countries_sel]
    selected_ops = {id_by_name[n] for n in ops_sel}

    def _matches(op: dict) -> bool:
        if selected_codes and not any(code in op.get("countries", []) for code in selected_codes):
            return False
        if selected_ops and op["operator_id"] not in selected_ops:
            return False
        return True

    filtered = [op for op in night_ops if _matches(op)]

    # The map shows the lines of the operators in view, narrowed to the chosen countries
    # so selecting a country actually changes what is drawn.
    shown_ids = {op["operator_id"] for op in filtered}

    def _route_shown(s: dict) -> bool:
        if s["operator_id"] not in shown_ids:
            return False
        if selected_codes and not any(c in s.get("countries", []) for c in selected_codes):
            return False
        return True

    map_routes = [s for s in night_graph.all_services() if _route_shown(s)]
    render_overview_map(map_routes or night_graph.all_services())
    st.caption(f"Showing {len(filtered)} operators. Open one for its lines and booking site.")

    if not filtered:
        st.write("No operators match these filters. Try widening them.")
        return
    cols = st.columns(2)
    for idx, op in enumerate(filtered):
        with cols[idx % 2]:
            _render_card(op, selected_codes, routes_by_op.get(op["operator_id"], []))


if __name__ == "__main__":
    print("ui/operator_directory.py imports cleanly")
