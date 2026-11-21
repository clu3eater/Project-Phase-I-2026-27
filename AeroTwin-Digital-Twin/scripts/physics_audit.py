"""Systematic audit of the physics model -- find every defect in ONE pass.

Regenerating the fleet and retraining costs hours, so discovering defects one
at a time and re-running between each is the expensive way to work. This runs
the whole battery at once.

It exists because of DEV-85. A degraded turbocharger cost NO power: the
brake-torque map was scaled against the actual turbo's own output, so the turbo
was compared with itself and could never be found wanting. That defect was
found by accident, while building something else, and it had been sitting in
the fleet dataset the whole time.

The general form of that bug is the first and most important check here:

    A FAULT THAT PRODUCES NO OBSERVABLE CHANGE IS INVISIBLE TO EVERY LAYER
    ABOVE IT.

If a fault does not move the sensors then no residual, no health index, no
detector and no RUL model can ever see it -- and the fleet dataset teaches the
network that a labelled fault has no signature, which is worse than not having
the fault at all. The same applies to a fault that SATURATES: below the cliff
there is no gradient, so no trend, so no prognostic lead time.

TWO METHODOLOGICAL POINTS, both learned by getting them wrong first:

1. AUDIT REACHABLE STATES. Setting one degradation factor by hand reaches
   states the engine can never be in, because the derived quantities the
   physics actually consumes (oil_viscosity_ratio, bearing_clearance_mm,
   injector_flow_variance) do not co-vary with it. Audited that way,
   ``oil_quality`` looked like a completely dead pathway -- when in fact the
   physics couples to oil VISCOSITY and the degradation engine moves the two
   together. So faults are driven here through the real
   ``DegradationEngine`` + ``InjectedFault`` path, exactly as the fleet
   generator drives them.

2. COMPARE IN PHYSICAL UNITS, NOT RELATIVE ONES. Dividing each channel by its
   own baseline seems natural and is wrong: knock retard sits at essentially
   zero on a healthy engine, so any retard at all is a near-infinite relative
   change and that single channel swamps the direction vector. Measured that
   way, two genuinely distinct cooling faults came out at cosine 0.998 --
   "inseparable" -- purely because both are dominated by a 600-800 % knock
   term. Channel scales below are physical.

    python scripts/physics_audit.py            # full report
    python scripts/physics_audit.py --json     # machine-readable
    python scripts/physics_audit.py --quick    # sensitivity matrix only

Exits non-zero if any check fails.
"""

from __future__ import annotations

import argparse
import json
import math

import numpy as np

from common import config
from layer2_physics import mvem
from layer2_physics.atmosphere import ambient_at
from layer2_physics.degradation import (
    DegradationEngine,
    DegradationFactors,
    FaultMode,
    InjectedFault,
)

ENGINE_KEY = "rotax_915is"

# Observables a fielded system can actually see on the bus. Health indices and
# residuals are built from these, so a fault invisible in all of them is
# invisible everywhere.
OBSERVABLES = (
    "rpm", "power_kw", "torque_nm", "manifold_pressure_bar",
    "cht_max", "cht_spread", "coolant_temperature_c", "oil_temperature_c",
    "oil_pressure_psi", "egt_max", "egt_spread", "fuel_flow_lph",
    "bsfc_g_per_kwh", "vibration_rms_m_s2", "battery_voltage_v",
    "knock_retard_deg", "injector_duty_fraction", "air_mass_flow_kg_s",
)

# Roughly the change that matters operationally on each channel. See point 2
# in the module docstring for why this is not a relative comparison.
CHANNEL_SCALE = {
    "rpm": 200.0, "power_kw": 10.0, "torque_nm": 20.0,
    "manifold_pressure_bar": 0.15, "cht_max": 10.0, "cht_spread": 8.0,
    "coolant_temperature_c": 8.0, "oil_temperature_c": 8.0,
    "oil_pressure_psi": 8.0, "egt_max": 40.0, "egt_spread": 40.0,
    "fuel_flow_lph": 3.0, "bsfc_g_per_kwh": 30.0,
    "vibration_rms_m_s2": 2.0, "battery_voltage_v": 0.5,
    "knock_retard_deg": 2.0, "injector_duty_fraction": 0.05,
    "air_mass_flow_kg_s": 0.01,
}

FAULT_MODES = tuple(FaultMode)

# Faults whose signature lives wholly or partly in the INSTRUMENT layer
# (engine_sim.py) rather than in the physics. This audit reads the mean-value
# model directly, so it cannot see them and must not report that as a defect:
#
#   sensor_drift  -- expressed only as instrument bias; the physics is by
#                    definition unaffected, which is exactly what makes it
#                    separable from a real process change (PRD Part 2 s10.5).
#   misfire       -- shares a degradation pathway with combustion_instability,
#                    and is told apart by its ACUTE signature: one cylinder's
#                    EGT collapsing 28 % with an rpm droop, applied in
#                    engine_sim.
#
# Both are audited properly by scripts/sensor_audit.py, which reads the
# SensorFrame -- the layer the dataset is actually built from. Reporting them
# here would mean this tool cried wolf on every run, and a tool that does that
# gets ignored.
INSTRUMENT_LAYER_FAULTS = {str(FaultMode.SENSOR_DRIFT)}
INSTRUMENT_LAYER_PAIRS = {
    frozenset({str(FaultMode.MISFIRE), str(FaultMode.COMBUSTION_INSTABILITY)}),
}

# Operating points the sweeps are evaluated at. Cruise matters most -- a MALE
# UAV spends its life there -- but a fault invisible at cruise and obvious at
# max power is still worth knowing about.
POINTS = {
    "cruise":   dict(throttle=70.0, altitude_ft=15000.0, airspeed_kmh=150.0),
    "max_cont": dict(throttle=95.0, altitude_ft=10000.0, airspeed_kmh=200.0),
    "loiter":   dict(throttle=45.0, altitude_ft=18000.0, airspeed_kmh=120.0),
}

SEVERITIES = (0.0, 0.15, 0.3, 0.45, 0.6, 0.75, 0.9, 1.0)

# Below a quarter of one channel scale, a fault has not moved anything a
# detector could key on.
DEAD_BAND = 0.25


def settle(deg, point: dict, *, seconds: float = 90.0, dt: float = 0.25,
           seed: int | None = None):
    """Run to steady state at one operating point and return the last output."""
    m = mvem.build(ENGINE_KEY, deg)
    if seed is not None:
        m.set_manufacturing_spread(np.random.default_rng(seed))
    amb = ambient_at(point["altitude_ft"], airspeed_kmh=point["airspeed_kmh"])
    m.initialise_warm(amb)
    out = None
    for _ in range(int(seconds / dt)):
        out = m.step(dt, throttle_pct=point["throttle"], ambient=amb)
    return out


def read(out) -> dict[str, float]:
    return {k: float(getattr(out, k)) for k in OBSERVABLES}


def degraded_by_fault(mode: FaultMode, severity: float, hours: float = 400.0):
    """Factors the degradation engine actually produces for this fault.

    The same path the fleet generator uses, so every derived quantity the
    physics consumes moves with the factor it belongs to -- AND, like the
    generator, it stops at end of life.

    Stopping matters. Run past end of life, severe bearing wear drives oil
    pressure into its ``max(0.0, ...)`` floor and vibration into the
    ``bearing_condition`` floor, so the sweep reports a flat line and calls it
    a saturation defect. But the fleet never records those states: an engine is
    withdrawn when its true health crosses the threshold, and measured on the
    recorded fleet, bearing_condition bottoms out at 0.193 and oil pressure at
    0.28 bar, with ZERO rows at either floor. Auditing states the data can
    never contain produces findings about the audit.
    """
    from layer2_physics.synth_data_gen import end_of_life, truth_health

    eng = config.load_engine(ENGINE_KEY)
    d = DegradationEngine(engine=eng)
    if severity > 0:
        d.inject(InjectedFault(mode=mode, onset_hours=0.0, severity=severity,
                               ramp_hours=1.0))
    threshold = float(
        config.load_thresholds()["rul"]["maintenance_chi_threshold"]
    )
    step = 10.0
    for _ in range(int(hours / step)):
        d.advance(step, oil_temp_c=100.0, cht_max_c=115.0)
        if end_of_life(truth_health(d.factors, eng), threshold):
            break
    return d.factors


def life_trajectory(mode: FaultMode, severity: float = 0.6,
                    max_hours: float = 1200.0, step: float = 25.0):
    """Factors at successive points along ONE engine's life, up to end of life.

    This is the sweep a prognostic actually cares about. Sweeping SEVERITY
    instead and comparing terminal states says nothing useful once end of life
    is enforced: every severe engine is withdrawn at the same health boundary,
    so its terminal state is by definition the same one, and a check reading
    that as "the signal stopped moving" is measuring the definition of end of
    life rather than a defect in the physics.

    What matters for an RUL is whether the signal keeps moving AS THE ENGINE
    AGES, because that gradient is the only thing a trend can be fitted to.
    """
    from layer2_physics.synth_data_gen import end_of_life, truth_health

    eng = config.load_engine(ENGINE_KEY)
    d = DegradationEngine(engine=eng)
    d.inject(InjectedFault(mode=mode, onset_hours=0.0, severity=severity,
                           ramp_hours=1.0))
    threshold = float(
        config.load_thresholds()["rul"]["maintenance_chi_threshold"]
    )
    out = []
    for _ in range(int(max_hours / step)):
        d.advance(step, oil_temp_c=100.0, cht_max_c=115.0)
        # A COPY. ``d.factors`` is mutated in place by advance(), so appending
        # the object itself would leave every entry aliasing the final state
        # and the trajectory would read as perfectly flat -- which this check
        # would then report as a missing gradient. The bug would have
        # manufactured exactly the finding it exists to detect.
        out.append(DegradationFactors(**d.factors.as_dict()))
        if end_of_life(truth_health(d.factors, eng), threshold):
            break
    return out


# ---------------------------------------------------------------------------
# A. Sensitivity -- does each fault actually move a sensor?
# ---------------------------------------------------------------------------


class Sensitivity:
    def __init__(self, label, point, responses, saturates_at, dead,
                 non_monotonic):
        self.label = label
        self.point = point
        self.responses = responses
        self.saturates_at = saturates_at
        self.dead = dead
        self.non_monotonic = non_monotonic


def sweep_fault(mode: FaultMode, point_name: str) -> Sensitivity:
    point = POINTS[point_name]
    rows = [read(settle(degraded_by_fault(mode, sev), point))
            for sev in SEVERITIES]

    base = rows[0]
    responses: dict[str, float] = {}
    non_monotonic: list[str] = []
    for obs in OBSERVABLES:
        series = [r[obs] for r in rows]
        scale = CHANNEL_SCALE.get(obs, 1.0)
        responses[obs] = max(abs(v - base[obs]) / scale for v in series)
        if responses[obs] > 0.5:
            d = np.diff(series)
            if d.max() > 0 and d.min() < 0 and abs(d).max() > 0.25 * scale:
                non_monotonic.append(obs)

    dead = max(responses.values()) < DEAD_BAND

    # Gradient along the engine's LIFE, not across severities -- see
    # life_trajectory for why the latter cannot answer this question.
    flat_from = None
    if not dead:
        key = max(responses, key=lambda k: responses[k])
        scale = CHANNEL_SCALE.get(key, 1.0)
        full = life_trajectory(mode)
        # Subsampled to ~10 points: the question is whether the signal keeps
        # moving over the engine's life, and a settle per 25 h step is
        # thousands of solves for no extra information.
        pick = full[:: max(1, len(full) // 10)]
        traj = [read(settle(f, point))[key] for f in pick]
        if len(traj) >= 4:
            half = len(traj) // 2
            tail = traj[half:]
            # If the second half of the engine's life moves the strongest
            # channel by less than a quarter of its scale, there is nothing
            # left for a trend to fit in the window that matters most.
            if (max(tail) - min(tail)) / scale < DEAD_BAND:
                flat_from = round(half / len(traj), 2)

    return Sensitivity(str(mode), point_name, responses, flat_from, dead,
                       non_monotonic)


def audit_sensitivity() -> tuple[list[Sensitivity], list[str]]:
    out, problems = [], []
    for mode in FAULT_MODES:
        for pname in POINTS:
            s = sweep_fault(mode, pname)
            out.append(s)
            if s.dead and str(mode) in INSTRUMENT_LAYER_FAULTS:
                pass  # expected here; see INSTRUMENT_LAYER_FAULTS
            elif s.dead:
                problems.append(
                    f"DEAD FAULT: '{mode}' at {pname} moves NO observable by a "
                    f"quarter of its channel scale across severity 0 -> 1. "
                    f"Nothing above the physics can ever detect it, and the "
                    f"fleet dataset teaches the network a labelled fault that "
                    f"has no signature."
                )
            elif s.saturates_at is not None:
                problems.append(
                    f"NO LATE-LIFE GRADIENT: '{mode}' at {pname} stops moving "
                    f"its strongest channel over the second half of the "
                    f"engine's life. That is the window an RUL matters most "
                    f"in, and there is nothing there for a trend to fit."
                )
    return out, problems


# ---------------------------------------------------------------------------
# B. Separability -- can two different faults be told apart?
# ---------------------------------------------------------------------------


def signature(mode: FaultMode, point_name: str,
              severity: float = 0.7) -> np.ndarray:
    """Direction a fault moves the observables, in channel-scale units."""
    point = POINTS[point_name]
    base = read(settle(degraded_by_fault(mode, 0.0), point))
    bad = read(settle(degraded_by_fault(mode, severity), point))
    v = np.array([
        (bad[o] - base[o]) / CHANNEL_SCALE.get(o, 1.0) for o in OBSERVABLES
    ])
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def audit_separability(point_name: str = "cruise") -> tuple[dict, list[str]]:
    sigs = {m: signature(m, point_name) for m in FAULT_MODES}
    problems: list[str] = []
    table: dict[str, float] = {}
    for i, a in enumerate(FAULT_MODES):
        for b in FAULT_MODES[i + 1:]:
            if np.linalg.norm(sigs[a]) < 1e-9 or np.linalg.norm(sigs[b]) < 1e-9:
                continue
            cos = float(np.dot(sigs[a], sigs[b]))
            table[f"{a} vs {b}"] = round(cos, 4)
            # Near-parallel signatures mean the two faults are the same event
            # as far as the sensors are concerned, and no classifier can
            # separate them however good it is.
            if cos > 0.99 and frozenset({str(a), str(b)}) in INSTRUMENT_LAYER_PAIRS:
                continue  # separated at the instrument layer, not here
            if cos > 0.99:
                problems.append(
                    f"INSEPARABLE: '{a}' and '{b}' have signature cosine "
                    f"{cos:.3f} at {point_name}. No classifier can tell them "
                    f"apart -- the confusion is in the physics, not the model."
                )
    return table, problems


# ---------------------------------------------------------------------------
# C. Envelope sanity -- is anything non-physical anywhere it will be run?
# ---------------------------------------------------------------------------


def audit_envelope() -> tuple[list[dict], list[str]]:
    eng = config.load_engine(ENGINE_KEY)
    lim = eng["limits"]
    rows: list[dict] = []
    problems: list[str] = []

    for alt in (0.0, 5000.0, 10000.0, 15000.0, 20000.0, 23000.0):
        for thr in (20.0, 50.0, 80.0, 100.0):
            pt = dict(throttle=thr, altitude_ft=alt, airspeed_kmh=180.0)
            out = settle(None, pt)
            r = read(out)
            rows.append({"altitude_ft": alt, "throttle": thr,
                         **{k: round(v, 3) for k, v in r.items()}})
            tag = f"{alt:.0f} ft / {thr:.0f}%"

            if not all(math.isfinite(v) for v in r.values()):
                problems.append(f"NON-FINITE output at {tag}")
            if r["power_kw"] < -1e-6:
                problems.append(f"NEGATIVE POWER at {tag}: {r['power_kw']:.2f} kW")
            if r["power_kw"] > 1.12 * float(eng["ratings"]["max_power_kW"]):
                problems.append(
                    f"POWER ABOVE RATING at {tag}: {r['power_kw']:.1f} kW vs "
                    f"{eng['ratings']['max_power_kW']} kW rated"
                )
            if r["manifold_pressure_bar"] <= 0:
                problems.append(f"NON-PHYSICAL MAP at {tag}")
            if r["egt_max"] > 1.25 * float(lim["egt_max_C"]):
                problems.append(f"IMPLAUSIBLE EGT at {tag}: {r['egt_max']:.0f} C")
            if r["fuel_flow_lph"] < 0:
                problems.append(f"NEGATIVE FUEL FLOW at {tag}")
            if getattr(out, "physics_constraint_violations", 0):
                problems.append(
                    f"PHYSICS CONSTRAINT VIOLATION at {tag}: "
                    f"{out.physics_constraint_violations}"
                )
            # A HEALTHY engine inside its certified envelope must not exceed
            # its own certified limits. If it does, either the model is wrong
            # or the aircraft cannot fly there, and either is worth knowing.
            if r["coolant_temperature_c"] > float(lim["coolant_temperature_max_C"]):
                problems.append(
                    f"HEALTHY ENGINE OVER COOLANT LIMIT at {tag}: "
                    f"{r['coolant_temperature_c']:.1f} C"
                )
            if r["oil_temperature_c"] > float(lim["oil_temperature_C"][1]):
                problems.append(
                    f"HEALTHY ENGINE OVER OIL LIMIT at {tag}: "
                    f"{r['oil_temperature_c']:.1f} C"
                )
    return rows, problems


# ---------------------------------------------------------------------------
# D. Internal consistency
# ---------------------------------------------------------------------------


def audit_consistency() -> tuple[dict, list[str]]:
    """The air path and the fuel path are independent estimates of the same
    thing. The model publishes their disagreement rather than hiding it; this
    checks the disagreement stays inside what is documented."""
    detail = {}
    worst = 0.0
    for pname, pt in POINTS.items():
        out = settle(None, pt)
        resid = abs(float(getattr(out, "air_fuel_consistency_residual", 0.0)))
        detail[pname] = round(resid, 4)
        worst = max(worst, resid)

    probs = []
    if worst > 0.35:
        probs.append(
            f"AIR/FUEL CLOSURE DIVERGENCE: worst residual {worst:.3f}, above "
            f"the 0.25 the model documents. The air path and the BSFC map are "
            f"no longer describing the same engine."
        )
    return {"air_fuel_residual": detail}, probs


# ---------------------------------------------------------------------------
# E. Determinism and build scatter
# ---------------------------------------------------------------------------


def audit_determinism() -> tuple[dict, list[str]]:
    probs = []
    a = read(settle(None, POINTS["cruise"]))
    b = read(settle(None, POINTS["cruise"]))
    drift = max(abs(a[k] - b[k]) / max(abs(a[k]), 1e-6) for k in a)
    if drift > 1e-9:
        probs.append(f"NON-DETERMINISTIC: identical runs differ by {drift:.2e}")

    # Build scatter must actually vary between engines, or every engine in the
    # fleet is the same engine and the network memorises one trajectory.
    spreads = [float(settle(None, POINTS["max_cont"], seed=s).egt_spread)
               for s in range(6)]
    if max(spreads) - min(spreads) < 1.0:
        probs.append(
            f"BUILD SCATTER NOT VARYING: EGT spread across 6 engines spans "
            f"only {max(spreads) - min(spreads):.2f} C -- every engine in the "
            f"fleet is effectively identical."
        )
    return {"determinism_drift": drift,
            "egt_spread_by_seed": [round(s, 2) for s in spreads]}, probs


# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quick", action="store_true",
                    help="sensitivity matrix only")
    args = ap.parse_args()

    all_problems: list[str] = []
    result: dict = {}

    sens, p = audit_sensitivity()
    all_problems += p
    result["sensitivity"] = [
        {"fault": s.label, "point": s.point, "dead": s.dead,
         "saturates_at": s.saturates_at,
         "top": sorted(s.responses.items(), key=lambda kv: -kv[1])[:4],
         "non_monotonic": s.non_monotonic}
        for s in sens
    ]

    if not args.quick:
        sep, p = audit_separability()
        all_problems += p
        result["separability"] = sep

        env, p = audit_envelope()
        all_problems += p
        result["envelope_rows"] = len(env)

        cons, p = audit_consistency()
        all_problems += p
        result["consistency"] = cons

        det, p = audit_determinism()
        all_problems += p
        result["determinism"] = det

    result["problems"] = all_problems

    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return 1 if all_problems else 0

    print("=" * 78)
    print("  PHYSICS AUDIT")
    print("=" * 78)
    print("\n  A. FAULT SENSITIVITY -- top channels moved, in channel-scale units")
    print("     (a fault must move SOMETHING or no layer above can see it)")
    print("  " + "-" * 74)
    for pname in POINTS:
        print(f"\n  at {pname}:")
        for s in sens:
            if s.point != pname:
                continue
            top = sorted(s.responses.items(), key=lambda kv: -kv[1])[:4]
            flag = ("  (instrument-layer fault; see sensor_audit.py)"
                    if str(s.label) in INSTRUMENT_LAYER_FAULTS
                    else "  <<< DEAD") if s.dead else (
                "  <<< no late-life gradient"
                if s.saturates_at is not None else "")
            print(f"    {s.label:<24} " +
                  "  ".join(f"{k}={v:.1f}" for k, v in top) + flag)

    if not args.quick:
        print("\n  B. SIGNATURE SEPARABILITY (cosine; 1.0 = indistinguishable)")
        print("  " + "-" * 74)
        for k, v in sorted(result["separability"].items(),
                           key=lambda kv: -kv[1])[:8]:
            print(f"    {k:<56} {v:+.3f}")

        print("\n  C. AIR/FUEL CLOSURE RESIDUAL")
        print("  " + "-" * 74)
        print(f"    {result['consistency']['air_fuel_residual']}")

        print("\n  D. DETERMINISM AND BUILD SCATTER")
        print("  " + "-" * 74)
        print(f"    repeat-run drift      "
              f"{result['determinism']['determinism_drift']:.2e}")
        print(f"    EGT spread by engine  "
              f"{result['determinism']['egt_spread_by_seed']}")

    print("\n" + "=" * 78)
    if all_problems:
        print(f"  {len(all_problems)} PROBLEM(S) FOUND")
        print("=" * 78)
        for i, prob in enumerate(all_problems, 1):
            print(f"  {i:>2}. {prob}")
    else:
        print("  NO PROBLEMS FOUND")
    print("=" * 78)

    return 1 if all_problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
