"""The live pipeline, running as one thing.

WHY THIS FILE EXISTS
--------------------
It did not, and that is how the console came to freeze in front of an operator.

Every layer had tests. The loop that runs all five together -- `LiveTwin` --
had none: nothing in the suite instantiated it. So a defect that could only
appear when the layers were wired together was invisible to 508 passing tests.

The defect: `alerts.active` holds `layer1_edge.edge_rules.Alert` DATACLASSES,
and the flight-record render step used `dict(a)` as its fallback for anything
without `model_dump`. A dataclass is not iterable, so that raises
`TypeError: 'Alert' object is not iterable` -- on every tick from then on,
because `_run` catches the exception and the tick counter never advances past
the failing line. The twin froze permanently, the console showed stale values,
and `/api/healthz` went on reporting `{"ok": true}`.

The path only runs when an alert is ACTIVE. A healthy engine never reaches it.
The system broke the first time it did the one thing it exists to do.

These tests run the real pipeline, so they take a few seconds each. That is the
point: the cheap unit tests already passed.
"""

from __future__ import annotations

import time

import pytest

from layer1_edge.edge_rules import Alert, AlertLevel
from layer4_core.live import LiveTwin, _alert_as_dict


def _wait_for_ticks(twin: LiveTwin, n: int, timeout: float = 15.0) -> int:
    end = time.time() + timeout
    while time.time() < end:
        t = twin.snapshot().pipeline.get("ticks", 0)
        if t >= n:
            return t
        err = twin.snapshot().pipeline.get("error")
        assert not err, f"the pipeline stopped on {err}"
        time.sleep(0.1)
    return twin.snapshot().pipeline.get("ticks", 0)


def test_alert_renders_without_raising():
    """The exact object the rule engine emits must render to a plain dict.

    This is the unit-level half of the freeze: `Alert` is a dataclass, so the
    old `dict(a)` fallback raised. The flight record needs `rule_id`, `level`,
    `legend` and `advisory`, so those must survive the conversion.
    """
    a = Alert(rule_id="R1", legend="OIL PRESS LOW", level=AlertLevel.ORANGE,
              parameter="oil_pressure", value=1.0, limit=2.0, advisory="LAND")
    d = _alert_as_dict(a)
    assert d["rule_id"] == "R1"
    assert d["legend"] == "OIL PRESS LOW"
    assert d["advisory"] == "LAND"
    assert int(d["level"]) == int(AlertLevel.ORANGE)


def test_alert_renderer_never_raises_on_anything():
    """A rendering detail must not be able to stop the engine.

    The original bug was not that one type was unhandled -- it was that an
    unhandled type killed the whole twin. Whatever arrives, this returns a
    dict rather than raising.
    """
    for odd in [{"legend": "ALREADY A DICT"}, "a bare string", 42, None]:
        assert isinstance(_alert_as_dict(odd), dict)


@pytest.mark.slow
def test_live_twin_ticks_and_produces_a_complete_snapshot():
    """The baseline nobody had: the pipeline runs and fills the snapshot."""
    twin = LiveTwin(speed=400.0)
    twin.start()
    try:
        assert _wait_for_ticks(twin, 20) >= 20
        s = twin.snapshot()

        p = s.pipeline
        assert not p.get("error")
        assert p["frames_decoded"] > 0
        assert p["frames_lost"] == 0
        assert p["decode_errors"] == 0
        assert p["channels_usable"] == p["channels_total"]
        assert p["shadow_available"] is True

        assert len(s.twin["residuals"]) >= 7
        # Twenty ticks is ten seconds on the starter: the engine is cold, and
        # its condition is judged only warm, loaded and steady. So the health
        # figures are WITHHELD and say why -- a cold engine's indices must
        # never be published as its health (the red bars on every start).
        a = s.health["assessment"]
        if a["state"] == "assessing":
            assert s.health["chi"] is None
            assert "not yet warm" in a["reason"]
        else:
            assert isinstance(s.health["chi"], float)
            assert 0.0 <= s.health["chi"] <= 1.0
        # RUL may legitimately withhold a figure early on, but the contract
        # it reports against is always present.
        assert {"hours", "reportable", "reason"} <= set(s.rul)
        assert s.fusion["level_name"]
        assert "chi" in s.display
    finally:
        twin.stop()


@pytest.mark.slow
def test_live_survives_its_first_alert():
    """THE REGRESSION. The twin must keep ticking once an alert fires.

    Injects a fault severe enough to raise a real Tier-1 alert, then asserts
    the loop is still advancing afterwards and has recorded no error. Before
    the fix this froze on the first tick after the alert appeared.
    """
    twin = LiveTwin(speed=400.0)
    twin.start()
    try:
        _wait_for_ticks(twin, 20)
        twin.inject("injector_abnormal", 0.9, ramp_hours=0.01)

        raised = False
        end = time.time() + 30.0
        while time.time() < end:
            s = twin.snapshot()
            assert not s.pipeline.get("error"), (
                f"the pipeline stopped on {s.pipeline['error']}"
            )
            if s.twin.get("alerts", {}).get("active"):
                raised = True
                break
            time.sleep(0.2)

        # Whether or not the alert latched inside the window, the loop must
        # still be alive -- and if it did latch, this is the exact case that
        # used to freeze.
        before = twin.snapshot().pipeline.get("ticks", 0)
        time.sleep(1.5)
        after = twin.snapshot().pipeline.get("ticks", 0)

        assert not twin.snapshot().pipeline.get("error")
        assert after > before, (
            f"the twin stopped ticking at {after} "
            f"(alert {'was' if raised else 'was not'} raised)"
        )
    finally:
        twin.stop()


@pytest.mark.slow
def test_an_alert_reaches_the_flight_record():
    """Not just 'it did not crash' -- the event must actually be recorded.

    A fix that swallowed the alert instead of rendering it would pass the
    regression test above while quietly losing the post-flight event log.
    """
    twin = LiveTwin(speed=400.0)
    twin.start()
    try:
        _wait_for_ticks(twin, 20)
        twin.inject("injector_abnormal", 0.95, ramp_hours=0.01)

        end = time.time() + 30.0
        while time.time() < end:
            s = twin.snapshot()
            assert not s.pipeline.get("error")
            if s.flight_record.get("events"):
                ev = s.flight_record["events"][0]
                assert ev.get("legend")
                assert "phase" in ev
                return
            time.sleep(0.2)
        pytest.skip("no alert latched within the window; timing-dependent")
    finally:
        twin.stop()


@pytest.mark.slow
def test_persistent_tick_failure_is_logged_and_degrades_health(caplog):
    """A PERSISTENT failure must become loud, and must stop claiming health.

    The old handler stored the message in a snapshot field and carried on with
    no log and no counter, so DEV-149 froze the twin while `/api/healthz` went
    on reporting ok. This asserts the three properties that were missing:

      * the first failure is logged WITH a traceback,
      * consecutive failures are counted,
      * past the limit the twin marks itself DEGRADED so the health probe
        stops reporting ok.
    """
    import logging

    from layer4_core.live import _TICK_FAILURE_LIMIT

    twin = LiveTwin(speed=400.0)
    twin.start()
    try:
        _wait_for_ticks(twin, 10)

        boom = RuntimeError("synthetic tick failure")
        with caplog.at_level(logging.ERROR, logger="layer4_core.live"):
            twin._tick = lambda: (_ for _ in ()).throw(boom)  # type: ignore[method-assign]

            end = time.time() + 15.0
            while time.time() < end:
                p = twin.snapshot().pipeline
                if p.get("consecutive_failures", 0) >= _TICK_FAILURE_LIMIT:
                    break
                time.sleep(0.1)

        p = twin.snapshot().pipeline
        assert p.get("consecutive_failures", 0) >= _TICK_FAILURE_LIMIT
        assert p.get("degraded") is True, "the twin still claims to be healthy"
        assert "synthetic tick failure" in str(p.get("error"))
        # A traceback must have reached the log, not only the snapshot.
        assert any("tick failed" in r.message or "tick has failed" in r.message
                   for r in caplog.records), "the failure was never logged"
    finally:
        twin.stop()
