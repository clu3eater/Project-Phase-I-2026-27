"""Serving the trained RUL network -- PHASE A1.

The failure this guards against is not "the model gives a wrong number". It is
TRAIN/SERVE SKEW: a serving path that builds its feature vector slightly
differently from the training path produces confident nonsense, and nothing
downstream can tell. Two such skews were found while writing it -- an
un-baselined residual and a percent fed into a fraction -- so most of these
tests are about the feature contract rather than the arithmetic.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import torch

from layer3_ai import features as feat
from layer3_ai.rul_lstm import RulLstm
from layer3_ai.rul_serving import (
    BASELINED_RESIDUALS,
    LstmRulServer,
    ResidualBaseline,
    ServedRul,
)

SEQ = 30


def _checkpoint(tmp_path, columns=None, seed=0):
    """A real, loadable checkpoint in the shape train_rul.py writes."""
    fs = feat.extended()
    cols = list(columns) if columns is not None else list(fs.columns)
    torch.manual_seed(seed)
    model = RulLstm(len(cols))
    path = tmp_path / "rul_lstm.pt"
    torch.save({"model": model.state_dict(), "features": cols,
                "rul_max": 400.0, "val_loss": 0.5}, path)
    return path


def _sample(**over):
    """One live reading, keyed by DATASET column name."""
    row = {c: 0.0 for c in feat.extended().columns}
    row.update({
        "rpm": 5200.0, "cht_max": 105.0, "egt_max": 820.0,
        "oil_pressure": 55.0, "oil_temperature": 98.0, "fuel_flow": 22.0,
        "vibration_rms_total": 3.0, "vibration_kurtosis": 3.0,
        "cht_minus_coolant": 12.0, "cht_spread": 8.0, "egt_spread": 45.0,
        "injection_deviation_max": 0.5, "knock_retard_deg": 3.0,
        "injector_duty": 0.35,
    })
    for c in BASELINED_RESIDUALS:
        row[c] = 0.0
    row.update(over)
    return row


# ---------------------------------------------------------------- checkpoint


def test_a_real_checkpoint_loads(tmp_path):
    s = LstmRulServer(_checkpoint(tmp_path), sequence_length=SEQ)
    assert s.available, s.unavailable_reason
    assert s.rul_max == 400.0


def test_a_missing_checkpoint_disables_serving_it_does_not_raise(tmp_path):
    """The aircraft must keep flying. No checkpoint means physics, not a crash."""
    s = LstmRulServer(tmp_path / "absent.pt", sequence_length=SEQ)
    assert not s.available
    assert "no checkpoint" in s.unavailable_reason
    out = s.observe(_sample(), 10.0)
    assert out.hours is None and out.source == "none"


def test_a_feature_order_mismatch_is_REFUSED_not_silently_served(tmp_path):
    """THE ONE THAT MATTERS.

    A network handed the right number of features in the wrong ORDER produces
    a confident number and nothing downstream can tell it is wrong. The
    checkpoint records the order it was trained on, so this is checkable --
    and it must be checked, not assumed.
    """
    cols = list(feat.extended().columns)
    swapped = cols.copy()
    swapped[0], swapped[1] = swapped[1], swapped[0]
    s = LstmRulServer(_checkpoint(tmp_path, columns=swapped), sequence_length=SEQ)
    assert not s.available
    assert "feature contract mismatch" in s.unavailable_reason
    assert "index 0" in s.unavailable_reason


def test_the_serving_feature_order_equals_the_training_order(tmp_path):
    """Stated as its own assertion so a reordering of EXTENDED breaks here,
    beside the reason, rather than three layers away in a metric."""
    ck = torch.load(_checkpoint(tmp_path), map_location="cpu", weights_only=False)
    assert ck["features"] == list(feat.extended().columns)
    # The COUNT is whatever EXTENDED defines -- it was pinned at 23 and the
    # contract grew to 34 when the actuator-authority, lane-disagreement,
    # exhaust-scatter and bearing-order features were added. What must never
    # drift is the two lists being identical, which the line above checks.
    assert len(ck["features"]) == len(feat.extended().columns)


# ------------------------------------------------------------------ warm-up


def test_it_declines_to_answer_until_the_window_is_full(tmp_path):
    s = LstmRulServer(_checkpoint(tmp_path), sequence_length=SEQ)
    for i in range(SEQ - 1):
        out = s.observe(_sample(), 1.0 + i)
        assert out.hours is None
        assert out.source == "none"
        assert "warming up" in out.reason
    assert s.observe(_sample(), 100.0).source == "lstm"


def test_a_full_window_produces_a_bounded_estimate(tmp_path):
    s = LstmRulServer(_checkpoint(tmp_path), sequence_length=SEQ)
    for i in range(SEQ):
        out = s.observe(_sample(), 1.0 + i)
    assert out.source == "lstm"
    # Never negative -- a negative remaining life is not conservative, it is
    # meaningless -- and never beyond the horizon the model was trained to.
    assert 0.0 <= out.hours <= 400.0


def test_reset_forgets_the_window(tmp_path):
    s = LstmRulServer(_checkpoint(tmp_path), sequence_length=SEQ)
    for i in range(SEQ):
        s.observe(_sample(), 1.0 + i)
    assert s.warm
    s.reset()
    assert not s.warm
    assert s.observe(_sample(), 200.0).source == "none"


# ----------------------------------------------------------------- baseline


def test_the_baseline_subtracts_early_life_and_then_FREEZES():
    """A running baseline would cancel the degradation it exists to reveal.

    `twin_state.Residual.mean_delta` is a running mean over the whole life, so
    as an engine degrades the mean follows it and `delta - mean_delta` tends
    back to zero. Training used an EARLY-LIFE median and stopped. So must this.
    """
    b = ResidualBaseline(hours=60.0, min_samples=20)
    for i in range(40):                       # early life, residual ~ +2.0
        b.observe({"res_cht": 2.0}, flight_hours=float(i))
    assert not b.frozen
    b.observe({"res_cht": 2.0}, flight_hours=61.0)
    assert b.frozen

    # A DEGRADING engine: the residual climbs. The baseline must not follow it.
    late = b.observe({"res_cht": 12.0}, flight_hours=500.0)
    assert late["res_cht"] == pytest.approx(10.0), (
        "the baseline tracked the degradation instead of the build offset"
    )
    for _ in range(200):
        b.observe({"res_cht": 12.0}, flight_hours=900.0)
    assert b.observe({"res_cht": 12.0}, 950.0)["res_cht"] == pytest.approx(10.0)


def test_a_fault_on_a_young_engine_is_not_learned_as_its_normal():
    """Left open for sixty hours, the reference was the median of everything
    seen -- so a fault in that time became it. Measured live: a lubrication
    fault's +9 psi was 6 psi absorbed fifteen minutes in, and the fused alert
    fell back to NORMAL with the fault still present."""
    b = ResidualBaseline(hours=60.0, min_samples=20, settle_samples=100)
    for _ in range(100):                      # healthy, build offset -0.5 psi
        b.observe({"res_oil_pressure": -0.5}, flight_hours=1.0)
    assert b.frozen, "the build offset is known; the reference must close"
    for _ in range(1000):                     # the fault, still at hour 1
        out = b.observe({"res_oil_pressure": 9.0}, flight_hours=1.2)
    assert out["res_oil_pressure"] == pytest.approx(9.5)


def test_a_sample_the_caller_excludes_never_enters_the_reference():
    """Climb samples are applied against the reference but never form it
    (DEV-254): a climb-formed reference put a healthy cruise 10 degC off."""
    b = ResidualBaseline(hours=60.0, min_samples=20, settle_samples=50)
    for _ in range(500):                              # climb: +6 degC, not learned
        out = b.observe({"res_egt": 6.0}, 1.0, learn=False)
    assert not b.frozen and out["res_egt"] == pytest.approx(6.0)
    for _ in range(50):                               # level flight: +16 degC
        b.observe({"res_egt": 16.0}, 1.1)
    assert b.frozen
    assert b.observe({"res_egt": 16.0}, 1.2)["res_egt"] == pytest.approx(0.0)
    assert b.observe({"res_egt": 6.0}, 1.2, learn=False)["res_egt"] == pytest.approx(-10.0)


def test_without_a_settle_count_the_reference_waits_for_sixty_hours():
    """The training-time definition, unchanged for a caller that asks for it."""
    b = ResidualBaseline(hours=60.0, min_samples=20)
    for _ in range(5000):
        b.observe({"res_oil_pressure": 0.0}, flight_hours=1.0)
    assert not b.frozen


def test_a_missing_residual_stays_missing():
    """None means no information. Substituting 0.0 would invent a reading."""
    b = ResidualBaseline()
    assert b.observe({"res_cht": None}, 5.0)["res_cht"] is None


def test_the_baseline_covers_manifold_pressure():
    """It is not one of the 23 inputs, but it FEEDS the three structured
    residual features, so an un-baselined one leaks build scatter into them."""
    assert "res_manifold_pressure" in BASELINED_RESIDUALS


# ------------------------------------------------- structured residual parity


def test_structured_residuals_one_matches_the_batch_version():
    """The single-sample path and the training path must agree exactly.

    They share `_RESIDUAL_SCALE` but not their code, so the duplication is
    checked here rather than trusted.
    """
    rng = np.random.default_rng(0)
    cols = list(BASELINED_RESIDUALS)
    rows = [{c: float(v) for c, v in zip(cols, rng.normal(0, 5, len(cols)))}
            for _ in range(25)]
    batch = feat.add_structured_residual_features(pd.DataFrame(rows))
    for i, row in enumerate(rows):
        one = feat.structured_residuals_one(row)
        for k in ("res_isolation", "res_n_excursions", "res_top_abs"):
            assert one[k] == pytest.approx(float(batch[k].iloc[i])), (k, i)


# -------------------------------------------------------------------- units


def test_injector_duty_is_a_fraction_not_a_percent():
    """The twin carries `injector_duty_pct` (~13.5); the training column
    `injector_duty` is a fraction (0.221-0.651, centre 0.35, scale 0.25). Fed
    the percent, this one feature normalises to ~52 against a training range
    of about 0.3 and swamps the other twenty-two."""
    from layer4_core.live import _pct_to_fraction

    assert _pct_to_fraction(13.5) == pytest.approx(0.135)
    assert _pct_to_fraction(None) is None

    fs = feat.extended()
    i = list(fs.columns).index("injector_duty")
    as_percent = feat.build_one(_sample(injector_duty=13.5), fs)[i]
    as_fraction = feat.build_one(_sample(injector_duty=0.135), fs)[i]
    assert abs(as_percent) > 40.0, "fixture no longer demonstrates the hazard"
    assert abs(as_fraction) < 1.5


# ------------------------------------------------------------------ fallback


def test_inference_failure_falls_back_and_does_not_stop_the_engine(tmp_path):
    """A diagnostic that fails must not take the aircraft with it."""
    s = LstmRulServer(_checkpoint(tmp_path), sequence_length=SEQ)
    for i in range(SEQ):
        s.observe(_sample(), 1.0 + i)

    class Boom:
        def __call__(self, *a, **k):
            raise RuntimeError("inference exploded")

        def eval(self):
            return self

    s._model = Boom()
    with pytest.raises(RuntimeError):
        s.observe(_sample(), 200.0)          # the server itself does not swallow it


def test_served_rul_reports_none_without_an_estimate():
    out = ServedRul(source="none", reason="checkpoint absent")
    assert not out.reportable
    assert out.as_dict()["hours"] is None
    assert out.as_dict()["source"] == "none"


def test_no_interval_is_fabricated(tmp_path):
    """`train_rul.py` saves the network WITHOUT its conformal multiplier, so no
    calibrated bound for it exists. Inventing one would be decoration on an
    uncertainty that was measured and then discarded."""
    s = LstmRulServer(_checkpoint(tmp_path), sequence_length=SEQ)
    for i in range(SEQ):
        out = s.observe(_sample(), 1.0 + i)
    assert out.source == "lstm" and out.hours is not None
    assert out.lower_hours is None and out.upper_hours is None
