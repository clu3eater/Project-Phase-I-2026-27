"""NASA C-MAPSS turbofan benchmark -- the outside yardstick.

WHY A JET ENGINE DATASET IS IN A PISTON ENGINE PROJECT
------------------------------------------------------
It is NOT compatible with the reference engine and is never mixed with it.
C-MAPSS is a Commercial Modular Aero-Propulsion System Simulation: a
high-bypass TURBOFAN, whose fault modes are HPC degradation and fan
degradation, measured through 21 gas-path channels -- fan speed, core speed,
bypass ratio, burner fuel-air ratio, bleed enthalpy, and pressures and
temperatures at numbered turbine stations. The Rotax 915 iS is a four-cylinder
piston engine whose faults are misfire, injector abnormality, cooling
degradation, lubrication, sensor drift, combustion instability, overheating
and bearing wear, measured through CHT, EGT, oil pressure and temperature,
fuel flow, vibration and injection timing.

The two share **no sensor and no failure mechanism**. A model trained here
cannot be applied there, and this module deliberately provides no path to try:
there is no merge, no shared feature space and no pre-training entry point.
DEV-181 records why that temptation is refused rather than merely unimplemented.

WHAT IT IS FOR
--------------
Benchmarking the METHOD, not the engine. Published RUL results are reported on
C-MAPSS and essentially nowhere else, so it is the only surface on which the
question "is our estimator competitive with what other groups achieve" has an
answer at all. Our own simulator cannot answer it: a score on a fixture we
wrote says how hard we made the fixture.

So the claim this dataset supports is precise and narrow:

    our ALGORITHM, run on the same data everyone else reports on, scores X
    against a published state of the art of 12.6-15 RMSE

and the claim it does NOT support is:

    our engine model, our health index, or our RUL on the 915 iS is validated
    by real data

The second needs piston-engine run-to-failure data, which this is not.

FORMAT
------
Four sub-datasets of increasing difficulty. Space-separated, 26 columns:

    unit, cycle, op_setting_1..3, sensor_1..21

Training units run to failure; the last cycle IS end of life. Test units stop
part way, and the true remaining cycles are in the matching ``RUL_FDxxx.txt``,
one line per unit in order.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_log = logging.getLogger(__name__)

SUBSETS = ("FD001", "FD002", "FD003", "FD004")

# Column layout, fixed by the dataset. Named rather than indexed because a
# bare column number in analysis code is unreviewable.
OP_COLUMNS = tuple(f"op_setting_{i}" for i in range(1, 4))
SENSOR_COLUMNS = tuple(f"sensor_{i}" for i in range(1, 22))
COLUMNS = ("unit", "cycle") + OP_COLUMNS + SENSOR_COLUMNS

# (train units, test units) per subset. Asserted on load, because a truncated
# or half-extracted download reads as a smaller fleet rather than as an error
# -- and would then quietly produce a benchmark number that is not the
# benchmark.
#
# These are MEASURED from the archive, not copied from its readme, because for
# FD004 the two disagree: the readme says 248 train / 249 test and the data
# holds 249 train / 248 test. The data is right and the readme has them
# transposed -- RUL_FD004.txt carries exactly 248 labels, one per test unit,
# which it could not do if there were 249. The published C-MAPSS tables agree
# with the data. Recorded rather than silently matched, because "assert what
# the documentation claims" and "assert what the file contains" are different
# tests and only the second one catches a bad download.
EXPECTED_UNITS = {
    "FD001": (100, 100),
    "FD002": (260, 259),
    "FD003": (100, 100),
    "FD004": (249, 248),
}

# The piecewise cap conventional in the C-MAPSS literature. Published RMSE
# figures are reported against it, so comparing without it compares nothing.
RUL_CAP_CYCLES = 125.0


@dataclass
class CmapssSplit:
    """One sub-dataset, train and test, with the test labels attached."""

    name: str
    train_unit: np.ndarray
    train_cycle: np.ndarray
    train_x: np.ndarray          # (n, 24) op settings + sensors
    test_unit: np.ndarray
    test_cycle: np.ndarray
    test_x: np.ndarray
    test_rul: np.ndarray         # true remaining cycles, one per test unit

    @property
    def n_train_units(self) -> int:
        return len(np.unique(self.train_unit))

    @property
    def n_test_units(self) -> int:
        return len(np.unique(self.test_unit))


def default_root() -> Path:
    from common import config
    return config.data_dir() / "benchmarks"


def is_available(root: Path | None = None) -> bool:
    """True when the dataset has been fetched. It is never committed."""
    root = root or default_root()
    return all((root / f"train_{s}.txt").exists() for s in SUBSETS)


def _load_table(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    raw = np.loadtxt(path)
    if raw.ndim != 2 or raw.shape[1] != len(COLUMNS):
        raise ValueError(
            f"{path.name}: expected {len(COLUMNS)} columns, got "
            f"{raw.shape[1] if raw.ndim == 2 else 'ragged'} -- the download is "
            f"truncated or is not C-MAPSS"
        )
    return raw[:, 0].astype(int), raw[:, 1].astype(int), raw[:, 2:]


def load(name: str = "FD001", root: Path | None = None) -> CmapssSplit:
    """Load one sub-dataset, verifying it is the fleet the readme describes."""
    if name not in SUBSETS:
        raise ValueError(f"unknown subset {name!r}; expected one of {SUBSETS}")
    root = root or default_root()
    if not (root / f"train_{name}.txt").exists():
        raise FileNotFoundError(
            f"C-MAPSS not found under {root}. It is a third-party dataset and "
            f"is deliberately not committed -- run scripts/fetch_benchmarks.py"
        )

    tr_u, tr_c, tr_x = _load_table(root / f"train_{name}.txt")
    te_u, te_c, te_x = _load_table(root / f"test_{name}.txt")
    rul = np.loadtxt(root / f"RUL_{name}.txt", ndmin=1)

    split = CmapssSplit(name, tr_u, tr_c, tr_x, te_u, te_c, te_x, rul)

    want_train, want_test = EXPECTED_UNITS[name]
    if split.n_train_units != want_train or split.n_test_units != want_test:
        raise ValueError(
            f"{name}: got {split.n_train_units}/{split.n_test_units} "
            f"train/test units, readme says {want_train}/{want_test} -- "
            f"refusing to benchmark against a partial download"
        )
    if len(rul) != split.n_test_units:
        raise ValueError(
            f"{name}: {len(rul)} RUL labels for {split.n_test_units} test "
            f"units; the label file does not match the data"
        )
    return split


def train_targets(
    unit: np.ndarray, cycle: np.ndarray, *, cap: float = RUL_CAP_CYCLES
) -> np.ndarray:
    """Remaining cycles for training rows, capped the way the field caps them.

    A training unit runs to failure, so its RUL at any cycle is simply the last
    cycle minus this one. The cap is applied because nothing in a healthy
    engine's readings distinguishes 200 remaining cycles from 180, and every
    published figure this is compared against uses it -- the same argument
    `rul_physics.piecewise_rul_target` makes for the 400 h horizon here.
    """
    out = np.empty(len(unit), dtype=float)
    for u in np.unique(unit):
        m = unit == u
        out[m] = cycle[m].max() - cycle[m]
    return np.minimum(out, cap)


def test_targets(
    unit: np.ndarray, cycle: np.ndarray, rul: np.ndarray, *,
    cap: float = RUL_CAP_CYCLES
) -> np.ndarray:
    """Remaining cycles for every test row, not merely the last one.

    The label file gives RUL at each unit's FINAL observed cycle. Earlier rows
    are that value plus the cycles still to come, which is what makes a test
    unit a trajectory rather than a single point -- and trajectories are what
    the prognostics metrics need.
    """
    out = np.empty(len(unit), dtype=float)
    for i, u in enumerate(np.unique(unit)):
        m = unit == u
        out[m] = rul[i] + (cycle[m].max() - cycle[m])
    return np.minimum(out, cap)


# --------------------------------------------------------------------------
# Operating-regime normalisation
#
# FD002 and FD004 are flown under SIX operating conditions; FD001 and FD003
# under one. Scaled globally, the spread between regimes dominates every
# sensor channel and the degradation signal -- the thing being predicted --
# is left as a small wobble on top of a much larger regime step. The standard
# remedy in the literature is to cluster the three operating settings and
# scale within each cluster, so a reading is expressed relative to other
# readings taken under the SAME conditions.
#
# Reported effect of doing this rather than scaling globally: mean RMSE deltas
# of -4.39 on FD002 and -7.40 on FD004 (Auditing Operating-Condition
# Normalization in C-MAPSS RUL Evaluation, engrxiv 8145). FD001 and FD003 have
# one regime, so it should change nothing there -- which is the check that the
# implementation is doing what it claims.

N_REGIMES = 6
_REGIME_EPS = 1e-8


def n_operating_regimes(op: np.ndarray) -> int:
    """How many distinct operating conditions this subset was flown under.

    The settings are near-discrete per condition, so rounding and counting
    distinct triples separates the one-regime subsets from the six-regime ones
    without assuming which subset is which.
    """
    return len(np.unique(np.round(op[:, :3], 0), axis=0))


@dataclass(frozen=True)
class RegimeScaler:
    """Per-regime centre and scale, fitted on TRAIN rows only.

    `centroids` is None for a single-regime subset, in which case this is an
    ordinary global scaler and the regime machinery costs nothing.
    """

    centroids: np.ndarray | None
    centre: np.ndarray            # (regimes, channels)
    scale: np.ndarray             # (regimes, channels), pinned to 1 when flat
    within_std: np.ndarray        # (regimes, channels), the RAW spread

    @property
    def n_regimes(self) -> int:
        return self.centre.shape[0]

    def regime_only(self, eps: float = _REGIME_EPS) -> np.ndarray:
        """Channels that are flat inside EVERY regime.

        Such a channel reports which operating condition the engine is in, not
        anything about the engine. It survives a global zero-variance filter
        because the regimes differ from each other, which is why all 24
        channels look informative on the six-regime subsets.

        This reads `within_std`, not `scale`: `scale` has already had flat
        channels pinned to 1.0 so the division is safe, so testing it finds
        nothing. That mistake made the first version of this check a silent
        no-op -- it returned identical numbers, which is what exposed it.
        """
        return self.within_std.max(axis=0) <= eps


def _assign(centroids: np.ndarray | None, op: np.ndarray) -> np.ndarray:
    if centroids is None:
        return np.zeros(len(op), dtype=int)
    d = ((op[:, None, :] - centroids[None, :, :]) ** 2).sum(axis=2)
    return d.argmin(axis=1)


def fit_regime_scaler(op: np.ndarray, x: np.ndarray, *,
                      seed: int = 0) -> RegimeScaler:
    """Fit one scaler per operating regime. Call on TRAIN rows only.

    A channel that is constant WITHIN a regime carries no information there
    even though it varies across regimes -- it is reporting the regime, not
    the engine. Its scale is set to 1 so it normalises to a constant rather
    than exploding on a near-zero divisor.
    """
    if n_operating_regimes(op) <= 1:
        sd = x.std(axis=0)
        return RegimeScaler(None, x.mean(axis=0)[None, :],
                            np.where(sd > _REGIME_EPS, sd, 1.0)[None, :],
                            sd[None, :])

    from sklearn.cluster import KMeans
    km = KMeans(n_clusters=N_REGIMES, n_init=10, random_state=seed).fit(op)
    lab = km.labels_
    centre = np.zeros((N_REGIMES, x.shape[1]))
    scale = np.ones((N_REGIMES, x.shape[1]))
    within = np.zeros((N_REGIMES, x.shape[1]))
    for r in range(N_REGIMES):
        m = lab == r
        if not m.any():
            continue
        centre[r] = x[m].mean(axis=0)
        sd = x[m].std(axis=0)
        within[r] = sd
        scale[r] = np.where(sd > _REGIME_EPS, sd, 1.0)
    return RegimeScaler(km.cluster_centers_, centre, scale, within)


def apply_regime_scaler(sc: RegimeScaler, op: np.ndarray,
                        x: np.ndarray) -> np.ndarray:
    """Scale rows against the regime each was flown under."""
    r = _assign(sc.centroids, op)
    return (x - sc.centre[r]) / sc.scale[r]


__all__ = [
    "SUBSETS",
    "COLUMNS",
    "RUL_CAP_CYCLES",
    "CmapssSplit",
    "default_root",
    "is_available",
    "load",
    "N_REGIMES",
    "RegimeScaler",
    "n_operating_regimes",
    "fit_regime_scaler",
    "apply_regime_scaler",
    "train_targets",
    "test_targets",
]
