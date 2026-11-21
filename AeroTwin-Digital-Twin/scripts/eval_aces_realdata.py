"""The twin against a REAL Rotax-family engine: NASA's Altus II UAV (2002).

WHAT THIS ANSWERS
-----------------
Every other benchmark in this repository scores the twin against engines the
same physics generated. This one flies the AS-NEW twin along real flights of a
real Rotax 912 (1352 cc, liquid-cooled heads, two-stage turbocharger, EFI) in a
real UAV and reports how far its predictions land from what the engine did.

How it flies the twin (the same way the live twin's shadow model runs):
  * engine speed is locked to the measured rpm every second;
  * throttle is steered by a small feedback loop until the twin's manifold
    pressure matches the measured one -- the Altus throttle-to-boost map is
    its own, so matching BOOST, not lever, puts both engines at the same load;
  * altitude, outside air temperature (from density altitude) and true
    airspeed come from the aircraft;
  * head, coolant and oil temperatures are seeded from the first measurement
    once, then evolve on the twin's own physics.

WHAT TO EXPECT, AND WHY
-----------------------
The Altus engine is a sibling, not a 915 iS: two-stage turbo and intercooler,
its own EFI calibration, its own radiator and cowl flaps. So a CONSTANT offset
per channel is expected and is not a model failure -- it is exactly the
installation difference the twin's per-engine residual reference removes
(rul_serving.ResidualBaseline). The quantities that decide whether the physics
is right are therefore reported separately:
  * offset        mean(predicted - measured) at steady airborne points;
  * scatter       RMS error AFTER removing that offset -- what the twin's
                  residual would still carry on this healthy engine;
  * trend r       correlation of predicted with measured across operating
                  points: does the twin move the right way with power,
                  altitude and airspeed?
It also reports how the REAL sensors behave -- resolution, steady-state noise,
dropouts -- against what the simulator assumes.

No faults are labelled in this data; nothing here trains or tunes a model.

Run:  python scripts/aces_extract.py && python scripts/eval_aces_realdata.py
"""

from __future__ import annotations

import json
import math
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from common import config  # noqa: E402
from layer2_physics import mvem  # noqa: E402
from layer2_physics.atmosphere import air_density, ambient_at  # noqa: E402
from layer2_physics.degradation import DegradationFactors  # noqa: E402

SRC = REPO / "data" / "external" / "aces" / "aces_engine.parquet"
OUT = REPO / "data" / "benchmarks" / "aces_realdata.json"

# (twin output, measured column, unit)
CHANNELS = (
    ("cht_max", "cht_c", "degC"),
    ("coolant_temperature_c", "coolant_c", "degC"),
    ("oil_temperature_c", "oil_temperature_c", "degC"),
    ("oil_pressure_psi", "oil_pressure_psi", "psi"),
    ("egt_max", "egt_max_c", "degC"),
    ("fuel_flow_lph", "fuel_flow_lph", "L/h"),
)
MIN_RPM = 3000.0          # loaded running, where the twin is judged live
MIN_KIAS = 40.0           # airborne
STEADY_S = 60             # a steady point: 60 s with ...
STEADY_RPM = 0.015        # ... rpm within 1.5 %
STEADY_MAP_BAR = 0.03     # ... and boost within 0.03 bar
SUBSTEPS = 2              # 1 Hz data, twin stepped at 0.5 s as it is live


def _twin() -> mvem.MeanValueEngineModel:
    eng = config.load_engine("rotax_915is")
    return mvem.MeanValueEngineModel(engine=eng, engine_key="rotax_915is",
                                     degradation=DegradationFactors.as_new(eng))


def _ambient(row):
    amb = ambient_at(float(row.pressure_alt_ft), humidity_pct=60.0,
                     airspeed_kmh=float(row.airspeed_kmh))
    rho = air_density(amb.pressure_pa, float(row.oat_c) + 273.15, 60.0)
    return replace(amb, oat_c=float(row.oat_c), density_kg_m3=rho)


def fly(flight: pd.DataFrame) -> pd.DataFrame:
    """Run the as-new twin along one real flight; one prediction per second."""
    model = _twin()
    throttle = 50.0
    seeded = False
    preds = []
    for row in flight.itertuples(index=False):
        ok = (np.isfinite(row.rpm) and row.rpm >= MIN_RPM
              and all(np.isfinite(getattr(row, c)) for c in
                      ("map_bar", "pressure_alt_ft", "oat_c", "airspeed_kmh")))
        if not ok:
            preds.append(None)
            continue
        if not seeded:
            model.initialise_warm(_ambient(row), rpm=float(row.rpm))
            for attr, col in (("t_coolant", "coolant_c"), ("t_oil", "oil_temperature_c")):
                v = getattr(row, col)
                if np.isfinite(v):
                    setattr(model, attr, v + 273.15)
            if np.isfinite(row.cht_c):
                model.t_cht[:] = row.cht_c + 273.15
            seeded = True
        amb = _ambient(row)
        out = None
        for _ in range(SUBSTEPS):
            model.omega = float(row.rpm) * 2.0 * math.pi / 60.0
            out = model.step(0.5, throttle_pct=throttle, ambient=amb)
            # Steer throttle so the twin's boost follows the measured boost.
            err = float(row.map_bar) - out.manifold_pressure_bar
            throttle = float(np.clip(throttle + 25.0 * err, 0.0, 100.0))
        # Prefixed: the measured frame already has oil_pressure_psi and
        # fuel_flow_lph, and two columns of one name break the concatenation.
        preds.append({"twin_map_bar": out.manifold_pressure_bar, "twin_throttle": throttle,
                      **{f"twin_{k}": float(getattr(out, k)) for k, _, _ in CHANNELS}})
    rows = [p if p is not None else {} for p in preds]
    return pd.concat([flight.reset_index(drop=True), pd.DataFrame(rows)], axis=1)


def steady_points(df: pd.DataFrame) -> pd.DataFrame:
    """One row per steady, airborne, loaded minute."""
    ok = (df["rpm"] >= MIN_RPM) & (df["kias"] >= MIN_KIAS) & df["twin_cht_max"].notna()
    pts = []
    i = 0
    n = len(df)
    while i + STEADY_S <= n:
        w = df.iloc[i:i + STEADY_S]
        if ok.iloc[i:i + STEADY_S].all():
            r, m = w["rpm"], w["map_bar"]
            if (r.max() - r.min()) <= STEADY_RPM * r.mean() and (m.max() - m.min()) <= STEADY_MAP_BAR:
                pts.append(w.median(numeric_only=True))
                i += STEADY_S
                continue
        i += 10
    return pd.DataFrame(pts)


def sensor_behaviour(df: pd.DataFrame) -> dict:
    """Resolution, steady noise and dropout rate of the real instruments."""
    out = {}
    run = df[df["rpm"] >= MIN_RPM]
    for _, col, unit in CHANNELS:
        v = run[col]
        diffs = np.abs(np.diff(v.dropna().to_numpy()))
        diffs = diffs[diffs > 1e-9]
        # noise: std of 60 s windows after removing each window's linear trend
        resid = []
        arr = v.to_numpy()
        for s in range(0, len(arr) - 60, 60):
            w = arr[s:s + 60]
            if np.isfinite(w).all():
                t = np.arange(60)
                resid.append(np.std(w - np.polyval(np.polyfit(t, w, 1), t)))
        out[col] = {
            "unit": unit,
            "resolution": round(float(np.percentile(diffs, 5)), 3) if len(diffs) else None,
            "steady_noise_sd": round(float(np.median(resid)), 3) if resid else None,
            "dropout_pct": round(100.0 * float(v.isna().mean()), 2),
        }
    return out


def main() -> int:
    if not SRC.exists():
        print(f"{SRC} missing: run scripts/aces_extract.py first")
        return 1
    started = time.time()
    raw = pd.read_parquet(SRC)
    todo = [g for _, g in raw.groupby(["day", "file"], sort=True)
            if (g["rpm"] >= MIN_RPM).sum() >= 300 and (g["kias"] >= MIN_KIAS).sum() >= 300]
    # One flight per process: each is independent, and the twin is ~20 ms a
    # step, so 48 h of flying is an hour and a half on one core.
    from concurrent.futures import ProcessPoolExecutor
    import os
    flights = []
    with ProcessPoolExecutor(max_workers=max(1, min(6, (os.cpu_count() or 2) - 2))) as pool:
        for g, done in zip(todo, pool.map(fly, todo)):
            flights.append(done)
            print(f"  flew {g['day'].iloc[0]}/{g['file'].iloc[0]}: {len(g)} s "
                  f"({time.time() - started:.0f}s)", flush=True)
    both = pd.concat(flights, ignore_index=True)
    pts = steady_points(both)
    print(f"\n{len(flights)} flights, {len(pts)} steady airborne points "
          f"({time.time() - started:.0f}s)\n")

    report = {"engine": "Rotax 912 (Altus II, two-stage turbo, EFI) vs twin rotax_915is as-new",
              "flights": len(flights), "steady_points": int(len(pts)), "channels": {}}
    print(f"{'channel':<22}{'offset':>9}{'scatter':>9}{'trend r':>9}{'measured range':>22}")
    for twin_col, col, unit in CHANNELS:
        twin_col = f"twin_{twin_col}"
        d = pts[[twin_col, col]].dropna()
        if len(d) < 5:
            continue
        err = d[twin_col] - d[col]
        offset = float(err.mean())
        scatter = float(np.sqrt(np.mean((err - offset) ** 2)))
        r = float(np.corrcoef(d[twin_col], d[col])[0, 1]) if d[col].std() > 0 else float("nan")
        report["channels"][col] = {"unit": unit, "n": int(len(d)), "offset": round(offset, 2),
                                   "scatter_after_offset": round(scatter, 2),
                                   "trend_r": round(r, 3),
                                   "measured_min": round(float(d[col].min()), 1),
                                   "measured_max": round(float(d[col].max()), 1)}
        print(f"{col:<22}{offset:>+9.1f}{scatter:>9.2f}{r:>9.2f}"
              f"{d[col].min():>11.1f} - {d[col].max():<8.1f}{unit}")
    report["sensors"] = sensor_behaviour(raw)
    print("\nreal instruments (loaded running):")
    for col, s in report["sensors"].items():
        print(f"  {col:<22} resolution {s['resolution']!s:>7}  steady noise sd "
              f"{s['steady_noise_sd']!s:>7}  dropouts {s['dropout_pct']:>5}%")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2))
    both.to_parquet(SRC.with_name("aces_twin_flown.parquet"))
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
