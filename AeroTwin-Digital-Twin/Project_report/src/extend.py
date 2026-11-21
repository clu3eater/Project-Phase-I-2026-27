"""One-off: insert the additional material (tables, pseudocode, test cases)
into content.md at fixed anchors. Safe to re-run: it skips if already applied."""
import pathlib

P = pathlib.Path(__file__).with_name("content.md")
s = P.read_text(encoding="utf-8")
if "Table 3.1 Functional Requirements" in s:
    raise SystemExit("already extended")


def after(anchor: str, text: str) -> None:
    global s
    assert s.count(anchor) == 1, anchor[:70]
    s = s.replace(anchor, anchor + "\n\n" + text.strip("\n") + "\n")


def before(anchor: str, text: str) -> None:
    global s
    assert s.count(anchor) == 1, anchor[:70]
    s = s.replace(anchor, text.strip("\n") + "\n\n" + anchor)


# ---------------------------------------------------------------- Chapter 2
before("These insights directly shaped the present project.", """
The main published works that this project draws on are summarised in Table 2.2, together with the specific contribution taken from each and the limitation that the project had to address in its own design.

TABLE|Ref.|Work|Contribution used here|Limitation for this problem
ROW|[1]|Saxena et al., run-to-failure simulation (2008)|Simulated fleets with known ground truth for prognostics|Turbofan model; no piston engine physics
ROW|[2]|Saxena et al., prognostic metrics (2008)|Standard way to score RUL predictions|Does not address false alarms in detection
ROW|[3]|Tao et al., digital twin in industry (2019)|Definition and structure of a digital twin|Survey; no ready model for an engine
ROW|[4]|Shahin and Lazarova-Molnar (2024)|Role of twins in diagnosis and maintenance|Mostly cloud-hosted, after-the-fact twins
ROW|[5]|Raissi et al., physics-informed networks (2019)|Physics term in the training loss|Needs governing equations in usable form
ROW|[8]|Cox, proportional hazards (1972)|Failure risk linked to measured covariates|Assumes proportional hazards over time
ROW|[9]|Angelopoulos and Bates, conformal prediction (2021)|Intervals with guaranteed coverage|Needs exchangeable calibration data
ROW|[11]|Malhotra et al., LSTM encoder-decoder (2016)|Reconstruction error as an anomaly score|Sensitive to operating-point changes
ROW|[12], [13]|CBLOF (2003), matrix profile (2016)|Label-free statistical anomaly scores|Depend on good, condition-free features
CAPTION|Table 2.2 Summary of Literature Used in This Project

Two observations follow from this table. First, every technique the project relies on has been published and validated separately, which reduces technical risk; the novelty of the work lies in combining them around a physics-based twin of a specific piston engine. Second, most of the listed limitations concern the input data rather than the algorithms: detectors are sensitive to operating conditions, and prognostic models need trustworthy ground truth. Both limitations are addressed in this project by the same design choice, namely computing residuals against an as-new physics twin and generating a simulated fleet whose ground truth is known exactly.
""")

# ---------------------------------------------------------------- Chapter 3
after("FIG|3.1|fig3_1_architecture.png|Architecture Diagram – Layered System Architecture|5.75", """
These objectives were refined into the functional requirements listed in Table 3.1 and the non-functional requirements listed in Table 3.2. Each requirement was traced to the module that implements it and to the tests or measurements that verify it.

TABLE|ID|Functional requirement|Implemented in
ROW|FR1|Acquire engine data from a CAN bus and validate every value|Edge layer (CAN ingest)
ROW|FR2|Raise certified-limit alerts on the aircraft without the datalink|Edge layer (rule engine)
ROW|FR3|Predict the as-new engine response at the current operating point|Physics layer (shadow twin)
ROW|FR4|Detect anomalies from residuals with few false alarms|AI layer (detectors, fusion)
ROW|FR5|Report subsystem health and name the most likely fault|AI layer (health, fault namer)
ROW|FR6|Estimate remaining useful life with an uncertainty interval|AI layer (RUL server)
ROW|FR7|Assess mission reliability and give a Go or No-Go verdict|Twin core (mission module)
ROW|FR8|Manage missions, aircraft release and defects by role|Twin core (squadron operations)
ROW|FR9|Stream live state to the console and export flight reports|Twin core (API), console
ROW|FR10|Authenticate users and record every state change|Twin core (security, audit)
CAPTION|Table 3.1 Functional Requirements

TABLE|ID|Non-functional requirement|Target|Measured
ROW|NFR1|Twin update latency (p95)|≤ 200 ms|83 ms
ROW|NFR2|False alarms on healthy engines|≤ 5 %|1.0 %
ROW|NFR3|Onboard model size|≤ 1 MB|150 KB
ROW|NFR4|Onboard memory use|≤ 10 % of 2 GB|69 MB (3.4 %)
ROW|NFR5|Operation without a network|Required|No external calls
ROW|NFR6|Data buffered during link loss|72 hours|72-hour store
ROW|NFR7|New engine type without code change|Required|One YAML file
CAPTION|Table 3.2 Non-Functional Requirements and Measured Values
""")

after("lowers the confidence of the result to zero when the input is unlike anything seen in training.", """
The processing performed on every update of the twin is summarised in the following pseudocode. It shows how validation, the shadow twin, the detectors and the fusion step are combined, and where the system deliberately refuses to report a result.

CODE|procedure TWIN_TICK(dt = 0.5 s)
CODE|    tel <- CanIngest.poll()                    # validated values with states
CODE|    if tel has no usable operating point then
CODE|        publish state marked "not assessable"; return
CODE|    healthy <- ShadowModel.update(tel, dt)     # as-new prediction
CODE|    r <- tel.measured - healthy                # residual set
CODE|    x <- FEATURES(r, tel.operating_point)      # 34-column contract
CODE|    s2 <- Tier2Ensemble.score(x)               # statistical score
CODE|    s3 <- Tier3Detector.anomaly_score(window(x))   # deep score
CODE|    level <- ScoreFusion.fuse(s2, s3)
CODE|    if OOD.check(x) is out of distribution then
CODE|        level.confidence <- 0                  # do not trust the models
CODE|    health <- HEALTH_INDICES(r, level)         # worst sub-index per subsystem
CODE|    fault <- FaultNamer.name(history, level)
CODE|    rul <- LstmRulServer.observe(r, hours)
CODE|    if rul has no calibrated interval then
CODE|        rul <- withheld, with the reason
CODE|    state <- TwinState(tel, healthy, r, health, fault, rul, alerts)
CODE|    TwinSynchroniser.publish(state)            # WebSocket /ws/state
CODE|end procedure

The procedure has two properties that matter for safety. Nothing in it can block the certified-limit rules, which run independently on the edge layer, and every branch that cannot produce a trustworthy figure publishes the reason instead of a value.
""")

after("FIG|3.9|fig3_9_usecase.png|Use Case Diagram – Actors and System Functions|5.75", """
Each use case is protected by a permission, called a scope, and each role is granted a fixed set of scopes in the system configuration. Table 3.3 lists the main scopes of each role. The commander holds every scope, while the other roles receive only what their duties require; for example, an operator can fly a mission but cannot inject a simulated fault, and an attempt to do so is refused and recorded in the audit log.

TABLE|Role|Main scopes granted|Typical actions
ROW|Commander|All scopes (*)|Plan and allot missions, manage users
ROW|Operator|read:telemetry, fly:mission, control:sortie, raise:defect|Prepare, start, launch, recall, debrief
ROW|Maintenance|write:maintenance, read:prognostics, read:reports|Release aircraft, rectify defects, ground run
ROW|Engineer|review:defects, run:simulation, write:engines, read:physics|Disposition defects, set limitations, test faults
CAPTION|Table 3.3 Roles and Their Permission Scopes
""")

after("FIG|3.12|fig3_12_er.png|ER Diagram – Application Database|5.75", """
The main tables of the squadron and user databases are described in the data dictionary below. Tables 3.4 to 3.6 list the columns of the Missions, Defects and Users tables, which carry the core workflow of the system; the Aircraft and Logbook tables follow the same conventions, with timestamps stored as ISO 8601 text in Coordinated Universal Time and structured details stored as JSON text.

TABLE|Column|Type|Description
ROW|id|TEXT (PK)|Mission identifier, for example MSN-0001
ROW|name, type|TEXT|Mission name and task type, such as MARITIME or ISR_PATROL
ROW|status|TEXT|Current state from the mission state machine
ROW|environment|TEXT|Conditions used for the reliability assessment
ROW|duration_h, altitude_ft|REAL|Planned endurance and altitude
ROW|throttle_pct|REAL|Planned cruise power setting
ROW|area, priority, notes|TEXT|Task area, priority and commander's notes
ROW|created_by, approved_by|TEXT|Commander who planned and who approved
ROW|tail, operator|TEXT (FK)|Allotted aircraft and operator
ROW|assessment|TEXT (JSON)|Predicted mission success at allotment
ROW|preflight|TEXT (JSON)|Confirmed checklist, who confirmed and when
ROW|launched_utc, landed_utc|TEXT|Flight timestamps
ROW|outcome, debrief|TEXT|Debrief result and remarks
ROW|engine_hours|REAL|Engine hours added by the flight
CAPTION|Table 3.4 Data Dictionary – Missions Table

TABLE|Column|Type|Description
ROW|id|INTEGER (PK)|Defect number, assigned automatically
ROW|tail, mission_id|TEXT (FK)|Aircraft and mission concerned
ROW|source|TEXT|Raised by the twin or reported by a person
ROW|description, severity|TEXT|What was found, and its alert level
ROW|grounding|INTEGER|1 if the aircraft may not fly until rectified
ROW|status|TEXT|OPEN, CONFIRMED, DEFERRED or CLOSED
ROW|evidence|TEXT (JSON)|Twin readings supporting a twin-raised defect
ROW|disposition, disposed_by|TEXT|Engineer's decision and who made it
ROW|defer_until_hours|REAL|Hours limit for a deferred defect
ROW|rectified_by, rectification|TEXT|Who repaired it and what was done
CAPTION|Table 3.5 Data Dictionary – Defects Table

TABLE|Column|Type|Description
ROW|username|TEXT (PK)|Login name
ROW|role|TEXT|One of the four roles
ROW|hash|TEXT|bcrypt hash of the password
ROW|disabled|INTEGER|1 if the account is disabled
ROW|must_change|INTEGER|1 until the first-run password is changed
ROW|token_epoch|INTEGER|Raised to revoke all existing tokens
ROW|created_utc, updated_utc|TEXT|Account timestamps
CAPTION|Table 3.6 Data Dictionary – Users Table
""")

# ---------------------------------------------------------------- Chapter 4
after("FIG|4.1|fig4_1_filestructure.png|Project File Structure – Repository Layout|5.75", """
The hardware and software used to develop and run the system are listed in Table 4.1. The ground station requirements are modest, and the onboard requirements were derived from the measured footprint of the edge model.

TABLE|Item|Development and ground station|Onboard edge computer
ROW|Processor|x86-64, 4 cores|ARM64 single-board computer
ROW|Memory|8 GB RAM|2 GB RAM (69 MB used)
ROW|Operating system|Windows 11 or Linux|Linux
ROW|Runtime|Python 3.12, Node.js 18 or newer|Python 3.12, ONNX Runtime
ROW|Main libraries|PyTorch, scikit-learn, CatBoost, Cantera, FastAPI|python-can, ONNX Runtime
ROW|Storage|SQLite, Parquet|SQLite (72-hour buffer)
ROW|Interface|Web browser for the console|CAN transceiver
CAPTION|Table 4.1 Hardware and Software Requirements
""")

after("Squadron operations are implemented in the OpsStore class, which enforces the mission state machine of Fig 3.10.1 and rejects any transition that is not allowed.", """
The main endpoints of the API are listed in Table 4.2 with the scope each one requires. In total the server exposes 76 REST endpoints and one WebSocket endpoint; the table shows the most important ones for each function.

TABLE|Method and path|Purpose|Scope required
ROW|POST /api/auth/login|Sign in and receive tokens|None
ROW|GET /api/state|Current twin state|read:telemetry
ROW|WS /ws/state|Live twin state stream|read:telemetry
ROW|POST /api/ops/missions|Plan a mission|plan:mission
ROW|GET /api/ops/missions/{id}/candidates|Rank aircraft for a mission|plan:mission
ROW|POST /api/ops/missions/{id}/approve|Allot aircraft and operator|plan:mission
ROW|POST /api/ops/missions/{id}/launch|Launch after checks pass|fly:mission
ROW|POST /api/ops/missions/{id}/debrief|Debrief and report snags|fly:mission
ROW|POST /api/ops/aircraft/{tail}/release|Sign maintenance release|write:maintenance
ROW|POST /api/ops/defects/{id}/disposition|Engineer's decision on a defect|review:defects
ROW|POST /api/ops/defects/{id}/rectify|Record a repair|write:maintenance
ROW|POST /api/faults/inject|Inject a simulated fault|run:simulation
ROW|GET /api/report.pdf|Post-flight report|read:reports
ROW|GET /api/audit|Read and verify the audit log|read:audit
CAPTION|Table 4.2 Main API Endpoints and Required Scopes
""")

# ---------------------------------------------------------------- Chapter 5
after("FIG|5.2|fig5_2_detection.png|Analysis Chart – Detection Precision, Recall and False Alarms|5.75", """
Functional behaviour was verified with the test cases in Table 5.2, which were executed against the running system during the demonstration mission. Each case states the input, the expected behaviour and the result observed.

TABLE|No.|Test case|Expected result|Observed result
ROW|TC1|Log in with valid credentials|Token issued, role dashboard shown|Pass
ROW|TC2|Plan a mission with an unknown type|Request rejected, valid types listed|Pass
ROW|TC3|Allot an aircraft awaiting inspection|Aircraft shown as unavailable|Pass
ROW|TC4|Start engine before checklist is complete|Start refused|Pass
ROW|TC5|Launch with oil below 50 °C|Launch refused with the reason|Pass
ROW|TC6|Operator injects a simulated fault|Refused: scope run:simulation missing|Pass
ROW|TC7|Healthy climb compared with the twin|All readings "As expected"|Pass
ROW|TC8|Inject a misfire on cylinder 1 in flight|Caution "MISFIRE SUSPECTED" raised|Pass
ROW|TC9|Recall the aircraft (RTB)|Mission moves to RTB, then debrief|Pass
ROW|TC10|Debrief with a reported snag|Defect raised on the technical log|Pass
ROW|TC11|Sustained CAN traffic over the mission|No frames lost or rejected|Pass
CAPTION|Table 5.2 Functional Test Cases

In addition to these system tests, each layer has an automated test suite that runs on every change. The number of test functions in each layer is given in Table 5.3; with parameterised cases the suite runs about one thousand tests.

TABLE|Layer|Test functions|Main areas covered
ROW|Edge layer|141|CAN decoding, validation, rules, buffer
ROW|Physics layer|105|Engine model, combustion, degradation
ROW|AI layer|323|Features, detectors, fusion, health, RUL
ROW|Twin core|341|State, API, security, missions, replay
ROW|Integration|16|End-to-end pipeline
ROW|Total|926|
CAPTION|Table 5.3 Automated Test Suite by Layer
""")

after("FIG|5.5.1|shot_records.png|Screenshot – Post-Flight Engine Report|5.75", """
The engineer's squadron view, shown in Fig 5.5.2, compares the last recorded health of every aircraft. After the demonstration flight, MALE-01 showed an overall health of 76.8 % with a combustion index of only 12.1 %, which immediately identifies the subsystem affected by the injected misfire, while the thermal, mechanical and electrical indices remained above 96 %. The view also lists engine hours, hours to the next inspection and the remaining time before overhaul for each aircraft.

FIG|5.5.2|shot_squadron.png|Screenshot – Squadron Engine Health Comparison|5.75
""")

s = s.replace("as listed in Table 5.2.", "as listed in Table 5.4.")
s = s.replace("CAPTION|Table 5.2 Remaining Useful Life Error", "CAPTION|Table 5.4 Remaining Useful Life Error")
P.write_text(s, encoding="utf-8")
print("extended")
