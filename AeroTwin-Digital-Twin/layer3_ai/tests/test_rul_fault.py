"""Per-fault time-to-action must predict, and must refuse.

PS section C asks for the "detection/prediction" of eight fault modes, and the
two are different questions. These tests pin both halves: that a real trend
produces a usable forecast, and that everything else produces a refusal rather
than a confident number fitted to noise.
"""

from __future__ import annotations

import numpy as np
import pytest

from common import config
from layer3_ai.rul_fault import INDICATORS, FaultRul


def _feed(r: FaultRul, mode: str, start: float, rate: float,
          *, n: int = 90, dt: float = 0.25, noise: float = 0.0, seed: int = 7):
    """Drive one indicator along a known line."""
    rng = np.random.default_rng(seed)
    for k in range(n):
        h = k * dt
        r.observe(h, {mode: start + rate * h + rng.normal(0.0, noise)})


# ---------------------------------------------------------------------------
# It predicts
# ---------------------------------------------------------------------------


def test_a_rising_indicator_forecasts_when_it_reaches_the_action_threshold():
    """The cooling residual climbs from 2 to its 10 degC fault threshold."""
    r = FaultRul()
    _feed(r, "cooling_degradation", start=2.0, rate=0.25, noise=0.4)
    f = r.forecast("cooling_degradation")
    assert f.status == "trending"
    assert f.reportable
    # True crossing from the final value at 0.25 C/h. Generous, because the fit
    # is over noisy data -- the test is that the answer is in the right place,
    # not that it is exact.
    assert 5.0 < f.hours_to_action < 40.0
    assert f.rate_per_hour == pytest.approx(0.25, abs=0.06)


def test_a_forecast_carries_an_interval():
    """PRD Part 4 s7.4a applies to EVERY prediction this system makes, not
    only to the engine-level RUL. A single number would be read as a promise."""
    r = FaultRul()
    _feed(r, "cooling_degradation", start=2.0, rate=0.25, noise=0.5)
    f = r.forecast("cooling_degradation")
    assert f.lower_hours is not None and f.upper_hours is not None
    assert f.lower_hours <= f.hours_to_action <= f.upper_hours
    assert f.upper_hours > f.lower_hours, "a zero-width interval is not an interval"


def test_an_indicator_that_falls_towards_its_threshold_is_handled():
    """The oil pressure residual degrades DOWNWARD, towards -10 psi.

    Treating every indicator as rising would report a failing lubrication
    system as improving -- which is the worst direction for that error.
    """
    assert INDICATORS["lubrication_issue"].rising is False
    r = FaultRul()
    _feed(r, "lubrication_issue", start=-1.0, rate=-0.3, noise=0.3)
    f = r.forecast("lubrication_issue")
    assert f.status == "trending"
    assert f.hours_to_action is not None and f.hours_to_action > 0


# ---------------------------------------------------------------------------
# It refuses
# ---------------------------------------------------------------------------


def test_a_flat_indicator_is_not_trending():
    """A slope fitted to noise extrapolates to nonsense with great confidence,
    and a planner cannot tell the difference by looking."""
    r = FaultRul()
    _feed(r, "cooling_degradation", start=2.0, rate=0.0, noise=0.8)
    f = r.forecast("cooling_degradation")
    assert f.status == "not trending"
    assert not f.reportable


def test_an_improving_indicator_is_never_reported_as_a_deadline():
    r = FaultRul()
    _feed(r, "cooling_degradation", start=8.0, rate=-0.25, noise=0.2)
    f = r.forecast("cooling_degradation")
    assert f.status == "improving"
    assert not f.reportable


def test_too_little_history_produces_no_estimate():
    """Fitting a line through a handful of points is arithmetic, not a
    forecast."""
    r = FaultRul()
    _feed(r, "cooling_degradation", start=2.0, rate=0.5, n=5)
    f = r.forecast("cooling_degradation")
    assert f.status == "no data"
    assert not f.reportable
    assert "samples" in f.reason


def test_an_indicator_already_past_its_threshold_reports_reached():
    """That is a DETECTION result. Reporting "0 hours" as a forecast would let
    a planner read a present exceedance as a future one."""
    r = FaultRul()
    _feed(r, "cooling_degradation", start=12.0, rate=0.1, noise=0.1)
    f = r.forecast("cooling_degradation")
    assert f.status == "reached"
    assert not f.reportable


def test_a_mode_that_is_never_observed_says_so():
    """A mode with no measured signal must not acquire a forecast."""
    r = FaultRul()
    f = r.forecast("misfire")
    assert f.status == "no data"
    assert not f.reportable


# ---------------------------------------------------------------------------
# It stays tied to the configured thresholds
# ---------------------------------------------------------------------------


def test_every_ps_fault_mode_has_an_indicator():
    """Section C names eight. A mode with no indicator can never be
    predicted, only detected."""
    from layer2_physics.degradation import FAULT_CLASS_ORDER

    for mode in FAULT_CLASS_ORDER:
        assert mode in INDICATORS, f"{mode} has no progression indicator"


def test_thresholds_come_from_the_config_not_the_code():
    """A retuned threshold must move this prediction with it, or the forecast
    and the alert that fires at the same point will disagree."""
    cfg = config.load_thresholds()["faults"]
    r = FaultRul()
    for mode, ind in INDICATORS.items():
        if ind.fault_key is None:
            continue
        assert ind.fault_key in cfg[mode], f"{mode}.{ind.fault_key} missing"
        assert r._threshold(mode, ind.fault_key, 0.0) == float(
            cfg[mode][ind.fault_key]
        )


def test_the_soonest_fault_is_the_one_reported_first():
    """A planner reads top-down, so the ordering is the recommendation."""
    r = FaultRul()
    # Both must still be BELOW their thresholds at the end of the window, or
    # they report "reached" -- which is a detection result, not a forecast.
    # Cooling: 4.0 -> 7.4 degC of 10.0 over 22.5 h, crossing in about 17 h.
    # Injector: 90 -> 112 degC of 150 over the same span, crossing in about 37.
    _feed(r, "cooling_degradation", start=4.0, rate=0.15, noise=0.2)
    _feed(r, "injector_abnormal", start=90.0, rate=1.0, noise=2.0)
    rows = r.all_forecasts()
    reportable = [x for x in rows if x["reportable"]]
    assert len(reportable) >= 2
    hours = [x["hours_to_action"] for x in reportable]
    assert hours == sorted(hours)
    assert r.soonest().mode == reportable[0]["mode"]


# ---------------------------------------------------------------------------
# Review fixes: stale readings, intermittent faults, live tick rate
# ---------------------------------------------------------------------------


def test_a_reading_that_stops_arriving_expires():
    """SAF-09. The last cruise value used to be reported, and acted on,
    indefinitely after the indicator went silent."""
    r = FaultRul()
    _feed(r, "abnormal_vibration", start=6.0, rate=0.0, noise=0.1, n=40)
    assert r.forecast("abnormal_vibration").status == "reached"
    for k in range(12):
        r.observe(9.75 + (k + 1) * 0.1, {"abnormal_vibration": None})
    f = r.forecast("abnormal_vibration")
    assert f.status == "no data"
    assert f.value is None
    assert "old" in f.reason


def test_an_intermittent_fault_is_not_averaged_away():
    """ML-11. Present in 40 % of samples, a fault never moved a median."""
    r = FaultRul()
    for k in range(60):
        v = 8.0 if (k % 5) < 2 else 1.0
        r.observe(k * 0.5 / 3600.0, {"misfire": v})
    assert r.forecast("misfire").status == "reached"


def test_one_noisy_sample_still_cannot_report_reached():
    r = FaultRul()
    for k in range(60):
        v = 8.0 if k == 55 else 1.0
        r.observe(k * 0.5 / 3600.0, {"misfire": v})
    assert r.forecast("misfire").status != "reached"


def test_a_slow_real_trend_is_seen_at_the_live_tick_rate():
    """ML-03. At the live 0.5 s tick a 240-sample window spanned two minutes,
    so a genuine trend measured in hours was invisible."""
    r = FaultRul()
    dt = 0.5 / 3600.0
    rng = np.random.default_rng(5)
    for k in range(int(2.0 / dt)):
        h = k * dt
        r.observe(h, {"cooling_degradation": 2.0 + 1.0 * h + rng.normal(0.0, 0.4)})
    f = r.forecast("cooling_degradation")
    assert f.status == "trending"
    assert f.rate_per_hour == pytest.approx(1.0, abs=0.3)
