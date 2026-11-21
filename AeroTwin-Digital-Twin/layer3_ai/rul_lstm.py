"""Data-driven remaining useful life -- PRD Part 2 sections 12.3 and 12.5.

The other half of the RUL estimate. ``rul_physics`` extrapolates a health
trend and can explain itself; this learns degradation patterns directly from
sequences and cannot. Section 12.5 fuses them by confidence, which is the right
arrangement: the interpretable estimate carries the argument, the learned one
carries the accuracy, and neither is trusted alone.

THE LOSS FUNCTION HAD TO BE CORRECTED
-------------------------------------
PRD Part 2 s12.3 asks for ``L = 0.7 x MSE + 0.3 x Score`` where Score is the
NASA C-MAPSS prognostics score, and states the intent plainly -- "penalizes
late predictions more than early predictions". The formula printed beside it
does the opposite. It penalises ``RUL_pred < RUL_true``, the CONSERVATIVE case,
and scores over-prediction at exactly zero:

    predicted 100 h when 200 h remained  ->  penalty 2190
    predicted 200 h when 100 h remained  ->  penalty    0

Trained against that, a network learns to over-estimate remaining life, which
is the one error in prognostics that puts an aircraft in the air past the point
the engine should have been pulled. The standard asymmetric score is used
instead, with the intent the PRD states. See docs/PRD_DEVIATIONS.md DEV-66.

CENSORED ENGINES TRAIN AGAINST A BOUND, NOT A VALUE
---------------------------------------------------
Twenty-seven of the hundred engines reach TBO without failing. Their recorded
RUL is a LOWER BOUND -- all that is known is that they had at least that much
life left. Training on it as though it were the truth teaches the network that
healthy engines are about to fail.

The response to that was to DROP them, and that was wrong in the other
direction: it discarded 39.9 % of windows, and the discard is not random -- it
removes precisely the healthy, long-lived engines. The survival literature
names both costs, efficiency and bias, and predicts the direction: an
over-estimate of failure risk, meaning UNDER-prediction of remaining life.
Measured here as a -123.7 h bias on the at-cap band.

They are now kept, and trained through the hinge in ``rul_loss``: below the
bound is a known error and is penalised; at or above it costs nothing. They
remain excluded from the reported METRICS, because a metric needs a known
truth and a bound is not one.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
import torch
from torch import nn

from common import config
from layer3_ai import rul_physics as rp


def _cfg() -> dict:
    return config.load_thresholds()["rul"]


class RulLstm(nn.Module):
    """LSTM(64) -> Dropout -> LSTM(32) -> Dropout -> Dense(16) -> Dense(1).

    Exactly the architecture of PRD Part 2 s12.3. The output is linear and
    unbounded during training; :func:`predict` clamps to non-negative, because
    a negative remaining life is not a conservative estimate, it is a
    meaningless one.
    """

    def __init__(self, n_features: int, *, lstm1: int = 64, lstm2: int = 32,
                 dense: int = 16, dropout: float = 0.2) -> None:
        super().__init__()
        self.lstm1 = nn.LSTM(n_features, lstm1, batch_first=True)
        self.drop1 = nn.Dropout(dropout)
        self.lstm2 = nn.LSTM(lstm1, lstm2, batch_first=True)
        self.drop2 = nn.Dropout(dropout)
        self.head = nn.Sequential(nn.Linear(lstm2, dense), nn.ReLU(), nn.Linear(dense, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        y, _ = self.lstm1(x)
        y = self.drop1(y)
        _, (h, _) = self.lstm2(y)
        return self.head(self.drop2(h[-1])).squeeze(-1)


def rul_loss(
    pred: torch.Tensor,
    true: torch.Tensor,
    censored: torch.Tensor | None = None,
    *,
    alpha: float = 0.7,
    beta: float = 0.3,
    tau_early: float = 13.0,
    tau_late: float = 10.0,
    scale: float = 100.0,
    late_weight: float = 3.0,
) -> torch.Tensor:
    """alpha x MSE + beta x asymmetric score (PRD Part 2 s12.3, corrected),
    with a survival hinge for RIGHT-CENSORED units.

    ``scale`` divides the hours before the exponential. Without it the score
    term overflows the moment an untrained network is a few hundred hours out
    -- exp(300/10) is 1e13 and the first gradient step destroys the weights.
    Dividing by 100 keeps the asymmetry (late still costs more than early at
    every magnitude) while keeping the term finite and trainable.

    ``late_weight`` exists because that compression, while necessary, very
    nearly removed the asymmetry it was protecting. Measured: at a 200 h
    error this loss charged late only 1.75x early, while the NASA score the
    model is JUDGED by charges 101x. The model was therefore optimised on a
    near-symmetric objective and graded on a violently asymmetric one, and it
    behaved accordingly -- a +44.5 h LATE bias on the informative band, when
    the asymmetric-loss literature reports such a loss should induce a
    negative (conservative) bias.

    The remedy is the stable one that literature recommends over steepening
    the exponential: weight the SQUARED term when the prediction is late. It
    is quadratic, so it cannot overflow the way a smaller ``scale`` would, and
    it acts hardest on exactly the large late errors that the score punishes
    and this model was producing. ``late_weight = 1.0`` restores the previous
    behaviour exactly.

    A late prediction says there is more life left than there is. That is the
    failure that puts an aircraft in the air on an engine that should have
    been pulled, which is why it is worth paying accuracy for.

    CENSORING
    ---------
    An engine withdrawn at TBO without failing has not told us its remaining
    life; it has told us a LOWER BOUND on it. Those units were previously
    DROPPED from training entirely -- 39.9 % of windows -- which the survival
    literature identifies as causing both a loss of efficiency and a bias,
    because censoring is not random here: it removes precisely the healthy,
    long-lived engines and leaves a training set of engines that failed early.
    The predicted consequence is over-estimation of failure risk, i.e.
    UNDER-prediction of remaining life, and that is what was measured -- a
    -123.7 h bias on the at-cap band.

    For a censored window the truth is ``true <= RUL_actual``, so:

      * predicting BELOW the bound is known to be wrong, and is penalised by
        how far below it falls;
      * predicting AT OR ABOVE the bound is consistent with everything known,
        and costs nothing.

    This is the hinge form used for censored samples in survival regression
    (MAE-hinge): loss = max(0, observed - predicted), zero above the bound.
    It is applied through the same alpha/beta split and the same scale as the
    uncensored term so the two are commensurate and one cannot quietly
    dominate the other.
    """
    d = (pred - true) / scale
    # d > 0 is LATE: the prediction claims more remaining life than there is.
    sq = d ** 2 * torch.where(d > 0,
                              torch.full_like(d, float(late_weight)),
                              torch.ones_like(d))
    score = torch.where(
        d < 0, torch.expm1(-d / (tau_early / 10.0)), torch.expm1(d / (tau_late / 10.0))
    )
    observed_loss = alpha * sq + beta * score

    if censored is None:
        return torch.mean(observed_loss)

    # Only the shortfall below the known lower bound is an error.
    short = torch.clamp((true - pred) / scale, min=0.0)
    censored_loss = alpha * short**2 + beta * torch.expm1(short / (tau_early / 10.0))

    return torch.mean(torch.where(censored > 0.5, censored_loss, observed_loss))


@dataclass
class RulTrainReport:
    epochs: int = 0
    best_epoch: int = 0
    best_val_loss: float = float("inf")
    history: list[dict] = field(default_factory=list)
    stopped_early: bool = False
    seconds: float = 0.0


def train_rul(
    model: RulLstm,
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
    c_train: np.ndarray | None = None,
    c_val: np.ndarray | None = None,
    *,
    epochs: int = 60,
    batch_size: int = 32,
    lr: float = 1e-3,
    patience: int = 15,
    seed: int = 0,
    loss_kwargs: dict | None = None,
) -> RulTrainReport:
    """Adam, early stopping on validation loss, best weights restored.

    Batch size 32 and patience 15 are the PRD's own figures (s12.3).
    """
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    sched = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, patience=5, factor=0.5)

    xt = torch.tensor(x_train, dtype=torch.float32)
    yt = torch.tensor(y_train, dtype=torch.float32)
    xv = torch.tensor(x_val, dtype=torch.float32)
    yv = torch.tensor(y_val, dtype=torch.float32)
    # Censoring indicators travel with the targets so a withdrawn engine is
    # scored against its lower bound rather than dropped.
    ct = None if c_train is None else torch.tensor(c_train, dtype=torch.float32)
    cv = None if c_val is None else torch.tensor(c_val, dtype=torch.float32)

    # The loss shape comes from the config, not from the defaults. Until
    # 2026-09-07 `rul.loss_weights` was read by nothing at all -- the defaults
    # happened to match, so the key looked live while editing it did nothing.
    if loss_kwargs is None:
        _c = _cfg()
        _w = _c.get("loss_weights") or {}
        lw = {"alpha": float(_w.get("mse", 0.7)),
              "beta": float(_w.get("nasa_score", 0.3)),
              "late_weight": float(_c.get("late_weight", 3.0))}
    else:
        lw = dict(loss_kwargs)

    rep = RulTrainReport()
    best_state = None
    bad = 0
    started = time.time()
    for ep in range(1, epochs + 1):
        model.train()
        total = 0.0
        order = rng.permutation(len(xt))
        for i in range(0, len(order), batch_size):
            b = order[i : i + batch_size]
            opt.zero_grad()
            loss = rul_loss(model(xt[b]), yt[b],
                            None if ct is None else ct[b], **lw)
            loss.backward()
            # RUL targets span hundreds of hours, so gradients can be large
            # early on. Clipping keeps the first few epochs from diverging.
            nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            opt.step()
            total += float(loss.detach()) * len(b)
        model.eval()
        with torch.no_grad():
            val = float(rul_loss(model(xv), yv, cv, **lw))
        sched.step(val)
        rep.history.append({"epoch": ep, "train": total / len(xt), "val": val})
        if val < rep.best_val_loss - 1e-9:
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
        model.load_state_dict(best_state)
    return rep


@torch.no_grad()
def predict(model: RulLstm, x: np.ndarray, batch_size: int = 1024) -> np.ndarray:
    model.eval()
    out = []
    xt = torch.tensor(x, dtype=torch.float32)
    for i in range(0, len(xt), batch_size):
        out.append(model(xt[i : i + batch_size]).numpy())
    return np.clip(np.concatenate(out) if out else np.zeros(0), 0.0, None)


@torch.no_grad()
def predict_with_interval(
    model: RulLstm, x: np.ndarray, *, passes: int = 30, seed: int = 0,
    q: float = 1.96,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Monte-Carlo dropout interval (PRD Part 0 s0.5 point 5).

    Dropout is left ACTIVE at inference and the network is run repeatedly; the
    spread across passes is the model's own uncertainty.

    ``q`` MULTIPLIES that spread, and defaults to the Gaussian 1.96 only so the
    function still works uncalibrated. It should be supplied by
    ``conformal_q`` -- see below for why the Gaussian value is wrong here.
    """
    torch.manual_seed(seed)
    model.train()  # keeps dropout on -- the point of the method
    xt = torch.tensor(x, dtype=torch.float32)
    draws = np.stack([model(xt).numpy() for _ in range(passes)])
    model.eval()
    mean = np.clip(draws.mean(axis=0), 0.0, None)
    sd = draws.std(axis=0)
    return mean, np.clip(mean - q * sd, 0.0, None), mean + q * sd


def conformal_q(
    model: RulLstm, x_cal: np.ndarray, y_cal: np.ndarray, *,
    alpha: float = 0.05, passes: int = 30, seed: int = 0,
) -> float:
    """Split-conformal multiplier giving the interval its advertised coverage.

    WHY THE GAUSSIAN 1.96 IS WRONG.
    MC dropout is a mean-field variational approximation, and mean-field
    posteriors are known to UNDERESTIMATE variance -- the published shortfall
    is 74-80 % coverage where 90 % was claimed, and far worse in some studies.
    Measured on this model it was worse still: the 95 % interval contained the
    truth **18.0 %** of the time, and was NARROWER (89.5 h) than the mean
    absolute error it was supposed to span (79.6 h).

    An interval that wrong is not merely useless. PRD Part 4 s7.4a forbids a
    bare RUL number precisely so the operator sees the uncertainty; an interval
    that understates it by a factor of five invites more confidence than the
    bare number would have, which is worse than showing nothing.

    Split conformal fixes this without assuming anything about the error
    distribution: on data the model did not train on, take the nonconformity
    score |y - mean| / sd, and use its (1-alpha) empirical quantile as the
    multiplier. Coverage is then guaranteed in finite samples under exchange-
    ability alone. The multiplier is a property of the CALIBRATION set, so it
    is fitted on validation and never on test.
    """
    # sigma is recovered from the interval predict_with_interval already
    # returns (hi = mean + 1.96 sigma at the default multiplier), rather than
    # re-running the dropout passes. One less 30-pass sweep, and no second
    # copy of the sampling loop to fall out of step with the first -- the
    # duplicate was also missing its no_grad context, which is how this
    # function failed the first time it ran.
    mean, _, hi = predict_with_interval(model, x_cal, passes=passes, seed=seed)
    sd = (hi - mean) / 1.96

    # FLOOR sigma AGAINST ITS OWN MEDIAN, not against a bare epsilon.
    #
    # Normalised conformal divides by sigma, so a handful of windows where the
    # dropout passes happen to agree drives the score to infinity and the
    # quantile with it. Measured on an untrained network, where sigma is
    # ~0 everywhere, the multiplier came out at 29,467 -- coverage was
    # perfect and the interval was several thousand hours wide, which is
    # correct and useless at the same time.
    #
    # Flooring at a tenth of the median sigma keeps the interval ADAPTIVE
    # where the model genuinely disagrees with itself, without letting the
    # quietest windows set the width for all of them.
    med = float(np.median(sd)) if len(sd) else 0.0
    sd = np.maximum(sd, max(med * 0.1, 1e-6))
    scores = np.abs(np.asarray(y_cal, dtype=float) - mean) / sd
    n = len(scores)
    if n == 0:
        return 1.96
    # The finite-sample conformal quantile: ceil((n+1)(1-alpha))/n.
    k = min(1.0, np.ceil((n + 1) * (1.0 - alpha)) / n)
    return float(np.quantile(scores, k))


# ---------------------------------------------------------------------------
# Fusion -- PRD Part 2 section 12.5
# ---------------------------------------------------------------------------


def fuse_rul(
    data_hours: float | None,
    physics: rp.RulEstimate,
    *,
    data_confidence: float,
    data_lower: float | None = None,
    data_upper: float | None = None,
) -> rp.RulEstimate:
    """Confidence-weighted combination of the two estimates.

        w_data = c_data / (c_data + c_physics)

    Per PRD Part 2 s12.5. Two behaviours the PRD states in prose and are
    implemented literally here: when only one estimator has anything to say,
    it is used alone rather than averaged against a default; and when both are
    uncertain the result is CONSERVATIVE -- the lower of the two -- because
    over-stating remaining life is the dangerous direction.
    """
    c_phys = float(physics.estimator_confidence)
    c_data = float(np.clip(data_confidence, 0.0, 1.0))

    if data_hours is None and not physics.reportable:
        out = rp.RulEstimate(source="fused", reason="neither estimator is ready")
        return out
    if data_hours is None:
        physics.source = "physics"
        return physics
    if not physics.reportable:
        return rp.RulEstimate(
            hours=float(data_hours), lower_hours=data_lower, upper_hours=data_upper,
            source="data", estimator_confidence=c_data,
            reason="physics trend not yet established",
        )

    total = c_data + c_phys
    if total <= 1e-9:
        # Both estimators are unsure. Take the lower figure rather than the
        # average: an averaged RUL that is too high reads as permission to fly.
        low = min(float(data_hours), float(physics.hours))
        return rp.RulEstimate(
            hours=low, lower_hours=0.0, upper_hours=max(float(data_hours), float(physics.hours)),
            source="fused", estimator_confidence=0.0,
            reason="both estimators uncertain -- reporting the conservative figure",
        )

    w_data = c_data / total
    w_phys = c_phys / total

    # DISAGREEMENT GATE.
    #
    # A confidence-weighted average is only meaningful when the two estimators
    # are describing the same thing. When they are far apart one of them is
    # simply wrong, and averaging a right answer with a wrong one produces a
    # third answer that is wrong by less -- which is not the same as being
    # right, and is dangerous when the error is upward.
    #
    # Measured on held-out engines: the LSTM scored RMSE 117.7 h (R2 +0.27),
    # the physics extrapolation 255.7 h (R2 -2.28), and the s12.5 weighted
    # average came out at 151.6 h -- WORSE THAN ITS OWN BEST COMPONENT. The
    # physics estimate carried a self-reported confidence of 0.8 against the
    # data estimate's earned 0.545, so the weaker estimator took 59 % of the
    # weight. A self-reported confidence that has never been calibrated
    # against measured accuracy will do that every time.
    #
    # This is the weighted-average dilution defect for the fifth time in this
    # project, after DEV-45 (end of life), DEV-72 (advisory), DEV-80
    # (maintenance urgency) and the mission worst-subsystem rule. The lesson
    # has been the same each time: an average lets one bad component hide
    # behind the others.
    #
    # So when the two disagree by more than half the smaller figure, the
    # conservative value is reported rather than the average. That is the rule
    # the PRD already applies when both estimators are uncertain, and its
    # reasoning -- over-stating remaining life reads as permission to fly --
    # applies with more force here, not less.
    lo_est = min(float(data_hours), float(physics.hours))
    hi_est = max(float(data_hours), float(physics.hours))
    if hi_est > 1.5 * max(lo_est, 1e-9):
        return rp.RulEstimate(
            hours=lo_est, lower_hours=0.0, upper_hours=hi_est,
            confidence=physics.confidence, health_now=physics.health_now,
            rate_per_hour=physics.rate_per_hour, source="fused",
            estimator_confidence=max(c_data, c_phys),
            reason=(
                f"estimators disagree ({lo_est:.0f} h vs {hi_est:.0f} h); "
                f"reporting the conservative figure rather than averaging"
            ),
        )

    hours = w_data * float(data_hours) + w_phys * float(physics.hours)
    lo = w_data * float(data_lower if data_lower is not None else data_hours) \
        + w_phys * float(physics.lower_hours)
    hi = w_data * float(data_upper if data_upper is not None else data_hours) \
        + w_phys * float(physics.upper_hours)
    return rp.RulEstimate(
        hours=hours, lower_hours=lo, upper_hours=hi,
        confidence=physics.confidence, health_now=physics.health_now,
        rate_per_hour=physics.rate_per_hour, source="fused",
        estimator_confidence=max(c_data, c_phys),
        reason=f"fused: {w_data:.0%} data-driven, {w_phys:.0%} physics",
    )


def confidence_from_val_loss(val_loss: float) -> float:
    """c_data = 1 / (1 + val_loss), per PRD Part 2 s12.5."""
    return float(1.0 / (1.0 + max(float(val_loss), 0.0)))


__all__ = [
    "RulLstm",
    "conformal_q",
    "RulTrainReport",
    "confidence_from_val_loss",
    "fuse_rul",
    "predict",
    "predict_with_interval",
    "rul_loss",
    "train_rul",
]
