"""Fault audit at the SENSOR layer -- the data path the dataset actually comes from.

``physics_audit.py`` drives the mean-value model directly. That misses half the
system, because faults act in TWO places:

  * slow wear, through the degradation factors, which the MVEM consumes;
  * acute and instrument effects, in ``engine_sim.py`` -- a misfiring
    cylinder's own EGT collapse and rpm droop, and sensor bias drift, which is
    applied to the INSTRUMENT and never touches the physics at all.

Audited at the MVEM only, ``sensor_drift`` looks completely dead and ``misfire``
looks identical to ``combustion_instability``. Both conclusions are artifacts of
reading the wrong layer. What the fleet dataset records is the ``SensorFrame``,
so that is what has to be audited.

Method: two identical engines, same seed, same flight profile, one with a fault
injected. Because the seed is shared, sensor noise is common-mode and every
difference between the two frames is the fault. That is a far more sensitive
test than comparing against a separately-drawn healthy engine.

    python scripts/sensor_audit.py
    python scripts/sensor_audit.py --json

Exits non-zero if any fault is undetectable or indistinguishable from another.
"""

from __future__ import annotations

import argparse
import json

import numpy as np

from layer2_physics.degradation import FaultMode, InjectedFault
from layer2_physics.engine_sim import (
    PHASE_CLIMB,
    PHASE_CRUISE,
    FlightPhase,
    VirtualEngine,
)

ENGINE_KEY = "rotax_915is"

# Scalar channels a detector can key on, with the physical scale that matters
# on each. List channels (per-cylinder CHT/EGT, the vibration triad) are
# reduced to max/spread below, since that is what the feature builder does.
CHANNEL_SCALE = {
    "rpm": 200.0,
    "coolant_temperature_c": 8.0,
    "oil_pressure_bar": 0.5,
    "oil_temperature_c": 8.0,
    "fuel_flow_lph": 3.0,
    "manifold_pressure_bar": 0.15,
    "manifold_air_temp_c": 10.0,
    "fuel_pressure_bar": 0.3,
    "vibration_kurtosis": 1.0,
    "battery_voltage_v": 0.5,
    "injector_duty": 0.05,
    "knock_intensity": 0.5,
    "knock_retard_deg": 2.0,
    "air_flow_g_per_min": 60.0,
    "cht_max": 10.0,
    "cht_spread": 8.0,
    "egt_max": 40.0,
    "egt_spread": 40.0,
    "vib_max": 2.0,
}

DEAD_BAND = 0.25          # channel-scale units
INSEPARABLE_COSINE = 0.99

# WHICH DRIFT CHANNELS ARE OBSERVABLE AT ALL (Stage 1.2).
#
# A sensor drift is detected as a disagreement between the instrument and the
# physics. That only works if the drift is larger than the physics model's own
# error on the channel. Measured on healthy engines, shadow-model RMSE against
# the drift magnitude at median severity:
#
#     oil_temperature      1.257 vs 3.500   SNR 2.78   observable
#     coolant_temperature  1.375 vs 3.250   SNR 2.36   observable
#     manifold_pressure    0.041 vs 0.045   SNR 1.11   observable
#     cht                  4.245 vs 4.500   SNR 1.06   observable
#     egt                 21.362 vs 19.000  SNR 0.89   marginal
#     fuel_flow            1.456 vs 0.650   SNR 0.45   NOT observable
#     oil_pressure        14.782 vs 3.989   SNR 0.27   NOT observable
#     rpm                  -- no residual exists --    NOT observable
#
# The last three are not detector failures. On two of them the physics error
# exceeds the fault; on rpm the shadow model is DRIVEN by the measured speed
# (shadow_model.py: omega = rpm * 2pi/60), so measured minus predicted is
# identically zero and no residual can exist by construction.
#
# Reporting a single sensor_drift F1 across all eight channels therefore mixes
# a solvable problem with an unsolvable one. The unobservable channels are
# named, not quietly dropped.
UNOBSERVABLE_DRIFT = {
    "oil_pressure": "physics RMSE 14.78 exceeds the 3.99 drift (SNR 0.27)",
    "fuel_flow": "physics RMSE 1.46 exceeds the 0.65 drift (SNR 0.45)",
    "rpm": "shadow model is driven BY measured rpm; residual is identically 0",
}
MARGINAL_DRIFT = {"egt": "SNR 0.89 -- detectable only at high severity"}


def _profile() -> list[FlightPhase]:
    """A short cruise-dominated sortie, held long enough to settle."""
    return [
        FlightPhase("CLIMB", 200.0, 85.0, 8000.0, 150.0, PHASE_CLIMB),
        FlightPhase("CRUISE", 900.0, 70.0, 15000.0, 150.0, PHASE_CRUISE),
    ]


def _scalars(f) -> dict[str, float]:
    """Reduce a SensorFrame to the scalar channels a detector sees."""
    out: dict[str, float] = {}
    for k in ("rpm", "coolant_temperature_c", "oil_pressure_bar",
              "oil_temperature_c", "fuel_flow_lph", "manifold_pressure_bar",
              "manifold_air_temp_c", "fuel_pressure_bar", "vibration_kurtosis",
              "battery_voltage_v", "injector_duty", "knock_intensity",
              "knock_retard_deg", "air_flow_g_per_min"):
        v = getattr(f, k, None)
        out[k] = float(v) if v is not None else float("nan")

    cht = [v for v in f.cht_c if v is not None]
    egt = [v for v in f.egt_c if v is not None]
    vib = [v for v in f.vibration_rms if v is not None]
    out["cht_max"] = max(cht) if cht else float("nan")
    out["cht_spread"] = (max(cht) - min(cht)) if cht else float("nan")
    out["egt_max"] = max(egt) if egt else float("nan")
    out["egt_spread"] = (max(egt) - min(egt)) if egt else float("nan")
    out["vib_max"] = max(vib) if vib else float("nan")
    return out


def run(mode: FaultMode | None, severity: float, *, seed: int = 7,
        hours_before: float = 300.0, samples: int = 240) -> dict[str, float]:
    """Mean sensor frame over the settled tail of a sortie.

    ``hours_before`` puts the engine at a realistic mid-life state so the fault
    is added to an engine that has already worn, which is the situation the
    dataset contains -- not a fault on a factory-fresh engine.
    """
    ve = VirtualEngine(engine_key=ENGINE_KEY, seed=seed,
                       initial_flight_hours=hours_before)
    ve.set_profile(_profile())
    if mode is not None and severity > 0:
        ve.inject(InjectedFault(mode=mode, onset_hours=0.0, severity=severity,
                                ramp_hours=0.01))
    # Advanced for BOTH the faulted and the healthy engine, so the two differ
    # only by the fault. Advancing only the faulted one added 50 hours of
    # ordinary wear to every delta: measured, four unrelated faults all moved
    # air flow by exactly -0.32, which was not the faults at all but the
    # baseline wear they had in common.
    ve.degradation.advance(50.0, oil_temp_c=100.0, cht_max_c=115.0)

    acc: list[dict[str, float]] = []
    n = int((_profile()[0].duration_s + _profile()[1].duration_s) / 0.1)
    for i in range(n):
        f = ve.step(0.1)
        if i >= n - samples:
            acc.append(_scalars(f))
    keys = acc[0].keys()
    return {k: float(np.nanmean([a[k] for a in acc])) for k in keys}


_BASE: dict[str, float] | None = None


def healthy() -> dict[str, float]:
    """The shared healthy reference, computed once.

    Recomputing it per fault is deterministic and gives the same answer, but it
    doubles the cost of the audit for nothing -- and this audit is meant to be
    cheap enough to run before every regeneration.
    """
    global _BASE
    if _BASE is None:
        _BASE = run(None, 0.0)
    return _BASE


def delta(mode: FaultMode, severity: float = 0.8) -> dict[str, float]:
    """Fault minus healthy, in channel-scale units, with noise common-mode."""
    base = healthy()
    bad = run(mode, severity)
    return {k: (bad[k] - base[k]) / CHANNEL_SCALE.get(k, 1.0)
            for k in base if not (np.isnan(base[k]) or np.isnan(bad[k]))}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    problems: list[str] = []
    deltas: dict[str, dict[str, float]] = {}

    for mode in FaultMode:
        d = delta(mode)
        deltas[str(mode)] = {k: round(v, 3) for k, v in d.items()}
        strongest = max(abs(v) for v in d.values())
        if strongest < DEAD_BAND:
            problems.append(
                f"DEAD FAULT AT THE SENSORS: '{mode}' at severity 0.8 moves no "
                f"channel by {DEAD_BAND} of its scale. The fleet dataset "
                f"labels these windows as this fault while the telemetry is "
                f"indistinguishable from a healthy engine, so the network is "
                f"being taught to fit noise."
            )

    # Separability at the sensor layer.
    names = [str(m) for m in FaultMode]
    keys = sorted(set.intersection(*(set(deltas[n]) for n in names)))
    vecs = {}
    for n in names:
        v = np.array([deltas[n][k] for k in keys])
        nn = np.linalg.norm(v)
        vecs[n] = v / nn if nn > 1e-12 else v

    cosines: dict[str, float] = {}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if np.linalg.norm(vecs[a]) < 1e-9 or np.linalg.norm(vecs[b]) < 1e-9:
                continue
            c = float(np.dot(vecs[a], vecs[b]))
            cosines[f"{a} vs {b}"] = round(c, 4)
            if c > INSEPARABLE_COSINE:
                problems.append(
                    f"INSEPARABLE AT THE SENSORS: '{a}' and '{b}' move the "
                    f"telemetry in the same direction (cosine {c:.3f}). A "
                    f"classifier asked to separate them is being asked to do "
                    f"something the data does not support."
                )

    result = {"deltas": deltas, "cosines": cosines, "problems": problems}
    if args.json:
        print(json.dumps(result, indent=2))
        return 1 if problems else 0

    print("=" * 78)
    print("  SENSOR-LAYER FAULT AUDIT (the data path the dataset comes from)")
    print("=" * 78)
    print("\n  Strongest channels moved, in channel-scale units, severity 0.8")
    print("  " + "-" * 74)
    for n in names:
        top = sorted(deltas[n].items(), key=lambda kv: -abs(kv[1]))[:5]
        strongest = max(abs(v) for v in deltas[n].values())
        flag = "  <<< DEAD" if strongest < DEAD_BAND else ""
        print(f"  {n:<24} " +
              "  ".join(f"{k}={v:+.2f}" for k, v in top) + flag)

    print("\n  Signature separability (cosine; 1.0 = indistinguishable)")
    print("  " + "-" * 74)
    for k, v in sorted(cosines.items(), key=lambda kv: -kv[1])[:8]:
        print(f"    {k:<56} {v:+.3f}")

    print("\n" + "=" * 78)
    if problems:
        print(f"  {len(problems)} PROBLEM(S) FOUND")
        print("=" * 78)
        for i, p in enumerate(problems, 1):
            print(f"  {i:>2}. {p}")
    else:
        print("  NO PROBLEMS FOUND")
    print("=" * 78)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
