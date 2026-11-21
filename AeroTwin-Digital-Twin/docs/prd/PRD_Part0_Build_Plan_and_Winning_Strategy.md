================================================================================
!! REVISION 2 - 27 August 2026 !!  READ THIS BEFORE ANYTHING BELOW
================================================================================
This document was issued at Revision 1 against the Rotax 914 as reference
engine. It has since been corrected against primary source documents. Where
this notice and the body text disagree, THIS NOTICE WINS.

WHAT CHANGED AT REVISION 2
  1. REFERENCE ENGINE: Rotax 914  ->  ROTAX 915 iS / iSc A.
     The 914 is carburetted, with no FADEC and no CAN bus, so it cannot
     support this document's own CAN-acquisition and ECU/FADEC requirements.
     The 915 iS carries a CERTIFIED DUAL-CHANNEL FADEC with a Display CAN bus
     and a Maintenance CAN bus on each lane. The 914 is retained in
     configs/engines/ as a secondary profile, and the Austro AE330 diesel as
     an adaptation stub, which together demonstrate the engine-agnostic claim.

  2. OPERATING LIMITS are now the CERTIFIED limits of the reference engine,
     not the air-cooled-engine bands originally written here. The 915 iS has
     LIQUID-COOLED cylinder heads: the certified thermal limit is COOLANT
     temperature at 120 degC, and EGT at 950 degC with a 200 degC split limit.

  3. The CAN bus is CANAEROSPACE, not an ad-hoc identifier set.

SOURCE DOCUMENTS (all held locally in `engines manuals/`)
  [TCDS] EASA Type Certificate Data Sheet E.121, Issue 17, 18 December 2023
  [OM]   BRP-Rotax Operators Manual OM-915 i, Ed. 0 Rev. 4, 01 September 2022
  [IM]   BRP-Rotax Installation Manual IM-915 i A/C24, Ed. 0 Rev. 5, 01 Feb 2024
  [MML]  BRP-Rotax Maintenance Manual Line MML-915 i, Ed. 0 Rev. 3, 01 May 2025
  [MMH]  BRP-Rotax Maintenance Manual Heavy MMH-915 i A/C24, Ed. 1 Rev. 0
  [CANAS] CANaerospace Interface Specification Rev. 1.6, Stock Flight Systems

EVERY DEPARTURE FROM REVISION 1 IS LOGGED WITH ITS EVIDENCE IN
  docs/PRD_DEVIATIONS.md   (29 entries)
COMPLIANCE AGAINST THE PROBLEM STATEMENT IS MACHINE-CHECKED BY
  python scripts/ps_compliance.py   and   pytest tests/
================================================================================

================================================================================
PRD PART 0 — PRODUCTION-READY BUILD PLAN & SIH WINNING STRATEGY
SIH 2026 / DRDO IDEX Problem Statement 26054
AI-Enabled Real-Time Digital Twin for Aero Piston Engines in MALE UAVs
================================================================================
Document Version: 1.0
Purpose: The executable, ZERO-COST blueprint that turns Parts 1–3 (the "what")
         into a buildable, demonstrable, judge-winning system (the "how").
Read this FIRST. It defines scope, stack, data strategy, repo layout, timeline,
demo script, and the scoring strategy for the finale.
================================================================================

TABLE OF CONTENTS — PART 0
================================================================================
0.1  What "production-ready" means for SIH (and how we win)
0.2  Corrections applied to Parts 1–3 (changelog)
0.3  Zero-Cost Technology Stack (100% open source, no paid APIs)
0.4  The MVP Cut Line — Demo scope vs. Production target
0.5  Honest Data Strategy (fixing the training-data trap)
0.6  Monorepo Structure & Service Layout
0.7  Build Roadmap (36-hour finale + 6-week pre-build)
0.8  Docker Compose — one-command bring-up
0.9  The 8-Minute Winning Demo Script
0.10 Judging Strategy — mapping features to the scorecard
0.11 "Production-Ready" Engineering Checklist
0.12 Risk register (buildable version)

================================================================================
0.1  WHAT "PRODUCTION-READY" MEANS FOR SIH (AND HOW WE WIN)
================================================================================

The tension: a hackathon rewards a WORKING, DEMONSTRABLE system; "production
grade" rewards architecture, security, and scale. You win by delivering BOTH,
clearly separated:

  1. A LIVE, END-TO-END WORKING CORE (built, runs on one laptop, no cloud,
     no hardware) — this is what judges see move in real time.
  2. A PRODUCTION ARCHITECTURE (designed in Parts 1–3, containerized, with a
     credible path to fleet + defence deployment) — this is what earns the
     "not just a toy" marks.

Winning formula = (Working demo that visibly does the hard thing) × (Credible
production story) × (Honesty about what is real vs simulated). Judges punish
over-claiming far harder than they punish honest scoping. Every "simulated" or
"future" label you add BUILDS trust — it does not cost you marks.

Definition of "production-ready" we commit to (all achievable at zero cost):
  • Containerized, reproducible (docker compose up → whole system runs).
  • Config-driven, engine-agnostic (add an engine via YAML, zero code change).
  • Secured (TLS, JWT/RBAC, audit log) — real, not slideware.
  • Observed (health checks, structured logs, metrics).
  • Tested (unit tests on physics + detectors; a CI workflow on GitHub Actions).
  • Documented (OpenAPI, README, runbook) and deployable (edge + server).
  • Graceful degradation (works offline at the edge; falls back to rules if ML
    confidence is low).

================================================================================
0.2  CORRECTIONS APPLIED TO PARTS 1–3 (CHANGELOG)
================================================================================

FIX 1 — Engine/platform accuracy (Part 1 §1.2–1.3): The TAPAS-BH-201 uses twin
  Austro AE330-class turbo-DIESEL engines, NOT the spark-ignition Rotax 914.
  Reframed the Rotax 914 as the honest, well-documented REFERENCE/DEMO engine
  (as actually used on Rustom-I, Heron, Searcher, Predator), declared the
  framework engine-agnostic, and made the TAPAS diesel a modular future
  adaptation that swaps only the combustion sub-model. This removes the single
  biggest credibility risk a DRDO domain expert would catch.

FIX 2 — Acronym collision (Part 2 §9.2/§9.3): "CHI" was used for BOTH Combustion
  Health Index and Composite Health Index. Combustion index renamed to CombHI;
  Composite stays CHI. Formula in §9.3 updated.

FIX 3 — Latency arithmetic (Part 1 §6.4): Pipeline sums to 81–203 ms but text
  claimed "<100 ms". Restated as "<100 ms typical (median), <200 ms worst-case";
  clarified the <50 ms critical path runs onboard (rules only) and bypasses the
  physics/AI stages.

FIX 4 — Parameter count (this document, note): The 8 PS health parameters count
  "Oil Pressure & Temperature" as ONE bullet; injection timing is the 8th. Our
  PRD splits oil P and oil T and adds injection timing, giving 9 tracked signals.
  In the pitch, say: "all 8 PS-required parameters, plus injection timing as a
  9th, and oil pressure/temperature tracked independently." Do not claim a gap.

FIX 5 — Data methodology (see §0.5): Replaced the circular "train on physics,
  validate on physics" risk with a held-out, degradation-trajectory validation
  protocol plus a public real dataset. Verify IDF-DS19 availability before
  citing it; if unavailable, drop it (do not list data you cannot obtain).

================================================================================
0.3  ZERO-COST TECHNOLOGY STACK (100% OPEN SOURCE, NO PAID APIS)
================================================================================

Every component below is free/open-source and runs locally. No cloud account,
no paid API key, no license fee — critical for a "zero proprietary cost"
defence pitch and for reproducibility by judges.

LAYER 1 — DATA ACQUISITION & EDGE
  • SocketCAN + vcan0 (Linux kernel)      — virtual CAN bus, no hardware
  • python-can                            — CAN frame produce/consume
  • cantools + a .dbc file                — signal encode/decode (documents bus)
  • paho-mqtt                             — edge → GCS publish
  • ONNX Runtime (INT8)                   — quantized edge inference
      [REVISED AT REV 2: tflite-runtime publishes no reliable Windows wheels;
       ONNX Runtime ships for Windows x64 AND linux-aarch64, so the identical
       artifact runs on the demo laptop and on the RPi/Jetson edge target.]
  • (real HW option, cheap) Raspberry Pi 4 + PiCAN2 — only if you have one

LAYER 2 — PHYSICS MODEL
  • Cantera (gri30.yaml)                  — combustion / adiabatic flame / EGT
  • NumPy + SciPy (solve_ivp RK45)        — 0-D Mean-Value Engine Model ODEs
  • scipy.interpolate.RegularGridInterpolator — performance maps
  • A Python "DegradationEngine" module   — the 6 degradation pathways

LAYER 3 — AI/ML ANALYTICS
  • scikit-learn                          — IsolationForest, scalers, metrics
  • PyOD                                  — CBLOF, ensemble outlier detection
  • ADTK                                  — rule/threshold time-series detectors
  • TensorFlow/Keras (or PyTorch)         — LSTM autoencoder, LSTM RUL, PINN
  • stumpy                                — Matrix Profile (subsequence anomaly)
  • SHAP + LIME                           — explainability
  • Flower (flwr)                         — federated learning (real, runnable)
  • Opacus / TF-Privacy (optional)        — differential privacy

LAYER 4 — DIGITAL TWIN CORE & STATE
  • FastAPI                               — REST API gateway + WebSocket (twin)
  • Eclipse Ditto (Docker)  OR  a Flask/FastAPI "Twin Stub" — twin state engine
      → For the DEMO use the FastAPI Twin Stub (lighter, faster to build).
      → Keep Ditto in the production diagram; optionally show it running.
  • Mosquitto (Docker)                    — MQTT broker (TLS-capable)
  • InfluxDB OSS 2.x (Docker)             — time-series store  [demo may use SQLite]
  • PostgreSQL (Docker)  OR  SQLite       — twin registry / metadata
  • Pydantic                              — JSON schema validation of twin state

LAYER 5 — VISUALIZATION & HMI  [REVISED AT REV 2]
  • Purpose-built React + TypeScript GCS console, governed by
    docs/PRD_Part4_Defence_HMI_Standard.md. Grafana cannot express MIL-STD-411F
    alerting semantics (master warning/caution with push-to-reset and re-arm,
    overflow memory, 3-second minimum message duration, inhibit logic) or
    MIL-STD-1472H coding rules. Those are requirements, not styling.
  • Grafana OSS (Docker)                  — retained for fleet-level ops views
  • Streamlit                             — retained for engineering what-if
  • Plotly / Matplotlib                   — SHAP plots, spectra, trends
  • ReportLab or WeasyPrint               — post-flight PDF mission report

SECURITY (all free)
  • TLS 1.3                               — Mosquitto + FastAPI (self-signed CA)
  • python-jose / PyJWT                   — JWT RS256 tokens
  • Keycloak (Docker)  OR  FastAPI RBAC   — identity + roles
      → DEMO: FastAPI dependency-injection RBAC (4 roles). Keycloak in prod diagram.
  • passlib[bcrypt]                       — password hashing
  • structlog                             — structured, hashable audit logging

PLATFORM / DEVOPS (all free)
  • Docker + docker-compose               — one-command reproducible bring-up
  • GitHub + GitHub Actions               — repo + free CI (lint, tests, build)
  • pytest                                — unit/integration tests
  • ruff + black + mypy                   — lint/format/type-check
  • uv or pip-tools                       — pinned, reproducible dependencies

DATASETS (all public / self-generated — see §0.5)
  • NASA C-MAPSS (FD001–FD004)            — prognostics pre-training (public)
  • NASA Bearing (IMS) / CWRU Bearing     — real vibration fault signatures (public)
  • Self-generated synthetic run-to-failure — from MVEM + degradation + noise

Language/runtime: Python 3.11. That is the entire cost: ₹0.

================================================================================
0.4  THE MVP CUT LINE — DEMO SCOPE vs. PRODUCTION TARGET
================================================================================

Build the LEFT column for the finale. Keep the RIGHT column in Parts 1–3 as
"designed for production." Put this exact table in your pitch deck — judges love
a team that knows the difference.

  CAPABILITY                 | DEMO (BUILT & SHOWN)          | PRODUCTION TARGET
  ---------------------------+-------------------------------+-------------------
  Data acquisition           | vcan0 + python-can, DBC-      | Real CAN 2.0B via
                             | encoded, all 9 signals, 10-   | PiCAN2 / ECU-FADEC
                             | 100 Hz, replayable            | ARINC429/1553B
  Physics model              | Cantera + 0-D MVEM live,      | Higher-fidelity
                             | CHT/EGT/torque/fuel predicted | 1-D GT-Power class
  Degradation                | 6 pathways, injectable,       | Calibrated on VRDE
                             | run-to-failure synthetic      | test-rig data
  Anomaly detection          | Tier-1 rules + IsolationForest| Full 3-tier ensemble
                             | + LSTM-AE (all 3 tiers, lite) | tuned per fleet
  Fault classification       | 4 of 8 faults deep + 8 via    | All 8 faults, high
                             | rules (misfire, cooling,      | recall, field-tuned
                             | lubrication, vibration)       |
  RUL                        | LSTM RUL + physics extrap.,   | Fleet-calibrated,
                             | fused, with CI                | active-learning loop
  Explainability             | SHAP force + NL advisory live | LIME + audit export
  Twin core                  | FastAPI Twin Stub, 4 states   | Eclipse Ditto, 100+
                             | (reported/desired/pred/sim)   | concurrent twins
  Storage                    | InfluxDB OSS + SQLite         | Influx cluster + PG
  Dashboard                  | Grafana 10 panels + Streamlit | Same + role SSO
  Alerts                     | 5-level, dashboard+audio+log  | +Email/SMS/webhook
  Simulation & replay        | 4 env conditions + replay +   | Full mission library
                             | what-if, all live             |
  Security                   | TLS, JWT/RBAC(4), audit log   | Keycloak+MFA, HSM,
                             | (REAL, running)               | Zero-Trust segments
  Edge AI                    | TFLite INT8 model, <50 ms     | Jetson Orin, FADEC
                             | rule path, offline buffer     | auto power-reduction
  Federated learning         | Flower, 3 simulated clients,  | 76-UAV fleet, secure
                             | FedAvg + DP noise (RUNS)      | aggregation (SMPC)
  Deploy                     | docker compose up             | K8s + HPA, CI/CD

Golden rule: it is better to show 6 capabilities WORKING end-to-end than 15
half-working. Depth beats breadth in the live demo; breadth lives in the docs.

================================================================================
0.5  HONEST DATA STRATEGY (FIXING THE TRAINING-DATA TRAP)
================================================================================

THE TRAP: If you train the ML on data generated by your physics model and then
"validate" on data from the SAME model, you have only proven the network can
copy the model. A sharp judge will ask "where is your ground truth?" — have the
answer ready.

THE HONEST PROTOCOL (build this, say this):

  1. SYNTHETIC GENERATOR (your strength): The MVEM + 6 degradation pathways
     generate 100 "virtual engines" run to failure. CRITICAL additions that make
     it non-circular:
       • Inject STOCHASTIC faults at random times with random severities.
       • Add realistic SENSOR NOISE, bias drift, and dropouts (not clean model
         output). Use noise statistics taken from a REAL dataset (C-MAPSS/IDF).
       • Randomize physics parameters per engine (manufacturing spread) so the
         NN cannot memorize one trajectory.

  2. STRICT SPLIT BY ENGINE, NOT BY SAMPLE: Train on engines 1–80, validate on
     81–90, TEST on 91–100 — engines the model has never seen. Report test-set
     RMSE / NASA-Score. This defeats leakage.

  3. REAL-DATA ANCHORING (the credibility move):
       • Pre-train the LSTM on NASA C-MAPSS (public turbofan run-to-failure) for
         GENERAL prognostic patterns — frame it honestly as transfer/pre-train,
         NOT as "turbofan == piston".
       • Validate the VIBRATION fault path on a REAL bearing dataset (NASA IMS or
         CWRU) — real BPFO/BPFI signatures, not synthetic. This single move lets
         you say "our bearing detector works on real fault data," which is gold.

  4. PHYSICS-AS-VALIDATOR, NOT AS TRUTH: Use physics residuals (predicted vs
     actual) as an ANOMALY FEATURE and a PLAUSIBILITY GATE, not as the ML target.
     The hybrid model (y = y_physics + NN(residual)) then has an interpretable
     baseline you can defend.

  5. UNCERTAINTY EVERYWHERE: Always output confidence intervals (from Kalman
     covariance / MC-dropout). "RUL = 47 h [42–53, 95%]" reads as engineering;
     a bare number reads as a guess.

WHAT TO SAY IN THE PITCH (one line): "We pre-train on public NASA prognostics
data, generate physics-based synthetic run-to-failure with injected stochastic
faults and real-sensor noise, validate the bearing path on real NASA/CWRU
vibration data, and test on held-out engines — so our numbers are not circular."

================================================================================
0.6  MONOREPO STRUCTURE & SERVICE LAYOUT
================================================================================

digital-twin-uav/
├─ README.md                     ← 60-second quickstart + architecture image
├─ docker-compose.yml            ← one command brings up the whole system
├─ .github/workflows/ci.yml      ← lint + type + test on every push (free CI)
├─ pyproject.toml                ← pinned deps, ruff/black/mypy config
├─ configs/
│  ├─ engines/rotax_914.yaml     ← engine-agnostic config (add engine = new YAML)
│  ├─ engines/austro_ae330.yaml  ← stub showing diesel adaptation path
│  ├─ can/engine.dbc             ← CAN signal definitions (0x100..0x108)
│  └─ thresholds.yaml            ← all alert thresholds (no magic numbers in code)
├─ layer1_edge/
│  ├─ can_simulator.py           ← publishes DBC-encoded frames to vcan0
│  ├─ can_ingest.py              ← reads vcan0 → validates → MQTT publish
│  ├─ sensor_fusion.py           ← Hampel filter, resample, Kalman bias
│  ├─ edge_rules.py              ← <50 ms critical rule engine (offline-capable)
│  ├─ edge_infer_tflite.py       ← INT8 anomaly model, local 72-h buffer
│  └─ tests/
├─ layer2_physics/
│  ├─ combustion_cantera.py      ← adiabatic flame, EGT baseline, species
│  ├─ mvem.py                    ← 0-D mean-value engine model (solve_ivp)
│  ├─ perf_maps.py               ← BMEP/BSFC/η_vol/CHT/EGT interpolators
│  ├─ degradation.py             ← 6 pathways + fault injection API
│  ├─ synth_data_gen.py          ← 100 virtual engines run-to-failure (§0.5)
│  └─ tests/                     ← physics sanity: energy balance, bounds
├─ layer3_ai/
│  ├─ tier1_rules.py             ← ADTK rule/threshold detectors
│  ├─ tier2_statistical.py       ← IsolationForest + CBLOF + MatrixProfile ens.
│  ├─ tier3_deep.py              ← LSTM-AE + multi-task fault classifier
│  ├─ rul_lstm.py                ← data-driven RUL + custom NASA-score loss
│  ├─ rul_physics.py             ← degradation extrapolation + fusion
│  ├─ pinn.py                    ← physics-informed net (optional, stretch)
│  ├─ explain_shap.py            ← SHAP/LIME + natural-language advisory
│  ├─ fed/flower_sim.py          ← Flower FedAvg + DP, 3 simulated clients
│  └─ tests/
├─ layer4_core/
│  ├─ twin_state.py              ← Pydantic twin schema (reported/desired/…)
│  ├─ twin_api.py                ← FastAPI REST + WebSocket gateway
│  ├─ registry.py                ← twin registry (SQLite/PG), fleet view
│  ├─ security.py                ← JWT RS256, RBAC(4 roles), audit log
│  └─ storage.py                 ← InfluxDB writer + SQLite fallback
├─ layer5_viz/
│  ├─ grafana/                   ← provisioned dashboards (JSON) + datasource
│  ├─ streamlit_app.py           ← HMI: live, replay, what-if, reports
│  └─ report_pdf.py              ← post-flight mission PDF (ReportLab)
├─ scripts/
│  ├─ setup_vcan.sh              ← modprobe vcan; ip link add vcan0
│  ├─ demo_scenario.py           ← scripted fault injection for the pitch
│  └─ make_certs.sh              ← self-signed CA for TLS
└─ docs/
   ├─ PRD_Part0..3               ← this + the three PRDs
   ├─ openapi.json               ← auto-generated by FastAPI
   ├─ RUNBOOK.md                 ← how to operate / troubleshoot
   └─ architecture.png           ← the diagram

Data flow (matches your architecture image exactly):
  can_simulator → vcan0 → can_ingest → MQTT → twin_api
    → physics(mvem/cantera) + ai(tiers/rul/shap) → twin_state
    → InfluxDB + WebSocket → Grafana + Streamlit + alerts

================================================================================
0.7  BUILD ROADMAP
================================================================================

You almost certainly have a PRE-BUILD window before the finale. Use it. SIH
grand finales are ~36 hours and are for INTEGRATION + POLISH, not first-time
coding of an LSTM.

PRE-BUILD (6 weeks, part-time — do the heavy lifting here)
  Week 1  Repo, docker-compose skeleton, vcan0, DBC, CAN sim + ingest working.
          Milestone: frames flow vcan0 → MQTT → console.
  Week 2  Physics: Cantera EGT baseline + MVEM CHT/EGT/torque/fuel. Perf maps.
          Milestone: physics predicts sane CHT/EGT for a given throttle/altitude.
  Week 3  Degradation + synthetic run-to-failure generator (100 engines).
          Milestone: labeled dataset with injected faults + realistic noise.
  Week 4  AI: Tier-1 rules, IsolationForest, LSTM-AE, LSTM RUL. Held-out test.
          Milestone: anomaly + RUL metrics on UNSEEN engines; bearing path on
          real NASA/CWRU data.
  Week 5  Twin core (FastAPI + Pydantic state + SQLite/Influx) + security
          (TLS, JWT, RBAC, audit) + SHAP advisory.
          Milestone: end-to-end state sync with auth; SHAP explains an alert.
  Week 6  Grafana + Streamlit dashboards, replay, what-if, 4 env conditions,
          PDF report, Flower FL demo. Freeze features. Write tests + CI.
          Milestone: `docker compose up` → full system live; demo rehearsed 3×.

FINALE (36 hours — integrate, harden, rehearse; DO NOT start new features)
  Hr 0–6   Bring up full stack on the demo laptop; fix env/integration bugs.
  Hr 6–16  Polish dashboards; wire scripted fault-injection demo; edge offline
           demo; test the "unplug network → edge keeps working" moment.
  Hr 16–24 Buffer for the inevitable breakage; add nice-to-haves ONLY if core
           is rock-solid; record a backup demo video (insurance vs live failure).
  Hr 24–32 Rehearse the 8-minute script (§0.9) until it is muscle memory. Assign
           speaking roles. Prepare answers to the tough questions (§0.10).
  Hr 32–36 Final polish, deck freeze, sleep in shifts. Arrive fresh.

================================================================================
0.8  DOCKER COMPOSE — ONE-COMMAND BRING-UP
================================================================================

Target experience for a judge: `git clone … && docker compose up` → open
localhost:3000 (Grafana) and localhost:8501 (Streamlit) → watch it run.

Services in docker-compose.yml:
  mosquitto      (MQTT broker, TLS)            :8883
  influxdb       (time-series)                 :8086
  postgres       (registry; or omit for SQLite):5432
  twin-core      (FastAPI: REST+WS+security)   :8000
  physics        (MVEM/Cantera worker)         (internal)
  ai             (detectors/RUL/SHAP worker)   (internal)
  edge           (can-sim + ingest + tflite)   (internal, vcan0)
  grafana        (dashboards)                  :3000
  streamlit      (HMI)                         :8501

Notes:
  • vcan0 needs the host kernel module; run scripts/setup_vcan.sh on the host,
    or run the edge container with --network host + NET_ADMIN (documented in
    RUNBOOK). Fallback: a pure-Python in-process CAN bus (python-can 'virtual'
    bus) needs no kernel module — use it if the demo machine blocks modprobe.
  • Grafana dashboards + Influx datasource are PROVISIONED from files so they
    appear automatically (no manual clicking during the demo).
  • Health checks on every service so `docker compose up` waits for readiness.

================================================================================
0.9  THE 8-MINUTE WINNING DEMO SCRIPT
================================================================================

Tell a STORY: a healthy engine flies a mission, quietly degrades, the twin
predicts the failure BEFORE it happens, explains WHY, and advises action — the
exact thing conventional threshold systems cannot do. That contrast is your win.

  0:00 HOOK (30s). "A TAPAS-class MALE UAV piston engine failure over the sea
        means mission abort and a ₹50-crore asset at risk. Today's monitors are
        reactive — they alarm AFTER failure. We built the predictive digital
        twin that sees it coming." Show the architecture image (1 slide).

  0:30 LIVE, IT'S REAL (60s). `docker compose up` already running. Show Grafana:
        all 9 parameters live, health index green, CAN frames flowing on vcan0.
        "Every number is a simulated Rotax-914-class engine on a virtual CAN bus
        — the same code path a real PiCAN2 would feed."

  1:30 PHYSICS TWIN (60s). Show predicted vs actual CHT/EGT tracking closely;
        the residual near zero. "This is a physics twin — Cantera combustion +
        a mean-value engine model — not a curve fit. It knows the thermodynamics."

  2:30 INJECT DEGRADATION (90s). Run scripts/demo_scenario.py: start cooling
        degradation. Watch CHT residual climb, Thermal Health Index fall, alert
        escalate GREEN→BLUE→YELLOW. "No threshold has been crossed yet — a
        conventional system is still silent. Ours already sees the trend."

  4:00 PREDICT + EXPLAIN (90s). RUL countdown drops with confidence interval.
        Open the SHAP panel: "The twin says 87% cooling degradation, driven by
        CHT residual +12°C and cooling-efficiency 0.78 — and here's the plain-
        English advisory: inspect the water pump within 10 flight hours." THIS is
        the money moment — prediction + explanation + action.

  5:30 EDGE + OFFLINE (45s). "Comms to a UAV drop constantly." Kill the network
        to the GCS; show the edge node still detecting the critical alert in
        <50 ms and buffering locally; restore link → data syncs. Defence-relevant.

  6:15 SIM & REPLAY (45s). Streamlit what-if: "Climb to 20,000 ft at 45°C?" →
        NO-GO with predicted 218°C CHT. Then replay the mission at 100× and jump
        to the fault event. Post-flight PDF generated.

  7:00 PRODUCTION + SECURITY (45s). Show JWT login as 'Operator' vs 'Commander'
        (RBAC), the audit log, TLS on MQTT, and the Flower federated-learning run
        across 3 UAV clients. "Zero proprietary cost, defence-grade design,
        scales to 100 twins."

  7:45 CLOSE (15s). "Predictive, explainable, edge-capable, secure, and fully
        open-source. From reactive alarms to a twin that prevents failures."

Backup: have a RECORDED run of this exact script. If live breaks, switch to
video without missing a beat.

================================================================================
0.10 JUDGING STRATEGY — MAPPING FEATURES TO THE SCORECARD
================================================================================

SIH/DRDO panels typically score: Problem understanding, Innovation, Technical
depth, Completeness vs PS, Feasibility/scalability, Demo, Presentation, Impact.
Deliberately hit each:

  • Problem understanding → open by naming the REAL failure cost and why
    threshold monitoring is inadequate; show the PS→feature traceability table.
  • Completeness → the traceability matrix (Part 0.4 + PRD §24): "all 8 params,
    all 8 faults, all 5 env conditions, all 8 innovation areas — here's each."
  • Innovation → lead with the 3 sharpest: physics-informed hybrid, edge AI
    with offline autonomy, explainable RUL advisory. Federated learning is your
    "wow, they actually ran it" moment.
  • Technical depth → show ONE thing deeply (the physics residual → SHAP → RUL
    chain). Depth in one place implies competence everywhere.
  • Feasibility → "docker compose up, ₹0 cost, runs on this laptop, deploys to a
    ₹4,000 Raspberry Pi." Concrete and cheap = believable.
  • Honesty → your simulated/future labels. Say them proactively.

TOUGH QUESTIONS — HAVE ANSWERS READY:
  Q: "Rotax 914 isn't the TAPAS engine." → "Correct — TAPAS uses Austro AE330
     diesels. We model the well-documented Rotax 914 as a representative
     spark-ignition MALE engine (Rustom-I/Heron/Predator) for honest validation;
     our framework is engine-agnostic and TAPAS needs only a diesel combustion
     sub-model swap. We flagged this explicitly in our PRD." (Turns a weakness
     into a credibility WIN — you knew before they asked.)
  Q: "Your ML is trained on synthetic data — is it real?" → give the §0.5 line
     (public pre-train + real bearing data + held-out engine test).
  Q: "Real-time on real hardware?" → cite the edge latency budget and the TFLite
     INT8 numbers; show the edge path bypasses the heavy stack for <50 ms.
  Q: "How does this scale to a fleet?" → twin registry (add engine = YAML), MQTT
     topic hierarchy, federated learning, containerized services.
  Q: "Security for defence?" → TLS+JWT+RBAC+audit are RUNNING (not slides);
     Keycloak/HSM/Zero-Trust are the documented production hardening.

================================================================================
0.11 "PRODUCTION-READY" ENGINEERING CHECKLIST (ZERO-COST, DO ALL)
================================================================================

  [ ] docker compose up brings up the ENTIRE system, no manual steps.
  [ ] Every threshold/constant lives in configs/*.yaml — none hard-coded.
  [ ] Adding an engine = new YAML file, zero code change (prove with AE330 stub).
  [ ] Pydantic validates all twin-state I/O; invalid data is rejected + logged.
  [ ] TLS on MQTT and API; JWT RS256; 4 RBAC roles enforced on endpoints.
  [ ] Structured audit log with UTC + user + change hash for every state mutation.
  [ ] Health checks + /healthz on every service; graceful shutdown.
  [ ] Edge works with the network unplugged; buffers 72 h; syncs on reconnect.
  [ ] ML falls back to rule-based when confidence < threshold (graceful degrade).
  [ ] Every prediction carries a confidence interval.
  [ ] pytest suite: physics sanity (energy balance, bounds), detectors, API auth.
  [ ] GitHub Actions CI: ruff + mypy + pytest green on every push.
  [ ] OpenAPI spec auto-served at /docs; RUNBOOK.md written.
  [ ] Reproducible: pinned deps; README quickstart tested on a clean machine.
  [ ] Backup demo video recorded.

================================================================================
0.12 RISK REGISTER (BUILDABLE VERSION)
================================================================================

  RISK                              | MITIGATION (all free)
  ----------------------------------+--------------------------------------------
  vcan0 blocked on demo machine     | Fall back to python-can 'virtual' in-proc
                                    | bus (no kernel module). Test both early.
  Live demo breaks on stage         | Pre-recorded backup video of the exact run.
  ML looks circular to judges       | §0.5 protocol + real bearing-data validation.
  Over-scope → nothing finished     | §0.4 MVP cut line; freeze features Week 6.
  Cantera install pain              | Pin conda-forge/pip version; containerize it;
                                    | pre-compute EGT baselines to a lookup if slow.
  Real-time too slow in Python      | Vectorize NumPy; cache physics; run AI in a
                                    | worker; INT8 TFLite at edge; async FastAPI.
  Engine/platform credibility       | Already fixed in PRD §1.2–1.3; rehearse the
                                    | tough-question answer.
  Team skill gaps                   | Pair on the 6-week pre-build; each layer has
                                    | one owner; this doc is the shared contract.

================================================================================
BOTTOM LINE
================================================================================
Parts 1–3 already prove you understand the problem completely. Part 0 makes it
BUILDABLE and WINNABLE: one open-source stack (₹0), a clear MVP you can finish,
an honest data story that survives scrutiny, a rehearsed demo that shows the
twin PREDICTING and EXPLAINING a failure before it happens, and a production
architecture that scales. Build the left column, narrate the right, be honest
about the seams — and you win.
================================================================================
END OF PRD PART 0
================================================================================
