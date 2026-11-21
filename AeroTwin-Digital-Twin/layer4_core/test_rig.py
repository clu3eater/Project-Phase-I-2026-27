"""Engine test-rig mode -- the third deployment context, gap G2.

The problem statement asks for a framework designed for "defence grade Ground
Control Station (GCS), **engine test rigs**, and fleet-level health monitoring
infrastructures". The console covers the first, mission reliability and the
fleet view the third. This is the second: an engine on a stand rather than in
an airframe, run to a scripted schedule and judged against its certified
ratings.

It is the context in which an engine is accepted after overhaul, and it is
where a digital twin earns its keep differently -- not by predicting a failure
in flight, but by saying whether the engine that just came off the bench meets
the numbers on its type certificate.

A TEST CELL IS NOT AN AIRCRAFT STANDING STILL
---------------------------------------------
The tempting model is "the flight case with airspeed set to zero". It predicts
a destroyed engine. Measured on this model at 95 % throttle:

    in flight, 200 km/h        CHT 114.9 C   coolant  95.6 C
    test cell, 45 km/h fan     CHT 239.4 C   coolant 203.3 C
    test cell, no fan          CHT 265.2 C   coolant 206.9 C

against a certified coolant limit of 120 C. A real cell does not rely on ram
air at all: it has a dedicated fan or a liquid-to-liquid exchanger on the
coolant circuit, frequently giving BETTER cooling than flight. Modelling the
cell as a slow aircraft would fail every acceptance test -- on the facility,
not on the engine -- and an operator would spend a week chasing a cooling fault
that does not exist.

So cell cooling is an explicit property of the rig, and the acceptance report
says whether the CELL was the limiting factor. Distinguishing "this engine
failed" from "this test was invalid" is the whole reason to state it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from common import config
from layer2_physics import mvem
from layer2_physics.atmosphere import ambient_at
from layer2_physics.degradation import DegradationFactors


@dataclass
class TestPoint:
    """One dwell in a test schedule.

    ``target_rpm`` engages the dynamometer. Every rating on a type certificate
    is quoted AT A SPEED -- "99 kW at 5500 rpm" -- so a bench that lets the
    engine free-run to wherever the throttle puts it is not measuring the rated
    point. Measured on the first run of this schedule: 92 % throttle settled at
    5742 rpm and made 100.9 kW, which was recorded as a pass against the 99 kW
    max-continuous rating. It is not one. It is a different rating, at a speed
    242 rpm above the one the certificate names.

    A real cell holds speed with a dyno and reads torque. With a target set,
    the rig trims the absorbed load to hold it and reports the torque.
    """

    # Not a pytest class, despite the name: these are domain objects for an
    # engine test rig. Without this pytest emits a collection warning for
    # every one of them.
    __test__ = False

    name: str
    throttle_pct: float
    duration_s: float
    settle_s: float = 30.0
    target_rpm: float | None = None
    # Time limit the certificate places on this rating, if any. The rig refuses
    # to run a schedule that would itself breach the certificate.
    max_duration_s: float | None = None


@dataclass
class TestSchedule:
    """A named acceptance or investigation run."""

    # Not a pytest class, despite the name: these are domain objects for an
    # engine test rig. Without this pytest emits a collection warning for
    # every one of them.
    __test__ = False

    name: str
    points: list[TestPoint]
    description: str = ""

    @property
    def duration_s(self) -> float:
        return sum(p.duration_s + p.settle_s for p in self.points)


def acceptance_schedule() -> TestSchedule:
    """Post-overhaul acceptance, following the shape of a real ground run.

    Warm-up first because every limit in the type certificate assumes a warm
    engine, then a power sweep, then a dwell at each certified rating on the
    dyno, then a cool-down.

    The two rating points are speed-targeted at the speeds the certificate
    names -- 5500 rpm for max continuous, 5800 rpm for take-off -- because a
    power figure without its speed is not the rating.

    The take-off point is bounded by the certificate's own five-minute limit
    [TCDS s6, ratings.max_power_time_limit_min]. Settling counts against it:
    the engine does not know the difference between a settling minute and a
    recorded one.
    """
    return TestSchedule(
        name="ACCEPTANCE",
        description="post-overhaul acceptance against the type certificate",
        points=[
            TestPoint("WARM-UP", 25.0, 300.0, settle_s=0.0),
            TestPoint("IDLE", 15.0, 60.0, target_rpm=1800.0),
            TestPoint("SWEEP 40%", 40.0, 60.0),
            TestPoint("SWEEP 60%", 60.0, 60.0),
            TestPoint("SWEEP 80%", 80.0, 60.0),
            TestPoint("MAX CONTINUOUS", 95.0, 300.0, settle_s=60.0,
                      target_rpm=5500.0),
            TestPoint("TAKE-OFF", 100.0, 240.0, settle_s=45.0,
                      target_rpm=5800.0, max_duration_s=300.0),
            TestPoint("COOL-DOWN", 20.0, 120.0, settle_s=0.0),
        ],
    )


def endurance_schedule(hours: float = 2.0) -> TestSchedule:
    return TestSchedule(
        name="ENDURANCE",
        description="sustained max-continuous running",
        points=[
            TestPoint("WARM-UP", 25.0, 300.0, settle_s=0.0),
            TestPoint("MAX CONTINUOUS", 95.0, hours * 3600.0, settle_s=60.0,
                      target_rpm=5500.0),
            TestPoint("COOL-DOWN", 20.0, 120.0, settle_s=0.0),
        ],
    )


def throttle_response_schedule() -> TestSchedule:
    """Rapid transitions -- PS section E names them explicitly."""
    pts = [TestPoint("WARM-UP", 25.0, 300.0, settle_s=0.0)]
    for i in range(4):
        pts.append(TestPoint(f"SLAM OPEN {i+1}", 95.0, 20.0, settle_s=0.0))
        pts.append(TestPoint(f"SLAM CLOSED {i+1}", 20.0, 20.0, settle_s=0.0))
    pts.append(TestPoint("COOL-DOWN", 20.0, 60.0, settle_s=0.0))
    return TestSchedule("THROTTLE RESPONSE", pts,
                        "rapid throttle transitions (PS section E)")


SCHEDULES = {
    "acceptance": acceptance_schedule,
    "endurance": endurance_schedule,
    "throttle": throttle_response_schedule,
}


# ---------------------------------------------------------------------------


@dataclass
class PointResult:
    """What the engine did at one test point."""

    name: str
    throttle_pct: float
    rpm: float = 0.0
    power_kw: float = 0.0
    torque_nm: float = 0.0
    cht_max_c: float = 0.0
    coolant_c: float = 0.0
    egt_max_c: float = 0.0
    egt_spread_c: float = 0.0
    oil_pressure_psi: float = 0.0
    oil_temperature_c: float = 0.0
    fuel_flow_lph: float = 0.0
    bsfc_g_per_kwh: float = 0.0
    vibration_rms: float = 0.0
    # Dyno state. ``load_saturated`` means the absorber ran out of authority
    # and the speed was NOT held -- the point is then not the rated point and
    # any power read off it is meaningless.
    # Time from the start of the dwell to reaching 95 % of the speed the point
    # settles at. Only meaningful on a step change, so it is None elsewhere.
    response_time_s: float | None = None
    target_rpm: float | None = None
    load_factor: float = 1.0
    rpm_error: float = 0.0
    load_saturated: bool = False
    # How much of the airframe's cooling-air travel the engine needed to hold
    # its temperatures, 0-1. A radiator losing capacity spends this long before
    # it shows as temperature, so a cell that cannot overheat the engine can
    # still measure the loss.
    cooling_flap_fraction: float = 0.0
    oil_flap_fraction: float = 0.0
    # The turbocharger's own authority. A worn compressor holds boost by
    # closing the wastegate, so it costs no power until the wastegate is shut:
    # the manufacturer's table shows power is nearly independent of charge
    # temperature at a held plenum pressure (105.0 kW at -24.6 C against
    # 104.0 kW at +44.2 C, same 1.5 bar). Spent travel is the early signal.
    wastegate_fraction: float = 1.0
    exceedances: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: (round(v, 2) if isinstance(v, float) else v)
                for k, v in self.__dict__.items()}


@dataclass
class AcceptanceReport:
    """Pass or fail, and on what evidence."""

    schedule: str
    engine_key: str
    passed: bool = False
    points: list[PointResult] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    cell_limited: bool = False
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "schedule": self.schedule,
            "engine": self.engine_key,
            "passed": self.passed,
            "cell_limited": self.cell_limited,
            "points": [p.as_dict() for p in self.points],
            "checks": self.checks,
            "notes": self.notes,
        }


class TestRig:
    """An engine on a stand, run to a schedule and judged against its ratings.

    No air-data bus: an engine on a bench has no altitude, no airspeed and no
    vehicle management computer. Ambient comes from the cell instead, which is
    also the honest deployment difference -- the twin's shadow model is driven
    by the operating point, and on a rig that operating point is supplied by
    the facility rather than by an aircraft.
    """

    # Dynamometer authority. A water-brake or eddy-current absorber on a stand
    # this size can take well over the engine's own output, but it cannot take
    # less than the driveline's own drag -- hence a floor rather than zero.
    __test__ = False  # a rig, not a pytest class

    LOAD_MIN = 0.15
    LOAD_MAX = 4.0

    def __init__(
        self,
        engine_key: str = "rotax_915is",
        *,
        cell_temperature_c: float = 25.0,
        cell_elevation_ft: float = 500.0,
        # Cooling the cell provides, expressed as the airspeed that would give
        # the same radiator conductance. A real cell's fan or exchanger is
        # sized to hold the engine in limits at full power; 200 km/h-equivalent
        # is representative. It is a PROPERTY OF THE FACILITY and is reported,
        # because a cell that cannot cool invalidates the test.
        cell_cooling_kmh: float = 200.0,
        seed: int = 0,
    ) -> None:
        self.engine_key = engine_key
        self.engine = config.load_engine(engine_key)
        self.cell_temperature_c = cell_temperature_c
        self.cell_elevation_ft = cell_elevation_ft
        self.cell_cooling_kmh = cell_cooling_kmh
        self.seed = seed
        self.rng = np.random.default_rng(seed)

    # ------------------------------------------------------------------
    def _ambient(self):
        from layer2_physics.atmosphere import air_density
        from dataclasses import replace as dc_replace

        amb = ambient_at(
            self.cell_elevation_ft, humidity_pct=40.0,
            airspeed_kmh=self.cell_cooling_kmh,
        )
        rho = air_density(amb.pressure_pa, self.cell_temperature_c + 273.15, 40.0)
        return dc_replace(amb, oat_c=self.cell_temperature_c, density_kg_m3=rho)

    def _tick(self, model, pt: TestPoint, amb, dt: float, load: float):
        """One step, trimming the dynamometer to hold the point's speed.

        Proportional load trim. The absorber takes more torque when the engine
        runs fast and less when it runs slow; prop torque goes as omega^2, so a
        fractional correction on the load factor is well conditioned.
        """
        out = model.step(dt, throttle_pct=pt.throttle_pct, ambient=amb,
                         load_factor=load)
        if pt.target_rpm is not None:
            err = (out.rpm - pt.target_rpm) / pt.target_rpm
            load = float(np.clip(load * (1.0 + 0.35 * err),
                                 self.LOAD_MIN, self.LOAD_MAX))
        return out, load

    def validate(self, schedule: TestSchedule) -> None:
        """Refuse a schedule that would itself breach the certificate.

        The take-off rating carries a five-minute limit. A schedule that
        settles for 45 s and then records for 300 s runs the engine at that
        rating for 345 s -- the engine does not distinguish settling time from
        recorded time. Catching it here rather than in the report matters:
        by the time it appears as an exceedance the engine has already been
        over-run.
        """
        for pt in schedule.points:
            if pt.max_duration_s is None:
                continue
            total = pt.settle_s + pt.duration_s
            if total > pt.max_duration_s:
                raise ValueError(
                    f"test point {pt.name!r} would hold a time-limited rating "
                    f"for {total:.0f} s against a {pt.max_duration_s:.0f} s "
                    f"certificate limit -- shorten the dwell or the settle"
                )

    def run(
        self, schedule: TestSchedule, *, degradation: DegradationFactors | None = None,
        dt: float = 0.5,
    ) -> AcceptanceReport:
        """Run the schedule and judge the result."""
        self.validate(schedule)

        model = mvem.MeanValueEngineModel(
            engine=self.engine, engine_key=self.engine_key,
            degradation=degradation or DegradationFactors.as_new(self.engine),
        )
        # Give the engine its build scatter. Without it all four cylinders are
        # numerically identical, EGT spread is exactly 0.0 C, and the cylinder
        # balance check -- one of the few things a bench is actually for --
        # cannot fail. Measured across seeds, real build scatter puts a healthy
        # engine's EGT spread at 7-42 C.
        model.set_manufacturing_spread(np.random.default_rng(self.seed))
        amb = self._ambient()
        model.initialise_warm(amb)

        rep = AcceptanceReport(schedule=schedule.name, engine_key=self.engine_key)
        limits = self.engine["limits"]
        params = config.load_thresholds()["parameters"]

        for pt in schedule.points:
            load = 1.0

            # Settle unrecorded, then average over the dwell. A single sample
            # at the end of a dwell is a sample of the noise on it.
            for _ in range(int(pt.settle_s / dt)):
                _, load = self._tick(model, pt, amb, dt, load)

            acc: list = []
            loads: list[float] = []
            for _ in range(max(int(pt.duration_s / dt), 1)):
                out, load = self._tick(model, pt, amb, dt, load)
                acc.append(out)
                loads.append(load)

            r = PointResult(
                name=pt.name, throttle_pct=pt.throttle_pct,
                rpm=float(np.mean([o.rpm for o in acc])),
                power_kw=float(np.mean([o.power_kw for o in acc])),
                torque_nm=float(np.mean([o.torque_nm for o in acc])),
                cht_max_c=float(np.max([o.cht_max for o in acc])),
                coolant_c=float(np.max([o.coolant_temperature_c for o in acc])),
                egt_max_c=float(np.max([o.egt_max for o in acc])),
                egt_spread_c=float(np.max([o.egt_spread for o in acc])),
                oil_pressure_psi=float(np.mean([o.oil_pressure_psi for o in acc])),
                oil_temperature_c=float(np.max([o.oil_temperature_c for o in acc])),
                fuel_flow_lph=float(np.mean([o.fuel_flow_lph for o in acc])),
                bsfc_g_per_kwh=float(np.mean([o.bsfc_g_per_kwh for o in acc])),
                vibration_rms=float(np.mean([o.vibration_rms_m_s2 for o in acc])),
                target_rpm=pt.target_rpm,
                load_factor=float(np.mean(loads)),
                cooling_flap_fraction=float(np.max([o.cooling_flap_fraction for o in acc])),
                oil_flap_fraction=float(np.max([o.oil_flap_fraction for o in acc])),
                wastegate_fraction=float(np.min(
                    [o.turbo_state.wastegate_fraction for o in acc])),
            )
            if pt.settle_s == 0.0 and len(acc) > 2:
                # A step was commanded at the top of this dwell, so the dwell
                # contains the whole transient.
                trace = np.array([o.rpm for o in acc])
                final = float(trace[-1])
                start = float(trace[0])
                if abs(final - start) > 100.0:
                    target = start + 0.95 * (final - start)
                    reached = (trace >= target) if final > start else (trace <= target)
                    idx = int(np.argmax(reached)) if reached.any() else len(trace) - 1
                    r.response_time_s = float(idx * dt)
            if pt.target_rpm is not None:
                r.rpm_error = r.rpm - pt.target_rpm
                # Saturated against a limit stop means the speed was not held.
                r.load_saturated = bool(
                    min(loads) <= self.LOAD_MIN * 1.001
                    or max(loads) >= self.LOAD_MAX * 0.999
                )
            r.exceedances = self._exceedances(r, limits, params)
            rep.points.append(r)

        self._judge(rep, limits)
        return rep

    # ------------------------------------------------------------------
    @staticmethod
    def _exceedances(r: PointResult, limits: dict, params: dict) -> list[str]:
        out = []
        if r.coolant_c > float(limits["coolant_temperature_max_C"]):
            out.append(f"coolant {r.coolant_c:.1f} C over "
                       f"{limits['coolant_temperature_max_C']} C")
        if r.egt_max_c > float(limits["egt_max_C"]):
            out.append(f"EGT {r.egt_max_c:.0f} C over {limits['egt_max_C']} C")
        if r.egt_spread_c > float(limits["egt_split_max_C"]):
            out.append(f"EGT split {r.egt_spread_c:.0f} C over "
                       f"{limits['egt_split_max_C']} C")
        lo, hi = limits["oil_temperature_C"]
        if r.oil_temperature_c > float(hi):
            out.append(f"oil {r.oil_temperature_c:.1f} C over {hi} C")
        if r.rpm > 3500:
            p_lo, p_hi = limits["oil_pressure_above_3500rpm_bar"]
            bar = r.oil_pressure_psi / 14.5038
            if bar < float(p_lo):
                out.append(f"oil pressure {bar:.2f} bar under {p_lo} bar")
        if r.cht_max_c > float(params["cht"]["critical_max"]):
            out.append(f"CHT {r.cht_max_c:.1f} C over "
                       f"{params['cht']['critical_max']} C")
        return out

    def _judge(self, rep: AcceptanceReport, limits: dict) -> None:
        """Did the engine meet its certificate, and was the test valid?"""
        ratings = self.engine["ratings"]

        def find(name: str) -> PointResult | None:
            return next((p for p in rep.points if p.name.startswith(name)), None)

        checks: list[dict] = []

        mc = find("MAX CONTINUOUS")
        if mc is not None:
            target = float(ratings["continuous_power_kW"])
            # A post-overhaul engine is accepted at 95 % of its rating: the
            # certificate figure is a nominal, and cell instrumentation has its
            # own tolerance. Demanding the nominal exactly would reject sound
            # engines.
            checks.append(self._check(
                "max-continuous power", mc.power_kw, 0.95 * target,
                f">= 95% of {target:.0f} kW", higher_is_better=True,
            ))
            checks.append(self._check(
                "max-continuous coolant", mc.coolant_c,
                float(limits["coolant_temperature_max_C"]),
                f"<= {limits['coolant_temperature_max_C']} C",
            ))
            # COOLING AUTHORITY, not just temperature. A cell cools far better
            # than a hot day, so an engine can hold its coolant here and still
            # have no margin left where it has to fly: measured, 30 % of the
            # radiator blocked moved max-continuous coolant by 1.9 degC -- which
            # no limit catches -- while the cooling flap went from 0.49 to 0.68.
            #
            # The margin the engine must keep is derived, not chosen. Rejecting
            # heat at the OM's 50 degC ambient limit instead of this cell's air
            # needs (T_coolant - T_cell) / (T_coolant - 50) times the travel, so
            # what is spent here must leave room for that.
            hot_c = float(limits["coolant_temperature_max_C"]) - 5.0
            scale = max(mc.coolant_c - self.cell_temperature_c, 1.0) / max(
                mc.coolant_c - 50.0, 1.0)
            checks.append(self._check(
                "cooling authority at max continuous",
                mc.cooling_flap_fraction * scale, 1.0,
                f"cooling-air travel used ({mc.cooling_flap_fraction:.2f}) must still "
                f"reject the same heat at the OM's 50 C ambient limit "
                f"(x{scale:.2f}); coolant held at {mc.coolant_c:.1f} C, limit {hot_c + 5.0:.0f} C",
            ))

        to = find("TAKE-OFF")
        if to is not None:
            target = float(ratings["max_power_kW"])
            checks.append(self._check(
                "take-off power", to.power_kw, 0.95 * target,
                f">= 95% of {target:.0f} kW", higher_is_better=True,
            ))
            checks.append(self._check(
                "take-off EGT", to.egt_max_c, float(limits["egt_max_C"]),
                f"<= {limits['egt_max_C']} C",
            ))
            checks.append(self._check(
                "cylinder balance", to.egt_spread_c, float(limits["egt_split_max_C"]),
                f"EGT split <= {limits['egt_split_max_C']} C",
            ))

        idle = find("IDLE")
        if idle is not None:
            # NOT a throttle-position check. On a dual-channel FADEC engine
            # idle speed is closed-loop and is set on the bench, so testing
            # "what rpm does 15 % throttle give" measures this model's throttle
            # map, not the engine. Measured that way it read 1662 rpm and
            # failed an otherwise sound engine against the 1800 rpm minimum.
            #
            # What a bench genuinely accepts at idle is that the engine HOLDS
            # the certified idle speed and makes oil pressure there. Below
            # 3500 rpm the certificate allows 0.8 bar [OM s2.1], not the 2.0
            # bar it demands above.
            checks.append(self._check(
                "idle speed held", abs(idle.rpm_error), 50.0,
                f"within 50 rpm of {ratings['idle_rpm_min']:.0f} rpm",
            ))
            lo_bar = float(limits["oil_pressure_below_3500rpm_bar"][0])
            checks.append(self._check(
                "idle oil pressure", idle.oil_pressure_psi / 14.5038, lo_bar,
                f">= {lo_bar} bar below 3500 rpm", higher_is_better=True,
            ))

        # A power reading from a point where the dyno lost the speed is not a
        # reading of that rating at all, so this gates the ones above.
        for p in rep.points:
            if p.target_rpm is None:
                continue
            if p.load_saturated:
                rep.notes.append(
                    f"{p.name}: dynamometer saturated at load factor "
                    f"{p.load_factor:.2f}; {p.rpm:.0f} rpm was held against a "
                    f"{p.target_rpm:.0f} rpm target -- power at this point is "
                    f"not the rated point and the check above is void"
                )

        # Throttle response. Rotax publishes NO acceleration-time figure for
        # the 915 iS, so there is no certified number to test against and this
        # deliberately does not invent one. What a bench can judge without a
        # published spec is REPEATABILITY: a sound engine gives the same
        # response on every slam, while fouled injectors or a lazy turbo make
        # it slower and more variable from one slam to the next.
        #
        # The absolute time is recorded but not graded. In the fielded system
        # it is graded -- against this engine's own as-new shadow model
        # (layer4_core.shadow_model), which is the reference a bench does not
        # otherwise have.
        slams = [p for p in rep.points
                 if p.name.startswith("SLAM OPEN") and p.response_time_s is not None]
        if len(slams) >= 2:
            times = [p.response_time_s for p in slams]
            checks.append(self._check(
                "throttle response repeatability",
                max(times) - min(times), 1.0,
                f"spread <= 1.0 s across {len(times)} slams "
                f"(median {float(np.median(times)):.1f} s; no published spec)",
            ))

        rep.checks = checks
        # An empty check list must NEVER read as a pass. ``all([])`` is True,
        # so the throttle-response schedule -- which defines no rating checks
        # -- reported PASSED with zero evidence behind it. A green light backed
        # by nothing is worse than a red one.
        rep.passed = (
            bool(checks)
            and all(c["passed"] for c in checks)
            and not any(p.exceedances for p in rep.points)
        )
        if not checks:
            rep.notes.append(
                "this schedule defines no acceptance criteria -- it is an "
                "investigation run, and its result is the recorded data, not a "
                "pass or a fail"
            )

        # Was the CELL the limiting factor? An engine that overheats in a cell
        # that cannot cool has not failed; the test has. Saying which is the
        # difference between a week spent on a real fault and a week wasted.
        hot = [p for p in rep.points if p.coolant_c > float(
            limits["coolant_temperature_max_C"])]
        if hot and self.cell_cooling_kmh < 120.0:
            rep.cell_limited = True
            rep.notes.append(
                f"cell cooling is only {self.cell_cooling_kmh:.0f} km/h-equivalent; "
                f"the coolant exceedance is likely the FACILITY, not the engine -- "
                f"re-run with adequate cell cooling before condemning it"
            )
        if not rep.passed and not rep.cell_limited:
            # NAME what failed. A run can fail on an exceedance recorded at any
            # point while every named check passed -- measured with 40 % of the
            # radiator left, the report said FAILED and listed nothing at all,
            # which tells a maintainer nothing.
            exceeded = [f"{p.name}: {e}" for p in rep.points for e in p.exceedances]
            failed_checks = [c["name"] for c in rep.checks if not c["passed"]]
            why = ", ".join(failed_checks + exceeded) or "no criterion recorded why"
            rep.notes.append(
                f"engine did not meet its type-certificate ratings -- {why}")
        if rep.passed:
            rep.notes.append("engine meets its type-certificate ratings")

    @staticmethod
    def _check(
        name: str, measured: float, limit: float, criterion: str,
        *, higher_is_better: bool = False,
    ) -> dict:
        ok = measured >= limit if higher_is_better else measured <= limit
        return {
            "name": name,
            "measured": round(measured, 2),
            "criterion": criterion,
            "passed": bool(ok),
        }


__all__ = [
    "SCHEDULES",
    "AcceptanceReport",
    "PointResult",
    "TestPoint",
    "TestRig",
    "TestSchedule",
    "acceptance_schedule",
    "endurance_schedule",
    "throttle_response_schedule",
]
