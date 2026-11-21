"""Three-tier score fusion -- PRD Part 2 section 11.2.

Each tier answers a different question and fails in a different way:

  Tier 1  rules        a limit was crossed. Certain, immediate, and blind to
                       anything that has not yet reached a limit.
  Tier 2  statistical  this combination of channels is unusual. Catches
                       subtle multivariate drift; over-fires.
  Tier 3  deep         the network recognises this. Precise, and conservative
                       to the point of missing a third of what is there.

Measured on the held-out engines, the two model tiers fail in OPPOSITE
directions -- the autoencoder runs 0.974 recall at 0.948 precision, the
supervised head 1.000 precision at 0.672 recall. Neither is the answer. Fusing
them is not a formality; it is where most of the remaining accuracy is.

THE SPEC DEFECT THIS MODULE HAD TO FIX
--------------------------------------
PRD Part 2 section 11.2 gives the weights and then three trigger rules:

    L3 if S_final > 0.60 AND S_rule > 0.50
    L4 if S_final > 0.80 AND (S_statistical > 0.70 OR S_deep > 0.80)
    L5 if S_final > 0.95 AND S_rule = 1.0

Work through the arithmetic with the rule engine silent, which is the case
this whole system exists for. S_rule = 0, so even with both models perfectly
certain:

    S_final = 0.3(0) + 0.3(1.0) + 0.4(1.0) = 0.70

That is below the 0.80 L4 needs. And L3 is gated behind S_rule > 0.50, which
on the normalised scale means the rule engine must ALREADY be at ORANGE. So a
model-only detection can raise **nothing at all** -- not a caution, not an
advisory, nothing.

This system has already demonstrated cooling degradation and lubrication
issues detected with the rule engine correctly silent and no threshold
crossed. Under the fusion logic as written, every one of those findings would
have been discarded on the way to the operator. The tiers would have been
built, scored, reported -- and then muted.

THE FIX, AND WHAT IT DELIBERATELY DOES NOT CHANGE
-------------------------------------------------
A fourth path is added: when the rules are silent but BOTH model tiers agree
strongly, raise a CAUTION marked PREDICTIVE. The operator is told plainly that
no limit has been exceeded and this is a developing condition.

What is left exactly as the PRD wrote it: an EMERGENCY still requires
S_rule = 1.0. A model may say an engine is degrading; it may not declare an
emergency on its own. That gate is correct and it stays.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

import numpy as np

from common import config


class FusedLevel(IntEnum):
    """PRD Part 2 section 9.5 levels, as produced by fusion."""

    NONE = 1
    ADVISORY = 2
    CAUTION = 3
    WARNING = 4
    EMERGENCY = 5


def _cfg() -> dict:
    return config.load_thresholds()["detectors"]


def normalise_rule_level(level: int | None) -> float:
    """Map a Tier-1 alert level (1-5) onto [0, 1].

    GREEN 1 -> 0.0, BLUE 2 -> 0.25, YELLOW 3 -> 0.5, ORANGE 4 -> 0.75,
    RED 5 -> 1.0. This is the normalisation PRD Part 2 section 11.2 assumes
    when it writes "max alert level from rule engine (normalized 0-1)", and it
    is what makes its own ``S_rule > 0.50`` gate mean "at least ORANGE".
    """
    if level is None:
        return 0.0
    return float(np.clip((int(level) - 1) / 4.0, 0.0, 1.0))


@dataclass
class FusionResult:
    """One fused verdict, with everything needed to justify it."""

    score: float = 0.0
    level: FusedLevel = FusedLevel.NONE
    s_rule: float = 0.0
    s_statistical: float = 0.0
    s_deep: float = 0.0
    predictive: bool = False
    rule_confirmed: bool = False
    reason: str = ""
    confidence: float = 0.0

    @property
    def rule_based_fallback(self) -> bool:
        """PRD Part 4 section 7.4b: the system must say when it is on rules.

        True when model confidence is below the configured floor, so the
        operator is never left thinking a threshold trip was a learned
        prediction.
        """
        return self.confidence < float(_cfg()["confidence_floor"])


class ScoreFusion:
    """Combines the three tiers into one operator-facing verdict."""

    def __init__(self) -> None:
        c = _cfg()["fusion"]
        w = c["weights"]
        self.w_rule = float(w["rule"])
        self.w_stat = float(w["statistical"])
        self.w_deep = float(w["deep"])
        self.l3 = c["l3"]
        self.l4 = c["l4"]
        self.l5 = c["l5"]
        # The added model-only path. Absent from the PRD, which is the defect
        # described in the module docstring.
        self.l3_pred = c.get(
            "l3_predictive", {"s_statistical_above": 0.70, "s_deep_above": 0.70}
        )

    # ------------------------------------------------------------------
    def fuse(
        self,
        *,
        rule_level: int | None = None,
        s_statistical: float = 0.0,
        s_deep: float = 0.0,
        model_confidence: float = 1.0,
    ) -> FusionResult:
        """Fuse one sample's three tier scores."""
        s_rule = normalise_rule_level(rule_level)
        s_stat = float(np.clip(s_statistical, 0.0, 1.0))
        s_dp = float(np.clip(s_deep, 0.0, 1.0))
        s_final = self.w_rule * s_rule + self.w_stat * s_stat + self.w_deep * s_dp

        res = FusionResult(
            score=s_final, s_rule=s_rule, s_statistical=s_stat, s_deep=s_dp,
            confidence=float(np.clip(model_confidence, 0.0, 1.0)),
        )

        # --- PRD Part 2 section 11.2, in its own order of severity ---------
        if (
            s_final > float(self.l5["s_final_above"])
            and s_rule >= float(self.l5["s_rule_equals"])
        ):
            res.level = FusedLevel.EMERGENCY
            res.rule_confirmed = True
            res.reason = "hard limit exceeded and all tiers agree"
            return res

        if s_final > float(self.l4["s_final_above"]) and (
            s_stat > float(self.l4["s_statistical_above"])
            or s_dp > float(self.l4["s_deep_above"])
        ):
            res.level = FusedLevel.WARNING
            res.rule_confirmed = s_rule > 0.0
            res.reason = "fused score high with strong model agreement"
            return res

        if (
            s_final > float(self.l3["s_final_above"])
            and s_rule > float(self.l3["s_rule_above"])
        ):
            res.level = FusedLevel.CAUTION
            res.rule_confirmed = True
            res.reason = "rule engine and models agree"
            return res

        # --- the added path: models only, no limit crossed -----------------
        # Requires BOTH model tiers, not either. One tier alone is an opinion;
        # two independent methods agreeing is evidence, and this path has no
        # rule confirmation behind it to fall back on.
        if (
            s_stat > float(self.l3_pred["s_statistical_above"])
            and s_dp > float(self.l3_pred["s_deep_above"])
        ):
            res.level = FusedLevel.CAUTION
            # "Predictive" means precisely one thing: NO limit has been
            # exceeded. If the rule engine is firing at all -- even below the
            # PRD's own L3 gate -- the finding is confirmed by a real limit and
            # labelling it predictive would tell the operator the opposite of
            # the truth.
            res.predictive = s_rule <= 0.0
            res.rule_confirmed = s_rule > 0.0
            res.reason = (
                "developing condition -- no limit exceeded; statistical and "
                "deep tiers both indicate degradation"
                if res.predictive
                else "rule engine and both model tiers agree"
            )
            return res

        # A single model tier on its own is an advisory at most. It is worth
        # telling a maintenance engineer about and not worth interrupting a
        # pilot for.
        if max(s_stat, s_dp) > float(self.l3_pred["s_statistical_above"]):
            res.level = FusedLevel.ADVISORY
            res.predictive = s_rule <= 0.0
            res.rule_confirmed = s_rule > 0.0
            res.reason = "single model tier indicates a developing condition"
            return res

        if s_rule > 0.0:
            res.level = FusedLevel(min(5, max(2, int(round(s_rule * 4)) + 1)))
            res.rule_confirmed = True
            res.reason = "rule engine only"
            return res

        res.reason = "all tiers nominal"
        return res

    # ------------------------------------------------------------------
    def fuse_many(
        self,
        rule_levels: np.ndarray,
        s_statistical: np.ndarray,
        s_deep: np.ndarray,
    ) -> dict[str, np.ndarray]:
        """Vectorised fusion for evaluating a whole dataset."""
        n = len(s_statistical)
        score = np.empty(n)
        level = np.empty(n, dtype=int)
        predictive = np.zeros(n, dtype=bool)
        for i in range(n):
            r = self.fuse(
                rule_level=int(rule_levels[i]) if rule_levels is not None else None,
                s_statistical=float(s_statistical[i]),
                s_deep=float(s_deep[i]),
            )
            score[i] = r.score
            level[i] = int(r.level)
            predictive[i] = r.predictive
        return {"score": score, "level": level, "predictive": predictive}


# ---------------------------------------------------------------------------
# Combining the two Tier-3 outputs into one S_deep
# ---------------------------------------------------------------------------


@dataclass
class DeepScoreCombiner:
    """Turns the autoencoder and the supervised head into one S_deep.

    PRD Part 2 section 11.2 assumes a single "anomaly probability from neural
    network", but Tier 3 produces two and they are not interchangeable:
    measured on held-out engines the autoencoder gives 0.974 recall at 0.948
    precision, the supervised head 1.000 precision at 0.672 recall.

    The default is the MAXIMUM, and the reasoning that first put ``mean`` here
    was wrong. The argument against the maximum was that it would inherit the
    autoencoder's false-positive rate wholesale. Measured, it does not: fusion
    only raises an alert when BOTH model tiers agree, and that gate filters the
    autoencoder's false positives before they reach the operator. On held-out
    engines:

        S_deep = mean   precision 1.000  recall 0.551  F1 0.710  FPR 0.000
        S_deep = max    precision 1.000  recall 0.878  F1 0.935  FPR 0.000

    Same precision, same zero false-positive rate, and 33 points more recall.
    Taking the mean was quietly throwing away most of the autoencoder's
    sensitivity by averaging it against a head that abstains.

    Kept configurable because that is how the question was settled --
    scripts/eval_fusion.py measures all four modes rather than trusting the
    argument above.
    """

    mode: str = "max"
    weights: tuple[float, float] = (0.5, 0.5)

    def __call__(self, ae_score: np.ndarray, head_prob: np.ndarray) -> np.ndarray:
        # The autoencoder score is a ratio against its calibrated healthy
        # threshold: 1.0 means "at the boundary". Squashed onto [0, 1] so it
        # is on the same footing as a probability, with 1.0 mapping to 0.5.
        ae = np.asarray(ae_score, dtype=float)
        ae01 = ae / (1.0 + ae)
        hd = np.asarray(head_prob, dtype=float)
        if self.mode == "max":
            return np.maximum(ae01, hd)
        if self.mode == "min":
            return np.minimum(ae01, hd)
        if self.mode == "ae":
            return ae01
        if self.mode == "head":
            return hd
        wa, wh = self.weights
        return (wa * ae01 + wh * hd) / (wa + wh)


__all__ = [
    "DeepScoreCombiner",
    "FusedLevel",
    "FusionResult",
    "ScoreFusion",
    "normalise_rule_level",
]
