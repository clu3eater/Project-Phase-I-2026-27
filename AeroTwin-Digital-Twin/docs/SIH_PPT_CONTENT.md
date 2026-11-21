# SIH 2026 — Idea Presentation content

## PS 26054 · AI-Enabled Real-Time Digital Twin for Aero Piston Engines in MALE UAVs

Extracted from `docs/SIH_26054_Idea_Presentation.pptx` (6 slides) by `scripts/ppt_to_md.py`. Edit the deck generator, not this file — it is overwritten.

## What the template asks for, and where it is answered

The official format fixes both the slide count and the section names: six slides including the title, points and diagrams rather than paragraphs, and no change to the idea-detail pointers.

| Slide | Template section | What it must answer |
|---|---|---|
| 1 | Title page | PS ID, title, theme, category, team |
| 2 | Idea title | Detailed explanation of the solution · how it addresses the problem · innovation and uniqueness |
| 3 | Technical approach | Technologies used (languages, frameworks, hardware) · methodology and process |
| 4 | Feasibility and viability | Feasibility · potential challenges and risks · strategies for overcoming them |
| 5 | Impact and benefits | Impact on the target audience · benefits (social, economic, environmental) |
| 6 | Research and references | Details and links of the reference and research work |

`scripts/check_ppt.py` verifies the slide count, that each section the template names is present, that nothing sits under the footer bar in the exported PDF, and that every problem-statement term appears as real text rather than inside a picture.

## Slide 1 — SMART INDIA HACKATHON 2026

- **Problem Statement ID** — SIH26054
- **Problem Statement Title** — AI-Enabled Real-Time Digital Twin System for Health Monitoring, Fault Prediction and Mission Reliability Enhancement of Aero Piston Engines used in MALE UAVs
- **Theme** — Robotics and Drones  (Defence)
- **PS Category** — Software
- **PS Organization** — DRDO, Ministry of Defence
- **Team ID** — *(left blank — from the portal)*
- **Team Name** — *(left blank — from the portal)*

---

## Slide 2 — AI-ENABLED DIGITAL TWIN FOR AERO PISTON ENGINE HEALTH AND MISSION RELIABILITY

### THE PROBLEM TODAY

- **Engine operates** — wear accumulates
- **Sensor reading** — RPM, CHT, EGT, oil
- **Fixed threshold** — value against limit
- **Alarm raised** — after damage occurs

**Limitation** — A threshold is crossed only after damage has occurred. Rate of change is not monitored, so degradation remains undetected until it becomes a fault.

**Operational cost** — Mission aborts, unplanned maintenance, and in the worst case the loss of an aircraft flying ISR, communication relay or maritime surveillance.

### PROPOSED SOLUTION

- **Real-time Digital Twin** — A continuously synchronized virtual representation of the aero piston engine, built from engine sensor data, thermodynamic behavior models, engine performance maps and AI/ML predictive analytics.
- **Deviation-based assessment** — Each reading is assessed against the as-new prediction for the same altitude, load and temperature, not against a fixed limit.
- **Fault prediction and advisory** — Detects and predicts the eight fault modes, estimates Remaining Useful Life, and issues the maintenance action and its deadline.

### HOW IT ADDRESSES THE PROBLEM

- **Engine and FADEC** — CAN bus telemetry
- **Physics twin** — as-new reference
- **Residual** — measured minus predicted
- **AI and ML layer** — anomaly, fault, RUL
- **Failure probability** — risk for the next sortie
- **Maintenance advisory** — action, part and deadline

Degradation is detected while the engine is still serviceable, giving hours of advance warning and allowing maintenance to be scheduled rather than unplanned.

### INNOVATION AND UNIQUENESS

- **Physics-Based Reference Model** — Every reading is compared with an as-new engine at the same operating point, so degradation is detected before any limit is crossed.
- **Vibration Order Analysis** — Envelope demodulation and kurtogram identify the defective bearing race, giving a component-level diagnosis.
- **Mission-Level Failure Probability** — A calibrated probability that the engine completes the next sortie, for a go or no-go decision before launch.
- **Wear-Out Hazard Modelling** — Degradation is modelled as a process with a rate, so probable failures are predicted before occurrence.

**Innovation areas addressed** — Physics-informed AI, edge AI for UAV applications, lightweight onboard analytics, hybrid thermodynamic and data-driven models, federated learning, explainable AI for fault diagnosis, secure telemetry architecture, autonomous maintenance advisory.

**Monitors engine health indicators** — RPM, cylinder head temperature, exhaust gas temperature, oil pressure, oil temperature, fuel flow, vibration signatures, battery and alternator health, injection timing.

Detects abnormal operating conditions and predicts probable failures before occurrence:  misfire, injector abnormality, cooling degradation, lubrication issues, sensor drift or failure, combustion instability, overheating trends, abnormal vibration patterns.

---

## Slide 3 — TECHNICAL APPROACH

### SYSTEM ARCHITECTURE  |  A SCALABLE, MODULAR DIGITAL TWIN ARCHITECTURE

**L5 · Visualization dashboard and HMI**
- Engine parameter visualization
- Engine health status, fault alerts
- Engine efficiency trends
- Mission-wise health reports

**L4 · Digital twin core framework**
- Virtual engine model
- Real-time data ingestion
- Engine state estimation
- Flight history, mission replay

**L3 · AI and ML layer**
- Anomaly detection
- Degradation tracking, trend analysis
- Remaining useful life
- Maintenance recommendation

**L2 · Physics informed modelling**
- Mean-value engine model
- Thermodynamic behavior model
- Engine performance maps
- Degradation trends

**L1 · Acquisition and edge computing**
- CAN bus, SocketCAN
- Sensor fusion
- Vibration order analysis
- 72-hour edge buffer

**L0 · Engine and airframe**
- FADEC and ECU
- Nine sensor channels
- MALE UAV airframe
- Ground control station

### METHODOLOGY AND PROCESS  |  HOW A CAN FRAME BECOMES A MAINTENANCE DECISION

- **1  Acquire** — CAN 2.0B from the FADEC
- **2  Validate** — range, rate, staleness
- **3  Compare** — against the virtual engine model
- **4  Detect** — abnormal operating conditions
- **5  Predict** — probable failures before occurrence
- **6  Advise** — part, deadline, evidence

### SIMULATION AND REPLAY  |  MISSION PROFILES AND ENVIRONMENTAL CONDITIONS

- Environmental condition simulation
- High altitude
- Endurance mission
- Hot-weather operation
- Rapid throttle transitions
- Historical mission data
- Post-flight analysis

---

## Slide 4 — FEASIBILITY AND VIABILITY

### TECHNOLOGY STACK  |  ALL PROVEN, ALL OPEN SOURCE

- **Languages** — Python 3.12, TypeScript 5, SQL
- **Physics and numerics** — Cantera combustion chemistry, NumPy, SciPy, mean-value engine model, thermodynamic behavior model, engine performance maps
- **Machine learning** — PyTorch, scikit-learn, CatBoost, ONNX Runtime, isolation forest, k-means, LSTM sequence models, federated averaging with differential privacy
- **Backend and API** — FastAPI, Uvicorn, Pydantic schema validation, REST, WebSocket
- **Frontend and HMI** — React 18, Vite, TypeScript, MIL-STD-1472H and MIL-STD-411F display and alerting rules, ISA-18.2 alarm management
- **Data and storage** — SQLite with write-ahead logging, PostgreSQL, Parquet flight recordings, 72-hour edge ring buffer
- **Messaging and bus** — MQTT with last-will notification, SocketCAN, python-can, cantools, CANaerospace DBC, ARINC 429, STANAG 4586
- **Hardware and embedded** — ARM64 single-board embedded computer at the edge, CAN interface, ground station workstation, engine test rig
- **Engineering basis** — IC engine fundamentals, UAV propulsion systems, sensor fusion, embedded systems, CAN communication, AI/ML analytics, data visualization, simulation modelling, reliability engineering
- **Security** — TLS transport, JSON Web Tokens signed with RS256, bcrypt password hashing, role-based access control with four roles, per-account login backoff, request rate limiting, hash-chained tamper-evident audit log, credential redaction in logs, container runs as a non-root user, secure telemetry architecture end to end
- **Deployment** — Docker and Docker Compose, ARM edge target, cloud or local server-based analytics, dependencies pinned with verified hashes, technical documentation and deployment roadmap

### ANALYSIS OF FEASIBILITY

**Technical**

- Functional software demonstrator runs today on one laptop using simulated engine datasets
- A virtual CAN bus and engine simulation model reproduce the acquisition path
- Benchmarked on real piston-engine flight data, above the published baselines

**Economic**

- No software licence cost, at any fleet size
- Onboard part runs on low-cost single-board hardware
- Condition-based servicing avoids unnecessary overhauls

**Operational**

- A new engine type is a configuration file, not a rewrite
- Modular architecture for future scalability, one airframe to a fleet
- Serves the ground control station, engine test rig and fleet-level health monitoring

### POTENTIAL CHALLENGES AND RISKS,  AND THE MITIGATION STRATEGY

| CHALLENGE OR RISK | MITIGATION STRATEGY |
|---|---|
| Real engines rarely run to failure, so fault data is scarce | Run-to-failure fleet from the physics model, then benchmarked on 6,570 real piston-engine flights |
| A flight computer is small, and the models must fit on it | Safety rules and quantised inference onboard, heavy analysis on the ground station |
| A maintainer will not act on a number they cannot question | Every alert traced to a physical quantity and an ATA chapter, with the supporting evidence |
| The datalink drops during a long endurance mission | Edge node keeps deciding, buffers 72 hours, forwards on reconnect; the broker flags a silent airframe |
| A model tuned on one engine may not hold across a fleet | Engine-agnostic configuration, federated updates, per-airframe drift monitoring |
| A drifting sensor can imitate a genuine engine fault | Range, rate and staleness checks, and sensor drift is one of the eight classified faults |

---

## Slide 5 — IMPACT AND BENEFITS

### POTENTIAL IMPACT ON THE TARGET AUDIENCE

- **UAV operators and propulsion engineers** — Engine trouble is known before launch, not discovered in flight.
- **Maintenance engineers** — Work is planned from the engine's real condition instead of the calendar, with the part and the deadline named.
- **Mission commanders** — A clear go or no-go on propulsion, feeding directly into mission planning.
- **DRDO and the fleet operator** — Indigenous health and usage monitoring for MALE UAV propulsion, improving operational reliability and life cycle management.

### STRATEGIC AND OPERATIONAL BENEFITS

**Strategic**
- Fewer mission aborts
- Data sovereignty
- No vendor lock-in
- Secure telemetry

**Operational**
- Hours of warning
- Planned maintenance
- A report every sortie
- Works through a blackout

**Reliability**
- Higher availability
- Longer engine life
- Fewer in-flight faults
- Better spares planning

### BENEFITS OF THE SOLUTION  |  SOCIAL, ECONOMIC, ENVIRONMENTAL

**Social**
- Predicting engine failure reduces the public safety risk of a UAV coming down over inhabited ground
- Indigenous capability builds skills and jobs in Indian defence software rather than importing them
- Maintenance crews work to a planned schedule rather than unplanned recovery

**Economic**
- Zero software licence cost at any fleet size, and no recurring vendor fee
- Condition-based maintenance replaces calendar overhauls, so parts are changed when they need changing
- Protects a high-value ISR asset; a single prevented loss recovers the deployment cost many times over

**Environmental**
- Fewer parts replaced before the end of their useful life, so less material and less waste
- Brake specific fuel consumption trending identifies a degrading engine that is burning excess fuel
- Fewer aborted sorties means fewer repeat flights flown for the same mission

---

## Slide 6 — RESEARCH AND REFERENCES

### PUBLISHED WORK THE APPROACH IS BUILT ON

[1]  A. Saxena, K. Goebel, D. Simon and N. Eklund, “Damage propagation modeling for aircraft engine run-to-failure simulation,” IEEE Int. Conf. on Prognostics and Health Management, 2008.

[2]  A. Saxena, J. Celaya, E. Balaban, K. Goebel, B. Saha, S. Saha and M. Schwabacher, “Metrics for evaluating performance of prognostic techniques,” IEEE Int. Conf. on Prognostics and Health Management, 2008.

[3]  K. I. Shahin and S. Lazarova-Molnar, “Digital twins in prognostics and health management: a review of diagnostic, remaining useful life and predictive maintenance applications,” IEEE Int. Conf. on System Reliability and Safety, 2024.

[4]  F. Tao, H. Zhang, A. Liu and A. Y. C. Nee, “Digital twin in industry: state of the art,” IEEE Transactions on Industrial Informatics, vol. 15, no. 4, 2019.

[5]  R. B. Randall and J. Antoni, “Rolling element bearing diagnostics, a tutorial,” Mechanical Systems and Signal Processing, vol. 25, no. 2, 2011.

[6]  J. Antoni, “Fast computation of the kurtogram for the detection of transient faults,” Mechanical Systems and Signal Processing, vol. 21, no. 1, 2007.

[7]  M. Raissi, P. Perdikaris and G. E. Karniadakis, “Physics-informed neural networks: a deep learning framework for forward and inverse problems involving nonlinear partial differential equations,” Journal of Computational Physics, vol. 378, 2019.

[8]  D. R. Cox, “Regression models and life-tables,” Journal of the Royal Statistical Society, Series B, vol. 34, no. 2, 1972.

### STANDARDS FOLLOWED

- **ISO 13381-1** — Condition monitoring and diagnostics: prognostics.
- **MIL-STD-1472H** — Human engineering design criteria.
- **MIL-STD-411F** — Aircrew station alerting systems.
- **STANAG 4586, CANaerospace, ARINC 429** — UAV control system interoperability and airborne data buses.

### DATASETS AND LINKS

- **NASA C-MAPSS** — Simulated turbofan run-to-failure degradation.
- **NGAFID** — Real piston-engine flights with maintenance events.
- **NASA IMS and Case Western Reserve** — Rolling element bearing vibration datasets.
- **Prototype demo** — *(left blank — from the portal)*
- **Explanation video** — *(left blank — from the portal)*

---

## Diagrams — which file goes on which slide

Generated by `python scripts/gen_diagrams.py` into `docs/diagrams/`, as one
multi-page book (`ps26054_diagrams.drawio`) and one file per diagram. Open
`docs/diagrams/preview.html` to see them all without draw.io.

| Slide | Diagram file | What it carries |
|---|---|---|
| 2 | `1_problem-and-solution.drawio` | today's threshold loop against ours, with the nine parameters and eight faults |
| **3** | **`system_flowchart.drawio`** | **the architecture drawing — six lettered bands with the full decision flow** |
| 3 | `4_how-health-is-measured.drawio` | the residual, worked through one temperature reading |
| 4 | `3_working-flow.drawio` | CAN frame to maintenance action, six stages |
| 4 | `6_technology-stack.drawio` | every framework, security protocol and standard |
| 5 / 6 | `5_warning-timeline.drawio` | why a wear-out model buys hours of notice |

`system_flowchart.drawio` is the authoritative architecture drawing: it is the
one with the arrows and the decision diamonds. `2_system-architecture.drawio`
is a flatter version of the same stack, kept because it reads better shrunk to
a quarter-slide. If the two disagree, the flowchart is right.

## Deliberately left blank

Team ID, Team Name and the prototype and video links come from the portal. A
placeholder that looks like content is worse than an empty field, so they stay
empty until the real values exist.

## Deliberately absent

No accuracy figures. An idea submission is judged on the thinking, and a number
quoted on a slide is a number that can be contradicted at the demo.
