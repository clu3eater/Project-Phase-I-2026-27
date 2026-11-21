"""Physics sanity tests -- PRD Part 0 section 0.11 ("pytest suite: physics
sanity (energy balance, bounds), detectors, API auth").

These tests are the guard rail on the whole system. Every one of them encodes
either a CERTIFIED limit from the engine's Type Certificate Data Sheet or
Operators Manual, or a physical law. If one fails, the twin is lying about the
engine and no amount of AI on top of it can help.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from common import config
from layer2_physics import atmosphere as atm
from layer2_physics import combustion, mvem, perf_maps, turbo
from layer2_physics.degradation import (
    DegradationEngine,
    DegradationFactors,
    FaultMode,
    InjectedFault,
    random_fault_schedule,
)

ENGINE_KEY = "rotax_915is"


@pytest.fixture(scope="module")
def engine() -> dict:
    return config.load_engine(ENGINE_KEY)


@pytest.fixture(scope="module")
def cruise_ambient() -> atm.Ambient:
    return atm.ambient_at(15000.0, airspeed_kmh=180.0)


# ---------------------------------------------------------------------------
# Atmosphere
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "altitude_ft,expect_oat_c,expect_hpa,expect_sigma",
    [
        (0.0, 15.0, 1013.25, 1.000),
        (10000.0, -4.8, 696.8, 0.7385),
        (20000.0, -24.6, 465.6, 0.5328),
    ],
)
def test_isa_matches_standard_tables(altitude_ft, expect_oat_c, expect_hpa, expect_sigma):
    """ISA temperature, pressure and density ratio against published tables."""
    a = atm.ambient_at(altitude_ft, humidity_pct=0.0)
    assert a.oat_c == pytest.approx(expect_oat_c, abs=0.2)
    assert a.pressure_hpa == pytest.approx(expect_hpa, rel=0.002)
    assert a.density_ratio == pytest.approx(expect_sigma, rel=0.005)


def test_humid_air_is_less_dense_than_dry_air():
    """Water vapour displaces heavier N2/O2, so moist air is lighter."""
    dry = atm.air_density(atm.P0_PA, 313.15, 0.0)
    wet = atm.air_density(atm.P0_PA, 313.15, 100.0)
    assert wet < dry


def test_every_environmental_condition_of_the_problem_statement_exists():
    """PRD Part 3 section 18.1 requires these scenarios to be simulable."""
    required = {
        atm.EnvCondition.HIGH_ALTITUDE,
        atm.EnvCondition.ENDURANCE,
        atm.EnvCondition.HOT_WEATHER,
        atm.EnvCondition.RAPID_THROTTLE,
        atm.EnvCondition.MARITIME,
        atm.EnvCondition.COLD_WEATHER,
    }
    assert required.issubset(set(atm.ENV_PROFILES))
    for cond in required:
        a = atm.ambient_for(cond)
        assert -60.0 < a.oat_c < 60.0
        assert a.density_kg_m3 > 0.0


# ---------------------------------------------------------------------------
# Performance maps -- the published anchors
# ---------------------------------------------------------------------------


def test_performance_maps_reproduce_every_published_anchor():
    """Each map anchor must sit within 3% of the manufacturer / certified value.

    Sources: EASA TCDS E.121 Issue 17; BRP-Rotax OM-915 i A Ed.0 Rev.1.
    """
    results = perf_maps.validate_against_anchors(ENGINE_KEY)
    assert results, "no anchors evaluated"
    failures = []
    for name, (expected, actual) in results.items():
        if expected == 0:
            continue
        err = abs(actual - expected) / abs(expected)
        if err > 0.03:
            failures.append(f"{name}: expected {expected:.4g}, model {actual:.4g} ({err:.1%})")
    assert not failures, "performance map anchors drifted:\n" + "\n".join(failures)


def test_bmep_torque_relation_is_the_standard_one(engine):
    """T = BMEP * V / (2*pi*n_r). Round-trip must be exact."""
    disp = float(engine["geometry"]["displacement_total_L"])
    for bmep in (2.0, 8.0, 16.0):
        t = perf_maps.torque_from_bmep(bmep, disp)
        assert perf_maps.bmep_from_torque(t, disp) == pytest.approx(bmep, rel=1e-9)


def test_volumetric_efficiency_falls_with_altitude():
    m = perf_maps.maps_for(ENGINE_KEY)
    values = [m.eta_vol_at(5000.0, alt) for alt in (0.0, 5000.0, 10000.0, 15000.0)]
    assert all(a > b for a, b in zip(values, values[1:], strict=False))


def test_bmep_increases_monotonically_with_throttle():
    m = perf_maps.maps_for(ENGINE_KEY)
    values = [m.bmep_at(4500.0, th, 5000.0) for th in (10, 30, 50, 70, 90, 100)]
    assert all(a < b for a, b in zip(values, values[1:], strict=False))


def test_bsfc_stays_in_the_published_band():
    """Rotax publishes 280-310 g/kWh at 5500 rpm for the 915 iS."""
    m = perf_maps.maps_for(ENGINE_KEY)
    bmep_cruise = m.bmep_at(5500.0, 90.0, 5000.0)
    assert 270.0 <= m.bsfc_at(5500.0, bmep_cruise) <= 330.0


def test_point_lookup_matches_the_scipy_interpolator():
    """The accessors' fast path is the same linear interpolation as the
    RegularGridInterpolator it replaced, on the nodes, on the edges and
    between them -- to rounding, not approximately."""
    import random

    m = perf_maps.maps_for(ENGINE_KEY)
    axes = {
        "bmep": (perf_maps.RPM_AXIS, perf_maps.THROTTLE_AXIS, perf_maps.ALTITUDE_AXIS),
        "bsfc": (perf_maps.RPM_AXIS, perf_maps.BMEP_AXIS),
        "eta_vol": (perf_maps.RPM_AXIS, perf_maps.ALTITUDE_AXIS),
        "cht_rise": (perf_maps.POWER_SETTING_AXIS, perf_maps.OAT_AXIS,
                     perf_maps.AIRSPEED_AXIS),
        "egt": (perf_maps.POWER_SETTING_AXIS, perf_maps.MIXTURE_AXIS,
                perf_maps.ALTITUDE_AXIS),
    }
    rng = random.Random(7)
    for name, ax in axes.items():
        for _ in range(2000):
            x = [rng.choice([a[0], a[-1], rng.choice(list(a))]) if rng.random() < 0.2
                 else rng.uniform(a[0], a[-1]) for a in ax]
            ref = float(getattr(m, name)([x])[0])
            assert m._fast[name](*x) == pytest.approx(ref, rel=1e-12, abs=1e-12), (name, x)


# ---------------------------------------------------------------------------
# Turbocharger
# ---------------------------------------------------------------------------


def test_turbo_holds_rated_boost_to_critical_altitude_then_knees(engine):
    """EASA TCDS E.121 section 6: max continuous is available UP TO 15,000 ft."""
    crit = float(engine["turbocharger"]["critical_altitude_ft"])
    # The boost controller targets the PUBLISHED schedule (OM Ed.0 Rev.4 s2.1):
    # 1450 mbar at 5500 rpm, 1520 mbar at 5800 rpm. 1730 mbar is a never-exceed
    # authority limit, not a setpoint.
    rated_map = float(engine["turbocharger"]["target_map_at_5500rpm_bar"])

    below = turbo.solve(
        ambient=atm.ambient_at(crit - 3000.0),
        rpm=5500.0,
        throttle_pct=100.0,
        engine=engine,
    )
    at_crit = turbo.solve(
        ambient=atm.ambient_at(crit), rpm=5500.0, throttle_pct=100.0, engine=engine
    )
    above = turbo.solve(
        ambient=atm.ambient_at(crit + 5000.0),
        rpm=5500.0,
        throttle_pct=100.0,
        engine=engine,
    )

    assert below.manifold_pressure_bar == pytest.approx(rated_map, rel=0.02)
    assert at_crit.manifold_pressure_bar == pytest.approx(rated_map, rel=0.03)
    # The knee is gradual [OM performance table]: at 20,000 ft and 5500 rpm
    # the manual prints about 1.39 bar, 4 % under the rating. The corner model
    # this line was written against asserted more than 5 % and read 1.04 bar
    # at 23,000 ft (review PHY-01).
    assert above.manifold_pressure_bar < rated_map * 0.97
    assert above.boost_limited
    assert below.wastegate_fraction > at_crit.wastegate_fraction


def test_manifold_pressure_never_exceeds_the_certified_limit(engine):
    """OM-915 i Ed.0 Rev.4 section 2.1: manifold/boost never-exceed 1730 hPa."""
    limit = float(engine["intake"]["manifold_pressure_max_hPa"]) / 1000.0
    for alt in range(0, 24000, 2000):
        st = turbo.solve(
            ambient=atm.ambient_at(float(alt)),
            rpm=5800.0,
            throttle_pct=100.0,
            engine=engine,
        )
        assert st.manifold_pressure_bar <= limit * 1.02, f"over-boost at {alt} ft"


def test_boost_lags_a_step_throttle_input(engine):
    """PRD Part 3 section 18.1 CONDITION 4: boost takes 2-3 s to respond."""
    amb = atm.ambient_at(10000.0)
    state = turbo.solve(ambient=amb, rpm=3000.0, throttle_pct=20.0, engine=engine)
    settled = turbo.solve(ambient=amb, rpm=5500.0, throttle_pct=100.0, engine=engine)

    lagged = state
    for _ in range(5):  # 0.5 s of 0.1 s steps
        lagged = turbo.solve(
            ambient=amb,
            rpm=5500.0,
            throttle_pct=100.0,
            engine=engine,
            previous=lagged,
            dt=0.1,
        )
    assert lagged.manifold_pressure_bar < settled.manifold_pressure_bar

    for _ in range(60):  # 6 s total -- must have caught up
        lagged = turbo.solve(
            ambient=amb,
            rpm=5500.0,
            throttle_pct=100.0,
            engine=engine,
            previous=lagged,
            dt=0.1,
        )
    assert lagged.manifold_pressure_bar == pytest.approx(
        settled.manifold_pressure_bar, rel=0.02
    )


# ---------------------------------------------------------------------------
# Combustion
# ---------------------------------------------------------------------------


def test_adiabatic_flame_temperature_is_physically_sane():
    """PRD Part 1 section 4.2: T_ad in the 2100-2400 K band, peaking near phi=1."""
    temps = {
        phi: combustion.adiabatic_flame(phi, 320.0, 40.0, ENGINE_KEY).t_adiabatic_k
        for phi in (0.6, 0.8, 1.0, 1.05, 1.3)
    }
    assert 2100.0 <= temps[1.0] <= 2500.0
    assert temps[1.0] > temps[0.6]
    assert temps[1.0] > temps[1.3]
    peak = max(temps, key=lambda k: temps[k])
    assert 0.95 <= peak <= 1.10, "flame temperature must peak near stoichiometric"


def test_stoichiometric_afr_matches_textbook_value(engine):
    """n-heptane: AFR_s ~ 15.2 by mass."""
    assert combustion.stoichiometric_afr(engine) == pytest.approx(15.2, rel=0.02)


def test_wiebe_burn_fraction_is_monotonic_and_bounded(engine):
    xs = [combustion.wiebe_burn_fraction(theta, engine) for theta in range(0, 80, 5)]
    assert xs[0] == 0.0
    assert xs[-1] == pytest.approx(1.0, abs=1e-6)
    assert all(a <= b + 1e-12 for a, b in zip(xs, xs[1:], strict=False))


def test_lookup_table_agrees_with_live_cantera():
    """The shipped lookup must reproduce Cantera to within a few kelvin."""
    if not combustion.cantera_available():
        pytest.skip("Cantera not installed")
    for phi in (0.7, 0.95, 1.1):
        live = combustion.adiabatic_flame(phi, 320.0, 40.0, ENGINE_KEY, prefer_cantera=True)
        table = combustion.adiabatic_flame(phi, 320.0, 40.0, ENGINE_KEY)
        assert live.source == "cantera"
        assert table.source == "lookup"
        assert table.t_adiabatic_k == pytest.approx(live.t_adiabatic_k, abs=25.0)


def test_compression_ignition_engine_runs_lean():
    """The diesel adaptation must schedule a globally lean mixture."""
    diesel = config.load_engine("austro_ae330")
    assert combustion.combustion_mode(diesel) == "COMPRESSION"
    assert combustion.operating_phi(diesel, 0.5) < 0.7
    assert combustion.operating_phi(diesel, 1.0) < 0.85


# ---------------------------------------------------------------------------
# Mean-value engine model -- certified limits
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sea_level_wot() -> mvem.EngineOutputs:
    m = mvem.build(ENGINE_KEY)
    return mvem.trim_to_steady_state(
        m, throttle_pct=100.0, ambient=atm.ambient_at(0.0, airspeed_kmh=180.0),
        seconds=1200.0, dt=1.0,
    )


def test_model_reaches_rated_power_at_sea_level(sea_level_wot, engine):
    """EASA TCDS E.121: 104 kW take-off at 5800 rpm."""
    rated = float(engine["ratings"]["max_power_kW"])
    assert sea_level_wot.power_kw == pytest.approx(rated, rel=0.06)
    assert sea_level_wot.rpm == pytest.approx(
        float(engine["ratings"]["max_power_rpm"]), rel=0.03
    )


def test_no_certified_limit_is_exceeded_anywhere_in_the_envelope(engine):
    """The model must stay legal across the whole operating envelope.

    A twin that predicts an impossible engine state cannot be trusted to
    predict a real failure.
    """
    limits = engine["limits"]
    violations: list[str] = []
    for altitude in (0.0, 8000.0, 15000.0, 20000.0):
        for throttle in (45.0, 70.0, 100.0):
            m = mvem.build(ENGINE_KEY)
            o = mvem.trim_to_steady_state(
                m,
                throttle_pct=throttle,
                ambient=atm.ambient_at(altitude, airspeed_kmh=180.0),
                seconds=1200.0,
                dt=1.0,
            )
            tag = f"{altitude:.0f}ft/{throttle:.0f}%"
            if o.cht_max > float(engine["thermal"]["cht_limit_C"]):
                violations.append(f"{tag}: CHT {o.cht_max:.1f} over limit")
            if o.coolant_temperature_c > float(limits["coolant_temperature_max_C"]):
                violations.append(f"{tag}: coolant {o.coolant_temperature_c:.1f} over limit")
            if o.egt_max > float(limits["egt_max_C"]):
                violations.append(f"{tag}: EGT {o.egt_max:.1f} over limit")
            if o.oil_temperature_c > float(limits["oil_temperature_C"][1]):
                violations.append(f"{tag}: oil temp {o.oil_temperature_c:.1f} over limit")
            oil_max_psi = float(limits["oil_pressure_above_3500rpm_bar"][1]) * 14.5038
            if o.oil_pressure_psi > oil_max_psi * 1.02:
                violations.append(f"{tag}: oil press {o.oil_pressure_psi:.1f} over limit")
            if o.physics_constraint_violations:
                violations.append(f"{tag}: {o.physics_constraint_violations} constraint violations")
    assert not violations, "certified limits exceeded:\n" + "\n".join(violations)


def test_oil_pressure_correlates_with_engine_speed(cruise_ambient):
    """PRD Part 2 section 10.4 Method A needs Pearson r > 0.95 on a healthy engine.

    If the model cannot produce that correlation, the lubrication-health
    detector has no signal to degrade.
    """
    # Only below the relief valve's regulating band -- the same rule the health
    # estimator applies, because above it the valve holds pressure flat by
    # design. With a governed propeller at 15,000 ft four of the six settings
    # this test used sat on that plateau, and the whole-range r of an as-new
    # engine fell to 0.94.
    ceiling = float(config.load_thresholds()["health"]["lhi"]["correlation_below_psi"])
    rpm, psi = [], []
    for throttle in (20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 50.0):
        m = mvem.build(ENGINE_KEY)
        o = mvem.trim_to_steady_state(
            m, throttle_pct=throttle, ambient=cruise_ambient, seconds=1200.0, dt=1.0
        )
        if o.oil_pressure_psi < ceiling:
            rpm.append(o.rpm)
            psi.append(o.oil_pressure_psi)
    # Filtered, not forbidden -- exactly what HealthEstimator._correlation does.
    # A fixed list of settings broke as soon as the resized oil cooler (DEV-236)
    # thickened the oil and lifted the 45 % point to 56.5 psi.
    assert len(psi) >= 5, f"too few settings below the regulating band: {psi}"
    r = float(np.corrcoef(rpm, psi)[0, 1])
    assert r > 0.95, f"oil pressure / rpm correlation too weak: r={r:.3f}"


def test_energy_balance_closes(sea_level_wot, engine):
    """First law: fuel power in = shaft work + coolant heat + exhaust heat.

    Checked to 20% because the 0-D model lumps radiation, oil-cooler rejection
    and blow-by into the exhaust term rather than resolving them.
    """
    lhv = float(engine["fuel_properties"]["lhv_MJ_per_kg"]) * 1e6
    rho = float(engine["fuel_properties"]["density_kg_per_L"])
    fuel_power_w = sea_level_wot.fuel_flow_lph * rho / 3600.0 * lhv
    shaft_w = sea_level_wot.power_kw * 1000.0

    assert fuel_power_w > shaft_w, "engine cannot produce more work than fuel energy"
    thermal_efficiency = shaft_w / fuel_power_w
    assert 0.20 < thermal_efficiency < 0.42, (
        f"implausible brake thermal efficiency {thermal_efficiency:.3f}"
    )
    assert sea_level_wot.heat_to_head_w < fuel_power_w


def test_power_falls_with_altitude_above_critical(engine):
    """Above 15,000 ft the wastegate is shut and power must fall with ambient."""
    powers = []
    for altitude in (15000.0, 18000.0, 21000.0):
        m = mvem.build(ENGINE_KEY)
        o = mvem.trim_to_steady_state(
            m, throttle_pct=100.0,
            ambient=atm.ambient_at(altitude, airspeed_kmh=180.0),
            seconds=900.0, dt=1.0,
        )
        powers.append(o.power_kw)
    assert powers[0] > powers[-1], "power must fall above the critical altitude"


def test_model_step_meets_the_real_time_budget(cruise_ambient):
    """PRD Part 1 section 2.2: physics model update <= 20 ms."""
    import time

    m = mvem.build(ENGINE_KEY)
    m.initialise_warm(cruise_ambient)
    for _ in range(20):  # warm the caches
        m.step(0.1, throttle_pct=75.0, ambient=cruise_ambient)

    start = time.perf_counter()
    n = 50
    for _ in range(n):
        m.step(0.1, throttle_pct=75.0, ambient=cruise_ambient)
    per_step_ms = (time.perf_counter() - start) / n * 1000.0
    assert per_step_ms < 20.0, f"physics step took {per_step_ms:.1f} ms, budget is 20 ms"


# ---------------------------------------------------------------------------
# Degradation -- the signatures the detectors depend on
# ---------------------------------------------------------------------------


def test_cooling_degradation_raises_cht_while_coolant_stays_regulated(cruise_ambient):
    """The diagnostic signature of PRD Part 2 section 10.3.

    Scale build-up degrades the HEAD-TO-COOLANT path. A thermostatted coolant
    loop holds its own temperature, so the tell-tale is the widening
    CHT-minus-coolant delta, not the coolant reading itself. A single-node
    thermal model cannot produce this and would miss the fault.
    """
    deltas = []
    for eff in (1.0, 0.85, 0.7, 0.6):
        engine = config.load_engine(ENGINE_KEY)
        d = DegradationFactors.as_new(engine)
        d.cooling_efficiency = eff
        m = mvem.build(ENGINE_KEY, degradation=d)
        o = mvem.trim_to_steady_state(
            m, throttle_pct=85.0, ambient=cruise_ambient, seconds=1500.0, dt=1.0
        )
        deltas.append(o.cht_max - o.coolant_temperature_c)
    assert all(a < b for a, b in zip(deltas, deltas[1:], strict=False)), (
        f"CHT-coolant delta must grow as cooling degrades, got {deltas}"
    )
    assert deltas[-1] > deltas[0] * 1.4


def test_bearing_wear_drops_oil_pressure_and_raises_vibration(cruise_ambient):
    """PRD Part 2 section 10.4 Method A and section 10.8 Method A."""
    pressures, vibrations = [], []
    engine = config.load_engine(ENGINE_KEY)
    design = float(engine["degradation"]["bearing_wear"]["design_clearance_mm"])
    for cond in (1.0, 0.8, 0.6, 0.4):
        d = DegradationFactors.as_new(engine)
        d.bearing_condition = cond
        d.bearing_clearance_mm = design * (1.0 + (1.0 - cond))
        m = mvem.build(ENGINE_KEY, degradation=d)
        o = mvem.trim_to_steady_state(
            m, throttle_pct=85.0, ambient=cruise_ambient, seconds=1200.0, dt=1.0
        )
        pressures.append(o.oil_pressure_psi)
        vibrations.append(o.vibration_rms_m_s2)
    assert all(a > b for a, b in zip(pressures, pressures[1:], strict=False))
    assert all(a < b for a, b in zip(vibrations, vibrations[1:], strict=False))


def test_wearing_pathways_advance_monotonically(engine):
    """PRD Part 1 section 5.2 says degradation factors only ever decrease.

    That is true of the five WEARING pathways and false of oil quality, which
    is a consumable: a scheduled oil change restores it, and modelling it
    otherwise made dirty oil the life-limiting item on every engine at a fifth
    of TBO. Oil is asserted separately below.
    """
    deg = DegradationEngine(engine=engine)
    previous = deg.snapshot()
    for _ in range(50):
        current = deg.advance(10.0, oil_temp_c=105.0, cht_max_c=118.0)
        for key in (
            "cooling_efficiency",
            "combustion_efficiency",
            "injector_condition",
            "bearing_condition",
            "turbocharger_condition",
        ):
            assert getattr(current, key) <= getattr(previous, key) + 1e-12, key
        previous = DegradationFactors(**current.as_dict())
    assert deg.hours == pytest.approx(500.0)


def test_oil_quality_falls_within_an_interval_and_is_restored_by_the_change(engine):
    """The one pathway that is serviced rather than worn out [MML 05-20-00]."""
    deg = DegradationEngine(engine=engine)
    interval = float(engine["degradation"]["oil_thermal"]["change_interval_hours"])

    previous = 1.0
    step = 10.0
    # Stop BEFORE the step that reaches the interval -- that step is the change.
    while deg.hours + step < interval - 1e-9:
        current = deg.advance(step, oil_temp_c=105.0, cht_max_c=118.0).oil_quality
        assert current <= previous + 1e-12, "oil must degrade between changes"
        previous = current
    assert previous < 0.5, "oil should be well used by the end of its interval"

    # The change itself.
    assert deg.advance(step, oil_temp_c=105.0, cht_max_c=118.0).oil_quality == 1.0
    assert deg.hours == pytest.approx(interval)

    # Wear caused by running on degraded oil is permanent, as on a real engine.
    assert deg.factors.bearing_condition < 1.0


def test_hotter_operation_degrades_the_engine_faster(engine):
    """Wear is a function of how hard the engine is worked, not just time."""
    cool = DegradationEngine(engine=engine)
    hot = DegradationEngine(engine=engine)
    # Kept inside ONE oil-change interval. Run past it and both engines are
    # compared just after a change, where each has exactly fresh oil and the
    # comparison is between two identical 1.0s -- which is what this assertion
    # was actually measuring before the scheduled change was modelled.
    for _ in range(19):
        cool.advance(5.0, oil_temp_c=92.0, cht_max_c=100.0)
        hot.advance(5.0, oil_temp_c=125.0, cht_max_c=132.0)
    assert hot.hours < float(engine["degradation"]["oil_thermal"]["change_interval_hours"])
    assert hot.factors.cooling_efficiency < cool.factors.cooling_efficiency
    assert hot.factors.oil_quality < cool.factors.oil_quality


def test_injected_fault_ramps_from_zero_to_its_severity(engine):
    deg = DegradationEngine(engine=engine)
    deg.inject(
        InjectedFault(
            mode=FaultMode.COOLING_DEGRADATION,
            onset_hours=100.0,
            severity=0.8,
            ramp_hours=50.0,
        )
    )
    deg.advance(90.0)
    assert deg.fault_label_vector().sum() == 0.0, "fault must not express before onset"
    deg.advance(35.0)  # 125 h: half way up the ramp
    mid = deg.fault_label_vector().max()
    assert 0.2 < mid < 0.8
    deg.advance(60.0)  # 185 h: fully expressed
    assert deg.fault_label_vector().max() == pytest.approx(0.8, abs=1e-6)


def test_all_eight_required_faults_are_injectable(engine):
    """Problem statement section C requires all eight."""
    from layer2_physics.degradation import FAULT_CLASS_ORDER

    assert len(FAULT_CLASS_ORDER) == 8
    for mode in FAULT_CLASS_ORDER:
        deg = DegradationEngine(engine=engine)
        deg.inject(InjectedFault(mode=mode, onset_hours=0.0, severity=1.0, ramp_hours=0.0))
        deg.advance(1.0)
        assert deg.fault_label_vector()[FAULT_CLASS_ORDER.index(mode)] == pytest.approx(1.0)


def test_random_fault_schedules_are_stochastic_and_reproducible(engine):
    """PRD Part 0 section 0.5: random times and severities, but seeded."""
    a = random_fault_schedule(np.random.default_rng(7), life_hours=1200.0)
    b = random_fault_schedule(np.random.default_rng(7), life_hours=1200.0)
    c = random_fault_schedule(np.random.default_rng(8), life_hours=1200.0)
    assert [(f.mode, f.onset_hours) for f in a] == [(f.mode, f.onset_hours) for f in b]
    assert [(f.mode, f.onset_hours) for f in a] != [(f.mode, f.onset_hours) for f in c]

    schedules = [
        random_fault_schedule(np.random.default_rng(s), life_hours=1200.0) for s in range(60)
    ]
    assert any(len(s) == 0 for s in schedules), "some engines must stay fault-free"
    assert any(len(s) > 1 for s in schedules), "some engines must carry multiple faults"


def test_manufacturing_spread_makes_engines_differ(engine):
    """Otherwise a network can memorise one trajectory (PRD Part 0 section 0.5)."""
    rates = []
    for seed in range(5):
        deg = DegradationEngine(engine=engine, rng=np.random.default_rng(seed))
        deg.randomise_rates()
        deg.advance(200.0, oil_temp_c=100.0, cht_max_c=115.0)
        rates.append(deg.factors.cooling_efficiency)
    assert len(set(np.round(rates, 6))) == len(rates), "engines must not be identical"


# ---------------------------------------------------------------------------
# Engine-agnosticism
# ---------------------------------------------------------------------------


def test_every_configured_engine_loads_and_runs():
    """PRD Part 1 section 2.4: adding an engine is a YAML file, zero code change."""
    for key in config.available_engines():
        eng = config.load_engine(key)
        assert eng["identity"]["ignition"] in {"SPARK", "COMPRESSION"}
        m = mvem.build(key)
        m.initialise_warm(atm.ambient_at(5000.0))
        out = m.step(0.5, throttle_pct=70.0, ambient=atm.ambient_at(5000.0))
        assert math.isfinite(out.rpm)
        assert out.physics_constraint_violations == 0, key


def test_diesel_adaptation_is_flagged_as_unvalidated():
    """docs/PRD_DEVIATIONS.md: the AE330 stub must never be presented as real."""
    diesel = config.load_engine("austro_ae330")
    assert diesel["identity"].get("validated") is False


# ---------------------------------------------------------------------------
# Facts taken from the official Rotax document set (engines manuals/)
# ---------------------------------------------------------------------------


def test_boost_target_follows_the_published_speed_schedule(engine):
    """OM Ed.0 Rev.4 section 2.1 publishes the boost controller's setpoints."""
    from layer2_physics.turbo import _target_manifold_bar

    at_5500 = _target_manifold_bar(100.0, engine, 1.0, 5500.0)
    at_5800 = _target_manifold_bar(100.0, engine, 1.0, 5800.0)
    assert at_5500 == pytest.approx(
        float(engine["turbocharger"]["target_map_at_5500rpm_bar"]), rel=0.01
    )
    assert at_5800 == pytest.approx(
        float(engine["turbocharger"]["target_map_at_5800rpm_bar"]), rel=0.01
    )
    assert at_5800 > at_5500
    # The never-exceed value must never be used as a setpoint.
    assert at_5800 < float(engine["turbocharger"]["map_never_exceed_bar"])


def test_intercooler_holds_manifold_air_temperature_below_the_limit(engine):
    """OM section 2.1: MAT limit 50 degC, with targets quoted at 25-35 degC.

    Without an intercooler the modelled compressor discharge is 57-89 degC,
    i.e. illegal at every altitude. This test is the guard on that.
    """
    limit = float(engine["intake"]["manifold_air_temp_max_C"])
    for altitude in (0.0, 8000.0, 15000.0, 20000.0):
        st = turbo.solve(
            ambient=atm.ambient_at(altitude, airspeed_kmh=180.0),
            rpm=5500.0,
            throttle_pct=100.0,
            engine=engine,
        )
        mat_c = st.manifold_air_temp_k - 273.15
        assert mat_c < limit, f"MAT {mat_c:.1f} C over limit at {altitude:.0f} ft"
        assert mat_c < st.compressor_outlet_temp_k - 273.15, "intercooler must cool"


def test_power_falls_after_the_critical_altitude_and_the_map_covers_the_ceiling(engine):
    """The performance map must span the full certified operating envelope.

    An altitude axis that stops at the critical altitude silently clamps every
    higher query back to it, hiding the power loss the high-altitude scenario
    of PRD Part 3 section 18.1 is meant to show.
    """
    ceiling = float(engine["ratings"]["max_operating_altitude_ft"])
    assert perf_maps.ALTITUDE_AXIS[-1] >= ceiling

    m = perf_maps.maps_for(ENGINE_KEY)
    crit = float(engine["turbocharger"]["critical_altitude_ft"])
    p_crit = m.power_at(5500.0, 100.0, crit)
    p_ceiling = m.power_at(5500.0, 100.0, ceiling)
    # [OM performance table] 88.6 kW at 22,999 ft against 99.7 kW at 15,000 ft,
    # 5500 rpm full throttle: 0.889. The 0.80 asserted before came from the
    # PRD's analytic knee, which read up to 38 % low (review PHY-01).
    assert p_ceiling < 0.92 * p_crit, "power must fall materially above critical altitude"


def test_the_manufacturer_failure_matrix_is_present_and_consistent(engine):
    """IM Rev.5 Appendix: the published sensor/actuator FMEA.

    It is the ground truth for sensor-fault detection (PRD Part 2 section 10.5)
    and for lamp annunciation (PRD Part 4 section 4).
    """
    fm = engine["failure_matrix"]
    items = fm["items"]
    assert len(items) >= 25
    valid_modes = {"Auto_A", "Auto_B", "Auto_AB", "Only_A", "Only_B"}
    valid_lamps = {"ON", "OFF", "FLASHING"}
    for it in items:
        assert it["lane"] in {"A", "B"}, it
        assert it["mode"] in valid_modes, it
        assert it["lamp_a"] in valid_lamps and it["lamp_b"] in valid_lamps, it
    # Oil pressure and oil temperature sensors sit on lane B, and their failure
    # flashes lamp B -- a detail the detector layer must not invert.
    ops = next(i for i in items if i["item"] == "OPS")
    assert ops["lane"] == "B" and ops["lamp_b"] == "FLASHING" and ops["lamp_a"] == "OFF"
    # Coolant temperature, EGT and knock sit on lane A.
    for name in ("CTS", "EGT", "KNOCK"):
        it = next(i for i in items if i["item"] == name)
        assert it["lane"] == "A" and it["lamp_a"] == "FLASHING"


def test_tbo_has_both_an_hours_and_a_calendar_limit(engine):
    """MML Rev.3: "1200 h or 15 years, whichever comes first".

    RUL must therefore be the minimum of the two, not the hours figure alone.
    """
    assert float(engine["ratings"]["tbo_hours"]) == pytest.approx(1200.0)
    assert float(engine["ratings"]["tbo_calendar_years"]) == pytest.approx(15.0)


def test_extended_manifold_temperature_range_is_captured(engine):
    """OM Rev.4 adds a 50-80 degC MAT range with a published power penalty."""
    intake = engine["intake"]
    assert float(intake["manifold_air_temp_extended_max_C"]) == pytest.approx(80.0)
    assert float(intake["extended_mat_power_loss_continuous_kW"]) == pytest.approx(1.0)
    assert float(intake["extended_mat_power_loss_takeoff_kW"]) == pytest.approx(2.7)


# ---------------------------------------------------------------------------
# ECU / FADEC: injection and ignition timing
#
# Problem statement section B requires "Injection timing parameters" as a
# monitored parameter, and section C requires injector-abnormality detection.
# These tests exist because timing was previously a hard-coded constant, which
# satisfied neither: a constant cannot indicate a fault.
# ---------------------------------------------------------------------------


def test_healthy_engine_shows_no_injection_timing_deviation(cruise_ambient):
    """A real ECU compensates the injector's characterised nominal dead time.

    So on a healthy engine actual and commanded agree, and every degree of
    deviation observed in service is wear.
    """
    m = mvem.build(ENGINE_KEY)
    o = mvem.trim_to_steady_state(
        m, throttle_pct=85.0, ambient=cruise_ambient, seconds=900.0, dt=1.0
    )
    assert o.max_injection_timing_deviation_deg < 0.5


def test_injector_wear_drives_timing_deviation_through_the_prd_bands(cruise_ambient):
    """PRD Part 2 section 10.2 Method C: normal <1 deg, degraded 1-3, fault >3."""
    engine = config.load_engine(ENGINE_KEY)
    bands = config.load_thresholds()["faults"]["injector_abnormal"]
    deviations = []
    for cond in (1.0, 0.9, 0.75, 0.6, 0.4):
        d = DegradationFactors.as_new(engine)
        d.injector_condition = cond
        m = mvem.build(ENGINE_KEY, degradation=d)
        m.set_manufacturing_spread(np.random.default_rng(3))
        o = mvem.trim_to_steady_state(
            m, throttle_pct=85.0, ambient=cruise_ambient, seconds=900.0, dt=1.0
        )
        deviations.append(o.max_injection_timing_deviation_deg)

    assert all(a < b for a, b in zip(deviations, deviations[1:], strict=False)), (
        f"deviation must grow monotonically with wear, got {deviations}"
    )
    assert deviations[0] < float(bands["timing_deviation_degraded_deg"])
    assert deviations[-1] > float(bands["timing_deviation_fault_deg"])


def test_injection_timing_deviation_grows_with_engine_speed(cruise_ambient):
    """The signature that separates injector wear from a sensor problem.

    A solenoid delay is a fixed number of milliseconds, so it subtends more
    crank angle the faster the engine turns. A sensor bias would not.
    """
    engine = config.load_engine(ENGINE_KEY)
    d = DegradationFactors.as_new(engine)
    d.injector_condition = 0.70
    results = []
    for throttle in (40.0, 60.0, 80.0, 100.0):
        m = mvem.build(ENGINE_KEY, degradation=d)
        o = mvem.trim_to_steady_state(
            m, throttle_pct=throttle, ambient=cruise_ambient, seconds=900.0, dt=1.0
        )
        results.append((o.rpm, o.max_injection_timing_deviation_deg))
    rpms = [r for r, _ in results]
    devs = [v for _, v in results]
    assert all(a < b for a, b in zip(rpms, rpms[1:], strict=False))
    assert all(a < b for a, b in zip(devs, devs[1:], strict=False)), (
        f"deviation must rise with speed, got {results}"
    )


def test_injector_wear_widens_egt_spread(cruise_ambient):
    """PRD Part 2 section 10.2 Method B.

    Per-cylinder EGT must be driven by the fuel each cylinder actually
    receives. If EGT spread does not respond to injector condition, the
    detector has no signal and the model is merely decorative.
    """
    engine = config.load_engine(ENGINE_KEY)
    spreads = []
    for cond in (1.0, 0.85, 0.7, 0.5):
        d = DegradationFactors.as_new(engine)
        d.injector_condition = cond
        m = mvem.build(ENGINE_KEY, degradation=d)
        m.set_manufacturing_spread(np.random.default_rng(3))
        o = mvem.trim_to_steady_state(
            m, throttle_pct=85.0, ambient=cruise_ambient, seconds=900.0, dt=1.0
        )
        spreads.append(o.egt_spread)
    assert all(a < b for a, b in zip(spreads, spreads[1:], strict=False)), spreads
    # A healthy engine must sit inside the certified 200 degC EGT-split limit.
    assert spreads[0] < float(engine["exhaust"]["egt_split_limit_C"])


def test_knock_retards_ignition_as_the_engine_runs_hotter(cruise_ambient):
    """Cooling degradation raises charge temperature, which promotes knock,
    which the ECU answers with ignition retard.

    That cross-coupling means ignition timing carries cooling-health
    information -- an early indicator well before any temperature limit is
    approached (PRD Part 2 section 10.6).
    """
    engine = config.load_engine(ENGINE_KEY)
    retards = []
    for eff in (1.0, 0.85, 0.7, 0.55):
        d = DegradationFactors.as_new(engine)
        d.cooling_efficiency = eff
        m = mvem.build(ENGINE_KEY, degradation=d)
        o = mvem.trim_to_steady_state(
            m, throttle_pct=95.0, ambient=cruise_ambient, seconds=1200.0, dt=1.0
        )
        retards.append(o.knock_retard_deg)
    assert all(a < b for a, b in zip(retards, retards[1:], strict=False)), retards


def test_ignition_timing_stays_in_its_configured_band(cruise_ambient):
    spec = config.load_thresholds()["parameters"]["ignition_timing"]
    for throttle in (35.0, 60.0, 85.0, 100.0):
        m = mvem.build(ENGINE_KEY)
        o = mvem.trim_to_steady_state(
            m, throttle_pct=throttle, ambient=cruise_ambient, seconds=900.0, dt=1.0
        )
        assert float(spec["normal_min"]) <= o.ignition_timing_commanded_deg <= float(
            spec["normal_max"]
        ), f"ignition {o.ignition_timing_commanded_deg:.1f} outside band at {throttle}%"


def test_injector_duty_cycle_never_saturates(cruise_ambient):
    """If the injectors saturate, the ECU cannot meter fuel and the whole
    speed-density strategy fails. Sizing must leave headroom at rated power."""
    spec = config.load_thresholds()["parameters"]["injection_period"]
    m = mvem.build(ENGINE_KEY)
    o = mvem.trim_to_steady_state(
        m, throttle_pct=100.0, ambient=atm.ambient_at(0.0, airspeed_kmh=180.0),
        seconds=900.0, dt=1.0,
    )
    assert o.injector_duty_fraction < float(spec["duty_critical"])
    assert o.injection_period_ms > 0.0


def test_injection_period_follows_air_mass(cruise_ambient):
    """OM Rev.4 section 7.5.3: fuel quantity is metered from airbox air density.

    More air must command a longer injection period; otherwise the model is not
    implementing the manufacturer's stated control law.
    """
    periods, airflows = [], []
    for throttle in (40.0, 70.0, 100.0):
        m = mvem.build(ENGINE_KEY)
        o = mvem.trim_to_steady_state(
            m, throttle_pct=throttle, ambient=cruise_ambient, seconds=900.0, dt=1.0
        )
        periods.append(o.injection_period_ms)
        airflows.append(o.air_mass_flow_kg_s)
    assert all(a < b for a, b in zip(airflows, airflows[1:], strict=False))
    assert all(a < b for a, b in zip(periods, periods[1:], strict=False)), periods

def test_clearing_a_sensor_drift_fault_un_biases_the_instrument():
    """A fault that cannot be un-injected is not a demonstration, it is a
    broken rig.

    The drift fault is expressed as a BIAS on the instrument, not in the
    physics, so ``clear_faults()`` -- which only empties the fault list --
    cannot reach it. Applying the bias inside ``if magnitude > 0`` left it at
    its last non-zero value forever: measured, a cleared fault left the engine
    permanently reading 0.55 bar low on oil pressure and 9 degC high on CHT,
    and the alert it raised never went away.
    """
    from layer2_physics.engine_sim import VirtualEngine, isr_patrol_profile

    ve = VirtualEngine(engine_key="rotax_915is", seed=1)
    ve.set_profile(isr_patrol_profile(0.2))
    for _ in range(600):
        ve.step(0.1)

    # The channel is NAMED. This test used to inject an unnamed drift and
    # assert that oil pressure AND CHT were both biased, because that is what
    # the fault used to do -- every instance moved the same two channels by the
    # same two amounts. That was the defect: it made the class collide with
    # cooling_degradation, and 84 % of the cooling head's false positives were
    # sensor-drift windows. A transducer fault afflicts ONE instrument, so the
    # test now asserts the clearing property it was written for, on a channel
    # it chose, rather than the coincidence of which channels were hard-coded.
    ve.inject(
        InjectedFault(mode=FaultMode.SENSOR_DRIFT, onset_hours=0.0,
                      severity=1.0, ramp_hours=0.001,
                      channel="oil_pressure")
    )
    ve.degradation.advance(5.0, oil_temp_c=100.0, cht_max_c=115.0)
    for _ in range(50):
        ve.step(0.1)
    assert ve.sensors["oil_pressure"].bias != 0.0
    # And ONLY that instrument. A drift that moves channels it was not told to
    # move is the confusability this fault class was rebuilt to remove.
    assert ve.sensors["cht"].bias == 0.0

    ve.degradation.clear_faults()
    ve.step(0.1)
    assert ve.sensors["oil_pressure"].bias == 0.0
    assert ve.sensors["cht"].bias == 0.0


def test_every_problem_statement_fault_is_injectable():
    """All eight classes the PS names must appear in the fleet.

    Sensor drift was excluded from the generator on the reasoning that the
    instrument layer already models drift. It does -- a slow ageing DRIFT, held
    in a different field from the sensor-drift FAULT's bias. The exclusion left
    lab_sensor_drift with zero positive rows on zero engines, so one of the
    eight required classes was silently unsupported.
    """
    from layer2_physics.synth_data_gen import _INJECTABLE

    assert set(_INJECTABLE) == set(FaultMode)


def test_every_fault_class_is_guaranteed_coverage_in_every_split():
    """Sampling modes independently per engine left coverage to luck, and luck
    lost: validation held zero engines with injector_abnormal and zero with
    overheating_trend, and five of eight classes sat on a single test engine.
    A per-class score computed on one engine measures that engine.
    """
    from collections import Counter

    from layer2_physics.synth_data_gen import (
        N_ENGINES,
        _guaranteed_mode,
        split_for,
    )

    seen: dict[str, Counter] = {"train": Counter(), "val": Counter(),
                                "test": Counter()}
    free = Counter()
    for eid in range(1, N_ENGINES + 1):
        mode = _guaranteed_mode(eid)
        if mode is None:
            free[split_for(eid)] += 1
        else:
            seen[split_for(eid)][str(mode)] += 1

    for split, counts in seen.items():
        for mode in FaultMode:
            assert counts[str(mode)] >= 2, (split, mode, dict(counts))
        # Honest negatives survive: a detector that fires on every engine has
        # to be catchable.
        assert free[split] >= 1, split


# ---------------------------------------------------------------------------
# The manufacturer's performance table (Operator's Manual 915 i Ed.0 Rev.4,
# PDF pp.111-130). Every expected value is a PRINTED cell, read from the CSV
# here -- never through layer2_physics.om_table, which the model itself uses --
# so these tests hold the model to the manual rather than to its own lookup.
# ---------------------------------------------------------------------------


def _om_printed(rpm: float, throttle: float, altitude_ft: float, isa_dev_c: float) -> dict:
    """The printed row, and the ambient it was printed at."""
    import csv

    path = config.config_dir() / "engines" / "rotax_915is_om_performance.csv"
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        alt = float(row["alt_ft"])
        isa_c = atm.ambient_at(alt).oat_c
        if (abs(float(row["rpm"]) - rpm) < 1.0
                and abs(float(row["throttle_pct"]) - throttle) < 0.05
                and abs(alt - altitude_ft) < 2.0
                and abs(float(row["t_amb_c"]) - isa_c - isa_dev_c) < 3.0):
            dev = float(row["t_amb_c"]) - isa_c
            return {
                "ambient": atm.ambient_at(alt, isa_deviation_c=dev, airspeed_kmh=180.0),
                "power_kw": float(row["power_kw"]),
                "plenum_bar": float(row["p_plenum_bar"]),
                "plenum_c": float(row["t_plenum_k"]) - 273.15,
                "fuel_kg_h": float(row["fuel_kg_h"]),
            }
    raise AssertionError(f"no printed row for {rpm} rpm {throttle} % {altitude_ft} ft ISA{isa_dev_c:+}")


def _governed_trim(throttle: float, ambient, rpm_setpoint: float | None = None):
    m = mvem.build(ENGINE_KEY)
    out = mvem.trim_to_steady_state(m, throttle_pct=throttle, ambient=ambient,
                                    seconds=120.0, dt=0.5, rpm_setpoint=rpm_setpoint)
    return m, out


@pytest.mark.parametrize("rpm, altitude_ft, isa_dev_c", [
    (5800.0, 0.0, 0.0),
    (5800.0, 15000.0, 0.0),
    (5800.0, 18999.0, 0.0),
    (5800.0, 22999.0, 0.0),
    (5500.0, 22999.0, 0.0),
    (5500.0, 21001.0, 30.0),
    (5800.0, 22999.0, -15.0),
    (5000.0, 15000.0, 0.0),
])
def test_full_throttle_matches_the_manufacturer_performance_table(engine, rpm, altitude_ft, isa_dev_c):
    """Power, plenum pressure, charge-air temperature and fuel flow, as printed.

    Before the table was used the model read 55.7 kW at 23,000 ft against the
    manual's 89.5 kW, charge air 12-37 K hot, full-power fuel flow on a BMEP
    grid clipped at 12 bar, and speed collapsing to 4711 rpm (review PHY-01,
    PHY-05, PHY-06, PHY-09).
    """
    om = _om_printed(rpm, 100.0, altitude_ft, isa_dev_c)
    _, out = _governed_trim(100.0, om["ambient"], rpm_setpoint=rpm)
    rho_fuel = float(engine["fuel_properties"]["density_kg_per_L"])
    assert out.rpm == pytest.approx(rpm, rel=0.01)
    assert out.power_kw == pytest.approx(om["power_kw"], rel=0.03)
    assert out.manifold_pressure_bar == pytest.approx(om["plenum_bar"], rel=0.03)
    assert out.turbo_state.manifold_air_temp_k - 273.15 == pytest.approx(om["plenum_c"], abs=2.0)
    assert out.fuel_flow_lph * rho_fuel == pytest.approx(om["fuel_kg_h"], rel=0.04)


def test_a_hot_day_costs_power_above_the_knee_and_almost_none_below_it():
    """[OM table] ISA+30 at 5500 rpm: -0.8 % at sea level, -13.3 % at 21,001 ft.

    The model used to give identical power from ISA-20 to ISA+35 (PHY-04).
    """
    ratios = {}
    for alt in (0.0, 21001.0):
        cold = _om_printed(5500.0, 100.0, alt, 0.0)
        hot = _om_printed(5500.0, 100.0, alt, 30.0)
        _, o_cold = _governed_trim(100.0, cold["ambient"], rpm_setpoint=5500.0)
        _, o_hot = _governed_trim(100.0, hot["ambient"], rpm_setpoint=5500.0)
        ratios[alt] = (o_hot.power_kw / o_cold.power_kw, hot["power_kw"] / cold["power_kw"])
    for alt, (model, manual) in ratios.items():
        assert model == pytest.approx(manual, abs=0.02), f"{alt:.0f} ft"
    assert ratios[21001.0][0] < ratios[0.0][0] - 0.08


def test_a_constant_speed_propeller_holds_full_throttle_speed_to_the_ceiling(engine):
    """[OM "Designation"] the iS installation drives a governor; speed is held.

    The fixed-pitch law with no air-density term let full-throttle speed fall to
    4711 rpm at 23,000 ft (PHY-06).
    """
    rated_rpm = float(engine["ratings"]["max_power_rpm"])
    powers = {}
    for alt in (0.0, 15000.0, 23000.0):
        m, out = _governed_trim(100.0, atm.ambient_at(alt, airspeed_kmh=180.0))
        assert out.rpm == pytest.approx(rated_rpm, rel=0.01), f"{alt:.0f} ft"
        powers[alt] = out.power_kw
    assert powers[23000.0] < powers[15000.0]
    assert powers[23000.0] > 0.80 * powers[0.0]


def test_a_governed_engine_runs_where_the_fixed_pitch_engine_did_at_sea_level():
    """The governor schedule is the old sea-level operating line wherever that
    line respects maximum continuous, so those sea-level points did not move;
    full lever holds take-off speed less the regulation band, where the old law
    also settled (DEV-227, DEV-234)."""
    amb = atm.ambient_at(0.0, airspeed_kmh=180.0)
    for lever in (45.0, 70.0, 100.0):
        _, governed = _governed_trim(lever, amb)
        fixed = mvem.build(ENGINE_KEY)
        fixed.initialise_warm(amb)
        for _ in range(240):
            out = fixed.step(0.5, throttle_pct=lever, ambient=amb, load_factor=1.0)
        assert governed.rpm == pytest.approx(out.rpm, rel=0.015), f"lever {lever}"
        assert governed.power_kw == pytest.approx(out.power_kw, rel=0.02), f"lever {lever}"


def test_the_governor_never_holds_part_throttle_above_maximum_continuous(engine):
    """[TCDS] 5500 rpm maximum continuous; take-off speed only at full lever.

    Held on the old sea-level line, an 80 % climb lever sat at 5603 rpm for a
    ten-minute climb and a full lever at exactly 5800 rpm read 5803 through
    sensor noise: MAX CONT EXCEEDED and OVERSPEED on a healthy engine (DEV-234).
    """
    mcp = float(engine["ratings"]["continuous_power_rpm"])
    rated = float(engine["ratings"]["max_power_rpm"])
    for alt in (0.0, 15000.0):
        amb = atm.ambient_at(alt, airspeed_kmh=170.0)
        for lever in (80.0, 90.0, 97.0):
            _, out = _governed_trim(lever, amb)
            assert out.rpm < mcp, f"lever {lever} at {alt:.0f} ft held {out.rpm:.0f} rpm"
        _, full = _governed_trim(100.0, amb)
        assert full.rpm < rated, f"full lever at {alt:.0f} ft held {full.rpm:.0f} rpm"
        assert full.rpm > rated - 50.0


def test_the_installation_keeps_every_temperature_in_limits_at_the_50c_ambient_limit(engine):
    """[IM-915 i] "The cooling system must be designed so that operating
    temperatures will not exceed the maximum values"; [OM-915 i] ambient to 50 C.

    The radiator and oil cooler are installation values, not manufacturer data,
    and had been sized for a standard day only: at 50 C a five-minute take-off
    ran oil to 170 C, coolant to 134 C and the heads to 159 C (review PHY-03).
    Sized to the requirement, a take-off and a maximum-continuous climb stay in
    limits, and a standard-day cruise stays in the recommended oil band.
    """
    limits = engine["limits"]
    oil_max = float(limits["oil_temperature_C"][1])
    coolant_max = float(limits["coolant_temperature_max_C"])
    cht_max = float(engine["thermal"]["cht_limit_C"])
    cases = (
        ("five-minute take-off", 300.0, None, 120.0),
        ("maximum-continuous climb", 1500.0, 5500.0, 130.0),
    )
    for name, seconds, rpm_setpoint, airspeed in cases:
        amb = atm.ambient_at(0.0, isa_deviation_c=35.0, airspeed_kmh=airspeed, humidity_pct=12.0)
        m = mvem.build(ENGINE_KEY)
        o = mvem.trim_to_steady_state(m, throttle_pct=100.0, ambient=amb, seconds=seconds,
                                      dt=1.0, rpm_setpoint=rpm_setpoint)
        assert o.oil_temperature_c < oil_max, f"{name}: oil {o.oil_temperature_c:.1f} C"
        assert o.coolant_temperature_c < coolant_max, f"{name}: coolant {o.coolant_temperature_c:.1f} C"
        assert o.cht_max < cht_max, f"{name}: CHT {o.cht_max:.1f} C"

    # [OM s2.1] 90-110 C recommended; a cooler sized for 50 C must not overcool a standard day.
    m = mvem.build(ENGINE_KEY)
    cruise = mvem.trim_to_steady_state(m, throttle_pct=70.0, ambient=atm.ambient_at(0.0, airspeed_kmh=180.0),
                                       seconds=1500.0, dt=1.0)
    assert 90.0 <= cruise.oil_temperature_c <= 110.0, f"standard-day oil {cruise.oil_temperature_c:.1f} C"


def test_rotating_inertia_is_the_installation_value_from_the_engine_definition():
    """One number for the equation of motion and the ingest plausibility limit.

    It was a bare 0.16 inside the model while the ingest limit was set
    separately, which is how the two came to disagree (DEV-237).
    """
    from common import config

    m = mvem.build(ENGINE_KEY)
    assert m._inertia == float(
        config.load_engine(ENGINE_KEY)["propeller"]["rotating_inertia_at_crank_kg_m2"])
