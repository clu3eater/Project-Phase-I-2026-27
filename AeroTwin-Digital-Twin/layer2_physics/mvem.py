"""0-D Mean-Value Engine Model -- PRD Part 1 section 4.3 (Level 1).

The MVEM is the beating heart of the digital twin: it takes throttle and
ambient conditions and produces the cycle-averaged thermodynamic state the twin
compares against the real engine. The residual between this prediction and the
measured sensor value is what makes the system *predictive* rather than
threshold-based -- it is the input to cooling-degradation detection (PRD Part 2
section 10.3 Method A), sensor-bias estimation (section 10.5 Method B) and the
hybrid physics-plus-network model (PRD Part 3 INNOVATION 4).

State vector integrated with ``scipy.integrate.solve_ivp`` (RK45):

    x = [ omega, P_man, T_CHT_1..N, T_oil ]

    omega    crankshaft angular velocity      [rad/s]   engine-propeller torque balance
    P_man    intake manifold pressure         [Pa]      filling and emptying, section 4.3.1
    T_CHT_i  cylinder head temperature        [K]       lumped head capacity, section 4.3.3
    T_oil    bulk oil temperature             [K]       friction heat vs cooler, section 4.3.5

Everything else -- torque, BMEP, EGT, oil pressure, fuel flow, BSFC, vibration
-- is algebraic on top of that state.
"""

from __future__ import annotations

import functools
import math
from dataclasses import dataclass, field

import numpy as np
from scipy.integrate import solve_ivp

from layer2_physics import combustion, ecu, om_table, perf_maps, turbo
from layer2_physics.atmosphere import Ambient, ambient_at
from layer2_physics.degradation import DegradationFactors

R_AIR = 287.0
PSI_PER_PA = 1.0 / 6894.757


@dataclass
class EngineOutputs:
    """Everything the physics model predicts at one instant.

    Field names deliberately mirror the twin's ``simulated_state``
    (PRD Part 1 section 6.1) so that no translation layer is needed.
    """

    # primary state
    rpm: float
    manifold_pressure_bar: float
    cht_c: list[float]
    coolant_temperature_c: float
    oil_temperature_c: float

    # algebraic outputs
    torque_nm: float
    power_kw: float
    bmep_bar: float
    bsfc_g_per_kwh: float
    fuel_flow_lph: float
    egt_c: list[float]
    oil_pressure_psi: float
    air_mass_flow_kg_s: float
    equivalence_ratio: float
    vibration_rms_m_s2: float
    battery_voltage_v: float
    alternator_current_a: float
    # Positive while the battery DISCHARGES, negative on charge. Without this
    # the pack's internal resistance is not inferable at all -- see the
    # BATTERY_CURRENT note in scripts/gen_can_dbc.py.
    battery_current_a: float
    # Injection and ignition, per cylinder. These are MEASURED values; the
    # ECU's commanded values are carried separately so that the deviation --
    # the actual diagnostic quantity of PRD Part 2 section 10.2 Method C --
    # can be computed.
    injection_timing_deg: list[float]
    ignition_timing_deg: list[float]
    injection_timing_commanded_deg: float
    ignition_timing_commanded_deg: float
    injection_period_ms: float
    injector_duty_fraction: float
    knock_retard_deg: float
    knock_intensity: float
    delivered_fuel_fraction: list[float]

    # diagnostics
    turbo_state: turbo.TurboState
    flame_temp_k: float
    throttle_pct: float
    heat_to_head_w: float
    heat_to_coolant_w: float
    bsfc_map_g_per_kwh: float = 0.0
    air_fuel_consistency_residual: float = 0.0
    physics_constraint_violations: int = 0
    # How much of the airframe's cooling-air travel the engine is using, 0-1.
    # The engine has no thermostat, so these flaps are what hold the coolant and
    # oil where the installation wants them -- and, like the wastegate, they run
    # out. A radiator losing capacity is seen HERE, as authority spent, long
    # before it is seen as temperature: measured 0.64 against a healthy 0.36 at
    # cruise with 45 % of the radiator blocked, at which point coolant
    # temperature had moved 2.8 degC.
    cooling_flap_fraction: float = 0.0
    oil_flap_fraction: float = 0.0

    @property
    def injection_timing_deviation_deg(self) -> list[float]:
        """Actual minus commanded start of injection, per cylinder."""
        return [a - self.injection_timing_commanded_deg for a in self.injection_timing_deg]

    @property
    def max_injection_timing_deviation_deg(self) -> float:
        devs = self.injection_timing_deviation_deg
        return max(abs(d) for d in devs) if devs else 0.0

    @property
    def ignition_timing_deviation_deg(self) -> list[float]:
        return [a - self.ignition_timing_commanded_deg for a in self.ignition_timing_deg]

    @property
    def cht_max(self) -> float:
        return max(self.cht_c)

    @property
    def cht_spread(self) -> float:
        return max(self.cht_c) - min(self.cht_c)

    @property
    def egt_max(self) -> float:
        return max(self.egt_c)

    @property
    def egt_spread(self) -> float:
        return max(self.egt_c) - min(self.egt_c)


@dataclass
class MeanValueEngineModel:
    """0-D mean-value model for one engine instance."""

    engine: dict
    engine_key: str = "rotax_915is"
    degradation: DegradationFactors = field(default_factory=DegradationFactors)

    # integration state
    omega: float = 0.0  # rad/s
    p_man: float = 101325.0  # Pa
    t_cht: np.ndarray = field(default_factory=lambda: np.array([]))
    t_oil: float = 293.15  # K
    t_coolant: float = 293.15  # K

    _turbo_prev: turbo.TurboState | None = None
    # An AS-NEW turbo solved alongside the real one, at the same operating
    # point. It is the reference the brake-torque map was calibrated against;
    # see the charge_ratio note in _assemble_outputs for why the actual turbo
    # cannot be its own reference.
    _turbo_ref_prev: turbo.TurboState | None = None
    _ecu: ecu.EcuModel | None = None
    _oil_pressure_psi: float | None = None
    _cyl_flow_bias: np.ndarray = field(default_factory=lambda: np.array([]))
    _prop_k: float = 0.0
    # Propeller law: "constant_speed" (governed), "fixed_pitch", or "legacy"
    # for an engine definition with no propeller section (no density term --
    # exactly the behaviour such a definition was calibrated with).
    _prop_type: str = "legacy"
    # Governed blade pitch, relative to the sea-level full-throttle angle, and
    # the propeller's torque absorption (pitch x air density ratio) that the
    # governor actually lags -- see _govern for why not pitch alone.
    _pitch: float = 1.0
    _absorb: float = 1.0
    # This step's departure from sea level ISA per the manufacturer's table
    # (neutral for an engine without one), and the hot/cold-day power factor
    # on top of the ISA altitude lapse already inside the performance map.
    _env: om_table.Envelope = om_table.NEUTRAL
    _power_dev_factor: float = 1.0
    # Mean fuel the injectors actually delivered last step, as a fraction of the
    # command (1.0 on a healthy engine). See _assemble_outputs.
    _delivered_mean: float = 1.0
    _last_dt: float = 0.1
    _last_outputs: EngineOutputs | None = None
    # IGNITION AND FUEL. Off, the engine makes no torque and burns nothing:
    # friction and the propeller bring the shaft to rest, and the heads, oil
    # and coolant cool from wherever the run left them. `stopped` is set once
    # the shaft is down to rest, and the speed then reads zero -- the model's
    # 1 rad/s numerical floor is not a speed an engine turns at.
    ignition: bool = True
    stopped: bool = False

    def __post_init__(self) -> None:
        n = int(self.engine["geometry"]["cylinders"])
        if self.t_cht.size == 0:
            self.t_cht = np.full(n, 293.15)
        if self._cyl_flow_bias.size == 0:
            # Small permanent per-cylinder fuelling bias even on a new engine:
            # a perfectly balanced engine would make the EGT-spread detector
            # look better than it can ever be in the field.
            self._cyl_flow_bias = np.zeros(n)
        if self._ecu is None:
            self._ecu = ecu.EcuModel(engine=self.engine)
        self._calibrate_propeller()

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # SUDDEN FAILURES. The eight fault modes of the problem statement are WEAR:
    # they move the engine's condition over hours and are what the twin exists
    # to find early. A failure is different -- the engine stops making power,
    # now -- and a demonstration that could only wear the engine could not
    # show the thing an operator most needs to handle: fuel cut, and the
    # engine carried on at cruise power as if nothing had happened.
    #   fuel_starvation   no fuel reaches the injectors: combustion stops.
    #   ignition_failure  both lanes lose ignition: combustion stops.
    #   oil_loss          oil pressure collapses; run on without it and the
    #                     bearings seize and stop the engine.
    #   coolant_loss      the coolant is lost: heat stays in the heads.
    FAILURES = ("fuel_starvation", "ignition_failure", "oil_loss", "coolant_loss")
    # Running on with no oil pressure: seconds until the bearings seize.
    SEIZE_AFTER_S = 40.0

    @property
    def firing(self) -> bool:
        """Is anything burning? Ignition commanded on, and no failure or
        seizure preventing combustion."""
        f = getattr(self, "failures", ())
        return (self.ignition and not getattr(self, "seized", False)
                and "fuel_starvation" not in f and "ignition_failure" not in f)

    def _calibrate_propeller(self) -> None:
        """Size the propeller load so that WOT at sea level settles at rated rpm.

        Fixed-pitch propeller law: ``T_prop = k * omega^2``. Setting k from the
        rated point makes the engine-propeller system self-consistent, so the
        modelled rpm response to throttle is a real dynamic result rather than
        a scripted number.
        """
        maps = perf_maps.maps_for(self.engine_key)
        rpm_rated = float(self.engine["ratings"]["max_power_rpm"])
        omega_rated = rpm_rated * 2.0 * math.pi / 60.0
        t_rated = maps.torque_at(rpm_rated, 100.0, 0.0)
        self._prop_k = t_rated / (omega_rated**2)
        prop = self.engine.get("propeller") or {}
        self._prop_type = str(prop.get("type", "legacy"))
        if self._prop_type not in ("legacy", "fixed_pitch", "constant_speed"):
            raise ValueError(f"unknown propeller type {self._prop_type!r}")
        # Engine, reduction gear and propeller, referred to the crankshaft. It
        # was a bare 0.16 inside the equation of motion. It belongs to the
        # installation, and the ingest's engine-speed plausibility limit is
        # derived from it, so both must read the same number.
        if "rotating_inertia_at_crank_kg_m2" not in prop:
            raise ValueError(
                f"engine '{self.engine_key}': propeller section must give "
                "rotating_inertia_at_crank_kg_m2")
        self._inertia = float(prop["rotating_inertia_at_crank_kg_m2"])

    def set_manufacturing_spread(self, rng: np.random.Generator, spread: float = 0.007) -> None:
        """Per-engine build variation in cylinder-to-cylinder fuelling.

        PRD Part 0 section 0.5: randomise physics parameters per engine so that
        the network cannot memorise one trajectory.
        """
        n = int(self.engine["geometry"]["cylinders"])
        self._cyl_flow_bias = rng.normal(0.0, spread, n)
        self._cyl_flow_bias -= self._cyl_flow_bias.mean()
        if self._ecu is not None:
            self._ecu.set_manufacturing_spread(rng)

    # ------------------------------------------------------------------
    # Initialisation helpers
    # ------------------------------------------------------------------

    def initialise_warm(self, ambient: Ambient, rpm: float = 2500.0) -> None:
        """Put the model at a plausible warm idle so demos do not start cold."""
        self.omega = rpm * 2.0 * math.pi / 60.0
        # A governor that has been running at this altitude already has its
        # blades coarse enough for the thin air; starting them at the
        # sea-level angle would overspeed the first seconds at altitude.
        self._pitch = 1.0 / max(ambient.density_ratio, 0.2)
        self._absorb = 1.0
        self.p_man = ambient.pressure_pa * 0.6
        self.t_cht = np.full(
            int(self.engine["geometry"]["cylinders"]),
            float(self.engine["thermal"]["coolant_inlet_C"]) + 20.0 + 273.15,
        )
        self.t_oil = 95.0 + 273.15
        self.t_coolant = float(self.engine["thermal"]["coolant_inlet_C"]) + 273.15

    def initialise_cold(self, ambient: Ambient, crank_rpm: float = 250.0) -> None:
        """Put the model where a stopped, cold engine actually is: on the starter.

        The counterpart to ``initialise_warm``, and the state a sortie really
        begins in. Everything is at ambient -- heads, oil and coolant -- and the
        crankshaft is turning only as fast as the electric starter drives it, so
        there is almost no oil pressure and the engine is making no power.

        WHY NOT SIMPLY OMEGA = 0. The model integrates a torque balance, and at
        rest there is no torque to balance: the state sits on the 1 rad/s floor
        in ``step`` and never leaves it, which is not a stopped engine but a
        broken one. A real engine does not start itself either -- a starter
        motor turns it until combustion can carry it -- so the honest initial
        condition is cranking speed, not zero. From here, at an idle throttle,
        the engine catches and settles at its own idle on the model's own
        dynamics: measured at ~1,905 rpm with oil pressure building to 57 psi,
        from any crank speed between 200 and 600 rpm.

        ``crank_rpm`` defaults to 250, the middle of the 200-300 rpm an electric
        starter turns an engine of this size at [STD]. The settled idle is
        insensitive to it, which is the sign the start is being computed rather
        than assumed.
        """
        self.omega = max(crank_rpm, 1.0) * 2.0 * math.pi / 60.0
        self.ignition = True
        self.stopped = False
        # Blades where a governor leaves them with no oil pressure to move them:
        # against the fine stop, which is also what makes a start possible.
        self._pitch = 1.0 / max(ambient.density_ratio, 0.2)
        self._absorb = 1.0
        # Manifold pressure below ambient: the engine is being turned over
        # against a nearly closed throttle.
        self.p_man = ambient.pressure_pa * 0.4
        cold_k = ambient.oat_c + 273.15
        self.t_cht = np.full(int(self.engine["geometry"]["cylinders"]), cold_k)
        self.t_oil = cold_k
        self.t_coolant = cold_k

    # ------------------------------------------------------------------
    # Sub-models
    # ------------------------------------------------------------------

    def _throttle_mass_flow(self, throttle_pct: float, ambient: Ambient, p_up_pa: float) -> float:
        """Isentropic orifice flow through the throttle -- PRD section 4.3.1.

        ``p_up_pa`` is the pressure upstream of the throttle: ambient on a
        naturally aspirated engine, compressor discharge on a turbocharged one.
        """
        intake = self.engine["intake"]
        cd = float(intake["throttle_discharge_coeff"])
        a_max = float(intake["throttle_area_max_m2"])
        gamma = float(self.engine["thermodynamics"]["gamma_mixture"])

        a = float(np.clip(throttle_pct, 0.0, 100.0)) / 100.0
        area = a_max * math.sin(0.5 * math.pi * a) ** 1.35
        if area <= 0.0 or p_up_pa <= 0.0:
            return 0.0

        pi_ratio = float(np.clip(self.p_man / p_up_pa, 1e-6, 1.0))
        crit = (2.0 / (gamma + 1.0)) ** (gamma / (gamma - 1.0))
        if pi_ratio > crit:
            phi = math.sqrt(
                max(
                    0.0,
                    (2.0 * gamma / (gamma - 1.0))
                    * (pi_ratio ** (2.0 / gamma) - pi_ratio ** ((gamma + 1.0) / gamma)),
                )
            )
        else:  # choked
            exponent = (gamma + 1.0) / (2.0 * (gamma - 1.0))
            phi = math.sqrt(gamma) * (2.0 / (gamma + 1.0)) ** exponent

        t_up = ambient.oat_k if self._turbo_prev is None else self._turbo_prev.manifold_air_temp_k
        return cd * area * p_up_pa / math.sqrt(R_AIR * max(t_up, 100.0)) * phi

    def _cylinder_mass_flow(self, rpm: float, altitude_ft: float, t_man_k: float) -> float:
        """Air drawn into the cylinders -- the filling-and-emptying sink term.

            m_dot = eta_vol * V_d * (N/ (2*60)) * rho_man
        """
        # eta_vol depends only on speed and altitude, but this is called about
        # 45 times per step from inside the manifold bisection with both held
        # fixed, and each scipy grid lookup cost ~60 us -- the single largest
        # item in a profiled step. The last lookup is remembered instead.
        cache = getattr(self, "_eta_cache", None)
        if cache is None or cache[0] != rpm or cache[1] != altitude_ft:
            cache = (rpm, altitude_ft,
                     perf_maps.maps_for(self.engine_key).eta_vol_at(rpm, altitude_ft))
            self._eta_cache = cache
        eta_vol = cache[2]
        v_disp = float(self.engine["geometry"]["displacement_total_L"]) * 1e-3
        rho_man = self.p_man / (R_AIR * max(t_man_k, 100.0))
        return eta_vol * v_disp * (rpm / (2.0 * 60.0)) * rho_man

    def _friction_torque(self, rpm: float, viscosity_ratio: float | None = None) -> float:
        """Friction and pumping torque [N m], Chen-Flynn style FMEP.

        Chen-Flynn: FMEP = a + b*N + c*N^2, scaled by oil viscosity. Oil
        thickening from thermal breakdown raises viscous drag, which shows up
        in both the BSFC trend and the oil-pressure signature the detectors
        key on.
        """
        disp = float(self.engine["geometry"]["displacement_total_L"])
        visc = self.degradation.oil_viscosity_ratio if viscosity_ratio is None else viscosity_ratio
        fmep_bar = 0.30 + 0.09 * (rpm / 1000.0) + 0.012 * (rpm / 1000.0) ** 2
        fmep_bar *= 0.85 + 0.15 * visc
        return perf_maps.torque_from_bmep(fmep_bar, disp)

    def _excess_friction_torque(self, rpm: float) -> float:
        """Friction ABOVE the as-new value.

        The performance map returns BRAKE mean effective pressure, so friction
        at the as-new condition is ALREADY deducted from it. Subtracting the
        full friction torque again -- as an earlier version of this model did --
        double-counts it and cost roughly 11% of rated power. Only the *excess*
        friction caused by degradation may be subtracted.
        """
        return self._friction_torque(rpm) - self._friction_torque(rpm, viscosity_ratio=1.0)

    def _mat_penalty_torque(self, rpm: float) -> float:
        """Published power loss with hot charge air [OM-915 i s2.1], as torque.

        Between 50 and 80 degC manifold air temperature the manual allows
        operation at a stated power penalty: 1.0 kW at maximum continuous and
        2.7 kW at take-off. The engine definition carried both figures and only
        a test read them, so power stayed at 103 kW with 84 degC charge air
        (review PHY-03). Interpolated in speed between the two ratings; nothing
        at or below 50 degC.
        """
        ts = self._turbo_prev
        intake = self.engine.get("intake", {})
        if ts is None or "extended_mat_power_loss_continuous_kW" not in intake:
            return 0.0
        if ts.manifold_air_temp_k - 273.15 <= float(intake["manifold_air_temp_max_C"]):
            return 0.0
        ratings = self.engine["ratings"]
        continuous_rpm = float(ratings["continuous_power_rpm"])
        loss_kw = float(np.interp(
            rpm,
            [continuous_rpm, float(ratings["max_power_rpm"])],
            [float(intake["extended_mat_power_loss_continuous_kW"]),
             float(intake["extended_mat_power_loss_takeoff_kW"])],
        ))
        # THE MANUAL QUOTES THIS LOSS AT RATED POWER, AND A FIXED POWER LOSS
        # BECOMES AN INFINITE TORQUE AS THE ENGINE STOPS.
        #
        # Dividing a constant kW by omega is correct near the speeds the figure
        # is published at -- 1.0 kW at maximum continuous is 1.7 N m -- and is
        # nonsense below them. `np.interp` clamps the loss to 1.0 kW all the
        # way down to zero rpm, so at a 250 rpm cranking speed the same figure
        # came out as 38 N m, and at the model's 9.5 rpm floor as 1,000 N m
        # against a peak engine torque of 172.
        #
        # The consequence was not subtle: on any day with charge air over
        # 50 degC -- which is every hot day, and the problem statement asks for
        # 30 to 50 degC ambient -- the engine was handed a braking torque
        # several times what it could make the moment the starter turned it,
        # and stopped dead. Measured: at ISA+30 it never left 9.5 rpm, made no
        # power and burned no fuel, for the whole sortie.
        #
        # Tapering the loss with speed below the continuous rating holds the
        # TORQUE at its rated value instead of letting it diverge, which is the
        # conservative reading of a figure the manual does not quote at idle.
        # Nothing changes at or above continuous speed, where the published
        # numbers actually apply.
        if rpm < continuous_rpm:
            loss_kw *= max(rpm, 0.0) / continuous_rpm
        omega = max(rpm, 1.0) * 2.0 * math.pi / 60.0
        return loss_kw * 1000.0 / omega

    def _oil_pressure_psi_steady(self, rpm: float, t_oil_k: float) -> float:
        """Oil pressure -- PRD section 4.3.5.

            P_oil = P_pump - dP_bearing - dP_gallery - dP_filter

        The gross pump pressure is the delivered flow of a positive-displacement
        pump multiplied by the hydraulic resistance of the circuit, capped by
        the relief valve. Circuit resistance rises with oil viscosity and falls
        with the cube of bearing clearance (the short-bearing leakage result),
        which is precisely why the oil-pressure-versus-rpm correlation of
        PRD Part 2 section 10.4 Method A is a genuine lubrication-health
        indicator and not a coincidence:

          * oil thermal breakdown  -> viscosity up   -> pressure up, then
            filter drop up, and the dP/dT slope flattens (Method C)
          * bearing wear           -> clearance up   -> leakage up -> pressure
            down and the correlation with rpm weakens (Method A)
        """
        oil = self.engine["oil_system"]
        drive = float(oil["pump_drive_ratio"])
        disp_cm3 = float(oil["pump_displacement_cm3_per_rev"])
        eta_p = float(oil["pump_efficiency"])
        k_circuit = float(oil["pump_pressure_psi_per_cm3_s"])
        relief_psi = float(oil["relief_valve_psi"])

        pump_speed = rpm * drive
        flow_cm3_s = eta_p * disp_cm3 * pump_speed / 60.0

        # Viscosity ratio against the 95 degC reference: thinner when hot,
        # thicker when oxidised.
        t_c = t_oil_k - 273.15
        visc = math.exp(-0.020 * (t_c - 95.0)) * self.degradation.oil_viscosity_ratio
        visc = float(np.clip(visc, 0.15, 6.0))

        design_clearance = float(
            self.engine["degradation"]["bearing_wear"]["design_clearance_mm"]
        )
        # A zero clearance means "not initialised", not "seized": treat it as
        # as-new rather than letting it divide the leakage term to nothing.
        actual_clearance = self.degradation.bearing_clearance_mm or design_clearance
        clearance_ratio = float(
            np.clip(actual_clearance / max(design_clearance, 1e-9), 0.5, 4.0)
        )

        # Bearing leakage grows with clearance cubed, but the bearings are ONE
        # path of the circuit, in parallel with galleries, jets and the turbo
        # feed that wear does not open up. Dividing the WHOLE circuit by
        # clearance cubed took a 2x-clearance engine -- the maintenance multiple
        # -- from 3.97 to 0.10 bar at 4764 rpm, a seizure reading for a service
        # condition (review PHY-11). The conductance is now a mix, with the
        # bearings' share of it as-new from the engine definition (absent:
        # 1.0, the old law exactly).
        share = float(oil.get("bearing_leak_share_new", 1.0))
        conductance = (1.0 - share) + share * clearance_ratio**3
        p_gross = k_circuit * flow_cm3_s * visc / conductance
        # Relief valve. Saturating the WHOLE curve with a tanh (as an earlier
        # version did) flattens oil pressure across the entire speed range,
        # which destroys the oil-pressure-versus-rpm correlation that
        # PRD Part 2 section 10.4 Method A depends on. Instead the response is
        # linear up to the valve's cracking point and only then rolls off, so
        # the correlation survives in the normal operating band.
        knee = 0.80 * relief_psi
        if p_gross <= knee:
            p_pump = p_gross
        else:
            span = relief_psi - knee
            p_pump = knee + span * math.tanh((p_gross - knee) / span)

        dp_gallery = float(oil["gallery_dp_psi"]) * (pump_speed / 2500.0) * visc
        dp_filter = float(oil["filter_dp_psi"]) * visc

        return float(max(0.0, p_pump - dp_gallery - dp_filter))

    def _oil_pressure_lagged(self, rpm: float, t_oil_k: float, dt: float) -> float:
        """Oil pressure with the circuit's hydraulic compliance.

        The steady-state relation above is algebraic in engine speed, so a
        throttle slam moved modelled oil pressure instantly -- at up to
        46 psi/s, which the ingest layer correctly rejected as physically
        impossible (PRD Part 1 section 8.3 Method 2 caps it at 20 psi/s).
        A real gallery has volume and the oil has bulk compliance, so pressure
        follows a change in pump speed with a short lag. Modelling that removes
        the spurious rejections without touching the plausibility limit.
        """
        target = self._oil_pressure_psi_steady(rpm, t_oil_k)
        if self._oil_pressure_psi is None:
            self._oil_pressure_psi = target
            return target
        tau = 1.5
        alpha = dt / (tau + dt)
        self._oil_pressure_psi += alpha * (target - self._oil_pressure_psi)
        return float(self._oil_pressure_psi)

    def _heat_split(
        self, fuel_power_w: float, shaft_power_w: float
    ) -> tuple[float, float]:
        """(heat to cylinder heads, heat to exhaust) in watts.

        A calibrated first-law split: roughly a third of the fuel energy leaves
        as shaft work, a quarter to a third through the coolant/head path, and
        the balance out of the exhaust. The head fraction is a config value
        because it is engine-specific (PRD section 4.3.3 uses 0.28).
        """
        head_frac = float(self.engine["thermal"]["comb_heat_to_head_fraction"])
        losses = max(0.0, fuel_power_w - shaft_power_w)
        q_head = head_frac * fuel_power_w
        q_head = min(q_head, 0.85 * losses)
        q_exh = losses - q_head
        return q_head, q_exh

    # ------------------------------------------------------------------
    # ODE right-hand side
    # ------------------------------------------------------------------

    # -- fast state: intake manifold ------------------------------------
    #
    # The manifold filling-and-emptying equation of PRD section 4.3.1 has a
    # time constant of roughly 70 ms, while the thermal states have time
    # constants of 9-13 s. Integrating all of them together makes the system
    # stiff: an explicit RK45 solver was taking 429 internal steps to cross a
    # 0.5 s window, which blows the 20 ms physics budget of PRD Part 1
    # section 2.2 by three orders of magnitude.
    #
    # Standard mean-value-model practice is to split the timescales. The
    # manifold is advanced analytically as a first-order lag toward the
    # pressure at which throttle inflow equals cylinder outflow, using a time
    # constant linearised about that equilibrium. That is exact for a
    # first-order system and, at the 10 Hz telemetry rate, indistinguishable
    # from integrating it -- while costing two bisections instead of hundreds
    # of derivative evaluations.

    def _manifold_flows(
        self, p_man: float, throttle_pct: float, ambient: Ambient, p_up: float,
        rpm: float, t_man: float
    ) -> tuple[float, float]:
        saved = self.p_man
        self.p_man = p_man
        try:
            m_in = self._throttle_mass_flow(throttle_pct, ambient, p_up)
            m_out = self._cylinder_mass_flow(rpm, ambient.altitude_ft, t_man)
        finally:
            self.p_man = saved
        return m_in, m_out

    def _relax_manifold(
        self, dt: float, throttle_pct: float, ambient: Ambient, rpm: float
    ) -> tuple[float, float]:
        """Advance manifold pressure by ``dt``. Returns (p_man, t_man)."""
        ts = self._turbo_prev
        p_up = ts.manifold_pressure_bar * 1e5 if ts else ambient.pressure_pa
        # Post-intercooler manifold air temperature is what MATS1/2 measure and
        # what sets charge density. No further blending with a config nominal:
        # the intercooler model now produces this value physically.
        t_man = ts.manifold_air_temp_k if ts else ambient.oat_k

        def imbalance(p: float) -> float:
            m_in, m_out = self._manifold_flows(p, throttle_pct, ambient, p_up, rpm, t_man)
            return m_in - m_out

        # Inflow falls and outflow rises with manifold pressure, so the
        # imbalance is monotonically decreasing -- bisection is guaranteed.
        lo, hi = 1000.0, max(p_up * 1.02, 2000.0)
        f_lo = imbalance(lo)
        f_hi = imbalance(hi)
        if f_lo <= 0.0:
            p_eq = lo
        elif f_hi >= 0.0:
            p_eq = hi
        else:
            for _ in range(40):
                mid = 0.5 * (lo + hi)
                if imbalance(mid) > 0.0:
                    lo = mid
                else:
                    hi = mid
            p_eq = 0.5 * (lo + hi)

        # Linearise about the equilibrium to get the local time constant.
        v_man = float(self.engine["intake"]["manifold_volume_m3"])
        eps = max(200.0, 0.002 * p_eq)
        slope = (imbalance(p_eq + eps) - imbalance(p_eq - eps)) / (2.0 * eps)
        gain = R_AIR * t_man / v_man
        rate = -gain * slope  # 1/s, positive for a stable manifold
        if rate <= 1e-6:
            p_new = p_eq
        else:
            tau = 1.0 / rate
            p_new = p_eq + (self.p_man - p_eq) * math.exp(-dt / tau)
        return float(np.clip(p_new, 1000.0, 4.0e5)), t_man

    @staticmethod
    def _flap(temp_k: float, target_c: float, lowest: float, gain_per_k: float) -> float:
        """How far a cooling-air flap is open, 0-1.

        Proportional around the installation's target and saturating at both
        ends. Saturation is the point: while the flap has travel it holds the
        temperature where the installation wants it, and the moment it is fully
        open the temperature starts to tell the truth about the radiator. The
        same authority-then-runaway shape as the turbocharger's wastegate.
        """
        return float(np.clip(lowest + gain_per_k * (temp_k - (target_c + 273.15)),
                             lowest, 1.0))

    def _cooling_flap(self, t_coolant_k: float, thermal: dict) -> float:
        """The coolant radiator's flap. This engine has no thermostat."""
        return self._flap(t_coolant_k, float(thermal["cooling_flap_target_C"]),
                          float(thermal["cooling_flap_min_fraction"]),
                          float(thermal["cooling_flap_gain_per_K"]))

    def _derivatives(
        self, x: np.ndarray, throttle_pct: float, ambient: Ambient, load_factor: float | None
    ) -> np.ndarray:
        """Slow states only: [omega, T_CHT_1..N, T_oil, T_coolant]."""
        n_cyl = int(self.engine["geometry"]["cylinders"])
        omega = max(x[0], 1.0)
        t_cht = x[1 : 1 + n_cyl]
        t_oil = x[1 + n_cyl]
        t_coolant = x[2 + n_cyl]

        rpm = omega * 60.0 / (2.0 * math.pi)
        maps = perf_maps.maps_for(self.engine_key)

        p_man = self.p_man

        # -- torque balance (PRD 4.3.2) -------------------------------------
        # Indicated torque from the performance map, scaled by how much air is
        # actually in the manifold against what an AS-NEW turbocharger delivers
        # here in steady state (see step() and review PHY-08).
        ref = self._turbo_ref_prev
        p_map_ref = (ref.manifold_pressure_bar * 1e5) if ref else ambient.pressure_pa
        charge_ratio = float(np.clip(p_man / max(p_map_ref, 1e3), 0.05, 1.4))
        t_brake_map = maps.torque_at(rpm, throttle_pct, ambient.altitude_ft) * charge_ratio
        t_brake_map *= self._power_dev_factor
        t_brake_map *= self.degradation.combustion_efficiency
        t_brake_map -= self._mat_penalty_torque(rpm)
        t_friction = self._friction_torque(rpm)
        t_engine = t_brake_map - self._excess_friction_torque(rpm)
        if not self.firing:
            # No fire: the shaft is slowed by its own friction and the
            # propeller, and nothing else acts on it.
            t_engine = -(abs(t_friction) + self._excess_friction_torque(rpm))
        if getattr(self, "seized", False):
            # Seized bearings: the crank is all but locked.
            t_engine -= 20.0 * abs(t_friction) + 150.0
        t_prop = self._prop_k * omega * omega * self._absorber(load_factor, ambient)
        domega = (t_engine - t_prop) / self._inertia

        # -- cylinder head temperature (PRD 4.3.3) ---------------------------
        shaft_w = max(0.0, t_engine) * omega
        fuel_w = (self._fuel_power_w(rpm, max(t_engine, 0.0), ambient)
                  if self.firing else 0.0)
        q_head_total, _ = self._heat_split(fuel_w, shaft_w)

        thermal = self.engine["thermal"]
        m_head = float(thermal["head_mass_kg"])
        cp_head = float(thermal["head_cp_J_per_kgK"])
        a_cool = float(thermal["cooling_jacket_area_m2"])
        h0 = float(thermal["h_coolant_new_W_per_m2K"])
        ram = float(thermal["ram_air_cooling_coeff"])
        # NOTE: coolant temperature is an INTEGRATED STATE (t_coolant, read
        # from x above), not the fixed coolant_inlet_C config value. A leftover
        # assignment here previously shadowed the state, which froze the
        # radiator thermostat shut and let the modelled coolant run away.

        # TWO-NODE THERMAL MODEL. Node 1 is the head metal, node 2 is the
        # coolant loop. This split matters diagnostically: scale build-up in
        # the jacket degrades the HEAD-TO-COOLANT conductance, so cylinder head
        # temperature climbs while coolant temperature can stay near normal --
        # a signature a single-node model cannot produce, and precisely what
        # the cooling-degradation detector of PRD Part 2 section 10.3 looks for.
        h_cool = h0 * self.degradation.cooling_efficiency
        coolant_lost = "coolant_loss" in getattr(self, "failures", ())
        if coolant_lost:
            # Steam and air where coolant was: the jacket barely conducts.
            h_cool *= 0.35
        h_cool *= max(0.45, 1.0 + ram * (ambient.airspeed_kmh**0.8 - 100.0**0.8) * 3.2)

        q_head_per_cyl = q_head_total / n_cyl
        # Per-cylinder heat varies with the fuelling bias, which is exactly the
        # mechanism that makes injector fouling show up as CHT/EGT spread.
        bias = 1.0 + self._cyl_flow_bias[:n_cyl]
        q_i = q_head_per_cyl * bias
        q_cool_i = h_cool * a_cool * (t_cht - t_coolant)
        dt_cht = (q_i - q_cool_i) / (m_head * cp_head)

        # Coolant node: absorbs what the heads reject, loses it through the
        # radiator. Radiator effectiveness scales with ram airflow.
        m_coolant = float(thermal["coolant_capacity_L"]) * float(
            thermal["coolant_density_kg_per_L"]
        )
        cp_coolant = float(thermal["coolant_cp_J_per_kgK"])
        # Radiator conductance scales with ram airflow AND with the
        # cooling_airflow health factor -- a blocked radiator or lost cooling
        # air. Degrading this raises coolant and head together, which is the
        # signature that separates an overheating trend from jacket scaling.
        # THE AIRFRAME'S COOLING-AIR FLAP, NOT A THERMOSTAT. This engine has no
        # thermostat: the word appears in none of the manufacturer's thirteen
        # manuals, the IM's cooling-system interfaces do not include one and the
        # parts catalogue lists no such part (engine definition, 17 Sep). What
        # holds the coolant band on a real installation is the cooling air the
        # airframe admits, which the IM makes the installer's responsibility.
        # Modelled as a proportional flap that SATURATES: while it has travel
        # left it holds the target, and when it does not the coolant rises --
        # which is what makes a blocked radiator visible at all. The invented
        # thermostat absorbed exactly that, so a 45 % blocked radiator could not
        # be found overheating.
        flap = self._cooling_flap(float(t_coolant), thermal)
        ua_rad = (
            float(thermal["radiator_UA_W_per_K"])
            * max(0.35, (ambient.airspeed_kmh / 150.0) ** 0.8)
            * self.degradation.cooling_airflow
            * flap
        )
        if coolant_lost:
            ua_rad *= 0.2
        q_radiator = ua_rad * (t_coolant - ambient.oat_k)
        dt_coolant = (float(np.sum(q_cool_i)) - q_radiator) / (m_coolant * cp_coolant)

        # -- oil temperature (PRD 4.3.5) --------------------------------------
        oil = self.engine["oil_system"]
        m_oil = float(oil["capacity_L"]) * float(oil["density_kg_per_L"])
        cp_oil = float(oil["cp_J_per_kgK"])
        q_friction = t_friction * omega  # all friction work becomes heat
        # Oil also picks up heat from the hot metal.
        q_from_metal = 0.06 * q_head_total
        # Oil cooler rejects to ram air. Modelled as an overall conductance UA
        # referenced to 150 km/h, scaling with airspeed^0.6 for forced
        # convection on the air side. UA is a calibrated config value: sizing it
        # from an assumed oil mass flow instead gave a cooler an order of
        # magnitude too powerful, which drove the modelled sump below freezing.
        # The oil radiator sits in the same cooling duct as the coolant
        # radiator, so it breathes through the same flap. There is no
        # vernatherm on this engine either: the IPC lists an oil tank, an oil
        # pump assembly and an oil radiator, and nothing else. Its conductance
        # is sized to the IM's stated 30 kW duty (engine definition).
        ua_ref = float(oil["cooler_UA_W_per_K"])
        oil_flap = self._flap(float(t_oil), float(oil["cooler_flap_target_C"]),
                              float(oil["cooler_flap_min_fraction"]),
                              float(oil["cooler_flap_gain_per_K"]))
        ua = ua_ref * max(0.40, (ambient.airspeed_kmh / 150.0) ** 0.6) * oil_flap
        q_cooler = ua * (t_oil - ambient.oat_k)
        # A stopped engine's sump still loses heat through its walls to the
        # nacelle. The cooler flap closes below its target and has no minimum
        # opening, so with this left out nothing cooled the oil at all: after
        # shutdown it held 100 degC for as long as the station ran while the
        # heads and coolant cooled to ambient. Only while not firing, so the
        # running calibration against the manual is untouched. [MOD] ~6 W/K,
        # a sump cooling over tens of minutes.
        if not self.firing:
            q_cooler += float(oil.get("sump_UA_W_per_K", 6.0)) * (t_oil - ambient.oat_k)
        dt_oil = (q_friction + q_from_metal - q_cooler) / (m_oil * cp_oil)

        out = np.empty_like(x)
        out[0] = domega
        out[1 : 1 + n_cyl] = dt_cht
        out[1 + n_cyl] = dt_oil
        out[2 + n_cyl] = dt_coolant
        return out

    def _fuel_power_w(self, rpm: float, torque_nm: float, ambient: Ambient) -> float:
        """Chemical power RELEASED in the cylinders, from BSFC, shaft power and mixture."""
        maps = perf_maps.maps_for(self.engine_key)
        disp = float(self.engine["geometry"]["displacement_total_L"])
        bmep = perf_maps.bmep_from_torque(max(torque_nm, 0.0), disp)
        bsfc = self._bsfc(maps, rpm, bmep)
        p_kw = perf_maps.power_kw(max(torque_nm, 0.0), rpm)
        m_fuel_kg_h = bsfc * p_kw / 1000.0
        lhv = float(self.engine["fuel_properties"]["lhv_MJ_per_kg"]) * 1e6
        # The same mixture _assemble_outputs uses, so the heat the ODE integrates
        # and the heat the outputs report cannot disagree.
        phi = combustion.operating_phi(
            self.engine, p_kw / float(self.engine["ratings"]["max_power_kW"]))
        phi *= self._delivered_mean
        return (m_fuel_kg_h * self._delivered_mean / 3600.0 * lhv
                * _heat_released_fraction(phi))

    def _bsfc(self, maps: perf_maps.PerformanceMaps, rpm: float, bmep_bar: float) -> float:
        """BSFC at this condition, from the sea-level map and the manufacturer table.

        The map is a sea-level surface. At altitude the same throttle position
        makes less BMEP, and reading the map at that lower BMEP applied the
        map's own low-load penalty -- a sea-level effect -- to an altitude
        condition. The map is read at the sea-level-equivalent BMEP instead and
        scaled by the manufacturer's BSFC ratio for the altitude and
        temperature. Both factors are neutral for an engine without a table.
        """
        env = self._env
        bmep_sl = bmep_bar / max(env.power, 0.05)
        return (maps.bsfc_at(rpm, bmep_sl) * env.bsfc
                / max(self.degradation.combustion_efficiency, 0.5))

    def _absorber(self, load_factor: float | None, ambient: Ambient) -> float:
        """Multiplier on the propeller's sea-level torque law ``k * omega^2``.

        An explicit ``load_factor`` is a dynamometer or scripted load and is
        used as given. Otherwise a propeller absorbs torque in proportion to
        air density at a given blade angle -- which the original law left out,
        and is why full-throttle speed fell to 4711 rpm at 23,000 ft instead
        of being held (review PHY-06).
        """
        if load_factor is not None:
            return float(load_factor)
        if self._prop_type == "constant_speed":
            return self._absorb
        if self._prop_type == "fixed_pitch":
            return ambient.density_ratio
        return 1.0

    def _govern(
        self, dt: float, throttle_pct: float, ambient: Ambient, rpm_setpoint: float | None
    ) -> None:
        """Constant-speed governor: the blade pitch that holds speed, with a hydraulic lag.

        The speed held is either commanded (``rpm_setpoint``, e.g. 5500 rpm for
        maximum continuous) or scheduled from the lever: the speed the same
        propeller settles at on a sea-level ISA day with that lever, which keeps
        every sea-level operating point where it was and holds it at altitude.

        The pitch is the one at which the propeller absorbs exactly the torque
        the engine makes AT THE TARGET SPEED under the present conditions -- the
        steady state any working governor reaches -- approached through a
        first-order lag standing in for the hydraulic pitch-change mechanism.

        The first version was pure integral action on the speed error. From rest
        it wound the blades to the fine stop, and the first throttle advance
        then overspeeded the engine while the pitch caught up: a healthy engine
        on the simulator raised RPM_CRIT, CHT_CRIT and OILT_HIGH and lost CAN
        frames. Trims never showed it because they start with the blades set.
        A pitch computed from the torque at the target speed cannot wind up,
        because it never looks at the present speed.

        The lag acts on the propeller's ABSORPTION -- pitch times air density
        -- rather than on pitch alone. In flight density changes over the
        minutes of a climb, which a governor follows completely; but the
        simulator's flight profiles step altitude between phases, and lagging
        pitch alone turned a 500 -> 15,000 ft step into a 6781 rpm overspeed
        for one sample, which the rule engine rightly called RPM_CRIT. Blade
        stops still bound the pitch at the present density.
        """
        prop = self.engine.get("propeller") or {}
        if rpm_setpoint is not None:
            target = float(rpm_setpoint)
        else:
            levers, speeds = _governor_schedule(self.engine_key)
            target = float(np.interp(throttle_pct, levers, speeds))
        omega_t = target * 2.0 * math.pi / 60.0
        maps = perf_maps.maps_for(self.engine_key)
        # The same torque terms _derivatives integrates, evaluated at the target,
        # on the boost this turbocharger is HEADING for there rather than the
        # boost it has reached. On the lagged value the pitch trailed a power
        # surge: a 20 -> 100 % slam at 12,000 ft overspeeded to 5947 rpm while
        # the pitch caught up. On the steady value the pitch is already where
        # the settled engine needs it. Against the as-new turbocharger at the
        # same speed, as the torque map is.
        heading = turbo.solve(ambient=ambient, rpm=target, throttle_pct=throttle_pct,
                              engine=self.engine,
                              turbo_health=self.degradation.turbocharger_condition)
        as_new = turbo.solve(ambient=ambient, rpm=target, throttle_pct=throttle_pct,
                             engine=self.engine, turbo_health=1.0)
        charge_ratio = float(np.clip(
            heading.manifold_pressure_bar / max(as_new.manifold_pressure_bar, 1e-2), 0.05, 1.4))
        torque = (maps.torque_at(target, throttle_pct, ambient.altitude_ft) * charge_ratio
                  * self._power_dev_factor * self.degradation.combustion_efficiency
                  - self._mat_penalty_torque(target)
                  - self._excess_friction_torque(target))
        sigma = max(ambient.density_ratio, 0.05)
        lo = float(prop.get("pitch_fine_ratio", 0.25)) * sigma
        hi = float(prop.get("pitch_coarse_ratio", 3.0)) * sigma
        wanted = max(torque, 0.0) / max(self._prop_k * omega_t * omega_t, 1e-9)
        # Proportional speed trim for what feed-forward cannot know (a model
        # mismatch, a transient). No integral action, so nothing winds up. The
        # gain is bounded by stability at the largest step the twin takes: with
        # the 0.5 s lag a 1.0 s step moves 86 % of the way, and the loop factor
        # 1 - 0.86 (1 + K/2) must stay inside (-1, 1). K = 3 gave -1.16: it
        # oscillated divergently and ran a trimmed engine to 7050 rpm. K = 1.2
        # gives -0.38 at a 1.0 s step and +0.71 at 0.1 s [MOD].
        rpm_now = self.omega * 60.0 / (2.0 * math.pi)
        err = float(np.clip((rpm_now - target) / max(target, 1.0), -0.2, 0.2))
        wanted *= 1.0 + 1.2 * err
        wanted = float(np.clip(wanted, lo, hi))
        tau = float(prop.get("governor_time_constant_s", 0.5))
        self._absorb += (1.0 - math.exp(-dt / max(tau, 1e-3))) * (wanted - self._absorb)
        self._absorb = float(np.clip(self._absorb, lo, hi))
        self._pitch = self._absorb / sigma

    # ------------------------------------------------------------------
    # Public step
    # ------------------------------------------------------------------

    def step(
        self,
        dt: float,
        *,
        throttle_pct: float,
        ambient: Ambient,
        load_factor: float | None = None,
        electrical_load_a: float = 8.0,
        rpm_setpoint: float | None = None,
    ) -> EngineOutputs:
        """Advance the model by ``dt`` seconds and return the full output set.

        ``load_factor`` fixes the propeller or dynamometer load (the test rig
        trims it to hold a speed). Left as None, the engine definition's
        propeller law applies, which for a governed installation holds
        ``rpm_setpoint`` or the lever's scheduled speed.
        """
        n_cyl = int(self.engine["geometry"]["cylinders"])
        self._last_dt = dt
        rpm_now = self.omega * 60.0 / (2.0 * math.pi)

        # The manufacturer's table at this condition, once per step. The
        # performance map already carries the ISA altitude lapse, so what the
        # step adds is the hot or cold day on top of it, and the BSFC shift.
        rpm_env = max(rpm_now, 500.0)
        dev = om_table.isa_deviation_c(ambient)
        frac = perf_maps._throttle_factor(throttle_pct, rpm_env)
        self._env = om_table.envelope(self.engine, rpm_env, frac, ambient.altitude_ft, dev)
        if self._env is om_table.NEUTRAL or abs(dev) < 1e-9:
            self._power_dev_factor = 1.0
        else:
            at_isa = om_table.envelope(self.engine, rpm_env, frac, ambient.altitude_ft, 0.0)
            self._power_dev_factor = self._env.power / max(at_isa.power, 1e-6)

        # Turbocharger is solved first (quasi-steady with lag) because it sets
        # the upstream boundary condition for the manifold.
        self._turbo_prev = turbo.solve(
            ambient=ambient,
            rpm=max(rpm_now, 500.0),
            throttle_pct=throttle_pct,
            engine=self.engine,
            turbo_health=self.degradation.turbocharger_condition,
            previous=self._turbo_prev,
            dt=dt,
        )
        # The as-new reference is solved in STEADY STATE. It used to carry the
        # same boost lag as the real turbo, so the charge ratio cancelled the
        # lag: slamming 20 -> 100 % at 12,000 ft gave 92 % of steady boost at
        # 2 s but 99 % of steady power (review PHY-08). Against a steady
        # reference, air the turbo has not yet delivered is power not yet made.
        self._turbo_ref_prev = turbo.solve(
            ambient=ambient,
            rpm=max(rpm_now, 500.0),
            throttle_pct=throttle_pct,
            engine=self.engine,
            turbo_health=1.0,
            previous=None,
            dt=dt,
        )

        # Fast state first, analytically (see _relax_manifold), then the slow
        # states with RK45 on a now well-conditioned system.
        self.p_man, _ = self._relax_manifold(dt, throttle_pct, ambient, max(rpm_now, 500.0))

        x0 = np.concatenate(([self.omega], self.t_cht, [self.t_oil, self.t_coolant]))
        sol = solve_ivp(
            lambda _t, x: self._derivatives(x, throttle_pct, ambient, load_factor),
            (0.0, dt),
            x0,
            method="RK45",
            rtol=1e-4,
            atol=1e-6,
            max_step=dt,
        )
        x = sol.y[:, -1]

        self.omega = float(max(x[0], 1.0))
        # Below 30 rpm a shaft with no fire is at rest; the last few turns take
        # a fraction of a second and are not worth integrating toward zero.
        self.stopped = (not self.firing
                        and self.omega * 60.0 / (2.0 * math.pi) < 30.0)
        if self.stopped:
            self.omega = 1.0
            # Nothing is pumping the manifold, so it sits at the outside air
            # pressure, as a MAP gauge on a parked aircraft reads. The relax
            # step above works at a 500 rpm numerical floor and, left to it,
            # pumped a stopped engine's manifold down to 0.01 bar -- where the
            # two FADEC lanes' normal noise read as a disagreement and raised
            # SENSOR REDUNDANCY LOST on a parked aircraft.
            self.p_man = ambient.pressure_pa
        self.t_cht = np.clip(x[1 : 1 + n_cyl], 200.0, 900.0)
        self.t_oil = float(np.clip(x[1 + n_cyl], 200.0, 500.0))
        self.t_coolant = float(np.clip(x[2 + n_cyl], 200.0, 480.0))

        if (load_factor is None and self._prop_type == "constant_speed"
                and self.firing):
            self._govern(dt, throttle_pct, ambient, rpm_setpoint)

        return self._assemble_outputs(throttle_pct, ambient, electrical_load_a)

    def _assemble_outputs(
        self, throttle_pct: float, ambient: Ambient, electrical_load_a: float
    ) -> EngineOutputs:
        n_cyl = int(self.engine["geometry"]["cylinders"])
        rpm = self.omega * 60.0 / (2.0 * math.pi)
        maps = perf_maps.maps_for(self.engine_key)
        disp = float(self.engine["geometry"]["displacement_total_L"])

        ts = self._turbo_prev
        # CHARGE RATIO -- actual manifold pressure against the pressure the
        # brake-torque map assumes.
        #
        # The map was calibrated on published data for an AS-NEW engine, so the
        # pressure it implies is the as-new one. Referencing it against the
        # actual turbo's own output instead compares the turbo with itself, and
        # a turbo compared with itself can never be found wanting: measured
        # that way, turbocharger_condition falling 1.00 -> 0.65 dropped
        # manifold pressure 1.505 -> 0.988 bar, a 34 % loss of charge, and
        # brake power did not move at all -- 102.9 kW at both. At 15,000 ft the
        # charge fell 61 % and power went 96.0 -> 95.9 kW. A turbo failure
        # produced no power loss, which is its defining symptom.
        #
        # It is the same reference error the shadow model exists to avoid,
        # committed inside the physics: a degraded component must be measured
        # against an as-new reference, never against itself.
        #
        # The ratio still carries the manifold FILLING LAG it was written for,
        # because self.p_man is the integrated state and lags the turbo's
        # quasi-steady target during a transient. On an as-new engine the
        # reference and the actual turbo are the same solve, so every published
        # anchor is untouched.
        ref = self._turbo_ref_prev
        p_ref = (ref.manifold_pressure_bar * 1e5) if ref else ambient.pressure_pa
        charge_ratio = float(np.clip(self.p_man / max(p_ref, 1e3), 0.05, 1.4))
        t_brake_map = maps.torque_at(rpm, throttle_pct, ambient.altitude_ft) * charge_ratio
        t_brake_map *= self._power_dev_factor
        # What the charge would have delivered with as-new combustion. The part
        # a degraded burn fails to put into the piston leaves as exhaust heat.
        t_before_burn = max(0.0, t_brake_map)
        t_brake_map *= self.degradation.combustion_efficiency
        t_brake_map -= self._mat_penalty_torque(rpm)
        torque = max(0.0, t_brake_map - self._excess_friction_torque(rpm))
        power = perf_maps.power_kw(torque, rpm)
        bmep = perf_maps.bmep_from_torque(torque, disp)

        # -- fuel and mixture ------------------------------------------------
        #
        # MODEL CLOSURE, stated explicitly because it is over-determined.
        # Three quantities are related by two independent relations: brake
        # torque (performance map), fuel flow (BSFC map) and inducted air mass
        # (throttle/turbo/eta_vol path). All three are anchored to published
        # data, and they do not close exactly -- the air path and the BSFC map
        # disagree by 15-25% depending on operating point.
        #
        # We take the two *published* anchors as authoritative:
        #     torque    <- performance map  (reproduces 84.8 kW / 144 Nm exactly)
        #     fuel flow <- BSFC map         (280-320 g/kWh, 6-14 L/hr at cruise,
        #                                    PRD Part 1 sections 3.1 and 5.1)
        # and use the commanded equivalence ratio -- which is what the ECU
        # actually schedules, and what physically sets the flame temperature --
        # for the combustion calculation.
        #
        # The air path is then a THIRD, independent estimate. Its disagreement
        # with the fuel path is not hidden: it is published as
        # ``air_fuel_consistency_residual`` so that an engineer can see the
        # model's own uncertainty, and so that a future calibration against
        # VRDE rig data has a defined target to close.
        t_man = ts.manifold_air_temp_k if ts else ambient.oat_k
        m_air = self._cylinder_mass_flow(rpm, ambient.altitude_ft, t_man)

        bsfc = self._bsfc(maps, rpm, bmep)
        # Fuel the injectors actually DELIVER. A fouled nozzle and a late-opening
        # solenoid pass less than the ECU commands (layer2_physics.ecu), and a
        # speed-density ECU has no feedback on it -- so the flow meter reads less
        # and the mixture goes LEAN. It used to be ENRICHED by up to 19 %, the
        # wrong sign (review PHY-12). Taken from the previous step's per-cylinder
        # delivery, which the ECU model computes below.
        m_fuel_kg_h = bsfc * power / 1000.0 * self._delivered_mean
        rho_fuel = float(self.engine["fuel_properties"]["density_kg_per_L"])
        fuel_lph = m_fuel_kg_h / rho_fuel

        power_fraction = power / float(self.engine["ratings"]["max_power_kW"])
        # Commanded mixture sets the injection command; the delivered mixture is
        # what burns. Commanding on the delivered one would feed a fouled
        # injector's shortfall back into a shorter command and run away.
        phi_cmd = combustion.operating_phi(self.engine, power_fraction)
        phi = phi_cmd * self._delivered_mean

        phi_from_air = combustion.equivalence_ratio(
            m_air, m_fuel_kg_h / 3600.0, self.engine
        )
        af_residual = (phi_from_air - phi) / max(phi, 1e-6)

        # -- ignition and injection (ECU/FADEC model) -------------------------
        # Previously this was a constant, which meant injection timing carried
        # no information and no injector fault could ever be detected from it.
        # It is now scheduled by the speed-density control law the manufacturer
        # describes, and measured per cylinder with wear-driven deviation.
        assert self._ecu is not None
        mat_c = (ts.manifold_air_temp_k - 273.15) if ts else ambient.oat_c
        knock = ecu.knock_intensity(
            cht_c=float(np.max(self.t_cht) - 273.15),
            manifold_air_temp_c=mat_c,
            equivalence_ratio=phi,
            load_fraction=power_fraction,
            engine=self.engine,
        )
        # Charge mass the ECU calculates from airbox density, in grams per
        # cylinder per cycle -- the manufacturer's stated basis for metering.
        cycles_per_s = max(rpm, 1.0) / 60.0 / 2.0
        air_per_cycle_per_cyl_g = (m_air * 1000.0) / (cycles_per_s * n_cyl)
        rail_bar = float(
            np.mean(self.engine["fuel_properties"].get("rail_pressure_bar", [3.0, 3.0]))
        )
        command = self._ecu.commanded(
            rpm=rpm,
            load_fraction=power_fraction,
            air_mass_per_cycle_g=air_per_cycle_per_cyl_g,
            afr_target=combustion.stoichiometric_afr(self.engine) / max(phi_cmd, 1e-6),
            knock_intensity=knock,
            rail_pressure_bar=rail_bar,
        )
        measured = self._ecu.measured(
            command,
            rpm=rpm,
            injector_condition=self.degradation.injector_condition,
            cylinder_flow_bias=self._cyl_flow_bias,
        )
        timing = measured.injection_start_btdc_deg

        # -- EGT ------------------------------------------------------------
        fuel_w = (m_fuel_kg_h / 3600.0 * float(self.engine["fuel_properties"]["lhv_MJ_per_kg"])
                  * 1e6 * _heat_released_fraction(phi))
        shaft_w = torque * self.omega
        q_head, q_exh = self._heat_split(fuel_w, shaft_w)
        exhaust_loss_fraction = self._exhaust_pipe_loss_fraction(m_air, ambient)
        # As-new burn quality for the flame chain. A degraded burn used to scale
        # the flame temperature DOWN, so combustion degradation cooled the
        # exhaust (716 -> 596 degC at efficiency 0.90). Slow, late burning does
        # the opposite: work the charge fails to do on the piston leaves as
        # exhaust heat, added after the chain below (review PHY-12).
        eta_comb = float(self.engine["thermodynamics"]["combustion"]["efficiency_new"])
        p_peak = float(self.engine["thermodynamics"]["peak_cylinder_pressure_bar"]) * charge_ratio
        egt_mean_c, flame = combustion.egt_baseline_c(
            phi=phi,
            t_intake_k=t_man,
            p_peak_bar=max(p_peak, 1.0),
            eta_comb=eta_comb,
            exhaust_loss_fraction=exhaust_loss_fraction,
            engine=self.engine,
            engine_key=self.engine_key,
            map_egt_c=maps.egt_at(
                float(np.clip(power_fraction * 100.0, 25.0, 100.0)),
                phi,
                ambient.altitude_ft,
            ),
        )
        lost_w = t_before_burn * (1.0 - self.degradation.combustion_efficiency) * self.omega
        if lost_w > 0.0:
            m_exh = max(m_air + m_fuel_kg_h / 3600.0, 1e-4)
            cp_exh = float(self.engine["thermodynamics"]["cp_exhaust_J_per_kgK"])
            egt_mean_c += lost_w * (1.0 - exhaust_loss_fraction) / (m_exh * cp_exh)
        # Per-cylinder EGT is driven by the fuel each cylinder ACTUALLY
        # receives, which the ECU model computes from build variation plus
        # injector wear. A cylinder short of fuel moves AWAY from its siblings:
        # hotter rich of peak EGT, cooler lean of it, until it goes so lean that
        # it misfires and goes cold. This is the physical basis of PRD Part 2
        # section 10.2 Method B, and it is what makes EGT spread grow as
        # injectors foul.
        delivered = np.asarray(measured.delivered_fuel_fraction[:n_cyl], dtype=float)
        mean_delivered = float(np.mean(delivered)) if delivered.size else 1.0
        if mean_delivered <= 1e-6:
            mean_delivered = 1.0
        self._delivered_mean = float(np.clip(mean_delivered, 0.3, 1.2))
        rel = delivered / mean_delivered - 1.0
        # Which way depends on the side of peak EGT the mixture is on. The old
        # rule made a lean cylinder hotter everywhere, which is right only rich
        # of peak (take-off, climb) and backwards at a lean cruise mixture
        # (review PHY-12). Peak at phi 1.05, the peak of the EGT map in
        # perf_maps; the size of the effect away from peak is unchanged.
        side = math.tanh((1.05 - phi) / 0.05)
        egt_c = [float(egt_mean_c * (1.0 + 1.6 * side * r)) for r in rel]

        # -- oil ------------------------------------------------------------
        oil_psi = self._oil_pressure_lagged(rpm, self.t_oil, self._last_dt)
        if "oil_loss" in getattr(self, "failures", ()):
            # The sump empties and the pump sucks air: pressure falls away
            # over some ten seconds, whatever the engine speed.
            self._oil_loss_s = getattr(self, "_oil_loss_s", 0.0) + self._last_dt
            oil_psi *= max(0.03, math.exp(-self._oil_loss_s / 10.0))
            # Turning with no oil: the bearings go, and then the engine.
            if oil_psi < 6.0 and rpm > 1000.0:
                self._dry_run_s = getattr(self, "_dry_run_s", 0.0) + self._last_dt
                if self._dry_run_s >= self.SEIZE_AFTER_S:
                    self.seized = True

        # -- vibration ------------------------------------------------------
        vib = self._vibration_rms(rpm, torque)

        # -- electrical -----------------------------------------------------
        v_batt, i_alt, i_batt = self._electrical(rpm, electrical_load_a)


        if not self.firing:
            # Nothing burns, so there is no torque, no power and no fuel flow;
            # the exhaust probes sit in pipes bolted to the heads and cool
            # with them. Oil pressure follows the pump, i.e. the shaft speed,
            # which the lagged model above already does.
            torque, power, fuel_lph = 0.0, 0.0, 0.0
            egt_c = [float(t - 273.15) for t in self.t_cht]
            vib = self._vibration_rms(rpm, 0.0)
            if self.stopped:
                rpm = 0.0
                oil_psi = 0.0
                self._oil_pressure_psi = 0.0
                vib = 0.0

        violations = self._check_constraints(egt_c, oil_psi, rpm)

        outputs = EngineOutputs(
            rpm=rpm,
            manifold_pressure_bar=self.p_man / 1e5,
            cht_c=[float(t - 273.15) for t in self.t_cht],
            coolant_temperature_c=self.t_coolant - 273.15,
            oil_temperature_c=self.t_oil - 273.15,
            torque_nm=torque,
            power_kw=power,
            bmep_bar=bmep,
            bsfc_g_per_kwh=bsfc,
            fuel_flow_lph=fuel_lph,
            egt_c=egt_c,
            oil_pressure_psi=oil_psi,
            air_mass_flow_kg_s=m_air,
            equivalence_ratio=phi,
            vibration_rms_m_s2=vib,
            battery_voltage_v=v_batt,
            alternator_current_a=i_alt,
            battery_current_a=i_batt,
            injection_timing_deg=timing,
            ignition_timing_deg=measured.ignition_btdc_deg,
            injection_timing_commanded_deg=command.injection_start_btdc_deg,
            ignition_timing_commanded_deg=command.ignition_btdc_deg,
            injection_period_ms=command.injection_period_ms,
            injector_duty_fraction=command.injector_duty_fraction,
            knock_retard_deg=command.knock_retard_deg,
            knock_intensity=knock,
            delivered_fuel_fraction=measured.delivered_fuel_fraction,
            turbo_state=ts,
            flame_temp_k=flame.t_adiabatic_k,
            throttle_pct=throttle_pct,
            heat_to_head_w=q_head,
            heat_to_coolant_w=q_head,
            bsfc_map_g_per_kwh=bsfc,
            air_fuel_consistency_residual=af_residual,
            physics_constraint_violations=violations,
            cooling_flap_fraction=self._cooling_flap(
                self.t_coolant, self.engine["thermal"]),
            oil_flap_fraction=self._flap(
                self.t_oil,
                float(self.engine["oil_system"]["cooler_flap_target_C"]),
                float(self.engine["oil_system"]["cooler_flap_min_fraction"]),
                float(self.engine["oil_system"]["cooler_flap_gain_per_K"])),
        )
        self._last_outputs = outputs
        return outputs

    def _exhaust_pipe_loss_fraction(self, m_air: float, ambient: Ambient) -> float:
        """Fraction of exhaust enthalpy lost to the pipe -- PRD section 4.3.4."""
        ex = self.engine["exhaust"]
        h = float(ex["h_pipe_W_per_m2K"])
        a = float(ex["pipe_area_m2"])
        cp = float(self.engine["thermodynamics"]["cp_exhaust_J_per_kgK"])
        m_exh = max(m_air, 1e-4)
        # NTU-style: loss fraction = 1 - exp(-hA/(m_dot cp)), bounded so that a
        # near-idle mass flow cannot drive the predicted EGT to ambient.
        ntu = h * a / (m_exh * cp)
        return float(np.clip(1.0 - math.exp(-ntu), 0.10, 0.55))

    def _vibration_rms(self, rpm: float, torque_nm: float) -> float:
        """Broadband vibration RMS.

        Baseline scales with combustion forcing (roughly with BMEP and speed);
        bearing wear adds an impulsive component. The spectral detail used by
        the bearing detectors is synthesised separately in ``engine_sim.py`` --
        this is the 10 Hz RMS that the CAN bus actually carries.
        """
        base = float(self.engine["vibration"]["baseline_rms_m_per_s2"])
        rpm_ref = float(self.engine["ratings"]["max_torque_rpm"])
        speed_term = 0.55 + 0.45 * (rpm / rpm_ref) ** 1.5
        t_rated = max(float(self.engine["ratings"]["max_torque_Nm"]), 1.0)
        load_term = 0.75 + 0.25 * (torque_nm / t_rated)
        wear = (1.0 - self.degradation.bearing_condition) ** 1.4
        return float(base * speed_term * load_term * (1.0 + 3.2 * wear))

    def _electrical(self, rpm: float, load_a: float) -> tuple[float, float, float]:
        """Battery voltage and alternator current.

        The alternator only supports the bus above its cut-in speed; below that
        the battery discharges and voltage sags. This is what lets the
        electrical health index mean something during a low-rpm event.
        """
        el = self.engine["electrical"]
        v_nom = float(el["nominal_bus_V"])
        rated_a = float(el["alternator_rated_A"])
        cut_in = 1400.0
        capability = float(np.clip((rpm - cut_in) / (3000.0 - cut_in), 0.0, 1.0)) * rated_a
        i_alt = min(load_a, capability)
        if capability >= load_a:
            # Generator carrying the load: bus sits slightly above nominal at
            # the regulator setpoint.
            v = v_nom * 1.035 - 0.004 * load_a
        else:
            # Generator cannot carry the load: the battery makes up the
            # difference and the bus sags by I*R across its internal resistance.
            deficit = load_a - capability
            # The AGED resistance, not the as-new value. This is the only
            # condition in which internal resistance is observable at all --
            # a battery carrying no current reveals nothing about its health,
            # which is why battery SOH cannot be measured continuously.
            r_cell = (
                self.degradation.battery_internal_resistance_ohm
                or float(el["battery_internal_resistance_new_ohm"])
            )
            # Cells in series add their resistances. The count comes from the
            # engine configuration rather than a bare literal.
            r_pack = r_cell * float(el.get("battery_cells_series", 8))
            v = v_nom * 0.96 - deficit * r_pack
        # Clip to a band scaled from the bus voltage, NOT a fixed 8-16 V: this
        # engine's C24 variant runs a 28 V system and a hard 16 V ceiling
        # silently pinned every reading at the clip.
        # Battery current closes the node: whatever the alternator cannot
        # supply comes out of the pack, and any surplus charges it.
        i_batt = load_a - i_alt
        return (
            float(np.clip(v, 0.55 * v_nom, 1.15 * v_nom)),
            float(max(i_alt, 0.0)),
            float(i_batt),
        )

    def _check_constraints(self, egt_c: list[float], oil_psi: float, rpm: float) -> int:
        """Count physically impossible predictions -- PRD Part 1 section 6.2.

        A model that produces a nonsense number must say so rather than let the
        AI layer treat it as data (PRD Part 4 section 7.2).
        """
        v = 0
        if any(not math.isfinite(e) or e < -50.0 or e > 1400.0 for e in egt_c):
            v += 1
        if any(not math.isfinite(t) or t < 200.0 or t > 900.0 for t in self.t_cht):
            v += 1
        if not math.isfinite(oil_psi) or oil_psi < 0.0 or oil_psi > 150.0:
            v += 1
        if not math.isfinite(rpm) or rpm < 0.0 or rpm > 12000.0:
            v += 1
        # Outside what the thermal model can represent (review PHY-03): it has
        # no boiling in the coolant loop and no oil breakdown, so a prediction
        # past either is not a hot engine, it is an invalid one. At 50 degC and
        # 0 km/h the model once reported coolant 207 degC with zero violations.
        boil = self.engine.get("thermal", {}).get("coolant_boiling_C")
        if boil is not None and self.t_coolant - 273.15 > float(boil):
            v += 1
        oil_valid = self.engine.get("oil_system", {}).get("model_valid_max_C")
        if oil_valid is not None and self.t_oil - 273.15 > float(oil_valid):
            v += 1
        return v


def _heat_released_fraction(phi: float) -> float:
    """Share of the fuel's chemical energy released in the cylinders.

    Rich of stoichiometric there is not enough oxygen to burn all the fuel; the
    excess leaves as CO and H2 and heats nothing in the head. Combustion
    efficiency falls roughly as 1/phi on the rich side (Heywood, Internal
    Combustion Engine Fundamentals, 1988, section 4.9).

    It did not show while full-power fuel flow read 7 % low (31.5 kg/h against
    the manufacturer's 33.95): that shortfall happened to offset charging the
    14 % climb enrichment to the head as if it burned. With fuel flow corrected
    to the table (DEV-229), charging all of it raised take-off CHT by 8 K and
    put a healthy engine through its CHT caution in a 45 s take-off.
    """
    return min(1.0, 1.0 / max(phi, 1e-6))


@functools.lru_cache(maxsize=8)
def _governor_schedule(engine_key: str) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Lever -> speed a constant-speed governor holds.

    Below full lever: the speed at which the performance map's sea-level torque
    equals the propeller's sea-level law ``k * omega^2`` -- where the
    fixed-pitch model used to settle on a standard day -- CAPPED at the
    certified maximum-continuous speed. At full lever: the take-off speed.
    Both less ``governed_speed_margin_rpm``, the governor's regulation band.

    Both limits were found by the silent-healthy-engine test, not assumed. A
    governor holding exactly 5800 rpm read 5803 through sensor noise and raised
    OVERSPEED on a healthy take-off; an 80 % climb lever held 5603 rpm and
    raised MAX CONT EXCEEDED for the whole climb. The old fixed-pitch line ran
    those part-lever settings above maximum continuous too, and only escaped
    the alert because its speed fell with altitude.
    """
    maps = perf_maps.maps_for(engine_key)
    engine = maps.engine
    rpm_rated = float(engine["ratings"]["max_power_rpm"])
    omega_rated = rpm_rated * 2.0 * math.pi / 60.0
    k = maps.torque_at(rpm_rated, 100.0, 0.0) / omega_rated**2
    prop = engine.get("propeller") or {}
    margin = float(prop.get("governed_speed_margin_rpm", 0.0))
    mcp_rpm = float(engine["ratings"].get("continuous_power_rpm", rpm_rated))
    # Take-off speed only in the last 1 % of lever travel, a take-off detent:
    # interpolating all the way from 95 % held a 97 % lever at 5600 rpm.
    levers = tuple(float(v) for v in range(0, 100, 5)) + (99.0, 100.0)
    speeds = []
    for lever in levers:
        lo, hi = 300.0, 1.3 * rpm_rated
        for _ in range(40):
            mid = 0.5 * (lo + hi)
            omega = mid * 2.0 * math.pi / 60.0
            if maps.torque_at(mid, lever, 0.0) > k * omega * omega:
                lo = mid
            else:
                hi = mid
        line = 0.5 * (lo + hi)
        if lever >= 100.0:
            speeds.append(rpm_rated - margin)
        else:
            speeds.append(min(line, mcp_rpm - margin))
    return levers, tuple(speeds)


def build(
    engine_key: str = "rotax_915is",
    degradation: DegradationFactors | None = None,
) -> MeanValueEngineModel:
    from common import config

    engine = config.load_engine(engine_key)
    return MeanValueEngineModel(
        engine=engine,
        engine_key=engine_key,
        degradation=degradation or DegradationFactors.as_new(engine),
    )


def trim_to_steady_state(
    model: MeanValueEngineModel,
    *,
    throttle_pct: float,
    ambient: Ambient,
    seconds: float = 400.0,
    dt: float = 0.5,
    rpm_setpoint: float | None = None,
) -> EngineOutputs:
    """Run the model until the thermal states settle.

    Used to establish the baseline operating point for residual computation and
    to start a mission simulation from a warm engine. ``rpm_setpoint`` is the
    speed a governed propeller is commanded to hold (e.g. 5500 rpm, maximum
    continuous); a fixed-pitch installation ignores it.
    """
    model.initialise_warm(ambient)
    out = None
    steps = int(seconds / dt)
    for _ in range(steps):
        out = model.step(dt, throttle_pct=throttle_pct, ambient=ambient,
                         rpm_setpoint=rpm_setpoint)
    assert out is not None
    return out


if __name__ == "__main__":  # pragma: no cover
    amb = ambient_at(15000.0, airspeed_kmh=180.0)
    m = build()
    o = trim_to_steady_state(m, throttle_pct=75.0, ambient=amb)
    print(f"altitude       {amb.altitude_ft:8.0f} ft   OAT {amb.oat_c:6.1f} C")
    print(f"rpm            {o.rpm:8.0f}")
    print(f"manifold       {o.manifold_pressure_bar:8.3f} bar")
    print(f"torque         {o.torque_nm:8.1f} N m     power {o.power_kw:6.1f} kW")
    print(f"BMEP           {o.bmep_bar:8.2f} bar     BSFC  {o.bsfc_g_per_kwh:6.1f} g/kWh")
    print(f"CHT            {[round(c, 1) for c in o.cht_c]}  max {o.cht_max:.1f} C")
    print(f"coolant        {o.coolant_temperature_c:8.1f} C   (certified limit 120 C)")
    print(f"EGT            {[round(e, 1) for e in o.egt_c]}  max {o.egt_max:.1f} C")
    print(f"oil            {o.oil_pressure_psi:8.1f} psi   {o.oil_temperature_c:6.1f} C")
    print(f"fuel flow      {o.fuel_flow_lph:8.2f} L/hr")
    print(f"phi            {o.equivalence_ratio:8.3f}")
    print(f"vibration      {o.vibration_rms_m_s2:8.2f} m/s2")
    print(f"electrical     {o.battery_voltage_v:8.2f} V   {o.alternator_current_a:5.1f} A")
    print(f"inj timing     cmd {o.injection_timing_commanded_deg:6.1f} degBTDC   "
          f"actual {[round(v, 1) for v in o.injection_timing_deg]}")
    print(f"inj deviation  {[round(v, 2) for v in o.injection_timing_deviation_deg]}  "
          f"max |dev| {o.max_injection_timing_deviation_deg:.2f} deg")
    print(f"ign timing     cmd {o.ignition_timing_commanded_deg:6.1f} degBTDC   "
          f"knock retard {o.knock_retard_deg:.2f} deg (intensity {o.knock_intensity:.3f})")
    print(f"injection      {o.injection_period_ms:6.2f} ms   duty "
          f"{100 * o.injector_duty_fraction:5.1f}%")
    print(f"violations     {o.physics_constraint_violations}")
