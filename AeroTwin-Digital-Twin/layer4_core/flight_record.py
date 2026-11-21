"""What a post-flight report is actually made of.

The report this system produced was a snapshot with a title: the health indices
and worst-ever extremes as they stood at the moment somebody pressed export.
That is not a post-flight report, and two things from real practice were
missing entirely.

THE PFR STRUCTURE: EVENTS CARRY A TIME AND A FLIGHT PHASE
----------------------------------------------------------
An Airbus Post Flight Report lists each warning and fault message "with the
associated time, flight phase and ATA reference", and that is what makes it
usable on the ramp: a maintainer reading "EGT high" learns almost nothing, and
a maintainer reading "EGT high, 04:12, CLIMB, ATA 77" knows where to look and
what the engine was being asked to do at the time.

Our alerts existed only as a LIVE list. An alert that fired during the climb
and cleared in the cruise left no trace at all in the report, which meant the
report was systematically blind to exactly the transient events a debrief
exists to discuss.

THE ECTM DATUM: ONE STABILISED CRUISE POINT PER FLIGHT
-------------------------------------------------------
Engine Condition Trend Monitoring works by recording the same parameters at the
same condition, once per flight, and watching the numbers move over months. The
recording is taken "after the aircraft has been flying at a stable cruise
condition for several minutes" -- the stability is the whole point, because a
parameter read during a climb is a measurement of the climb.

Without that datum a report has extremes and instantaneous values, and neither
can be trended: the peak CHT of a flight depends on how hard it was flown, and
the value at export depends on when somebody pressed the button. The stabilised
cruise point is the only row in a flight that is comparable with the same row
from the flight before.

So this module watches for stability and captures ONE datum per flight, and
declines to capture anything if the flight never stabilised -- a sortie of
continuous manoeuvring has no valid ECTM point, and inventing one by averaging
the whole flight would produce a number that trends against nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# The phase codes engine_sim uses. CRUISE is the only one an ECTM datum may be
# taken in; the others are by definition not stable.
PHASE_NAMES = ("GROUND", "STARTUP", "TAXI", "TAKE-OFF",
               "CLIMB", "CRUISE", "DESCENT", "LANDING")
PHASE_CRUISE = 5


def phase_name(code: int | None) -> str:
    if code is None or not (0 <= int(code) < len(PHASE_NAMES)):
        return "UNKNOWN"
    return PHASE_NAMES[int(code)]


@dataclass
class Event:
    """One alert, with what the engine was doing when it happened.

    ``cleared_s`` is None while the alert is still standing. A report that only
    lists what is active at export time hides every transient, which is the
    class of event a debrief is mostly about.
    """

    t_s: float
    phase: str
    level: int
    legend: str
    advisory: str = ""
    ata: str = ""
    cleared_s: float | None = None

    @property
    def duration_s(self) -> float | None:
        return None if self.cleared_s is None else self.cleared_s - self.t_s

    def as_dict(self) -> dict:
        return {
            "t_s": round(self.t_s, 1),
            "phase": self.phase,
            "level": self.level,
            "legend": self.legend,
            "advisory": self.advisory,
            "ata": self.ata,
            "cleared_s": (None if self.cleared_s is None
                          else round(self.cleared_s, 1)),
            "duration_s": (None if self.duration_s is None
                           else round(self.duration_s, 1)),
            "standing": self.cleared_s is None,
        }


@dataclass
class Exceedance:
    """A limit that was crossed, with how far and for how long.

    Peak alone understates a slow cook and overstates a spike. Maintenance
    manuals set inspection thresholds on BOTH -- an over-temperature for two
    seconds and the same peak sustained for four minutes are different findings
    with different actions -- so both are carried.
    """

    parameter: str
    unit: str
    limit: float
    peak: float = 0.0
    seconds_above: float = 0.0
    first_t_s: float | None = None
    phase: str = ""
    # CAP 739 grades every event 1 (minor) to 3 (major) against SEPARATE
    # limits, and it is the grade -- not the raw excess -- that decides whether
    # anybody is woken up. Carried as configured level limits rather than
    # derived from a percentage, because the step from "note it" to "ground the
    # aircraft" is a maintenance-manual decision, not an arithmetic one.
    level_limits: tuple[float, float, float] | None = None
    minimum: bool = False

    @property
    def severity(self) -> int:
        """1, 2 or 3. Falls back to 1 when no level limits were configured."""
        if not self.level_limits:
            return 1
        worst = 1
        for i, lim in enumerate(self.level_limits, start=1):
            crossed = self.peak < lim if self.minimum else self.peak > lim
            if crossed:
                worst = i
        return worst

    def as_dict(self) -> dict:
        return {
            "parameter": self.parameter, "unit": self.unit,
            "limit": round(self.limit, 1), "peak": round(self.peak, 1),
            "seconds_above": round(self.seconds_above, 1),
            "first_t_s": (None if self.first_t_s is None
                          else round(self.first_t_s, 1)),
            "phase": self.phase,
            "over_by": round(abs(self.peak - self.limit), 1),
            "severity": self.severity,
            # Which side of the limit: a minimum is breached by going under.
            "minimum": self.minimum,
        }


@dataclass
class CruiseDatum:
    """The one stabilised cruise reading a flight contributes to the trend."""

    t_s: float = 0.0
    altitude_ft: float | None = None
    oat_c: float | None = None
    airspeed_kmh: float | None = None
    throttle_pct: float | None = None
    rpm: float | None = None
    manifold_pressure_bar: float | None = None
    cht_max_c: float | None = None
    cht_spread_c: float | None = None
    egt_max_c: float | None = None
    egt_spread_c: float | None = None
    oil_pressure_psi: float | None = None
    oil_temperature_c: float | None = None
    coolant_temperature_c: float | None = None
    fuel_flow_lph: float | None = None
    power_kw: float | None = None
    # How long the engine had been stable when the reading was taken.
    stable_for_s: float = 0.0

    def as_dict(self) -> dict:
        def r(v, n=1):
            return None if v is None else round(float(v), n)

        return {
            "t_s": round(self.t_s, 1),
            "altitude_ft": r(self.altitude_ft, 0),
            "oat_c": r(self.oat_c),
            "airspeed_kmh": r(self.airspeed_kmh, 0),
            "throttle_pct": r(self.throttle_pct),
            "rpm": r(self.rpm, 0),
            "manifold_pressure_bar": r(self.manifold_pressure_bar, 3),
            "cht_max_c": r(self.cht_max_c),
            "cht_spread_c": r(self.cht_spread_c),
            "egt_max_c": r(self.egt_max_c, 0),
            "egt_spread_c": r(self.egt_spread_c, 0),
            "oil_pressure_psi": r(self.oil_pressure_psi),
            "oil_temperature_c": r(self.oil_temperature_c),
            "coolant_temperature_c": r(self.coolant_temperature_c),
            "fuel_flow_lph": r(self.fuel_flow_lph, 2),
            "power_kw": r(self.power_kw),
            "stable_for_s": round(self.stable_for_s, 1),
        }


# ATA chapter per parameter. A maintainer looks work up by chapter, so a report
# that names the parameter without the chapter has left the lookup to them.
#
# Numbers and titles are from the FAA Joint Aircraft System/Component code
# table (JASC), which is derived from ATA Spec 100 and is public
# (sdrs.faa.gov/documents/JASC_Code.pdf). That table splits the engine chapter
# by engine type: 72 is "Engine (Turbine/Turboprop)" and 85 is "Engine
# (Reciprocating)", whose 8530 is the cylinder section. The 915 iS is a piston
# engine, so work on the engine itself files under 85. It used to file under
# 72, the turbine chapter, which sends a maintainer to the wrong part of the
# manual. The same table puts engine cooling at 7520 and the exhaust
# turbocharger at 8120.
ENGINE_CHAPTER = "85 Engine (reciprocating)"

ATA = {
    "rpm": "77 Engine indicating",
    "cht": ENGINE_CHAPTER,
    "coolant": "75 Engine cooling",
    "egt": "77 Engine indicating",
    "oil_pressure": "79 Oil",
    "oil_temperature": "79 Oil",
    "fuel_flow": "73 Engine fuel and control",
    "vibration": ENGINE_CHAPTER,
    "electrical": "24 Electrical power",
    "timing": "73 Engine fuel and control",
    # "IGN RETARD HIGH", matched on its second word: "ign" alone is inside
    # "signal".
    "retard": "74 Ignition",
}


# ATA 100 chapter by RULE ID prefix, checked before the legend (REP-04).
# Matching on legend text sent "IGN TIMING DEV" to 73 (because "timing" matched
# first), "MISFIRE SUSPECTED" and "SENSOR FAULT" to the engine chapter, and
# mapped "electrical" to 74 Ignition. Electrical power is chapter 24; a
# turbocharger on a reciprocating engine is chapter 81.
RULE_ATA: tuple[tuple[str, str], ...] = (
    ("IGN", "74 Ignition"),
    ("MISFIRE", "74 Ignition"),
    ("KNOCK", "74 Ignition"),
    ("INJ", "73 Engine fuel and control"),
    ("FUEL", "73 Engine fuel and control"),
    ("OIL", "79 Oil"),
    ("COOL", "75 Engine cooling"),
    ("CHT", ENGINE_CHAPTER),
    ("EGT", "77 Engine indicating"),
    ("RPM", "77 Engine indicating"),
    ("VIB", ENGINE_CHAPTER),
    ("MAP", "81 Exhaust turbocharger"),
    ("BOOST", "81 Exhaust turbocharger"),
    ("TURBO", "81 Exhaust turbocharger"),
    ("BUS", "24 Electrical power"),
    ("BATT", "24 Electrical power"),
    ("VOLT", "24 Electrical power"),
    ("SENSOR", "77 Engine indicating"),
    ("DATA", "77 Engine indicating"),
)


def ata_for(legend: str, rule_id: str | None = None) -> str:
    """ATA chapter for an alert: by rule id when there is one, else legend."""
    rid = (rule_id or "").upper()
    for prefix, chapter in RULE_ATA:
        if rid.startswith(prefix):
            return chapter
    low = legend.lower()
    for key, chapter in ATA.items():
        if key.split("_")[0] in low:
            return chapter
    return ENGINE_CHAPTER


class FlightRecord:
    """Accumulates what a post-flight report needs, over the whole flight."""

    def __init__(
        self,
        *,
        stable_seconds: float = 120.0,
        throttle_band_pct: float = 2.0,
        altitude_band_ft: float = 300.0,
        mcp_pct: float = 92.0,
        throttle_step_pct: float = 15.0,
    ) -> None:
        # Above maximum continuous power an engine is on a clock, not a
        # rating. The manufacturer's five-minute take-off allowance is the
        # usual shape of that, so time spent there is counted separately from
        # time spent flying.
        self.mcp_pct = mcp_pct
        # "Rapid throttle transitions" is named in the problem statement as a
        # condition to handle. A step of this size between consecutive ticks is
        # a slam, not a trim.
        self.throttle_step_pct = throttle_step_pct
        # "Several minutes" in the ECTM guidance. Two is the shortest window
        # over which this engine's thermal states actually settle -- shorter and
        # the datum records the approach to cruise rather than cruise.
        self.stable_seconds = stable_seconds
        self.throttle_band_pct = throttle_band_pct
        self.altitude_band_ft = altitude_band_ft

        self.events: list[Event] = []
        self.exceedances: dict[str, Exceedance] = {}
        self.cruise: CruiseDatum | None = None
        self.phases_flown: list[str] = []

        # ADS-79's regime recognition, in the only form this data supports.
        # Hours alone do not describe a life: two engines with identical hours
        # have not lived identical lives if one spent them at maximum
        # continuous power, and only a per-phase accounting can tell them
        # apart.
        self.phase_seconds: dict[str, float] = {}
        self.seconds_above_mcp = 0.0
        self.throttle_transitions = 0

        # What the report could NOT see. A document silent about a dead
        # channel reads as a clean bill of health, which is worse than saying
        # nothing at all -- so coverage is accumulated alongside the findings
        # and printed whether or not anything went wrong.
        self.ticks = 0
        self.recorded_seconds = 0.0
        self.gaps: list[tuple[float, float]] = []
        self.invalid_channels: set[str] = set()
        self._seen_channels: set[str] = set()

        # Actual against the twin's own prediction, averaged over the flight.
        # This is the one number that makes the document a DIGITAL TWIN report
        # rather than a general engine log.
        self._twin: dict[str, list[float]] = {}

        # Environment over the WHOLE sortie. The live series is a ring buffer
        # holding the last few minutes, so summarising the environment from it
        # reports the conditions at the moment of export -- on an eighteen-hour
        # endurance flight that is the descent, and it would print a 5 C
        # temperature range for a sortie that spanned 65 C.
        self._env: dict[str, list[float]] = {}

        self._open: dict[str, Event] = {}
        self._stable_since: float | None = None
        self._ref_throttle: float | None = None
        self._ref_altitude: float | None = None
        self._last_t: float | None = None
        self._last_throttle: float | None = None

    # ------------------------------------------------------------------
    def observe_alerts(self, t_s: float, phase: int | None,
                       active: list[dict]) -> None:
        """Open an event when an alert appears, close it when it goes.

        Keyed by rule id, so the same rule firing twice in a flight is two
        events with two durations rather than one smeared across the gap.
        """
        seen = set()
        for a in active:
            rid = str(a.get("rule_id") or a.get("legend", ""))
            seen.add(rid)
            if rid not in self._open:
                ev = Event(
                    t_s=t_s, phase=phase_name(phase),
                    level=int(a.get("level", 0)),
                    legend=str(a.get("legend", "")),
                    advisory=str(a.get("advisory", "")),
                    ata=ata_for(str(a.get("legend", "")), a.get("rule_id")),
                )
                self._open[rid] = ev
                self.events.append(ev)
        for rid in list(self._open):
            if rid not in seen:
                self._open.pop(rid).cleared_s = t_s

    def observe_exceedance(self, t_s: float, phase: int | None, *,
                           parameter: str, value: float | None,
                           limit: float, unit: str, dt: float,
                           minimum: bool = False,
                           level_limits: tuple[float, float, float] | None = None,
                           ) -> None:
        """Accumulate peak AND time-above for one limited parameter."""
        if value is None:
            return
        over = value < limit if minimum else value > limit
        if not over:
            return
        # One record per LIMIT, not per parameter (REP-03). The oil-pressure
        # minimum is 29 psi above 3500 rpm and 11.6 psi below it; accumulated
        # under the first limit seen, a 10 psi idle reading was reported as
        # 19 psi beyond a 29 psi limit when the real shortfall was 1.6 psi.
        key = parameter
        e = self.exceedances.get(key)
        if e is not None and e.limit != limit:
            key = f"{parameter}@{limit:g}"
            e = self.exceedances.get(key)
        if e is None:
            e = Exceedance(parameter=parameter, unit=unit, limit=limit,
                           peak=value, first_t_s=t_s, phase=phase_name(phase),
                           level_limits=level_limits, minimum=minimum)
            self.exceedances[key] = e
        e.peak = min(e.peak, value) if minimum else max(e.peak, value)
        e.seconds_above += dt

    def observe_phase(self, phase: int | None) -> None:
        name = phase_name(phase)
        if not self.phases_flown or self.phases_flown[-1] != name:
            self.phases_flown.append(name)

    # ------------------------------------------------------------------
    def observe_tick(self, t_s: float, phase: int | None, dt: float, *,
                     throttle_pct: float | None = None,
                     power_pct: float | None = None) -> None:
        """Usage accounting for one tick: which regime, and how hard.

        Separate from `observe_phase` because that one records the SEQUENCE of
        phases and this one records the DURATION of each, and a sortie that
        dips into a phase for four seconds should appear in one and barely
        register in the other.

        A gap is inferred rather than reported: if the clock jumped further
        than the tick interval, the recording lost that stretch, and the report
        must say so instead of quietly interpolating across it.
        """
        if self._last_t is not None:
            jump = t_s - self._last_t
            # Twice the nominal tick is the smallest gap that cannot be
            # explained by ordinary scheduling jitter.
            if jump > max(dt * 2.0, dt + 1.0):
                self.gaps.append((self._last_t, t_s))
            else:
                self.recorded_seconds += jump
        self._last_t = t_s
        self.ticks += 1

        self.observe_phase(phase)
        name = phase_name(phase)
        self.phase_seconds[name] = self.phase_seconds.get(name, 0.0) + dt

        if power_pct is not None and power_pct > self.mcp_pct:
            self.seconds_above_mcp += dt

        if throttle_pct is not None:
            if (self._last_throttle is not None
                    and abs(throttle_pct - self._last_throttle)
                    >= self.throttle_step_pct):
                self.throttle_transitions += 1
            self._last_throttle = throttle_pct

    def observe_environment(self, **channels: float | None) -> None:
        """Accumulate min/mean/max of each condition across the whole flight."""
        for name, value in channels.items():
            if value is None:
                continue
            acc = self._env.setdefault(name, [0.0, 0.0, float("inf"),
                                              float("-inf")])
            acc[0] += float(value)
            acc[1] += 1.0
            acc[2] = min(acc[2], float(value))
            acc[3] = max(acc[3], float(value))

    def environment(self) -> dict:
        """What was measured, and nothing for what was not."""
        out = {}
        for name, (total, count, lo, hi) in self._env.items():
            if count <= 0:
                continue
            out[name] = {"avg": round(total / count, 1),
                         "min": round(lo, 1), "max": round(hi, 1)}
        return out

    def observe_channel(self, name: str, value: Any) -> None:
        """Record a channel as unusable when it never produces a reading.

        Called per tick with whatever the bus offered. A channel is only
        declared invalid at report time, when it has been absent for the whole
        flight -- one dropped sample is noise, a silent flight is a dead
        sensor.
        """
        if value is not None:
            self.invalid_channels.discard(name)
            self._seen_channels.add(name)
        elif name not in self._seen_channels:
            self.invalid_channels.add(name)

    def observe_twin(self, actual: dict[str, float | None],
                     twin: dict[str, float | None]) -> None:
        """Running means of the real engine and the twin's prediction of it."""
        for k, a in actual.items():
            t = twin.get(k)
            if a is None or t is None:
                continue
            acc = self._twin.setdefault(k, [0.0, 0.0, 0.0])
            acc[0] += float(a)
            acc[1] += float(t)
            acc[2] += 1.0

    def twin_comparison(self) -> list[dict]:
        """Actual vs twin, averaged, with the deviation that matters."""
        out = []
        for k, (sa, st, n) in sorted(self._twin.items()):
            if n <= 0:
                continue
            a, t = sa / n, st / n
            # Percentage of the ACTUAL, so a deviation reads as "the twin was
            # this far out", which is the direction a reader cares about.
            dev = abs(a - t) / abs(a) * 100.0 if a else 0.0
            out.append({"parameter": k, "actual": round(a, 2),
                        "twin": round(t, 2), "deviation_pct": round(dev, 2),
                        "samples": int(n)})
        return out

    # ------------------------------------------------------------------
    def observe_cruise(self, t_s: float, phase: int | None, *,
                       throttle_pct: float | None,
                       altitude_ft: float | None,
                       sample: dict) -> None:
        """Capture ONE stabilised cruise datum, the first time stability holds.

        Only the FIRST is kept. A later one would be a different operating
        point -- fuel burnt off, the engine warmer -- and the value of the datum
        comes from being taken the same way every flight, not from being the
        most recent thing available.
        """
        if self.cruise is not None:
            return
        if phase != PHASE_CRUISE or throttle_pct is None or altitude_ft is None:
            self._stable_since = None
            return

        moved = (
            self._ref_throttle is None
            or abs(throttle_pct - self._ref_throttle) > self.throttle_band_pct
            or abs(altitude_ft - (self._ref_altitude or 0.0)) > self.altitude_band_ft
        )
        if moved:
            # The reference resets to HERE rather than to the flight's start:
            # a throttle change begins a new stable period, it does not
            # disqualify the rest of the cruise.
            self._ref_throttle = throttle_pct
            self._ref_altitude = altitude_ft
            self._stable_since = t_s
            return

        if self._stable_since is None:
            self._stable_since = t_s
            return

        held = t_s - self._stable_since
        if held >= self.stable_seconds:
            self.cruise = CruiseDatum(t_s=t_s, stable_for_s=held, **sample)

    # ------------------------------------------------------------------
    def as_dict(self) -> dict:
        return {
            "events": [e.as_dict() for e in self.events],
            "exceedances": [e.as_dict() for e in self.exceedances.values()],
            "cruise_datum": None if self.cruise is None else self.cruise.as_dict(),
            "phases_flown": list(self.phases_flown),
            # Stated explicitly rather than left to be inferred from a null.
            # "No valid ECTM point" is a finding about the sortie, not a gap in
            # the report.
            "cruise_reason": (
                "" if self.cruise is not None
                else f"no cruise segment held within +/-{self.throttle_band_pct:.0f} % "
                     f"throttle and +/-{self.altitude_band_ft:.0f} ft for "
                     f"{self.stable_seconds:.0f} s"
            ),
            "usage": self.usage(),
            "environment": self.environment(),
            "data_quality": self.data_quality(),
            "twin_vs_actual": self.twin_comparison(),
        }

    # ------------------------------------------------------------------
    def usage(self) -> dict:
        """Time per regime, plus the two counts that turn hours into a life."""
        total = sum(self.phase_seconds.values())
        rows = [
            {"phase": name,
             "seconds": round(secs, 1),
             "hours": round(secs / 3600.0, 2),
             "pct": round(secs / total * 100.0, 1) if total else 0.0}
            for name, secs in sorted(
                self.phase_seconds.items(), key=lambda kv: -kv[1])
        ]
        return {
            "phases": rows,
            "total_seconds": round(total, 1),
            "hours_above_mcp": round(self.seconds_above_mcp / 3600.0, 2),
            "mcp_pct": self.mcp_pct,
            "throttle_transitions": self.throttle_transitions,
            "throttle_step_pct": self.throttle_step_pct,
        }

    def data_quality(self) -> dict:
        """Coverage, gaps and dead channels -- what the report could not see.

        `coverage_pct` is deliberately computed against wall-clock span rather
        than against an expected tick count: a recorder that stopped for two
        minutes and one that ran slow for two minutes are different faults, and
        only the span notices the first.
        """
        gap_s = sum(b - a for a, b in self.gaps)
        span = self.recorded_seconds + gap_s
        return {
            "ticks": self.ticks,
            "recorded_seconds": round(self.recorded_seconds, 1),
            "gap_seconds": round(gap_s, 1),
            "gaps": [{"from_s": round(a, 1), "to_s": round(b, 1),
                      "seconds": round(b - a, 1)} for a, b in self.gaps],
            "coverage_pct": (round(self.recorded_seconds / span * 100.0, 1)
                             if span else 100.0),
            "invalid_channels": sorted(self.invalid_channels),
            "cruise_datum_captured": self.cruise is not None,
        }


__all__ = ["ATA", "CruiseDatum", "Event", "Exceedance", "FlightRecord",
           "PHASE_NAMES", "ata_for", "phase_name"]
