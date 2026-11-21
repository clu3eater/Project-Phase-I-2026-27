# ASTRA — Software Documentation

**AI-Enabled Real-Time Digital Twin for Aero Piston Engines in MALE UAVs**
DRDO · Smart India Hackathon 2026 · Problem Statement 26054
Package `dt-uav-engine`, version 0.1.0, licence Apache-2.0

`Restricted (Government Use Only)`

---

## About this document

This is the engineering reference for the ASTRA codebase: what each part is,
how the parts fit together, what contracts exist between them, and how to
build, run, test, extend and deploy the system. It is written for someone who
has to work on the code or assess it.

It complements rather than replaces:

| Document | Its job |
|---|---|
| [`README.md`](../README.md) | what the system is and what it measures — the evidence case |
| [`RUNBOOK.md`](../RUNBOOK.md) | operating, demonstrating, troubleshooting, deployment |
| [`docs/ps.md`](ps.md) | the problem statement, verbatim |
| [`docs/prd/`](prd/) | the original design documents (Parts 0–4) and the living plan |
| [`docs/PRD_DEVIATIONS.md`](PRD_DEVIATIONS.md) | every departure from the plan, with the measurement that forced it |
| [`docs/SQUADRON_OPERATIONS.md`](SQUADRON_OPERATIONS.md) | the operational workflow in detail |
| [`docs/PRD_Part4_Defence_HMI_Standard.md`](PRD_Part4_Defence_HMI_Standard.md) | the console's normative HMI standard |

Figures here were read from the code and configuration on the `update3`
branch. Where a figure differs from the README the difference is noted in place.

---

## Table of contents

1. [System summary](#1-system-summary)
2. [Technology stack and repository statistics](#2-technology-stack-and-repository-statistics)
3. [Architecture](#3-architecture)
4. [Layer 1 — Edge acquisition](#4-layer-1--edge-acquisition)
5. [Layer 2 — Physics](#5-layer-2--physics)
6. [Layer 3 — AI and analytics](#6-layer-3--ai-and-analytics)
7. [Layer 4 — Twin core](#7-layer-4--twin-core)
8. [Layer 5 — Operator console](#8-layer-5--operator-console)
9. [Central fleet server](#9-central-fleet-server)
10. [Shared modules](#10-shared-modules)
11. [The twin state schema](#11-the-twin-state-schema)
12. [The feature contract and model inventory](#12-the-feature-contract-and-model-inventory)
13. [Configuration reference](#13-configuration-reference)
14. [HTTP and WebSocket API](#14-http-and-websocket-api)
15. [Security model](#15-security-model)
16. [Squadron operations model](#16-squadron-operations-model)
17. [Build, run and developer workflow](#17-build-run-and-developer-workflow)
18. [Test architecture](#18-test-architecture)
19. [Continuous integration and container](#19-continuous-integration-and-container)
20. [Data, models and artefact layout](#20-data-models-and-artefact-layout)
21. [Scripts reference](#21-scripts-reference)
22. [Measured performance](#22-measured-performance)
23. [Extension guides](#23-extension-guides)
24. [Deployment roadmap](#24-deployment-roadmap)
25. [Known limitations](#25-known-limitations)
26. [Engineering conventions](#26-engineering-conventions)
27. [Glossary](#27-glossary)

---

## 1. System summary

### 1.1 What the software is

ASTRA is a **digital twin** of a specific aero piston engine — the BRP-Rotax
915 iS / iSc A, a 104 kW turbocharged four-cylinder engine used on Medium
Altitude Long Endurance (MALE) unmanned aircraft. The twin runs continuously
alongside the engine, consumes its live telemetry, and reports the engine's
internal condition in real time.

The system is a **complete vertical slice**: engine physics, CAN bus transport,
edge validation and alerting, three-tier anomaly detection, health indices,
remaining-life estimation, mission-reliability assessment, flight recording and
replay, a PDF post-flight report, a role-based defence-standard operator
console, and a squadron-operations workflow that turns the twin's findings into
signed maintenance actions.

There is **no physical engine and no mock data path**. Telemetry originates in
the Layer 2 physics model, is encoded into real CANaerospace frames, transmitted
on a real `python-can` bus object, and decoded and validated by Layer 1 exactly
as hardware telemetry would be. Everything the console shows comes from a
physics step that actually ran.

### 1.2 The central measurement

The system's core idea is the **residual**. A second instance of the engine
model — the *shadow twin*, [`layer4_core/shadow_model.py`](../layer4_core/shadow_model.py)
— is held permanently at zero hours and driven by the same throttle, speed,
altitude and outside air temperature as the real engine. The difference between
what the engine reads and what an as-new engine would read at the same
operating point is the residual, and it moves from the first flight hour, long
before any absolute reading approaches a certified limit.

The naive implementation — reusing the simulator's own outputs as the
"prediction" — yields a residual of exactly zero always, because the same
degraded model generated both sides. It looks like a working digital twin and
is not one. The shadow model exists specifically to avoid that.

A second, related signal is **control authority**: on a FADEC engine with
closed-loop control, degradation is spent actuator travel (wastegate, cooling
flap) before it is a changed temperature. Both residuals and actuator positions
are first-class model inputs — see [§12](#12-the-feature-contract-and-model-inventory).

### 1.3 What it answers, continuously

| Question | Where answered |
|---|---|
| What condition is this engine in right now? | health indices, [§6.4](#64-health-indices) |
| Is anything going wrong, and in which subsystem? | three-tier detection, [§6.2](#62-detection-tiers) |
| How long before it needs maintenance? | RUL and survival, [§6.5](#65-remaining-useful-life-and-survival) |
| Will it complete the mission it has been assigned? | mission reliability, [§7.5](#75-mission-planning-and-assessment) |

### 1.4 Problem-statement coverage

Coverage is **executable**, not asserted. `python scripts/ps_compliance.py`
walks every requirement in [`docs/ps.md`](ps.md), checks for the artefact that
satisfies it, and marks it `BUILT`, `PARTIAL`, `DESIGNED` or `MISSING`. A
requirement is `BUILT` only when something in the repository demonstrates it
now; a design in a PRD counts as `DESIGNED`. The README records
**82 / 86 BUILT, 0 MISSING**. The script exits non-zero on a regression and
runs in CI.

| PS section | Where it lives |
|---|---|
| A · Digital twin core framework | `layer4_core/twin_state.py`, `shadow_model.py`, `live.py` |
| B · Health monitoring, 8 parameters | `layer3_ai/health.py`, `battery.py`, `layer2_physics/ecu.py`, `layer1_edge/order_analysis.py` |
| C · Fault detection and predictive analytics, 8 faults | `layer1_edge/edge_rules.py`, `layer3_ai/tier2_statistical.py`, `tier3_deep.py`, `fault_namer.py`, `rul_fault.py` |
| D · AI/ML layer | `layer3_ai/` in full — detection, RUL, trend, advisory, OOD, PINN, federated |
| E · Simulation and replay | `layer4_core/scenarios.py`, `flight_sim.py`, `replay.py`, `sortie_replay.py`, `recorder.py` |
| F · Visualisation dashboard | `layer5_viz/gcs_console/`, `layer4_core/operator_view.py`, `report_pdf.py` |
| Innovation areas | physics-informed AI `layer3_ai/pinn.py`; edge AI `layer1_edge/edge_infer.py`; federated `layer3_ai/fed/`; explainable `layer3_ai/explain.py`; secure telemetry `layer1_edge/secure_link.py`; autonomous advisory `layer3_ai/advisory.py` |

---

## 2. Technology stack and repository statistics

### 2.1 Runtime requirements

| Tool | Version | Needed for |
|---|---|---|
| Python | ≥ 3.11 (3.12 recommended) | the twin, models, API |
| Node.js + npm | ≥ 18 | builds the operator console |
| Git LFS | any recent | trained models and the 3D engine asset |
| Docker | optional | containerised run |

### 2.2 Python dependency groups

Declared in [`pyproject.toml`](../pyproject.toml). Nothing is declared for work
that has not been written — `scripts/licence_audit.py` fails on an import that
is not declared, and on a declaration nothing imports.

| Group | Packages | Notes |
|---|---|---|
| core | numpy, scipy, pandas, pyarrow, pyyaml, pydantic, python-can, cantools, paho-mqtt, scikit-learn **==1.7.2**, catboost, fastapi, uvicorn, websockets | scikit-learn is pinned **exactly**: the Tier-2 ensemble and the survival calibrator are pickles, and scikit-learn supports unpickling only in the version that pickled |
| `ml` | torch | training only; deliberately **off** the serving path so the edge image stays small |
| `edge` | onnx, onnxruntime | run exported networks without torch |
| `physics` | cantera | optional by decision D7 — a precomputed flame lookup ships in-repo |
| `reports` | reportlab | PDF post-flight report |
| `fleet` | asyncpg | central fleet server (Apache-2.0, async-native) |
| `security` | pyjwt[crypto], bcrypt, cryptography | **required to start the API** — `twin_api` imports `layer4_core.security` at module scope, which imports all three unguarded |
| `docs` | python-pptx | builds the SIH idea deck |
| `dev` | pytest, pytest-asyncio, httpx, ruff, mypy, psutil, pypdf | tooling |

`python-can` is LGPL-3.0-only — the single non-permissive licence in the
closure. It is imported as a separable, replaceable library, which satisfies the
LGPL, and is recorded as a distribution constraint in
[`docs/INDIGENISATION.md`](INDIGENISATION.md) rather than discovered at handover.

`catboost` was chosen for the survival head on a measured comparison against
scikit-learn's `HistGradientBoosting` and LightGBM **on this data**; scikit-learn
remains the automatic fallback where catboost is absent.

### 2.3 Console stack

React 18 + TypeScript 5.6, built with Vite 5. `three` 0.160 renders the 3D
engine model. No UI framework and no chart library: the widgets, gauges and
traces are written against the MIL-STD-1472H / MIL-STD-411F semantics in
[`docs/PRD_Part4_Defence_HMI_Standard.md`](PRD_Part4_Defence_HMI_Standard.md),
which is why Grafana was rejected (decision D2 — it cannot express 411F
alerting semantics, master caution/warning, or 1472H coding rules).

### 2.4 Size of the system

| Part | Measure |
|---|---|
| Python, whole tree excluding `.venv` | 71,351 lines |
| Python, the seven shipped packages excluding tests | 41,550 lines |
| Console TypeScript / TSX | 12,377 lines in 39 files |
| Configuration YAML | 2,788 lines (`thresholds.yaml` alone is 1,366) |
| CAN database | `configs/can/engine.dbc`, 20 KB, generated |
| Test functions | 923 across 71 files in 5 suites |
| HTTP routes on the twin API | 74, plus 1 WebSocket |
| HTTP routes on the fleet server | 6 |
| Utility, training and evaluation scripts | 52 |

Lines per package, tests included:

| Package | Lines |
|---|---|
| `layer4_core` | 25,474 |
| `layer3_ai` | 13,765 |
| `scripts` | 13,170 |
| `layer2_physics` | 9,342 |
| `layer1_edge` | 7,278 |
| `common` | 722 |
| `fleet_server` | 499 |
| `tests` (cross-cutting) | 289 |

Largest single modules: `layer4_core/twin_api.py` (3,468), `layer4_core/live.py`
(3,114), `layer4_core/report_pdf.py` (2,386), `layer2_physics/mvem.py` (1,543),
`layer2_physics/engine_sim.py` (1,319).

---

## 3. Architecture

### 3.1 The five layers

```
       Rotax 915 iS physics model  (there is no physical engine)
                     │  sensor frames
                     ▼
  ┌──────────────────────────────────────────────────────────────┐
  │ LAYER 1 · EDGE       CANaerospace encode → bus → decode       │
  │  layer1_edge/        5 validation methods · 5 value states     │
  │                      44-rule alert engine · 72 h SQLite buffer │
  │                      MQTT downlink (Will) · HMAC frame auth    │
  │                      MAVLink EFI_STATUS · ONNX edge inference  │
  └──────────────────────────────────────────────────────────────┘
          │ validated telemetry                    │
          ▼                                        ▼
  ┌───────────────────────────┐        ┌──────────────────────────┐
  │ LAYER 2 · PHYSICS         │        │ LAYER 3 · AI             │
  │  layer2_physics/          │        │  layer3_ai/              │
  │  0-D mean-value model     │        │  34-column feature set   │
  │  Cantera combustion       │───────▶│  Tier 2 statistical      │
  │  turbo + intercooler      │residuals  Tier 3 deep            │
  │  two-node thermal         │        │  fusion · OOD · PINN     │
  │  ECU/FADEC scheduling     │        │  health · RUL · survival │
  │  6 degradation pathways   │        │  advisory · explain      │
  │  run-to-failure generator │        │  federated learning      │
  └───────────────────────────┘        └──────────────────────────┘
          │                                        │
          └────────────────┬───────────────────────┘
                           ▼
  ┌──────────────────────────────────────────────────────────────┐
  │ LAYER 4 · TWIN CORE   layer4_core/                            │
  │  Pydantic twin state (reported/desired/simulated/predicted)    │
  │  as-new shadow model · live pipeline thread · sensor monitors  │
  │  mission reliability · route cost · terrain · scenarios        │
  │  flight recorder · replay · PDF report · test-rig mode         │
  │  squadron operations · security · REST + WebSocket API         │
  └──────────────────────────────────────────────────────────────┘
                           │ REST + WS
                           ▼
  ┌──────────────────────────────────────────────────────────────┐
  │ LAYER 5 · CONSOLE   layer5_viz/gcs_console/                   │
  │  React + TypeScript on MIL-STD-1472H / MIL-STD-411F           │
  └──────────────────────────────────────────────────────────────┘
                           │ optional store-and-forward
                           ▼
              fleet_server/   central fleet tier (FastAPI + Postgres)
```

### 3.2 The per-tick data flow

One tick of [`layer4_core/live.py`](../layer4_core/live.py), the first and only
place all five layers run as one thing:

```
physics step                       layer2_physics.engine_sim
  → instrument model               noise, bias, resolution, lag, dropout
  → CANaerospace encode            layer1_edge.can_simulator (cantools)
  → real python-can bus            interface="virtual" | "socketcan" | "pcan"
  → CANaerospace decode            layer1_edge.can_ingest
  → 5 validation methods           value state assigned per channel
  → Tier-1 rules                   layer1_edge.edge_rules → alerts
  → shadow twin prediction         as-new values at the same operating point
  → residuals                      measured − as-new
  → twin state synchronise         layer4_core.twin_state.TwinSynchroniser
  → health indices                 layer3_ai.health
  → Tier-2 scoring, Tier-3 if served
  → fusion                         layer3_ai.fusion → one verdict
  → RUL / survival / advisory / OOD
  → operator-view smoothing        layer4_core.operator_view
  → snapshot published
```

### 3.3 Process and threading model

The system runs as a **single Python process** by default.

- `layer4_core.twin_api` is a FastAPI app served by uvicorn.
- The pipeline runs on a **background thread** that advances the simulation on
  a steady clock whether or not a client is connected, and publishes an
  immutable **snapshot**. Readers never touch pipeline state; a slow console
  cannot stall the engine.
- The WebSocket pushes **complete snapshots**, not deltas. A console open for
  an hour and one that just connected render identically, and a dropped frame
  costs one frame of latency rather than permanent divergence. Frames are
  **tiered**: readings at 4 Hz (`dashboard_live_refresh_s` = 0.25 s), the full
  snapshot including the two ~30 KB chart series at 0.5 Hz
  (`dashboard_refresh_s` = 2.0 s). A partial frame is flagged `partial` and the
  client merges it over what it holds; a full frame always replaces. The
  distinction is load-bearing: on a full frame an **absent field means the
  system is declining to publish it**, and that meaning must survive.
- The `fleet_server` is a **separate optional process** with its own database.

### 3.4 Architectural rules the code enforces

**One aircraft on the ground station at a time**, as a real GCS works. The
aircraft on the GCS has its engine twin running; the others are parked and
represented by the condition their last engine run measured. Each engine's life
persists in `data/twin_state/<twin_id>.pkl`.

**Degradation ground truth never shares code with its estimator.**
`layer2_physics/degradation.py` generates truth and is imported by the simulator
and the dataset generator; nothing in `layer3_ai` imports it except the offline
evaluation scripts that compare estimate against truth. Without that separation
every reported metric would be circular.

**An invalid reading is removed, never substituted.** A frozen last-good value
that still looks plausible is the most dangerous failure mode a monitoring
system has, so the HMI shows `———` and the reason rather than a stale number
(PRD Part 4 §7.2).

**No fallback path invents a plausible number** — see
[§26.2](#262-a-number-is-shown-only-when-it-was-earned).

**Nothing hard-codes a limit** (decision D6). Every threshold, weight and engine
dimension lives in `configs/*.yaml`, read only through `common/config.py`.

**Transport is a configuration string.** Moving from simulation to hardware
changes `virtual` → `socketcan`, the DBC file, and the engine profile. The
physics, twin, detectors, health indices and console all consume validated
telemetry and are indifferent to its origin.

### 3.5 Binding design decisions

From [`docs/prd/PROJECT_PLAN.md`](prd/PROJECT_PLAN.md) §3. Read these before
changing anything structural.

| ID | Decision | Reason |
|---|---|---|
| D1 | Virtual CAN via `python-can` `virtual` bus, not Linux `vcan0` | host is Windows; SocketCAN path kept behind a config flag for Linux/RPi |
| D2 | Custom React + TypeScript console, not Grafana/Streamlit | Grafana cannot express MIL-STD-411F alerting semantics |
| D3 | PyTorch (CPU) + ONNX Runtime INT8, not TensorFlow/TFLite | ONNX Runtime ships for Windows *and* ARM64, so one artefact runs on the edge target |
| D5 | SQLite + Parquet for demo storage | zero-setup; InfluxDB behind the same interface |
| D6 | All thresholds and constants in `configs/*.yaml` | no magic numbers in code |
| D7 | Cantera optional | a Cantera-generated flame lookup ships in-repo; an equilibrium solve per sample blows the tick budget |
| D8 | CHI = composite health index, CombHI = combustion | naming collision fixed |
| D9 | Latency claim: <100 ms median / <200 ms p95 pipeline; <50 ms edge rule path | arithmetic honesty |
| D10 | Reference engine = Rotax **915 iS / iSc A**, superseding the 914 | the 914 is carburetted with no FADEC and no CAN bus, so it cannot satisfy the PS's own CAN and FADEC requirements; 915 iS limits are traceable to EASA TCDS E.121 |
| D11 | Every engine value is provenance-tagged in YAML | a domain expert will check the numbers; marking manufacturer data against modelling assumptions is the difference between a defensible and an unfalsifiable model |
| D12 | CAN modelled as CANaerospace, generated by `scripts/gen_can_dbc.py` | the Rotax Display CAN *is* CANaerospace; the exact Rotax assignment is proprietary, so ours uses open standard IDs and says so |

---

## 4. Layer 1 — Edge acquisition

`layer1_edge/` · 7,278 lines · 141 tests in 9 files

The acquisition and safety layer. It has **no network dependency and no
dependency on any trained artefact** by construction: rules, buffering and
alerting continue with the ground link down.

| Module | Lines | Responsibility |
|---|---|---|
| [`can_ingest.py`](../layer1_edge/can_ingest.py) | 919 | decode CANaerospace frames, validate, assign value states |
| [`can_simulator.py`](../layer1_edge/can_simulator.py) | 402 | encode the physics model's output as real CANaerospace frames onto a `python-can` bus |
| [`edge_rules.py`](../layer1_edge/edge_rules.py) | 1,105 | Tier-1 rule engine — the deterministic alerting path |
| [`edge_buffer.py`](../layer1_edge/edge_buffer.py) | 297 | 72-hour store-and-forward SQLite (WAL) buffer |
| [`edge_infer.py`](../layer1_edge/edge_infer.py) | 322 | Tier-3 ONNX inference on the aircraft, without PyTorch |
| [`order_analysis.py`](../layer1_edge/order_analysis.py) | 431 | envelope order analysis of the vibration waveform |
| [`sensor_fusion.py`](../layer1_edge/sensor_fusion.py) | 263 | three-level fusion: Hampel, cross-correlation, lane voting |
| [`mqtt_link.py`](../layer1_edge/mqtt_link.py) | 346 | aircraft→ground telemetry link, and its Last Will and Testament |
| [`mavlink_efi.py`](../layer1_edge/mavlink_efi.py) | 305 | MAVLink 2 `EFI_STATUS` (msg 225) for a standard GCS |
| [`secure_link.py`](../layer1_edge/secure_link.py) | — | HMAC frame authentication over an untrusted downlink |

### 4.1 CAN transport

The **data** originates in the physics model; the **transport is not
simulated**. `can_simulator` encodes real CANaerospace v1.6 frames with
`cantools` and transmits them through `python-can` onto an actual bus object.
The bus is chosen by one configuration string:

| Value | Meaning |
|---|---|
| `virtual` | in-process, no hardware, no kernel module — demonstration |
| `socketcan` | Linux SocketCAN, real `can0` or `vcan0` — Raspberry Pi / rig |
| `pcan` | PEAK PCAN-USB adapter — bench |

`configs/can/engine.dbc` is **generated** by `scripts/gen_can_dbc.py` using
open CANaerospace identifiers. The Rotax Display CAN message assignment is not
public, so this DBC must not be presented as the Rotax database; on real
hardware it is replaced with the manufacturer's.

### 4.2 The five validation methods

Applied in `can_ingest` before anything downstream is allowed to believe a
number (PRD Part 1 §8.3):

| Method | Check |
|---|---|
| 1 · Range | value outside the physically possible band |
| 2 · Rate of change | change faster than physics permits |
| 3 · Cross-sensor consistency | the two FADEC lanes must agree |
| 4 · Staleness | tracked from the CANaerospace message-code sequence |
| 5 · Multi-source voting | lane A against lane B |

Two further checks live in Layer 4 but feed the same removal decision:

- **Frozen readings** — a working sensor's noise makes a long run of identical
  readings improbable. `can_ingest` derives, per sensor, the run length a
  working sensor produces with probability below
  `frozen_false_alarm_probability` (1e-9) and removes the reading from there.
  Measured on healthy flights, the longest identical run on any listed sensor
  was 9 readings.
- **Sensors that stop following the engine** —
  [`layer4_core/sensor_response.py`](../layer4_core/sensor_response.py). If over
  60 s the twin's prediction for a channel moves by ≥ 5 × the instrument's noise
  and the reading by ≤ 2 ×, the sensor is not following the engine and its
  reading is removed, restored when a later window shows it following again.
  Measured: a working sensor's spread was never below 3.98 noise, a stuck one's
  never above 1.23.

### 4.3 The five value states

Every value carries a state that travels with it through the entire system
(PRD Part 4 §7.1):

| State | Meaning |
|---|---|
| `VALID` | decoded, in range, fresh |
| `STALE` | no update within the expected interval (`stale_after_intervals` = 3) |
| `INVALID` | failed a plausibility check |
| `MISSING` | never received |
| `SUSPECT` | plausible, but the redundant lane disagrees |

### 4.4 The rule engine

`build_rules()` returns **44 rules** for the Rotax 915 iS definition (the README
quotes 43, which is one behind). Composition, measured at runtime:

| Rule type | Count | What it catches |
|---|---|---|
| `ThresholdRule` | 26 | parameter outside an absolute limit |
| `CorrelationRule` | 11 | a cross-parameter relationship violated |
| `DeviationRule` | 3 | measured minus commanded, for FADEC-scheduled channels |
| `PersistenceRule` | 2 | out of band continuously for a duration |
| `RateRule` | 2 | moving faster than is safe |

Alert semantics come from MIL-STD-411F via PRD Part 4 §4. Five levels, defined
in `configs/thresholds.yaml → alert_levels`:

| Level | Name | Category | CHI above | Audio | Recorded for maintenance |
|---|---|---|---|---|---|
| 1 | GREEN | NORMAL | 0.90 | none | no — 411F generates no message |
| 2 | BLUE | ADVISORY | 0.85 | none | no — 411F 5.2.10 |
| 3 | YELLOW | CAUTION | 0.75 | repeat until ack | yes |
| 4 | ORANGE | CAUTION | 0.60 | repeat until ack, 5 s | yes |
| 5 | RED | WARNING | 0.00 | continuous | yes |

Alerting behaviour, also configured: minimum display 3.0 s (411F 5.2.5.5),
master reset re-arm, 3 Hz flash at 0.5 duty, visible stack depth 6 with
overflow beyond it (411F 5.2.5.3), legend ≤ 24 characters.

**Inhibits** (411F 5.2.6.2) prevent nuisance alerts when nothing is wrong:
ground-phase inhibits for `OIL TEMP LOW` and `CHT LOW`; a 25 s engine-start
settle; a minimum running speed of 1,800 rpm; and suppression of rate rules
during a commanded throttle transient (> 6 %/s) plus a 30 s settle, because a
throttle slam legitimately moves temperatures fast and that is the operator's
doing, not a fault.

### 4.5 Offline operation

`edge_buffer` holds 72 hours of telemetry in SQLite WAL — on every Python
install, survives power loss, needs no server, runs on a Raspberry Pi. Frames
are stored as compact rows rather than JSON blobs so 72 hours fits an industrial
microSD budget. On reconnect, data is uploaded oldest-first and the operator is
told **which time span was back-filled**, so replayed history is never mistaken
for live telemetry (PRD Part 4 §7.3c). Alerts raised offline keep their original
timestamps, because *when* a fault started matters more than when it was
reported.

### 4.6 The downlink, and why MQTT

Two different links were being conflated:

| Hop | Transport | Why |
|---|---|---|
| ground server → browser | WebSocket | browser-native, one connection, inside TLS, wants complete snapshots |
| **aircraft → ground** | **MQTT** | lossy, intermittent, outside the aircraft's control |

The feature that justifies MQTT is the **Last Will and Testament**: the broker
*announces* a lost airframe instead of the ground station inferring it from a
timeout. That distinguishes two states a crew station must keep apart — "the
aircraft is gone" and "the aircraft is fine and the ground station stopped
hearing it".

`secure_link.py` adds HMAC authentication of the frames themselves, which is
what survives a terminated TLS session, a replayed capture, or a compromised
relay — and a UAV downlink passes through relays by design. TLS in `twin_api`
covers interception; frame authentication covers tampering. They are separate
mechanisms because they defend different things.

### 4.7 Edge inference

The Tier-3 network is trained in PyTorch on a workstation and exported **once,
on the ground**, to ONNX; the aircraft runs it with `onnxruntime`. PyTorch is
not what you put on a UAV — several hundred megabytes and a general-purpose
autodiff framework being used for a fixed forward pass.

Quantisation is **measured, not assumed**: dynamic INT8 is 2.94× smaller and,
across 300 windows, changed **one decision**.

### 4.8 Vibration order analysis

`engine_sim.vibration_waveform()` generates a 10 kHz signal containing 1×
unbalance, 2× misalignment, gear mesh, firing frequency and — when a bearing is
worn — BPFO and BPFI impulses on a structural resonance. `order_analysis`
resamples to equal increments of **crank angle** rather than time, so a defect
frequency becomes a fixed *order*: a pure function of bearing geometry,
independent of rpm. A plain spectrum smears when shaft speed moves, and on a UAV
in a climb it moves constantly.

The four bearing defect orders (BPFO, BPFI, BSF, FTF) are model features. RMS
and kurtosis say a bearing is rough; the order spectrum says **which race is
spalling**, which is the difference between "inspect the engine" and a named
part.

---

## 5. Layer 2 — Physics

`layer2_physics/` · 9,342 lines · 104 tests in 6 files

| Module | Lines | Responsibility |
|---|---|---|
| [`mvem.py`](../layer2_physics/mvem.py) | 1,543 | 0-D mean-value engine model — the beating heart |
| [`engine_sim.py`](../layer2_physics/engine_sim.py) | 1,319 | the virtual engine: physics plus instrumentation |
| [`synth_data_gen.py`](../layer2_physics/synth_data_gen.py) | 1,056 | run-to-failure dataset generator |
| [`degradation.py`](../layer2_physics/degradation.py) | 892 | six degradation pathways, eight injectable faults |
| [`perf_maps.py`](../layer2_physics/perf_maps.py) | 598 | five interpolated performance maps |
| [`combustion.py`](../layer2_physics/combustion.py) | 489 | adiabatic flame temperature, burned-gas composition, EGT baseline |
| [`om_table.py`](../layer2_physics/om_table.py) | 456 | the manufacturer's 941-point performance table as a lookup |
| [`ecu.py`](../layer2_physics/ecu.py) | 386 | FADEC ignition and injection scheduling |
| [`turbo.py`](../layer2_physics/turbo.py) | 356 | turbocharger, wastegate, intercooler, boost lag |
| [`atmosphere.py`](../layer2_physics/atmosphere.py) | 316 | ISA atmosphere and six environmental profiles |

### 5.1 The mean-value engine model

State vector integrated with `scipy.integrate.solve_ivp` (RK45):

```
x = [ omega, P_man, T_CHT_1..N, T_oil ]

omega     crankshaft angular velocity   [rad/s]   engine–propeller torque balance
P_man     intake manifold pressure      [Pa]      filling and emptying
T_CHT_i   cylinder head temperature     [K]       lumped head capacity
T_oil     bulk oil temperature          [K]       friction heat vs cooler
```

Everything else — torque, BMEP, EGT, oil pressure, fuel flow, BSFC, vibration —
is algebraic on that state.

### 5.2 Provenance of the engine numbers

The engine is modelled from BRP-Rotax's own documents: the Operator's Manual,
Installation Manual, both Maintenance Manuals, the Illustrated Parts Catalogue
and nine Service Instructions — **thirteen manuals**. They are not redistributed
(`engines manuals/` is git-ignored); values taken from them are tagged in place:

| Tag | Source |
|---|---|
| `[TCDS]` | EASA type certificate data sheet E.121 |
| `[OM]` | Operator's Manual |
| `[IM]` | Installation Manual |
| `[MML]` | Maintenance Manual (line / heavy) |
| `[DS]` | data sheet |
| `[DER]` | derived from tagged values |
| `[MOD]` | modelling choice, not published |

**No value that shapes engine behaviour is untagged.** Where the manuals
contradicted the implementation, the manuals won: two modelled thermostats that
do not exist in this engine were deleted, and a cylinder-head limit borrowed
from a different engine was corrected.

`perf_maps.py` is explicit about what is anchored and what is shaped: the
published data set is a handful of anchor points (104 kW take-off at 5,800 rpm,
99 kW max continuous at 5,500 rpm, critical altitude 15,000 ft, boost limit
1,730 hPa, SFC 280–310 g/kWh, and an explicit airflow-to-power closure relation
from OM §2.1). No manufacturer publishes a full four-dimensional map, so the
grids are generated by analytic shape functions **pinned** to those anchors and
regenerated deterministically at import.

`om_table.py` supplies what no certificate publishes and what a MALE UAV spends
its life in: behaviour **away** from sea-level ISA. 941 operating points at
4,500/5,000/5,500/5,800 rpm, eight throttle positions, sea level to 22,999 ft,
ISA−15 to ISA+30. Every quantity is returned as a **ratio** to the same engine's
sea-level ISA value at the same speed and lever, so the certified anchors are
untouched by construction.

### 5.3 Combustion

Cantera with GRI-Mech 3.0 when installed, a Cantera-generated lookup table when
not (decision D7). Two ignition modes, selected by `identity.ignition` in the
engine YAML:

| Mode | Behaviour |
|---|---|
| `SPARK` | premixed charge, equivalence ratio near stoichiometric, flame temperature peaks slightly rich (φ ≈ 1.05) |
| `COMPRESSION` | diesel: globally lean (φ 0.3–0.8) with locally stoichiometric diffusion burning, so peak temperature is set by the local flame |

That split is the *entire* code difference between the Rotax reference engine
and the Austro AE330 diesel adaptation.

### 5.4 Degradation pathways and fault modes

Six physical **degradation pathways**, each with a rate law, an effect on the
physics, and a maintenance threshold:

`COOLING` · `OIL_THERMAL` · `COMBUSTION_DEPOSITS` · `INJECTOR_FOULING` ·
`BEARING_WEAR` · `TURBOCHARGER`

Eight injectable **fault modes**, the eight the problem statement names:

`MISFIRE` · `INJECTOR_ABNORMAL` · `COOLING_DEGRADATION` · `LUBRICATION_ISSUE` ·
`SENSOR_DRIFT` · `COMBUSTION_INSTABILITY` · `OVERHEATING_TREND` ·
`ABNORMAL_VIBRATION`

Sensor drift is **not injectable** through this API — the instrument layer models
it directly, and injecting it as well would double-count it.

**Damage does not heal.** Clearing an injected fault stops it progressing; it
does not repair the engine. Only maintenance restores a pathway, and only the
one it physically renews (`MAINTENANCE_REMOVES`; `INSPECTIONS` = A5, A6 restore
nothing unless parts were replaced). A test enforces this for all eight modes:
[`test_damage_is_permanent.py`](../layer2_physics/tests/test_damage_is_permanent.py),
[`test_maintenance_actions.py`](../layer2_physics/tests/test_maintenance_actions.py).

### 5.5 Instrumentation

`engine_sim` adds the layer a real engine is observed through: per-channel
noise, bias, finite resolution, first-order lag and dropout. Training on clean
model output is the documented trap (PRD Part 0 §0.5); rows carry what the
**sensors** said, not what the model computed.

### 5.6 The run-to-failure dataset generator

200 virtual engines, each flown until its health index crosses the maintenance
threshold, written as Parquet with a strict train/val/test split **by engine**.
Four defences against the training-data trap, all implemented:

1. **Stochastic faults** — random times, severities and ramp rates, so no two
   engines fail the same way.
2. **Manufacturing spread** — each engine gets its own physics parameters and
   degradation rates (log-normal, so rates stay positive). A network cannot
   memorise one trajectory because there is no one trajectory.
3. **Real instrumentation** — rows carry sensor readings, not model truth.
4. **Split by engine** — every reported figure is on engines the models have
   never seen. `scripts/eval_split_inflation.py` measures how much a random-row
   split would have inflated the result.

Generation: `python -m layer2_physics.synth_data_gen --engines 100 --workers 7`
— roughly 50 minutes on 7 cores, ~96 MB.

---

## 6. Layer 3 — AI and analytics

`layer3_ai/` · 13,765 lines · 322 tests in 24 files

| Module | Lines | Responsibility |
|---|---|---|
| [`features.py`](../layer3_ai/features.py) | 731 | **the feature contract** — one definition per feature, shared by training and serving |
| [`health.py`](../layer3_ai/health.py) | 603 | composite health index, four subsystems, nine sub-indices |
| [`advisory.py`](../layer3_ai/advisory.py) | 575 | costed, scheduled maintenance recommendations |
| [`tier3_deep.py`](../layer3_ai/tier3_deep.py) | 572 | LSTM autoencoder + multi-task supervised network |
| [`rul_physics.py`](../layer3_ai/rul_physics.py) | 568 | interpretable RUL: health trend / rate of decline, Kalman-filtered |
| [`tier2_statistical.py`](../layer3_ai/tier2_statistical.py) | 523 | isolation forest, CBLOF, matrix profile ensemble |
| [`rul_survival.py`](../layer3_ai/rul_survival.py) | 519 | P(failure within horizon) — the prognostic question that has an answer |
| [`rul_lstm.py`](../layer3_ai/rul_lstm.py) | 483 | data-driven RUL from sequences |
| [`rul_serving.py`](../layer3_ai/rul_serving.py) | 458 | serve the trained RUL network without train/serve skew |
| [`rul_fault.py`](../layer3_ai/rul_fault.py) | 409 | per-fault time-to-action |
| [`explain.py`](../layer3_ai/explain.py) | 401 | exact attribution where an exact answer exists; SHAP only where it does not |
| [`fed/federated.py`](../layer3_ai/fed/federated.py) | 398 | FedAvg across a fleet — raw telemetry never leaves the aircraft |
| [`sortie_features.py`](../layer3_ai/sortie_features.py) | 396 | per-sortie aggregation: the degradation view a 30 s window cannot hold |
| [`prognostic_metrics.py`](../layer3_ai/prognostic_metrics.py) | 382 | α-λ accuracy, prognostic horizon, NASA score |
| [`cmapss.py`](../layer3_ai/cmapss.py) | 332 | NASA C-MAPSS benchmark — the outside yardstick |
| [`fusion.py`](../layer3_ai/fusion.py) | 309 | three-tier score fusion |
| [`pinn.py`](../layer3_ai/pinn.py) | 291 | physics-informed hybrid model |
| [`ood.py`](../layer3_ai/ood.py) | — | is this sample like the training data? |
| [`battery.py`](../layer3_ai/battery.py) | 271 | battery state of health from discharge events |
| [`fault_namer.py`](../layer3_ai/fault_namer.py) | 251 | which fault is it, using the engine's history |
| [`efficiency.py`](../layer3_ai/efficiency.py) | — | BSFC, volumetric and thermal efficiency, and their trends |
| [`survival_serving.py`](../layer3_ai/survival_serving.py) | — | serve the calibrated failure probability to the live twin |

### 6.1 The feature contract

`features.py` is the single most important module for correctness. If training
features and serving features are built by two different pieces of code they
will drift apart, and the failure is **silent**: the model keeps returning
confident numbers about a different engine than the one on the aircraft. There
is exactly one definition of each feature and both paths call it.

Three named sets:

| Set | Columns | Contents |
|---|---|---|
| `PRD7` | 7 | the raw channels the PS names: rpm, CHT max, EGT max, oil pressure, oil temperature, fuel flow, vibration RMS |
| `EXTENDED` | **34** | PRD7 + 6 physics residuals + 21 derived |
| `EXTENDED_OPS` | 34 + condition | EXTENDED plus the flight condition it was measured at (Tier-2 only) |

The 6 residuals: `res_cht`, `res_coolant`, `res_egt`, `res_oil_pressure`,
`res_oil_temperature`, `res_fuel_flow`.

The 21 derived, grouped by what they exist to see:

| Group | Columns |
|---|---|
| thermal / combustion spread | `cht_minus_coolant`, `cht_spread`, `egt_spread` |
| FADEC scheduling | `injection_deviation_max`, `knock_retard_deg`, `injector_duty` |
| vibration magnitude | `vibration_kurtosis` |
| structured residual (FDI) | `res_isolation`, `res_n_excursions`, `res_top_abs` |
| **actuator authority** | `wastegate_pct`, `cooling_flap_pct`, `res_wastegate`, `res_cooling_flap` |
| lane disagreement | `rpm_lane_delta`, `map_lane_delta` |
| cycle-to-cycle variation | `egt_scatter` |
| bearing defect orders | `vib_bpfo`, `vib_bpfi`, `vib_bsf`, `vib_ftf` |

Actuator authority earns its place on measurement: across 18 operating points,
losing 30 % of the cooling air moves the flap **31.8 sensor-sigmas** and the best
temperature channel **4.0**; a turbocharger worn from 1.00 to 0.55 moves brake
power by 0.1 kW and the wastegate by 0.29 of its travel.

Two mechanisms keep the contract honest:

- **`FORBIDDEN_PREFIXES` / `FORBIDDEN_EXACT`** — ground truth the aircraft cannot
  observe (`deg_`, `lab_`, `chi_`, `thi_`, `mhi_`, `comb_hi_`, `rul_hours`,
  `censored`, `any_fault`) and identifiers a model could memorise (`engine_id`,
  `split`, `sortie`, `t_s`) can never reach a model input. Enforced by
  [`test_no_leakage.py`](../layer3_ai/tests/test_no_leakage.py).
- **Fixed centres and scales** from `configs/thresholds.yaml → feature_norm`, not
  per-batch statistics. Per-batch normalisation makes a sample's features depend
  on whichever other samples arrived with it — fine in training, meaningless at
  inference where samples arrive one at a time.

`features.py` also records features that were **measured out again**:
`rpm_scatter` and `egt_spread_scatter` had real single-feature evidence
(AUC 0.707 and 0.736 against the exhaust residual's 0.599) and still cost more
in dilution than they were worth — combustion instability 0.372 → 0.283,
macro-F1 0.607 → 0.588. They are still computed so the measurement can be
repeated cheaply, and are not served.

### 6.2 Detection tiers

Each tier answers a different question and fails in a different way:

| Tier | Where | Method | Failure mode |
|---|---|---|---|
| 1 · rules | `layer1_edge/edge_rules.py` | certified limits, rates, persistence, correlation, deviation | certain, immediate, and blind to anything that has not yet reached a limit |
| 2 · statistical | `layer3_ai/tier2_statistical.py` | isolation forest + CBLOF + matrix profile; unsupervised | catches subtle multivariate drift; over-fires |
| 3 · deep | `layer3_ai/tier3_deep.py` | LSTM autoencoder (unsupervised) + multi-task supervised net (anomaly / fault class / severity) | precise, and conservative to the point of missing a third of what is there |

PyOD and dtaianomaly are named in the PRD and **not** used: they pin numpy and
scikit-learn versions that conflict with the rest of the stack. The requirement
is the *algorithms*, not the packages — isolation forest comes from
scikit-learn, and CBLOF and the matrix profile are short enough to implement and
test directly. Every parameter lives in `thresholds.detectors.tier2`.

Tier 2 uses **per-condition limits**: a threshold that is right at cruise is
wrong on a climb. That change took false alarms per engine-hour from 0.29 to
**0.20**.

### 6.3 Fusion

`fusion.py` combines the tiers. Measured on held-out engines, the two model
tiers fail in **opposite** directions — the autoencoder 0.974 recall at 0.948
precision, the supervised head 1.000 precision at 0.672 recall. Neither alone is
the answer, and fusing them is where most of the remaining accuracy is.

| Detector | ROC-AUC | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| Tier 2 — statistical ensemble | 0.915 | 0.969 | 0.530 | 0.686 | 0.051 |
| Tier 3 — autoencoder | 0.916 | 0.937 | 0.241 | 0.384 | 0.049 |
| Tier 3 — deep anomaly head | 0.962 | 0.983 | 0.936 | 0.959 | 0.049 |
| **Fused** | **0.989** | **0.996** | **0.870** | **0.929** | **0.010** |

The combiner is chosen on **validation**, and where two combiners tie on
validation F1 the one with the lower validation false-alarm rate wins — a rule
fixed before the test engines are touched. Every combiner's curve is in
`data/models/fusion_report.json`.

### 6.4 Health indices

The composite health index (CHI) is the one number an operator reads first and
the number every maintenance decision hangs off, so it has to mean the same
thing on a cold cruise and a hot climb.

The PRD's specified formulas were **absolute**:
`THI = 1 − max(0, (CHT_max − 105) / (135 − 105))`. Cylinder head temperature
depends far more on what the throttle is doing than on engine condition:
measured on 83,000 rows from engines the simulator certifies as genuinely
healthy, that formula labels **25.7 %** of them degraded. The implementation
therefore scores against the **as-new twin at the same operating point**, not
against an absolute number.

Structure: CHI is a weighted sum of four subsystem scores, each of which is the
**minimum** of named sub-indices with published formulas:

| Subsystem | Sub-indices |
|---|---|
| thermal | `thermal_index`, `oil_thermal_index`, `cht_spread_index` |
| mechanical | `mechanical_index`, `lubrication_index`, `rpm_stability_index` |
| combustion | `combustion_index`, `egt_efficiency_factor`, `fuel_system_index` |
| electrical | `electrical_index` |

Bands come from `configs/thresholds.yaml → health`; `band_for(chi)` maps a score
to `EXCELLENT` / `GOOD` / `FAIR` / `POOR` / `CRITICAL`. Measured against ground
truth: MAE **0.077**, 0.6 % of healthy engines mislabelled.

Because CHI is a closed-form weighted sum of minima, **every contribution to it
can be computed exactly**. `explain.py` does that rather than sampling a SHAP
approximation of a quantity that can be written down; SHAP is used only for the
genuinely opaque parts.

### 6.5 Remaining useful life and survival

Four estimators, deliberately:

| Estimator | Question | Character |
|---|---|---|
| `rul_physics` | how long has this engine got? | `RUL = (CHI_now − CHI_threshold) / rate_of_decline`; Kalman-filtered rate, because RUL has that rate in a denominator and a line fit swings wildly; **interpretable** |
| `rul_lstm` | same question | learned from sequences; more accurate, cannot explain itself |
| `rul_fault` | when will *this fault* matter? | extrapolates a measured indicator to its fault threshold — "the cooling residual reaches its fault threshold in about 14 flight hours" |
| `rul_survival` | P(failure within H hours)? | calibrated CatBoost head, AUC 0.95–0.97 at 12/25/50 h horizons — **the project's strongest prognostic result** |

The PRD's specified loss function was **corrected**. It asked for
`L = 0.7·MSE + 0.3·Score` to "penalise late predictions more than early", and
the printed formula did the opposite — penalising the conservative case and
scoring over-prediction at exactly zero.

`rul_survival.py` documents why hours cannot be estimated accurately on this
fleet, and that it is a property of the data:

| Model, engine-grouped, 3,807 sortie rows | rmse/σ |
|---|---|
| our sensor model | 0.799–0.819 |
| **oracle**, given the simulator's own hidden wear state | 0.760 |
| + the entire true fault schedule | 0.752 |
| + the true future operating profile | 0.693 |

A model handed the hidden state, every future fault and the future flight
profile still cannot get below ~0.69 σ. Being within ~5 % of that means there is
no version of "try harder on the regression" that pays — which is why the
system serves a **calibrated probability** and withholds an uncalibrated hours
figure.

`prognostic_metrics.py` exists because RMSE answers the wrong question: **64.9 %
of test labels are censored or sitting at the 400 h horizon cap**, the target is
constant over that region, and an average hides the error in the 35 % anybody
cares about. α-λ accuracy and prognostic horizon are reported instead.

`sortie_features.py` addresses the observability limit directly: the estimator
read a 30-sample window — about 0.0013 % of an engine's life — and RUL is a
*rate*. Aggregating each sortie to one row with a rate-of-change term improves
rmse/σ from 0.874 to 0.775.

### 6.6 Out-of-distribution checking

`ood.py`: a trained model answers every question it is asked, including about
engines, conditions and failures it has never seen. Two quantities, fitted on
**healthy training rows only** and stored with the artefact so serving cannot
drift from them: the **Mahalanobis distance** of the 23-feature vector from the
training mean (which accounts for how features vary *together*), and a density
term. When a sample is unlike anything in training, **detection confidence drops
to zero and says so**.

On held-out engines the check flags **0.0 %** of both healthy and faulted rows —
the models are being asked only what they were trained to answer.

### 6.7 Physics-informed learning

`pinn.py` is exact about which of three meanings of "physics-informed" it is:

1. a network given physics-derived **features** — common, useful, already done
   here (residuals into Tiers 2 and 3, measured ROC-AUC 0.945 → 0.971), and
   not what anyone means by a PINN;
2. a network whose **output corrects a physics model** — the hybrid half;
3. a network whose **loss penalises violations of a governing relationship**,
   evaluated through the network's own derivatives — the actual PINN.

Measured: hybrid loss versus data-only gives RMSE 4.53 vs 4.57 — the same
accuracy — but physical-constraint violations fall **1.000 → 0.216**. The
physics term buys enforceable behaviour, not curve-fitting.

### 6.8 Federated learning

`fed/federated.py`: the point is **not** accuracy. A model trained on pooled
telemetry will always be at least as good, and pretending otherwise would be
dishonest. The point is that **raw telemetry never leaves the aircraft** — each
airframe trains on its own data and uploads only weights.

For a defence fleet that is the whole argument: engine telemetry is
operationally revealing (sortie length, altitude band, power setting, how hard
an asset is worked, where). FedAvg is implemented rather than imported from
Flower, because FedAvg is a weighted average of weight vectors. The accuracy
given up is **measured** by `scripts/eval_federated.py` rather than glossed.

### 6.9 The outside yardstick

`cmapss.py` runs the same RUL architecture, **untuned**, on NASA's C-MAPSS
turbofan benchmark:

| Subset | ASTRA RMSE | Published SOTA | Ratio |
|---|---|---|---|
| FD001 | 14.84 | 12.6 | 1.18× |
| FD002 | 14.18 | 13.1 | 1.08× |
| FD003 | 13.65 | 12.7 | 1.08× |
| FD004 | 15.59 | 14.0 | 1.11× |

C-MAPSS is a **turbofan** and shares no sensor and no failure mode with a piston
engine. The module deliberately provides **no merge, no shared feature space and
no pre-training entry point**: the claim is that the *method* is sound on real
benchmark data, and nothing more. No transfer-learning claim is made.

### 6.10 Maintenance advisory

`advisory.py` turns findings into decisions. "Cooling system degraded" is a
finding; "cooling system flush, 2 hours down, ₹5,000, do it within 25 flight
hours" is something a planner can schedule against. Ordering is by **urgency,
not severity** — two actions of equal severity are not equally pressing if one
has ten flight hours of margin and the other two hundred.

---

## 7. Layer 4 — Twin core

`layer4_core/` · 25,474 lines · 340 tests in 30 files. The largest layer, and
the integration point.

| Module | Lines | Responsibility |
|---|---|---|
| [`twin_api.py`](../layer4_core/twin_api.py) | 3,468 | FastAPI app: 74 routes + 1 WebSocket |
| [`live.py`](../layer4_core/live.py) | 3,114 | the live pipeline — all five layers, once per tick |
| [`report_pdf.py`](../layer4_core/report_pdf.py) | 2,386 | 15-section post-flight report as a filed document |
| [`twin_state.py`](../layer4_core/twin_state.py) | 1,243 | Pydantic twin state and the synchroniser |
| [`ops.py`](../layer4_core/ops.py) | 1,144 | squadron operations: aircraft, missions, defects, releases, logbook |
| [`flight_sim.py`](../layer4_core/flight_sim.py) | 1,144 | fly a planned route minute by minute and keep the track |
| [`security.py`](../layer4_core/security.py) | 1,060 | authentication, authorisation, hash-chained audit log |
| [`route_cost.py`](../layer4_core/route_cost.py) | 641 | what a proposed mission costs the engine, leg by leg |
| [`test_rig.py`](../layer4_core/test_rig.py) | 618 | engine test-cell mode |
| [`flight_record.py`](../layer4_core/flight_record.py) | 609 | what a post-flight report is made of: events with time and flight phase |
| [`fleet_sync.py`](../layer4_core/fleet_sync.py) | 464 | store-and-forward to the central fleet server |
| [`recorder.py`](../layer4_core/recorder.py) | 431 | flight data recorder — what makes replay real |
| [`mission.py`](../layer4_core/mission.py) | 414 | mission reliability: can this engine fly the mission in front of it? |
| [`scenarios.py`](../layer4_core/scenarios.py) | 410 | the four scripted PS scenarios |
| [`history.py`](../layer4_core/history.py) | 362 | flight history that survives a restart, and ECTM trend |
| [`operator_view.py`](../layer4_core/operator_view.py) | 303 | what the operator sees, as distinct from what the model computed |
| [`replay.py`](../layer4_core/replay.py) | 279 | replay over the synthetic fleet: scrubber, markers, recomputed residuals |
| [`sortie_replay.py`](../layer4_core/sortie_replay.py) | — | replay of the flights flown on **this** ground station |
| [`shadow_model.py`](../layer4_core/shadow_model.py) | — | the as-new twin |
| [`fleet.py`](../layer4_core/fleet.py) | 258 | fleet roster sorted by RUL ascending |
| [`terrain.py`](../layer4_core/terrain.py) | 245 | terrain under a route, and whether the engine can make the altitude it demands |
| [`sensor_bias.py`](../layer4_core/sensor_bias.py) | — | how far each instrument reads from the twin, and whether it can be blamed |
| [`sensor_response.py`](../layer4_core/sensor_response.py) | — | does each sensor still follow the engine? |

### 7.1 The twin state

`twin_state.py` is the record that joins the physics model and the live
telemetry. Four state categories (PRD Part 1 §6.2 defines three; physics
contributes the fourth):

| Category | Meaning |
|---|---|
| `reported` | what the engine's sensors actually said, after validation |
| `desired` | what the operator or mission plan asked for |
| `simulated` | what the physics model says the engine *should* be doing |
| `predicted` | what the AI layer expects (health, RUL, fault probabilities, degradation) |

Plus `residuals`, `advisory`, `alerts`, `history`, `metadata`. Full schema in
[§11](#11-the-twin-state-schema).

### 7.2 The live pipeline

`live.py` is where nothing is mocked. The CAN frames are really encoded and
really decoded; the twin really compares measurement against an as-new
reference; the alerts really come from the rule engine that a healthy engine
leaves silent.

It also owns the detectors that need the twin as a reference rather than a
model: `sensor_bias`, `sensor_response`, `egt_scatter_c`, the actuator-authority
checks, and the engine-failure detection.

### 7.3 Operator view — the smoothing layer

`operator_view.py` exists because of a measurement. Over twenty seconds on a
**healthy** engine with no fault injected:

| Quantity | Swing |
|---|---|
| BSFC deterioration | −4.52 % … +6.88 % (11.40 points) |
| Mission success probability | 56.79 % … 86.52 % (29.73 points) |
| Remaining useful life | 29.46 h … 30.40 h, changed in 35 of 40 frames |
| Composite health index | 0.78 … 0.89 |

Nothing was wrong with the engine. Every one of those was noise, and every one
was printed in the largest type on the dashboard. This module governs what
reaches the operator, under the rules in
[`docs/WHO_READS_THIS_SCREEN.md`](WHO_READS_THIS_SCREEN.md).

### 7.4 Recording, replay and the report

| Concern | Module | Note |
|---|---|---|
| record a real sortie | `recorder.py` | one Parquet file per aircraft per session, written in parts while it runs, deliberately in the **training-fleet schema** so `replay.py` reads it unchanged |
| replay the synthetic fleet | `replay.py` | scrubber, event markers, recomputed residuals, annotations — for checking detection lead times |
| replay this station's flights | `sortie_replay.py` | the channels an operator and engineer look at, thinned for the browser, with events derived from the data |
| what a report is made of | `flight_record.py` | events carry a **time and a flight phase**, as an Airbus PFR does: "EGT high, 04:12, CLIMB, ATA 77" is usable on the ramp; "EGT high" is not |
| the filed document | `report_pdf.py` | 15 sections, one page each, assembled from ADS-79E-HDBK (US Army CBM, the only one of these that covers unmanned aircraft), supplying regime recognition and exceedance processing |

### 7.5 Mission planning and assessment

| Module | Question it answers |
|---|---|
| `mission.py` | can this engine fly the mission in front of it? Remaining life in **missions**, not hours; Go / No-Go per profile with reasons and alternatives |
| `route_cost.py` | what does this route cost the engine, leg by leg? Not a fuel calculator: it reports that the third leg puts the wastegate hard against its stop for forty minutes, or that the same sortie at 18,000 ft in 42 °C consumes 1.4× the engine life it would at 10,000 ft in ISA |
| `flight_sim.py` | *where* does it go wrong? Flies the route minute by minute and keeps the track: position, altitude, phase, every temperature and pressure, and the ground underneath |
| `terrain.py` | does the aircraft clear the ground — and **can the engine make the altitude the terrain demands**, on the day in question? |
| `scenarios.py` | the four PS scenarios: high altitude, endurance, hot weather, rapid throttle transitions |

### 7.6 Deployment contexts

The problem statement names three. All three exist:

| Context | Module | The question it asks |
|---|---|---|
| defence-grade GCS | `layer5_viz/` + `twin_api` | how is *this* engine, right now |
| engine test rig | `test_rig.py` | does the engine that just came off the bench meet the numbers on its type certificate |
| fleet-level health monitoring | `fleet.py`, `fleet_server/` | which engine do I work on first, and how many aircraft can I put in the air on Thursday |

`fleet.py` sorts the roster by **RUL ascending**, because a maintenance planner
reads top-down and stops when the day is full.

---

## 8. Layer 5 — Operator console

`layer5_viz/gcs_console/` · 12,377 lines of TypeScript / TSX in 39 files

Built with Vite to `dist/`, which is git-ignored and served by the API from the
same origin. A fresh clone has no `dist/`, so the root URL returns a JSON hint
until `python run.py` (or `npm run build`) builds it.

### 8.1 Structure

| Path | Contents |
|---|---|
| `src/App.tsx` (560) | shell, routing, role-gated navigation, link state |
| `src/lib/api.ts` (672) | typed client for every endpoint; WebSocket connection and partial-frame merge |
| `src/components/Core.tsx` (923) | the engine workspace: readouts, traces, residual panel |
| `src/components/TerrainMap.tsx` (1,060) | terrain and route rendering |
| `src/components/RouteMap.tsx` (761) | mission route planning |
| `src/components/EngineModel.tsx` (567) | the 3D engine, with fault-layer highlighting |
| `src/components/TwinCompare.tsx` | live engine against its as-new twin, per parameter |
| `src/components/Checklist.tsx`, `Sortie.tsx`, `Widgets.tsx` | electronic checklists, sortie strip, gauges |
| `src/pages/home/` | the four role home workspaces: `Operations.tsx`, `Mission.tsx`, `Fleet.tsx`, `Review.tsx` |
| `src/pages/detail/` | `Health.tsx`, `Prognostics.tsx`, `Simulation.tsx` |
| `src/pages/` | `Overview.tsx`, `Pages.tsx`, `Replay.tsx`, `Scenarios.tsx`, `Maintenance.tsx`, `TestRig.tsx`, `Engines.tsx`, `Users.tsx`, `Audit.tsx`, `Fleet.tsx`, `Login.tsx` |
| `src/theme/tokens.css`, `ui.css` | the design tokens and component styles the HMI standard fixes |
| `src/lib/audio.ts` | master warning and caution tones (411F 5.3.1: 700→1700 Hz sweep over 0.85 s) |
| `src/lib/faultLayer.js` | maps a detected fault onto 3D engine components |

### 8.2 The display contract

Governed by [`docs/PRD_Part4_Defence_HMI_Standard.md`](PRD_Part4_Defence_HMI_Standard.md),
which is normative, and verified by two scripts:

- `scripts/hmi_check.py` — the automatable parts of the Part 4 §15 checklist
  (runs in CI, exits non-zero on a finding)
- `scripts/hmi_runtime_check.py` — the half that needs a **running** console

Refresh-rate contract (Part 4 §8.3): Zone B readings at the telemetry rate,
trend charts at 4 Hz, derived indices at 1 Hz. This is why the WebSocket is
tiered.

**The footer strip** is the "can I believe this screen" indicator (Part 4 §7):
source, rate, channel count, frames decoded and lost, measured latency, and
whether the shadow model is locked.

**`———` is correct behaviour, not a rendering bug.** A channel that fails
validation has its value removed; if every readout shows it, the pipeline is not
producing — check `/api/healthz`.

### 8.3 What each page answers

| Page | Question |
|---|---|
| ENGINE | what the sensors say, and how far it is from an as-new engine at the same operating point |
| HEALTH | composite index, four subsystems, nine sub-indices, degradation factors, onset detection |
| PROGNOSTICS | remaining life with its interval, three-tier detection breakdown, maintenance advisory |
| MISSION | Go / No-Go per mission profile, with reasons and alternatives |
| SIMULATION | fault injection, environmental state |
| REPORT | mission-wise health report |
| REPLAY | a recorded sortie, scrubbable, with events |
| FLEET | the squadron, each aircraft's technical log |
| ENGINES | author and check an engine definition |
| AUDIT | the hash-chained audit log |
| ECTM (`/api/history/ectm`) | drift against the baseline flight, across flights, weather excluded |

---

## 9. Central fleet server

`fleet_server/` · 499 lines · FastAPI + PostgreSQL (`asyncpg`)

The tier above the ground stations. Without it, each station holds its own
SQLite file and its own users, two stations share nothing, and there is no
fleet.

**The division of authority is the whole design**: a ground station in the field
may have no route to the central server for days and must keep working
completely, so the **local SQLite store stays authoritative for the station**
and `layer4_core/fleet_sync.py` is a one-way, store-and-forward uploader that
never loses a record.

The PS asks for "cloud **or** local server-based analytics". The `or` is read as
on-premise, because `docs/INDIGENISATION.md` claims no foreign vendor in the
critical path and a cloud tenancy would be exactly that.

| Route | Purpose |
|---|---|
| `GET /api/v1/directory` | the signed station and user directory |
| `POST /api/v1/directory` | publish a directory update |
| `POST /api/v1/ingest` | a station forwards its records |
| `GET /api/v1/fleet` | the cross-station fleet picture |
| `GET /api/v1/stations` | registered ground stations |
| `GET /healthz` | liveness |

Run with `python -m fleet_server.app`; compose file
[`docker-compose.fleet.yml`](../docker-compose.fleet.yml). Registration:
`python scripts/register_station.py`.

---

## 10. Shared modules

`common/` · 722 lines

| Module | Responsibility |
|---|---|
| [`config.py`](../common/config.py) | the **only** sanctioned way to read `configs/*.yaml`. Decision D6: nothing in the repository may hard-code a limit, a weight or an engine dimension. Handles `extends:` inheritance between engine definitions and `thresholds_override:` per engine |
| [`fadec.py`](../common/fadec.py) | which FADEC lanes each bus-carried sensor is fitted to, from the manufacturer's failure matrix; only the sensor→channel name mapping is defined locally |
| [`logging.py`](../common/logging.py) | structured JSON-lines logging. There was none, so when the pipeline once froze the only evidence anywhere was a string in a snapshot field nothing read. `structlog` and `loguru` are both good and neither is used: the indigenisation claim is cheapest to hold when the answer is the standard library |

---

## 11. The twin state schema

Defined in [`layer4_core/twin_state.py`](../layer4_core/twin_state.py) with
Pydantic v2 models on a `Strict` base (extra fields forbidden). `SCHEMA_VERSION`
is carried in every snapshot.

### 11.1 The measurement wrapper

Every telemetry value is a `Measurement`, never a bare float:

```python
class Measurement(Strict):
    value:  float | None = None     # None when removed — never substituted
    state:  str = "MISSING"         # VALID | STALE | INVALID | MISSING | SUSPECT
    age_s:  float | None = None
    reason: str = ""                # why it is not VALID
```

`PerCylinder` carries the four-cylinder channels plus their `spread`.

### 11.2 Top-level structure

```
TwinState
├── schema_version
├── metadata      TwinMetadata      identity and life
├── reported      ReportedState     what the sensors said, validated
├── desired       DesiredState      what was asked for
├── simulated     SimulatedState    what the physics says it should be doing
├── predicted     PredictedState    what the AI expects
├── residuals     ResidualSet       measured − as-new
├── advisory      MaintenanceAdvisory
├── alerts        AlertSummary
├── history       OperationalHistory
├── sync_count, last_sync_utc
```

| Model | Notable fields |
|---|---|
| `TwinMetadata` | `twin_id`, `aircraft_id`, `engine_type`, `engine_key`, `serial_number`, `total_flight_hours`, `total_cycles`, `lifecycle` (`CREATED`/`ACTIVE`/`MAINTENANCE`/`DECOMMISSIONED`), `tbo_hours` (1200), `tbo_calendar_years` (15), `hours_at_last_overhaul` |
| `ReportedState` | `rpm`, `propeller_rpm`, `cht` (PerCylinder), `cht_max`, `coolant_temperature`, `egt`, `egt_max`, `oil_pressure`, `oil_temperature`, `fuel_flow`, `fuel_pressure`, `manifold_pressure`, `manifold_air_temperature`, `throttle_pct`, `wastegate_pct`, `cooling_flap_pct`, `oil_flap_pct`, `air_flow_g_per_min`, plus `vibration`, `electrical`, `timing`, `environmental`, and the channel census (`channels_total/usable/stale/invalid`) |
| `Vibration` | `rms_x/y/z`, `rms_total`, `kurtosis`, `dominant_frequency_hz`, `spectral_peaks` |
| `Electrical` | `bus_voltage`, `alternator_current`, `alternator_voltage`, `battery_soh` |
| `TimingState` | `injection_measured`, `ignition_measured` (per cylinder), the commanded values, `injection_period_ms`, `injector_duty_pct`, `knock_retard_deg`, and the max deviations |
| `Environmental` | `oat_c`, `altitude_ft`, `airspeed_kmh`, `ambient_pressure_hpa`, `humidity_pct`, `flight_phase` |
| `SimulatedState` | the as-new predictions (`cht_predicted`, `egt_predicted`, `power_predicted_kw`, `bsfc_predicted`, …), `model_residual`, `physics_constraint_violations`, `model_available`, `outside_manufacturer_data` |
| `Residual` | `measured`, `predicted`, `delta`, `mean_delta`, `samples`, `usable` — a residual states whether it is usable rather than being silently trusted |
| `HealthIndices` | `composite`, `thermal`, `mechanical`, `electrical`, `combustion`, `band` |
| `RemainingLife` | `hours`, `cycles`, `lower_hours`, `upper_hours`, `confidence` (0.95), `limited_by`, `source` (an enum, so the console can say *which* estimator spoke) |
| `DegradationEstimate` | `cooling_efficiency`, `oil_quality`, `combustion_efficiency`, `injector_condition`, `bearing_condition`, `turbocharger_condition` — one per pathway, so wear is attributed to a **named subsystem** |
| `MaintenanceAdvisory` | `severity`, `message`, `recommended_action`, `time_to_action`, `shap_explanation`, `fault_codes`, `source` (`none`/`rules`/`model`/`fused`) |
| `ActiveAlert` | `rule_id`, `legend`, `level`, `category`, `parameter`, `value`, `limit`, `advisory`, `fault_mode`, `first_seen_s`, `acknowledged` |
| `AlertSummary` | `active`, `overflow_count`, `master_warning`, `master_caution`, `inhibits_active` |
| `OperationalHistory` | `mission_count`, `thermal_cycles`, the `max_*_recorded` extremes, `hours_since_inspection`, `time_above_max_continuous_s` |
| `PredictedState` | the above plus `fault_probability` (per mode), `fault_probability_source`, `rule_fault_levels`, `rule_based_fallback`, `model_confidence` |

`TwinSynchroniser` is the step that keeps this record current from validated
telemetry plus the shadow model's prediction.

### 11.3 Persistence

| What | Where |
|---|---|
| each engine's life across restarts | `data/twin_state/<twin_id>.pkl` |
| flight history and ECTM trend | `data/history/` |
| squadron log, missions, defects | `data/ops/` |
| recorded sorties | `data/recordings/` (Parquet, training-fleet schema) |
| 72 h edge buffer | SQLite WAL |
| users and audit log | SQLite, `data/keys/` for signing material |

`DT_PERSIST=0` starts every aircraft and the squadron log fresh, for a clean
demonstration.

---

## 12. The feature contract and model inventory

### 12.1 Trained artefacts

Models are stored with Git LFS and mirrored in the `astra-models.zip` release
asset. `run.py` checks for LFS pointer files (130 bytes where a model should be)
and names every missing file, because a clone on a machine without Git LFS
*succeeds* and says nothing is wrong.

| Artefact | What it is |
|---|---|
| `data/models/tier3.pt` | multi-task network: anomaly / fault class / severity |
| `data/models/tier3_edge.onnx`, `tier3_edge_int8.onnx` | the exported edge graphs (149.6 KB; int8 2.94× smaller) |
| `data/models/rul_lstm.pt` | data-driven RUL |
| `data/models/survival_head.pkl` | calibrated CatBoost survival head |
| `data/physics/flame_*.json` | precomputed adiabatic-flame lookups, one per engine (decision D7) — **tracked, not generated**; the physics needs one on every tick |
| `data/models/*_report.json` | the measurement behind every quoted figure |

Report artefacts worth knowing by name:

| File | Contains |
|---|---|
| `fusion_report.json` | every combiner's curve, the chosen operating point, precision / ROC-AUC / FPR |
| `tier2_report.json` | per-condition limits, false alarms per engine-hour |
| `tier3_report.json`, `tier3_edge_report.json` | detection and classification, and the export comparison |
| `fault_namer_report.json` | per-class F1 across the eight fault modes |
| `edge_footprint.json` | ONNX size, inference latency, resident memory, memory growth |
| `latency_bench.json`, `latency_bench_1core.json` | tick latency under load, multi-core and pinned |
| `ood_report.json` | OOD flag rates on healthy and faulted held-out rows |
| `pinn_report.json` | hybrid versus data-only loss, and constraint violations |
| `physics_om_validation.json` | the model against the manufacturer's table, row by row |
| `rul_interval_comparison.json`, `rul_ceiling*.json`, `survival*.json` | the RUL information-ceiling work |

### 12.2 Training and evaluation protocol

Every reported figure obeys the same rules:

1. **Split by engine**, never by row. 200 engines; 40 held out.
2. **Thresholds fixed on training and validation data** and never moved to suit
   the test set.
3. **Combiner chosen on validation**, with a published tie-break.
4. **Multi-seed where a single run is not a result** —
   `scripts/rul_multiseed.py`. Per-class F1 moves ±0.10 between runs with
   nothing changed but the seed, because each class is carried by 5–12 of the 40
   test engines. Quote the aggregate.
5. **The inflation from a wrong protocol is measured**, not assumed —
   `scripts/eval_split_inflation.py` scores the same model on random rows versus
   unseen engines.

Retraining, end to end: `python scripts/retrain_all.py`. Individual stages are
in [§21](#21-scripts-reference).

---

## 13. Configuration reference

### 13.1 Files

| File | Lines | Contents |
|---|---|---|
| `configs/thresholds.yaml` | 1,366 | every limit, weight, detector parameter and policy in the system |
| `configs/engines/rotax_915is.yaml` | 603 | the reference engine, fully provenance-tagged |
| `configs/engines/austro_ae330.yaml` | 249 | turbo-diesel **placeholder**, ~70 lines of its own on top of the Rotax; labelled unvalidated everywhere |
| `configs/engines/_template.yaml` | 63 | starting point for a new engine; `extends: rotax_915is` |
| `configs/engines/rotax_915is_om_performance.csv` | — | the manufacturer's 941-point table, beside the model it validates |
| `configs/fleet.yaml` | 97 | the squadron: aircraft, mission types, environments, pre-flight checklist, ops timing |
| `configs/checklists.yaml` | 263 | electronic checklists |
| `configs/airframes/male_uav_reference.yaml` | 147 | the airframe: drag, cooling-air supply, tank capacity |
| `configs/can/engine.dbc` | 20 KB | CANaerospace database, **generated** by `scripts/gen_can_dbc.py` |

### 13.2 `thresholds.yaml` top-level sections

| Section | Contents |
|---|---|
| `parameters` | per-channel physical range, rate limit, resolution, units |
| `health` | sub-index formulas, subsystem grouping, composite weights, bands |
| `alert_levels` | the five MIL-STD-411F levels ([§4.4](#44-the-rule-engine)) |
| `alerting` | display minimums, flash rate, stack depth, legend length, inhibits |
| `faults` | detection parameters for each of the eight fault modes |
| `detectors` | Tier-2 ensemble parameters and per-condition limits |
| `feature_norm` | the fixed centres and scales of the feature contract |
| `rul` | horizon cap, thresholds, interval policy |
| `pipeline` | rates, budgets, validation tuning ([§13.3](#133-pipeline-tuning-worth-knowing)) |
| `mavlink` | EFI_STATUS bridge; `enabled: false` by default — nothing should be sent to a port nobody is listening on |
| `fusion` | combiner definitions and the chosen operating point |
| `twin_compare` | which parameters the console compares against the twin, and their bands |
| `advisory` | maintenance actions, costs, downtime, urgency |
| `security` | JWT policy, roles → scopes, audit event list, rate limit |
| `report` | the deployment identity on the report cover: location, operator, classification |
| `exceedance_grades` | exceedance severity grading for the post-flight report |

### 13.3 Pipeline tuning worth knowing

| Key | Value | Meaning |
|---|---|---|
| `telemetry_hz` | 10 | bus rate |
| `edge_critical_path_ms` | 50 | rules only, onboard, bypassing physics and AI |
| `target_median_ms` / `target_p95_ms` | 100 / 200 | full pipeline budget |
| `dashboard_refresh_s` | 2.0 | full snapshot, chart series included |
| `dashboard_live_refresh_s` | 0.25 | readings only, 4 Hz |
| `stale_after_intervals` | 3 | staleness threshold |
| `lane_agreement_fraction` | 0.05 | FADEC inter-lane tolerance, with per-channel **floors** — a fraction of a temperature in °C means nothing: at 20 °C 5 % is 1 °C and at 0 °C it is nothing at all |
| `frozen_false_alarm_probability` | 1e-9 | run length above which identical readings are improbable |
| `response_window_s` / `_excitation_x` / `_flat_x` / `_agree_x` / `_persist_s` | 60 / 5.0 / 2.0 / 3.0 / 15 | the "sensor stopped following the engine" check |
| `link_degraded_after_s` / `link_lost_after_s` | 2.0 / 5.0 | link state |
| `edge_buffer_hours` | 72 | offline buffer depth |

All `[MOD]` values in this block are simulated-instrument derived, and the
configuration says so: **on hardware the floors and noise ratios must be
re-derived from sensor datasheets or bench data.**

### 13.4 Environment variables

| Variable | Effect |
|---|---|
| `DT_DATA_DIR` | where datasets, models and state live (default `data/`) |
| `DT_CONFIG_DIR` | alternative config root |
| `DT_HOST`, `DT_PORT` | API bind address (default `127.0.0.1:8000`) |
| `DT_ALLOW_INSECURE_BIND` | permit a non-loopback bind without TLS |
| `DT_TLS_CERT`, `DT_TLS_KEY` | serve HTTPS |
| `DT_ENGINE`, `DT_ENGINE_SEED` | which engine definition runs, and its manufacturing seed |
| `DT_SPEED` | simulated seconds per wall second |
| `DT_CRUISE_HOURS` | compressed cruise for a tasked mission (default 0.1 h) |
| `DT_PERSIST=0` | start every aircraft and the squadron log fresh |
| `DT_LOG_LEVEL` | structured-log verbosity |
| `DT_ALLOW_INITIAL_PASSWORDS` | permit the seeded first-run passwords (demo only) |
| `DT_STATION_ID`, `DT_STATION_KEY` | this ground station's identity to the fleet server |
| `DT_FLEET_URL`, `DT_FLEET_DSN`, `DT_FLEET_HOST`, `DT_FLEET_PORT` | fleet-server location and database |
| `DT_FLEET_ADMIN_KEY`, `DT_FLEET_DIRECTORY_KEY`, `DT_FLEET_DB_PASSWORD` | fleet-server secrets |
| `DT_FLEET_ALLOW_HTTP`, `DT_FLEET_ALLOW_UNSIGNED_DIRECTORY` | development escape hatches |
| `DT_MQTT_USERNAME`, `DT_MQTT_PASSWORD`, `DT_MQTT_TLS_CA/CERT/KEY` | downlink broker credentials |
| `DT_MAP_TILES` | map tile source for the planner |
| `DT_VENV`, `DT_RUN_REEXEC` | used internally by `run.py` |

### 13.5 The engine definition

An engine is **one YAML file and no code change**. Top-level sections of
`rotax_915is.yaml`:

`identity` · `geometry` · `ratings` · `fuel_properties` · `ignition_system` ·
`thermodynamics` · `intake` · `turbocharger` · `thermal` · `exhaust` ·
`oil_system` · `performance_table` · `propeller` · `vibration` · `electrical` ·
`sensors` · `degradation` · `limits` · `can` · `failure_matrix` · `environmental`

`_template.yaml` starts with `extends: rotax_915is`, so a new engine writes only
what differs; limits that differ go under `thresholds_override:`.
`identity.ignition` (`SPARK` | `COMPRESSION`) selects the combustion model, and
`identity.validated` marks whether the definition is real or a placeholder.

---

## 14. HTTP and WebSocket API

Served by [`layer4_core/twin_api.py`](../layer4_core/twin_api.py). 74 HTTP
routes and one WebSocket. Everything served comes from the running pipeline:
there is no mock data path and no seeded demo file.

`python -m layer4_core.twin_api`, then http://127.0.0.1:8000

### 14.1 Authentication

| Route | Purpose |
|---|---|
| `POST /api/auth/login` | username + password → access and refresh tokens |
| `POST /api/auth/change_password` | required at first login |
| `POST /api/auth/refresh` | exchange a refresh token |
| `GET /api/auth/me` | the caller's subject, role and scopes |

RS256, 15-minute access tokens, 24-hour refresh, issuer `dt-uav-gcs`.

### 14.2 Live state and telemetry

| Route | Scope |
|---|---|
| `GET /api/state` | `read:telemetry` — the full twin snapshot |
| `GET /api/engine` | `read:telemetry` — the engine workspace payload |
| `GET /api/healthz` | open — `{ok, ticks, ...}`; readiness means **advancing ticks**, not an open port |
| `WS /ws/state?token=…` | `read:telemetry` — tiered snapshot stream |

The WebSocket takes its token as a **query parameter** because a browser cannot
set an `Authorization` header on a handshake. It is the same check with a
different carrier, and the token is **re-verified every ~5 s**, not only at
connect: checked once, a revoked or disabled credential would keep receiving the
full telemetry picture for as long as the socket stayed open. An unauthenticated
peer is closed **before** accept (code 4401) so it never sees a frame; an
unauthorised one gets 4403 and an `AUTHZ_DENY` audit entry.

### 14.3 Faults, failures and simulation

| Route | Purpose |
|---|---|
| `GET /api/faults` · `POST /api/faults/inject` · `POST /api/faults/clear` | the eight injectable fault modes |
| `GET /api/faults/failures` · `POST /api/faults/failure` | sudden failures (raises `ENGINE FAILURE`) |
| `GET /api/faults/sensors` · `POST /api/faults/sensor` | sensor faults: drift, freeze, detach |
| `POST /api/faults/lane` | fail a FADEC lane |
| `GET /api/faults/forecast` | per-fault time-to-action |
| `GET /api/scenarios` · `POST /api/scenarios/{key}` · `POST /api/scenarios/custom` | the four PS scenarios and a custom one |

### 14.4 Analysis and reporting

| Route | Purpose |
|---|---|
| `GET /api/report` · `.pdf` · `.csv` · `.json` | the post-flight report in four forms |
| `GET /api/explain` | attribution for the current verdict |
| `GET /api/maintenance` · `/catalog` · `POST /api/maintenance/performed` | the costed advisory and the action catalogue (A1–A7) |
| `GET /api/history/ectm` | engine condition trend monitoring across flights |
| `GET /api/replay/flights` · `/{sid}` · `/sessions` · `/{engine_id}` | replay of this station's sorties and of the synthetic fleet |
| `GET /api/audit` | the hash-chained audit log |
| `GET /api/fleet` · `/sync` | fleet roster and sync state |

### 14.5 Mission and route

| Route | Purpose |
|---|---|
| `GET /api/mission` | Go / No-Go for the current profile |
| `POST /api/mission/route` | leg-by-leg engine cost of a proposed route |
| `GET /api/mission/envelope` | the achievable envelope on the day |
| `POST /api/mission/flight` | fly the planned route minute by minute |

### 14.6 Squadron operations

Full state machines in [§16](#16-squadron-operations-model).

| Route | Scope |
|---|---|
| `GET /api/ops/board` · `/aircraft/{tail}` | `read:ops` |
| `POST /api/ops/missions` · `GET …/candidates` · `POST …/approve` · `…/cancel` | `plan:mission` |
| `POST …/prepare` · `/handback` · `/start` · `/launch` · `/rtb` · `/abort` · `/debrief` | `fly:mission` |
| `POST /api/ops/aircraft/{tail}/release` · `/maintenance` · `/ground_run`, `POST /api/ops/defects/{id}/rectify` | `write:maintenance` |
| `POST /api/ops/defects/{id}/disposition`, `POST /api/ops/aircraft/{tail}/limitations` | `review:defects` |
| `POST /api/ops/aircraft/{tail}/defects` · `/ground` | `raise:defect` |
| `POST /api/ops/aircraft/{tail}/connect` | `read:ops` |
| `POST /api/ops/aircraft/{tail}/engine` | `admin:fleet` — an engine change |

### 14.7 Administration

| Route | Scope |
|---|---|
| `GET /api/engines` · `/template` · `/{key}/yaml` · `POST /api/engines` | `write:engines` |
| `GET /api/users` · `POST /api/users` · `POST /api/users/{username}` | `admin:users` |
| `GET /api/testrig/schedules` · `POST /api/testrig/run` | test-cell mode |
| `GET /api/checklists` | electronic checklists |
| `POST /api/alerts/acknowledge` | `ack:alert` |
| `POST /api/sortie/start` | `control:sortie` |

---

## 15. Security model

[`layer4_core/security.py`](../layer4_core/security.py) · 1,060 lines ·
[`test_security.py`](../layer4_core/tests/test_security.py),
[`test_stream_scopes.py`](../layer4_core/tests/test_stream_scopes.py)

### 15.1 The rule that matters most

> Authorisation **shall** be enforced server-side regardless of UI state; the UI
> is a convenience, never the security boundary. *(PRD Part 4 §10c)*

The console's habit of hiding controls a role cannot use is a courtesy. Every
route checks the scope itself.

### 15.2 Threats and answers

PRD Part 3 §20.1 lists five:

| Threat | Answer |
|---|---|
| 1 · interception | TLS configuration in `twin_api` (`DT_TLS_CERT` / `DT_TLS_KEY`) |
| 2 · unauthorised access | JWT RS256 + RBAC, server-side |
| 3 · tampering | HMAC frame authentication, `layer1_edge/secure_link.py` — survives a terminated TLS session, a replayed capture, or a compromised relay |
| 4 · denial of service | `RateLimiter` on every authenticated route, 600 req/min |
| 5 · insider misuse | SHA-256 hash-chained audit log |

### 15.3 Roles and scopes

Four roles — the problem statement's three audiences ("UAV operators, propulsion
engineers and maintenance team") plus the commander. Each role is scoped to the
**decision it actually makes**, which is a stricter test than "what might be
interesting to it". Defined in `configs/thresholds.yaml → security.roles`.

| Role | Account | Scopes |
|---|---|---|
| `ROLE_OPERATOR` | `op.rao` | `read:telemetry`, `read:health`, `read:alerts`, `ack:alert`, `read:replay`, `read:mission`, `control:sortie`, `read:ops`, `fly:mission`, `raise:defect` |
| `ROLE_ENGINEER` | `eng.menon` | the above minus `control:sortie`/`fly:mission`, plus `read:physics`, `read:prognostics`, `read:advisory`, `read:reports`, `run:simulation`, `write:sim_params`, `write:engines`, `review:defects` |
| `ROLE_MAINTENANCE` | `mt.iyer` | reading scopes plus `read:prognostics`, `read:advisory`, `read:reports`, `write:maintenance` |
| `ROLE_COMMANDER` | `cdr.sharma` | `*` — and the commander alone holds `admin:users`, `plan:mission` and `admin:fleet` through it |

`*` is checked **explicitly**, not by string matching, so a role that happens to
hold a scope named `*something` gains nothing.

The scope assignments carry their reasoning in the config, because several were
wrong at first in instructive ways: `read:mission` (the Go/No-Go call) belongs to
the **operator**, because continuing or aborting the sortie is the operator's
decision, and withholding it left the person flying the aircraft unable to see
the reliability assessment made for their flight. `read:advisory` was split
between two roles such that neither could use it.

### 15.4 Token handling

- RS256, signed with a key in `data/keys/`.
- The **role in the token must still be the role in the store** (SEC-06):
  otherwise a role change took effect only when the token expired, and anyone
  holding the signing key chose their own role.
- `token_epoch` per user invalidates outstanding tokens on password change or
  disable.
- WebSocket tokens are re-verified every ~5 s while the socket is open.

### 15.5 First-run accounts

The first run creates one account per role with **random** passwords, written to
`data/keys/FIRST_RUN_CREDENTIALS.txt` on the local machine only and never
committed. Each account **must change its password at first login**.

### 15.6 The audit log

SHA-256 **hash-chained**, so an entry cannot be altered or removed without
breaking the chain. Recorded event types:

`AUTH` · `AUTHZ_DENY` · `STATE_MUTATION` · `ALERT_GENERATED` · `ALERT_ACK` ·
`MODEL_UPDATE` · `MAINTENANCE_ACTION` · `THRESHOLD_CHANGE` · `REPORT_EXPORT` ·
`ENGINE_CONFIG` · `ENGINE_CHANGE` · `USER_ADMIN` · `MISSION` · `SORTIE_START`

`REPORT_EXPORT` records a digest, which is what lets a printout be matched back
to its entry.

### 15.7 Standards scope, stated precisely

The alignment claimed is with **STANAG 4586's** separation of the Core UCS from
the Human Computer Interface, scoped explicitly to **LOI 1–2** — receipt and
display of telemetry and derived products. **This console issues no vehicle or
payload commands (LOI 3–5).** The qualification is repeated in the module itself
so a reader of `security.py` alone does not read a wire-protocol claim into an
architectural one.

---

## 16. Squadron operations model

[`layer4_core/ops.py`](../layer4_core/ops.py) · detail in
[`docs/SQUADRON_OPERATIONS.md`](SQUADRON_OPERATIONS.md)

The twin says what condition the engine is in. This is how a squadron **acts**
on that answer: tasking, allotment, airworthiness release, pre-flight, engine
start, launch, recovery, debrief, defect, engineering disposition,
rectification — each decision owned by one role and every one written to the
aircraft's technical log.

### 16.1 The squadron

`configs/fleet.yaml`. Each aircraft has a **tail** (airframe), a **twin_id**
(the engine's serial — its twin's identity), an **engine_key**, and the hours it
arrives with.

| Tail | Twin | Engine | Hours | Note |
|---|---|---|---|---|
| MALE-01 | UAV-ENG-001 | rotax_915is | 0 | the station's original aircraft |
| MALE-02 | UAV-ENG-002 | rotax_915is | 420 | |
| MALE-03 | UAV-ENG-003 | rotax_915is | 960 | registered with a **cooling fault beginning to develop, and nobody is told** — the twin has to find it |
| TAPAS-01 | UAV-ENG-101 | austro_ae330 | 150 | the turbo-diesel; unvalidated engine model, labelled as such |

Six mission types (ISR patrol 10 h @ 18,000 ft, comm relay 18 h @ 20,000 ft,
maritime 12 h, high-altitude ISR 12 h @ 23,000 ft, transit 4 h, training 2 h)
across six environments (standard, hot weather, cold weather, high altitude,
maritime, endurance).

**Signing in does not start an engine.** It starts because an operator started
it for an approved mission, or a maintainer ran it on the ground, and it starts
from cold at 0 rpm.

### 16.2 Aircraft status — derived, never stored

| Status | When |
|---|---|
| FLYING / ENGINE RUNNING / GROUND RUN / ON GCS | the station is working this aircraft |
| UNSERVICEABLE | any grounding reason |
| AWAITING INSPECTION | no maintenance release signed since the last engine run or work |
| SERVICEABLE | released, nothing grounds it |

**Grounding reasons**: an open or confirmed grounding defect; a deferred defect
past its hours limit; the 100 h inspection due (`inspection_interval_h`); TBO
reached. A release is **withdrawn automatically** after every engine run
(after-flight inspection due), after any work, when a grounding defect is
raised, and on an engine change.

### 16.3 Mission states

```
PLANNED ─approve(tail, operator)─▶ APPROVED ─prepare─▶ PREFLIGHT ─start(checklist)─▶ ENGINE_RUNNING
   │                                  │  ▲ handback        │                          │    │
   └─cancel─▶ CANCELLED ◀─cancel──────┘  └──────────────────┘                     launch  abort
                                                                                      ▼    ▼
                          COMPLETED / ABORTED ◀─debrief─ AWAITING_DEBRIEF ◀─shutdown─ AIRBORNE ─rtb─▶ RTB
                                                                               ▲─────────── ABORTING
```

| Transition | Conditions |
|---|---|
| **approve** (commander) | the aircraft must be SERVICEABLE, not allotted to another open mission, inside its operating limitations, and **not NO-GO** in the twin's assessment for *this* mission's endurance and altitude — the same `MissionReliability` the live twin uses, fed with the aircraft's last measured condition. Candidates are ranked GO, GO WITH LIMITS, NOT ASSESSED, then by predicted success |
| **prepare** (the allotted operator) | the aircraft is loaded onto the station, engine off. Only one mission or ground run occupies the station |
| **start** | every `preflight_checklist` item confirmed; the engine starts from cold and holds at the warm-up setting. Not cleared to launch within 30 min of engine time → shut down |
| **launch** | refused unless: holding at warm-up, oil at the take-off minimum (50 °C), running steadily, **no warning active**, twin verdict not NO-GO. Active *cautions* are shown to be weighed, not blocking |
| **rtb** | from take-off, climb or cruise; the aircraft descends from where it is |
| **abort** | before launch: cool down and shut down |
| **shutdown** | the mission waits for debrief, the release is withdrawn, and the twin's advisories of CAUTION and above are written to the technical log as **TWIN defects**. WARNING and EMERGENCY ground the aircraft. A repeat advisory does not duplicate an open defect |
| **debrief** (operator) | outcome, remarks, and snags — each snag becomes a defect |

### 16.4 Defects

| Source | Raised by |
|---|---|
| TWIN | the engine twin, at the end of **every** engine run |
| OPERATOR | a debrief snag, or reported from the technical log |
| MAINTENANCE / ENGINEER | found on inspection, or grounding the aircraft |

**Engineer's disposition**: `CONFIRM` (optionally grounding), `DEFER` with an
hours limit (the aircraft may fly; past the limit it is grounded again), or
`NFF` (no fault found, closed). Every disposition needs its reasoning.

**Maintainer's `RECTIFY`** closes a defect with the maintenance actions done
(A1–A7). The work reaches the aircraft's engine twin **immediately** if it is on
the ground station, otherwise at its next engine run, with its "before" reading
taken from the condition the squadron log kept.

### 16.5 Ground runs

Start → 3 min warm-up → 2 min run-up at 45 % (held where the twin can judge the
engine warm and loaded, inside every limit for a sound engine with no ram air)
→ 90 s cool-down → shutdown. This is how rectification is verified and how an
aircraft that has not flown gets a **measured** condition. A ground run ends
like a flight: the twin's findings are written as defects.

### 16.6 The chain, end to end

1. Maintainer ground-runs and inspects an aircraft and signs its release.
2. Commander plans a mission and allots it — with every aircraft ranked by the
   twin's predicted mission success for *that* mission, and the reason any may
   not be used.
3. Operator prepares, checks, starts, launches, flies, recalls or lands.
4. At shutdown the mission waits for debrief, the release is withdrawn, and the
   twin's CAUTION-and-above advisories become technical-log defects.
5. Engineer dispositions them; maintainer rectifies, ground-runs, releases.

Every step is in the aircraft's logbook and the audit log, and each role's page
opens with **what is waiting on them** (`OpsStore.tasks` — a person's own work
only).

---

## 17. Build, run and developer workflow

### 17.1 One command

```bash
python run.py
```

[`run.py`](../run.py) (~950 lines) is the entire quickstart. It:

1. checks the Python version;
2. creates `.venv` if there is none and re-executes itself inside it;
3. installs the pinned Python packages;
4. **fetches the Git LFS content**, detecting 130-byte pointer files and naming
   every missing model when it cannot;
5. builds the console if `dist/` is absent or older than its source;
6. proves each of the five layers once (the self-check);
7. serves at http://127.0.0.1:8000 and prints the logins.

Wrappers: `run.ps1` (Windows without Python on PATH), `run.sh` (POSIX).

### 17.2 Flags

| Flag | Effect |
|---|---|
| `--check` | run every check, then exit without serving |
| `--demo` | the ninety-second terminal demonstration instead of serving |
| `--tests` | also run the full test suite in the self-check |
| `--full` | also install the `ml`, `physics` and `dev` extras (torch is ~2 GB) |
| `--no-console` | skip the npm build |
| `--no-check` | serve immediately |
| `--no-browser` | do not open a browser |
| `--reinstall` | reinstall dependencies even when present |
| `--port N` | serve somewhere other than 8000 |
| `--list-engines` | list engine definitions, which one runs, whether each is complete, and the aircraft it is on |
| `--check-engine KEY` | name every key `configs/engines/KEY.yaml` is missing, then fly it for ten seconds |

`--check` is the one to run before a demonstration: about ten seconds, and it
exercises the CAN pipeline, the shadow model, the health index, the fusion, the
operator view, the display standard and the traceability audit, then injects a
cooling fault and shows the twin registering it **while every certified limit is
still satisfied**.

### 17.3 By hand

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows
source .venv/bin/activate         # Linux / macOS
pip install -e ".[security,reports]"
python -m layer4_core.twin_api
```

**The `security` extra is not optional.** `twin_api` imports
`layer4_core.security` at module scope, which imports `jwt`, `bcrypt` and
`cryptography` unguarded, so `pip install -e .` alone dies on
`ModuleNotFoundError` before `main()` runs. `reports` *is* guarded — the API
starts without it, and PDF export then fails instead of producing a report.

### 17.4 The demonstration

```bash
python scripts/demo.py
python scripts/demo.py --fault abnormal_vibration --severity 0.95
python scripts/demo.py --speed 300        # simulated seconds per wall second
```

Ninety seconds, terminal only. Watch about forty seconds in: the twin reports a
degrading engine while every certified limit is still satisfied.

**Inject faults at power, not while taxiing.** A severity-0.95 misfire at
5,764 rpm takes misfire probability from 0.001 to **1.000 in 25 seconds**; the
same injection at 2,060 rpm on 20 % throttle raises nothing, because a missed
firing at idle barely disturbs an engine that is not being asked for power. A
brand-new engine also needs its first stretch of **level flight** before the
learned models judge it; until then the rules alone decide, and the console says
so.

### 17.5 Retraining and regenerating

None of this is needed to run or demonstrate the system — only to reproduce the
reported numbers.

```bash
pip install -e ".[ml]"                                        # torch, onnx
python -m layer2_physics.synth_data_gen --engines 100 --workers 7
python scripts/eval_tier2.py          # statistical detection
python scripts/train_tier3.py         # deep detection + fault classification
python scripts/eval_fusion.py         # three-tier fusion
python scripts/eval_health.py         # health index vs ground truth
python scripts/train_rul.py           # remaining useful life
python scripts/train_survival.py      # the survival head
python scripts/retrain_all.py         # all of the above, end to end
```

### 17.6 Code style

`ruff` at line length 100, target py311, rule sets `E,F,I,UP,B,SIM,N`. Three
`N` rules are disabled on purpose: physics uses `l`, `I`, `O` as symbols and
`T`, `P`, `N_e` as argument and variable names. `mypy` runs with
`ignore_missing_imports` and `disallow_untyped_defs = false`. Both are
**advisory** in CI, and that is recorded rather than hidden — the tree has never
been ruff-clean (333 findings on the first run, all pre-dating CI), and
narrowing the check until it passes would make a red light green by removing the
light.

---

## 18. Test architecture

923 test functions in 71 files. Parametrisation expands this at collection; the
README quotes 963 collected tests. `pytest -n auto --dist loadfile` takes about
13 minutes on 8 cores (~75 minutes on one).

| Suite | Tests | Files | Covers |
|---|---|---|---|
| `layer4_core/tests` | 340 | 30 | twin state, live pipeline, ops, security, reports, replay, mission, sensors, admin API |
| `layer3_ai/tests` | 322 | 24 | features and leakage, all three tiers, fusion, health, RUL (four estimators), OOD, PINN, federated, prognostic metrics |
| `layer1_edge/tests` | 141 | 9 | CAN pipeline, edge layer, FADEC lanes, frozen sensors, MAVLink, MQTT, secure link, order analysis, edge inference |
| `layer2_physics/tests` | 104 | 6 | physics, synthetic data, fault coverage, OM-table range, maintenance actions, permanence of damage |
| `tests/` | 16 | 2 | engine configuration completeness, PS compliance |

### 18.1 Tests that encode a rule rather than a behaviour

These are the ones to read first, because each exists because something went
wrong:

| Test | The rule it holds |
|---|---|
| `layer3_ai/tests/test_no_leakage.py` | no forbidden column can reach a model input |
| `layer2_physics/tests/test_damage_is_permanent.py` | clearing a fault does not repair the engine |
| `layer2_physics/tests/test_maintenance_actions.py` | maintenance restores only the pathway it physically renews |
| `layer2_physics/tests/test_fault_coverage.py` | all eight PS fault modes are injectable and detectable |
| `layer4_core/tests/test_twin_compare.py` | every Section-B parameter has a twin comparison |
| `layer4_core/tests/test_stream_scopes.py` | the WebSocket enforces the same scopes as REST |
| `layer4_core/tests/test_oil_pressure_limit.py` | the oil-pressure-at-speed correlation rule |
| `layer4_core/tests/test_engine_model_wiring.py` | the engine on the aircraft is the engine whose limits are in force |
| `layer3_ai/tests/test_trend_restart.py` | a trend restarts correctly after maintenance |
| `layer4_core/tests/test_live_pipeline.py` | marked `slow`; runs the **real** loop for seconds — the only tests that exercise all five layers together |

The `slow` marker exists because of a specific failure: a console freeze reached
an operator while every cheap unit test passed. Deselect with `-m "not slow"`
only when you must.

---

## 19. Continuous integration and container

### 19.1 CI jobs

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml). On push to `main`,
on every pull request, nightly at 02:00, and on dispatch. Jobs are ordered
cheapest-first so an obvious failure reports in a minute rather than twenty.

| Job | Contents |
|---|---|
| **lint** | `ruff check`, `mypy` — both advisory (`continue-on-error`), by explicit decision |
| **audit** | `hmi_check.py` (display standard), `ps_compliance.py` (traceability), `licence_audit.py` (indigenisation claim). Each already exits non-zero on a finding, so CI just has to run them |
| **test** | `pytest -m "not slow"` on push and PR; the full suite including live-pipeline tests on the nightly schedule |
| **container** | build, **start**, and prove the image works |

The `container` job is the one that matters most, and its existence is the
lesson: `.github/workflows/` was an empty directory while 508 tests, a display
checker, a traceability matrix and a licence audit all existed and nothing ran
them. The image had **never been able to start** — the Dockerfile installed core
dependencies only, so `twin_api` died on `ModuleNotFoundError: No module named
'jwt'` before reaching `main()`.

The job therefore checks, in order:

1. the image builds;
2. the container starts;
3. `/api/healthz` reports `ok:true` — readiness is the **pipeline producing
   ticks**, not the port opening;
4. **ticks keep advancing** between two samples six seconds apart, not merely
   non-zero (the freeze-class regression);
5. `data/physics/flame_rotax_915is.json` is present in the image (`.dockerignore`
   once excluded all of `data/`, so the image shipped without the flame lookup
   and the engine could not have run even had it started);
6. the container does **not** run as root;
7. the root URL returns 200, so the console was built in.

### 19.2 The container

[`Dockerfile`](../Dockerfile), two stages:

| Stage | Contents |
|---|---|
| `console` | `node:22-slim`; `npm ci` then `npm run build`. Node has no business in the image that runs |
| runtime | `python:3.12-slim`; `pip install --require-hashes -r requirements.lock`, then the application, then the built console. `build-essential` is installed for SciPy/Cantera and **purged again** so it does not travel to an edge node |

`requirements.lock` is fully pinned and resolved for linux/amd64, and
`--require-hashes` makes the build **refuse any artefact whose SHA-256 does not
match**. An image built today and one built in six months contain the same code
— the point for a deliverable that has to be auditable.

```bash
docker compose up          # http://127.0.0.1:8000
```

The compose healthcheck calls `/api/healthz`, so `docker compose ps` showing
`healthy` means the engine is actually running. `twin-data` is a named volume so
a 96 MB run-to-failure fleet survives a rebuild — regenerating it takes fifty
minutes.

`docker-compose.fleet.yml` brings up the central fleet server and its database.

---

## 20. Data, models and artefact layout

`data/` is git-ignored; `DT_DATA_DIR` moves it.

| Directory | Contents |
|---|---|
| `data/synthetic/` | the run-to-failure training fleet: `train/val/test.parquet`, per-engine shards, a manifest and a fingerprint |
| `data/synthetic_hazard/` | the hazard-schedule variant used in the RUL ceiling work |
| `data/models/` | trained artefacts and the `*_report.json` measurement files |
| `data/benchmarks/` | C-MAPSS FD001–FD004, NGAFID, ACES, and the evaluation outputs |
| `data/physics/` | the precomputed flame lookups — **tracked**, one per engine |
| `data/twin_state/` | `<twin_id>.pkl`, each engine's life across restarts |
| `data/history/` | flight history and the ECTM trend |
| `data/ops/` | the squadron log: aircraft, missions, defects, releases |
| `data/recordings/` | recorded sorties, Parquet, training-fleet schema |
| `data/reports/` | generated PDF post-flight reports |
| `data/audit/` | the hash-chained audit log |
| `data/keys/` | signing material and `FIRST_RUN_CREDENTIALS.txt` |
| `data/terrain_tiles/` | fetched terrain for the mission planner |
| `data/training_logs/` | the stdout of every evaluation run, referenced by the README |

### 20.1 What does not fit in git

Trained models (`data/models/`) come with the clone through Git LFS — see the
main [README](../README.md#2--download-and-start). Running or evaluating the
twin needs nothing beyond that.

The larger training and benchmark data sets (the run-to-failure fleet,
NGAFID, older models, recorded flights, …) are **not included in this
repository** — retraining or re-measuring a benchmark figure needs them, running
the twin does not. [`docs/DATA_DOWNLOAD.md`](DATA_DOWNLOAD.md) lists exactly
what is and is not available. NASA C-MAPSS is the one exception:
`scripts/fetch_benchmarks.py` fetches it directly from NASA on demand.
`scripts/unpack_release.py` is a leftover from that other project's release
workflow and finds nothing to do here; it is harmless to run.

---

## 21. Scripts reference

52 scripts in `scripts/`. Grouped by what they are for.

### 21.1 Verification — run these to check a claim

| Script | What it proves |
|---|---|
| `ps_compliance.py` | executable traceability to the problem statement |
| `hmi_check.py` | the automatable parts of the PRD Part 4 §15 display checklist |
| `hmi_runtime_check.py` | the half of that checklist that needs a running console |
| `licence_audit.py` | the dependency and licence closure behind the indigenisation claim |
| `validate_physics_om.py` | the engine model against every printed full-throttle row of the manufacturer's table |
| `eval_split_inflation.py` | how much a random-row split would have inflated the result |
| `check_diagrams.py`, `check_ppt.py` | the diagram set and the idea deck against their own rules |

### 21.2 Training

`train_tier3.py` · `train_rul.py` · `train_survival.py` ·
`train_fault_namer.py` · `fit_ood.py` · `retrain_all.py` (all of it, end to end)

### 21.3 Evaluation

| Script | Measures |
|---|---|
| `eval_tier2.py` | the statistical tier: per-condition limits, false alarms, and PRD7 versus PRD7 + residuals side by side |
| `eval_fusion.py` | the fused detector against each tier alone |
| `eval_health.py` | the health estimator against ground truth |
| `eval_pinn.py` | whether the physics-informed loss actually helps |
| `eval_federated.py` | what federated training costs in accuracy |
| `eval_rul_matched.py`, `eval_rul_interval.py` | RUL estimators on identical windows; interval quality |
| `eval_aces_realdata.py` | the twin flown along real NASA Altus II flights |
| `benchmark_cmapss.py`, `benchmark_ngafid.py` | the outside yardsticks |
| `measure_rul_ceiling.py` | what a perfect state observer could do — the information ceiling |
| `rul_multiseed.py`, `learning_curve.py` | seed variance; whether macro-F1 still improves with more engines |
| `prognostic` metrics via `eval_*` | α-λ accuracy, prognostic horizon, NASA score |

### 21.4 Measurement of the deployment

`latency_bench.py` (tick latency under load, and what that figure is **not**) ·
`edge_footprint.py` (ONNX size, inference latency, resident memory) ·
`export_edge.py` (export the network and measure the export)

### 21.5 Diagnosis — read-only investigations

`diagnose_rul.py` · `diagnose_cooling.py` · `physics_audit.py` ·
`sensor_audit.py` · `investigate.py` · `investigate2.py` ·
`experiment_sortie_rul.py`

### 21.6 Generation and fetching

`gen_can_dbc.py` (the CANaerospace DBC) · `gen_diagrams.py`, `preview_diagrams.py`,
`gen_arch.py` · `gen_ppt.py`, `gen_ppt_v2.py`, `ppt_to_md.py` ·
`fetch_benchmarks.py`, `fetch_geodata.py` · `aces_extract.py` ·
`make_postflight_report.py` · `unpack_release.py` · `register_station.py` ·
`demo.py`

---

## 22. Measured performance

Every figure below is written by a script in this repository into an artefact
you can open. All model figures are on **40 engines the models have never
seen**, from a 200-engine run-to-failure fleet.

### 22.1 Headline

| | Measured | Artefact |
|---|---|---|
| Alarm precision | **0.996** | `data/models/fusion_report.json` |
| Detection ROC-AUC | **0.989** | `data/models/fusion_report.json` |
| False-positive rate | **1.0 %** of windows on healthy engines | `data/models/fusion_report.json` |
| False alarms per engine-hour | **0.20** (statistical tier, per-condition limits; was 0.29) | `data/models/tier2_report.json` |
| Fault classification, 8 classes | macro-F1 **0.780** (network alone 0.610) · misfire 0.97 · lubrication 0.92 | `data/models/fault_namer_report.json` |
| Health index vs ground truth | MAE **0.077**, 0.6 % of healthy engines mislabelled | `data/training_logs/eval_health.log` |
| Twin tick latency | p50 **51 ms** · p95 **83 ms** (budget 200 ms) | `data/models/latency_bench.json` |
| Edge model | **150 KB** ONNX · **0.64 ms** inference · 69 MB RAM | `data/models/edge_footprint.json` |
| PS traceability | **82 / 86 BUILT**, 0 MISSING | `python scripts/ps_compliance.py` |

### 22.2 The number that decides the system

Across 12,165 evaluated windows, the certified limits raise an alarm on **77**.
In the same data there are **7,558** windows in which the engine is genuinely
degrading and **not one limit is exceeded** — a conventional monitor has nothing
to say about any of them.

```
  certified limits fire on              77 windows
  the problem statement's own logic     74 windows
  ASTRA                              7,256 windows   <- 6,567 otherwise missed
```

Delivered at **99.6 % precision**, so the operator is not paying for them in
noise. Reproduce: `python scripts/eval_fusion.py`.

### 22.3 Control authority, measured

| Radiator blockage | Coolant temperature | Cooling flap | Caught by |
|---|---|---|---|
| none | 98.4 °C | 0.49 | — |
| 30 % | 100.3 °C | 0.68 | **authority check** |
| 45 % | 101.9 °C | 0.84 | **authority check** |
| 70 % | 143.7 °C | 1.00 saturated | temperature limit (too late) |

A 30 % blockage moves coolant temperature **1.9 °C** — no limit will ever catch
it. It moves the flap **0.19 of its full travel** — measurable on the first
sortie. This engine has **no thermostat**, confirmed against all thirteen
manuals; its temperatures are held by the airframe's cooling-air flaps, and like
the wastegate a flap **runs out of travel**.

### 22.4 Physics validation

| | |
|---|---|
| Against the manufacturer's table | 130 full-throttle rows: median power error **1.05 %**, plenum pressure 0.43 %, charge-air temperature **0.007 K**, fuel flow 1.71 %. Within **1.3 %** at every altitude to 15,000 ft |
| Physics-informed learning | hybrid vs data-only RMSE 4.53 vs 4.57 — same accuracy, constraint violations **1.000 → 0.216** |
| Cooling system | rebuilt from the manuals: no thermostat, oil cooler sized to the IM's stated 30 kW duty. Coolant 96–102 °C, CHT 113–124 °C across the full envelope, against limits of 120 °C and 135 °C |
| Envelope | 0–23,000 ft, full FADEC authority, every published limit respected |

### 22.5 Edge readiness

| | |
|---|---|
| Twin tick | p50 **51.3 ms**, p95 **82.7 ms**, p99 104.4 ms with 3 concurrent clients, against a 200 ms budget. Pinned to one core: p95 **95.3 ms** — still inside budget |
| Model on the aircraft | **149.6 KB** ONNX, **0.638 ms** median inference (p95 1.205 ms) |
| Memory | **68.9 MB** resident, **0.34 MB** growth over 200 inferences — no leak. **3.4 % of the smallest Raspberry Pi** |
| Quantised | int8 is **2.94× smaller**; across 300 windows it changed **1 decision** |
| Offline | 72-hour store-and-forward buffer; the twin keeps running with no link |

**Latency is twin-tick compute on x86-64.** It bounds algorithmic cost. It is
**not** sensor-to-screen, and **not** an ARM target.

---

## 23. Extension guides

### 23.1 Add an engine

An engine is a YAML file in `configs/engines/`. **No code changes.**

1. Copy `configs/engines/_template.yaml` to `configs/engines/<key>.yaml`. It
   starts with `extends: rotax_915is`, so write only what differs; everything
   else is inherited. Limits that differ (vibration bands, rpm limits, the
   health-assessment rpm) go under `thresholds_override:`.
2. Set `identity.ignition` to `SPARK` or `COMPRESSION` — that selects the
   combustion model and is the entire code difference between a petrol and a
   diesel engine here. Set `identity.validated: false` until it is.
3. `python run.py --check-engine <key>` names every missing key, then flies the
   engine for ten seconds in the virtual engine.
4. Fit it to an aircraft: set `engine_key` in `configs/fleet.yaml`, or, as
   commander, **Admin → Engine definitions → Fit to aircraft**. That is an
   engine change: the aircraft is unreleased until it is ground-run and
   inspected, and the new engine starts at 0 h.
5. `python run.py --list-engines` shows each engine and the aircraft it is on.

The limits in force are always those of the engine on the aircraft loaded on the
ground station — held by
[`test_engine_model_wiring.py`](../layer4_core/tests/test_engine_model_wiring.py).

On the console, **ENGINES** lets the engineer write and check a definition from
the template or from an existing engine. `austro_ae330.yaml` is a worked example:
a turbo-diesel stated in about 70 lines on top of the Rotax.

### 23.2 Move to real CAN hardware

Three things change; nothing else does.

**1 · The transport.** `layer1_edge` takes its interface as a string:
`virtual` → `socketcan` → `pcan`.

```bash
sudo ip link set can0 type can bitrate 1000000
sudo ip link set up can0
```

**2 · The CAN database.** `configs/can/engine.dbc` uses open CANaerospace
identifiers. The Rotax Display CAN assignment is not public — the installation
manual directs the reader to an authorised distributor. **Our DBC must not be
presented as the Rotax database**; on real hardware it is replaced with the
manufacturer's.

**3 · The engine profile.** `configs/engines/*.yaml`.

**What does not change:** the physics model, the twin, the detectors, the health
indices and the console all consume validated telemetry and are indifferent to
where it came from.

**What must be re-derived on hardware**, because the shipped values come from
the simulated instruments: `lane_agreement_floor`,
`frozen_noise_over_resolution`, and `response_noise`. The configuration says so
in place, and a sensor quieter than the shipped ratio would be wrongly flagged.

### 23.3 Add a detector or a feature

1. Add the feature to `DERIVED` in `layer3_ai/features.py` with an explicit
   centre and scale, and compute it in both the dataset generator and
   `layer4_core/live.py` — the contract is that training and serving call the
   same definition.
2. Check it against `FORBIDDEN_PREFIXES` / `FORBIDDEN_EXACT`; the leakage test
   will fail if it is ground truth in disguise.
3. **Measure it.** `features.py` records two features that were added on sound
   reasoning and real single-feature evidence, and removed again because they
   cost more in dilution than the signal was worth. Re-run `eval_tier2.py`,
   `train_tier3.py` and `eval_fusion.py` and compare the aggregate.
4. Record the outcome in `docs/PRD_DEVIATIONS.md`, including a negative result.

### 23.4 Add a route to the API

1. Decide the **scope** it needs, and add it to the roles that make that
   decision in `configs/thresholds.yaml → security.roles` — the scope reflects
   the decision, not what might be interesting.
2. Guard the route server-side. The UI is never the boundary.
3. If it mutates state, add it to `security.audit.log_events`.
4. Add a test asserting a role without the scope is refused, and — if it streams
   — that the WebSocket enforces the same thing.

---

## 24. Deployment roadmap

### 24.1 Today

| Target | State |
|---|---|
| Developer workstation | `python run.py`, one command, Windows / macOS / Linux |
| Container | `docker compose up`, hash-verified lock file, non-root, healthcheck on advancing ticks |
| Ground station | the same container or process, with `DT_TLS_CERT`/`DT_TLS_KEY` and a non-loopback bind |
| Central fleet tier | `fleet_server` + PostgreSQL, on-premise |

### 24.2 The edge node

The Layer 1 stack has **no network dependency by construction**: rules,
buffering and alerting continue with the link down, and 72 hours of telemetry
are held locally in SQLite WAL for back-fill on reconnect. Dependencies are
light enough for a Raspberry Pi 4 — measured at 68.9 MB resident, 3.4 % of the
smallest Pi, with a 149.6 KB ONNX model inferring in 0.638 ms.

The path onto hardware is [§23.2](#232-move-to-real-can-hardware): a PiCAN2 HAT,
`socketcan`, the manufacturer's DBC, and the instrument constants re-derived
from datasheets or bench data.

### 24.3 What is not yet done

- **Latency on ARM.** Every figure is x86-64 twin-tick compute. An ARM
  measurement, and a sensor-to-screen measurement, are both outstanding.
- **A VRDE-class rig calibration.** The `[MOD]` tags mark precisely which values
  a rig would replace — that is what the provenance tagging is *for*.
- **Real-engine validation beyond one narrow claim.** The RUL architecture is
  validated on C-MAPSS. IMS and CWRU are not downloaded, so no real-bearing
  claim may be made.

---

## 25. Known limitations

Stated because an evaluator will find them, and a system that knows its own
edges is worth more than one that does not.

| Limit | Detail |
|---|---|
| **Recall is 0.870** at the chosen operating point | the fusion trades recall for precision deliberately; the threshold is a published, tunable choice and every combiner's curve is in `fusion_report.json` |
| **Naming *which* fault is weaker than detecting *that* there is one** | macro-F1 0.780 across eight classes on unseen engines. Misfire 0.97, vibration 0.94, lubrication 0.92, injector 0.86, overheating 0.84 are usable; cooling 0.71 is borderline; sensor drift 0.54 and combustion instability 0.46 are not yet. On an engine with under four completed flights a history fault is named only while a detector agrees |
| **Per-class scores move ±0.10 between runs** | with nothing changed but the seed, because each class is carried by 5–12 of the 40 test engines. Quote the aggregate; treat a single per-class figure as approximate |
| **Above 15,000 ft with OAT below −30 °C** | 14 of 130 manual rows are under-predicted for power. Below that, inside 1.3 % everywhere |
| **Remaining-life intervals are not calibrated** to their nominal coverage | which is exactly why the system refuses to publish a figure without one |
| **RUL on this engine is observability-limited** | RMSE 121 h at 0.87 σ, α-λ 0.20; 3 of 15 engines inside the ±20 % cone at half-life. The same architecture scores 1.08–1.18× published SOTA on C-MAPSS, so the cause is the data, not the estimator: a 30-sample window sees 0.0013 % of an engine's life — a state, not a rate. The 48 per-engine sessions spanning ~500 h that would show the rate are in the dataset and not yet fed to the model. The NASA prognostics score (298 vs < 500) is met, so the errors are not systematically dangerous |
| **Battery state of health is not implemented** (gap G4) | it needs internal-resistance trending no channel provides. The electrical index **renormalises** rather than scoring the missing term 1.0 |
| **Latency is measured on x86-64** | not on a deployed ARM edge computer, and it is tick compute rather than sensor-to-screen |
| **The Austro AE330 diesel is a placeholder**, not a model | its own numbers are order-of-magnitude and what it inherits is Rotax data. It runs cleanly (health ~0.95–0.97 when new, no false alarms) and is labelled unvalidated everywhere. The trained networks were trained on the Rotax fleet only |
| **One aircraft on the ground station at a time** | changing aircraft parks the one leaving (its life saved) and loads the next; the others are their last-known condition, not a parallel simulation |
| **A tasked mission's cruise is compressed** | `ops.simulated_cruise_hours`, 6 minutes by default, so a demonstration ends. The Go/No-Go is assessed for the **planned** endurance, and the console says so |
| **An aircraft's condition is unknown until the twin has run its engine** on this station | its hours, inspection and TBO position are known from its log; its health is not invented |
| **Real-data validation is one narrow claim** | the RUL *method* on C-MAPSS. C-MAPSS is a turbofan sharing no sensor and no failure mode with a piston engine, so it says nothing about the 915 iS model, its health index, or its RUL on this airframe. No transfer-learning claim is made and no path to attempt one exists |
| **`ruff` and `mypy` are advisory in CI** | 333 pre-existing findings; clearing the debt is tracked work, at which point `continue-on-error` comes off |

---

## 26. Engineering conventions

Four rules are enforced in code rather than asked for in review.

### 26.1 Every engine value carries its source

`[TCDS]` · `[OM]` · `[IM]` · `[MML]` · `[DS]` · `[DER]` · `[MOD]`. **No value
that shapes engine behaviour is untagged.** Where the manuals contradicted the
implementation, the manuals won.

### 26.2 A number is shown only when it was earned

| Situation | What the system does |
|---|---|
| No measurable degradation trend | states the reason — never a remaining-life figure |
| Remaining life with no calibrated interval | withholds it; a bare RUL is forbidden |
| Sample unlike anything in training | detection confidence drops to zero and says so |
| No network scoring available | fault probabilities are **absent**, not zeros dressed as certainty |
| Instrument offset with no second source | reported as unattributed |
| A channel fails validation | the value is removed and the reason given, never substituted |

There is **no fallback path that invents a plausible number.** This is why the
WebSocket distinguishes full from partial frames: on a full frame, an absent
field *means* the system is declining to publish it.

### 26.3 Damage does not heal

Clearing an injected fault stops it progressing; it does not repair the engine.
Only maintenance restores a pathway, and only the one it physically renews. An
inspection that replaced nothing restores nothing. A test enforces this for all
eight fault modes.

### 26.4 Every departure from the plan is recorded

[`docs/PRD_DEVIATIONS.md`](PRD_DEVIATIONS.md) holds 246+ entries, each with the
measurement that forced it — **including the ones that made this system look
worse**. No deviation from the PRDs exists in code without an entry.

### 26.5 Module docstrings carry the reasoning

Most modules in this tree open with several hundred words explaining *why the
module exists*, *what it is not*, *what was measured*, and *what defect in the
specification it had to fix*. That is deliberate and it is the fastest way into
any part of this system: read the docstring before the code. Several record a
correction to the PRD (the RUL loss function, the absolute health formulas, the
fusion spec defect) and several record a negative result.

---

## 27. Glossary

| Term | Meaning |
|---|---|
| **MALE UAV** | Medium Altitude Long Endurance Unmanned Aerial Vehicle — flies 20–30 hours at a stretch with no crew on board |
| **Digital twin** | a software model of a specific physical machine, running live alongside it and fed by its real data |
| **FADEC** | Full Authority Digital Engine Control — the engine's computer, with two independent lanes so one failure cannot stop the engine |
| **CANaerospace** | the aerospace standard for carrying engine and avionics data on a CAN bus |
| **Residual** | measured value minus what a brand-new engine would read under identical conditions. The core measurement in this system |
| **Shadow model** | the second instance of the engine model, held permanently at zero hours, that produces the as-new side of a residual |
| **Control authority** | how much travel a control still has in reserve. A cooling flap at 49 % has room left; the same flap at 100 % has none |
| **CHI** | Composite Health Index — the weighted sum of four subsystem scores |
| **CombHI** | Combustion Health Index — one of the sub-indices |
| **RUL** | Remaining Useful Life — flight hours left before maintenance is required |
| **CHT / EGT** | Cylinder Head Temperature / Exhaust Gas Temperature |
| **MAT** | Manifold Air Temperature (charge-air temperature after the intercooler) |
| **BSFC** | Brake Specific Fuel Consumption, g/kWh — fuel burned per unit of shaft work |
| **BMEP** | Brake Mean Effective Pressure |
| **MVEM** | 0-D Mean-Value Engine Model — cycle-averaged thermodynamic state |
| **ECTM** | Engine Condition Trend Monitoring — drift against a baseline flight, across flights, weather excluded |
| **TBO** | Time Between Overhauls (1,200 h / 15 years for this engine) |
| **PFR** | Post-Flight Report — events with time, flight phase and ATA reference |
| **OOD** | Out Of Distribution — a sample unlike anything in training |
| **PINN** | Physics-Informed Neural Network — a loss that penalises violations of a governing relationship through the network's own derivatives |
| **FedAvg** | Federated Averaging — a weighted average of locally trained weight vectors |
| **BPFO / BPFI / BSF / FTF** | bearing defect orders: ball pass frequency outer / inner, ball spin, fundamental train |
| **False-positive rate** | how often the system cries wolf on a healthy engine — the number that decides whether anyone keeps reading the alerts |
| **Held-out engines** | engines the models were never trained on. Every model figure in this documentation is reported only on these |
| **C-MAPSS** | NASA's Commercial Modular Aero-Propulsion System Simulation turbofan benchmark — the outside yardstick |
| **α-λ accuracy** | a prognostics metric: is the estimate inside an ±α cone at fraction λ of life? |
| **LOI** | Level Of Interoperability (STANAG 4586). This system is scoped to LOI 1–2: receipt and display only |
| **GCS** | Ground Control Station |
| **Sortie** | one flight, from engine start to shutdown |
| **Snag** | a defect reported by an operator at debrief |

---

<div align="center">

**Defence Research and Development Organisation**
Smart India Hackathon 2026 · Problem Statement 26054

`Restricted (Government Use Only)`

</div>
