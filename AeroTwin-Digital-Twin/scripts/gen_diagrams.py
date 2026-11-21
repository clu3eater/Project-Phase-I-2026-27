# -*- coding: utf-8 -*-
"""Draw.io diagram set for PS-26054, generated rather than hand-placed.

Six diagrams, written both as one multi-page file and as one file each:

    1  Problem and Solution      what monitoring does today, and what we do
    2  System Architecture       the full stack, banded by layer
    3  Working Flow              how a CAN frame becomes a maintenance action
    4  How Health Is Measured    the residual idea, with a worked example
    5  Warning Timeline          why a wear-out model gives hours of notice
    6  Technology Stack          every framework, protocol and standard

The visual language follows docs/diagrams/system_flowchart.drawio: a dark
title bar, numbered full-width bands with a monospace tagline on the right,
and white component chips inside each band. A reader moving between the two
drawings should not have to relearn what a box means.

Generated because hand-placed diagrams drift from the system they describe.
When the architecture changes this is re-run, not nudged.

    python scripts/gen_diagrams.py
"""
from pathlib import Path
from xml.sax.saxutils import escape

OUT = (Path(__file__).resolve().parent.parent / "docs" / "diagrams"
       / "ps26054_diagrams.drawio")

INK = "#14212F"
DIM = "#44566B"
ACC = "#0D8B7C"
RED = "#C0392B"
AMB = "#C87E10"
L5, L4, L3, L2, L1, L0 = ("#0E9E8C", "#4551C0", "#773CAC", "#286BCC",
                          "#1B9949", "#526076")
GREY = "#8899AB"


def attr(v: str) -> str:
    """Escape a value for an XML attribute.

    drawio stores HTML-formatted labels ESCAPED inside `value="..."`, so the
    <b> and <br> tags have to be escaped along with the text. Escaping only
    the text -- the obvious thing to do -- produces a file drawio refuses to
    open.
    """
    return escape(v, {'"': "&quot;"})


def wash(hexcol: str, f: float = 0.90) -> str:
    """A pale fill of the same hue, so a chip reads as part of its band."""
    r, g, b = (int(hexcol[i:i + 2], 16) for i in (1, 3, 5))
    r, g, b = (int(c + (255 - c) * f) for c in (r, g, b))
    return f"#{r:02X}{g:02X}{b:02X}"


class Page:
    def __init__(self, name, w=1600, h=900):
        self.name = name
        # An id beginning with a digit is not a valid XML name, and some
        # drawio builds silently drop the page rather than complain -- which
        # looks exactly like "the file only has one diagram in it".
        self.slug = name.lower().replace(" ", "-").replace(",", "")
        self.w, self.h = w, h
        self.cells = []
        self.n = 0

    def _id(self, prefix="c"):
        self.n += 1
        return f"{prefix}{self.n}"

    def _add(self, cid, value, style, x, y, w, h):
        self.cells.append(
            f'<mxCell id="{cid}" value="{value}" style="{style}" vertex="1" '
            f'parent="1"><mxGeometry x="{x}" y="{y}" width="{w}" '
            f'height="{h}" as="geometry"/></mxCell>')
        return cid

    # -------------------------------------------------- banded style helpers
    def titlebar(self, label, tagline=None):
        style = ("rounded=0;whiteSpace=wrap;html=1;fillColor=#16324F;"
                 "strokeColor=none;fontColor=#FFFFFF;fontSize=14;fontStyle=1;"
                 "align=left;spacingLeft=16;verticalAlign=middle;")
        cid = self._add(self._id("hdr"), attr(label), style, 0, 0, self.w, 46)
        if tagline:
            self.mono(self.w - 446, 13, 430, 20, tagline, "#9DB4CC", "right")
        return cid

    def mono(self, x, y, w, h, label, color="#1F6B6B", align="center", fs=8):
        style = (f"text;html=1;align={align};verticalAlign=middle;"
                 f"fontSize={fs};fontColor={color};fontFamily=Courier New;")
        return self._add(self._id("m"), attr(label), style, x, y, w, h)

    def container(self, x, y, w, h, label, tagline=None, color="#8A968F"):
        style = (f"rounded=1;whiteSpace=wrap;html=1;fillColor=#F0F2F1;"
                 f"strokeColor={color};strokeWidth=2;verticalAlign=top;"
                 f"align=left;spacingLeft=12;spacingTop=6;fontSize=13;"
                 f"fontStyle=1;fontColor=#3D4A45;arcSize=6;")
        cid = self._add(self._id("g"), attr(label), style, x, y, w, h)
        if tagline:
            self.mono(x + w - 364, y + 8, 352, 16, tagline, "#6B7C86", "right")
        return cid

    def chip(self, x, y, w, h, label, sub=None, color="#14181A",
             fill="#FFFFFF", fs=10, sub_fs=8):
        v = f"<b>{label}</b>"
        if sub:
            v += (f"<br><font style=\"font-size:{sub_fs}px;font-weight:normal;"
                  f"color:#5D6B66\">{sub.replace(chr(10), '<br>')}</font>")
        style = (f"rounded=1;whiteSpace=wrap;html=1;fillColor={fill};"
                 f"strokeColor={color};strokeWidth=1.5;fontSize={fs};"
                 f"fontColor={color};align=center;verticalAlign=middle;"
                 f"arcSize=14;")
        return self._add(self._id("k"), attr(v), style, x, y, w, h)

    def decision(self, x, y, w, h, label, color="#14181A"):
        style = (f"rhombus;whiteSpace=wrap;html=1;fillColor=#FFFFFF;"
                 f"strokeColor={color};strokeWidth=1.5;fontSize=9;"
                 f"fontColor={color};")
        return self._add(self._id("d"), attr(label.replace("\n", "<br>")),
                         style, x, y, w, h)

    def text(self, x, y, w, h, label, color=DIM, fs=13, bold=0, align="left"):
        v = attr(f"<b>{label}</b>" if bold else label)
        style = (f"text;html=1;strokeColor=none;fillColor=none;align={align};"
                 f"verticalAlign=middle;fontSize={fs};fontColor={color};"
                 f"whiteSpace=wrap;")
        return self._add(self._id("t"), v, style, x, y, w, h)

    def band(self, x, y, w, h, label, color):
        style = (f"rounded=1;whiteSpace=wrap;html=1;fillColor={color};"
                 f"strokeColor=none;fontSize=14;fontColor=#FFFFFF;"
                 f"fontStyle=1;arcSize=10;verticalAlign=middle;")
        return self._add(self._id("b"), attr(label), style, x, y, w, h)

    def flow(self, src, dst, color="#6B7C86", label=None, dashed=0, w=1.5,
             exitd=(0.5, 1), entryd=(0.5, 0)):
        style = (f"edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;"
                 f"endArrow=block;endFill=1;strokeColor={color};"
                 f"strokeWidth={w};dashed={dashed};fontSize=9;"
                 f"fontColor={color};"
                 f"exitX={exitd[0]};exitY={exitd[1]};exitDx=0;exitDy=0;"
                 f"entryX={entryd[0]};entryY={entryd[1]};entryDx=0;entryDy=0;")
        cid = self._id("f")
        val = attr(label) if label else ""
        self.cells.append(
            f'<mxCell id="{cid}" value="{val}" style="{style}" edge="1" '
            f'parent="1" source="{src}" target="{dst}">'
            f'<mxGeometry relative="1" as="geometry"/></mxCell>')
        return cid

    def xml(self):
        body = "\n        ".join(self.cells)
        return (
            f'  <diagram name="{escape(self.name)}" id="pg-{self.slug}">\n'
            f'    <mxGraphModel dx="1400" dy="800" grid="1" gridSize="10" '
            f'guides="1" tooltips="1" connect="1" arrows="1" fold="1" '
            f'page="1" pageScale="1" pageWidth="{self.w}" '
            f'pageHeight="{self.h}" math="0" shadow="0">\n'
            f'      <root>\n        <mxCell id="0"/>\n'
            f'        <mxCell id="1" parent="0"/>\n        {body}\n'
            f'      </root>\n    </mxGraphModel>\n  </diagram>')


pages = []

# ======================= PAGE 1 : PROBLEM AND SOLUTION =======================
p = Page("1 Problem and Solution", 1600, 900)
p.titlebar("THE PROBLEM TODAY, AND WHAT WE PROPOSE  |  PS 26054",
           "REACTIVE MONITORING  ->  PREDICTIVE DIGITAL TWIN")

p.container(16, 62, 1568, 252, "A  ·  HOW ENGINE MONITORING WORKS TODAY",
            "THRESHOLD-BASED  |  REACTIVE  |  AFTER THE FACT", RED)
ids = []
x = 40
for i, (a, b) in enumerate([
        ("Engine runs", "wear accumulates quietly"),
        ("Sensor reads a value", "RPM, CHT, EGT, oil pressure"),
        ("Compare to a fixed limit", "is the value over the line?"),
        ("Alarm raised", "after the damage is done")]):
    ids.append(p.chip(x, 112, 340, 62, a, b, RED if i == 3 else DIM,
                      "#FFFFFF", 12))
    x += 380
for i in range(3):
    p.flow(ids[i], ids[i + 1], GREY, exitd=(1, 0.5), entryd=(0, 0.5))
p.chip(40, 200, 1520, 46,
       "The gap:  a limit is only crossed once damage has already happened.  "
       "Nothing here watches how the engine is CHANGING, so degradation stays "
       "invisible until it becomes a fault.", None, RED, wash(RED, 0.95), 11)
p.chip(40, 256, 1520, 42,
       "What it costs:  mission aborts, unplanned maintenance, and in the "
       "worst case the loss of a high-value ISR aircraft.",
       None, DIM, "#FFFFFF", 11)

p.container(16, 330, 1568, 248, "B  ·  HOW OUR DIGITAL TWIN WORKS INSTEAD",
            "PREDICTIVE  |  PHYSICS-INFORMED  |  EXPLAINABLE", ACC)
ids2 = []
x = 34
for a, b, col in [("Engine and FADEC", "CAN bus telemetry", L0),
                  ("Physics twin", "what an as-new engine\nwould do now", L2),
                  ("The difference", "measured minus expected\nthis is health",
                   ACC),
                  ("AI and ML layer", "anomaly, fault class,\nremaining life",
                   L3),
                  ("Failure probability", "will it last the\nnext sortie?", L4),
                  ("Maintenance advisory", "what to do,\nand by when", L5)]:
    ids2.append(p.chip(x, 380, 240, 74, a, b, col, wash(col, 0.93), 11))
    x += 256
for i in range(5):
    p.flow(ids2[i], ids2[i + 1], ACC, exitd=(1, 0.5), entryd=(0, 0.5))
p.chip(34, 472, 1532, 46,
       "Warning arrives in HOURS, not seconds.  Maintenance is planned instead "
       "of reacted to, and a commander gets a straight answer before the "
       "aircraft leaves the ground.", None, ACC, wash(ACC, 0.94), 11)
p.mono(34, 528, 1532, 16,
       "REAL-TIME ENGINE STATE ESTIMATION  ·  ANOMALY DETECTION  ·  "
       "DEGRADATION TRACKING  ·  FAULT PREDICTION  ·  MISSION REPLAY",
       "#0E7F70", "left")

p.container(16, 594, 774, 254, "C  ·  PARAMETERS MONITORED",
            "PS SECTION B", L2)
x, y = 34, 644
for lab in ["RPM", "Cylinder head temperature", "Exhaust gas temperature",
            "Oil pressure", "Oil temperature", "Fuel flow",
            "Vibration signatures", "Battery / alternator health",
            "Injection timing"]:
    p.chip(x, y, 240, 44, lab, None, L2, "#FFFFFF", 10)
    x += 250
    if x > 700:
        x = 34
        y += 54

p.container(810, 594, 774, 254, "D  ·  FAULTS DETECTED AND PREDICTED",
            "PS SECTION C", L3)
x, y = 828, 644
for lab in ["Misfire", "Injector abnormality", "Cooling degradation",
            "Lubrication issues", "Sensor drift", "Combustion instability",
            "Overheating trends", "Abnormal vibration"]:
    p.chip(x, y, 240, 44, lab, None, L3, "#FFFFFF", 10)
    x += 250
    if x > 1490:
        x = 828
        y += 54
pages.append(p)

# ======================== PAGE 2 : SYSTEM ARCHITECTURE ========================
p = Page("2 System Architecture", 1600, 1180)
p.titlebar("INDIGENOUS DIGITAL TWIN  —  HEALTH MONITORING, FAULT PREDICTION "
           "AND MISSION RELIABILITY  |  PS 26054",
           "ATMANIRBHAR BHARAT  |  SAFE SKIES  |  MISSION READY")

# ---- 0 : physical ------------------------------------------------------------
p.container(16, 56, 1568, 110,
            "0  ·  PHYSICAL LAYER — AERO PISTON ENGINE ON MALE UAV",
            "SENSORS  |  ENGINE  |  AIRFRAME", L0)
eng = p.chip(32, 104, 194, 46, "Engine + FADEC / ECU", "dual lane, CAN 2.0B",
             L0, wash(L0, 0.90))
x = 240
for lab, w in [("RPM", 104), ("CHT", 104), ("EGT", 104), ("Oil Pressure", 126),
               ("Oil Temp", 110), ("Fuel Flow", 112), ("Vibration", 112),
               ("Battery / Alt", 126), ("Injection Timing", 140)]:
    p.chip(x, 104, w, 46, lab, None, L0, "#FFFFFF", 9)
    x += w + 10

# ---- 1 : edge ----------------------------------------------------------------
p.container(16, 178, 1568, 154,
            "1  ·  DATA ACQUISITION AND EDGE COMPUTING — EMBEDDED SYSTEMS",
            "REAL-TIME  |  LOW POWER  |  DATALINK RESILIENT", L1)
a1 = p.chip(32, 228, 194, 58, "CAN Bus Acquisition",
            "SocketCAN, python-can,\nCANaerospace DBC", L1)
a2 = p.chip(240, 228, 172, 58, "Decode and Validate",
            "range, rate, staleness", L1)
d1 = p.decision(428, 224, 114, 66, "Reading\nvalid?", L1)
a3 = p.chip(558, 228, 166, 58, "Sensor Fusion",
            "Kalman, Hampel filter", L1)
a4 = p.chip(738, 228, 196, 58, "Vibration Order Analysis",
            "envelope, kurtogram,\nBPFO / BPFI bearing races", L1)
a5 = p.chip(948, 228, 176, 58, "Tier-1 Safety Rules",
            "onboard, no link needed", AMB, wash(AMB, 0.92))
a6 = p.chip(1138, 228, 176, 58, "Edge Inference",
            "ONNX Runtime on ARM", L1)
a7 = p.chip(1328, 228, 240, 58, "72-Hour Buffer",
            "store and forward\nthrough a blackout", L1, wash(L1, 0.92))
p.flow(eng, a1, L0, "CAN 2.0B", w=2)
for src, dst in ((a1, a2), (a2, d1), (d1, a3), (a3, a4), (a4, a5),
                 (a5, a6), (a6, a7)):
    p.flow(src, dst, "#6B7C86", exitd=(1, 0.5), entryd=(0, 0.5))
p.mono(408, 292, 156, 14, "no -> reject, never substitute", "#B04A3A")

# ---- 2 : physics -------------------------------------------------------------
p.container(16, 344, 1568, 138,
            "2  ·  PHYSICS-BASED ENGINE MODEL — THERMODYNAMIC BEHAVIOUR AND "
            "PERFORMANCE MAPS",
            "PHYSICS-BASED  |  MODEL-DRIVEN  |  EXPLAINABLE", L2)
x = 32
for lab, sub in [
        ("Mean-Value Engine Model",
         "mass and energy balance,\nfilling and emptying"),
        ("Combustion Model", "Cantera chemistry,\nWiebe burn, EGT"),
        ("Engine Performance Maps",
         "torque, BMEP, BSFC,\nvolumetric efficiency"),
        ("Turbo and Intercooler",
         "boost, wastegate,\nmanifold air temperature"),
        ("Degradation Model",
         "six wear pathways,\nwear-out fault onset"),
        ("Shadow Model",
         "as-new reference at the\nsame operating point")]:
    p.chip(x, 392, 240, 66, lab, sub, L2)
    x += 255
p.mono(32, 462, 1100, 14,
       "PHYSICS-INFORMED MODELLING  ·  HYBRID THERMODYNAMIC + DATA-DRIVEN  ·  "
       "ENGINE-AGNOSTIC BY CONFIGURATION", "#3E6FA8", "left")

# ---- 3 : AI / ML -------------------------------------------------------------
p.container(16, 494, 1568, 244,
            "3  ·  AI / ML LAYER — ANOMALY DETECTION, FAULT PREDICTION, "
            "REMAINING USEFUL LIFE",
            "MULTI-MODEL  |  CALIBRATED  |  EARLY DETECTION", L3)
# The three detectors are STACKED, not in a row. Side by side, the arrows into
# score fusion have to pass through each other and the band reads as a
# pipeline -- which would say tier 3 runs after tier 1. They run in parallel.
t1 = p.chip(32, 536, 236, 56, "Tier 1 — Rules",
            "37 threshold rules,\nrun on the edge", L3)
t2 = p.chip(32, 600, 236, 56, "Tier 2 — Statistical",
            "isolation forest, k-means,\ncorrelation", L3)
t3 = p.chip(32, 664, 236, 56, "Tier 3 — Deep",
            "LSTM sequence model,\nmulti-channel patterns", L3)
fu = p.chip(288, 600, 172, 56, "Score Fusion",
            "weighted, with a\ndisagreement gate", L3, wash(L3, 0.90))
for t in (t1, t2, t3):
    p.flow(t, fu, "#6B7C86", exitd=(1, 0.5), entryd=(0, 0.5))
o1 = p.chip(482, 536, 248, 56, "Fault Identification",
            "misfire · injector · cooling · lubrication\nsensor drift · "
            "combustion · overheat · vibration", L3, "#FFFFFF", 10, 7)
o2 = p.chip(482, 600, 248, 56, "Remaining Useful Life",
            "LSTM + physics Kalman,\nconformal interval", L4)
o3 = p.chip(482, 664, 248, 56, "Failure Probability",
            "P(fail within 12 / 25 / 50 h),\ncalibrated", L4, wash(L4, 0.90))
for o in (o1, o2, o3):
    p.flow(fu, o, "#6B7C86", exitd=(1, 0.5), entryd=(0, 0.5))
p.mono(32, 726, 428, 12, "THREE INDEPENDENT DETECTORS, RUN IN PARALLEL",
       "#7A4FA8", "left")

p.container(740, 518, 838, 140, "SUPPORTING CAPABILITIES",
            "RUN ALONGSIDE THE CHAIN", L3)
x, y = 750, 542
for lab, sub, col, fill in [
        ("Explainable AI", "exact closed-form attribution", L3, "#FFFFFF"),
        ("Trend Analysis", "EMA smoothing, CUSUM knee", L3, "#FFFFFF"),
        ("Federated Learning", "FedAvg, differential privacy", L3, "#FFFFFF"),
        ("Physics-Informed NN", "residual laws as penalty", L3, "#FFFFFF"),
        ("Battery State of Health", "internal resistance trend", L3,
         "#FFFFFF"),
        ("Efficiency Trending", "BSFC, brake thermal", L3, "#FFFFFF")]:
    p.chip(x, y, 262, 50, lab, sub, col, fill, 10)
    x += 278
    if x > 1400:
        x, y = 750, 600
p.chip(750, 664, 818, 56, "Maintenance Advisory",
       "costed, scheduled and explained — \"inspect the cooling path within "
       "25 flight hours\", with the evidence attached", L5, wash(L5, 0.90), 10)

# ---- 4 : twin core -----------------------------------------------------------
p.container(16, 750, 1568, 152,
            "4  ·  DIGITAL TWIN CORE FRAMEWORK — CENTRAL INTELLIGENCE LAYER",
            "MODULAR  |  SCALABLE  |  SECURE", L4)
p.chip(32, 800, 248, 66, "Twin State Engine",
       "reported · desired ·\npredicted · simulated", L4, wash(L4, 0.90))
p.chip(294, 800, 206, 66, "Real-Time Ingestion",
       "10 Hz sync, staleness\nand link-state machine", L4)
p.chip(514, 800, 206, 66, "REST + WebSocket API",
       "FastAPI, Pydantic\nschema validation", L4)
p.chip(734, 800, 250, 66, "Security",
       "TLS · JWT RS256 · bcrypt · RBAC ×4\nrate limit · tamper-evident audit",
       RED, wash(RED, 0.94), 10, 7)
p.chip(998, 800, 196, 66, "MQTT Broker",
       "QoS, last will,\nlost-airframe alarm", L4)
p.chip(1208, 800, 172, 66, "Flight History",
       "SQLite, one row\nper sortie, ECTM", L4)
p.chip(1394, 800, 174, 66, "Fleet Registry",
       "PostgreSQL,\nmany airframes", L4)
p.mono(32, 872, 1140, 14,
       "MODULAR ARCHITECTURE FOR FUTURE SCALABILITY  ·  REAL-TIME DATA "
       "INGESTION  ·  CLOUD OR LOCAL SERVER-BASED ANALYTICS",
       "#4551C0", "left")

# ---- 5 and 6 : simulation, HMI ----------------------------------------------
p.container(16, 914, 880, 156, "5  ·  SIMULATION AND REPLAY",
            "TEST  |  VALIDATE  |  REPLAY", L2)
x = 32
for lab, sub in [("Mission Replay", "scrub, event markers"),
                 ("Environmental Sim", "altitude, hot-and-high"),
                 ("Scenario Engine", "rapid throttle, what-if"),
                 ("Flight Recorder", "Parquet, one per sortie")]:
    p.chip(x, 964, 200, 62, lab, sub, L2)
    x += 210
p.mono(32, 1034, 700, 16,
       "MISSION PROFILE SIMULATION  ·  SCENARIO TESTING  ·  POST-FLIGHT "
       "ANALYSIS", "#3E6FA8", "left")

p.container(910, 914, 674, 156, "6  ·  VISUALISATION DASHBOARD / HMI",
            "OPERATORS · ENGINEERS · MAINTAINERS", L5)
x = 926
for lab, sub in [("Ground Console", "React + TypeScript,\neight screens"),
                 ("Alerts and Advisory",
                  "five levels, instruction\nnot a token"),
                 ("Mission-Wise Reports",
                  "post-flight PDF,\nhealth per sortie")]:
    p.chip(x, 964, 210, 62, lab, sub, L5)
    x += 220
p.mono(1226, 1034, 342, 16, "MIL-STD-1472H  ·  MIL-STD-411F  ·  ISA-18.2",
       "#0E7F70", "right")

# ---- 7 : outcome -------------------------------------------------------------
p.container(16, 1082, 1568, 80, "7  ·  OUTCOME",
            "HIGHER AVAILABILITY  |  LOWER COST  |  MISSION SUCCESS", ACC)
x = 32
for lab, w in [("Failure predicted before it happens", 290),
               ("Condition-based maintenance", 256),
               ("Go / no-go before launch", 234),
               ("Fleet-level readiness", 216),
               ("Indigenous, zero licence cost", 256),
               ("Life-cycle management", 214)]:
    p.chip(x, 1116, w, 32, lab, None, ACC, wash(ACC, 0.92), 10)
    x += w + 12
pages.append(p)

# ========================== PAGE 3 : WORKING FLOW ==========================
p = Page("3 Working Flow", 1600, 1060)
p.titlebar("WORKING FLOW  —  HOW A CAN FRAME BECOMES A MAINTENANCE ACTION  |  "
           "PS 26054",
           "ACQUIRE -> VALIDATE -> COMPARE -> DETECT -> PREDICT -> ACT")

stages = [
    ("ACQUIRE", L0, [("Engine sensors", "nine measured channels"),
                     ("FADEC / ECU", "dual lane, CAN 2.0B"),
                     ("CAN frame", "CANaerospace DBC")]),
    ("VALIDATE", L1, [("Decode signal", "from the raw frame"),
                      ("Plausibility check", "range, rate, staleness"),
                      ("Fuse and filter", "reject, never substitute")]),
    ("COMPARE", L2, [("Physics twin", "as-new reference"),
                     ("Residual", "measured minus expected"),
                     ("Health index", "per subsystem, smoothed")]),
    ("DETECT", L3, [("Rules on the edge", "instant safety alerts"),
                    ("Statistical models", "unusual behaviour"),
                    ("Deep model", "subtle multi-channel patterns")]),
    ("PREDICT", L4, [("Fault class", "which of the eight"),
                     ("Remaining life", "hours, with a range"),
                     ("Failure probability", "for the next sortie")]),
    ("ACT", L5, [("Maintenance advisory", "action and deadline"),
                 ("Ground console", "alerts, trends, replay"),
                 ("Mission report", "post-flight record")]),
]
y = 62
prev = None
for si, (stage, col, cells) in enumerate(stages):
    p.container(16, y, 1568, 132, f"{si}  ·  {stage}", None, col)
    badge = p.band(32, y + 42, 132, 72, stage, col)
    x = 190
    row = []
    for a, b in cells:
        row.append(p.chip(x, y + 42, 440, 72, a, b, col,
                          wash(ACC, 0.90) if a == "Residual" else "#FFFFFF",
                          12))
        x += 456
    p.flow(badge, row[0], col, exitd=(1, 0.5), entryd=(0, 0.5))
    for i in range(2):
        p.flow(row[i], row[i + 1], col, exitd=(1, 0.5), entryd=(0, 0.5))
    if prev is not None:
        p.flow(prev, row[0], GREY, exitd=(0.5, 1), entryd=(0.5, 0))
    prev = row[-1]
    y += 144

p.container(16, y, 1568, 80, "RESILIENCE  ·  WHEN THE DATALINK DROPS",
            "STORE AND FORWARD  |  LAST WILL", AMB)
p.chip(32, y + 38, 1536, 32,
       "The edge node keeps deciding and stores 72 hours of data.  On "
       "reconnect it forwards what the ground missed, and the broker reports "
       "any aircraft that went silent.", None, AMB, wash(AMB, 0.94), 11)
pages.append(p)

# ===================== PAGE 4 : HOW HEALTH IS MEASURED =====================
p = Page("4 How Health Is Measured", 1500, 860)
p.titlebar("HOW HEALTH IS MEASURED  —  THE RESIDUAL IDEA  |  PS 26054",
           "A READING ON ITS OWN SAYS NOTHING")

p.chip(370, 76, 760, 56, "SAME FLIGHT CONDITIONS",
       "throttle  ·  altitude  ·  airspeed  ·  outside air temperature",
       DIM, "#EFF2F5", 14, 10)

real = p.chip(150, 186, 500, 140, "REAL ENGINE",
              "in service, 900 hours flown\n\ncylinder head temperature "
              "MEASURED:   112 °C", L2, wash(L2, 0.90), 15, 11)
twin = p.chip(850, 186, 500, 140, "PHYSICS TWIN",
              "as-new reference, same conditions\n\ncylinder head temperature "
              "EXPECTED:   103 °C", L1, wash(L1, 0.90), 15, 11)

diff = p.chip(430, 396, 640, 92, "THE DIFFERENCE  =  + 9 °C",
              "not a limit breach, but this engine is running hotter than it "
              "should for this operating point", ACC, wash(ACC, 0.88), 17, 11)
p.flow(real, diff, L2, w=2.5, exitd=(0.5, 1), entryd=(0.25, 0))
p.flow(twin, diff, L1, w=2.5, exitd=(0.5, 1), entryd=(0.75, 0))

x = 150
for a, b, col in [("WHAT is wrong", "cooling path degradation", L3),
                  ("HOW BAD it is", "health index and trend", L4),
                  ("HOW LONG you have", "remaining life and probability", L5)]:
    o = p.chip(x, 558, 400, 86, a, b, col, "#FFFFFF", 14, 10)
    p.flow(diff, o, ACC, w=2, exitd=(0.5, 1), entryd=(0.5, 0))
    x += 430

p.chip(150, 692, 1200, 66,
       "This is why a limit-based system misses degradation.  112 °C is well "
       "inside every red line, so no threshold fires.  It is only wrong "
       "RELATIVE to what this engine should be doing today.",
       None, INK, "#F0F2F1", 12)
p.mono(150, 778, 1200, 16,
       "REAL-TIME ENGINE STATE ESTIMATION  ·  DEGRADATION TRACKING  ·  "
       "MONITORING OF ENGINE HEALTH INDICATORS", "#0E7F70", "left")
pages.append(p)

# ====================== PAGE 5 : WARNING TIMELINE ======================
p = Page("5 Warning Timeline", 1600, 660)
p.titlebar("WHY THE WARNING ARRIVES EARLY  —  WEAR RAISES RISK  |  PS 26054",
           "PREDICTING PROBABLE FAILURES BEFORE OCCURRENCE")

p.container(16, 56, 1568, 254,
            "THE LIFE OF A DEVELOPING FAULT, LEFT TO RIGHT",
            "SAME ENGINE  |  SAME FLIGHT HOURS  |  TWO WAYS OF WATCHING IT",
            L4)
ids = []
x = 26
for a, b, col, risk in [
        ("Engine as-new", "no measurable residual", L1, "risk: low"),
        ("Wear accumulates", "residuals begin to drift", L1, "risk: rising"),
        ("Health index falls", "trend detected, still serviceable", L2,
         "risk: climbing"),
        ("Fault begins", "identified by class and severity", AMB,
         "risk: high"),
        ("Advisory issued", "action, deadline, evidence", L3, "ACT HERE"),
        ("Failure avoided", "engine serviced on the ground", L5, "—")]:
    cid = p.chip(x, 98, 238, 104, a, b, col, wash(col, 0.93), 12)
    p.mono(x, 206, 238, 16, risk, col)
    ids.append(cid)
    x += 259
for i in range(5):
    p.flow(ids[i], ids[i + 1], GREY, exitd=(1, 0.5), entryd=(0, 0.5))

# The time axis: a plain rule with the direction of travel written on it, so
# the six stages read as one engine ageing rather than six separate states.
p.chip(32, 246, 1533, 14, "", None, GREY, GREY, 8)
p.mono(32, 268, 700, 18, "FLIGHT HOURS ACCUMULATE  ->", DIM, "left", 10)
p.mono(865, 268, 700, 18, "END OF USEFUL LIFE", RED, "right", 10)

p.container(16, 326, 774, 150, "CONVENTIONAL MONITORING", "REACTIVE", RED)
p.chip(32, 372, 742, 88,
       "Sees nothing until a reading crosses a fixed limit, which happens at "
       "the far right of this timeline.  By then the damage is done, and the "
       "aircraft may already be airborne.", None, RED, wash(RED, 0.95), 12)

p.container(810, 326, 774, 150, "DIGITAL TWIN WITH A WEAR-OUT MODEL",
            "PREDICTIVE", ACC)
p.chip(826, 372, 742, 88,
       "Sees the residual drift from the second stage onward, and reports a "
       "rising probability of failure while the engine is still serviceable "
       "and on the ground.", None, ACC, wash(ACC, 0.94), 12)

p.container(16, 492, 1568, 132,
            "WHY THIS WORKS  —  DEGRADATION IS MODELLED AS A PROCESS WITH A "
            "RATE", "RELIABILITY ENGINEERING", L4)
x = 32
for a, b in [("Wear-out hazard",
              "damage raises the chance\nof a fault, as in a real engine"),
             ("Rate, not just state",
              "the model tracks how fast\nhealth is falling"),
             ("Condition becomes warning",
              "current health carries\ninformation about the future"),
             ("Hours of notice",
              "enough time to schedule\nrather than react")]:
    p.chip(x, 540, 372, 68, a, b, L4, "#FFFFFF", 11)
    x += 384
pages.append(p)

# ====================== PAGE 6 : TECHNOLOGY STACK ======================
p = Page("6 Technology Stack", 1600, 928)
p.titlebar("TECHNOLOGY STACK  —  EVERY FRAMEWORK, PROTOCOL AND STANDARD  |  "
           "PS 26054",
           "100% OPEN SOURCE  |  ZERO LICENCE COST  |  INDIGENOUS")

stack = [
    ("FRONTEND / HMI", L5, "OPERATOR-FACING", [
        ("React 18 + TypeScript", "eight console screens"),
        ("Vite", "build and dev server"),
        ("WebSocket client", "live telemetry at 10 Hz"),
        ("Inline SVG rendering", "trend plots, no charting library"),
        ("MIL-STD-1472H layout", "human engineering"),
        ("ISA-18.2 alarm palette", "five severity levels")]),
    ("BACKEND / API", L4, "SERVER-SIDE", [
        ("Python 3.12", "single language across layers"),
        ("FastAPI + Uvicorn", "async REST and WebSocket"),
        ("Pydantic v2", "schema validation on every payload"),
        ("websockets", "/ws/state live push to the console"),
        ("asyncpg", "async PostgreSQL for the fleet server"),
        ("pytest · ruff · mypy", "regression suite across all six layers")]),
    ("AI / ML", L3, "PREDICTION", [
        ("PyTorch", "LSTM sequence model"),
        ("scikit-learn", "isolation forest, k-means, isotonic"),
        ("CatBoost / HistGradientBoosting", "calibrated failure probability"),
        ("ONNX Runtime", "quantised inference on the edge"),
        ("NumPy / SciPy", "signal processing, kurtogram"),
        ("FedAvg, written in-house", "federated learning, DP noise")]),
    ("PHYSICS AND SIMULATION", L2, "MODEL-DRIVEN", [
        ("Cantera", "combustion chemistry and EGT"),
        ("Mean-value engine model", "mass and energy balance"),
        ("Engine performance maps", "torque, BMEP, BSFC"),
        ("Six-pathway degradation model", "wear-out hazard, fault onset"),
        ("Monte-Carlo fleet generator", "run-to-failure synthetic data"),
        ("NASA C-MAPSS", "external benchmark for prognostics")]),
    ("EDGE AND EMBEDDED", L1, "ONBOARD", [
        ("SocketCAN / python-can", "CAN 2.0B acquisition"),
        ("cantools", "CANaerospace DBC decode"),
        ("Eclipse Mosquitto", "MQTT broker, QoS and last will"),
        ("paho-mqtt", "airframe-side client"),
        ("ARM64 single-board computer", "Raspberry Pi class, low power"),
        ("Store-and-forward buffer", "72 hours through a blackout")]),
    ("DATA AND STORAGE", L0, "PERSISTENCE", [
        ("SQLite", "per-airframe flight history, ECTM"),
        ("PostgreSQL + asyncpg", "fleet registry across airframes"),
        ("Parquet + PyArrow", "flight recorder, one file per sortie"),
        ("pandas", "sortie aggregation and feature build"),
        ("Append-only audit log", "who saw what, and when"),
        ("Versioned dataset manifests", "every claim traceable to a build")]),
]
for i, (name, col, tag, rows) in enumerate(stack):
    cx = 16 + (i % 3) * 528
    cy = 56 + (i // 3) * 322
    p.container(cx, cy, 512, 310, name, tag, col)
    for j, (lab, sub) in enumerate(rows):
        p.chip(cx + 16, cy + 44 + j * 42, 480, 36, lab, sub, col,
               "#FFFFFF", 10, 8)

p.container(16, 700, 1568, 104,
            "SECURITY  —  PROTOCOLS AND CONTROLS",
            "DEFENCE DATA STAYS ON DEFENCE INFRASTRUCTURE", RED)
x = 32
for lab, sub in [("TLS 1.3", "transport encryption"),
                 ("JWT RS256", "asymmetric signed tokens"),
                 ("bcrypt", "password hashing"),
                 ("RBAC, four roles", "operator · engineer · maintainer · "
                  "admin"),
                 ("Rate limiting", "and account lockout"),
                 ("Tamper-evident audit", "hash-chained log"),
                 ("MQTT auth + ACL", "one topic scope per airframe")]:
    p.chip(x, 744, 210, 42, lab, sub, RED, wash(RED, 0.95), 9, 7)
    x += 220

p.container(16, 816, 1568, 94, "STANDARDS AND COMPLIANCE",
            "INTEROPERABLE BY DESIGN", ACC)
x = 32
for lab, sub in [("CANaerospace", "airborne CAN messaging"),
                 ("STANAG 4586", "UAV / ground station interoperability"),
                 ("ISO 13381-1", "condition monitoring and prognostics"),
                 ("MIL-STD-1472H", "human engineering"),
                 ("MIL-STD-411F", "aircrew alerting"),
                 ("ISA-18.2", "alarm management")]:
    p.chip(x, 860, 248, 42, lab, sub, ACC, wash(ACC, 0.94), 9, 7)
    x += 256
pages.append(p)

# ------------------------------------------------------------------ write out
HEAD = '<mxfile host="app.diagrams.net" agent="PS26054" version="24.0.0">'
OUT.parent.mkdir(parents=True, exist_ok=True)

# The combined book. The five diagrams appear as TABS along the bottom of the
# drawio window, which is easy to miss if you are not looking for it.
OUT.write_text(HEAD + "\n" + "\n".join(pg.xml() for pg in pages)
               + "\n</mxfile>\n", encoding="utf-8")
print(f"Saved {OUT}")
print(f"  ({len(pages)} pages, shown as TABS along the bottom of the drawio window)")
print()

# And one file per diagram, because a single diagram is easier to open, to drop
# into a slide, and to point at in a review than a tab nobody noticed.
print("Also saved one file per diagram:")
for i, pg in enumerate(pages, 1):
    one = OUT.parent / f"{i}_{pg.slug.split('-', 1)[1]}.drawio"
    one.write_text(HEAD + "\n" + pg.xml() + "\n</mxfile>\n", encoding="utf-8")
    print(f"  {one.name:<36} {len(pg.cells):>3} shapes  {pg.w}x{pg.h}")
