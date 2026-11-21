# Pitch deck and handbook — corrections before judging

The SIH idea presentation (`SIH2026-IDEA-Presentation-ASTRA.pdf` and its two
near-copies), the pitch handbook (`ASTRA-Pitch-Handbook.pdf`, 52 pages) and the
sample post-flight report are PDFs with no editable source in this repository,
so their corrections are listed here to be applied by hand. Each entry gives
where the text is, what it says, what it should say, and the evidence that was
checked. Findings come from the review of 14–15 September 2026 (IDs JUR-, ML-,
CAN-, PHY-).

**Branding is not in scope.** The DRDO logo, seal, State Emblem, DRDO wording
and the classification marking stay exactly as they are.

Page numbers are the handbook's printed "Page N of 52"; slide numbers are the
deck's page order. Quoted text is exact.

---

## 1. Engine and platform facts a propulsion judge will correct

| # | Where | Says | Should say | Evidence |
|---|---|---|---|---|
| 1.1 | Handbook pages 6, 7 and 13 | "Air-cooled" (glossary heading); "On an air-cooled engine, cylinder head temperature is the single most revealing measurement"; "The most informative single channel on an air-cooled engine"; "On an air-cooled engine this is the failure mode that matters most." | The 915 iS has **liquid-cooled cylinder heads and ram-air-cooled cylinders**. Coolant temperature carries the certified limit (120 °C); cylinder head temperature is added instrumentation. Cooling degradation on this engine is a fouled radiator or coolant-side scaling. | `configs/engines/rotax_915is.yaml` lines 34 and 202, quoting the type certificate data sheet §2; DEV-13 (yaml line 42) |
| 1.2 | Handbook page 33 (script for slide 1) and page 40 | "But it has only one engine." | "The Heron — the MALE UAV India already flies — has one engine." As written it will be heard as TAPAS, and **TAPAS-BH-201 is twin-engined**. | en.wikipedia.org/wiki/TAPAS-BH-201 |
| 1.3 | Handbook pages 6 and 42 | "The older Rotax 914 is carburetted with neither — you physically cannot build this on it." | "The 914 has no FADEC and no CAN bus, so it would need an add-on data unit. We built on the 915 iS because its FADEC already publishes engine data on CAN — **and it is the engine of the Heron Mk II that the IAF and Army have ordered**." India's Heron Mk I fleet flies the 914, so dismissing it invites a correction; the Mk II fact is the stronger line. | Heron Mk II engine: en.wikipedia.org/wiki/Rotax_915_iS; Indian order: jpost.com, "India buys 4 Heron MK II" |
| 1.4 | Handbook page 36 (script for slide 3); repeated on page 48 | "we add no new sensors — we just listen on the aircraft's CAN bus"; "No new sensors means no new airworthiness certification of new hardware" | "Most readings come from the engine's own FADEC over CAN. Four are added sensors, and we say so: per-cylinder head temperature, a fuel-flow meter, a battery current shunt and an accelerometer." | CAN-13; HUMS message range 1800–1899 in `scripts/gen_can_dbc.py`; the handbook itself concedes the accelerometer elsewhere |

## 2. Claims the code or the measurements do not support

| # | Where | Says | Should say | Evidence |
|---|---|---|---|---|
| 2.1 | Slide 4 (messaging and bus row); slide 6 heading "STANDARDS FOLLOWED"; handbook page 9 (glossary) and page 48 ("We also support ARINC 429 for older avionics") | ARINC 429 and STANAG 4586 as standards followed and supported | Rename the heading **"Standards referenced"**. Remove ARINC 429, or mark it "roadmap": there is no ARINC 429 code. State STANAG 4586 as architectural alignment at levels of interoperability 1–2 only (receive and display telemetry; no vehicle commands). | JUR-04; no ARINC 429 implementation in the repository; `layer4_core/security.py` header scopes STANAG 4586 to LOI 1–2 |
| 2.2 | Handbook page 18 (glossary, quantisation); slide 4 ("quantised inference onboard") | "Roughly four times smaller and substantially faster, for a small accuracy cost." | "The on-board model is a 150 KB ONNX graph that scores a window in 0.48 ms. We also measured an 8-bit version: 2.9 times smaller but **slightly slower (0.91×)**, and it changed 5 of 300 decisions, so the full-precision graph is the one on board." | JUR-05; `data/models/tier3_edge_report.json` (float 153,186 B, int8 52,111 B, ratio 2.94, speedup 0.91, decisions changed 5 of 300) |
| 2.3 | Slide 2 | "Crank-angle order analysis pinpoints the misfiring cylinder" | "Per-cylinder exhaust temperature names the misfiring cylinder; order analysis names the damaged bearing element." | JUR-09; misfire is found by the cold-cylinder check in `layer4_core/live.py`; `layer1_edge/order_analysis.py` computes bearing orders |
| 2.4 | Handbook page 25 | "NASA IMS / Case Western … IMS and Case Western for vibration" as validation data | Remove, or run the benchmark first: no IMS or Case Western result exists in `data/benchmarks/`. | JUR-09 |
| 2.5 | Slide 4 ("Demonstrated using simulated and real engine datasets"); handbook pages 42–43 | "we benchmark the method on real piston-engine flights"; "on real piston-engine flight data" | "On NGAFID — real Cessna 172 flights with maintenance records — a feature pipeline built on the same method (not the physics twin itself) reaches ROC-AUC 0.772 and 0.764, against published 0.826 and 0.775." | JUR-08; `data/benchmarks/ngafid.json` (intake gasket 0.7716 ± 0.023 vs 0.826; rocker cover 0.7636 ± 0.009 vs 0.775) |
| 2.6 | Slide 4 (risk row); handbook pages 38 and 46 | "sensor drift is one of the eight classified faults" offered as the answer to "what if a sensor drifts?" | Lead with what works: range, rate and staleness checks at ingest, and the physics cross-check (one gauge moving while the related channels stay consistent with the twin points to the instrument, not the engine). Do not offer the classifier: sensor drift is its **weakest** class. | JUR-10; `data/models/tier3_report.json`, sensor_drift F1 0.303 (precision 0.34, recall 0.27) |
| 2.7 | Slides 2 and 3; handbook page 19 | "A calibrated probability" | "A failure probability with measured skill — Brier skill 0.38 at 25 h and 0.52 at 50 h — that is over-confident at the top: at 25 h, the 12 sorties it put at 100 % failed 75 % of the time." | JUR-11, ML-10; `data/benchmarks/survival.json` (reliability bin 0.9–1.0 at 25 h: n 12, predicted 1.00, observed 0.75) |
| 2.8 | Handbook page 45 | CatBoost "came out ahead on the horizons that carry a dispatch decision and was notably steadier across splits" | "CatBoost had the best Brier score at 25 and 50 hours and was steadier than the others at 50 h. At 25 h it was the *least* steady, and at 100 h scikit-learn was marginally ahead; the differences are inside the fold-to-fold spread." | JUR-12; `data/benchmarks/booster_comparison.json` (25 h AUC sd: CatBoost 0.033, scikit-learn 0.031, LightGBM 0.021; 50 h skill sd: CatBoost 0.029, scikit-learn 0.071) |
| 2.9 | Slide 3 ("RUL estimation with confidence interval", per the page-36 script); handbook pages 18, 24 and 42 | "The operator never sees a bare '340 hours'"; "never present it bare — always with a range and a confidence" | True for the physics estimate only. The learned network's estimate has no served interval. Say: "Remaining life is shown with the physics model's range; where the network's estimate is shown, it is labelled as having no calibrated range, and every plan is made on the conservative figure." That is what the console now displays. | JUR-03; `layer4_core/live.py` (network checkpoint saved without its conformal multiplier); console RUL card after the September fixes |

## 3. Numbers — use these, not the old ones

| Quantity | Old figure in circulation | Figure from the artifact | Source |
|---|---|---|---|
| Pipeline latency | "p50 25.8 ms / p95 42.3 ms", unlabelled | **p50 51.3 / p95 82.7 ms** with 3 connected clients; **p95 95.3 ms** pinned to one core. This is the twin's per-tick compute on an x86-64 PC, not sensor-to-screen and not an ARM edge computer. Budget 200 ms. | `data/models/latency_bench.json`, `latency_bench_1core.json` |
| RUL NASA score | 11.8 | **478.2** in the latest training log (target < 500). Re-evaluate the shipped checkpoint before quoting any RUL figure. | `data/training_logs/train_rul.log`; ML-06 |
| Fused detection | "precision 0.997, recall 0.931, false-positive rate 0.009" | That row was picked on the test set itself. `scripts/eval_fusion.py` now picks the combiner on validation engines and writes `data/models/fusion_report.json`; quote that file once it has been re-run. | ML-05 |
| Detection lead time | "all 15 failing test engines caught, median 382 flight hours before end of life" | Tier-2 statistical detector only, and 9 of the 15 engines were flagged **before their fault had started**, so the lead time is inflated. Quote only lead time measured from fault onset. | ML-04; `scripts/eval_tier2.py` |
| Health index MAE | 0.067 | **0.065** (residual model with smoothing) | `data/training_logs/eval_health.log`; ML-13 |
| NASA C-MAPSS vs state of the art | "1.09× to 1.36×" (single-seed, 25-epoch runs) | **1.11× to 1.14×** mean over three seeds at 200 epochs (FD001 1.12, FD002 1.12, FD003 1.14, FD004 1.11; single runs 1.05–1.19) | `data/benchmarks/results.jsonl` rows 18–29 |
| Test count | 508 | Count on the day: `pytest --collect-only -q` | JUR-13 |
| Deviations recorded | 170 | Count on the day in `docs/PRD_DEVIATIONS.md` | JUR-13 |
| Physics accuracy | "12 published anchors reproduced, worst error 1.6 %" | Those 12 points were used to tune the model, so they are calibration targets. Say instead: "altitude and temperature behaviour come from the Rotax Operator's Manual performance table; at 11 printed full-throttle points up to 23,000 ft the model is within 1.3 % on power and 2.4 % on fuel flow." Do not call it independent validation: the table is an input. Independent validation needs rig data. | PHY-01, PHY-02; `layer2_physics/tests/test_physics.py::test_full_throttle_matches_the_manufacturer_performance_table`; DEV-226 |

## 4. The sample post-flight report contradicts itself

Regenerate `ASTRA-Post-Flight-Report.pdf` after the fixes; the generator has
changed. The printed copy shows:

- a flight of "0.7 hours" against a clock window of 23:16 to 23:24 (8 minutes);
- a drift of "−298.65 °C per 100 h" fitted to a handful of points;
- the same 23.1 % failure probability at both 12 h and 25 h;
- faults marked "REACHED" beside subsystems rated EXCELLENT, with no logged event.

(JUR-01; REP-01, REP-03, REP-06 fixed in code.)

## 5. Quick hygiene

- Slide 1: **"Team ID-" is blank.**
- Slide 6: "Prototype Demo" and "Explanation video" have **no links**.
- Three near-identical deck files exist; the unnumbered one is newest
  (10:33 on 11 Sep, against 10:25 and 10:28). Decide which is submitted and
  remove the others.
- Slide 3 typos: "on-board Security", "Hot- weather", "UAV– ISR".

## 6. The backup slide the deck does not have (JUR-15)

Neither the deck nor the handbook covers:

- the technology readiness level, with justification;
- the certification path (CEMILAC, DO-178C);
- size, weight and power of the added sensors and the edge computer;
- telemetry bandwidth;
- integration with a TAPAS or Heron ground control station;
- cost in rupees;
- a phased plan of test-rig hours.

One backup slide answering these separates a software demonstration from a
defence proposal.

## 7. The line only ASTRA can say

"The engine we modelled is the engine of the Heron Mk II that India has
ordered, and every limit behind our verdicts is traced to its type certificate
and manuals."

The earlier version of this line quoted a cooling fault reaching thermal
health 0.62 with a 25-hour deadline while all 37 limit rules stayed silent.
Re-measure that scenario after the September fixes before quoting the numbers,
because the advisory and grounding logic have changed.
