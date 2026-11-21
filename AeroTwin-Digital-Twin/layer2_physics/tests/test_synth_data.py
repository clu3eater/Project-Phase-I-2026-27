"""Tests for the run-to-failure dataset generator.

The point of these tests is not that the generator runs -- it is that the
dataset it produces cannot flatter a model. PRD Part 0 section 0.5 calls this
"the training-data trap", and every defence it lists is checked here:

  * the split is by ENGINE, so no engine's samples straddle it
  * labels come from internal state and features from sensors, and the two
    never mix
  * faults are stochastic, so no two engines fail the same way
  * each engine has its own physics, so there is no single trajectory to
    memorise
  * the shadow model stays as-new for life, so residuals do not collapse

The last one is the subtle one and it has its own test: a shadow re-seeded per
sortie would inherit the degraded engine's temperatures, drive every residual
toward zero, and produce a dataset whose most important columns are silently
dead. Nothing else in the pipeline would notice.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from common import config
from layer2_physics.degradation import (
    FAULT_CLASS_ORDER,
    DegradationEngine,
    FaultMode,
    InjectedFault,
)
from layer2_physics.synth_data_gen import (
    N_ENGINES,
    SPLIT_TEST,
    SPLIT_TRAIN,
    SPLIT_VAL,
    end_of_life,
    run_one_engine,
    sample_faults,
    split_for,
    truth_health,
)

LABEL_PREFIXES = ("deg_", "lab_", "chi_", "thi_", "mhi_", "comb_hi_")
LABEL_EXACT = {"rul_hours", "censored", "any_fault"}


# ---------------------------------------------------------------------------
# The split
# ---------------------------------------------------------------------------


def test_split_is_by_engine_and_covers_the_fleet():
    """PRD Part 0 section 0.5 point 2.

    Splitting by sample would put consecutive readings from one engine on both
    sides of the boundary, and the reported test score would be measuring
    memorisation rather than generalisation.
    """
    ids = set(SPLIT_TRAIN) | set(SPLIT_VAL) | set(SPLIT_TEST)
    assert ids == set(range(1, N_ENGINES + 1))
    # Disjoint: an engine belongs to exactly one split.
    assert len(SPLIT_TRAIN) + len(SPLIT_VAL) + len(SPLIT_TEST) == len(ids)
    # The evaluation splits must be able to CARRY the eight fault classes.
    # They could not at 80/10/10: ten engines meant validation held zero with
    # injector_abnormal and zero with overheating_trend, and five of the eight
    # classes sat on a single test engine. A per-class score computed on one
    # engine measures that engine, not the class.
    from layer2_physics.degradation import FAULT_CLASS_ORDER

    assert len(SPLIT_VAL) >= 2 * len(FAULT_CLASS_ORDER)
    assert len(SPLIT_TEST) >= 2 * len(FAULT_CLASS_ORDER)
    # Training still holds the majority.
    assert len(SPLIT_TRAIN) > len(SPLIT_VAL) + len(SPLIT_TEST)


def test_every_engine_maps_to_exactly_one_split():
    for eid in range(1, N_ENGINES + 1):
        assert split_for(eid) in ("train", "val", "test")
    # Derived from the ranges rather than hardcoded, so a deliberate change to
    # the split proportions does not read as a regression.
    assert split_for(min(SPLIT_TRAIN)) == "train"
    assert split_for(max(SPLIT_TRAIN)) == "train"
    assert split_for(min(SPLIT_VAL)) == "val"
    assert split_for(max(SPLIT_VAL)) == "val"
    assert split_for(min(SPLIT_TEST)) == "test"
    assert split_for(max(SPLIT_TEST)) == "test"


# ---------------------------------------------------------------------------
# Stochastic faults and manufacturing spread
# ---------------------------------------------------------------------------


def test_fault_schedules_differ_between_engines():
    """No two engines may fail the same way (section 0.5 point 1).

    Called with the engine id, as the generator calls it: each engine carries a
    GUARANTEED mode dealt round-robin within its split, plus random extras, and
    random severity and ramp. Guaranteeing coverage must not cost variety.

    ONSET IS NO LONGER PART OF THE SCHEDULE. Under the wear-out hazard model
    (DEV-193) it is decided DURING the run, when accumulated damage triggers it,
    so `sample_faults` leaves it pending and this test keys on what it actually
    randomises. `test_onset_is_pending_under_the_hazard_model` covers the other
    half.
    """
    schedules = []
    for eid in range(1, 31):
        rng = np.random.default_rng(eid)
        schedules.append(
            tuple(sorted((str(f.mode), round(f.severity, 3), round(f.ramp_hours, 1))
                         for f in sample_faults(rng, eid)))
        )
    assert len(set(schedules)) > 20, "fault schedules are not stochastic enough"


def test_onset_is_pending_under_the_hazard_model():
    """A dealt fault carries no onset until the engine earns one.

    The old generator drew `onset = uniform(15, 400)` before the engine ever
    ran, INDEPENDENT of its condition -- a constant hazard, which models random
    failures rather than wear-out, and which made "predict failures before
    occurrence" impossible by construction. `inf` marks the fault as dealt but
    not yet scheduled; `DegradationEngine.arm_pending_faults` decides the time
    from accumulated damage. See DEV-193.
    """
    for eid in range(1, 12):
        for f in sample_faults(np.random.default_rng(eid), eid):
            assert math.isinf(f.onset_hours), (
                f"engine {eid}: onset was pre-scheduled at {f.onset_hours}, so "
                f"condition cannot influence when the fault starts"
            )


def test_the_old_constant_hazard_model_is_still_reproducible():
    """The change has to justify itself against the model it replaced, so that
    model must remain runnable rather than remembered (DEV-198)."""
    seen = []
    for eid in range(1, 12):
        for f in sample_faults(np.random.default_rng(eid), eid, hazard_onset=False):
            assert math.isfinite(f.onset_hours)
            assert 15.0 <= f.onset_hours <= 400.0
            seen.append(round(f.onset_hours, 1))
    assert len(set(seen)) > 5, "the legacy path lost its variety"


def test_ramp_times_follow_the_mode_not_one_distribution():
    """A failed ignition coil and a coking injector do not progress alike.

    The old generator drew one log-uniform 0.5-300 h span -- 600:1 -- for all
    eight modes. Ramps are now keyed on the physical mechanism (DEV-196).
    """
    from layer2_physics.degradation import FAULT_RAMP_HOURS, FaultMode

    assert set(FAULT_RAMP_HOURS) == set(FaultMode), "a mode has no ramp range"
    # An ignition component failing is near-step; deposit build-up is not.
    assert FAULT_RAMP_HOURS[FaultMode.MISFIRE][1] < 20.0
    assert FAULT_RAMP_HOURS[FaultMode.INJECTOR_ABNORMAL][0] > 20.0
    # OVERHEATING_TREND is named a trend; a step would contradict the mode.
    assert FAULT_RAMP_HOURS[FaultMode.OVERHEATING_TREND][0] >= 50.0

    for mode, (lo, hi) in FAULT_RAMP_HOURS.items():
        assert 0.0 < lo < hi, mode
        assert hi / lo < 100.0, (
            f"{mode} spans {hi/lo:.0f}:1, which is the undifferentiated range "
            f"this table replaced"
        )


def test_a_worn_pathway_raises_its_own_fault_hazard():
    """The loop the old model left open: a fault accelerated wear, but wear
    never made a fault likelier. On a real engine that is a cycle (DEV-194)."""
    from layer2_physics.degradation import FaultMode, onset_probability

    p_new = onset_probability(0.0, 12.0, mode=FaultMode.ABNORMAL_VIBRATION)
    p_worn = onset_probability(1.0, 12.0, mode=FaultMode.ABNORMAL_VIBRATION)
    assert p_worn > 5.0 * p_new, (
        f"a destroyed bearing is only {p_worn/p_new:.1f}x likelier to develop "
        f"a bearing fault than a new one"
    )


def test_sensor_drift_stays_a_random_failure():
    """A transducer failing is ELECTRONIC, not mechanical wear-out, and a
    constant hazard is the CORRECT model for it. Making every mode
    condition-dependent would be the same error in the opposite direction
    (DEV-195)."""
    from layer2_physics.degradation import FaultMode, onset_probability

    a = onset_probability(0.0, 12.0, mode=FaultMode.SENSOR_DRIFT)
    b = onset_probability(1.0, 12.0, mode=FaultMode.SENSOR_DRIFT)
    assert a == b


def test_some_engines_are_left_healthy():
    """The dataset needs honest negatives.

    A detector that fires on every engine has to be catchable, and it cannot be
    if every engine in the fleet carries a fault.
    """
    counts = [len(sample_faults(np.random.default_rng(e), e))
              for e in range(1, 201)]
    assert counts.count(0) > 10, "no fault-free engines in 200 draws"
    assert max(counts) <= 3


def test_all_eight_problem_statement_faults_are_injected():
    """This test used to assert the OPPOSITE, and was wrong.

    Sensor drift was excluded on the grounds that the instrument layer already
    models drift, so injecting it would double-count. That conflates the slow
    ageing DRIFT every transducer accumulates (SensorSpec.drift) with a
    sensor-drift FAULT, which is a separate BIAS field; engine_sim keeps them
    deliberately apart and they never double-counted.

    The cost was that lab_sensor_drift carried ZERO positive rows on ZERO
    engines, the multi-label head had a class with no positive examples, and
    one of the eight classes the problem statement requires was silently
    unsupported.
    """
    modes = set()
    for eid in range(1, 201):
        modes.update(f.mode for f in sample_faults(np.random.default_rng(eid), eid))
    assert FaultMode.SENSOR_DRIFT in modes
    assert modes == set(FAULT_CLASS_ORDER)


def test_each_engine_gets_its_own_degradation_rates():
    """Section 0.5 point 3: randomised physics per engine.

    With one shared trajectory a network can memorise the answer instead of
    learning the signal.
    """
    eng = config.load_engine("rotax_915is")
    rates = []
    for seed in range(10):
        d = DegradationEngine(engine=eng, rng=np.random.default_rng(seed))
        d.randomise_rates()
        rates.append(tuple(round(v, 6) for v in d.rate_scale.values()))
    assert len(set(rates)) == 10
    # Log-normal: rates must stay positive.
    assert all(v > 0 for r in rates for v in r)


# ---------------------------------------------------------------------------
# Degradation over a full life
# ---------------------------------------------------------------------------


def _advance_to(hours: float, **kw) -> DegradationEngine:
    eng = config.load_engine("rotax_915is")
    d = DegradationEngine(engine=eng, **kw)
    while d.hours < hours:
        d.advance(1.0, oil_temp_c=98.0, cht_max_c=107.0)
    return d


def test_oil_is_changed_on_schedule():
    """DEV-42. Oil is a consumable, not a life-limited part.

    Without this the viscosity increase crossed its condemnation limit at
    223 h and oil_quality stayed at zero for the rest of the engine's life --
    every virtual engine condemned by oil a real operator would have changed
    twelve times before overhaul.
    """
    d = _advance_to(1200.0)
    assert d.oil_changes == 12
    assert d.factors.oil_quality > 0.9  # just serviced
    assert d.factors.oil_viscosity_ratio == pytest.approx(1.0, abs=0.02)


def test_oil_quality_recovers_after_a_change_and_decays_again():
    d = _advance_to(99.0)
    before = d.factors.oil_quality
    assert before < 0.6, "oil should be well used just before its change"
    d.advance(2.0, oil_temp_c=98.0, cht_max_c=107.0)
    assert d.factors.oil_quality > 0.95, "oil change did not restore quality"


def test_a_healthy_engine_survives_to_tbo():
    """DEV-42/43. TBO exists so the engine is overhauled BEFORE it fails.

    Before the recalibration a fault-free engine crossed the maintenance
    threshold at roughly a third of TBO, which meant injected faults were
    drowned by baseline wear and the dataset taught the wrong lesson.
    """
    chi_fail = float(config.load_thresholds()["rul"]["maintenance_chi_threshold"])
    d = _advance_to(1200.0)
    chi = truth_health(d.factors)["chi_true"]
    assert chi > chi_fail, f"healthy engine failed before TBO: CHI {chi:.3f}"
    assert chi < 0.90, "1200 h of wear should be clearly visible"


def test_injectors_are_not_the_life_limiting_item():
    """DEV-43. They were, at two thirds of TBO, with no such service interval."""
    d = _advance_to(1200.0)
    assert d.factors.injector_condition > 0.70


def test_ground_truth_health_weights_sum_to_one():
    """DEV-44: the electrical term is absent, so the rest are renormalised.

    Leaving it at a constant 1.0 would hand every engine a free 0.20 and put
    the 0.60 maintenance threshold out of reach, so nothing would ever be
    labelled failed.
    """
    eng = config.load_engine("rotax_915is")
    d = DegradationEngine(engine=eng)
    h = truth_health(d.factors)
    # An as-new engine must score exactly 1.0; anything else means the weights
    # do not sum to one.
    assert h["chi_true"] == pytest.approx(1.0, abs=1e-9)


def test_health_falls_as_the_engine_degrades():
    early = truth_health(_advance_to(100.0).factors)["chi_true"]
    late = truth_health(_advance_to(1000.0).factors)["chi_true"]
    assert late < early - 0.05


# ---------------------------------------------------------------------------
# The emitted rows
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def short_run():
    """One engine over a deliberately short life, to keep the test quick."""
    return run_one_engine(7, max_life_hours=60.0)


def test_rows_carry_features_labels_and_residuals(short_run):
    row = short_run.rows[-1]
    # measured
    for col in ("rpm", "cht_max", "oil_pressure", "fuel_flow", "vibration_rms_total"):
        assert col in row
    # residuals -- feature, never target (section 0.5 point 4)
    for col in ("res_cht", "res_coolant", "res_oil_pressure", "res_egt"):
        assert col in row
    # labels
    for col in ("chi_true", "rul_hours", "censored", "deg_cooling_efficiency"):
        assert col in row
    for mode in FAULT_CLASS_ORDER:
        assert f"lab_{mode.value}" in row


def test_labels_are_separable_from_features(short_run):
    """Nothing unobservable may leak into a feature column.

    A single mislabelled column -- a degradation factor sitting among the
    features -- would let a model read the answer off its own input, and the
    reported accuracy would be meaningless.
    """
    row = short_run.rows[-1]
    labels = {
        k for k in row
        if k.startswith(LABEL_PREFIXES) or k in LABEL_EXACT
    }
    features = set(row) - labels - {"engine_id", "sortie", "t_s", "split",
                                    "flight_hours", "shadow_available"}
    assert not any(f.startswith(("deg_", "lab_")) for f in features)
    assert "chi_true" not in features
    assert len(features) > 20


def test_the_shadow_stays_as_new_for_the_whole_life(short_run):
    """The residual must not collapse as the engine degrades.

    A shadow re-seeded each sortie would inherit the degraded engine's
    temperatures and quietly zero the most informative columns in the file,
    and nothing downstream would notice.
    """
    assert any(r["shadow_available"] for r in short_run.rows)
    residuals = [r["res_cht"] for r in short_run.rows if r["res_cht"] is not None]
    assert residuals, "no CHT residuals were emitted"
    # Not identically zero -- that is the signature of a shadow tracking the
    # engine it is supposed to be independent of.
    assert max(abs(x) for x in residuals) > 1e-6


def test_rul_decreases_within_an_engine(short_run):
    rul = [r["rul_hours"] for r in short_run.rows]
    assert all(b <= a + 1e-9 for a, b in zip(rul, rul[1:], strict=False))
    assert rul[0] > rul[-1]


def test_an_engine_that_did_not_fail_is_marked_censored(short_run):
    """Its RUL is a lower bound, not a value.

    Training on a censored engine's RUL as if it were the truth teaches the
    model that healthy engines are about to fail.
    """
    assert short_run.failed is False  # 60 h is far short of any failure
    assert all(r["censored"] for r in short_run.rows)


def test_sortie_lengths_vary(short_run):
    """A fleet flies a mix of transits and full-endurance patrols.

    MALE means Medium Altitude LONG ENDURANCE -- a fixed 3 h sortie would be a
    trainer, not an ISR asset.
    """
    hours = sorted({round(r["flight_hours"], 3) for r in short_run.rows})
    assert len(hours) > 10
    assert short_run.rows[-1]["flight_hours"] > 20.0


# ---------------------------------------------------------------------------
# Faults must actually be able to end an engine's life
# ---------------------------------------------------------------------------


def _life_with(fault: InjectedFault | None) -> tuple[float, bool]:
    eng = config.load_engine("rotax_915is")
    chi_fail = float(config.load_thresholds()["rul"]["maintenance_chi_threshold"])
    d = DegradationEngine(engine=eng)
    if fault is not None:
        d.inject(fault)
    while d.hours < 1200.0:
        d.advance(1.0, oil_temp_c=98.0, cht_max_c=107.0)
        if end_of_life(truth_health(d.factors, eng), chi_fail):
            return d.hours, True
    return d.hours, False


def test_a_severe_fault_ends_the_engine_before_tbo():
    """DEV-45 -- the defect that made the whole dataset pointless.

    Faults used to CLAMP a health factor rather than accelerate wear, and a
    clamp cannot end a life: measured, a severity-1.0 fault left the composite
    index at 0.77-0.89 against a 0.60 threshold. Every failure in the fleet
    therefore came from baseline wear near TBO, and a model trained on it would
    have learned "RUL = TBO - hours" while ignoring the faults entirely --
    exactly the circularity PRD Part 0 section 0.5 exists to prevent.
    """
    for mode in (
        FaultMode.COOLING_DEGRADATION,
        FaultMode.ABNORMAL_VIBRATION,
        FaultMode.COMBUSTION_INSTABILITY,
        FaultMode.MISFIRE,
    ):
        hours, failed = _life_with(
            InjectedFault(mode=mode, onset_hours=150.0, severity=0.9, ramp_hours=50.0)
        )
        assert failed, f"{mode.value} at severity 0.9 never ended the engine's life"
        assert hours < 1000.0, f"{mode.value} barely shortened life ({hours:.0f} h)"


def test_life_shortens_monotonically_with_fault_severity():
    """Without a gradient there is no RUL signal to learn, only a threshold."""
    lives = [
        _life_with(
            InjectedFault(
                mode=FaultMode.COOLING_DEGRADATION,
                onset_hours=150.0, severity=s, ramp_hours=50.0,
            )
        )[0]
        for s in (0.3, 0.5, 0.7, 0.9)
    ]
    assert all(b < a for a, b in zip(lives, lives[1:], strict=False)), lives


def test_a_fault_free_engine_is_unaffected_by_the_acceleration_table():
    hours, failed = _life_with(None)
    assert not failed
    assert hours >= 1200.0


def test_end_of_life_catches_a_single_destroyed_subsystem():
    """A weighted average dilutes one bad subsystem behind two healthy ones.

    PRD Part 2 section 9.3's own band table calls anything below 0.40 "UNSAFE --
    ground aircraft immediately", so end of life is either criterion.
    """
    healthy = {"chi_true": 0.85, "thi_true": 0.95, "mhi_true": 0.95, "comb_hi_true": 0.90}
    assert not end_of_life(healthy, 0.60)
    destroyed = {**healthy, "comb_hi_true": 0.30}
    assert end_of_life(destroyed, 0.60), "a destroyed subsystem must end the engine's life"
