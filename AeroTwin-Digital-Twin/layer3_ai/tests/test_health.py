"""Tests for the health indices of PRD Part 2 sections 9.2 to 9.4.

The composite health index is the number an operator reads first and every
maintenance decision hangs off, so the tests here are less about arithmetic
than about two properties that decide whether it is usable at all:

  * it must mean the same thing at idle and at take-off power
  * it must not call a healthy engine degraded

The first test documents the specified formula failing the first property, so
nobody restores it by accident.
"""

from __future__ import annotations

import numpy as np
import pytest

from layer3_ai import health as hl


# ---------------------------------------------------------------------------
# The operating-point problem
# ---------------------------------------------------------------------------


def test_absolute_thermal_index_falls_with_power_on_a_healthy_engine():
    """The defect in PRD Part 2 s9.2, pinned.

    THI = 1 - (CHT - 105)/(135 - 105) reads DEGRADED whenever the engine is
    working hard. Measured on 83,000 rows from genuinely healthy engines the
    specified formula called 25.7 % of them degraded and 5.6 % faulted.
    """
    cool = hl.thermal_index(100.0, 90.0)
    hot = hl.thermal_index(112.0, 96.0)
    assert cool > 0.95
    assert hot < 0.85, "the specified formula should sag under power"
    assert cool - hot > 0.1


def test_residual_thermal_index_is_flat_across_the_power_range():
    """A residual is measured minus as-new AT THE SAME operating point.

    Both engines below are healthy; one is simply working harder. The residual
    form must not be able to tell them apart, because there is nothing to tell.
    """
    cruise = hl.thermal_index(100.0, 90.0, res_cht=0.5, res_coolant=0.2)
    climb = hl.thermal_index(118.0, 99.0, res_cht=0.5, res_coolant=0.2)
    assert cruise == pytest.approx(climb)
    assert cruise > 0.95


def test_residual_thermal_index_still_catches_real_degradation():
    """Flat under power, but not blind."""
    healthy = hl.thermal_index(108.0, 94.0, res_cht=0.4, res_coolant=0.1)
    fouled = hl.thermal_index(108.0, 94.0, res_cht=18.0, res_coolant=0.3)
    assert healthy > 0.95
    assert fouled < 0.5


# ---------------------------------------------------------------------------
# Individual indices
# ---------------------------------------------------------------------------


def test_an_as_new_engine_scores_a_perfect_composite():
    est = hl.HealthEstimator(use_residuals=True)
    s = est.update({
        "rpm": 5000.0, "cht_max": 105.0, "cht_spread": 1.0,
        "coolant_temperature": 92.0, "egt_spread": 20.0,
        "oil_pressure": 52.0, "oil_pressure_predicted": 52.0,
        "oil_temperature": 95.0, "fuel_flow": 22.0, "fuel_flow_predicted": 22.0,
        "vibration_rms_total": 2.8, "vibration_kurtosis": 3.0,
        "battery_voltage": 28.0, "alternator_current": 40.0,
        "res_cht": 0.0, "res_coolant": 0.0, "res_egt": 0.0,
        "res_oil_pressure": 0.0, "res_oil_temperature": 0.0, "res_fuel_flow": 0.0,
    })
    assert s.chi > 0.97, s.as_dict()
    assert s.band == "EXCELLENT"
    assert s.action == "none"


def test_mechanical_index_nominal_matches_the_three_axis_total():
    """The nominal was the PER-AXIS baseline (2.0) compared against the
    three-axis vector total, which is 2.93 on a healthy engine.

    That scored every healthy engine MHI 0.845, and because mechanical health
    is the minimum of its contributors it capped the composite fleet-wide.
    """
    assert hl.mechanical_index(2.93, 3.0) > 0.95
    assert hl.mechanical_index(7.0, 3.2) < 0.35


def test_mechanical_index_uses_kurtosis_as_the_earlier_warning():
    """Bearing damage produces impulses; kurtosis rises before RMS does."""
    quiet_but_impulsive = hl.mechanical_index(2.9, 8.0)
    quiet_and_smooth = hl.mechanical_index(2.9, 3.0)
    assert quiet_but_impulsive < quiet_and_smooth
    assert quiet_but_impulsive < 0.3


def test_subsystems_take_the_minimum_not_the_average():
    """A subsystem is only as healthy as its worst symptom.

    Averaging lets one good number hide a bad one, which is exactly the case
    where an operator needs to be told.
    """
    est = hl.HealthEstimator(use_residuals=True)
    s = est.update({
        "rpm": 5000.0, "cht_max": 105.0, "coolant_temperature": 92.0,
        "cht_spread": 1.0, "egt_spread": 20.0,
        "oil_pressure": 52.0, "oil_pressure_predicted": 52.0,
        "oil_temperature": 95.0, "fuel_flow": 22.0, "fuel_flow_predicted": 22.0,
        # Perfect thermals, wrecked bearings.
        "vibration_rms_total": 7.5, "vibration_kurtosis": 9.0,
        "battery_voltage": 28.0, "alternator_current": 40.0,
        "res_cht": 0.0, "res_coolant": 0.0, "res_egt": 0.0,
        "res_oil_pressure": 0.0, "res_oil_temperature": 0.0, "res_fuel_flow": 0.0,
    })
    assert s.thermal > 0.95
    assert s.mechanical < 0.2, "the bad symptom must survive the roll-up"
    assert s.chi < 0.85


def test_lubrication_index_uses_the_correlation_term():
    """A weakening oil-pressure/rpm correlation indicates bearing leakage even
    while the pressure itself is still inside limits."""
    strong = hl.lubrication_index(52.0, 52.0, 0.97)
    weak = hl.lubrication_index(52.0, 52.0, 0.40)
    assert strong > 0.95
    assert weak < 0.55


def test_oil_pressure_above_the_as_new_twin_is_a_lubrication_finding():
    """Thickened oil raises pressure at the same speed and temperature.

    Measured: a severity-0.9 lubrication fault read 63 psi against the twin's
    54 and the index stayed at a perfect 1.000, because only a shortfall was
    scored. The healthy scatter (about 0.35 psi) must still read as sound.
    """
    assert hl.lubrication_index(None, 54.0, None, res_oil_pressure=9.5) < 0.85
    assert hl.lubrication_index(None, 54.0, None, res_oil_pressure=0.35) > 0.99
    # Symmetric: 10 % high costs what 10 % low does.
    high = hl.lubrication_index(None, 50.0, None, res_oil_pressure=5.0)
    low = hl.lubrication_index(None, 50.0, None, res_oil_pressure=-5.0)
    assert high == pytest.approx(low)


def test_high_oil_pressure_cannot_buy_back_a_weak_correlation():
    """Pressure above prediction used to multiply a weak correlation back up."""
    on_twin = hl.lubrication_index(None, 50.0, 0.80, res_oil_pressure=0.0)
    above = hl.lubrication_index(None, 50.0, 0.80, res_oil_pressure=5.0)
    assert above < on_twin


def test_correlation_is_dropped_when_rpm_barely_moves():
    """In a steady cruise there is no signal to correlate.

    Correlating one noise sequence against another returns a number between
    -1 and +1 that means nothing, and it multiplies straight into the
    lubrication index.
    """
    est = hl.HealthEstimator()
    for _ in range(60):
        est._push({"rpm": 5000.0 + np.random.default_rng(0).normal(0, 0.3),
                   "oil_pressure": 52.0})
    assert est._correlation() is None


def test_electrical_index_renormalises_without_battery_soh():
    """Battery SOH needs internal-resistance trending no channel provides.

    Scoring it a constant 1.0 would hand every engine a free 0.2 of the
    electrical index. Gap G4.
    """
    without = hl.electrical_index(0.05, 40.0, bus_voltage=28.0)
    assert without > 0.95
    # A collapsed bus must show, not be diluted by a phantom third term.
    assert hl.electrical_index(0.05, 4.0, bus_voltage=23.0) < 0.7


def test_electrical_index_does_not_penalise_a_light_electrical_load():
    """I_actual / I_rated is a LOAD measure, not a health measure.

    An alternator supplying 8 A of a 40 A rating is meeting the demand that
    exists. Taken literally the PRD term scored a healthy engine EHI 0.68,
    which under the worst-subsystem rule raised "ELECTRICAL subsystem POOR" on
    an aircraft with nothing wrong -- a MIL-STD-411F 4.1.1a violation.
    """
    light = hl.electrical_index(0.05, 8.0, bus_voltage=28.9)
    heavy = hl.electrical_index(0.05, 38.0, bus_voltage=28.9)
    assert light > 0.95
    assert light == pytest.approx(heavy, abs=1e-9)


def test_electrical_index_catches_a_dead_alternator_on_a_sagging_bus():
    """The battery carries the load for a while, so voltage alone is slow.

    Near-zero output with the bus already below regulation is the case worth
    catching before the battery goes flat.
    """
    assert hl.electrical_index(0.05, 0.1, bus_voltage=26.5) < 0.6


def test_egt_efficiency_factor_signs_match_the_prd():
    """Positive EEF = lean or degraded combustion; negative = rich or cooling."""
    assert hl.egt_efficiency_factor(-40.0, 800.0) > 0
    assert hl.egt_efficiency_factor(+40.0, 800.0) < 0
    assert hl.egt_efficiency_factor(None, 800.0) == 0.0


def test_indices_are_bounded_to_the_unit_interval():
    """Nothing downstream should ever have to clamp a health index."""
    extremes = [
        hl.thermal_index(400.0, 300.0),
        hl.thermal_index(-50.0, -50.0),
        hl.cht_spread_index(500.0),
        hl.combustion_index(9999.0),
        hl.oil_thermal_index(400.0),
        hl.mechanical_index(500.0, 100.0),
        hl.lubrication_index(0.0, 52.0, 0.0),
        hl.rpm_stability_index(9999.0, 5000.0),
        hl.fuel_system_index(500.0, 22.0),
    ]
    assert all(0.0 <= v <= 1.0 for v in extremes), extremes


# ---------------------------------------------------------------------------
# Bands
# ---------------------------------------------------------------------------


def test_bands_match_the_prd_table():
    assert hl.band_for(0.95)[0] == "EXCELLENT"
    assert hl.band_for(0.85)[0] == "GOOD"
    assert hl.band_for(0.75)[0] == "FAIR"
    assert hl.band_for(0.65)[0] == "POOR"
    assert hl.band_for(0.55)[0] == "DEGRADED"
    assert hl.band_for(0.45)[0] == "CRITICAL"
    assert hl.band_for(0.20)[0] == "UNSAFE"


def test_each_band_carries_an_action_not_just_a_label():
    """A colour with no instruction is decoration."""
    for chi in (0.95, 0.75, 0.65, 0.55, 0.45, 0.10):
        label, action = hl.band_for(chi)
        assert label and action


# ---------------------------------------------------------------------------
# Trend, PRD Part 2 section 9.4
# ---------------------------------------------------------------------------


def test_ema_smoothing_is_slow_by_design():
    """alpha = 0.1. A single noisy sample must not move the displayed index."""
    est = hl.HealthEstimator()
    for _ in range(30):
        est.track(1.0)
    before = est._chi_ema
    est.track(0.0)   # one catastrophic outlier
    assert est._chi_ema > before - 0.15, "one bad sample moved the index too far"


def test_cusum_finds_the_onset_not_the_limit_crossing():
    """The knee is the number a maintenance planner can act on.

    A raw index never shows it, because the decline is buried in noise until
    it is already large.
    """
    est = hl.HealthEstimator()
    rng = np.random.default_rng(0)
    # 200 healthy hours to establish this engine's own baseline, then a
    # slow decline away from it.
    for h in range(200):
        est.track(float(np.clip(0.97 + rng.normal(0, 0.005), 0, 1)), float(h))
    assert not est.onset_detected, "CUSUM tripped on noise alone"
    for h in range(200, 400):
        est.track(max(0.0, 0.97 - 0.004 * (h - 200)), float(h))
    assert est.onset_detected
    assert est.onset_hours is not None
    # It must fire well before health reaches the maintenance threshold.
    assert est.onset_hours < 320


def test_cusum_does_not_trip_on_a_healthy_engine():
    """MIL-STD-411F 4.1.1a reaches the trend detector too."""
    est = hl.HealthEstimator()
    rng = np.random.default_rng(1)
    for h in range(1000):
        est.track(float(np.clip(0.97 + rng.normal(0, 0.01), 0, 1)), float(h))
    assert not est.onset_detected


def test_track_reports_the_smoothed_value_and_the_cusum():
    est = hl.HealthEstimator()
    out = est.track(0.9, 10.0)
    assert set(out) >= {"chi_ema", "cusum", "onset_detected"}
    assert 0.0 <= out["chi_ema"] <= 1.0
    assert out["cusum"] >= 0.0


def test_cusum_baselines_on_the_engines_own_level_not_on_as_new():
    """An engine settled at 0.90 must not read as continuously degrading.

    With the baseline assumed to be 1.0 every sample contributes a positive
    increment and the detector trips on everything.
    """
    est = hl.HealthEstimator()
    for h in range(400):
        est.track(0.90, float(h))
    assert not est.onset_detected
    assert est._baseline == pytest.approx(0.90, abs=1e-6)


def test_the_correlation_ignores_the_relief_valve_band():
    """Above the relief valve's regulating pressure oil pressure is held flat by
    design, so rpm stops predicting it on a perfectly healthy engine.

    Once the propeller holds speed at altitude, most cruise settings sit on
    that plateau, and the whole-range correlation of an as-new engine fell to
    0.94 -- under the 0.95 nominal, which the lubrication index reads as wear.
    Only the band where pressure follows speed is correlated.
    """
    est = hl.HealthEstimator()
    ceiling = float(hl._h()["lhi"]["correlation_below_psi"])
    rng = np.random.default_rng(1)
    for i in range(60):
        rpm = 2500.0 + 60.0 * i                   # 2500 -> 6040 rpm
        psi = min(10.0 + 0.0095 * rpm, 59.0)      # follows speed, then regulated
        est._push({"rpm": rpm, "oil_pressure": psi + rng.normal(0.0, 0.2)})
    r = est._correlation()
    assert r is not None and r > 0.98
    whole = float(np.corrcoef(np.array(est._rpm), np.array(est._oil))[0, 1])
    assert whole < r, "the plateau is what weakened the whole-range figure"
    assert sum(1 for p in est._oil if p < ceiling) >= 10


def test_the_correlation_is_dropped_when_everything_sits_on_the_relief_valve():
    """All samples regulated: there is no speed-driven band to judge, so the
    term is dropped rather than read as a lubrication fault."""
    est = hl.HealthEstimator()
    for i in range(60):
        est._push({"rpm": 5000.0 + 15.0 * i, "oil_pressure": 59.0 + 0.01 * (i % 3)})
    assert est._correlation() is None
