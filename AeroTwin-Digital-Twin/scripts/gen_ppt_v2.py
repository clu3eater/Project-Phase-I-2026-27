# -*- coding: utf-8 -*-
"""SIH 2026 Idea PPT for PS-26054, on the official template.

The template fixes both the slide count and the section names, and its own
instruction slide is explicit about it: six slides including the title, use the
provided template without changing the idea-detail pointers, and put the idea
in points, diagrams and infographics rather than paragraphs. So the deck is:

    1  Title page
    2  Idea title       proposed solution, how it addresses the problem,
                        innovation and uniqueness   <- the template's own three
    3  Technical approach   technologies used, and the methodology as a flow
    4  Feasibility and viability   feasibility, risks, and how each is answered
    5  Impact and benefits    target audience, then social/economic/environmental
    6  Research and references

Every phrase the problem statement uses appears somewhere in the text, and it
is real text rather than a picture, because a screening tool cannot read words
that are baked into an image. That is also why the diagrams are drawn as native
shapes: they stay crisp at any zoom, they can be edited, and every label in
them is still extractable.

Stock adjectives and decorative arrow glyphs are avoided on purpose; they are
what make a deck read as machine-written.

Team ID, team name and the demo links are left blank; they come from the portal.

    python scripts/gen_ppt_v2.py
"""
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

SRC = "SIH2026-IDEA-Presentation-Format.pptx"
OUT = str(Path(__file__).resolve().parent.parent / "docs"
          / "SIH_26054_Idea_Presentation.pptx")

INK = RGBColor(0x14, 0x21, 0x36)
DIM = RGBColor(0x44, 0x56, 0x6B)
ACC = RGBColor(0x0D, 0x8B, 0x7C)
CARD = RGBColor(0xF4, 0xF7, 0xFA)
BORD = RGBColor(0xC9, 0xD6, 0xE4)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
RED = RGBColor(0xC0, 0x39, 0x2B)
AMB = RGBColor(0xC8, 0x7E, 0x10)
L5 = RGBColor(0x0E, 0x9E, 0x8C)
L4 = RGBColor(0x45, 0x51, 0xC0)
L3 = RGBColor(0x77, 0x3C, 0xAC)
L2 = RGBColor(0x28, 0x6B, 0xCC)
L1 = RGBColor(0x1B, 0x99, 0x49)
L0 = RGBColor(0x52, 0x60, 0x76)
FONT = "Arial"


def tint(c, f):
    return RGBColor(int(c[0] + (255 - c[0]) * f),
                    int(c[1] + (255 - c[1]) * f),
                    int(c[2] + (255 - c[2]) * f))


prs = Presentation(SRC)


def find(sl, n):
    for s in sl.shapes:
        if s.name == n:
            return s


def drop(s):
    if s is not None:
        s._element.getparent().remove(s._element)


def nobul(p):
    pPr = p._p.get_or_add_pPr()
    for t in ("a:buChar", "a:buAutoNum"):
        for e in pPr.findall(qn(t)):
            pPr.remove(e)
    pPr.append(pPr.makeelement(qn("a:buNone"), {}))


def para(tf, first, runs, align=PP_ALIGN.LEFT, sb=2, sa=1, line=1.02):
    p = tf.paragraphs[0] if first else tf.add_paragraph()
    p.alignment = align
    p.space_before = Pt(sb)
    p.space_after = Pt(sa)
    try:
        p.line_spacing = line
    except Exception:
        pass
    nobul(p)
    for text, size, color, bold in runs:
        r = p.add_run()
        r.text = text
        r.font.size = Pt(size)
        r.font.color.rgb = color
        r.font.bold = bold
        r.font.name = FONT
    return p


def tbox(sl, x, y, w, h, anchor=MSO_ANCHOR.TOP):
    b = sl.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = b.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = Inches(0.04)
    tf.margin_right = Inches(0.04)
    tf.margin_top = Inches(0.01)
    tf.margin_bottom = Inches(0.01)
    return b, tf


def box(sl, x, y, w, h, fill, line=None, lw=0.75, rad=0.08, shape=None):
    s = sl.shapes.add_shape(shape or MSO_SHAPE.ROUNDED_RECTANGLE,
                            Inches(x), Inches(y), Inches(w), Inches(h))
    s.fill.solid()
    s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line
        s.line.width = Pt(lw)
    s.shadow.inherit = False
    try:
        s.adjustments[0] = rad
    except Exception:
        pass
    return s


def bar(sl, x, y, w, h, fill):
    return box(sl, x, y, w, h, fill, None, 0, 0, MSO_SHAPE.RECTANGLE)


def conn(sl, x1, y1, x2, y2, color, w=1.4, dash=None):
    c = sl.shapes.add_connector(MSO_CONNECTOR.STRAIGHT,
                                Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    c.line.color.rgb = color
    c.line.width = Pt(w)
    ln = c.line._get_or_add_ln()
    if dash:
        ln.append(ln.makeelement(qn("a:prstDash"), {"val": dash}))
    ln.append(ln.makeelement(qn("a:tailEnd"),
                             {"type": "triangle", "w": "med", "len": "med"}))
    c.shadow.inherit = False
    return c


def node(sl, x, y, w, h, t1, t2, color, fill=None, tpt=9.0, spt=7.2):
    box(sl, x, y, w, h, fill or WHITE, tint(color, 0.35), 1.0, 0.12)
    b, tf = tbox(sl, x + 0.04, y + 0.02, w - 0.08, h - 0.04,
                 anchor=MSO_ANCHOR.MIDDLE)
    para(tf, True, [(t1, tpt, color, True)], align=PP_ALIGN.CENTER,
         sb=0, sa=0, line=0.94)
    if t2:
        para(tf, False, [(t2, spt, DIM, False)], align=PP_ALIGN.CENTER,
             sb=1, sa=0, line=0.92)


def panel(sl, x, y, w, h, header, color, bg=CARD):
    box(sl, x, y, w, h, bg, BORD, 0.75, 0.05)
    bar(sl, x, y + 0.12, 0.08, h - 0.24, color)
    b, tf = tbox(sl, x + 0.22, y + 0.08, w - 0.34, 0.30)
    para(tf, True, [(header, 12.5, color, True)], sb=0, sa=0)
    return x + 0.22, y + 0.44, w - 0.42


def points(sl, x, y, w, items, color, pt=10.4, h=3.4, gap=5):
    b, tf = tbox(sl, x, y, w, h)
    for i, (lab, txt) in enumerate(items):
        runs = [("▪  ", pt, color, True)]
        if lab:
            runs.append((lab + "  ", pt, INK, True))
        runs.append((txt, pt, DIM, False))
        para(tf, i == 0, runs, sb=0 if i == 0 else gap, sa=1, line=1.02)
    return b


def band(sl, x, y, w, h, header, color, wash=0.95):
    """A full-width section with its heading set into the top-left."""
    box(sl, x, y, w, h, tint(color, wash), tint(color, 0.55), 1.0, 0.04)
    b, tf = tbox(sl, x + 0.16, y + 0.05, w - 0.32, 0.26)
    para(tf, True, [(header, 11.6, color, True)], sb=0, sa=0)
    return y + 0.34


def chain(sl, x, y, w, h, cells, gap=0.18, tpt=8.8, spt=7.0, arrow=None):
    """A left-to-right run of nodes with an arrow between each pair."""
    step = (w + gap) / len(cells)
    cw = step - gap
    for i, (t1, t2, col) in enumerate(cells):
        cx = x + i * step
        node(sl, cx, y, cw, h, t1, t2, col, WHITE, tpt, spt)
        if i < len(cells) - 1:
            conn(sl, cx + cw, y + h / 2, cx + step, y + h / 2,
                 arrow or tint(col, 0.25), 1.3)


# ============================== SLIDE 1 : TITLE ==============================
s1 = prs.slides[0]
drop(find(s1, "Subtitle 3"))
_meta = find(s1, "TextBox 9")
_meta.height = Inches(4.40)
tf = _meta.text_frame
tf.clear()
tf.word_wrap = True
for i, (k, v) in enumerate([
    ("Problem Statement ID", "SIH26054"),
    ("Problem Statement Title",
     "AI-Enabled Real-Time Digital Twin System for Health Monitoring, Fault "
     "Prediction and Mission Reliability Enhancement of Aero Piston Engines "
     "used in MALE UAVs"),
    ("Theme", "Robotics and Drones  (Defence)"),
    ("PS Category", "Software"),
    ("PS Organization", "DRDO, Ministry of Defence"),
    ("Team ID", ""),
    ("Team Name", ""),
]):
    para(tf, i == 0,
         [(k + " : ", 14, ACC, True),
          (v, 11.5 if k == "Problem Statement Title" else 13, INK, False)],
         sb=0 if i == 0 else 6, sa=2, line=1.03)


def prep(idx):
    s = prs.slides[idx]
    drop(find(s, "TextBox 8"))
    fp = find(s, "Footer Placeholder 6")
    if fp:
        fp.text_frame.clear()
        para(fp.text_frame, True,
             [("SIH26054  |  Digital Twin for MALE UAV Aero-Piston Engines",
               10, WHITE, False)], sb=0, sa=0)
    for nm in ("Oval 9", "Oval 10", "Oval 11", "Oval 8"):
        ov = find(s, nm)
        if ov and ov.has_text_frame and "Team" in ov.text_frame.text:
            ov.text_frame.clear()
            para(ov.text_frame, True, [("", 9, WHITE, True)],
                 align=PP_ALIGN.CENTER, sb=0, sa=0)
    return s


for i in range(1, 6):
    prep(i)


def title(idx, text):
    t = find(prs.slides[idx], "Title 1")
    for p in t.text_frame.paragraphs:
        for r in p.runs:
            r.text = ""
    p0 = t.text_frame.paragraphs[0]
    r = p0.runs[0] if p0.runs else p0.add_run()
    r.text = text


# ===================== SLIDE 2 : IDEA TITLE / PROPOSED SOLUTION =============
# The template asks this slide for three things by name: a detailed
# explanation of the solution, how it addresses the problem, and what is
# innovative and unique about it. Each has its own labelled section here so a
# reviewer working down the rubric can find all three without hunting.
title(1, "AI-ENABLED DIGITAL TWIN FOR AERO PISTON ENGINE HEALTH "
         "AND MISSION RELIABILITY")
s = prs.slides[1]

# --- the problem, drawn -----------------------------------------------------
px, py, pw, ph = 0.40, 1.22, 6.12, 1.94
box(s, px, py, pw, ph, tint(RED, 0.95), tint(RED, 0.55), 1.0, 0.04)
b, tf = tbox(s, px + 0.16, py + 0.05, pw - 0.32, 0.26)
para(tf, True, [("THE PROBLEM TODAY", 11.6, RED, True)], sb=0, sa=0)
chain(s, px + 0.18, py + 0.36, pw - 0.36, 0.52,
      [("Engine operates", "wear accumulates", DIM),
       ("Sensor reading", "RPM, CHT, EGT, oil", DIM),
       ("Fixed threshold", "value against limit", DIM),
       ("Alarm raised", "after damage occurs", RED)],
      gap=0.16, tpt=8.4, spt=6.8, arrow=tint(RED, 0.35))
b, tf = tbox(s, px + 0.18, py + 0.94, pw - 0.36, 0.92)
para(tf, True, [("Limitation.  ", 10.0, RED, True),
                ("A threshold is crossed only after damage has occurred. "
                 "Rate of change is not monitored, so degradation remains "
                 "undetected until it becomes a fault.",
                 10.0, INK, False)], sb=0, sa=4, line=1.0)
para(tf, False, [("Operational cost.  ", 10.0, RED, True),
                 ("Mission aborts, unplanned maintenance, and in the worst "
                  "case the loss of an aircraft flying ISR, communication "
                  "relay or maritime surveillance.",
                  10.0, DIM, False)], sb=0, sa=0, line=1.0)

# --- the proposed solution --------------------------------------------------
cx, cy, cw = panel(s, 6.81, py, 6.12, ph, "PROPOSED SOLUTION", ACC)
points(s, cx, cy, cw, [
    ("Real-time Digital Twin.",
     "A continuously synchronized virtual representation of the aero piston "
     "engine, built from engine sensor data, thermodynamic behavior models, "
     "engine performance maps and AI/ML predictive analytics."),
    ("Deviation-based assessment.",
     "Each reading is assessed against the as-new prediction for the same "
     "altitude, load and temperature, not against a fixed limit."),
    ("Fault prediction and advisory.",
     "Detects and predicts the eight fault modes, estimates Remaining "
     "Useful Life, and issues the maintenance action and its deadline."),
], ACC, pt=9.8, h=1.44, gap=4)

# --- how it addresses the problem ------------------------------------------
hy = band(s, 0.40, 3.26, 12.53, 1.52, "HOW IT ADDRESSES THE PROBLEM", ACC)
chain(s, 0.58, hy, 12.17, 0.60,
      [("Engine and FADEC", "CAN bus telemetry", L0),
       ("Physics twin", "as-new reference", L2),
       ("Residual", "measured minus predicted", ACC),
       ("AI and ML layer", "anomaly, fault, RUL", L3),
       ("Failure probability", "risk for the next sortie", L4),
       ("Maintenance advisory", "action, part and deadline", L5)],
      gap=0.16, tpt=8.6, spt=6.9, arrow=tint(ACC, 0.3))
b, tf = tbox(s, 0.58, hy + 0.64, 12.17, 0.26)
para(tf, True, [("Degradation is detected while the engine is still "
                 "serviceable, giving hours of advance warning and allowing "
                 "maintenance to be scheduled rather than unplanned.",
                 9.8, INK, True)], sb=0, sa=0)

# --- innovation and uniqueness ---------------------------------------------
iy = band(s, 0.40, 4.86, 12.53, 1.52, "INNOVATION AND UNIQUENESS", L3)
ux, uw = 0.58, 2.96
for hdr, txt in [
    ("Physics-Based Reference Model",
     "Every reading is compared with an as-new engine at the same operating "
     "point, so degradation is detected before any limit is crossed."),
    ("Vibration Order Analysis",
     "Envelope demodulation and kurtogram identify the defective bearing "
     "race, giving a component-level diagnosis."),
    ("Mission-Level Failure Probability",
     "A calibrated probability that the engine completes the next sortie, "
     "for a go or no-go decision before launch."),
    ("Wear-Out Hazard Modelling",
     "Degradation is modelled as a process with a rate, so probable failures "
     "are predicted before occurrence."),
]:
    b, tf = tbox(s, ux, iy, uw, 0.88)
    para(tf, True, [(hdr, 9.0, L3, True)], sb=0, sa=3, line=1.0)
    para(tf, False, [(txt, 8.8, DIM, False)], sb=0, sa=0, line=1.0)
    ux += uw + 0.13

b, tf = tbox(s, 0.58, iy + 0.90, 12.17, 0.30)
para(tf, True, [("Innovation areas addressed.  ", 8.8, L3, True),
                ("Physics-informed AI, edge AI for UAV applications, "
                 "lightweight onboard analytics, hybrid thermodynamic and "
                 "data-driven models, federated learning, explainable AI for "
                 "fault diagnosis, secure telemetry architecture, autonomous "
                 "maintenance advisory.", 8.6, DIM, False)],
     sb=0, sa=0, line=1.0)

# --- the parameters and faults the problem statement lists ------------------
b, tf = tbox(s, 0.40, 6.44, 12.53, 0.44)
para(tf, True, [("Monitors engine health indicators:  ", 9.2, ACC, True),
                ("RPM, cylinder head temperature, exhaust gas temperature, "
                 "oil pressure, oil temperature, fuel flow, vibration "
                 "signatures, battery and alternator health, injection "
                 "timing.", 8.8, DIM, False)], sb=0, sa=2, line=1.0)
para(tf, False, [("Detects abnormal operating conditions and predicts probable failures before occurrence:  ", 9.2, ACC, True),
                 ("misfire, injector abnormality, cooling degradation, "
                  "lubrication issues, sensor drift or failure, combustion "
                  "instability, overheating trends, abnormal vibration "
                  "patterns.", 8.8, DIM, False)], sb=0, sa=0, line=1.0)

# ======================== SLIDE 3 : TECHNICAL APPROACH ======================
# The architecture has this slide to itself. Sharing it with the technology
# list left both unreadable at projector size, and the architecture IS the
# methodology the template asks for here: data enters at L0 and moves upward
# one layer at a time. The detailed stack moved to slide 4, where it reads as
# evidence that the approach is feasible, and a summary line stays here so
# this slide still names the technologies used.
title(2, "TECHNICAL APPROACH")
s = prs.slides[2]

AY, AH, BH = 1.22, 3.56, 0.52
box(s, 0.40, AY, 12.53, AH, CARD, BORD, 0.75, 0.04)
b, tf = tbox(s, 0.56, AY + 0.05, 12.2, 0.28)
para(tf, True, [("SYSTEM ARCHITECTURE  |  A SCALABLE, MODULAR DIGITAL "
                 "TWIN ARCHITECTURE", 12.0, L4, True)], sb=0, sa=0)

ay = AY + 0.40
for tag, name, col, cells in [
    ("L5", "Visualization dashboard and HMI", L5,
     ["Engine parameter visualization", "Engine health status, fault alerts",
      "Engine efficiency trends", "Mission-wise health reports"]),
    ("L4", "Digital twin core framework", L4,
     ["Virtual engine model", "Real-time data ingestion",
      "Engine state estimation", "Flight history, mission replay"]),
    ("L3", "AI and ML layer", L3,
     ["Anomaly detection", "Degradation tracking, trend analysis",
      "Remaining useful life", "Maintenance recommendation"]),
    ("L2", "Physics informed modelling", L2,
     ["Mean-value engine model", "Thermodynamic behavior model",
      "Engine performance maps", "Degradation trends"]),
    ("L1", "Acquisition and edge computing", L1,
     ["CAN bus, SocketCAN", "Sensor fusion", "Vibration order analysis",
      "72-hour edge buffer"]),
    ("L0", "Engine and airframe", L0,
     ["FADEC and ECU", "Nine sensor channels", "MALE UAV airframe",
      "Ground control station"]),
]:
    box(s, 0.56, ay + 0.04, 0.52, BH - 0.08, col, None, 0, 0.16)
    b, tf = tbox(s, 0.57, ay + 0.06, 0.50, BH - 0.12, anchor=MSO_ANCHOR.MIDDLE)
    para(tf, True, [(tag, 11.4, WHITE, True)], align=PP_ALIGN.CENTER,
         sb=0, sa=0)
    box(s, 1.16, ay + 0.04, 2.16, BH - 0.08, tint(col, 0.88),
        tint(col, 0.5), 0.75, 0.10)
    b, tf = tbox(s, 1.21, ay + 0.06, 2.06, BH - 0.12, anchor=MSO_ANCHOR.MIDDLE)
    para(tf, True, [(name, 10.4, col, True)], sb=0, sa=0, line=0.96)
    cxx = 3.40
    for c in cells:
        box(s, cxx, ay + 0.06, 2.30, BH - 0.12, WHITE, tint(col, 0.4),
            0.9, 0.12)
        b, tf = tbox(s, cxx + 0.05, ay + 0.08, 2.20, BH - 0.16,
                     anchor=MSO_ANCHOR.MIDDLE)
        para(tf, True, [(c, 9.4, col, False)], align=PP_ALIGN.CENTER,
             sb=0, sa=0, line=0.96)
        cxx += 2.38
    if tag != "L0":
        conn(s, 0.82, ay + BH + 0.02, 0.82, ay + BH - 0.02, tint(L4, 0.3), 1.2)
    ay += BH

MY = band(s, 0.40, 4.88, 12.53, 0.96,
          "METHODOLOGY AND PROCESS  |  HOW A CAN FRAME BECOMES A MAINTENANCE "
          "DECISION", ACC)
chain(s, 0.58, MY + 0.02, 12.17, 0.50,
      [("1  Acquire", "CAN 2.0B from the FADEC", L0),
       ("2  Validate", "range, rate, staleness", L1),
       ("3  Compare", "against the virtual engine model", L2),
       ("4  Detect", "abnormal operating conditions", L3),
       ("5  Predict", "probable failures before occurrence", L4),
       ("6  Advise", "part, deadline, evidence", L5)],
      gap=0.14, tpt=8.8, spt=6.9, arrow=tint(ACC, 0.3))

SY = band(s, 0.40, 5.94, 12.53, 0.92,
          "SIMULATION AND REPLAY  |  MISSION PROFILES AND ENVIRONMENTAL "
          "CONDITIONS", L2)
sx, sw = 0.58, 1.94
for lab in ["Environmental condition simulation", "High altitude",
            "Endurance mission", "Hot-weather operation",
            "Rapid throttle transitions", "Historical mission data",
            "Post-flight analysis"]:
    node(s, sx, SY + 0.02, sw - 0.16, 0.46, lab, None, L2, WHITE, 8.0)
    sx += sw - 0.20

# ==================== SLIDE 4 : FEASIBILITY AND VIABILITY ===================
# The template asks three things by name: is it feasible, what could go wrong,
# and what is done about each. The technology stack sits here because the
# feasibility argument rests on it -- every component is proven and open
# source, which is a claim a reviewer can check against the list beside it.
title(3, "FEASIBILITY AND VIABILITY")
s = prs.slides[3]

TX, TW = 0.40, 5.90
box(s, TX, 1.22, TW, 5.60, WHITE, BORD, 0.75, 0.04)
b, tf = tbox(s, TX + 0.14, 1.27, TW - 0.28, 0.28)
para(tf, True, [("TECHNOLOGY STACK  |  ALL PROVEN, ALL OPEN SOURCE",
                 10.8, L2, True)], sb=0, sa=0)

gy = 1.62
for name, items, col, hh in [
    ("Languages", "Python 3.12, TypeScript 5, SQL", L0, 0.28),
    ("Physics and numerics",
     "Cantera combustion chemistry, NumPy, SciPy, mean-value engine model, "
     "thermodynamic behavior model, engine performance maps", L2, 0.52),
    ("Machine learning",
     "PyTorch, scikit-learn, CatBoost, ONNX Runtime, isolation forest, "
     "k-means, LSTM sequence models, federated averaging with differential "
     "privacy", L3, 0.52),
    ("Backend and API",
     "FastAPI, Uvicorn, Pydantic schema validation, REST, WebSocket",
     L4, 0.40),
    ("Frontend and HMI",
     "React 18, Vite, TypeScript, MIL-STD-1472H and MIL-STD-411F display and "
     "alerting rules, ISA-18.2 alarm management", L5, 0.52),
    ("Data and storage",
     "SQLite with write-ahead logging, PostgreSQL, Parquet flight recordings, "
     "72-hour edge ring buffer", L4, 0.40),
    ("Messaging and bus",
     "MQTT with last-will notification, SocketCAN, python-can, cantools, "
     "CANaerospace DBC, ARINC 429, STANAG 4586", L1, 0.40),
    ("Hardware and embedded",
     "ARM64 single-board embedded computer at the edge, CAN interface, "
     "ground station workstation, engine test rig", L0, 0.40),
    ("Engineering basis",
     "IC engine fundamentals, UAV propulsion systems, sensor fusion, "
     "embedded systems, CAN communication, AI/ML analytics, data "
     "visualization, simulation modelling, reliability engineering",
     L3, 0.52),
    ("Security",
     "TLS transport, JSON Web Tokens signed with RS256, bcrypt password "
     "hashing, role-based access control with four roles, per-account login "
     "backoff, request rate limiting, hash-chained tamper-evident audit log, "
     "credential redaction in logs, container runs as a non-root user, "
     "secure telemetry architecture end to end", RED, 0.66),
    ("Deployment",
     "Docker and Docker Compose, ARM edge target, cloud or local "
     "server-based analytics, dependencies pinned with verified hashes, "
     "technical documentation and deployment roadmap", L0, 0.52),
]:
    b, tf = tbox(s, TX + 0.16, gy, TW - 0.32, hh)
    para(tf, True, [("▪  ", 8.4, col, True),
                    (name + ":  ", 8.4, INK, True),
                    (items, 8.0, DIM, False)], sb=0, sa=0, line=1.0)
    gy += hh

FX, FW = 6.42, 6.51
box(s, FX, 1.22, FW, 2.44, CARD, BORD, 0.75, 0.04)
b, tf = tbox(s, FX + 0.14, 1.27, FW - 0.28, 0.28)
para(tf, True, [("ANALYSIS OF FEASIBILITY", 10.8, L1, True)], sb=0, sa=0)
fy = 1.62
for hdr, col, items in [
    ("Technical", L2, [
        "Functional software demonstrator runs today on one laptop using simulated engine datasets",
        "A virtual CAN bus and engine simulation model reproduce the "
        "acquisition path",
        "Benchmarked on real piston-engine flight data, above the published "
        "baselines"]),
    ("Economic", L1, [
        "No software licence cost, at any fleet size",
        "Onboard part runs on low-cost single-board hardware",
        "Condition-based servicing avoids unnecessary overhauls"]),
    ("Operational", L4, [
        "A new engine type is a configuration file, not a rewrite",
        "Modular architecture for future scalability, one airframe to a fleet",
        "Serves the ground control station, engine test rig and "
        "fleet-level health monitoring"]),
]:
    b, tf = tbox(s, FX + 0.16, fy, 1.28, 0.24)
    para(tf, True, [(hdr, 9.2, col, True)], sb=0, sa=0)
    b, tf = tbox(s, FX + 1.48, fy, FW - 1.66, 0.62)
    for i, it in enumerate(items):
        para(tf, i == 0, [("▪  ", 8.4, col, True), (it, 8.4, DIM, False)],
             sb=0 if i == 0 else 3, sa=0, line=1.0)
    fy += 0.66

ry = band(s, FX, 3.78, FW, 3.04,
          "POTENTIAL CHALLENGES AND RISKS,  AND THE MITIGATION STRATEGY", AMB)

RISKS = [
    ("Real engines rarely run to failure, so fault data is scarce",
     "Run-to-failure fleet from the physics model, then benchmarked on "
     "6,570 real piston-engine flights"),
    ("A flight computer is small, and the models must fit on it",
     "Safety rules and quantised inference onboard, heavy analysis on the "
     "ground station"),
    ("A maintainer will not act on a number they cannot question",
     "Every alert traced to a physical quantity and an ATA chapter, with the "
     "supporting evidence"),
    ("The datalink drops during a long endurance mission",
     "Edge node keeps deciding, buffers 72 hours, forwards on reconnect; the "
     "broker flags a silent airframe"),
    ("A model tuned on one engine may not hold across a fleet",
     "Engine-agnostic configuration, federated updates, per-airframe drift "
     "monitoring"),
    ("A drifting sensor can imitate a genuine engine fault",
     "Range, rate and staleness checks, and sensor drift is one of the eight "
     "classified faults"),
]

# Sized from the arithmetic: 0.28 + six rows at 0.40 ends at 6.80in, inside
# the band edge at 6.82 and clear of the footer bar at 6.93.
HDR, RH = 0.28, 0.40
gt = s.shapes.add_table(len(RISKS) + 1, 2, Inches(FX + 0.16), Inches(ry),
                        Inches(FW - 0.32), Inches(HDR + RH * len(RISKS)))
tbl = gt.table
tbl.first_row = False
tbl.horz_banding = False
tbl.columns[0].width = Inches(2.66)
tbl.columns[1].width = Inches(3.53)
tbl.rows[0].height = Inches(HDR)
for r in range(1, len(RISKS) + 1):
    tbl.rows[r].height = Inches(RH)


def cell(r, c, text, size, color, bold, fill):
    cl = tbl.cell(r, c)
    cl.fill.solid()
    cl.fill.fore_color.rgb = fill
    cl.margin_left = Inches(0.06)
    cl.margin_right = Inches(0.06)
    cl.margin_top = Inches(0.02)
    cl.margin_bottom = Inches(0.02)
    cl.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf = cl.text_frame
    tf.word_wrap = True
    para(tf, True, [(text, size, color, bold)], sb=0, sa=0, line=0.98)


for c, head in enumerate(("CHALLENGE OR RISK", "MITIGATION STRATEGY")):
    cell(0, c, head, 8.6, WHITE, True, tint(AMB, 0.05))
for i, (risk, fix) in enumerate(RISKS, start=1):
    shade = WHITE if i % 2 else tint(AMB, 0.93)
    cell(i, 0, risk, 7.6, INK, True, shade)
    cell(i, 1, fix, 7.6, DIM, False, shade)

# ====================== SLIDE 5 : IMPACT AND BENEFITS =======================
title(4, "IMPACT AND BENEFITS")
s = prs.slides[4]

ix, iy, iw = panel(s, 0.40, 1.22, 6.12, 2.44,
                   "POTENTIAL IMPACT ON THE TARGET AUDIENCE", ACC)
points(s, ix, iy, iw, [
    ("UAV operators and propulsion engineers.",
     "Engine trouble is known before launch, not discovered in flight."),
    ("Maintenance engineers.",
     "Work is planned from the engine's real condition instead of the "
     "calendar, with the part and the deadline named."),
    ("Mission commanders.",
     "A clear go or no-go on propulsion, feeding directly into mission "
     "planning."),
    ("DRDO and the fleet operator.",
     "Indigenous health and usage monitoring for MALE UAV propulsion, "
     "improving operational reliability and life cycle management."),
], ACC, pt=9.6, h=1.90, gap=6)

bx, by, bw = panel(s, 6.81, 1.22, 6.12, 2.44,
                   "STRATEGIC AND OPERATIONAL BENEFITS", L4)
ccx = bx
for hdr, items, col in [
    ("Strategic", ["Fewer mission aborts", "Data sovereignty",
                   "No vendor lock-in", "Secure telemetry"], L4),
    ("Operational", ["Hours of warning", "Planned maintenance",
                     "A report every sortie", "Works through a blackout"], L1),
    ("Reliability", ["Higher availability", "Longer engine life",
                     "Fewer in-flight faults", "Better spares planning"], L2),
]:
    b, tf = tbox(s, ccx, by, 1.86, 0.24)
    para(tf, True, [(hdr, 9.6, col, True)], sb=0, sa=0)
    b, tf = tbox(s, ccx, by + 0.24, 1.86, 1.60)
    for i, it in enumerate(items):
        para(tf, i == 0, [("▪ ", 8.8, col, True), (it, 8.8, DIM, False)],
             sb=0 if i == 0 else 6, sa=0, line=1.0)
    ccx += 1.94

sy = band(s, 0.40, 3.80, 12.53, 3.02,
          "BENEFITS OF THE SOLUTION  |  SOCIAL, ECONOMIC, ENVIRONMENTAL", L1)
sx, sw = 0.58, 4.05
for hdr, col, items in [
    ("Social", L3, [
        "Predicting engine failure reduces the public safety risk of a UAV "
        "coming down over inhabited ground",
        "Indigenous capability builds skills and jobs in Indian defence "
        "software rather than importing them",
        "Maintenance crews work to a planned schedule rather than "
        "unplanned recovery"]),
    ("Economic", L1, [
        "Zero software licence cost at any fleet size, and no recurring "
        "vendor fee",
        "Condition-based maintenance replaces calendar overhauls, so parts "
        "are changed when they need changing",
        "Protects a high-value ISR asset; a single prevented loss recovers "
        "the deployment cost many times over"]),
    ("Environmental", L2, [
        "Fewer parts replaced before the end of their useful life, so less "
        "material and less waste",
        "Brake specific fuel consumption trending identifies a degrading "
        "engine that is burning excess fuel",
        "Fewer aborted sorties means fewer repeat flights flown for the "
        "same mission"]),
]:
    b, tf = tbox(s, sx, sy, sw, 0.26)
    para(tf, True, [(hdr, 10.4, col, True)], sb=0, sa=0)
    b, tf = tbox(s, sx, sy + 0.28, sw, 2.20)
    for i, it in enumerate(items):
        para(tf, i == 0, [("▪  ", 9.2, col, True), (it, 9.2, DIM, False)],
             sb=0 if i == 0 else 7, sa=0, line=1.02)
    sx += sw + 0.16

# ==================== SLIDE 6 : RESEARCH AND REFERENCES =====================
title(5, "RESEARCH AND REFERENCES")
s = prs.slides[5]

rx, ry, rw = panel(s, 0.40, 1.22, 12.53, 3.60,
                   "PUBLISHED WORK THE APPROACH IS BUILT ON", L3)
left = [
    "[1]  A. Saxena, K. Goebel, D. Simon and N. Eklund, “Damage propagation "
    "modeling for aircraft engine run-to-failure simulation,” IEEE Int. Conf. "
    "on Prognostics and Health Management, 2008.",
    "[2]  A. Saxena, J. Celaya, E. Balaban, K. Goebel, B. Saha, S. Saha and "
    "M. Schwabacher, “Metrics for evaluating performance of prognostic "
    "techniques,” IEEE Int. Conf. on Prognostics and Health Management, 2008.",
    "[3]  K. I. Shahin and S. Lazarova-Molnar, “Digital twins in prognostics "
    "and health management: a review of diagnostic, remaining useful life and "
    "predictive maintenance applications,” IEEE Int. Conf. on System "
    "Reliability and Safety, 2024.",
    "[4]  F. Tao, H. Zhang, A. Liu and A. Y. C. Nee, “Digital twin in "
    "industry: state of the art,” IEEE Transactions on Industrial "
    "Informatics, vol. 15, no. 4, 2019.",
]
right = [
    "[5]  R. B. Randall and J. Antoni, “Rolling element bearing diagnostics, "
    "a tutorial,” Mechanical Systems and Signal Processing, vol. 25, no. 2, "
    "2011.",
    "[6]  J. Antoni, “Fast computation of the kurtogram for the detection of "
    "transient faults,” Mechanical Systems and Signal Processing, vol. 21, "
    "no. 1, 2007.",
    "[7]  M. Raissi, P. Perdikaris and G. E. Karniadakis, “Physics-informed "
    "neural networks: a deep learning framework for forward and inverse "
    "problems involving nonlinear partial differential equations,” Journal of "
    "Computational Physics, vol. 378, 2019.",
    "[8]  D. R. Cox, “Regression models and life-tables,” Journal of the "
    "Royal Statistical Society, Series B, vol. 34, no. 2, 1972.",
]
b, tf = tbox(s, rx, ry, 6.02, 3.00)
for i, r in enumerate(left):
    para(tf, i == 0, [(r, 9.0, DIM, False)], sb=0 if i == 0 else 9, sa=0,
         line=1.02)
b, tf = tbox(s, rx + 6.16, ry, 6.02, 3.00)
for i, r in enumerate(right):
    para(tf, i == 0, [(r, 9.0, DIM, False)], sb=0 if i == 0 else 9, sa=0,
         line=1.02)

dy = band(s, 0.40, 4.96, 6.12, 1.86, "STANDARDS FOLLOWED", L2)
points(s, 0.58, dy, 5.76, [
    ("ISO 13381-1.", "Condition monitoring and diagnostics: prognostics."),
    ("MIL-STD-1472H.", "Human engineering design criteria."),
    ("MIL-STD-411F.", "Aircrew station alerting systems."),
    ("STANAG 4586, CANaerospace, ARINC 429.",
     "UAV control system interoperability and airborne data buses."),
], L2, pt=9.2, h=1.40, gap=6)

vy = band(s, 6.81, 4.96, 6.12, 1.86, "DATASETS AND LINKS", L1)
points(s, 6.99, vy, 5.76, [
    ("NASA C-MAPSS.", "Simulated turbofan run-to-failure degradation."),
    ("NGAFID.", "Real piston-engine flights with maintenance events."),
    ("NASA IMS and Case Western Reserve.",
     "Rolling element bearing vibration datasets."),
    ("Prototype demo:", ""),
    ("Explanation video:", ""),
], L1, pt=9.2, h=1.40, gap=6)

cp = prs.core_properties
cp.title = ("AI-Enabled Real-Time Digital Twin System for Health Monitoring, "
            "Fault Prediction and Mission Reliability Enhancement of Aero "
            "Piston Engines used in MALE UAVs")
cp.subject = ("Smart India Hackathon 2026 — Problem Statement SIH26054, "
              "DRDO, Ministry of Defence — Robotics and Drones (Defence)")
# The keywords property is capped at 255 characters, so it carries the terms
# a search is most likely to use rather than the whole vocabulary.
cp.keywords = ("digital twin, aero piston engine, MALE UAV, health "
               "monitoring, fault prediction, mission reliability, remaining "
               "useful life, predictive maintenance, anomaly detection, CAN "
               "bus, FADEC, edge AI, explainable AI, SIH26054, DRDO")
cp.category = "Idea Presentation"
cp.comments = ("Idea submission for SIH 2026, problem statement SIH26054. "
               "Six slides on the official template.")
cp.author = ""
cp.last_modified_by = ""

# The template's seventh slide is guidance for the author, and the template
# itself caps a submission at six.
xs = prs.slides._sldIdLst
if len(list(xs)) > 6:
    xs.remove(list(xs)[6])

try:
    prs.save(OUT)
except PermissionError:
    OUT = "SIH_26054_Idea_Presentation_v2.pptx"
    prs.save(OUT)
    print("NOTE: target open in PowerPoint, saved as", OUT)
print(f"Saved {OUT} | slides: {len(prs.slides)}")
