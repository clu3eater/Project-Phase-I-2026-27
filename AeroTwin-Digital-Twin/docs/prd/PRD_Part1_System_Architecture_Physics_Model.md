================================================================================
!! REVISION 2 - 27 August 2026 !!  READ THIS BEFORE ANYTHING BELOW
================================================================================
This document was issued at Revision 1 against the Rotax 914 as reference
engine. It has since been corrected against primary source documents. Where
this notice and the body text disagree, THIS NOTICE WINS.

WHAT CHANGED AT REVISION 2
  1. REFERENCE ENGINE: Rotax 914  ->  ROTAX 915 iS / iSc A.
     The 914 is carburetted, with no FADEC and no CAN bus, so it cannot
     support this document's own CAN-acquisition and ECU/FADEC requirements.
     The 915 iS carries a CERTIFIED DUAL-CHANNEL FADEC with a Display CAN bus
     and a Maintenance CAN bus on each lane.
     [REVISED AGAIN] The 914 profile has since been REMOVED entirely rather
     than retained as a secondary. An engine this framework could never
     actually acquire from is a poor advertisement for engine-agnosticism.
     The claim is now carried by the Austro AE330 turbo-diesel adaptation
     stub, which is a far stronger demonstration: compression ignition on
     Jet-A1 at 18:1 against spark ignition on Avgas at 10.5:1, and it is the
     engine of the DRDO TAPAS-BH-201 (Rustom-II) itself.

  2. OPERATING LIMITS are now the CERTIFIED limits of the reference engine,
     not the air-cooled-engine bands originally written here. The 915 iS has
     LIQUID-COOLED cylinder heads: the certified thermal limit is COOLANT
     temperature at 120 degC, and EGT at 950 degC with a 200 degC split limit.

  3. The CAN bus is CANAEROSPACE, not an ad-hoc identifier set.

SOURCE DOCUMENTS (all held locally in `engines manuals/`)
  [TCDS] EASA Type Certificate Data Sheet E.121, Issue 17, 18 December 2023
  [OM]   BRP-Rotax Operators Manual OM-915 i, Ed. 0 Rev. 4, 01 September 2022
  [IM]   BRP-Rotax Installation Manual IM-915 i A/C24, Ed. 0 Rev. 5, 01 Feb 2024
  [MML]  BRP-Rotax Maintenance Manual Line MML-915 i, Ed. 0 Rev. 3, 01 May 2025
  [MMH]  BRP-Rotax Maintenance Manual Heavy MMH-915 i A/C24, Ed. 1 Rev. 0
  [CANAS] CANaerospace Interface Specification Rev. 1.6, Stock Flight Systems

EVERY DEPARTURE FROM REVISION 1 IS LOGGED WITH ITS EVIDENCE IN
  docs/PRD_DEVIATIONS.md   (29 entries)
COMPLIANCE AGAINST THE PROBLEM STATEMENT IS MACHINE-CHECKED BY
  python scripts/ps_compliance.py   and   pytest tests/
================================================================================


================================================================================
TECHNICAL PRODUCT REQUIREMENTS DOCUMENT (PRD) — PART 1 of 3
SIH 2026 / DRDO IDEX Problem Statement 26054
AI-Enabled Real-Time Digital Twin for Aero Piston Engines in MALE UAVs
================================================================================
Document Version: 1.0
Date: 22 August 2026
Classification: Internal Technical Document
Organization Context: DRDO / Department of Defence Production / IDEX
================================================================================

TABLE OF CONTENTS — PRD PART 1
================================================================================
1. Executive Summary & DRDO Strategic Context
2. System Architecture Specification
3. Data Acquisition & Edge Connectivity Layer
4. Physics-Based Engine Model — Thermodynamic Foundation
5. Engine Performance Maps & Degradation Modeling
6. Digital Twin Core Framework Specification
7. Real-Time Data Ingestion & Synchronization Protocol
8. Sensor Fusion & Signal Processing Architecture

================================================================================
1. EXECUTIVE SUMMARY & DRDO STRATEGIC CONTEXT
================================================================================

1.1 Problem Domain
------------------
Medium Altitude Long Endurance (MALE) Unmanned Aerial Vehicles (UAVs) deployed
by the Indian Armed Forces (IAF, Indian Navy, Indian Army) for Intelligence,
Surveillance, and Reconnaissance (ISR), communication relay, maritime
surveillance, and strategic defence missions require propulsion system
reliability exceeding 99.5% mission availability. Current threshold-based,
reactive monitoring systems indicate failures only after abnormality has
occurred, resulting in mission aborts, asset losses (₹50+ crore per TAPAS-BH-201
airframe), and unsafe recovery conditions.

1.2 DRDO Context & Alignment
------------------------------
This solution addresses DRDO's live Technology Development Fund (TDF) RFP
(November 2025) for "Digital Twin Framework for Aero Engine Health & Usage
Monitoring System (HUMS)" and aligns with the indigenous engine development
programs at VRDE (Ahmednagar) and CVRDE (Avadi). The framework is designed to
support DRDO's MALE UAV programs developed by ADE Bangalore, with production
integration by HAL and avionics by BEL.

IMPORTANT — ENGINE / PLATFORM SCOPE (accuracy note) [REVISED AT REV 2]:
NOTE: the paragraph below described the Rotax 914 as the reference engine.
The reference engine is now the ROTAX 915 iS / iSc A. Read §1.3 for the
current specification. The reasoning about engine-agnosticism is unchanged
and still applies — it is demonstrated across two engine profiles that differ
fundamentally (915 iS spark/Avgas reference, Austro AE330 compression/Jet-A1
adaptation stub). The 914 profile was removed; see the Revision 2 notice.
The problem statement targets "aero piston engines used in MALE UAVs"
generically and does NOT mandate a specific engine. This framework is
deliberately ENGINE-AGNOSTIC (see §6.3 twin registry with per-engine YAML
configuration). For a concrete, well-documented, and defensible demonstration
we model the Rotax 914 F/UL class spark-ignition aero piston engine. The
platform-engine pairing is stated explicitly to avoid any factual inaccuracy:
  • Rotax 914 (spark-ignition, gasoline/Avgas)  → DRDO Rustom-I, IAI Heron,
    IAI Searcher, General Atomics MQ-1 Predator. This is our REFERENCE/DEMO
    engine.
  • TAPAS-BH-201 (Rustom-II)  → powered by twin Austro AE330-class turbo-DIESEL
    (compression-ignition, Jet-A1) engines — NOT the Rotax 914. Supporting
    TAPAS is a planned future adaptation that requires swapping ONLY the
    combustion sub-model (§4) from spark-ignition (Cantera + Wiebe SI) to
    compression-ignition (diesel injection + heat-release). Every other layer —
    data acquisition (§3), digital-twin core (§6), AI/ML analytics, health
    monitoring, visualization, and security — is reused unchanged.
This honest framing keeps every specification in this PRD valid while making the
migration path to the actual TAPAS diesel engine explicit, modular, and
low-risk. It also demonstrates domain awareness that DRDO evaluators expect.

1.3 Reference (Demonstration) Engine: Rotax 914 Class Aero Piston Engine
------------------------------------------------------------------------
The reference engine for the demonstrator is the Rotax 914 F/UL class 4-stroke,
turbocharged, horizontally-opposed, spark-ignition aero piston engine — the
global standard for gasoline MALE/tactical UAV propulsion (DRDO Rustom-I, IAI
Heron, IAI Searcher, MQ-1 Predator). It is chosen because (a) its performance
data is publicly documented, enabling HONEST model validation, and (b) it
exercises every capability required by the problem statement (turbocharging,
altitude effects, per-cylinder CHT/EGT, dual ignition, injection timing).

ENGINE SPECIFICATIONS — ROTAX 915 iS / iSc A  [REVISED AT REV 2]
Every figure below is from a primary source, tagged accordingly.
• Type: 4-cylinder, 4-stroke, horizontally opposed, spark ignition   [TCDS]
• Bore × Stroke: 84.0 mm × 61.0 mm                                   [TCDS]
• Displacement: 1,352 cm³ (82.5 cu in)                               [TCDS]
• Compression Ratio: 8.2:1                                           [TCDS]
• Reduction gear ratio (crankshaft : propeller): 2.5454 : 1          [TCDS]
• Take-off Power: 104 kW (141 hp) at 5,800 rpm, max 5 minutes        [TCDS §6]
• Max Continuous Power: 99 kW (135 hp) at 5,500 rpm, available up to
  the critical altitude                                              [TCDS §6]
• Max Torque: 171.9 N·m — DERIVED. Rotax publishes no peak-torque figure
  for this engine; both certified ratings imply ~172 N·m, so the curve is
  flat across the top of the range.
• Idle speed: minimum 1,800 rpm                                      [OM §2.1]
• Critical Altitude: 15,000 ft (at MAT ≤ 50 °C)                      [TCDS/OM]
• Max Operating Altitude: 23,000 ft                                  [TCDS/OM]
• Mass: 82.2 kg with gearbox, turbocharger, intercooler and exhaust  [Data sheet]
• TBO: 1,200 hours OR 15 years, whichever comes first                [MML §05-10-00]
• Cooling: LIQUID-COOLED cylinder heads, ram-air cooled cylinders    [TCDS §2]
• Lubrication: dry sump, separate oil tank; max oil consumption
  0.06 L/h                                                           [TCDS, OM §2.4]
• Fuel: min MON 85 / RON 95 / AKI 91; AVGAS 100LL and E10 permitted  [Data sheet]
• Engine control: CERTIFIED DUAL-CHANNEL FADEC (Lane A / Lane B) for both
  ignition AND injection                                             [TCDS §2]
• Ignition: 4 double ignition coils, electronically generated,
  "almost entirely wear-free"                                        [OM §7.5.2]
• Fuel system: electronic port fuel injection, 8 injectors (2 per cylinder,
  one per lane). Fuel quantity / injection period is metered from the
  CALCULATED AIR DENSITY IN THE AIRBOX — a speed-density strategy   [OM §7.5.3]
• Fuel rail pressure: 2.9 – 3.2 bar (transient 2.5 – 3.5 bar, ≤3 s) [OM §2.1]
• Turbocharger: wastegate-controlled WITH INTERCOOLER. Boost controller
  targets 1,450 mbar at 5,500 rpm and 1,520 mbar at 5,800 rpm;
  1,730 mbar is a NEVER-EXCEED value, not a setpoint                 [OM §2.1]
• Electrical: two internal generators (Gen 1 → EMS, Gen 2 → airframe);
  the iSc C24 variant carries a 28 V system interface   [OM §4.1.1, TCDS §2]
• Data buses: Display CAN and Maintenance CAN on EACH lane — four buses —
  on Harness Interface Connectors A and B, plus a 12 V / 120 mA warning
  lamp per lane. The Display CAN is based on the CANaerospace
  protocol                                                          [IM ch. 77-00-00]

1.4 Document Scope
------------------
This PRD defines the complete technical specification for building an
indigenous, zero-cost, open-source Digital Twin framework. It covers:
• System architecture (5-layer modular stack)
• Data acquisition protocols (CAN bus, sensor mapping, edge computing)
• Physics-based thermodynamic and mean-value engine models
• Engine performance map representations
• Degradation and failure pathway modeling
• Digital twin state management and synchronization
• Real-time ingestion pipelines and latency requirements

================================================================================
2. SYSTEM ARCHITECTURE SPECIFICATION
================================================================================

2.1 Architectural Philosophy
------------------------------
The system shall adopt a Modular Open Systems Approach (MOSA) aligned with
STANAG 4586 (NATO UAV GCS interoperability) and DRDO's own GCS design
principles (open architecture, COTS technology, distributed computing,
incremental enhancement) as documented in ADE Bangalore's Defence Science
Journal paper on Ground Control Stations for UAVs.

2.2 Five-Layer Modular Stack
----------------------------

┌─────────────────────────────────────────────────────────────────────────────┐
│ LAYER 5: VISUALIZATION & HMI                                               │
│ Purpose: Real-time operational interface for operators, engineers,         │
│          maintenance teams                                                   │
│ Components: Grafana Dashboard, Streamlit HMI, Alert Notification System    │
│ Latency Requirement: Dashboard refresh ≤ 2 seconds                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ LAYER 4: DIGITAL TWIN CORE & STATE MANAGEMENT                              │
│ Purpose: Central intelligence layer, continuous synchronization of virtual │
│          representation with physical engine                                 │
│ Components: Eclipse Ditto (or Flask-based DTOP), MQTT Broker, InfluxDB,    │
│             REST API Gateway, JSON Schema Validator                        │
│ Latency Requirement: State sync ≤ 100 ms                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│ LAYER 3: AI/ML PREDICTIVE ANALYTICS                                        │
│ Purpose: Adaptive learning, predictive diagnostics, intelligent maintenance│
│          planning                                                            │
│ Components: PyOD Ensemble, ADTK Rules Engine, LSTM/GRU Networks,           │
│             SHAP/LIME Explainers, Fault Classifier Bank                    │
│ Latency Requirement: Anomaly detection ≤ 50 ms; RUL inference ≤ 100 ms     │
├─────────────────────────────────────────────────────────────────────────────┤
│ LAYER 2: PHYSICS-BASED ENGINE MODEL & SIMULATION                           │
│ Purpose: Thermodynamic behavior prediction, combustion quality assessment, │
│          degradation factor estimation                                       │
│ Components: Cantera Combustion Suite, 0-D Mean-Value Engine Model (MVEM),  │
│             Performance Map Interpolator, Degradation Tracker              │
│ Latency Requirement: Model update ≤ 20 ms                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│ LAYER 1: DATA ACQUISITION & EDGE CONNECTIVITY                              │
│ Purpose: Real-time sensor data ingestion, CAN bus communication, edge      │
│          preprocessing, telemetry transmission                               │
│ Components: SocketCAN/vcan, python-can, CANdevStudio, Edge Node (RPi),     │
│             MAVLink Bridge, Sensor Fusion Module                           │
│ Latency Requirement: Sensor-to-ingestion ≤ 10 ms                           │
└─────────────────────────────────────────────────────────────────────────────┘

2.3 Inter-Layer Communication Protocols
----------------------------------------
• Layer 1 → Layer 2: ZeroMQ or shared memory (intra-process, <1ms)
• Layer 2 → Layer 3: MQTT publish/subscribe (topic: dt/engine/model/update)
• Layer 3 → Layer 4: MQTT + REST API (state update + query response)
• Layer 4 → Layer 5: WebSocket (Grafana Live) + REST (dashboard queries)
• Cross-layer: InfluxDB Line Protocol for time-series persistence

2.4 Modularity & Scalability Requirements
------------------------------------------
• Each layer must be independently deployable as a Docker container
• Layer interfaces must be versioned REST APIs with OpenAPI 3.0 specification
• Adding a new engine to the fleet shall require zero code changes — only
  configuration of a new twin_id in the twin registry
• Fleet-level monitoring shall support minimum 100 concurrent engine twins
  without performance degradation
• Horizontal scaling of Layer 3 (AI/ML) shall be achievable via Kubernetes
  HPA (Horizontal Pod Autoscaler) based on inference queue depth

2.5 Defense-Grade Requirements
-------------------------------
• All inter-layer communication shall use TLS 1.3 encryption
• Data at rest in InfluxDB shall use AES-256 encryption
• Authentication: JWT tokens with RS256 signing, 15-minute expiry
• Authorization: RBAC with 4 roles — Operator, Engineer, Commander, Maintenance
• Network segmentation: vcan network → Edge Gateway (DMZ) → Secure LAN → GCS
• Audit logging: All state mutations, alert generations, and model updates
  shall be logged with UTC timestamp, user_id, and change_hash
• Compliance: Conceptual alignment with NIST 800-171, DO-326A (cybersecurity),
  and DEF STAN 00-82 (defence software)

================================================================================
3. DATA ACQUISITION & EDGE CONNECTIVITY LAYER
================================================================================

3.1 Sensor Parameter Specification (All 8 Required Parameters)
--------------------------------------------------------------

PARAMETER 1: RPM (Engine Speed)
• Sensor Type: Magnetic pickup / Hall effect on flywheel
• Measurement Range: 0 – 6,000 rpm
• Resolution: 1 rpm
• Sampling Rate: 100 Hz (for misfire detection via fluctuation analysis)
• CAN Message ID: 0x100 (byte 0-1: uint16, big-endian)
• Normal Operating Range: 2,000 – 5,500 rpm
• Alert Threshold: >5,800 rpm (overspeed) or <1,500 rpm (underspeed stall)
• Critical Threshold: >6,000 rpm (engine overspeed protection) or <800 rpm
  (engine stall imminent)

PARAMETER 2: CHT (Cylinder Head Temperature)
• Sensor Type: K-type thermocouple per cylinder head
• Measurement Range: 0 – 350°C
• Resolution: 0.1°C
• Sampling Rate: 10 Hz
• CAN Message ID: 0x101 (bytes 0-1: cyl1, 2-3: cyl2, 4-5: cyl3, 6-7: cyl4)
• [REVISED AT REV 2] The bands below were air-cooled Lycoming/Continental
  figures. The reference engine has LIQUID-COOLED heads.
• Normal Operating Range: 80°C – 120°C (per cylinder)
• Alert Threshold: >125°C, or cylinder-to-cylinder spread >15°C
• Critical Threshold: >135°C — the Rotax family CHT limit [TCDS, 912 S series]
• NOTE ON INSTRUMENTATION: per-cylinder CHT is NOT fitted to a standard
  915 iS, which carries a single Coolant Temperature Sensor on cylinder
  head 4 [OM §7.2]. The problem statement requires CHT monitoring, so this
  project specifies the per-cylinder thermocouples as ADDED HUMS
  instrumentation and says so explicitly.
• THE CERTIFIED THERMAL LIMIT for this engine is COOLANT temperature:
  120°C in normal operation, measured by the CTS [TCDS, OM §2.1].
  The twin monitors both.
• Physics Model: two-node thermal model — head metal and a thermostatted
  coolant loop, integrated separately. Scale build-up degrades the
  HEAD-TO-COOLANT path, so CHT rises while the thermostat holds coolant
  steady; the widening CHT-minus-coolant delta is the cooling-degradation
  signature. A single-node model cannot produce it.

PARAMETER 3: EGT (Exhaust Gas Temperature)
• Sensor Type: K-type thermocouple per exhaust port
• Measurement Range: 0 – 1,000°C
• Resolution: 0.5°C
• Sampling Rate: 10 Hz
• CAN Message ID: 0x102 (bytes 0-1: cyl1, 2-3: cyl2, 4-5: cyl3, 6-7: cyl4)
• [REVISED AT REV 2] The bands below were naturally-aspirated figures.
• Normal Operating Range: 700°C – 900°C (per cylinder)
• Alert Threshold: >920°C
• Critical Threshold: >950°C — CERTIFIED LIMIT [OM §2.1]
• EGT-SPLIT LIMIT (certified): 200°C above 3 L/hr fuel flow, 500°C below it
  [OM §2.1]. "EGT-Split is the difference between the actual highest EGT
  value of the actual lowest EGT value."
• Physics Model: THREE-STAGE chain, not a single formula — (1) expansion from
  the adiabatic flame temperature to exhaust valve opening, (2) blowdown to
  manifold pressure, (3) pipe heat loss. The Rev 1 formula omitted the
  expansion stroke entirely and predicted ~1,683°C. See PRD_DEVIATIONS DEV-12.

PARAMETER 4: Oil Pressure
• Sensor Type: Piezoresistive pressure transducer
• Measurement Range: 0 – 100 psi
• Resolution: 0.1 psi
• Sampling Rate: 10 Hz
• CAN Message ID: 0x103 (byte 0-1: uint16, 0.1 psi/LSB)
• [REVISED AT REV 2 to the certified limits, OM §2.1]
• Normal Operating Range: 2.0 – 5.0 bar (29 – 72.5 psi) above 3,500 rpm
• Below 3,500 rpm the minimum is 0.8 bar (11.6 psi)
• Critical: 7.0 bar (101.5 psi), permitted only briefly at cold start
• Physics Model: Oil pressure = f(RPM, oil viscosity, temperature, bearing
  clearance). Degradation tracked via pressure vs RPM correlation drift.

PARAMETER 5: Oil Temperature
• Sensor Type: RTD (Pt100) in oil sump
• Measurement Range: 0 – 150°C
• Resolution: 0.1°C
• Sampling Rate: 1 Hz
• CAN Message ID: 0x104 (byte 0-1: int16, 0.1°C/LSB, offset -40°C)
• [CONFIRMED AT REV 2 against OM §2.1 — these were already correct]
• Recommended Operating Range: 90°C – 110°C. Running below 90°C risks
  condensation in the lubrication system; 100°C must be reached at least
  once a day to evaporate it.
• Normal operation band: 50°C – 130°C; minimum 50°C for take-off
• Minimum for engine start: −20°C
• Critical Threshold: >130°C — CERTIFIED LIMIT [TCDS, OM §2.1]
• Physics Model: Oil temperature rise from bearing friction + combustion heat
  transfer to sump. Degradation: viscosity model μ(t) = μ₀·exp(β·T_avg·t).

PARAMETER 6: Fuel Flow
• Sensor Type: Turbine flow meter (positive displacement optional)
• Measurement Range: 0 – 30 L/hr
• Resolution: 0.01 L/hr
• Sampling Rate: 10 Hz
• CAN Message ID: 0x105 (bytes 0-3: float32, L/hr)
• [REVISED AT REV 2 — the reference engine is larger and turbocharged]
• Normal Operating Range: 8 – 42 L/hr. Derived from the certified ratings and
  the published 280–310 g/kWh SFC band: 99 kW × 0.295 kg/kWh ≈ 29.2 kg/h
  ≈ 40.6 L/hr at max continuous, falling to roughly 18–22 L/hr at a 60%
  cruise setting.
• Alert Threshold: <6 L/hr or >46 L/hr
• Critical Threshold: <3 L/hr or >52 L/hr
• Physics Model: Fuel flow = f(BSFC, BMEP, RPM, altitude). Degradation tracked
  via BSFC trend (brake specific fuel consumption increase over time).

PARAMETER 7: Vibration Signatures
• Sensor Type: Tri-axial MEMS accelerometer (ADXL355 or equivalent)
• Measurement Range: ±50 g
• Resolution: 0.001 g
• Sampling Rate: 10,000 Hz (for FFT analysis up to 5 kHz)
• CAN Message ID: 0x106 (RMS data at 10 Hz; raw waveform via high-speed bus)
• Normal Operating Range: RMS < 3.5 m/s² (broadband, 10-1000 Hz)
• Alert Threshold: RMS > 5 m/s² or peak at bearing frequencies
• Critical Threshold: RMS > 8 m/s² or peak at gear mesh frequencies
• Physics Model: Vibration spectrum analyzed for:
  - 1× RPM: Unbalance
  - 2× RPM: Misalignment
  - Gear mesh frequencies (reduction gear): Gear wear
  - Bearing BPFO/BPFI: Bearing defects
  - Blade pass frequency: Propeller issues

PARAMETER 8: Battery / Alternator Health
• Battery Voltage Sensor: Resistive divider, 0-20V range, 0.01V resolution
• Alternator Current Sensor: Hall effect, 0-50A range, 0.1A resolution
• Sampling Rate: 10 Hz
• CAN Message ID: 0x107 (byte 0-1: voltage, byte 2-3: current)
• Normal Operating Range: 13.5V – 14.5V (charging), 0A – 15A (alternator load)
• Alert Threshold: <13.0V (undercharge) or >15.0V (overcharge/regulator fault)
• Critical Threshold: <12.0V (battery failure) or >15.5V (electrical damage)
• Physics Model: Battery state-of-health from voltage stability under load,
  internal resistance trend, and charge/discharge cycle count.

PARAMETER 9: Injection Timing  [SUBSTANTIALLY REVISED AT REV 2]

Revision 1 conflated two distinct quantities under one heading. On a FADEC
engine with port fuel injection they are separate, separately scheduled, and
separately diagnostic. Both are now monitored, and a third — the injection
period — is added because it is the engine's PRIMARY fuel-metering command.

9a. IGNITION TIMING  (this is what Rev 1's "15°–26° BTDC" actually described)
• Sensor: crankshaft position sensors CPS1/CPS2 + camshaft position sensor CCS
• Range 0° – 60° BTDC, resolution 0.1°, 100 Hz (per ignition event)
• Normal Operating Range: 5° – 35° BTDC, ECU-scheduled from speed and load
• Alert: deviation > ±2° from command; Critical: > ±5°
• KNOCK RETARD is monitored separately: alert at 6°, critical at 10° of
  commanded retard. A rising retard trend at constant power is an early
  combustion-quality indicator AND an early cooling-degradation indicator,
  because knock tendency rises with charge temperature.
• CAN: measured per cylinder on CANaerospace user-defined id 1804; the ECU's
  commanded value on id 1805.

9b. INJECTION TIMING (start of injection)
• Measured per cylinder from crank/cam position sensing
• Reported in degrees before the FIRING TDC. Port injection is a
  closed-valve event during the exhaust/intake phase of the 720° cycle, so
  the absolute angle is large (~370° BTDC). It is the DEVIATION that carries
  the diagnosis, not the absolute value.
• Alert: deviation > ±1°; Critical: > ±3°  [PRD Part 2 §10.2 Method C]
  These are TIGHTER than 9a's ±2°/±5°, which apply to ignition.
• DIAGNOSTIC MECHANISM: a real ECU compensates the injector's characterised
  nominal dead time, so a healthy engine shows ~zero deviation. What it
  cannot compensate is the EXTRA opening delay that fouling and solenoid wear
  introduce, because it has no feedback on needle lift. Crucially, a fixed
  millisecond delay subtends MORE CRANK ANGLE at higher rpm — so injector
  wear produces a speed-dependent deviation, while a sensor bias does not.
  That distinction is what separates the two faults.
• CAN: measured per cylinder on id 1803; commanded on id 1805.

9c. INJECTION PERIOD (pulse width)
• "the required fuel quantity or injection period is determined on the basis
  of the calculated air density in the airbox. It is monitored
  continuously." [OM §7.5.3]
• Normal 1 – 20 ms; injector duty alert at 90%, critical at 95% — beyond
  saturation the ECU can no longer meter fuel at all.
• Delivery shortfall (commanded fuel mass vs measured fuel flow): alert at
  5%, critical at 12%. This comparison detects a fouled injector that neither
  signal reveals alone.
• CAN: id 1805.

3.2 CAN Bus Communication Specification  [REPLACED AT REV 2]
----------------------------------------
SUPERSEDED: the identifier list below (0x100–0x108, 0x200) was invented.
The reference engine's Display CAN is based on the CANAEROSPACE protocol
[IM ch. 77-00-00], which fixes both the message layout and the identifier for
every standard parameter. The authoritative definition is now generated from
the standard by `scripts/gen_can_dbc.py` into `configs/can/engine.dbc`.

CANaerospace message layout (all messages, 8 bytes):
  byte 0  Node-ID        transmitting station
  byte 1  Data Type      2 = FLOAT (IEEE-754 single precision)
  byte 2  Service Code   status of the data / transmitting unit — gives
                         per-frame VALIDITY straight from the bus
  byte 3  Message Code   message numbering — detects missing frames and
                         compares the AGE of messages from redundant sources
  bytes 4–7  Data

Bytes 2 and 3 are why this matters: they deliver validity and staleness at the
frame level, which is exactly what the HMI value-state model of PRD Part 4 §7.1
must annunciate, and they let the two FADEC lanes be cross-checked directly.

Standard identifiers used (Engine #1; ECS channel B is channel A + 64, which
maps onto FADEC Lane A / Lane B):
  500 / 564  engine speed (1/min)        532 / 596  oil pressure (hPa)
  504 / 568  propeller speed (1/min)     536 / 600  oil temperature (K)
  508 / 572  engine torque               540 / 604  cylinder head temp (K)
  520 / 584  exhaust gas temp (K)        548 / 612  coolant temperature (K)
  524 / 588  fuel flow rate (l/h)        684        fuel system pressure (hPa)
  528 / 592  manifold pressure (hPa)     920 / 930  DC voltage / current
HUMS extensions occupy the CANaerospace user-defined range 1800–1899:
  1800 per-cylinder CHT     1803 per-cylinder injection timing
  1801 per-cylinder EGT     1804 per-cylinder ignition timing
  1802 vibration            1805 ECU commanded schedule
  1810 ECU status           1811 manifold air     1812 air data

Note the units: CANaerospace uses KELVIN and hPa. Conversion to engineering
units is the ingest layer's job, not the bus definition's.

HONESTY LIMIT: the IM states "For detailed interface description contact an
authorized ROTAX Distributor". The exact Rotax message assignment is NOT
public and is NOT reproduced here. Our database uses the open CANaerospace
standard assignments and must never be described as "the Rotax CAN database".

Measured bus load: 3.2 % at 10 Hz on a 1 Mbit/s bus, against the <30 % target.

--- Revision 1 text retained below for history ---
Bus Standard: CAN 2.0B (ISO 11898-1)
Physical Layer: ISO 11898-2 high-speed CAN (1 Mbps)
Frame Format: Standard 11-bit identifiers (extended 29-bit for diagnostics)
Data Frame Structure:
  - 0x100: Engine Speed (RPM)
  - 0x101: Cylinder Head Temperatures (4× uint16)
  - 0x102: Exhaust Gas Temperatures (4× uint16)
  - 0x103: Oil Pressure
  - 0x104: Oil Temperature
  - 0x105: Fuel Flow
  - 0x106: Vibration RMS (3× float16 for X,Y,Z)
  - 0x107: Battery Voltage & Alternator Current
  - 0x108: Injection Timing
  - 0x200: ECU Status Word (error flags, mode, checksum)
  - 0x7DF: OBD-II Diagnostic Request (UDS protocol)
  - 0x7E0-0x7E7: OBD-II Diagnostic Response

Bus Load Target: <30% at 1 Mbps with 10 Hz update rate for all parameters
Jitter Tolerance: <1 ms inter-frame for critical parameters (CHT, EGT, Oil P)
Error Handling: CRC-15, ACK slot monitoring, bus-off recovery with 128×11 bit
  recessive bit recovery sequence

3.3 Virtual CAN Bus Development Environment
--------------------------------------------
For development and demonstration without physical hardware:
• Linux SocketCAN framework: vcan0 virtual interface
• Configuration: sudo modprobe vcan; sudo ip link add dev vcan0 type vcan;
  sudo ip link set vcan0 up
• CANdevStudio: Qt-based visual CAN signal simulation with DBC file support
• Cangaroo: DBC-based CAN analyzer with real-time graphing
• python-can: Universal Python CAN library supporting SocketCAN, PCAN, Kvaser

3.4 Edge Computing Architecture
--------------------------------
Edge Node Hardware (Raspberry Pi 4/5 or NVIDIA Jetson Nano):
• CPU: Quad-core ARM Cortex-A72 @ 1.5 GHz (RPi 4) or Hexa-core ARM @ 1.9 GHz
• RAM: 4 GB LPDDR4
• Storage: 64 GB microSD (industrial grade, -40°C to +85°C)
• CAN Interface: PiCAN2 HAT (MCP2515 + MCP2551) or USB-CAN adapter
• Network: Ethernet 1 Gbps + WiFi 5 (for GCS link)
• OS: Ubuntu 22.04 LTS Server (ARM64)

Edge Software Stack:
• python-can: CAN frame parsing and publishing
• Node-RED: Visual flow-based edge preprocessing
• TensorFlow Lite: Quantized anomaly detection model (INT8)
• Mosquitto Client: MQTT publisher to GCS
• InfluxDB Client: Local buffer for offline operation

Edge Processing Requirements:
• Critical alert detection: <50 ms (rule-based, onboard)
• Anomaly scoring: <200 ms (TFLite model)
• Data buffering: 72 hours of telemetry at 10 Hz (local storage)
• Sync to GCS: When connectivity available, compressed batch upload

3.5 ECU / FADEC Communication Interface
----------------------------------------
For future indigenous engine development (VRDE/CVRDE programs):
• Protocol: ARINC 429 or MIL-STD-1553B (defence avionics standards)
• Data Words: 32-bit, BCD or BNR encoding
• Refresh Rate: 12.5 Hz (ARINC 429 low speed) or 100 Hz (high speed)
• Parameters: All 8 required + FADEC internal status (fuel scheduling,
  ignition timing, turbocharger wastegate position, knock detection)
• Fault Codes: DTC (Diagnostic Trouble Codes) per SAE J1939 or proprietary
  VRDE specification
• Interface Adapter: Protocol converter (ARINC 429 → CAN 2.0B) for backward
  compatibility with existing GCS infrastructure

================================================================================
4. PHYSICS-BASED ENGINE MODEL — THERMODYNAMIC FOUNDATION
================================================================================

4.1 Model Hierarchy
--------------------
The Digital Twin shall implement a hierarchical physics model:

Level 0: Cantera Equilibrium Combustion Model
  → Provides adiabatic flame temperature, species composition, ignition delay
  → Used for: EGT baseline prediction, combustion quality assessment,
    emissions estimation, misfire detection via residual analysis

Level 1: 0-D Mean-Value Engine Model (MVEM)
  → Provides cycle-averaged thermodynamic state variables
  → Used for: Real-time state estimation, CHT/EGT prediction, torque estimation,
    fuel consumption prediction, degradation factor estimation

Level 2: Performance Map Interpolator
  → Provides steady-state operating point lookup
  → Used for: Baseline comparison, efficiency tracking, off-design detection

Level 3: Degradation Model
  → Provides time-varying correction factors to Level 1 and Level 2
  → Used for: RUL estimation, maintenance scheduling, trend analysis

4.2 Cantera Combustion Model Specification
-------------------------------------------
Chemical Mechanism: GRI-Mech 3.0 (gri30.yaml) — 53 species, 325 reactions
Fuel Composition: n-Heptane (C7H16) surrogate for Avgas 100LL
  (85% iso-octane, 15% n-heptane by volume, approximated as C7.2H15.5)
Oxidizer: Air (21% O2, 79% N2 by volume)

Operating Points for Equilibrium Calculation:
• Intake Conditions: T₁ = 300 K, P₁ = P_ambient (ISA: 101.325 kPa at sea level)
• Compression: Isentropic compression to P₂ = 35 bar (peak cylinder pressure)
  with γ = 1.35 (air-fuel mixture)
• Combustion: Constant pressure heat addition (HP equilibrium)
• Equivalence Ratio Range: φ = 0.6 (lean cruise) to φ = 1.3 (rich climb)

Key Outputs:
• T_ad (Adiabatic Flame Temperature): 2,100 – 2,400 K depending on φ
• Species: CO₂, H₂O, N₂, O₂, CO, NO, NO₂, unburned hydrocarbons
• Ignition Delay: τ_ign = f(T, P, φ) from Cantera reactor network

EGT Prediction Model  [CORRECTED AT REV 2 — the Rev 1 formula is wrong]

The formula below omits the expansion stroke. Adiabatic flame temperature is
the PEAK temperature at top dead centre (~2,300 K); the gas does work on the
piston all the way to exhaust valve opening and then blows down to manifold
pressure before it ever reaches the thermocouple. Applied literally the Rev 1
formula yields ~1,683 °C against a real cruise EGT of 780–880 °C.

CORRECT three-stage chain (see docs/PRD_DEVIATIONS.md DEV-12):
  1. Expansion to EVO:   T_EVO  = T_ad · η_comb · (1/r_e)^(γ_exh − 1)
  2. Blowdown:           T_port = T_EVO · (P_exh / P_cyl_EVO)^((γ_exh−1)/γ_exh)
  3. Pipe loss:          T_EGT  = T_port · (1 − ΔQ_pipe/Q)
with r_e the effective expansion ratio (≈0.88 × geometric compression ratio).

--- Revision 1 formula, retained for history ---
T_EGT_predicted = T_ad × η_comb × (1 - ΔQ_exhaust_loss / Q_in)
Where:
  η_comb = combustion efficiency (0.95 – 0.99, degrades over time)
  ΔQ_exhaust_loss = heat lost to exhaust manifold walls
  Q_in = fuel lower heating value × fuel mass flow rate

CHT Prediction Model:
T_CHT_predicted = T_coolant + (Q_comb_to_head - Q_coolant) / (h_coolant × A_coolant)
Where:
  Q_comb_to_head = fraction of combustion heat transferred to cylinder head
    (typically 25-30% of total heat release)
  h_coolant = convective heat transfer coefficient (degrades with scale buildup)
  A_coolant = effective cooling surface area

4.3 0-D Mean-Value Engine Model (MVEM) Equations
-------------------------------------------------
The MVEM shall solve the following coupled ordinary differential equations
in real-time using SciPy solve_ivp with RK45 method:

4.3.1 Intake Manifold Pressure Dynamics
  dP_man/dt = (R_air × T_man / V_man) × (ṁ_throttle - ṁ_cyl)

  Where:
    R_air = 287 J/(kg·K) (specific gas constant for air)
    T_man = intake manifold temperature (K)
    V_man = intake manifold volume (m³)
    ṁ_throttle = mass flow rate through throttle body (kg/s)
    ṁ_cyl = mass flow rate into cylinders (kg/s)

  Throttle Mass Flow (isentropic orifice flow):
    ṁ_throttle = C_d × A_throttle(α) × P_ambient / √(R_air × T_ambient)
                 × Φ(P_man / P_ambient)

  Where:
    C_d = discharge coefficient (~0.85)
    A_throttle(α) = throttle area as function of throttle angle α
    Φ(Π) = flow function:
      Φ(Π) = √(γ/(γ-1)) × (Π^(2/γ) - Π^((γ+1)/γ)) for Π > (2/(γ+1))^(γ/(γ-1))
      Φ(Π) = √(γ/(γ-1)) × ((2/(γ+1))^(2/(γ-1)) - (2/(γ+1))^((γ+1)/(γ-1))) for Π ≤ critical

  Cylinder Mass Flow (filling and emptying):
    ṁ_cyl = (η_vol × V_d × N_cyl × N_e) / (2 × 60 × V_man) × P_man / (R_air × T_man)

  Where:
    η_vol = volumetric efficiency (from performance map)
    V_d = displacement volume per cylinder (1.211 L / 4 = 0.30275 L)
    N_cyl = 4 (number of cylinders)
    N_e = engine speed (rpm)

4.3.2 Cylinder Pressure and Torque Generation  [CORRECTED AT REV 2]

  The Rev 1 relation below is a factor of two below the standard definition of
  brake mean effective pressure when V_d is the per-cylinder displacement, and
  cannot reproduce the certified power and torque figures. Use:

    T_b = BMEP × V_total / (2π × n_r) = BMEP × V_total / 4π      (n_r = 2)

  A second consequence: BMEP is by definition BRAKE mean effective pressure,
  so friction is ALREADY deducted from it. Subtracting a friction torque again
  double-counts it — an error that cost 11 % of rated power until it was
  found. Only friction IN EXCESS of the as-new value may be subtracted.

  --- Revision 1 relation, retained for history ---
  Brake Torque:
    T_b = (BMEP × V_d × N_cyl) / (4π × n_r)

  Where:
    BMEP = brake mean effective pressure (from performance map, bar)
    n_r = 2 (revolutions per power stroke for 4-stroke)
    V_d = total displacement (1.211 × 10⁻³ m³)

  BMEP from indicated mean effective pressure (IMEP):
    BMEP = IMEP × η_mech - PMEP

  Where:
    η_mech = mechanical efficiency (0.80 – 0.88, degrades with bearing wear)
    PMEP = pumping mean effective pressure (friction loss, ~0.3-0.5 bar)

  Wiebe Burn Profile (heat release rate):
    dQ_burn/dθ = Q_total × (m + 1) × (θ/θ_dur)^m × exp(-a × (θ/θ_dur)^(m+1))

  Where:
    Q_total = fuel mass × LHV × η_comb
    θ = crank angle (degrees)
    θ_dur = combustion duration (~60° CA)
    m = Wiebe shape factor (~2.0)
    a = Wiebe efficiency factor (~5.0)

4.3.3 Cylinder Head Temperature (CHT) Dynamics
  dT_CHT/dt = (Q_comb_to_head - Q_coolant - Q_exhaust_to_head) / (m_head × c_p_head)

  Where:
    Q_comb_to_head = 0.28 × Q_total × (1 - η_mech) × (1 - η_cool_efficiency)
    Q_coolant = h_cool × A_cool × (T_CHT - T_coolant_in)
    Q_exhaust_to_head = h_exh × A_exh_port × (T_exh_gas - T_CHT)
    m_head = mass of cylinder head material (aluminum, ~2.5 kg per head)
    c_p_head = specific heat of aluminum (~900 J/(kg·K))
    h_cool = convective heat transfer coefficient (degrades with scale)
    A_cool = cooling jacket surface area (~0.08 m² per head)

  Degradation Model for Cooling:
    h_cool(t) = h_cool_0 × (1 - α_scale × t_flight_hours)
    Where α_scale = scale buildup rate (~0.0002 per flight hour for hard water)

4.3.4 Exhaust Gas Temperature (EGT) Dynamics
  T_EGT = T_exh_port - ΔT_pipe_loss

  T_exh_port = T_cyl_at_EVO × (P_exh/P_cyl_EVO)^((γ_exh-1)/γ_exh)

  Where:
    T_cyl_at_EVO = temperature at exhaust valve opening
    P_exh = exhaust manifold pressure (~1.05 bar)
    P_cyl_EVO = cylinder pressure at EVO (~3-5 bar)
    γ_exh = specific heat ratio of exhaust gas (~1.3)

  Pipe Loss:
    ΔT_pipe_loss = (h_pipe × A_pipe × L_pipe / (ṁ_exh × c_p_exh)) × (T_exh_port - T_ambient)

4.3.5 Oil System Dynamics
  Oil Pressure Model:
    P_oil = P_pump - ΔP_bearing - ΔP_gallery - ΔP_filter

  P_pump = η_pump × ω_pump × V_displacement_pump / (60 × C_leakage)

  Where:
    ω_pump = pump speed (typically camshaft speed = RPM/2 for dry sump)
    V_displacement_pump = pump displacement (cm³/rev)
    C_leakage = leakage coefficient (increases with wear)
    η_pump = pump efficiency (0.70 – 0.85)

  Oil Temperature Rise:
    dT_oil/dt = (Q_friction_bearings + Q_friction_pump + Q_heat_from_sump)
                / (m_oil × c_p_oil) - (ṁ_cooler × c_p_oil × (T_oil - T_coolant_air))
                  / (m_oil × c_p_oil)

  Oil Viscosity Degradation:
    μ_oil(t) = μ_0 × exp(β_thermal × T_avg_oil × t_operating_hours)
    Where β_thermal = thermal degradation coefficient (~0.001 per °C·hr)

4.3.6 Fuel System Dynamics
  Fuel Flow Model:
    ṁ_fuel = (BMEP × V_d × N_cyl × N_e) / (2 × 60 × LHV × η_comb)

  Where:
    LHV = lower heating value of fuel (~43.5 MJ/kg for Avgas 100LL)
    η_comb = combustion efficiency (0.95 – 0.99)

  Brake Specific Fuel Consumption:
    BSFC = ṁ_fuel / P_brake  (kg/kWh)
    Normal: 0.28 – 0.32 kg/kWh for Rotax 914 at cruise

4.4 Turbocharger Model  [REVISED AT REV 2 for the Rotax 915 iS]
Key differences from the Rev 1 (914) model:
  • Critical altitude 15,000 ft, not ~12,000 ft
  • AN INTERCOOLER IS FITTED. Without modelling it, compressor discharge is
    57–89 °C at every altitude — above the 50 °C manifold-air-temperature
    limit, i.e. an illegal engine. With it, MAT lands at 20–32 °C, inside the
    25–35 °C band the OM quotes its boost targets at.
  • The boost controller targets 1.45 bar at 5,500 rpm and 1.52 bar at
    5,800 rpm. 1.73 bar is a NEVER-EXCEED authority limit, not a setpoint;
    treating it as the target over-boosts the engine by 14 %.
  • Manifold air temperature has an EXTENDED range 50–80 °C in which the
    engine runs at a published, quantified penalty of −1 kW continuous /
    −2.7 kW take-off [OM §2.1] — a degraded-but-airworthy mode, not an
    exceedance.

--- Revision 1 section (914) retained for history ---
4.4 Turbocharger Model (Rotax 914 Specific)
--------------------------------------------
The Rotax 914 is turbocharged — this significantly affects altitude performance:

Compressor Model:
  P_boost = P_ambient × π_c
  Where π_c = compressor pressure ratio (1.0 – 1.5 depending on altitude and RPM)

  Compressor map: ṁ_air_corrected = f(π_c, N_c Turbo/N_c Turbo_design)
  Where N_c Turbo = turbocharger speed (typically 80,000 – 150,000 rpm)

Wastegate Model:
  The wastegate controls boost pressure to prevent over-boost at low altitude.
  Wastegate position = f(RPM, P_man, T_ambient)
  At sea level: wastegate partially open (bypassing exhaust gas)
  At 10,000 ft: wastegate fully closed (all exhaust gas drives turbine)

Altitude Effect on Power:
  P_available = P_sea_level × (P_ambient / P_sea_level) × η_vol(altitude)
  At 10,000 ft: P_available ≈ 0.75 × P_sea_level (25% power loss)
  At 20,000 ft: P_available ≈ 0.55 × P_sea_level (45% power loss)
  The turbocharger partially compensates but cannot fully restore sea-level
  power above critical altitude (~12,000 ft for Rotax 914).

================================================================================
5. ENGINE PERFORMANCE MAPS & DEGRADATION MODELING
================================================================================

5.1 Performance Map Specification
----------------------------------
The Digital Twin shall maintain the following interpolated lookup tables:

MAP 1: BMEP [RPM × Throttle Position × Altitude]
• RPM axis: 1,000, 1,500, 2,000, 2,500, 3,000, 3,500, 4,000, 4,500, 5,000,
  5,500, 5,800 rpm
• Throttle axis: 10%, 20%, 30%, 40%, 50%, 60%, 70%, 80%, 90%, 100%
• Altitude axis: 0, 2,000, 4,000, 6,000, 8,000, 10,000, 12,000, 15,000 ft
• Interpolation: Cubic spline (scipy.interpolate.RegularGridInterpolator)
• Data Source: Rotax 914 operator's manual + Cantera simulation + empirical
  correction for Indian atmospheric conditions

MAP 2: BSFC [RPM × BMEP]
• RPM axis: same as MAP 1
• BMEP axis: 2, 4, 6, 8, 10, 12 bar
• Units: g/kWh
• Normal range: 280 – 350 g/kWh
• Degradation indicator: BSFC increase >10% from baseline → combustion or
  mechanical degradation

MAP 3: Volumetric Efficiency [RPM × Altitude]
• η_vol decreases with altitude due to lower air density
• At sea level: 0.85 – 0.90
• At 10,000 ft: 0.75 – 0.80
• At 20,000 ft: 0.60 – 0.65

MAP 4: CHT Rise Above Coolant [Power Setting × OAT × Airspeed]
• Power Setting: 25%, 50%, 75%, 100%
• OAT (Outside Air Temperature): -20°C, 0°C, 15°C, 30°C, 45°C
• Airspeed: 50, 100, 150, 200 km/h (affects ram air cooling)
• Units: °C above coolant temperature

MAP 5: EGT [Power Setting × Mixture Setting × Altitude]
• Mixture Setting: Lean (φ=0.85), Best Power (φ=1.0), Rich (φ=1.15)
• EGT peaks at stoichiometric (φ=1.0) for best power mixture
• Lean mixture: EGT lower but fuel efficiency higher
• Rich mixture: EGT lower, power slightly reduced, cooling benefit

5.2 Degradation Pathway Models
-------------------------------
The Digital Twin shall track the following degradation mechanisms:

DEGRADATION 1: Cooling System Efficiency Loss
• Mechanism: Scale buildup in cooling jackets, coolant degradation, pump wear
• Model: η_cool(t) = η_cool_0 × (1 - α_cool × t_flight_hours)
• α_cool: degradation rate (~0.0001 – 0.0003 per flight hour)
• Effect: CHT rises gradually at same power setting
• Detection: CHT residual (actual - predicted) trend > 0.5°C per 10 hours
• RUL Impact: When η_cool < 0.70, maintenance required

DEGRADATION 2: Oil Thermal Breakdown
• Mechanism: Oxidation, additive depletion, viscosity increase
• Model: μ_oil(t) = μ_0 × exp(β_thermal × T_avg_oil × t)
• β_thermal: ~0.001 per °C·hr
• Effect: Oil pressure drops at given RPM, bearing friction increases
• Detection: Oil pressure vs RPM correlation coefficient drift < 0.85
• RUL Impact: When viscosity increase > 25%, oil change required

DEGRADATION 3: Combustion Chamber Deposits
• Mechanism: Carbon buildup on piston crown, valve faces, spark plug
• Model: η_comb(t) = η_comb_0 × (1 - γ_carbon × t_flight_hours)
• γ_carbon: ~0.00005 per flight hour (depends on fuel quality)
• Effect: BSFC increases, EGT decreases (heat transfer to deposits), power loss
• Detection: BSFC trend increase > 5% from baseline
• RUL Impact: When η_comb < 0.92, decarbonization required

DEGRADATION 4: Injector / Carburetor Fouling
• Mechanism: Fuel varnish buildup, nozzle wear, air bleed blockage
• Model: Flow variance σ²_fuel(t) = σ²_0 + δ_foul × t
• δ_foul: ~0.001 (L/hr)² per flight hour
• Effect: Cylinder-to-cylinder fuel imbalance → EGT spread increase
• Detection: EGT coefficient of variation (CV) > 5% per cylinder
• RUL Impact: When CV > 10%, injector cleaning/replacement required

DEGRADATION 5: Bearing Wear
• Mechanism: Fatigue spalling, abrasive wear, lubrication film breakdown
• Model: Clearance increase C_bearing(t) = C_0 + κ_wear × t
• κ_wear: ~0.00001 mm per flight hour
• Effect: Vibration at bearing frequencies increases, oil pressure drops
• Detection: Vibration FFT peak at BPFO/BPFI frequencies > 3× baseline
• RUL Impact: When clearance > 2× design limit, bearing replacement required

DEGRADATION 6: Turbocharger Efficiency Loss
• Mechanism: Compressor blade erosion, bearing wear, seal leakage
• Model: η_turbo(t) = η_turbo_0 × (1 - λ_turbo × t)
• λ_turbo: ~0.00008 per flight hour
• Effect: Boost pressure drops at altitude, power loss above critical altitude
• Detection: Manifold pressure vs RPM residual trend
• RUL Impact: When boost loss > 15% at cruise, turbocharger overhaul required

5.3 Failure Mode Library
-------------------------
The Digital Twin shall maintain a library of the following failure modes
with associated precursor signatures:

FAILURE MODE 1: Catastrophic Engine Failure (Seizure)
• Precursors: Oil pressure drop > 20% in <30 seconds, CHT spike > 250°C,
  vibration RMS > 10 m/s², metal particles in oil (if sensor available)
• Warning Time: 10 – 60 seconds
• Recommended Action: Immediate engine shutdown, emergency landing

FAILURE MODE 2: Turbocharger Failure
• Precursors: Boost pressure drop > 20%, EGT increase > 50°C (turbine side),
  oil consumption increase, vibration at turbocharger speed frequency
• Warning Time: 5 – 30 minutes
• Recommended Action: Reduce power, monitor, land at nearest suitable field

FAILURE MODE 3: Cooling System Failure
• Precursors: CHT rise rate > 5°C/min, coolant loss (if level sensor),
  oil temperature correlation break
• Warning Time: 2 – 10 minutes
• Recommended Action: Reduce power, open cowl flaps (if applicable), land

FAILURE MODE 4: Ignition System Failure
• Precursors: Misfire rate > 5%, RPM fluctuation > ±100 rpm, EGT drop on
  affected cylinder, rough running
• Warning Time: Immediate (misfire) to 30 minutes (gradual degradation)
• Recommended Action: Switch to redundant ignition (if dual), reduce power

FAILURE MODE 5: Fuel System Failure
• Precursors: Fuel flow drop > 30%, engine stumble, power loss, fuel pressure
  drop (if pressure sensor)
• Warning Time: 5 – 60 seconds
• Recommended Action: Switch to alternate fuel tank, emergency procedures

================================================================================
6. DIGITAL TWIN CORE FRAMEWORK SPECIFICATION
================================================================================

6.1 Twin State Data Model
--------------------------
[REVISED AT REV 2 — implemented in layer4_core/twin_state.py]
The schema below is the Revision 1 text. It is retained because it is still
the structure that was built, but four corrections apply and THIS NOTICE WINS:

  a. engine_type: the enum below names ROTAX_914. The reference engine is the
     ROTAX 915 iS / iSc A (see the Revision 2 notice at the head of this
     document). engine_type is now a string taken from the engine YAML, not a
     closed enum, so adding an engine stays a configuration change.

  b. tbo_remaining is NOT a single number. The 915 iS TBO is "1200 h OR 15
     years, whichever comes first" [MML 05-10-00]. A rarely-flown engine ages
     out on the calendar with hours to spare, so the twin carries BOTH clocks
     and reports the binding one (see docs/PRD_DEVIATIONS.md DEV-26).

  c. reported_state carries a VALUE STATE per channel, not a bare float. A
     float cannot distinguish "110 degC" from "110 degC, 4 seconds stale" or
     "no reading". Every measurement is therefore
     {value, state, age_s, reason} with state from PRD Part 4 section 7.1.
     This is what lets an unusable residual be marked unusable instead of
     silently averaged in as a zero.

  d. simulated_state requires a SECOND model instance to be meaningful. The
     schema below implies a prediction exists, but says nothing about where it
     comes from; taking it from the same degraded model that produced the
     measurement yields a residual of exactly zero forever. The prediction
     comes from an as-new reference (layer4_core/shadow_model.py) driven by
     the live operating point. See section 6.5, added at Revision 2.

The Digital Twin shall maintain a comprehensive state representation for each
engine instance:

TWIN STATE SCHEMA (JSON):
{
  "twin_metadata": {
    "twin_id": "string (e.g., TAPAS-ENG-001)",
    "aircraft_id": "string (e.g., TAPAS-BH-201-AF12)",
    "engine_type": "enum [ROTAX_914, AUSTRO_E4, VRDE_INDIGENOUS]",
    "installation_date": "ISO 8601 datetime",
    "total_flight_hours": "float",
    "total_cycles": "integer",
    "last_maintenance_date": "ISO 8601 datetime",
    "tbo_hours": "float (Time Between Overhaul)",
    "tbo_remaining": "float"
  },
  "reported_state": {
    "timestamp": "ISO 8601 datetime (UTC)",
    "rpm": "float (0-6000)",
    "cht": {
      "cyl_1": "float (°C)",
      "cyl_2": "float (°C)",
      "cyl_3": "float (°C)",
      "cyl_4": "float (°C)",
      "spread_max": "float (max - min, °C)"
    },
    "egt": {
      "cyl_1": "float (°C)",
      "cyl_2": "float (°C)",
      "cyl_3": "float (°C)",
      "cyl_4": "float (°C)",
      "spread_max": "float (°C)"
    },
    "oil_pressure": "float (psi)",
    "oil_temperature": "float (°C)",
    "fuel_flow": "float (L/hr)",
    "vibration": {
      "rms_x": "float (m/s²)",
      "rms_y": "float (m/s²)",
      "rms_z": "float (m/s²)",
      "rms_total": "float (m/s²)",
      "dominant_frequency": "float (Hz)",
      "spectral_features": "object (peak frequencies and amplitudes)"
    },
    "electrical": {
      "battery_voltage": "float (V)",
      "alternator_current": "float (A)",
      "alternator_voltage": "float (V)",
      "battery_soh": "float (0-1)"
    },
    "injection_timing": {
      "cyl_1": "float (°BTDC)",
      "cyl_2": "float (°BTDC)",
      "cyl_3": "float (°BTDC)",
      "cyl_4": "float (°BTDC)"
    },
    "environmental": {
      "oat": "float (°C)",
      "altitude": "float (ft)",
      "pressure": "float (hPa)",
      "humidity": "float (%)",
      "airspeed": "float (km/h)"
    }
  },
  "predicted_state": {
    "rul_hours": "float (remaining useful life in flight hours)",
    "rul_cycles": "integer (remaining cycles)",
    "health_index": "float (0-1, composite)",
    "health_sub_indices": {
      "thermal": "float (0-1)",
      "mechanical": "float (0-1)",
      "electrical": "float (0-1)",
      "combustion": "float (0-1)"
    },
    "fault_probability": {
      "misfire": "float (0-1)",
      "injector_abnormal": "float (0-1)",
      "cooling_degradation": "float (0-1)",
      "lubrication_issue": "float (0-1)",
      "sensor_drift": "float (0-1)",
      "combustion_instability": "float (0-1)",
      "overheating_trend": "float (0-1)",
      "abnormal_vibration": "float (0-1)"
    },
    "confidence_interval": {
      "rul_lower": "float",
      "rul_upper": "float",
      "confidence_level": "float (e.g., 0.95)"
    },
    "degradation_factors": {
      "cooling_efficiency": "float (0-1, 1.0 = new)",
      "oil_quality": "float (0-1)",
      "combustion_efficiency": "float (0-1)",
      "injector_condition": "float (0-1)",
      "bearing_condition": "float (0-1)",
      "turbocharger_condition": "float (0-1)"
    }
  },
  "simulated_state": {
    "cht_predicted": "float (°C)",
    "egt_predicted": "float (°C)",
    "bmep_predicted": "float (bar)",
    "torque_predicted": "float (N·m)",
    "fuel_consumption_predicted": "float (L/hr)",
    "bsfc_predicted": "float (g/kWh)",
    "model_residual": "float (RMSE of current prediction)",
    "physics_constraint_violation": "integer (0 = valid, >0 = violation count)"
  },
  "maintenance_advisory": {
    "severity": "enum [INFO, ADVISORY, CAUTION, WARNING, EMERGENCY]",
    "message": "string (natural language)",
    "recommended_action": "string",
    "time_to_action": "string (e.g., 'Within 10 flight hours')",
    "shap_explanation": "object (feature importance mapping)",
    "fault_codes": "array of strings"
  },
  "operational_history": {
    "mission_count": "integer",
    "last_mission_id": "string",
    "total_thermal_cycles": "integer",
    "max_cht_ever_recorded": "float",
    "max_egt_ever_recorded": "float",
    "max_vibration_ever_recorded": "float",
    "hours_since_last_inspection": "float"
  }
}

6.2 State Synchronization Protocol
-----------------------------------
The Digital Twin shall maintain three state categories:

REPORTED STATE:
• Source: Physical engine sensors via CAN bus
• Update Frequency: Real-time (10 Hz for most parameters, 100 Hz for RPM)
• Validation: Range checks, rate-of-change limits, cross-sensor consistency
• Persistence: All reported states stored in InfluxDB with nanosecond timestamps

DESIRED STATE:
• Source: Operator commands or automated optimization
• Examples: Target RPM for cruise, target CHT limit for thermal management
• Update Frequency: On demand or per mission profile
• Validation: Feasibility check against physics model

PREDICTED STATE:
• Source: AI/ML models and physics model extrapolation
• Update Frequency: Every 30 seconds for RUL, every 5 seconds for fault probs
• Confidence: Always include confidence intervals (95% default)
• Validation: Physics constraint checking (e.g., predicted CHT must be < 300°C)

6.3 Twin Registry & Fleet Management
-------------------------------------
• Each engine instance registered with unique twin_id
• Fleet view: Aggregate health across all engines in squadron
• Twin lifecycle: Created → Active → Maintenance → Decommissioned
• Metadata persistence: PostgreSQL or JSON file store
• State persistence: InfluxDB time-series database
• Configuration: YAML files per engine type [REVISED AT REV 2: the three
  profiles carried are rotax_915is (reference), rotax_914 (secondary) and
  austro_ae330 (diesel adaptation stub)]

6.4 Real-Time State Update Pipeline
------------------------------------
CAN Frame Arrival (1-10 ms)
  → python-can Parser (1 ms)
  → Sensor Validation (2 ms)
  → Feature Extraction (5 ms)
  → Physics Model Update (10-20 ms)
  → Anomaly Detection (20-50 ms)
  → Health Index Calculation (5 ms)
  → RUL Estimation (30-100 ms)
  → Alert Generation (2 ms)
  → State Persistence (5 ms)
  → Dashboard Update (5-10 ms)
  = TOTAL END-TO-END: 81-203 ms (full pipeline, best–worst case)

Target: <100 ms typical (median), <200 ms worst-case (95th percentile)
Critical alert path (edge, rule-based, bypasses the full pipeline): <50 ms
Note: The <50 ms critical path runs ONBOARD at the edge node (Layer 1) using
only the rule engine, so it does not depend on physics/AI/RUL stages above.

6.5 Reference (Shadow) Model and Residual Generation  [ADDED AT REV 2]
-----------------------------------------------------------------------
Revision 1 specified `simulated_state` but never said which model produces it.
Implementation exposed that as the single most important unstated decision in
the document, because the obvious reading is wrong in a way that is invisible
from the outside.

THE FAILURE MODE
If `simulated_state` is filled from the same engine model whose output is being
monitored, the residual (reported minus simulated) is identically zero at every
instant, for every engine, healthy or failing. The twin still validates,
serialises, renders and passes its schema tests. It detects nothing. Nothing in
the Revision 1 text rules this out.

THE REQUIREMENT
The twin SHALL maintain a second, independent model instance -- the SHADOW
MODEL -- whose degradation factors are pinned as-new and never advanced. It
answers one question: at this operating point, what SHOULD the engine be doing
if it were new? The residual against it is the primary degradation signal and
the primary input to the AI layer.

DRIVING INPUTS (normative)
The shadow model SHALL be driven only by quantities that describe the operating
point:
    throttle position, crankshaft speed, pressure altitude, outside air
    temperature, airspeed
Each is a command or an environmental condition. The shadow model SHALL NOT
consume any engine RESPONSE -- cylinder head temperature, coolant temperature,
oil pressure, exhaust gas temperature or fuel flow -- as an input. Feeding back
a response allows the reference to track the degrading engine, and the residual
then collapses toward zero exactly as the fault grows. This is the classic way
a model-based monitor blinds itself and it SHALL be prevented by construction,
not by tuning.

ONE PERMITTED EXCEPTION
Thermal states MAY be seeded once, from the first valid telemetry frame, to
remove the shadow's own warm-up transient. This SHALL happen exactly once per
mission and SHALL NOT recur.

SPEED IS AN INPUT, NOT A RESIDUAL
Crankshaft speed is locked to the measured value. Left free, the shadow's speed
drifts from the real engine's through propeller load and governor behaviour,
and that operating-point mismatch alone swamps the thermal signal the residual
exists to measure. Speed is directly threshold-monitored at Layer 1, so nothing
is lost.

AVAILABILITY
The shadow model SHALL return no prediction -- rather than a carried-over one --
when the engine is not running, or when a driving channel fails validation. A
residual computed against a stale prediction is worse than no residual, because
it is indistinguishable from a real one downstream.

VERIFICATION (achieved, 900 s missions, severity 0.8, 1800 syncs each)
  condition              CHT resid   oil press. resid   EGT resid   alerts
  healthy                  +0.6 K       +0.02 psi        +9.5 C     none
  cooling degradation     +12.0 K       +0.02 psi        +9.5 C     none
  lubrication issue        +0.5 K       +5.07 psi        +9.2 C     none
  injector abnormal        +0.6 K       +0.02 psi       -28.5 C     INJ TIMING DEV

Each fault moves one residual and leaves the others at the healthy value, so
the residual vector is diagnostic rather than a single anomaly score. Cooling
degradation and lubrication issue are both detected with NO threshold crossed
and the Layer 1 rule engine correctly silent -- which is the entire argument
for a digital twin over a limit monitor.

================================================================================
7. REAL-TIME DATA INGESTION & SYNCHRONIZATION PROTOCOL
================================================================================

7.1 Data Ingestion Architecture
--------------------------------
┌─────────────────────────────────────────────────────────────────────────────┐
│  PHYSICAL ENGINE                                                            │
│  └── CAN Bus (1 Mbps, ISO 11898-2)                                        │
│       └── Edge Node (Raspberry Pi 4 + PiCAN2 HAT)                         │
│            ├── Critical Alert Processor (<50 ms, rule-based)              │
│            ├── Data Buffer (72-hour local storage)                        │
│            └── MQTT Publisher (compressed, batched)                       │
│                 └── Ground Control Station (Secure LAN)                   │
│                      ├── MQTT Broker (Mosquitto, TLS 1.3)               │
│                      ├── InfluxDB (time-series persistence)               │
│                      ├── Digital Twin Core (Eclipse Ditto)              │
│                      └── Analytics Engine (AI/ML models)                │
│                           └── Grafana Dashboard (real-time viz)         │
└─────────────────────────────────────────────────────────────────────────────┘

7.2 MQTT Topic Hierarchy
-------------------------
• dt/fleet/{aircraft_id}/engine/{twin_id}/reported
  → Raw sensor data from edge node
• dt/fleet/{aircraft_id}/engine/{twin_id}/predicted
  → AI/ML model outputs
• dt/fleet/{aircraft_id}/engine/{twin_id}/simulated
  → Physics model predictions
• dt/fleet/{aircraft_id}/engine/{twin_id}/alerts
  → Real-time alerts and advisories
• dt/fleet/{aircraft_id}/engine/{twin_id}/commands
  → Operator commands to edge node
• dt/fleet/{aircraft_id}/engine/{twin_id}/config
  → Configuration updates

7.3 Data Compression & Bandwidth
---------------------------------
• Telemetry bandwidth (UAV to GCS): Typically 256 kbps – 2 Mbps
• Engine data payload: ~200 bytes per frame at 10 Hz = 16 kbps
• Compression: MessagePack or CBOR (30-50% smaller than JSON)
• Batch upload: Edge node buffers 100 frames, compresses, uploads as batch
• Priority queuing: Critical alerts bypass batch queue and transmit immediately

7.4 Offline Operation Mode
---------------------------
When GCS link is lost (common in UAV operations):
• Edge node continues all processing locally
• Critical alerts trigger onboard actions (e.g., automatic power reduction)
• Data buffered locally in SQLite or InfluxDB Edge
• Upon link restoration: Automatic sync of buffered data to GCS
• Conflict resolution: Timestamp-based, GCS state takes precedence for commands

================================================================================
8. SENSOR FUSION & SIGNAL PROCESSING ARCHITECTURE
================================================================================

8.1 Multi-Sensor Data Fusion Strategy
--------------------------------------
The Digital Twin shall implement the following sensor fusion techniques:

LEVEL 1: DATA-LEVEL FUSION
• Time synchronization: All sensors aligned to GPS PPS or internal clock
• Interpolation: Missing samples interpolated using cubic spline (max gap: 3 samples)
• Outlier rejection: Hampel filter (median absolute deviation > 3σ)
• Resampling: All signals resampled to common 10 Hz grid

LEVEL 2: FEATURE-LEVEL FUSION
• Cross-correlation: Oil pressure vs RPM correlation coefficient (lubrication health)
• CHT-EGT cross-sensitivity: Combustion efficiency indicator
• Vibration-RPM coherence: Mechanical health indicator
• Fuel flow-power coherence: Fuel system health indicator

LEVEL 3: DECISION-LEVEL FUSION
• Multi-sensor voting: 3-of-5 rule for sensor failure detection
• Bayesian fusion: Combine anomaly scores from multiple detectors
• Dempster-Shafer evidence theory: Combine fault probabilities from
  different subsystems (thermal, mechanical, electrical, combustion)

8.2 Signal Processing Specifications
-------------------------------------
RPM Signal Processing:
• Raw: Pulse train from magnetic pickup
• Processing: Frequency-to-RPM conversion (rpm = 60 × f_pulses / N_teeth)
• Filtering: Moving average (window: 10 samples = 1 second)
• Feature: RPM fluctuation (standard deviation over 1-second window)
• Misfire Detection: RPM drop > 50 rpm for > 100 ms on single cylinder event

CHT/EGT Signal Processing:
• Raw: K-type thermocouple voltage (41 μV/°C)
• Cold junction compensation: RTD measurement at junction box
• Filtering: Low-pass Butterworth, fc = 1 Hz (thermal inertia ~1 second)
• Feature: Rate of change (dT/dt), thermal shock indicator
• Feature: Cylinder-to-cylinder spread (max - min)

Vibration Signal Processing:
• Raw: 10,000 Hz tri-axial acceleration
• Preprocessing: DC offset removal, anti-aliasing filter (fc = 5 kHz)
• Time-domain features: RMS, peak, crest factor, kurtosis, skewness
• Frequency-domain: FFT (N = 4096, Δf = 2.44 Hz), Hanning window, 50% overlap
• Envelope analysis: Hilbert transform for bearing fault detection
• Spectral features: Peak frequencies, amplitudes, bandwidth, centroid

Fuel Flow Signal Processing:
• Raw: Turbine frequency (pulses per liter)
• Filtering: Moving average (window: 5 seconds)
• Feature: Flow variance (indicates injector instability)
• Feature: Cylinder-individual flow estimation (from EGT correlation)

Oil Pressure Signal Processing:
• Raw: Piezoresistive voltage
• Filtering: Low-pass, fc = 2 Hz
• Feature: Pressure vs RPM correlation (Pearson r, updated every 60 seconds)
• Feature: Pressure pulsation amplitude (pump frequency component)

8.3 Sensor Failure Detection
-----------------------------
The system shall detect sensor failures using:

METHOD 1: Range Check
• Value outside physically possible range (e.g., CHT < 0°C or > 400°C)
• Immediate flag: SENSOR_RANGE_FAULT

METHOD 2: Rate-of-Change Check
• Change exceeding physical possibility (e.g., CHT change > 50°C in 1 second)
• Immediate flag: SENSOR_RATE_FAULT

METHOD 3: Cross-Sensor Consistency
• Compare with correlated sensors (e.g., CHT vs EGT should correlate at r > 0.7)
• If correlation breaks: SENSOR_DRIFT_FAULT

METHOD 4: Model Residual
• Compare sensor reading with physics model prediction
• If residual > 3σ for > 10 seconds: SENSOR_BIAS_FAULT

METHOD 5: Multi-Sensor Voting
• For critical parameters, use 3 sensors and majority voting
• If one sensor disagrees with other two: SENSOR_FAILURE (flag but continue
  operation with remaining sensors)

8.4 Sensor Calibration & Drift Compensation
--------------------------------------------
• Baseline calibration: Performed during ground run-up test
• Auto-calibration: During steady-state cruise, compare sensor reading with
  physics model prediction and update offset
• Drift tracking: Kalman filter estimates sensor bias as state variable
• Compensation: Reported value = Raw value - Estimated bias
• Alert: When estimated bias > 5% of full scale → SENSOR_DRIFT_ADVISORY

================================================================================
END OF PRD PART 1
================================================================================
