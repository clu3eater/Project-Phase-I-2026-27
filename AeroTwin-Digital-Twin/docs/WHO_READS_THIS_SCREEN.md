# Who reads this screen, and what they need from it

**Status:** governs the console. Where this document and `PRD_Part4_Defence_HMI_Standard.md`
disagree about *what to show*, this one wins; Part 4 still governs *how to show it*
(colour, type size, flash rate, alert semantics).

---

## Why this document exists

The console was built correctly against a typography and colour standard, and
wrongly against the people who use it. Part 4 tells you a caution is amber and
16 px. It does not tell you that "measured against the as-new shadow model at
this operating point" is a sentence no UAV operator will ever read.

So this document starts from the three audiences the problem statement names,
and from one measurement.

---

## The measurement that started this

Twenty seconds of the live stream, **on a healthy engine, with no fault
injected**, reading the values the dashboard puts in its largest type:

| Quantity shown large on the dashboard | Range over 20 s | Swing | Frames changed |
|---|---|---|---|
| BSFC deterioration (`%`) | −4.52 → +6.88 | **11.40 points** | 39 / 40 |
| Mission success probability (`%`) | 56.79 → 86.52 | **29.73 points** | 36 / 40 |
| Remaining useful life (`h`) | 29.46 → 30.40 | 0.94 | 35 / 40 |
| Composite health index | 0.78 → 0.89 | 0.11 | 10 / 40 |
| Fusion score | 0.17 → 0.32 | 0.15 | 10 / 40 |

Nothing was wrong with the engine. Every one of those numbers is noise.

An operator watching mission success probability swing between 57 % and 87 %
twice a second does not learn that the mission is uncertain. They learn that
the number is worthless, and then they stop looking at the panel that carries
it — including on the day it is telling them something true.

This is the display equivalent of a **chattering alarm**, and alarm-management
practice has treated chattering as a defect to be eliminated, not tuned, for
thirty years.

### It is not a display bug. It is a category error.

RUL, health, efficiency and mission probability are **slow** quantities. They
describe how an engine is ageing over tens or hundreds of hours. Sampling them
at 2 Hz and printing the instantaneous value shows the sensor noise on a
*derived* quantity, amplified by every division in the derivation chain.

BSFC is fuel flow divided by shaft power. Both are noisy; the ratio is noisier
than either; the deterioration is that ratio divided by another ratio. Eleven
points of swing on a healthy engine is what that arithmetic produces, and no
amount of UI polish fixes it — the fix is upstream of the screen.

**PRD Part 2 §9.4 already requires the fix and it was never applied to the
display:**

> METHOD 1: Moving Average with Exponential Weighting
> `CHI_ema(t) = α × CHI(t) + (1-α) × CHI_ema(t-1)` where **α = 0.1 (slow
> response, filters noise)**. Trend direction: slope of CHI_ema over a
> **10-flight-hour window**.

Ten flight hours. Not half a second.

---

## The second defect: it explains instead of instructing

The dashboard's own text, measured:

| Field | Length | Text |
|---|---|---|
| `efficiency.reason` | 64 chars | "measured against the as-new shadow model at this operating point" |
| `maintenance.summary` | 129 chars | "2 action(s) indicated. Most urgent: Oil Change within 10 flight …" |
| `rul.reason` | 43 chars | "extrapolated from the observed health trend" |

Compare PRD Part 2 §9.5, which gives its own examples of what an alert should
say:

> "Oil pressure correlation degraded. **Schedule inspection within 10 flight hours.**"
> "CHT at 127 °C — **monitor closely, reduce power if trend continues**"
> "CHT CRITICAL at 137 °C! **Reduce power immediately!**"

Every one of those ends in an **instruction**. Every one of ours ends in a
**method note**.

The difference is who the sentence was written for. "Measured against the
as-new shadow model" is written for a reviewer assessing whether we did the
maths properly. It belongs in this repository, in the module docstring where it
already is. It does not belong on a crew station.

[ISA-18.2](https://www.yokogawa.com/us/library/resources/media-publications/implementing-alarm-management-per-the-ansi-isa-182-standard-control-engineering/)
defines an alarm as an abnormal condition **requiring a response**, and says
each one should carry priority, likely cause, and a **recommended response
procedure**. An indication with no response attached is not an alarm; it is
decoration that costs attention.

---

## The three audiences, and what each is actually deciding

The PS names three. PRD Part 3 §19.5 gives each a focus line, and those focus
lines are the whole specification — everything else follows from them.

### 1. UAV operator — *"Mission safety, immediate operational decisions"*

Sitting at a ground control station, mid-sortie, with other things to watch.
Not an engineer. Not a developer.

**The only questions they have:**
- Is the engine alright *right now*?
- If not, what do I do — and how long do I have to do it?
- Can I finish this sortie?

**What they need on screen:** a state word, the parameters against their
limits, and any alert with the action attached. Nothing else.

**What they must never be given:** a method note; a probability that moves
while they read it; a number with no limit beside it; a prediction without the
action it implies. An operator cannot act on "BSFC deterioration +1.1 %". They
can act on "coolant margin 12 °C — reduce power if it falls below 8".

**Update rate:** live parameters at the display rate. Everything derived —
health, RUL, efficiency, mission probability — **smoothed, and stated at the
resolution the underlying quantity actually supports.**

### 2. Propulsion engineer — *"Engine performance, degradation analysis, model validation"*

The one audience that genuinely wants the method note, the residual, the
covariance, the confidence interval and the shadow-model comparison. They are
validating a model, not flying an aircraft.

**Their questions:** Which subsystem is degrading, how fast, and does the
physics agree with the data? Is the model trustworthy here?

**What they need:** residuals against the as-new twin, per-subsystem indices,
degradation rates with intervals, the explainability decomposition, and the
scenario tools. Provenance and method **belong on their screens** — this is
where the sentences we wrote for a reviewer are correctly addressed.

### 3. Maintenance team — *"Preventive maintenance, repair execution"*

Not in the aircraft. Working to a schedule, a parts list and a budget.

**Their questions:** What must be done, by when, what does it need, and what
does it cost? Which engine is next?

**What they need:** the ordered action list with deadlines in **flight hours**,
parts, downtime and cost; the RUL as a planning horizon *with its interval*;
the history. A live 2 Hz telemetry stream is close to useless to them — their
unit of time is the next inspection, not the next half-second.

### 4. Commander (not named in the PS; PRD Part 3 §19.5 role 4)

*"Operational readiness, mission success probability."* Fleet-level. Which
airframes can fly what, and which are the constraint.

---

## What this means for the console, concretely

### R1 — Nothing derived is displayed raw

Health, RUL, efficiency and mission probability are EMA-smoothed (α = 0.1, per
PRD Part 2 §9.4) before they reach the display, and quantised to a step the
operator can read. A number that cannot hold still for five seconds does not go
on a dashboard at all.

### R2 — Display resolution matches real precision

BSFC deterioration that swings ±5 points on a healthy engine is not a one-
decimal quantity. It is reported to the nearest whole percent, or as a
direction (`steady` / `rising` / `falling`) when the swing exceeds the value.
An RUL with a ±120 h interval is not reported to 0.1 h.

### R3 — A deadband stops the last digit chattering

A displayed value updates only when it has moved by more than its display
resolution. This is the display counterpart of eliminating chattering alarms.

### R4 — Operator text is an instruction, never a method

Every string the operator sees answers *what do I do*. Method notes, model
provenance and residual arithmetic move to the engineer's screens, where they
are wanted. No operator-facing string exceeds roughly one line.

### R5 — Every number carries its limit

A temperature without its limit is a number. With its limit it is a margin,
which is a decision. Operators read margins.

### R6 — The screen is quiet when the engine is well

Already the rule (Part 4 §4.1.1a, MIL-STD-411F). It now extends to derived
values: a healthy engine shows a steady state word and still numbers, not five
quantities twitching.

---

## Alarm loading targets

Adopted from
[EEMUA 191 / ISA-18.2 benchmarking](https://process.honeywell.com/content/dam/process/en/documents/document-lists/doc_asm-consortium/white-papers/February%2028%202005%20-%20Acheiving%20Effective%20Alarm%20System%20Performance%20Benchmarking.pdf),
which are the numbers the process-control world converged on after decades of
measured operator loading:

| Metric | Target |
|---|---|
| Steady-state alarm rate | **< 1 per 10 minutes** per operator |
| Peak, first 10 min of an upset | **< 10** |
| Standing (uncleared) alarms | **< 10** |
| Chattering alarms | **zero** |
| Priority distribution | roughly 5 % high / 15 % medium / 80 % low |

These are testable, and should be tested against a full simulated sortie rather
than asserted.

---

## What this document does not change

The physics, the models, the detection tiers, the fusion, and every measured
figure in `PRD_DEVIATIONS.md` stand. Smoothing a value **for display** does not
alter what the model computed, and the engineer's screens continue to show the
unsmoothed quantity — because for the engineer, the noise is data.

The change is in deciding *which human is being addressed* by each number, and
saying only what that human can act on.
