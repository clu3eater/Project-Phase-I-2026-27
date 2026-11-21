# Archify source for the reference architecture.
# Row order is driven by connectivity so routes stay short and clear of nodes.
#   label    : units * 6.6 <= width + 8
#   sublabel : units * 3.6 <= width - 8
import json, math, io, sys

VBW = 1860  # provisional; recomputed from content below
H = 34
INTRA = 24
BAND = 36
TOP = 40
GAP = 30
MINW = 104

def wfor(label, sub):
    return max(MINW, int(math.ceil(len(label) * 6.6)) + 24)

class N:
    def __init__(s, nid, label, typ, sub=None, tag=None):
        if sub: label = label + " - " + sub
        s.id, s.label, s.typ, s.sub, s.tag = nid, label, typ, None, tag
        s.w = wfor(label, None); s.x = s.y = 0

D = "decision"
def R(*n): return list(n)

PHYS = R(N("p_sensor","ENGINE SENSOR","external"), N("p_rpm","RPM","external"),
         N("p_cht","CHT","external"), N("p_egt","EGT","external"),
         N("p_oilp","OIL PRESSURE","external"), N("p_oilt","OIL TEMPERATURE","external"),
         N("p_fuel","FUEL FLOW","external"), N("p_vib","VIBRATION SIGNATURE","external"),
         N("p_batt","BATTERY / ALTERNATOR","external"), N("p_inj","INJECTION TIMING","external"))

A1 = R(N("a_can","CAN Bus Data Acquisition","messagebus"),
       N("a_ecu","ECU/FADEC","messagebus","Communication Interface"),
       N("a_ingest","Real-Time Data Ingestion","backend"),
       N("a_valid","Reading Valid?","cloud",tag=D),
       N("a_fusion","Sensor Fusion","backend"),
       N("a_edgeai","Lightweight Onboard Analytics","backend","Edge AI"),
       N("a_buffer","72-Hour Store-and-Forward Buffer","database"))
A2 = R(N("a_reject","Reject Invalid Value","external","noise substitute"),
       N("a_vib","Vibration Order Analysis","backend"),
       N("a_tier1","Tier-1 Safety Rules On Board","backend"),
       N("a_sec","On-Board Security","security"),
       N("a_mqtt","MQTT Telemetry","messagebus","QoS + last will"))

B1 = R(N("b_thermo","Thermodynamic Behaviour Model","backend"),
       N("b_perfmap","Engine Performance Map","backend"),
       N("b_faillogic","Failure/Degradation Logic","backend"))
B2 = R(N("b_vem","Virtual Engine Model","backend","synchronized with live engine data"),
       N("b_asnew","As-New Reference","backend","predicts at same operating point"),
       N("b_residual","RESIDUAL = Measured - Predicted","backend"),
       N("b_state","Real Time Engine State Estimation","backend"),
       N("b_history","Flight History","database","record per sortie"))

C1 = R(N("c_t1","Tier 1 - Rule Based Threshold","backend"),
       N("c_t2","Tier 2 - Statistical Anomaly Detection","backend"),
       N("c_t3","Tier 3 - Deep Learning LSTM Autoencoder","backend"),
       N("c_hold","Hold - No False Alarm","external"))
C2 = R(N("c_fusion","Score Fusion","backend"),
       N("c_agree","Tiers 2 & 3 Agree?","cloud",tag=D),
       N("c_detect","Detection Of Abnormal Operating Conditions","backend"))
C3 = R(N("c_fault8","Fault Prediction - 8 Modes","backend"),
       N("c_f1","Misfire","external"), N("c_f2","Injector Abnormality","external"),
       N("c_f3","Cooling Degradation","external"), N("c_f4","Lubrication Issues","external"),
       N("c_f5","Sensor Drift / Failure","external"), N("c_f6","Combustion Instability","external"),
       N("c_f7","Overheating Trends","external"), N("c_f8","Abnormal Vibration","external"))
C4 = R(N("c_health","Health Indicators & Indices","backend","per sub-system"),
       N("c_degrade","Degradation Tracking","backend"),
       N("c_trend","Trend Analysis","backend"),
       N("c_kalman","Physics-Based Kalman Filter","backend",
         "conformal interval - narrows the hour-remaining range"))
C5 = R(N("c_rul","RUL Estimation With Confidence Interval","backend"),
       N("c_prob","Failure Probability - Next Sortie","backend",
         "calibrated: will it survive the mission?"),
       N("c_xai","Explainable AI","backend",
         "every alert traced to a physical quantity and ATA chapter"),
       N("c_advisory","Maintenance Advisory","backend","part - ATA chapter - deadline"))

D1 = R(N("d_env","Environmental Condition Simulation","backend"),
       N("d_mission","Mission Profile Simulation","backend"),
       N("d_rel","Mission Reliability?","cloud",tag=D),
       N("d_go","Go","backend"), N("d_golim","Go With Limits","messagebus"),
       N("d_nogo","No Go","security"))
D2 = R(N("d_c1","High Altitude","external"), N("d_c2","Endurance Mission","external"),
       N("d_c3","Hot-Weather Operation","external"), N("d_c4","Rapid Throttle Transitions","external"),
       N("d_replay","Replay Of Historical Mission Data","backend"),
       N("d_post","Post-Flight Analysis & Mission Replay","backend"))

E1 = R(N("e_advisory","Maintenance Advisory","frontend"),
       N("e_alerts","Fault Alerts With Recommended Action","frontend"))
E2 = R(N("e_param","Real-Time Engine Parameter Visualization","frontend"),
       N("e_abn","Detection Of Abnormal Conditions","frontend","operator view"))
E3 = R(N("e_health","Real-Time Engine Health Status","frontend"),
       N("e_eff","Engine Efficiency Trends","frontend"),
       N("e_reports","Mission-Wise Health Reports","frontend"))

FF = R(N("f_pm","Predictive Maintenance","cloud"), N("f_or","Operational Reliability","cloud"),
       N("f_mp","Mission Planning","cloud"), N("f_lcm","Life Cycle Management","cloud"))

def rw(r, gap=GAP): return sum(n.w for n in r) + gap * (len(r) - 1)

def centre(r, y, gap=GAP, cx=VBW / 2):
    x = cx - rw(r, gap) / 2
    for n in r: n.x, n.y = int(round(x)), y; x += n.w + gap

def frm(r, y, x0, gap=GAP):
    x = x0
    for n in r: n.x, n.y = int(round(x)), y; x += n.w + gap

# ----------------------------------------------------------------- layout ---
y = TOP
centre(PHYS, y);                       y += H + BAND
centre(A1, y); centre(A2, y + H + INTRA); y += 2 * H + INTRA + BAND
b2y, b1y = y + H + INTRA, y
centre(B2, b2y)
frm(B1, b1y, B2[0].x + B2[0].w + 64)   # kept clear of the Virtual Engine Model column
y += 2 * H + INTRA + BAND
for r in (C1, C2, C3, C4, C5):
    centre(r, y, gap=26 if r is C3 else GAP); y += H + INTRA
y += BAND - INTRA
dw, ew = max(rw(D1), rw(D2)), max(rw(E1), rw(E2), rw(E3))
x0 = VBW / 2 - (dw + 120 + ew) / 2
ex = x0 + dw + 120
for i, (dr, er) in enumerate(((D1, E1), (D2, E2), (None, E3))):
    yy = y + i * (H + INTRA)
    if dr: frm(dr, yy, x0)
    frm(er, yy, ex)
y += 3 * H + 2 * INTRA + BAND
centre(FF, y)
VBH = int(y + H + 46)

ROWS = [PHYS, A1, A2, B1, B2, C1, C2, C3, C4, C5, D1, D2, E1, E2, E3, FF]
MARGIN = 46
right = max(n.x + n.w for r in ROWS for n in r)
left = min(n.x for r in ROWS for n in r)
shift = MARGIN - left
if shift:
    for r in ROWS:
        for n in r: n.x += shift
VBW = int(max(n.x + n.w for r in ROWS for n in r) + MARGIN)
nodes = [n for r in ROWS for n in r]
ids = lambda rs: [n.id for r in rs for n in r]

comps = []
for n in nodes:
    c = {"id": n.id, "type": n.typ, "label": n.label}
    if n.sub: c["sublabel"] = n.sub
    if n.tag: c["tag"] = n.tag
    c["pos"] = [n.x, n.y]; c["size"] = [n.w, H]
    comps.append(c)

boundaries = [
 {"kind":"region","label":"1. PHYSICAL LAYER - AERO PISTON ENGINE ON MALE UAV - ISR, COMMUNICATION RELAY, MARITIME SURVEILLANCE","wraps":ids([PHYS]),"pad":16},
 {"kind":"security-group","label":"A. EDGE COMPUTING ARCHITECTURE - EMBEDDED SYSTEMS ON THE AIRCRAFT","wraps":ids([A1,A2]),"pad":16},
 {"kind":"region","label":"B. DIGITAL TWIN CORE FRAMEWORK - CENTRAL INTELLIGENCE LAYER CONTINUOUSLY SYNCHRONIZED & VIRTUAL REPRESENTATION","wraps":ids([B1,B2]),"pad":16},
 {"kind":"region","label":"C. AI/ML LAYER - PHYSICS-INFORMED, HYBRID THERMODYNAMIC + DATA-DRIVEN, ADAPTIVE LEARNING","wraps":ids([C1,C2,C3,C4,C5]),"pad":16},
 {"kind":"region","label":"D. SIMULATION AND REPLAY","wraps":ids([D1,D2]),"pad":16},
 {"kind":"region","label":"E. VISUALIZATION DASHBOARD / HMI","wraps":ids([E1,E2,E3]),"pad":16},
 {"kind":"region","label":"F. OUTCOME","wraps":ids([FF]),"pad":16},
]

def c(a, b, label=None, variant=None):
    e = {"from": a, "to": b}
    if label: e["label"] = label
    if variant: e["variant"] = variant
    return e

conns = [
 c("p_sensor","a_can",variant="emphasis"),
 c("a_can","a_ecu",variant="emphasis"), c("a_ecu","a_ingest",variant="emphasis"),
 c("a_ingest","a_valid",variant="emphasis"),
 dict(c("a_valid","a_reject","invalid","dashed"),
      labelAt=[A1[3].x + A1[3].w // 2, A1[0].y + H + 13]), c("a_valid","a_fusion","valid","emphasis"),
 c("a_fusion","a_edgeai",variant="emphasis"), c("a_edgeai","a_buffer",variant="emphasis"),
 c("a_ingest","a_vib"), c("a_vib","a_tier1"), c("a_tier1","a_sec"),
 c("a_sec","a_mqtt",variant="security"), c("a_buffer","a_mqtt"),
 dict(c("a_mqtt","b_vem","downlink","emphasis"),
      labelAt=[B2[0].x + B2[0].w // 2, B1[0].y + 9]),
 c("b_thermo","b_vem"), c("b_perfmap","b_vem"), c("b_faillogic","b_vem"),
 c("b_vem","b_asnew",variant="emphasis"), c("b_asnew","b_residual",variant="emphasis"),
 c("b_residual","b_state",variant="emphasis"), c("b_state","b_history"),
 c("b_state","c_t1",variant="emphasis"), c("b_state","c_t2"), c("b_state","c_t3"),
 c("c_t1","c_fusion"), c("c_t2","c_fusion"), c("c_t3","c_fusion"),
 c("c_fusion","c_agree",variant="emphasis"),
 dict(c("c_agree","c_hold","no","dashed"),
      labelAt=[(C2[1].x + C1[3].x) // 2, C1[0].y + H + 13]), c("c_agree","c_detect","yes","emphasis"),
 c("c_detect","c_fault8",variant="emphasis"), c("c_fault8","c_f1"),
 c("c_fault8","c_health"), c("c_fault8","c_degrade"), c("c_fault8","c_trend"),
 c("c_health","c_rul"), c("c_degrade","c_rul"), c("c_trend","c_rul"),
 c("c_kalman","c_rul",variant="emphasis"),
 c("c_rul","c_prob",variant="emphasis"), c("c_rul","c_xai"),
 c("c_prob","c_advisory"), c("c_xai","c_advisory"),
 c("c_prob","d_rel","mission risk","emphasis"),
 c("d_c1","d_env"), c("d_c2","d_env"), c("d_c3","d_env"), c("d_c4","d_env"),
 c("d_env","d_mission",variant="emphasis"), c("d_mission","d_rel",variant="emphasis"),
 c("d_rel","d_go"), c("d_rel","d_golim"), c("d_rel","d_nogo",variant="security"),
 c("d_rel","d_replay"), c("d_replay","d_post",variant="emphasis"),
 c("d_post","f_pm",variant="emphasis"), c("e_eff","f_or",variant="emphasis"),
 c("e_reports","f_mp",variant="emphasis"), c("e_health","f_lcm",variant="emphasis"),
]

# Sides follow the placed geometry; a same-row hop over a neighbour dips below.
by = {n.id: n for n in nodes}
index = {}
for r in ROWS:
    for i, n in enumerate(r): index[n.id] = i
BAND_HEAD = {id(r) for r in (PHYS, A1, B1, C1, D1, E1, FF)}
head_of = {}
for r in ROWS:
    for n in r: head_of[n.id] = id(r) in BAND_HEAD
for e in conns:
    a, b = by[e["from"]], by[e["to"]]
    if a.y == b.y:
        if abs(index[a.id] - index[b.id]) == 1:
            e["fromSide"], e["toSide"] = ("right","left") if b.x > a.x else ("left","right")
        else:
            e["fromSide"] = e["toSide"] = "top" if head_of[a.id] else "bottom"
    elif b.y > a.y:
        e["fromSide"], e["toSide"] = "bottom", "top"
    else:
        e["fromSide"], e["toSide"] = "top", "bottom"

spec = {
 "schema_version":1, "diagram_type":"architecture",
 "meta":{
  "title":"Aerospace Engine Health Monitoring & Digital Twin System Architecture",
  "output":"docs/diagrams/astra-system-architecture.html",
  "quality_profile":"standard",
  "viewBox":[VBW,VBH],
  "views":[
   {"id":"acquisition","label":"Acquisition","focus":ids([PHYS,A1,A2]),
    "note":"Sensors to the edge node: acquire, validate, fuse, buffer, downlink."},
   {"id":"twin","label":"Digital twin","focus":ids([B1,B2]),
    "note":"The virtual engine and the residual it forms against an as-new reference."},
   {"id":"detection","label":"Detection","focus":ids([C1,C2,C3]),
    "note":"Three tiers, fused and gated, resolved into the eight fault modes."},
   {"id":"prognostics","label":"Prognostics","focus":ids([C4,C5]),
    "note":"Remaining life, failure probability and the advisory they justify."},
   {"id":"operations","label":"Operations","focus":ids([D1,D2,E1,FF]),
    "note":"Simulation, replay, the operator dashboard and the programme outcomes."}]},
 "components":comps, "boundaries":boundaries, "connections":conns,
}

with io.open(sys.argv[1],"w",encoding="utf-8") as f:
    json.dump(spec,f,indent=2,ensure_ascii=False); f.write("\n")
print("components",len(comps),"connections",len(conns),"viewBox",VBW,VBH)
print("widest row",max(rw(r) for r in ROWS))
