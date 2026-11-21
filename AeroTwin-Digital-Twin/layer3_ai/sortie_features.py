"""Per-sortie features: the degradation view the 30-second window cannot hold.

WHY THIS EXISTS
---------------
The RUL estimator read a 30-sample window -- about 30 seconds, or 0.0013 % of
an engine's life (DEV-183). RUL is the RATE of degradation, and a window that
short observes a STATE. DEV-182 measured the consequence from the other side:
the same architecture scores 1.09-1.36x published state of the art on C-MAPSS,
where it is handed whole cycles, and alpha-lambda 0.20 here.

The dataset already contains the longer view -- 17 to 115 sorties per engine
spanning hundreds of flight hours -- and the estimator was throwing all but one
50-second slice of it away.

WHAT ACTUALLY HELPED, AND WHAT DID NOT
--------------------------------------
Measured, not assumed. Aggregating each sortie to one row and adding a
rate-of-change term improves on the shipped window: rmse/sigma 0.874 -> 0.775.
But a SEQUENCE of those rows makes it monotonically worse -- 1/2/3/6/8/12/16
sorties give 0.781 / 0.801 / 0.802 / 0.834 / 0.860 / 0.951 / 1.005, with R^2
falling from 0.390 to -0.009.

So the gain is DENOISING plus the explicit rate, not the long memory that was
predicted. `DEFAULT_SORTIES = 1` records that, and the sweep above is why it
must not be "improved" back to 12. Whether longer history is genuinely
uninformative or 35 training engines simply cannot support it is NOT settled by
that experiment and is not claimed here.

WHY A RATE TERM AT ALL, IF HISTORY DOES NOT HELP
-------------------------------------------------
A rate is one difference, not a memory. Degradation between two sorties divided
by the flight hours between them is a single number that says which direction
the engine is moving; carrying twelve past sorties so a network can infer the
same thing is a far more expensive way to buy it, and the measurements above
say it does not pay.

WHAT IS DELIBERATELY EXCLUDED
-----------------------------
Nothing forbidden by `features.FORBIDDEN_PREFIXES` -- no `deg_*`, no `lab_*`,
no `chi_true`. `flight_hours` IS included, and that decision is argued at
`AGE_COLUMNS` below rather than made silently, because it is the one feature
here that could reintroduce the DEV-45 circularity.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from layer3_ai import features as feat

_log = logging.getLogger(__name__)

# Sorties per model input. 1 -- see the sweep in the module docstring.
DEFAULT_SORTIES = 1

# Engine age, in hours and in sorties flown.
#
# THE CIRCULARITY QUESTION. DEV-45 found a dataset where every failure came from
# baseline wear near TBO, so a model could score well by learning
# "RUL = TBO - hours" while ignoring the faults entirely. Feeding the clock back
# in risks exactly that, so it is not a free feature.
#
# It is included because on THIS fleet the shortcut does not exist: engines fail
# between 167 h and 1212 h (median 624), 27 of 100 censor at TBO without failing
# at all, and the dominant driver of when an engine dies is an injected fault
# schedule that the clock knows nothing about. Age is genuinely informative --
# an old engine is nearer death -- without being sufficient.
#
# `scripts/train_rul.py` reports an age-only baseline beside the full model so
# the shortcut, if it ever appears, is visible rather than inferred.
#
# `sortie` is NOT here, though it carries much the same information. It is on
# `features.FORBIDDEN_EXACT`, and the first version of this module included it
# anyway -- caught within minutes by `rul_survival._check_no_leakage`, which is
# the argument for having the guard rather than the convention alone.
# `flight_hours` already carries engine age; a sortie counter adds an index a
# model could memorise an engine by.
AGE_COLUMNS = ("flight_hours",)

# Health as the fielded system estimates it, from sensors alone. Optional: it
# is expensive to compute and the caller supplies it if it has it.
#
# `train_rul.py` computed this per row and then built sequences from a feature
# set that does not contain it -- the best operating-point-normalised
# degradation summary in the system, calculated and dropped one line before use.
HEALTH_COLUMN = "health_est"


def _rate_columns(cols: list[str]) -> list[str]:
    return [f"rate_{c}" for c in cols]


def _sd_columns(cols: list[str]) -> list[str]:
    return [f"sd_{c}" for c in cols]


def feature_columns(
    base: list[str] | tuple[str, ...], *, health: bool = False
) -> list[str]:
    """The full column list this module produces, in a fixed order.

    Order is fixed and derived from `base` so that a model trained on one call
    and scored on another cannot silently receive its inputs transposed.
    """
    base = list(base)
    cols = base + _sd_columns(base) + _rate_columns(base) + list(AGE_COLUMNS)
    if health:
        cols += [HEALTH_COLUMN, f"rate_{HEALTH_COLUMN}"]
    return cols


def sortie_table(
    df: pd.DataFrame,
    feature_set=None,
    *,
    health: np.ndarray | None = None,
) -> pd.DataFrame:
    """One row per (engine, sortie): level, spread, and rate of change.

    Three views of each channel, and the third is the one the 30-second window
    could not provide at any sampling rate:

      level  the sortie mean -- where the engine is
      spread the within-sortie standard deviation -- a degrading engine gets
             noisier as well as hotter, and the mean alone discards that
      rate   the change in the level since the PREVIOUS sortie of the same
             engine, per flight hour -- which direction it is moving

    `health` is the per-row health estimate, if the caller has computed one.

    Rows are returned sorted by (engine_id, sortie) and the frame carries every
    label column the caller will need (`rul_hours`, `censored`, `chi_true`) so
    that a downstream split cannot lose the correspondence between a feature
    row and its label.
    """
    fs = feature_set if feature_set is not None else feat.extended()
    base = [c for c in fs.columns if c in df.columns]
    missing = [c for c in fs.columns if c not in df.columns]
    if missing:
        _log.warning("sortie_table: %d feature columns absent from the frame: %s",
                     len(missing), missing[:5])
    if not base:
        raise ValueError("no feature columns present in the frame")

    work = df
    if health is not None:
        if len(health) != len(df):
            raise ValueError(
                f"health has {len(health)} rows, frame has {len(df)}"
            )
        work = df.copy()
        work[HEALTH_COLUMN] = np.asarray(health, dtype=float)
        base = base + [HEALTH_COLUMN]

    keys = ["engine_id", "sortie"]
    agg = {c: "mean" for c in base}
    agg["flight_hours"] = "max"
    for label in ("rul_hours", "censored", "chi_true"):
        if label in work.columns:
            agg[label] = "last"

    g = (work.groupby(keys, as_index=False).agg(agg)
              .sort_values(keys).reset_index(drop=True))

    sd = (work.groupby(keys, as_index=False)[base].std()
              .sort_values(keys).reset_index(drop=True))
    for c in base:
        # A single-sample sortie has undefined spread; 0.0 is the honest value
        # for "no variation observed", not a missing one.
        g[f"sd_{c}"] = sd[c].fillna(0.0).to_numpy()

    by = g.groupby("engine_id")
    # Guard the denominator: two sorties recorded at the same flight hour give
    # an infinite rate, which would poison the whole column after scaling.
    dt = by["flight_hours"].diff()
    dt = dt.where(dt > 1e-6)
    for c in base:
        g[f"rate_{c}"] = (by[c].diff() / dt).fillna(0.0).to_numpy()

    return g


def build_sequences(
    g: pd.DataFrame,
    columns: list[str],
    *,
    n_sorties: int = DEFAULT_SORTIES,
    drop_censored: bool = True,
):
    """Sequences of consecutive sorties. Engines are never crossed.

    Returns ``(x, y, unit, t_h)`` where x is
    ``(n, n_sorties, len(columns))``, y is the RUL label at the LAST sortie of
    each window, and unit/t_h identify the engine and flight hour of that same
    sortie -- which is what the trajectory metrics need to reconstruct a
    per-engine sequence.

    A censored engine's RUL is a LOWER BOUND, not a label. Scoring against one
    measures how near the model came to a number that was never the answer, so
    those windows are dropped by default -- the same choice `diagnose_rul.py`
    makes.
    """
    if n_sorties < 1:
        raise ValueError(f"n_sorties must be >= 1, got {n_sorties}")
    missing = [c for c in columns if c not in g.columns]
    if missing:
        raise ValueError(f"columns absent from the sortie table: {missing}")

    xs, ys, us, ts = [], [], [], []
    for eid, e in g.groupby("engine_id", sort=True):
        e = e.sort_values("sortie")
        x = e[columns].to_numpy(dtype=np.float32)
        y = e["rul_hours"].to_numpy(dtype=np.float32)
        h = e["flight_hours"].to_numpy(dtype=float)
        cen = (e["censored"].to_numpy() if "censored" in e.columns
               else np.zeros(len(e)))
        for i in range(n_sorties, len(e) + 1):
            if drop_censored and cen[i - 1] >= 0.5:
                continue
            xs.append(x[i - n_sorties:i])
            ys.append(y[i - 1])
            us.append(eid)
            ts.append(h[i - 1])

    if not xs:
        return (np.empty((0, n_sorties, len(columns)), dtype=np.float32),
                np.empty(0, dtype=np.float32), np.empty(0), np.empty(0))
    return (np.asarray(xs, dtype=np.float32), np.asarray(ys, dtype=np.float32),
            np.asarray(us), np.asarray(ts, dtype=float))


def fit_scaler(g: pd.DataFrame, columns: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """Mean and spread from the TRAINING frame only.

    Returned rather than applied, so that the caller cannot accidentally fit on
    validation or test -- the asymmetry has to be visible at the call site.
    """
    mu = g[columns].mean().to_numpy(dtype=np.float32)
    sd = g[columns].std().replace(0.0, 1.0).to_numpy(dtype=np.float32)
    sd[~np.isfinite(sd)] = 1.0
    sd[sd == 0.0] = 1.0
    return mu, sd


def apply_scaler(
    g: pd.DataFrame, columns: list[str], mu: np.ndarray, sd: np.ndarray
) -> pd.DataFrame:
    out = g.copy()
    out[columns] = (out[columns] - mu) / sd
    return out


class SortieAccumulator:
    """Build the sortie feature vector LIVE, one reading at a time.

    `sortie_table` computes these features from a finished fleet, in pandas,
    one row per completed sortie. Serving needs the same numbers from a stream
    that has not finished yet, and the two must agree exactly: the model is fed
    a plain vector, so a serving-side definition that differs even slightly
    produces a confident number that means something else. That is the same
    failure the injector-duty units bug was, and it was invisible for the same
    reason -- the output looks entirely reasonable.

    Two details are easy to get wrong and are pinned by
    `test_sortie_accumulator_matches_the_training_table`:

      spread  pandas `.std()` is the SAMPLE standard deviation, ddof=1. numpy
              defaults to ddof=0. Using numpy's default here would make every
              sd_ feature slightly too small, by a factor that grows as the
              sortie gets shorter.
      rate    change in LEVEL since the previous sortie, divided by the change
              in flight hours. First sortie of an engine has no previous, so
              0.0 -- not missing, because the model has no missing-value path.

    **Serving mid-sortie is not the same as scoring a finished one.** The level
    and spread are computed over the samples seen SO FAR, so early in a sortie
    they are noisy and the estimate firms up as it proceeds. That is a real
    difference from training and is reported in `samples`, so a caller can
    decline to act on a vector built from three readings.
    """

    def __init__(self, base_columns: list[str] | tuple[str, ...], *,
                 health: bool = True) -> None:
        self.base = list(base_columns)
        if health and HEALTH_COLUMN not in self.base:
            self.base = self.base + [HEALTH_COLUMN]
        self.columns = feature_columns(
            [c for c in self.base if c != HEALTH_COLUMN],
            health=HEALTH_COLUMN in self.base,
        )
        # Running statistics, not stored rows (RT-01). Rows accumulated for the
        # whole sortie and features() rebuilt an array from all of them on
        # every tick -- measured 26 ms per tick at 1.4 flight hours and 421 ms
        # at 24 h, against a 500 ms tick, with memory growing all flight.
        # Welford's update gives the same mean and sample standard deviation
        # in constant time and memory, without the cancellation a naive
        # sum-of-squares suffers on a high-mean, low-spread channel.
        self._n = 0
        self._mean = np.zeros(len(self.base))
        self._ss = np.zeros(len(self.base))
        self._hours_max: float | None = None
        self._prev_level: dict[str, float] | None = None
        self._prev_hours: float | None = None

    @property
    def samples(self) -> int:
        return self._n

    def observe(self, values: dict[str, float | None],
                flight_hours: float) -> None:
        """Take one reading. A row with any base column missing is skipped.

        Skipped rather than imputed: the level is a mean, and substituting a
        zero for an absent oil pressure moves it toward a value the engine
        never produced.
        """
        row = []
        for c in self.base:
            v = values.get(c)
            if v is None:
                return
            row.append(float(v))
        x = np.asarray(row, dtype=float)
        self._n += 1
        d = x - self._mean
        self._mean += d / self._n
        self._ss += d * (x - self._mean)
        h = float(flight_hours)
        self._hours_max = h if self._hours_max is None else max(self._hours_max, h)

    def discard(self) -> None:
        """Drop the readings taken so far WITHOUT closing the sortie.

        For a change of operating point: the levels gathered at the last one
        are not this sortie's levels at the new one, and they must not become
        the rate baseline either -- a "rate" between the climb and the cruise
        of one flight is a change of throttle divided by minutes.
        """
        self._n = 0
        self._mean = np.zeros(len(self.base))
        self._ss = np.zeros(len(self.base))
        self._hours_max = None

    def end_sortie(self) -> None:
        """Close the current sortie; its levels become the rate baseline."""
        if self._n:
            self._prev_level = dict(zip(self.base, self._mean.copy()))
            self._prev_hours = self._hours_max
        self._n = 0
        self._mean = np.zeros(len(self.base))
        self._ss = np.zeros(len(self.base))
        self._hours_max = None

    def features(self) -> dict[str, float] | None:
        """The full vector for the sortie so far, or None if nothing is in it."""
        if not self._n:
            return None
        level = self._mean.copy()
        # ddof=1 to match pandas. A one-sample sortie has undefined spread and
        # 0.0 is the honest value for "no variation observed" -- the same
        # substitution sortie_table makes with .fillna(0.0).
        sd = (np.sqrt(np.maximum(self._ss, 0.0) / (self._n - 1)) if self._n > 1
              else np.zeros(len(self.base)))
        sd = np.nan_to_num(sd, nan=0.0)
        hours = float(self._hours_max)

        out: dict[str, float] = {}
        for i, c in enumerate(self.base):
            out[c] = float(level[i])
            out[f"sd_{c}"] = float(sd[i])
        for i, c in enumerate(self.base):
            if self._prev_level is None or self._prev_hours is None:
                out[f"rate_{c}"] = 0.0
                continue
            dt = hours - self._prev_hours
            out[f"rate_{c}"] = (0.0 if dt <= 1e-6
                                else float((level[i] - self._prev_level[c])
                                           / dt))
        out["flight_hours"] = hours
        return out


__all__ = [
    "AGE_COLUMNS",
    "DEFAULT_SORTIES",
    "HEALTH_COLUMN",
    "apply_scaler",
    "build_sequences",
    "feature_columns",
    "fit_scaler",
    "sortie_table",
    "SortieAccumulator",
]
