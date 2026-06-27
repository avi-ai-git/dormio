"""The Dormio agent: a small LangGraph that decides how to answer.

A traveller can ask two different kinds of question, and the agent routes each to
the right tool instead of guessing:

  routing question  -> the deterministic night-train graph (agent/night_graph.py)
  knowledge question -> retrieval over the night-train know-how corpus (agent/knowledge.py)

A router node classifies the message (route, knowledge, both, or chitchat) and
extracts any cities, the relevant tool nodes run, and a synthesis node writes one
grounded answer from the tool outputs only. The model never decides a route and
never invents a fact: routing comes from the graph, knowledge comes from cited
documents. LLM on tap, not on top.

Every run is traced in Langfuse. Without an API key, or in TEST_MODE, the router
falls back to a deterministic heuristic and the synthesis falls back to the facts
themselves, so the whole pipeline still works offline.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional, TypedDict

import config
from agent import knowledge, night_graph, websearch
from agent.observability import flush, get_callbacks

logger = logging.getLogger(__name__)

Intent = str  # "route" | "knowledge" | "both" | "chitchat"


def _fill(template: str, **values: str) -> str:
    """Fill a prompt template without str.format.

    Retrieved documents and a traveller's own message can contain a stray brace, and
    str.format would crash on it, which once showed up as a failure on every knowledge
    question. Plain replacement keeps any brace in the text literal and safe.
    """
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", value or "")
    return out


class AgentState(TypedDict):
    query: str
    from_city: str
    to_city: str
    model_key: Optional[str]
    history: list
    intent: Intent
    route_result: dict
    knowledge: list
    web: list
    answer: str
    sources: list


def _format_history(history: list, limit: int = 4) -> str:
    """The last few turns as plain text, so the agent can follow a conversation."""
    if not history:
        return ""
    recent = history[-limit:]
    lines = [f"{'Traveller' if m['role'] == 'user' else 'You'}: {m['content']}" for m in recent]
    return "Recent conversation:\n" + "\n".join(lines) + "\n\n"


# --- the language model (shared provider switch) -------------------------------

def _get_llm(model_key: Optional[str]):
    """Build the chosen chat model, or None in test mode or without a key."""
    if os.getenv("TEST_MODE", "false").lower() == "true":
        return None
    option = config.model_by_key(model_key or config.DEFAULT_RUNTIME_MODEL)
    try:
        if option.provider == "mistral":
            from langchain_mistralai import ChatMistralAI
            if not config.MISTRAL_API_KEY:
                return None
            return ChatMistralAI(model=option.model_id, api_key=config.MISTRAL_API_KEY, temperature=0)
        if option.provider == "ollama":
            from langchain_openai import ChatOpenAI
            base = config.OLLAMA_BASE_URL.rstrip("/")
            base = base if base.endswith("/v1") else base + "/v1"
            return ChatOpenAI(model=option.model_id, openai_api_key=config.OLLAMA_API_KEY,
                              openai_api_base=base, temperature=0)
        from langchain_openai import ChatOpenAI
        if not config.OPENROUTER_API_KEY:
            return None
        return ChatOpenAI(model=option.model_id, openai_api_key=config.OPENROUTER_API_KEY,
                          openai_api_base=config.OPENROUTER_BASE_URL, temperature=0)
    except Exception as exc:
        logger.warning("agent llm unavailable: %s", exc)
        return None


# --- the routing tool: a deterministic lookup over the night-train graph --------

def route_lookup(from_city: str, to_city: str, pref: str = "changes", via: str = "") -> dict:
    """Resolve a routing question against the graph. No model, fully deterministic."""
    raw_from, raw_to = (from_city or "").strip(), (to_city or "").strip()
    from_on = night_graph.is_on_map(raw_from) if raw_from else False
    to_on = night_graph.is_on_map(raw_to) if raw_to else False

    result: dict = {
        "from": night_graph.display_city(raw_from) if raw_from else "",
        "to": night_graph.display_city(raw_to) if raw_to else "",
        "from_on_map": from_on, "to_on_map": to_on,
        "options": [], "options2": [], "via": "", "from_list": [], "origin_options": [],
        "mode": "need_input",
    }

    if not raw_from and not raw_to:
        result["mode"] = "need_input"
    elif raw_from and raw_to:
        if not from_on or not to_on:
            result["mode"] = "offmap"
            if from_on:
                result["from_list"] = night_graph.from_city(raw_from)
            elif to_on:
                result["from_list"] = night_graph.from_city(raw_to)
        elif via and night_graph.is_on_map(via):
            # A stop on the way: plan it as two stages, reusing the same search.
            to_via = night_graph.plan_routes(raw_from, via, k=3, pref=pref)
            from_via = night_graph.plan_routes(via, raw_to, k=3, pref=pref)
            if to_via and from_via:
                result["mode"] = "via"
                result["via"] = night_graph.display_city(via)
                result["options"], result["options2"] = to_via, from_via
            else:
                result["mode"], result["options"] = "routes", night_graph.plan_routes(raw_from, raw_to, k=3, pref=pref)
        else:
            options = night_graph.plan_routes(raw_from, raw_to, k=3, pref=pref)
            if options:
                result["mode"], result["options"] = "routes", options
            else:
                result["mode"] = "none"
                result["origin_options"] = night_graph.from_city(raw_from)
    else:
        city = raw_from or raw_to
        if night_graph.is_on_map(city):
            result["mode"] = "from" if raw_from else "to"
            result["from_list"] = night_graph.from_city(city)
            result["anchor"] = night_graph.display_city(city)
        else:
            result["mode"] = "offmap"
    return result


# --- the router: classify the message and extract cities -----------------------

_KNOWLEDGE_HINTS = (
    "book", "booking", "interrail", "eurail", "pass", "bike", "bicycle", "cater",
    "food", "eat", "luggage", "season", "seasonal", "price", "cost", "cheap",
    "expensive", "fare", "wheelchair", "accessible", "plug", "socket", "shower",
    "women", "woman", "safe", "reservation", "frequency", "difference",
    "how ", "what ", "when ", "why ", "which class",
)
# Common filler around a city name in free text, so we do not mistake it for a place.
_FILLER = {
    "night", "train", "trains", "sleeper", "couchette", "seat", "the", "a", "an",
    "by", "go", "get", "travel", "is", "there", "from", "to", "out", "of", "do",
    "i", "how", "can", "and", "overnight",
}


def _valid_city(name: str) -> str:
    name = (name or "").strip(" ?.!,")
    return name if name and night_graph.is_on_map(name) else ""


def _leading_valid_city(phrase: str) -> str:
    """Longest run of leading words naming a real city ('Reggio Calabria and ...' -> 'Reggio Calabria')."""
    words = (phrase or "").strip(" ?.!,").split()
    for end in range(len(words), 0, -1):
        hit = _valid_city(" ".join(words[:end]))
        if hit:
            return hit
    return ""


def _trailing_valid_city(phrase: str) -> str:
    """Longest run of trailing words naming a real city ('night train Berlin' -> 'Berlin')."""
    words = (phrase or "").strip(" ?.!,").split()
    for start in range(0, len(words)):
        hit = _valid_city(" ".join(words[start:]))
        if hit:
            return hit
    return ""


def _last_place_token(phrase: str) -> str:
    """A trailing single token that looks like a place, so an off-map origin like
    'Atlantis to Rome' is still recognised and reported as off-map (not silently dropped)."""
    words = (phrase or "").strip(" ?.!,").split()
    if words and words[-1].lower() not in _FILLER and words[-1].isalpha():
        return words[-1]
    return ""


def _extract_cities(query: str) -> tuple[str, str]:
    """Best-effort origin/destination from free text, anchored on the word 'to'."""
    q = query.strip()
    m = re.search(r"\bto\b", q, re.I)
    if m:
        left, right = q[: m.start()], q[m.end():]
        origin = _trailing_valid_city(left) or _last_place_token(left)
        dest = _leading_valid_city(right)
        if origin or dest:
            return origin, dest
    m = re.search(r"(?:from|out of|leaving|departing)\s+(.+)", q, re.I)
    if m:
        origin = _leading_valid_city(m.group(1))
        if origin:
            return origin, ""
    return "", ""


def _heuristic_route(query: str, from_city: str, to_city: str) -> tuple[Intent, str, str]:
    if from_city or to_city:
        return "route", from_city, to_city
    f, t = _extract_cities(query)
    has_route = bool(f or t)
    has_knowledge = any(h in query.lower() for h in _KNOWLEDGE_HINTS)
    if has_route and has_knowledge:
        return "both", f, t
    if has_route:
        return "route", f, t
    if has_knowledge:
        return "knowledge", "", ""
    return "chitchat", "", ""


_ROUTER_PROMPT = """You route a traveller's message for a night-train assistant. Reply with ONLY a JSON object:
{{"intent": "route" | "knowledge" | "both" | "chitchat", "from_city": "", "to_city": ""}}

route: they want to know whether or how to travel somewhere by night train. Naming a class like sleeper, couchette, or seat inside a route request is still route, not knowledge.
knowledge: they ask how night trains work in general (booking, Interrail or Eurail, couchette vs sleeper, bikes, seasons, prices, accessibility), without a specific trip.
both: a specific route question and a general knowledge question together.
chitchat: a greeting or anything off topic, like the weather.
Fill from_city and to_city whenever the message names them, even if the city may not have a night train. A stopover or via city is not the from or the to, so for "Berlin to Bucharest via Krakow" the from is Berlin and the to is Bucharest.

Examples:
"night train from Berlin to Vienna" -> {{"intent":"route","from_city":"Berlin","to_city":"Vienna"}}
"Amsterdam to Prague by sleeper" -> {{"intent":"route","from_city":"Amsterdam","to_city":"Prague"}}
"is my interrail pass valid on nightjet" -> {{"intent":"knowledge","from_city":"","to_city":""}}
"how do I get from Paris to Vienna and can I take a bike" -> {{"intent":"both","from_city":"Paris","to_city":"Vienna"}}
"trains out of Munich" -> {{"intent":"route","from_city":"Munich","to_city":""}}
"what is the weather like" -> {{"intent":"chitchat","from_city":"","to_city":""}}

Use the recent conversation to resolve follow-ups. "how do I book it" after a route is a knowledge question. When a follow-up names a new city it is a new route, and you keep the other endpoint from the conversation: after talking about Berlin to Bucharest, "what about from Krakow" means from_city Krakow and to_city Bucharest, and "is there anything from Poland" means from_city Krakow or the named Polish city to Bucharest.

{context}Message: {query}"""


def _router_node(state: AgentState) -> dict:
    query = state.get("query", "")
    from_city, to_city = state.get("from_city", ""), state.get("to_city", "")

    # The structured form path is unambiguous: both cities given means a route.
    if from_city and to_city:
        return {"intent": "route", "from_city": from_city, "to_city": to_city}

    llm = _get_llm(state.get("model_key"))
    if llm is not None:
        try:
            from langchain_core.messages import HumanMessage
            context = _format_history(state.get("history", []))
            resp = llm.invoke([HumanMessage(content=_fill(_ROUTER_PROMPT, context=context, query=query))])
            raw = re.sub(r"^```(json)?|```$", "", (resp.content or "").strip()).strip()
            data = json.loads(raw)
            intent = data.get("intent", "chitchat")
            if intent in ("route", "knowledge", "both", "chitchat"):
                # Pass the extracted cities through as given. The graph decides whether
                # each is on the network, so an off-map origin is reported, not dropped.
                return {
                    "intent": intent,
                    "from_city": (data.get("from_city") or "").strip() or from_city,
                    "to_city": (data.get("to_city") or "").strip() or to_city,
                }
        except Exception as exc:
            logger.warning("router parse failed, using heuristic: %s", exc)

    intent, f, t = _heuristic_route(query, from_city, to_city)
    return {"intent": intent, "from_city": f, "to_city": t}


def _detect_pref(query: str) -> str:
    """Read a ranking preference from the message, default fewest changes."""
    q = (query or "").lower()
    if any(w in q for w in ("fastest", "quickest", "quick", "shortest", "least time", "sooner")):
        return "time"
    return "changes"


_LIVE_HINTS = ("price", "prices", "cost", "how much", "cheap", "fare", "ticket", "live",
               "still run", "still running", "currently", "this week", "tonight",
               "tomorrow", "available", "sold out", "today")


def _wants_live(query: str) -> bool:
    """The traveller is asking about live times, prices, or availability."""
    q = (query or "").lower()
    return any(h in q for h in _LIVE_HINTS)


def _detect_via(query: str) -> str:
    """A single stop on the way, like 'Berlin to Bucharest via Krakow'."""
    city = r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .'\-]*"
    patterns = (
        rf"\bvia\s+({city})",
        rf"pit ?stop (?:in|at)\s+({city})",
        rf"stop(?:ping|over)?\s+(?:in|at)\s+({city})",
        rf"through\s+({city})",
    )
    for pattern in patterns:
        m = re.search(pattern, query or "", re.I)
        if m:
            hit = _leading_valid_city(m.group(1))
            if hit:
                return hit
    return ""


def _route_tool_node(state: AgentState) -> dict:
    try:
        query = state.get("query", "")
        result = route_lookup(state.get("from_city", ""), state.get("to_city", ""),
                              pref=_detect_pref(query), via=_detect_via(query))
        web = []
        a = result.get("from") or state.get("from_city", "")
        b = result.get("to") or state.get("to_city", "")
        # Search the web when the trip runs off the night-train network (the day-train
        # last mile) or when the traveller asks for live times, prices, or availability.
        if a and b and (result.get("mode") in ("offmap", "none") or _wants_live(query)):
            web = websearch.search(f"{a} to {b} by train or bus, overland route and times")
        return {"route_result": result, "web": web}
    except Exception as exc:
        logger.warning("route tool failed, continuing without it: %s", exc)
        return {"route_result": {}, "web": list(state.get("web", []))}


def _knowledge_tool_node(state: AgentState) -> dict:
    try:
        hits = knowledge.retrieve(state.get("query", ""), k=4)
        sources = [{"title": h["title"], "source": h["source"]} for h in hits]
        web = list(state.get("web", []))
        # Back-fill from the web when the corpus has nothing close, or for live questions.
        if not web and websearch.available() and (
                not hits or hits[0].get("score", 0) < 0.05 or _wants_live(state.get("query", ""))):
            web = websearch.search(state.get("query", ""))
        return {"knowledge": hits, "sources": sources, "web": web}
    except Exception as exc:
        logger.warning("knowledge tool failed, continuing without it: %s", exc)
        return {"knowledge": [], "sources": [], "web": list(state.get("web", []))}


# --- synthesis: write one grounded answer from the tool outputs ----------------

def _option_lines(options: list) -> list:
    out = []
    for i, opt in enumerate(options, 1):
        mins = opt.get("duration_min") or 0
        dur = f", about {mins // 60}h{mins % 60:02d}" if mins else ""
        label = "direct" if opt["changes"] == 0 else f"{opt['changes']} change" + ("s" if opt["changes"] > 1 else "")
        out.append(f"- Option {i} ({label}{dur})")
        for leg in opt["legs"]:
            s = leg["service"]
            dep = f", departs {s['depart']}" if s.get("depart") else ""
            arr = f", arrives {s['arrive']}" if s.get("arrive") else ""
            out.append(f"  ride {s['operator']} from {leg['board']} to {leg['alight']} ({', '.join(s.get('classes', []))}{dep}{arr})")
    return out


def _route_facts(result: dict) -> str:
    if not result:
        return ""
    mode, a, b = result.get("mode"), result.get("from", ""), result.get("to", "")
    lines: list[str] = []
    if mode == "routes":
        lines.append(f"Ways to travel by night train from {a} to {b}, best first:")
        lines += _option_lines(result.get("options", []))
    elif mode == "via":
        stop = result.get("via", "")
        lines.append(f"A trip from {a} to {b} stopping in {stop}, planned in two stages.")
        lines.append(f"Stage one, {a} to {stop}:")
        lines += _option_lines(result.get("options", []))
        lines.append(f"Stage two, {stop} to {b}:")
        lines += _option_lines(result.get("options2", []))
    elif mode in ("from", "to"):
        anchor = result.get("anchor", a or b)
        lines.append(f"Night trains from {anchor}:")
        for r in result["from_list"][:12]:
            dep = f", departs {r['service']['depart']}" if r["service"].get("depart") else ""
            lines.append(f"- to {r['destination']} on {r['service']['operator']}{dep}")
    elif mode == "none":
        lines.append(f"There is no night train between {a} and {b}.")
        for r in result.get("origin_options", [])[:8]:
            lines.append(f"- {a} does have a night train to {r['destination']} on {r['service']['operator']}")
    elif mode == "offmap":
        off = a if not result.get("from_on_map") else b
        lines.append(f"{off or 'That city'} is not on the night-train network.")
        for r in result.get("from_list", [])[:8]:
            lines.append(f"- the other city has a night train to {r['destination']} on {r['service']['operator']}")
    return "\n".join(lines)


def _knowledge_facts(hits: list) -> str:
    if not hits:
        return ""
    blocks = [f"Source ({h['title']}): {h['text']}" for h in hits[:3]]
    return "Knowledge from the guides and operator notes:\n" + "\n\n".join(blocks)


def _web_facts(web: list) -> str:
    if not web:
        return ""
    blocks = [f"Web result ({w['title']}): {w['snippet']}" for w in web[:3] if w.get("snippet")]
    return "From a live web search (use only for the part the night-train data cannot cover, and say it came from the web):\n" + "\n".join(blocks)


_SYNTH_PROMPT = """You are Dormio, a warm, plain-spoken guide to Europe's night trains, in a conversation with a traveller. Answer their latest message using ONLY the facts and sources below. Never invent a train, a time, a price, or a route. If a route fact says there is no night train, say so honestly and offer what does exist.

Write like a helpful person, not a brochure:
- Open with one short, direct sentence that answers the question.
- When you describe a route or a chain, lay it out as a clear itinerary in bullet points: each leg with the operator, the departure time if known, and the sleeping options. Keep the bullets short.
- For a knowledge question, answer in a sentence or two, in plain words.
- You can suggest a natural follow-up, or point them to the booking links shown below your message, or to the Night Train Explorer to see the whole map.
- If web results are given, use them only for the last mile or the connection the night-train data does not have, and say that part comes from a web search the traveller should confirm.
- Favour trains, day or night, then buses. Never lead with a flight. Mention a flight only as a last resort when there is no overland option at all, because this is about travelling without flying.
- Never say the network has no route, no city, or no data for a leg. If something the traveller mentions is not in the facts below, do not claim it does not exist. Say you have not mapped that exact leg here, and suggest they ask for it directly, for example Krakow to Vienna, or check the Night Train Explorer.
- No headings, no bold text, no em dashes. Use a normal hyphen for bullets.

{history}Traveller's latest message: {query}

{route_facts}

{knowledge}

{web}"""


# A safety net so no em dash, en dash, or other long dash ever reaches the reader,
# even if a model slips one in. Hyphens in words like step-free are left alone, only
# the long dashes are rewritten into plain punctuation.
_DASHES = "—–―‒﹘−"  # em, en, horizontal bar, figure, small, minus


def _humanize(text: str) -> str:
    """Strip typographic dashes from model output. Plain words, no AI slop."""
    if not text:
        return text
    # A dash between numbers is a range, so read it as "to": 05-10, 20:05-08:35.
    text = re.sub(rf"(?<=\d)\s*[{_DASHES}]\s*(?=\d)", " to ", text)
    # A dash joining words is a separator, so a comma reads naturally.
    text = re.sub(rf"(?<=\w)\s*[{_DASHES}]\s*(?=\w)", ", ", text)
    # Anything left over, at the start or end of a clause, just goes.
    text = re.sub(rf"\s*[{_DASHES}]\s*", " ", text)
    # Tidy the doubled or stranded punctuation the rewrite can leave behind.
    text = re.sub(r",\s*,", ", ", text)
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    return text.strip()


def _synthesize_node(state: AgentState) -> dict:
    intent = state.get("intent", "chitchat")
    if intent == "chitchat":
        return {"answer": "I help with Europe's night trains. Ask me for a route, like "
                          "Vienna to Rome, or how something works, like whether your Interrail "
                          "pass covers a sleeper."}

    route_facts = _route_facts(state.get("route_result", {}))
    knowledge_facts = _knowledge_facts(state.get("knowledge", []))
    web_facts = _web_facts(state.get("web", []))

    if route_facts and state.get("route_result", {}).get("mode") == "need_input":
        return {"answer": "Tell me where you want to start or where you want to go, and I will "
                          "find the night trains."}

    llm = _get_llm(state.get("model_key"))
    if llm is None:
        fallback = route_facts.split("\n")[0] if route_facts else ""
        if not fallback and state.get("knowledge"):
            fallback = state["knowledge"][0]["text"].splitlines()[-1][:200]
        return {"answer": fallback or "I could not find that one."}

    try:
        from langchain_core.messages import HumanMessage
        prompt = _fill(_SYNTH_PROMPT, history=_format_history(state.get("history", [])),
                       query=state.get("query", ""), route_facts=route_facts,
                       knowledge=knowledge_facts, web=web_facts)
        resp = llm.invoke([HumanMessage(content=prompt)])
        text = (resp.content or "").strip()
        return {"answer": text or (route_facts.split("\n")[0] if route_facts else "")}
    except Exception as exc:
        logger.warning("synthesis failed: %s", exc)
        return {"answer": route_facts.split("\n")[0] if route_facts else "I could not find that one."}


# --- graph wiring --------------------------------------------------------------

def _from_router(state: AgentState) -> str:
    return state.get("intent", "chitchat")


def _after_route(state: AgentState) -> str:
    return "knowledge" if state.get("intent") == "both" else "synthesize"


def _build_graph():
    from langgraph.graph import END, StateGraph
    g = StateGraph(AgentState)
    g.add_node("router", _router_node)
    g.add_node("route_tool", _route_tool_node)
    g.add_node("knowledge_tool", _knowledge_tool_node)
    g.add_node("synthesize", _synthesize_node)
    g.set_entry_point("router")
    g.add_conditional_edges("router", _from_router, {
        "route": "route_tool", "both": "route_tool",
        "knowledge": "knowledge_tool", "chitchat": "synthesize",
    })
    g.add_conditional_edges("route_tool", _after_route, {
        "knowledge": "knowledge_tool", "synthesize": "synthesize",
    })
    g.add_edge("knowledge_tool", "synthesize")
    g.add_edge("synthesize", END)
    return g.compile()


_GRAPH = _build_graph()


def answer_query(query: str, from_city: str = "", to_city: str = "",
                 model_key: Optional[str] = None, history: Optional[list] = None) -> dict:
    """Answer one traveller message end to end, in the context of the conversation.

    Returns the grounded answer, the router's intent, the routing result (so the UI
    can show the route), and the knowledge sources used. Traced in Langfuse.
    """
    base_state = {
        "query": query or "", "from_city": from_city or "", "to_city": to_city or "",
        "model_key": model_key, "history": history or [], "intent": "", "route_result": {},
        "knowledge": [], "web": [], "answer": "", "sources": [],
    }
    state = _run_graph(base_state)
    return {
        "answer": _humanize(state.get("answer", "")) or
        "I had trouble with that one. Try a route like Vienna to Rome, or ask how something works.",
        "intent": state.get("intent", ""),
        "route_result": state.get("route_result", {}),
        "sources": state.get("sources", []),
        "knowledge": state.get("knowledge", []),
        "web": state.get("web", []),
    }


def _run_graph(base_state: dict) -> dict:
    """Run the agent. Tracing is best effort: if the callbacks ever break a run, retry
    once without them, so a tracing hiccup can never turn into a failed answer."""
    try:
        callbacks = get_callbacks()
    except Exception as exc:
        logger.warning("tracing callbacks unavailable: %s", exc)
        callbacks = []
    if callbacks:
        try:
            out = _GRAPH.invoke(base_state, config={"callbacks": callbacks, "run_name": "dormio-agent"})
            flush()
            return out
        except Exception as exc:
            logger.warning("traced run failed, retrying without tracing: %s", exc)
    try:
        return _GRAPH.invoke(base_state)
    except Exception as exc:
        logger.error("agent run failed: %s", exc)
        return dict(base_state)


def classify(query: str, model_key: Optional[str] = None) -> dict:
    """Run only the router. Returns {intent, from_city, to_city}. Used by the eval."""
    return _router_node({"query": query or "", "from_city": "", "to_city": "",
                         "model_key": model_key, "history": [], "intent": "", "route_result": {},
                         "knowledge": [], "web": [], "answer": "", "sources": []})


def plan_night(from_city: str, to_city: str, model_key: Optional[str] = None) -> dict:
    """Backward-compatible structured route lookup for the form path and the map."""
    query = f"night train from {from_city or 'anywhere'} to {to_city or 'anywhere'}"
    out = answer_query(query, from_city=from_city, to_city=to_city, model_key=model_key)
    return {"result": out["route_result"], "summary": out["answer"], "intent": out["intent"]}


if __name__ == "__main__":
    os.environ.setdefault("TEST_MODE", "true")
    samples = [
        ("Vienna to Rome", "", ""),
        ("is my interrail pass valid on nightjet", "", ""),
        ("how do I get from Gdynia to Vienna and can I take a bike", "", ""),
        ("trains from Krakow", "", ""),
        ("hello there", "", ""),
        ("", "Vienna", "Rome"),
    ]
    for q, f, t in samples:
        out = answer_query(q, f, t)
        print(f"\nQ: {q or f+'->'+t}\n  intent={out['intent']} | {out['answer'][:110]}")
        if out["sources"]:
            print("  sources:", [s["title"] for s in out["sources"]][:3])
