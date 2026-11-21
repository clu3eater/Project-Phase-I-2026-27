# Competitor analysis: SIH26054 teams and industry

*Internal: for the team, to prepare for judging. Checked on 23–24 Sep 2026.*

## 1. How this was checked

- **Found:** 101 public GitHub repositories that match this problem statement (SIH26054, aero-piston, MALE UAV engine twin). Of these, 72 are genuine SIH26054 engine-twin projects with code.
- **Cloned and audited by script:** every one. The script counts code lines (excluding libraries and build output), engine-physics code, test functions, and real model training. It also records how models are evaluated, which datasets are used, whether the browser generates readings with `Math.random()`, whether accuracy figures are hard-coded in the UI, and whether a cloud LLM is used.
- **Read by hand:** the code of the 16 strongest (below).
- The same audit was run on ASTRA for a fair comparison.

## 2. The field in numbers (72 competing repositories)

| | Competitors | ASTRA |
|---|---|---|
| Median size | 3,700 code lines | 59,345 |
| Train a real ML model | 44 of 72 | yes |
| Test on engines or flights the model never saw | **10 of 72** | yes: every metric, split by engine |
| Use a random row split (inflates scores; see §4) | 15 of 72 | no |
| Any real-world engine data | 1 (NASA ACES, labels self-made) | NGAFID (real piston aircraft, real maintenance labels) + NASA ACES (real Rotax-912 UAV flights) |
| Automated tests | 45 of 72 have **none**; 7 have 50 or more | 848 test functions (935 tests) |
| Engine physics of 1,000+ lines | 11 of 72 | 8,741 lines |
| Readings generated in the browser with `Math.random()` | 13 of 72 | none (the only use is a 0.3 mm visual shake of 3D parts already in a real fault state) |
| Send data to a cloud LLM (Groq, Gemini, etc.) | 10 of 72 | none: fully offline |
| Reference MIL-STD / EASA | 16 of 72 | yes: MIL-STD-1472H and 411F implemented; EASA mapping in `docs/EASA_AI_MAPPING.md` |

## 3. The strongest competitors, from their code

| Team / repo | Real strengths | Weaknesses found in the code |
|---|---|---|
| **rajaspatil1105** (AERIS + Rotax-915 simulator) | The most serious physics: a mean-value engine model (`shared/engine_mvem.py`, 1,583 lines), sensor model, throttle dynamics, fault injection. The Rotax reference model is scored with MAE, RMSE and MAPE | ML uses a **random row split** (`train_baselines.py`: `train_test_split(..., test_size=0.15)`), so rows of the same engine sit in both train and test. No tests. Absolute local data paths (`C:/aeris_data/...`) |
| **akshat-u/SIH26054** (largest repo) | Big UI, many pages, backend of 3,700 lines | The frontend is **duplicated** (`src/` and `frontend/src/` are copies), so real size is about half. "Physics" is scaling factors, not an engine model. No tests. LLM chat through Ollama or Gemini |
| **DHRUVA** | Polished UI, 77 test functions | Dashboard readings made in the browser (`engineSimulationService.ts`: sine waves plus `Math.random()`). **Hard-coded confidences** "98.2%", "99.1%", "99.8%" (`engineDetailsTelemetryService.ts`). AI agent returns canned text |
| **GARUDAVYUHA** | 3D Rotax model, Weibull wear-out | Anomaly model trained on NASA **jet-engine** data (C-MAPSS) and used for a piston engine. The RUL error defaults to a hard-coded **6.8 h** (`server.py:295`) |
| **AeroTwin-UAV (Sahilpatil)** | Honest: splits by engine; 109 test functions | Physics is one-line formulas (`density_ratio = exp(-alt/8500)`; `oil_pressure -= 0.35*severity`) |
| **Gagguverse** | Good documentation; clear "synthetic data" notices | The engine "simulation" runs in browser JavaScript. Its **99% accuracy** comes from a random row split on its own data (`train_models.py:248`). Sends telemetry to a US cloud LLM (Groq) |
| **VIKASHL25** | XGBoost; RUL split by engine; CAN adapter; MATLAB/Simulink link | Trained only on its own 100k-row CSV. Dashboard has a hard-coded fallback `confidence: 0.98` |
| **Kavish-0/UAV-EngineTwin** | Real engine model; checks altitude-power derating against published figures; Kalman estimator | Random Forest benchmark only. Small test suite |
| **AeroPulse** | **The only team using real UAV engine data** (NASA ACES); splits by flight | NASA's data has no health labels, so the reported "87% health accuracy" predicts labels the team made from the same data |
| **ADARSH200703** | Arduino hardware demo | Hard-coded model errors in the backend (`main.py:1517`: `rmse_rpm: 12.4`, `rmse_cht_c: 0.85`). Hard-coded RUL strings in the UI (`aiPredictor.js`: '01:15:30', '00:45:12', …). Demo data from `Math.random()` |
| **Vibro-AI** | 97 test functions; vibration focus | Hard-coded confidences in the browser (`anomalyEngine.ts`: 98.2, 89.2, 88.4, 87.0); fake "inference latency" from `Math.random()` |
| **twinguard-aero** | CI pipeline; honest "proof-of-concept" labels | Physics is straight-line formulas (`exp_cht = amb + 105 + 58*load + …`); random row split |
| **TITAN** | Neural-network training, C-MAPSS pre-validation, virtual sensors | No split by engine |
| **atharv20s** | PINN, a reinforcement-learning maintenance agent, split by engine | 3D view hard-codes `estRul = 485.0` |
| **Rishi-09** | Split by flight run; "nominal twin" regressor | Advisory from a US cloud LLM (Groq llama-3.3-70b) |
| **123sanjaypadmaraj** | 137 JavaScript tests, CI | No ML at all; `rul = 500` fixed; LLM writes the narrative |

## 4. Why their 96–99% and our lower numbers are not comparable

A random row split puts rows from the same engine in both training and test data. The model is then partly graded on engines it has already seen. We measured the effect on our own data with the same simple model (a Random Forest, as most teams use):

| Same model, same data | Accuracy | Macro-F1 |
|---|---|---|
| Random row split (what most teams do) | **96.0%** | 0.961 |
| Engines never seen in training (what ASTRA reports) | **62.8%** | 0.615 |

**Our numbers on unseen engines, in the terms competitors use:**

| Measure | ASTRA |
|---|---|
| "Is something wrong?" (anomaly F1) | 0.95 (precision 0.97, recall 0.93) |
| Faults at meaningful size (≥ 20% severity): caught | 96–99% |
| Fault named correctly, all 8 types (macro-F1) | 0.78 (misfire 0.97, vibration 0.94, lubrication 0.92, injector 0.87, overheating 0.84) |
| Failing engines warned before end of life | 31 of 31, median 318 flight hours ahead |
| False alarms on healthy engines (statistical tier) | 4.8% (target < 5%) |
| Failure within 50 h: ranking quality (AUC) | 0.965 |

## 5. What competitors have that we don't (and whether to copy it)

| Feature | Who | Recommendation |
|---|---|---|
| AI chat assistant | Gagguverse, Rishi-09, akshat-u, 123sanjaypadmaraj | **Don't copy a cloud one.** Sending engine data to a US cloud service is a security problem for DRDO. If one is added, it must run offline and only explain what the system already computed |
| Physical hardware in the loop | ADARSH200703 (Arduino), VIKASHL25 (CAN hardware) | Worth doing for the live demo: a USB-CAN adapter replaying a flight into our CAN ingest |
| Flight profiles from real autopilot software | dractonixx (ArduPilot) | Nice-to-have: realism for the mission profile |
| Physics checked against published figures | Kavish-0 (DRDO/VRDE derating) | We already check against the Rotax manual. Add the NASA ACES comparison to the pitch |

## 6. Industry, for context

- Savvy Aviation (FEVA): ML on piston-engine EGT, 3M+ flights, 60+ valve failures caught early.
- C3 AI / USAF PANDA: official CBM+ system, 3,000+ aircraft.
- GE Aerospace: AI engine monitoring, 45% more issues detected, 50% fewer false alerts.
- Honeywell Ensemble and P&W FAST: upload engine data after each flight (not live).
- Palantir / Airbus Skywise: a data platform, not an engine model.
- Rotax B.U.D.S.: fault memory reader, no prediction.

**None of them offers a live, offline, physics-plus-ML twin for a Rotax-class engine in a MALE UAV.** That is ASTRA's position.
