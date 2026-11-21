"""ECU / FADEC control model -- ignition and injection scheduling.

WHY THIS MODULE EXISTS
----------------------
The problem statement requires "Injection timing parameters" as one of the
eight monitored parameters (section B), and injection-timing deviation as a
detection method for injector abnormalities (PRD Part 2 section 10.2 Method C).
Until now injection timing was a hard-coded constant in the engine model, so it
carried no information: it could not respond to load, speed, knock or wear, and
therefore no injector fault could ever be detected from it. This module makes
it a real, physically-driven signal.

MANUFACTURER DESCRIPTION [OM-915 i Ed.0 Rev.4 sections 7.5.1 - 7.5.3]
---------------------------------------------------------------------
Ignition control:
    "The 915 iSc/iS is equipped with 4 double ignition coils. The ignition
     system is almost entirely wear-free, as the ECU generates and processes
     the ignition signal electronically."

Fuel injection control:
    "The engine is equipped with an electronic fuel injection system. This
     system is controlled by the ECU and enables highly accurate metering of
     the fuel according to operating and load conditions, whilst at the same
     time also taking ambient conditions into account.
     The key input variables are throttle valve position, engine speed signal,
     intake air temperature, ambient pressure, manifold pressure and exhaust
     temperature. Ultimately, the required fuel quantity or INJECTION PERIOD is
     determined on the basis of the CALCULATED AIR DENSITY IN THE AIRBOX. It is
     monitored continuously."

So the engine runs a classic speed-density strategy: the ECU computes charge
mass from airbox density and engine speed, divides by the target air-fuel
ratio, and converts the result into an injection period. That is exactly what
``commanded_injection`` below does -- the control law is taken from the
manufacturer's own description rather than invented.

Lane redundancy [OM section 7.5.1]:
    "each of the sensors or actuators is connected to a Lane, so that the two
     Lanes have the same measurement values and send the same output signals.
     Non-redundant sensors (e.g. oil pressure sensors) are connected to one
     Lane only and serve for the expanded monitoring of the engine
     functionality."

COMMANDED vs ACTUAL -- the whole point
--------------------------------------
The ECU publishes what it COMMANDED. The HUMS instrumentation measures what
ACTUALLY happened, from crankshaft and camshaft position sensing. The
difference between the two is the diagnostic quantity:

  * a fouled or coked injector opens late and closes late -> the start of
    injection retards and the delivered mass falls short of command
  * a degraded solenoid slows its response -> deviation grows with engine speed,
    because the same absolute delay is a larger crank angle at higher rpm
  * knock drives the ECU to retard ignition -> a rising retard trend at constant
    power is an early combustion-quality indicator

None of that is visible if timing is a constant.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

# Nominal injector static flow. Not published by Rotax, so it is derived from
# the engine's own certified rating: at take-off the engine burns roughly
# 29 kg/h of fuel through 8 injectors at a duty cycle well below saturation.
# The value is calibrated in `calibrate_injector_flow` against the engine
# definition so that full power lands near 85 % duty, which is standard
# port-injection sizing practice.
_TARGET_DUTY_AT_RATED = 0.85

# Extra solenoid opening delay at total injector failure, and the nozzle
# flow restriction at the same point. Both are modelled, not published;
# the delay is scaled so that the degraded/fault bands of PRD Part 2
# section 10.2 Method C (1 deg / 3 deg CA) fall where they should.
_MAX_EXTRA_DELAY_MS = 0.35
_MAX_FLOW_RESTRICTION = 0.25
# Injectors never foul at the same rate. Relative susceptibility per cylinder
# [MOD], mean 1.0: without it an engine built with no scatter kept an EGT
# spread of exactly zero however badly its injectors fouled (review PHY-12).
#
# DRAWN PER ENGINE, not shared. It was the same fixed pattern on every engine,
# which is not how injectors foul and which made the pattern able to cancel an
# engine's build bias systematically rather than by chance: measured on seed 3,
# EGT spread at injector condition 0.70 collapsed to 4.25 degC -- NARROWER than
# the same engine healthy at 39.5 degC -- because the two patterns opposed each
# other. The spread of the draw matches the fixed pattern it replaces.
_FOULING_SPREAD = 0.15
_FOULING_SUSCEPTIBILITY = (1.15, 0.85, 1.05, 0.95)   # fallback before a draw


@dataclass(frozen=True)
class IgnitionCommand:
    """What the ECU commanded for one engine cycle."""

    ignition_btdc_deg: float
    injection_start_btdc_deg: float
    injection_period_ms: float
    injector_duty_fraction: float
    afr_target: float
    knock_retard_deg: float


@dataclass(frozen=True)
class TimingMeasurement:
    """What the HUMS instrumentation actually observed, per cylinder."""

    ignition_btdc_deg: list[float]
    injection_start_btdc_deg: list[float]
    delivered_fuel_fraction: list[float]  # actual / commanded mass, per cylinder

    def ignition_deviation(self, commanded: float) -> list[float]:
        return [a - commanded for a in self.ignition_btdc_deg]

    def injection_deviation(self, commanded: float) -> list[float]:
        return [a - commanded for a in self.injection_start_btdc_deg]

    @property
    def max_abs_injection_deviation(self) -> float:
        if not self.injection_start_btdc_deg:
            return 0.0
        return max(abs(v) for v in self.injection_start_btdc_deg)


@dataclass
class EcuModel:
    """Speed-density ignition and injection scheduler for one engine."""

    engine: dict
    injector_flow_g_per_s: float = 0.0
    _cyl_timing_bias: np.ndarray = field(default_factory=lambda: np.array([]))
    _fouling_susceptibility: np.ndarray = field(default_factory=lambda: np.array([]))

    def __post_init__(self) -> None:
        n = int(self.engine["geometry"]["cylinders"])
        if self._cyl_timing_bias.size == 0:
            self._cyl_timing_bias = np.zeros(n)
        if self._fouling_susceptibility.size == 0:
            self._fouling_susceptibility = np.array(
                [_FOULING_SUSCEPTIBILITY[i % len(_FOULING_SUSCEPTIBILITY)] for i in range(n)])
        if self.injector_flow_g_per_s <= 0.0:
            self.injector_flow_g_per_s = self.calibrate_injector_flow()

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    def calibrate_injector_flow(self) -> float:
        """Size the injectors from the engine's certified rating.

        At rated power the engine burns ``P_rated * BSFC`` of fuel. Spread over
        the injector count and the available injection window, sizing them for
        ~85 % duty at that point is standard practice and fixes the only free
        parameter.
        """
        rated_kw = float(self.engine["ratings"]["max_power_kW"])
        rated_rpm = float(self.engine["ratings"]["max_power_rpm"])
        n_inj = int(self.engine["ignition_system"].get("injectors", 4))
        # ~295 g/kWh is the mid-point of the published SFC band.
        fuel_g_per_s = rated_kw * 295.0 / 3600.0
        # One injection per cylinder per cycle; a cycle is two revolutions.
        cycles_per_s = rated_rpm / 60.0 / 2.0
        window_s = 1.0 / cycles_per_s
        per_injector_g_per_cycle = fuel_g_per_s / cycles_per_s / n_inj
        return per_injector_g_per_cycle / (window_s * _TARGET_DUTY_AT_RATED)

    def set_manufacturing_spread(
        self, rng: np.random.Generator, spread_deg: float = 0.25
    ) -> None:
        """Per-cylinder build variation in injector opening delay.

        Even a new engine is not perfectly matched. Without this the
        injection-deviation detector would look better than it can ever be in
        the field (PRD Part 0 section 0.5).
        """
        n = int(self.engine["geometry"]["cylinders"])
        self._cyl_timing_bias = rng.normal(0.0, spread_deg, n)
        self._cyl_timing_bias -= self._cyl_timing_bias.mean()
        # Which injector fouls fastest is a property of THIS engine, drawn with
        # the rest of its build, not a pattern every engine in the fleet shares.
        sus = np.clip(rng.normal(1.0, _FOULING_SPREAD, n), 0.5, 1.5)
        self._fouling_susceptibility = sus / sus.mean()

    # ------------------------------------------------------------------
    # Control laws
    # ------------------------------------------------------------------

    def _ignition_schedule_btdc(self, rpm: float, load_fraction: float) -> float:
        """Base ignition advance before knock correction.

        Standard spark-advance shape: advance rises with engine speed (less time
        per crank degree for the flame to cross the chamber) and falls with load
        (denser charge burns faster and knocks sooner). Rotax publishes no
        ignition map for this engine, so the shape is modelled and the nominal
        is anchored to the engine YAML.
        """
        nominal = float(self.engine["ignition_system"]["nominal_timing_deg_btdc"])
        rpm_ref = float(self.engine["ratings"]["max_torque_rpm"])
        speed_term = 8.0 * float(np.clip(rpm / rpm_ref, 0.0, 1.2))
        load_term = -10.0 * float(np.clip(load_fraction, 0.0, 1.0)) ** 1.3
        return float(np.clip(nominal + speed_term + load_term, 2.0, 40.0))

    def _injection_start_btdc(self, rpm: float, load_fraction: float) -> float:
        """Commanded start of injection.

        Port injection targets a closed-valve event: injection begins well
        before intake valve opening so the fuel has time to vaporise against the
        hot valve. The angle advances with speed because the same physical
        vaporisation time is more crank degrees at higher rpm.
        """
        rpm_ref = float(self.engine["ratings"]["max_torque_rpm"])
        base = 300.0  # deg BTDC of the firing TDC, i.e. during the exhaust stroke
        speed_term = 60.0 * float(np.clip(rpm / rpm_ref, 0.0, 1.2))
        load_term = 20.0 * float(np.clip(load_fraction, 0.0, 1.0))
        return float(base + speed_term + load_term)

    def commanded(
        self,
        *,
        rpm: float,
        load_fraction: float,
        air_mass_per_cycle_g: float,
        afr_target: float,
        knock_intensity: float = 0.0,
        rail_pressure_bar: float | None = None,
    ) -> IgnitionCommand:
        """Compute this cycle's ignition and injection command.

        ``air_mass_per_cycle_g`` is the charge mass the ECU calculates from
        airbox density -- the manufacturer's stated basis for fuel metering.
        """
        n_cyl = int(self.engine["geometry"]["cylinders"])
        n_inj = int(self.engine["ignition_system"].get("injectors", n_cyl))
        injectors_per_cyl = max(1, n_inj // n_cyl)

        # Knock feedback: retard ignition proportionally to knock intensity,
        # bounded by the authority a real ECU is given.
        knock_retard = float(np.clip(knock_intensity, 0.0, 1.0)) * 12.0
        ignition = self._ignition_schedule_btdc(rpm, load_fraction) - knock_retard
        ignition = float(np.clip(ignition, 0.0, 40.0))

        # Speed-density fuel command (OM section 7.5.3).
        fuel_g_per_cycle_per_cyl = air_mass_per_cycle_g / max(afr_target, 1e-6)
        fuel_per_injector_g = fuel_g_per_cycle_per_cyl / injectors_per_cyl

        # Rail pressure sets the injector flow rate; the ECU compensates, but a
        # pressure error still shows up as a delivery error.
        rail_nominal = 3.0
        if rail_pressure_bar is None:
            rail_pressure_bar = rail_nominal
        flow_g_per_s = self.injector_flow_g_per_s * math.sqrt(
            max(rail_pressure_bar, 0.1) / rail_nominal
        )
        period_s = fuel_per_injector_g / max(flow_g_per_s, 1e-9)

        cycles_per_s = max(rpm, 1.0) / 60.0 / 2.0
        available_s = 1.0 / cycles_per_s
        duty = float(np.clip(period_s / available_s, 0.0, 1.0))

        return IgnitionCommand(
            ignition_btdc_deg=ignition,
            injection_start_btdc_deg=self._injection_start_btdc(rpm, load_fraction),
            injection_period_ms=period_s * 1000.0,
            injector_duty_fraction=duty,
            afr_target=afr_target,
            knock_retard_deg=knock_retard,
        )

    # ------------------------------------------------------------------
    # What actually happens
    # ------------------------------------------------------------------

    def measured(
        self,
        command: IgnitionCommand,
        *,
        rpm: float,
        injector_condition: float = 1.0,
        ignition_condition: float = 1.0,
        misfire_cylinders: tuple[int, ...] = (),
        cylinder_flow_bias: np.ndarray | None = None,
    ) -> TimingMeasurement:
        """Per-cylinder actual timing, given component condition.

        The physical mechanism, and the reason deviation is speed-dependent:
        an injector solenoid has an opening DELAY measured in milliseconds. A
        fixed millisecond delay is a larger CRANK ANGLE at higher engine speed,
        so a worn injector's timing deviation grows with rpm. That signature is
        what distinguishes injector wear from a sensor problem.
        """
        n_cyl = int(self.engine["geometry"]["cylinders"])

        # A real ECU compensates the injector's NOMINAL dead time -- it is a
        # known, characterised constant. What it cannot compensate is the EXTRA
        # delay that fouling and solenoid wear introduce, because it has no
        # feedback on actual needle lift. So a healthy engine shows ~zero
        # deviation and every degree of deviation is wear.
        #
        # SCALE: PRD Part 2 section 10.2 Method C calls >3 deg CA a fault. At
        # 5500 rpm one degree is 30 us, so the whole degraded-to-fault band is
        # roughly 30-150 us of extra solenoid delay. A worn or coked injector
        # adds tenths of a millisecond, not milliseconds.
        wear = 1.0 - float(np.clip(injector_condition, 0.0, 1.0))
        extra_delay_ms = _MAX_EXTRA_DELAY_MS * wear**1.3

        deg_per_ms = 6.0 * max(rpm, 1.0) / 1000.0  # 360 deg per rev -> deg/ms
        delay_deg = extra_delay_ms * deg_per_ms

        # Fouling also restricts the nozzle, which reduces the FLOW RATE
        # independently of the timing shift. This is the larger effect on
        # delivered mass and it is what the fuel-flow and EGT-spread detectors
        # actually see.
        flow_restriction = _MAX_FLOW_RESTRICTION * wear

        inj_start: list[float] = []
        ign: list[float] = []
        delivered: list[float] = []
        for i in range(n_cyl):
            bias = float(self._cyl_timing_bias[i]) if self._cyl_timing_bias.size > i else 0.0
            # Wear amplifies the per-cylinder scatter as well as the mean shift:
            # injectors do not foul at the same rate, so an ageing set spreads
            # apart. That growing spread is the injector-imbalance signature.
            scatter = bias * (1.0 + 3.0 * wear)
            inj_start.append(command.injection_start_btdc_deg - delay_deg + scatter)

            # Ignition is electronic and "almost entirely wear-free" per the OM,
            # so its deviation is far smaller than the injection deviation.
            ign_dev = scatter * 0.15 + (1.0 - ignition_condition) * 1.5
            ign.append(command.ignition_btdc_deg - ign_dev)

            # Delivered fuel: the solenoid opens late but still closes on
            # schedule, so the effective open period shrinks; and the fouled
            # nozzle passes less fuel while it is open.
            if command.injection_period_ms > 1e-9:
                shortfall = extra_delay_ms / command.injection_period_ms
            else:
                shortfall = 0.0
            # Per-cylinder build variation in delivered mass, amplified by wear.
            if cylinder_flow_bias is not None and cylinder_flow_bias.size > i:
                flow_bias = float(cylinder_flow_bias[i]) * (1.0 + 2.5 * wear)
            else:
                flow_bias = 0.0
            restriction_i = flow_restriction * float(self._fouling_susceptibility[i])
            frac = (1.0 - shortfall) * (1.0 - restriction_i) * (1.0 + flow_bias)
            frac = float(np.clip(frac, 0.0, 1.2))
            if (i + 1) in misfire_cylinders:
                frac = 0.0
            delivered.append(frac)

        return TimingMeasurement(
            ignition_btdc_deg=ign,
            injection_start_btdc_deg=inj_start,
            delivered_fuel_fraction=delivered,
        )


def knock_intensity(
    *,
    cht_c: float,
    manifold_air_temp_c: float,
    equivalence_ratio: float,
    load_fraction: float,
    engine: dict,
) -> float:
    """Estimated knock tendency in [0, 1].

    Knock rises with charge temperature, with load, and as the mixture leans
    out toward stoichiometric from the rich side. This drives the ECU's
    ignition retard, so a rising retard trend at constant power is an early
    warning of degraded cooling or a lean-drifting injector -- which is why
    PRD Part 2 section 10.6 lists it as a combustion-instability indicator.
    """
    cht_limit = float(engine["thermal"]["cht_limit_C"])
    mat_limit = float(engine["intake"]["manifold_air_temp_max_C"])

    thermal = max(0.0, (cht_c - 0.80 * cht_limit) / (0.20 * cht_limit))
    charge = max(0.0, (manifold_air_temp_c - 0.6 * mat_limit) / (0.4 * mat_limit))
    # Richer than stoichiometric suppresses knock; lean of best power promotes it.
    mixture = max(0.0, 1.15 - equivalence_ratio) / 0.35
    load = float(np.clip(load_fraction, 0.0, 1.0)) ** 2

    raw = 0.45 * thermal + 0.25 * charge + 0.20 * mixture * load + 0.10 * load
    return float(np.clip(raw, 0.0, 1.0))
