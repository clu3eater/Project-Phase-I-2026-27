"""Chapter 3 diagrams, part A: architecture, component, deployment, activity, DFD, class."""
from __future__ import annotations

from svgkit import AMBER, BLUE, DARK, GREEN, GREY, INK, Svg


# ---------------------------------------------------------------------------
def system_architecture() -> Svg:
    s = Svg(760, 640)
    bands = [
        ("L5", "Presentation", ["Operator Console|(React + TS)", "Role dashboards|(4 user roles)",
                                "3-D engine view|(fault on the part)", "Reports|(PDF / CSV)"]),
        ("L4", "Twin Core & API", ["REST API +|WebSocket stream", "LiveTwin pipeline|(0.5 s tick)",
                                   "Mission|reliability", "Squadron ops +|security"]),
        ("L3", "AI & Analytics", ["Statistical|ensemble (Tier 2)", "LSTM autoencoder|+ deep head (T3)",
                                  "Score fusion +|fault naming", "Health indices,|RUL, OOD check"]),
        ("L2", "Physics Model", ["Mean-value|engine model", "Combustion|(Cantera)",
                                 "Turbocharger +|thermal model", "Shadow twin|(as-new engine)"]),
        ("L1", "Edge Layer", ["CANaerospace|decoding", "Sensor validation|(5 value states)",
                              "Certified-limit|rule engine", "72-hour|edge buffer"]),
        ("L0", "Engine & Bus", ["Rotax 915 iS|engine", "Dual-lane|FADEC", "9 sensor|channels",
                                "CAN bus (virtual|or SocketCAN)"]),
    ]
    flows = ["twin state (REST / WebSocket)", "anomaly scores, health, RUL",
             "as-new prediction and residuals", "validated telemetry", "CAN frames"]
    top, bh, gap = 12, 78, 26
    for i, (code, name, comps) in enumerate(bands):
        y = top + i * (bh + gap)
        s.rect(10, y, 590, bh, fill=GREY, rx=6)
        s.rect(10, y, 112, bh, fill=DARK, rx=6)
        s.rect(100, y, 22, bh, fill=DARK, stroke="none", sw=0)
        s.text(66, y + bh / 2 - 6, code, size=15, bold=True, fill="#fff")
        s.text(66, y + bh / 2 + 14, name, size=12.5, bold=True, fill="#fff")
        cw, cg, x0 = 111, 8, 130
        for j, c in enumerate(comps):
            x = x0 + j * (cw + cg)
            s.rect(x, y + 9, cw, bh - 18, fill="#fff", rx=5, sw=1.3)
            rows = c.split("|")
            s.lines(x + cw / 2, y + bh / 2 - (len(rows) - 1) * 8 + 4, rows, size=12.5, lh=16)
        if i < len(bands) - 1:
            ay = y + bh
            s.line(365, ay + gap - 2, 365, ay + 2, head="arrow", sw=1.6)
            s.label(372, ay + gap / 2 + 5, flows[i], size=12, anchor="start", bg="#fff")
    # data stores on the right
    stores = [("Squadron, user,|flight databases|(SQLite)", 1), ("Model artifacts|(PyTorch / ONNX)", 2),
              ("Engine configs|(YAML)", 3), ("Edge buffer|(SQLite, 72 h)", 4)]
    for rows, bi in stores:
        y = top + bi * (bh + gap) + 4
        s.cylinder(625, y, 125, bh - 8, rows.split("|"), size=12)
        s.line(600, y + bh / 2 - 4, 625, y + bh / 2 - 4, dash="5,4", sw=1.3)
    s.text(687, 30, "Data stores", size=13.5, bold=True)
    return s


# ---------------------------------------------------------------------------
def component_diagram() -> Svg:
    s = Svg(760, 560)
    # packages
    for x, y, w, h, name in [(8, 30, 196, 520, "Edge Node"), (222, 30, 380, 520, "Twin Server"),
                             (620, 30, 132, 520, "Operator Client")]:
        s.rect(x, y, w, h, fill="#fafafa", rx=4, dash="7,4", sw=1.4)
        s.rect(x, y - 22, len(name) * 8.6 + 20, 22, fill=GREY, sw=1.2)
        s.text(x + 10, y - 6, name, size=13.5, bold=True, anchor="start")
    W, H = 160, 78
    # edge column
    s.component(20, 60, W, H, "CAN Ingest", ["decode + validate"])
    s.component(20, 220, W, H, "Edge Rules", ["certified limits"])
    s.component(20, 380, W, H, "Edge Buffer", ["72 h store-and-forward"])
    # server grid
    cx = [234, 424]
    rows_y = [60, 180, 300, 420]
    s.component(cx[0], rows_y[0], W, H, "Shadow Model", ["as-new physics"])
    s.component(cx[1], rows_y[0], W, H, "AI Detection", ["Tier 2 + Tier 3 + fusion"])
    s.component(cx[0], rows_y[1], W, H, "LiveTwin", ["orchestrator, 0.5 s"])
    s.component(cx[1], rows_y[1], W, H, "Twin API", ["REST + WebSocket"])
    s.component(cx[0], rows_y[2], W, H, "Health & RUL", ["indices, life, OOD"])
    s.component(cx[1], rows_y[2], W, H, "Security & Audit", ["JWT, RBAC, audit log"])
    s.component(cx[0], rows_y[3], W, H, "Mission", ["reliability, Go / No-Go"])
    s.component(cx[1], rows_y[3], W, H, "Squadron Ops", ["missions, defects"])
    # client
    s.component(630, rows_y[1], 114, H, "Console", ["React UI"], size=12, tsize=13.5)
    s.component(630, rows_y[2], 114, H, "3-D View", ["engine model"], size=12, tsize=13.5)

    def mid(x, y, w=W, h=H):
        return x + w / 2, y + h / 2

    # edge links
    s.line(106, 60 + H, 106, 220, head="arrow")
    s.label(106, 182, "frames")
    s.line(106, 220 + H, 106, 380, head="arrow")
    s.label(106, 342, "alerts")
    # CAN ingest -> LiveTwin (ITelemetry, lollipop on the ingest side)
    s.poly([(192, 99), (212, 99), (212, 219), (236, 219)], head="open", dash="6,4")
    s.circle(212, 99, 6, fill="#fff")
    s.label(212, 160, "ITelemetry", size=12)
    # LiveTwin uses
    lx, ly = mid(cx[0], rows_y[1])
    s.line(lx, rows_y[1], lx, rows_y[0] + H, head="open", dash="6,4")
    s.line(lx, rows_y[1] + H, lx, rows_y[2], head="open", dash="6,4")
    gx = cx[0] + W + 15
    s.poly([(cx[0] + W, rows_y[1] + 16), (gx, rows_y[1] + 16), (gx, rows_y[0] + 58),
            (cx[1], rows_y[0] + 58)], head="open", dash="6,4")
    # Twin API -> LiveTwin (ITwinState)
    s.line(cx[1], rows_y[1] + 66, cx[0] + W, rows_y[1] + 66, head="open", dash="6,4")
    s.circle(cx[1] - 6, rows_y[1] + 66, 6, fill="#fff")
    s.label(cx[0] + W + 32, rows_y[1] + H + 18, "ITwinState", size=12)
    # Twin API -> Security, Squadron ops
    ax, _ = mid(cx[1], rows_y[1])
    s.line(ax, rows_y[1] + H, ax, rows_y[2], head="open", dash="6,4")
    s.poly([(cx[1] + W, rows_y[1] + 40), (594, rows_y[1] + 40), (594, rows_y[3] + 40),
            (cx[1] + W, rows_y[3] + 40)], head="open", dash="6,4")
    # Squadron ops -> Mission ; Health -> Mission
    s.line(cx[1], rows_y[3] + 40, cx[0] + W, rows_y[3] + 40, head="open", dash="6,4")
    s.label(cx[0] + W + 32, rows_y[3] + 30, "uses", size=12)
    hx, _ = mid(cx[0], rows_y[2])
    s.line(hx, rows_y[2] + H, hx, rows_y[3], head="open", dash="6,4")
    # Console -> Twin API
    s.line(630, rows_y[1] + 39, cx[1] + W + 12, rows_y[1] + 39, head="open", dash="6,4")
    s.circle(cx[1] + W + 6, rows_y[1] + 39, 6, fill="#fff")
    s.label(687, rows_y[1] - 12, "REST / WS", size=12)
    s.line(687, rows_y[2], 687, rows_y[1] + H, head="open", dash="6,4")
    # legend
    s.line(30, 520, 70, 520, head="open", dash="6,4")
    s.text(78, 524, "dependency (uses)", size=12, anchor="start")
    s.circle(250, 520, 6, fill="#fff")
    s.text(262, 524, "provided interface", size=12, anchor="start")
    return s


# ---------------------------------------------------------------------------
def deployment_diagram() -> Svg:
    s = Svg(760, 500)
    # UAV airframe node containing engine and edge computer
    s.node3d(10, 30, 270, 455, "UAV Airframe (MALE)", d=12)
    s.node3d(30, 80, 228, 130, "Rotax 915 iS engine", d=9, fill="#fff", size=13.5)
    s.text(44, 152, "• dual-lane FADEC (ECU)", size=12.5, anchor="start")
    s.text(44, 172, "• 9 sensor channels", size=12.5, anchor="start")
    s.text(44, 192, "• CAN 2.0B transceiver", size=12.5, anchor="start")
    s.node3d(30, 280, 228, 186, "Edge computer (ARM64 SBC)", d=9, fill="#fff", size=13.5)
    s.rect(44, 330, 200, 124, fill=BLUE, rx=3, sw=1.2)
    s.text(54, 348, "«executionEnvironment» Python 3.12", size=11.5, italic=True, anchor="start")
    for i, a in enumerate(["can_ingest.py", "edge_rules.py", "edge_infer.py (ONNX)",
                           "edge_buffer (SQLite)"]):
        s.rect(54, 358 + i * 23, 180, 19, fill="#fff", sw=1)
        s.text(60, 372 + i * 23, f"«artifact» {a}", size=11.5, anchor="start")
    s.line(144, 210, 144, 280, sw=2)
    s.label(144, 250, "CANaerospace bus", size=12)

    # ground station
    s.node3d(330, 30, 250, 455, "Ground Control Station", d=12)
    s.text(340, 86, "x86-64 workstation, 8 GB RAM", size=12, anchor="start", fill="#333")
    s.rect(346, 100, 218, 238, fill=BLUE, rx=3, sw=1.2)
    s.text(356, 120, "«executionEnvironment»", size=11.5, italic=True, anchor="start")
    s.text(356, 138, "Uvicorn + FastAPI", size=13, bold=True, anchor="start")
    for i, a in enumerate(["twin_api.py (REST + WS)", "live.py (LiveTwin)", "layer2_physics/*",
                           "layer3_ai/* models", "ops.py, security.py", "console dist/ (static)"]):
        s.rect(356, 150 + i * 30, 198, 24, fill="#fff", sw=1)
        s.text(362, 167 + i * 30, f"«artifact» {a}", size=11.5, anchor="start")
    s.rect(346, 350, 218, 120, fill=GREY, rx=3, sw=1.2)
    s.text(356, 370, "«database» local stores", size=11.5, italic=True, anchor="start")
    for i, a in enumerate(["squadron.db, users.db", "flights.db, outbox.db", "audit.jsonl (hash chain)",
                           "data/models (ONNX, .pt)"]):
        s.text(362, 394 + i * 21, a, size=12, anchor="start")

    # client and fleet
    s.node3d(604, 40, 136, 150, "Operator terminal", d=10, size=13)
    s.rect(614, 100, 116, 70, fill=BLUE, rx=3, sw=1.2)
    s.lines(672, 126, ["Web browser", "Operator Console"], size=12.5)
    s.node3d(604, 280, 136, 190, "Fleet server", d=10, size=13)
    s.text(612, 334, "(optional, on-premise)", size=11, anchor="start", fill="#333")
    s.rect(614, 344, 116, 112, fill=GREY, rx=3, sw=1.2)
    s.lines(672, 370, ["Docker", "fleet_server", "PostgreSQL", "station sync"], size=12.5)

    s.line(258, 372, 330, 372, sw=2)
    s.label(294, 356, "MQTT/TLS", size=11.5)
    s.label(294, 392, "datalink", size=11.5)
    s.line(580, 115, 604, 115, sw=2)
    s.label(592, 100, "HTTPS", size=11)
    s.label(592, 132, "WSS", size=11)
    s.line(580, 375, 604, 375, sw=2, dash="6,4")
    s.label(592, 362, "sync", size=11)
    return s


# ---------------------------------------------------------------------------
def activity_diagram() -> Svg:
    s = Svg(760, 900)
    X, W = 290, 300
    def act(y, rows, fill="#fff"):
        h = 26 + 17 * len(rows)
        s.rect(X - W / 2, y, W, h, fill=fill, rx=18)
        s.lines(X, y + h / 2 - (len(rows) - 1) * 8.5 + 5, rows, size=13.5, lh=17)
        return y + h

    s.start_node(X, 24)
    s.line(X, 34, X, 56, head="arrow")
    b1 = act(56, ["Receive CAN frame from a FADEC lane"])
    s.line(X, b1, X, 120, head="arrow")
    s.diamond(X, 160, 270, 76, ["Identifier and data", "type recognised?"])
    s.text(X + 10, 214, "[yes]", size=12.5, anchor="start")
    s.line(X, 198, X, 232, head="arrow")
    # reject branch
    s.line(X + 135, 160, 520, 160, head="arrow")
    s.text(X + 150, 152, "[no]", size=12.5, anchor="start")
    s.rect(520, 135, 220, 50, fill=GREY, rx=18)
    s.lines(630, 156, ["Reject frame and", "count a bus error"], size=13, lh=16)
    s.poly([(630, 135), (630, 82), (X + W / 2, 82)], head="arrow")
    s.label(560, 75, "next frame", size=12)
    b2 = act(232, ["Decode the engineering value"])
    s.line(X, b2, X, 296, head="arrow")
    b3 = act(296, ["Check range, rate of change,", "staleness and frozen value"])
    s.line(X, b3, X, 386, head="arrow")
    s.diamond(X, 424, 270, 76, ["Value plausible?"])
    s.text(X + 10, 478, "[yes]", size=12.5, anchor="start")
    s.line(X, 462, X, 520, head="arrow")
    s.line(X + 135, 424, 520, 424, head="arrow")
    s.text(X + 150, 416, "[no]", size=12.5, anchor="start")
    s.rect(520, 398, 220, 52, fill=GREY, rx=18)
    s.lines(630, 419, ["Mark value SUSPECT,", "STALE or FAILED"], size=13, lh=16)
    s.poly([(630, 450), (630, 500), (X + 20, 500), (X + 20, 520)], head="arrow")
    b4 = act(520, ["Vote the two FADEC lanes", "(agreement check)"])
    s.line(X, b4, X, 600, head="arrow")
    b5 = act(600, ["Evaluate the certified-limit rules"])
    s.line(X, b5, X, 664, head="arrow")
    s.diamond(X, 700, 270, 70, ["Limit exceeded?"])
    s.text(X + 10, 752, "[no]", size=12.5, anchor="start")
    s.line(X, 735, X, 776, head="arrow")
    s.line(X + 135, 700, 520, 700, head="arrow")
    s.text(X + 150, 692, "[yes]", size=12.5, anchor="start")
    s.rect(520, 674, 220, 52, fill=AMBER, rx=18)
    s.lines(630, 695, ["Raise edge alert", "(caution / warning)"], size=13, lh=16)
    s.poly([(630, 726), (630, 762), (X + 20, 762), (X + 20, 776)], head="arrow")
    b6 = act(776, ["Write to the 72-hour edge buffer and", "publish validated telemetry to the twin"],
             fill=BLUE)
    s.line(X, b6, X, b6 + 30, head="arrow")
    s.end_node(X, b6 + 44)
    return s


# ---------------------------------------------------------------------------
def dfd_level1() -> Svg:
    s = Svg(760, 640)

    def entity(x, y, rows, w=130, h=60):
        s.rect(x + 5, y + 5, w, h, fill="#bfbfbf", stroke="none", sw=0)
        s.rect(x, y, w, h, fill=GREY, sw=1.6)
        s.lines(x + w / 2, y + h / 2 - (len(rows) - 1) * 8 + 5, rows, size=13.5, lh=16, bold=True)

    def process(x, y, num, rows, w=150, h=92):
        s.rect(x, y, w, h, fill=BLUE, rx=12)
        s.line(x, y + 24, x + w, y + 24, sw=1.2)
        s.text(x + w / 2, y + 17, num, size=12.5, bold=True)
        s.lines(x + w / 2, y + 24 + (h - 24) / 2 - (len(rows) - 1) * 8 + 5, rows, size=13, lh=16)

    def store(x, y, sid, name, w=170, h=34):
        s.line(x, y, x + w, y, sw=1.6)
        s.line(x, y + h, x + w, y + h, sw=1.6)
        s.line(x, y, x, y + h, sw=1.6)
        s.line(x + 38, y, x + 38, y + h, sw=1.2)
        s.text(x + 19, y + 22, sid, size=12.5, bold=True)
        s.text(x + 46, y + 22, name, size=12.5, anchor="start")

    entity(10, 40, ["Engine &", "FADEC"])
    process(205, 24, "1.0", ["Acquire and", "validate"])
    process(420, 24, "2.0", ["Predict as-new", "(shadow twin)"])
    entity(620, 40, ["Operator"])
    process(420, 220, "3.0", ["Detect anomalies", "and fuse scores"])
    process(205, 220, "4.0", ["Estimate health", "and RUL"])
    process(205, 420, "5.0", ["Assess mission", "reliability"])
    process(420, 420, "6.0", ["Manage squadron", "operations"])
    entity(10, 436, ["Commander"])
    entity(620, 436, ["Maintenance /", "Engineer"])
    store(10, 175, "D1", "Edge buffer", w=160)
    store(420, 345, "D2", "Model artifacts", w=160)
    store(10, 300, "D3", "Flight history", w=160)
    store(420, 585, "D4", "Squadron database", w=200)

    s.line(140, 70, 205, 70, head="arrow"); s.label(172, 62, "frames", size=12)
    s.line(355, 70, 420, 70, head="arrow"); s.label(388, 62, "telemetry", size=12)
    s.line(280, 116, 280, 140, sw=1.6); s.poly([(280, 140), (90, 140), (90, 175)], head="arrow")
    s.label(185, 134, "buffered frames", size=12)
    s.line(495, 116, 495, 220, head="arrow"); s.label(488, 160, "residuals", size=12, anchor="end")
    s.line(470, 345, 470, 312, head="arrow"); s.label(470, 335, "models", size=12)
    s.line(420, 266, 355, 266, head="arrow"); s.label(388, 258, "scores", size=12)
    s.poly([(570, 250), (600, 250), (600, 100), (620, 100)], head="arrow")
    s.label(596, 182, "live state", size=12, anchor="end")
    s.poly([(205, 290), (130, 290), (130, 300)], head="arrow"); s.label(150, 282, "record", size=12)
    s.line(280, 312, 280, 420, head="arrow"); s.label(280, 368, "health, RUL", size=12)
    s.line(205, 466, 140, 466, head="arrow"); s.label(172, 458, "Go/No-Go", size=12)
    s.poly([(75, 436), (75, 400), (480, 400), (480, 420)], head="arrow")
    s.label(330, 394, "mission plan", size=12)
    s.line(420, 486, 355, 486, head="arrow"); s.label(388, 504, "aircraft", size=12)
    s.poly([(690, 105), (690, 392), (550, 392), (550, 420)], head="arrow")
    s.label(690, 300, "commands", size=12)
    s.line(620, 470, 570, 470, head="arrow", tail="arrow"); s.label(596, 458, "defects", size=12)
    s.line(520, 512, 520, 585, head="arrow", tail="arrow"); s.label(520, 552, "records", size=12)
    return s


# ---------------------------------------------------------------------------
def class_diagram() -> Svg:
    s = Svg(760, 760)
    c = s.uml_class
    hL = c(275, 12, 230, "LiveTwin",
           ["- engine_key : str", "- tick_s : float = 0.5", "- shadow : ShadowModel"],
           ["+ start() / stop()", "+ snapshot() : Snapshot", "+ inject(mode, severity)",
            "+ launch() : bool", "+ rtb() : bool"])
    hC = c(10, 12, 225, "CanIngest", ["- channels : dict", "- lanes : (A, B)"],
           ["+ poll() : Telemetry", "+ condemn(name, reason)", "+ raw(name) : float"])
    hT = c(10, 200, 225, "Telemetry", ["+ t_s : float", "+ channels : dict", "+ state : ValueState"],
           ["+ value(name) : float"])
    hS = c(545, 12, 205, "ShadowModel", ["- engine_key : str"],
           ["+ update(tel, dt) : Outputs", "+ reset()"])
    y2 = 300
    h2 = c(275, y2, 230, "Tier2Ensemble", ["- cblof : CBLOF", "- profile : MatrixProfile"],
           ["+ fit(x_healthy)", "+ score(x) : Tier2Result"])
    h3 = c(545, 170, 205, "Tier3Detector", ["- autoencoder : LstmAutoencoder", "- head : MultiTaskNet"],
           ["+ anomaly_score(x)", "+ predict(x) : dict"])
    hF = c(545, 345, 205, "ScoreFusion", [], ["+ fuse(t2, t3) : FusionResult"])
    hR = c(545, 470, 205, "LstmRulServer", ["- baseline : ResidualBaseline"],
           ["+ observe(values, hours)", "+ available() : bool"])
    hTS = c(10, 345, 225, "TwinState", ["+ reported, simulated", "+ residuals, health", "+ alerts : AlertSummary"],
            ["+ model_dump() : dict"], stereo="Pydantic model")
    yO = 500
    hO = c(10, yO, 240, "OpsStore", ["- db : squadron.db"],
           ["+ create_mission(...)", "+ approve(mid, tail, operator)", "+ prepare() / start()",
            "+ launch() / rtb() / abort()", "+ debrief(mid, outcome)", "+ raise_defect(tail, ...)"])
    hM = c(275, 470, 230, "MissionReliability", [],
           ["+ assess(profile, health)", "  : MissionAssessment", "+ assess_all() : list"])
    hA = c(275, 640, 230, "AuditLog", ["- key : HMAC key"], ["+ record(event, subject)", "+ verify() : dict"])

    # LiveTwin composition (filled diamond at LiveTwin)
    s.poly([(505, 120), (525, 120)], head=None, tail="diamond")
    s.line(525, 60, 525, 510, head=None)
    for yy in (60, 230, 380, 510):
        s.line(525, yy, 545, yy, head=None)
    s.text(531, 113, "parts", size=11.5, anchor="start", italic=True)
    s.poly([(390, 12 + hL), (390, y2)], head=None, tail="diamond")
    # LiveTwin uses CanIngest ; CanIngest creates Telemetry
    s.line(275, 60, 235, 60, head="open", dash="6,4")
    s.label(255, 52, "uses", size=11.5)
    s.line(122, 12 + hC, 122, 200, head="open", dash="6,4")
    s.label(122, 12 + hC + 20, "«create»", size=11.5)
    # LiveTwin produces TwinState
    s.poly([(275, 160), (255, 160), (255, 390), (235, 390)], head="open", dash="6,4")
    s.text(251, 336, "«produce»", size=11.5, anchor="end")
    # OpsStore uses MissionReliability and AuditLog
    s.line(250, 520, 275, 520, head="open", dash="6,4")
    s.poly([(130, yO + hO), (130, 690), (275, 690)], head="open", dash="6,4")
    s.label(200, 683, "records to", size=11.5)
    return s
