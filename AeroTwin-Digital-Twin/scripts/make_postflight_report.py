"""Generate the demonstration post-flight report from the running twin.

Flies one simulated Rotax 915 iS through a short history of sorties and one
reported sortie with faults injected in flight, then exports the post-flight
report of that last sortie through the same code the console's export uses
(twin_api.mission_report -> report_pdf.build). Nothing in the document is
typed in: every figure comes from the pipeline flying the engine.

The earlier sorties exist for Section 8 (trend over recent flights), which is
built from earlier flights of the same engine. Their start hours are fixed in
advance, so all flights run IN PARALLEL on separate cores and the result is
the same as flying them one after another.

    python scripts/make_postflight_report.py
    python scripts/make_postflight_report.py --export-only   (rebuild the PDF)

Set OMP_NUM_THREADS=1 (and MKL/OPENBLAS the same) before running it. Each
sortie is its own process and torch otherwise starts a thread pool per process,
which oversubscribes the machine and costs more than the flying does. Expect
around twenty minutes of wall clock: the history sorties are 1.34 h of
simulated flight each and run at roughly thirty times real time.

Run data goes to its own directory, never the station's data/ folder:
demonstration flights must not enter a real engine's history.
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

ENGINE = "rotax_915is"
TWIN_ID = "ENG-915-DEMO"
AIRCRAFT = "MALE-DEMO-01"
START_HOURS = 412.0          # engine hours since overhaul at the first recorded flight
MONTHS_INSTALLED = 14.0
# Six earlier flights with a 1.2 h cruise each: Section 8 quotes a drift rate
# only once the comparable flights span 5 flight hours (twin_api
# _MIN_TREND_SPAN_H), and three 13-minute sorties spanned 0.22 h.
N_PRIOR = 6
FINAL_CRUISE_H = 1200.0 / 3600.0
SEED = 915

# The earlier sorties: the standard patrol profile's settings with shorter
# phases. The cruise leg is identical, so every datum is comparable with the
# baseline flight's -- which is what the trend requires.
SHORT_PHASES = [
    ("GROUND", 20.0, 12.0, 0.0, 0.0, "PHASE_GROUND"),
    ("TAXI", 20.0, 20.0, 0.0, 20.0, "PHASE_TAXI"),
    ("TAKEOFF", 30.0, 100.0, 500.0, 120.0, "PHASE_TAKEOFF"),
    ("CLIMB", 240.0, 80.0, 15000.0, 175.0, "PHASE_CLIMB"),
    ("CRUISE", 4320.0, 68.0, 18000.0, 180.0, "PHASE_CRUISE"),
    ("DESCENT", 150.0, 35.0, 3000.0, 190.0, "PHASE_DESCENT"),
    ("LANDING", 40.0, 25.0, 0.0, 110.0, "PHASE_LANDING"),
]
SHORT_S = sum(p[1] for p in SHORT_PHASES)
FINAL_S = FINAL_CRUISE_H * 3600.0 + 1365.0
TOTAL_H = (N_PRIOR * SHORT_S + FINAL_S) / 3600.0

# One wear-out fault across the whole history: the cooling passages silting.
COOLING = ("cooling_degradation", START_HOURS + 0.05, 0.85, TOTAL_H, None)

DEMO_IDENTITY = {
    "location": "ASTRA ground station (simulated sortie)",
    "operator": "Team ASTRA, SIH 2026 prototype",
    "classification": "Unclassified: prototype demonstration on simulated data",
    "mission_prefix": "SIM",
    "engine_serial": "915-DEMO-0007",
}


def _fly(job: dict):
    """One sortie in its own process. Returns the finished snapshot."""
    os.environ["DT_DATA_DIR"] = job["data"]
    os.environ.pop("DT_CRUISE_HOURS", None)
    import numpy as np

    from layer2_physics import engine_sim as es
    from layer2_physics.degradation import FaultMode, InjectedFault
    from layer4_core import recorder as rec
    from layer4_core.live import LiveTwin

    lt = LiveTwin(twin_id=TWIN_ID, aircraft_id=AIRCRAFT, engine_key=ENGINE,
                  speed=1e6, channel=f"pf{job['i']}", seed=SEED,
                  cruise_hours=job["cruise_h"])
    if job["short"]:
        lt.veng.set_profile([es.FlightPhase(n, d, th, alt, spd, getattr(es, code))
                             for n, d, th, alt, spd, code in SHORT_PHASES])
    lt.veng.rng = np.random.default_rng(SEED * 1000 + job["i"])
    lt.veng.flight_hours = job["start_h"]
    lt.veng.degradation.hours = job["start_h"]
    lt.state.metadata.total_flight_hours = job["start_h"]

    def add(mode, onset, sev, ramp, cyl=None):
        lt.veng.inject(InjectedFault(mode=FaultMode(mode), onset_hours=float(onset),
                                     severity=float(sev), ramp_hours=float(ramp),
                                     cylinder=cyl))
        r = {"mode": mode, "severity": float(sev), "onset_hours": round(float(onset), 3),
             "ramp_hours": float(ramp)}
        if cyl:
            r["cylinder"] = cyl
        with lt._lock:
            lt._injected.append(r)

    add(*COOLING)
    recorder = rec.FlightRecorder(aircraft_id=AIRCRAFT) if job["record"] else None
    if recorder:
        lt._on_tick = recorder.record

    pending = sorted(job["acute"], key=lambda e: e[0])
    lt.start()
    t0 = time.time()
    while not lt.veng.profile_complete:
        time.sleep(0.5)
        s = lt.snapshot()
        while pending and s.t_s >= pending[0][0]:
            _, mode, sev, ramp, cyl = pending.pop(0)
            add(mode, lt.veng.flight_hours, sev, ramp, cyl)
    lt.stop()
    snap = lt.snapshot()
    info = None
    if recorder:
        info = {"path": str(recorder.path), "rows": recorder.rows}
        recorder.close()
    return job["i"], snap, info, time.time() - t0


def _scenario(key: str):
    from layer4_core import scenarios as scen
    return key, scen.run(key, engine_key=ENGINE).as_dict()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--export-only", action="store_true")
    ap.add_argument("--data", default=str(Path(tempfile.gettempdir()) / "astra_postflight_run"))
    ap.add_argument("--out", default=str(REPO / "ASTRA-Post-Flight-Report.pdf"))
    args = ap.parse_args()

    data = Path(args.data)
    os.environ["DT_DATA_DIR"] = str(data)
    saved = data / "final_flight.pkl"

    if not args.export_only:
        import shutil
        if data.exists():
            shutil.rmtree(data)
        data.mkdir(parents=True)
        # The trained networks are READ from the data directory. Without them
        # remaining life fell back to a straight line through one flight's
        # health (1.1 h) and no failure probability was produced at all.
        models = REPO / "data" / "models"
        if models.is_dir():
            shutil.copytree(models, data / "models")
        jobs = []
        for i in range(N_PRIOR):
            jobs.append({"i": i, "start_h": START_HOURS + i * SHORT_S / 3600.0,
                         "short": True, "cruise_h": 0.1, "acute": [], "record": False,
                         "data": str(data)})
        cruise0 = 765.0
        jobs.append({"i": N_PRIOR, "start_h": START_HOURS + N_PRIOR * SHORT_S / 3600.0,
                     "short": False, "cruise_h": FINAL_CRUISE_H, "record": True,
                     "data": str(data),
                     # From a calibration sweep through this same pipeline: a
                     # partly blocked cylinder 3 injector, and bearing wear
                     # developing over the rest of the cruise. Six-minute ramps
                     # at 0.7-0.8 read as an engine failing in flight (oil at
                     # 3 psi, 15 g), and the steep health slope put the physics
                     # RUL under 10 h, so an overhaul swallowed every other job.
                     "acute": [(cruise0 + 60.0, "injector_abnormal", 0.60, 0.1, 3),
                               (cruise0 + 240.0, "abnormal_vibration", 0.16, 0.3, None)]})
        t0 = time.time()
        print(f"flying {len(jobs)} sorties and 1 what-if scenario in parallel ...", flush=True)
        with ProcessPoolExecutor(max_workers=len(jobs) + 1) as ex:
            flights = [ex.submit(_fly, j) for j in jobs]
            scen_f = ex.submit(_scenario, "rapid_throttle")
            results = {}
            for f in flights:
                i, snap, info, wall = f.result()
                results[i] = (snap, info)
                print(f"  sortie {i + 1} done: {snap.t_s / 3600:.2f} h flown, "
                      f"CHI {(snap.health or {}).get('chi', 0):.3f}, {wall:.0f}s wall "
                      f"[{time.time() - t0:.0f}s elapsed]", flush=True)
            key, run = scen_f.result()
            print(f"  what-if {key} done [{time.time() - t0:.0f}s elapsed]", flush=True)

        from layer4_core import history as hist
        history = hist.FlightHistory()
        for i in range(N_PRIOR):
            snap, _ = results[i]
            fr = snap.flight_record or {}
            fid = history.record(
                fr.get("cruise_datum"), engine_key=ENGINE, aircraft_id=AIRCRAFT,
                # The flight's DURATION -- the trend sums these to get the
                # hours between datums.
                flight_hours=round(snap.t_s / 3600.0, 4),
                health_chi=(snap.health or {}).get("chi"), health=snap.health,
                events=fr.get("events"))
            print(f"  history: sortie {i + 1} -> record {fid}", flush=True)
        snap, info = results[N_PRIOR]
        with open(saved, "wb") as fh:
            pickle.dump({"snapshot": snap, "recorder": info,
                         "scenario_runs": {key: run}}, fh)
    with open(saved, "rb") as fh:
        state = pickle.load(fh)

    # ---- export through the console's own code path -----------------------
    from common import config
    from layer4_core import history as hist
    from layer4_core import report_pdf
    from layer4_core import twin_api

    real_identity = config.load_report_identity
    config.load_report_identity = lambda: {**real_identity(), **DEMO_IDENTITY}

    class _Frozen:
        def __init__(self, snap):
            self._s = snap
            self.engine_key = ENGINE

        def snapshot(self):
            return self._s

    class _Recording:
        def __init__(self, info):
            self.path = Path(info["path"])
            self.rows = info["rows"]

    md = (state["snapshot"].twin or {}).get("metadata") or {}
    if not md.get("installation_date"):
        import datetime as _dt
        md["installation_date"] = (_dt.datetime.now(_dt.timezone.utc)
                                   - _dt.timedelta(days=MONTHS_INSTALLED * 30.44)).isoformat()
    twin_api.twin = _Frozen(state["snapshot"])
    twin_api.history = hist.FlightHistory()
    twin_api.recorder = _Recording(state["recorder"])
    twin_api.SCENARIO_RUNS.clear()
    twin_api.SCENARIO_RUNS.update(state["scenario_runs"])

    payload = twin_api.mission_report({"sub": "report-generator", "role": "maintainer"})
    (data / "payload.json").write_text(json.dumps(payload, indent=1, default=str),
                                       encoding="utf-8")
    pdf = report_pdf.build(payload)
    Path(args.out).write_bytes(pdf)
    print(f"PDF: {args.out}  ({len(pdf) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
