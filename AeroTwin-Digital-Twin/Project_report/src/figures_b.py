"""Chapter 3 and 4 diagrams, part B: use case, sequence, state, security, ER,
file structure, SDLC model and the per-tick data-flow interaction diagram."""
from __future__ import annotations

from svgkit import AMBER, BLUE, DARK, GREEN, GREY, INK, Svg


# ---------------------------------------------------------------------------
def use_case() -> Svg:
    s = Svg(760, 740)
    s.rect(160, 12, 440, 690, fill="#fbfbfb", rx=8)
    s.text(380, 36, "AeroTwin Ground Control Station", size=14.5, bold=True)
    L, R, rx = 266, 494, 96
    left = [(80, ["Plan mission"]), (138, ["Allot aircraft and", "operator"]),
            (196, ["View predicted", "mission success"]), (254, ["Cancel mission"]),
            (330, ["Prepare aircraft,", "run checklist"]), (388, ["Start engine", "and launch"]),
            (446, ["Recall (RTB)", "or abort"]), (504, ["Monitor live", "engine health"]),
            (562, ["Debrief and", "report snags"]), (652, ["Log in /", "change password"])]
    right = [(80, ["Inspect and", "release aircraft"]), (138, ["Rectify defect"]),
             (196, ["Engine ground run"]), (254, ["Record scheduled", "maintenance"]),
             (330, ["Review twin-raised", "defects"]), (388, ["Defer with an", "hours limit"]),
             (446, ["Set operating", "limitations"]), (504, ["Compare squadron", "engines"]),
             (600, ["Stream engine", "telemetry"])]
    for y, rows in left:
        s.usecase(L, y, rows, rx=rx, ry=26, size=12.5)
    for y, rows in right:
        s.usecase(R, y, rows, rx=rx, ry=26, size=12.5)
    s.actor(70, 92, "Commander")
    s.actor(70, 352, "Operator")
    s.actor(70, 588, "Squadron user")
    s.actor(690, 92, "Maintenance")
    s.actor(690, 352, "Engineer")
    s.actor(690, 548, "Engine /\nFADEC")
    for y, _ in left[:4]:
        s.line(90, 122, L - rx, y)
    for y, _ in left[4:9]:
        s.line(90, 382, L - rx, y)
    s.line(90, 618, L - rx, 652)
    for y, _ in right[:4]:
        s.line(670, 122, R + rx, y)
    for y, _ in right[4:8]:
        s.line(670, 382, R + rx, y)
    s.line(670, 578, R + rx, 600)
    # «extend» and «include»
    s.poly([(L + rx, 138), (L + rx + 12, 138), (L + rx + 12, 196), (L + rx, 196)], head="open", dash="5,4")
    s.els.append(f'<text x="{L + rx + 23}" y="167" font-family="Arial" font-size="11" font-style="italic" '
                 f'text-anchor="middle" transform="rotate(90 {L + rx + 23} 167)">«include»</text>')
    s.poly([(R - rx, 388), (R - rx - 10, 388), (R - rx - 10, 330), (R - rx, 330)], head="open", dash="5,4")
    s.els.append(f'<text x="{R - rx - 22}" y="359" font-family="Arial" font-size="11" font-style="italic" '
                 f'text-anchor="middle" transform="rotate(-90 {R - rx - 22} 359)">«extend»</text>')
    # generalisation of the four roles into the abstract user
    s.poly([(52, 122), (26, 122), (26, 382)], head=None)
    s.poly([(52, 382), (26, 382), (26, 612), (50, 612)], head="tri")
    s.poly([(708, 122), (744, 122), (744, 718), (110, 718), (110, 612), (90, 612)], head="tri")
    s.line(708, 382, 744, 382, head=None)
    return s


# ---------------------------------------------------------------------------
def sequence() -> Svg:
    s = Svg(760, 870)
    xs = {"op": 50, "ui": 172, "api": 300, "ops": 428, "lt": 560, "ai": 690}
    names = {"ui": ":Console", "api": ":TwinAPI", "ops": ":OpsStore", "lt": ":LiveTwin",
             "ai": ":AI Models"}
    s.actor(xs["op"], 8, "Operator", size=13)
    for k, n in names.items():
        s.rect(xs[k] - 58, 26, 116, 40, fill=BLUE, rx=3)
        s.text(xs[k], 51, n, size=13.5, bold=True)
    for k, x in xs.items():
        s.line(x, 112 if k == "op" else 66, x, 855, dash="6,5", sw=1.2)
    def msg(a, b, y, text, *, ret=False, asyn=False):
        x1 = xs[a] + (6 if xs[b] > xs[a] else -6) if a != "op" else xs[a]
        x2 = xs[b] - (6 if xs[b] > xs[a] else -6) if b != "op" else xs[b]
        s.line(x1, y, x2, y, head="open" if (ret or asyn) else "arrow", dash="6,4" if ret else None,
               sw=1.4)
        s.label((x1 + x2) / 2, y - 9, text, size=12)

    msg("op", "ui", 125, "1: prepare aircraft")
    msg("ui", "api", 155, "2: POST /prepare")
    msg("api", "ops", 185, "3: prepare(mid)")
    msg("ops", "api", 214, "PREFLIGHT", ret=True)
    msg("api", "ui", 243, "200 OK", ret=True)
    msg("ui", "op", 272, "4: show checklist", ret=True)
    msg("op", "ui", 306, "5: start engine")
    msg("ui", "api", 336, "6: POST /start")
    msg("api", "ops", 366, "7: start(mid, checklist)")
    msg("api", "lt", 398, "8: begin_profile(phases)")
    # loop fragment
    s.rect(330, 418, 420, 190, fill="none", sw=1.3)
    s.polygon([(330, 418), (470, 418), (470, 432), (460, 442), (330, 442)], fill=GREY, sw=1.2)
    s.text(336, 435, "loop [every 0.5 s tick]", size=12, bold=True, anchor="start")
    s.path(f"M566,460 L610,460 L610,482 L566,482", head="arrow", sw=1.4)
    s.label(616, 466, "9: poll telemetry,", size=12, anchor="start")
    s.label(616, 482, "shadow update", size=12, anchor="start")
    msg("lt", "ai", 505, "10: score(features)")
    msg("ai", "lt", 532, "level, health, RUL", ret=True)
    s.line(554, 580, xs["ui"] + 6, 580, head="open", sw=1.4)
    s.label(360, 572, "11: push TwinState over /ws/state", size=12)
    msg("op", "ui", 640, "12: launch")
    msg("ui", "api", 670, "13: POST /launch")
    msg("api", "lt", 700, "14: launch() [launch checks pass]")
    msg("api", "ops", 732, "15: launch(mid)")
    # alt fragment
    s.rect(20, 752, 730, 98, fill="none", sw=1.3)
    s.polygon([(20, 752), (200, 752), (200, 766), (190, 776), (20, 776)], fill=GREY, sw=1.2)
    s.text(26, 769, "alt [CAUTION or higher]", size=12, bold=True, anchor="start")
    s.line(554, 798, xs["ui"] + 6, 798, head="open", sw=1.4)
    s.label(360, 790, "16: alert banner + master caution", size=12)
    msg("op", "ui", 830, "17: recall (RTB)")
    # activation bars
    for k, y0, y1 in [("ui", 118, 840), ("api", 150, 248), ("api", 330, 405), ("api", 666, 742),
                      ("ops", 180, 218), ("ops", 362, 380), ("ops", 727, 745), ("lt", 392, 850),
                      ("ai", 496, 534)]:
        s.rect(xs[k] - 6, y0, 12, y1 - y0, fill="#fff", sw=1.3)

    return s


# ---------------------------------------------------------------------------
def state_diagram() -> Svg:
    s = Svg(760, 620)
    W, H = 160, 46

    def st(x, y, name, w=W, fill="#fff"):
        s.rect(x, y, w, H, fill=fill, rx=20)
        s.text(x + w / 2, y + H / 2 + 5, name, size=13.5, bold=True)

    st(300, 20, "CANCELLED", fill=GREY)
    st(60, 130, "PLANNED")
    st(300, 130, "APPROVED")
    st(540, 130, "PREFLIGHT")
    st(60, 270, "RTB", fill=BLUE)
    st(300, 270, "AIRBORNE", fill=BLUE)
    st(540, 270, "ENGINE_RUNNING", fill=BLUE)
    st(290, 410, "AWAITING_DEBRIEF", w=180, fill=AMBER)
    st(540, 410, "ABORTING", fill=AMBER)
    st(150, 530, "COMPLETED", fill=GREEN)
    st(450, 530, "ABORTED", fill=GREY)
    s.start_node(28, 153)
    s.line(38, 153, 60, 153, head="arrow")
    s.line(220, 143, 300, 143, head="arrow"); s.text(260, 124, "allot", size=12)
    s.text(260, 110, "approve /", size=12)
    s.line(460, 143, 540, 143, head="arrow"); s.text(500, 135, "prepare", size=12)
    s.line(540, 166, 460, 166, head="arrow"); s.text(500, 186, "hand back", size=12)
    s.line(620, 176, 620, 270, head="arrow")
    s.label(624, 214, "start", size=12, anchor="start")
    s.label(624, 232, "[checklist done]", size=12, anchor="start")
    s.line(540, 293, 460, 293, head="arrow")
    s.text(500, 262, "launch", size=12); s.text(500, 315, "[checks pass]", size=12)
    s.line(300, 293, 220, 293, head="arrow"); s.text(260, 285, "recall", size=12)
    s.line(620, 316, 620, 410, head="arrow"); s.label(626, 366, "abort", size=12, anchor="start")
    s.poly([(140, 316), (140, 433), (290, 433)], head="arrow")
    s.label(140, 372, "engine stopped", size=12)
    s.line(380, 316, 380, 410, head="arrow"); s.label(384, 366, "engine stopped", size=12, anchor="start")
    s.line(540, 433, 470, 433, head="arrow")
    # debrief outcomes
    s.poly([(340, 456), (340, 490), (230, 490), (230, 530)], head="arrow")
    s.text(334, 480, "debrief [accomplished / partial]", size=12, anchor="end")
    s.poly([(420, 456), (420, 500), (530, 500), (530, 530)], head="arrow")
    s.text(535, 495, "debrief [aborted]", size=12, anchor="start")
    # cancel
    s.poly([(140, 130), (140, 43), (300, 43)], head="arrow")
    s.line(380, 130, 380, 66, head="arrow")
    s.poly([(620, 130), (620, 43), (460, 43)], head="arrow")
    s.text(200, 36, "cancel", size=12); s.text(386, 102, "cancel", size=12, anchor="start")
    s.text(560, 36, "cancel", size=12)
    # final states
    s.line(310, 553, 340, 553, head="arrow"); s.end_node(354, 553)
    s.line(610, 553, 640, 553, head="arrow"); s.end_node(654, 553)
    return s


# ---------------------------------------------------------------------------
def security_architecture() -> Svg:
    s = Svg(760, 600)
    s.text(80, 26, "Layer", size=13.5, bold=True)
    s.text(365, 26, "Controls implemented", size=13.5, bold=True)
    s.text(662, 26, "Threat addressed", size=13.5, bold=True)
    rows = [
        ("Client", ["HTTPS / WSS|(TLS)", "No external CDN,|fonts or scripts", "Role-based|menus"],
         "Interception,|third-party scripts"),
        ("API gateway", ["JWT RS256,|algorithm pinned", "Access + refresh|tokens", "Login back-off|+ rate limiter"],
         "Token forgery,|brute force, DoS"),
        ("Application", ["RBAC with|4 roles", "Strict Pydantic|validation", "Must-change|password"],
         "Privilege misuse,|malformed input"),
        ("Data", ["bcrypt password|hashes", "SHA-256 hash-|chained audit log", "Keys kept in|data/keys"],
         "Credential theft,|insider tampering"),
        ("Edge & link", ["CAN identity +|data-type checks", "Dual-lane|voting", "Signed, encrypted|telemetry frames"],
         "Spoofed or|tampered frames"),
        ("Infrastructure", ["Docker,|non-root user", "Pinned dependency|hashes", "Air-gappable,|no cloud calls"],
         "Supply-chain and|host compromise"),
    ]
    y, h, g = 40, 78, 13
    for i, (name, chips, threat) in enumerate(rows):
        yy = y + i * (h + g)
        s.rect(10, yy, 140, h, fill=DARK, rx=6)
        s.text(80, yy + h / 2 + 5, name, size=13.5, bold=True, fill="#fff")
        s.rect(160, yy, 410, h, fill=GREY, rx=6)
        for j, c in enumerate(chips):
            x = 170 + j * 132
            s.rect(x, yy + 10, 124, h - 20, fill=BLUE, rx=8, sw=1.2)
            rr = c.split("|")
            s.lines(x + 62, yy + h / 2 - (len(rr) - 1) * 8 + 5, rr, size=12.5, lh=16)
        s.rect(585, yy, 165, h, fill=AMBER, rx=6)
        tt = threat.split("|")
        s.lines(667, yy + h / 2 - (len(tt) - 1) * 8 + 5, tt, size=12.5, lh=16)
        s.line(570, yy + h / 2, 585, yy + h / 2, sw=1.3)
    return s


# ---------------------------------------------------------------------------
def er_diagram() -> Svg:
    s = Svg(760, 580)
    W = 200

    def ent(x, y, name, rows, note=None):
        h = 26 + len(rows) * 19 + 6
        s.rect(x, y, W, h, fill="#fff")
        s.rect(x, y, W, 26, fill=DARK)
        s.text(x + W / 2, y + 18, name, size=13.5, bold=True, fill="#fff")
        for i, (k, a) in enumerate(rows):
            yy = y + 26 + 19 * (i + 1) - 3
            if k:
                s.text(x + 8, yy, k, size=11, bold=True, anchor="start", fill="#7a1f1f" if k == "PK" else "#1f3a7a")
            s.text(x + 40, yy, a, size=12.5, anchor="start")
        if note:
            s.text(x + W - 6, y + 18, note, size=10.5, italic=True, anchor="end", fill="#dde6f3")
        return h

    ent(10, 15, "ENGINE_CONFIG", [("PK", "engine_key"), ("", "identity"), ("", "geometry"),
                                  ("", "thermodynamics")], note="YAML")
    ent(285, 15, "AIRCRAFT", [("PK", "tail"), ("FK", "engine_key"), ("", "released"),
                              ("FK", "release_by"), ("", "limitations (JSON)"), ("", "last_health (JSON)")])
    ent(560, 15, "FLIGHTS", [("PK", "flight_id"), ("FK", "aircraft_id"), ("", "engine_key"),
                             ("", "flight_hours"), ("", "health_chi"), ("", "events_json")])
    ent(10, 215, "USERS", [("PK", "username"), ("", "role"), ("", "hash (bcrypt)"), ("", "disabled"),
                           ("", "must_change"), ("", "token_epoch")])
    ent(285, 215, "MISSIONS", [("PK", "id"), ("FK", "tail"), ("FK", "operator"), ("FK", "approved_by"),
                               ("", "status"), ("", "engine_hours")])
    ent(560, 215, "OUTBOX", [("PK", "id"), ("UK", "record_uuid"), ("", "kind"), ("", "payload"),
                             ("", "synced")])
    ent(10, 415, "LOGBOOK", [("PK", "id"), ("FK", "tail"), ("FK", "by"), ("", "role"), ("", "kind"),
                             ("", "data (JSON)")])
    ent(285, 415, "DEFECTS", [("PK", "id"), ("FK", "tail"), ("FK", "mission_id"), ("", "severity"),
                              ("", "status"), ("", "raised_by")])

    def rel(pts, text=None, tx=None, ty=None):
        s.poly(pts, head="zmany", tail="one", sw=1.4)
        if text:
            s.label(tx, ty, text, size=11.5)

    rel([(210, 50), (285, 50)], "fits", 247, 44)
    rel([(485, 50), (560, 50)], "flies", 522, 44)
    rel([(385, 159), (385, 215)], "allotted to", 385, 190)
    rel([(210, 240), (285, 240)])
    s.label(260, 228, "commands", size=10)
    rel([(110, 359), (110, 415)], "logs", 110, 390)
    rel([(385, 359), (385, 415)], "raised in", 385, 390)
    rel([(485, 140), (520, 140), (520, 490), (485, 490)], "raised against", 520, 400)
    rel([(285, 120), (233, 120), (233, 470), (210, 470)], "logged for", 233, 400)
    s.poly([(660, 159), (660, 215)], head="zone", tail="one", sw=1.4)
    s.label(660, 190, "serialised to", size=11.5)
    # legend
    s.line(560, 470, 610, 470, head="zmany", tail="one", sw=1.4)
    s.text(618, 474, "one to zero-or-many", size=11.5, anchor="start")
    s.line(560, 500, 610, 500, head="zone", tail="one", sw=1.4)
    s.text(618, 504, "one to zero-or-one", size=11.5, anchor="start")
    s.text(560, 535, "PK primary key · FK foreign key", size=11.5, anchor="start")
    s.text(560, 553, "UK unique key", size=11.5, anchor="start")
    return s


# ---------------------------------------------------------------------------
def file_structure() -> Svg:
    rows = [
        ("AeroTwin/", "project root"),
        ("├── common/", "shared configuration and utilities"),
        ("├── configs/", "thresholds, fleet, CAN database"),
        ("│   └── engines/", "rotax_915is.yaml, _template.yaml"),
        ("├── layer1_edge/", "CAN ingest, validation, edge rules, buffer"),
        ("├── layer2_physics/", "engine model, combustion, degradation"),
        ("├── layer3_ai/", "features, detectors, fusion, health, RUL"),
        ("│   └── fed/", "federated learning (weights only)"),
        ("├── layer4_core/", "twin state, shadow model, LiveTwin, API"),
        ("├── layer5_viz/", "operator console (React + TypeScript)"),
        ("├── fleet_server/", "optional on-premise fleet sync"),
        ("├── data/", "models, ops, history, keys, audit"),
        ("├── scripts/", "training, evaluation, compliance"),
        ("├── tests/", "integration tests"),
        ("├── deploy/", "deployment files"),
        ("├── docs/", "design notes and diagrams"),
        ("├── run.py", "one-command launcher"),
        ("├── pyproject.toml", "package metadata, dependencies"),
        ("└── Dockerfile", "container image definition"),
    ]
    lh = 24
    s = Svg(760, 40 + len(rows) * lh)
    s.rect(6, 6, 748, 28 + len(rows) * lh, fill="#fbfbfb", rx=6)
    for i, (path, note) in enumerate(rows):
        y = 32 + i * lh
        s.text(22, y, path, size=14.5, anchor="start", family="Consolas, 'Courier New', monospace",
               fill=DARK if i else INK)
        s.text(300, y, note, size=13.5, anchor="start", fill="#444")
    return s


# ---------------------------------------------------------------------------
def sdlc_model() -> Svg:
    s = Svg(760, 430)
    s.rect(10, 40, 108, 370, fill=DARK, rx=8)
    s.lines(64, 205, ["Require-", "ments and", "literature", "study"], size=13.5, bold=True, fill="#fff",
            lh=18)
    incs = ["Increment 1: physics engine model and edge layer",
            "Increment 2: AI detection, health indices and RUL",
            "Increment 3: twin core, REST / WebSocket API, security",
            "Increment 4: operator console and squadron operations"]
    phases = ["Design", "Implement", "Test", "Integrate"]
    fills = [BLUE, "#fff", GREEN, AMBER]
    for i, title in enumerate(incs):
        y = 50 + i * 92
        x0 = 145 + i * 38
        s.text(x0, y + 4, title, size=12.5, bold=True, anchor="start")
        for j, ph in enumerate(phases):
            x = x0 + j * 104
            s.rect(x, y + 14, 94, 44, fill=fills[j], rx=6, sw=1.4)
            s.text(x + 47, y + 41, ph, size=13)
            if j < 3:
                s.line(x + 94, y + 36, x + 104, y + 36, head="arrow", sw=1.4)
        s.line(118, y + 36, x0, y + 36, head="arrow", sw=1.3, dash="5,4")
        rx = x0 + 4 * 104
        s.polygon([(rx, y + 24), (rx + 58, y + 24), (rx + 70, y + 36), (rx + 58, y + 48), (rx, y + 48)],
                  fill=GREY, sw=1.3)
        s.text(rx + 32, y + 41, f"Build {i + 1}", size=12, bold=True)
        s.line(rx - 10, y + 36, rx, y + 36, head="arrow", sw=1.3)
    s.text(380, 22, "Each increment adds working, tested functionality to the previous build",
           size=12.5, italic=True, fill="#333")
    return s


# ---------------------------------------------------------------------------
def data_flow_interaction() -> Svg:
    s = Svg(760, 470)
    W, H = 165, 74
    xs = [10, 205, 400, 590]
    ys = [30, 175, 320]

    def b(x, y, title, rows, fill="#fff"):
        s.box(x, y, W, H, title, rows, fill=fill, tsize=13.5, size=12.5, rx=8)

    b(xs[0], ys[0], "CAN frames", ["FADEC lanes A and B"], GREY)
    b(xs[1], ys[0], "CanIngest", ["decode, validate,", "vote lanes"], BLUE)
    b(xs[2], ys[0], "Telemetry", ["validated values", "with value states"])
    b(xs[3], ys[0], "ShadowModel", ["as-new prediction", "at same operating point"], BLUE)
    b(xs[3], ys[1], "ResidualSet", ["measured − as-new"])
    b(xs[2], ys[1], "Feature builder", ["34-column feature", "contract"], BLUE)
    b(xs[1], ys[1], "Tier 2 + Tier 3", ["statistical and", "deep detectors"], BLUE)
    b(xs[0], ys[1], "ScoreFusion", ["fused anomaly level"], BLUE)
    b(xs[0], ys[2], "Health + RUL", ["indices, life left,", "fault namer, OOD"], BLUE)
    b(xs[1], ys[2], "TwinState", ["strict Pydantic", "snapshot"])
    b(xs[2], ys[2], "TwinSynchroniser", ["versioned state,", "history buffer"], BLUE)
    b(xs[3], ys[2], "Operator Console", ["via /ws/state", "WebSocket"], AMBER)
    for i in range(3):
        s.line(xs[i] + W, ys[0] + H / 2, xs[i + 1], ys[0] + H / 2, head="arrow")
        s.line(xs[i + 1], ys[1] + H / 2, xs[i] + W, ys[1] + H / 2, head="arrow")
        s.line(xs[i] + W, ys[2] + H / 2, xs[i + 1], ys[2] + H / 2, head="arrow")
    s.line(xs[3] + W / 2, ys[0] + H, xs[3] + W / 2, ys[1], head="arrow")
    s.line(xs[0] + W / 2, ys[1] + H, xs[0] + W / 2, ys[2], head="arrow")
    s.poly([(xs[2] + W / 2, ys[0] + H), (xs[2] + W / 2, ys[0] + H + 22), (xs[3] + 30, ys[0] + H + 22),
            (xs[3] + 30, ys[1])], head="arrow", dash="6,4")
    s.label(xs[2] + W + 12, ys[0] + H + 18, "measured", size=11.5)
    s.text(380, 440, "One LiveTwin tick covers 0.5 s of engine time; measured compute p50 51 ms, "
           "p95 83 ms (budget 200 ms).", size=12.5, italic=True, fill="#333")
    return s


FIGS = {
    "fig3_9_usecase": use_case,
    "fig3_10_sequence": sequence,
    "fig3_10_1_state": state_diagram,
    "fig3_11_security": security_architecture,
    "fig3_12_er": er_diagram,
    "fig4_1_filestructure": file_structure,
    "fig4_1_1_sdlc": sdlc_model,
    "fig4_2_dataflow": data_flow_interaction,
}
