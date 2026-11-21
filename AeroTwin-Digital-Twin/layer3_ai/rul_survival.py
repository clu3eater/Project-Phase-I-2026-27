"""Failure probability within a horizon -- the prognostic question that HAS an answer.

WHY THIS EXISTS
---------------
Remaining life in hours cannot be estimated accurately on this fleet, and that
is a property of the data rather than of the modelling. Measured, engine-grouped,
3,807 sortie rows:

    our sensor model                                       0.799-0.819 sigma
    ORACLE, given the simulator's own hidden wear state     0.760 sigma
    + the entire true fault schedule                        0.752 sigma
    + the true FUTURE operating profile                     0.693 sigma

A model handed the hidden state, every future fault and the future flight
profile still cannot get below ~0.69 sigma. We are within about 5 % of that
already, so there is no version of "try harder on the regression" that pays.

THE MECHANISM, SINCE IT DETERMINES WHAT CAN BE FIXED
-----------------------------------------------------
The engine's realised WHOLE-LIFE wear rate would collapse the error --
0.760 -> 0.490 sigma. But that feature peeks at the future. Fitted causally, on
the engine's past alone, it buys nothing: 0.760 -> 0.771 from perfect health
history, 0.819 -> 0.817 from sensor-estimated health, and the past rate
correlates with the whole-life rate at only 0.393.

Faults arrive at random times with random ramps and change the decline rate
AFTER the prediction is made. The past slope does not predict the future slope.
No sensor, window length or architecture fixes that, because at prediction time
the information does not exist yet.

WHAT DOES HAVE AN ANSWER
------------------------
"Will this engine fail within the next H hours?" -- which is the question a
dispatcher actually asks, and the one the maintenance advisory actually needs.
Same features, same engine-grouped splits, gradient-boosted classifier:

    horizon   base    AUC     Brier   base Brier
      12 h   0.027   0.946   0.0216     0.0266
      25 h   0.053   0.926   0.0390     0.0505
      50 h   0.097   0.910   0.0617     0.0873
     100 h   0.183   0.872   0.1201     0.1496
     200 h   0.360   0.825   0.1967     0.2304
     400 h   0.639   0.712   0.2928     0.2307   <- NO SKILL

The same ceiling is still there -- it shows up as the far horizon losing skill --
but it is now visible and labelled instead of hidden inside an RMSE.

WHY GRADIENT BOOSTING RATHER THAN THE NETWORK
----------------------------------------------
3,807 tabular rows. A boosted tree is the right estimator at that scale, and it
matched the LSTM on the regression while being far cheaper to fit and to
explain. The architecture is not the interesting part of this problem; the
framing is.

CALIBRATION IS THE DELIVERABLE, NOT THE AUC
--------------------------------------------
An AUC says the ranking is good. A maintenance decision needs the NUMBER to
mean something: told 0.30, an operator must be right to expect failure about
three times in ten. So every horizon is isotonically calibrated on VALIDATION
engines -- never on test, never on its own training rows -- and reported by
Brier score against the base rate, which is the score a constant predictor of
the base rate would achieve. A horizon that cannot beat that is reported as
having no skill rather than published as if it did.
"""

from __future__ import annotations

import logging
import pickle
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

_log = logging.getLogger(__name__)

# Horizons in flight hours. The first four carry real dispatch decisions -- a
# MALE ISR sortie runs 12-18 h, and the advisory's own scheduling bands are
# 10 h and 25 h. 200 and 400 are computed so the loss of skill is VISIBLE
# rather than assumed.
HORIZONS: tuple[float, ...] = (12.0, 25.0, 50.0, 100.0, 200.0, 400.0)

# A horizon is reported as skilful only if it beats the base rate by this
# margin in Brier skill score. 0.05 rather than 0.0 because a score barely
# above zero is inside the noise of 73 engines and would be a claim the data
# cannot support.
MIN_BRIER_SKILL = 0.05

# Never an input. `rul_hours` DEFINES the label, so admitting it as a feature
# would let the model read the answer; the others are simulator ground truth
# the aircraft cannot observe. Enforced in `_check_no_leakage`, not trusted.
FORBIDDEN_FEATURES = (
    "rul_hours", "rul_target", "censored", "engine_id", "sortie", "split",
    "any_fault",
)
FORBIDDEN_PREFIXES = ("deg_", "lab_", "chi_", "thi_", "mhi_", "comb_hi_")


# Which gradient booster fits each horizon.
#
# MEASURED ON THIS DATA rather than adopted on reputation. Engine-grouped
# 6-fold, identical folds for every library, Brier skill (higher is better):
#
#     horizon   sklearn HistGB      LightGBM        CatBoost
#       25 h    0.327 +/-0.047   0.354 +/-0.054   0.398 +/-0.067
#       50 h    0.443 +/-0.071   0.440 +/-0.078   0.454 +/-0.029
#      100 h    0.479 +/-0.047   0.475 +/-0.052   0.464 +/-0.059
#
# CatBoost wins the two horizons that carry a dispatch decision and is far
# STEADIER at 50 h -- a third of the fold-to-fold spread. It loses at 100 h by
# 0.015, which is inside the noise of six folds, so one library is used
# throughout rather than picking a different one per horizon and calling the
# noise a result. The published comparison that prompted the test (CatBoost
# winning 26 of 30 datasets on Brier) is consistent with this but is not the
# evidence for it; the table above is.
#
# sklearn remains the FALLBACK, not a second choice on merit: it is already in
# the dependency closure, so the system still runs where CatBoost is absent --
# a slim edge image, or a build that has not installed the extra.
BOOSTER_BACKENDS = ("catboost", "sklearn")


def _make_classifier(seed: int, max_iter: int, backend: str = "auto"):
    """The booster, preferring CatBoost and degrading rather than failing."""
    if backend in ("auto", "catboost"):
        try:
            from catboost import CatBoostClassifier

            return CatBoostClassifier(
                iterations=max_iter, random_seed=seed, verbose=0,
                # Writing training artefacts from inside a twin that may run
                # read-only, or from many parallel folds into one directory, is
                # a failure mode with no upside here.
                allow_writing_files=False,
            ), "catboost"
        except ImportError:
            if backend == "catboost":
                raise
    from sklearn.ensemble import HistGradientBoostingClassifier

    return HistGradientBoostingClassifier(
        max_iter=max_iter, random_state=seed
    ), "sklearn"


@dataclass
class HorizonResult:
    """What one horizon achieved, and whether it may be published."""

    horizon_h: float
    n: int = 0
    positives: int = 0
    base_rate: float = 0.0
    auc: float = float("nan")
    brier: float = float("nan")
    brier_base: float = float("nan")
    brier_skill: float = float("nan")
    skilful: bool = False
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "horizon_h": self.horizon_h,
            "n": self.n,
            "positives": self.positives,
            "base_rate": round(self.base_rate, 4),
            "auc": None if np.isnan(self.auc) else round(self.auc, 4),
            "brier": None if np.isnan(self.brier) else round(self.brier, 4),
            "brier_base": None if np.isnan(self.brier_base) else round(self.brier_base, 4),
            "brier_skill": (None if np.isnan(self.brier_skill)
                            else round(self.brier_skill, 4)),
            "skilful": self.skilful,
            "reason": self.reason,
        }


@dataclass
class SurvivalReport:
    horizons: list[HorizonResult] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"horizons": [h.as_dict() for h in self.horizons]}

    def skilful_horizons(self) -> list[float]:
        return [h.horizon_h for h in self.horizons if h.skilful]

    def at(self, horizon_h: float) -> HorizonResult | None:
        for h in self.horizons:
            if abs(h.horizon_h - horizon_h) < 1e-9:
                return h
        return None


def _check_no_leakage(columns) -> None:
    """Refuse a feature set that contains the answer or the simulator's truth.

    A leak here would not fail loudly -- it would produce an excellent AUC and
    a system that cannot work on an aircraft, which is the most expensive kind
    of mistake this project can make (PRD Part 0 s0.5).
    """
    bad = [
        c for c in columns
        if c in FORBIDDEN_FEATURES or c.startswith(FORBIDDEN_PREFIXES)
    ]
    if bad:
        raise ValueError(
            f"these columns must never be model inputs: {sorted(bad)}. "
            f"`rul_hours` defines the label; `deg_*`/`chi_*` are ground truth "
            f"the aircraft cannot observe."
        )


def labels_for(rul_hours: np.ndarray, horizon_h: float) -> np.ndarray:
    """1 if the engine fails within `horizon_h`, else 0."""
    return (np.asarray(rul_hours, dtype=float) <= float(horizon_h)).astype(int)


class SurvivalHead:
    """One calibrated classifier per horizon.

    Separate models rather than one multi-output model: the horizons have very
    different base rates (2.7 % at 12 h, 64 % at 400 h) and calibrating a
    shared output across that range would trade the near horizons -- the ones
    that carry a dispatch decision -- against the far ones, which have no skill
    to protect.
    """

    def __init__(
        self,
        horizons: tuple[float, ...] = HORIZONS,
        *,
        max_iter: int = 300,
        seed: int = 0,
        min_brier_skill: float = MIN_BRIER_SKILL,
        booster: str = "auto",
    ) -> None:
        self.horizons = tuple(float(h) for h in horizons)
        self.max_iter = int(max_iter)
        self.seed = int(seed)
        self.booster = booster
        self.backend = ""      # filled in on fit: which library actually ran
        self.min_brier_skill = float(min_brier_skill)
        self.columns: list[str] = []
        self._models: dict[float, object] = {}
        self._calibrators: dict[float, object] = {}
        self._base_rate: dict[float, float] = {}
        self.report = SurvivalReport()

    # -- fitting ------------------------------------------------------------

    def fit_oof(
        self,
        x: np.ndarray,
        rul: np.ndarray,
        groups: np.ndarray,
        *,
        columns=None,
        n_folds: int = 5,
    ) -> SurvivalReport:
        """Calibrate on OUT-OF-FOLD predictions across ALL training engines.

        WHY THIS EXISTS RATHER THAN THE VALIDATION-SET PATH
        ---------------------------------------------------
        A single held-out validation split gives the isotonic fit only that
        split's engines -- twenty here -- and isotonic regression is least
        reliable exactly at the extremes, where it has fewest points. Measured
        on the real fleet with the validation-set path: the top bin predicted
        **1.000 and was observed at 0.872**. An operator told "certain failure"
        would have been grounding a serviceable aircraft about one time in
        eight, and the error is in the OVER-confident direction, which is the
        expensive one for a dispatch decision.

        Splitting the training engines K ways and calibrating on the pooled
        out-of-fold scores uses every training engine for calibration while
        still never calibrating a model on rows it was fitted to. The model is
        then refitted on all of them.

        Grouped by ENGINE throughout: rows from one engine are near-duplicates,
        so a row-wise fold would let a model recognise an engine it had trained
        on and the calibration would flatter itself.
        """
        from sklearn.isotonic import IsotonicRegression
        from sklearn.model_selection import GroupKFold

        if columns is not None:
            _check_no_leakage(columns)
            self.columns = list(columns)

        n_folds = max(2, min(int(n_folds), len(np.unique(groups))))
        self.report = SurvivalReport()
        for h in self.horizons:
            y = labels_for(rul, h)
            base = float(y.mean())
            self._base_rate[h] = base
            if y.sum() < 10 or (1 - y).sum() < 10:
                self.report.horizons.append(HorizonResult(
                    horizon_h=h, n=len(y), positives=int(y.sum()),
                    base_rate=base, skilful=False,
                    reason="too few examples on one side to fit or score",
                ))
                continue

            oof = np.zeros(len(y), dtype=float)
            for i_fit, i_out in GroupKFold(n_splits=n_folds).split(x, y, groups):
                if y[i_fit].sum() == 0 or (1 - y[i_fit]).sum() == 0:
                    oof[i_out] = base
                    continue
                m, self.backend = _make_classifier(
                    self.seed, self.max_iter, self.booster
                )
                m.fit(x[i_fit], y[i_fit])
                oof[i_out] = m.predict_proba(x[i_out])[:, 1]

            cal = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            cal.fit(oof, y)

            model, self.backend = _make_classifier(
                self.seed, self.max_iter, self.booster
            )
            model.fit(x, y)
            self._models[h] = model
            self._calibrators[h] = cal
            self.report.horizons.append(
                self._score(h, cal.predict(oof), y, on="out-of-fold")
            )
        return self.report

    def fit(
        self,
        x_train: np.ndarray,
        rul_train: np.ndarray,
        *,
        x_val: np.ndarray,
        rul_val: np.ndarray,
        columns=None,
    ) -> SurvivalReport:
        """Fit on training engines, calibrate on VALIDATION engines.

        The split must be by ENGINE. Calibrating on rows from an engine the
        model trained on measures how well it memorised that engine, and the
        calibration would then be optimistic exactly where it is relied on.

        Prefer `fit_oof` where the engine ids are available: this path gives
        the isotonic fit only the validation engines, and measured on the real
        fleet that left the top probability bin over-confident (predicted
        1.000, observed 0.872).
        """
        from sklearn.isotonic import IsotonicRegression

        if columns is not None:
            _check_no_leakage(columns)
            self.columns = list(columns)

        self.report = SurvivalReport()
        for h in self.horizons:
            y_tr = labels_for(rul_train, h)
            y_va = labels_for(rul_val, h)
            base = float(y_va.mean()) if len(y_va) else float("nan")
            self._base_rate[h] = base

            # A horizon with almost no positives on either side cannot be
            # fitted OR scored; say so rather than returning a model that
            # always predicts the majority class.
            if y_tr.sum() < 10 or (1 - y_tr).sum() < 10 or len(y_va) < 20:
                self.report.horizons.append(HorizonResult(
                    horizon_h=h, n=len(y_va), positives=int(y_va.sum()),
                    base_rate=base, skilful=False,
                    reason="too few examples on one side to fit or score",
                ))
                continue

            model, self.backend = _make_classifier(
                self.seed, self.max_iter, self.booster
            )
            model.fit(x_train, y_tr)
            raw = model.predict_proba(x_val)[:, 1]

            # Isotonic rather than Platt: it assumes only monotonicity, where
            # Platt assumes the scores are logistic in the log-odds, and a
            # boosted tree's scores are not.
            cal = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            cal.fit(raw, y_va)

            self._models[h] = model
            self._calibrators[h] = cal
            self.report.horizons.append(
                self._score(h, cal.predict(raw), y_va, on="validation")
            )
        return self.report

    # -- prediction ---------------------------------------------------------

    def predict_proba(self, x: np.ndarray) -> dict[float, np.ndarray]:
        """Calibrated P(fail within h) for every horizon that was fitted."""
        out = {}
        for h, model in self._models.items():
            raw = model.predict_proba(x)[:, 1]
            out[h] = np.clip(self._calibrators[h].predict(raw), 0.0, 1.0)
        return out

    def predict_one(self, x_row: np.ndarray) -> dict[float, float]:
        """One sample, for live serving."""
        row = np.asarray(x_row, dtype=float).reshape(1, -1)
        return {h: float(p[0]) for h, p in self.predict_proba(row).items()}

    # -- persistence --------------------------------------------------------

    def save(self, path: Path | str, *, features: list[str] | None = None
             ) -> Path:
        """Write the fitted head so it can be served by another process.

        Without this the head only ever existed inside the process that
        trained it, which is why the strongest result in the project could not
        be shown anywhere: nothing running could produce the number.

        The FEATURE ORDER travels with the model. A survival probability is
        computed from a plain vector, so a caller that assembles the columns in
        a different order gets a confident answer to a different question, with
        nothing to signal that anything is wrong. `SurvivalServer` refuses to
        serve unless the order it is handed matches the one recorded here.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as fh:
            pickle.dump({
                "version": 1,
                "horizons": list(self.horizons),
                "models": self._models,
                "calibrators": self._calibrators,
                "features": list(features or []),
                "report": self.report.as_dict() if self.report else None,
            }, fh)
        return path

    @classmethod
    def load(cls, path: Path | str) -> tuple[SurvivalHead, list[str]]:
        """Rebuild a fitted head, with the feature order it was trained on."""
        with Path(path).open("rb") as fh:
            blob = pickle.load(fh)
        if blob.get("version") != 1:
            raise ValueError(f"unsupported survival checkpoint version "
                             f"{blob.get('version')!r}")
        head = cls(horizons=tuple(blob["horizons"]))
        head._models = blob["models"]
        head._calibrators = blob["calibrators"]
        return head, list(blob.get("features") or [])

    # -- scoring ------------------------------------------------------------

    def evaluate(self, x: np.ndarray, rul: np.ndarray) -> SurvivalReport:
        """Score on held-out engines. Calibration is NOT refitted here."""
        probs = self.predict_proba(x)
        rep = SurvivalReport()
        for h in self.horizons:
            if h not in probs:
                existing = self.report.at(h)
                rep.horizons.append(existing or HorizonResult(horizon_h=h))
                continue
            rep.horizons.append(
                self._score(h, probs[h], labels_for(rul, h), on="test")
            )
        return rep

    def _score(self, h: float, p: np.ndarray, y: np.ndarray, *, on: str
               ) -> HorizonResult:
        from sklearn.metrics import brier_score_loss, roc_auc_score

        base = float(y.mean())
        res = HorizonResult(horizon_h=h, n=len(y), positives=int(y.sum()),
                            base_rate=base)
        if y.sum() == 0 or y.sum() == len(y):
            res.reason = f"one class only on {on}; nothing to discriminate"
            return res

        res.auc = float(roc_auc_score(y, p))
        res.brier = float(brier_score_loss(y, p))
        # The score a constant predictor of the base rate would get. Beating
        # it is the minimum bar for the number to be worth showing anyone.
        res.brier_base = float(base * (1.0 - base))
        res.brier_skill = (
            1.0 - res.brier / res.brier_base if res.brier_base > 1e-12
            else float("nan")
        )
        res.skilful = bool(res.brier_skill >= self.min_brier_skill)
        res.reason = (
            f"skilful on {on}" if res.skilful
            else f"NO SKILL on {on}: Brier {res.brier:.4f} against "
                 f"{res.brier_base:.4f} for predicting the base rate"
        )
        return res


def format_report(rep: SurvivalReport) -> str:
    lines = [
        f"  {'horizon':<10}{'n':>7}{'base':>8}{'AUC':>8}{'Brier':>9}"
        f"{'base Br':>9}{'skill':>8}  verdict",
        "  " + "-" * 74,
    ]
    for h in rep.horizons:
        auc = "   --  " if np.isnan(h.auc) else f"{h.auc:>7.3f}"
        br = "     -- " if np.isnan(h.brier) else f"{h.brier:>8.4f}"
        bb = "     -- " if np.isnan(h.brier_base) else f"{h.brier_base:>8.4f}"
        sk = "    -- " if np.isnan(h.brier_skill) else f"{h.brier_skill:>7.3f}"
        lines.append(
            f"  {h.horizon_h:<10.0f}{h.n:>7,}{h.base_rate:>8.3f}{auc}{br}{bb}{sk}"
            f"  {'SKILFUL' if h.skilful else 'no skill'}"
        )
    return "\n".join(lines)


__all__ = [
    "HORIZONS",
    "MIN_BRIER_SKILL",
    "HorizonResult",
    "SurvivalHead",
    "SurvivalReport",
    "format_report",
    "labels_for",
]
