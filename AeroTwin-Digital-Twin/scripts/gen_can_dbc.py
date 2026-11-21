"""Generate configs/can/engine.dbc as a CANaerospace-conformant database.

WHY THIS IS GENERATED RATHER THAN HAND-WRITTEN
----------------------------------------------
The Rotax 915 i publishes engine data on a **Display CAN bus that is based on
the CANaerospace protocol** (Installation Manual IM-915 i A/C24 Ed.0 Rev.5,
chapter 77-00-00). CANaerospace fixes both the message layout and the CAN
identifier for every standard parameter, so the correct database is *derived*
from the standard, not invented. Generating it keeps the identifier arithmetic
honest and documents where every number comes from.

Run:  python scripts/gen_can_dbc.py

SOURCES
-------
[IM]    BRP-Rotax Installation Manual IM-915 i A / C24, Ed. 0 Rev. 5,
        01 February 2024, chapter 77-00-00 "Interface overview".
        - HIC Connector A: Display CAN Lane A + Maintenance CAN Lane A
        - HIC Connector B: Display CAN Lane B + Maintenance CAN Lane B
        - "The Display CAN is based on the CANAerospace protocol."
        - Warning lamp per lane: 12 V nominal, 120 mA nominal
[CANAS] CANaerospace "Interface specification for airborne CAN applications",
        Revision 1.6, 13 March 2001, Stock Flight Systems.
        - Section 2.1 message types / identifier ranges
        - Section 2.2 data types
        - Section 3.3 Normal Operation Data message format
        - Standard identifier assignment list (engine parameters)

HONESTY NOTE -- READ BEFORE PRESENTING THIS
-------------------------------------------
The IM states: "For detailed interface description contact an authorized
ROTAX Distributor or its independent Service Center." The exact Rotax message
assignment is therefore NOT public and is NOT reproduced here. What this file
contains is a database built from the OPEN CANaerospace standard identifier
assignments for the parameters the engine is known to publish. It is
protocol-correct and drop-in replaceable with the real Rotax definition, but it
must never be described as "the Rotax CAN database".

CANAEROSPACE MESSAGE LAYOUT (all messages, 8 bytes)
---------------------------------------------------
    byte 0   Node-ID        transmitting station (EED / NOD)
    byte 1   Data Type      2 = FLOAT (IEEE-754 single precision)
    byte 2   Service Code   for NOD: continuously reflects the status of the
                            data or the transmitting unit, "to support data
                            integrity monitoring within receiving units"
    byte 3   Message Code   message numbering: detects missing messages and
                            compares the age of messages from redundant
                            sources
    bytes 4-7  Data         the parameter value

Bytes 2 and 3 are why this protocol matters to us: they give the ingest layer
per-frame validity and staleness information *from the bus itself*, which is
exactly what PRD Part 4 section 7 requires the HMI to annunciate.

IDENTIFIER RANGES [CANAS section 2.1]
-------------------------------------
       0 -  127   Emergency Event Data (EED)
     128 -  199   High Priority Node Service Data (NSH)
     200 -  299   High Priority User-Defined Data (UDH)
     300 - 1799   Normal Operation Data (NOD)      <- standard parameters
    1800 - 1899   Low Priority User-Defined Data (UDL)  <- our HUMS extensions
    1900 - 1999   Debug Service Data (DSD)
    2000 - 2031   Low Priority Node Service Data (NSL)

ENGINE PARAMETER IDENTIFIERS [CANAS standard assignment list]
-------------------------------------------------------------
Engine #n occupies base+(n-1); this engine is Engine #1. ECS channel B is
offset +64 from channel A, which maps exactly onto the Rotax Lane A / Lane B
FADEC channels.

    channel A   channel B   parameter                        unit
    ---------   ---------   -------------------------------  ----
    500         564         Engine N1 (crankshaft RPM)       1/min
    504         568         Engine N2 (propeller RPM)        1/min
    508         572         Engine torque                    Norm
    520         584         Exhaust gas temperature          K
    524         588         Fuel flow rate                   l/h
    528         592         Manifold pressure                hPa
    532         596         Oil pressure                     hPa
    536         600         Oil temperature                  K
    540         604         Cylinder head temperature        K
    544         608         Oil quantity                     l
    548         612         Coolant temperature              K
    552         616         Power rating                     Norm
    684                     Fuel system pressure             hPa
    920                     DC system voltage                V
    930                     DC system current                A

Note the units: CANaerospace uses KELVIN for temperature and hPa for pressure.
The ingest layer converts to engineering units; the bus definition does not.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "configs" / "can" / "engine.dbc"

# CANaerospace data type codes [CANAS section 2.2]
DT_FLOAT = 2

CH_B_OFFSET = 64  # ECS channel A -> channel B

# CANaerospace Node-ID of each station [CANAS section 3.3: byte 0 of a Normal
# Operation Data message identifies the transmitting station]. Written into the
# DBC as a node attribute, so the bus definition itself says which Node-ID each
# message may carry and a receiver can refuse a frame from anywhere else.
# 0 = the station sends no header messages.
NODE_IDS = {"ECU_A": 11, "ECU_B": 12, "HUMS": 20, "VMC": 30, "EDGE": 0}

# Channel-A messages whose transmitter is not FADEC lane A. Fuel flow and CHT
# come from instrumentation this project adds (HUMS node comment below). Oil
# pressure and oil temperature are Lane B sensors [IM Rev.5 failure matrix,
# engines/rotax_915is.yaml] and travel on their ECS channel B identifiers.
SENDER_OVERRIDE = {"ECSA_FUEL_FLOW": "HUMS", "ECSA_CHT": "HUMS"}

# (base_id_channel_A, name, unit, min, max, comment)
STANDARD_PARAMS = [
    (500, "ENGINE_SPEED", "1/min", 0, 6500,
     "Engine N1. For a piston engine this is crankshaft RPM. Idle minimum "
     "1800 rpm, max continuous 5500 rpm, take-off 5800 rpm for 5 minutes "
     "(EASA TCDS E.121). Sampled at 100 Hz for per-power-stroke misfire "
     "detection (PRD Part 2 section 10.1 Method A)."),
    (504, "PROPELLER_SPEED", "1/min", 0, 3000,
     "Engine N2. Propeller shaft speed = crankshaft / 2.5454 reduction ratio "
     "(EASA TCDS E.121)."),
    (508, "ENGINE_TORQUE", "Norm", 0, 2,
     "Normalised engine torque."),
    (520, "EGT", "K", 0, 1500,
     "Exhaust gas temperature. Certified limit 950 degC; certified EGT-split "
     "limit 200 degC above 3 L/hr fuel flow and 500 degC below it "
     "(OM-915 i Ed.0 Rev.4 section 2.1). CANaerospace assigns ONE identifier "
     "per engine, so this frame carries the highest of the four probes; the "
     "per-cylinder detail travels in the user-defined range."),
    (524, "FUEL_FLOW", "l/h", -5, 75,
     "Fuel flow rate."),
    (528, "MANIFOLD_PRESSURE", "hPa", 0, 2000,
     "Manifold absolute pressure. Range 60-1730 hPa. The boost controller "
     "targets 1450 hPa at 5500 rpm and 1520 hPa at 5800 rpm; 1730 hPa is a "
     "never-exceed authority limit, not a setpoint (OM Ed.0 Rev.4 section 2.1)."),
    (532, "OIL_PRESSURE", "hPa", -500, 13000,
     "Oil pressure. Normal 2.0-5.0 bar above 3500 rpm, minimum 0.8 bar below "
     "3500 rpm, 7.0 bar tolerated briefly at cold start."),
    (536, "OIL_TEMPERATURE", "K", 200, 500,
     "Oil temperature. Normal operation 50-130 degC, 90-110 degC recommended."),
    (540, "CHT", "K", 200, 500,
     "Cylinder head temperature. HUMS-ADDED INSTRUMENTATION: the 915 i is "
     "liquid-cooled on the heads and fits a single coolant temperature sensor "
     "on cylinder head 4 (OM section 7.2), not per-cylinder CHT. This frame "
     "carries the highest of the four added probes."),
    (548, "COOLANT_TEMPERATURE", "K", 200, 500,
     "Coolant temperature -- the CERTIFIED thermal limit for this engine, "
     "120 degC in normal operation (EASA TCDS E.121, OM section 2.1). Measured "
     "by the CTS on cylinder head 4."),
]

# Parameters that exist on channel A only (no redundant lane).
SINGLE_CHANNEL_PARAMS = [
    (684, "FUEL_SYSTEM_PRESSURE", "hPa", 0, 8000,
     "Fuel rail pressure. Normal 2.9-3.2 bar; 2.5-3.5 bar tolerated for at "
     "most 3 s after a power-setting change (OM Ed.0 Rev.4 section 2.1)."),
    (920, "DC_VOLTAGE", "V", -5, 45,
     "DC system voltage. The iSc C24 variant carries a 28 V system interface "
     "(EASA TCDS E.121 section 2)."),
    # Range starts below zero: a current sensor reading near zero at idle will
    # sit slightly negative once noise is applied, and the bus definition must
    # be able to carry what the instrument actually produces.
    (930, "DC_CURRENT", "A", -5, 60,
     "DC system current. The engine has two internal generators: Generator 1 "
     "supplies the Engine Management System, Generator 2 supplies the airframe "
     "(OM section 4.1.1)."),
    # Battery current, from a shunt on the pack. Signed: positive while the
    # battery is DISCHARGING, negative while the alternator recharges it.
    #
    # Added because battery state of health is not inferable without it. Pack
    # internal resistance is recovered from the slope of terminal voltage
    # against BATTERY current, and the bus carried only ALTERNATOR current --
    # which during a discharge event is pinned at what the generator can
    # supply and says nothing about the pack. The estimator correctly refused
    # to report a state of health for the whole life of the engine. A battery
    # shunt is standard on any aircraft with battery monitoring, and no amount
    # of estimation substitutes for it.
    (940, "BATTERY_CURRENT", "A", -60, 60,
     "Battery current from a pack shunt. Positive discharging, negative on "
     "charge. Required for internal-resistance estimation (PRD Part 2 "
     "section 9.2 Parameter 8)."),
]

# Low Priority User-Defined Data (1800-1899) -- our HUMS extensions.
# CANaerospace explicitly reserves this range for exactly this purpose, so
# adding health-monitoring channels here is standards-conformant rather than a
# violation of the protocol.
UDL_PARAMS = [
    (1800, "CHT_PER_CYLINDER", ["CHT_CYL1", "CHT_CYL2", "CHT_CYL3", "CHT_CYL4"],
     "K", 200, 500, 4,
     "Per-cylinder cylinder head temperature. HUMS-ADDED. Four 16-bit values "
     "replace the CANaerospace header+data layout because this is a "
     "user-defined message: the range 1800-1899 has an entirely user-defined "
     "format by CANAS section 2.1."),
    (1801, "EGT_PER_CYLINDER", ["EGT_CYL1", "EGT_CYL2", "EGT_CYL3", "EGT_CYL4"],
     "K", 200, 1500, 4,
     "Per-cylinder exhaust gas temperature. Needed for the EGT-split limit and "
     "for injector-imbalance detection (PRD Part 2 section 10.2 Method B)."),
    (1802, "VIBRATION", ["VIB_RMS_X", "VIB_RMS_Y", "VIB_RMS_Z", "VIB_KURTOSIS"],
     "m/s2", 0, 60, 4,
     "Tri-axial vibration RMS plus kurtosis. HUMS-ADDED. The raw 10 kHz "
     "waveform used for FFT, envelope and order analysis travels on the "
     "high-speed path, not on this frame."),
    # Range 0-550 deg, NOT the -20..60 deg of ignition timing. Port injection
    # is a closed-valve event during the exhaust/intake phase of the 720 deg
    # four-stroke cycle, so the start angle referenced to the firing TDC is
    # around 370 deg. Using the ignition band here silently made every
    # injection-timing frame unencodable.
    (1803, "INJECTION_TIMING",
     ["INJ_TIMING_CYL1", "INJ_TIMING_CYL2", "INJ_TIMING_CYL3", "INJ_TIMING_CYL4"],
     "degBTDC", 0, 550, 4,
     "Per-cylinder start-of-injection timing. REQUIRED BY THE PROBLEM "
     "STATEMENT section B ('Injection timing parameters'). On a FADEC engine "
     "this is ECU-scheduled and varies with load, speed and knock feedback, so "
     "it is monitored as a DEVIATION from the commanded value rather than "
     "against a fixed number. CANaerospace has no standard identifier for it, "
     "so it sits in the user-defined range."),
    (1804, "IGNITION_TIMING",
     ["IGN_TIMING_CYL1", "IGN_TIMING_CYL2", "IGN_TIMING_CYL3", "IGN_TIMING_CYL4"],
     "degBTDC", -20, 60, 4,
     "Per-cylinder ignition timing. Not itself a problem-statement parameter, "
     "but it is what the knock sensor retards, so a diverging ignition-vs-"
     "injection timing pair is a direct combustion-quality indicator "
     "(PRD Part 2 section 10.6)."),
]


def dbc_float_message(can_id: int, name: str, sender: str, sig: str,
                      unit: str, lo: float, hi: float) -> str:
    """One CANaerospace Normal Operation Data message.

    Layout is fixed by CANAS section 3.3: a four-byte header followed by the
    parameter value. Motorola (big-endian) byte order throughout, which is the
    CANaerospace convention.
    """
    return (
        f"BO_ {can_id} {name}: 8 {sender}\n"
        f" SG_ NODE_ID : 7|8@0+ (1,0) [0|255] \"\" EDGE\n"
        f" SG_ DATA_TYPE : 15|8@0+ (1,0) [0|255] \"\" EDGE\n"
        f" SG_ SERVICE_CODE : 23|8@0+ (1,0) [0|255] \"\" EDGE\n"
        f" SG_ MESSAGE_CODE : 31|8@0+ (1,0) [0|255] \"\" EDGE\n"
        f" SG_ {sig} : 39|32@0+ (1,0) [{lo}|{hi}] \"{unit}\" EDGE\n"
    )


def build() -> str:
    L: list[str] = []
    L.append(
        'VERSION "DRDO PS-26054 HUMS bus - CANaerospace 1.6 - Rotax 915 i reference"\n'
    )
    L.append("""
NS_ :
\tNS_DESC_
\tCM_
\tBA_DEF_
\tBA_
\tVAL_
\tCAT_DEF_
\tCAT_
\tFILTER
\tBA_DEF_DEF_
\tEV_DATA_
\tENVVAR_DATA_
\tSGTYPE_
\tSGTYPE_VAL_
\tBA_DEF_SGTYPE_
\tBA_SGTYPE_
\tSIG_TYPE_REF_
\tVAL_TABLE_
\tSIG_GROUP_
\tSIG_VALTYPE_
\tSIGTYPE_VALTYPE_
\tBO_TX_BU_
\tBA_DEF_REL_
\tBA_REL_
\tBA_DEF_DEF_REL_
\tBU_SG_REL_
\tBU_EV_REL_
\tBU_BO_REL_

BS_:

BU_: ECU_A ECU_B VMC HUMS EDGE

""")

    floats: list[int] = []

    # --- standard Normal Operation Data, both ECS channels -----------------
    for base, name, unit, lo, hi, _cm in STANDARD_PARAMS:
        sender = SENDER_OVERRIDE.get(f"ECSA_{name}", "ECU_A")
        L.append(dbc_float_message(base, f"ECSA_{name}", sender, name, unit, lo, hi))
        floats.append(base)
        L.append(
            dbc_float_message(
                base + CH_B_OFFSET, f"ECSB_{name}", "ECU_B", name, unit, lo, hi
            )
        )
        floats.append(base + CH_B_OFFSET)

    for cid, name, unit, lo, hi, _cm in SINGLE_CHANNEL_PARAMS:
        L.append(dbc_float_message(cid, name, "ECU_A", name, unit, lo, hi))
        floats.append(cid)

    # --- user-defined HUMS messages ----------------------------------------
    for cid, name, sigs, unit, lo, hi, _n, _cm in UDL_PARAMS:
        L.append(f"BO_ {cid} {name}: 8 HUMS\n")
        for i, sname in enumerate(sigs):
            start = 7 + i * 16
            scale = 0.01 if unit == "m/s2" else 0.1
            L.append(
                f" SG_ {sname} : {start}|16@0+ ({scale},{lo}) "
                f"[{lo}|{hi}] \"{unit}\" EDGE\n"
            )
        L.append("\n")

    # --- ECU status: user-defined, carries lane health ---------------------
    L.append("""BO_ 1810 ECU_STATUS: 8 ECU_A
 SG_ ECU_MODE : 7|8@0+ (1,0) [0|255] "" EDGE
 SG_ ACTIVE_LANE : 15|2@0+ (1,0) [0|3] "" EDGE
 SG_ LANE_A_HEALTH : 13|1@0+ (1,0) [0|1] "" EDGE
 SG_ LANE_B_HEALTH : 12|1@0+ (1,0) [0|1] "" EDGE
 SG_ WARN_LAMP_A : 11|2@0+ (1,0) [0|2] "" EDGE
 SG_ WARN_LAMP_B : 9|2@0+ (1,0) [0|2] "" EDGE
 SG_ ECU_ERROR_FLAGS : 23|16@0+ (1,0) [0|65535] "" EDGE
 SG_ THROTTLE_POS : 39|8@0+ (0.5,0) [0|100] "%" EDGE
 SG_ WASTEGATE_POS : 47|8@0+ (0.5,0) [0|100] "%" EDGE
 SG_ KNOCK_RETARD : 55|8@0+ (0.1,0) [0|25.5] "deg" EDGE
 SG_ ECU_SEQ_COUNTER : 63|8@0+ (1,0) [0|255] "" EDGE

BO_ 1811 MANIFOLD_AIR: 8 ECU_A
 SG_ MAT1 : 7|16@0+ (0.1,-50) [-50|150] "degC" EDGE
 SG_ MAT2 : 23|16@0+ (0.1,-50) [-50|150] "degC" EDGE
 SG_ AIR_FLOW : 39|16@0+ (1,0) [0|12000] "g/min" EDGE
 SG_ INJECTOR_DUTY : 55|8@0+ (0.5,0) [0|100] "%" EDGE

BO_ 1805 ECU_COMMANDS: 8 ECU_A
 SG_ IGN_TIMING_CMD : 7|16@0+ (0.1,-10) [-10|60] "degBTDC" EDGE
 SG_ INJ_TIMING_CMD : 23|16@0+ (0.1,0) [0|550] "degBTDC" EDGE
 SG_ INJECTION_PERIOD : 39|16@0+ (0.01,0) [0|40] "ms" EDGE
 SG_ KNOCK_INTENSITY : 55|8@0+ (0.005,0) [0|1] "" EDGE

BO_ 1813 AIRFRAME_COOLING: 8 VMC
 SG_ COOLING_FLAP_PCT : 7|8@0+ (0.5,0) [0|100] "%" EDGE
 SG_ OIL_FLAP_PCT : 15|8@0+ (0.5,0) [0|100] "%" EDGE

BO_ 1812 AIR_DATA: 8 VMC
 SG_ ALTITUDE_FT : 7|16@0+ (1,-1000) [-1000|40000] "ft" EDGE
 SG_ OAT : 23|16@0+ (0.1,-70) [-70|70] "degC" EDGE
 SG_ AIRSPEED_KMH : 39|16@0+ (0.1,0) [0|400] "km/h" EDGE
 SG_ HUMIDITY : 55|8@0+ (0.5,0) [0|100] "%" EDGE
 SG_ FLIGHT_PHASE : 63|8@0+ (1,0) [0|7] "" EDGE

""")

    # --- float declarations -------------------------------------------------
    for cid, name, *_ in STANDARD_PARAMS:
        L.append(f"SIG_VALTYPE_ {cid} {name} : 1;\n")
        L.append(f"SIG_VALTYPE_ {cid + CH_B_OFFSET} {name} : 1;\n")
    for cid, name, *_ in SINGLE_CHANNEL_PARAMS:
        L.append(f"SIG_VALTYPE_ {cid} {name} : 1;\n")
    L.append("\n")

    # --- node comments ------------------------------------------------------
    L.append(
        'CM_ BU_ ECU_A "Engine Control Unit Lane A. The Rotax 915 i carries a '
        "certified dual-channel FADEC for ignition and injection (EASA TCDS "
        "E.121 section 2). Lane A publishes on Display CAN Lane A via Harness "
        "Interface Connector A, and drives Warning Lamp A (12 V, 120 mA). "
        'CANaerospace calls this ECS channel A."\n'
    )
    L.append(
        'CM_ BU_ ECU_B "Engine Control Unit Lane B. Independent redundant '
        "channel on Display CAN Lane B via Harness Interface Connector B, "
        "driving Warning Lamp B. CANaerospace ECS channel B, identifiers "
        "offset +64 from channel A. Having both lanes on the bus gives the "
        "ingest layer a genuine two-source cross-check, which is the cheapest "
        'and strongest sensor-validity vote available (PRD Part 1 section 8.3)."\n'
    )
    L.append(
        'CM_ BU_ VMC "Vehicle Management Computer. Supplies the air data the '
        "physics model needs. Not part of the engine EMS; carried in the "
        'CANaerospace user-defined range."\n'
    )
    L.append(
        'CM_ BU_ HUMS "Health and Usage Monitoring instrumentation added by '
        "THIS PROJECT and not fitted to a standard 915 i: per-cylinder "
        "cylinder-head thermocouples, per-cylinder EGT breakout, a tri-axial "
        "MEMS accelerometer and a turbine fuel-flow meter. Declared separately "
        'so no reader mistakes added instrumentation for factory capability."\n'
    )
    L.append(
        'CM_ BU_ EDGE "Edge node. Raspberry Pi 4 / Jetson class with a CAN '
        "interface in the production build; python-can virtual bus in the demo "
        '(decision D1)."\n'
    )

    # --- message comments ---------------------------------------------------
    for base, _name, _u, _lo, _hi, cm in STANDARD_PARAMS:
        L.append(f'CM_ BO_ {base} "CANaerospace ID {base} (ECS channel A). {cm}"\n')
        L.append(
            f'CM_ BO_ {base + CH_B_OFFSET} "CANaerospace ID {base + CH_B_OFFSET} '
            f'(ECS channel B, +64 offset). Redundant lane of ID {base}."\n'
        )
    for cid, _name, _u, _lo, _hi, cm in SINGLE_CHANNEL_PARAMS:
        L.append(f'CM_ BO_ {cid} "CANaerospace ID {cid}. {cm}"\n')
    for cid, _name, _s, _u, _lo, _hi, _n, cm in UDL_PARAMS:
        L.append(f'CM_ BO_ {cid} "User-defined (CANAS 1800-1899). {cm}"\n')

    L.append(
        'CM_ SG_ 500 SERVICE_CODE "CANaerospace: for Normal Operation Data this '
        "byte continuously reflects the status of the data or of the "
        "transmitting unit, so the validity of every value is known at the "
        "instant it arrives. This is the bus-level input to the value-state "
        'model of PRD Part 4 section 7.1."\n'
    )
    L.append(
        'CM_ SG_ 500 MESSAGE_CODE "CANaerospace: message numbering. Detects '
        "missing frames and lets a receiver compare the age of messages from "
        "redundant sources -- i.e. decide which FADEC lane is fresher. Drives "
        'the STALE state of PRD Part 4 section 7.1."\n'
    )
    L.append(
        'CM_ SG_ 1810 ECU_ERROR_FLAGS "Bitfield. bit0 SENSOR_FAULT, bit1 '
        "IGNITION_FAULT, bit2 INJECTION_FAULT, bit3 OVERBOOST, bit4 "
        "KNOCK_DETECTED, bit5 WASTEGATE_FAULT, bit6 LIMP_MODE, bit7 "
        "OVERSPEED_PROTECT, bit8 LANE_A_FAULT, bit9 LANE_B_FAULT, bit10 "
        "GEN1_FAULT, bit11 GEN2_FAULT, bit12 FUEL_PRESS_FAULT, bit13 "
        'MAT_OVER_LIMIT, bit14 COOLANT_OVER_LIMIT, bit15 OIL_PRESS_LOW."\n'
    )
    L.append(
        'CM_ BO_ 1805 "ECU commanded ignition and injection schedule. The bus '
        'carries what the ECU COMMANDED; messages 1803/1804 carry what the HUMS '
        'instrumentation MEASURED per cylinder. Their difference is the '
        'diagnostic quantity of PRD Part 2 section 10.2 Method C: a fouled '
        'injector opens late and its deviation grows with engine speed, because '
        'a fixed solenoid delay is more crank angle at higher rpm. Injection '
        'period is the engine primary fuel-metering command, OM-915 i Ed.0 '
        'Rev.4 section 7.5.3."' + chr(10)
    )
    L.append(
        'CM_ SG_ 1810 KNOCK_RETARD "Ignition retard commanded by the knock '
        "sensor feedback loop. A rising trend at constant power is an early "
        'combustion-quality indicator (PRD Part 2 section 10.6)."\n'
    )
    L.append(
        'CM_ BO_ 1813 "Airframe cooling-air flap positions. This engine has NO '
        "thermostat: the manufacturer's manuals contain neither the word nor "
        'the part, so what holds coolant and oil temperature is the air the '
        'airframe admits and these are the actuators that admit it. Like the '
        'wastegate they SATURATE, and a radiator losing capacity spends this '
        'travel long before it moves a temperature: measured, losing 30 percent '
        'of the cooling air moves the flap 31.8 sensor-sigmas and the coolant '
        '4.0."' + chr(10)
    )
    L.append(
        'CM_ SG_ 1811 MAT1 "Manifold air temperature from the lane A MATS. MATS is '
        'fitted to both FADEC lanes [IM Rev.5 failure matrix]."\n'
    )
    L.append('CM_ SG_ 1811 MAT2 "Manifold air temperature from the lane B MATS."\n')
    L.append(
        'CM_ SG_ 500 NODE_ID "CANaerospace: the transmitting station. A frame '
        "whose Node-ID is not a declared transmitter of the message is refused "
        'by the receiver, never decoded (audit 15 Sep, P0)."\n'
    )
    L.append(
        'CM_ SG_ 500 DATA_TYPE "CANaerospace data type. Every header message on '
        "this bus carries FLOAT (2). NODATA (0) or any other type is refused as a "
        'reading: a NODATA payload decodes as 0.0 and must not become one."\n'
    )
    L.append("\n")

    # --- node attributes ----------------------------------------------------
    L.append('BA_DEF_ BU_ "CANaerospaceNodeId" INT 0 255;\n')
    L.append('BA_DEF_DEF_ "CANaerospaceNodeId" 0;\n')
    for node, node_id in NODE_IDS.items():
        L.append(f'BA_ "CANaerospaceNodeId" BU_ {node} {node_id};\n')
    L.append("\n")

    # --- value tables -------------------------------------------------------
    L.append(
        'VAL_ 1810 ECU_MODE 0 "OFF" 1 "STARTING" 2 "RUNNING" 3 "LIMP" '
        '4 "SHUTDOWN" 5 "FAULT" ;\n'
    )
    L.append(
        'VAL_ 1810 ACTIVE_LANE 0 "NONE" 1 "ONLY_A" 2 "ONLY_B" 3 "AUTO_AB" ;\n'
    )
    # Warning lamp states are exactly those the manufacturer FMEA uses.
    L.append('VAL_ 1810 WARN_LAMP_A 0 "OFF" 1 "ON" 2 "FLASHING" ;\n')
    L.append('VAL_ 1810 WARN_LAMP_B 0 "OFF" 1 "ON" 2 "FLASHING" ;\n')
    L.append(
        'VAL_ 1812 FLIGHT_PHASE 0 "GROUND" 1 "STARTUP" 2 "TAXI" 3 "TAKEOFF" '
        '4 "CLIMB" 5 "CRUISE" 6 "DESCENT" 7 "LANDING" ;\n'
    )
    text = "".join(L)
    return _normalise(text)


def _normalise(text: str) -> str:
    """Enforce DBC syntax rules the string builders above do not guarantee.

    Every CM_ (comment) and VAL_ (value table) statement must terminate with a
    semicolon, and message blocks read better separated by a blank line.
    Normalising here rather than at each call site means a new comment can be
    added without remembering the rule.
    """
    out: list[str] = []
    for line in text.split(chr(10)):
        stripped = line.rstrip()
        if stripped.startswith(("CM_ ", "VAL_ ")) and not stripped.endswith(";"):
            stripped += ";"
        out.append(stripped)
    return chr(10).join(out) + chr(10)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build(), encoding="utf-8")
    print(f"wrote {OUT}")

    import cantools

    db = cantools.database.load_file(str(OUT))
    print(f"validated: {len(db.messages)} messages")
    for m in db.messages:
        print(f"  {m.frame_id:5d} 0x{m.frame_id:03X}  {m.name:28s} {len(m.signals)} sig")


if __name__ == "__main__":
    main()
