"""The prognostics metrics the field actually judges a prognostic by.

WHY THIS EXISTS
---------------
RUL was scored here on RMSE, R^2, MAPE and the C-MAPSS score. Those are
regression metrics with one prognostics metric bolted on, and they answer the
wrong question. A prognostic is not a regressor that happens to output hours:
it is a device that has to become trustworthy BEFORE the thing it is watching
dies, and stay trustworthy from then on. RMSE averaged over an engine's whole
life cannot see that, because it averages the part that matters into the part
that does not.

Concretely, DEV-102 measured that **64.9 % of test labels are censored or
sitting exactly at the 400 h horizon cap**. Over that region the target is a
constant, every model scores well on it, and a metric dominated by it reports
mostly how much of the test set is flat. That is why RMSE ~102 h and R^2 0.22
can coexist: the error is concentrated in the 35 % of labels anybody cares
about, and the average hides it.

WHAT THE FIELD USES INSTEAD
---------------------------
Saxena et al. (NASA, "Metrics for Evaluating Performance of Prognostic
Techniques", PHM 2008) define four prognostics-specific metrics, applied as a
waterfall -- each is only meaningful if the previous one passes. They are
implemented in NASA's own public Prognostics Metrics Library and are the
metrics ISO 13381-1's process is written around:

    Prognostic Horizon   how far before end of life the prediction first
                         enters the accuracy cone AND STAYS THERE
    alpha-lambda         at a chosen fraction of the way to end of life, is
                         the prediction inside +/- alpha of the truth
    Relative Accuracy    error as a FRACTION of the life actually remaining
    Convergence          does the estimate tighten as death approaches, or
                         drift

The unifying idea is that error must be judged RELATIVE TO REMAINING LIFE. An
error of 40 h on an engine with 400 h left is a good prediction. The same 40 h
on an engine with 50 h left is a missed failure. RMSE scores them identically;
every metric here does not.

WHY alpha = 0.2
---------------
Saxena's convention, and the value the C-MAPSS literature reports against.
It is not derived from this engine, which is the point -- a target chosen from
our own data is a target we have already met by construction (the DEV-95
mistake). Where a value IS specific to this engine it is passed in, not baked
in.

WHAT THIS MODULE DOES NOT DO
----------------------------
It does not train, tune or select anything. It scores trajectories that
already exist. Nothing in here may be used as a loss, because a metric used as
a loss stops being a measurement.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

_log = logging.getLogger(__name__)

# Saxena's conventional accuracy cone: +/- 20 % of true remaining life.
DEFAULT_ALPHA = 0.2

# Where on the way to end of life alpha-lambda is evaluated. 0.5 is the
# halfway point and the value most commonly reported.
DEFAULT_LAMBDA = 0.5

# Absolute floor on the half-width of the accuracy cone, in flight hours.
#
# A cone of +/- alpha * RUL collapses to ZERO width as RUL -> 0, so no
# estimator carrying any noise at all can satisfy it at the last sample, and
# the prognostic horizon is then identically zero for every algorithm ever
# written. Measured here before the floor existed: a very good estimator
# (RMSE 0.165 sigma, alpha-lambda 1.00) scored a horizon of 0.0 h, which is
# a statement about the metric and not about the estimator.
#
# The floor is NOT tuned. It is the tightest maintenance band this system
# itself issues -- "Schedule maintenance within 10 flight hours" in
# configs/thresholds.yaml. Below that granularity the decision no longer
# changes: the engine is being pulled either way, so demanding the estimate
# resolve hours it cannot act on measures nothing.
DEFAULT_MIN_BOUND_H = 10.0


@dataclass
class EngineTrajectory:
    """One engine's predictions, ordered in time, up to its end of life."""

    engine_id: object
    t_h: np.ndarray          # flight hours at each prediction
    pred_rul_h: np.ndarray   # predicted remaining life
    true_rul_h: np.ndarray   # actual remaining life

    def __post_init__(self) -> None:
        order = np.argsort(self.t_h)
        self.t_h = np.asarray(self.t_h, dtype=float)[order]
        self.pred_rul_h = np.asarray(self.pred_rul_h, dtype=float)[order]
        self.true_rul_h = np.asarray(self.true_rul_h, dtype=float)[order]

    @property
    def eol_h(self) -> float:
        """End of life: the last time we have a reading for."""
        return float(self.t_h[-1])


@dataclass
class PrognosticReport:
    """What the fleet's trajectories say, per Saxena's waterfall."""

    engines: int = 0
    scored_engines: int = 0
    alpha: float = DEFAULT_ALPHA
    lam: float = DEFAULT_LAMBDA
    min_bound_h: float = DEFAULT_MIN_BOUND_H

    prognostic_horizon_h: float = 0.0      # median across engines
    prognostic_horizon_frac: float = 0.0   # as a fraction of each engine's life
    alpha_lambda: float = 0.0              # fraction of engines inside the cone
    relative_accuracy: float = 0.0         # mean over engines
    convergence: float = 0.0               # mean; lower is better
    late_fraction: float = 0.0             # predicted MORE life than there was

    skipped: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "engines": self.engines,
            "scored_engines": self.scored_engines,
            "alpha": self.alpha,
            "lambda": self.lam,
            "min_bound_h": self.min_bound_h,
            "prognostic_horizon_h": round(self.prognostic_horizon_h, 1),
            "prognostic_horizon_frac": round(self.prognostic_horizon_frac, 3),
            "alpha_lambda": round(self.alpha_lambda, 3),
            "relative_accuracy": round(self.relative_accuracy, 3),
            "convergence": round(self.convergence, 2),
            "late_fraction": round(self.late_fraction, 3),
            "skipped": self.skipped,
        }


def alpha_bounds(
    true_rul_h: np.ndarray,
    alpha: float = DEFAULT_ALPHA,
    *,
    min_bound_h: float = DEFAULT_MIN_BOUND_H,
) -> tuple[np.ndarray, np.ndarray]:
    """The accuracy cone: +/- alpha of the life ACTUALLY remaining.

    The cone narrows as the engine dies, which is the whole point -- it demands
    more of the estimate exactly where a wrong answer costs an airframe.

    It stops narrowing at ``min_bound_h``, because a cone that reaches zero
    width is unsatisfiable by construction rather than demanding. See
    ``DEFAULT_MIN_BOUND_H`` for why that floor is the system's own decision
    granularity and not a tuned constant.
    """
    true_rul_h = np.asarray(true_rul_h, dtype=float)
    margin = np.maximum(alpha * np.abs(true_rul_h), float(min_bound_h))
    return true_rul_h - margin, true_rul_h + margin


def _inside(
    traj: EngineTrajectory, alpha: float, min_bound_h: float = DEFAULT_MIN_BOUND_H
) -> np.ndarray:
    lo, hi = alpha_bounds(traj.true_rul_h, alpha, min_bound_h=min_bound_h)
    return (traj.pred_rul_h >= lo) & (traj.pred_rul_h <= hi)


def prognostic_horizon_h(
    traj: EngineTrajectory,
    alpha: float = DEFAULT_ALPHA,
    *,
    informative_below_h: float | None = None,
    min_bound_h: float = DEFAULT_MIN_BOUND_H,
) -> float:
    """Hours before end of life at which the estimate becomes, and STAYS, good.

    "And stays" is the load-bearing half. A prediction that wanders into the
    cone, back out, and in again has not earned a horizon -- an operator cannot
    act on an estimate that is right intermittently. So this is the first index
    from which EVERY later index is inside the cone.

    Returns 0.0 when the estimate never settles: not an error, a result.

    `informative_below_h` excludes the flat region where RUL is pinned at the
    prediction-horizon cap. Predicting a constant correctly is not prognosis,
    and counting it inflates the horizon without adding any capability.
    """
    inside = _inside(traj, alpha, min_bound_h)
    if informative_below_h is not None:
        # Outside the informative region the test is vacuous rather than
        # passed; treat it as not-yet-settled so the horizon starts where the
        # countdown does.
        inside = inside & (traj.true_rul_h <= informative_below_h)
    if not inside.any():
        return 0.0

    # Walk back from the end: the horizon starts at the earliest index whose
    # entire suffix is inside the cone.
    settled_from = len(inside)
    for i in range(len(inside) - 1, -1, -1):
        if not inside[i]:
            break
        settled_from = i
    if settled_from >= len(inside):
        return 0.0
    return float(traj.eol_h - traj.t_h[settled_from])


def alpha_lambda_accuracy(
    traj: EngineTrajectory,
    alpha: float = DEFAULT_ALPHA,
    lam: float = DEFAULT_LAMBDA,
    *,
    min_bound_h: float = DEFAULT_MIN_BOUND_H,
) -> bool | None:
    """Is the estimate inside the cone at a fraction `lam` of the way to death?

    Binary by design. Saxena's waterfall asks a yes/no question at a fixed
    point so that two algorithms can be compared without arguing about which
    part of the curve to average over. Returns None when the trajectory has no
    sample near that point, so a missing answer is never scored as a pass.
    """
    if len(traj.t_h) < 2:
        return None
    t_start, t_eol = float(traj.t_h[0]), traj.eol_h
    if t_eol <= t_start:
        return None
    t_lambda = t_start + lam * (t_eol - t_start)
    i = int(np.argmin(np.abs(traj.t_h - t_lambda)))
    return bool(_inside(traj, alpha, min_bound_h)[i])


def relative_accuracy(
    traj: EngineTrajectory, lam: float = DEFAULT_LAMBDA
) -> float | None:
    """1 - |error| / true RUL at the lambda point. 1.0 is perfect.

    Reported alongside alpha-lambda because the binary metric cannot separate
    "just outside the cone" from "wrong by a factor of three", and those are
    different failures. Clipped at 0 rather than allowed to go negative: an
    estimate wrong by more than the life remaining is simply zero use, and
    letting one such engine drive a fleet mean to -40 tells nobody anything.
    """
    if len(traj.t_h) < 2:
        return None
    t_start, t_eol = float(traj.t_h[0]), traj.eol_h
    if t_eol <= t_start:
        return None
    t_lambda = t_start + lam * (t_eol - t_start)
    i = int(np.argmin(np.abs(traj.t_h - t_lambda)))
    true = float(traj.true_rul_h[i])
    if abs(true) < 1e-9:
        return None
    ra = 1.0 - abs(true - float(traj.pred_rul_h[i])) / abs(true)
    return float(max(ra, 0.0))


def convergence(traj: EngineTrajectory) -> float | None:
    """How quickly the error shrinks as end of life approaches. Lower is better.

    Saxena's definition: the distance from the start of the prediction window
    to the CENTROID of the area under the error curve. An estimator whose error
    collapses early has its mass near the start and a small distance; one that
    only gets good at the last moment, or never, has a large one.

    This is the metric that catches an estimator which is accurate ON AVERAGE
    while being useless when it matters -- the exact failure RMSE hides.
    """
    t = traj.t_h
    err = np.abs(traj.pred_rul_h - traj.true_rul_h)
    if len(t) < 2:
        return None
    dt = np.diff(t)
    m = err[:-1]
    area = float(np.sum(dt * m))
    if area <= 1e-12:
        return 0.0
    x_c = 0.5 * float(np.sum((t[1:] ** 2 - t[:-1] ** 2) * m)) / area
    y_c = 0.5 * float(np.sum(dt * m * m)) / area
    return float(np.hypot(x_c - float(t[0]), y_c))


def evaluate(
    trajectories: list[EngineTrajectory],
    *,
    alpha: float = DEFAULT_ALPHA,
    lam: float = DEFAULT_LAMBDA,
    informative_below_h: float | None = None,
    min_bound_h: float = DEFAULT_MIN_BOUND_H,
) -> PrognosticReport:
    """Score a fleet. Engines that cannot be scored are named, never assumed.

    A trajectory too short to have a lambda point is skipped and reported,
    because silently dropping it would flatter whichever metric it would have
    hurt -- the same discipline DEV-164 applies to a trend it cannot make
    honestly.
    """
    report = PrognosticReport(
        engines=len(trajectories), alpha=alpha, lam=lam, min_bound_h=min_bound_h
    )
    horizons_h: list[float] = []
    horizons_frac: list[float] = []
    passes: list[bool] = []
    ras: list[float] = []
    convs: list[float] = []
    late = 0
    total = 0

    for traj in trajectories:
        hit = alpha_lambda_accuracy(traj, alpha, lam, min_bound_h=min_bound_h)
        if hit is None:
            report.skipped.append(f"{traj.engine_id}: too few samples to score")
            continue
        report.scored_engines += 1
        passes.append(hit)

        ph = prognostic_horizon_h(
            traj, alpha, informative_below_h=informative_below_h,
            min_bound_h=min_bound_h,
        )
        horizons_h.append(ph)
        life = traj.eol_h - float(traj.t_h[0])
        horizons_frac.append(ph / life if life > 0 else 0.0)

        ra = relative_accuracy(traj, lam)
        if ra is not None:
            ras.append(ra)
        cv = convergence(traj)
        if cv is not None:
            convs.append(cv)

        late += int(np.sum(traj.pred_rul_h > traj.true_rul_h))
        total += len(traj.t_h)

    if report.scored_engines == 0:
        _log.warning("no trajectory could be scored; %d skipped", len(report.skipped))
        return report

    # Median rather than mean for the horizon: it is bounded below at zero and
    # a handful of engines the estimator never settles on would otherwise drag
    # a mean toward a number no individual engine exhibits.
    report.prognostic_horizon_h = float(np.median(horizons_h))
    report.prognostic_horizon_frac = float(np.median(horizons_frac))
    report.alpha_lambda = float(np.mean(passes))
    report.relative_accuracy = float(np.mean(ras)) if ras else 0.0
    report.convergence = float(np.mean(convs)) if convs else 0.0
    report.late_fraction = float(late / total) if total else 0.0
    return report


def trajectories_from_frame(
    engine_ids: np.ndarray,
    t_h: np.ndarray,
    pred_rul_h: np.ndarray,
    true_rul_h: np.ndarray,
) -> list[EngineTrajectory]:
    """Group flat prediction arrays into per-engine trajectories.

    Prognostics metrics are trajectory metrics: they ask how one engine's
    estimate behaves over ITS life. Pooling every engine's samples into one
    array -- which is what an RMSE over the test set does -- discards the
    ordering the question depends on.
    """
    engine_ids = np.asarray(engine_ids)
    out: list[EngineTrajectory] = []
    for eid in dict.fromkeys(engine_ids.tolist()):
        m = engine_ids == eid
        out.append(
            EngineTrajectory(
                engine_id=eid,
                t_h=np.asarray(t_h)[m],
                pred_rul_h=np.asarray(pred_rul_h)[m],
                true_rul_h=np.asarray(true_rul_h)[m],
            )
        )
    return out
