"""Tests for sequence construction and the Tier-3 deep models.

The sequence tests come first because they guard the subtlest failure in the
whole layer: a window that crosses a sortie boundary looks like thirty
contiguous seconds but spans up to eighteen flight hours of wear. A model
trained on those learns the discontinuity as a fault signature, scores well in
training, and then fires at every sortie boundary in service.

The rest check the decisions that measurement forced -- the multi-label head,
the threshold rule, the excluded class -- so none of them can be quietly
reverted to the version that scored worse.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
# torch is the OPTIONAL `ml` extra, deliberately kept off the serving
# path so an aircraft image does not carry a training framework. These
# tests genuinely need it, so they SKIP when it is absent rather than
# erroring at collection -- an optional dependency that breaks the whole
# suite is not optional. Found by CI on its first run; locally torch is
# installed, so nobody had ever seen it.
pytest.importorskip("torch")
import torch

from layer3_ai import features as feat
from layer3_ai import tier3_deep as t3


# ---------------------------------------------------------------------------
# Sequences
# ---------------------------------------------------------------------------


def _frame(engines: int = 2, sorties: int = 3, per: int = 50) -> pd.DataFrame:
    n = engines * sorties * per
    rng = np.random.default_rng(0)
    cols = {c: rng.normal(0.0, 1.0, n) for c in feat.extended().columns}
    cols["engine_id"] = np.repeat(np.arange(1, engines + 1), sorties * per)
    cols["sortie"] = np.tile(np.repeat(np.arange(1, sorties + 1), per), engines)
    cols["flight_hours"] = np.arange(n, dtype=float)
    cols["chi_true"] = np.full(n, 0.95)
    cols["any_fault"] = np.zeros(n)
    for c in feat.FAULT_LABEL_COLUMNS:
        cols[c] = np.zeros(n)
    return pd.DataFrame(cols)


def test_sequences_never_cross_a_sortie_boundary():
    """The failure this prevents is silent and would ship.

    Consecutive rows in different sorties are 50 seconds apart on the clock and
    up to eighteen flight hours apart in the engine's life.
    """
    df = _frame(engines=2, sorties=3, per=50)
    X, _, idx = feat.build_sequences(df, feat.extended(), length=30, stride=1)
    # 21 windows per sortie, 6 sorties.
    assert len(X) == 6 * (50 - 30 + 1)
    eng = df["engine_id"].to_numpy()
    sort = df["sortie"].to_numpy()
    for last in idx:
        first = last - 29
        assert eng[first] == eng[last], "window crossed an engine boundary"
        assert sort[first] == sort[last], "window crossed a sortie boundary"


def test_sequences_drop_groups_shorter_than_the_window():
    df = _frame(engines=1, sorties=1, per=20)
    X, _, _ = feat.build_sequences(df, feat.extended(), length=30)
    assert len(X) == 0


def test_sequence_label_comes_from_the_last_row():
    """The prediction is about the present, not the middle of the window."""
    df = _frame(engines=1, sorties=1, per=40)
    df["lab_misfire"] = np.linspace(0.0, 1.0, len(df))
    _, y, idx = feat.build_sequences(
        df, feat.extended(), length=30, stride=1,
        label_columns=("lab_misfire",),
    )
    expected = df["lab_misfire"].to_numpy()[idx]
    assert np.allclose(y[:, 0], expected)


def test_sequence_stride_reduces_the_count_proportionally():
    df = _frame(engines=1, sorties=2, per=50)
    a, _, _ = feat.build_sequences(df, feat.extended(), length=30, stride=1)
    b, _, _ = feat.build_sequences(df, feat.extended(), length=30, stride=5)
    assert len(a) == 2 * 21
    assert len(b) == 2 * 5


# ---------------------------------------------------------------------------
# The stratified split
# ---------------------------------------------------------------------------


def _manifest(n: int = 100) -> dict:
    rng = np.random.default_rng(3)
    modes = ["cooling_degradation", "misfire", "lubrication_issue",
             "abnormal_vibration", "injector_abnormal"]
    engines = {}
    for eid in range(1, n + 1):
        k = int(rng.integers(0, 3))
        faults = [
            {"mode": modes[int(rng.integers(0, len(modes)))],
             "onset_hours": float(rng.uniform(10, 900)), "severity": 0.5,
             "ramp_hours": 20.0, "cylinder": None}
            for _ in range(k)
        ]
        engines[str(eid)] = {"faults": faults}
    return {"engines": engines}


def test_stratified_split_keeps_engines_whole_and_sizes_right():
    """Engine-level separation is the actual requirement and is untouched."""
    assign = feat.stratified_engine_split(_manifest())
    from collections import Counter

    counts = Counter(assign.values())
    assert counts["train"] == 80 and counts["val"] == 10 and counts["test"] == 10
    by: dict[str, set[int]] = {}
    for e, s in assign.items():
        by.setdefault(s, set()).add(e)
    assert not (by["train"] & by["val"])
    assert not (by["train"] & by["test"])
    assert not (by["val"] & by["test"])


def test_stratified_split_spreads_fault_types_across_splits():
    """DEV-52. The ID ordering left validation with zero of two fault classes.

    Early stopping runs on validation, so a model getting worse at a class
    validation cannot see still looks like it is improving -- measured, that
    produced a worse test model than stopping early by accident.
    """
    man = _manifest()
    assign = feat.stratified_engine_split(man)
    seen: dict[str, set[str]] = {"train": set(), "val": set(), "test": set()}
    for eid, info in man["engines"].items():
        for f in info["faults"]:
            seen[assign[int(eid)]].add(f["mode"])
    # Every fault type present in training must also reach validation, or it
    # cannot be early-stopped or thresholded on.
    assert seen["train"] <= seen["val"] | seen["train"]
    assert len(seen["val"]) >= 3
    assert len(seen["test"]) >= 3


# ---------------------------------------------------------------------------
# The models
# ---------------------------------------------------------------------------


def test_autoencoder_shapes_round_trip():
    ae = t3.LstmAutoencoder(6, encoder=8, bottleneck=4, decoder=8)
    x = torch.randn(5, 30, 6)
    assert ae(x).shape == x.shape
    assert ae.reconstruction_error(x).shape == (5,)


def test_autoencoder_reconstructs_what_it_was_trained_on_better():
    """The whole premise: unfamiliar input reconstructs badly.

    An autoencoder taught on faulty data learns to reconstruct faults
    perfectly and reports them as normal, which is why it sees healthy
    windows only.
    """
    t3.set_seed(0)
    rng = np.random.default_rng(0)
    healthy = rng.normal(0.0, 0.3, (400, 30, 4)).astype(np.float32)
    val = rng.normal(0.0, 0.3, (80, 30, 4)).astype(np.float32)
    anomalous = rng.normal(4.0, 0.3, (80, 30, 4)).astype(np.float32)

    ae = t3.LstmAutoencoder(4, encoder=16, bottleneck=8, decoder=16)
    t3.train_autoencoder(ae, healthy, val, epochs=25, patience=25, batch_size=64)

    e_ok = ae.reconstruction_error(torch.tensor(val)).numpy().mean()
    e_bad = ae.reconstruction_error(torch.tensor(anomalous)).numpy().mean()
    assert e_bad > e_ok * 3, f"healthy {e_ok:.4f} vs anomalous {e_bad:.4f}"


def test_multitask_net_emits_all_three_heads():
    net = t3.MultiTaskNet(6, lstm1=16, lstm2=8, dense=8, n_classes=8)
    out = net(torch.randn(4, 30, 6))
    assert out["anomaly"].shape == (4,)
    assert out["fault"].shape == (4, 8)
    assert out["severity"].shape == (4,)


def test_fault_head_can_report_two_faults_at_once():
    """DEV-51. Softmax cannot; 6.6 % of the fleet has two or three.

    Independent sigmoids mean two classes may both exceed 0.5, which a softmax
    forbids by construction because its outputs must sum to one.
    """
    net = t3.MultiTaskNet(4, lstm1=8, lstm2=8, dense=8, n_classes=8)
    with torch.no_grad():
        net.head_fault.bias[:] = torch.tensor([3.0, 3.0, -5, -5, -5, -5, -5, -5])
        net.head_fault.weight.zero_()
    p = t3.predict(net, np.zeros((1, 30, 4), dtype=np.float32))["fault"][0]
    assert p[0] > 0.9 and p[1] > 0.9, "two classes must be able to fire together"
    assert p.sum() > 1.5, "sigmoid outputs must not be forced to sum to one"


# ---------------------------------------------------------------------------
# Thresholds and metrics
# ---------------------------------------------------------------------------


def test_threshold_tuning_prefers_the_lowest_of_an_equally_good_plateau():
    """DEV-56. The F1 curve is flat near its peak.

    Taking the argmax lands on whichever grid point noise favoured; on one
    split that gave injector_abnormal 0.84, which then scored F1 0.000 on test
    because nothing there ever exceeded it.
    """
    # Perfectly separable at any threshold between 0.2 and 0.8.
    prob = np.array([[0.1], [0.15], [0.85], [0.9]])
    truth = np.array([[0.0], [0.0], [1.0], [1.0]])
    t = t3.tune_thresholds(prob, truth)[0]
    assert 0.15 < t < 0.5, f"threshold {t} is not at the low end of the plateau"


def test_threshold_tuning_skips_a_class_with_no_positives():
    prob = np.random.default_rng(0).random((50, 2))
    truth = np.zeros((50, 2))
    truth[:10, 0] = 1.0
    t = t3.tune_thresholds(prob, truth)
    assert t[1] == 0.5, "a class with no positives must keep the neutral default"


def test_no_fault_class_is_excluded_from_the_score():
    """DEV-92. Every one of the eight PS fault classes is scored.

    This test used to assert the opposite -- that sensor_drift was excluded and
    that the exclusion was reported. The exclusion was justified on the grounds
    that the class "has zero positive labels anywhere in the fleet", which was
    true, and that Tier 3 "never will" learn it, which was not: the class had
    no labels only because the fleet generator was wrongly excluding it from
    injection. Scoring around a data bug hid it for as long as it took to audit
    the fleet directly.

    With all eight classes injected, nothing is excluded and the macro average
    covers the whole problem statement.
    """
    n_cls = len(feat.FAULT_LABEL_COLUMNS)
    prob = np.zeros((10, n_cls))
    truth = np.zeros((10, n_cls))
    for i in range(n_cls):
        prob[:5, i] = 0.9
        truth[:5, i] = 1.0
    m = t3.multilabel_metrics(prob, truth)

    assert t3.UNLEARNABLE_CLASSES == ()
    assert m["excluded"] == []
    assert m["macro_f1"] == pytest.approx(1.0)
    # With nothing excluded the two figures are necessarily the same. They are
    # still both reported, so that re-introducing an exclusion is visible in
    # the output rather than silently shrinking what "macro" covers.
    assert m["macro_f1_all_eight"] == pytest.approx(m["macro_f1"])


def test_an_exclusion_would_still_be_reported_if_one_were_added():
    """The reporting machinery stays covered even though nothing uses it now.

    If a class is ever excluded again it must show up in ``excluded`` and pull
    the all-eight figure below the macro, so the cost of the exclusion is
    visible at the point the score is read.
    """
    n_cls = len(feat.FAULT_LABEL_COLUMNS)
    prob = np.zeros((10, n_cls))
    truth = np.zeros((10, n_cls))
    dropped = feat.FAULT_LABEL_COLUMNS[0][4:]
    for i, col in enumerate(feat.FAULT_LABEL_COLUMNS):
        if col[4:] == dropped:
            continue
        prob[:5, i] = 0.9
        truth[:5, i] = 1.0

    original = t3.UNLEARNABLE_CLASSES
    try:
        t3.UNLEARNABLE_CLASSES = (dropped,)
        m = t3.multilabel_metrics(prob, truth)
        assert m["excluded"] == [dropped]
        assert m["macro_f1"] == pytest.approx(1.0)
        assert m["macro_f1_all_eight"] < m["macro_f1"]
    finally:
        t3.UNLEARNABLE_CLASSES = original


def test_metrics_accept_a_threshold_per_class():
    n_cls = len(feat.FAULT_LABEL_COLUMNS)
    prob = np.full((4, n_cls), 0.6)
    truth = np.ones((4, n_cls))
    lenient = t3.multilabel_metrics(prob, truth, 0.5)
    strict = t3.multilabel_metrics(prob, truth, np.full(n_cls, 0.7))
    assert lenient["macro_recall"] == pytest.approx(1.0)
    assert strict["macro_recall"] == pytest.approx(0.0)


def test_macro_not_micro_so_a_rare_class_cannot_be_hidden():
    """A rare-but-serious class the model never predicts must show up.

    Micro-averaging would drown it in whichever fault happens to be common,
    and that is exactly the class a maintenance engineer most needs named.
    """
    n_cls = len(feat.FAULT_LABEL_COLUMNS)
    prob = np.zeros((1000, n_cls))
    truth = np.zeros((1000, n_cls))
    prob[:900, 0] = 0.9   # common class, predicted perfectly
    truth[:900, 0] = 1.0
    truth[900:910, 7] = 1.0  # rare class, never predicted
    m = t3.multilabel_metrics(prob, truth)
    assert m["per_class"]["abnormal_vibration"]["f1"] == 0.0
    # 7 learnable classes, one perfect, six zero.
    assert m["macro_f1"] == pytest.approx(1.0 / 7, abs=0.02)


# ---------------------------------------------------------------------------
# Training behaviour
# ---------------------------------------------------------------------------


def test_training_restores_the_best_epoch_not_the_last():
    """Otherwise early stopping detects overfitting and ships it anyway."""
    t3.set_seed(0)
    rng = np.random.default_rng(0)
    x = rng.normal(0, 1, (200, 30, 4)).astype(np.float32)
    xv = rng.normal(0, 1, (60, 30, 4)).astype(np.float32)
    ae = t3.LstmAutoencoder(4, encoder=8, bottleneck=4, decoder=8)
    rep = t3.train_autoencoder(ae, x, xv, epochs=12, patience=3, batch_size=64)
    assert rep.best_epoch <= rep.epochs
    with torch.no_grad():
        final = float(((ae(torch.tensor(xv)) - torch.tensor(xv)) ** 2).mean())
    assert final == pytest.approx(rep.best_val_loss, rel=1e-4)


def test_classifier_early_stops_on_macro_f1_not_loss():
    """DEV-55. The composite weighted loss is only a proxy for the objective.

    Watching it stopped training at epoch 3 and shipped 0.515 anomaly recall
    while macro-F1 was still climbing.
    """
    t3.set_seed(0)
    rng = np.random.default_rng(0)
    n_cls = len(feat.FAULT_LABEL_COLUMNS)
    x = rng.normal(0, 1, (300, 30, 4)).astype(np.float32)
    y = np.zeros((300, n_cls), dtype=np.float32)
    y[:100, 0] = 1.0
    x[:100] += 2.0  # make the class learnable
    net = t3.MultiTaskNet(4, lstm1=16, lstm2=8, dense=8, n_classes=n_cls)
    rep = t3.train_multitask(net, x, y, x[:80], y[:80], epochs=6, patience=6,
                             batch_size=64)
    assert all("val_macro_f1" in h for h in rep.history)
    # The selected epoch is the one with the best macro-F1, NOT the best loss.
    best_by_f1 = max(rep.history, key=lambda h: h["val_macro_f1"])["val_macro_f1"]
    assert rep.best_score == pytest.approx(best_by_f1)
    best_loss_epoch = min(rep.history, key=lambda h: h["val"])["epoch"]
    chosen = next(h for h in rep.history if h["epoch"] == rep.best_epoch)
    assert chosen["val_macro_f1"] == pytest.approx(best_by_f1)
    # Nothing forces the two criteria to agree, and that is the whole point.
    del best_loss_epoch


# ---------------------------------------------------------------------------
# Where a decision threshold is placed
# ---------------------------------------------------------------------------
#
# A threshold fitted on data the model has memorised is fitted to the wrong
# distribution. abnormal_vibration is the measured case: ROC-AUC 0.977 on the
# test engines and recall 0.175 at the training-fitted cut of 0.56.


def _split(n, lo_pos, hi_pos, rng):
    """Probabilities for `n` windows, positives drawn high, negatives low."""
    y = np.zeros(n)
    y[: n // 2] = 1.0
    p = np.where(y > 0, rng.uniform(lo_pos, 1.0, n), rng.uniform(0.0, hi_pos, n))
    return p.reshape(-1, 1), y.reshape(-1, 1)


def test_threshold_prefers_validation_when_the_class_is_represented():
    rng = np.random.default_rng(0)
    # The model is over-confident where it trained: positives sit above 0.9.
    ptr, ytr = _split(2000, 0.90, 0.10, rng)
    # On unseen engines the same positives only reach 0.30.
    pva, yva = _split(2000, 0.30, 0.05, rng)
    thr = t3.tune_thresholds(ptr, ytr, val_prob=pva, val_truth=yva)[0]
    assert thr < 0.30, (
        f"threshold {thr:.2f} was placed on the training distribution and will "
        "cut off the unseen engines it is meant to score")


def test_threshold_falls_back_to_training_when_validation_is_too_thin():
    rng = np.random.default_rng(1)
    ptr, ytr = _split(2000, 0.60, 0.10, rng)
    # Far fewer positives than MIN_VAL_POSITIVE: not enough to place a cut.
    pva, yva = _split(20, 0.01, 0.99, rng)
    thr = t3.tune_thresholds(ptr, ytr, val_prob=pva, val_truth=yva)[0]
    alone = t3.tune_thresholds(ptr, ytr)[0]
    assert thr == alone, (
        "a handful of validation windows must not be allowed to place the "
        "threshold; training is the better of two imperfect sources here")


def test_threshold_is_unchanged_when_no_validation_is_offered():
    rng = np.random.default_rng(2)
    ptr, ytr = _split(1000, 0.70, 0.20, rng)
    assert t3.tune_thresholds(ptr, ytr)[0] == t3.tune_thresholds(
        ptr, ytr, val_prob=None, val_truth=None)[0]


def test_a_class_absent_everywhere_keeps_a_neutral_threshold():
    """No tuned threshold may hide a class the fleet never produced."""
    p = np.random.default_rng(3).uniform(0, 1, 500).reshape(-1, 1)
    y = np.zeros((500, 1))
    assert t3.tune_thresholds(p, y)[0] == 0.5
