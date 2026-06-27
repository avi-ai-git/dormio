"""About tab. What Dormio is, how to use it, and how it works."""
import streamlit as st

from agent import knowledge, night_graph


def render_about():
    st.subheader("What Dormio is")
    st.markdown(
        "Dormio is a calm place to plan Europe's night trains, the sleeper and couchette services "
        "that carry you across the continent while you sleep. Night trains are having a comeback, but "
        "they are scattered across dozens of operators with no single place that tells you which routes "
        "exist, what you can sleep in, and how to book. Dormio brings them into one conversation, one map, "
        "and one directory."
    )

    routes = len(night_graph.all_services())
    ops = len(night_graph.operators())
    countries = len(night_graph.night_countries())
    stats = knowledge.corpus_stats()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Night-train routes", routes)
    c2.metric("Operators", ops)
    c3.metric("Countries", countries)
    c4.metric("Knowledge sources", stats["documents"])

    st.divider()
    st.subheader("How to use each tab")

    with st.container(border=True):
        st.markdown("**Ask Dormio**")
        st.markdown(
            "A conversation. Type in plain language and keep talking, and the assistant remembers the "
            "thread. Ask for a route like Vienna to Rome and it finds the direct sleeper, a one change "
            "journey, or an honest no. Leave the destination out, like night trains from Krakow, to see "
            "everywhere a sleeper can take you. Ask how something works, like whether your Interrail pass "
            "covers a couchette, and it answers from the guides and the operator notes and shows its "
            "sources. When the trip runs off the edge of the map, it searches the web for the last mile "
            "and tells you that part came from a search."
        )

    with st.container(border=True):
        st.markdown("**The Night Map**")
        st.markdown(
            "The whole night-train network on one map, with a switch between Night Train Routes and Night "
            "Train Operators. Routes lists every service, pick a country or two, sort by how long the "
            "journey runs or when it leaves or arrives, and narrow to trains that carry bikes. Each card "
            "shows the times, the cities it calls at, and the CO2 for the trip. Operators lists who runs "
            "the trains, filter by the countries a train passes through or pick an operator by name, and "
            "open one for its lines, booking site, and notes."
        )

    st.divider()
    st.subheader("How it works")
    st.markdown(
        "Dormio sends each question to the tool that can answer it well. A routing question goes to a "
        "graph over the real night-train network, so the answer is correct and can never be a bus or an "
        "invented train. A how-does-it-work question goes to a retrieval layer over a set of night-train "
        "guides and operator notes, so the answer is grounded in real documents and cites them. A trip "
        "that runs off the network goes to a web search for the day-train last mile, which is always "
        "labelled. The model you pick in the sidebar only puts the found facts into plain words, so "
        "changing it changes the wording, never the routes."
    )
    st.caption(
        f"The knowledge base is {stats['guides']} night-train guides plus {stats['operators']} operator "
        f"profiles, {stats['documents']} short documents in all. The assistant searches them and cites the "
        "ones it used, so a how-does-it-work answer always points back to a real source."
    )

    st.divider()
    st.subheader("Ethics, privacy, and bias")
    st.markdown(
        "- **Nothing about you is kept.** No account, no tracking. Your question is screened, answered, "
        "and forgotten. The only data stored is the open night-train dataset.\n"
        "- **The same answer for everyone.** Routes come from a deterministic graph, not from the model, "
        "so there is no model bias in what gets suggested and nobody is quietly shown a different train.\n"
        "- **It will not make a train up.** The model only puts found facts into words. Every route, time, "
        "and fact comes from the graph, a cited document, or a labelled web search, and an honest no night "
        "train here is a valid answer.\n"
        "- **It is hard to misuse.** Every message passes a rate limit, a prompt-injection filter, and a "
        "moderation check before any model is called."
    )

    st.divider()
    st.subheader("Get in touch")
    st.markdown(
        "Built by Avishek Chatterjee. If you have feedback, an idea, or a route that looks "
        "wrong, I would love to hear it. Reach me on "
        "[LinkedIn](https://www.linkedin.com/in/avishek-chatterjee/)."
    )
    st.caption(
        "Route and operator data from the Back-on-Track "
        "[Open Night Train Database](https://github.com/Back-on-Track-eu/night-train-data), CC BY-NC-ND 4.0. "
        "Night trains run on fixed schedules, so always confirm the day and time on the operator's site "
        "before booking."
    )
