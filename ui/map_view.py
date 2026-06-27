"""The network map: night-train routes drawn as arcs on a real map of Europe.

Built with deck.gl through pydeck, from the endpoint coordinates baked into each
service at ingestion. Each route is one curved arc from origin to destination, so a
dense region stays readable. The basemap is a token-free Carto dark style, so it
works anywhere without a Mapbox key. Used by the Night Train Explorer.
"""
from __future__ import annotations

import math

import streamlit as st

from agent import night_graph

_ARC_FROM = [56, 135, 240]
_ARC_TO = [129, 199, 255]
_CARTO_DARK = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json"


# Keep the map on Europe. You can scroll out a little, but not to the whole globe.
_MIN_ZOOM = 3.0
_MAX_ZOOM = 9.0


def _view_state(coords: list):
    import pydeck as pdk
    if not coords:
        return pdk.ViewState(latitude=49.5, longitude=13.0, zoom=4.0,
                             min_zoom=_MIN_ZOOM, max_zoom=_MAX_ZOOM)
    lats = [c[1] for c in coords]
    lons = [c[0] for c in coords]
    clat = (min(lats) + max(lats)) / 2
    clon = (min(lons) + max(lons)) / 2
    span = max(max(lats) - min(lats), max(lons) - min(lons), 1.0)
    zoom = max(_MIN_ZOOM, min(6.5, 7.8 - math.log2(span)))
    # For a wide spread (the whole network or a big slice) frame Europe rather than
    # the globe: hold a sensible floor and keep the centre on the continent even when
    # a route reaches Turkey or Ukraine.
    if len(coords) > 12:
        zoom = max(3.9, zoom)
        clat = min(56.0, max(45.0, clat))
        clon = min(22.0, max(4.0, clon))
    return pdk.ViewState(latitude=clat, longitude=clon, zoom=zoom,
                         min_zoom=_MIN_ZOOM, max_zoom=_MAX_ZOOM)


def render_overview_map(services: list, height: int = 540) -> bool:
    """Draw the given routes as arcs, with named city points. Returns True if drawn."""
    try:
        import pydeck as pdk
    except Exception:
        return False

    arcs, coords, node_names = [], [], {}
    for svc in services:
        a, b = night_graph.service_endpoints(svc)  # [lat, lon], with a baked-coord fallback
        if a and b:
            source, target = [a[1], a[0]], [b[1], b[0]]  # deck.gl wants [lon, lat]
            arcs.append({"source": source, "target": target,
                         "name": f"{night_graph.display_city(svc.get('from_city',''))} to "
                                 f"{night_graph.display_city(svc.get('to_city',''))}"})
            coords += [source, target]
            node_names[tuple(source)] = night_graph.display_city(svc.get("from_city", ""))
            node_names[tuple(target)] = night_graph.display_city(svc.get("to_city", ""))
    if not arcs:
        return False

    # Only the city points are hoverable. The arcs are drawn but not pickable, so the
    # tooltip never flickers between a hundred crossing lines as the mouse moves.
    nodes = [{"lon": k[0], "lat": k[1], "name": name} for k, name in node_names.items()]
    width = 3 if len(arcs) <= 6 else 2
    layers = [
        pdk.Layer("ArcLayer", data=arcs, get_source_position="source",
                  get_target_position="target", get_source_color=_ARC_FROM,
                  get_target_color=_ARC_TO, get_width=width, get_height=0.3,
                  width_min_pixels=2, opacity=0.5, pickable=False),
        pdk.Layer("ScatterplotLayer", data=nodes, get_position=["lon", "lat"],
                  get_fill_color=[255, 255, 255], get_radius=3,
                  radius_min_pixels=3, radius_max_pixels=6, pickable=True, auto_highlight=False),
    ]
    deck = pdk.Deck(layers=layers, initial_view_state=_view_state(coords),
                    map_style=_CARTO_DARK, tooltip={"text": "{name}"})
    st.pydeck_chart(deck, use_container_width=True, height=height)
    return True
