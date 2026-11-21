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
TECHNICAL PRODUCT REQUIREMENTS DOCUMENT (PRD) — PART 2 of 3
SIH 2026 / DRDO IDEX Problem Statement 26054
AI-Enabled Real-Time Digital Twin for Aero Piston Engines in MALE UAVs
================================================================================
Document Version: 1.0
Date: 22 August 2026
Classification: Internal Technical Document
================================================================================

TABLE OF CONTENTS — PRD PART 2
================================================================================
9. Health Monitoring System Specification
10. Fault Detection & Predictive Analytics (All 8 Required Faults)
11. AI/ML Layer — Anomaly Detection Architecture
12. AI/ML Layer — Remaining Useful Life (RUL) Estimation
13. AI/ML Layer — Trend Analysis & Predictive Maintenance
14. Physics-Informed Neural Network (PINN) Specification
15. Explainable AI (XAI) for Fault Diagnosis
16. Autonomous Maintenance Advisory System

================================================================================
9. HEALTH MONITORING SYSTEM SPECIFICATION
================================================================================

9.1 System Objective
---------------------
The Health Monitoring System shall continuously assess the condition of all
engine subsystems and generate quantitative health indices for predictive
maintenance decision support. The system shall transition from conventional
threshold-based reactive monitoring to a predictive, model-based approach that
estimates current health, predicts future degradation, and recommends
maintenance actions before failure occurs.

9.2 Monitored Engine Parameters (All 8 Required)
-------------------------------------------------

PARAMETER 1: RPM (Engine Speed)
• Monitoring Objective: Detect misfire, governor failure, propeller issues,
  power loss, overspeed conditions
• Health Indicator: RPM stability index (RSI)
  RSI = 1 - (σ_RPM_1s / RPM_nominal)
  Where σ_RPM_1s = standard deviation of RPM over 1-second window
  Normal: RSI > 0.995 (σ < ±10 rpm at 2,500 rpm)
  Degraded: RSI 0.98 – 0.995 (σ ±20-50 rpm)
  Fault: RSI < 0.98 (σ > ±50 rpm)
• Subsystem: Mechanical / Combustion

PARAMETER 2: CHT (Cylinder Head Temperature)
• Monitoring Objective: Detect cooling system degradation, combustion
  abnormalities, thermal overload, pre-ignition, detonation
• Health Indicator: Thermal Health Index (THI)
  THI = 1 - max(0, (CHT_max - CHT_nominal) / (CHT_limit - CHT_nominal))
  [REVISED AT REV 2 — the reference values below were air-cooled figures]
  Where CHT_max = maximum CHT across all 4 cylinders
  CHT_nominal = 105°C (cruise, ISA conditions)
  CHT_limit   = 135°C — Rotax family CHT limit [TCDS, 912 S series]
  A PARALLEL index is computed on COOLANT temperature, which is this engine's
  CERTIFIED thermal limit: coolant_nominal = 95°C, coolant_limit = 120°C.
  Normal: THI > 0.85     Degraded: THI 0.70 – 0.85     Fault: THI < 0.70
• Subsystem: Thermal
• Additional Metric: CHT Spread Index (CSI)
  CSI = 1 - (CHT_spread / CHT_spread_limit)
  Where CHT_spread = max(CHT) - min(CHT) across cylinders
  CHT_spread_limit = 25°C  [REVISED AT REV 2: liquid-cooled heads run far
  more even than the air-cooled heads the 80°C figure assumed]
  Normal: CSI > 0.90 (spread < 8°C)
  Degraded: CSI 0.75 – 0.90 (spread 8-20°C)
  Fault: CSI < 0.75 (spread > 20°C)

PARAMETER 3: EGT (Exhaust Gas Temperature)
• Monitoring Objective: Detect lean/rich mixture, injector imbalance,
  combustion inefficiency, turbocharger issues
• Health Indicator: Combustion Health Index (CombHI)
  NOTE: named "CombHI" (not "CHI") to avoid collision with the top-level
  Composite Health Index (CHI) defined in §9.3. CombHI is the combustion
  sub-index that feeds the composite.
  CombHI = 1 - max(0, (EGT_spread - EGT_spread_nominal) / (EGT_spread_limit - EGT_spread_nominal))
  Where EGT_spread_nominal = 40°C (new engine, balanced injectors)
  EGT_spread_limit = 200°C — the CERTIFIED EGT-split limit above 3 L/hr fuel
  flow [OM §2.1]; 500°C applies below 3 L/hr.  [REVISED AT REV 2]
  Normal: CombHI > 0.90 (spread < 22°C)
  Degraded: CombHI 0.75 – 0.90 (spread 22-35°C)
  Fault: CombHI < 0.75 (spread > 35°C)
• Subsystem: Combustion
• Additional Metric: EGT Efficiency Factor (EEF)
  EEF = (EGT_predicted - EGT_actual) / EGT_predicted
  Positive EEF: Lean mixture or combustion degradation
  Negative EEF: Rich mixture or cooling issue
  Normal: |EEF| < 0.05 (5% deviation)
  Degraded: |EEF| 0.05 – 0.10
  Fault: |EEF| > 0.10

PARAMETER 4: Oil Pressure
• Monitoring Objective: Detect bearing wear, oil pump degradation, leaks,
  filter blockage, oil quality degradation
• Health Indicator: Lubrication Health Index (LHI)
  LHI = (P_oil_actual / P_oil_predicted) × η_correlation
  Where P_oil_predicted = f(RPM, oil_temp, nominal viscosity)
  η_correlation = Pearson correlation coefficient between P_oil and RPM
    over last 60 seconds (nominal: > 0.95)
  Normal: LHI > 0.90
  Degraded: LHI 0.80 – 0.90
  Fault: LHI < 0.80
• Subsystem: Mechanical
• Additional Metric: Oil Pressure Trend (OPT)
  OPT = slope of P_oil vs time regression (last 10 minutes)
  Normal: OPT ≈ 0 (stable)
  Degraded: OPT < -0.5 psi/min (gradual pressure loss)
  Fault: OPT < -2.0 psi/min (rapid pressure loss)

PARAMETER 5: Oil Temperature
• Monitoring Objective: Detect cooling system issues, bearing overheating,
  oil degradation, insufficient oil capacity
• Health Indicator: Oil Thermal Index (OTI)
  OTI = 1 - max(0, (T_oil - T_oil_nominal) / (T_oil_limit - T_oil_nominal))
  Where T_oil_nominal = 95°C (cruise)
  T_oil_limit = 130°C (critical)
  Normal: OTI > 0.80 (T_oil < 105°C)
  Degraded: OTI 0.65 – 0.80 (T_oil 105-120°C)
  Fault: OTI < 0.65 (T_oil > 120°C)
• Subsystem: Thermal / Mechanical

PARAMETER 6: Fuel Flow
• Monitoring Objective: Detect injector issues, fuel pump degradation, leaks,
  mixture abnormalities, efficiency loss
• Health Indicator: Fuel System Health Index (FSHI)
  FSHI = (BSFC_actual / BSFC_nominal)^(-1)
  Where BSFC_actual = fuel_flow / (BMEP × V_d × N_cyl × N_e / (2 × 60 × 1000))
  BSFC_nominal = from performance map at current operating point
  Normal: FSHI > 0.95 (BSFC within 5% of nominal)
  Degraded: FSHI 0.90 – 0.95 (BSFC 5-10% high)
  Fault: FSHI < 0.90 (BSFC > 10% high)
• Subsystem: Combustion
• Additional Metric: Fuel Flow Variance Index (FFVI)
  FFVI = 1 - (σ_fuel_flow / μ_fuel_flow)
  Where σ and μ computed over 60-second window
  Normal: FFVI > 0.95 (CV < 5%)
  Degraded: FFVI 0.85 – 0.95 (CV 5-15%)
  Fault: FFVI < 0.85 (CV > 15%, indicates injector instability)

PARAMETER 7: Vibration Signatures
• Monitoring Objective: Detect bearing wear, gear damage, propeller imbalance,
  mount looseness, structural resonance
• Health Indicator: Mechanical Health Index (MHI)
  MHI = 1 - max(0, (V_rms - V_nominal) / (V_limit - V_nominal))
  Where V_rms = total RMS vibration (X² + Y² + Z²)^0.5
  V_nominal = 2.0 m/s² (cruise, balanced engine)
  V_limit = 8.0 m/s² (structural damage risk)
  Normal: MHI > 0.90 (V_rms < 2.6 m/s²)
  Degraded: MHI 0.75 – 0.90 (V_rms 2.6-4.5 m/s²)
  Fault: MHI < 0.75 (V_rms > 4.5 m/s²)
• Subsystem: Mechanical
• Additional Metrics:
  - Unbalance Index: Amplitude at 1× RPM frequency
  - Misalignment Index: Amplitude at 2× RPM frequency
  - Gear Wear Index: Amplitude at gear mesh frequency (reduction gear)
  - Bearing Health Index: Envelope spectrum peak at BPFO/BPFI

PARAMETER 8: Battery / Alternator Health
• Monitoring Objective: Detect alternator failure, battery degradation,
  charging system issues, electrical overload
• Health Indicator: Electrical Health Index (EHI)
  EHI = 0.5 × (V_stability) + 0.3 × (I_capacity) + 0.2 × (SOH_battery)
  Where:
    V_stability = 1 - (σ_V_batt / 0.5V) [σ over 60 seconds, nominal < 0.2V]
    I_capacity = I_alternator_actual / I_alternator_rated
    SOH_battery = f(cycle_count, internal_resistance, voltage_under_load)
  Normal: EHI > 0.90
  Degraded: EHI 0.80 – 0.90
  Fault: EHI < 0.80
• Subsystem: Electrical

9.3 Composite Health Index (CHI)
---------------------------------
The system shall compute a top-level Composite Health Index combining all
subsystem indices:

CHI = w_thermal × THI + w_mechanical × MHI + w_electrical × EHI + w_combustion × CombHI

(Here CHI = top-level Composite Health Index; CombHI = Combustion Health Index
from §9.2 Parameter 3. Do not confuse the two.)

Where:
  w_thermal = 0.30 (thermal stress is primary failure mode in piston engines)
  w_mechanical = 0.25 (bearing, gear, structural integrity)
  w_electrical = 0.20 (ignition, FADEC, sensor power)
  w_combustion = 0.25 (combustion quality, efficiency, emissions)

CHI Interpretation:
  0.90 – 1.00: EXCELLENT — Engine in new or near-new condition
  0.80 – 0.90: GOOD — Normal wear, no action required
  0.70 – 0.80: FAIR — Degradation detected, monitor closely
  0.60 – 0.70: POOR — Maintenance recommended within 25 flight hours
  0.50 – 0.60: DEGRADED — Maintenance required within 10 flight hours
  0.40 – 0.50: CRITICAL — Maintenance required before next flight
  < 0.40: UNSAFE — Ground aircraft immediately

9.4 Health Trend Tracking
--------------------------
The system shall track health index trends using:

METHOD 1: Moving Average with Exponential Weighting
  CHI_ema(t) = α × CHI(t) + (1-α) × CHI_ema(t-1)
  Where α = 0.1 (slow response, filters noise)
  Trend direction: slope of CHI_ema over 10-flight-hour window

METHOD 2: Kalman Filter State Estimation
  State vector: x = [CHI, dCHI/dt, degradation_rate]
  Process model: x(t+1) = F × x(t) + w
  Where F = [[1, Δt, 0.5×Δt²], [0, 1, Δt], [0, 0, 1]]
  Measurement: z(t) = H × x(t) + v
  Where H = [1, 0, 0]
  Kalman gain updated at each measurement
  Output: Smoothed CHI + estimated degradation rate

METHOD 3: Degradation Onset Detection
  CUSUM (Cumulative Sum) algorithm:
  S_t = max(0, S_{t-1} + (CHI_nominal - CHI(t)) - K)
  Where K = 0.02 (drift allowance)
  Alert when S_t > H (H = 0.5, threshold for degradation onset)
  This detects the "knee point" where health begins declining

9.5 Alert Level System
-----------------------
The system shall implement a 5-level alert system:

LEVEL 1 — GREEN (Normal):
  • Condition: All parameters within normal range, CHI > 0.90
  • Action: Log data, no operator notification
  • Display: Green indicator on dashboard
  • Audio: None

LEVEL 2 — BLUE (Advisory):
  • Condition: Trend detected but within normal range, CHI 0.85-0.90
  • Action: Log data, display advisory message, no immediate action
  • Examples: "Cooling efficiency trending down 2% over last 50 hours"
  • Display: Blue indicator with information icon
  • Audio: None

LEVEL 3 — YELLOW (Caution):
  • Condition: Parameter outside normal but within safe range, CHI 0.75-0.85
  • Action: Display caution message, recommend monitoring
  • Examples: "CHT at 127°C — monitor closely, reduce power if trend continues"
  • Display: Yellow indicator with warning icon
  • Audio: Single beep

LEVEL 4 — ORANGE (Warning):
  • Condition: Degradation confirmed, maintenance required soon, CHI 0.60-0.75
  • Action: Display warning message, recommend maintenance action
  • Examples: "Oil pressure correlation degraded. Schedule inspection within
    10 flight hours."
  • Display: Orange indicator with alert icon, flashing
  • Audio: Periodic beep (every 30 seconds)

LEVEL 5 — RED (Emergency):
  • Condition: Critical parameter exceeded, immediate action required, CHI < 0.60
  • Action: Display emergency message, recommend immediate power reduction or
    engine shutdown
  • Examples: "CHT CRITICAL at 137°C! Reduce power immediately!"
  • Display: Red indicator with emergency icon, flashing rapidly
  • Audio: Continuous alarm tone
  • Automatic Action: If configured, automatic power reduction to 50%

9.6 Health Report Generation
-----------------------------
The system shall generate automated health reports:

MISSION REPORT (Post-Flight):
  • Generated automatically after each flight
  • Content: Max/min/average of all parameters, health index trajectory,
    alert summary, degradation detected, maintenance recommendations
  • Format: PDF + JSON for database storage
  • Distribution: Maintenance team, propulsion engineer, operator

WEEKLY FLEET REPORT:
  • Generated every Sunday at 00:00 UTC
  • Content: Health status of all engines in fleet, trending analysis,
    maintenance scheduling recommendations, spare parts forecasting
  • Format: PDF dashboard + CSV data export
  • Distribution: Fleet manager, maintenance chief, DRDO liaison

ON-DEMAND REPORT:
  • Generated upon operator request
  • Content: Customizable — any time range, any parameters, any engine
  • Format: PDF, CSV, or JSON
  • Distribution: Per request

================================================================================
10. FAULT DETECTION & PREDICTIVE ANALYTICS (ALL 8 REQUIRED FAULTS)
================================================================================

10.1 Fault 1: Misfire Conditions
---------------------------------
DEFINITION: Failure of air-fuel mixture to ignite in one or more cylinders,
resulting in incomplete or absent power stroke.

PHYSICAL CAUSES:
• Ignition system: Failed spark plug, degraded CDI unit, broken ignition lead
• Fuel system: Clogged injector/nozzle, fuel starvation, incorrect mixture
• Mechanical: Low compression (worn rings, valve leak), incorrect valve timing
• Environmental: Excessive moisture, extreme cold start, altitude effects

DETECTION METHODS:

Method A: RPM Fluctuation Analysis (Primary)
  • Sampling: RPM at 100 Hz (per crankshaft revolution)
  • Processing: Detect instantaneous RPM drop during power stroke of each
    cylinder
  • Algorithm: For 4-cylinder 4-stroke, power stroke every 180° CA
    Compute ΔRPM_i = RPM(θ_i) - RPM(θ_i + 180°)
    Where θ_i = crank angle at TDC for cylinder i
    Misfire detected if ΔRPM_i < threshold (typically -50 rpm)
  • Sensitivity: Detects >90% of misfires within 2 engine revolutions
  • False Positive Rate: <2% (filtered by EGT confirmation)

Method B: Per-Cylinder EGT Drop (Confirmation)
  • EGT on misfiring cylinder drops 50-150°C within 1-2 seconds
  • Detection: EGT_cyl_i < EGT_avg - 3σ_EGT
  • Cross-reference with RPM fluctuation for confirmation

Method C: Cylinder Pressure Imbalance (If Pressure Sensors Available)
  • Peak cylinder pressure on misfiring cylinder < 70% of nominal
  • IMEP (indicated mean effective pressure) drop > 30%

Method D: Vibration Signature
  • Misfire creates characteristic 0.5× RPM sub-harmonic in vibration
  • FFT analysis: Peak at 0.5× RPM frequency with amplitude > 2× baseline

PREDICTION (Before Occurrence):
  • Precursor: Gradual increase in EGT variance (CV > 8%) over 10+ flight hours
  • Precursor: Ignition system degradation (spark energy drop > 15%)
  • Precursor: Fuel injector flow imbalance (CV > 10%)
  • ML Model: LSTM trained on [RPM_variance, EGT_spread, ignition_energy,
    injector_balance] → misfire probability within next 50 flight hours

RUL IMPACT:
  • Single misfire event: No RUL impact (immediate repair required)
  • Chronic misfire tendency: Combustion health index degradation, potential
    catalyst damage (if equipped), increased fuel consumption

10.2 Fault 2: Injector Abnormalities
-------------------------------------
DEFINITION: Deviation from nominal fuel injection quantity, timing, or spray
pattern in one or more cylinders.

PHYSICAL CAUSES:
• Nozzle fouling (carbon deposits, varnish)
• Nozzle wear (orifice enlargement, spray pattern degradation)
• Solenoid/piezo actuator degradation (response time increase)
• Fuel contamination (water, particulates, microbial growth)
• Fuel pressure irregularities (pump wear, regulator failure)

DETECTION METHODS:

Method A: Fuel Flow Variance Analysis (Primary)
  • Compute coefficient of variation (CV) of fuel flow per cylinder
    CV_i = σ_fuel_i / μ_fuel_i
    Where fuel per cylinder estimated from EGT correlation
  • Normal: CV < 5% across all cylinders
  • Degraded: CV 5-10% on one cylinder
  • Fault: CV > 10% or spread > 20% between max and min cylinder

Method B: EGT Spread Analysis (Confirmation)
  • EGT spread = max(EGT_cyl) - min(EGT_cyl)
  • Normal spread: < 15°C (new engine, balanced injectors)
  • Degraded: 15-30°C (beginning imbalance)
  • Fault: > 30°C (significant injector issue)
  • Cylinder-specific: Identify which cylinder has anomalous EGT

Method C: Injection Timing Deviation  [IMPLEMENTED — see PRD Part 1 §3.1 P9]
  • Monitor actual injection timing vs commanded timing
  • Normal: Deviation < ±1° CA
  • Degraded: Deviation ±1-3° CA
  • Fault: Deviation > ±3° CA
  • MECHANISM: the ECU compensates the injector's characterised nominal dead
    time, so a healthy engine reads ~0° deviation. Fouling and solenoid wear
    add an EXTRA opening delay the ECU cannot compensate, because it has no
    needle-lift feedback.
  • DISCRIMINATOR: a fixed millisecond delay subtends more crank angle at
    higher rpm, so injector wear gives a SPEED-DEPENDENT deviation. A sensor
    bias does not. Use this to separate fault 2 from fault 5.
  • Model verification: deviation 0.32° healthy → 6.92° at injector condition
    0.40, rising monotonically, with EGT spread tracking it 72°C → 165°C.

Method D: Combustion Quality Index (CQI)
  • CQI = (EGT_actual / EGT_predicted) × (P_cyl_peak_actual / P_cyl_peak_predicted)
  • Normal: CQI = 0.95 – 1.05
  • Degraded: CQI 0.85 – 0.95 or 1.05 – 1.15
  • Fault: CQI < 0.85 or > 1.15

PREDICTION (Before Occurrence):
  • Precursor: Gradual increase in EGT spread (slope > 0.5°C per 10 hours)
  • Precursor: Fuel flow CV trend increase
  • Precursor: BSFC increase > 3% over 50 flight hours
  • ML Model: Trend regression on EGT_spread + fuel_flow_variance + BSFC_trend

RUL IMPACT:
  • Minor injector fouling: 200-500 flight hours (cleaning restores performance)
  • Significant wear: 50-200 flight hours (replacement required)
  • Severe contamination: 0-50 flight hours (immediate action)

10.3 Fault 3: Cooling Degradation
----------------------------------
NOTE: Problem statement says "Coding degradation" which is a typo for
"Cooling degradation." The system shall address cooling system degradation.

DEFINITION: Reduction in cooling system effectiveness due to scale buildup,
coolant degradation, pump wear, airflow blockage, or thermostat issues.

PHYSICAL CAUSES:
• Scale/mineral deposits in cooling jackets (hard water, improper coolant)
• Coolant degradation (pH drop, additive depletion, contamination)
• Water pump impeller erosion or seal leakage
• Thermostat stuck partially closed
• Radiator / heat exchanger blockage (debris, oil contamination)
• Airflow reduction (cowling damage, fan degradation)

DETECTION METHODS:

Method A: CHT Residual vs Physics Model (Primary)
  • Compute residual: R_CHT = CHT_actual - CHT_predicted
  • CHT_predicted from physics model at current power, OAT, airspeed
  • Normal: |R_CHT| < 5°C
  • Degraded: R_CHT > 5°C (CHT higher than predicted, indicates cooling loss)
  • Fault: R_CHT > 15°C (significant cooling degradation)
  • Trend: Linear regression slope of R_CHT over 50 flight hours
    Slope > 0.1°C per flight hour → cooling degradation detected

Method B: Cooling Efficiency Factor (CEF)
  • CEF = (CHT_actual - T_coolant_in) / (CHT_predicted - T_coolant_in)
  • Normal: CEF = 0.95 – 1.05
  • Degraded: CEF 1.05 – 1.20 (CHT 5-20% higher than expected)
  • Fault: CEF > 1.20 (>20% cooling loss)

Method C: Thermal Time Constant Analysis
  • τ_thermal = time for CHT to change by 63% of step change
  • Normal: τ_thermal = 30-60 seconds
  • Degraded: τ_thermal > 90 seconds (reduced heat transfer)
  • Test: Rapid throttle change (e.g., 50% to 100% power) and measure response

Method D: Coolant Temperature Differential
  • ΔT_coolant = T_coolant_out - T_coolant_in
  • Normal: ΔT_coolant = 10-20°C
  • Degraded: ΔT_coolant < 10°C (insufficient heat removal)
  • Fault: ΔT_coolant < 5°C (severe cooling loss)

PREDICTION (Before Occurrence):
  • Precursor: Gradual CHT residual increase (slope > 0.05°C per flight hour)
  • Precursor: Coolant pH drop (if chemistry sensor available)
  • Precursor: Coolant flow rate reduction (if flow sensor available)
  • ML Model: Kalman filter tracking η_cool with process noise estimation

RUL IMPACT:
  • Scale buildup: 500-1000 flight hours (flushing restores performance)
  • Pump wear: 200-500 flight hours (pump replacement)
  • Severe blockage: 50-200 flight hours (immediate cleaning required)

10.4 Fault 4: Lubrication Issues
---------------------------------
DEFINITION: Degradation of oil quality, oil pressure, or oil flow resulting in
inadequate lubrication of engine bearings, pistons, and valvetrain.

PHYSICAL CAUSES:
• Oil oxidation (thermal breakdown, additive depletion)
• Oil contamination (fuel dilution, coolant intrusion, particulate ingress)
• Oil pump wear (reduced flow capacity)
• Bearing clearance increase (wear, fatigue)
• Oil filter blockage
• Incorrect oil grade or viscosity

DETECTION METHODS:

Method A: Oil Pressure vs RPM Correlation (Primary)
  • Compute Pearson correlation coefficient r between P_oil and RPM
    over 60-second window
  • Normal: r > 0.95 (strong positive correlation)
  • Degraded: r 0.85 – 0.95 (weakening correlation)
  • Fault: r < 0.85 (significant lubrication issue)
  • Physical basis: Oil pressure is strongly RPM-dependent in healthy engine
    (pump speed ∝ RPM). If correlation breaks, indicates pump wear or
    excessive leakage (bearing clearance increase)

Method B: Oil Pressure Trend Analysis
  • Compute linear regression slope of P_oil vs time (last 10 minutes, constant RPM)
  • Normal: Slope ≈ 0 (stable)
  • Degraded: Slope < -0.5 psi/min
  • Fault: Slope < -2.0 psi/min

Method C: Oil Temperature-Pressure Cross-Analysis
  • At constant RPM, oil pressure should decrease as temperature increases
    (viscosity decreases)
  • Compute: dP_oil/dT_oil at constant RPM
  • Normal: dP/dT = -0.3 to -0.5 psi/°C
  • Degraded: dP/dT > -0.3 psi/°C (less pressure drop than expected, indicates
    viscosity increase from oxidation) or dP/dT < -0.8 psi/°C (excessive
    viscosity loss from fuel dilution)

Method D: Vibration-Bearing Frequency Analysis
  • Bearing defects create characteristic frequencies:
    BPFO (Ball Pass Frequency Outer) = (N_balls/2) × RPM × (1 - d_ball/D_pitch)
    BPFI (Ball Pass Frequency Inner) = (N_balls/2) × RPM × (1 + d_ball/D_pitch)
    BSF (Ball Spin Frequency) = (D_pitch / (2 × d_ball)) × RPM × (1 - (d_ball/D_pitch)²)
  • Envelope analysis: Hilbert transform of vibration signal → FFT of envelope
  • Normal: Peak at BPFO/BPFI < 2× baseline
  • Degraded: Peak 2-5× baseline
  • Fault: Peak > 5× baseline

PREDICTION (Before Occurrence):
  • Precursor: Oil pressure correlation coefficient gradual decline
    (drift > 0.01 per 50 flight hours)
  • Precursor: Oil viscosity increase (from oxidation model)
  • Precursor: Metal particle count increase (if oil analysis sensor)
  • ML Model: LSTM on [P_oil, T_oil, RPM, vibration_BPFO] → lubrication RUL

RUL IMPACT:
  • Oil degradation: 50-100 flight hours (oil change restores performance)
  • Bearing wear: 200-500 flight hours (bearing replacement)
  • Severe contamination: 0-50 flight hours (immediate action)

10.5 Fault 5: Sensor Drift / Failure
-------------------------------------
DEFINITION: Gradual or sudden deviation of sensor output from true physical
value, resulting in incorrect data for monitoring and control.

PHYSICAL CAUSES:
• Thermocouple degradation (oxidation, cold junction drift)
• Pressure transducer zero drift (temperature cycling, aging)
• Accelerometer bias drift (temperature, mechanical shock)
• Electrical interference (EMI, ground loops)
• Connector corrosion (maritime environment, humidity)
• Wiring harness fatigue (vibration, thermal cycling)

DETECTION METHODS:

Method A: Multi-Sensor Voting (Primary)
  • For CHT: 4 cylinder sensors + physics model prediction
    If one sensor deviates from median by > 3σ → flag as drift
    If two sensors deviate → possible actual thermal issue
  • For EGT: Same approach
  • Voting rule: 3-of-5 agreement required for valid reading

Method B: Physics Model Residual Analysis
  • Compute residual: R = sensor_reading - physics_model_prediction
  • Kalman filter estimates sensor bias as state variable
  • Normal: |bias| < 2% of full scale
  • Drift: |bias| 2-5% of full scale
  • Failure: |bias| > 5% of full scale or residual variance > 3× normal

Method C: Cross-Sensor Correlation
  • CHT and EGT should correlate (r > 0.7) during power changes
  • Oil pressure and RPM should correlate (r > 0.95)
  • If correlation breaks suddenly → one of the sensors has failed

Method D: Rate-of-Change Plausibility
  • CHT cannot change > 50°C in 1 second (physical thermal inertia)
  • Oil pressure cannot change > 20 psi in 1 second
  • If rate exceeds physical limit → sensor spike or electrical fault

PREDICTION (Before Occurrence):
  • Precursor: Gradual bias increase (Kalman filter drift estimate)
  • Precursor: Increased noise variance (aging sensor)
  • Precursor: Correlation coefficient gradual decline
  • ML Model: Autoencoder reconstruction error on sensor reading → drift probability

RUL IMPACT:
  • Sensor drift: 100-500 flight hours (recalibration or replacement)
  • Sensor failure: Immediate (replacement required)

10.6 Fault 6: Combustion Instability
-------------------------------------
DEFINITION: Unstable or incomplete combustion resulting in pressure oscillations,
power fluctuations, increased emissions, and potential engine damage.

PHYSICAL CAUSES:
• Lean mixture instability (φ < 0.7)
• Rich mixture misfire (φ > 1.3)
• EGR (exhaust gas recirculation) excessive (if equipped)
• Fuel quality variation (octane rating, volatility)
• Ignition timing too advanced or retarded
• Intake air temperature excessive
• Combustion chamber deposits altering flame propagation

DETECTION METHODS:

Method A: EGT Variance Analysis (Primary)
  • Compute EGT variance over 10-second window
  • Normal: σ_EGT < 10°C
  • Unstable: σ_EGT 10-30°C (cyclic variation)
  • Severe: σ_EGT > 30°C (knock or partial burn)

Method B: Cylinder Pressure Oscillation (If Pressure Sensors)
  • FFT of cylinder pressure trace
  • Detect peaks at non-harmonic frequencies (combustion instability creates
    broadband noise)
  • Normal: Pressure spectrum smooth, peaks at ignition frequency only
  • Unstable: Broadband energy increase in 500-2000 Hz range

Method C: Cantera Residual Analysis
  • Compute predicted EGT from Cantera equilibrium at current φ, P, T
  • Compare with actual EGT
  • Normal: |Residual| < 5%
  • Unstable: Residual > 10% (incomplete combustion, actual EGT lower than
    equilibrium prediction)

Method D: Vibration Kurtosis Analysis
  • Kurtosis of vibration signal (measure of tail heaviness)
  • Normal: Kurtosis ≈ 3 (Gaussian)
  • Knock/Instability: Kurtosis > 6 (impulsive events from pressure waves)

Method E: IMEP Coefficient of Variation (COV)
  • COV_IMEP = σ_IMEP / μ_IMEP × 100%
  • Normal: COV_IMEP < 3%
  • Degraded: COV_IMEP 3-5%
  • Fault: COV_IMEP > 5%

PREDICTION (Before Occurrence):
  • Precursor: Gradual increase in EGT variance (trend > 0.5°C per 10 hours)
  • Precursor: Combustion efficiency decline (BSFC increase)
  • Precursor: Deposit buildup (from oil consumption trend)
  • ML Model: LSTM on [EGT_variance, COV_IMEP, Cantera_residual, knock_index]
    → combustion instability probability

RUL IMPACT:
  • Minor instability: 100-300 flight hours (fuel system adjustment)
  • Deposit-induced: 200-500 flight hours (decarbonization)
  • Severe knock: 0-50 flight hours (immediate power reduction)

10.7 Fault 7: Overheating Trends
---------------------------------
DEFINITION: Gradual or rapid increase in engine temperatures (CHT, EGT, oil
 temperature) beyond safe operating limits, indicating thermal stress and
 potential component damage.

PHYSICAL CAUSES:
• Cooling system degradation (see Fault 3)
• Excessive power setting for ambient conditions
• Lean mixture (excessive EGT)
• Timing too advanced (increased combustion temperature)
• Ambient temperature extreme (hot weather, high altitude)
• Airspeed insufficient (climb, hover, taxi)
• Cowl flap malfunction (if equipped)

DETECTION METHODS:

Method A: CHT Trend Regression (Primary)
  • Fit linear regression to CHT over 5-minute window
  • Slope = dCHT/dt
  • Normal: |Slope| < 0.5°C/min
  • Trending up: Slope 0.5-2.0°C/min
  • Rapid: Slope > 2.0°C/min (thermal runaway risk)

Method B: Thermal Inertia Model
  • Predict CHT at t+Δt based on current power, cooling, and thermal mass
  • If actual CHT > predicted CHT + margin → overheating detected
  • Margin: 5°C (normal), 10°C (degraded cooling)

Method C: ADTK LevelShift Detector
  • Detect sudden step change in CHT baseline
  • Algorithm: CUSUM with adaptive threshold
  • Alert when CHT baseline shifts > 10°C from previous stable state

Method D: Multi-Temperature Correlation
  • CHT, EGT, and oil temperature should correlate during power changes
  • If CHT rises disproportionately to EGT → cooling issue
  • If EGT rises disproportionately to CHT → combustion issue (lean mixture)
  • If all temperatures rise together → excessive power or ambient conditions

PREDICTION (Before Occurrence):
  • Precursor: CHT baseline gradual increase (slope > 0.1°C per flight hour)
  • Precursor: Cooling efficiency factor decline (see Fault 3)
  • Precursor: Ambient temperature forecast (if weather data available)
  • ML Model: Thermal model extrapolation + weather forecast → overheating
    probability for planned mission

RUL IMPACT:
  • Gradual overheating: 50-200 flight hours (cooling system maintenance)
  • Rapid overheating: 0-10 minutes (immediate power reduction required)
  • Thermal damage: Permanent — requires component inspection/replacement

10.8 Fault 8: Abnormal Vibration Patterns
------------------------------------------
DEFINITION: Vibration signatures deviating from normal baseline, indicating
mechanical issues such as imbalance, misalignment, bearing wear, gear damage,
propeller issues, or structural looseness.

PHYSICAL CAUSES:
• Propeller imbalance (ice, damage, erosion)
• Propeller blade track deviation
• Engine mount looseness or deterioration
• Crankshaft imbalance (bearing wear, counterweight issue)
• Reduction gear wear (gear mesh frequency increase)
• Bearing defects (inner race, outer race, ball, cage)
• Accessory drive issues (alternator, fuel pump, vacuum pump)
• Structural resonance (airframe-engine coupling)

DETECTION METHODS:

Method A: FFT Peak Tracking (Primary)
  • Compute FFT of vibration signal (4096-point, Hanning window, 50% overlap)
  • Track amplitude of key frequencies:
    - 1× RPM: Unbalance
    - 2× RPM: Misalignment
    - Gear mesh frequency (F_mesh = N_teeth × RPM / 60)
    - Bearing frequencies (BPFO, BPFI, BSF, FTF)
  • Normal: All peaks < 3× baseline
  • Degraded: One peak 3-5× baseline
  • Fault: One peak > 5× baseline or multiple peaks elevated

Method B: Envelope Analysis (Bearing Fault Detection)
  • Hilbert transform: v_env(t) = |v(t) + j·H{v(t)}|
  • FFT of envelope signal
  • Detect peaks at BPFO, BPFI, BSF
  • Normal: Envelope spectrum flat
  • Degraded: Peaks at bearing frequencies 2-5× baseline
  • Fault: Peaks > 5× baseline with sidebands

Method C: Statistical Features
  • RMS: Overall vibration energy
  • Kurtosis: Impulsive content (bearing faults create impulses)
  • Crest Factor: Peak-to-RMS ratio
  • Skewness: Asymmetry of distribution
  • Normal: Kurtosis ≈ 3, Crest Factor < 6
  • Bearing fault: Kurtosis > 6, Crest Factor > 8

Method D: Order Tracking (Speed-Synchronous Analysis)
  • Resample vibration signal at constant crank angle increments
  • Eliminates speed variation effects
  • Track amplitude vs order (multiples of RPM)
  • More accurate than FFT for varying speed conditions

PREDICTION (Before Occurrence):
  • Precursor: Gradual increase in bearing frequency amplitudes
    (trend > 0.1× per 50 flight hours)
  • Precursor: Kurtosis gradual increase
  • Precursor: Oil pressure correlation decline (indicates bearing wear)
  • ML Model: LSTM on [RMS_trend, kurtosis_trend, BPFO_amplitude,
    oil_pressure_correlation] → bearing RUL

RUL IMPACT:
  • Propeller imbalance: 0-50 flight hours (balancing required)
  • Gear wear: 200-500 flight hours (gear replacement)
  • Bearing defect: 50-200 flight hours (bearing replacement)
  • Mount looseness: 0-100 flight hours (immediate inspection)

================================================================================
11. AI/ML LAYER — ANOMALY DETECTION ARCHITECTURE
================================================================================

11.1 Three-Tier Anomaly Detection System
-----------------------------------------
The AI/ML layer shall implement a hierarchical anomaly detection architecture
that combines the strengths of rule-based, statistical, and deep learning
approaches:

TIER 1: RULE-BASED / THRESHOLD DETECTION (Latency: <5ms)
----------------------------------------------------------
Purpose: Ultra-fast detection of obvious violations. No ML training required.
Domain knowledge encoded as explicit rules.

Implementation: ADTK (Anomaly Detection Toolkit)

Rule Types:
• Threshold Rule: Parameter outside absolute limits
  Example: IF CHT > 135°C THEN ALERT(LEVEL_5, "CHT CRITICAL")
           IF COOLANT > 120°C THEN ALERT(LEVEL_5, "COOLANT CRITICAL")
  [REVISED AT REV 2 to the certified limits of the reference engine. Note that
   coolant temperature, not CHT, is the certified thermal limit here.]

• Rate-of-Change Rule: Parameter changing too fast
  Example: IF dCHT/dt > 5°C/min THEN ALERT(LEVEL_4, "Rapid CHT rise")
           IF knock_retard > 6° THEN ALERT(LEVEL_3, "IGNITION RETARD HIGH")
  [Added at Rev 2: knock-driven ignition retard is an early indicator of both
   combustion quality and cooling degradation — see Part 1 §3.1 PARAMETER 9a.]

• Persistence Rule: Parameter outside normal range for extended duration
  Example: IF CHT > 125°C FOR > 60 seconds THEN ALERT(LEVEL_3, "CHT high")

• Correlation Rule: Cross-parameter relationship violation
  Example: IF P_oil < 40 psi AND RPM > 3000 THEN ALERT(LEVEL_4, "Low oil pressure at high RPM")

• Time-of-Day Rule: Parameter abnormal for current flight phase
  Example: IF CHT < 100°C AND flight_time > 10 minutes THEN ALERT(LEVEL_3, "CHT low after warm-up")

Rule Engine Configuration:
• Total rules: 50-100 rules covering all 8 parameters
• Rule priority: 1-10 (10 = highest, evaluated first)
• Rule suppression: Lower priority rules suppressed when higher priority
  alert active for same parameter
• Rule hysteresis: Alert deactivates only when parameter returns to
  normal range + deadband (e.g., CHT must drop below 120°C to clear a 125°C alert)

TIER 2: STATISTICAL / UNSUPERVISED DETECTION (Latency: 5-50ms)
---------------------------------------------------------------
Purpose: Detect subtle, multivariate anomalies not captured by simple rules.
No labeled fault data required. Learns "normal" behavior from data.

Implementation: PyOD (Python Outlier Detection) + dtaianomaly

Algorithm 1: Isolation Forest (PyOD)
• Type: Tree-based ensemble
• Principle: Anomalies are isolated closer to the root of random trees
• Input: Multivariate feature vector [RPM, CHT, EGT, Oil_P, Oil_T, Fuel_Flow, Vib_RMS]
• Parameters: n_estimators=100, contamination=0.05, max_samples=256
• Output: Anomaly score (0 = normal, 1 = anomaly)
• Use case: Sensor drift, subtle operating point anomalies

Algorithm 2: CBLOF (Clustering-Based Local Outlier Factor)
• Type: Clustering-based
• Principle: Anomalies are far from cluster centers or in small clusters
• Input: Same multivariate feature vector
• Parameters: n_clusters=8, alpha=0.9, beta=5
• Output: Local outlier factor
• Use case: Operating mode transitions, off-design conditions

Algorithm 3: Matrix Profile (dtaianomaly)
• Type: Time-series subsequence analysis
• Principle: Anomalous subsequences have high distance to their nearest neighbor
• Input: Univariate time series (e.g., CHT over 1000 samples)
• Parameters: window_size=100, exclusion_zone=50
• Output: Matrix profile (distance to nearest neighbor for each subsequence)
• Use case: Transient anomalies, pattern changes

Algorithm 4: LSTM Autoencoder (PyOD / Custom)
• Type: Deep learning reconstruction
• Principle: Reconstruct normal behavior; high reconstruction error = anomaly
• Architecture: Encoder(LSTM(32)) → Bottleneck(16) → Decoder(LSTM(32))
• Input: Sequence of 30 time steps × 7 features
• Output: Reconstruction error (MSE between input and output)
• Threshold: 95th percentile of training set reconstruction errors
• Use case: Complex multivariate patterns, combustion instability

Ensemble Strategy:
• Each algorithm produces anomaly score s_i ∈ [0, 1]
• Final score: s_ensemble = weighted_average(s_i, w_i)
  Where w_i = algorithm weight based on validation performance
• Decision: IF s_ensemble > 0.7 THEN ALERT(LEVEL_3)
  IF s_ensemble > 0.9 THEN ALERT(LEVEL_4)

TIER 3: DEEP LEARNING / SUPERVISED DETECTION (Latency: 10-100ms)
-----------------------------------------------------------------
Purpose: Highest accuracy for known fault patterns. Requires labeled training
data but provides precise fault classification.

Implementation: TensorFlow/Keras

Architecture: Multi-Task Neural Network
• Shared layers: LSTM(64) → Dropout(0.2) → LSTM(32) → Dense(32)
• Task 1 (Anomaly Detection): Dense(1, sigmoid) → binary anomaly flag
• Task 2 (Fault Classification): Dense(8, softmax) → 8 fault probabilities
• Task 3 (Severity Estimation): Dense(1, linear) → severity score 0-1

Input: Sequence of 30 time steps × 7 normalized features
• Feature normalization: z-score (mean=0, std=1) per feature
• Sequence creation: Sliding window with stride=1
• Data augmentation: Add Gaussian noise (σ=0.01) to training sequences

Training Data:
• Source 1: NASA C-MAPSS (FD001-FD004) — 100+ turbofan engines, run-to-failure
  Mapped to piston engine: Fan speed → RPM, HPC temp → CHT/EGT, etc.
• Source 2: Self-generated synthetic data from physics model with injected faults
  100 "virtual engines" with random initial health, run to failure
  Faults injected at random times with realistic progression
• Source 3: IDF-DS19 dataset — 240 real UAV flights, 160 telemetry parameters
  Provides realistic flight patterns and sensor noise characteristics

Training Strategy:
• Pre-training: Train on C-MAPSS (large dataset, general prognostics knowledge)
• Fine-tuning: Train on synthetic Rotax 914 data (specific engine knowledge)
• Validation: 80/10/10 split (train/validation/test)
• Early stopping: Patience=10 epochs, monitor validation loss
• Class balancing: Use class weights or SMOTE for imbalanced fault classes

Performance Targets:
• Anomaly Detection: Precision > 0.85, Recall > 0.90, F1 > 0.87
• Fault Classification: Accuracy > 0.85, Macro-F1 > 0.82
• False Positive Rate: < 5% (critical for operator trust)

11.2 Anomaly Score Fusion
--------------------------
The system shall fuse anomaly scores from all three tiers:

Fusion Formula:
  S_final = 0.3 × S_rule + 0.3 × S_statistical + 0.4 × S_deep

Where:
  S_rule = max alert level from rule engine (normalized 0-1)
  S_statistical = ensemble score from PyOD/dtaianomaly
  S_deep = anomaly probability from neural network

Alert Trigger Logic:
  IF S_final > 0.6 AND S_rule > 0.5 → LEVEL_3 (Caution)
  IF S_final > 0.8 AND (S_statistical > 0.7 OR S_deep > 0.8) → LEVEL_4 (Warning)
  IF S_final > 0.95 AND S_rule = 1.0 → LEVEL_5 (Emergency)

This fusion ensures:
• Rule-based catches obvious violations immediately
• Statistical detects subtle multivariate patterns
• Deep learning provides precise fault classification
• Fusion reduces false positives while maintaining high recall

================================================================================
12. AI/ML LAYER — REMAINING USEFUL LIFE (RUL) ESTIMATION
================================================================================

12.1 RUL Definition
--------------------
Remaining Useful Life is defined as the estimated number of flight hours (or
cycles) remaining before the engine health index falls below the maintenance
threshold (CHI < 0.60) or a critical failure occurs.

RUL can be expressed as:
• Flight hours remaining
• Engine cycles remaining (one cycle = one start-stop or one TBO interval)
• Mission count remaining (based on average mission duration)

12.2 RUL Estimation Architecture
---------------------------------
The system shall implement two complementary RUL estimation approaches:

APPROACH 1: Data-Driven RUL (LSTM/GRU Network)
• Input: Multivariate time series of sensor readings
• Output: Scalar RUL prediction
• Advantage: Captures complex degradation patterns without explicit physics
• Disadvantage: Requires large training dataset

APPROACH 2: Physics-Based RUL (Degradation Model Extrapolation)
• Input: Estimated degradation factors from physics model
• Output: RUL based on degradation rate extrapolation
• Advantage: Interpretable, works with limited data
• Disadvantage: Requires accurate degradation model

FUSION: Weighted combination of both approaches based on confidence

12.3 LSTM/GRU RUL Model Specification
--------------------------------------
Architecture:
```
Input Layer: (batch, sequence_length=30, n_features=7)
  ↓
LSTM Layer 1: 64 units, return_sequences=True
  ↓
Dropout: 0.2
  ↓
LSTM Layer 2: 32 units, return_sequences=False
  ↓
Dropout: 0.2
  ↓
Dense Layer 1: 16 units, ReLU activation
  ↓
Dense Output: 1 unit, linear activation (RUL in flight hours)
```

Input Features (7 normalized sensors):
1. RPM_norm = (RPM - 3000) / 2500
2. CHT_norm = (CHT_avg - 175) / 55
3. EGT_norm = (EGT_avg - 620) / 200
4. Oil_P_norm = (Oil_P - 55) / 45
5. Oil_T_norm = (Oil_T - 95) / 55
6. Fuel_Flow_norm = (Fuel_Flow - 10) / 10
7. Vib_norm = (Vib_RMS - 2.5) / 7.5

Target Function: Piecewise Linear RUL
  • For healthy engine (t < t_onset): RUL = RUL_max (constant)
  • For degrading engine (t ≥ t_onset): RUL = RUL_max - (t - t_onset) × degradation_rate
  • t_onset = time when health index first drops below 0.90
  • RUL_max = Time Between Overhaul (TBO) = 2,000 hours for Rotax 914

Loss Function: Custom RUL Loss
  • L = α × MSE(RUL_pred, RUL_true) + β × Score(RUL_pred, RUL_true)
  • Where Score = Σ exp((RUL_true - RUL_pred) / 13) - 1 for RUL_pred < RUL_true
    (penalizes late predictions more than early predictions)
  • α = 0.7, β = 0.3

Training Configuration:
• Optimizer: Adam (learning_rate=0.001, β1=0.9, β2=0.999)
• Batch size: 32
• Epochs: 100 (with early stopping, patience=15)
• Validation split: 10%
• Callbacks: ModelCheckpoint (save best), ReduceLROnPlateau (patience=5),
  EarlyStopping (patience=15, monitor=val_loss)

Performance Targets:
• RMSE < 25 flight hours on test set
• NASA Score < 500 (penalizes late predictions heavily)
• MAPE < 15%
• R² > 0.85

12.4 Physics-Based RUL Model
-----------------------------
The physics-based RUL uses degradation factor extrapolation:

For each degradation factor d_i(t):
  d_i(t) = d_i(0) - k_i × t
  Where k_i = degradation rate (estimated from trend)

RUL_i = (d_i(threshold) - d_i(current)) / k_i

Where:
  d_i(threshold) = degradation factor value at which maintenance is required
  d_i(current) = current degradation factor value
  k_i = estimated degradation rate from Kalman filter

Overall RUL = min(RUL_thermal, RUL_mechanical, RUL_electrical, RUL_combustion)

Confidence Interval:
  RUL_lower = RUL - 1.96 × σ_RUL
  RUL_upper = RUL + 1.96 × σ_RUL
  Where σ_RUL = uncertainty from Kalman filter covariance matrix

12.5 RUL Fusion & Confidence
-----------------------------
Final RUL = w_data × RUL_data-driven + w_physics × RUL_physics

Where:
  w_data = confidence_data / (confidence_data + confidence_physics)
  w_physics = confidence_physics / (confidence_data + confidence_physics)
  confidence_data = 1 / (1 + val_loss)  (inverse of validation loss)
  confidence_physics = 1 / (1 + model_residual_variance)

This ensures:
• When data-driven model is well-trained (low val_loss), it dominates
• When physics model has low residual variance, it dominates
• When both are uncertain, the prediction is conservative (lower RUL)

================================================================================
13. AI/ML LAYER — TREND ANALYSIS & PREDICTIVE MAINTENANCE
================================================================================

13.1 Trend Analysis Methods
----------------------------
The system shall implement the following trend analysis techniques:

METHOD 1: Time-Series Decomposition
  • Decompose each sensor signal into:
    - Trend component (long-term direction)
    - Seasonal component (mission-cycle patterns)
    - Residual component (noise + anomalies)
  • Algorithm: STL (Seasonal and Trend decomposition using Loess)
  • Parameters: seasonal period = average mission duration (e.g., 18 hours)
  • Use case: Separate mission-related variation from actual degradation

METHOD 2: Exponential Smoothing
  • Holt-Winters method with trend and seasonality
  • Forecast next 10-50 flight hours for each parameter
  • Confidence intervals: 80% and 95%
  • Use case: Predict when parameter will cross threshold

METHOD 3: Change Point Detection
  • Detect abrupt changes in mean, variance, or trend
  • Algorithms: PELT (Pruned Exact Linear Time), Binary Segmentation
  • Use case: Identify when degradation accelerated (e.g., after hard landing)

METHOD 4: Spectral Trend Analysis
  • Track FFT peak frequencies and amplitudes over time
  • Detect gradual shifts in dominant frequencies
  • Use case: Bearing wear progression, gear wear progression

13.2 Predictive Maintenance Recommendation Engine
--------------------------------------------------
The system shall generate maintenance recommendations based on:

INPUTS:
• Current health index (CHI)
• RUL estimate (hours, cycles, missions)
• Degradation factor trends
• Fault probabilities
• Operating history (thermal cycles, max stress events)
• Maintenance history (last service, parts replaced, TBO status)
• Mission schedule (upcoming missions, criticality)

RECOMMENDATION LOGIC:

Rule 1: IF CHI < 0.60 THEN
  Recommendation: "GROUND AIRCRAFT IMMEDIATELY. Engine unsafe for flight.
  Schedule emergency inspection."
  Priority: CRITICAL
  Timeframe: Before next flight

Rule 2: IF CHI < 0.70 AND RUL < 25 flight hours THEN
  Recommendation: "Schedule maintenance within 10 flight hours.
  {specific subsystem} degradation detected."
  Priority: HIGH
  Timeframe: Within 10 flight hours

Rule 3: IF CHI < 0.80 AND any degradation factor < 0.75 THEN
  Recommendation: "Monitor closely. {specific component} showing degradation.
  Plan maintenance within 50 flight hours."
  Priority: MEDIUM
  Timeframe: Within 50 flight hours

Rule 4: IF CHI > 0.80 AND trend indicates gradual degradation THEN
  Recommendation: "Normal operation. Continue monitoring.
  Next scheduled inspection at {TBO_remaining} hours."
  Priority: LOW
  Timeframe: At next scheduled maintenance

Rule 5: IF mission profile requires high power AND predicted CHT > 125°C THEN
  Recommendation: "MISSION ADVISORY: Planned mission profile may exceed thermal
  limits. Consider reduced power setting or alternate route."
  Priority: MISSION_PLANNING
  Timeframe: Before mission

Rule 6: IF RUL < mission_duration × 1.5 THEN
  Recommendation: "MISSION ABORT RISK: Estimated RUL ({RUL} hours) is less than
  1.5× planned mission duration ({mission_duration} hours). Recommend inspection
  before mission or reduce mission scope."
  Priority: MISSION_CRITICAL
  Timeframe: Before mission

RECOMMENDATION FORMAT:
{
  "recommendation_id": "REC-2026-08-22-001",
  "timestamp": "2026-08-22T14:04:00Z",
  "priority": "HIGH",
  "category": "THERMAL",
  "message": "Cooling efficiency degraded 18%. Schedule inspection within 10 flight hours.",
  "affected_subsystem": "Cooling System",
  "affected_components": ["Water pump", "Cooling jackets"],
  "recommended_actions": [
    "Inspect coolant level and condition",
    "Check water pump flow rate",
    "Flush cooling system if scale detected"
  ],
  "estimated_downtime": "4 hours",
  "estimated_cost": "₹15,000",
  "shap_explanation": {
    "cht_trend": 0.42,
    "cooling_efficiency": 0.28,
    "oat_compensation": 0.15,
    "mission_thermal_load": 0.10,
    "other": 0.05
  },
  "confidence": 0.87
}

================================================================================
14. PHYSICS-INFORMED NEURAL NETWORK (PINN) SPECIFICATION
================================================================================

14.1 PINN Architecture
-----------------------
The system shall implement a Physics-Informed Neural Network to combine the
strengths of physics-based modeling (interpretability, data efficiency) with
deep learning (pattern recognition, nonlinear mapping).

Architecture: Multi-Output Neural Network with Physics Constraints

Input: [RPM, throttle, altitude, OAT, airspeed, time]
  ↓
Shared Encoder: Dense(64, ReLU) → Dense(32, ReLU) → Dense(16, ReLU)
  ↓ (branches to multiple outputs)

Branch 1 (CHT Prediction):
  Dense(8, ReLU) → Dense(1, linear) → CHT_pred

Branch 2 (EGT Prediction):
  Dense(8, ReLU) → Dense(1, linear) → EGT_pred

Branch 3 (Torque Prediction):
  Dense(8, ReLU) → Dense(1, linear) → Torque_pred

Branch 4 (Fuel Flow Prediction):
  Dense(8, ReLU) → Dense(1, linear) → FuelFlow_pred

14.2 Physics Loss Functions
----------------------------
The neural network training loss shall include physics constraint terms:

Total Loss = L_data + λ_physics × L_physics + λ_boundary × L_boundary

Where:
  L_data = MSE(y_pred, y_true)  (standard supervised loss)
  L_physics = sum of physics residual terms
  L_boundary = boundary condition penalties
  λ_physics = 0.1 (weight for physics constraints)
  λ_boundary = 1.0 (weight for boundary conditions)

PHYSICS CONSTRAINTS:

Constraint 1: Energy Balance
  L_energy = |Q_in - Q_out - W_shaft - dE/dt|
  Where:
    Q_in = fuel_flow × LHV
    Q_out = Q_coolant + Q_exhaust + Q_radiation
    W_shaft = torque × angular_velocity
    dE/dt = rate of change of internal energy (small, quasi-steady)

Constraint 2: Heat Transfer Consistency
  L_heat = |Q_coolant - h_cool × A_cool × (CHT - T_coolant)|
  Ensures predicted CHT is consistent with heat transfer model

Constraint 3: Mass Balance
  L_mass = |ṁ_air_in - ṁ_air_burned - ṁ_exhaust|
  Ensures air mass flow consistency

Constraint 4: Thermodynamic Bounds
  L_bounds = max(0, CHT_pred - 350)² + max(0, -CHT_pred)²
             + max(0, EGT_pred - 1000)² + max(0, -EGT_pred)²
  Ensures predictions within physically possible ranges

Constraint 5: Degradation Monotonicity
  L_monotonic = max(0, -(dη/dt))
  Ensures degradation factors only decrease (or stay constant)

14.3 PINN Training
-------------------
• Framework: DeepXDE (supports TensorFlow, PyTorch, JAX backends)
• Alternative: SciANN (Keras-based, more user-friendly)
• Training data: Physics model simulations + C-MAPSS data
• Physics loss computed via automatic differentiation (AD)
• Training: 500-1000 epochs, learning rate 0.001, Adam optimizer

14.4 PINN Advantages for This Application
------------------------------------------
• Data Efficiency: Requires 50-70% less training data than pure data-driven
  models because physics constraints provide regularization
• Interpretability: Network outputs must satisfy physical laws, increasing
  trust for defense applications
• Generalization: Better performance on unseen operating conditions because
  physics constraints prevent unphysical extrapolation
• Real-Time: Once trained, inference is as fast as standard neural network

================================================================================
15. EXPLAINABLE AI (XAI) FOR FAULT DIAGNOSIS
================================================================================

15.1 XAI Requirements
----------------------
The system shall provide explainable AI capabilities to:
• Enable operator trust in automated predictions
• Support maintenance decision-making with evidence
• Meet defense audit requirements (traceability of all decisions)
• Facilitate regulatory approval for autonomous maintenance advisories

15.2 SHAP (SHapley Additive exPlanations) Implementation
---------------------------------------------------------
SHAP provides global and local feature importance explanations.

GLOBAL EXPLANATIONS:
• Purpose: Which sensors contribute most to RUL prediction across all engines?
• Method: SHAP summary plot (bar chart of mean absolute SHAP values)
• Output: Ranked list of features by importance
• Example: "EGT spread (28%), Oil pressure correlation (22%), CHT trend (18%),
  Vibration RMS (15%), Fuel flow variance (10%), RPM stability (5%),
  Battery voltage (2%)"

LOCAL EXPLANATIONS:
• Purpose: Why was THIS specific alert generated for THIS engine at THIS time?
• Method: SHAP force plot (waterfall chart showing feature contributions)
• Output: Feature contributions pushing prediction toward alert vs normal
• Example: "This cooling degradation alert was driven by:
  + CHT residual +12°C (strong push toward alert)
  + Cooling efficiency factor 0.78 (moderate push)
  - OAT normal 15°C (slight push toward normal)
  + Mission thermal load high (moderate push)
  = Final prediction: 85% probability of cooling degradation"

15.3 LIME (Local Interpretable Model-agnostic Explanations)
------------------------------------------------------------
LIME provides local surrogate model explanations.

Method:
• For a specific prediction, generate perturbed samples around the input
• Train a simple interpretable model (e.g., linear regression, decision tree)
  on the perturbed samples weighted by proximity
• Use the simple model to explain the complex model's prediction

Output:
• Top 5 features contributing to the prediction
• Feature direction (increases/decreases prediction)
• Local fidelity score (how well surrogate approximates complex model)

15.4 Natural Language Explanation Generator
--------------------------------------------
The system shall convert SHAP/LIME outputs into natural language maintenance
advisories:

Template:
"{Fault Type} detected with {Confidence}% confidence.
Primary cause: {Top Feature 1} ({Contribution 1}%).
Contributing factors: {Top Feature 2} ({Contribution 2}%),
{Top Feature 3} ({Contribution 3}%).
Recommended action: {Action}.
Estimated time to critical: {RUL} flight hours."

Example:
"Cooling degradation detected with 87% confidence.
Primary cause: CHT residual +12°C above predicted (42%).
Contributing factors: Cooling efficiency factor 0.78 (28%),
Mission thermal load high (18%).
Recommended action: Inspect coolant system and water pump within 10 flight hours.
Estimated time to critical: 47 flight hours."

15.5 XAI Dashboard Integration
-------------------------------
The visualization dashboard shall include:
• SHAP summary plot (global feature importance)
• SHAP force plot for selected alert (local explanation)
• Feature contribution bar chart for current prediction
• Natural language explanation panel
• "Why this alert?" button on every alert card

================================================================================
16. AUTONOMOUS MAINTENANCE ADVISORY SYSTEM
================================================================================

16.1 System Objective
----------------------
The Autonomous Maintenance Advisory System (AMAS) shall automatically generate,
prioritize, and distribute maintenance recommendations without human intervention,
reducing cognitive load on operators and ensuring consistent decision-making.

16.2 Advisory Generation Pipeline
----------------------------------
┌─────────────────────────────────────────────────────────────────────────────┐
│  INPUT: Health Index + RUL + Fault Probabilities + Degradation Trends     │
│       ↓                                                                   │
│  RULE ENGINE: Map health state to maintenance action library              │
│       ↓                                                                   │
│  PRIORITIZATION: Rank by severity, mission criticality, resource avail.  │
│       ↓                                                                   │
│  XAI ENRICHMENT: Add SHAP explanations to each recommendation            │
│       ↓                                                                   │
│  FORMATTING: Generate natural language message + structured JSON         │
│       ↓                                                                   │
│  DISTRIBUTION: Push to dashboard, email, SMS, maintenance system         │
└─────────────────────────────────────────────────────────────────────────────┘

16.3 Maintenance Action Library
--------------------------------
The system shall maintain a library of maintenance actions:

ACTION 1: Oil Change
• Trigger: Oil quality index < 0.75 OR oil viscosity increase > 25%
• Procedure: Drain oil, replace filter, refill with specified grade
• Estimated downtime: 1 hour
• Estimated cost: ₹3,000
• Parts required: Oil (5L), filter, crush washer

ACTION 2: Cooling System Flush
• Trigger: Cooling efficiency < 0.70 OR CHT residual > 15°C
• Procedure: Drain coolant, flush with cleaner, refill with specified coolant
• Estimated downtime: 2 hours
• Estimated cost: ₹5,000
• Parts required: Coolant (8L), flush chemical

ACTION 3: Injector Cleaning/Replacement
• Trigger: EGT spread > 30°C OR fuel flow CV > 10%
• Procedure: Remove injectors, ultrasonic clean or replace
• Estimated downtime: 3 hours
• Estimated cost: ₹12,000 (clean) / ₹25,000 (replace)
• Parts required: Injector seals, O-rings

ACTION 4: Spark Plug Replacement
• Trigger: Misfire rate > 5% OR ignition energy drop > 15%
• Procedure: Remove old plugs, inspect, gap and install new plugs
• Estimated downtime: 0.5 hours
• Estimated cost: ₹2,000
• Parts required: Spark plugs (4)

ACTION 5: Bearing Inspection
• Trigger: Vibration BPFO/BPFI > 5× baseline OR oil pressure correlation < 0.80
• Procedure: Borescope inspection, oil analysis, vibration analysis
• Estimated downtime: 4 hours
• Estimated cost: ₹20,000
• Parts required: Bearing set (if replacement needed)

ACTION 6: Turbocharger Inspection
• Trigger: Boost pressure drop > 20% OR EGT increase > 50°C (turbine side)
• Procedure: Visual inspection, shaft play measurement, compressor map test
• Estimated downtime: 6 hours
• Estimated cost: ₹35,000
• Parts required: Turbocharger rebuild kit or replacement

ACTION 7: Complete Engine Overhaul
• Trigger: CHI < 0.50 OR RUL < 10 flight hours OR multiple critical faults
• Procedure: Full disassembly, inspection, replacement of worn parts,
  reassembly, test run
• Estimated downtime: 2-3 weeks
• Estimated cost: ₹5,00,000
• Parts required: Full overhaul kit, gaskets, bearings, rings, valves

16.4 Autonomous Scheduling
---------------------------
The system shall automatically schedule maintenance based on:
• RUL estimate (schedule before RUL reaches critical)
• Mission schedule (avoid scheduling during critical missions)
• Resource availability (parts, personnel, hangar space)
• Fleet coordination (stagger maintenance to maintain operational readiness)

Scheduling Algorithm:
  1. Sort all engines by RUL (ascending)
  2. For each engine with RUL < threshold:
     a. Identify required maintenance actions
     b. Estimate downtime
     c. Check mission schedule for conflicts
     d. Find earliest available slot
     e. Reserve parts and personnel
  3. Generate weekly maintenance schedule
  4. Alert maintenance chief of upcoming tasks

16.5 Spare Parts Forecasting
-----------------------------
The system shall forecast spare parts demand based on:
• Degradation trends across fleet
• Predicted maintenance actions
• Lead times for parts procurement
• Safety stock requirements

Forecasting Method:
• Exponential smoothing on parts consumption history
• Adjusted by predicted maintenance schedule
• Seasonal adjustment for high-tempo operations

Output:
• 30-day parts requirement forecast
• Reorder alerts when stock falls below safety level
• Cost optimization: Bulk ordering for common parts

================================================================================
END OF PRD PART 2
================================================================================
