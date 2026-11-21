# ASTRA against EASA's AI guidance

**Reference:** EASA Artificial Intelligence Concept Paper, Issue 2, *Guidance for Level 1 & 2 machine learning applications* (March 2024).
This is the most detailed published guidance on how an aviation authority expects machine learning to be assured. India has no equivalent yet; CEMILAC and DGCA reviewers read this document. It has 125 objectives. This page maps the ones that apply to ASTRA, with evidence in this repository, and says plainly where we fall short.

Status key: **Met** = evidence in the repo · **Partial** = started, not complete · **Gap** = not done.

## 1. What kind of AI system this is (CL-01)

**ASTRA is Level 1B: cognitive assistance to a human who decides.**

- It never commands the engine, throttle or aircraft. It advises the operator (go / no-go, alerts) and the maintainer (what to inspect, by when).
- The safety-critical path does **not** depend on machine learning. Tier-1 rules run on the edge within a 50 ms budget and bypass physics and AI entirely (`configs/thresholds.yaml` → `pipeline.edge_critical_path_ms`).
- Machine learning can only add evidence to the fused verdict. It never removes a rule-based alert.

That last point is our **safety risk mitigation layer (SRM-01)**: if every learned model failed, the certified-limit rules would still fire.

## 2. Mapping

| Objective (EASA) | What it asks | ASTRA evidence | Status |
|---|---|---|---|
| **CL-01** | Classify the AI level | Level 1B, justified above | Met |
| **SRM-01** | Independent safety layer if assurance is incomplete | Tier-1 rule engine (`layer1_edge/edge_rules.py`) on the edge, independent of all ML | Met |
| **CO-01/02** | Identify end users, roles, tasks | Four roles: operator, maintainer, engineer, commander. Each has its own scopes (`layer4_core/security.py`) and screens (`docs/WHO_READS_THIS_SCREEN.md`) | Met |
| **CO-04** | Concept of operations, operating domain | PRD Parts 0–4 (`docs/prd/`); Rotax 915 iS certified limits (`configs/thresholds.yaml`, TCDS/OM referenced line by line) | Partial: no single ConOps document |
| **DM-01, DA-04** | Data sources and data quality requirements | Physics fleet generator (`layer2_physics/synth_data_gen.py`); NASA C-MAPSS; NGAFID (real piston aircraft); **NASA ACES real Rotax-912 UAV flights** (`scripts/aces_extract.py`) | Partial: fault data is simulated |
| **DM-06 / DM-09** | Independent train / validation / test sets | Split **by engine**: no engine appears in two sets (`layer3_ai/features.py` → `stratified_engine_split`). Every threshold is fitted on train or validation, never on test | Met |
| **DM-08** | Data normalisation fit for learning | Fixed centres and scales, never per-batch (`features.FeatureSet.normalise`); per-engine residual reference (`layer3_ai/rul_serving.py` → `ResidualBaseline`) | Met |
| **LM-01, LM-15** | Describe the model architecture | Tier-2 ensemble (`layer3_ai/tier2_statistical.py`), Tier-3 network (`layer3_ai/tier3_deep.py`), per-fault gradient-boosted fault namer with engine history (`layer3_ai/fault_namer.py`), RUL LSTM, CatBoost survival head | Met |
| **LM-04 / LM-14** | Generalisation bounds, checked on the test set | Every metric reported on **unseen engines**; engine-grouped cross-validation for the survival head; split-conformal RUL intervals whose coverage is measured | Partial: empirical bounds only, no formal (complexity-based) bound |
| **LM-09** | Evaluate the trained model on the test set; document it | `data/training_logs/*.log`, `data/benchmarks/*.json`, acceptance tables, **including targets not met** | Met |
| **LM-12 / LM-13** | Stability and robustness in adverse conditions | Sensor failure and lane failure injection (`/api/faults/sensor`, `/api/faults/lane`); CAN validation (range, rate, frozen); stuck-sensor check (`layer4_core/sensor_response.py`); instrument-drift attribution (`layer4_core/sensor_bias.py`) | Partial: no systematic robustness sweep report |
| **IMP-04 / IMP-06** | Validate any post-training transformation | ONNX export compared float32 vs int8: int8 changes 0.3% of decisions, so **the float graph is deployed** (`scripts/export_edge.py`, `data/models/tier3_edge_report.json`) | Met |
| **IMP-07** | Differences between training and target hardware | Measured on the development PC only | Gap: not yet measured on the target on-board computer |
| **SU-01** | Accuracy of the reference (physics) model | Mean-value engine model validated against the Rotax Operator's Manual (`scripts/validate_physics_om.py`). Flown along **52 h of real Altus II (Rotax 912) flights** (`scripts/eval_aces_realdata.py`, `data/benchmarks/aces_realdata.json`): it follows fuel flow (r 0.80), coolant (0.80) and EGT (0.72) across operating points, but not that installation's oil system (oil temperature r 0.11, oil pressure -0.36) | Partial: not yet calibrated to a real installation |
| **CM-01** | Configuration management of models and data | Git; checkpoints tracked; library versions pinned with hashes (`requirements.lock`, scikit-learn 1.7.2); a checkpoint whose feature order disagrees with the code is **refused**, not served | Met |
| **QA-01** | Quality assurance | 935 automated tests across all five layers; every deviation from the PRD logged with its reason (`docs/PRD_DEVIATIONS.md`, 250+ entries) | Met (no independent QA yet) |
| **EXP-04** | Output confidence from real measurement | Conformal RUL interval (no interval shown without calibration); calibrated survival probabilities with reliability tables; per-fault calibrated thresholds | Met |
| **EXP-05** | Monitor that inputs are inside the design domain | Out-of-distribution detector (`layer3_ai/ood.py`, `data/models/ood.npz`). An unfamiliar input is flagged, and the learned tiers are not trusted on it | Met |
| **EXP-07** | Monitor that output confidence is acceptable | RUL withheld as "beyond horizon" until evidence exists; survival head used only where validated skilful; health values marked live / held / assessing | Met |
| **EXP-09** | Record data to explain behaviour afterwards | Flight recorder (`layer4_core/recorder.py`); tamper-evident audit log; replay page | Met |
| **EXP-11 / EXP-12 / EXP-17** | Clear, useful, valid explanations | Every alert names the channel, the residual against the as-new twin and the rule or tier that raised it (`layer3_ai/explain.py`, `layer3_ai/advisory.py`) | Met |
| **EXP-19** | Tell the user about unsafe conditions in time | Master warning and caution per MIL-STD-411F (`docs/PRD_Part4_Defence_HMI_Standard.md`) | Met |
| **HF-01..03** | Situation awareness | Operator overview on one screen, per MIL-STD-1472H; flight phase, go / no-go and alerts together | Met |
| **HF-06** | Diagnose abnormal situations: root cause, resolution, consequences | Fault named with evidence; maintenance action and time-to-action; mission impact | Met |
| **IS-01..03** | AI-specific information-security risks | Role scopes enforced server-side, including on the live stream; HMAC-authenticated links (`layer1_edge/secure_link.py`); signed audit | Partial: no multi-factor login or encryption at rest yet |
| **ET-02** | No over-reliance | Advisory only; unknown values shown as unknown ("---"), never as a plausible number | Met |
| **ET-05** | Users know they are dealing with AI | Every verdict shows its source tier (RULE / STAT / DEEP) | Met |
| **ET-07 / ET-08** | Training needs; risk of de-skilling | Not done | Gap |
| **ET-06** | Environmental impact analysis | Not done | Gap |

## 3. Honest summary

- **Met: 21.** The strongest areas are data independence (engine-level splits), confidence reporting, input-domain monitoring, the independent rule-based safety layer, and model-transformation checks.
- **Partial: 7.** The biggest is data. Fault data is still simulated. Real Rotax-family flight data (NASA ACES) now checks the physics, and shows it follows fuel, coolant and EGT but not that engine's oil system; the data contains no labelled failures.
- **Gap: 3.** Target-hardware verification, operator training analysis, and environmental impact.

None of the gaps is a design flaw. They are work that follows a working prototype.
