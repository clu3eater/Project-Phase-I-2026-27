"""Tests for battery state of health (gap G4).

The property that matters most here is a refusal. Internal resistance is only
visible while the pack is supplying current, so an estimator that produced a
number at cruise would be inventing one. Several of these tests check that it
declines to answer, and say why that is the correct behaviour.
"""

from __future__ import annotations

import numpy as np
import pytest

from common import config
from layer3_ai.battery import BatteryHealth


def _discharge(b: BatteryHealth, r_pack: float, *, n=40, hours=1.0, seed=0):
    """Simulate a discharge event at a known pack resistance."""
    rng = np.random.default_rng(seed)
    est = None
    for _ in range(n):
        i = 4.0 + 12.0 * rng.random()
        v = 28.0 * 0.96 - i * r_pack + rng.normal(0, 0.01)
        est = b.update(bus_voltage=v, alternator_current=2.0, rpm=900.0,
                       flight_hours=hours, battery_current=i)
    return est


# ---------------------------------------------------------------------------
# It recovers the right number
# ---------------------------------------------------------------------------


def test_it_recovers_a_known_pack_resistance():
    """V = OCV - I x R, so the slope of terminal voltage against current is -R."""
    b = BatteryHealth()
    est = _discharge(b, 0.096)
    assert est.internal_resistance_ohm == pytest.approx(0.096, rel=0.05)
    assert est.open_circuit_v == pytest.approx(26.88, abs=0.2)


def test_state_of_health_spans_new_to_end_of_life():
    new = _discharge(BatteryHealth(), 0.096).soh
    half = _discharge(BatteryHealth(), 0.144).soh
    dead = _discharge(BatteryHealth(), 0.192).soh
    assert new > 0.95
    assert 0.4 < half < 0.6
    assert dead < 0.05


def test_it_compares_pack_against_pack_not_against_a_cell():
    """The configured resistance is PER CELL and the fit sees the whole pack.

    Comparing a fitted pack resistance against a per-cell reference reported a
    brand-new battery as eight times end-of-life -- the defect that exposed an
    unexplained literal 8 in the physics model.
    """
    b = BatteryHealth()
    el = config.load_engine("rotax_915is")["electrical"]
    cells = float(el["battery_cells_series"])
    per_cell = float(el["battery_internal_resistance_new_ohm"])
    assert b.r_new == pytest.approx(per_cell * cells)
    assert _discharge(BatteryHealth(), per_cell * cells).soh > 0.95


# ---------------------------------------------------------------------------
# It refuses to answer when it cannot know
# ---------------------------------------------------------------------------


def test_it_reports_nothing_before_a_discharge_event():
    """A pack that has never supplied current has revealed nothing."""
    b = BatteryHealth()
    est = b.update(bus_voltage=28.9, alternator_current=8.0, rpm=5200.0,
                   battery_current=0.0)
    assert est.soh is None
    assert not est.reportable
    assert not est.observable_now


def test_a_constant_current_cannot_identify_a_slope():
    """Several samples at one current fit a line through a single point.

    This is not a hypothetical: with the simulator's electrical load pinned at
    a constant 8 A, the current spanned 0.80 A and the estimator correctly
    refused to report a state of health for the whole life of the engine.
    """
    b = BatteryHealth()
    est = None
    for _ in range(40):
        est = b.update(bus_voltage=27.0, alternator_current=2.0, rpm=900.0,
                       battery_current=10.0)
    assert est.soh is None
    assert "not enough variation" in est.reason


def test_it_says_so_when_there_is_no_battery_shunt():
    """Alternator current during a discharge is pinned at what the generator
    can supply and says nothing about the pack.

    An installation without a shunt cannot have battery SOH at all, and the
    honest response is to name the missing instrument rather than guess.
    """
    b = BatteryHealth()
    est = b.update(bus_voltage=27.0, alternator_current=11.0, rpm=900.0,
                   battery_current=None)
    assert est.soh is None
    assert "no battery shunt" in est.reason


def test_a_charging_battery_is_not_a_discharge_event():
    """Negative current is the alternator recharging the pack. The V-I
    relationship then describes the charger, not the battery's resistance."""
    b = BatteryHealth()
    for _ in range(40):
        est = b.update(bus_voltage=28.9, alternator_current=20.0, rpm=5000.0,
                       battery_current=-6.0)
    assert est.soh is None


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------


def test_the_last_measurement_survives_but_is_dated():
    """A reading taken two hundred hours ago is a historical fact, not a
    current one, and an operator should be told which they are looking at."""
    b = BatteryHealth()
    _discharge(b, 0.12, hours=10.0)
    fresh = b.confidence()

    est = b.update(bus_voltage=28.9, alternator_current=8.0, rpm=5200.0,
                   flight_hours=210.0, battery_current=0.0)
    assert est.soh is not None, "the last measurement must survive"
    assert est.hours_since_measured == pytest.approx(200.0)
    assert b.confidence() < fresh * 0.5
    assert not est.observable_now


def test_confidence_is_zero_with_no_measurement_at_all():
    assert BatteryHealth().confidence() == 0.0


def test_a_non_physical_fit_is_rejected():
    """A negative resistance is not a very healthy battery."""
    b = BatteryHealth()
    rng = np.random.default_rng(0)
    est = None
    for _ in range(30):
        i = 4.0 + 12.0 * rng.random()
        est = b.update(bus_voltage=26.0 + 0.5 * i, alternator_current=2.0,
                       rpm=900.0, battery_current=i)   # voltage RISES with load
    assert est.soh is None


def test_the_estimate_serialises_for_the_api():
    import json

    json.dumps(_discharge(BatteryHealth(), 0.11).as_dict())


# ---------------------------------------------------------------------------
# The physics it is estimating
# ---------------------------------------------------------------------------


def test_the_pack_ages_on_both_cycles_and_hours():
    """A battery left on a shelf still dies, and each start is the largest
    single current it ever sees. Both clocks have to run."""
    from layer2_physics.degradation import DegradationEngine

    eng = config.load_engine("rotax_915is")
    hours_only = DegradationEngine(engine=eng)
    for _ in range(400):
        hours_only.advance(1.0, oil_temp_c=98.0, cht_max_c=107.0)

    cycles_too = DegradationEngine(engine=eng)
    for _ in range(400):
        cycles_too.advance(1.0, oil_temp_c=98.0, cht_max_c=107.0)
        cycles_too.record_start_cycle()

    assert hours_only.factors.battery_health < 1.0
    assert cycles_too.factors.battery_health < hours_only.factors.battery_health


def test_battery_current_closes_the_electrical_node():
    """Whatever the alternator cannot supply comes out of the pack."""
    from layer2_physics import mvem
    from layer2_physics.atmosphere import ambient_at

    m = mvem.build("rotax_915is")
    amb = ambient_at(5000.0)
    out = None
    for _ in range(80):
        out = m.step(0.5, throttle_pct=20.0, ambient=amb, electrical_load_a=14.0)
    assert out.battery_current_a == pytest.approx(
        14.0 - out.alternator_current_a, abs=1e-6
    )
