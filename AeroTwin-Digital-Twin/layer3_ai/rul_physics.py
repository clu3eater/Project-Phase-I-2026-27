"""Physics-based remaining useful life -- PRD Part 2 sections 12.2 and 12.4.

The interpretable half of the RUL estimate. A network can learn degradation
patterns a physicist would not think to look for, but it cannot say WHY it
expects the engine to last 300 more hours, and a maintenance engineer who is
being asked to pull an engine early is entitled to an answer.

    RUL = (CHI_now - CHI_threshold) / rate_of_decline

Simple to state, and every term is inspectable: the current health, the
threshold that defines end of life, and how fast health is falling.

WHY A KALMAN FILTER AND NOT A LINE FIT
--------------------------------------
The rate has to be estimated from a health index that is noisy sample to
sample and only trends over hundreds of hours. Fitting a straight line to a
recent window gives a rate that swings wildly -- and RUL is that rate in a
DENOMINATOR, so a rate that wobbles by a factor of two makes RUL wobble by a
factor of two.

A constant-velocity Kalman filter tracks health and its rate of change as
coupled states, which is exactly the [CHI, dCHI/dt] estimator PRD Part 2
section 9.4 Method 2 asks for. It also carries a covariance, and that
covariance is what produces an honest confidence interval instead of an
invented one.

THE INTERVAL IS NOT DECORATION
------------------------------
PRD Part 4 section 7.4a forbids presenting a bare RUL number to an operator.
"340 hours" reads as a measurement; "340 hours [280-410, 95%]" reads as an
engineering estimate, and only the second supports a decision about whether to
fly one more sortie.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

import numpy as np

from layer3_ai import prognostic_metrics

from common import config


def _rul_cfg() -> dict:
    return config.load_thresholds()["rul"]


@dataclass
class RulEstimate:
    """A remaining-life estimate with everything needed to defend it."""

    hours: float | None = None
    lower_hours: float | None = None
    upper_hours: float | None = None
    confidence: float = 0.95
    rate_per_hour: float | None = None
    health_now: float | None = None
    source: str = "physics"
    reason: str = ""
    # Confidence in this estimate itself, for the section 12.5 fusion weights.
    estimator_confidence: float = 0.0

    @property
    def reportable(self) -> bool:
        """A bare number must never reach the operator (PRD Part 4 s7.4a)."""
        return (
            self.hours is not None
            and self.lower_hours is not None
            and self.upper_hours is not None
        )


class HealthKalman:
    """Constant-velocity filter over [health, d(health)/dt].

    Process model, with dt in flight hours:

        x = [h, v]      F = [[1, dt], [0, 1]]      H = [1, 0]

    The process noise on the VELOCITY state is what sets how quickly the filter
    will believe the degradation rate has changed. It is deliberately small: a
    filter that chases every wobble reports a rate that swings by a factor of
    two between sorties, and since the rate sits in the denominator of the RUL
    that makes the remaining-life figure swing with it.
    """

    def __init__(
        self,
        *,
        process_noise_h: float = 1e-8,
        process_noise_v: float = 1e-10,
        measurement_noise: float = 4e-4,
    ) -> None:
        self.x = np.array([1.0, 0.0])
        self.P = np.diag([1e-2, 1e-6])
        self.Q = np.diag([process_noise_h, process_noise_v])
        self.R = float(measurement_noise)
        self.n = 0

    def update(self, health: float, dt_hours: float) -> tuple[float, float, float]:
        """One measurement in; returns (health, rate, rate variance)."""
        dt = max(float(dt_hours), 0.0)
        F = np.array([[1.0, dt], [0.0, 1.0]])
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + self.Q * max(dt, 1e-3)

        H = np.array([1.0, 0.0])
        y = float(health) - float(H @ self.x)
        S = float(H @ self.P @ H.T) + self.R
        K = (self.P @ H) / S
        self.x = self.x + K * y
        self.P = self.P - np.outer(K, H @ self.P)
        self.n += 1
        return float(self.x[0]), float(self.x[1]), float(self.P[1, 1])


class PhysicsRul:
    """Extrapolates the health trend to the maintenance threshold.

    Fed the health index rather than raw degradation factors, because the
    factors are ground truth the aircraft cannot observe. The health estimate
    is what a fielded system actually has.
    """

    def __init__(
        self, *, min_samples: int = 60, engine_key: str = "rotax_915is"
    ) -> None:
        cfg = _rul_cfg()
        self.threshold = float(cfg["maintenance_chi_threshold"])
        self.confidence_level = float(cfg["confidence_level"])
        self.min_samples = min_samples
        self.rul_max = float(
            config.load_engine(engine_key)["ratings"]["tbo_hours"]
        )
        # The slowest decline that could still matter: the whole health margin
        # consumed over one overhaul interval.
        self.min_rate = (1.0 - self.threshold) / self.rul_max
        self.kf = HealthKalman()
        self._last_hours: float | None = None
        self._rate_history: list[float] = []

    def restart(self) -> None:
        """Forget the health trend, after maintenance restores the engine.

        The rate is fitted to the health history. Carried across a repair it
        projects the worn engine's decline onto the restored one, so an engine
        that has just had its injectors cleaned would still be given the life
        of the engine that needed them. Until enough samples arrive afterwards
        the estimate says the trend is being established, which is true.
        """
        self.kf = HealthKalman()
        self._last_hours = None
        self._rate_history.clear()

    def update(self, health: float, flight_hours: float) -> RulEstimate:
        """One health sample in, one remaining-life estimate out."""
        dt = 0.0 if self._last_hours is None else max(0.0, flight_hours - self._last_hours)
        self._last_hours = flight_hours
        h, rate, rate_var = self.kf.update(health, dt)
        self._rate_history.append(rate)
        # Bounded (RT-01): appended every tick and read by nothing, it grew for
        # the whole life of the process.
        if len(self._rate_history) > 720:
            del self._rate_history[:-720]

        est = RulEstimate(
            health_now=h, rate_per_hour=rate, confidence=self.confidence_level
        )

        if self.kf.n < self.min_samples:
            est.reason = "establishing the degradation trend"
            return est

        if h <= self.threshold:
            est.hours = 0.0
            est.lower_hours = 0.0
            est.upper_hours = 0.0
            est.estimator_confidence = 0.9
            est.reason = "health is already at or below the maintenance threshold"
            return est

        margin = h - self.threshold
        decline = -rate  # positive when health is falling

        # An engine that is not measurably degrading has no meaningful RUL.
        # Reporting a huge number would be arithmetic, not an estimate -- and
        # a huge number is exactly what an operator would read as reassurance.
        # Saying "not yet determinable" is the honest answer.
        # 1e-7 per hour is not "degrading slowly", it is noise. Left as the
        # guard, it put a near-zero number in a DENOMINATOR: measured, that
        # produced physics RUL estimates in the tens of thousands of hours and
        # an RMSE of 19,857 h. The floor is set from the engine itself -- a
        # rate slower than "the whole health margin over one TBO" cannot end
        # this engine's life before it is overhauled anyway.
        if decline <= self.min_rate:
            est.reason = "no measurable degradation trend yet"
            est.estimator_confidence = 0.0
            return est

        # Nothing has more remaining life than a full overhaul interval. An
        # uncapped extrapolation reads as reassurance precisely when the trend
        # is too weak to support any claim at all.
        est.hours = float(min(margin / decline, self.rul_max))

        # The interval comes from the uncertainty in the RATE, propagated
        # through RUL = margin / decline. Because the rate is a denominator the
        # interval is asymmetric: the same uncertainty stretches much further
        # upward than downward, which is a real property of the estimate and
        # not something to symmetrise for tidiness.
        z = 1.959963985 if self.confidence_level >= 0.95 else 1.6448536
        sd = math.sqrt(max(rate_var, 0.0))
        fast = decline + z * sd          # degrading faster -> less life
        slow = max(decline - z * sd, self.min_rate)
        est.lower_hours = float(min(margin / fast, self.rul_max))
        est.upper_hours = float(min(margin / slow, self.rul_max))

        # Confidence falls as the rate uncertainty grows relative to the rate.
        rel = sd / max(decline, 1e-12)
        est.estimator_confidence = float(np.clip(1.0 / (1.0 + rel), 0.0, 1.0))
        est.reason = "extrapolated from the observed health trend"
        return est


# ---------------------------------------------------------------------------
# A second interval, to be measured against the first
# ---------------------------------------------------------------------------


def wiener_fht_quantiles(
    margin: float, drift_per_h: float, diffusion_per_h: float, probs: tuple[float, ...]
) -> tuple[float, ...]:
    """Quantiles of the first time a drifting random walk falls through a margin.

    Health modelled as dH = -mu dt + sigma dW, starting `margin` above the
    threshold. The first-passage time of that process is inverse Gaussian with
    mean margin/mu and shape margin^2/sigma^2 (Chhikara and Folks, "The Inverse
    Gaussian Distribution", 1989; applied to remaining life in Si et al.,
    European Journal of Operational Research 213, 2011). scipy's
    invgauss(m, scale=s) has mean m*s and variance m^3*s^2, so the standard
    IG(mean, shape) is invgauss(mean/shape, scale=shape).

    `diffusion_per_h` is sigma^2, in health^2 per hour. With no diffusion the
    passage happens at margin/mu for certain, and every quantile is that time.
    """
    from scipy.stats import invgauss

    mean = margin / drift_per_h
    if diffusion_per_h <= 0.0:
        return tuple(mean for _ in probs)
    shape = margin * margin / diffusion_per_h
    dist = invgauss(mean / shape, scale=shape)
    return tuple(float(dist.ppf(p)) for p in probs)


class WienerRul:
    """Remaining life from a drift-and-diffusion fit to hourly health.

    AN EVALUATION CANDIDATE, NOT SERVED. PhysicsRul's interval propagates the
    uncertainty in the RATE only. It does not carry the fact that health keeps
    wandering after the estimate is made, which is the part that grows with
    the horizon. The first-passage interval carries the rate through its mean
    and the wandering through its shape. Whether that makes it the better
    interval on this engine is a measurement -- scripts/eval_rul_interval.py --
    and it replaces nothing until that measurement says so.

    Increments of noisy samples would read measurement noise as diffusion, so
    health is averaged over `bucket_h` and the variance each mean still carries
    is subtracted from the diffusion estimate. That correction assumes the
    samples inside a bucket are independent; on a smoothed health index they
    are not, which is one more reason the result is measured, not assumed.
    """

    def __init__(self, *, bucket_h: float = 1.0, min_buckets: int = 8,
                 window_buckets: int = 48, engine_key: str = "rotax_915is") -> None:
        cfg = _rul_cfg()
        self.threshold = float(cfg["maintenance_chi_threshold"])
        self.confidence_level = float(cfg["confidence_level"])
        self.rul_max = float(config.load_engine(engine_key)["ratings"]["tbo_hours"])
        self.min_rate = (1.0 - self.threshold) / self.rul_max
        self.bucket_h = float(bucket_h)
        self.min_buckets = int(min_buckets)
        self._means: deque[tuple[float, float, float]] = deque(maxlen=int(window_buckets))
        self._open: list[float] | None = None  # [t0, sum_t, sum_h, sum_h2, n]

    def update(self, health: float, flight_hours: float) -> RulEstimate:
        h, t = float(health), float(flight_hours)
        b = self._open
        if b is not None and t - b[0] >= self.bucket_h:
            n = b[4]
            mean = b[2] / n
            var = max(b[3] / n - mean * mean, 0.0) * n / max(n - 1.0, 1.0)
            self._means.append((b[1] / n, mean, var / n))
            b = None
        if b is None:
            self._open = [t, t, h, h * h, 1.0]
        else:
            b[1] += t
            b[2] += h
            b[3] += h * h
            b[4] += 1.0

        est = RulEstimate(confidence=self.confidence_level, source="wiener")
        if len(self._means) < self.min_buckets:
            est.reason = "establishing the degradation trend"
            return est
        ts = np.array([m[0] for m in self._means])
        hs = np.array([m[1] for m in self._means])
        se2 = np.array([m[2] for m in self._means])
        dt, dh, noise = np.diff(ts), np.diff(hs), se2[:-1] + se2[1:]
        ok = dt > 0.0
        dt, dh, noise = dt[ok], dh[ok], noise[ok]
        h_now = float(hs[-1])
        est.health_now = h_now
        if len(dt) < self.min_buckets - 1:
            est.reason = "establishing the degradation trend"
            return est
        decline = -float(dh.sum() / dt.sum())
        est.rate_per_hour = -decline

        if h_now <= self.threshold:
            est.hours = est.lower_hours = est.upper_hours = 0.0
            est.reason = "health is already at or below the maintenance threshold"
            return est
        if decline <= self.min_rate:
            est.reason = "no measurable degradation trend yet"
            return est

        diffusion = max(float(np.mean(((dh + decline * dt) ** 2 - noise) / dt)), 0.0)
        margin = h_now - self.threshold
        a = 1.0 - self.confidence_level
        lo, hi = wiener_fht_quantiles(margin, decline, diffusion, (a / 2.0, 1.0 - a / 2.0))
        est.hours = float(min(margin / decline, self.rul_max))
        est.lower_hours = float(min(lo, self.rul_max))
        est.upper_hours = float(min(hi, self.rul_max))
        est.reason = "first passage of the fitted health walk"
        return est


# ---------------------------------------------------------------------------
# Targets and scoring
# ---------------------------------------------------------------------------


def piecewise_rul_target(
    rul_raw: np.ndarray, health: np.ndarray | None = None, *,
    rul_max: float, onset: float = 0.90
) -> np.ndarray:
    """The piecewise-linear RUL target of PRD Part 2 section 12.3.

    Before degradation begins, RUL is CAPPED rather than counted down. This is
    not a convenience: nothing in a healthy engine's sensor readings
    distinguishes one with 1,100 hours left from one with 900, so asking a
    network to output the difference is asking it to learn noise. It burns
    capacity, inflates the error on the part of the curve that matters, and
    teaches nothing.

    ``rul_max`` is the PREDICTION HORIZON, not the TBO. PRD s12.3 says to cap
    at RUL_max = TBO (and states 2,000 h "for Rotax 914"; the reference engine
    is the 915 iS at 1,200 h). Capping at TBO does nothing, because the raw
    countdown already tops out there -- the cap never binds, and the network is
    left being asked whether a healthy engine has 900 or 1,100 hours left.
    ``rul.prediction_horizon_hours`` in configuration carries the real cap.
    """
    return np.minimum(np.asarray(rul_raw, dtype=float), float(rul_max))


# The C-MAPSS score's time constants are defined against RUL measured in
# CYCLES over a 0-130 range. This engine's RUL is in HOURS over a 0-400
# horizon, so the constants scale with the range -- otherwise the same relative
# accuracy produces a wildly different score. At tau=10 on an hours scale a
# 100 h error costs exp(100/10) = 22,000 per sample, which says nothing about
# the model and everything about the units. Scaled by 400/130 = 3.08.
_CMAPSS_RANGE_CYCLES = 130.0


def score_time_constants(horizon_hours: float) -> tuple[float, float]:
    """(tau_early, tau_late) scaled from C-MAPSS cycles to this RUL horizon."""
    k = float(horizon_hours) / _CMAPSS_RANGE_CYCLES
    return 13.0 * k, 10.0 * k


def nasa_score(
    pred: np.ndarray, true: np.ndarray, *, tau_early: float = 13.0, tau_late: float = 10.0
) -> float:
    """The NASA C-MAPSS prognostics score. Asymmetric, and the asymmetry is
    the entire point.

    With d = pred - true:

        d < 0  (early -- predicted less life than there is): exp(-d/13) - 1
        d >= 0 (late  -- predicted MORE life than there is): exp(d/10) - 1

    The smaller time constant on the late branch makes over-prediction cost
    more, because over-predicting remaining life is how an engine is flown past
    the point it should have been pulled.

    PRD Part 2 s12.3 states the intent correctly -- "penalizes late predictions
    more than early predictions" -- and then writes a formula that does the
    opposite: it penalises ``RUL_pred < RUL_true``, the conservative case, and
    scores the dangerous over-prediction at ZERO. Training against it would
    have actively taught the model to over-estimate remaining life. See
    docs/PRD_DEVIATIONS.md DEV-66.
    """
    d = np.asarray(pred, dtype=float) - np.asarray(true, dtype=float)
    # exp(700) overflows a float64, and an untrained model is easily 7,000
    # hours out, so the exponent is clipped. The score is already astronomically
    # bad by then -- what is lost is an unrepresentable number, not information.
    early = np.expm1(np.clip(-d / tau_early, -700.0, 700.0))
    late = np.expm1(np.clip(d / tau_late, -700.0, 700.0))
    return float(np.sum(np.where(d < 0, early, late)))


def rul_metrics(
    pred: np.ndarray,
    true: np.ndarray,
    *,
    unit: np.ndarray | None = None,
    t_h: np.ndarray | None = None,
    horizon_hours: float = 400.0,
    mape_floor_hours: float = 25.0,
    alpha: float = prognostic_metrics.DEFAULT_ALPHA,
    lam: float = prognostic_metrics.DEFAULT_LAMBDA,
) -> dict[str, float]:
    """RMSE / MAE / MAPE / R2 / NASA score, plus the late-prediction rate.

    ``late_fraction`` is reported alongside the accuracy numbers because it is
    the one an engineer should read first: a model with an excellent RMSE that
    achieves it by over-predicting half the time is not safe to field.

    ``unit`` (engine id per sample) makes the NASA score a sum over ENGINES,
    which is what C-MAPSS defines and what its "< 500" target is calibrated
    against. Summing over windows instead inflates it by the number of windows
    per engine -- about 140x here -- and the resulting number says nothing.

    ``mape_floor_hours`` excludes targets near zero. MAPE divides by the truth,
    so an engine one hour from the threshold produces an unbounded percentage
    from a one-hour error; averaging those in makes the statistic a report on
    how close to zero the smallest target was.

    ``t_h`` (flight hours per sample) unlocks the metrics the field actually
    judges a prognostic by -- prognostic horizon, alpha-lambda, relative
    accuracy and convergence, per Saxena et al. and ISO 13381-1. They need
    per-engine TRAJECTORIES, so they require both ``unit`` and ``t_h``; without
    them the ``prognostic`` key is absent rather than guessed. See
    ``layer3_ai/prognostic_metrics.py`` for why RMSE alone cannot answer the
    question, and DEV-178 for why these replaced the invented targets.

    ``target_sigma`` is returned so RMSE can be judged RELATIVE to the spread
    of the label. An absolute hour figure is meaningless without it: the same
    RMSE is state of the art on a wide label and useless on a narrow one.
    """
    p = np.asarray(pred, dtype=float)
    t = np.asarray(true, dtype=float)
    err = p - t
    ss_res = float(np.sum(err**2))
    ss_tot = float(np.sum((t - t.mean()) ** 2))
    ok = t > mape_floor_hours
    te, tl = score_time_constants(horizon_hours)

    if unit is None:
        score = nasa_score(p, t, tau_early=te, tau_late=tl)
        n_units = len(p)
    else:
        u = np.asarray(unit)
        # One prediction per engine: the LAST one, which is the estimate the
        # operator would actually have been holding.
        last_p, last_t = [], []
        for uid in np.unique(u):
            m = np.where(u == uid)[0]
            last_p.append(p[m[-1]])
            last_t.append(t[m[-1]])
        score = nasa_score(np.array(last_p), np.array(last_t),
                           tau_early=te, tau_late=tl)
        n_units = len(last_p)

    out: dict = {
        "rmse": float(np.sqrt(np.mean(err**2))),
        "mae": float(np.mean(np.abs(err))),
        "mape": float(np.mean(np.abs(err[ok] / t[ok]))) if ok.any() else float("nan"),
        "r2": float(1.0 - ss_res / ss_tot) if ss_tot > 0 else float("nan"),
        "nasa_score": score,
        "nasa_units": n_units,
        "late_fraction": float(np.mean(err > 0)),
        "target_sigma": float(np.std(t)),
        "n": int(len(p)),
    }

    if unit is not None and t_h is not None:
        trajectories = prognostic_metrics.trajectories_from_frame(
            np.asarray(unit), np.asarray(t_h, dtype=float), p, t
        )
        # Credit is withheld for the flat region where the label is pinned at
        # the horizon cap: predicting a constant correctly is not prognosis,
        # and DEV-102 measured that region at 64.9 % of the test labels.
        out["prognostic"] = prognostic_metrics.evaluate(
            trajectories, alpha=alpha, lam=lam,
            informative_below_h=float(horizon_hours) - 1e-6,
        ).as_dict()

    return out


def monotone_trajectory(
    pred: np.ndarray,
    unit: np.ndarray,
    t_h: np.ndarray,
    *,
    increasing: bool = False,
) -> np.ndarray:
    """Force each engine's RUL estimate to count DOWN, never up.

    Remaining life cannot grow. An estimator that says 300 h at one sortie and
    340 h at the next has contradicted itself, and an operator watching the
    figure climb learns to disbelieve it -- the same argument DEV-118 makes for
    the display deadband, one layer earlier.

    Isotonic regression by pool-adjacent-violators: the closest non-increasing
    sequence to the one given, in least squares. O(n), no parameter to choose,
    and it can only reduce squared error against a target that is itself
    monotone, which the RUL label is by construction.

    Applied PER ENGINE and ordered by flight hours. Pooling engines would
    enforce an ordering between airframes that has no meaning.

    Measured on the oracle ceiling model: rmse/sigma 0.765 -> 0.710, at no
    cost. It is NOT applied automatically inside `rul_metrics` -- a caller
    scoring a single window has no trajectory to be monotone over, and
    silently reshaping predictions inside a scoring function would make the
    metric depend on how the data happened to be batched.
    """
    from sklearn.isotonic import IsotonicRegression

    pred = np.asarray(pred, dtype=float)
    unit = np.asarray(unit)
    t_h = np.asarray(t_h, dtype=float)
    if not (len(pred) == len(unit) == len(t_h)):
        raise ValueError(
            f"length mismatch: pred {len(pred)}, unit {len(unit)}, t_h {len(t_h)}"
        )

    out = pred.copy()
    for uid in np.unique(unit):
        rows = np.flatnonzero(unit == uid)
        if len(rows) < 2:
            continue
        ordered = rows[np.argsort(t_h[rows])]
        # Ties in time carry no ordering information; isotonic handles them by
        # averaging, which is the right answer for two readings of one moment.
        out[ordered] = IsotonicRegression(increasing=increasing).fit_transform(
            t_h[ordered], pred[ordered]
        )
    return out


__all__ = [
    "HealthKalman",
    "score_time_constants",
    "PhysicsRul",
    "RulEstimate",
    "monotone_trajectory",
    "nasa_score",
    "piecewise_rul_target",
    "rul_metrics",
]
