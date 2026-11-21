# Product Requirements Document
## AI-Enabled Real-Time Digital Twin for Aero Piston Engines in MALE UAVs

**Problem Statement:** DRDO / IDEX PS 26054
**Document:** Solution definition and system architecture
**Scope:** The production system. Not a demonstrator, not a laboratory
prototype — the configuration intended for deployment in a defence-grade Ground
Control Station, on an engine test rig, and across a fleet.

---

## Table of contents

1. [The problem today](#1-the-problem-today)
2. [Root cause: the single technical gap](#2-root-cause-the-single-technical-gap)
3. [What we set out to build](#3-what-we-set-out-to-build)
4. [The core mechanism](#4-the-core-mechanism)
5. [System architecture](#5-system-architecture)
6. [Layer specifications](#6-layer-specifications)
7. [Monitored parameters](#7-monitored-parameters)
8. [Fault detection and prediction](#8-fault-detection-and-prediction)
9. [The AI/ML layer](#9-the-aiml-layer)
10. [Remaining Useful Life and uncertainty](#10-remaining-useful-life-and-uncertainty)
11. [Simulation and mission replay](#11-simulation-and-mission-replay)
12. [Visualization and HMI](#12-visualization-and-hmi)
13. [Security architecture](#13-security-architecture)
14. [Deployment configurations](#14-deployment-configurations)
15. [Non-functional requirements](#15-non-functional-requirements)
16. [Continuity of operation](#16-continuity-of-operation)
17. [Standards and compliance](#17-standards-and-compliance)
18. [Requirement traceability](#18-requirement-traceability)
19. [Innovation areas](#19-innovation-areas)
20. [Keyword glossary](#20-keyword-glossary)

---

## 1. The problem today

### 1.1 Operational context

Medium Altitude Long Endurance (MALE) UAVs fly long-duration Intelligence,
Surveillance and Reconnaissance (ISR) missions, communication relay, maritime
surveillance and strategic defence tasks. These are single-engine aircraft on
sorties measured in tens of hours, often over contested or featureless terrain
where diversion is not a free choice.

Propulsion reliability is therefore not one system concern among many. A piston
engine failure in flight leads directly to one of three outcomes, all bad:

- **Mission abort** — the sortie is lost, and with it the intelligence it was
  flown to collect.
- **Asset loss** — the airframe does not come home.
- **Unsafe recovery** — a forced landing at an unplanned site.

### 1.2 What existing monitoring does

Conventional engine monitoring on UAVs is **threshold-based and reactive**.
Each sensor reading is compared against a fixed limit taken from the engine's
type certificate. If the reading is inside the limit, the system is silent. If
it crosses, the system raises an alarm.

It is a sound safety backstop, and it leaves three capabilities unaddressed:

| Gap | Consequence |
|---|---|
| Failures are indicated **only after the abnormality has already occurred** | The alarm is a report of damage, not a warning of it |
| **No Remaining Useful Life estimate** | Maintenance cannot be planned; parts are replaced on a calendar |
| **No degradation trend, no mission-wise simulation** | Nobody can answer "will this engine complete a 20-hour sortie at 6,000 m in 45 °C?" |

### 1.3 The maintenance consequence

Because condition is unknown, maintenance is **scheduled**: components are
replaced at fixed flight-hour intervals regardless of their actual state. A
fixed interval is necessarily a compromise between two different engines:

```
      SCHEDULED MAINTENANCE — two failure modes, same cause

      component condition
        100% |
             |  *.                        engine A: still healthy
             |    '*..                    at the replacement interval
             |        '*...               -> serviceable part scrapped
             |             '*...          -> cost and downtime for nothing
             |                  '*..
             |                      '*
             |
             |  *,                        engine B: degrading fast
             |    ',                      -> fails BEFORE the interval
             |      ',                    -> in-flight failure
             |        ',                  -> the exact event the schedule
             |          'x  FAILURE          was meant to prevent
             +--------------|---------------------> flight hours
                            ^
                     replacement interval
                     (the same for both engines)
```

A fixed interval treats engine A and engine B identically, because it is set
from a population average rather than from either engine. Condition-based
maintenance addresses both cases with one measurement.

---

## 2. Root cause: the single technical gap

Every gap in Section 1 has one technical cause. Stating it precisely is what
makes the solution follow.

> **A single sensor reading confounds two independent variables: what the
> operator is doing, and what condition the engine is in.**

Cylinder Head Temperature (CHT) rises when the throttle is opened. It also
rises when the cooling system silts up. A limit check sees one number and has
no way to attribute it.

```
    WHAT ONE READING CANNOT SEPARATE

    CHT = 112 degC
         |
         +----- caused by high power demand?        (normal)
         |
         +----- caused by degraded cooling?         (a fault)
         |
         +----- caused by high outside air temp?    (normal)
         |
         +----- caused by a drifting sensor?        (an instrument fault)

    A fixed limit answers none of these. It can only wait until the
    number crosses 135 degC, and by then the cause no longer matters.
```

Because the limit cannot attribute the reading, it must be set at the
worst-case value that is genuinely unsafe. That single design decision produces
every symptom in Section 1.2:

- The limit is far above the healthy operating point, so **degradation is
  invisible** until it is severe.
- With no measure of degradation, there is **nothing to extrapolate**, so no
  RUL.
- With no model of expected behaviour, there is **nothing to simulate**
  against, so no mission-wise prediction.

The three gaps are not three problems. They are one problem seen from three
directions, and it is solved by removing the confound.

---

## 3. What we set out to build

An **indigenous digital twin framework** that maintains a continuously
synchronised virtual representation of the physical engine, and uses it to move
engine management from reactive threshold alarms to predictive,
condition-based decisions.

### 3.1 Design principles

These govern every decision in the rest of this document.

| # | Principle | Rationale |
|---|---|---|
| P1 | **Measure condition against a reference, not a limit** | Removes the operator's actions from the measurement |
| P2 | **Physics first, learning second** | A model grounded in thermodynamics can be validated against published engine data; a purely learned model cannot |
| P3 | **The aircraft must not depend on the ground** | A denied datalink is an operational norm, not an exception |
| P4 | **Never display a value the system cannot justify** | An invalid reading is removed, never estimated or substituted |
| P5 | **Publish every prediction with its confidence interval** | An interval is what lets a maintenance planner act on the figure; a bare number cannot be planned against |
| P6 | **Every alert carries a recommended response** | An alert an operator cannot act on trains them to ignore alerts |
| P7 | **Explainability is a certification requirement, not a feature** | An unexplainable model will not be accepted for airworthiness |
| P8 | **Indigenous and auditable** | The claim must be checkable, not asserted |

### 3.2 System boundary

**In scope.** Engine health estimation, fault detection and attribution,
degradation tracking, remaining life prediction, mission reliability
assessment, environmental and mission simulation, post-flight analysis and
replay, and the operator, engineer and maintainer interfaces.

**System boundary.** The system is **advisory by design**. It observes,
predicts and recommends; command authority stays with the crew and the FADEC.
Flight control, navigation, payload management and airframe structural
monitoring are handled by their own systems, with which this one integrates
rather than overlaps.

This boundary is a deliberate engineering advantage. A system with no control
authority carries a substantially shorter certification path, integrates into an
existing Ground Control Station without disturbing flight-critical software, and
can be fielded and upgraded on its own schedule.

---

## 4. The core mechanism

### 4.1 The as-new reference

Run a second engine model in parallel with the real one. Drive it with the
**same operating point** — throttle position, altitude, airspeed, outside air
temperature — at the same instant. Hold it permanently at factory condition.

It answers exactly one question: *what should this engine be reading right now,
if it were new?*

Subtract that prediction from the measurement. The operator's actions moved
both numbers identically, so they cancel. **What remains is condition, and only
condition.** This quantity is the **residual**.

```
                    OPERATING POINT
        throttle | altitude | airspeed | outside air temperature
                             |
              +--------------+--------------+
              |                             |
              v                             v
   +----------------------+      +----------------------+
   |   PHYSICAL ENGINE    |      |  AS-NEW SHADOW MODEL |
   |   in service, aged   |      |  factory condition   |
   |                      |      |  same operating point|
   |   MEASURED value     |      |  PREDICTED value     |
   +----------------------+      +----------------------+
              |                             |
              +--------------+--------------+
                             v
                  +---------------------+
                  |      RESIDUAL       |
                  | measured - predicted|
                  +---------------------+
                             |
              +--------------+--------------+
              |                             |
              v                             v
   the operator's actions          degradation is visible
   moved BOTH models,              from the first hours,
   so they cancel out              far below any limit
```

### 4.2 Why one mechanism answers six requirements

The residual is not a feature. It is the substrate the rest of the system is
built on, and it is why a physics-based twin is the correct architecture here
rather than a purely data-driven one.

| Requirement | How the residual provides it |
|---|---|
| Health indices per sub-system | Each sub-system scored by how far its residuals sit from zero |
| Predictive rather than threshold diagnostics | A residual grows continuously; a threshold fires once |
| Sensor fault vs engine fault | An instrument disagreeing with physics is faulty; an engine agreeing with a worn model is worn |
| Remaining Useful Life | Extrapolate the trend in the residual, not in the raw reading |
| Degradation trend analysis | The raw reading trends with the mission profile; the residual trends only with condition |
| Mission and environment simulation | The same validated model runs forward under any altitude, temperature or throttle profile |

### 4.3 Detection before limit exceedance

```
   condition
      100% +===========
           |           =====                TRUE ENGINE CONDITION
           |                ======          (falls continuously)
           |                      ======
           |  [//////// PREDICTIVE WINDOW ////////]     ======
   limit   + - - - - - - - - - - - - - - - - - - - - - - - - -\- -
           |                                                FAILURE
           +--------------------------------------------------------> hours
           ^                                                  ^
    residual departs zero                          threshold monitor
    -> our first indication                        -> its first indication

   The shaded span is the interval in which maintenance is still a
   planning decision rather than an emergency. Conventional monitoring
   reports nothing inside it.
```

---

## 5. System architecture

### 5.1 Layered view

Five layers. The numbering is build order; the vertical position is signal
flow, which is why Layer 1 sits above Layer 2.

```
+==================================================================+
| LAYER 5   VISUALIZATION AND HMI                    (GCS)         |
|                                                                  |
|  Operator console - role-filtered - MIL-STD-1472H / 411F         |
|  Health status | Fault alerts | Efficiency trends |              |
|  Maintenance advisory | Mission-wise reports | Replay            |
+==================================================================+
        ^  state snapshot, 2 Hz          |  acknowledge, inject,
        |                                v  scenario, export
+==================================================================+
| LAYER 4   DIGITAL TWIN CORE                        (GCS)         |
|                                                                  |
|  Twin state: Reported | Desired | Predicted | Simulated          |
|  As-new shadow model - operating-point synchronisation           |
|  Mission reliability - flight record - replay store              |
|  REST + WebSocket API - role-based access control                |
+==================================================================+
        ^  residuals, health, life       |  operating point
        |                                v
+==================================================================+
| LAYER 3   AI AND ANALYTICS                    (edge + GCS)       |
|                                                                  |
|  Tier 1 rules | Tier 2 statistical | Tier 3 deep sequence        |
|  Score fusion - health indices - fault attribution               |
|  Remaining Useful Life with calibrated interval                  |
+==================================================================+
        ^  validated channels            |
        |                                v
+==================================================================+
| LAYER 1   EDGE ACQUISITION                    (ON THE AIRCRAFT)  |
|                                                                  |
|  CANaerospace decode - ECU / FADEC interface                     |
|  Value-state validation - onboard rule engine                    |
|  Lightweight inference - 72 h store-and-forward buffer           |
|  Authenticated telemetry uplink                                  |
+==================================================================+
        ^  CAN frames                    |
        |                                v
+==================================================================+
| LAYER 2   ENGINE AND PHYSICS MODEL                               |
|                                                                  |
|  Mean-value thermodynamic engine model                           |
|  Engine performance maps - turbocharger and intercooler          |
|  Two-node thermal model - degradation pathways                   |
|  Reference engine: Rotax 915 iS / iSc A, EASA TCDS E.121         |
+==================================================================+
```

### 5.2 Processing sequence

Nine stages. Stages 1–5 execute on the aircraft; 6–9 at the ground station.

```
  RUNS ON THE AIRCRAFT
  --------------------
  1  ACQUIRE      Engine CAN bus / FADEC interface, fixed rate
        |         Every channel decoded and timestamped
        v
  2  VALIDATE     Each value assigned a state:
        |         VALID | STALE | INVALID | OUT-OF-RANGE | ABSENT
        |         Invalid values are REMOVED, never substituted
        v
  3  COMPARE      Shadow model predicts the same operating point
        |         residual = measured - predicted, per channel
        v
  4  DETECT       Three independent methods, run in parallel
        |         Tier 1 rules always available, even link-down
        v
  5  BUFFER       72 h store-and-forward; authenticated uplink
        |
  ==========================  encrypted, authenticated  ==========
        |
  AT THE GROUND STATION
  ---------------------
  6  ATTRIBUTE    Which of the eight fault modes, and how severe
        |
        v
  7  PREDICT      Remaining Useful Life WITH a calibrated interval,
        |         or an explicit refusal carrying its reason
        v
  8  DECIDE       Mission reliability: Go / Go-with-limits / No-Go
        |         Maintenance advisory with deadline
        v
  9  RECORD       Work order with ATA chapter reference,
                  post-flight report, tamper-evident audit log,
                  full mission replay
```

The system ends at a **work order**, not at a dashboard. That is the difference
between a monitoring display and an operational system.

### 5.3 Module structure

Modular by design, so a sub-system can be replaced without disturbing the
others — the PS requirement for "modular architecture for future scalability".

```
layer1_edge/       CAN encode/decode, value states, rule engine,
                   edge inference, secure link, offline buffer

layer2_physics/    Mean-value engine model, combustion, turbocharger,
                   thermal network, degradation pathways, data generation

layer3_ai/         Feature contract, three detection tiers, fusion,
                   health indices, RUL (physics + learned), advisory,
                   efficiency, battery, explanation

layer4_core/       Twin state model, shadow model, live pipeline,
                   mission reliability, flight record, reports,
                   scenarios, test rig, fleet, replay, API, security

layer5_viz/        Operator console

common/            Configuration, units, shared contracts
configs/           Engine data, thresholds, limits — all external
```

**No engine limit, threshold or tuning constant is hard-coded.** All reside in
configuration, sourced from the type certificate and the manufacturer's
manuals. Re-targeting the framework to a different engine is a configuration
exercise, not a code change.

---

## 6. Layer specifications

### 6.1 Layer 1 — Edge acquisition

**Location:** on the aircraft, on computing already carried by the airframe.

| Function | Specification |
|---|---|
| Bus interface | CAN bus via SocketCAN; CANaerospace application layer; ECU / FADEC interface |
| Channel count | 46 signals covering all PS-listed parameters plus derived quantities |
| Value states | Every channel carries one of five states, propagated end to end |
| Rule engine | Fixed-limit and rate-of-change rules from the type certificate; executes locally with no ground dependency |
| Edge inference | Compiled inference graph; the training framework is absent from the flight image |
| Offline operation | 72-hour store-and-forward buffer; reconciliation on reconnection |
| Uplink | Authenticated, sequence-numbered, replay-rejecting telemetry |

**Why the edge tier exists.** Principle P3. A MALE UAV over contested airspace
may lose its link for hours. Detection that only works when the link is up is
detection that fails at exactly the moment it is needed.

### 6.2 Layer 2 — Engine and physics model

**Reference engine:** Rotax 915 iS / iSc A, EASA Type Certificate Data Sheet
E.121. Selected because it is turbocharged, fuel-injected and FADEC-equipped
with a CAN interface — a carburetted engine cannot satisfy the PS requirements
for CAN acquisition and ECU/FADEC interfacing.

**Model composition:**

- Mean-value engine model — cylinder-averaged thermodynamic states
- Combustion chemistry with realistic species and flame properties
- Turbocharger and intercooler, including critical-altitude behaviour
- Two-node thermal network — cylinder head and coolant, separately tracked
- Engine performance maps across the operating envelope
- Degradation pathways: fouling, cooling loss, bearing wear, injector
  degradation, ignition degradation, instrument drift

**Validation basis.** The model is anchored to the manufacturer's published
performance data — torque, power, fuel consumption and thermal behaviour at
declared operating points — *before* any learning component is trained against
it. A model that does not reproduce published engine behaviour is not a
reference; it is an assumption.

**Two uses, one model:**

1. **The shadow model** — held at factory condition, driven by the live
   operating point, producing the as-new prediction of Section 4.
2. **The simulation engine** — driven forward under arbitrary mission and
   environmental profiles for the PS-required scenario work.

### 6.3 Layer 3 — AI and analytics

Detailed in [Section 9](#9-the-aiml-layer).

### 6.4 Layer 4 — Digital twin core

The central intelligence layer. Maintains four synchronised state views:

| View | Meaning |
|---|---|
| **Reported** | What the physical engine currently reports |
| **Desired** | Commanded or intended state |
| **Predicted** | What the as-new model expects at this operating point |
| **Simulated** | What a projected mission or environment would produce |

Also owns: operating-point synchronisation, mission reliability assessment, the
flight record, report generation, scenario execution, the fleet view, replay,
the API surface, and access control.

### 6.5 Layer 5 — Visualization and HMI

Detailed in [Section 12](#12-visualization-and-hmi).

---

## 7. Monitored parameters

All eight parameter groups named in the problem statement, with what each
reveals and its degradation signature.

| # | Parameter | What it indicates | Degradation signature |
|---|---|---|---|
| 1 | **RPM** | Engine speed; the reference for nearly every other quantity | Instability, hunting, imbalance between banks |
| 2 | **Cylinder Head Temperature (CHT)** | Heat rejection from the cylinder head | Rising residual against as-new at matched operating point |
| 3 | **Exhaust Gas Temperature (EGT)** | Combustion completeness and timing | Rising mean; widening spread between cylinders |
| 4 | **Oil pressure** | Bearing and lubrication system health | Falling residual, particularly at low speed |
| 5 | **Oil temperature** | Heat rejection through the oil circuit | Rising residual; divergence from coolant temperature |
| 6 | **Fuel flow** | Delivery and combustion efficiency | Rising specific consumption at matched power |
| 7 | **Vibration signature** | Mechanical condition of rotating assembly | Peak growth at characteristic orders |
| 8 | **Battery / alternator health** | Electrical generation and storage | Voltage sag under load; charge acceptance decline |
| 9 | **Injection timing** | Fuel system and ECU behaviour | Timing deviation from commanded value |

Each is monitored in **three forms simultaneously**: the raw value, its value
state, and its residual against the as-new model. The residual is the
diagnostic quantity; the raw value is what the operator reads.

---

## 8. Fault detection and prediction

### 8.1 The eight fault modes

All eight named in the problem statement, each mapped to the physical indicator
that reveals it and the maintenance action it drives.

| # | Fault mode | Physical indicator | ATA area | Action |
|---|---|---|---|---|
| 1 | **Misfire** | Cylinder-to-cylinder imbalance; cyclic variability | 74 Ignition | Inspect ignition system |
| 2 | **Injector abnormality** | EGT spread between cylinders; fuel flow residual | 73 Fuel and control | Inspect and test injector |
| 3 | **Cooling degradation** | CHT and coolant residual at matched operating point | 75 Engine cooling | Coolant system inspection |
| 4 | **Lubrication issue** | Oil pressure and temperature residual | 79 Oil | Oil system inspection |
| 5 | **Sensor drift / failure** | Disagreement between instrument and physics model | 77 Engine indicating | Instrument check, not engine work |
| 6 | **Combustion instability** | Cyclic variability of indicated pressure | 73 Fuel and control | Fuel quality and injection check |
| 7 | **Overheating trend** | CHT rate of change; sustained residual growth | 75 Engine cooling | Power reduction, then inspection |
| 8 | **Abnormal vibration** | Vibration peak ratio at characteristic orders | 85 Engine (reciprocating) | Bearing and mounting inspection |

Chapter numbers follow the FAA Joint Aircraft System/Component code table
(JASC, derived from ATA Spec 100): 85 is "Engine (Reciprocating)", 7520 "Engine
Cooling System", 8120 "Exhaust Turbocharger". Chapter 72 in that table is the
turbine engine and does not apply to the 915 iS.

### 8.2 Separating instrument faults from engine faults

Fault 5 deserves separate treatment because getting it wrong is expensive in
both directions: an instrument fault dispatched as an engine fault wastes a
teardown, and an engine fault dismissed as an instrument fault flies again.

The discriminator is the physics model:

```
   A reading has moved away from expectation.

        Does the rest of the engine agree with it?

        YES ------------------------> the ENGINE has changed
        (other channels show the        -> engine fault
         same physical story)

        NO -------------------------> the INSTRUMENT has changed
        (this channel alone             -> instrument fault
         disagrees with physics)        -> engine is serviceable
```

A threshold monitor cannot make this distinction at all, because it has no
model of what the reading ought to be.

### 8.3 Channel confidence and detection weighting

The system knows how much diagnostic authority each channel carries, and
weights its decisions accordingly. This is what allows detection to be both
sensitive and precise at the same time.

Each channel is characterised by its **signal-to-noise ratio** — how far a
fault signature rises above the model's own prediction accuracy on that
channel. Channels are graded, and the grading feeds the fusion stage directly:

| Grade | Meaning | Use in detection |
|---|---|---|
| **Primary** | Fault signature is large relative to model accuracy | Drives detection and attribution |
| **Supporting** | Signature is present and usable alongside others | Corroborates a primary channel; strengthens confidence |
| **Reference** | Channel defines the operating point the model is driven from | Establishes the comparison basis for every other channel |

Grading each channel rather than treating all of them alike is a measurable
engineering advantage: a fault is confirmed from the channels that carry real
information about it, so genuine detections are reached faster and nuisance
alerts from low-authority channels are suppressed. The grading is derived from
the physics model and is published with the system, so an assessor can see
exactly which evidence supports each detection.

---

## 9. The AI/ML layer

### 9.1 Three independent tiers

Three methods of different kind, running in parallel. Diversity is the point:
methods that fail in the same way provide no redundancy.

```
   TIER 1                 TIER 2                 TIER 3
   RULE-BASED             STATISTICAL            DEEP SEQUENCE
   +----------------+    +----------------+    +----------------+
   | Certified      |    | Residual       |    | Sequence model |
   | limits and     |    | features over  |    | over multi-    |
   | rate-of-change |    | time windows   |    | channel history|
   +----------------+    +----------------+    +----------------+
   | Deterministic  |    | Change-point   |    | Multi-label    |
   | Explainable    |    | and outlier    |    | fault head +   |
   | by construction|    | detection      |    | severity       |
   +----------------+    +----------------+    +----------------+
   | Runs on the    |    | Detects slow   |    | Detects        |
   | AIRCRAFT       |    | drift a rule   |    | multi-channel  |
   | Never offline  |    | rules miss     |    | patterns       |
   +----------------+    +----------------+    +----------------+
           \                     |                     /
            \                    |                    /
             v                   v                   v
        +----------------------------------------------+
        |                SCORE FUSION                  |
        |  independent evidence combined;              |
        |  agreement required before escalation        |
        +----------------------------------------------+
                              |
                              v
        +----------------------------------------------+
        |  NORMAL -> ADVISORY -> CAUTION -> WARNING    |
        |  every level carries a recommended response  |
        +----------------------------------------------+
```

### 9.2 Why fusion rather than a single model

Requiring independent agreement before escalation is the primary defence
against false alarms, and false alarms are the failure mode that destroys an
operational monitoring system permanently. An operator who learns that alerts
are unreliable stops reading them, and the system's detection performance
becomes irrelevant.

Fusion also preserves the **certification argument**. Tier 1 is deterministic
and explainable by construction. It runs on the aircraft, always, independent
of the learned tiers. Whatever the learned components do or fail to do, the
certified limits are still enforced by a mechanism an assessor can read line by
line.

### 9.3 Physics-informed learning

The learned components do not regress raw sensor values. They are constrained
by the physics in two ways:

1. **The physics prediction is an input**, not something the network must
   rediscover. The network learns the *correction* to physics, not the physics.
2. **Thermodynamic constraints enter the training objective.** The model is
   penalised for producing states that violate the relationships it is meant to
   obey — for example, predicting that cylinder head temperature falls as
   throttle opens, or as outside air temperature rises.

The second point is an airworthiness argument, not an accuracy argument. An
unconstrained network can output a physically impossible claim. That is not a
small error to be tuned away; it is a class of behaviour that a certification
authority cannot accept from a system informing maintenance decisions.

### 9.4 Explainability

Every alert resolves to:

- the **physical quantity** that moved,
- the **direction and magnitude** of its departure from as-new,
- the **sub-system** affected,
- the **ATA chapter** for the maintenance manual,
- the **recommended response**.

Explanation is generated from the same quantities that produced the detection,
not from a separate post-hoc attribution model. The explanation and the
decision cannot disagree, because they are the same computation.

### 9.5 Federated fleet learning

Models improve across a fleet without operationally sensitive telemetry leaving
any airframe.

```
   AIRCRAFT 1        AIRCRAFT 2        AIRCRAFT 3        AIRCRAFT n
   local model       local model       local model       local model
   local data        local data        local data        local data
        |                 |                 |                 |
        |  model updates only -- never raw telemetry           |
        +--------+--------+--------+--------+-----------------+
                          |
                          v
              +-------------------------+
              |   FLEET AGGREGATION     |
              |  robust averaging with  |
              |  outlier rejection      |
              |  privacy noise added    |
              +-------------------------+
                          |
                  improved model distributed back
```

Two properties matter operationally: sortie telemetry never crosses an
organisational boundary, and a single corrupted or compromised contributor
cannot dominate the aggregate.

---

## 10. Remaining Useful Life and uncertainty

### 10.1 Two independent estimators

| Estimator | Basis | What it contributes | Available from |
|---|---|---|---|
| **Physics extrapolation** | Projects the observed degradation trend forward through the validated engine model | Fully explainable; traceable to physical quantities; needs no training history | The first sortie |
| **Learned sequence model** | Trained on complete degradation histories | Captures non-linear late-life acceleration that a linear projection would miss | Once fleet history is available |

The two are deliberately complementary. The physics estimator gives the system
a working life prediction from day one and an explanation an assessor can
follow; the learned estimator adds sensitivity to late-life behaviour. Together
they cover the whole service life of the engine and the whole deployment life
of the system.

### 10.2 Combination with a disagreement gate

The estimates are combined by confidence weighting. Where the two disagree
substantially, the system reports the **more conservative** figure rather than
their average.

This is a deliberate safety trade. Averaging two estimates that disagree
produces a number neither estimator supports, and in life prediction the error
is asymmetric: **over-stating remaining life reads as permission to fly.**
Under-stating it costs an early inspection. The gate resolves disagreement in
the direction where being wrong is cheaper.

### 10.3 Calibrated intervals and confidence-gated reporting

Every life estimate is published as an interval with a stated confidence level,
produced by a distribution-free calibration procedure — the interval carries a
coverage guarantee that does not depend on the error distribution being of any
particular shape.

Reporting is **gated on evidence**. A life figure is published once the
supporting evidence meets the standard the interval is calibrated against. Until
then the system reports its current status — for example that it is still
establishing the degradation trend on a new engine — so the operator always
knows precisely what the system knows.

```
   EVIDENCE GATE

   Is a degradation trend established?
        not yet -> status: "establishing degradation trend"
                   -> tells the operator condition monitoring is
                      healthy and the engine has not yet degraded

        yes     -> is the engine inside the validated envelope?
                     no  -> status: "outside validated envelope"
                            -> raw readings and Tier 1 limits remain live
                     yes -> PUBLISH estimate WITH interval and confidence
```

Principle P5. Gating on evidence is what makes the published figure
trustworthy: every number the system reports is one it can support, so an
operator can act on it directly. The status messages carry real operational
information of their own — "establishing degradation trend" tells a maintainer
that the engine is behaving as a healthy engine should.

---

## 11. Simulation and mission replay

### 11.1 Mission and environment simulation

The validated physics model is run forward under specified conditions, using
the **current degradation state of the actual engine** rather than a generic
one. The question answered is not "how does this engine type behave at
altitude" but "how will *this* engine, in *its* present condition, behave on
*this* sortie".

All four PS-named scenarios are first-class:

| Scenario | What it exercises |
|---|---|
| **High altitude** | Turbocharger critical altitude; power lapse; cooling authority in thin air |
| **Endurance mission** | Cumulative thermal soak; oil condition; fuel consumption over long duration |
| **Hot-weather operation** | Reduced cooling margin; density altitude effects |
| **Rapid throttle transitions** | Thermal transients and mechanical loading during rapid power changes |

Environmental parameters are settable across the full operational envelope, so
mission profiles beyond the four named cases can be constructed.

### 11.2 Mission reliability assessment

The simulation output becomes an operational recommendation:

```
   Proposed mission profile + current engine condition
                        |
                        v
        Simulate the sortie through the engine model
                        |
        +---------------+---------------+
        |               |               |
        v               v               v
      GO         GO WITH LIMITS       NO-GO
   no constraint  constraint named   reason named
                  (e.g. altitude,    and the limiting
                   duration, power)  sub-system given
```

A No-Go without a reason is an obstruction. The limiting sub-system is always
named, and where a constrained profile would be acceptable, that alternative is
offered rather than withheld.

### 11.3 Post-flight analysis and replay

Two distinct products.

**The flight record**, accumulated in flight and not reconstructible afterwards
from a snapshot:

- **Events** — each alert opened when it appears and closed when it clears, tagged
  with flight phase and ATA chapter, so a transient has a *duration* rather than
  vanishing
- **Exceedances** — peak value, amount over limit, and **time above limit**, since
  maintenance manuals set inspection thresholds on both
- **Stabilised cruise datum** — one reading per flight taken at a repeatable
  condition, which is what makes trending between flights valid
- **Life-to-date extremes**, explicitly distinguished from this sortie's values

**Mission replay** — the full recorded sortie replayed through the analytics at
controllable speed, so an engineer can see exactly what the system saw and when
it saw it.

### 11.4 Why the stabilised cruise datum matters

Trending requires that successive measurements be comparable. A peak value
depends on how hard the aircraft was flown; a value sampled at export time
depends on when somebody pressed the button. Neither trends against anything.

One reading, taken at a stabilised condition, once per flight, is the standard
practice for engine condition trend monitoring, and it is what makes a
flight-to-flight comparison meaningful. Where a sortie never stabilises, the
report states that no valid reading was obtained — a finding about the sortie,
not a gap to be filled with something else.

---

## 12. Visualization and HMI

### 12.1 Roles

Four roles. The distinction is not cosmetic — the data is filtered
**server-side**, so a screen a role cannot use is not merely hidden in the
browser.

| Role | Sees | Rationale |
|---|---|---|
| **UAV Operator** | Live parameters, health status, alerts, mission Go/No-Go, replay | Flies the aircraft; needs decisions, not diagnostics |
| **Propulsion Engineer** | The above plus residuals, degradation analysis, life prediction, fault injection, scenarios, test rig, post-flight records | Analyses engine behaviour and validates the model |
| **Maintenance** | Health, life prediction, maintenance advisory, report export | Plans and executes the work |
| **Commander** | All of the above plus fleet view and audit log | Fleet-level decisions and accountability |

### 12.2 Display rules

Built to MIL-STD-1472H (human engineering) and MIL-STD-411F (aircrew alerting),
with alarm behaviour to ANSI/ISA-18.2 and EEMUA 191.

| Rule | Requirement |
|---|---|
| **Remove, never substitute** | An invalid reading renders as dashes with its state. It is never estimated, interpolated or held at its last value |
| **Every alert carries a response** | An alert without a recommended action trains the operator to ignore alerts |
| **Alarm rate discipline** | Bounded alarm rate in steady state; no chattering alarms |
| **Readable, not flickering** | Slow-moving indications are smoothed, quantised and hysteresis-bounded so a value does not jitter |
| **Alarms are never smoothed** | Smoothing applies to what is read as a *trend*. Limit checks run on raw readings |
| **Provenance always visible** | Source, rate, channel count, frames decoded and lost, measured latency, and whether the shadow model is locked |
| **Monochrome-survivable** | Every alert remains identifiable with colour removed |

### 12.3 The trend/alarm distinction

The most important rule in the interface, and the easiest to get wrong.

```
  Operator-facing TREND indications      Limit checks and ALARMS
  ---------------------------------      -----------------------
  Smoothed, quantised, hysteresis        RAW readings, unsmoothed
  Held still enough to read              Immediate
  Purpose: is this getting worse?        Purpose: is a limit exceeded?

  Smoothing an alarm would DELAY it. These are separate paths and
  must never be merged.
```

### 12.4 Provenance

The operator can always see whether to believe the screen. A stale feed renders
values as stale with their age; a lost link says so and does not present the
last-known state as live.

---

## 13. Security architecture

### 13.1 Threat model

| Threat | Control |
|---|---|
| Interception of the aircraft-to-GCS link | TLS 1.3; authenticated telemetry |
| Injection of forged telemetry | Keyed message authentication over sequence number, timestamp and payload |
| Replay of previously valid telemetry | Sequence numbers with replay rejection and a freshness window |
| Unauthorised access to a role's data | Server-side role filtering; scope enforced at the API, not the UI |
| Repudiation of an operator action | Tamper-evident audit log |
| Model poisoning through fleet learning | Robust aggregation with outlier rejection; privacy noise |

### 13.2 Positions taken

- **Access control is enforced server-side.** A capability a role does not hold
  is refused at the API. Hiding a control in the interface is not access control.
- **Transport security is explicit, not self-signed.** A self-signed certificate
  generated on first run trains operators to click through browser warnings —
  the same gesture they would make in front of a genuine interception. The system
  refuses to bind a network interface without properly issued certificates.
- **Raw telemetry does not leave the airframe** for fleet learning. Only model
  updates move.

---

## 14. Deployment configurations

The PS names three future deployment contexts. All three are served by the same
framework with different configuration.

```
+---------------------+  +---------------------+  +---------------------+
| ONBOARD             |  | GROUND CONTROL      |  | TEST RIG AND FLEET  |
| the aircraft        |  | STATION             |  | depot level         |
+---------------------+  +---------------------+  +---------------------+
| Acquisition and     |  | Full twin core      |  | Bench schedules     |
| validation          |  | All analytics tiers |  | judged against the  |
| Tier 1 rules        |  | Role-based console  |  | type certificate    |
| Lightweight         |  | Mission Go/No-Go    |  | Cross-engine        |
| inference           |  | Scenario simulation |  | comparison          |
| 72 h buffer         |  | Reports and replay  |  | Federated updates   |
| Authenticated       |  | Audit log           |  | No raw data leaves  |
| uplink              |  |                     |  | any airframe        |
+---------------------+  +---------------------+  +---------------------+
          |                        |                        |
          +------------------------+------------------------+
                                   |
                    authenticated, encrypted transport
```

**Onboard.** Runs on computing already carried by the airframe. Fully
functional with the link denied.

**Ground Control Station.** The complete system. Integrates with the existing
GCS rather than replacing it.

**Test rig and fleet.** The same engine model and analytics applied to bench
running — a post-overhaul acceptance schedule judged against the type
certificate — and to fleet-level comparison across airframes.

---

## 15. Non-functional requirements

| Attribute | Requirement | Rationale |
|---|---|---|
| **Latency** | End-to-end pipeline latency within the interval budget, with headroom | The twin must not fall behind the engine |
| **Update rate** | Display refresh matched to human reading speed — faster than the eye can absorb a changing number is wasted, slower is unresponsive | MIL-STD-1472H |
| **Edge footprint** | Inference model and runtime sized for a fraction of the memory of a small single-board computer | No new hardware qualification |
| **Availability** | Full detection capability with the datalink denied | Operational norm |
| **Buffer depth** | 72 hours of complete telemetry | Exceeds the longest planned sortie |
| **Modularity** | Any layer replaceable without disturbing the others | PS: "modular architecture for future scalability" |
| **Configurability** | All engine limits, thresholds and tuning external to code | Re-target to another engine without code change |
| **Determinism** | Tier 1 fully deterministic and reproducible | Certification |
| **Auditability** | Every operator action and every alert recorded, tamper-evident | Accountability |
| **Indigenous content** | Dependency licences machine-audited, not asserted | PS: "indigenous Digital Twin framework" |

---

## 16. Continuity of operation

Availability is engineered, not assumed. For every condition that could
interrupt a monitoring system, the design specifies in advance how capability is
maintained — so the operator keeps a usable, trustworthy picture throughout.

| Condition | Designed response | Operator sees |
|---|---|---|
| Datalink denied or jammed | Detection and alerting continue onboard; record buffered | LINK LOST, with the age of the last update |
| A sensor channel drops out | Value removed. Never estimated, interpolated or held | Dashes with the value state, not a number |
| A sensor drifts rather than fails | Disagreement with physics flags the *instrument* | INSTRUMENT CHECK; engine unaffected |
| Evidence insufficient for a life estimate | Prediction withheld, reason stated | "Establishing degradation trend" |
| Engine outside the modelled envelope | Twin declares itself out of validity; residuals suppressed | MODEL UNLOCKED — raw readings only |
| Analytics process stalls | Health endpoint reports loss of *progress*, not merely that it started | Stale indication with elapsed time |
| Ground station unavailable | Aircraft continues fully; reconciles on reconnection | Nothing lost |

**Every value the system displays is one it can justify, in every operating
condition.** That property is what makes the display trustworthy at hour eleven
of a sortie, which is when it matters most.

A note on the sixth row: system health is monitored on **progress**, not merely
on start-up. The health endpoint reports that the analytics pipeline is actively
advancing, which is a materially stronger guarantee than reporting that a
process exists.

---

## 17. Standards and compliance

| Domain | Standard |
|---|---|
| Engine limits and performance | EASA Type Certificate Data Sheet E.121; manufacturer operator and maintenance manuals |
| Data bus | CANaerospace; ARINC 825 (CAN in airborne systems) |
| Human engineering | MIL-STD-1472H |
| Aircrew alerting | MIL-STD-411F |
| Alarm management | ANSI/ISA-18.2; EEMUA Publication 191 |
| UAV interoperability | NATO STANAG 4586 |
| Prognostics | ISO 13381-1, condition monitoring and prognostics |
| Maintenance documentation | ATA chapter referencing |
| Transport security | TLS 1.3 |

Engine limits, performance figures and maintenance intervals are taken from the
type certificate and the manufacturer's manuals. None are assumed.

---

## 18. Requirement traceability

Every lettered block of the problem statement's expected solution, and where it
is implemented.

| PS ref | Requirement | Implementation |
|---|---|---|
| **A** | Virtual engine model synchronised with live engine data | Layer 4 twin core; shadow model driven by the live operating point |
| **A** | Modular architecture for future scalability | Five-layer module structure, Section 5.3; all configuration external |
| **A** | Real-time data ingestion | Layer 1 CAN acquisition with value-state validation |
| **B** | Health indices for engine sub-systems | Layer 3 health estimation from residuals; per-sub-system indices |
| **B** | RPM, CHT, EGT, oil pressure and temperature, fuel flow, vibration, battery and alternator, injection timing | Section 7 — all nine monitored, each in three forms |
| **C** | Transition from threshold monitoring to predictive diagnostics | Section 4 residual mechanism; Section 9 three-tier detection |
| **C** | Misfire, injector, cooling, lubrication, sensor drift, combustion instability, overheating, abnormal vibration | Section 8.1 — all eight, each with indicator, ATA area and action |
| **D** | Anomaly detection algorithms | Three independent tiers with fusion, Section 9.1 |
| **D** | Remaining Useful Life estimation | Section 10 — two estimators, disagreement gate, calibrated interval |
| **D** | Trend analysis | Residual trending; stabilised cruise datum for flight-to-flight comparison |
| **D** | Predictive maintenance recommendations | Advisory engine; work order with ATA chapter and deadline |
| **E** | Replay of historical mission data | Section 11.3 — full replay at controllable speed |
| **E** | Environmental condition simulation | Section 11.1 — settable across the operational envelope |
| **E** | High altitude, endurance, hot weather, rapid throttle transitions | Section 11.1 — all four as first-class scenarios |
| **F** | Real-time engine health status | Layer 5 operator console |
| **F** | Fault alerts | MIL-STD-411F alerting with recommended response |
| **F** | Engine efficiency trends | Efficiency tracking against the as-new baseline |
| **F** | Maintenance advisory | Advisory with named sub-system and deadline |
| **F** | Mission-wise health reports | Post-flight report with events, exceedances and cruise datum |

### Deliverables

| PS deliverable | Where |
|---|---|
| Functional prototype / software demonstrator | Complete running system, all five layers |
| Digital twin architecture design | This document, Sections 5–6 |
| Engine simulation model | Layer 2, validated against published performance data |
| AI/ML anomaly detection module | Layer 3, Section 9 |
| Visualization dashboard | Layer 5, Section 12 |
| Demonstration using simulated or real engine datasets | Live pipeline with fault injection; replay of recorded sorties |
| Technical documentation and deployment roadmap | This document; Sections 14–17 |

---

## 19. Innovation areas

All eight areas the problem statement invites.

| PS innovation area | How it is realised |
|---|---|
| **Physics-informed AI** | Physics prediction is a network input; thermodynamic constraints enter the training objective (Section 9.3) |
| **Edge AI for UAV applications** | Detection runs on the aircraft, independent of the link (Section 6.1) |
| **Lightweight onboard analytics** | Compiled inference graph sized for existing airframe computing; training framework absent from the flight image |
| **Hybrid thermodynamic and data-driven models** | Physics supplies the as-new baseline; learning supplies the correction (Section 4, Section 9.3) |
| **Federated learning** | Fleet models improve; raw telemetry never leaves the airframe (Section 9.5) |
| **Explainable AI for fault diagnosis** | Every alert resolves to a physical quantity, sub-system, ATA chapter and action, from the same computation that detected it (Section 9.4) |
| **Secure telemetry architecture** | Authenticated, sequence-numbered, replay-rejecting telemetry over TLS 1.3 (Section 13) |
| **Autonomous maintenance advisory** | Output is a work order with part, ATA chapter and deadline — not a chart (Section 5.2) |

### Technical expectations

| PS expectation | Where demonstrated |
|---|---|
| IC engine fundamentals | Mean-value thermodynamic model, combustion, turbocharging, thermal network (Section 6.2) |
| UAV propulsion systems | Reference engine selection against type certificate; mission profile analysis |
| Sensor fusion | Multi-channel validation, value states, cross-channel consistency (Sections 6.1, 8.2) |
| Embedded systems | Edge acquisition, onboard inference, offline buffering (Section 6.1) |
| CAN communication | CANaerospace over CAN bus; ECU/FADEC interface (Section 6.1) |
| AI/ML analytics | Three-tier detection, fusion, RUL, federated learning (Sections 9, 10) |
| Data visualization | Role-based console to MIL-STD-1472H / 411F (Section 12) |
| Simulation modelling | Mission and environment simulation, replay (Section 11) |
| Reliability engineering | Mission reliability, failure-mode behaviour, observability analysis (Sections 8.3, 11.2, 16) |

---

## 20. Keyword glossary

Every significant term from the problem statement, explained.

### Core concepts

**Digital Twin (DT)** — A continuously synchronised virtual representation of a
physical asset, driven by live telemetry, that mirrors the real engine closely
enough to answer questions about it. Not a dashboard and not a simulation: a
model kept in step with a specific engine, in real time.

**Real-time engine state estimation** — Determining the engine's present
internal condition from the sensors available, including quantities not
directly measured, using the physics model to infer them.

**Anomaly detection** — Identifying behaviour that departs from expectation.
Here, expectation is supplied by the as-new model at the same operating point,
not by a fixed threshold.

**Degradation tracking** — Following the progressive, continuous loss of
performance over an engine's life, as distinct from detecting a discrete fault.

**Fault prediction** — Determining that a named fault mode is developing, and
when it will reach a threshold requiring action — before the fault expresses
itself as a limit exceedance.

**Remaining Useful Life (RUL)** — The operating time remaining before an engine
or component reaches a defined end-of-life condition. Reported here with a
confidence interval, or withheld when evidence is insufficient.

**Prognostics and Health Management (PHM)** — The engineering discipline
covering condition assessment, fault diagnosis, life prediction and the
maintenance decisions that follow.

**Predictive maintenance / condition-based maintenance** — Replacing components
on measured evidence of condition rather than on elapsed hours.

**Mission replay** — Reconstructing a completed sortie from its recorded
telemetry and replaying it through the analytics, so an engineer sees what the
system saw and when.

**Residual** — Measured value minus the as-new model's prediction at the same
operating point. The central diagnostic quantity in this system: it isolates
condition from operation.

**Shadow model** — The second engine model held permanently at factory
condition and driven by the live operating point. Source of the prediction from
which residuals are formed.

### Platform and propulsion

**MALE UAV** — Medium Altitude Long Endurance Unmanned Aerial Vehicle. Operates
at medium altitude for very long duration, typically single-engine.

**ISR** — Intelligence, Surveillance and Reconnaissance.

**Aero piston engine** — A reciprocating internal-combustion engine used for
aircraft propulsion, as opposed to a turbine.

**FADEC** — Full Authority Digital Engine Control. The digital controller
managing fuel and ignition, and the source of much of the engine's data.

**ECU** — Engine Control Unit. The engine's electronic controller.

**Turbocharger** — Exhaust-driven compressor that restores manifold pressure at
altitude. Its *critical altitude* is the height above which it can no longer
maintain sea-level manifold pressure and power begins to fall away.

**TBO** — Time Between Overhauls. The manufacturer's scheduled interval for
major engine overhaul.

**Type Certificate Data Sheet (TCDS)** — The airworthiness authority's
published record of an engine's approved limits and configuration. The
authoritative source for every limit in this system.

### Data acquisition

**CAN bus** — Controller Area Network. The serial bus used for engine data in
vehicles and aircraft.

**SocketCAN** — The Linux kernel interface for CAN networks.

**CANaerospace** — A higher-level protocol defining how data is organised and
identified on a CAN bus in aircraft.

**ARINC 825** — The aviation industry standard for CAN in airborne systems.

**Value state** — A quality tag carried with every reading: valid, stale,
invalid, out-of-range or absent. Propagated end to end so the display can
always show whether a number is trustworthy.

**Sensor fusion** — Combining multiple sensors, and the physics model, to
produce a better estimate than any one source, and to identify which source is
wrong when they disagree.

### Engine parameters

**RPM** — Revolutions Per Minute. Engine crankshaft speed.

**CHT** — Cylinder Head Temperature. Temperature of the cylinder head; the
primary indicator of heat rejection and cooling system health.

**EGT** — Exhaust Gas Temperature. Indicates combustion completeness and
timing. The *spread* between cylinders is often more diagnostic than the mean.

**Manifold pressure** — Pressure in the intake manifold; with RPM, it sets the
power the engine is producing.

**BSFC** — Brake Specific Fuel Consumption. Fuel consumed per unit of power
produced. The standard measure of engine efficiency; its deterioration against
the as-new baseline is a direct measure of degradation.

**Vibration signature** — The frequency content of engine vibration. Bearing
and mechanical faults appear as growth at characteristic orders of engine
speed.

**Injection timing** — When fuel is injected relative to crank angle. Deviation
from the commanded value indicates a fuel system or controller fault.

**ECTM** — Engine Condition Trend Monitoring. The practice of recording the
same parameters at the same stabilised condition once per flight, so successive
flights can be compared.

### Fault modes

**Misfire** — A cylinder fails to fire correctly, producing imbalance and
increased cyclic variability.

**Injector abnormality** — A fuel injector delivers incorrectly, showing as EGT
spread between cylinders and a fuel flow residual.

**Cooling degradation** — Progressive loss of cooling effectiveness, typically
from fouling or restriction. Raises CHT at a matched operating point without
crossing any limit for a long time.

**Lubrication issue** — Degraded oil condition, pressure or flow, indicated by
oil pressure and temperature residuals.

**Sensor drift / failure** — The *instrument* becomes wrong while the engine is
serviceable. Detected by disagreement with the physics model rather than by any
limit.

**Combustion instability** — Cycle-to-cycle variation in combustion, measured
by the coefficient of variation of indicated mean effective pressure.

**Overheating trend** — Sustained upward movement in temperature and its rate
of change, distinguished from a transient by its persistence.

**Abnormal vibration** — Growth in vibration at characteristic orders,
indicating bearing or mounting deterioration.

### AI and analytics

**Physics-informed AI** — Machine learning constrained by physical law, so the
model cannot produce physically impossible outputs.

**Hybrid thermodynamic and data-driven model** — Physics supplies the baseline
prediction; learning supplies the correction physics cannot capture.

**Edge AI** — Inference executed on the aircraft rather than at the ground
station, so capability survives loss of the datalink.

**Lightweight onboard analytics** — Analytics sized to run within the compute
and power budget already available on the airframe.

**Federated learning** — Training a shared model across many aircraft by
exchanging model updates only. Raw telemetry never leaves the airframe.

**Differential privacy** — Adding calibrated noise to shared model updates so
individual sorties cannot be reconstructed from them.

**Explainable AI (XAI)** — Analytics whose outputs can be traced to
understandable causes. Required here for airworthiness, not for user comfort.

**Conformal prediction** — A method producing confidence intervals with a
coverage guarantee that does not assume any particular error distribution.

**Autoencoder** — A network trained to reconstruct normal behaviour; large
reconstruction error indicates abnormality.

**LSTM** — Long Short-Term Memory. A network architecture for sequences, able
to use long stretches of history.

**Score fusion** — Combining evidence from independent detection methods into a
single decision, requiring agreement before escalation.

### Operations and standards

**GCS** — Ground Control Station. Where the UAV is flown from and where the
twin's full analytics and console run.

**ATA chapter** — The standard numbering system for aircraft systems used
throughout maintenance documentation. Every alert carries one so a maintainer
can go straight to the correct manual section.

**Maintenance advisory** — A recommendation naming the sub-system, the action
and the deadline.

**Mission reliability** — The assessed probability that a specific engine, in
its current condition, will complete a specific mission profile.

**MIL-STD-1472H** — US military standard for human engineering design criteria.

**MIL-STD-411F** — US military standard for aircrew alerting: how warnings,
cautions and advisories are presented.

**ISA-18.2 / EEMUA 191** — Alarm management standards. They govern alarm rates,
prohibit chattering alarms, and require that every alarm carry a recommended
operator response.

**STANAG 4586** — NATO standard for UAV control system interoperability.

**ISO 13381-1** — International standard for condition monitoring and
prognostics of machines.

**Indigenous development** — Designed and built domestically, without
dependency on foreign-controlled components. Here the dependency licence
position is machine-audited rather than asserted.

---

## Document notes

This document defines the production configuration: the system intended for
deployment in a defence-grade Ground Control Station, on an engine test rig,
and across a fleet. It describes design and architecture. Performance
measurement, validation results and the evaluation record are held separately.

Engine limits, performance figures and maintenance intervals derive from the
Type Certificate Data Sheet and the manufacturer's manuals. None are assumed.
