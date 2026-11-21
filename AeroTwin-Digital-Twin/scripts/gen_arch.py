# -*- coding: utf-8 -*-
"""Render the corrected, detailed DRDO Digital-Twin architecture as a high-res PNG.
Fixes vs the reference image: engine (FADEC fuel-injected / heavy-fuel target),
lists all 8 fault classes, corrects Tier-2 (PyOD) and typos."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W,H = 2280,1330
img = Image.new("RGB",(W,H),"#FFFFFF")
d = ImageDraw.Draw(img)

AR="C:/Windows/Fonts/arial.ttf"; ARB="C:/Windows/Fonts/arialbd.ttf"; BLK="C:/Windows/Fonts/ariblk.ttf"
def F(p,s): return ImageFont.truetype(p,s)
f_title=F(BLK,34); f_sub=F(AR,19); f_lnum=F(BLK,26); f_lname=F(ARB,17)
f_ctitle=F(ARB,17); f_item=F(AR,14); f_item_s=F(AR,13); f_side_h=F(ARB,16); f_side=F(AR,13); f_leg=F(AR,14); f_small=F(AR,12)

NAVY="#0B1F3A"; INK="#1A2A40"; DIM="#4A5A70"; BORD="#C6D2E0"; WHITE="#FFFFFF"
L5="#0E9E8C"; L4="#4A54C4"; L3="#7A3FB0"; L2="#2C6FD0"; L1="#1E9E4C"; PHY="#55637A"
CRIT="#D93A3A"; AMBER="#E39A1E"; VIOLET="#7A3FB0"
def tint(hexc,f):
    c=tuple(int(hexc[i:i+2],16) for i in (1,3,5)); return tuple(int(x+(255-x)*f) for x in c)

def rrect(x,y,w,h,fill,outline=None,ow=1,rad=10):
    d.rounded_rectangle([x,y,x+w,y+h],radius=rad,fill=fill,outline=outline,width=ow)
def text(x,y,s,font,fill,anchor="la"): d.text((x,y),s,font=font,fill=fill,anchor=anchor)
def wrap(s,font,maxw):
    words=s.split(); lines=[]; cur=""
    for w0 in words:
        t=(cur+" "+w0).strip()
        if d.textlength(t,font=font)<=maxw: cur=t
        else:
            if cur: lines.append(cur)
            cur=w0
    if cur: lines.append(cur)
    return lines

def card(x,y,w,h,title,items,color,two_col=False,item_font=f_item):
    rrect(x,y,w,h,WHITE,tint(color,0.35),2,12)
    d.rounded_rectangle([x,y,x+w,y+6],radius=3,fill=color)
    text(x+w/2,y+20,title,f_ctitle,color,anchor="ma")
    ty=y+42
    if two_col:
        col_w=(w-24)/2
        half=(len(items)+1)//2
        for ci,chunk in enumerate((items[:half],items[half:])):
            cx=x+12+ci*col_w; yy=ty
            for it in chunk:
                for ln in wrap(it,item_font,col_w-6):
                    text(cx,yy,ln,item_font,DIM); yy+=17
    else:
        for it in items:
            for ln in wrap(it,item_font,w-24):
                text(x+13,ty,"• "+ln if not ln.startswith(("1","2","3","4","5","6","7","8","-")) else ln,item_font,DIM); ty+=18

# ---------------- header ----------------
d.rectangle([0,0,W,92],fill=NAVY)
text(W/2,20,"AI-Enabled Real-Time Digital Twin  —  SIH 2026 / DRDO IDEX  PS-26054",f_title,"#FFFFFF",anchor="ma")
text(W/2,64,"TAPAS-BH-201 MALE UAV   ·   FADEC Fuel-Injected Aero-Piston (Rotax 916 iS class · Heavy-Fuel Jet-A1 target)   ·   5-Layer MOSA Stack",f_sub,"#BFE3DE",anchor="ma")
text(30,26,"DRDO",F(BLK,26),"#FFFFFF"); text(30,58,"IDEX",F(ARB,18),"#8FB7E0")

# ---------------- sidebars ----------------
SB_TOP=108; SB_BOT=1150
# GCS left
rrect(20,SB_TOP,232,SB_BOT-SB_TOP,tint(PHY,0.9),tint(PHY,0.5),2,12)
rrect(20,SB_TOP,232,54,PHY,None,0,12)
text(136,SB_TOP+14,"GROUND CONTROL",f_side_h,"#FFFFFF",anchor="ma"); text(136,SB_TOP+32,"STATION (GCS)",f_side_h,"#FFFFFF",anchor="ma")
for i,t in enumerate(["Mission Planning","Fleet Monitoring","Command & Control","Data Ingestion","Alert Management","Twin Registry"]):
    yy=SB_TOP+80+i*70
    rrect(36,yy,200,52,WHITE,tint(PHY,0.5),1,9)
    d.ellipse([50,yy+20,64,yy+34],fill=PHY)
    for j,ln in enumerate(wrap(t,f_side,150)): text(78,yy+14+j*16,ln,f_side,INK)
# Security right
SX=2028
rrect(SX,SB_TOP,232,SB_BOT-SB_TOP,tint(CRIT,0.92),tint(CRIT,0.45),2,12)
rrect(SX,SB_TOP,232,54,"#5A2A3A",None,0,12)
text(SX+116,SB_TOP+14,"SECURITY &",f_side_h,"#FFFFFF",anchor="ma"); text(SX+116,SB_TOP+32,"COMPLIANCE",f_side_h,"#FFFFFF",anchor="ma")
sec=[("Network Segmentation","UAV↔DMZ↔LAN↔Mgmt"),("TLS 1.3 · AES-256-GCM","at rest & in-transit"),("JWT RBAC + MFA","role-based access"),
     ("Audit Logging","all state · actions · alerts"),("Differential Privacy","federated (protected)"),("Zero Trust","verify · least privilege")]
for i,(t,s) in enumerate(sec):
    yy=SB_TOP+80+i*116
    rrect(SX+12,yy,208,100,WHITE,tint(CRIT,0.5),1,9)
    d.ellipse([SX+26,yy+16,SX+42,yy+32],fill="#5A2A3A")
    for j,ln in enumerate(wrap(t,f_side_h,150)): text(SX+52,yy+14+j*17,ln,f_side_h,INK)
    yy2=yy+52
    for ln in wrap(s,f_small,180): text(SX+26,yy2,ln,f_small,DIM); yy2+=16

# ---------------- center layers ----------------
CX=268; CW=SX-16-CX   # center width
def layer(y,h,num,name,color,cards):
    # label box
    rrect(CX,y,150,h,color,None,0,12)
    text(CX+75,y+16,"LAYER",F(ARB,14),"#FFFFFF",anchor="ma")
    text(CX+75,y+30,num,f_lnum,"#FFFFFF",anchor="ma")
    yy=y+72
    for ln in wrap(name,f_lname,132): text(CX+75,yy,ln,f_lname,"#EAF6F3",anchor="ma"); yy+=18
    # cards
    ax=CX+164; aw=CX+CW-ax; n=len(cards); g=12
    cwid=(aw-(n-1)*g)/n
    for i,(ct,items,twocol) in enumerate(cards):
        card(ax+i*(cwid+g),y+6,cwid,h-12,ct,items,color,two_col=twocol,
             item_font=f_item_s if (len(items)>4 or twocol) else f_item)

y=108
layer(y,150,"5","VISUALIZATION & HMI",L5,[
 ("Grafana Dashboard (10-Panel)",["RPM · CHT · EGT · Oil P/T","Fuel · Vibration · Battery","Injector Duty · Health Index","Live Trends · Tables · Maps"],False),
 ("Alert & Notification (5-Level)",["Green — Advisory","Blue — Watch","Yellow — Warning","Orange — Major","Red — Critical"],False),
 ("Streamlit HMI (Python)",["Real-time overview","Health metrics","Twin state view","Reports & exports"],False),
 ("Simulation & Replay",["Mission profiles","High-Alt·Endurance·Hot·Throttle","What-If scenarios","Historical mission replay"],False),
])
y=266
layer(y,150,"4","DIGITAL TWIN CORE & STATE",L4,[
 ("MQTT Broker (Mosquitto)",["Topic hierarchy","QoS 1/2 · Retained","Last-Will · Alerts"],False),
 ("Twin State Engine (Ditto)",["Reported (real-time)","Desired (operator)","Predicted (AI)","Simulated (physics)"],False),
 ("REST API + RBAC",["JWT auth · RBAC ×4","Rate limiting","Versioned APIs","Audit trails"],False),
 ("Data Stores",["InfluxDB — time-series (2 yr)","PostgreSQL — registry","Config · users · logs","Maintenance history"],False),
])
y=424
layer(y,206,"3","AI/ML PREDICTIVE ANALYTICS",L3,[
 ("Three-Tier Anomaly Detection",["T1 Rule-based (>200 rules, <5ms)","T2 Statistical — PyOD","    (Isolation Forest · CBLOF)","T3 Deep — LSTM Autoencoder","Fused score · 5 alert levels"],False),
 ("8 Fault Classes Detected",["1 Misfire","2 Injector Abnorm.","3 Cooling Degrad.","4 Lubrication","5 Sensor Drift","6 Combustion Inst.","7 Overheating","8 Abnormal Vibr."],True),
 ("RUL + PINN + Trend",["LSTM + Physics fusion","RUL with ±confidence","Trend analysis (degrade-rate)","PINN physics-informed net"],False),
 ("Explainable AI (XAI)",["SHAP summary plots","LIME local surrogate","Top contributing factors","Natural-language advisory"],False),
 ("Advisory · FL · Health Index",["Maintenance action library","Autonomous scheduler","Federated Learning + DP","Composite Health Index (CHI)"],False),
])
y=642
layer(y,168,"2","PHYSICS-BASED ENGINE MODEL",L2,[
 ("Environmental Simulation",["ISA atmosphere","Temp · Pressure · Humidity","Wind · Altitude","Mission profiles"],False),
 ("Cantera Combustion",["Detailed chemistry","Species transport","Equilibrium composition","Ignition & flame"],False),
 ("0-D Mean-Value Model (MVEM)",["Mass & energy balance","Manifold pressures","Heat transfer","Volumetric efficiency"],False),
 ("Performance Maps + Degrad.",["BMEP · BSFC · EGT maps","6 degradation factors","Health params","Trend generation"],False),
 ("Synthetic Fault Injection",["8 fault classes","Severity levels","Run-to-failure","Labeled datasets"],False),
])
y=822
layer(y,158,"1","DATA ACQUISITION & EDGE",L1,[
 ("CAN & Connectivity",["SocketCAN · python-can","CAN 2.0B / CAN FD","J1939 / DBC","MAVLink bridge"],False),
 ("Sensor Fusion & DSP",["3-level Kalman filter","Outlier removal (Hampel)","Resampling & sync","Time alignment"],False),
 ("9 Onboard Sensors (1–100 Hz)",["RPM 100 · CHT 10 · EGT 10","OilP 10 · OilT 1 · Fuel 10","Vibration 10 · Battery 10","Injection timing 100"],False),
 ("Edge AI Inference (TFLite)",["INT8 quantized model","<50 ms critical latency","<2.5 MB · <512 MB RAM","RPi 4 / Jetson Nano"],False),
 ("Edge Data Buffer",["72-hour local buffer","Store & forward","Compressed retention","Offline autonomy"],False),
])

# ---------------- physical fleet ----------------
py=990
rrect(20,py,232,158,tint(PHY,0.9),tint(PHY,0.5),2,12)
text(136,py+16,"PHYSICAL ENGINE",f_side_h,INK,anchor="ma"); text(136,py+36,"& UAV FLEET",f_side_h,INK,anchor="ma")
# ECU card
rrect(CX,py,300,158,WHITE,tint(PHY,0.5),2,12)
d.rounded_rectangle([CX,py,CX+300,py+6],radius=3,fill=PHY)
text(CX+150,py+18,"Engine ECU / FADEC",f_ctitle,PHY,anchor="ma")
for i,t in enumerate(["CAN 2.0B + ARINC 429","FADEC fuel scheduling","Injection timing control","Wastegate + knock detection","Heavy-fuel (Jet-A1) capable"]):
    text(CX+16,py+44+i*21,"• "+t,f_item,DIM)
# 4 drones
dx0=CX+320; dwid=(CX+CW-dx0-0)/4
for i in range(4):
    x=dx0+i*dwid
    rrect(x+6,py,dwid-12,158,WHITE,tint(L1,0.5),2,12)
    d.rounded_rectangle([x+6,py,x+dwid-6,py+6],radius=3,fill=L1)
    # simple UAV glyph
    cxg=x+dwid/2; cyg=py+40
    d.polygon([(cxg,cyg-18),(cxg+7,cyg-2),(cxg+7,cyg+14),(cxg,cyg+8),(cxg-7,cyg+14),(cxg-7,cyg-2)],fill=L1)
    d.line([(x+22,cyg+2),(x+dwid-22,cyg+2)],fill=L1,width=4)  # wings
    text(cxg,py+62,f"UAV-ENG-00{i+1}",f_ctitle,INK,anchor="ma")
    for j,t in enumerate(["RPi 4 / Jetson Nano","Edge AI · 72 h buffer","MQTT uplink (TLS)"]):
        text(x+18,py+84+j*18,"• "+t,f_small,DIM)
    text(cxg,py+142,f"TAPAS-BH-201-AFE{i+1}",f_small,L1,anchor="ma")

# ---------------- data-flow legend ----------------
ly=1168
rrect(20,ly,W-40,60,tint(NAVY,0.94),tint(NAVY,0.6),1,10)
text(40,ly+20,"DATA FLOW",f_side_h,NAVY)
legs=[("Sensor Data (Edge→Core)",L1),("Command / Control (GCS→Core)",L2),("Analytics / Insights (AI→HMI)",VIOLET),("Alerts / Notifications (Core→GCS)",AMBER),("Model Updates (FL)",PHY)]
lx=180
for t,c in legs:
    d.line([(lx,ly+30),(lx+46,ly+30)],fill=c,width=4)
    d.polygon([(lx+46,ly+25),(lx+58,ly+30),(lx+46,ly+35)],fill=c)
    text(lx+66,ly+22,t,f_leg,INK); lx+=66+d.textlength(t,font=f_leg)+56

# footnote
text(40,ly+72,"Full architecture = production target.  Demo prototype: SQLite + FastAPI twin stub + simulated CAN (python-can vcan0).  Engine-agnostic: add engine = YAML config.",f_small,DIM)

# Written into docs/diagrams rather than the working directory. A generator
# that drops its output wherever it happened to be run is how the repository
# root filled up in the first place.
_OUT = Path(__file__).resolve().parent.parent / "docs" / "diagrams"
_OUT.mkdir(parents=True, exist_ok=True)
img.save(_OUT / "architecture_diagram.png")
print("saved", _OUT / "architecture_diagram.png", img.size)
