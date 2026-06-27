"""Route Planner tab: a scrolling conversation with the night-train agent.

The input sits at the bottom, the conversation scrolls above it, and the newest reply
is at the bottom, the way a normal chat works. Each line of planning is its own trip
with its own memory. Pin a trip to keep it in the sidebar, or start a new chat to
explore a different idea without mixing them up. The map lives in the Explorer.
"""
import logging
import random
from urllib.parse import urlparse

import streamlit as st

import config
from agent import agent, night_graph, safety

logger = logging.getLogger(__name__)

# The wait is short, so the message may as well have a little character. Picked at random.
_SPINNERS = [
    "Checking the night-train network...",
    "Reading the timetables...",
    "Looking for a bed on rails...",
    "Following the tracks across Europe...",
    "Plotting your night on the rails...",
]

# Four starters that double as test cases, one per capability: a one-change route with
# alternatives, a clean direct, the from-a-city discovery, and an off-map web last mile.
EXAMPLES = [
    "Berlin to Bucharest",
    "Vienna to Rome",
    "Night trains from Prague",
    "Gdynia to Rijeka",
]


def _model_key():
    label = st.session_state.get("model_label")
    return config.model_by_label(label).key if label else None


# --- trips (one conversation thread each) --------------------------------------

def _threads() -> list:
    return st.session_state.setdefault("threads", [])


def _new_thread():
    # Reuse an existing empty trip instead of piling up blank ones.
    for thread in _threads():
        if not thread["chat"]:
            st.session_state["active_id"] = thread["id"]
            return
    st.session_state["thread_counter"] = st.session_state.get("thread_counter", 0) + 1
    tid = f"t{st.session_state['thread_counter']}"
    _threads().append({"id": tid, "title": "New trip", "chat": [], "pinned": False})
    st.session_state["active_id"] = tid


def _active() -> dict:
    if not _threads():
        _new_thread()
    aid = st.session_state.get("active_id")
    for thread in _threads():
        if thread["id"] == aid:
            return thread
    st.session_state["active_id"] = _threads()[0]["id"]
    return _threads()[0]


def _switch(tid: str):
    st.session_state["active_id"] = tid


def _pin():
    _active()["pinned"] = True
    st.toast("Saved to the sidebar. Keep chatting here, or start a new chat for a different trip.",
             icon="📌")


def _queue(query: str):
    st.session_state["pending_query"] = query


def render_pinned_sidebar():
    """List the pinned trips in the sidebar so the traveller can switch back."""
    pinned = [t for t in _threads() if t.get("pinned")]
    if not pinned:
        return
    st.subheader("Pinned trips")
    active = st.session_state.get("active_id")
    for thread in pinned:
        mark = "🌙 " if thread["id"] == active else ""
        st.button(mark + thread["title"], key=f"pin_{thread['id']}",
                  on_click=_switch, args=(thread["id"],), use_container_width=True)


# --- rendering helpers ---------------------------------------------------------

def _booking_links(route_result: dict) -> list:
    """One button per operator, linked to that operator's own booking site."""
    services = []
    for opt in route_result.get("options", []) + route_result.get("options2", []):
        services += [leg["service"] for leg in opt["legs"]]
    for r in route_result.get("from_list", []) + route_result.get("origin_options", []):
        services.append(r["service"])
    seen, links = set(), []
    for svc in services:
        operator = svc["operator"]
        if operator in seen:
            continue
        url = night_graph.operator_booking_url(svc.get("operator_id", "")) or svc.get("booking_url")
        if url:
            seen.add(operator)
            links.append((operator, url))
    return links[:6]


def _domain(url: str) -> str:
    host = urlparse(url or "").netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _web_label(w: dict) -> str:
    """A clean button label for a web result: the site it opens, not a chopped title."""
    dom = _domain(w.get("url", ""))
    return f"Open on {dom}" if dom else (w.get("title") or "Open")[:28]


def _render_payload(out: dict):
    links = _booking_links(out.get("route_result", {}))
    if links:
        cols = st.columns(min(len(links), 3))
        for i, (operator, url) in enumerate(links):
            cols[i % len(cols)].link_button(f"Book {operator}", url, use_container_width=True)
    web = [w for w in out.get("web", []) if w.get("url")]
    if web:
        st.caption("From a web search, please confirm on the site:")
        wcols = st.columns(min(len(web), 3))
        for i, w in enumerate(web[:3]):
            wcols[i % len(wcols)].link_button(_web_label(w), w["url"], use_container_width=True)
    if out.get("sources"):
        titles = ", ".join(dict.fromkeys(s["title"] for s in out["sources"]))
        st.caption(f"Based on the night-train guides and operator notes: {titles}")


def _handle(thread: dict, query: str):
    history = [{"role": m["role"], "content": m["content"]} for m in thread["chat"]]
    thread["chat"].append({"role": "user", "content": query})
    if thread["title"] == "New trip":
        thread["title"] = query[:24] + ("..." if len(query) > 24 else "")
    ok, reason = safety.screen_query(query, st.session_state)
    if not ok:
        thread["chat"].append({"role": "assistant", "content": reason, "payload": None})
        return
    try:
        with st.spinner(random.choice(_SPINNERS)):
            out = agent.answer_query(query, model_key=_model_key(), history=history)
        thread["chat"].append({"role": "assistant", "content": out["answer"], "payload": out})
    except Exception as exc:
        logger.warning("agent failed: %s", exc)
        thread["chat"].append({"role": "assistant",
                               "content": "Something went wrong reaching the night-train network. Please try again.",
                               "payload": None})


def render_route_planner():
    thread = _active()
    chat = thread["chat"]

    if chat:
        spacer, pin_col, new_col = st.columns([5, 1.3, 1.1])
        pinned = thread.get("pinned")
        pin_col.button("📌 Pinned" if pinned else "📌 Pin this trip", key="pin_btn",
                       on_click=_pin, disabled=pinned, use_container_width=True,
                       help="Save this trip to the sidebar so you can come back to it. You can keep "
                            "chatting here and it stays up to date.")
        new_col.button("🆕 New chat", key="new_btn", on_click=_new_thread, use_container_width=True,
                       help="Start a fresh trip. This one stays saved in the sidebar if you pinned it.")
    else:
        st.subheader("Where do you want to sleep your way across Europe?")
        st.markdown(
            "Type your trip in the chat box at the bottom, like **Berlin to Bucharest**. Leave the "
            "destination out to see everywhere a city's night trains go, or ask how something works. "
            "Keep talking and I remember the trip."
        )
        st.caption("Or tap an example to start:")
        cols = st.columns(len(EXAMPLES))
        for i, ex in enumerate(EXAMPLES):
            cols[i].button(ex, key=f"ex_{i}", on_click=_queue, args=(ex,), use_container_width=True)

    # The conversation scrolls here, oldest at the top, newest just above the input.
    for msg in chat:
        avatar = "🌙" if msg["role"] == "assistant" else None
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])
            if msg.get("payload"):
                _render_payload(msg["payload"])

    if chat:
        st.caption("Night trains run on fixed schedules. Confirm the day and exact time on the operator's site.")

    # The input is the last thing rendered, so Streamlit pins it to the bottom.
    user_in = st.chat_input("Ask for a night train, e.g. Berlin to Bucharest")
    pending = user_in or st.session_state.pop("pending_query", None)
    if pending:
        _handle(thread, pending)
        st.rerun()


if __name__ == "__main__":
    print("ui/route_planner.py imports cleanly")
