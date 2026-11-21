"""Autonomous maintenance advisory -- PRD Part 2 section 16.

The layers below this one say what is wrong. This one says what to DO about
it, when, and what it will cost -- which is the form a maintenance planner can
actually schedule against.

WHY COST AND DOWNTIME BELONG HERE
---------------------------------
"Cooling system degraded" is a finding. "Cooling system flush, 2 hours down,
Rs 5,000, do it within 25 flight hours" is a decision someone can take to a
planning meeting. A recommendation without a cost gets deferred indefinitely
because nobody can weigh it against the sortie it would displace; one with a
cost can be argued about, which is the point.

THE ORDERING IS BY URGENCY, NOT BY SEVERITY
-------------------------------------------
Two actions with the same severity are not equally pressing if one has ten
flight hours of margin and the other has two hundred. Sorting by severity alone
puts a distant overhaul above an oil change that is due now, and a planner
reading top-down would schedule the wrong thing. Actions are therefore ranked
by how soon they must happen, with severity breaking ties.

WHAT IT WILL NOT DO
-------------------
Recommend an action whose trigger has not fired. A maintenance system that
suggests plausible work on a healthy engine is a maintenance system that gets
switched off -- the same MIL-STD-411F 4.1.1a discipline the alerting layer
follows, applied to advice rather than alarms.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from common import config


@dataclass
class MaintenanceAction:
    """One recommended job, costed and scheduled."""

    action_id: str
    name: str
    reason: str
    severity: str = "ADVISORY"
    due_within_hours: float | None = None
    downtime_hours: float = 0.0
    cost_inr: float = 0.0
    parts: list[str] = field(default_factory=list)
    procedure: list[str] = field(default_factory=list)
    evidence: dict[str, float] = field(default_factory=dict)
    # Actions this one makes unnecessary. A full overhaul replaces the oil,
    # cleans the injectors and inspects the bearings by definition.
    subsumes: list[str] = field(default_factory=list)

    @property
    def urgency_rank(self) -> float:
        """Lower sorts first. Actions with no deadline sort last."""
        return self.due_within_hours if self.due_within_hours is not None else 1e9

    def as_dict(self) -> dict:
        return {
            "action_id": self.action_id,
            "name": self.name,
            "reason": self.reason,
            "severity": self.severity,
            "due_within_hours": self.due_within_hours,
            "downtime_hours": self.downtime_hours,
            "cost_inr": self.cost_inr,
            "parts": self.parts,
            "procedure": self.procedure,
            "evidence": {k: round(v, 4) for k, v in self.evidence.items()},
            "subsumes": self.subsumes,
        }


@dataclass
class MaintenancePlan:
    """Everything that needs doing, in the order it needs doing."""

    actions: list[MaintenanceAction] = field(default_factory=list)
    total_cost_inr: float = 0.0
    total_downtime_hours: float = 0.0
    grounding_required: bool = False
    summary: str = ""

    def as_dict(self) -> dict:
        return {
            "actions": [a.as_dict() for a in self.actions],
            "total_cost_inr": self.total_cost_inr,
            "total_downtime_hours": self.total_downtime_hours,
            "grounding_required": self.grounding_required,
            "summary": self.summary,
        }


# Severity implied by how soon the work is needed. Ranked so ties can be broken
# and so the plan can say whether the aircraft flies.
_SEVERITY_RANK = {"ADVISORY": 1, "CAUTION": 2, "WARNING": 3, "EMERGENCY": 4}


def _band_for(chi: float) -> dict | None:
    """The configured health band containing `chi` (bands listed high to low)."""
    try:
        c = float(chi)
    except (TypeError, ValueError):
        return None
    if c != c:  # NaN belongs to no band
        return None
    for b in config.load_thresholds()["health"]["chi_bands"]:
        if c >= float(b["min"]):
            return b
    return None


class AdvisoryEngine:
    """Turns twin state into a costed, ordered maintenance plan.

    Triggers come from ``thresholds.advisory.actions`` rather than from code,
    so a maintenance engineer can change what prompts a job without touching
    Python -- and so the trigger that fired can be quoted back as evidence.
    """

    def __init__(self) -> None:
        adv = config.load_thresholds()["advisory"]
        self.actions = adv["actions"]
        self.rules = adv["rules"]
        # Measured limits come from the action library itself, never from
        # copies in code that drift from it (SAF-13).
        trig = {a["id"]: a.get("trigger", {}) for a in self.actions}
        self._SEVERE_ABOVE = {
            "misfire_rate": float(trig.get("A4", {}).get("misfire_rate_above", 0.05)),
            "bearing_envelope_x": float(
                trig.get("A5", {}).get("bearing_envelope_above_x", 5.0)),
        }
        # Past these a measured finding grounds the aircraft on its own
        # (SAF-06). Before, only the overhaul could: a dead cylinder -- 100 %
        # misfire -- or a bearing at 50x its envelope floor was told "within
        # 10 flight hours" on a single-engine airframe.
        self._GROUND_ABOVE = {
            "misfire_rate": trig.get("A4", {}).get("ground_misfire_rate_above"),
            "bearing_envelope_x": trig.get("A5", {}).get(
                "ground_bearing_envelope_above_x"),
        }
        # Latched state of the failure-probability trigger (SAF-05).
        self._p_fail_tripped = False

    # ------------------------------------------------------------------
    def recommend(
        self,
        *,
        degradation: dict[str, float],
        health: dict[str, float],
        residuals: dict[str, dict],
        rul_hours: float | None = None,
        survival: dict[str, float] | None = None,
        egt_spread: float | None = None,
        oil_rpm_correlation: float | None = None,
        misfire_rate: float | None = None,
        bearing_envelope_x: float | None = None,
        hours_since_inspection: float | None = None,
        boost_drop_fraction: float | None = None,
        egt_rise_c: float | None = None,
        cht_residual_c: float | None = None,
        wastegate_closure_pct: float | None = None,
    ) -> MaintenancePlan:
        """Build the plan. Only fires on triggers that actually match.

        `survival` is the payload from `layer3_ai.survival_serving`: an
        `available` flag and `horizons` keyed "12h" / "25h" / "50h". It is the
        better-measured of the two prognostics available here: engine-grouped
        AUC 0.946 at 12 h against a point RUL that is late 55% of the time.
        Until it was passed in, it was computed, served and drawn on screen
        while every maintenance decision was still taken on the point RUL --
        the system displayed the trustworthy number and decided on the other
        one. It is ADDITIVE: no existing trigger changed, so an engine that
        was grounded before is still grounded now.

        `misfire_rate` (fraction of cruise samples) and `bearing_envelope_x`
        (bearing defect order against its envelope floor) are the MEASURED
        triggers the configuration names for A4 and A5. The code checked only
        the simulator's own degradation factors for those two -- which a real
        aircraft does not have -- so a vibration limit measured as reached
        raised no bearing inspection. Also additive.
        """
        found: list[MaintenanceAction] = []

        def res(name: str) -> float | None:
            r = residuals.get(name) or {}
            return r.get("mean_delta") if r.get("usable") else None

        chi = float(health.get("chi", 1.0))

        for spec in self.actions:
            hit, reason, evidence = self._evaluate(
                spec, degradation, chi, residuals, rul_hours,
                egt_spread, oil_rpm_correlation, res, survival,
                {"misfire_rate": misfire_rate,
                 "bearing_envelope_x": bearing_envelope_x,
                 "hours_since_inspection": hours_since_inspection,
                 "boost_drop_fraction": boost_drop_fraction,
                 "egt_rise_c": egt_rise_c,
                 "cht_residual_c": cht_residual_c,
                 "wastegate_closure_pct": wastegate_closure_pct},
            )
            if not hit:
                continue
            severity, due = self._schedule(spec["id"], chi, rul_hours, evidence)
            found.append(
                MaintenanceAction(
                    action_id=spec["id"],
                    name=spec["name"],
                    reason=reason,
                    severity=severity,
                    due_within_hours=due,
                    downtime_hours=float(spec.get("downtime_hours", 0.0)),
                    cost_inr=float(spec.get("cost_inr", 0.0)),
                    parts=list(spec.get("parts", [])),
                    procedure=list(spec.get("procedure", [])),
                    evidence=evidence,
                )
            )

        # A full overhaul SUBSUMES the individual jobs -- it drains the oil,
        # cleans the injectors and inspects the bearings by definition. Listing
        # them alongside it double-counts both cost and downtime: on a
        # worn-out engine that inflated the estimate by Rs 77,000 over the
        # overhaul's own Rs 500,000, and a planner reading "complete overhaul
        # AND oil change AND injector clean" would rightly stop trusting the
        # rest of the list.
        found = self._absorb_subsumed(found)

        # Urgency first, severity as the tie-break. A distant overhaul must not
        # outrank an oil change that is due now.
        found.sort(key=lambda a: (a.urgency_rank, -_SEVERITY_RANK[a.severity]))

        plan = MaintenancePlan(
            actions=found,
            total_cost_inr=sum(a.cost_inr for a in found),
            total_downtime_hours=sum(a.downtime_hours for a in found),
            grounding_required=(
                any(a.severity == "EMERGENCY" for a in found)
                # The UNSAFE band's own instruction is "Ground the aircraft".
                or ((_band_for(chi) or {}).get("action") == "ground_immediately")
            ),
        )
        plan.summary = self._summarise(plan, chi)
        return plan

    # ------------------------------------------------------------------
    @staticmethod
    def _absorb_subsumed(found: list[MaintenanceAction]) -> list[MaintenanceAction]:
        """Fold jobs an overhaul already includes into the overhaul itself.

        They are recorded on ``subsumes`` rather than dropped, so the evidence
        that prompted each one survives into the work package -- a technician
        opening the engine should know the injectors were already suspect.
        """
        overhaul = next((a for a in found if a.action_id == "A7"), None)
        if overhaul is None:
            return found
        rest = [a for a in found if a.action_id != "A7"]
        overhaul.subsumes = [a.action_id for a in rest]
        if rest:
            overhaul.reason += (
                f" (supersedes {', '.join(a.name.lower() for a in rest)}; "
                f"an overhaul covers this work)"
            )
        return [overhaul]

    def _evaluate(
        self, spec, degradation, chi, residuals, rul_hours,
        egt_spread, oil_corr, res, survival=None, measured=None,
    ) -> tuple[bool, str, dict]:
        """Does this action's configured trigger fire, and on what evidence?

        Each branch names the measurement that fired it. An action that cannot
        say why it was recommended is one an engineer will ignore.

        EVERY branch is evaluated and every match is kept (SAF-03). Returning
        on the first match let a mild trigger hide a severe one: a bearing
        measured at 12x its envelope floor was booked "at the next scheduled
        maintenance" because a bearing-condition trigger of 0.69 matched first,
        and `_schedule` only ever saw that evidence.
        """
        t = spec.get("trigger", {})
        ev: dict[str, float] = {}
        hits: list[str] = []

        if spec["id"] == "A1":                       # oil change
            q = degradation.get("oil_quality")
            if q is not None and q < float(t["oil_quality_below"]):
                ev["oil_quality"] = q
                hits.append(f"oil quality {q:.2f}, below {t['oil_quality_below']}")
            # A MEASURED trigger a real aircraft has (ML-02): the maintenance
            # clock. Oil quality above is a simulator factor no sensor reports,
            # so on its own the oil change could never fire outside the demo.
            hsi = (measured or {}).get("hours_since_inspection")
            lim = t.get("or_hours_since_oil_change_above")
            if hsi is not None and lim is not None and hsi >= float(lim):
                ev["hours_since_inspection"] = float(hsi)
                hits.append(f"{hsi:.0f} h since the last scheduled check; the oil "
                            f"change falls due every {float(lim):.0f} h "
                            f"(MML-915 i 05-20-00)")

        elif spec["id"] == "A2":                     # cooling flush
            eff = degradation.get("cooling_efficiency")
            # A RECENT residual level when the caller has one. The flight-long
            # running mean in `residuals` dilutes a fault that began mid-flight.
            r = (measured or {}).get("cht_residual_c")
            if r is None:
                r = res("cht")
            if eff is not None and eff < float(t["cooling_efficiency_below"]):
                ev["cooling_efficiency"] = eff
                hits.append(f"cooling efficiency {eff:.2f}")
            if r is not None and r > float(t["or_cht_residual_above"]):
                ev["cht_residual"] = r
                hits.append(
                    f"cylinder head running {r:+.1f} K hotter than an as-new "
                    f"engine at the same operating point"
                )

        elif spec["id"] == "A3":                     # injectors
            if egt_spread is not None and egt_spread > float(t["egt_spread_above"]):
                ev["egt_spread"] = egt_spread
                hits.append(f"EGT spread {egt_spread:.0f} degC across cylinders")
            cond = degradation.get("injector_condition")
            if cond is not None and cond < 0.60:
                ev["injector_condition"] = cond
                hits.append(f"injector condition {cond:.2f}")

        elif spec["id"] == "A4":                     # spark plugs
            comb = degradation.get("combustion_efficiency")
            if comb is not None and comb < 0.90:
                ev["combustion_efficiency"] = comb
                hits.append(f"combustion efficiency {comb:.3f}")
            mr = (measured or {}).get("misfire_rate")
            lim = t.get("misfire_rate_above")
            # `>=`: the per-fault tracker calls the threshold itself "reached",
            # so the advisory must act on it too (SAF-13).
            if mr is not None and lim is not None and mr >= float(lim):
                ev["misfire_rate"] = float(mr)
                hits.append(f"cold-cylinder events in {mr:.0%} of cruise samples "
                            f"(limit {float(lim):.0%})")

        elif spec["id"] == "A5":                     # bearings
            bc = degradation.get("bearing_condition")
            if bc is not None and bc < 0.70:
                ev["bearing_condition"] = bc
                hits.append(f"bearing condition {bc:.2f}")
            if oil_corr is not None and oil_corr < float(t["or_oil_correlation_below"]):
                ev["oil_rpm_correlation"] = oil_corr
                hits.append(
                    f"oil pressure / rpm correlation fallen to {oil_corr:.2f} -- "
                    f"pressure is no longer tracking speed as it should"
                )
            env = (measured or {}).get("bearing_envelope_x")
            lim = t.get("bearing_envelope_above_x")
            if env is not None and lim is not None and env >= float(lim):
                ev["bearing_envelope_x"] = float(env)
                hits.append(f"bearing defect order at {env:.1f}x its "
                            f"envelope floor (limit {float(lim):.1f}x)")

        elif spec["id"] == "A6":                     # turbocharger
            tc = degradation.get("turbocharger_condition")
            if tc is not None and tc < (1.0 - float(t["boost_drop_above"])):
                ev["turbocharger_condition"] = tc
                hits.append(f"turbocharger condition {tc:.2f}")
            # The configured MEASURED triggers (ML-02): charge pressure short of
            # the as-new twin at the same operating point, and exhaust running
            # hotter than it. Before, only the simulator's own turbocharger
            # factor was read, which no real engine publishes.
            bd = (measured or {}).get("boost_drop_fraction")
            if bd is not None and bd >= float(t["boost_drop_above"]):
                ev["boost_drop_fraction"] = float(bd)
                hits.append(f"manifold pressure {bd:.0%} below the as-new twin "
                            f"at the same operating point")
            er = (measured or {}).get("egt_rise_c")
            lim = t.get("or_egt_rise_above_C")
            if er is not None and lim is not None and er >= float(lim):
                ev["egt_rise_c"] = float(er)
                hits.append(f"exhaust gas {er:+.0f} degC hotter than the as-new "
                            f"twin at the same operating point")
            # The early sign (PHY-07): closed-loop boost control holds the boost
            # on a worn turbocharger by closing the wastegate further.
            wc = (measured or {}).get("wastegate_closure_pct")
            lim = t.get("or_wastegate_closure_above_pct")
            if wc is not None and lim is not None and wc >= float(lim):
                ev["wastegate_closure_pct"] = float(wc)
                hits.append(f"wastegate {wc:.0f} points more closed than the as-new "
                            f"twin to hold the same boost")

        elif spec["id"] == "A7":                     # overhaul
            if chi < float(t["chi_below"]):
                ev["chi"] = chi
                hits.append(f"composite health {chi:.2f}")
            if rul_hours is not None and rul_hours < float(t["or_rul_below_hours"]):
                ev["rul_hours"] = rul_hours
                hits.append(f"remaining life {rul_hours:.0f} h")
            # The calibrated horizon probability, which is the better-measured
            # prognostic of the two. Configured as a horizon and a threshold so
            # the operational question -- "how likely is this engine to fail
            # inside the next sortie?" -- is answered by the number that was
            # actually validated against it, rather than inferred from a point
            # estimate that overstates remaining life more often than not.
            limit = t.get("or_p_fail_above")
            horizon = f"{float(t.get('p_fail_horizon_h', 25)):g}h"
            if limit is not None:
                # Trip above `or_p_fail_above`; clear only below
                # `or_p_fail_clear_below` (SAF-05). With a single threshold a
                # probability sitting on it grounded and released the aircraft
                # on alternate ticks -- 0.349 / 0.351 / 0.349 / 0.351 -- and a
                # grounding that flickers is one people learn to ignore. The
                # deadband is standard alarm practice (ISA-18.2, EEMUA 191).
                # An unavailable head is not a low probability, so it neither
                # trips nor clears the latch.
                clear = float(t.get("or_p_fail_clear_below", float(limit) - 0.10))
                p = None
                if (survival or {}).get("available"):
                    p = (survival.get("horizons") or {}).get(horizon)
                if p is not None:
                    p = float(p)
                    if p > float(limit):
                        self._p_fail_tripped = True
                    elif p < clear:
                        self._p_fail_tripped = False
                if self._p_fail_tripped:
                    hz = horizon.rstrip("h")
                    if p is None:
                        hits.append(f"failure probability within {hz} h last "
                                    f"above {float(limit):.0%} (head unavailable; "
                                    f"held until a reading below {clear:.0%})")
                    else:
                        ev["p_fail"] = p
                        hits.append(
                            f"{p:.0%} chance of failure within {hz} h"
                            + ("" if p > float(limit)
                               else f" (held until below {clear:.0%})"))

        return bool(hits), "; ".join(hits), ev

    # How far past its trigger a measurement has to be before the job becomes
    # urgent regardless of the composite. Keyed by the evidence name each
    # trigger records.
    _SEVERE_EVIDENCE = {
        "oil_quality": 0.35,             # below this, the oil is finished
        "cooling_efficiency": 0.55,
        "injector_condition": 0.45,
        "bearing_condition": 0.55,
        "turbocharger_condition": 0.60,
        "combustion_efficiency": 0.85,
        "oil_rpm_correlation": 0.60,
    }
    # The same for MEASURED triggers, where higher is worse: past the
    # configured limit (thresholds.yaml, A4 and A5) is already a finding.
    _SEVERE_ABOVE = {
        "misfire_rate": 0.05,
        "bearing_envelope_x": 5.0,
    }

    def _schedule(
        self,
        action_id: str,
        chi: float,
        rul_hours: float | None,
        evidence: dict[str, float] | None = None,
    ) -> tuple[str, float | None]:
        """When the work must happen.

        The composite health band sets the baseline, but the ACTION'S OWN
        evidence can override it. Grading only on the composite is the same
        dilution DEV-45 found at end-of-life and DEV-72 in the advisory,
        arriving a third time: measured here, an engine whose oil quality had
        fallen to 0.00 was told to change the oil "at the next scheduled
        maintenance", because three healthy subsystems held the composite above
        0.80. A job is as urgent as the thing that triggered it.

        The deadline is bounded by remaining life: recommending work "within
        50 hours" on an engine with 12 hours left is not a schedule, it is a
        contradiction.
        """
        if action_id == "A7":
            return "EMERGENCY", 0.0

        # A measured finding past its grounding band is an emergency on its
        # own, whatever the composite says (SAF-06).
        for name, band in self._GROUND_ABOVE.items():
            v = (evidence or {}).get(name)
            if v is not None and band is not None and v >= float(band):
                return "EMERGENCY", 0.0

        if chi < 0.50:
            severity, due = "WARNING", 10.0
        elif chi < 0.60:
            severity, due = "WARNING", 10.0
        elif chi < 0.70:
            severity, due = "CAUTION", 25.0
        elif chi < 0.80:
            severity, due = "CAUTION", 50.0
        else:
            severity, due = "ADVISORY", None

        # The action's own evidence can escalate past what the composite says.
        for name, floor in self._SEVERE_EVIDENCE.items():
            v = (evidence or {}).get(name)
            if v is not None and v <= floor:
                if _SEVERITY_RANK["CAUTION"] > _SEVERITY_RANK[severity]:
                    severity = "CAUTION"
                due = min(due if due is not None else 25.0, 25.0)
                # Well past the floor is not merely a caution.
                if v <= floor * 0.5:
                    severity = "WARNING"
                    due = min(due, 10.0)
                # No `break`: with every trigger's evidence now kept, the
                # schedule must follow the WORST of them, not the first.

        # A measured limit already crossed is at least a caution inside 25 h,
        # and at twice the limit a warning inside 10 h -- the mirror of the
        # floors above. Left to the composite, a bearing measured past its
        # limit was scheduled "at the next scheduled maintenance".
        for name, limit in self._SEVERE_ABOVE.items():
            v = (evidence or {}).get(name)
            if v is not None and v >= limit:
                if _SEVERITY_RANK["CAUTION"] > _SEVERITY_RANK[severity]:
                    severity = "CAUTION"
                due = min(due if due is not None else 25.0, 25.0)
                if v >= 2.0 * limit:
                    severity = "WARNING"
                    due = min(due, 10.0)

        if rul_hours is not None and due is not None:
            due = min(due, max(rul_hours, 0.0))
        elif rul_hours is not None and due is None and rul_hours < 100.0:
            severity, due = "CAUTION", rul_hours
        return severity, due

    def _summarise(self, plan: MaintenancePlan, chi: float) -> str:
        """The line a planner reads first."""
        if not plan.actions:
            # With no component trigger, the health BAND still carries an
            # instruction, and the advisory must say the same thing as the band
            # the console shows beside it (SAF-10). Health 0.55 used to read
            # "DEGRADED -- maintain within 10 h" on one panel and "No configured
            # trigger has fired" on this one.
            band = _band_for(chi)
            if band and band.get("action") not in (None, "none", "monitor"):
                return (f"Health {band['label']} ({chi:.2f}): "
                        f"{band['instruction']} No component-specific trigger "
                        f"has fired -- inspect the limiting subsystem.")
            return (
                "No maintenance action indicated. Continue monitoring."
                if chi >= 0.80
                else "No configured trigger has fired; monitor the health trend."
            )
        if plan.grounding_required:
            return (
                f"GROUND THE AIRCRAFT. {len(plan.actions)} action(s), "
                f"Rs {plan.total_cost_inr:,.0f}, "
                f"{plan.total_downtime_hours:.1f} h down."
            )
        first = plan.actions[0]
        when = (
            f"within {first.due_within_hours:.0f} flight hours"
            if first.due_within_hours is not None
            else "at the next scheduled maintenance"
        )
        return (
            f"{len(plan.actions)} action(s) indicated. Most urgent: "
            f"{first.name} {when} ({first.reason}). "
            f"Total Rs {plan.total_cost_inr:,.0f}, "
            f"{plan.total_downtime_hours:.1f} h down."
        )


__all__ = ["AdvisoryEngine", "MaintenanceAction", "MaintenancePlan"]
