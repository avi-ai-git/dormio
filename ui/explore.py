"""Explore tab: the night-train network as routes or as operators, on one map.

One place to browse the network. A toggle switches the list between the routes and
the operators that run them, and the map reflects whichever you are looking at.
"""
import streamlit as st

from ui.night_trains import render_routes_view
from ui.operator_directory import render_operators_view


def render_explore():
    st.subheader("Explore the night-train network")
    view = st.radio("View", ["Night Train Routes", "Night Train Operators"], horizontal=True,
                    label_visibility="collapsed", key="explore_view")
    if view == "Night Train Operators":
        render_operators_view()
    else:
        render_routes_view()
