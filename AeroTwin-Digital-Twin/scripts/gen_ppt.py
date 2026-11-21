# -*- coding: utf-8 -*-
"""SIH 2026 Idea PPT for PS-26054 on the official 2026 template.
Standard 6-slide structure, exact template points, 100% native text (ATS-friendly),
architecture drawn natively (no image). Font = Arial (matches template body)."""
from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.oxml.ns import qn

SRC="SIH2026-IDEA-Presentation-Format.pptx"
# docs/, not the working directory -- see gen_arch.py for the reasoning.
OUT=str(Path(__file__).resolve().parent.parent / "docs"
        / "SIH_26054_Idea_Presentation.pptx")

INK=RGBColor(0x16,0x24,0x3A); DIM=RGBColor(0x45,0x57,0x6C); ACC=RGBColor(0x0E,0x8F,0x80)
CARD=RGBColor(0xF3,0xF6,0xFA); BORD=RGBColor(0xCB,0xD8,0xE6); WHITE=RGBColor(0xFF,0xFF,0xFF)
L5=RGBColor(0x0E,0x9E,0x8C); L4=RGBColor(0x4A,0x54,0xC4); L3=RGBColor(0x7A,0x3F,0xB0)
L2=RGBColor(0x2C,0x6F,0xD0); L1=RGBColor(0x1E,0x9E,0x4C); L0=RGBColor(0x55,0x63,0x7A)
CRIT=RGBColor(0xD9,0x3A,0x3A); AMBER=RGBColor(0xE0,0x8A,0x1E); VIOLET=L3; GREY=RGBColor(0x8A,0x99,0xAB)
FONT="Arial"
def tint(c,f): return RGBColor(int(c[0]+(255-c[0])*f),int(c[1]+(255-c[1])*f),int(c[2]+(255-c[2])*f))

prs=Presentation(SRC)
def find(sl,n):
    for s in sl.shapes:
        if s.name==n: return s
def remove(s):
    if s is not None: s._element.getparent().remove(s._element)
def no_bullet(p):
    pPr=p._p.get_or_add_pPr()
    for t in ("a:buChar","a:buAutoNum"):
        for e in pPr.findall(qn(t)): pPr.remove(e)
    pPr.append(pPr.makeelement(qn("a:buNone"),{}))
def para(tf,first,runs,align=PP_ALIGN.LEFT,sb=2,sa=1,line=1.02):
    p=tf.paragraphs[0] if first else tf.add_paragraph()
    p.alignment=align; p.space_before=Pt(sb); p.space_after=Pt(sa)
    try:p.line_spacing=line
    except:pass
    no_bullet(p)
    for text,size,color,bold in runs:
        r=p.add_run(); r.text=text; r.font.size=Pt(size); r.font.color.rgb=color; r.font.bold=bold; r.font.name=FONT
    return p
def tbox(sl,x,y,w,h,anchor=MSO_ANCHOR.TOP):
    b=sl.shapes.add_textbox(Inches(x),Inches(y),Inches(w),Inches(h)); tf=b.text_frame
    tf.word_wrap=True; tf.vertical_anchor=anchor
    tf.margin_left=Inches(0.05); tf.margin_right=Inches(0.05); tf.margin_top=Inches(0.02); tf.margin_bottom=Inches(0.02)
    return b,tf
def rrect(sl,x,y,w,h,fill,line=None,lw=0.75,rad=0.08):
    s=sl.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,Inches(x),Inches(y),Inches(w),Inches(h))
    s.fill.solid(); s.fill.fore_color.rgb=fill
    if line is None: s.line.fill.background()
    else: s.line.color.rgb=line; s.line.width=Pt(lw)
    s.shadow.inherit=False
    try: s.adjustments[0]=rad
    except: pass
    return s
def barrect(sl,x,y,w,h,fill):
    s=sl.shapes.add_shape(MSO_SHAPE.RECTANGLE,Inches(x),Inches(y),Inches(w),Inches(h))
    s.fill.solid(); s.fill.fore_color.rgb=fill; s.line.fill.background(); s.shadow.inherit=False; return s
def arrow(sl,x1,y1,x2,y2,color,w=1.4,dash=None):
    c=sl.shapes.add_connector(MSO_CONNECTOR.STRAIGHT,Inches(x1),Inches(y1),Inches(x2),Inches(y2))
    c.line.color.rgb=color; c.line.width=Pt(w); ln=c.line._get_or_add_ln()
    if dash: ln.append(ln.makeelement(qn('a:prstDash'),{'val':dash}))
    ln.append(ln.makeelement(qn('a:tailEnd'),{'type':'triangle','w':'med','len':'med'}))
    c.shadow.inherit=False; return c
def card(sl,x,y,w,h,header,items,color,bpt=11.0,hpt=13.0,bg=CARD):
    rrect(sl,x,y,w,h,bg,BORD,0.75,0.05); barrect(sl,x,y+0.14,0.09,h-0.28,color)
    b,tf=tbox(sl,x+0.24,y+0.12,w-0.36,h-0.22)
    para(tf,True,[(header,hpt,color,True)],sb=0,sa=4)
    for i,(lab,txt) in enumerate(items):
        runs=[("▸  ",bpt,color,True)]
        if lab: runs.append((lab+": ",bpt,INK,True))
        runs.append((txt,bpt,DIM,False))
        para(tf,False,runs,sb=3,sa=2)
    return b

# ================= SLIDE 1 : TITLE =================
s1=prs.slides[0]; remove(find(s1,"Subtitle 3"))
tf=find(s1,"TextBox 9").text_frame; tf.clear(); tf.word_wrap=True
rows=[("Problem Statement ID","26054"),
 ("Problem Statement Title","AI-Enabled Real-Time Digital Twin System for Health Monitoring, Fault Prediction & Mission Reliability Enhancement of Aero Piston Engines in MALE UAVs"),
 ("Theme","Robotics & Drones  (Defence / Aerospace)"),("PS Category","Software"),
 ("PS Organization","DRDO  (Ministry of Defence / IDEX)"),
 ("Team ID","<Team ID>"),("Team Name","<Team Name — as registered on portal>")]
for i,(k,v) in enumerate(rows):
    para(tf,i==0,[(k+" : ",14,ACC,True),(v,12 if k=='Problem Statement Title' else 13,INK,False)],sb=0 if i==0 else 6,sa=2,line=1.03)

def prep(idx):
    s=prs.slides[idx]; remove(find(s,"TextBox 8"))
    fp=find(s,"Footer Placeholder 6")
    if fp:
        fp.text_frame.clear(); para(fp.text_frame,True,[("PS 26054 · Aero-Piston Engine Digital Twin",10,WHITE,False)],sb=0,sa=0)
    for nm in ("Oval 9","Oval 10","Oval 11","Oval 8"):
        ov=find(s,nm)
        if ov and ov.has_text_frame and "Team" in ov.text_frame.text:
            ov.text_frame.clear(); para(ov.text_frame,True,[("<Team\nName>",9,WHITE,True)],align=PP_ALIGN.CENTER,sb=0,sa=0)
    return s
for i in range(1,6): prep(i)
def set_title(idx,text):
    t=find(prs.slides[idx],"Title 1")
    for p in t.text_frame.paragraphs:
        for r in p.runs: r.text=""
    r=t.text_frame.paragraphs[0].add_run() if not t.text_frame.paragraphs[0].runs else t.text_frame.paragraphs[0].runs[0]
    r.text=text
set_title(1,"IDEA — REAL-TIME DIGITAL TWIN FOR UAV AERO-PISTON ENGINES")

# ================= SLIDE 2 : IDEA / PROPOSED SOLUTION =================
s=prs.slides[1]
card(s,0.40,1.42,6.15,4.40,"PROPOSED SOLUTION  (Idea / Prototype)",[
 (None,"A real-time, physics-informed Digital Twin — a continuously synchronised virtual replica of the UAV's FADEC fuel-injected aero-piston engine, built from live CAN 2.0B telemetry, thermodynamic models and AI/ML."),
 (None,"Replaces reactive, threshold-based monitoring with predictive diagnostics — reported, desired, predicted & simulated engine states."),
 ("How it addresses the problem","real-time health monitoring of 9 signals (RPM, CHT, EGT, oil pressure & temperature, fuel flow, vibration, battery/alternator, injection timing)."),
 (None,"Detects & predicts 8 faults before failure — misfire, injector abnormality, cooling degradation, lubrication issue, sensor drift, combustion instability, overheating, abnormal vibration."),
 (None,"Estimates Remaining Useful Life (RUL) with calibrated confidence intervals & degradation trends; simulates mission profiles and replays recorded flights."),
 (None,"Envelope ORDER ANALYSIS of raw vibration names the failing bearing race (BPFO / BPFI / BSF / FTF) — a diagnosis, not just 'vibration high'."),
], ACC, bpt=11.0, hpt=13.0)
card(s,6.78,1.42,6.15,4.40,"INNOVATION & UNIQUENESS",[
 ("Physics-informed AI","Cantera + Mean-Value Model + PINN — interpretable, needs 50–70% less data."),
 ("Edge AI","<50 ms onboard critical alerts — works during comms blackout."),
 ("Calibrated failure probability","P(failure within 12 / 25 / 50 / 100 flight-hours) — a go/no-go answer for the next sortie, not only an hours figure."),
 ("Wear-out reliability model","Cox proportional-hazards fault onset: damage RAISES failure rate (ISO 13381 / Weibull β>1), so failures are predictable BEFORE they occur."),
 ("Explainable AI","EXACT closed-form attribution — the health index decomposes analytically, so no SHAP approximation is needed."),
 ("Federated learning","fleet-wide learning; raw telemetry never leaves the aircraft; secure telemetry (TLS · JWT · RBAC)."),
 ("Indigenous & Zero-Cost","100% open-source, engine-agnostic (add engine = config) — Atmanirbhar, no licensing."),
], L3, bpt=11.0, hpt=13.0)
rrect(s,0.40,5.94,12.53,0.86,tint(ACC,0.9),tint(ACC,0.4),0.75,0.05); barrect(s,0.40,6.04,0.09,0.66,ACC)
b,tf=tbox(s,0.66,5.98,12.15,0.80,anchor=MSO_ANCHOR.MIDDLE)
para(tf,True,[("Reference engine: ",9.8,ACC,True),("FADEC fuel-injected, turbocharged aero-piston (Rotax 916 iS class) · heavy-fuel Jet-A1 aero-diesel (TAPAS-BH-201 / Austro AE330 class) as production target · engine-agnostic.",9.8,DIM,False)],sb=0,sa=1,line=1.0)
para(tf,False,[("Foundation: ",9.8,ACC,True),("built on IC-engine fundamentals & UAV propulsion system architecture; state estimation against calibrated engine performance maps.",9.8,DIM,False)],sb=1,sa=0,line=1.0)

# ================= SLIDE 3 : TECHNICAL APPROACH (native architecture) =================
s=prs.slides[2]
# Technologies line (explicit)
b,tf=tbox(s,0.35,1.28,12.63,0.34)
para(tf,True,[("Technologies: ",10.5,INK,True),
 ("Python 3.12 · NumPy/SciPy · Cantera · scikit-learn · CatBoost · PyTorch → ONNX Runtime (edge) · FastAPI · Pydantic · React 18 + TypeScript + Vite · SQLite · PostgreSQL · MQTT (Mosquitto) · SocketCAN / python-can · cantools · Docker  —  100% open-source (₹0)",9.3,DIM,False)],sb=0,sa=0,line=1.0)
# --- architecture bands ---
def chip(sl,x,y,w,h,title,detail,color):
    rrect(sl,x,y,w,h,WHITE,tint(color,0.4),1.0,0.14)
    b,tf=tbox(sl,x+0.06,y+0.03,w-0.12,h-0.06,anchor=MSO_ANCHOR.MIDDLE)
    para(tf,True,[(title,8.0,color,True)],sb=0,sa=0,line=0.95)
    if detail: para(tf,False,[(detail,7.0,DIM,False)],sb=1,sa=0,line=0.92)
def band(sl,y,h,num,name,lat,color,chips):
    rrect(sl,0.35,y,1.52,h,color,None,0,0.1)
    b,tf=tbox(sl,0.40,y+0.05,1.42,h-0.1,anchor=MSO_ANCHOR.MIDDLE)
    para(tf,True,[("LAYER "+num,8.0,WHITE,True)],align=PP_ALIGN.CENTER,sb=0,sa=1,line=0.95)
    para(tf,False,[(name,8.3,WHITE,True)],align=PP_ALIGN.CENTER,sb=0,sa=1,line=0.95)
    para(tf,False,[(lat,7.3,tint(color,0.75),True)],align=PP_ALIGN.CENTER,sb=1,sa=0,line=0.95)
    ax=1.94; aw=12.98-ax; n=len(chips); gap=0.08
    wts=[c[2] if len(c)>2 else 1 for c in chips]; sw=sum(wts)
    unit=(aw-(n-1)*gap)/sw; x=ax
    for c in chips:
        w=(c[2] if len(c)>2 else 1)*unit
        chip(sl,x,y+0.05,w,h-0.10,c[0],c[1],color); x+=w+gap
top=1.66; BH=0.73; G=0.055
bands=[
 ("5","VISUALIZATION & HMI","≤ 2 s",L5,[
   ("React + TypeScript GCS","8 screens · MIL-STD-1472H / 411F",1.4),("5-Level Alerts","Green·Blue·Yellow·Orange·Red",1),
   ("Operator / Engineer views","smoothed vs raw · deadband",1.1),("Simulation & Replay","mission profiles·what-if",1.0),("Mission PDF","post-flight report",0.85)]),
 ("4","DIGITAL TWIN CORE & STATE","≤ 100 ms",L4,[
   ("MQTT + Last Will","Mosquitto · QoS · lost-airframe alarm",1.25),("Twin State Engine","Pydantic · reported/desired/predicted/simulated",1.35),
   ("REST + WebSocket + RBAC","FastAPI·JWT·roles ×4",1.15),("SQLite history","per-flight ECTM trend",0.95),("PostgreSQL","fleet registry·audit",0.9)]),
 ("3","AI/ML PREDICTIVE ANALYTICS","≤ 50 ms",L3,[
   ("3-Tier Anomaly","Rules · IsolationForest/KMeans · LSTM",1.15),
   ("8 Faults Detected","Misfire·Injector·Cooling·Lubrication·Sensor-Drift·Combustion·Overheating·Vibration",2.0),
   ("RUL + PINN + interval","LSTM + physics Kalman · conformal ±CI",1.2),
   ("Survival head","CatBoost · P(fail ≤ H h) · calibrated",1.05),
   ("Exact attribution","closed-form · NL advisory",0.95),("Federated","FedAvg · DP · privacy",0.85)]),
 ("2","PHYSICS-BASED ENGINE MODEL","≤ 20 ms",L2,[
   ("Environmental Sim","ISA·temp·press·alt·wind",1),("Cantera Combustion","chemistry·flame·EGT",1),
   ("0-D Mean-Value Model","mass/energy·CHT/EGT",1.1),("Performance Maps","BMEP·BSFC·η_vol·EGT",1),
   ("Degradation ×6","η_cool·μ_oil·η_comb…",1),("Fault Injection","synthetic run-to-failure",1)]),
 ("1","DATA ACQUISITION & EDGE","≤ 10 ms",L1,[
   ("CAN Bus","SocketCAN·python-can·DBC",1.05),("Sensor Fusion","Kalman·Hampel·resample",0.95),
   ("9 Onboard Sensors","RPM·CHT·EGT·OilP/T·Fuel·Vib·Batt·Inj",1.35),
   ("Envelope Order Analysis","kurtogram · BPFO/BPFI/BSF/FTF",1.25),
   ("Edge AI","ONNX Runtime · ARM",0.85),("72 h Buffer","store & forward",0.8)]),
 ("0","PHYSICAL ENGINE & UAV FLEET","CAN 2.0B",L0,[
   ("Engine ECU / FADEC","ARINC 429·fuel sched·wastegate·knock",1.4),
   ("Aero-Piston Engine","FADEC fuel-injected (Rotax 916 iS class · heavy-fuel Jet-A1 target)",1.8),
   ("4× UAV Edge Nodes","Raspberry Pi 4 / Jetson · MQTT uplink (TLS)",1.6)]),
]
for i,(num,name,lat,color,chips) in enumerate(bands):
    y=top+i*(BH+G); band(s,y,BH,num,name,lat,color,chips)
    if i>0: arrow(s,1.15,y+BH+G,1.15,y+0.02,tint(bands[i][3],0.1),1.4)  # data flows up
# data flow legend + methodology
ly=top+6*(BH+G)+0.02
b,tf=tbox(s,0.35,ly,12.63,0.5)
para(tf,True,[("Data flow ▲ up (sensor→physics→AI→twin→HMI) · commands ▼ down · critical edge alert <50 ms · model updates via federated learning.  ",8.6,INK,True),
 ("Methodology: ",8.6,ACC,True),
 ("CAN telemetry → physics + AI twin → predictive alerts, RUL & SHAP advisory → GCS dashboard; reproducible via docker compose up, demoed on simulated CAN (vcan0).",8.6,DIM,False)],sb=0,sa=0,line=1.0)

# ================= SLIDE 4 : FEASIBILITY AND VIABILITY =================
s=prs.slides[3]
cw=4.06; x0=0.40; y0=1.45; ch=5.0; g=0.19
card(s,x0,y0,cw,ch,"FEASIBILITY ANALYSIS",[
 (None,"Fully open-source stack; runs on one laptop via docker compose up — ₹0 cost."),
 (None,"Prototype uses simulated CAN (vcan0) — no hardware needed to demonstrate."),
 (None,"Deploys to low-cost edge (Raspberry Pi 4 / Jetson Nano, ≈₹4–12k)."),
 (None,"Method benchmarked on NASA C-MAPSS — the public turbofan run-to-failure dataset the RUL literature reports on."),
 (None,"Validated across mission envelopes: high-altitude, endurance, hot-weather, rapid-throttle."),
], L1, bpt=10.5, hpt=12.5)
card(s,x0+cw+g,y0,cw,ch,"POTENTIAL CHALLENGES & RISKS",[
 (None,"Limited real run-to-failure engine data."),
 (None,"Real-time inference on constrained edge hardware."),
 (None,"Model trust / assurance for defence deployment."),
 (None,"Integration with legacy GCS and ECU/FADEC."),
 (None,"Sensor noise, drift and comms dropouts in flight."),
], AMBER, bpt=10.5, hpt=12.5)
card(s,x0+2*(cw+g),y0,cw,ch,"STRATEGIES TO OVERCOME",[
 (None,"Physics-based synthetic run-to-failure + NASA C-MAPSS transfer learning + real NASA/CWRU bearing data; validate on held-out engines (non-circular)."),
 (None,"INT8 TFLite quantization, pruning & knowledge distillation; rule path <50 ms onboard."),
 (None,"Physics-informed constraints + SHAP explainability + human-in-loop + graceful fallback to rules."),
 (None,"Protocol adapters (ARINC 429 / 1553B → CAN), OpenAPI; pilot before fleet."),
], ACC, bpt=10.0, hpt=12.5)

# ================= SLIDE 5 : IMPACT AND BENEFITS =================
s=prs.slides[4]
card(s,0.40,1.45,6.15,5.0,"POTENTIAL IMPACT ON TARGET AUDIENCE",[
 ("UAV operators","fewer in-flight engine failures → mission success & safe recovery."),
 ("Propulsion engineers","physics + AI insight into degradation & performance."),
 ("Maintenance teams","predictive, condition-based maintenance; less downtime; optimized TBO."),
 ("Mission commanders","fleet-level health & go/no-go readiness for planning."),
 ("Nation / DRDO","indigenous, self-reliant HUMS capability for MALE UAV propulsion."),
], L2, bpt=11.0, hpt=13.0)
card(s,6.78,1.45,6.15,5.0,"BENEFITS",[
 ("Social / Strategic","mission reliability & crew-recovery safety; data sovereignty; secure telemetry; Atmanirbhar defence tech."),
 ("Economic","₹0 software licensing; prevents ₹50+ cr asset loss; lower maintenance cost; spare-parts forecasting."),
 ("Environmental","optimized fuel burn (BSFC) & fewer emissions; fewer catastrophic failures; less waste from unplanned part changes."),
 ("Operational","predict-before-failure; engine efficiency trend reporting; mission replay; 99.5%+ availability target."),
], L1, bpt=11.0, hpt=13.0)

# ================= SLIDE 6 : RESEARCH AND REFERENCES =================
s=prs.slides[5]
card(s,0.40,1.45,6.15,5.0,"DATASETS & DOMAIN",[
 (None,"DRDO Technology Development Fund (TDF) RFP — Digital Twin Framework for Aero Engine HUMS, 2025."),
 (None,"NASA C-MAPSS Turbofan Run-to-Failure dataset — NASA PCoE Prognostics Repository."),
 (None,"NASA IMS & Case Western (CWRU) Bearing datasets — real vibration fault signatures."),
 (None,"Rotax 915 iS / 916 iS Operator's Manual — flyrotax.com (FADEC fuel-injected specs)."),
 (None,"STANAG 4586 (UAV / GCS interoperability); NIST SP 800-171 (CUI protection)."),
], ACC, bpt=11.0, hpt=13.0)
card(s,6.78,1.45,6.15,5.0,"TOOLS, METHODS & LINKS",[
 (None,"A. Saxena et al., “Damage Propagation Modeling for Aircraft Engine RUL (C-MAPSS)”, IEEE PHM, 2008."),
 (None,"M. Raissi, P. Perdikaris, G. Karniadakis, “Physics-Informed Neural Networks”, J. Comp. Physics, 2019."),
 (None,"E. Hendricks & S. Sorenson, “Mean Value Modelling of SI Engines”, SAE."),
 (None,"Open-source: Cantera · PyOD · SHAP · Flower · Eclipse Ditto · Grafana · FastAPI."),
 ("Prototype","functional demonstrator on simulated CAN (vcan0);  Demo & video: <add links before submission>."),
], L3, bpt=10.5, hpt=13.0)

# ================= delete instruction slide 7 =================
xs=prs.slides._sldIdLst; xs.remove(list(xs)[6])
try:
    prs.save(OUT)
except PermissionError:
    OUT="SIH_26054_Idea_Presentation_v2.pptx"; prs.save(OUT); print("NOTE: original locked (open in PowerPoint) — saved as",OUT)
print("Saved",OUT,"| slides:",len(list(prs.slides)))
