"""Mission reliability -- the third pillar of the problem statement's title.

"Health Monitoring, Fault Prediction and Mission Reliability Enhancement". The
first two pillars have had layers built for them. This one had nothing, and it
is the pillar that answers the question an operator actually asks:

    Can this engine fly the mission in front of it?

Health monitoring says how the engine IS. Fault prediction says what is coming.
Neither answers the operational question, because the answer depends on the
mission as much as on the engine: a 4-hour transit and an 18-hour endurance
patrol are different questions of the same airframe on the same day.

WHAT THIS COMPUTES
------------------
  * remaining life measured in MISSIONS, not hours
  * probability the engine completes a given mission
  * abort risk, and which subsystem drives it
  * a Go / No-Go verdict with the reasons that produced it
  * RUL consumed per mission hour -- the cost of flying a profile

WHY THE VERDICT CARRIES ITS REASONS
-----------------------------------
A bare NO-GO is not actionable and will be overridden by the first person under
schedule pressure. A NO-GO that says "remaining life 6 h against an 18 h
mission; thermal subsystem POOR; recommend the 4 h transit profile instead" is
a decision an operator can act on or knowingly accept. PRD Part 4 section 7.4c
forbids presenting a recommendation the operator cannot interrogate, and a
mission verdict is the most consequential recommendation this system makes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np

from common import config


class Verdict(StrEnum):
    GO = "GO"
    GO_WITH_LIMITS = "GO_WITH_LIMITS"
    NO_GO = "NO_GO"


@dataclass
class MissionProfile:
    """A mission the operator is proposing to fly."""

    name: str
    duration_hours: float
    cruise_altitude_ft: float = 15000.0
    cruise_throttle_pct: float = 72.0
    ambient_c: float | None = None

    @property
    def is_endurance(self) -> bool:
        return self.duration_hours >= 12.0


# Representative MALE ISR profiles. A fleet flies a mix, and the answer to
# "can it fly?" differs by profile -- which is the whole point of asking.
STANDARD_PROFILES: tuple[MissionProfile, ...] = (
    MissionProfile("TRANSIT", 4.0, 12000.0, 68.0),
    MissionProfile("ISR PATROL", 10.0, 18000.0, 72.0),
    MissionProfile("ENDURANCE", 18.0, 20000.0, 70.0),
    MissionProfile("HIGH-ALT ISR", 12.0, 23000.0, 82.0),
)


@dataclass
class MissionAssessment:
    """A Go/No-Go verdict and everything that produced it."""

    profile: str
    duration_hours: float
    verdict: Verdict = Verdict.GO
    success_probability: float = 1.0
    abort_risk: float = 0.0
    missions_remaining: float | None = None
    rul_hours: float | None = None
    rul_margin_ratio: float | None = None
    limiting_subsystem: str = ""
    reasons: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    confidence: float = 0.0

    def as_dict(self) -> dict:
        return {
            "profile": self.profile,
            "duration_hours": self.duration_hours,
            "verdict": str(self.verdict),
            "success_probability": round(self.success_probability, 4),
            "abort_risk": round(self.abort_risk, 4),
            "missions_remaining": (
                round(self.missions_remaining, 2)
                if self.missions_remaining is not None else None
            ),
            "rul_hours": self.rul_hours,
            "rul_margin_ratio": (
                round(self.rul_margin_ratio, 2)
                if self.rul_margin_ratio is not None else None
            ),
            "limiting_subsystem": self.limiting_subsystem,
            "reasons": self.reasons,
            "recommendations": self.recommendations,
            "confidence": round(self.confidence, 3),
        }


class MissionReliability:
    """Turns engine health and remaining life into a mission decision."""

    def __init__(self) -> None:
        t = config.load_thresholds()
        self.chi_threshold = float(t["rul"]["maintenance_chi_threshold"])
        # PRD Part 2 advisory rule R6: an engine whose remaining life is below
        # 1.5x the planned mission duration is a mission-abort risk. The margin
        # exists because RUL is an estimate with an interval, and flying to the
        # point estimate leaves nothing for the interval.
        self.required_margin = 1.5
        self.bands = t["health"]["chi_bands"]

    # ------------------------------------------------------------------
    def assess(
        self,
        profile: MissionProfile,
        *,
        chi: float,
        subsystems: dict[str, float],
        rul_hours: float | None,
        rul_lower_hours: float | None = None,
        rul_confidence: float = 0.0,
        active_alerts: int = 0,
        highest_alert_level: int = 1,
        grounded: bool = False,
        grounding_reason: str | None = None,
        tbo_remaining_hours: float | None = None,
    ) -> MissionAssessment:
        """Can this engine fly this mission?

        `grounded` carries the maintenance advisory's grounding decision. The
        advisory could say GROUND THE AIRCRAFT while every card here said GO,
        because nothing passed it across (SAF-02). `tbo_remaining_hours` is the
        overhaul limit still to run; no estimator may plan past it (SAF-07).
        """
        a = MissionAssessment(
            profile=profile.name,
            duration_hours=profile.duration_hours,
            rul_hours=rul_hours,
            confidence=rul_confidence,
        )

        worst_name, worst_value = self._worst(subsystems)
        a.limiting_subsystem = worst_name
        # A health figure that could not be computed is not a healthy one
        # (SAF-11). NaN compares False against every threshold below, so an
        # engine with NO valid health reading was given GO, "health nan, all
        # subsystems above 0.60".
        chi_known = chi is not None and bool(np.isfinite(chi))
        unknown_subsystems = sorted(
            k for k, v in subsystems.items()
            if v is None or not np.isfinite(v)
        )

        # --- remaining life against the mission ---------------------------
        # The LOWER bound is used, not the point estimate. Planning against the
        # centre of a confidence interval means being wrong half the time, and
        # the half you are wrong is the half where the engine quits early.
        planning_rul = rul_lower_hours if rul_lower_hours is not None else rul_hours
        # "1200 h or 15 years, whichever comes first" (MML-915 i 05-10-00)
        # bounds remaining life whatever any estimator says. It was computed
        # in twin_state and read by nothing, so an engine at 1,199 h could be
        # given GO for an 18 h sortie (SAF-07).
        if tbo_remaining_hours is not None:
            tbo = max(0.0, float(tbo_remaining_hours))
            planning_rul = tbo if planning_rul is None else min(planning_rul, tbo)
        if planning_rul is not None and profile.duration_hours > 0:
            a.rul_margin_ratio = planning_rul / profile.duration_hours
            a.missions_remaining = planning_rul / profile.duration_hours

        # --- probability of completing the mission ------------------------
        a.success_probability = self._success_probability(
            chi=chi if chi_known else 0.0, worst=worst_value,
            margin=a.rul_margin_ratio,
            alert_level=highest_alert_level,
        )
        a.abort_risk = 1.0 - a.success_probability

        # --- the verdict, and why -----------------------------------------
        no_go, limits = [], []

        if highest_alert_level >= 5:
            no_go.append("a WARNING-level limit is currently exceeded")
        if grounded:
            no_go.append("maintenance advisory requires grounding"
                         + (f" ({grounding_reason})" if grounding_reason else ""))
        if tbo_remaining_hours is not None and tbo_remaining_hours <= 0:
            no_go.append("overhaul limit reached: 1200 h or 15 years, "
                         "whichever comes first (MML-915 i 05-10-00)")
        if not chi_known:
            no_go.append("health index not determinable — no valid reading")
        elif chi <= self.chi_threshold:
            no_go.append(
                f"health index {chi:.2f} is at or below the maintenance "
                f"threshold {self.chi_threshold:.2f}"
            )
        if worst_value <= 0.40:
            # PRD Part 2 section 9.3's own band table: below 0.40 is UNSAFE.
            # A composite average can hide this, which is why the subsystem is
            # tested directly -- the same reasoning as DEV-45 and DEV-72.
            no_go.append(f"{worst_name} subsystem at {worst_value:.2f} (UNSAFE band)")
        # Everything above is a reason NO profile can be flown. Remaining life,
        # below, is the only NO-GO a shorter profile can answer.
        health_blocked = bool(no_go)
        if a.rul_margin_ratio is not None and a.rul_margin_ratio < 1.0:
            no_go.append(
                f"remaining life {planning_rul:.0f} h is less than the "
                f"{profile.duration_hours:.0f} h mission"
            )

        if a.rul_margin_ratio is not None and 1.0 <= a.rul_margin_ratio < self.required_margin:
            limits.append(
                f"remaining life {planning_rul:.0f} h gives only "
                f"{a.rul_margin_ratio:.1f}x the {profile.duration_hours:.0f} h "
                f"mission (policy requires {self.required_margin:.1f}x)"
            )
        if 0.40 < worst_value <= 0.60:
            limits.append(f"{worst_name} subsystem degraded ({worst_value:.2f})")
        if highest_alert_level == 4:
            limits.append("a CAUTION-level limit is active")
        if active_alerts > 0 and highest_alert_level < 4:
            limits.append(f"{active_alerts} advisory alert(s) active")
        if unknown_subsystems:
            limits.append(
                "health not determinable for the "
                + ", ".join(unknown_subsystems) + " subsystem(s)"
            )

        if no_go:
            a.verdict = Verdict.NO_GO
            a.reasons = no_go
        elif limits:
            a.verdict = Verdict.GO_WITH_LIMITS
            a.reasons = limits
        else:
            a.verdict = Verdict.GO
            a.reasons = [
                f"health {chi:.2f}, all subsystems above 0.60"
                + (
                    f", remaining life {a.rul_margin_ratio:.1f}x mission duration"
                    if a.rul_margin_ratio is not None else ""
                )
            ]

        a.recommendations = self._recommend(
            a, profile, worst_name, worst_value, health_blocked=health_blocked,
        )

        # A verdict resting on an RUL estimate is only as good as that
        # estimate. Saying so is the difference between a recommendation the
        # operator can weigh and one they must simply obey.
        if rul_hours is None:
            a.confidence = min(a.confidence, 0.3)
            a.reasons.append(
                "remaining life not yet determinable — verdict rests on current "
                "health alone"
            )
        return a

    # ------------------------------------------------------------------
    def _worst(self, subsystems: dict[str, float]) -> tuple[str, float]:
        vals = {k: v for k, v in subsystems.items()
                if v is not None and np.isfinite(v)}
        if not vals:
            return "", 1.0
        k = min(vals, key=lambda x: vals[x])
        return k, float(vals[k])

    def _success_probability(
        self, *, chi: float, worst: float, margin: float | None, alert_level: int
    ) -> float:
        """Probability the engine completes the mission.

        Deliberately NOT a calibrated statistical probability -- there is no
        fleet failure history to calibrate one against, and presenting an
        uncalibrated number as a probability would be the sort of false
        precision this project has been removing everywhere else. It is a
        bounded risk score on a probability scale, and ``confidence`` travels
        with it so the operator knows which they are reading.

        The worst subsystem is weighted more heavily than the composite,
        because engines fail at their weakest point rather than at their
        average.
        """
        p = 0.35 * float(np.clip(chi, 0, 1)) + 0.45 * float(np.clip(worst, 0, 1))
        if margin is not None:
            # Full marks at 2x the mission, falling away below it.
            p += 0.20 * float(np.clip(margin / 2.0, 0.0, 1.0))
        else:
            p += 0.20 * 0.5   # unknown remaining life is neither good nor bad
        if alert_level >= 5:
            p *= 0.25
        elif alert_level == 4:
            p *= 0.70
        return float(np.clip(p, 0.0, 1.0))

    def _recommend(
        self, a: MissionAssessment, profile: MissionProfile,
        worst_name: str, worst_value: float,
        *, health_blocked: bool = False,
    ) -> list[str]:
        """Concrete alternatives, not just a refusal.

        An operator told "no" without an alternative will fly anyway or lose
        the sortie. A shorter profile that the engine CAN fly is usually
        available, and naming it turns a refusal into a plan.
        """
        out: list[str] = []
        if a.verdict is Verdict.GO:
            return out

        if a.rul_margin_ratio is not None and a.rul_margin_ratio < self.required_margin:
            if health_blocked:
                # A shorter sortie does not cure a WARNING, an UNSAFE subsystem
                # or a health index at the maintenance threshold.
                out.append("no profile is flyable until the NO-GO condition "
                           "is cleared — maintain before the next sortie")
            else:
                # The SAME planning figure the verdict used: the lower
                # confidence bound (SAF-01). Sized from the central estimate,
                # the alternative told an engine planned at 5 h to fly the 18 h
                # ENDURANCE profile -- on every card, ENDURANCE's own included.
                # Only strictly shorter profiles are offered, and each clears
                # the policy margin, so none can be NO-GO on remaining life.
                planning_rul = a.rul_margin_ratio * profile.duration_hours
                usable = planning_rul / self.required_margin
                shorter = [p for p in STANDARD_PROFILES
                           if p.duration_hours <= usable
                           and p.duration_hours < profile.duration_hours]
                if shorter:
                    best = max(shorter, key=lambda p: p.duration_hours)
                    out.append(
                        f"fly the {best.name} profile instead "
                        f"({best.duration_hours:.0f} h, within the available margin)"
                    )
                elif a.verdict is Verdict.NO_GO:
                    out.append("no standard profile fits the remaining margin — "
                               "schedule maintenance before the next sortie")
                else:
                    out.append("no shorter standard profile restores the "
                               f"{self.required_margin:.1f}x planning margin")

        if worst_name == "thermal" and worst_value < 0.70:
            out.append(
                "thermal margin is the limit: reduce cruise altitude or "
                "throttle, or fly in the cooler part of the day"
            )
        elif worst_name == "mechanical" and worst_value < 0.70:
            out.append("mechanical margin is the limit: inspect bearings and "
                       "oil system before the next sortie")
        elif worst_name == "combustion" and worst_value < 0.70:
            out.append("combustion margin is the limit: inspect injectors and "
                       "check fuel delivery")
        elif worst_name == "electrical" and worst_value < 0.70:
            out.append("electrical margin is the limit: check alternator "
                       "output and bus regulation")

        if profile.is_endurance and a.verdict is not Verdict.GO:
            out.append("endurance profiles consume the most life per sortie — "
                       "prefer a shorter task while degraded")
        return out

    # ------------------------------------------------------------------
    def assess_all(self, **kwargs) -> list[MissionAssessment]:
        """Every standard profile, so the operator sees what IS flyable.

        Presenting only the requested mission answers "can I fly this?" but not
        "what can I fly?", and the second question is the one that saves the
        sortie.
        """
        return [self.assess(p, **kwargs) for p in STANDARD_PROFILES]


def rul_consumption_rate(
    health_rate_per_hour: float | None, chi: float, chi_threshold: float = 0.60
) -> float | None:
    """Life consumed per flight hour, relative to a nominal engine.

    1.0 means this engine is using up its life at the expected rate. 2.3 means
    the profile being flown is costing it more than twice what a nominal one
    would -- which is exactly the number that makes a thermal margin argument
    concrete to someone planning a mission.
    """
    if health_rate_per_hour is None or health_rate_per_hour >= 0:
        return None
    decline = -health_rate_per_hour
    margin = max(chi - chi_threshold, 1e-6)
    hours_left = margin / decline
    # A nominal engine consumes its remaining margin over the remaining TBO.
    nominal_hours = 1200.0 * (margin / max(1.0 - chi_threshold, 1e-6))
    return float(np.clip(nominal_hours / max(hours_left, 1e-6), 0.0, 99.0))


__all__ = [
    "STANDARD_PROFILES",
    "MissionAssessment",
    "MissionProfile",
    "MissionReliability",
    "Verdict",
    "rul_consumption_rate",
]
