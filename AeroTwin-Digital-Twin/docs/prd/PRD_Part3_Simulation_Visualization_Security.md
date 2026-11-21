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
     and a Maintenance CAN bus on each lane. The 914 is retained in
     configs/engines/ as a secondary profile, and the Austro AE330 diesel as
     an adaptation stub, which together demonstrate the engine-agnostic claim.

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
TECHNICAL PRODUCT REQUIREMENTS DOCUMENT (PRD) — PART 3 of 3
SIH 2026 / DRDO IDEX Problem Statement 26054
AI-Enabled Real-Time Digital Twin for Aero Piston Engines in MALE UAVs
================================================================================
Document Version: 1.0
Date: 22 August 2026
Classification: Internal Technical Document
================================================================================

TABLE OF CONTENTS — PRD PART 3
================================================================================
17. Simulation & Replay Capability Specification
18. Environmental Condition Simulation Engine
19. Visualization Dashboard & HMI Specification
20. Security Architecture & Secure Telemetry
21. Edge AI for UAV Applications
22. Federated Learning Architecture
23. Desired Innovation Areas (All 8)
24. Technical Expectations Compliance Matrix
25. Deliverables & Deployment Roadmap
26. Performance Benchmarks & Validation Criteria
27. Risk Assessment & Mitigation Strategies

================================================================================
17. SIMULATION & REPLAY CAPABILITY SPECIFICATION
================================================================================

17.1 Mission Replay Engine
---------------------------
The system shall provide a mission replay capability that reproduces engine
behavior from historical telemetry data for post-flight analysis, incident
investigation, and model validation.

REPLAY DATA SOURCE:
• Primary: InfluxDB time-series database (all telemetry stored with nanosecond
  timestamps)
• Secondary: Local log files (JSON or CSV format, for offline analysis)
• Tertiary: CAN bus log files (asc/blf format, for raw bus analysis)

REPLAY MODES:

Mode 1: Real-Time Replay (1× speed)
• Reproduces mission exactly as it occurred
• Synchronized with physics model predictions
• Operator can pause, resume, step forward/backward
• Use case: Detailed incident investigation, pilot debrief

Mode 2: Accelerated Replay (10× speed)
• Compresses 18-hour endurance mission to 1.8 hours
• Maintains all data points (no decimation)
• Alert triggers fire at correct relative times
• Use case: Mission summary review, trend identification

Mode 3: Fast Replay (100× speed)
• Compresses 18-hour mission to 10.8 minutes
• Data decimated to 1 Hz for display (full data available on demand)
• Key events (alerts, anomalies) highlighted
• Use case: Fleet-level overview, pattern recognition across missions

Mode 4: Event-Driven Replay
• Jump to specific events (alerts, anomalies, power changes)
• Pre-event buffer: 60 seconds before event
• Post-event buffer: 300 seconds after event
• Use case: Focused investigation of specific incidents

REPLAY SYNCHRONIZATION:
• Physics model predictions shall be recomputed during replay
• Model residual (predicted vs actual) displayed in real-time
• Degradation factor estimates updated based on replay data
• Health index trajectory recomputed and displayed

REPLAY ANNOTATIONS:
• Operator can add text annotations at any timestamp
• Annotations stored in database, linked to mission ID
• Pre-defined annotation categories:
  - PILOT_ACTION (throttle change, mixture adjustment)
  - ENVIRONMENTAL (weather, turbulence, altitude change)
  - MAINTENANCE (inspection note, part replacement)
  - ANOMALY (observed issue, sensor glitch)

17.2 Mission Profile Definition
--------------------------------
The system shall support mission profile definition for pre-flight simulation:

MISSION PROFILE SCHEMA (JSON):
{
  "mission_id": "MIS-2026-08-22-001",
  "aircraft_id": "TAPAS-BH-201-AF12",
  "engine_id": "UAV-ENG-001",
  "mission_type": "ISR_PATROL",
  "waypoints": [
    {
      "wp_id": 1,
      "lat": 12.9716,
      "lon": 77.5946,
      "altitude_ft": 500,
      "airspeed_kmh": 120,
      "power_setting": "CLIMB",
      "estimated_time_min": 0
    },
    {
      "wp_id": 2,
      "lat": 13.0827,
      "lon": 80.2707,
      "altitude_ft": 15000,
      "airspeed_kmh": 180,
      "power_setting": "CRUISE",
      "estimated_time_min": 120
    }
  ],
  "environmental_conditions": {
    "oat_c": 35,
    "pressure_hpa": 1013,
    "humidity_percent": 65,
    "wind_speed_kmh": 15,
    "wind_direction_deg": 270,
    "turbulence_index": 2
  },
  "payload": {
    "total_weight_kg": 350,
    "power_consumption_w": 500
  },
  "fuel_load_l": 450,
  "estimated_duration_hr": 18,
  "estimated_distance_km": 2000
}

17.3 What-If Scenario Engine
-----------------------------
The system shall support "what-if" scenario simulation for mission planning:

SCENARIO INPUTS:
• Modified mission profile (different altitudes, speeds, waypoints)
• Modified environmental conditions (hotter, colder, higher altitude)
• Modified payload (heavier, different power consumption)
• Modified engine health state (simulated degradation)

SCENARIO OUTPUTS:
• Predicted CHT envelope (max, min, average per mission segment)
• Predicted EGT envelope
• Predicted fuel consumption profile
• Predicted health index trajectory
• Predicted RUL consumption per mission segment
• Go/No-Go recommendation with confidence interval
• Optimal throttle schedule for engine preservation
• Thermal limit exceedance probability

SCENARIO COMPARISON:
• Side-by-side comparison of multiple scenarios
• Difference highlighting (parameter deltas, risk deltas)
• Recommendation ranking (best scenario for engine health)

EXAMPLE SCENARIO:
Input: "What if we climb to 20,000 ft at 80% throttle in 45°C ambient?"
Output:
  • Predicted max CHT: 218°C (ALERT: exceeds 210°C threshold)
  • Predicted max EGT: 745°C (WARNING: near 750°C limit)
  • Fuel consumption: 12.5 L/hr (18% higher than 15,000 ft cruise)
  • RUL consumption: 2.3 hours per mission hour (vs 1.0 at normal cruise)
  • Recommendation: NO-GO. Reduce altitude to 15,000 ft or reduce throttle to
    65%. Alternative: Climb during cooler part of day (early morning).

================================================================================
18. ENVIRONMENTAL CONDITION SIMULATION ENGINE
================================================================================

18.1 Environmental Model Library
---------------------------------
The system shall simulate engine behavior under the following environmental
conditions as specified in the problem statement:

CONDITION 1: HIGH ALTITUDE OPERATION
-------------------------------------
Altitude Range: 0 – 30,000 ft (TAPAS-BH-201 service ceiling: 32,000 ft)

Atmospheric Model (ISA + Indian atmospheric variations):
• Temperature: T = T₀ - L × h
  Where T₀ = 288.15 K (15°C), L = 6.5 K/km, h = altitude in km
  Indian variation: +5°C in summer (hot day model)
• Pressure: P = P₀ × (1 - L×h/T₀)^(g/(R×L))
  Where P₀ = 1013.25 hPa, g = 9.81 m/s², R = 287 J/(kg·K)
• Density: ρ = P / (R × T)

Engine Effects:
• Air density decreases 30% at 10,000 ft → mass airflow decreases 30%
• Turbocharger compensates partially: boost pressure increases to maintain
  manifold pressure, but critical altitude (~12,000 ft for Rotax 914) limits
  compensation
• Power loss: ~25% at 10,000 ft, ~45% at 20,000 ft
• CHT baseline decreases (colder air) but cooling margin decreases
  (less air mass for heat rejection)
• Fuel flow decreases (less air requires less fuel to maintain mixture)
• BSFC may increase (engine operating off-design)

Simulation Parameters:
• Altitude step: 1,000 ft
• Temperature model: ISA, ISA+10°C (hot day), ISA-10°C (cold day)
• Humidity model: 0-100% RH (affects air density slightly)
• Wind model: Headwind/tailwind/crosswind (affects airspeed, cooling)

CONDITION 2: ENDURANCE MISSION
-------------------------------
Mission Duration: 12 – 24+ hours (TAPAS-BH-201 target: 24 hours)

Degradation Accumulation:
• Oil thermal breakdown: Viscosity increases 5-10% over 18 hours at 100°C
• Carbon buildup: Combustion chamber deposits increase, η_comb decreases 2-3%
• Fuel system: Injector fouling increases, flow imbalance grows
• Cooling system: Scale effect accumulates (minimal over single mission)
• Battery: Charge/discharge cycles (if alternator load varies)

Simulation Parameters:
• Time step: 1 minute for long-duration simulation
• Degradation rate: Based on physics model with mission-averaged conditions
• Thermal cycling: Count of CHT excursions > 200°C (fatigue indicator)
• Oil degradation model: μ(t) = μ₀ × exp(β × T_avg × t)

CONDITION 3: HOT-WEATHER OPERATION
-----------------------------------
Temperature Range: 30°C – 50°C (Indian desert conditions, Thar/Rajasthan)

Engine Effects:
• Ambient temperature increase 20°C above ISA → CHT baseline increases 10-15°C
• Oil temperature increases → viscosity decreases → lubrication margin decreases
• Fuel temperature increases → vapor pressure increases → vapor lock risk
• Air density decreases (hot air is less dense) → slight power loss
• Cooling system working harder → pump and fan load increases

Simulation Parameters:
• OAT: 30°C, 35°C, 40°C, 45°C, 50°C
• Relative humidity: 10% (desert) to 90% (coastal)
• Ground effect: Reduced airflow during taxi/takeoff
• Ram air cooling: Airspeed-dependent cooling augmentation

CONDITION 4: RAPID THROTTLE TRANSITIONS
-----------------------------------------
Transition Types:
• Idle to Max Power: 0% to 100% throttle in < 5 seconds
• Max Power to Idle: 100% to 0% throttle in < 3 seconds
• Power oscillation: Repeated rapid changes (formation flying, turbulence)

Engine Effects:
• Transient enrichment: Fuel system lags air flow → temporary rich mixture
• Thermal shock: CHT changes > 5°C/min → cylinder head stress
• Turbocharger lag: Boost pressure takes 2-3 seconds to respond
• Oil pressure transient: Pump response lag → temporary pressure dip

Simulation Parameters:
• Throttle rate: 10%/s, 20%/s, 50%/s, 100%/s
• Transition frequency: Single, repeated (every 30s, 60s, 120s)
• Thermal shock limit: CHT rate-of-change < 5°C/min (design limit)
• Acceleration enrichment model: Additional fuel = f(throttle_rate, manifold_pressure)

ADDITIONAL CONDITION 5: MARITIME OPERATION
-------------------------------------------
(Not explicitly in problem statement but relevant for Indian Navy TAPAS ops)

Environmental Factors:
• High humidity: 70-95% RH → condensation risk, electrical degradation
• Salt spray: Corrosion of sensors, connectors, exhaust system
• Temperature moderation: Maritime climate reduces extreme temperatures
• Deck operations: Limited space, salt-laden air intake

Engine Effects:
• Salt ingestion: Compressor blade erosion, combustion chamber deposits
• Corrosion: Sensor drift (thermocouple oxidation, connector resistance)
• Humidity: Ignition system degradation (moisture in CDI, leads)

Simulation Parameters:
• Salt concentration: Low, medium, high (coastal, offshore, carrier deck)
• Humidity: 70%, 85%, 95%
• Corrosion rate: Accelerated sensor drift model

ADDITIONAL CONDITION 6: HIMALAYAN / COLD-WEATHER OPERATION
-----------------------------------------------------------
(Not explicitly in problem statement but relevant for Ladakh operations)

Environmental Factors:
• Extreme cold: -30°C to -50°C at altitude
• Low pressure: Air density 50% of sea level at 20,000 ft
• Icing risk: Intake icing, fuel icing

Engine Effects:
• Cold start: Oil viscosity increases 400% at -30°C → starter load increases
• Battery performance: Capacity drops 50% at -20°C
• Fuel vaporization: Poor atomization at low temperatures
• Pre-heat requirement: Engine block heater needed for reliable start

Simulation Parameters:
• OAT: -10°C, -20°C, -30°C, -40°C
• Pre-heat: None, partial (oil sump), full (block heater)
• Start attempt model: Cranking time, start success probability

18.2 Environmental Simulation Integration
------------------------------------------
The environmental simulation shall integrate with the physics model by:
• Modifying ambient conditions (T, P, ρ) in the intake manifold model
• Modifying cooling effectiveness (h_cool) based on airspeed and OAT
• Modifying oil viscosity based on temperature
• Modifying fuel properties based on temperature
• Modifying battery performance based on temperature

The simulation shall produce:
• Time-series of all 8 parameters under specified environmental conditions
• Health index trajectory over mission duration
• RUL consumption rate (hours of RUL consumed per flight hour)
• Thermal limit exceedance probability
• Go/No-Go recommendation with confidence interval

================================================================================
19. VISUALIZATION DASHBOARD & HMI SPECIFICATION
================================================================================

19.1 Dashboard Design Philosophy
---------------------------------
The visualization dashboard shall follow defense HMI best practices:
• Clarity: Information hierarchy — most critical data most prominent
• Consistency: Standardized colors, icons, layouts across all screens
• Context: Information relevant to current operational mode
• Control: Operator can customize views, set preferences
• Confirmation: Critical actions require confirmation

19.2 Primary Dashboard: Grafana
--------------------------------
Grafana shall serve as the primary visualization platform with the following
panel configuration:

PANEL 1: Engine Parameter Gauges (Top Row, 4 panels)
• RPM Gauge: 0-6,000 rpm, color zones (green: 2,000-5,500, yellow: 5,500-5,800,
  red: >5,800)
• CHT Gauge: 0-300°C, per-cylinder mini-gauges or average, color zones
  (green: <200, yellow: 200-210, orange: 210-230, red: >230)
• EGT Gauge: 0-1,000°C, per-cylinder or average, color zones
  (green: <700, yellow: 700-750, orange: 750-850, red: >850)
• Oil Pressure Gauge: 0-100 psi, color zones
  (green: 45-65, yellow: 40-45 or 65-75, orange: 25-40, red: <25)

PANEL 2: Health Index Display (Second Row, 2 panels)
• Composite Health Index: Radial gauge 0-100%, color-coded
  (green: >90%, yellow: 75-90%, orange: 60-75%, red: <60%)
• Subsystem Health Indices: 4 mini radial gauges (thermal, mechanical,
  electrical, combustion)

PANEL 3: RUL Countdown (Second Row, 1 panel)
• Large numeric display: "47.5 HOURS"
• Progress bar: RUL / TBO
• Confidence interval: "42.3 – 52.7 hours (95% confidence)"
• Color: Green (>50 hrs), Yellow (25-50 hrs), Orange (10-25 hrs), Red (<10 hrs)

PANEL 4: Fuel & Vibration (Second Row, 1 panel)
• Fuel Flow: Time-series line chart (last 60 minutes)
• Vibration RMS: Bar gauge with color zones
• Battery Voltage: Small gauge

PANEL 5: Time-Series Trends (Third Row, full width)
• Multi-line chart: CHT (all 4 cylinders), EGT (all 4 cylinders), Oil Temp
• X-axis: Time (last 60 minutes, selectable: 5 min, 15 min, 1 hr, 6 hr, 24 hr)
• Y-axis: Temperature (°C)
• Annotations: Alert events marked with vertical lines
• Zoom: Click and drag to zoom, double-click to reset

PANEL 6: Fault Alert Table (Fourth Row, left half)
• Table with columns: Time, Severity, Fault, Affected Cylinder, Advisory
• Sortable by time, severity
• Filterable by fault type, severity
• Click row to view detailed SHAP explanation

PANEL 7: Maintenance Advisory (Fourth Row, right half)
• Current top-priority advisory displayed prominently
• Natural language explanation
• SHAP feature importance bar chart
• Recommended action button ("Acknowledge", "Schedule Maintenance", "Dismiss")

PANEL 8: Mission Replay Controls (Fifth Row, left third)
• Play/Pause/Stop buttons
• Speed selector: 1×, 10×, 100×
• Timeline scrubber with event markers
• Current time display
• Event list: Click to jump to event

PANEL 9: Efficiency Trends (Fifth Row, middle third)
• BSFC trend: g/kWh over time
• Power output trend
• Fuel efficiency comparison: Actual vs nominal vs predicted

PANEL 10: Environmental Conditions (Fifth Row, right third)
• OAT, altitude, pressure, humidity display
• Wind speed/direction (if available)
• Environmental impact on engine: Power loss %, cooling margin %

19.3 Secondary Dashboard: Streamlit HMI
----------------------------------------
For rapid prototyping and competition demonstration, a Streamlit-based HMI
shall provide:
• st.metric() widgets for real-time parameter display
• st.line_chart() for time-series trends
• st.dataframe() for alert tables
• st.expander() for SHAP explanations
• st.selectbox() for mission profile selection
• st.slider() for what-if scenario inputs
• st.download_button() for report generation

19.4 Alert Notification System
-------------------------------
The system shall support multi-channel alert distribution:

CHANNEL 1: Dashboard Visual
• Color-coded indicators (green/yellow/orange/red)
• Flashing indicators for critical alerts
• Alert counter badge on navigation menu

CHANNEL 2: Audio Alerts
• Level 3 (Caution): Single beep (1 kHz, 200 ms)
• Level 4 (Warning): Periodic beep (1 kHz, 200 ms, every 30 seconds)
• Level 5 (Emergency): Continuous alarm (1 kHz, 50% duty cycle)
• Configurable: Volume, mute during night operations

CHANNEL 3: Email Notifications
• Recipients: Configurable per alert level
• Format: HTML email with alert details, SHAP explanation, recommended actions
• Rate limiting: Max 1 email per 5 minutes for same fault type

CHANNEL 4: SMS Notifications
• Recipients: Maintenance chief, duty officer
• Format: Text message with alert summary
• Trigger: Level 4 and Level 5 alerts only

CHANNEL 5: Webhook / API Integration
• Integration with maintenance management system (e.g., Oxmaint)
• Automatic work order creation for Level 4+ alerts
• Integration with fleet management system for operational decisions

19.5 User Roles & Views
------------------------
The dashboard shall support role-based views:

ROLE 1: UAV Operator
• View: Real-time engine parameters, health index, alerts
• Access: Read-only for all parameters
• Actions: Acknowledge alerts, view mission replay
• Focus: Mission safety, immediate operational decisions

ROLE 2: Propulsion Engineer
• View: All operator views + physics model details, degradation factors,
  trend analysis, simulation tools
• Access: Read-write for simulation parameters, what-if scenarios
• Actions: Run simulations, adjust model parameters, generate reports
• Focus: Engine performance, degradation analysis, model validation

ROLE 3: Maintenance Technician
• View: Health reports, maintenance advisories, parts forecasting,
  maintenance history
• Access: Read-write for maintenance records, parts orders
• Actions: Schedule maintenance, update maintenance log, order parts
• Focus: Preventive maintenance, repair execution

ROLE 4: Mission Commander
• View: Fleet-level overview, mission readiness status, risk assessment
• Access: Read-only for all engines, read-write for mission profiles
• Actions: Approve missions, modify mission profiles, abort missions
• Focus: Operational readiness, mission success probability

================================================================================
20. SECURITY ARCHITECTURE & SECURE TELEMETRY
================================================================================

20.1 Threat Model
------------------
The system shall address the following threat categories:

THREAT 1: Data Interception
• Adversary intercepts UAV-to-GCS telemetry
• Mitigation: TLS 1.3 encryption for all data in transit

THREAT 2: Unauthorized Access
• Adversary gains access to GCS or Digital Twin system
• Mitigation: JWT authentication, RBAC, multi-factor authentication

THREAT 3: Data Tampering
• Adversary modifies telemetry data or health predictions
• Mitigation: Digital signatures on critical messages, blockchain-like
  integrity verification for maintenance records

THREAT 4: Denial of Service
• Adversary floods system with fake data or connection requests
• Mitigation: Rate limiting, connection throttling, anomaly-based DDoS detection

THREAT 5: Insider Threat
• Authorized user misuses privileges
• Mitigation: Audit logging, principle of least privilege, behavior analysis

20.2 Encryption Specifications
-------------------------------
Data in Transit:
• Protocol: TLS 1.3 (RFC 8446)
• Cipher Suites: TLS_AES_256_GCM_SHA384 (mandatory),
  TLS_CHACHA20_POLY1305_SHA256 (optional)
• Certificate: X.509 v3, RSA-2048 or ECDSA P-256, issued by internal CA
  (or Let's Encrypt for development)
• Perfect Forward Secrecy: ECDHE key exchange
• Certificate Pinning: For UAV edge nodes to prevent MITM

Data at Rest:
• Algorithm: AES-256-GCM
• Key Management: Hardware Security Module (HSM) or software-based key store
  (HashiCorp Vault or similar)
• Key Rotation: Every 90 days
• Backup Encryption: Separate key for backup media

20.3 Authentication & Authorization
------------------------------------
Authentication:
• Method: JWT (JSON Web Tokens) with RS256 signing
• Token Structure: Header (alg, typ), Payload (sub, role, iat, exp, jti),
  Signature
• Token Lifetime: Access token: 15 minutes; Refresh token: 24 hours
• Issuer: Keycloak Identity and Access Management (open source)
• Multi-Factor Authentication: TOTP (Time-based One-Time Password) for
  Commander and Engineer roles

Authorization (RBAC):
• Role Definition:
  - ROLE_OPERATOR: Read all engine data, acknowledge alerts
  - ROLE_ENGINEER: All operator permissions + simulation, model adjustment
  - ROLE_MAINTENANCE: All operator permissions + maintenance scheduling,
    parts ordering
  - ROLE_COMMANDER: All permissions + mission approval, user management
• Permission Matrix: Explicit allow/deny for each API endpoint per role
• Dynamic Authorization: Attribute-Based Access Control (ABAC) for fine-grained
  control (e.g., Operator A can only view engines in Squadron X)

20.4 Network Security
----------------------
Network Segmentation:
• Segment 1: UAV Network (CAN bus, edge node) — Isolated, no direct internet
• Segment 2: DMZ (Edge Gateway, MQTT broker) — Controlled access
• Segment 3: Secure LAN (GCS, Digital Twin Core, Analytics) — Internal only
• Segment 4: Management Network (administration, monitoring) — Restricted

Firewall Rules:
• UAV → DMZ: MQTT publish only (port 8883, TLS)
• DMZ → Secure LAN: MQTT subscribe + REST API (port 443, TLS)
• Secure LAN → Management: SSH (port 22), monitoring (port 9090)
• Deny all other traffic by default

Intrusion Detection:
• Network IDS: Suricata or Snort (open source)
• Host IDS: OSSEC or Wazuh (open source)
• Anomaly Detection: ML-based network traffic anomaly detection

20.5 Audit & Compliance
------------------------
Audit Logging:
• All authentication attempts (success and failure)
• All authorization decisions (allow and deny)
• All state mutations (twin state changes, alert generation)
• All model updates (retraining, parameter changes)
• All maintenance actions (scheduled, executed, cancelled)

Log Format:
{
  "timestamp": "2026-08-22T14:04:00Z",
  "event_type": "ALERT_GENERATED",
  "severity": "WARNING",
  "user_id": "system",
  "twin_id": "UAV-ENG-001",
  "details": {
    "alert_id": "ALT-2026-08-22-001",
    "fault_type": "COOLING_DEGRADATION",
    "confidence": 0.87
  },
  "source_ip": "192.168.1.100",
  "session_id": "sess_abc123",
  "integrity_hash": "sha256:..."
}

Compliance:
• Conceptual alignment with NIST 800-171 (Protecting Controlled Unclassified
  Information in Nonfederal Systems)
• Conceptual alignment with DO-326A (Airworthiness Security Process Specification)
• Data retention: 7 years for maintenance records, 2 years for telemetry
• Data sovereignty: All data stored within Indian territory

================================================================================
21. EDGE AI FOR UAV APPLICATIONS
================================================================================

21.1 Edge Computing Architecture
---------------------------------
The system shall support edge AI deployment for onboard processing:

EDGE HARDWARE OPTIONS:
Option A: Raspberry Pi 4/5 (4GB RAM)
• CPU: Quad-core ARM Cortex-A72 @ 1.5 GHz
• AI Accelerator: None (CPU inference)
• Performance: ~50 ms for rule-based, ~500 ms for TFLite model
• Cost: ~₹3,000-5,000
• Power: 5V @ 3A = 15W

Option B: NVIDIA Jetson Nano (4GB RAM)
• CPU: Quad-core ARM Cortex-A57 @ 1.43 GHz
• GPU: 128-core Maxwell
• AI Accelerator: CUDA + TensorRT
• Performance: ~20 ms for TFLite, ~5 ms for TensorRT
• Cost: ~₹8,000-12,000
• Power: 5V @ 4A = 20W

Option C: Coral Dev Board (1GB RAM)
• CPU: NXP i.MX 8M SoC
• AI Accelerator: Edge TPU (4 TOPS INT8)
• Performance: ~10 ms for quantized models
• Cost: ~₹15,000
• Power: 5V @ 3A = 15W

21.2 Edge AI Model Optimization
--------------------------------
Model Quantization:
• Original: FP32 (32-bit floating point)
• Quantized: INT8 (8-bit integer)
• Size reduction: 75% (e.g., 10MB → 2.5MB)
• Speedup: 2-4× on CPU, 10-20× on TPU/GPU
• Accuracy loss: <2% (acceptable for edge deployment)

Pruning:
• Remove weights with magnitude < threshold
• Target sparsity: 50% (half weights removed)
• Fine-tune after pruning to recover accuracy

Knowledge Distillation:
• Train small "student" model to mimic large "teacher" model
• Student model: 10× smaller, 5× faster
• Accuracy: Within 3% of teacher

21.3 Edge AI Inference Pipeline
--------------------------------
┌─────────────────────────────────────────────────────────────────────────────┐
│  CAN Frame Arrival (10 Hz)                                                │
│       ↓                                                                   │
│  Feature Extraction (Python, <5 ms)                                       │
│       ↓                                                                   │
│  Rule-Based Anomaly Detection (<10 ms)                                    │
│       ↓                                                                   │
│  [IF rule triggers] → Immediate Alert → Local Action                      │
│       ↓ [IF no rule trigger]                                              │
│  TFLite Model Inference (<50 ms on RPi, <10 ms on Jetson)               │
│       ↓                                                                   │
│  [IF anomaly detected] → Alert + Buffer Data → Sync to GCS              │
│       ↓ [IF normal]                                                       │
│  Buffer Data → Batch Upload to GCS (when connectivity available)          │
└─────────────────────────────────────────────────────────────────────────────┘

21.4 Edge AI Use Cases
-----------------------
USE CASE 1: Critical Alert Onboard Processing
• Detect CHT > 230°C or Oil Pressure < 25 psi
• Trigger immediate alert (<50 ms)
• Automatic action: Reduce throttle to 50% (if FADEC integration available)
• No GCS dependency — works even in communication loss

USE CASE 2: Anomaly Scoring
• Run TFLite anomaly detection model every 30 seconds
• Compute anomaly score
• If score > 0.8: Transmit detailed data to GCS immediately
• If score < 0.8: Buffer data for batch upload

USE CASE 3: Health Index Update
• Update health index every 60 seconds using edge-computed features
• If health index drops by > 0.1 in 10 minutes: Transmit immediately
• Otherwise: Include in regular telemetry

USE CASE 4: Offline Operation
• If GCS link lost for > 5 minutes:
  - Switch to offline mode
  - Continue all edge processing
  - Buffer all data locally (72-hour capacity)
  - Log all alerts locally
  - Upon link restoration: Automatic sync of buffered data

================================================================================
22. FEDERATED LEARNING ARCHITECTURE
================================================================================

22.1 Federated Learning Concept
--------------------------------
Federated Learning enables training AI/ML models across a fleet of UAVs without
centralizing sensitive telemetry data. Each aircraft trains a local model on
its own data, and only model updates (not raw data) are shared with a central
server.

22.2 Federated Learning Architecture
-------------------------------------
┌─────────────────────────────────────────────────────────────────────────────┐
│  CENTRAL SERVER (GCS)                                                     │
│  ├── Global Model (initialized with C-MAPSS pre-training)                 │
│  ├── Aggregation Engine (FedAvg, FedProx, or SCAFFOLD)                  │
│  └── Model Distribution (push updated model to fleet)                     │
├─────────────────────────────────────────────────────────────────────────────┤
│  UAV 1 (Edge Node)          │  UAV 2 (Edge Node)        │  UAV N          │
│  ├── Local Data (engine     │  ├── Local Data           │  ├── Local Data │
│  │   telemetry, failures)   │  │   (different patterns)  │  │   (different) │
│  ├── Local Model Training   │  ├── Local Model Training │  ├── Local Train│
│  │   (1-2 epochs)           │  │   (1-2 epochs)          │  │   (1-2 epochs)│
│  └── Model Update Upload    │  └── Model Update Upload  │  └── Update     │
│       (gradients/weights)   │       (gradients/weights) │       (gradients)│
└─────────────────────────────────────────────────────────────────────────────┘

22.3 Federated Learning Protocol
---------------------------------
ROUND 1: Initialization
• Central server initializes global model (pre-trained on C-MAPSS)
• Distributes global model to all UAVs in fleet

ROUND 2: Local Training
• Each UAV trains local model on its own engine data for 1-2 epochs
• Data remains on aircraft — never leaves the edge node
• Local training captures aircraft-specific degradation patterns

ROUND 3: Update Upload
• Each UAV computes model update (gradient differences or weight deltas)
• Uploads only the update (compressed, differential privacy applied)
• Upload size: ~100 KB per round (vs. ~10 GB for raw telemetry)

ROUND 4: Aggregation
• Central server aggregates updates using FedAvg:
  w_global = Σ (n_k / n_total) × w_k
  Where n_k = number of samples on UAV k, w_k = updated weights from UAV k
• Alternative: FedProx (handles non-IID data better)
• Alternative: SCAFFOLD (corrects for client drift)

ROUND 5: Distribution
• Central server distributes updated global model to all UAVs
• UAVs replace local model with global model
• Repeat from Round 2

22.4 Privacy & Security in Federated Learning
----------------------------------------------
Differential Privacy:
• Add Gaussian noise to model updates before upload
• Privacy budget: ε = 1.0 (strong privacy)
• Trade-off: Slight accuracy reduction (<3%) for strong privacy guarantee

Secure Aggregation:
• Use secure multi-party computation (SMPC) to aggregate updates
• Central server cannot see individual updates, only the aggregate
• Implementation: PySyft or TensorFlow Federated (TFF)

Model Poisoning Detection:
• Detect malicious or corrupted updates
• Methods: Cosine similarity check, median aggregation (instead of mean),
  reputation scoring per UAV

22.5 Benefits for DRDO Fleet
-----------------------------
• Operational Security: Raw telemetry never leaves the aircraft
• Personalized Models: Each UAV learns its own engine's unique characteristics
• Fleet Intelligence: Global model benefits from all aircraft's experience
• Bandwidth Efficiency: 100× reduction in data transmission
• Regulatory Compliance: Easier to meet data sovereignty requirements

================================================================================
23. DESIRED INNOVATION AREAS (ALL 8)
================================================================================

The problem statement explicitly encourages exploration of 8 innovation areas.
The system shall address all 8:

INNOVATION 1: Physics-Informed AI
----------------------------------
• Implementation: Cantera combustion model + DeepXDE PINN
• Innovation: Combines first-principles thermodynamics with neural network
  flexibility. Physics loss functions constrain predictions to physically
  valid regions.
• Benefit: 50-70% less training data required, better generalization,
  interpretable predictions
• Demonstration: Show CHT/EGT predictions with and without physics constraints

INNOVATION 2: Edge AI for UAV Applications
-------------------------------------------
• Implementation: TensorFlow Lite on Raspberry Pi 4 / NVIDIA Jetson Nano
• Innovation: Critical anomaly detection processed onboard with <50 ms latency,
  no GCS dependency
• Benefit: Works during communication loss, reduces bandwidth, enables
  real-time autonomous responses
• Demonstration: Live edge node processing demo with simulated CAN data

INNOVATION 3: Lightweight Onboard Analytics
--------------------------------------------
• Implementation: Quantized INT8 models, pruned networks, knowledge distillation
• Innovation: 10MB model compressed to 2.5MB with <2% accuracy loss
• Benefit: Fits on resource-constrained edge hardware, fast inference,
  low power consumption
• Demonstration: Model size comparison, inference speed benchmark

INNOVATION 4: Hybrid Thermodynamic + Data-Driven Models
--------------------------------------------------------
• Implementation: Physics model provides baseline + neural network learns
  residual correction
• Innovation: y_pred = y_physics + NN(residual_features)
• Benefit: Physics provides interpretability and data efficiency; NN captures
  complex nonlinear effects physics misses
• Demonstration: Compare pure physics, pure data-driven, and hybrid approaches

INNOVATION 5: Federated Learning Approaches
--------------------------------------------
• Implementation: PySyft or TensorFlow Federated for fleet-wide model training
• Innovation: Train on 76 TAPAS UAVs without centralizing sensitive telemetry
• Benefit: Operational security, personalized models, fleet intelligence,
  bandwidth efficiency
• Demonstration: Architecture diagram, privacy analysis, bandwidth comparison

INNOVATION 6: Explainable AI for Fault Diagnosis
-------------------------------------------------
• Implementation: SHAP global + local explanations, LIME local surrogates,
  natural language generation
• Innovation: Every alert includes "WHY" — which sensors, what magnitude,
  what confidence
• Benefit: Operator trust, maintenance decision support, defense audit compliance
• Demonstration: SHAP force plot for sample alert, natural language explanation

INNOVATION 7: Secure Telemetry Architecture
--------------------------------------------
• Implementation: TLS 1.3, JWT RBAC, Zero Trust network segmentation,
  AES-256 at rest, differential privacy in federated learning
• Innovation: Defense-grade security with zero proprietary licensing cost
• Benefit: Meets NIST 800-171 and DO-326A conceptual requirements,
  protects against interception, tampering, and unauthorized access
• Demonstration: Security architecture diagram, encryption benchmark

INNOVATION 8: Autonomous Maintenance Advisory Systems
------------------------------------------------------
• Implementation: Rule engine + SHAP explanations + automated scheduling +
  spare parts forecasting
• Innovation: System automatically generates, prioritizes, schedules, and
  distributes maintenance recommendations
• Benefit: Reduces cognitive load, ensures consistent decision-making,
  optimizes fleet readiness
• Demonstration: End-to-end advisory generation for sample fault scenario

================================================================================
24. TECHNICAL EXPECTATIONS COMPLIANCE MATRIX
================================================================================

The problem statement lists 9 technical expectations. The following matrix
demonstrates how each expectation is addressed:

┌─────────────────────────────┬──────────────────────────────────────────────┐
│ TECHNICAL EXPECTATION       │ SOLUTION COMPONENT                           │
├─────────────────────────────┼──────────────────────────────────────────────┤
│ IC Engine Fundamentals      │ 0-D MVEM with Wiebe burn profile, Cantera    │
│                             │ combustion kinetics, thermodynamic cycles    │
├─────────────────────────────┼──────────────────────────────────────────────┤
│ UAV Propulsion Systems      │ Rotax 914 specification model, turbocharger  │
│                             │ model, altitude performance maps, TBO        │
│                             │ tracking                                     │
├─────────────────────────────┼──────────────────────────────────────────────┤
│ Sensor Fusion               │ 3-level fusion (data, feature, decision),    │
│                             │ Kalman filter, multi-sensor voting, cross-   │
│                             │ correlation analysis                         │
├─────────────────────────────┼──────────────────────────────────────────────┤
│ Embedded Systems            │ Raspberry Pi 4 / Jetson Nano edge node,      │
│                             │ PiCAN2 HAT, real-time processing pipeline    │
├─────────────────────────────┼──────────────────────────────────────────────┤
│ CAN Communication           │ SocketCAN/vcan, python-can, CANdevStudio,    │
│                             │ DBC file specification, 1 Mbps bus           │
├─────────────────────────────┼──────────────────────────────────────────────┤
│ AI/ML Analytics             │ 3-tier anomaly detection, LSTM RUL,          │
│                             │ PyOD ensemble, transfer learning, SHAP XAI   │
├─────────────────────────────┼──────────────────────────────────────────────┤
│ Data Visualization          │ Grafana 12-panel dashboard, Streamlit HMI,   │
│                             │ real-time refresh, role-based views          │
├─────────────────────────────┼──────────────────────────────────────────────┤
│ Simulation Modelling        │ 0-D MVEM, Cantera equilibrium, 5             │
│                             │ environmental conditions, mission replay,    │
│                             │ what-if scenario engine                      │
├─────────────────────────────┼──────────────────────────────────────────────┤
│ Reliability Engineering     │ RUL estimation, degradation factor tracking, │
│                             │ Weibull failure analysis, TBO optimization,  │
│                             │ mission abort risk assessment                │
└─────────────────────────────┴──────────────────────────────────────────────┘

================================================================================
25. DELIVERABLES & DEPLOYMENT ROADMAP
================================================================================

25.1 Required Deliverables (Per Problem Statement)
---------------------------------------------------

DELIVERABLE 1: Functional Prototype / Software Demonstrator
• Working Digital Twin system with all 5 layers operational
• Live dashboard with real-time parameter display
• Simulated CAN bus data feeding the system
• 5 pre-built mission scenarios for demonstration
• Docker containerization for easy deployment

DELIVERABLE 2: Digital Twin Architecture Design
• 5-layer architecture diagram (system, component, deployment views)
• Interface specification (API contracts, data formats)
• Technology stack documentation
• Scalability and security architecture
• STANAG 4586 conceptual alignment document

DELIVERABLE 3: Engine Simulation Model
• 0-D Mean-Value Engine Model (Python + SciPy)
• Cantera combustion model integration
• Performance map library (5 maps)
• Degradation model (6 degradation pathways)
• Validation report: Predicted vs actual error analysis

DELIVERABLE 4: AI/ML-Based Anomaly Detection Module
• 3-tier anomaly detection system (rule + statistical + deep learning)
• 8 fault classifiers (one per required fault)
• LSTM RUL estimation model
• Transfer learning pipeline (C-MAPSS → synthetic Rotax)
• Performance report: Accuracy, precision, recall, F1, RMSE

DELIVERABLE 5: Visualization Dashboard
• Grafana dashboard with 10+ panels
• Real-time refresh (≤2 seconds)
• 5-level alert system with audio/visual notifications
• Mission replay controls
• SHAP explanation integration
• Role-based views (4 roles)

DELIVERABLE 6: Demonstration Using Simulated Datasets
• 5 mission scenarios (high altitude, endurance, hot weather, rapid throttle,
  maritime)
• Simulated run-to-failure dataset (100 virtual engines)
• Fault injection demonstrations (all 8 faults)
• What-if scenario demonstrations
• 3-minute demo video with voiceover

DELIVERABLE 7: Technical Documentation
• This PRD (3 parts)
• API documentation (OpenAPI 3.0 specification)
• User manual (operator, engineer, maintenance, commander)
• Deployment guide (installation, configuration, troubleshooting)
• Model training guide (dataset preparation, training, validation)

DELIVERABLE 8: Deployment Roadmap
• Phase 1: Engine-centric Digital Twin (3 months)
• Phase 2: Aircraft ecosystem integration (6 months)
• Phase 3: Fleet-level deployment (12 months)
• Hardware requirements specification
• Software dependencies and versions
• Risk assessment and mitigation

25.2 Deployment Roadmap
------------------------

PHASE 1: ENGINE-CENTRIC DIGITAL TWIN (Months 1-3)
--------------------------------------------------
Month 1: Foundation
• Week 1-2: Environment setup, CAN bus simulation, data pipeline
• Week 3-4: Physics model implementation, Cantera integration
• Deliverable: Working data ingestion + physics model

Month 2: Core DT + Health Monitoring
• Week 5-6: Eclipse Ditto deployment, twin state management
• Week 7-8: Health monitoring system, 5-level alerts
• Deliverable: Working health monitoring with simulated data

Month 3: AI/ML Layer
• Week 9-10: Anomaly detection training, RUL model training
• Week 11-12: Fault classifiers, SHAP integration
• Deliverable: Working AI/ML pipeline with demo scenarios

PHASE 2: AIRCRAFT ECOSYSTEM INTEGRATION (Months 4-6)
------------------------------------------------------
Month 4: Simulation & Replay
• Mission replay engine
• Environmental condition simulation
• What-if scenario engine
• Deliverable: Full simulation capability

Month 5: Visualization & HMI
• Grafana dashboard deployment
• Streamlit HMI for rapid prototyping
• Alert notification system
• Deliverable: Production-ready dashboard

Month 6: Security & Edge AI
• TLS 1.3 implementation, RBAC, audit logging
• Edge AI deployment on Raspberry Pi
• Federated learning architecture
• Deliverable: Security-hardened system with edge capability

PHASE 3: FLEET-LEVEL DEPLOYMENT (Months 7-12)
----------------------------------------------
Month 7-8: Pilot Deployment
• Deploy on 2-3 TAPAS-BH-201 test aircraft
• Collect real telemetry data
• Validate models against real engine behavior
• Iterate based on feedback

Month 9-10: Scale-Up
• Deploy to full test fleet (10-20 aircraft)
• Fleet-level health monitoring
• Maintenance scheduling optimization
• Performance benchmarking

Month 11-12: Production Readiness
• HAL production integration
• BEL GCS electronics integration
• DRDO acceptance testing
• Documentation finalization
• Training for IAF/Navy/Army operators

================================================================================
26. PERFORMANCE BENCHMARKS & VALIDATION CRITERIA
================================================================================

26.1 Real-Time Performance Targets
-----------------------------------
┌────────────────────────────────────────┬─────────────────┬─────────────────┐
│ METRIC                                 │ TARGET          │ ACCEPTABLE      │
├────────────────────────────────────────┼─────────────────┼─────────────────┤
│ Sensor-to-ingestion latency            │ < 10 ms         │ < 50 ms         │
│ Physics model update latency           │ < 20 ms         │ < 100 ms        │
│ Anomaly detection latency (rule)       │ < 5 ms          │ < 10 ms         │
│ Anomaly detection latency (statistical)│ < 50 ms         │ < 200 ms        │
│ Anomaly detection latency (deep)       │ < 100 ms        │ < 500 ms        │
│ Health index update latency            │ < 5 ms          │ < 20 ms         │
│ RUL estimation latency                 │ < 100 ms        │ < 500 ms        │
│ Alert generation latency               │ < 2 ms          │ < 10 ms         │
│ Dashboard refresh latency              │ < 2 seconds     │ < 5 seconds     │
│ End-to-end (sensor to alert)           │ < 100 ms        │ < 500 ms        │
└────────────────────────────────────────┴─────────────────┴─────────────────┘

26.2 Model Accuracy Targets
----------------------------
┌────────────────────────────────────────┬─────────────────┬─────────────────┐
│ METRIC                                 │ TARGET          │ ACCEPTABLE      │
├────────────────────────────────────────┼─────────────────┼─────────────────┤
│ CHT prediction error (RMSE)            │ < 5°C           │ < 10°C          │
│ EGT prediction error (RMSE)            │ < 10°C          │ < 20°C          │
│ Torque prediction error (MAPE)         │ < 5%            │ < 10%           │
│ Fuel flow prediction error (MAPE)      │ < 3%            │ < 5%            │
│ Anomaly detection precision            │ > 0.90          │ > 0.85          │
│ Anomaly detection recall               │ > 0.95          │ > 0.90          │
│ Fault classification accuracy          │ > 0.90          │ > 0.85          │
│ RUL estimation RMSE                    │ < 25 hours      │ < 50 hours      │
│ RUL estimation NASA Score              │ < 500           │ < 1000          │
│ Health index correlation (vs actual)   │ r > 0.90        │ r > 0.85        │
└────────────────────────────────────────┴─────────────────┴─────────────────┘

26.3 System Reliability Targets
--------------------------------
• Uptime: > 99.9% (excluding planned maintenance)
• Data loss: < 0.01% (with local buffering and redundant storage)
• Alert false positive rate: < 5%
• Alert false negative rate: < 2% (critical faults must not be missed)
• Model retraining frequency: Every 100 flight hours or when accuracy drops
  below acceptable threshold

26.4 Scalability Targets
-------------------------
• Concurrent engine twins: 100+ (single GCS instance)
• Telemetry ingestion rate: 10,000 data points/second
• Historical data retention: 2 years (with automated archiving)
• Fleet report generation: < 5 minutes for 100 engines
• Model inference throughput: 100+ predictions/second

================================================================================
27. RISK ASSESSMENT & MITIGATION STRATEGIES
================================================================================

RISK 1: Insufficient Real Engine Data for Training
• Probability: HIGH
• Impact: HIGH
• Mitigation:
  - Use NASA C-MAPSS for transfer learning pre-training
  - Generate physically accurate synthetic data from Cantera + MVEM
  - Use IDF-DS19 for realistic flight patterns
  - Partner with DRDO VRDE for test rig data access
  - Implement active learning: system requests operator labels for uncertain cases

RISK 2: Model Accuracy Insufficient for Defense Deployment
• Probability: MEDIUM
• Impact: HIGH
• Mitigation:
  - Physics-informed AI provides interpretable baseline
  - Hybrid model combines physics + data-driven strengths
  - Continuous model validation against physics constraints
  - Human-in-the-loop: All critical alerts require operator confirmation
  - Graceful degradation: If model confidence is low, fall back to threshold-based

RISK 3: Real-Time Performance Not Achievable on Target Hardware
• Probability: MEDIUM
• Impact: MEDIUM
• Mitigation:
  - Optimize models via quantization, pruning, knowledge distillation
  - Use edge AI for critical alerts, cloud for detailed analytics
  - Parallel processing: Multi-threaded pipeline
  - Hardware upgrade path: Jetson Nano → Jetson Orin for production

RISK 4: Security Vulnerabilities in Open-Source Stack
• Probability: LOW
• Impact: HIGH
• Mitigation:
  - Regular security audits of all dependencies
  - Automated vulnerability scanning (Dependabot, Snyk)
  - Defense-in-depth: Multiple security layers
  - Regular updates: Patch management process
  - Penetration testing before production deployment

RISK 5: Integration Challenges with DRDO Legacy Systems
• Probability: MEDIUM
• Impact: MEDIUM
• Mitigation:
  - Modular architecture allows incremental integration
  - Adapter pattern for legacy protocol conversion
  - OpenAPI specification for easy integration
  - Pilot deployment on test aircraft before fleet-wide rollout
  - Close collaboration with DRDO ADE, BEL, HAL teams

RISK 6: Team Skill Gaps in Specialized Areas
• Probability: MEDIUM
• Impact: MEDIUM
• Mitigation:
  - Pre-hackathon training: Cantera, PyOD, TensorFlow, Grafana
  - Online courses: Fast.ai, Coursera, edX
  - Community support: Stack Overflow, GitHub issues, Discord servers
  - Mentor network: Reach out to DRDO scientists, university professors
  - Division of labor: Assign team members to areas matching their strengths

================================================================================
END OF PRD PART 3
END OF COMPLETE TECHNICAL PRD
================================================================================
