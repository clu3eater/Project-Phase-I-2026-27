"""The engine model against the manufacturer's performance table -- every printed full-throttle row.

Run:  python scripts/validate_physics_om.py            (about 2 minutes)
      python scripts/validate_physics_om.py --quick    (ISA rows only)

Trims the whole model -- governed propeller, turbocharger, intercooler, fuel
map -- at each full-throttle row the Operator's Manual 915 i Ed.0 Rev.4 prints
(pp.111-130), at the printed speed, altitude and ambient temperature, and
compares power, plenum pressure, charge-air temperature and fuel flow with the
printed values. The rows are read from the CSV here, not through
``layer2_physics.om_table``. Writes ``data/models/physics_om_validation.json``
so a quoted accuracy figure can always be traced to the run that produced it.

WHAT THIS IS AND IS NOT. Since DEV-226 the table is an INPUT to the model's
altitude and temperature behaviour, so agreement here checks that the model
implements it -- through the turbocharger, governor, intercooler and fuel map
-- not that a real engine behaves this way. Independent validation needs rig
data.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402

from common import config  # noqa: E402
from layer2_physics import atmosphere as atm  # noqa: E402
from layer2_physics import mvem  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quick", action="store_true", help="ISA rows only")
    ap.add_argument("--engine", default="rotax_915is")
    args = ap.parse_args()

    engine = config.load_engine(args.engine)
    spec = engine.get("performance_table")
    if not spec:
        print(f"{args.engine} has no manufacturer performance table")
        return 2
    path = config.config_dir() / "engines" / str(spec["file"])
    with path.open(newline="", encoding="utf-8") as fh:
        printed = [r for r in csv.DictReader(fh) if abs(float(r["throttle_pct"]) - 100.0) < 0.05]
    rho_fuel = float(engine["fuel_properties"]["density_kg_per_L"])

    started = time.time()
    rows = []
    for rec in printed:
        rpm = float(rec["rpm"])
        alt = float(rec["alt_ft"])
        oat = float(rec["t_amb_c"])
        dev = oat - atm.ambient_at(alt).oat_c
        if args.quick and abs(dev) > 3.0:
            continue
        amb = atm.ambient_at(alt, isa_deviation_c=dev, airspeed_kmh=180.0)
        model = mvem.build(args.engine)
        out = mvem.trim_to_steady_state(model, throttle_pct=100.0, ambient=amb,
                                        seconds=120.0, dt=0.5, rpm_setpoint=rpm)
        om_p = float(rec["power_kw"])
        om_map = float(rec["p_plenum_bar"])
        om_air = float(rec["t_plenum_k"]) - 273.15
        om_fuel = float(rec["fuel_kg_h"])
        model_air = out.turbo_state.manifold_air_temp_k - 273.15
        model_fuel = out.fuel_flow_lph * rho_fuel
        row = {
            "manual_row": int(float(rec["number"])),
            "pdf_page": int(float(rec["pdf_page"])),
            "rpm": rpm, "altitude_ft": alt, "oat_c": oat,
            "power_kw": [round(out.power_kw, 2), om_p],
            "plenum_bar": [round(out.manifold_pressure_bar, 4), om_map],
            "charge_air_c": [round(model_air, 2), round(om_air, 2)],
            "fuel_kg_h": [round(model_fuel, 2), om_fuel],
            "rpm_model": round(out.rpm, 1),
            "error": {
                "power_pct": round(100.0 * (out.power_kw - om_p) / om_p, 3),
                "plenum_pct": round(100.0 * (out.manifold_pressure_bar - om_map) / om_map, 3),
                "charge_air_k": round(model_air - om_air, 3),
                "fuel_pct": round(100.0 * (model_fuel - om_fuel) / om_fuel, 3),
                # THE SPEED THE ROW WAS ACTUALLY FLOWN AT.
                #
                # Every row commands `rpm_setpoint=rpm`, so the model is being
                # asked to hold the table's speed. `rpm_model` was already
                # recorded here and NOTHING EVER SUMMARISED IT, which is how a
                # governor that misses its setpoint by 673 rpm at 19,000 ft
                # stayed invisible behind a power figure: power scales with
                # speed, so a 13 % overspeed reads as a 50 % power error and
                # gets attributed to the boost model.
                #
                # Reported as its own number, because "the model makes too much
                # power here" and "the model is running 673 rpm fast here" call
                # for completely different investigations.
                "rpm_pct": round(100.0 * (out.rpm - rpm) / rpm, 3),
            },
        }
        rows.append(row)
        e = row["error"]
        print(f"row {row['manual_row']:4d}  {rpm:5.0f} rpm {alt:6.0f} ft {oat:+6.1f} C  "
              f"power {e['power_pct']:+6.2f}%  plenum {e['plenum_pct']:+6.2f}%  "
              f"air {e['charge_air_k']:+5.2f} K  fuel {e['fuel_pct']:+6.2f}%  "
              f"rpm {e['rpm_pct']:+5.1f}%", flush=True)

    def summary(key: str) -> dict:
        v = np.abs(np.array([row["error"][key] for row in rows]))
        return {"median_abs": round(float(np.median(v)), 3),
                "p95_abs": round(float(np.percentile(v, 95)), 3),
                "max_abs": round(float(v.max()), 3)}

    report = {
        "source": "BRP-Rotax Operator's Manual 915 i Ed.0 Rev.4, pp.111-130, full-throttle rows as printed",
        "caveat": "the table is an input to the model since DEV-226; this checks the implementation, "
                  "not independent validation",
        "points": len(rows),
        "quick": bool(args.quick),
        "airspeed_kmh": 180.0,
        # rpm_pct is in this list deliberately. Without it the report said the
        # model was within 1.05 % on power at the median and 44 % at p95, and
        # left a reader to conclude the boost model breaks down at altitude.
        # The actual finding is that the constant-speed governor misses its
        # commanded speed by up to 13 % above 15,000 ft on a cold day, and
        # power follows speed.
        "summary": {k: summary(k) for k in
                    ("power_pct", "plenum_pct", "charge_air_k", "fuel_pct",
                     "rpm_pct")},
        "rows": rows,
        "elapsed_s": round(time.time() - started, 1),
    }
    out_path = config.data_dir() / "models" / "physics_om_validation.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"{len(rows)} printed rows, wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
