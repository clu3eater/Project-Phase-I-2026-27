# Runbook

Operating, demonstrating and deploying the engine digital twin.
DRDO / IDEX PS 26054.

---

## 1. Start it

### One command

```bash
python run.py
```

Creates the virtual environment if there is none, installs whatever is
missing, builds the console if `dist/` is absent or older than its source, proves each of the five
layers works once, then serves and prints the logins. On Windows without
Python on PATH use `.\run.ps1`; on POSIX, `./run.sh`.

| flag | effect |
|---|---|
| `--check` | run every check, then exit without serving |
| `--demo` | run the ninety-second terminal demonstration instead of serving |
| `--tests` | also run the full test suite (~18 min) in the self-check |
| `--full` | also install the `ml`, `physics` and `dev` extras (torch is ~2 GB) |
| `--no-console` | skip the npm build |
| `--no-check` | serve immediately, skipping the self-check |
| `--no-browser` | do not open a browser |
| `--reinstall` | reinstall dependencies even when present |
| `--port N` | serve somewhere other than 8000 |
| `--list-engines` | list the engine definitions, which one runs, and whether each is complete |
| `--check-engine KEY` | name every key `configs/engines/KEY.yaml` is missing, then fly it for ten seconds |

`--check` is the one to run before a demonstration: it is about ten seconds
and it exercises the CAN pipeline, the shadow model, the health index, the
fusion, the operator view, the display standard and the traceability audit,
then injects a cooling fault and shows the twin registering it while every
certified limit is still satisfied.

### By hand

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows
source .venv/bin/activate       # Linux / macOS
pip install -e ".[security,reports]"

python -m layer4_core.twin_api
```

**The extras are not optional for starting the API.** `twin_api` imports
`layer4_core.security` at module scope, which imports `jwt`, `bcrypt` and
`cryptography` with no guard; all three live in the `security` extra, so
`pip install -e .` alone dies on `ModuleNotFoundError` before `main()` runs.
`reports` is guarded — the API starts without it — but the PDF export then
fails instead of producing a report.

http://127.0.0.1:8000

The console is served from the same origin as the API. `dist/` is git-ignored,
so a fresh clone has none and the root URL returns a JSON hint instead of the
page — see §6.

### From Docker

```bash
docker compose up
```

The container reports healthy only once the pipeline is producing ticks, not
merely once the port is open, so `docker compose ps` showing `healthy` means
the engine is actually running.

---

## 2. Demonstrate it

```bash
python scripts/demo.py
```

Ninety seconds, terminal only, no browser. It runs the real pipeline and shows
the moment that matters: the twin reporting a degrading engine **while every
certified limit is still satisfied**.

Options:

```bash
python scripts/demo.py --fault abnormal_vibration --severity 0.95
python scripts/demo.py --speed 300      # simulated seconds per wall second
```

Injectable faults: `misfire`, `injector_abnormal`, `cooling_degradation`,
`lubrication_issue`, `combustion_instability`, `overheating_trend`,
`abnormal_vibration`. Sensor drift is **not** injectable — the instrument layer
models it directly, and injecting it as well would double-count it.

### Demonstrating from the console: the squadron, end to end

Sign in four times (four browser windows, or one after another). Nothing flies
until the chain below has been walked; the engine is parked and cold.

1. **Maintenance** (`mt.iyer`, opens on Fleet). Select MALE-03 and press
   Engine ground run (twice: it arms, then runs): the engine starts from cold, warms, runs up, cools and
   shuts down (about 25 s at 20x). The twin finds the cooling problem MALE-03
   was registered with -- nobody told it -- and writes a CAUTION defect on the
   technical log. Sign the release on MALE-01 (and MALE-03 if you want to fly
   it with the concession).
2. **Engineer** (`eng.menon`, opens on Review). The twin's finding is
   waiting: Decide opens it beside its evidence -- confirm, defer with an hours
   limit, or no fault found. Set a limitation on MALE-03 (for example 4 h missions).
3. **Commander** (`cdr.sharma`, opens on Operations). Plan mission, then the
   allotment drawer shows every aircraft with the twin's verdict and predicted success for THAT
   mission and why the others cannot go; approve one with `op.rao`.
4. **Operator** (`op.rao`, opens on Mission). Prepare, tick the checklist, Start
   engine. The launch checks turn Met as the oil reaches 50 °C; Launch. Watch it
   climb on the engine strip and the Engine workspace; Recall (RTB) if you like.
   After shutdown, debrief and report a snag.
5. Back to **maintenance**: the aircraft is AWAITING INSPECTION with the snag
   and any twin defects open. Rectify, ground-run, sign the release.

`DT_CRUISE_HOURS` sets the compressed cruise (default 0.1 h); `DT_PERSIST=0`
starts every aircraft and the squadron log fresh for a clean demonstration.

### Fault injection from the console

Simulate → Fault injection (engineer) injects faults into the running physics model. The
signature then develops over the ramp; nothing is faked at the display layer.
Watch Engine → Parameters, the residual panel, not the readouts — the readouts stay
inside their limits, which is the point.

To close the loop, sign in as **maintenance** (`mt.iyer`) and open the
Engine → Maintenance plan (the aircraft on the ground station). Record the job that fixes the fault (a cooling flush, A2,
for `cooling_degradation`), with a note. The work log shows the affected
health indices before the work, then "confirming" while the engine runs, and
then the settled after-reading — about ten seconds at the default 20x.
Every job can be recorded, not only the recommended ones; an inspection asks
whether parts were replaced, because one that replaced nothing restores
nothing.

---

## 3. What to look at, and why

| page | what it answers |
|---|---|
| ENGINE | what the sensors say, and how far it is from an as-new engine at the same operating point |
| HEALTH | composite index, four subsystems, nine sub-indices, degradation factors, onset detection |
| PROGNOSTICS | remaining life with its interval, three-tier detection breakdown, maintenance advisory |
| MISSION PLANNING | draw a route, price it against this engine, check it, fly it through the model and read the result; Go / No-Go per mission profile is in its CHECKS tab |
| SIMULATION | fault injection, environmental state |
| REPORT | mission-wise health report |
| ECTM (`/api/history/ectm`) | drift against the baseline flight, across flights, weather excluded |

The footer strip is worth reading at any time: source, rate, channel count,
frames decoded and lost, measured latency, and whether the shadow model is
locked. PRD Part 4 §7 — the operator can always see whether to believe the
screen.

---

## 4. Regenerating data and retraining

None of this is needed to run or demonstrate the system. It is needed to
reproduce the reported numbers, and it needs the deep-learning extra:

```bash
pip install -e ".[ml]"      # torch, onnx, shap -- NOT needed to run the twin
```

torch is deliberately off the serving path (`layer4_core.live` does not import
it) so that an edge image stays small. Cantera is optional too -- a precomputed
flame lookup ships in the repository, decision D7.

```bash
# 100 engines run to failure. ~50 min on 7 cores, ~96 MB.
python -m layer2_physics.synth_data_gen --engines 100 --workers 7

# Evaluate / train, all reported on held-out engines
python scripts/eval_tier2.py       # statistical detection
python scripts/train_tier3.py      # deep detection + fault classification
python scripts/eval_fusion.py      # three-tier fusion
python scripts/eval_health.py      # health index vs ground truth
python scripts/train_rul.py        # remaining useful life
```

Datasets and models land in `data/` (gitignored). `DT_DATA_DIR` moves them.

---

## 5. Verifying the build

```bash
python scripts/ps_compliance.py    # traceability against docs/ps.md
pytest                             # full test suite
pytest layer2_physics -q           # one layer
```

`ps_compliance.py` is the honest answer to "where does this stand" — it marks a
requirement BUILT only when something in the repository demonstrates it now. A
design in a PRD counts as DESIGNED.

---

## 6. Troubleshooting

**The root URL returns JSON saying "console: not built".**
The React bundle is missing -- `dist/` is git-ignored, so a fresh clone never
has one. `python run.py` builds it. By hand:

```bash
cd layer5_viz/gcs_console
npm install
npm run build
```

Then restart the API. The Docker image builds it automatically.

**`ModuleNotFoundError: No module named 'jwt'` / `bcrypt` / `cryptography`.**
`pip install -e .` was run without the `security` extra. These three are
imported unguarded by `layer4_core.security`, which `twin_api` imports at
module scope, so the API cannot start without them:

```bash
pip install -e ".[security,reports]"
```

`python run.py` does this for you.

**`ModuleNotFoundError: No module named 'can'`.**
The virtual environment is not active, or `pip install -e .` has not been run.

**The console shows `LINK LOST`.**
The API stopped or the WebSocket dropped. The console retries every 1.5 s and
says so rather than showing stale data as though it were live. Check the API
process.

**Every readout shows `———`.**
That is correct behaviour when a channel fails validation, not a rendering
bug: invalid values are removed, never substituted (PRD Part 4 §7.2). If ALL
of them show it, the pipeline is not producing — check `/api/healthz`.

**The demo prints escape codes instead of colour.**
Output is being piped. Colour is disabled automatically when stdout is not a
terminal; if you are seeing raw codes, the terminal claims to be a TTY but
cannot render ANSI. The text is readable either way.

**Port 8000 is in use.**
`python run.py --port 8100`, or set `DT_PORT=8100` before starting the API
directly.

**A test hangs on the CAN bus.**
Each test opens its own named virtual channel. A crashed earlier run can leave
one held; restart the Python process.

---

## 7. Deploying to a real engine

The system is written so that moving from simulation to hardware is a
configuration change, not a rewrite. Three things change:

**1. The CAN transport.** `layer1_edge` takes its interface as a string:
`virtual` (demo) → `socketcan` (Raspberry Pi with a PiCAN2 HAT) → `pcan`
(bench). Decision D1 in `docs/prd/PROJECT_PLAN.md`.

```bash
sudo ip link set can0 type can bitrate 1000000
sudo ip link set up can0
```

**2. The CAN database.** `configs/can/engine.dbc` uses **open CANaerospace**
identifiers. The Rotax Display CAN message assignment is not public — the
installation manual directs the reader to an authorised distributor. Our DBC
must not be presented as the Rotax database; on real hardware it is replaced
with the manufacturer's.

**3. The engine profile.** `configs/engines/*.yaml`. Adding an engine is a
YAML file and no code change; the Austro AE330 stub demonstrates the path for a
compression-ignition engine on Jet-A1.

**What does NOT change:** the physics model, the twin, the detectors, the
health indices and the console all consume validated telemetry and are
indifferent to where it came from.

### Edge node

The Layer 1 stack has no network dependency by construction — rules, buffering
and alerting continue with the link down, and 72 hours of telemetry are held
locally in SQLite (WAL) for back-fill on reconnect. Dependencies are light
enough for a Raspberry Pi 4.

---

## 8. Known limits

Stated plainly rather than discovered later. Full detail in `docs/prd/PROJECT_PLAN.md`
and `docs/PRD_DEVIATIONS.md`.

| | |
|---|---|
| Remaining life | On this engine, RMSE 121 h at **0.87 sigma** and alpha-lambda 0.20 -- 3 of 15 engines inside the +/-20 % accuracy cone at half-life (DEV-178). The cause is observability, not the estimator: the SAME architecture scores **1.09-1.36x published state of the art on NASA C-MAPSS** (DEV-182). RUL depends on the *rate* of degradation and a 30-sample window sees 0.0013 % of an engine's life -- a state, not a rate. The 48 per-engine sessions spanning ~500 h that would show the rate are already in the dataset and are not yet fed to the model. The NASA prognostics score (298 vs < 500) is met, so the errors are not systematically dangerous. |
| Injector and cooling fault classes | F1 0.215 and 0.254. Natural wear and a fault produce the same signature, differing only in rate — not separable inside a 50-second window. |
| Detection false-positive rate | 7.4 % against a 5 % target on unseen engines, from a threshold fixed on training engines and never moved. |
| Battery state of health | Not implemented (gap G4) — needs internal-resistance trending no channel provides. The electrical index renormalises rather than scoring the missing term 1.0. |
| Real-data validation | **One narrow claim, measured.** The RUL architecture, untuned, scores RMSE 15.42 / 17.77 / 13.89 / 19.05 on NASA C-MAPSS FD001-FD004 against a published state of the art of 12.6 / 13.1 / 12.7 / 14.0 -- **1.09x to 1.36x**. That validates the METHOD on real benchmark data and nothing else: C-MAPSS is a turbofan and shares no sensor and no failure mode with a piston engine, so it says nothing about the 915 iS engine model, its health index, or its RUL on this airframe. No transfer-learning claim is made and no path to attempt one exists (DEV-181). IMS/CWRU are still not downloaded, so no real-bearing claim may be made. Reproduce with `scripts/fetch_benchmarks.py` then `scripts/benchmark_cmapss.py`. |

---

## 9. Provenance

Every engine value in `configs/engines/` is tagged by source: `[TCDS]` type
certificate, `[OM]` operator's manual, `[IM]` installation manual, `[MML]`
maintenance manual, `[DS]` data sheet, `[DER]` derived, `[MOD]` modelling
choice.

No deviation from the PRDs exists in code without an entry in
`docs/PRD_DEVIATIONS.md`, and every entry carries the measurement that forced
it.
