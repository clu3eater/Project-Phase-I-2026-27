# 1|INTRODUCTION

Unmanned aerial vehicles have moved from short-range reconnaissance tools to platforms that remain airborne for an entire day. The Medium Altitude Long Endurance (MALE) class of Unmanned Aerial Vehicle (UAV) flies for twenty to thirty hours at a time, carries expensive sensors, and is used for surveillance, communication relay and maritime patrol. Most aircraft in this class are driven by a single aero piston engine, and there is no pilot on board to hear a rough-running cylinder or notice a temperature that is slowly creeping upward. The reliability of that one engine therefore decides whether the mission is completed, whether the payload is recovered, and whether the aircraft comes home at all. At the same time, modern engines such as the Rotax 915 iS are controlled by a Full Authority Digital Engine Control (FADEC) unit that continuously publishes dozens of sensor readings on a data bus, so far more information about the engine is available than any operator can watch.

Conventional engine monitoring compares each reading against a certified limit and raises an alarm when the limit is crossed. This rule is correct and required by certification, but it is blind to slow degradation: a reading can drift for hundreds of flight hours while remaining "within limits", and the alarm arrives only when the margin is already gone. The approach taken in this project is to build a digital twin of the engine, a software model that runs alongside the real engine, receives the same inputs, and computes what a brand-new engine would read at exactly the same operating point. The difference between the measured value and this as-new prediction is a residual that grows with wear from the first flight hour. The project, named AeroTwin, combines this physics-based twin with machine-learning detectors, health indices and remaining-life estimation, and presents the result to operators, commanders and maintainers through a role-based ground control console.

## 1.1|Background of the Study

Engine health monitoring in aviation began with simple cockpit gauges and exceedance recorders. A recorder stored the moments when a temperature or pressure passed its limit, and maintenance engineers reviewed these events after landing. Later, large turbofan engines adopted trend monitoring, in which a handful of performance parameters were corrected for altitude and temperature and plotted across many flights. These systems worked well for airlines with large fleets, ground infrastructure and data specialists, but they were designed around turbine engines and they analysed data only after the flight.

Piston engines in light aircraft and UAVs received far less attention. Owners relied on fixed inspection intervals, such as an inspection every 100 hours and a complete overhaul at a Time Between Overhaul (TBO) of around 1,200 hours. This calendar-based approach is simple, but it replaces healthy parts too early and still misses parts that fail between inspections. For an unmanned aircraft flying long missions far from base, an in-flight failure is far more expensive than for a training aircraft that can glide to a nearby airfield.

Three technology changes now make a better approach possible. First, digitally controlled engines expose detailed telemetry on standard buses such as Controller Area Network (CAN). Second, physics-based engine models and combustion libraries can run in real time on an ordinary computer. Third, machine-learning methods for anomaly detection and Remaining Useful Life (RUL) prediction have matured and can be deployed on small edge computers. Together these allow an engine to be compared continuously with its own healthy behaviour rather than with a fixed limit, which is the idea this project builds on.

## 1.2|Problem Statement

The core problem is that existing monitoring for UAV piston engines raises an alarm only after a reading becomes unacceptable, and therefore cannot warn that the engine is gradually getting worse. In the evaluation data used in this project, the certified limits raise an alarm in only 77 out of 12,165 evaluation windows, while 7,558 windows show genuine degradation with every limit still satisfied. A conventional monitor has nothing to say about any of these windows.

Several factors make the problem harder. Engine readings depend strongly on altitude, throttle setting and outside air temperature, so a raw reading cannot be judged without knowing the operating point. Real engines are rarely allowed to run until they fail, so labelled failure data for training a model is scarce. The datalink between the aircraft and the ground station can drop during long missions, so any analysis that depends on the ground station alone may be unavailable exactly when it is needed. Finally, operators and maintainers will not act on a number that they cannot question, so an opaque prediction is of little practical value.

Thus, the problem addressed by this project lies in detecting gradual engine degradation before any certified limit is crossed, explaining which subsystem is affected and how urgently, and doing so in real time, offline and with very few false alarms, for the single piston engine of a long-endurance unmanned aircraft.

## 1.3|Objective of the Project

The main objective of this project is to design and build a real-time digital twin of an aero piston engine that estimates the engine's condition continuously, detects degradation early, predicts how much useful life remains, and supports a Go or No-Go decision before each mission.

Each module of the system contributes to this objective. The edge layer acquires engine data over a CAN bus and validates every value before it is used. The physics layer computes the behaviour of an as-new engine at the same operating point, so that the difference between measured and predicted values isolates wear. The artificial intelligence layer applies statistical and deep-learning detectors to these residuals, fuses their scores to keep false alarms rare, names the most likely fault among eight fault classes, and estimates health indices and remaining life. The twin core manages state, missions and maintenance records, and serves everything through a secure application programming interface.

The project also has supporting objectives. The system must be usable by four different roles, namely commander, operator, maintainer and engineer, each seeing only what is relevant to their job. It must run entirely offline on hardware the operator controls, with no cloud dependency. It must be modular, so that a new engine type can be added through a configuration file rather than new code. Finally, every reported result must be measured on engines that the models have never seen, so that the project's claims remain honest and reproducible.

## 1.4|Significance of the Study

The technological significance of the project lies in showing that a physics-informed digital twin can run in real time for a piston engine and can be combined with machine learning in a way that is both accurate and explainable. The as-new shadow model turns every raw reading into a residual with a clear physical meaning, and the fused detectors reach an alarm precision of 0.996 with a false-positive rate of about 1 % on healthy engines. The edge model occupies only 150 KB and answers in under one millisecond, which shows that useful analytics can run on a small onboard computer.

The societal significance follows from safety and cost. An engine failure on a long-endurance UAV can lead to the loss of the aircraft over inhabited ground or at sea. Early warning allows the mission to be recalled before the failure occurs, and condition-based maintenance replaces parts when they actually need replacement rather than on a fixed schedule. This reduces both the risk to people under the flight path and the waste of serviceable parts.

From the point of view of accessibility and inclusivity, the system is built entirely from open-source components with no licence cost at any fleet size. It runs on an ordinary laptop for the ground station and on low-cost single-board hardware for the aircraft, which makes it affordable for small operators, flying schools and research groups and not only for large defence organisations. Because it never sends data to an external service, it can also be used in air-gapped environments where sensitive data must remain on site.

The academic significance lies in the combination of several areas of computer science and engineering in a single working system: embedded data acquisition, numerical simulation, statistical learning, deep learning, distributed software design, security engineering and human-machine interface design. The project also follows good evaluation practice by splitting data by engine rather than by row, and it reports negative results alongside positive ones, which makes it a useful reference for future student work in prognostics and health management.

## 1.5|Report Organization

- Chapter 1 – Introduction

This chapter introduces the domain of long-endurance UAV propulsion, explains why limit-based monitoring is insufficient, and states the problem, objectives and significance of the project.

- Chapter 2 – Literature Review

This chapter reviews existing engine-monitoring platforms and the evolution of techniques from exceedance monitoring to physics-informed machine learning and digital twins, and summarises the gaps that this project addresses.

- Chapter 3 – System Design

This chapter presents the layered architecture of the system, the design of each processing module, and the full set of software-engineering diagrams, including component, deployment, activity, data flow, class, use case, sequence, state, security and entity-relationship diagrams.

- Chapter 4 – Implementation Details

This chapter describes the development environment, the development process and timeline, and how each module was implemented, ending with performance optimisation and scalability measurements.

- Chapter 5 – Results and Discussion

This chapter evaluates the system on unseen engines, presents screenshots of the working console for each role, and discusses the limitations observed during testing.

- Conclusion

The conclusion summarises the achievements of the project, its key capabilities, and the future scope for the second phase of the work.

# 2|LITERATURE REVIEW

The monitoring of engine health sits at the meeting point of several fields: aviation maintenance practice, reliability engineering, signal processing and machine learning. Each field has contributed techniques that this project uses, and each has limitations that the project attempts to overcome. This chapter first reviews six existing platforms that are close to the problem addressed here, comparing what each provides with what a long-endurance UAV piston engine requires. It then traces the evolution of the field, from fixed-limit exceedance monitoring through statistical trend analysis, classical machine learning and deep learning, to physics-informed learning and digital twins. The chapter ends by consolidating the insights from the literature and relating them to the design decisions made in this project.

## 2.1|Review of Existing Platforms

SUB|(a) Savvy Aviation FEVA – Failing Exhaust Valve Analytics

Savvy Aviation provides maintenance management for owners of piston-engine general aviation aircraft. Its Failing Exhaust Valve Analytics (FEVA) service applies machine learning to exhaust gas temperature data uploaded after each flight, and it is reported to have identified more than sixty failing exhaust valves early across over three million flights. It demonstrates that machine learning on piston-engine temperature data has real value. However, it works only after the data is uploaded following landing, it targets one failure mode, and it depends on a cloud service, so it does not provide live, onboard, multi-fault monitoring for an unmanned aircraft.

LINK|https://www.savvyaviation.com

SUB|(b) Rotax B.U.D.S. – Diagnostic Software for Rotax Engines

BRP-Rotax supplies the B.U.D.S. diagnostic software, which connects to the engine control unit of fuel-injected Rotax engines. It reads stored fault codes, displays live engine data on the ground, and supports maintenance tasks such as configuration and software updates. It is the manufacturer's tool and is valuable for troubleshooting. However, it reads fault memory rather than predicting faults, it does not estimate remaining life or mission reliability, and it is used on the ground with a cable rather than during flight.

LINK|https://www.flyrotax.com

SUB|(c) Honeywell and Pratt & Whitney – Engine Health Management Services

Large engine manufacturers such as Honeywell and Pratt & Whitney offer engine health management services in which engine data is downloaded after each flight and analysed by trend-monitoring software and specialist engineers. These services are mature and have prevented many in-flight shutdowns on turbine fleets. However, they are designed for turbine engines, they analyse data after landing rather than in real time, and they require a commercial service agreement and connection to the provider's infrastructure.

LINK|https://www.honeywell.com

SUB|(d) GE Aerospace – AI-Based Engine Monitoring

GE Aerospace applies machine learning to fleet-wide turbofan data and reports detecting substantially more issues with fewer false alerts than earlier rule-based methods. Its strength is the scale of its data and its combination of physics knowledge with learning. However, it is built for large commercial and military turbine fleets, runs on the provider's cloud platform, and is not available for small piston engines in unmanned aircraft.

LINK|https://www.geaerospace.com

SUB|(e) C3 AI and the US Air Force PANDA Programme

C3 AI provides the Predictive Analytics and Decision Assistant (PANDA) used by the US Air Force as its official condition-based maintenance platform, applied across more than 3,000 aircraft. It shows that predictive maintenance can be run at the scale of a whole air force and that maintainers will adopt it when predictions are tied to concrete maintenance actions. However, it is an enterprise platform for large fleets, it runs on substantial central infrastructure, and it works on maintenance and sensor records gathered after flights rather than as a live model running beside a single engine.

LINK|https://c3.ai

SUB|(f) Airbus Skywise – Aviation Data Platform

Skywise is a data platform, built with Palantir, that collects operational and maintenance data from airline fleets and makes it available for analytics, including predictive maintenance applications. Its strength is the breadth of data it brings together across operators. However, it is a data platform rather than a model of a specific engine, it depends on cloud connectivity, and it is designed for commercial airline fleets rather than the small piston engines of unmanned aircraft.

LINK|https://aircraft.airbus.com/en/services/enhance/skywise

The comparison in Table 2.1 summarises these platforms against the three properties that this project requires: support for a piston engine, operation on board the aircraft without a network, and prediction of faults before they occur.

TABLE|System|Piston engine|Works on board, offline|Predicts faults
ROW|GE Aerospace AI monitoring|No|No|Yes
ROW|Honeywell / Pratt & Whitney services|No|No|Yes
ROW|Savvy Aviation FEVA|Yes|No|Yes
ROW|Rotax B.U.D.S.|Yes|No|No

ROW|C3 AI PANDA (USAF)|No|No|Yes
ROW|Airbus Skywise|No|No|Yes

ROW|AeroTwin (this project)|Yes|Yes|Yes
CAPTION|Table 2.1 Comparison of Existing Engine-Monitoring Platforms

## 2.2|Exceedance and Limit-Based Monitoring

The earliest form of engine monitoring is the exceedance check. Each sensor reading is compared with a fixed limit published in the engine's type certificate or operator's manual, for example a maximum coolant temperature of 120 °C or a minimum oil pressure. When the limit is crossed, an alarm is raised and the event is recorded. This approach is simple, transparent and required by certification, which is why every modern engine still uses it as the last line of defence.

Its weakness is that a limit answers only one question: whether a reading is unacceptable right now. It cannot tell whether the engine is getting worse. A radiator that is slowly blocking up raises the coolant temperature by only a degree or two for a long time, because the cooling system compensates, and then the temperature rises rapidly once the reserve is exhausted. By the time the limit is crossed, the opportunity for planned maintenance has passed. This limitation is the starting point of the present work, and the certified limits are retained in the edge layer as a safety net rather than replaced.

## 2.3|Statistical Trend Monitoring

Trend monitoring improved on exceedance checks by correcting readings for the operating conditions and plotting them over many flights. A small shift in a corrected parameter, such as exhaust gas temperature margin, could then reveal gradual deterioration. Statistical process control charts and simple regression models were used to decide when a trend became significant.

Later statistical methods treated the problem as anomaly detection. Cluster-based methods such as the Cluster-Based Local Outlier Factor (CBLOF) score how far a new observation lies from the clusters formed by normal data [12], while the matrix profile identifies unusual subsequences in a time series by comparing each window with its nearest neighbour [13]. For vibration signals, envelope demodulation and the kurtogram are established tools for locating defects in rolling-element bearings [6], [7]. These methods need only healthy data for training, which suits a domain where failures are rare. Their limitation is that they depend on good features: applied to raw readings, they confuse a change in operating point with a change in health. This project therefore applies a statistical ensemble of this kind to physics residuals rather than raw readings, which removes most of the operating-point effect before the statistics are computed.

## 2.4|Classical Machine Learning for Fault Diagnosis

With the growth of sensor data, classical machine-learning classifiers such as decision trees, random forests, support vector machines and gradient-boosted trees were applied to engine fault diagnosis. Given labelled examples of healthy and faulty behaviour, these models learn to separate fault classes from features computed over windows of data. Gradient-boosting libraries such as CatBoost [16] handle mixed features well and are fast to train.

A common weakness in published work is the way these models are evaluated. If rows from the same engine appear in both the training and the test set, the model is partly graded on engines it has already seen, and its accuracy is inflated. In this project the effect was measured directly: the same random forest achieved 96.0 % accuracy with a random row split but only 62.8 % on engines it had never seen. For this reason every result in this report is measured with a split by engine, with forty engines held out entirely from training.

## 2.5|Deep Learning and Sequence Models

Deep learning brought models that learn features directly from sequences. Long Short-Term Memory (LSTM) networks [10] retain information over long time spans and are well suited to sensor time series. An LSTM autoencoder learns to reconstruct windows of normal data; when an abnormal window arrives, the reconstruction error rises, which provides an anomaly score that needs no fault labels [11]. Multi-task networks extend this idea by predicting several outputs at once, such as whether a window is anomalous, which fault class is present and how severe it is.

For prognostics, LSTM and convolutional networks are routinely applied to the NASA Commercial Modular Aero-Propulsion System Simulation (C-MAPSS) dataset, a simulated run-to-failure benchmark for turbofan engines [1]. Standard metrics for prognostic performance were defined by Saxena and colleagues [2]. Deep models achieve good accuracy on these benchmarks, but they need large amounts of training data and can behave unpredictably on inputs unlike their training data. This project uses both an LSTM autoencoder and a multi-task deep anomaly head, and adds an out-of-distribution check so that the deep models are not trusted on inputs they were not trained for.

## 2.6|Physics-Informed Machine Learning

A purely data-driven model can fit training data well and still violate physical laws when it extrapolates. Physics-informed neural networks address this by adding a term to the training loss that penalises violations of known physical relationships [5]. The network then learns from data while being guided by physics, which improves generalisation when data is limited.

Mean-value engine models describe the average behaviour of an engine over a cycle using thermodynamic relationships for air flow, combustion, heat transfer and turbocharging, as described in standard internal-combustion engine texts [14]. Detailed combustion chemistry can be computed with open-source libraries such as Cantera [15]. In this project a mean-value model of the Rotax 915 iS, validated against the manufacturer's performance table, provides the physical reference. A physics-informed variant of the learning model was also evaluated: it matched the accuracy of the data-only model while reducing physical-constraint violations from 1.000 to 0.216, showing that the physics term buys enforceable behaviour rather than curve-fitting.

## 2.7|Digital Twins in Prognostics and Health Management

A digital twin is a virtual representation of a specific physical asset that is updated with data from that asset throughout its life. Surveys of digital twins in industry [3] and in prognostics and health management [4] describe twins that mirror the state of the asset, predict its future behaviour, and support decisions about operation and maintenance. Their key advantage over a stand-alone model is the continuous connection between the physical and virtual objects.

Most reported twins are built for manufacturing equipment, turbines or large structures, and many depend on cloud platforms for computation and storage. Few address small piston engines, and fewer still operate in real time on the vehicle itself. The twin built in this project keeps a permanently as-new copy of the engine model, so that the comparison between the real engine and its healthy twin directly measures degradation, and it is designed to run on the ground station and, in reduced form, on an onboard edge computer.

## 2.8|Remaining Useful Life Estimation and Uncertainty

Remaining Useful Life is the expected operating time before a component reaches a failure threshold. Early work used reliability statistics such as the Weibull distribution and the proportional-hazards regression model of Cox [8], which relates the failure rate to measured covariates. Modern approaches use sequence models trained on run-to-failure data to predict RUL directly from recent sensor history.

A point estimate of RUL without an uncertainty interval can be misleading, because operators tend to treat a printed number as certain. Conformal prediction provides a distribution-free way of attaching intervals with a guaranteed coverage to the predictions of any model [9]. In this project the RUL estimator is benchmarked on the C-MAPSS dataset and reaches within 8 to 18 % of published state-of-the-art error without per-dataset tuning. The console deliberately withholds a remaining-life figure whenever a calibrated interval is not available, rather than displaying a number that looks authoritative but is not.

## 2.9|Consolidated Insights from Literature

The literature shows a clear trajectory. Monitoring began with fixed limits that are safe but blind to degradation, moved to statistical trend analysis that needs good features, and then to machine learning and deep learning that need large labelled datasets and careful evaluation. Physics-informed learning and digital twins combine knowledge of the system with data, which improves both accuracy and explainability.

At the same time, existing commercial platforms are designed for turbine fleets or for after-flight analysis, and they usually depend on cloud services. The manufacturer's own tool for Rotax engines reads fault memory but does not predict. No platform reviewed provides live, offline, predictive monitoring for the piston engine of a long-endurance UAV.

An audit of 72 publicly available student projects on the same problem, carried out at the start of this work, confirmed a further gap in practice. As shown in Fig 2.9, 45 of these projects had no automated tests, 15 evaluated their models with a random row split, and only 10 tested on engines the model had never seen. The right-hand chart shows why this matters: the same model's accuracy falls from 96.0 % to 62.8 % when it is tested honestly.

FIG|2.9|fig2_9_audit.png|Analysis Chart – Audit of Existing Student Projects and Effect of the Test Method|5.75

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

These insights directly shaped the present project. The design keeps certified limits as a safety layer, uses a physics-based as-new twin to produce residuals, applies both statistical and deep detectors to those residuals and fuses them, attaches uncertainty to remaining life, runs entirely offline, and evaluates every model on engines withheld from training.

In summary, the specific gaps that this project addresses are the following:

- No live, onboard monitoring exists for the piston engine of a long-endurance UAV; existing services analyse data after landing
- Limit-based monitors cannot see degradation that stays within limits, which is where most early warning lies
- Many published and student models are evaluated on engines they have already seen, so their accuracy is overstated
- Predictions are often shown without uncertainty, and cloud-based tools cannot be used where data must stay on site


# 3|SYSTEM DESIGN

The design phase translates the objectives of the project into a structure of modules, interfaces and data stores that can be implemented, tested and extended independently. The guiding principle is a layered and modular architecture: the system is divided into six layers, from the engine and its data bus at the bottom to the operator console at the top, and each layer communicates with its neighbours only through well-defined data structures. This separation allows the physics model, the machine-learning models and the user interface to be developed and replaced without affecting each other.

The design also follows an edge-first principle. Safety-related checks run on the aircraft itself, so that alerts never depend on a working datalink, while heavier analysis runs on the ground station. Every value that flows through the system carries a validity state, every alert is traced to a physical quantity, and every user action is checked against the user's role and recorded in an audit log.

The design is documented with a set of standard software-engineering diagrams. The chapter presents a layered architecture diagram, a component diagram and a deployment diagram for the overall structure; an activity diagram for data acquisition; a data flow diagram for the processing pipeline; a class diagram for the main objects; a use case diagram for the user roles; a sequence diagram and a state diagram for the mission workflow; a security architecture diagram; and an entity-relationship diagram for the database.

In summary, the chapter moves from the design objectives and overall architecture, through each processing module in the order in which data passes through it, to the user-facing behaviour, security and data design of the system.

## 3.1|Design Objectives

The first design objective is real-time operation. The twin must process the engine's telemetry and publish an updated state every 0.5 seconds of engine time, with a computation budget of 200 milliseconds per update, so that the operator always sees current information.

The second objective is early and reliable detection. The system must detect degradation before any certified limit is crossed, while keeping the false-alarm rate low enough that operators continue to trust the alerts. This is achieved by working on residuals rather than raw readings and by requiring agreement between independent detectors.

The third objective is explainability. Every alert must name a physical quantity, a subsystem and a recommended action, and every reading on the console must be shown beside the twin's expected value. The fourth objective is resilience: the system must keep working when the datalink drops, buffer data on the aircraft, and refuse to display figures that cannot be supported, such as a remaining-life estimate without a calibrated interval. The fifth objective is extensibility, so that a new engine type is added by writing a configuration file rather than changing code. The overall structure that meets these objectives is shown in Fig 3.1.

FIG|3.1|fig3_1_architecture.png|Architecture Diagram – Layered System Architecture|5.75

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


## 3.2|Overall System Architecture

The system is organised into six layers. Layer 0 is the engine and its bus: the Rotax 915 iS engine, its dual-lane FADEC and nine sensor channels, connected through a CAN bus that is simulated in software for this phase and can be switched to real hardware by a single configuration setting. Layer 1, the edge layer, decodes CAN frames, validates each value and runs the certified-limit rules. Layer 2 contains the physics model of the engine, including the as-new shadow twin. Layer 3 contains the artificial intelligence models. Layer 4, the twin core, holds the twin state, mission logic, squadron operations and the application programming interface. Layer 5 is the operator console.

The component view of this architecture is shown in Fig 3.2. Components are grouped into three deployable units: the edge node, the twin server and the operator client. The twin server is organised around the LiveTwin component, which orchestrates each update by polling telemetry, updating the shadow model, calling the detectors and health estimators, and publishing the resulting twin state through the Twin API component. The API depends on the security component for authentication and authorisation, and on the squadron operations component for missions and defects.

FIG|3.2|fig3_2_component.png|Component Diagram – Software Architecture|5.75

The physical placement of these components is shown in the deployment diagram in Fig 3.2.1. The engine and an ARM64 edge computer are installed in the airframe and connected by the CAN bus. The edge computer runs the acquisition, rule and buffering artifacts and a compact ONNX model. The ground control station runs the FastAPI server under Uvicorn, together with the physics and AI layers and the local SQLite databases. Operators connect from a web browser over HTTPS and secure WebSockets, and an optional on-premise fleet server can synchronise flight records between stations.

FIG|3.2.1|fig3_2_1_deployment.png|Deployment Diagram – Hardware and Software Nodes|5.75

## 3.3|Data Acquisition and Edge Validation Module

The acquisition module is the entry point of all engine data. The FADEC broadcasts each parameter on the CAN bus using the CANaerospace convention, in which every frame carries an identifier for the parameter and a declared data type. Because the engine has two independent control lanes, most parameters arrive twice, once from each lane.

The activity diagram in Fig 3.3 shows how each frame is processed. A frame whose identifier or data type is not recognised is rejected and counted as a bus error. A recognised frame is decoded into an engineering value, which is then checked for range, rate of change, staleness and a frozen value. A value that fails these checks is marked as suspect, stale or failed instead of being silently discarded, and this state travels with the value through the entire system. The two lanes are then compared, the certified-limit rules are evaluated, and any exceedance raises an edge alert. Finally, the validated telemetry is written to a 72-hour buffer on the aircraft and published to the twin.

FIG|3.3|fig3_3_activity.png|Activity Diagram – Frame Acquisition and Validation|4.2

## 3.4|Physics-Based Shadow Twin Module

The shadow twin is a mean-value model of the Rotax 915 iS engine that is permanently held at zero operating hours. It receives only the operating inputs of the real engine, namely throttle position, engine speed, altitude and outside air temperature, and computes the outputs that a brand-new engine would produce under exactly those conditions.

The model combines several sub-models. An air-path model computes the flow of air through the throttle and intake manifold, a turbocharger and intercooler model computes the boost and charge-air temperature, a combustion model based on Cantera computes the energy release and exhaust temperature, and a two-node thermal model computes the cylinder head and coolant temperatures. Six degradation pathways are modelled explicitly in the full engine simulator, namely cooling-system fouling, injector fouling, turbocharger wear, bearing wear, lubrication degradation and sensor drift, but the shadow twin never applies them, which is what makes it a fixed healthy reference.

The model was validated against 130 full-throttle rows of the manufacturer's performance table, with a median power error of 1.05 %, a plenum pressure error of 0.43 %, a charge-air temperature error of 0.007 K and a fuel-flow error of 1.71 %. The engine's cooling arrangement was rebuilt from its manuals after it was found that the engine has no thermostat, and the twin therefore models the airframe's cooling flaps as the controller that holds temperature.

## 3.5|Residual Generation and Data Flow

The residual is the difference between a measured value and the shadow twin's prediction for the same operating point. Because both values share the same altitude, throttle and temperature, the residual removes most of the variation caused by flight conditions and leaves the variation caused by the condition of the engine. Residuals are computed for the cylinder head, coolant and oil temperatures, oil pressure, exhaust temperature, fuel flow and manifold pressure.

The data flow diagram in Fig 3.5 shows how data moves between processes, external entities and data stores. Engine frames from the FADEC enter process 1.0, which acquires and validates them and writes them to the edge buffer. Validated telemetry flows to process 2.0, which produces the as-new prediction and the residuals. Process 3.0 detects anomalies using the trained models, and process 4.0 estimates health and remaining life and records each flight in the flight history. Process 5.0 assesses mission reliability for the commander, and process 6.0 manages squadron operations with the maintenance and engineering staff, storing records in the squadron database.

FIG|3.5|fig3_5_dfd.png|Data Flow Diagram – Level 1 Processing Pipeline|5.75

## 3.6|Anomaly Detection and Score Fusion Module

Anomaly detection uses three independent detectors that work on a 34-column feature vector built from residuals and operating conditions. The first is a statistical ensemble that combines a cluster-based outlier score with a matrix-profile score; it is trained only on healthy data. The second is an LSTM autoencoder that reconstructs windows of thirty consecutive samples and uses the reconstruction error as an anomaly score. The third is a deep multi-task network that predicts directly whether a window is anomalous, which fault class is present and how severe it is.

The scores of these detectors are combined by a fusion module. A window is reported as degraded only when the evidence from the statistical detector and the deep detectors together exceeds a threshold that was fixed on validation engines before the test engines were examined. Because the detectors make different kinds of errors, requiring their agreement reduces the false-positive rate to about one fifth of that of any single detector. An out-of-distribution check runs alongside the detectors and lowers the confidence of the result to zero when the input is unlike anything seen in training.

The processing performed on every update of the twin is summarised in the following pseudocode. It shows how validation, the shadow twin, the detectors and the fusion step are combined, and where the system deliberately refuses to report a result.

CODE|procedure TWIN_TICK(dt = 0.5 s)
CODE|    tel <- CanIngest.poll()                    # validated values
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
CODE|    health <- HEALTH_INDICES(r, level)         # worst sub-index
CODE|    fault <- FaultNamer.name(history, level)
CODE|    rul <- LstmRulServer.observe(r, hours)
CODE|    if rul has no calibrated interval then
CODE|        rul <- withheld, with the reason
CODE|    state <- TwinState(tel, healthy, r, health, fault, rul, alerts)
CODE|    TwinSynchroniser.publish(state)            # WebSocket /ws/state
CODE|end procedure

The procedure has two properties that matter for safety. Nothing in it can block the certified-limit rules, which run independently on the edge layer, and every branch that cannot produce a trustworthy figure publishes the reason instead of a value.


## 3.7|Health Index and Remaining Useful Life Module

The health module converts residuals and detector outputs into health indices for four subsystems: thermal, mechanical, combustion and electrical. Each subsystem index is the worst of its sub-indices rather than their average, so that a single failing part is not hidden by healthy ones. A composite health index between 0 and 1 is then derived and mapped to bands such as Excellent, Good, Fair and Poor.

A fault-naming component reads each engine's history and names the most likely of eight fault classes: misfire, injector abnormality, cooling degradation, lubrication issue, sensor drift, combustion instability, overheating trend and abnormal vibration. Remaining useful life is estimated by an LSTM network served from the twin core. The estimate is published only together with a calibrated interval; when no calibrated interval is available, the console shows the reason instead of a number. Each subsystem with low health is linked to a maintenance advisory that names the action, the part and the deadline.

## 3.8|Mission Reliability and Class Design

The mission reliability module estimates the probability that the engine will complete a planned mission. For a given mission profile, defined by task type, endurance, altitude and environmental conditions, it combines the current subsystem health, the engine's hours to inspection and to overhaul, and the operating limitations recorded by engineers, and returns a Go or No-Go verdict with the reason. The commander uses this assessment to rank the available aircraft for each mission.

The main classes that implement the design are shown in the class diagram in Fig 3.8. The LiveTwin class is composed of the shadow model, the statistical ensemble, the deep detector, the score fusion and the RUL server, and it uses the CAN ingest class, which creates Telemetry objects. Each update produces a TwinState object, a strictly validated Pydantic model that is sent to clients. The OpsStore class manages missions, aircraft and defects, uses the MissionReliability class for the Go or No-Go decision, and records every action in the AuditLog.

FIG|3.8|fig3_8_class.png|Class Diagram – Core Classes of the Twin|5.75

## 3.9|Use Case Design

The system has four primary actors, all specialisations of a general squadron user who can log in and change their password. The Commander plans missions, allots an aircraft and an operator to each mission based on the predicted mission success, and can cancel a mission. The Operator prepares the allotted aircraft, completes the pre-flight checklist, starts the engine and launches, monitors live engine health, recalls the aircraft or aborts, and debriefs after shutdown. The Maintenance user inspects and releases aircraft, rectifies defects, performs engine ground runs and records scheduled maintenance. The Engineer reviews defects raised by the twin, may defer a defect with an hours limit, sets operating limitations and compares the engines of the squadron.

A secondary actor, the engine with its FADEC, streams telemetry to the system. The use case diagram in Fig 3.9 shows these actors and their use cases. Allotting an aircraft includes viewing the predicted mission success, and deferring a defect extends the review of twin-raised defects.

FIG|3.9|fig3_9_usecase.png|Use Case Diagram – Actors and System Functions|5.75

Each use case is protected by a permission, called a scope, and each role is granted a fixed set of scopes in the system configuration. Table 3.3 lists the main scopes of each role. The commander holds every scope, while the other roles receive only what their duties require; for example, an operator can fly a mission but cannot inject a simulated fault, and an attempt to do so is refused and recorded in the audit log.

TABLE|Role|Main scopes granted|Typical actions
ROW|Commander|All scopes (*)|Plan and allot missions, manage users
ROW|Operator|read:telemetry, fly:mission, control:sortie, raise:defect|Prepare, start, launch, recall, debrief
ROW|Maintenance|write:maintenance, read:prognostics, read:reports|Release aircraft, rectify defects, ground run
ROW|Engineer|review:defects, run:simulation, write:engines, read:physics|Disposition defects, set limitations, test faults
CAPTION|Table 3.3 Roles and Their Permission Scopes


## 3.10|Sequence and State Design

The sequence diagram in Fig 3.10 shows the interaction between the operator, the console, the Twin API, the operations store, the LiveTwin pipeline and the AI models during a mission. The operator prepares the aircraft, which moves the mission to the pre-flight state, and then starts the engine after completing the checklist. The LiveTwin pipeline then runs a loop every 0.5 seconds, polling telemetry, updating the shadow model, scoring the features and pushing the twin state to the console over a WebSocket. Launch is accepted only after the twin's launch checks pass, such as oil temperature reaching the 50 °C take-off minimum. If a caution or higher alert is raised, the console shows a banner and the master caution, and the operator may recall the aircraft.

FIG|3.10|fig3_10_sequence.png|Sequence Diagram – Mission Execution and Live Monitoring|5.75

The life cycle of a mission is defined by the state diagram in Fig 3.10.1. A mission is created in the Planned state, becomes Approved when the commander allots an aircraft and an operator, and moves to Pre-flight when the operator prepares the aircraft. Starting the engine after the checklist moves it to Engine Running, from which it can be launched into Airborne or aborted on the ground. An airborne mission can be recalled to Return to Base. When the engine stops, the mission waits for the debrief and then ends as Completed or Aborted. A mission can be cancelled until the engine is started.

Every transition in this diagram is guarded in the software rather than left to the user interface. A mission can be approved only while it is planned, and only for an aircraft that is serviceable, released and within its limitations. The engine can be started only from the pre-flight state and only when every checklist item has been confirmed, and launch is accepted only from the engine-running state after the twin's launch checks pass. The debrief is accepted only after the engine has stopped, and it must record one of three outcomes: accomplished, partial or aborted. Any request that does not match the mission's current state is refused with that state in the error message, and every accepted transition is written to the aircraft's logbook with the user and role that made it.

FIG|3.10.1|fig3_10_1_state.png|State Diagram – Mission Life Cycle|5.75

## 3.11|Security Architecture

Security is designed in layers, as shown in Fig 3.11. At the client layer, the console is served over HTTPS and secure WebSockets and loads no scripts, fonts or resources from external networks, so it can operate in an air-gapped environment. At the API layer, users authenticate with JSON Web Tokens signed with the RS256 algorithm, the algorithm is pinned so that a forged token cannot downgrade it, and short-lived access tokens are renewed with refresh tokens. Repeated failed logins trigger a back-off, and a rate limiter protects every authenticated route.

At the application layer, role-based access control maps each of the four roles to a set of permitted scopes, all inputs are validated by strict Pydantic models, and first-run passwords must be changed before use. At the data layer, passwords are stored as bcrypt hashes and every significant action is written to an audit log in which each entry is chained to the previous one with a SHA-256 hash, so that tampering is detectable. At the edge layer, CAN frames are checked for identity and data type, the two FADEC lanes are voted, and telemetry frames sent over the datalink are signed and encrypted. At the infrastructure layer, the system runs in a Docker container as a non-root user with dependencies pinned by hash.

FIG|3.11|fig3_11_security.png|Security Architecture Diagram – Layered Controls and Threats|5.75

## 3.12|Database Design

The application stores its data in several SQLite databases, each with a single responsibility, together with engine definitions in YAML configuration files. The entity-relationship diagram in Fig 3.12 shows the main entities. The Aircraft entity is identified by its tail number and refers to an Engine Config by its engine key. Users are identified by username and hold a role. A Mission is allotted to one aircraft and one operator and records the user who approved it. Defects are raised against an aircraft and optionally linked to the mission in which they were found. The Logbook records every maintenance and operational event for an aircraft, and the Flights entity stores one record per flight with its health summary.

Records that must be synchronised with a fleet server are first serialised into an Outbox table with a unique record identifier, so that a record is sent exactly once even if the link drops. Users, squadron data, flight history and the outbox are stored in separate database files, which keeps credentials isolated from operational data and allows each store to be backed up independently.

The databases are configured for safety against power loss and crashes, which matter for a ground station that may run unattended for a whole mission. The user, squadron and flight-history databases use SQLite's write-ahead logging, so a reader never sees a half-written record, and the user database also forces each committed write to disk. The edge buffer on the aircraft uses write-ahead logging with a lighter synchronisation setting, because it writes telemetry at a high rate and can tolerate the loss of the last moments of data, but must never be corrupted. The audit log is kept as an append-only file in which every entry carries a SHA-256 hash of the previous entry, protected by a secret key, so that removing or changing any entry breaks the chain and is detected by the verification function. Engine definitions are kept outside the databases, in version-controlled YAML files, so that every engine parameter can be reviewed and traced to its source document.


FIG|3.12|fig3_12_er.png|ER Diagram – Application Database|5.75

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


# 4|IMPLEMENTATION DETAILS

The implementation follows the design presented in the previous chapter. Each layer was implemented as a separate Python package with its own tests, and the operator console was implemented as a separate web application. This chapter describes the development environment and process, explains how each module was built, and reports the measures taken to keep the system fast and scalable. The data flow and component interaction diagram in Fig 4.2 is used as a common reference throughout the chapter, because it shows how the implemented classes pass data to each other within one update of the twin.

## 4.1|Development Environment and Tools

The back end is written in Python 3.12. Numerical work uses NumPy and SciPy, combustion chemistry uses Cantera, and machine learning uses PyTorch, scikit-learn and CatBoost, with ONNX Runtime used for the compact edge model. The web server is built with FastAPI and Uvicorn, data models are defined and validated with Pydantic, and CAN communication uses python-can with a CANaerospace message database. Data is stored in SQLite with write-ahead logging, and training data is kept in Parquet files.

The front end is written in TypeScript with React 18 and built with Vite. Its display and alerting rules follow the MIL-STD-1472H human-engineering and MIL-STD-411F aircrew-alerting standards. Version control uses Git with Git LFS for trained models, and continuous integration runs the automated test suite of about one thousand tests on every change. The whole system can be started with a single command, and a Dockerfile is provided for containerised deployment. The project file structure is shown in Fig 4.1.

FIG|4.1|fig4_1_filestructure.png|Project File Structure – Repository Layout|5.75

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


The project was developed using an incremental process model, shown in Fig 4.1.1. After the requirements and literature study, the system was built in four increments: the physics model and edge layer, the AI detection and health models, the twin core with its API and security, and finally the operator console with squadron operations. Each increment passed through design, implementation, testing and integration, and produced a working build that extended the previous one. This model was chosen because each layer depends on the one below it, and because a working build at the end of each increment allowed early testing.

FIG|4.1.1|fig4_1_1_sdlc.png|Process Model – Incremental Development|5.75

The planned timeline of the phase is shown in the Gantt chart in Fig 4.1.2. Testing and evaluation ran in parallel with the later increments, so that each increment was verified as soon as it was integrated.

FIG|4.1.2|fig4_1_2_gantt.png|Gantt Chart – Project Timeline for Phase I|5.75

## 4.2|CAN Data Ingestion and Validation

The CanIngest class receives frames from the bus through python-can. On the development machine a virtual bus is used and the engine simulator encodes real CANaerospace frames onto it; changing one configuration string from virtual to socketcan points the same code at a hardware CAN interface. For each frame, the class checks the identifier and data type against the message database, decodes the value, applies the validation checks, and stores it in a Channel object with a value state. The two FADEC lanes are held as separate readings and voted.

As shown in Fig 4.2, the validated values form a Telemetry object, which is the only input that the rest of the twin receives. Values judged invalid are not removed; they keep their state, so that later stages can decide whether a reading may be used.

FIG|4.2|fig4_2_dataflow.png|Data Flow and Component Interaction Diagram – One Twin Update|5.75

## 4.3|Physics Model Implementation

The engine model is implemented in the layer-two package as a set of sub-models for the atmosphere, air path, turbocharger, combustion and thermal behaviour. The mean-value engine model advances its state with a fixed time step, and the combustion sub-model uses flame properties pre-computed with Cantera for the engine's fuel to keep each step fast. Engine-specific parameters, such as displacement, compression ratio, limits and performance-table data, are loaded from a YAML file, and every value in that file is tagged with its source, such as the type certificate or the operator's manual.

The ShadowModel class wraps the engine model, initialises its thermal state from the first valid telemetry, and on each update returns the as-new outputs for the same operating point, as shown in Fig 4.2. The residual set is then formed by subtracting these outputs from the measured values.

## 4.4|Training Data and Feature Engineering

Because labelled run-to-failure data for this engine does not exist, a fleet generator was implemented to produce it. The generator simulates 200 virtual engines, each with its own build scatter and its own combination of degradation pathways and fault onsets, and flies each one through repeated sorties until failure. Every sample records the measured values, the shadow residuals, and the hidden ground truth, which is used only for evaluation.

The engines are split by engine identifier into training, validation and test sets, with 40 engines held out for testing. A feature contract defines 34 columns, including residuals, operating conditions and derived quantities, and the same contract is used in training and in live operation, so that a model never receives features in a different order from those it was trained on.

The eight fault classes injected into the simulated fleet, and which the system must detect and name, are described in Table 4.2 by their effect on the engine. Each fault is applied with a severity between 0 and 1 and an onset ramp, so that the fleet contains both sudden and gradual failures, and several faults can be present on the same engine.

TABLE|Fault class|Effect on the engine|Main evidence used
ROW|Misfire|One cylinder stops firing cleanly; its exhaust runs cold and rpm roughens|Exhaust spread between cylinders
ROW|Injector abnormality|One injector delivers the wrong amount of fuel|Exhaust temperature split, fuel flow
ROW|Cooling degradation|Coolant carries less heat; head and coolant temperatures climb|Thermal residuals, cooling-flap travel
ROW|Lubrication issue|Oil pressure falls for the engine speed; oil temperature rises|Oil pressure and temperature residuals
ROW|Sensor drift|One instrument drifts while the engine itself is healthy|Disagreement with the twin and other sensors
ROW|Combustion instability|Combustion becomes uneven from cycle to cycle|Exhaust spread and vibration
ROW|Overheating trend|The whole engine runs progressively hotter|All temperature residuals trending upward
ROW|Abnormal vibration|A mechanical vibration source develops|Vibration level and impulsiveness
CAPTION|Table 4.2 Fault Classes in the Training Fleet

## 4.5|Detection Model Implementation

The statistical ensemble is implemented in the Tier2Ensemble class, which fits a cluster-based outlier model and a matrix-profile model on healthy training windows and calibrates their scores to a common scale. The deep detectors are implemented in PyTorch in the Tier3Detector class: an LSTM autoencoder with a sequence length of 30, and a multi-task network with separate heads for anomaly, fault class and severity. Both are trained on the training engines, and their thresholds are selected on the validation engines.

The ScoreFusion class combines the calibrated scores. Several combination rules were evaluated, and the rule with the best validation F1 score was selected, with ties broken by the lower validation false-alarm rate, before the test engines were scored once. For the onboard computer, the deep detector is exported to ONNX format and also quantised to eight-bit integers.

## 4.6|Health and Remaining Life Implementation

The health module computes subsystem indices from residuals and detector outputs and smooths them over time so that a single noisy window does not change the displayed band. The fault-naming model is a gradient-boosted classifier that reads features summarised over each engine's history. The RUL estimator is an LSTM network served by the LstmRulServer class, which first learns the engine's own build offset during an initial stretch of level flight and then predicts remaining hours from the corrected residuals.

The same RUL architecture was trained on the four subsets of the NASA C-MAPSS benchmark without any per-dataset tuning, to check that the estimator itself is sound. A calibration step attaches intervals to the estimate, and the serving code refuses to publish an estimate without a calibrated interval.

## 4.7|Back-End API and Security Implementation

The twin API is implemented with FastAPI and exposes REST endpoints for authentication, engine state, faults, missions, squadron operations, maintenance, replay and reports, together with a WebSocket endpoint that streams the twin state. Each endpoint declares the scope it requires, and a dependency function checks the user's token and role before the endpoint runs. Requests and responses are defined as Pydantic models, so malformed input is rejected before it reaches the application logic.

Authentication issues RS256-signed access and refresh tokens from a key pair generated on first use. Passwords are hashed with bcrypt, a login guard slows repeated failures, and every action that changes state is written to the hash-chained audit log, which can be verified at any time. Squadron operations are implemented in the OpsStore class, which enforces the mission state machine of Fig 3.10.1 and rejects any transition that is not allowed.

The permission check is implemented once, as a FastAPI dependency that every protected endpoint declares. The excerpt below is taken from the project source. A refused request is recorded in the audit log before the error is returned, because refused attempts are often the most important events for a security review.

CODE|def require(scope: str):
CODE|    def _dep(request: Request, c: dict = Depends(claims)) -> dict:
CODE|        role = str(c.get("role", ""))
CODE|        if not sec.has_scope(role, scope):
CODE|            AUDIT.record("AUTHZ_DENY", subject=str(c.get("sub", "?")),
CODE|                         role=role, scope=scope, path=request.url.path)
CODE|            raise HTTPException(403, f"role {role} lacks scope {scope!r}")
CODE|        return c
CODE|    return _dep
CODE|
CODE|@app.post("/api/faults/inject")
CODE|def inject_fault(req: FaultRequest, c: dict = Depends(require("run:simulation"))):
CODE|    ...

Mission transitions follow the same pattern of a single guarded function. Each transition names the states it may start from and the state it leads to, so an out-of-order request, such as launching a mission that has not started its engine, is refused with the mission's current state rather than corrupting the record. The excerpt below shows the shared transition function and the launch step that uses it.

CODE|def _step(self, mid, *, by, role, frm, to, kind, text, stamp=None):
CODE|    with self._lock, self._cx() as cx:
CODE|        m = self._mission(cx, mid)
CODE|        self._own(m, by, role)               # only the allotted operator
CODE|        if m["status"] not in frm:
CODE|            raise OpsError(f"{mid} is {m['status']}")
CODE|        cx.execute("UPDATE missions SET status=? WHERE id=?", (to, mid))
CODE|        self._log(cx, m["tail"], kind, f"{mid}: {text}", by=by, role=role)
CODE|        return self._mission(cx, mid)
CODE|
CODE|def launch(self, mid, *, by, role):
CODE|    return self._step(mid, by=by, role=role, frm=(ENGINE_RUNNING,),
CODE|                      to=AIRBORNE, kind="LAUNCH", text="launch clearance given")


The main endpoints of the API are listed in Table 4.3 with the scope each one requires. In total the server exposes 76 REST endpoints and one WebSocket endpoint; the table shows the most important ones for each function.

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
CAPTION|Table 4.3 Main API Endpoints and Required Scopes


## 4.8|Front-End Console Implementation

The operator console is a single-page React application that receives the twin state over a WebSocket and updates its views in place. After login, each role sees its own navigation: the commander sees Operations, Fleet, Engine, Records and Administration, while the operator sees Mission, Engine, Simulate and History. A strip at the top of every page shows the engine speed and the most important temperatures and pressures, each with the twin's expected value beside it.

Alerts follow the defence alerting standards: each alert has a level, a short title, an explanation and a procedure, and the master warning and master caution annunciators are shown in fixed positions. A three-dimensional model of the engine highlights the part associated with a detected fault. The console displays the development code name of the project, ASTRA, in its title bar.

## 4.9|Performance Optimization and Scalability

Several measures keep the twin within its real-time budget. Combustion properties are pre-computed rather than solved on every update, models are loaded once at start-up, the deep detector runs on batches of windows, and the twin state is pushed to clients over a WebSocket rather than polled. The state is versioned, so that a client that falls behind receives the latest state rather than a backlog.

The results are shown in Fig 4.9. With three clients connected, the twin update took 51 ms at the median and 83 ms at the 95th percentile, well inside the 200 ms budget, and even when pinned to a single processor core the 95th percentile remained at 95 ms. The onboard model is 150 KB in size, answers in 0.64 ms at the median and uses 69 MB of memory, which is about 3.4 % of the memory of the smallest Raspberry Pi; its memory grew by only 0.34 MB over 200 inferences. The eight-bit version is about three times smaller and changed only one decision in 300.

The latency measurements are listed in Table 4.4. Both runs measured the computation of the twin update only, on an x86-64 computer; the single-core run shows the margin that remains when the twin cannot use the other processor cores.

TABLE|Configuration|p50 (ms)|p95 (ms)|p99 (ms)|Budget (ms)
ROW|All cores, 3 clients connected|51.3|82.7|104.4|200
ROW|Pinned to a single core|45.3|95.3|144.0|200
CAPTION|Table 4.4 Twin Update Latency


FIG|4.9|fig4_9_performance.png|Performance and Scalability Analysis – Latency and Edge Footprint|5.75

For scalability across a fleet, each aircraft has its own twin, and a federated learning path exchanges only model weights between stations. In a test with three clients over 25 rounds, 51.92 MB of telemetry stayed on the aircraft while only 12.60 kB of weights crossed the link, and the fleet model matched the centrally trained model at a ROC-AUC of 0.869.

The measurements of this federated learning test are summarised in Table 4.5. Keeping the raw data on each aircraft cost no accuracy, because the federated model reached the same ROC-AUC as a model trained on all the data pooled centrally. A stronger privacy guarantee was also tested by adding differential-privacy noise to the shared weights. At the strict setting of ε = 1 per round, the noise reduced the ROC-AUC from 0.869 to 0.547, a much larger cost than expected; this result is reported rather than hidden, and it shows that useful private training would need more data per round and fewer rounds.

TABLE|Measurement|Value
ROW|Training rounds and participating stations|25 rounds, 3 stations
ROW|Telemetry kept on the aircraft|51.92 MB
ROW|Model weights sent over the link|12.60 kB
ROW|Reduction in data sent|About 4,100 times
ROW|ROC-AUC, all data pooled centrally|0.869
ROW|ROC-AUC, federated (weights only)|0.869
ROW|ROC-AUC, federated with privacy noise (ε = 1)|0.547
CAPTION|Table 4.5 Federated Learning Measurements

Scaling to a larger squadron therefore does not require moving telemetry to a central server. Each ground station runs its own twin for the aircraft it is operating, stores its own flight records, and synchronises only flight summaries and model weights with the optional fleet server. In the present version a ground station operates one aircraft at a time, as a real ground control station does; the other aircraft of the squadron are represented by their last recorded condition until they are next run.


# 5|RESULTS AND DISCUSSION

This chapter evaluates the implemented system. All model results are measured on the 40 engines held out from training, with thresholds fixed on validation engines before the test engines were examined. The chapter is organised by evaluation aspect: handling of inputs and access control, detection accuracy, the twin comparison and early warning, fault diagnosis and alerting, and prognostics and reporting. The screenshots were captured from the running system during a complete demonstration mission, in which a maritime patrol was planned, allotted, flown, recalled after a fault was detected, and debriefed. The chapter closes with the limitations observed and with the mission planning and operator workflow pages of the console.

## 5.1|Input Handling and Data Validation

Every interaction with the system begins at a login page that requires a username and password, and each account belongs to exactly one role. During the demonstration mission the twin processed more than 920,000 CAN frames with no frames lost and none rejected, and every value carried its validity state through the pipeline.


The value of working on validated residuals is shown in Fig 5.1. Across 12,165 evaluation windows, the certified limits raised an alarm in only 77 windows, while 7,558 windows showed genuine degradation with every limit satisfied. The system flagged 6,567 of these, warnings that no threshold monitor could have produced.

FIG|5.1|fig5_1_hidden.png|Analysis Chart – Degradation Missed by Limits and Caught by the Twin|5.75

## 5.2|Detection Accuracy and Validation

The accuracy of the detectors on unseen engines is summarised in Table 5.1 and Fig 5.2. The deep anomaly head was the strongest single detector, but every single detector raised false alarms on about 5 % of healthy windows. Fusing the detectors raised precision to 0.996 and reduced the false-positive rate to 1.0 %, about one fifth of any single detector, at a recall of 0.870.

TABLE|Detector|ROC-AUC|Precision|Recall|FPR
ROW|Statistical ensemble|0.915|0.969|0.530|5.1 %
ROW|LSTM autoencoder|0.916|0.937|0.241|4.9 %
ROW|Deep anomaly head|0.962|0.983|0.936|4.9 %
ROW|Fused detector (final)|0.989|0.996|0.870|1.0 %
CAPTION|Table 5.1 Detection Results on 40 Unseen Engines

FIG|5.2|fig5_2_detection.png|Analysis Chart – Detection Precision, Recall and False Alarms|5.75

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


The engine dashboard in Fig 5.2.1 shows how these results reach the operator. During the climb of the demonstration mission, the engine was assessed as 97 out of 100, Excellent, with each subsystem index above 96 %, and the console stated "No action required."

FIG|5.2.1|shot_engine.png|Screenshot – Engine Health Dashboard During Flight|5.75

## 5.3|Twin Comparison and Early Warning

The central mechanism of the system is the comparison of every reading with the twin's expected value. Fig 5.3 shows why this matters for a cooling fault. As the radiator becomes blocked, the coolant temperature rises only from 98.4 °C to 100.3 °C at 30 % blockage, far below the 120 °C limit, because the cooling flaps open further to compensate. The flap travel, however, rises from 0.49 to 0.68 of its full range, which the twin measures on the first sortie. At 70 % blockage the flaps are fully open and the temperature runs away to 143.7 °C.

FIG|5.3|fig5_3_cooling.png|Analysis Chart – Radiator Blockage: Temperature versus Control Authority|5.75

The operator's mission page in Fig 5.3.1 shows this comparison in practice. For each parameter it lists the current value, the twin's expectation and the difference. During the healthy climb the cylinder head temperature was 115.8 °C against an expected 115.1 °C, and every parameter was reported as "As expected".

FIG|5.3.1|shot_airborne.png|Screenshot – Live Comparison of Measured Values with the Twin|5.75

The accuracy of the twin itself was checked against the manufacturer's published performance table for the Rotax 915 iS, using 130 full-throttle operating points across the altitude range. Table 5.4 gives the median absolute error for each quantity. The small errors confirm that the residuals measure the engine's condition rather than the model's own error.

TABLE|Quantity compared with the manufacturer's table|Median absolute error
ROW|Engine power|1.05 %
ROW|Plenum (boost) pressure|0.43 %
ROW|Fuel flow|1.71 %
ROW|Engine speed|0.20 %
ROW|Charge-air temperature|0.007 K
CAPTION|Table 5.4 Shadow Twin Accuracy against the Manufacturer's Data


## 5.4|Fault Diagnosis and Alerting

To evaluate diagnosis during flight, a misfire of severity 0.8 was injected into the simulated engine while the aircraft was climbing. Within a short time the console raised a caution titled "MISFIRE SUSPECTED", with the explanation that one cylinder was markedly cooler than its siblings, and lit the master caution, as shown in Fig 5.4. The parameter page showed the exhaust of cylinder 1 at 622 °C, marked below normal, while the other cylinders read close to 800 °C.

FIG|5.4|shot_params.png|Screenshot – Misfire Caution and Per-Cylinder Diagnosis|5.75

The three-dimensional engine view in Fig 5.4.1 highlights the affected cylinder and lists the faults that can present at that part, with references to the engine's operator's manual, so that the maintainer knows where to look.

The operator does not need to open the engine pages to notice a fault. As shown in Fig 5.4.2, the alert appears in the alerts panel of every page, including the mission page used during flight, with its level, title, explanation and a button that opens the procedure to follow. The master caution annunciator in the top bar lights at the same time.

Alerts use four levels: advisory, caution, warning and emergency. Advisories are informational and remain on the console. When the engine stops, every caution or higher finding of the twin is written to the aircraft's technical log as a defect, so that it is owned by someone until it is closed. Warning and emergency defects also ground the aircraft until an engineer has dispositioned them or a maintainer has rectified them, which means that an aircraft with a serious unresolved finding cannot be allotted to another mission by mistake.

FIG|5.4.2|shot_alert.png|Screenshot – Caution Alert on the Operator's Mission Page|5.75


FIG|5.4.1|shot_3d.png|Screenshot – Three-Dimensional Engine View with the Faulty Cylinder|5.75

Across the test engines, the ability to name the fault varies by class, as shown in Fig 5.5. Misfire, abnormal vibration, lubrication issues, injector abnormality and overheating trends were named with F1 scores between 0.84 and 0.97, while cooling degradation, sensor drift and combustion instability were weaker. The macro-averaged F1 score across all eight classes was 0.78.

The precision and recall of the fault-naming model for each class are listed in Table 5.5, together with the number of test windows in which each fault was present. The weaker classes fail in different ways: sensor drift has both low precision and low recall, because a drifting instrument can look like a small genuine change; combustion instability is named correctly when it is named, with a precision of 0.80, but it is often missed, with a recall of only 0.32.

TABLE|Fault class|Precision|Recall|F1|Test windows
ROW|Misfire|0.97|0.97|0.97|4,254
ROW|Abnormal vibration|1.00|0.88|0.94|6,975
ROW|Lubrication issue|0.97|0.88|0.93|19,645
ROW|Injector abnormality|0.85|0.87|0.86|7,644
ROW|Overheating trend|0.84|0.84|0.84|3,621
ROW|Cooling degradation|0.62|0.83|0.71|5,269
ROW|Sensor drift|0.55|0.53|0.54|16,656
ROW|Combustion instability|0.80|0.32|0.46|5,594
CAPTION|Table 5.5 Fault Naming Precision and Recall by Class


## 5.5|Prognostics and Reporting

The fault-naming results discussed above are summarised in Fig 5.5. For remaining life, the RUL architecture was evaluated on the NASA C-MAPSS benchmark, where its root-mean-square error was within 8 to 18 % of published state-of-the-art results on all four subsets without tuning, as listed in Table 5.6.

FIG|5.5|fig5_5_faults.png|Analysis Chart – Fault Naming F1 Score by Class|5.75

TABLE|Subset|AeroTwin RMSE|Published best RMSE|Ratio
ROW|FD001|14.84|12.6|1.18
ROW|FD002|14.18|13.1|1.08
ROW|FD003|13.65|12.7|1.08
ROW|FD004|15.59|14.0|1.11
CAPTION|Table 5.6 Remaining Useful Life Error on the NASA C-MAPSS Benchmark

After each flight the system produces a report, shown in Fig 5.5.1, which can be exported as PDF, CSV or JSON. For the demonstration flight it recorded 0.40 engine hours, life-to-date extremes and a final health index of 0.771, Fair. Because the injected misfire had driven the combustion index down, the report advised grounding the aircraft, and it showed the remaining-life estimate explicitly marked as having no calibrated interval.

FIG|5.5.1|shot_records.png|Screenshot – Post-Flight Engine Report|5.75

The engineer's squadron view, shown in Fig 5.5.2, compares the last recorded health of every aircraft. After the demonstration flight, MALE-01 showed an overall health of 76.8 % with a combustion index of only 12.1 %, which immediately identifies the subsystem affected by the injected misfire, while the thermal, mechanical and electrical indices remained above 96 %. The view also lists engine hours, hours to the next inspection and the remaining time before overhaul for each aircraft.

The same view supports maintenance planning across the squadron. Engine hours are tracked per aircraft from its logbook; in the demonstration squadron, MALE-01 started with a new engine, MALE-02 with 420 engine hours and MALE-03 with 960. For each engine the console shows the hours remaining to the next 100-hour inspection, which includes the oil change, and the hours remaining to the manufacturer's overhaul interval of 1,200 hours. An aircraft that passes either limit cannot be allotted to a mission. Combined with the twin's health indices, this lets the engineer see at a glance which aircraft are healthy and available and which need attention first.

FIG|5.5.2|shot_squadron.png|Screenshot – Squadron Engine Health Comparison|5.75


## 5.6|Limitations Observed

First, all fault data used for training and testing comes from the physics-based simulator, because no real Rotax 915 iS engine or test bench was available during this phase. The transfer of the models to a real engine has therefore not yet been demonstrated. On real flight records from the NGAFID dataset of piston aircraft, the same approach reached a ROC-AUC of 0.77 against a published 0.83, which shows that real data remains harder than simulated data.

Second, naming which fault is present is weaker than detecting that a fault exists. Three of the eight classes, namely cooling degradation, sensor drift and combustion instability, have F1 scores below 0.80, and per-class scores move by about 0.10 between training runs because each class is carried by only five to twelve test engines.

Third, the remaining-life intervals are not yet calibrated to their nominal coverage, which is why the console withholds a remaining-life figure in most situations. The fusion threshold also trades recall for precision, so about one in eight degraded windows is not flagged.

Lastly, the latency figures were measured on an x86-64 computer rather than on an ARM edge computer, and the diesel engine profile included in the squadron is a placeholder rather than a validated model. These limitations define the main work for the second phase of the project.

Table 5.7 pairs each limitation with the work planned for the second phase of the project to remove it.

TABLE|Limitation observed|Planned Phase-II work
ROW|Fault data is simulated; no real-engine validation|Hardware-in-the-loop with a CAN adapter, then engine test-bench runs
ROW|Three of eight fault classes named below F1 0.80|Targeted fault data and features for cooling, sensor drift and combustion
ROW|Remaining-life intervals not yet calibrated|Calibrate intervals on held-out engines; publish coverage
ROW|Latency measured only on x86-64|Measure on the ARM edge computer under flight-like load
ROW|Real-flight score below the published baseline|Fine-tune on real piston-engine flight data
ROW|Diesel engine profile is a placeholder|Build and validate a second engine model from its manuals
CAPTION|Table 5.7 Limitations and Planned Phase-II Work


## 5.7|Mission Planning Pages

The commander's operations page, shown in Fig 5.7, gives an overview of the squadron. It contains the following elements:

- A readiness card for each aircraft, showing its engine, release status, last assessed health and endurance limit
- A mission board with columns for planned, approved, in-progress, debrief and completed missions
- An alerts panel and a "Waiting on you" list of actions required from the commander
- A Plan mission button that opens the mission form with task, endurance, altitude, conditions and area

FIG|5.7|shot_ops.png|Screenshot – Commander Operations Page|5.75

When a mission is selected, the commander allots an aircraft and an operator through the chooser shown in Fig 5.7.1. Aircraft that are serviceable are marked as assignable, and an aircraft that cannot be used, such as one awaiting inspection, is marked unavailable with the reason.

FIG|5.7.1|shot_allot.png|Screenshot – Aircraft and Operator Allotment|5.75

## 5.8|Operator Mission Workflow

The operator follows a five-step workflow for each mission: brief, pre-flight, engine, airborne and debrief. The pre-flight page, shown in Fig 5.8, requires the following confirmations before the engine can be started:

- Mission brief received, technical log checked and operating limitations reviewed
- Fuel and payload confirmed for the planned endurance
- Ground station datalink established and the twin's pre-flight status reviewed
- Weather within limits and the lost-link and recovery procedure set

FIG|5.8|shot_preflight.png|Screenshot – Pre-Flight Checklist|5.75

After shutdown, the operator completes the debrief shown in Fig 5.8.1 by selecting the outcome, adding remarks and reporting any snags. The page also summarises the sortie: flight time, limits crossed, health at the end of the flight and data coverage. Reported snags are entered on the aircraft's technical log as defects, and the aircraft's release is withdrawn until maintenance inspects it.

FIG|5.8.1|shot_debrief.png|Screenshot – Post-Flight Debrief|5.75

The maintenance view in Fig 5.8.2 closes the loop. The snag reported in the debrief appears as an open caution defect on MALE-01, the aircraft is shown as awaiting inspection, and the maintainer can rectify the defect, run the engine on the ground to verify the repair, and sign the release that makes the aircraft available for the next mission.

FIG|5.8.2|shot_defects.png|Screenshot – Maintenance Technical Log with the Raised Defect|5.75

The complete demonstration mission is summarised in Table 5.8. The simulated engine ran at twenty times real time, so the 24-minute flight took a little over a minute of wall-clock time while every protection, check and record behaved exactly as it would in a real sortie.

TABLE|Step|Event|Role|System response
ROW|1|Three aircraft inspected and released|Maintenance|Aircraft marked serviceable
ROW|2|Mission MSN-0001 planned: maritime patrol, 8 h at 12,000 ft|Commander|Mission in PLANNED state
ROW|3|MALE-01 and operator allotted|Commander|Unreleased TAPAS-01 shown unavailable
ROW|4|Aircraft prepared, eight checklist items confirmed|Operator|Mission in PREFLIGHT, then ENGINE_RUNNING
ROW|5|Launch requested during warm-up|Operator|Refused until oil reached 50 °C
ROW|6|Launch and climb|Operator|Health 97 / 100, all readings as expected
ROW|7|Misfire of severity 0.8 injected|Engineer|Caution MISFIRE SUSPECTED, cylinder 1 highlighted
ROW|8|Aircraft recalled and landed|Operator|RTB, then AWAITING_DEBRIEF after shutdown
ROW|9|Debrief: partial, snag reported|Operator|Defect #1 on the technical log
ROW|10|Release withdrawn|System|MALE-01 awaiting inspection; health 77, FAIR
CAPTION|Table 5.8 Event Sequence of the Demonstration Mission

The sequence shows the purpose of the system in a single sortie: a fault that no certified limit had flagged was detected in flight, located to a cylinder, turned into a recall decision, and carried through to a maintenance action before the aircraft could be dispatched again.

# 0|CONCLUSION

This project designed and implemented AeroTwin, a real-time digital twin for the piston engine of a long-endurance unmanned aircraft. The system combines a physics-based model of the Rotax 915 iS engine, held permanently in an as-new condition, with statistical and deep-learning detectors, health indices, fault naming, remaining-life estimation and mission reliability assessment, and it delivers the results to four user roles through a secure web console.

The key capability of the system is that it detects engine degradation before any certified limit is crossed. In the evaluation data, certified limits alarmed in only 77 windows while 7,558 windows showed real degradation within limits; the twin flagged 6,567 of them. This matters because a single-engine unmanned aircraft has no pilot to notice a gradual problem, and an early warning allows the mission to be recalled and maintenance to be planned before a failure.

The quality of the warnings comes from the comparison with the as-new twin and from the agreement between independent detectors. Working on residuals removes the effect of altitude, throttle and temperature, and fusing the detectors raised alarm precision to 0.996 while reducing false alarms on healthy engines to about 1 %. The supporting modules, namely edge safety rules, mission ranking and the squadron workflow, turn these findings into practical decisions.

Despite its strengths, the system has clear limits that define the future scope. The models have been trained and tested on simulated engines, so the next phase will connect the system to real engine hardware through a CAN interface, validate it on an engine test bench, and then move towards flight trials. Further work is needed on the weaker fault classes, on calibrated intervals for remaining life, on timing measurements on the onboard ARM computer, and on support for other engines, including indigenous designs, through new configuration files.

Overall, this project serves as a foundational prototype for condition-based maintenance of unmanned aircraft engines. It shows that physics and machine learning can be combined into a system that is accurate, explainable, offline and affordable, and it provides a tested platform on which the second phase of the project can build.
