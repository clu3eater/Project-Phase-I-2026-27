"""Each strip reading against what the twin says it should be now.

The certified limit says when a value is dangerous; the twin says what it
should be at this operating point. The difference is the early warning, and
this is the check that it stays quiet on a healthy engine and speaks on a
faulty one while the limit is still far away.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("DT_PERSIST", "0")

from layer2_physics import engine_sim as es  # noqa: E402
from layer4_core.live import LiveTwin  # noqa: E402


def _reference_established(t: LiveTwin) -> bool:
    """Has this engine's own reference -- its build offset -- been fixed yet?

    The twin expects the as-new engine plus this engine's build offset, learned
    over its first stretch of level flight and then frozen
    (health.assessment.residual_reference_settle_s). A fault already present
    while it is learned IS learned, as the build offset, exactly as it would be
    on a real engine, and nothing is left to see against the twin -- so a fault
    must arrive after it. Without torch the RUL network is not served, the
    reference is never fed, and the offset stays 0: there is nothing to wait
    for, which is the only configuration these tests used to run in.
    """
    return not t.rul_net.available or t.rul_net.baseline.frozen


@pytest.fixture(scope="module")
def flown():
    t = LiveTwin(seed=7, speed=1000.0)
    t.park()
    t._thread = object()           # queue commands as a started twin would
    t.begin_profile(es.mission_profile(0.3, 8000), kind="mission", label="T")
    seen = {}
    first = injected = None
    try:
        for i in range(6000):
            t._tick()
            s = t.snapshot()
            if (s.sortie or {}).get("holding"):
                t.launch()
            tw = s.display.get("twin", {})
            if first is None:
                if tw.get("cht_max", {}).get("graded"):
                    first = i
                else:
                    seen["before"] = tw
            elif injected is None:
                if i >= first + 300 and _reference_established(t):
                    seen["healthy"] = tw
                    t.inject("cooling_degradation", 0.9)
                    injected = i
            elif i == injected + 1200:
                seen["fault"] = tw
                seen["fault_cht"] = s.twin["reported"]["cht_max"]["value"]
                break
    finally:
        t._thread = None
        t.stop()
    return seen


def test_nothing_is_graded_before_the_engine_is_warm(flown):
    for ch in flown["before"].values():
        assert not ch.get("graded")


def test_a_healthy_engine_is_normal_against_its_twin(flown):
    for name, ch in flown["healthy"].items():
        assert ch["available"], name
        assert ch["level"] == "normal", (name, ch)


def test_a_cooling_fault_shows_against_the_twin_before_the_limit(flown):
    cht = flown["fault"]["cht_max"]
    assert cht["level"] in ("degraded", "fault"), cht
    assert cht["deviation"] > 4.0
    # ...while the reading itself is still inside the 135 degC limit.
    assert flown["fault_cht"] < 135.0


def test_a_stopped_engine_has_no_twin_comparison():
    t = LiveTwin(seed=3, speed=1000.0)
    t.park()
    try:
        for _ in range(20):
            t._tick()
        for ch in t.snapshot().display["twin"].values():
            assert ch["available"] is False
    finally:
        t.stop()


def test_every_monitored_parameter_of_the_problem_statement_has_a_twin(flown):
    """PS section B lists what must be monitored. Each is compared with the
    twin except RPM, the twin's own input (shadow_model.py)."""
    ps_b = {"cht_max", "egt_max", "oil_pressure", "oil_temperature", "fuel_flow",
            "vibration_rms_total", "bus_voltage", "injection_timing"}
    assert ps_b <= set(flown["healthy"])
    for name in ps_b:
        ch = flown["healthy"][name]
        # The reading shown is the reading, and the difference is exactly it
        # minus the twin -- in the reading's own unit.
        assert ch["measured"] - ch["expected"] == pytest.approx(ch["deviation"], abs=1e-6), name


def test_injector_and_vibration_faults_show_against_the_twin():
    t = LiveTwin(seed=7, speed=1000.0)
    t.park()
    t._thread = object()
    t.begin_profile(es.mission_profile(0.3, 8000), kind="mission", label="T")
    try:
        injected = None
        for i in range(4000):
            t._tick()
            if (t.snapshot().sortie or {}).get("holding"):
                t.launch()
            if injected is None:
                if i >= 900 and _reference_established(t):
                    t.inject("injector_abnormal", 0.9)
                    t.inject("abnormal_vibration", 0.9)
                    injected = i
            elif i == injected + 800:
                break
        assert injected is not None, "the engine reference never settled"
        tw = t.snapshot().display["twin"]
        for name in ("fuel_flow", "vibration_rms_total", "injection_timing"):
            assert tw[name]["level"] in ("degraded", "fault"), (name, tw[name])
        assert tw["bus_voltage"]["level"] == "normal"
    finally:
        t._thread = None
        t.stop()
