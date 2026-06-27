"""Dormio, Streamlit entry point.

A focused night-train assistant for Europe. An agent answers in plain language,
a map shows the network, and a directory lists the operators. This module only
wires the page together; the work lives in the agent and ui modules.
"""
import os
import random
from collections import Counter

import streamlit as st
import streamlit.components.v1 as components

# Bridge Streamlit Cloud secrets into the environment before config reads them.
# Locally there is no secrets file, so this is skipped and .env is used instead.
try:
    for _key, _value in st.secrets.items():
        os.environ.setdefault(_key, str(_value))
except Exception:
    pass

from dotenv import load_dotenv

load_dotenv()

import config
from agent import night_graph
from ui.route_planner import render_route_planner, render_pinned_sidebar
from ui.explore import render_explore
from ui.about import render_about

_LOGO_PATH = os.path.join(os.path.dirname(__file__), "assets", "dormio_logo.svg")

CUSTOM_CSS = """
<style>
.stTabs [data-baseweb="tab"] { font-size: 15px; }
[data-testid="stMetricValue"] { font-size: 24px; }
/* Nudge Streamlit's fullscreen button off the map's zoom controls so they stop overlapping. */
[data-testid="stFullScreenFrame"] button { right: 3rem !important; }
/* On a phone, let filter rows and the two-column card grid stack instead of squeezing. */
@media (max-width: 640px) {
  .stTabs [data-baseweb="tab"] { font-size: 13px; }
  [data-testid="stMetricValue"] { font-size: 20px; }
  [data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
  [data-testid="stHorizontalBlock"] > div { min-width: 100% !important; flex: 1 1 100% !important; }
}
</style>
"""


@st.cache_resource(show_spinner=False)
def _warm_knowledge() -> bool:
    """Build the ChromaDB knowledge collection once per process, then reuse it."""
    from agent import knowledge
    knowledge.retrieve("warm up the knowledge base", k=1)
    return True


@st.cache_data(show_spinner=False)
def _facts() -> list:
    """True one-liners drawn from the live data, plus a little night-train lore."""
    svcs = night_graph.all_services()

    def mins(s):
        parts = (s.get("duration") or "").split(":")
        try:
            return int(parts[0]) * 60 + int(parts[1])
        except (ValueError, IndexError):
            return None

    def city(s, key):
        return night_graph.display_city(s.get(key, ""))

    routes = len(svcs)
    countries = len(night_graph.night_countries())
    operators = len(night_graph.operators())
    bikes = sum(1 for s in svcs if s.get("amenities", {}).get("bikes"))
    seasonal = sum(1 for s in svcs if s.get("status") == "seasonal")
    sleepers = sum(1 for s in svcs if "sleeper" in (s.get("classes") or []))
    crossborder = sum(1 for s in svcs if len(s.get("countries") or []) > 1)
    timed = [(mins(s), s) for s in svcs if mins(s)]

    touch, cities, cc = Counter(), set(), Counter()
    for s in svcs:
        for c in [s.get("from_city", ""), *(s.get("via") or []), s.get("to_city", "")]:
            if c:
                touch[night_graph.display_city(c)] += 1
                cities.add(night_graph.display_city(c))
        for code in s.get("countries") or []:
            cc[code] += 1

    facts = [
        f"Europe runs {routes} night trains across {countries} countries. That is a lot of mornings "
        "waking up somewhere new.",
        f"{operators} operators run the night trains on this map, from national railways to small "
        "newcomers reviving old routes.",
        "A night train is your hotel on wheels. The journey and the bed come in one fare.",
        "Most sleepers leave in the evening and arrive after breakfast, so a travel day becomes a night.",
        "A couchette is a shared berth you can lie flat in. A sleeper is a private cabin, sometimes with "
        "a little sink.",
        "Interrail and Eurail passes cover many night trains, though a sleeper usually needs a "
        "reservation on top.",
    ]
    if timed:
        m, s = max(timed, key=lambda t: t[0])
        facts.append(f"The longest sleeper here runs {city(s,'from_city')} to {city(s,'to_city')}, about "
                     f"{m // 60} hours on the rails. Pack a book.")
        m, s = min(timed, key=lambda t: t[0])
        facts.append(f"The shortest hop with a bed is {city(s,'from_city')} to {city(s,'to_city')}, around "
                     f"{m // 60} hours. Asleep before you know it.")
        overnight = [s for _m, s in timed if (s.get("depart") or "") >= "17:00"]
        if overnight:
            s = random.choice(overnight)
            facts.append(f"You can fall asleep in {city(s,'from_city')} and wake up in {city(s,'to_city')}.")
    if bikes:
        facts.append(f"{bikes} of these night trains will carry your bike, so you can roll straight off "
                     "the platform and into the hills.")
    if sleepers:
        facts.append(f"{sleepers} of these services offer a proper private sleeper cabin, not just a seat.")
    if crossborder:
        facts.append(f"{crossborder} of these trains cross at least one border while you sleep.")
    if cities:
        facts.append(f"You can wake up in more than {len(cities) // 10 * 10} different towns and cities "
                     "without ever boarding a plane.")
    if touch:
        name, n = touch.most_common(1)[0]
        facts.append(f"{name} is the busiest junction on the map, touched by {n} night-train services.")
    if cc:
        code, n = cc.most_common(1)[0]
        facts.append(f"{night_graph.COUNTRY_NAMES.get(code, code)} has the most night trains running "
                     f"through it, {n} of them.")
    green = [s for s in svcs if s.get("emissions_kg") and s.get("distance_km")]
    if green:
        s = max(green, key=lambda x: x["distance_km"])
        facts.append(f"A night train from {city(s,'from_city')} to {city(s,'to_city')} gives off about "
                     f"{round(s['emissions_kg'])} kg of CO2, a small fraction of the same trip by air.")
    if seasonal:
        facts.append(f"{seasonal} of these are seasonal, here for the ski winter or the summer coast and "
                     "gone the rest of the year.")

    # One fact for every operator and every country, so the trivia keeps coming.
    by_op: dict = {}
    for s in svcs:
        if s.get("operator"):
            by_op.setdefault(s["operator"], []).append(s)
    for i, op in enumerate(sorted(by_op)):
        rs = by_op[op]
        longest = max(rs, key=lambda s: mins(s) or 0)
        a, b = city(longest, "from_city"), city(longest, "to_city")
        if len(rs) == 1:
            facts.append(f"{op} runs a single night train on this map, {a} to {b}.")
        elif i % 2:
            facts.append(f"{op} runs {len(rs)} night-train lines, the longest being {a} to {b}.")
        else:
            facts.append(f"{op} keeps {len(rs)} night-train lines running, {a} to {b} among them.")

    for i, (code, n) in enumerate(sorted(cc.items(), key=lambda kv: -kv[1])):
        name = night_graph.COUNTRY_NAMES.get(code, code)
        if n == 1:
            facts.append(f"{name} has a single night train running through it.")
        elif i % 2:
            facts.append(f"You can catch {n} different night trains in {name}.")
        else:
            facts.append(f"{name} has {n} night trains running through it.")
    return facts


def _render_logo() -> None:
    try:
        with open(_LOGO_PATH, encoding="utf-8") as fh:
            components.html(fh.read(), height=150)
    except OSError:
        st.markdown(f"# 🌙 {config.APP_TITLE}")


def render_sidebar() -> None:
    with st.sidebar:
        _render_logo()
        st.divider()

        with st.expander("Change the voice (optional)"):
            st.selectbox(
                "Who writes your answer",
                config.runtime_model_labels(),
                key="model_label",
                help="Any model is fine. The model only puts the found facts into words, so the "
                     "choice changes the voice, not the routes. Three integration patterns are "
                     "here: an aggregator, a direct European API, and an open-weight model.",
            )
        st.divider()

        st.subheader("Coverage")
        st.metric("Night-train routes", len(night_graph.all_services()))
        st.metric("Operators", len(night_graph.operators()))
        st.metric("Countries with night trains", len(night_graph.night_countries()))

        render_pinned_sidebar()

        st.divider()
        facts = _facts()
        if facts:
            if "fact_idx" not in st.session_state:
                st.session_state["fact_idx"] = random.randrange(len(facts))
            st.subheader("💡 Did you know")
            st.caption(facts[st.session_state["fact_idx"] % len(facts)])
            if st.button("💡 Try another", key="another_fact", use_container_width=True):
                nxt = random.randrange(len(facts))
                while len(facts) > 1 and nxt == st.session_state["fact_idx"]:
                    nxt = random.randrange(len(facts))
                st.session_state["fact_idx"] = nxt
                st.rerun()


def main() -> None:
    st.set_page_config(
        page_title=f"{config.APP_TITLE}, European Night Trains",
        page_icon="🌙",
        layout="wide",
        initial_sidebar_state="expanded",
        menu_items={
            "About": f"{config.APP_TITLE}, a European night-train planner by Avishek Chatterjee"
        },
    )
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    _warm_knowledge()

    render_sidebar()

    tab1, tab2, tab3 = st.tabs([
        "Ask Dormio",
        "The Night Map",
        "How It Works",
    ])

    with tab1:
        render_route_planner()
    with tab2:
        render_explore()
    with tab3:
        render_about()


if __name__ == "__main__":
    main()
