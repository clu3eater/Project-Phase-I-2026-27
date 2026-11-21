"""Turbocharger model -- PRD Part 1 section 4.4.

The Rotax 914 is turbocharged with automatic wastegate control, which is the
single most important reason a MALE UAV can hold useful power at altitude. The
model provides:

  * compressor pressure ratio and delivered manifold pressure
  * wastegate position as a function of altitude and demand
  * compressor discharge temperature (drives intake charge temperature, which
    feeds the combustion and CHT models)
  * turbocharger speed (used for the vibration signature and for the
    turbocharger degradation pathway of PRD Part 1 section 5.2 DEG-6)
  * boost lag, so that the rapid-throttle-transition scenario of PRD Part 3
    section 18.1 CONDITION 4 behaves correctly

Below the critical altitude the wastegate bleeds exhaust to hold target
manifold pressure. Above it the wastegate is shut and manifold pressure falls
with ambient pressure -- that transition is what the operator sees as the
"critical altitude knee" on the power available trace.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from layer2_physics import om_table, perf_maps
from layer2_physics.atmosphere import Ambient

GAMMA_AIR = 1.4
CP_AIR = 1005.0  # J/(kg K)


def _isa_pressure_bar(altitude_ft: float) -> float:
    """ISA static pressure [bar] -- used to size the compressor from the
    published critical altitude."""
    from layer2_physics.atmosphere import FT_PER_M, isa_pressure_pa

    return isa_pressure_pa(altitude_ft / FT_PER_M) / 1e5


@dataclass(frozen=True)
class TurboState:
    pressure_ratio: float
    manifold_pressure_bar: float
    compressor_outlet_temp_k: float
    manifold_air_temp_k: float  # post-intercooler: what MATS1/2 actually read
    wastegate_fraction: float  # 0 = fully closed (all gas to turbine), 1 = fully open
    turbo_speed_rpm: float
    boost_limited: bool  # True when ambient no longer supports target boost
    efficiency: float


def _target_manifold_bar(
    throttle_pct: float, engine: dict, health: float = 1.0, rpm: float = 5500.0
) -> float:
    """Manifold pressure the boost controller is trying to hold.

    PUBLISHED SCHEDULE [OM-915 i Ed.0 Rev.4 section 2.1]:

        "Target pressure at a temperature from 25 degC to 35 degC:
             5800 rpm   1520 mbar
             5500 rpm   1450 mbar
         1730 mbar is the 'not to exceed' value which is needed by the boost
         pressure control in special situations."

    So the controller targets 1.45-1.52 bar as a function of engine speed, and
    1.73 bar is a transient authority limit, not a setpoint. An earlier version
    of this model used 1.73 bar as the target, which over-boosted the engine by
    14 % and inflated every downstream airflow, fuel and thermal figure.

    ``health`` is accepted and deliberately NOT applied. It used to scale the
    target down, so a worn turbocharger lost boost at every altitude (condition
    0.60 at 18,000 ft: 1.278 -> 0.895 bar). The real boost control is closed
    loop: below its limit the wastegate closes further and HOLDS the target.
    Wear acts in ``solve`` instead, on compressor capability and efficiency, so
    the wastegate closes earlier, the critical altitude drops and the
    compressor runs hotter -- what a worn turbocharger on this engine actually
    shows (review PHY-07).
    """
    turbo = engine["turbocharger"]
    t_5500 = float(turbo.get("target_map_at_5500rpm_bar", turbo["max_boost_abs_bar"]))
    t_5800 = float(turbo.get("target_map_at_5800rpm_bar", turbo["max_boost_abs_bar"]))

    # Speed schedule: linear between the two published points and clamped at
    # the 5800 rpm value above it. Below 5500 rpm the published schedule is
    # silent, and holding 1450 mbar flat over-stated full-throttle plenum
    # pressure by up to 8 %: the manufacturer's performance table prints
    # 1373 mbar at 5000 rpm and 1338 mbar at 4500 rpm (sea level ISA). Where the
    # engine has that table its shape is used, scaled so the published 5500 rpm
    # point is unchanged; below 4500 rpm the 4500 rpm value is held.
    if rpm <= 5500.0:
        p_full = t_5500
        sl = om_table.sea_level_wot_plenum_bar(engine, rpm)
        if sl is not None:
            p_full = t_5500 * sl / om_table.sea_level_wot_plenum_bar(engine, 5500.0)
    else:
        frac = min(1.0, (rpm - 5500.0) / 300.0)
        p_full = t_5500 + (t_5800 - t_5500) * frac

    a = float(np.clip(throttle_pct, 0.0, 100.0)) / 100.0
    # Below roughly a third of lever travel the throttle plate, not the boost
    # controller, sets manifold pressure.
    if a <= 0.35:
        return 1.0 + (1.06 - 1.0) * (a / 0.35)
    frac = (a - 0.35) / 0.65
    p_cont = 1.0 + 0.72 * (p_full - 1.0)
    return float(p_cont + (p_full - p_cont) * frac**2.2)


def _intercooled_temp_k(pr: float, oat_k: float, eta: float, eff: float) -> float:
    """Post-intercooler air temperature for a compressor running at ``pr``."""
    t_out = oat_k * (
        1.0 + (max(pr, 1.0) ** ((GAMMA_AIR - 1.0) / GAMMA_AIR) - 1.0) / max(eta, 0.15)
    )
    return t_out - eff * (t_out - oat_k)


def _table_charge_offset_k(
    pr: float, ambient: Ambient, env: om_table.Envelope, eta_new: float, eff_nominal: float
) -> float:
    """Shift from the intercooler law's AS-NEW temperature to the manufacturer's."""
    as_new_law = _intercooled_temp_k(pr, ambient.oat_k, eta_new, eff_nominal)
    return ambient.oat_k + float(env.mat_rise_k) - as_new_law


def solve(
    *,
    ambient: Ambient,
    rpm: float,
    throttle_pct: float,
    engine: dict,
    turbo_health: float = 1.0,
    previous: TurboState | None = None,
    dt: float = 0.1,
) -> TurboState:
    """Steady or lagged turbocharger state at an operating point.

    ``previous`` and ``dt`` enable the first-order boost lag: PRD Part 3
    section 18.1 CONDITION 4 states boost takes 2-3 s to respond. Passing
    ``previous=None`` returns the steady-state solution.
    """
    turbo = engine.get("turbocharger", {})
    p_amb_bar = ambient.pressure_pa / 1e5

    if not turbo.get("fitted", False):
        return TurboState(
            pressure_ratio=1.0,
            manifold_pressure_bar=p_amb_bar * (0.3 + 0.7 * throttle_pct / 100.0),
            compressor_outlet_temp_k=ambient.oat_k,
            manifold_air_temp_k=ambient.oat_k,
            wastegate_fraction=1.0,
            turbo_speed_rpm=0.0,
            boost_limited=True,
            efficiency=1.0,
        )

    eta_c = float(turbo["efficiency_new"]) * turbo_health
    crit_ft = float(turbo["critical_altitude_ft"])
    target_bar = _target_manifold_bar(throttle_pct, engine, turbo_health, rpm)

    # Compressor capability, expressed as a PRESSURE RATIO.
    #
    # A turbocharger is sized by its critical altitude: it is the altitude at
    # which the compressor, running at its limit, can just still deliver the
    # rated manifold pressure. That single published number therefore fixes the
    # maximum pressure ratio:
    #
    #     PR_max = P_manifold_rated / P_ambient(critical altitude)
    #
    # For the Rotax 914 that is 1.35 bar / 0.644 bar = 2.10. Below the critical
    # altitude the required ratio is lower than PR_max, so the wastegate bleeds
    # exhaust and manifold pressure is held flat at the rating. Above it the
    # wastegate is shut, PR is pinned at PR_max, and manifold pressure falls
    # with ambient -- the "critical altitude knee".
    p_amb_at_crit = _isa_pressure_bar(crit_ft)
    # Size the compressor from the SCHEDULED target at max-continuous speed:
    # the certified claim is that max continuous power is available up to the
    # critical altitude, so the compressor must reach the 5500 rpm target there.
    rated_target = float(
        turbo.get("target_map_at_5500rpm_bar", turbo["max_boost_abs_bar"])
    )
    pr_capability = rated_target / p_amb_at_crit

    # THE MANUFACTURER'S TABLE, where the engine definition has one.
    #
    # Sizing the compressor from the critical altitude alone makes the knee a
    # corner: PR pinned at 1.45 / 0.572 = 2.54 above 15,000 ft, so manifold
    # pressure fell with ambient and read 1.04 bar at 23,000 ft. The Operator's
    # Manual prints 1.29 bar there at 5800 rpm -- a pressure ratio of 3.16 --
    # and a gradual knee: boost held to about 17,000 ft and tapering after
    # (review PHY-01). The table therefore sets
    #   * the plenum pressure at this altitude and temperature, as a ratio to
    #     sea level ISA at the same throttle position (throttled operation
    #     included, not only full throttle),
    #   * the compressor's capability, from the highest ratio it prints,
    #   * whether the lever is asking for more than the turbocharger can give
    #     here -- the honest meaning of "boost limited".
    # The 3 % margin on that last test keeps a hot sea-level day, where the
    # printed plenum pressure sits 2 % under ISA while power is held, from
    # being reported as a turbocharger at its limit.
    env = om_table.NEUTRAL
    limited_by_table = False
    if om_table.table_for(engine) is not None:
        dev = om_table.isa_deviation_c(ambient)
        frac = perf_maps._throttle_factor(throttle_pct, rpm)
        env = om_table.envelope(engine, rpm, frac, ambient.altitude_ft, dev)
        target_bar *= env.plenum
        pr_capability = max(pr_capability, 1.02 * om_table.max_pressure_ratio(engine, rpm))
        demand = (_target_manifold_bar(throttle_pct, engine, 1.0, rpm)
                  / _target_manifold_bar(100.0, engine, 1.0, rpm))
        limited_by_table = 0.97 * demand > om_table.wot_plenum_ratio(
            engine, rpm, ambient.altitude_ft, dev)

    # Exhaust-energy limit at low engine speed (the boost threshold): the
    # turbine cannot spin the compressor to full ratio until the engine is
    # producing enough exhaust enthalpy.
    rpm_ref = float(engine["ratings"]["max_torque_rpm"])
    speed_capability = float(np.clip((rpm / (0.55 * rpm_ref)) ** 1.4, 0.0, 1.0))
    pr_max = 1.0 + (pr_capability - 1.0) * speed_capability * turbo_health

    pr_needed = target_bar / max(p_amb_bar, 1e-6)
    boost_limited = pr_needed > pr_max or limited_by_table
    pr = min(pr_needed, pr_max)
    pr = max(pr, 1.0)

    manifold_bar = pr * p_amb_bar
    # Hard authority limit: the boost controller may transiently reach this in
    # special situations but the engine must never be modelled above it.
    nte = float(turbo.get("map_never_exceed_bar", turbo["max_boost_abs_bar"]))
    if manifold_bar > nte:
        manifold_bar = nte
        pr = manifold_bar / max(p_amb_bar, 1e-6)
    # Wastegate: fully open when far less boost is needed than available.
    if boost_limited:
        wg = 0.0
    else:
        wg = float(np.clip(1.0 - (pr - 1.0) / max(pr_max - 1.0, 1e-6), 0.0, 1.0))

    # Compressor discharge temperature (adiabatic with isentropic efficiency).
    t_out = ambient.oat_k * (
        1.0 + (pr ** ((GAMMA_AIR - 1.0) / GAMMA_AIR) - 1.0) / max(eta_c, 0.15)
    )

    # Turbo speed: scales with the enthalpy rise it must produce.
    n_design = float(turbo["design_speed_rpm"])
    n_turbo = n_design * math.sqrt(
        max(pr - 1.0, 0.0) / max(pr_capability - 1.0, 1e-6)
    )

    # Intercooler: an air-to-air heat exchanger rejecting to ram air.
    #     MAT = T_compressor_out - eff * (T_compressor_out - T_ambient)
    # Effectiveness falls at low airspeed because the core sees less mass flow.
    eff_nominal = float(turbo.get("intercooler_effectiveness", 0.0))
    eff_ic = eff_nominal
    if eff_ic > 0.0:
        eff_ic *= min(1.0, max(0.55, (ambient.airspeed_kmh / 150.0) ** 0.35))
    t_mat = t_out - eff_ic * (t_out - ambient.oat_k)

    # Charge temperature. The intercooler law above put manifold air 12-37 K
    # hotter than the plenum temperatures the manufacturer's table prints,
    # which sit only 4-6 K above ambient at every altitude and throttle
    # position (review PHY-05). Where the table exists it sets the AS-NEW
    # value, and the law above supplies only the departure from as-new -- a
    # worn compressor running hotter, or an intercooler short of ram air at low
    # airspeed -- so those degradation signatures are kept.
    eta_new = float(turbo["efficiency_new"])
    if env.mat_rise_k is not None:
        t_mat += _table_charge_offset_k(pr, ambient, env, eta_new, eff_nominal)

    state = TurboState(
        pressure_ratio=pr,
        manifold_pressure_bar=manifold_bar,
        compressor_outlet_temp_k=t_out,
        manifold_air_temp_k=t_mat,
        wastegate_fraction=wg,
        turbo_speed_rpm=n_turbo,
        boost_limited=boost_limited,
        efficiency=eta_c,
    )

    if previous is None:
        return state

    # First-order lag on manifold pressure and turbo speed. tau ~ 0.9 s gives
    # roughly 2-3 s to reach steady state, matching PRD Part 3 section 18.1.
    tau = 0.9
    alpha = dt / (tau + dt)
    man = previous.manifold_pressure_bar + alpha * (
        state.manifold_pressure_bar - previous.manifold_pressure_bar
    )
    spd = previous.turbo_speed_rpm + alpha * (state.turbo_speed_rpm - previous.turbo_speed_rpm)
    pr_lagged = man / max(p_amb_bar, 1e-6)
    t_out_lagged = ambient.oat_k * (
        1.0 + (max(pr_lagged, 1.0) ** ((GAMMA_AIR - 1.0) / GAMMA_AIR) - 1.0) / max(eta_c, 0.15)
    )
    t_mat_lagged = t_out_lagged - eff_ic * (t_out_lagged - ambient.oat_k)
    if env.mat_rise_k is not None:
        t_mat_lagged += _table_charge_offset_k(pr_lagged, ambient, env, eta_new, eff_nominal)
    # Charge air cannot change temperature instantly: the intercooler core and
    # the plenum have thermal mass (review PHY-10). Without it, once charge air
    # tracked ambient as the manufacturer's table says it should (DEV-228), a
    # flight profile's altitude step moved manifold air temperature 30 K in
    # half a second, and ingest correctly rejected the sensor as implausible.
    tau_air = float(turbo.get("charge_air_time_constant_s", 0.0))
    if tau_air > 0.0:
        a_air = dt / (tau_air + dt)
        t_mat_lagged = previous.manifold_air_temp_k + a_air * (
            t_mat_lagged - previous.manifold_air_temp_k)
    return TurboState(
        pressure_ratio=pr_lagged,
        manifold_pressure_bar=man,
        compressor_outlet_temp_k=t_out_lagged,
        manifold_air_temp_k=t_mat_lagged,
        wastegate_fraction=state.wastegate_fraction,
        turbo_speed_rpm=spd,
        boost_limited=state.boost_limited,
        efficiency=eta_c,
    )


def critical_altitude_report(engine: dict) -> list[tuple[float, float, bool]]:
    """(altitude_ft, manifold_bar, boost_limited) at full throttle -- the knee."""
    from layer2_physics.atmosphere import ambient_at

    out = []
    for ft in range(0, 26000, 2000):
        amb = ambient_at(float(ft))
        st = solve(
            ambient=amb,
            rpm=float(engine["ratings"]["max_power_rpm"]),
            throttle_pct=100.0,
            engine=engine,
        )
        out.append((float(ft), st.manifold_pressure_bar, st.boost_limited))
    return out


if __name__ == "__main__":  # pragma: no cover
    from common import config

    eng = config.load_engine()
    print("alt[ft]  MAP[bar]  wastegate  Tcomp[C]  MAT[C]  N_turbo[rpm]  limited")
    from layer2_physics.atmosphere import ambient_at

    for ft in range(0, 26000, 2000):
        amb = ambient_at(float(ft))
        st = solve(ambient=amb, rpm=5500.0, throttle_pct=100.0, engine=eng)
        print(
            f"{ft:7d}  {st.manifold_pressure_bar:8.3f}  {st.wastegate_fraction:9.2f}"
            f"  {st.compressor_outlet_temp_k - 273.15:8.1f}"
            f"  {st.manifold_air_temp_k - 273.15:6.1f}  {st.turbo_speed_rpm:12.0f}"
            f"  {st.boost_limited}"
        )
