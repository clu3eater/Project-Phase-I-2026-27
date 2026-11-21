"""Tier 3: deep supervised detection -- PRD Part 2 section 11.1.

Tier 1 says a limit was crossed. Tier 2 says the combination of channels is
unusual. Neither says WHICH of the eight problem-statement faults is present,
and that is the question a maintenance engineer actually has to answer before
touching the aircraft. Tier 3 is the tier that names the fault.

Two models live here:

  LstmAutoencoder   unsupervised. Reconstructs a 30-step window; the
                    reconstruction error is an anomaly score. This is
                    algorithm 4 of the Tier-2 ensemble in PRD Part 2 s11.1,
                    implemented here because it is a deep model and shares the
                    sequence machinery.

  MultiTaskNet      supervised, three heads on a shared recurrent trunk:
                    is anything wrong, which faults, and how severe.

WHY ONE NETWORK WITH THREE HEADS
--------------------------------
The three questions share almost all their evidence -- a rising CHT residual
is the same observation whether you are asking "is this abnormal", "is this
cooling degradation", or "how bad is it". Training three separate networks
would learn that representation three times from the same data and disagree
with itself at the edges: an engine flagged anomalous but classified healthy.
One trunk cannot disagree with itself.

FRAMEWORK
---------
PRD Part 2 s11.1 names TensorFlow/Keras. This uses PyTorch, per decision D3
and docs/PRD_DEVIATIONS.md DEV-6, because the deployment path is ONNX Runtime
INT8 on the edge node and PyTorch exports to it cleanly on every target
platform. Layer sizes and every hyper-parameter in
``thresholds.detectors.tier3`` are preserved exactly.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
import torch
from torch import nn

from common import config
from layer3_ai import features as feat


def _cfg() -> dict:
    return config.load_thresholds()["detectors"]["tier3"]


def set_seed(seed: int = 0) -> None:
    torch.manual_seed(seed)
    np.random.seed(seed)


# ---------------------------------------------------------------------------
# Algorithm 4: LSTM autoencoder
# ---------------------------------------------------------------------------


class LstmAutoencoder(nn.Module):
    """Encoder(LSTM) -> bottleneck -> Decoder(LSTM), per PRD Part 2 s11.1.

    Trained on HEALTHY windows only. It learns to reproduce what a healthy
    engine does; anything it reconstructs badly is, by construction, unlike
    anything it was shown. That is why the training set must be clean --
    an autoencoder taught on faulty data learns to reconstruct faults
    perfectly and reports them as normal.
    """

    def __init__(self, n_features: int, *, encoder: int = 32, bottleneck: int = 16,
                 decoder: int = 32) -> None:
        super().__init__()
        self.encoder = nn.LSTM(n_features, encoder, batch_first=True)
        self.to_bottleneck = nn.Linear(encoder, bottleneck)
        self.from_bottleneck = nn.Linear(bottleneck, decoder)
        self.decoder = nn.LSTM(decoder, decoder, batch_first=True)
        self.out = nn.Linear(decoder, n_features)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        _, (h, _) = self.encoder(x)
        z = self.to_bottleneck(h[-1])
        # The bottleneck is a single vector for the whole window, repeated
        # across time for the decoder. Feeding the encoder's per-step outputs
        # forward instead would let the model copy the input straight through
        # and reconstruct everything -- including faults -- perfectly.
        seq = self.from_bottleneck(z).unsqueeze(1).repeat(1, x.size(1), 1)
        y, _ = self.decoder(seq)
        return self.out(y)

    @torch.no_grad()
    def reconstruction_error(self, x: torch.Tensor) -> torch.Tensor:
        self.eval()
        return ((self(x) - x) ** 2).mean(dim=(1, 2))


# ---------------------------------------------------------------------------
# The multi-task classifier
# ---------------------------------------------------------------------------


class MultiTaskNet(nn.Module):
    """Shared LSTM trunk, three heads (PRD Part 2 s11.1 Tier 3).

    Trunk:     LSTM(64) -> Dropout(0.2) -> LSTM(32) -> Dense(32)
    Anomaly:   Dense(1)  -> is anything wrong at all
    Fault:     Dense(8)  -> which of the eight problem-statement faults
    Severity:  Dense(1)  -> how far progressed

    THE FAULT HEAD IS MULTI-LABEL, NOT SOFTMAX
    PRD Part 2 s11.1 specifies ``Dense(8, softmax)``. Softmax asserts the eight
    faults are mutually exclusive, and in this fleet they are not: 21,050
    training rows (6.6 %) carry two or three simultaneous faults, because a
    real engine can be losing cooling AND wearing a bearing at the same time.
    A softmax head cannot represent that -- it must split its probability mass
    between them, so it under-reports both, and the second fault is likeliest
    to be missed exactly when the engine is worst. Sigmoid per class with
    binary cross-entropy models each fault independently, which is what the
    data actually contains. See docs/PRD_DEVIATIONS.md DEV-51.
    """

    def __init__(self, n_features: int, *, lstm1: int = 64, dropout: float = 0.2,
                 lstm2: int = 32, dense: int = 32, n_classes: int = 8) -> None:
        super().__init__()
        self.lstm1 = nn.LSTM(n_features, lstm1, batch_first=True)
        self.drop = nn.Dropout(dropout)
        self.lstm2 = nn.LSTM(lstm1, lstm2, batch_first=True)
        self.dense = nn.Sequential(nn.Linear(lstm2, dense), nn.ReLU())
        self.head_anomaly = nn.Linear(dense, 1)
        self.head_fault = nn.Linear(dense, n_classes)
        self.head_severity = nn.Linear(dense, 1)

    def forward(self, x: torch.Tensor) -> dict[str, torch.Tensor]:
        y, _ = self.lstm1(x)
        y = self.drop(y)
        y, (h, _) = self.lstm2(y)
        z = self.dense(h[-1])
        return {
            # Logits, not probabilities: the losses are the numerically stable
            # *_with_logits forms, and callers apply sigmoid explicitly.
            "anomaly": self.head_anomaly(z).squeeze(-1),
            "fault": self.head_fault(z),
            "severity": self.head_severity(z).squeeze(-1),
        }


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


@dataclass
class TrainReport:
    epochs: int = 0
    best_epoch: int = 0
    best_val_loss: float = float("inf")
    # Higher-is-better selection score (validation macro-F1 for the
    # classifier). The autoencoder has no such metric and uses the loss.
    best_score: float = -1.0
    history: list[dict] = field(default_factory=list)
    stopped_early: bool = False
    seconds: float = 0.0


def _batches(n: int, size: int, rng: np.random.Generator, shuffle: bool = True):
    idx = rng.permutation(n) if shuffle else np.arange(n)
    for i in range(0, n, size):
        yield idx[i : i + size]


def train_autoencoder(
    model: LstmAutoencoder,
    x_train: np.ndarray,
    x_val: np.ndarray,
    *,
    epochs: int = 40,
    batch_size: int = 256,
    lr: float = 1e-3,
    patience: int = 10,
    seed: int = 0,
) -> TrainReport:
    """Fit on healthy windows. Early stopping on validation loss."""
    set_seed(seed)
    rng = np.random.default_rng(seed)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    xt = torch.tensor(x_train, dtype=torch.float32)
    xv = torch.tensor(x_val, dtype=torch.float32)

    rep = TrainReport()
    best_state = None
    bad = 0
    started = time.time()
    for ep in range(1, epochs + 1):
        model.train()
        total = 0.0
        for b in _batches(len(xt), batch_size, rng):
            xb = xt[b]
            opt.zero_grad()
            loss = ((model(xb) - xb) ** 2).mean()
            loss.backward()
            opt.step()
            total += float(loss.detach()) * len(b)
        model.eval()
        with torch.no_grad():
            val = float(((model(xv) - xv) ** 2).mean())
        rep.history.append({"epoch": ep, "train": total / len(xt), "val": val})
        if val < rep.best_val_loss - 1e-6:
            rep.best_val_loss, rep.best_epoch, bad = val, ep, 0
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= patience:
                rep.stopped_early = True
                break
    rep.epochs = len(rep.history)
    rep.seconds = time.time() - started
    if best_state is not None:
        # Restore the best epoch, not the last. Without this, early stopping
        # detects overfitting and then ships the overfitted weights anyway.
        model.load_state_dict(best_state)
    return rep


def train_multitask(
    model: MultiTaskNet,
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
    *,
    epochs: int = 40,
    batch_size: int = 256,
    lr: float = 1e-3,
    patience: int = 10,
    seed: int = 0,
    noise_sigma: float = 0.01,
    task_weights: tuple[float, float, float] = (1.0, 1.0, 0.5),
) -> TrainReport:
    """Train the three heads jointly.

    ``y`` is the per-class fault severity in [0, 1]. The anomaly target is
    derived from it (any class expressed) and the severity target is its
    maximum, so all three heads are supervised from one label array and cannot
    disagree about what the ground truth was.

    POSITIVE-CLASS WEIGHTING
    The eight faults are far from balanced -- some appear in a few per cent of
    windows. Unweighted BCE would find it cheaper to predict "absent" for the
    rare ones forever and still score well, which is precisely the failure a
    maintenance engineer would never forgive. Each class therefore carries a
    ``pos_weight`` of neg/pos, capped so a very rare class cannot destabilise
    the gradient.

    Gaussian noise (sigma 0.01) is added to training inputs, per PRD Part 2
    s11.1 "Data augmentation".
    """
    set_seed(seed)
    rng = np.random.default_rng(seed)
    opt = torch.optim.Adam(model.parameters(), lr=lr)

    xt = torch.tensor(x_train, dtype=torch.float32)
    yt = torch.tensor(y_train, dtype=torch.float32)
    xv = torch.tensor(x_val, dtype=torch.float32)
    yv = torch.tensor(y_val, dtype=torch.float32)

    present_t = (yt > 0.05).float()
    present_v = (yv > 0.05).float()
    pos = present_t.sum(dim=0)
    neg = len(present_t) - pos
    # Capped at 8. At 20 the loss was so dominated by the rare classes that
    # the model predicted them almost everywhere: measured macro recall 0.63
    # against macro precision 0.30. Rebalancing must make a rare class visible,
    # not make it the default answer.
    pos_weight = torch.clamp(neg / torch.clamp(pos, min=1.0), max=8.0)

    bce_fault = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    bce_anom = nn.BCEWithLogitsLoss()
    mse = nn.MSELoss()
    w_a, w_f, w_s = task_weights

    def losses(out, y_present, y_sev, y_any):
        return (
            w_a * bce_anom(out["anomaly"], y_any)
            + w_f * bce_fault(out["fault"], y_present)
            + w_s * mse(torch.sigmoid(out["severity"]), y_sev)
        )

    rep = TrainReport()
    best_state = None
    bad = 0
    started = time.time()
    for ep in range(1, epochs + 1):
        model.train()
        total = 0.0
        for b in _batches(len(xt), batch_size, rng):
            xb = xt[b]
            if noise_sigma > 0:
                xb = xb + torch.randn_like(xb) * noise_sigma
            yb = present_t[b]
            opt.zero_grad()
            loss = losses(model(xb), yb, yt[b].max(dim=1).values,
                          (yb.max(dim=1).values > 0).float())
            loss.backward()
            opt.step()
            total += float(loss.detach()) * len(b)

        model.eval()
        with torch.no_grad():
            out_v = model(xv)
            val = float(losses(out_v, present_v, yv.max(dim=1).values,
                               (present_v.max(dim=1).values > 0).float()))
            # Select on validation MACRO-F1, not on the composite loss.
            #
            # The loss mixes three tasks with positive-class weighting, so it
            # is only a proxy for what the model is for. Selecting on it stopped
            # training at epoch 3 and shipped a classifier with 0.515 anomaly
            # recall, while the metric that matters was still improving.
            # Macro-F1 is the objective, so it is what early stopping watches.
            prob_v = torch.sigmoid(out_v["fault"]).numpy()
            score = multilabel_metrics(prob_v, yv.numpy())["macro_f1"]
        rep.history.append(
            {"epoch": ep, "train": total / len(xt), "val": val, "val_macro_f1": score}
        )
        if score > rep.best_score + 1e-6:
            rep.best_score, rep.best_val_loss, rep.best_epoch, bad = score, val, ep, 0
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= patience:
                rep.stopped_early = True
                break
    rep.epochs = len(rep.history)
    rep.seconds = time.time() - started
    if best_state is not None:
        model.load_state_dict(best_state)
    return rep


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------


@torch.no_grad()
def predict(model: MultiTaskNet, x: np.ndarray, batch_size: int = 1024) -> dict[str, np.ndarray]:
    """Probabilities, not logits -- what the twin's predicted_state expects."""
    model.eval()
    anom, fault, sev = [], [], []
    xt = torch.tensor(x, dtype=torch.float32)
    for i in range(0, len(xt), batch_size):
        out = model(xt[i : i + batch_size])
        anom.append(torch.sigmoid(out["anomaly"]).numpy())
        fault.append(torch.sigmoid(out["fault"]).numpy())
        sev.append(torch.sigmoid(out["severity"]).numpy())
    return {
        "anomaly": np.concatenate(anom) if anom else np.zeros(0),
        "fault": np.concatenate(fault) if fault else np.zeros((0, 8)),
        "severity": np.concatenate(sev) if sev else np.zeros(0),
    }


class Tier3Detector:
    """Both deep models behind one interface, ready for the fusion layer."""

    def __init__(self, feature_set: feat.FeatureSet | None = None) -> None:
        c = _cfg()
        self.cfg = c
        self.features = feature_set or feat.extended()
        self.sequence_length = int(c["sequence_length"])
        self.threshold_percentile = float(c["threshold_percentile"])
        ae = c["lstm_ae"]
        cl = c["classifier"]
        n = len(self.features)
        self.autoencoder = LstmAutoencoder(
            n, encoder=int(ae["encoder_units"]), bottleneck=int(ae["bottleneck"]),
            decoder=int(ae["decoder_units"]),
        )
        self.net = MultiTaskNet(
            n, lstm1=int(cl["lstm1"]), dropout=float(cl["dropout"]),
            lstm2=int(cl["lstm2"]), dense=int(cl["dense"]),
            n_classes=int(cl["n_classes"]),
        )
        self.ae_threshold: float | None = None

    def calibrate_autoencoder(self, x_healthy: np.ndarray) -> float:
        """95th percentile of healthy reconstruction error (PRD Part 2 s11.1).

        Set on healthy TRAINING windows. Choosing it on the test set would make
        the reported false-positive rate a description of the test set rather
        than a prediction about the fleet.
        """
        err = self.autoencoder.reconstruction_error(
            torch.tensor(x_healthy, dtype=torch.float32)
        ).numpy()
        self.ae_threshold = float(np.percentile(err, self.threshold_percentile))
        return self.ae_threshold

    @torch.no_grad()
    def anomaly_score(self, x: np.ndarray, batch_size: int = 1024) -> np.ndarray:
        """Reconstruction error scaled by the healthy threshold.

        Divided by the calibrated threshold so 1.0 means "at the boundary",
        putting it on the same footing as the Tier-2 scores it is fused with.
        """
        errs = []
        xt = torch.tensor(x, dtype=torch.float32)
        for i in range(0, len(xt), batch_size):
            errs.append(self.autoencoder.reconstruction_error(xt[i : i + batch_size]).numpy())
        err = np.concatenate(errs) if errs else np.zeros(0)
        if not self.ae_threshold:
            return err
        return err / self.ae_threshold

    def predict(self, x: np.ndarray) -> dict[str, np.ndarray]:
        return predict(self.net, x)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def _best_threshold(p: np.ndarray, y: np.ndarray, grid_t: np.ndarray) -> float:
    """The lowest threshold whose F1 is within 2 % of the best on this grid."""
    f1s = []
    for th in grid_t:
        pred = p > th
        tp = int(np.sum(pred & y))
        fp = int(np.sum(pred & ~y))
        fn = int(np.sum(~pred & y))
        pr = tp / (tp + fp) if tp + fp else 0.0
        rc = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(2 * pr * rc / (pr + rc) if pr + rc else 0.0)
    f1s = np.asarray(f1s)
    # The F1 curve is usually flat near its peak, so the argmax lands on
    # whichever grid point noise happened to favour. Picked that way on one
    # split, injector_abnormal got a threshold of 0.84 and then scored F1 0.000
    # on the test engines -- nothing there ever exceeded it. The lowest
    # threshold statistically indistinguishable from the best is the one that
    # survives a shift in prevalence between splits.
    good = np.where(f1s >= f1s.max() - 0.02 * max(f1s.max(), 1e-9))[0]
    return float(grid_t[good[0]]) if len(good) else 0.5


# How many positive windows a class needs in validation before its threshold is
# placed there rather than on training predictions.
MIN_VAL_POSITIVE = 200


def tune_thresholds(
    prob: np.ndarray,
    truth: np.ndarray,
    *,
    grid: int = 49,
    val_prob: np.ndarray | None = None,
    val_truth: np.ndarray | None = None,
) -> np.ndarray:
    """Per-class decision threshold maximising F1, one per fault.

    A single 0.5 cut-off is wrong when the eight classes differ in prevalence
    by an order of magnitude -- and after positive-class weighting the logits
    are deliberately not calibrated to 0.5 anyway.

    Fitted on VALIDATION where the class has enough positives there, and on
    TRAINING where it does not.

    Fitting every threshold on training predictions was the earlier design, on
    the sound argument that a split BY ENGINE leaves some validation engines
    carrying no instance of a class at all -- a threshold cannot be placed on a
    class that does not appear, and tuned that way injector_abnormal once drew
    0.84 and scored F1 0.000 on test.

    But the model has MEMORISED the training engines, so its probabilities
    there are over-confident, and a threshold placed on that distribution sits
    too high for engines it has never seen. abnormal_vibration is the measured
    case: ROC-AUC 0.977 on the test engines -- the ranking is nearly perfect --
    and recall 0.175 at the training-fitted cut of 0.56. The model was right and
    the threshold was in the wrong place.

    So each class is placed wherever it can honestly be placed: on validation
    when at least ``MIN_VAL_POSITIVE`` positive windows are there, which is the
    distribution that matches unseen engines, and on training otherwise, which
    is better than a class with no threshold at all. The test engines are never
    touched either way.
    """
    y = truth > 0.05
    yv = val_truth > 0.05 if val_truth is not None else None
    grid_t = np.linspace(0.02, 0.98, grid)
    out = np.full(prob.shape[1], 0.5)
    for i in range(prob.shape[1]):
        if yv is not None and int(yv[:, i].sum()) >= MIN_VAL_POSITIVE:
            out[i] = _best_threshold(val_prob[:, i], yv[:, i], grid_t)
        elif y[:, i].any():
            out[i] = _best_threshold(prob[:, i], y[:, i], grid_t)
        # else: the class appears nowhere it can be fitted; 0.5 stands and the
        # metric will say so rather than a tuned threshold hiding it.
    return out


# No class is excluded from the macro average any more.
#
# This used to hold "sensor_drift", on the stated grounds that it "is not an
# injectable fault". That was true only because the fleet generator excluded
# it, and the exclusion was itself a mistake: the generator conflated the slow
# ageing DRIFT every transducer accumulates with a sensor-drift FAULT, which is
# a separate bias field. The consequence was that lab_sensor_drift carried zero
# positive rows on zero engines, so the class could not be learned -- and the
# conclusion "Tier 3 cannot learn it and never will from this dataset" was a
# description of the bug rather than of the design.
#
# With the generator dealing all eight of the problem statement's classes, the
# class has data and is scored like any other. Whether the model learns it WELL
# is now a measurement rather than an assumption; an instrument fault should be
# separable from a real process change precisely because the twin holds a
# physics reference (PRD Part 2 s10.5), and Tier 1's dual-lane vote and
# bias-deviation rules remain the independent path to it.
UNLEARNABLE_CLASSES: tuple[str, ...] = ()


def multilabel_metrics(
    prob: np.ndarray,
    truth: np.ndarray,
    threshold: float | np.ndarray = 0.5,
) -> dict[str, float]:
    """Per-class and macro precision/recall/F1 for the fault head.

    Macro-averaged, not micro. Micro would be dominated by whichever faults are
    common and hide a rare-but-serious class the model never predicts -- which
    is exactly the class a maintenance engineer most needs named.

    ``threshold`` may be a scalar or one value per class.
    """
    thr = np.broadcast_to(np.asarray(threshold, dtype=float), (prob.shape[1],))
    pred = prob > thr[None, :]
    y = truth > 0.05
    per: dict[str, dict[str, float]] = {}
    f1s, precs, recs = [], [], []
    skipped: list[str] = []
    for i, col in enumerate(feat.FAULT_LABEL_COLUMNS):
        tp = int(np.sum(pred[:, i] & y[:, i]))
        fp = int(np.sum(pred[:, i] & ~y[:, i]))
        fn = int(np.sum(~pred[:, i] & y[:, i]))
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        f = 2 * p * r / (p + r) if p + r else 0.0
        name = col[4:]
        per[name] = {
            "precision": p, "recall": r, "f1": f,
            "support": int(y[:, i].sum()), "threshold": float(thr[i]),
        }
        if name in UNLEARNABLE_CLASSES:
            skipped.append(name)
            continue
        precs.append(p)
        recs.append(r)
        f1s.append(f)
    # Subset accuracy: every one of the eight labels correct on a window.
    exact = float(np.mean(np.all(pred == y, axis=1)))
    all_f1 = [per[c[4:]]["f1"] for c in feat.FAULT_LABEL_COLUMNS]
    return {
        "macro_precision": float(np.mean(precs)) if precs else 0.0,
        "macro_recall": float(np.mean(recs)) if recs else 0.0,
        "macro_f1": float(np.mean(f1s)) if f1s else 0.0,
        # Reported alongside so the exclusion is visible rather than assumed.
        "macro_f1_all_eight": float(np.mean(all_f1)),
        "excluded": skipped,
        "exact_match": exact,
        "per_class": per,
    }
