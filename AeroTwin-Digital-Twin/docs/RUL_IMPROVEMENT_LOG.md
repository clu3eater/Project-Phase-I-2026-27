# RUL accuracy work — phased log

Every row here carries its dataset, split, seed and metric, so no claim in this
document can be read without knowing what produced it. Phases run one at a
time; each is measured against Phase 0 before the next begins.

**Rules this work is held to** — no leakage; `rul_hours`, `deg_*`, `chi_true`,
`thi_true`, `mhi_true`, `comb_hi_true`, `censored`, `engine_id` are never model
inputs; engine-grouped splits; no tuning against test; the original dataset is
never overwritten; one variable per experiment; no accuracy claim without a
measurement that demonstrates it.

---

## PHASE 0 — baseline

**Dataset** `data/synthetic` (original, 100 engines, unmodified).
**Split** engine-grouped, `features.stratified_engine_split` — test is 20
engines, 6,860 windows, **4,120 scoreable** after censored windows are excluded
from scoring (they are kept for training through the survival hinge).
**Seed** 0. **Command** `python scripts/train_rul.py --seed 0`.
**Model** `RulLstm`, 23 EXTENDED features, sequence length 30, stride 5,
20 epochs run (early stop, best epoch 5), val loss 0.7651.
**Target sigma** 138.7 h. **Horizon cap** 400 h.

### Estimator comparison, held-out engines

| Estimator | RMSE | MAE | MAPE | R² | NASA | late |
|---|---:|---:|---:|---:|---:|---:|
| LSTM (data-driven) | **113.9** | 84.1 | 0.47 | **+0.327** | 2,251.6 | 37 % |
| physics extrapolation | 162.5 | 124.4 | 0.78 | **−0.396** | 468,974.0 | 33 % |
| FUSED (§12.5) | 134.6 | 100.9 | 0.51 | +0.059 | 809.3 | 32 % |

Physics is scored on the **46 %** of windows where it is reportable at all, so
its row is not directly comparable to the other two on identical data. Its
R² of −0.396 means that on that subset it is worse than predicting the mean.

### Full metric set for the best estimator (LSTM)

| Metric | Baseline | Current target | Verdict |
|---|---:|---:|---|
| RMSE | 113.9 h | — | — |
| RMSE / σ | **0.821** | ≤ 0.710 | NOT MET |
| R² | +0.327 | — | — |
| alpha-lambda | **0.200** | ≥ 0.70 | NOT MET |
| relative accuracy | **0.481** | ≥ 0.82 | NOT MET |
| late fraction | 0.372 | < 0.35 | NOT MET |
| NASA score | 2,251.6 | < 500 | NOT MET |
| prognostic horizon | 0.0 h | reported only | — |
| convergence | 331.8 | reported only | — |
| interval coverage | 86.2 % | ≥ 80 % | MET |

### RMSE split by whether the label is informative

| Band | Windows | RMSE | Bias | late |
|---|---:|---:|---:|---:|
| below the cap (informative) | 2,410 | 118.5 | +31.5 | 0.64 |
| at the 400 h cap (constant) | 1,710 | 107.1 | −76.0 | 0.00 |
| all | 4,120 | 113.9 | −13.1 | 0.37 |

### Serving path — verified

- **`layer4_core/live.py:164`** constructs `rp.PhysicsRul(...)` and nothing else.
- **`live.py:466`** `rul = self.rul.update(trend["chi_ema"], flight_hours)`.
- **`live.py:490`** `source="physics" if rul.reportable else "none"` — hardcoded;
  there is no LSTM branch. The value reaches the twin state (`:532`), the
  alerting path (`:593`) and the API (`:700`, `:764`).
- **`rul_lstm.pt` is never loaded.** `train_rul.py:394` writes it;
  `rul_lstm`/`RulLstm` appears only in `scripts/train_rul.py`,
  `scripts/diagnose_rul.py`, `scripts/experiment_sortie_rul.py`,
  `scripts/benchmark_cmapss.py` and `layer3_ai/tests/test_rul.py`.
  **Zero references in `layer4_core/`, `layer5_viz/`, `fleet_server/`, `run.py`.**

**Consequence:** production serves the estimator measured at RMSE 162.5 and
R² −0.396, while the one measured at 113.9 and +0.327 is trained, saved and
discarded. On RMSE that is a **30 % gap in delivered accuracy**, and on the
NASA safety score the served estimator is worse by more than two orders of
magnitude (468,974 vs 2,252).

### Measured information ceiling (current dataset)

`python scripts/measure_rul_ceiling.py` → `data/benchmarks/rul_ceiling.json`.
RUL predicted from the simulator's **ground-truth internal state** (12 `deg_*`
channels + 4 true health indices), engine-grouped 5-fold, 3,807 sortie rows,
73 uncensored engines. No sensor-based model can beat this.

| | RMSE | rmse/σ | alpha-lambda | rel. accuracy |
|---|---:|---:|---:|---:|
| oracle | 105.7 | **0.765** | **0.356** | **0.583** |
| oracle + monotone | 98.1 | **0.710** | 0.356 | 0.582 |

**The current targets sit at or above this ceiling.** `alpha_lambda ≥ 0.70` is
about twice the oracle's 0.356; `relative_accuracy ≥ 0.82` exceeds 0.583;
`rmse_sigma_ratio ≤ 0.71` equals the oracle only *with* monotone
post-processing and perfect internal state. Targets are left unchanged pending
Phase B — if denser recording moves the ceiling, any number set now would be
wrong too.

### Instrumentation change made during Phase 0

`rul_metrics` was called at five sites without `t_h`, so the prognostics
metrics were silently omitted and the pipeline reported RMSE alone. The flight
hour of each window's last sample is now threaded through
(`scripts/train_rul.py`). This adds metrics; it does not touch features,
model, predictions or the dataset.

Three files were added before this phase began and are inert — imported and
called by nothing in the pipeline: `layer3_ai/sortie_features.py`,
`scripts/measure_rul_ceiling.py`, and `monotone_trajectory()` in
`layer3_ai/rul_physics.py`.

---

## PHASE A — model / pipeline

### A1 — serve the trained network (COMPLETE)

**Dataset** original, unmodified. **Split** engine-grouped, 15 held-out engines.
**Seed** 0. **Checkpoint** `data/models/rul_lstm.pt` from the Phase 0 run.
**Command** `python scripts/eval_rul_matched.py`.

#### Matched windows — the only comparable table

1,914 windows where BOTH estimators answer. sigma 138.8 h.

| Estimator | RMSE | rmse/sigma | R2 | alpha-lambda | RA | late | NASA |
|---|---:|---:|---:|---:|---:|---:|---:|
| LSTM (training path) | **109.8** | 0.799 | **+0.362** | **0.333** | 0.550 | 0.408 | 3,951 |
| LSTM (SERVING path) | **109.8** | 0.799 | **+0.362** | **0.333** | 0.556 | 0.408 | 3,888 |
| physics (capped, fair score) | 162.5 | 1.182 | -0.396 | 0.200 | 0.363 | 0.334 | 468,974 |
| physics (uncapped, AS SERVED) | 226.9 | 1.650 | **-1.723** | 0.133 | 0.301 | 0.477 | 5.9e11 |

Two physics rows because they answer different questions. `train_rul.py:210`
caps physics at 400 h for scoring, with a documented justification -- the target
is capped, so marking an uncapped prediction judges it on a quantity it was
never asked for. But `PhysicsRul` caps at TBO (1,200 h), so the UNCAPPED row is
what actually reached an operator before A1. Reporting only the capped figure
would flatter the estimator being replaced.

Full-coverage figures (each estimator on every window it answers, NOT
comparable across rows): LSTM 113.7 RMSE over 4,120 windows; physics reportable
on 46 % only.

#### What improved, against what was actually served

RMSE **-52 %** (226.9 -> 109.8). R2 **-1.723 -> +0.362**. alpha-lambda 0.133 ->
0.333. Relative accuracy 0.301 -> 0.556. NASA score improves by eight orders of
magnitude.

#### What got worse

**Late fraction 0.334 -> 0.408 against capped physics.** The network
over-predicts remaining life more often. Recorded as a regression rather than
buried: on the raw count it is one.

The NASA score, which exists precisely to penalise late predictions
asymmetrically (DEV-66), moves 468,974 -> 3,888 on the same windows -- so the
network is late more often and far less badly. Capped physics buys its lower
late-rate by being wrong in the safe direction almost everywhere, which is the
same property that makes its R2 negative.

#### Serving-path fidelity

**Train/serve agreement: RMSE 2.58 h between the two paths**, 2.4 % of the
estimate itself; the metric rows are identical to three decimals. Non-zero
because the serving path replays CONTINUOUSLY and crosses sortie boundaries,
while `features.build_sequences` never splices across one. On an aircraft the
twin runs continuously, so the serving behaviour is the correct one and the
training windowing is the approximation.

#### Serving path verified live

`{hours: 187.2, source: "lstm"}` in both the API payload and the twin's
`predicted.rul`. The network also answers EARLIER than physics: physics
returned None (60-sample warm-up plus an established trend) while the network
was already estimating.

**Limitation.** The estimate carries no interval. `train_rul.py` saves
`{model, features, rul_max, val_loss}` and not the conformal multiplier, so no
calibrated bound for the network exists and none was invented.
`RemainingLife.reportable` is therefore False for it, and PRD Part 4 s7.4a
forbids showing an operator a bare RUL number. Engineers and the API see the
value; operator display needs the calibration saved at training time, which is
outside A1.

#### Three defects found while building the serving path

| | Defect | Resolution |
|---|---|---|
| 1 | **Residual baselining absent from serving.** Training subtracts each engine's EARLY-LIFE residual median. The twin carries `Residual.mean_delta`, a RUNNING mean over the whole life -- as an engine degrades the mean follows it and `delta - mean_delta` tends to zero, cancelling the signal the model reads. | `ResidualBaseline` forms an early-life median and FREEZES it. |
| 2 | **Units mismatch.** The twin carries `injector_duty_pct` (~13.5); the training column `injector_duty` is a FRACTION (0.221-0.651, centre 0.35, scale 0.25). Unconverted it normalises to ~52 against a training range of ~0.3 and swamps the other twenty-two features. | `_pct_to_fraction` in the serving path. **`layer4_core/recorder.py` maps the same percent onto the same fraction column and is NOT fixed** -- out of A1 scope, needs its own change. |
| 3 | **Baseline froze only when EVERY channel had enough samples.** One permanently-absent transducer would leave an engine on a provisional baseline for its whole life. | Keyed on the best-observed channel; a channel with too little data simply gets no offset. |

#### Tests

15 new in `layer3_ai/tests/test_rul_serving.py`, all passing: checkpoint
loading; missing checkpoint degrades to physics without raising; **feature-order
mismatch refused rather than silently served**; serving order equals training
order; warm-up; bounded output; reset; baseline freeze; missing residuals;
single-vs-batch structured-residual parity; the units hazard; fallback; no
fabricated interval.

**Full fast suite: 589 passed, 0 failed, 1 skipped** (574 before A1).

#### Files

New: `layer3_ai/rul_serving.py`, `layer3_ai/tests/test_rul_serving.py`,
`scripts/eval_rul_matched.py`.
Modified: `layer4_core/live.py` (construction, `_serve_rul`, `_pct_to_fraction`,
snapshot payload), `layer4_core/twin_state.py` (source vocabulary extended;
`data`/`fused`/`physics` kept), `layer3_ai/features.py`
(+`structured_residuals_one`).

### SURVIVAL HEAD — P(fail within H hours)  (NEW, the accurate answer)

**Why this exists.** The point estimate is within ~5 % of its causal ceiling and
cannot be materially improved; see "The ceiling, and why" below. Reframed as the
question a dispatcher actually asks, the same features answer accurately.

**Dataset** original, unmodified. **Split** engine-grouped throughout. **Model**
`HistGradientBoostingClassifier`, one per horizon, isotonic calibration.
**Commands** `python scripts/train_survival.py --folds 6`.

#### Engine-grouped 6-fold over all 73 uncensored engines — the honest figures

| Horizon | AUC mean | sd | worst fold | Brier skill | sd |
|---|---:|---:|---:|---:|---:|
| 12 h | 0.932 | 0.026 | 0.881 | 0.141 | 0.126 |
| 25 h | 0.908 | 0.031 | 0.854 | 0.327 | 0.047 |
| **50 h** | **0.918** | **0.017** | **0.896** | **0.443** | 0.071 |
| **100 h** | **0.892** | **0.019** | **0.869** | **0.479** | 0.047 |
| 200 h | 0.825 | 0.045 | 0.748 | 0.339 | 0.097 |
| 400 h | 0.734 | 0.061 | 0.631 | 0.115 | 0.077 |

A single 20-engine split reported 0.954-0.964 at the near horizons; grouped CV
over all engines gives 0.908-0.932. **The single split was optimistic by up to
+0.05**, and the grouped figures are the ones any target or claim must use.

- **50 h and 100 h are the reliable pair** — tightest variance and best skill.
- **12 h has the best AUC and the least reliable PROBABILITY** (skill 0.141 +/-
  0.126): only 2.4 % of sorties are positive there, so each fold holds very few
  events. Good ranking, unstable calibration. Not a basis for a dispatch gate yet.
- **400 h is marginal** (skill 0.115 +/- 0.077, some folds near zero), which is
  the same far-horizon ceiling appearing honestly instead of hidden in an RMSE.

#### The seed sweep measured nothing, and that was checked rather than reported

Three seeds returned results identical to four decimal places.
`HistGradientBoostingClassifier` subsamples only for BINNING and only above
10,000 rows; at 2,109 it is fully deterministic and `random_state` does nothing
(verified directly). Reporting "sd 0.000" as stability would have been a claim
about the estimator when it was a fact about the library. The variance that
matters is WHICH ENGINES are held out, which is what `--folds` measures.

#### Calibration: the tail was over-confident, and the fix is partial

Calibrated on a single 20-engine validation set, the top bin at 50 h predicted
**1.000 and was observed at 0.872** — told "certain failure", an operator would
have been grounding a serviceable aircraft about one time in eight, and the
error is in the OVER-confident direction.

`SurvivalHead.fit_oof` calibrates on pooled OUT-OF-FOLD predictions across all
~80 train+val engines instead, never calibrating a model on rows it was fitted
to. Scored on the same held-out engines:

| | val-set calibration | out-of-fold |
|---|---:|---:|
| AUC @ 50 h | 0.954 | **0.967** |
| Brier skill @ 50 h | 0.475 | **0.521** |
| Brier skill @ 100 h | 0.377 | **0.471** |
| **max probability emitted** | **1.000** | **0.940** |
| top-bin gap @ 50 h | **-0.128** | **-0.040** |
| n-weighted ECE @ 50 h | **0.0142** | 0.0243 |

**Mixed, and reported as such.** Out-of-fold wins the Brier skill — a proper
scoring rule — at every horizon from 50 h up, and it never claims certainty.
Validation-set calibration wins the n-weighted ECE at the short horizons,
because ECE is dominated by the 0.0-0.1 bin holding ~75 % of the samples, where
both are already accurate.

**Recommendation: out-of-fold.** Brier skill is a proper scoring rule and ECE is
not; and the difference that matters operationally is at the confident end,
where a wrong "certain" grounds a serviceable aircraft. The remaining
+0.111 gap in the 0.4-0.5 bin is not yet resolved.

#### Leakage guard caught its own author

`_check_no_leakage` refused the first real run: `sortie` had been placed in
`sortie_features.AGE_COLUMNS`, and it is on `features.FORBIDDEN_EXACT` — an
index a model could memorise an engine by. `flight_hours` already carries engine
age, so it was removed with the reasoning recorded at the constant. A leak like
that does not fail loudly on its own; it produces an excellent AUC and a system
that cannot work on an aircraft.

#### Censored engines are excluded, not labelled negative

An engine that reached TBO without failing may have failed just after the record
ended, so "did it fail within H hours" is unknowable for it. Labelling those as
survivors would teach the model that survivors are healthy. Excluded from both
fitting and scoring: 2,109 train / 874 val / 824 test sorties usable of
3,988 / 1,426 / 1,372.

#### Files

New: `layer3_ai/rul_survival.py`, `layer3_ai/tests/test_rul_survival.py` (19
tests), `scripts/train_survival.py`.
Modified: `layer3_ai/sortie_features.py` (`sortie` removed from AGE_COLUMNS).

### A2-A6 — not started

## PHASE B — data / observability

### B1 — wear-out fleet generated and the ceiling measured on both

The simulator change (DEV-193..DEV-201) was written but had never been used:
`data/synthetic` was generated on 29 Aug, a week before `degradation.py`
changed, and carried no hazard-scheduled faults at all. Every RUL number in
this log up to here was measured on the old uniform-onset fleet.

`FAULT_BASE_HAZARD_PER_HOUR` also still held 0.002, a value the calibration
sweep never tested. Set to the measured 0.004 and the fleet regenerated into
`data/synthetic_hazard`, leaving the original untouched.

**The calibration held.** It is meant to fix the overall failure statistics so
the ONLY difference between the fleets is when a fault arrives relative to
condition:

| | uniform | wear-out |
|---|---:|---:|
| engines failed / censored | 73 / 27 | 75 / 25 |
| median fault onset | 212 h | 90 h |
| faults expressed | — | 116 of 123 |

**Ceiling, same script, same seed, 5-fold engine-grouped, oracle features**
(`scripts/measure_rul_ceiling.py --data ...`):

| | uniform | wear-out | change |
|---|---:|---:|---:|
| rmse/sigma (oracle) | 0.765 | **0.709** | -7.4 % |
| rmse/sigma (+monotone) | 0.710 | **0.640** | -9.9 % |
| alpha-lambda | 0.356 | **0.387** | +8.6 % |
| relative accuracy | 0.583 | **0.615** | +5.5 % |
| RMSE h (oracle) | 105.7 | **99.2** | -6.1 % |

Every metric moved the right way, so the change did what it was designed to:
condition now carries information about when a fault will arrive.

**What must not be claimed.** The model did not change. If the trained model
improves on this fleet, the honest statement is "RUL improved because the
simulator became more realistic", not "our model got better".

**And it is a 7-10 % move, not a step change.** A perfect model with perfect
internal state still scores 0.709 sigma — RMSE 99 h against a 140 h spread.
Point RUL stays hard here because severity, ramp and mode are still drawn at
random; only ONSET became condition-dependent. The survival head remains the
accurate answer to the question that matters.

**One measurement artefact worth recording.** The first uniform run took
5,897 s and the wear-out run 13 s — a 450x gap for the same computation, which
looked like a reason to distrust the comparison. It was CPU contention: the
uniform run shared the machine with the fleet generation. Re-run on an idle
machine it returns byte-identical numbers in 13 s
(`rul_ceiling_uniform_recheck.json`). Checked rather than assumed, because a
before/after where the "before" ran under different conditions is not a
comparison.

### B2 — retrain on the wear-out fleet

Same script, same seed, same architecture, only the fleet differs
(`train_rul.py --data`, results recorded with `--report`):

| metric | uniform | wear-out | change |
|---|---:|---:|---|
| alpha-lambda | 0.200 | **0.500** | **+150 %** |
| relative accuracy | 0.481 | **0.653** | +36 % |
| RMSE / sigma | 0.821 | **0.735** | -10 % |
| late fraction | 0.372 | 0.374 | unchanged |
| NASA score | 2,252 | **37,964** | **17x worse** |

Alpha-lambda is the metric that decides an airframe -- near the end of life, is
the estimate right -- and it more than doubled. Nothing in the model changed,
so the honest statement is that the simulator became more realistic, not that
the model got better.

**The NASA score is the finding that does not fit the story.** It is 17x worse
and twelve times above the top of the range DEV-103 measured across three seeds
(478 to 3,108). It is exponential in the error and penalises LATE predictions
asymmetrically, so one badly late window dominates it.

The late FRACTION is unchanged, 0.372 to 0.374. So the model is not late more
often -- when it is late it is late by much more. That is the dangerous
direction: a late RUL says there is more time than there is.

A plausible mechanism is that the wear-out fleet has a median fault onset of
90 h against the old 212 h, so an engine can fail early while the estimate is
still long, and the exponential does the rest. That is a hypothesis, not a
finding: it has not been traced to specific windows and should not be reported
as understood.

**So the fleet is not established as strictly better.** Three metrics improved
substantially and one worst-case measure degraded badly, and both belong in any
statement about this change.

## Benchmark work — closing the gap to published C-MAPSS results

Measured against the published best RMSE, our starting position was 22 % behind
on FD001, 9 % on FD003, and 36 % on each of FD002 and FD004. The two worst are
the SIX-REGIME subsets, which pointed at preprocessing rather than the model.

### Accepted: per-regime normalisation

The benchmark scaled every row together. On a six-regime subset the spread
BETWEEN operating conditions then dominates each channel and the degradation
signal survives as a small wobble on a much larger regime step. Replaced with
k-means over the three operating settings, six clusters, one scaler each,
fitted on TRAIN only.

| subset | global | regime | gap to best |
|---|---:|---:|---|
| FD002 | 17.77 | **17.13** | 1.36x -> 1.31x |
| FD004 | 19.05 | **17.27** | 1.36x -> 1.23x |

Verified on FD001, which has one regime: per-regime output is bit-identical to
global, max absolute difference 0.0. Now the default, because it is better on
the six-regime subsets and provably identical on the one-regime ones.

**The size is a quarter of what was reported.** The literature figures are mean
signed deltas of -4.39 and -7.40 across a factorial grid over subset, cap,
window, architecture and seed; ours are -0.65 and -1.78 in one cell of that
grid. Not a contradiction, but it does say the remaining gap is somewhere other
than where the research pointed first.

### Rejected: dropping regime-only channels

On both six-regime subsets all 24 channels clear the global zero-variance
filter, because variation BETWEEN regimes is enough to make a channel look
informative even when it is flat inside every regime. Five channels per subset
are flat within-regime -- they report the operating condition, not the engine.
Removing them looked obviously right. It is not:

| subset | regime | regime + drop 5 |
|---|---:|---:|
| FD002 | **17.13** | 17.52 |
| FD004 | **17.27** | 17.59 |

Worse on both. Kept in the code behind `--drop-const`, off, and recorded here
so the idea is not retried on the strength of how sensible it sounds.

**The first version of this test was a silent no-op.** It tested `scale`, which
has already had flat channels pinned to 1.0 so the division is safe, so nothing
was ever dropped. It was caught only because the run returned numbers
*identical* to the previous one — a change that alters nothing usually did not
run. The scaler now keeps the raw within-regime spread separately, and
`regime_only()` reads that.

### Accepted: early stopping on a held-out validation split

The benchmark trained a flat 25 epochs with no validation set and no stopping
rule. Added a UNIT-grouped validation split off train (never row-grouped:
windows from one engine overlap heavily, so a row split puts near-copies of the
same window on both sides and the score measures memorisation), early stopping
on validation RMSE, and restoration of the best epoch rather than the last.

**The framing was wrong.** This was queued as "train longer". Early stopping
chose epochs 8, 9 and 16 -- the model was OVER-trained at 25, not under-trained.

Three seeds each, mean and population spread:

| subset | 25 epochs | early stopping | vs published best |
|---|---:|---:|---|
| FD001 | 15.42 | **14.13 ± 0.66** | 1.22x -> 1.12x |
| FD002 | 17.77 | **14.70 ± 0.49** | 1.36x -> 1.12x |
| FD003 | 13.77 ± 0.95 | 14.52 ± 0.62 | 1.09x -> 1.14x |
| FD004 | 19.05 | **15.58 ± 0.31** | 1.36x -> 1.11x |

FD002 and FD004 gain 3.1 and 3.5, several times the spread. FD001 gains 1.3,
about twice it. FD003 loses 0.75, which is INSIDE it -- no change, not a
regression.

### The finding that reframes everything above: run-to-run spread is ~0.8

The same configuration on FD003, changing only the seed, returns 12.82, 13.89
and 14.72 -- a spread of 1.9 on a number we had been comparing to two decimal
places. Every single-seed comparison in this file below ~1.5 was reading noise.

Two claims made earlier do not survive it:

- FD002 regime vs global, -0.65, was reported as a real improvement. It is
  within one standard deviation. **Not established.**
- FD003 "got worse under early stopping", -0.97. Also within noise.
  **Withdrawn.**

FD004 regime vs global (-1.78) and the early-stopping gains (1.3 to 3.5) are
large enough to survive, but they were single-seed when first reported and
should not have been stated as firmly as they were.

Per-regime normalisation stays the default on the separate grounds that it is
bit-identical on one-regime subsets and theoretically motivated on six-regime
ones -- not because a 0.65 delta proved anything.

### Rejected: refit on all units after early stopping

Early stopping costs 15 % of the training units. Refitting from scratch on all
of them for the chosen number of epochs should recover that. On FD003 it gave
14.59 against 14.86 without -- inside the noise, and it doubles training time.
Kept behind `--refit`, off.

### Not started

Seed ensembling (averaging predictions rather than reporting the mean of
separate runs).

## The first evidence from a REAL engine

Every accuracy figure in this file above is measured on a fleet this project
generated. The problem statement permits that -- it asks for a simulator as a
deliverable and accepts "simulated or real engine datasets" -- but it means
none of those numbers say anything about a real engine. The only outside
benchmark was C-MAPSS, and C-MAPSS is a SIMULATED TURBOFAN: its fault modes are
HPC and fan degradation, and there are no cylinders in it.

**There is no MALE UAV piston engine dataset in existence publicly.** A survey
of 110 public degradation datasets across 43 applications contains no UAV
powerplant and no aero piston engine; "aircraft engine" appears five times and
every one is a turbofan.

NGAFID is the closest real thing: recorded flights from Cessna 172s, four
cylinders, with real unplanned maintenance events. Six of the eight parameters
the PS names are present and real. Vibration and injection timing are not
recorded, so nothing here exercises the order-analysis path.

### Protocol, taken from the paper rather than invented

Yang and Desell, AAAI 2022. Class 1 = flights BEFORE an unplanned maintenance
event, class 0 = after. The dataset ships five folds and they are used as
given. ROC-AUC and PR-AUC, not accuracy. Scored PER MAINTENANCE ISSUE -- an
easy thing to get wrong, since pooling all 36 issue types produces a number
comparable to nothing published.

### Result

| | ours | Conv-MHSA | Conv-LSTM baselines |
|---|---:|---:|---:|
| intake gasket, 4,310 flights | **0.772 ± 0.023** | 0.826 | 0.70 - 0.74 |
| rocker cover, 2,260 flights | **0.764 ± 0.009** | 0.775 | 0.70 - 0.74 |

Above the published deep-learning baselines on both. Within about one standard
deviation of the specialised transformer on rocker cover; clearly below it on
intake gasket.

Worth noting what produced that: 46 features -- level and spread per channel,
one row per flight -- against a convolutional transformer reading the full 1 Hz
series. The simple representation this project already uses is competitive with
purpose-built deep models on real data.

### What it does and does not establish

It tests the METHOD, not the shipped model. The weights trained on the Rotax
fleet are not used and could not be: different engine, different sensors,
different failure modes.

So the defensible sentence is "this approach works on real piston engines with
real faults, scored against published results on the published protocol". It is
NOT "our model is accurate on a MALE UAV engine", and no public data can
support that sentence for anyone.

## PHASE C — targets

_not started; current targets deliberately unchanged_
