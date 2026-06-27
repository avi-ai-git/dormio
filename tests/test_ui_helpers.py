"""Tests for the UI helpers and data integrity. Deterministic and offline.

These lock in the round of fixes around the map, the CO2 figures, the price
scrubbing, the dash-free output, and the trivia, and they double as a light
integrity sweep over every service in the dataset.
"""
import os

os.environ.setdefault("TEST_MODE", "true")

from collections import Counter

from agent import night_graph as ng
from agent.agent import _humanize

_DASHES = "—–―‒﹘−"


def test_humanize_strips_every_long_dash():
    out = _humanize("Vienna to Rome – departs 20:05, arrives 10:05 — seat or sleeper.")
    assert not any(d in out for d in _DASHES)
    assert "step-free" == _humanize("step-free")  # real hyphens survive


def test_humanize_number_range_reads_as_to():
    assert "05 to 10" in _humanize("mornings 05–10")


def test_no_prices_removes_fares():
    from ui.operator_directory import _no_prices
    out = _no_prices("Pendolino from €8.90 advance. Night trains to Lapland popular.")
    assert "8.90" not in out and "€" not in out
    assert "Lapland" in out


def test_facts_are_many_and_clean():
    import app
    facts = app._facts()
    assert len(facts) >= 50, f"expected a deep trivia pool, got {len(facts)}"
    for f in facts:
        assert not any(d in f for d in _DASHES), f"dash leaked into a fact: {f}"
        assert f.strip().endswith((".", "!"))


def test_every_service_resolves_endpoints_for_the_map():
    """The baked-coord fallback should let every service draw on the overview map."""
    unresolved = [s for s in ng.all_services()
                  if not all(ng.service_endpoints(s))]
    assert not unresolved, "routes that will not draw: " + ", ".join(
        f"{s.get('from_city')}->{s.get('to_city')}" for s in unresolved)


def test_co2_is_filled_for_almost_every_route():
    from ui.night_trains import _route_co2
    svcs = ng.all_services()
    real = [s for s in svcs if _route_co2(s) and not _route_co2(s)[1]]
    estimated = [s for s in svcs if _route_co2(s) and _route_co2(s)[1]]
    covered = [s for s in svcs if _route_co2(s)]
    assert len(real) >= 140, f"expected most CO2 to be real, got {len(real)}"
    assert len(covered) >= len(svcs) - 5, f"CO2 missing on too many: {len(svcs) - len(covered)}"
    assert estimated, "expected some routes to use the labelled estimate"


def test_fill_is_brace_safe():
    from agent.agent import _fill, _SYNTH_PROMPT
    out = _fill(_SYNTH_PROMPT, history="", query="what about {weird} input}",
                route_facts="", knowledge="a note with a stray { brace", web="")
    assert "stray { brace" in out and "{weird} input}" in out


def test_answer_survives_broken_tracing(monkeypatch):
    """A tracing callback that breaks a run must not break the answer."""
    import agent.agent as A
    monkeypatch.setattr(A, "get_callbacks", lambda: ["not-a-real-callback"])
    out = A.answer_query("Vienna to Rome")
    assert out["answer"], "expected an answer even when tracing is broken"


def test_answer_survives_tool_failure(monkeypatch):
    """If the knowledge tool throws, the agent still returns something useful."""
    import agent.agent as A
    monkeypatch.setattr(A.knowledge, "retrieve",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    out = A.answer_query("how do I book european sleeper")
    assert out["answer"], "expected a graceful answer when a tool fails"


def test_no_duplicate_route_ids_and_durations_parse():
    svcs = ng.all_services()
    ids = [s.get("id") for s in svcs if s.get("id")]
    assert not [k for k, v in Counter(ids).items() if v > 1], "duplicate route ids"
    for s in svcs:
        d = s.get("duration") or ""
        if d:
            h, _, m = d.partition(":")
            assert h.isdigit() and m.isdigit(), f"bad duration {d!r} on {s.get('id')}"
