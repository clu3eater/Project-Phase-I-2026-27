"""Tier 2: statistical / unsupervised detection -- PRD Part 2 section 11.1.

Tier 1 (``layer1_edge.edge_rules``) catches limit violations. It cannot catch
an engine whose every channel is individually in range but whose COMBINATION is
wrong -- a cylinder head 15 K hotter than that throttle setting and that
outside air temperature can explain. That is what this tier is for, and it
needs no labelled fault data: it learns what normal looks like and reports
distance from it.

WHY THESE ARE IMPLEMENTED RATHER THAN IMPORTED
----------------------------------------------
PRD Part 2 section 11.1 names PyOD and dtaianomaly. PyOD pins numpy and
scikit-learn versions that conflict with the rest of this stack, and the same
was already true of ADTK for Tier 1 (docs/PRD_DEVIATIONS.md DEV-7). The
requirement is the ALGORITHMS, not the packages: Isolation Forest comes from
scikit-learn, which is a first-class dependency already, and CBLOF and the
matrix profile are short enough to implement directly and test. Every
algorithm's semantics and every parameter in ``thresholds.detectors.tier2``
are preserved. See DEV-46.

WHAT "NORMAL" MEANS HERE
------------------------
The detectors are fitted ONLY on rows the simulator certifies as healthy, from
the training engines alone. Fitting on everything would teach the ensemble that
faults are ordinary -- which is the failure mode of most unsupervised
monitoring, and it is invisible because the model still produces scores.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from sklearn.cluster import KMeans
from sklearn.ensemble import IsolationForest

from common import config
from layer3_ai import features as feat


def _cfg() -> dict:
    return config.load_thresholds()["detectors"]["tier2"]


# ---------------------------------------------------------------------------
# Score calibration
# ---------------------------------------------------------------------------


@dataclass
class Calibrator:
    """Maps a detector's raw score onto [0, 1] against healthy data.

    Every algorithm here produces a score on its own arbitrary scale -- tree
    path length, distance to a cluster centre, nearest-neighbour distance.
    Averaging those directly would let whichever algorithm has the largest
    units dominate the ensemble, so each is first expressed as a percentile of
    what it produced on HEALTHY training data.

    The reference set is healthy data specifically. Calibrating against all
    data would define anomalies relative to a population that contains them.
    """

    quantiles: np.ndarray = field(default_factory=lambda: np.zeros(0))

    @classmethod
    def fit(cls, healthy_scores: np.ndarray, n: int = 512) -> Calibrator:
        qs = np.quantile(np.asarray(healthy_scores, dtype=float), np.linspace(0.0, 1.0, n))
        return cls(quantiles=np.maximum.accumulate(qs))

    def transform(self, scores: np.ndarray) -> np.ndarray:
        if self.quantiles.size == 0:
            return np.zeros_like(np.asarray(scores, dtype=float))
        idx = np.searchsorted(self.quantiles, np.asarray(scores, dtype=float), side="right")
        return np.clip(idx / len(self.quantiles), 0.0, 1.0)


# ---------------------------------------------------------------------------
# Algorithm 2: CBLOF
# ---------------------------------------------------------------------------


@dataclass
class CBLOF:
    """Clustering-Based Local Outlier Factor (PRD Part 2 section 11.1 alg. 2).

    Clusters are split into LARGE and SMALL by the alpha/beta rule of He, Xu
    and Deng (2003). A point in a large cluster is scored by its distance to
    that cluster's own centre; a point in a small cluster is scored by its
    distance to the nearest LARGE centre, because belonging to a small cluster
    is itself evidence of being unusual.

    This is what makes it complementary to Isolation Forest here: an engine
    drifting into its own small region of the operating space is caught by the
    cluster-size term even when no single coordinate is extreme.
    """

    n_clusters: int = 8
    alpha: float = 0.9
    beta: float = 5.0
    random_state: int = 0

    _km: KMeans | None = None
    _large: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=bool))
    _centres: np.ndarray = field(default_factory=lambda: np.zeros(0))

    def fit(self, x: np.ndarray) -> CBLOF:
        k = min(self.n_clusters, max(1, len(x) // 10))
        self._km = KMeans(n_clusters=k, n_init=10, random_state=self.random_state).fit(x)
        self._centres = self._km.cluster_centers_
        labels = self._km.labels_
        sizes = np.array([(labels == i).sum() for i in range(k)], dtype=float)
        order = np.argsort(-sizes)
        cum = np.cumsum(sizes[order])
        total = sizes.sum()

        # alpha: the boundary is where the largest clusters together hold
        # alpha of all points. beta: the boundary is where one cluster is beta
        # times the size of the next. Either rule can close the set; the
        # earlier boundary wins, as in the original paper.
        b_alpha = int(np.searchsorted(cum, self.alpha * total) + 1)
        b_beta = len(order)
        for i in range(1, len(order)):
            if sizes[order[i - 1]] >= self.beta * max(sizes[order[i]], 1e-9):
                b_beta = i
                break
        boundary = max(1, min(b_alpha, b_beta))

        self._large = np.zeros(k, dtype=bool)
        self._large[order[:boundary]] = True
        return self

    def score(self, x: np.ndarray) -> np.ndarray:
        assert self._km is not None, "CBLOF.score before fit"
        labels = self._km.predict(x)
        large_centres = self._centres[self._large]
        d_own = np.linalg.norm(x - self._centres[labels], axis=1)
        d_large = np.min(
            np.linalg.norm(x[:, None, :] - large_centres[None, :, :], axis=2), axis=1
        )
        in_large = self._large[labels]
        return np.where(in_large, d_own, d_large)


# ---------------------------------------------------------------------------
# Algorithm 3: Matrix profile
# ---------------------------------------------------------------------------


@dataclass
class MatrixProfile:
    """Distance from each subsequence to its nearest neighbour elsewhere.

    A repeated pattern has a near neighbour and scores low; a subsequence
    unlike anything else in the series scores high. This is the only Tier-2
    detector that sees TIME -- the other two treat each sample independently
    and so cannot distinguish a value that is unusual from a value that
    arrived in an unusual order.

    Z-NORMALISATION IS OFF BY DEFAULT, AND THAT IS DELIBERATE
    The textbook matrix profile z-normalises each subsequence so it matches on
    SHAPE regardless of level. That is the right choice when hunting repeated
    motifs, and exactly the wrong one here: engine degradation shows up as a
    slow LEVEL SHIFT in a residual, and z-normalising subtracts precisely the
    quantity being measured. Verified on a synthetic series with a planted
    level shift -- with z-normalisation the profile peaked at index 83 instead
    of the planted anomaly at 3000, because a shifted block of noise has the
    same shape as unshifted noise. Enable ``znorm`` only to hunt shape changes
    at a constant level.
    """

    window: int = 100
    exclusion: int = 50
    znorm: bool = False

    def profile(self, series: np.ndarray) -> np.ndarray:
        """Matrix profile of ``series``.

        Distances are computed from dot products rather than by materialising
        the difference of every subsequence pair. For z-normalised windows of
        length m the identity is exact:

            d(a, b)^2 = ||a||^2 + ||b||^2 - 2 a.b

        so the entire pairwise distance matrix is one matrix multiply. The
        direct form allocated a (block, n, m) array -- 61 GB on this dataset --
        for a result that fits in a single (block, n) product.
        """
        x = np.asarray(series, dtype=float)
        n = len(x) - self.window + 1
        if n <= self.exclusion + 2:
            return np.zeros(max(len(x), 1))

        idx = np.arange(self.window)[None, :] + np.arange(n)[:, None]
        subs = x[idx]
        if self.znorm:
            mu = subs.mean(axis=1, keepdims=True)
            sd = subs.std(axis=1, keepdims=True)
            subs = (subs - mu) / np.maximum(sd, 1e-9)
            sq = np.full(n, float(self.window))
        else:
            sq = np.einsum("ij,ij->i", subs, subs)

        out = np.empty(n)
        block = max(1, min(n, 256))
        cols = np.arange(n)
        for start in range(0, n, block):
            stop = min(start + block, n)
            d2 = (
                sq[start:stop, None] + sq[None, :]
                - 2.0 * (subs[start:stop] @ subs.T)
            )
            rows = np.arange(start, stop)
            # Trivial matches: a subsequence's neighbours in time are itself
            # shifted by a step or two, and would score every point zero.
            d2[np.abs(rows[:, None] - cols[None, :]) <= self.exclusion] = np.inf
            out[start:stop] = np.sqrt(np.maximum(d2.min(axis=1), 0.0))

        out[~np.isfinite(out)] = 0.0
        # Spread the subsequence score back over the samples it covers.
        full = np.empty(len(x))
        full[:n] = out
        full[n:] = out[-1]
        return full


# ---------------------------------------------------------------------------
# The ensemble
# ---------------------------------------------------------------------------


@dataclass
class Tier2Result:
    score: np.ndarray
    per_algorithm: dict[str, np.ndarray]
    alert_level: np.ndarray


class Tier2Ensemble:
    """Isolation Forest + CBLOF + matrix profile, weighted per configuration."""

    def __init__(
        self,
        feature_set: feat.FeatureSet | None = None,
        *,
        random_state: int = 0,
    ) -> None:
        c = _cfg()
        self.cfg = c
        self.features = feature_set or feat.extended()
        self.weights = dict(c["ensemble_weights"])
        self.l3 = float(c["alert_l3_above"])
        self.l4 = float(c["alert_l4_above"])
        self.random_state = random_state

        i = c["isolation_forest"]
        self.iforest = IsolationForest(
            n_estimators=int(i["n_estimators"]),
            contamination=float(i["contamination"]),
            max_samples=int(i["max_samples"]),
            random_state=random_state,
            n_jobs=-1,
        )
        b = c["cblof"]
        self.cblof = CBLOF(
            n_clusters=int(b["n_clusters"]),
            alpha=float(b["alpha"]),
            beta=float(b["beta"]),
            random_state=random_state,
        )
        m = c["matrix_profile"]
        self.mprofile = MatrixProfile(
            window=int(m["window_size"]), exclusion=int(m["exclusion_zone"])
        )
        self._cal: dict[str, Calibrator] = {}
        self.fitted = False

    # ------------------------------------------------------------------
    def fit(self, x_healthy: np.ndarray, mp_series: np.ndarray | None = None) -> Tier2Ensemble:
        """Fit on HEALTHY samples only (PRD Part 2 section 11.1 Tier 2)."""
        if len(x_healthy) < 50:
            raise ValueError(f"not enough healthy samples to fit: {len(x_healthy)}")

        self.iforest.fit(x_healthy)
        # score_samples is HIGHER for normal points; negate so that larger
        # always means more anomalous, consistently across all three.
        self._cal["iforest"] = Calibrator.fit(-self.iforest.score_samples(x_healthy))

        self.cblof.fit(x_healthy)
        self._cal["cblof"] = Calibrator.fit(self.cblof.score(x_healthy))

        if mp_series is not None and len(mp_series) > self.mprofile.window * 2:
            self._cal["matrix_profile"] = Calibrator.fit(self.mprofile.profile(mp_series))
        self.fitted = True
        return self

    def score(self, x: np.ndarray, mp_series: np.ndarray | None = None) -> Tier2Result:
        """Ensemble anomaly score in [0, 1] per sample."""
        if not self.fitted:
            raise RuntimeError("Tier2Ensemble.score before fit")

        per: dict[str, np.ndarray] = {
            "iforest": self._cal["iforest"].transform(-self.iforest.score_samples(x)),
            "cblof": self._cal["cblof"].transform(self.cblof.score(x)),
        }
        if mp_series is not None and "matrix_profile" in self._cal:
            mp = self.mprofile.profile(mp_series)[: len(x)]
            if len(mp) < len(x):
                mp = np.pad(mp, (0, len(x) - len(mp)), mode="edge")
            per["matrix_profile"] = self._cal["matrix_profile"].transform(mp)

        # Renormalise over the algorithms that actually ran, so a missing
        # matrix profile lowers nobody's score -- it would otherwise look like
        # evidence of health.
        active = {k: float(self.weights.get(k, 0.0)) for k in per}
        total = sum(active.values()) or 1.0
        score = sum(per[k] * (w / total) for k, w in active.items())

        level = np.where(score > self.l4, 4, np.where(score > self.l3, 3, 0))
        return Tier2Result(score=score, per_algorithm=per, alert_level=level)

    def score_one(self, values: dict) -> float:
        """Score a single live sample from the twin."""
        x = feat.build_one(values, self.features).reshape(1, -1)
        return float(self.score(x).score[0])


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def evaluate(score: np.ndarray, is_anomaly: np.ndarray, threshold: float) -> dict[str, float]:
    """Precision / recall / F1 / false-positive rate at one threshold.

    False-positive rate is reported alongside recall because PRD Part 2
    section 11.1 sets it as a hard target (< 5 %): an operator who is alerted
    on healthy engines stops reading the alerts, and the system's recall then
    becomes irrelevant.
    """
    pred = score > threshold
    tp = int(np.sum(pred & is_anomaly))
    fp = int(np.sum(pred & ~is_anomaly))
    fn = int(np.sum(~pred & is_anomaly))
    tn = int(np.sum(~pred & ~is_anomaly))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    fpr = fp / (fp + tn) if fp + tn else 0.0
    return {
        "precision": precision, "recall": recall, "f1": f1, "fpr": fpr,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
    }


def roc_auc(score: np.ndarray, is_anomaly: np.ndarray) -> float:
    """AUC by rank statistic -- threshold-free, so it compares feature sets fairly."""
    y = np.asarray(is_anomaly, dtype=bool)
    n_pos, n_neg = int(y.sum()), int((~y).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    order = np.argsort(np.asarray(score, dtype=float), kind="mergesort")
    ranks = np.empty(len(score), dtype=float)
    ranks[order] = np.arange(1, len(score) + 1)
    # Average ranks within ties, or identical scores would bias the result.
    s_sorted = np.asarray(score, dtype=float)[order]
    i = 0
    while i < len(s_sorted):
        j = i
        while j + 1 < len(s_sorted) and s_sorted[j + 1] == s_sorted[i]:
            j += 1
        if j > i:
            ranks[order[i : j + 1]] = 0.5 * (i + j) + 1.0
        i = j + 1
    return float((ranks[y].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def detection_lead_time(
    df, score: np.ndarray, threshold: float, *, min_run: int = 3
) -> dict[str, float]:
    """How many flight hours before end of life the detector first fires.

    This is the number that matters operationally, and no confusion matrix
    contains it. A detector that fires reliably one hour before failure scores
    beautifully on F1 and is useless: the maintenance decision it exists to
    inform was needed weeks earlier.

    ``min_run`` consecutive samples are required so a single noisy sample does
    not count as a detection.
    """
    leads: list[float] = []
    for eid, grp in df.assign(_s=score).groupby("engine_id", sort=True):
        if bool(grp["censored"].iloc[0]):
            continue  # no true failure time to measure against
        g = grp.sort_values("flight_hours")
        fired = (g["_s"] > threshold).to_numpy()
        run = 0
        first = None
        for i, f in enumerate(fired):
            run = run + 1 if f else 0
            if run >= min_run:
                first = i - min_run + 1
                break
        if first is None:
            leads.append(0.0)
            continue
        leads.append(float(g["rul_hours"].iloc[first]))
    if not leads:
        return {"engines": 0}
    arr = np.array(leads)
    return {
        "engines": len(arr),
        "detected": int((arr > 0).sum()),
        "median_lead_h": float(np.median(arr)),
        "mean_lead_h": float(arr.mean()),
        "min_lead_h": float(arr.min()),
        "max_lead_h": float(arr.max()),
    }


def _percentile_threshold(healthy_scores: np.ndarray, fpr_target: float) -> float:
    """Threshold that holds the false-positive rate on healthy data.

    Chosen on healthy TRAINING data, never on the test set -- picking it where
    it happens to look best on test is how a reported false-positive rate stops
    predicting the fielded one.
    """
    return float(np.quantile(healthy_scores, 1.0 - fpr_target))


# ---------------------------------------------------------------------------
# Alarm limits per flight condition (DEV-252)
# ---------------------------------------------------------------------------

# Band edges of the condition grid. Three throttle edges, two altitude, two
# OAT: 4 x 3 x 3 = 36 cells, of which a fleet flies about half. A cell with
# too few healthy training rows falls back to the single global limit.
REGIME_BINS = {
    "throttle_pct": (55.0, 70.0, 85.0),
    "altitude_ft": (6000.0, 12000.0),
    "oat_c": (-10.0, 5.0),
}
REGIME_MIN_ROWS = 300


def regime_code(throttle_pct, altitude_ft, oat_c, bins: dict | None = None):
    """Integer cell of the condition grid, for scalars or arrays.

    Missing condition values give -1: no cell, so the global limit applies.
    """
    b = bins or REGIME_BINS
    t = np.asarray(throttle_pct, dtype=float)
    a = np.asarray(altitude_ft, dtype=float)
    o = np.asarray(oat_c, dtype=float)
    code = (np.digitize(t, b["throttle_pct"]) * 100
            + np.digitize(a, b["altitude_ft"]) * 10
            + np.digitize(o, b["oat_c"]))
    code = np.where(np.isfinite(t) & np.isfinite(a) & np.isfinite(o), code, -1)
    return int(code) if code.ndim == 0 else code


def per_regime_thresholds(
    scores: np.ndarray, healthy: np.ndarray, regimes: np.ndarray,
    fpr_target: float, min_rows: int = REGIME_MIN_ROWS,
) -> tuple[dict[int, float], float]:
    """One alarm limit per flight condition, each holding the target rate.

    Fitted on HEALTHY TRAINING rows only. A single global limit is right on
    average and wrong everywhere: 13.6 % false alarms at part throttle, 1.3 %
    at high throttle. A limit per cell holds the rate in every cell.
    """
    glob = _percentile_threshold(scores[healthy], fpr_target)
    out: dict[int, float] = {}
    for r in np.unique(regimes[healthy]):
        sel = healthy & (regimes == r)
        if int(r) >= 0 and int(sel.sum()) >= min_rows:
            out[int(r)] = _percentile_threshold(scores[sel], fpr_target)
    return out, glob


def score_to_gate(score: float, threshold: float, gate: float) -> float:
    """Re-express a raw score so its calibrated limit lands on the fusion gate.

    The fusion layer decides on fixed gates (a statistical score above 0.70);
    the ensemble's calibrated limit is wherever the healthy percentile fell,
    0.87 for the shipped model. Without this the live alarm and the measured
    false-alarm rate refer to different lines. Piecewise linear: 0 -> 0,
    limit -> gate, 1 -> 1, so order is kept and the full range remains.
    """
    s = float(np.clip(score, 0.0, 1.0))
    thr = float(np.clip(threshold, 1e-6, 1.0 - 1e-6))
    if s <= thr:
        return gate * s / thr
    return gate + (1.0 - gate) * (s - thr) / (1.0 - thr)


def persistent(alarm: np.ndarray, groups: np.ndarray, k: int = 2, n: int = 3) -> np.ndarray:
    """An alarm that holds for k of the last n samples of the same sortie."""
    out = np.zeros(len(alarm), dtype=bool)
    order = np.arange(len(alarm))
    for g in np.unique(groups):
        idx = order[groups == g]
        run = np.convolve(alarm[idx].astype(int), np.ones(n, dtype=int), mode="full")[: len(idx)]
        out[idx] = run >= k
    return out


__all__ = [
    "REGIME_BINS",
    "per_regime_thresholds",
    "persistent",
    "regime_code",
    "score_to_gate",
    "CBLOF",
    "Calibrator",
    "MatrixProfile",
    "Tier2Ensemble",
    "Tier2Result",
    "detection_lead_time",
    "evaluate",
    "roc_auc",
    "_percentile_threshold",
]
