# -*- coding: utf-8 -*-
"""Post-flight report as a filed document -- problem statement section F.

"Mission-wise health reports" is the fifth dashboard item. A report that exists
only on a screen is not one a maintenance organisation can use: the artefact
that matters is the one that leaves the ground station, gets filed against the
airframe, and is read months later by somebody deciding whether an engine may
fly.

WHAT THIS DOCUMENT IS BUILT FROM
--------------------------------
Fifteen sections, one page each, assembled from the standards a defence
maintenance organisation would expect rather than invented:

  ADS-79E-HDBK   US Army condition-based maintenance, and the only one of these
                 that explicitly covers UNMANNED aircraft. Supplies regime
                 recognition (s02) and exceedance processing (s05).
  CAP 739        UK CAA flight data monitoring. Supplies severity grading 1/2/3
                 and the rule that limits belong to a flight PHASE, not to the
                 whole sortie.
  Airbus PFR     Each warning with "the associated time, flight phase and ATA
                 reference" (s06). "EGT high" tells a maintainer nothing; "EGT
                 high, 04:12, CLIMB, ATA 77" tells them which page to open.
  ECTM / GPA     One stabilised reading per flight, corrected to standard day,
                 tracked against a post-overhaul baseline (s07, s08).
  FRACAS         A finding is not closed until somebody signs for it (s15).

THREE SECTIONS EARN THEIR PLACE BY BEING UNCOMFORTABLE
-------------------------------------------------------
  s04  DIGITAL TWIN VERSUS ACTUAL. The premise of this whole project is a
       "continuously synchronized virtual representation". A post-flight report
       from a digital twin that never shows twin against actual has omitted its
       own headline claim.

  s13  DATA QUALITY AND COVERAGE. A report silent about a dead channel reads as
       a clean bill of health. This section states coverage, gaps and dead
       sensors whether or not anything went wrong, and s10 refuses to assess a
       fault whose channel is listed here.

  s11  Both the RUL hours AND the calibrated failure probability, with the
       probability marked as the more reliable of the two. The hours figure is
       near its measured ceiling; the probability is not, and a dispatcher
       should be able to see which is which.

REVERSAL OF AN EARLIER DECISION
-------------------------------
The previous version of this module said, in as many words, that it would carry
no charts: "a trend rendered small enough to sit beside a table cannot be read
to a precision that would change a decision". That was right about a trend
squeezed beside a table and wrong about ECTM, which is not a reading but a
SLOPE -- the number next to it cannot show that oil pressure has been falling
for twenty flights. Charts are drawn where the shape IS the finding (s02, s03,
s04, s08, s11) and nowhere else; every one of them still prints the figure it
depicts.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
from pathlib import Path
from typing import Any

# The dependency is optional -- declared in the `reports` extra -- so the API
# degrades to "PDF export unavailable" rather than failing to import.
try:
    from reportlab.graphics.charts.lineplots import LinePlot
    # The ring in s09 is drawn from Wedge rather than from a chart class:
    # Doughnut has moved package between reportlab releases, and a health
    # index is one arc -- not worth a version-dependent import.
    from reportlab.graphics.shapes import (
        Circle,
        Drawing,
        Line,
        Polygon,
        Rect,
        String,
        Wedge,
    )
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        BaseDocTemplate,
        Frame,
        Image,
        NextPageTemplate,
        PageBreak,
        PageTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
    )

    AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without the extra
    AVAILABLE = False


UNAVAILABLE_MESSAGE = (
    "PDF export requires the 'reports' extra: pip install -e '.[reports]'"
)

TOTAL_PAGES = 16

# Shipped cover artwork. It already contains the DRDO mark, the tricolour and
# both straplines, so the cover flowables must not draw those a second time.
# JPEG, not PNG. The artwork is a photograph, and this report is filed once
# per sortie: the PNG put 1.7 MB into every copy, where quality-90 JPEG puts
# 250 KB and is visually identical at the 128 DPI the artwork is authored at.
COVER_BG = str(Path(__file__).resolve().parent.parent / "assets"
               / "report_cover_bg.jpg")

ORG_MARK = "DRDO"
DEFAULT_CLASSIFICATION = "Restricted (Government Use Only)"

# Measured from the artwork's own luminance: everything between these two
# fractions of page height is clear sky and safe for dark text.
COVER_TEXT_TOP = 0.17
COVER_TEXT_BOTTOM = 0.56
DOC_TITLE = "POST-FLIGHT ENGINE HEALTH REPORT"
STRAPLINE = "SCIENCE FOR A SAFER TOMORROW"

# Print colours, not console colours. The console palette is tuned for an
# emissive panel in a darkened GCS; on white paper those same hues wash out and
# amber in particular becomes illegible.
if AVAILABLE:
    _INK = colors.HexColor("#101820")
    _DIM = colors.HexColor("#5a6572")
    _FAINT = colors.HexColor("#8c95a1")
    _RULE = colors.HexColor("#c2cad4")
    _HAIR = colors.HexColor("#dfe3e9")
    _BAND = colors.HexColor("#eef1f5")
    _HEAD = colors.HexColor("#3d4753")
    # One accent, used for the section rule, the primary chart trace and
    # nothing else. A document that highlights everything highlights nothing.
    _RED = colors.HexColor("#c8102e")
    _accent_colour = colors.HexColor("#4a5563")
    _WARN = colors.HexColor("#b3261e")
    _CAUT = colors.HexColor("#8a5a00")
    _FILL_CAUT = colors.HexColor("#e2a53f")
    _FILL_WARN = colors.HexColor("#cf4436")
    _FILL_OK = colors.HexColor("#2f9463")
    _OK = colors.HexColor("#1f6b45")
    _PALE_W = colors.HexColor("#fbeae8")
    _PALE_O = colors.HexColor("#e8f3ec")

# Eight fault types, in the order the problem statement lists them in
# section C. Kept as a constant so a report can state "not detected" for a
# fault the engine never showed -- an absent row and a negative row mean
# different things to a maintainer.
PS_FAULTS = (
    ("misfire", "Misfire"),
    ("injector_abnormal", "Injector abnormality"),
    ("cooling_degradation", "Cooling degradation"),
    ("lubrication_issue", "Lubrication issue"),
    ("sensor_drift", "Sensor drift or failure"),
    ("combustion_instability", "Combustion instability"),
    ("overheating_trend", "Overheating trend"),
    ("abnormal_vibration", "Abnormal vibration"),
)

# Which recorded channel each fault is judged from. When that channel appears
# in the data-quality section as invalid, section 10 reports NOT ASSESSABLE
# rather than "not detected" -- the difference between looking and not finding,
# and not being able to look.
FAULT_CHANNEL = {
    "abnormal_vibration": "vibration_rms_total",
    "misfire": "egt_spread",
    "overheating_trend": "cht_max",
    "lubrication_issue": "oil_pressure",
}

# The health block names its indices in the engineer's shorthand. On a
# maintenance record read by a technician on the ramp, "Esf" is not a
# subsystem -- it is a typo waiting to be reported as one.
SUBSYSTEM_NAMES = {
    "chi": "Composite health",
    "thi": "Thermal", "mhi": "Mechanical", "ehi": "Electrical",
    "lhi": "Lubrication", "oti": "Oil temperature", "fshi": "Fuel system",
    "rsi": "RPM stability", "comb_hi": "Combustion",
    "thermal": "Thermal", "mechanical": "Mechanical",
    "electrical": "Electrical", "combustion": "Combustion",
    "cooling": "Cooling", "lubrication": "Lubrication",
    "turbocharger": "Turbocharger", "ignition": "Ignition",
    "fuel_delivery": "Fuel delivery",
}


# How the composite is built: four subsystems, each the MINIMUM of the indices
# listed under it (layer3_ai/health.py, HealthEstimator.update). Section 9.2 is
# drawn from this, so a subsystem and the index it is made of are never printed
# as two unrelated rows.
HEALTH_TREE = (
    ("thermal", "Thermal", (("thi", "Cylinder head temperature"),
                            ("oti", "Oil temperature"))),
    ("mechanical", "Mechanical", (("mhi", "Vibration"),
                                  ("lhi", "Lubrication (oil pressure)"),
                                  ("rsi", "RPM stability"))),
    ("electrical", "Electrical (battery and alternator)", ()),
    ("combustion", "Combustion", (("comb_hi", "Exhaust gas temperature spread"),
                                  ("fshi", "Fuel system"),
                                  ("csi", "Cylinder head temperature spread"))),
)
# Carried in the health block but not 0-1 health scores, so never tabulated.
# `eef` is the EGT efficiency factor, a signed fraction: printed as an index it
# read "-0.01 CRITICAL" on a healthy engine.
_NOT_AN_INDEX = {"chi", "chi_raw", "band", "action", "eef", "used_residuals"}
# A subsystem's index under its short name, where the subsystem has no other
# contributing index: "ehi" IS the electrical subsystem.
_SAME_AS = {"ehi": "electrical"}


HEALTH_BANDS = (
    (0.90, "EXCELLENT", "No action required"),
    (0.80, "GOOD", "No action required"),
    (0.70, "FAIR", "Monitor"),
    (0.60, "POOR", "Service within 25 flight hours"),
    (0.50, "DEGRADED", "Service within 10 flight hours"),
    (0.00, "CRITICAL", "DO NOT FLY"),
)


def band_for(chi: float | None) -> tuple[str, str]:
    if chi is None:
        return ("---", "no health estimate")
    for floor, label, action in HEALTH_BANDS:
        if chi >= floor:
            return (label, action)
    return ("CRITICAL", "DO NOT FLY")


# ---------------------------------------------------------------------------
# Styles and small helpers
# ---------------------------------------------------------------------------
def _styles() -> dict[str, Any]:
    base = getSampleStyleSheet()
    return {
        "cover_title": ParagraphStyle(
            "ct", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=29, leading=32, textColor=_INK, alignment=TA_LEFT,
            spaceAfter=0),
        "cover_sub": ParagraphStyle(
            "cs", parent=base["Normal"], fontSize=11.5, leading=16,
            textColor=_INK, spaceAfter=0),
        "cover_meta": ParagraphStyle(
            "cm", parent=base["Normal"], fontSize=8.6, leading=11,
            textColor=_INK),
        "org": ParagraphStyle(
            "og", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=8.5, leading=11.5, textColor=_INK),
        "org_dim": ParagraphStyle(
            "od", parent=base["Normal"], fontSize=7.5, leading=10,
            textColor=_DIM),
        "sec_no": ParagraphStyle(
            "sn", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=32, leading=34, textColor=_INK),
        "sec_title": ParagraphStyle(
            "st", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=15, leading=18, textColor=_INK),
        "h3": ParagraphStyle(
            "h3", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=9.5, leading=13, textColor=_INK,
            spaceBefore=10, spaceAfter=4),
        "body": ParagraphStyle(
            "b", parent=base["Normal"], fontSize=9, leading=12.5,
            textColor=_INK),
        "note": ParagraphStyle(
            "n", parent=base["Normal"], fontSize=8, leading=11,
            textColor=_DIM),
        "big": ParagraphStyle(
            "bg", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=22, leading=25, textColor=_INK),
        "warn": ParagraphStyle(
            "w", parent=base["Normal"], fontSize=9, leading=12.5,
            textColor=_WARN),
        "ok": ParagraphStyle(
            "o", parent=base["Normal"], fontSize=9, leading=12.5,
            textColor=_OK),
        "cell": ParagraphStyle(
            "cl", parent=base["Normal"], fontSize=7.8, leading=10,
            textColor=_INK),
    }


def _num(v: Any, digits: int = 1, unit: str = "") -> str:
    """A number, or the console's own notation for one that is not there.

    PRD Part 4 s7.2: a value that failed validation is never rendered as a
    number and never as the last good reading. The document keeps the same
    convention as the screen, so the two cannot be read differently.
    """
    if v is None:
        return "---"
    try:
        s = f"{float(v):,.{digits}f}"
    except (TypeError, ValueError):
        return str(v)
    return f"{s} {unit}".strip()


def _clock(t_s: Any) -> str:
    """Seconds since engine start as hh:mm:ss.

    A debrief is conducted against the flight's own clock. "t+14712 s" is a
    number nobody can place in a sortie.
    """
    try:
        n = int(float(t_s))
    except (TypeError, ValueError):
        return "---"
    return f"{n // 3600:02d}:{(n % 3600) // 60:02d}:{n % 60:02d}"


def _dur(sec: Any) -> str:
    """A duration a human reads, not a count of seconds."""
    try:
        n = int(float(sec))
    except (TypeError, ValueError):
        return "---"
    if n < 120:
        return f"{n} s"
    if n < 3600:
        return f"{n // 60} min {n % 60:02d} s"
    return f"{n // 3600} h {(n % 3600) // 60:02d} min"


def digest(report: dict) -> str:
    """SHA-256 over the report data, for matching a printout to the log.

    Deliberately NOT called a signature. It proves this export and its audit
    entry describe the same data; it proves nothing about who produced either,
    and it does not make two exports taken minutes apart identical.
    """
    payload = json.dumps(report, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _table(rows: list[list[Any]], widths: list[float], *,
           head: bool = True, zebra: bool = False,
           align_right: list[int] | None = None,
           highlight: list[int] | None = None,
           colour_rows: list[tuple[int, Any]] | None = None,
           size: float = 8.0) -> Table:
    t = Table(rows, colWidths=widths, hAlign="LEFT",
              repeatRows=1 if head else 0)
    style = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), size),
        ("TEXTCOLOR", (0, 0), (-1, -1), _INK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5.4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5.4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, _HAIR),
        ("BOX", (0, 0), (-1, -1), 0.4, _RULE),
    ]
    if head:
        style += [
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("BACKGROUND", (0, 0), (-1, 0), _HEAD),
            ("TOPPADDING", (0, 0), (-1, 0), 5),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ]
    if zebra:
        for r in range(1 if head else 0, len(rows)):
            if r % 2 == (1 if head else 0):
                style.append(("BACKGROUND", (0, r), (-1, r),
                              colors.HexColor("#f7f8fa")))
    for c in align_right or []:
        style.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    for r in highlight or []:
        style.append(("FONTNAME", (0, r), (-1, r), "Helvetica-Bold"))
    for r, col in colour_rows or []:
        style.append(("BACKGROUND", (0, r), (-1, r), col))
    t.setStyle(TableStyle(style))
    return t


def _kv(rows: list[tuple[str, Any]], w1: float, w2: float,
        size: float = 8.2) -> Table:
    """A two-column key/value block -- the identity and summary shape."""
    t = Table([[k, v] for k, v in rows], colWidths=[w1, w2], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), size),
        ("TEXTCOLOR", (0, 0), (0, -1), _DIM),
        ("TEXTCOLOR", (1, 0), (1, -1), _INK),
        ("TOPPADDING", (0, 0), (-1, -1), 5.4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5.4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, _HAIR),
        ("BOX", (0, 0), (-1, -1), 0.4, _RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def _callout(text: str, st: dict, tone: str = "info",
             width: float | None = None):
    """A single boxed remark. Used where a table needs a sentence beside it.

    `width` resolves at call time rather than in the signature: `mm` only
    exists when reportlab imported, and a default argument is evaluated when
    the module loads -- which is exactly one import failure away from taking
    the whole module down with a NameError instead of degrading to
    "PDF export unavailable".
    """
    width = 170 * mm if width is None else width
    fill = {"warn": _PALE_W, "ok": _PALE_O}.get(tone, _BAND)
    edge = {"warn": _WARN, "ok": _OK}.get(tone, _RULE)
    style = st["warn"] if tone == "warn" else st["body"]
    # The glyph carries the tone before the sentence is read. Without it a
    # warning and a note are the same grey box with a different edge colour.
    t = Table([[_icon(tone), Paragraph(text, style)]],
              colWidths=[16, width - 16], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), fill),
        ("LINEBEFORE", (0, 0), (0, -1), 1.6, edge),
        ("BOX", (0, 0), (-1, -1), 0.3, _RULE),
        ("LEFTPADDING", (0, 0), (0, -1), 7),
        ("RIGHTPADDING", (0, 0), (0, -1), 0),
        ("LEFTPADDING", (1, 0), (1, -1), 7),
        ("RIGHTPADDING", (1, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (0, -1), "TOP"),
        ("VALIGN", (1, 0), (1, -1), "MIDDLE"),
    ]))
    return t


# ---------------------------------------------------------------------------
# Charts. Every one prints the number it depicts, so the shape is a second
# reading of the figure rather than the only one.
# ---------------------------------------------------------------------------
def _nice_scale(lo: float, hi: float, *, from_zero: bool = False,
                ticks: int = 4) -> tuple[float, float, list[float]]:
    """Round axis bounds and steps, instead of the data's own extremes.

    An axis fitted tightly to the data is the single most misleading thing a
    chart of engine parameters can do. RPM held between 5,140 and 5,260 --
    a variation of about one per cent -- fills the whole panel height and
    reads as an engine hunting badly. From zero, on round steps, it reads as
    what it is: flat.

    `from_zero` is the default for absolute quantities (RPM, pressures,
    flows). It is wrong for a delta-from-baseline, where zero IS the
    reference and the interesting range straddles it.
    """
    if from_zero:
        lo = min(0.0, lo)
        hi = max(0.0, hi)
    if hi <= lo:
        hi = lo + 1.0
    raw = (hi - lo) / max(1, ticks)
    mag = 10.0 ** math.floor(math.log10(raw)) if raw > 0 else 1.0
    for mult in (1.0, 2.0, 2.5, 5.0, 10.0):
        if raw <= mult * mag:
            step = mult * mag
            break
    else:  # pragma: no cover - the 10x branch always catches
        step = 10.0 * mag
    lo_n = math.floor(lo / step) * step
    hi_n = math.ceil(hi / step) * step
    steps, v = [], lo_n
    while v <= hi_n + step * 1e-6:
        steps.append(round(v, 10))
        v += step
    return lo_n, hi_n, steps


def _axis_style(ax, colour=_DIM, size: float = 5.2) -> None:
    ax.labels.fontName = "Helvetica"
    ax.labels.fontSize = size
    ax.labels.fillColor = colour
    ax.strokeColor = _RULE
    ax.strokeWidth = 0.4


def _mini_line(series: list[tuple[float, float]], *, title: str,
               w: float, h: float, colour=None, span_h: float | None = None,
               from_zero: bool = True) -> Drawing:
    """One small time-history panel, titled and axed.

    Sized to sit four-up on a page. The title carries the unit because an axis
    label at this scale is unreadable, and a chart whose unit is a guess is
    worse than no chart.

    `span_h` forces every panel onto the SAME x range -- the whole flight, from
    engine start to shutdown. Left to themselves the panels each end at their
    own last sample, so eight charts of one flight would carry eight slightly
    different time axes and could not be read against one another.
    """
    colour = colour if colour is not None else _RED
    d = Drawing(w, h)
    # A panel edge, so eight charts on a page read as eight objects rather
    # than as one field of lines.
    d.add(Rect(0, 0, w - 2, h - 2, fillColor=colors.white,
               strokeColor=_HAIR, strokeWidth=0.4))
    if not series:
        d.add(String(6, h / 2, "no data recorded", fontName="Helvetica",
                     fontSize=6, fillColor=_FAINT))
        d.add(String(4, h - 9, title, fontName="Helvetica-Bold",
                     fontSize=6.4, fillColor=_INK))
        return d
    d.add(String(4, h - 9, title, fontName="Helvetica-Bold",
                 fontSize=6.4, fillColor=_INK))

    xs = [p[0] for p in series]
    ys = [p[1] for p in series]
    x_end = span_h if span_h else max(xs)
    ylo, yhi, ysteps = _nice_scale(min(ys), max(ys), from_zero=from_zero,
                                   ticks=3)
    _, _, xsteps = _nice_scale(0.0, x_end, from_zero=True, ticks=6)

    lp = LinePlot()
    lp.x, lp.y = 26, 13
    lp.width, lp.height = w - 34, h - 26
    lp.data = [series]
    lp.lines[0].strokeColor = colour
    lp.lines[0].strokeWidth = 0.9
    lp.joinedLines = 1
    lp.xValueAxis.valueMin, lp.xValueAxis.valueMax = 0.0, x_end
    lp.xValueAxis.valueSteps = [v for v in xsteps if v <= x_end + 1e-9]
    lp.yValueAxis.valueMin, lp.yValueAxis.valueMax = ylo, yhi
    lp.yValueAxis.valueSteps = ysteps
    _axis_style(lp.xValueAxis)
    _axis_style(lp.yValueAxis)
    lp.yValueAxis.gridStrokeColor = _HAIR
    lp.yValueAxis.gridStrokeWidth = 0.25
    lp.yValueAxis.visibleGrid = 1
    d.add(lp)
    return d


def _overlay(a: list[tuple[float, float]], b: list[tuple[float, float]], *,
             w: float, h: float, label_a: str, label_b: str,
             title: str, dual_scale: bool = False) -> Drawing:
    """Two traces on one plot.

    `dual_scale=False` shares one axis, which is right when the two series are
    the same quantity -- actual against the twin's prediction of it.

    `dual_scale=True` maps the second series onto the first's range and prints
    its own end values on the right. Altitude runs to 21,000 and airspeed to
    110: on a shared axis the airspeed trace is a flat line along the bottom,
    which is not a small cosmetic problem -- it is a chart that appears to show
    an aircraft holding constant speed through a climb and a descent.
    """
    d = Drawing(w, h)
    if not a:
        d.add(String(4, h / 2, "no data", fontName="Helvetica",
                     fontSize=7, fillColor=_FAINT))
        return d
    d.add(String(0, h - 9, title, fontName="Helvetica-Bold",
                 fontSize=7.5, fillColor=_INK))

    b_lo = b_hi = None
    if dual_scale and b:
        a_ys = [p[1] for p in a]
        b_ys = [p[1] for p in b]
        a_lo, a_hi = min(a_ys), max(a_ys)
        b_lo, b_hi = min(b_ys), max(b_ys)
        span = (b_hi - b_lo) or 1.0
        b = [(x, a_lo + (y - b_lo) / span * (a_hi - a_lo)) for x, y in b]

    lp = LinePlot()
    lp.x, lp.y = 26, 20
    lp.width, lp.height = w - (52 if dual_scale else 34), h - 38
    lp.data = [a, b]
    lp.lines[0].strokeColor = _RED
    lp.lines[0].strokeWidth = 1.1
    lp.lines[1].strokeColor = _INK
    lp.lines[1].strokeWidth = 0.8
    ys = [p[1] for p in a] + [p[1] for p in b]
    xs = [p[0] for p in a]
    # Same rule as the small panels: round bounds from zero. A twin tracking
    # its engine to within 2 % must LOOK like it is tracking, and on a tight
    # axis two nearly identical traces separate into two unrelated curves.
    ylo, yhi, ysteps = _nice_scale(min(ys), max(ys), from_zero=True, ticks=4)
    _, _, xsteps = _nice_scale(0.0, max(xs), from_zero=True, ticks=6)
    lp.xValueAxis.valueMin, lp.xValueAxis.valueMax = 0.0, max(xs)
    lp.xValueAxis.valueSteps = [v for v in xsteps if v <= max(xs) + 1e-9]
    lp.yValueAxis.valueMin, lp.yValueAxis.valueMax = ylo, yhi
    lp.yValueAxis.valueSteps = ysteps
    _axis_style(lp.xValueAxis, size=6)
    _axis_style(lp.yValueAxis, size=6)
    lp.yValueAxis.visibleGrid = 1
    lp.yValueAxis.gridStrokeColor = _HAIR
    lp.yValueAxis.gridStrokeWidth = 0.25
    d.add(lp)

    # The right-hand scale, when the second series has one of its own. Without
    # these two numbers the mapped trace has a shape and no magnitude.
    if b_lo is not None:
        rx = lp.x + lp.width + 3
        d.add(Line(rx - 2, lp.y, rx - 2, lp.y + lp.height,
                   strokeColor=_RULE, strokeWidth=0.4))
        d.add(String(rx, lp.y + lp.height - 3, f"{b_hi:,.0f}",
                     fontName="Helvetica", fontSize=5.2, fillColor=_INK))
        d.add(String(rx, lp.y - 1, f"{b_lo:,.0f}", fontName="Helvetica",
                     fontSize=5.2, fillColor=_INK))

    # Legend, drawn rather than delegated so it sits exactly where there is room
    y = h - 9
    d.add(Line(w - 96, y + 2, w - 84, y + 2, strokeColor=_RED, strokeWidth=1.1))
    d.add(String(w - 81, y, label_a, fontName="Helvetica", fontSize=6,
                 fillColor=_DIM))
    d.add(Line(w - 46, y + 2, w - 34, y + 2, strokeColor=_INK, strokeWidth=0.8))
    d.add(String(w - 31, y, label_b, fontName="Helvetica", fontSize=6,
                 fillColor=_DIM))
    d.add(String(w / 2, 2, "Time (hours)", fontName="Helvetica", fontSize=5.6,
                 fillColor=_FAINT, textAnchor="middle"))
    return d


def _trend_panel(points: list[tuple[float, float]], *, title: str,
                 w: float, h: float) -> Drawing:
    """Per-flight deltas with a least-squares drift line through them.

    The fit is drawn because ECTM is a SLOPE, not a reading -- which is the
    whole reason this module now carries charts at all.
    """
    d = Drawing(w, h)
    if len(points) < 2:
        d.add(String(4, h / 2, "insufficient history", fontName="Helvetica",
                     fontSize=6.5, fillColor=_FAINT))
        return d
    d.add(String(0, h - 8, title, fontName="Helvetica-Bold",
                 fontSize=7, fillColor=_INK))
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    n = len(points)
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    slope = (sum((x - mx) * (y - my) for x, y in points) / den) if den else 0.0
    fit = [(min(xs), my + slope * (min(xs) - mx)),
           (max(xs), my + slope * (max(xs) - mx))]

    lp = LinePlot()
    lp.x, lp.y = 22, 16
    lp.width, lp.height = w - 30, h - 30
    lp.data = [points, fit]
    lp.lines[0].strokeColor = colors.transparent
    lp.lines[0].symbol = None
    lp.lines[1].strokeColor = _RED
    lp.lines[1].strokeWidth = 1.0
    allv = ys + [f[1] for f in fit]
    # from_zero here means "keep the baseline on the chart". These are deltas
    # FROM the post-overhaul baseline, so the zero line is the reference the
    # drift is being read against -- an axis that crops it out hides whether
    # the engine is above or below where it started.
    ylo, yhi, ysteps = _nice_scale(min(allv), max(allv), from_zero=True,
                                   ticks=3)
    lp.xValueAxis.valueMin, lp.xValueAxis.valueMax = min(xs), max(xs)
    # Flights are counted, so the axis is too: automatic steps put ticks at
    # "flight 1.2" and "flight 1.4".
    n_lo, n_hi = int(round(min(xs))), int(round(max(xs)))
    stride = max(1, (n_hi - n_lo) // 8 + 1)
    lp.xValueAxis.valueSteps = list(range(n_lo, n_hi + 1, stride))
    lp.xValueAxis.labelTextFormat = "%d"
    lp.yValueAxis.valueMin, lp.yValueAxis.valueMax = ylo, yhi
    lp.yValueAxis.valueSteps = ysteps
    _axis_style(lp.xValueAxis)
    _axis_style(lp.yValueAxis)
    lp.yValueAxis.visibleGrid = 1
    lp.yValueAxis.gridStrokeColor = _HAIR
    lp.yValueAxis.gridStrokeWidth = 0.25
    d.add(lp)

    # The points themselves, placed against the plot's own scale so a marker
    # can never drift away from the line fitted through it.
    xr = (max(xs) - min(xs)) or 1.0
    yr = (yhi - ylo) or 1.0
    for x, y in points:
        px = lp.x + (x - min(xs)) / xr * lp.width
        py = lp.y + (y - ylo) / yr * lp.height
        d.add(Line(px - 1.1, py, px + 1.1, py, strokeColor=_INK,
                   strokeWidth=1.6))
    d.add(String(w / 2, 1, "Flight number after the baseline flight",
                 fontName="Helvetica",
                 fontSize=5, fillColor=_FAINT, textAnchor="middle"))
    return d


def _health_ring(chi: float | None, band: str, *, w: float | None = None,
                 h: float | None = None) -> Drawing:
    """The overall index as a ring. The number is printed inside it.

    Drawn from two wedges and a punch-out circle. The filled arc starts at 12
    o'clock and runs clockwise, so a fuller ring always means a healthier
    engine and the shape can be read before the number is.
    """
    w = 46 * mm if w is None else w
    h = 46 * mm if h is None else h
    d = Drawing(w, h)
    val = 0.0 if chi is None else max(0.0, min(1.0, float(chi)))
    cx, cy, r = w / 2.0, h / 2.0, min(w, h) * 0.46
    colour = (_FILL_OK if val >= 0.80
              else _FILL_CAUT if val >= 0.60 else _FILL_WARN)

    d.add(Wedge(cx, cy, r, 0, 360, fillColor=_BAND, strokeColor=None))
    if val > 0:
        # Wedge angles run anticlockwise from 3 o'clock; starting at 90 and
        # sweeping negative puts the arc clockwise from the top.
        d.add(Wedge(cx, cy, r, 90 - val * 360.0, 90,
                    fillColor=colour, strokeColor=None))
    d.add(Circle(cx, cy, r * 0.68, fillColor=colors.white, strokeColor=None))

    d.add(String(cx, cy + 1, "---" if chi is None else f"{val:.2f}",
                 fontName="Helvetica-Bold", fontSize=19, fillColor=_INK,
                 textAnchor="middle"))
    d.add(String(cx, cy - 11, f"Band: {band}", fontName="Helvetica",
                 fontSize=7.4, fillColor=_DIM, textAnchor="middle"))
    return d


def _rul_curve(hours: float | None, lower: float | None, upper: float | None,
               used: float | None, *, w: float, h: float) -> Drawing:
    """Remaining life against engine hours, with the confidence band.

    Drawn as a decay from the current position rather than as a fitted history,
    because that is what the figure IS: one estimate with an interval, not a
    series. Anything more elaborate would imply evidence the model never had.
    """
    d = Drawing(w, h)
    if hours is None or used is None:
        d.add(String(4, h / 2, "no reportable estimate", fontName="Helvetica",
                     fontSize=7, fillColor=_FAINT))
        return d
    end = used + hours
    xs = [used + (end - used) * i / 20.0 for i in range(21)]
    mid = [(x, max(0.0, end - x)) for x in xs]
    lo = [(x, max(0.0, (used + (lower or hours)) - x)) for x in xs]
    hi = [(x, max(0.0, (used + (upper or hours)) - x)) for x in xs]

    lp = LinePlot()
    lp.x, lp.y = 30, 22
    lp.width, lp.height = w - 40, h - 38
    lp.data = [hi, mid, lo]
    for i, col in enumerate((colors.HexColor("#f4b8b0"), _RED,
                             colors.HexColor("#f4b8b0"))):
        lp.lines[i].strokeColor = col
        lp.lines[i].strokeWidth = 1.4 if i == 1 else 0.7
    # From a little before now to past the far end of the interval. Starting
    # at half the engine's hours squeezed a short estimate into a sliver at
    # the right-hand edge.
    far = used + (upper or hours)
    xlo, xhi, xsteps = _nice_scale(max(0.0, used - 0.25 * (far - used)),
                                   far + 0.05 * (far - used), ticks=5)
    _, yhi_n, ysteps = _nice_scale(0.0, (upper or hours) * 1.1,
                                   from_zero=True, ticks=4)
    lp.xValueAxis.valueMin, lp.xValueAxis.valueMax = xlo, xhi
    lp.xValueAxis.valueSteps = xsteps
    lp.yValueAxis.valueMin, lp.yValueAxis.valueMax = 0, yhi_n
    lp.yValueAxis.valueSteps = ysteps
    _axis_style(lp.xValueAxis, size=6)
    _axis_style(lp.yValueAxis, size=6)
    lp.yValueAxis.visibleGrid = 1
    lp.yValueAxis.gridStrokeColor = _HAIR
    lp.yValueAxis.gridStrokeWidth = 0.25
    d.add(lp)
    # "You are here" -- without it the curve is a shape with no anchor.
    px = lp.x + (used - lp.xValueAxis.valueMin) / (
        lp.xValueAxis.valueMax - lp.xValueAxis.valueMin) * lp.width
    d.add(Line(px, lp.y, px, lp.y + lp.height, strokeColor=_INK,
               strokeWidth=0.5, strokeDashArray=[2, 2]))
    d.add(String(px + 3, lp.y + lp.height - 6, f"Current: {used:,.0f} h",
                 fontName="Helvetica", fontSize=6, fillColor=_INK))
    d.add(String(w / 2, 2, "Engine hours", fontName="Helvetica", fontSize=5.6,
                 fillColor=_FAINT, textAnchor="middle"))
    d.add(String(6, h - 8, "RUL (hours)", fontName="Helvetica", fontSize=5.6,
                 fillColor=_FAINT))
    return d


def _uav_planform(w: float, h: float) -> Drawing:
    """A MALE UAV in plan view, drawn rather than photographed.

    The cover of the reference design carries a photograph. This generator has
    no photograph to carry and will not pretend otherwise, so it draws the
    aircraft instead: long high-aspect wing, slender fuselage, satcom fairing,
    V-tail on a boom. A technical document is entitled to a technical drawing,
    and a drawing cannot be mistaken for evidence of a particular airframe the
    way a stock photograph can.

    Pass `cover_image` in the payload to use a real photograph instead.
    """
    d = Drawing(w, h)
    d.add(Rect(0, 0, w, h, fillColor=_BAND, strokeColor=None))

    cx, cy = w * 0.5, h * 0.52
    sc = min(w / 260.0, h / 150.0)

    def P(pts):
        return [c for xy in pts for c in (cx + xy[0] * sc, cy + xy[1] * sc)]

    ink = colors.HexColor("#39424e")

    # Wing: high aspect ratio, slight taper, the defining feature of the class.
    d.add(Polygon(P([(-125, 6), (125, 6), (125, 1), (18, -2),
                     (-18, -2), (-125, 1)]),
                  fillColor=ink, strokeColor=None))
    # Fuselage with the satcom fairing forward.
    d.add(Polygon(P([(-6, 34), (6, 34), (9, 10), (9, -40),
                     (5, -52), (-5, -52), (-9, -40), (-9, 10)]),
                  fillColor=ink, strokeColor=None))
    d.add(Circle(cx, cy + 30 * sc, 11 * sc, fillColor=ink, strokeColor=None))
    # V-tail on a slender boom, swept aft.
    d.add(Polygon(P([(-3, -40), (-40, -60), (-34, -64), (-1, -46)]),
                  fillColor=ink, strokeColor=None))
    d.add(Polygon(P([(3, -40), (40, -60), (34, -64), (1, -46)]),
                  fillColor=ink, strokeColor=None))
    # Pusher propeller disc, aft of the tail so the two do not overlap.
    d.add(Circle(cx, cy - 60 * sc, 17 * sc, fillColor=None,
                 strokeColor=_RED, strokeWidth=0.6))
    d.add(Line(cx - 17 * sc, cy - 60 * sc, cx + 17 * sc, cy - 60 * sc,
               strokeColor=_RED, strokeWidth=0.9))

    d.add(String(10, 9, "AERO-PISTON MALE UAV  /  PLAN VIEW  /  NOT TO SCALE",
                 fontName="Helvetica", fontSize=5.6, fillColor=_FAINT))
    return d


def _track_map(track: list, w: float, h: float) -> Drawing:
    """The flown track, from recorded position. Real data or nothing.

    A map is the one graphic in this document that a reader will take as
    literal, so it is drawn from `replay.track` and omitted entirely when that
    is absent -- a decorative squiggle here would be a fabricated flight path
    in a maintenance record.
    """
    d = Drawing(w, h)
    d.add(Rect(0, 0, w, h, fillColor=colors.HexColor("#f2f4f6"),
               strokeColor=_RULE, strokeWidth=0.4))
    pts = [(float(p[0]), float(p[1])) for p in track or [] if len(p) >= 2]
    if len(pts) < 2:
        d.add(String(w / 2, h / 2, "No position track was recorded",
                     fontName="Helvetica", fontSize=7.5, fillColor=_FAINT,
                     textAnchor="middle"))
        return d

    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    pad = 16.0
    # One scale for both axes, so the track keeps its true shape instead of
    # being stretched to fill the box.
    sc = min((w - 2 * pad) / ((x1 - x0) or 1.0),
             (h - 2 * pad) / ((y1 - y0) or 1.0))
    ox = (w - (x1 - x0) * sc) / 2.0
    oy = (h - (y1 - y0) * sc) / 2.0

    def to_px(p):
        return (ox + (p[0] - x0) * sc, oy + (p[1] - y0) * sc)

    for i in range(len(pts) - 1):
        a, b = to_px(pts[i]), to_px(pts[i + 1])
        d.add(Line(a[0], a[1], b[0], b[1], strokeColor=_RED,
                   strokeWidth=1.1))
    a, b = to_px(pts[0]), to_px(pts[-1])
    d.add(Circle(a[0], a[1], 3.2, fillColor=colors.white, strokeColor=_INK,
                 strokeWidth=1.2))
    d.add(Circle(b[0], b[1], 3.2, fillColor=_INK, strokeColor=_INK))

    # Legend in the corner rather than labels beside the markers: a sortie that
    # recovers to its departure field puts both in the same place, and the two
    # words then print on top of one another.
    lx, ly = w - 76, h - 20
    d.add(Rect(lx - 8, ly - 9, 76, 26, fillColor=colors.white,
               strokeColor=_HAIR, strokeWidth=0.4))
    d.add(Line(lx - 3, ly + 11, lx + 7, ly + 11, strokeColor=_RED,
               strokeWidth=1.2))
    d.add(String(lx + 11, ly + 9, "Flight track", fontName="Helvetica",
                 fontSize=5.8, fillColor=_INK))
    d.add(Circle(lx + 2, ly + 2, 3.0, fillColor=colors.white,
                 strokeColor=_INK, strokeWidth=1.0))
    d.add(String(lx + 11, ly, "Take-off", fontName="Helvetica",
                 fontSize=5.8, fillColor=_INK))
    d.add(Circle(lx + 2, ly - 7, 3.0, fillColor=_INK, strokeColor=_INK))
    d.add(String(lx + 11, ly - 9, "Landing", fontName="Helvetica",
                 fontSize=5.8, fillColor=_INK))

    d.add(String(10, 9, "FLOWN TRACK FROM RECORDED POSITION",
                 fontName="Helvetica", fontSize=5.6, fillColor=_FAINT))
    return d


def _icon(tone: str, size: float = 11.0) -> Drawing:
    """A glyph for a callout, so tone reads before the sentence does."""
    d = Drawing(size, size)
    r = size / 2.0
    col = {"warn": _WARN, "ok": _OK}.get(tone, _accent_or_dim())
    d.add(Circle(r, r, r - 0.6, fillColor=col, strokeColor=None))
    if tone == "ok":
        d.add(Line(r - 2.6, r + 0.1, r - 0.7, r - 2.0,
                   strokeColor=colors.white, strokeWidth=1.4))
        d.add(Line(r - 0.9, r - 2.0, r + 2.7, r + 2.4,
                   strokeColor=colors.white, strokeWidth=1.4))
    elif tone == "warn":
        d.add(Line(r, r + 2.9, r, r - 0.7, strokeColor=colors.white,
                   strokeWidth=1.5))
        d.add(Circle(r, r - 2.5, 0.85, fillColor=colors.white,
                     strokeColor=None))
    else:
        d.add(Circle(r, r + 2.6, 0.85, fillColor=colors.white,
                     strokeColor=None))
        d.add(Line(r, r + 1.0, r, r - 3.0, strokeColor=colors.white,
                   strokeWidth=1.5))
    return d


def _accent_or_dim():
    return _accent_colour


# ---------------------------------------------------------------------------
# Page furniture
# ---------------------------------------------------------------------------
class _Furniture:
    """Header and footer drawn on every page but the cover.

    Page numbers come from the canvas rather than from a counter kept here,
    because a counter is exactly the thing that produced "03 / 12" on page
    seven of the mock-up.
    """

    def __init__(self, mission: str, total: int | None = None) -> None:
        self.mission = mission
        self.total = total

    def __call__(self, canvas, doc) -> None:
        canvas.saveState()
        W, H = A4
        m = 15 * mm

        canvas.setFont("Helvetica-Bold", 8)
        canvas.setFillColor(_INK)
        canvas.drawString(m, H - m + 2, ORG_MARK)
        canvas.setFont("Helvetica", 7.4)
        canvas.setFillColor(_DIM)
        canvas.drawCentredString(W / 2, H - m + 2, DOC_TITLE)
        canvas.drawRightString(W - m, H - m + 2, self.mission)
        canvas.setStrokeColor(_RULE)
        canvas.setLineWidth(0.5)
        canvas.line(m, H - m - 2, W - m, H - m - 2)

        canvas.setFont("Helvetica", 6.6)
        canvas.setFillColor(_FAINT)
        canvas.drawString(m, m - 6, STRAPLINE)
        # On the counting pass the total is unknown, so the footer shows the
        # page alone. The second pass fills it in.
        n = canvas.getPageNumber()
        canvas.drawRightString(
            W - m, m - 6,
            f"{n:02d} / {self.total:02d}" if self.total else f"{n:02d}")
        canvas.line(m, m - 1, W - m, m - 1)
        canvas.restoreState()


def _section(no: str, title: str, st: dict, W: float) -> list:
    """The big numeral, the title, and the red rule beneath both."""
    head = Table(
        [[Paragraph(no, st["sec_no"]), Paragraph(title, st["sec_title"])]],
        colWidths=[24 * mm, W - 24 * mm], hAlign="LEFT")
    head.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    rule = Table([[""]], colWidths=[18 * mm], rowHeights=[1.6])
    rule.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _RED),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return [head, rule, Spacer(1, 7 * mm)]


# ---------------------------------------------------------------------------
# Cover
# ---------------------------------------------------------------------------
def _pdf_date(yyyy, mm, dd, hh, mi, ss) -> str:
    """PDF date string with the local UTC offset's MINUTES kept."""
    from datetime import datetime, timedelta

    off = datetime.now().astimezone().utcoffset() or timedelta(0)
    total = int(off.total_seconds() // 60)
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    return (f"D:{yyyy:04d}{mm:02d}{dd:02d}{hh:02d}{mi:02d}{ss:02d}"
            f"{sign}{total // 60:02d}'{total % 60:02d}'")


def _cover_painter(path: str | None):
    """Draw the cover artwork full-bleed behind page one.

    Full-bleed rather than inset: the artwork is authored at A4 proportions
    (1055 x 1491, aspect 0.708 against A4's 0.707), so it fills the trim with
    no letterboxing and no crop worth speaking of.
    """
    def paint(canvas, doc):
        # Correct UTC offset in the PDF CreationDate (REP-08). reportlab
        # computes the minutes as (gmtoff % 3600) % 60, which is always zero
        # for a whole-minute zone, so IST was written +05'00' instead of
        # +05'30'. Set on page one, before anything can return early.
        canvas.setDateFormatter(_pdf_date)
        if not path:
            return
        try:
            canvas.saveState()
            canvas.drawImage(path, 0, 0, width=A4[0], height=A4[1],
                             preserveAspectRatio=False, anchor="c", mask=None)
            canvas.restoreState()
        except Exception:
            # A missing or unreadable image must not take the report down --
            # the cover degrades to type on white, which is still a cover.
            pass
    return paint


def _cover(rep: dict, st: dict, W: float) -> list:
    """Title, subtitle and identity block. Nothing the artwork already says.

    No DRDO mark, no tricolour, no strapline: those are in the background, and
    a flowable version of them would print on top of the printed ones.
    """
    title = Paragraph("POST-FLIGHT<br/>ENGINE HEALTH REPORT", st["cover_title"])
    sub_ = Paragraph(
        "AI-Enabled Real-Time Digital Twin System<br/>"
        "for Health Monitoring, Fault Prediction and<br/>"
        "Mission Reliability Enhancement of<br/>"
        "Aero Piston Engines used in MALE UAVs", st["cover_sub"])

    meta = [
        ("Mission ID", rep.get("mission_id", "---")),
        ("Airframe", rep.get("aircraft_id", "---")),
        ("Engine", f'{rep.get("engine", "---")} '
                   f'({rep.get("engine_serial", "---")})'),
        ("Date (UTC)", rep.get("date", "---")),
        ("Location", rep.get("location", "---")),
        ("Report Version", str(rep.get("report_version", "1.0"))),
    ]
    rows = [[k, ":", v] for k, v in meta]
    rows.append(["Classification", ":",
                 Paragraph(
                     f'<b>'
                     f'{rep.get("classification", DEFAULT_CLASSIFICATION)}'
                     f'</b>', st["cover_meta"])])
    kv = Table(rows, colWidths=[30 * mm, 4 * mm, W - 34 * mm], hAlign="LEFT")
    kv.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.6),
        ("TEXTCOLOR", (0, 0), (1, -1), _DIM),
        ("TEXTCOLOR", (2, 0), (2, -1), _INK),
        ("TOPPADDING", (0, 0), (-1, -1), 2.4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.4),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))

    rule = Table([[""]], colWidths=[16 * mm], rowHeights=[2.2])
    rule.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _RED),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    # The frame starts at the top of the trim, so this spacer is what places
    # the block inside the measured clear band rather than over the header.
    return [Spacer(1, A4[1] * COVER_TEXT_TOP - 8 * mm),
            rule, Spacer(1, 5 * mm), title, Spacer(1, 2 * mm), sub_,
            Spacer(1, 7 * mm), kv]


# ---------------------------------------------------------------------------
# 01 Identity and flight summary
# ---------------------------------------------------------------------------
def _s01(rep: dict, st: dict, W: float) -> list:
    m = rep.get("mission", {}) or {}
    f = _section("01", "IDENTITY AND<br/>FLIGHT SUMMARY", st, W)

    f.append(Paragraph("1.1 Identity Header", st["h3"]))
    f.append(_kv([
        ("Airframe", rep.get("aircraft_id", "---")),
        ("Engine type / serial",
         f'{rep.get("engine", "---")} / {rep.get("engine_serial", "---")}'),
        ("Mission ID", rep.get("mission_id", "---")),
        ("Flight window (UTC) -- record time", rep.get(
            "window_utc", rep.get("generated_utc", "---"))),
        # Shown beside the UTC window, never instead of it. DGCA CAR 66 keeps
        # the maintenance logbook in UTC and forbids mixing local and Zulu in
        # one entry, so both are labelled and neither is ever bare.
        (f'Flight window ({rep.get("local_timezone", "IST")}) -- local',
         rep.get("window_local") or "---"),
        ("Ground station software version", rep.get("gcs_version", "---")),
        ("Report integrity hash", digest(rep)[:12]),
    ], 62 * mm, W - 62 * mm))

    f.append(Spacer(1, 5 * mm))
    # The classification states the provenance, so it carries it once, as a
    # document property rather than an alarm. A second red block repeating
    # "simulated data" under it said the same thing twice and read, on a demo,
    # as a warning about the engine rather than about the document. The
    # provenance still travels in the PDF TITLE, which a reader's window bar
    # and a file manager both show -- see build().
    f.append(_callout(
        f'<b>Classification: '
        f'{rep.get("classification", DEFAULT_CLASSIFICATION)}</b>',
        st, "info", W))

    f.append(Paragraph("1.2 Flight Summary", st["h3"]))
    before = m.get("hours_before")
    after = m.get("flight_hours")
    if before is None and after is not None and m.get("duration_h") is not None:
        before = after - float(m["duration_h"])
    f.append(_kv([
        ("Flight duration", _num(m.get("duration_h"), 1, "hours")),
        ("Engine hours before this flight", _num(before, 1, "hours")),
        ("Engine hours after this flight", _num(after, 1, "hours")),
        ("Start-stop cycles this flight", _num(m.get("start_stop_cycles"), 0)),
        ("Thermal cycles this flight", _num(m.get("thermal_cycles"), 0)),
        ("Maximum altitude reached", _num(m.get("max_altitude_ft"), 0, "ft")),
        ("Outside air temperature range", m.get("oat_range", "---")),
        ("Mission type", m.get("mission_type", "---")),
    ], 62 * mm, W - 62 * mm))

    # THE TASKING, from the squadron's own record: what was ordered, who flew
    # it, who approved it, and how it ended. The report used to say only
    # "ISR patrol profile", whatever had been flown.
    tk = m.get("tasking") or {}
    if tk:
        f.append(Paragraph("1.2.1 Tasking", st["h3"]))
        f.append(_kv([
            ("Mission", f'{tk.get("id", "---")} -- {tk.get("name") or "---"}'),
            ("Task", tk.get("task") or "---"),
            ("Area or route", tk.get("area") or "---"),
            ("Planned endurance / altitude",
             f'{_num(tk.get("planned_endurance_h"), 1, "h")} at '
             f'{_num(tk.get("planned_altitude_ft"), 0, "ft")}'),
            ("Operator", tk.get("operator") or "---"),
            ("Approved by", tk.get("approved_by") or "---"),
            ("Launched / landed (UTC)",
             f'{tk.get("launched_utc") or "---"} / {tk.get("landed_utc") or "---"}'),
            ("Status / outcome",
             f'{(tk.get("status") or "---").replace("_", " ").lower()}'
             f'{" / " + tk["outcome"].lower() if tk.get("outcome") else ""}'),
            ("Operator's debrief", tk.get("debrief") or "---"),
        ], 62 * mm, W - 62 * mm))

    # These are LIFE-TO-DATE, and the heading has to say so. Under a
    # "post-flight" title a maintainer reads a six-month-old peak as something
    # that happened this morning, and acts on it.
    e = rep.get("extremes", {}) or {}
    if e:
        f.append(Paragraph("1.3 Life-to-date extremes "
                           "(whole engine life, not this flight)", st["h3"]))
        rows = [["Parameter", "Peak", "Parameter", "Peak"]]
        pairs = [
            ("Max CHT", _num(e.get("max_cht_c"), 1, "C"),
             "Max coolant", _num(e.get("max_coolant_c"), 1, "C")),
            ("Max EGT", _num(e.get("max_egt_c"), 0, "C"),
             "Max RPM", _num(e.get("max_rpm"), 0)),
            ("Max vibration", _num(e.get("max_vibration"), 2, "g"),
             "Time above max continuous",
             _dur(e.get("time_above_max_continuous_s"))),
        ]
        for a, b, c, d in pairs:
            rows.append([a, b, c, d])
        f.append(_table(rows, [(W - 70 * mm) / 2, 35 * mm,
                               (W - 70 * mm) / 2, 35 * mm],
                        zebra=True, align_right=[1, 3], size=7.8))
    return f


# ---------------------------------------------------------------------------
# 02 Mission profile -- ADS-79 regime recognition
# ---------------------------------------------------------------------------
def _s02(rep: dict, st: dict, W: float) -> list:
    fr = rep.get("flight_record", {}) or {}
    u = fr.get("usage", {}) or {}
    f = _section("02", "MISSION PROFILE", st, W)

    f.append(Paragraph("2.1 Time in Each Flight Phase", st["h3"]))
    rows = [["Flight Phase", "Time (h)", "Percentage"]]
    for p in u.get("phases", []):
        rows.append([p["phase"], _num(p["hours"], 2), f'{p["pct"]:.1f} %'])
    if len(rows) == 1:
        rows.append(["---", "---", "---"])
    f.append(_table(rows, [W - 70 * mm, 35 * mm, 35 * mm],
                    zebra=True, align_right=[1, 2]))

    f.append(Spacer(1, 3 * mm))
    f.append(_kv([
        (f'Time above maximum continuous power '
         f'({_num(u.get("mcp_pct"), 0)} %)',
         _num(u.get("hours_above_mcp"), 2, "h")),
        (f'Rapid throttle transitions counted '
         f'(step >= {_num(u.get("throttle_step_pct"), 0)} %)',
         _num(u.get("throttle_transitions"), 0)),
    ], W - 40 * mm, 40 * mm))

    prof = rep.get("profile", {}) or {}
    alt = [(p[0], p[1]) for p in prof.get("altitude_ft", [])]
    if alt:
        f.append(Paragraph("2.2 Altitude and Airspeed Profile", st["h3"]))
        f.append(_overlay(
            alt, [(p[0], p[1]) for p in prof.get("airspeed_kt", [])] or alt,
            w=W, h=88 * mm, label_a="Altitude (ft)",
            label_b="Airspeed (kt)", title="", dual_scale=True))
    return f


# ---------------------------------------------------------------------------
# 03 Engine parameters
# ---------------------------------------------------------------------------
def _s03(rep: dict, st: dict, W: float) -> list:
    f = _section("03", "ENGINE PARAMETERS<br/>(TIME HISTORY)", st, W)
    hist = rep.get("history", {}) or {}
    panels = [
        ("Engine RPM", "rpm"),
        # bar, not kPa. The channel is bar throughout, and a 1.3 with a kPa
        # label reads as an engine drawing a hard vacuum.
        ("Manifold Pressure (bar)", "manifold_pressure"),
        ("Cylinder Head Temperature (C)", "cht_max"),
        ("Exhaust Gas Temperature (C)", "egt_max"),
        ("Oil Pressure (psi)", "oil_pressure"),
        ("Oil Temperature (C)", "oil_temperature"),
        ("Fuel Flow (L/h)", "fuel_flow"),
        ("Vibration (g)", "vibration_rms_total"),
    ]
    cw = (W - 4 * mm) / 2.0
    # Every panel gets the same x range: the whole flight. Panels that each
    # ended at their own last sample would carry eight different time axes.
    span = 0.0
    for _, key in panels:
        pts = hist.get(key, [])
        if pts:
            span = max(span, float(pts[-1][0]))
    span = span or float((rep.get("mission", {}) or {}).get("duration_h") or 1.0)

    cells, row = [], []
    for i, (title, key) in enumerate(panels):
        series = [(p[0], p[1]) for p in hist.get(key, [])]
        colour = _RED if i % 2 == 0 else _INK
        row.append(_mini_line(series, title=title, w=cw, h=36 * mm,
                              colour=colour, span_h=span))
        if len(row) == 2:
            cells.append(row)
            row = []
    if row:
        row.append("")
        cells.append(row)
    grid = Table(cells, colWidths=[cw, cw], hAlign="LEFT")
    grid.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    f.append(grid)
    f.append(Paragraph(
        f"All eight panels share one time axis: hours from engine start to "
        f"engine shutdown, 0 to {span:.1f} h. Vertical axes begin at zero on "
        f"round steps, so a parameter held steady reads as steady.",
        st["note"]))

    env = rep.get("environment", {}) or {}
    if env:
        f.append(Paragraph("3.2 Environmental Parameters", st["h3"]))
        rows = [["Parameter", "Average", "Range"]]
        for label, key in (("Outside Air Temperature (C)", "oat_c"),
                           ("Ambient Pressure (hPa)", "pressure_hpa"),
                           ("Relative Humidity (%)", "humidity_pct")):
            e = env.get(key, {}) or {}
            rows.append([label, _num(e.get("avg"), 0),
                         f'{_num(e.get("min"), 0)} to {_num(e.get("max"), 0)}'])
        f.append(_table(rows, [W - 70 * mm, 35 * mm, 35 * mm],
                        zebra=True, align_right=[1, 2]))
    return f


# ---------------------------------------------------------------------------
# 04 Digital twin versus actual -- the premise of the project
# ---------------------------------------------------------------------------
def _s04(rep: dict, st: dict, W: float) -> list:
    fr = rep.get("flight_record", {}) or {}
    tv = fr.get("twin_vs_actual", []) or []
    f = _section("04", "DIGITAL TWIN VERSUS ACTUAL", st, W)

    f.append(Paragraph("4.1 Key Parameter Comparison (Cruise Average)",
                       st["h3"]))
    if not tv:
        f.append(_callout(
            "No paired twin and actual samples were recorded for this flight, "
            "so no comparison can be made. This is a gap in the recording, "
            "not a finding about the engine.", st, "warn", W))
        return f

    rows = [["Parameter", "Actual (avg)", "Digital Twin (avg)", "Deviation"]]
    worst, worst_name = 0.0, ""
    for r in tv:
        if r["deviation_pct"] >= worst:
            worst, worst_name = r["deviation_pct"], str(r["parameter"])
        rows.append([r["parameter"], _num(r["actual"], 1),
                     _num(r["twin"], 1), f'{r["deviation_pct"]:.1f} %'])
    f.append(_table(rows, [W - 105 * mm, 35 * mm, 35 * mm, 35 * mm],
                    zebra=True, align_right=[1, 2, 3]))

    f.append(Spacer(1, 4 * mm))
    tone = "ok" if worst <= 5.0 else "warn"
    f.append(_callout(
        f"Digital twin tracked the physical engine within "
        f"<b>{worst:.1f} %</b> deviation on all key parameters throughout the "
        f"mission." if tone == "ok" else
        # The twin is the engine AS NEW, so a gap between it and the engine
        # is the fault signal the health figures are computed from -- not a
        # twin that has lost synchronisation. Saying the latter told the
        # reader to distrust the very finding the report exists to make.
        f"The engine departed from its as-new digital twin by up to "
        f"<b>{worst:.1f} %</b> ({worst_name}). The twin models the engine "
        f"as it should be, so a departure above 5 % is a finding about the "
        f"engine: it is the residual Sections 9 and 10 are computed from.",
        st, tone, W))

    pair = rep.get("twin_overlay", {}) or {}
    if pair.get("actual"):
        f.append(Paragraph("4.2 Cylinder Head Temperature "
                           "(Actual vs Digital Twin)", st["h3"]))
        f.append(_overlay([(p[0], p[1]) for p in pair["actual"]],
                          [(p[0], p[1]) for p in pair.get("twin", [])],
                          w=W, h=78 * mm, label_a="Actual",
                          label_b="Digital Twin", title="CHT (C)"))
    return f


# ---------------------------------------------------------------------------
# 05 Limit exceedances -- CAP 739 severity grading
# ---------------------------------------------------------------------------
def _s05(rep: dict, st: dict, W: float) -> list:
    fr = rep.get("flight_record", {}) or {}
    exc = fr.get("exceedances", []) or []
    f = _section("05", "LIMIT EXCEEDANCES", st, W)

    if not exc:
        f.append(_callout(
            "No limit exceedances were observed during this flight.",
            st, "ok", W))
        return f

    rows = [["Parameter", "First At", "Limit", "Worst Value", "Beyond Limit",
             "Time Beyond", "Phase", "Severity"]]
    colour_rows = []
    for i, e in enumerate(exc, start=1):
        sev = e.get("severity", 1)
        name = str(e["parameter"])
        # A MINIMUM limit (oil pressure) is breached by going UNDER it, so the
        # excess is signed: "Over By 27.5 psi" on a pressure that fell to
        # 1.5 psi said the opposite of what happened.
        sign = "-" if e.get("minimum") else "+"
        rows.append([
            # Wrapped: "Cylinder head temperature" printed straight across the
            # time beside it.
            Paragraph(name[:1].upper() + name[1:], _styles()["cell"]),
            _clock(e.get("first_t_s")),
            _num(e["limit"], 1, e.get("unit", "")),
            _num(e["peak"], 1, e.get("unit", "")),
            sign + _num(e["over_by"], 1, e.get("unit", "")),
            _dur(e["seconds_above"]), e.get("phase", "---"),
            f"Level {sev}",
        ])
        if sev >= 3:
            colour_rows.append((i, _PALE_W))
        else:
            # A level 1 exceedance is still a limit that was crossed, and an
            # untinted row read as a table of ordinary readings.
            colour_rows.append((i, colors.HexColor("#fdf3e6")))
    f.append(_table(
        rows, [W - 152 * mm, 19 * mm, 21 * mm, 23 * mm, 19 * mm, 21 * mm,
               22 * mm, 27 * mm],
        align_right=[2, 3, 4], colour_rows=colour_rows, size=7.2))

    f.append(Spacer(1, 4 * mm))
    f.append(_callout(
        "Severity is graded 1 (minor) to 3 (major) against separate configured "
        "limits, following CAP 739. Peak and duration are both carried: an "
        "over-temperature for two seconds and the same peak sustained for four "
        "minutes are different findings with different manual actions.",
        st, "info", W))
    return f


# ---------------------------------------------------------------------------
# 06 Event log -- Airbus PFR shape
# ---------------------------------------------------------------------------
def _s06(rep: dict, st: dict, W: float) -> list:
    fr = rep.get("flight_record", {}) or {}
    events = fr.get("events", []) or []
    f = _section("06", "EVENT LOG", st, W)

    if not events:
        f.append(_callout("No alert was raised during this flight.",
                          st, "ok", W))
        return f

    rows = [["Time", "Phase", "Alert Text", "ATA Chapter", "Duration",
             "Cleared Before Landing"]]
    colour_rows, uncleared = [], 0
    cell = _styles()["cell"]
    m = rep.get("mission", {}) or {}
    # When the engine stopped, so an alert still standing has a duration too:
    # from when it was raised to shutdown. "---" there hid the longest-running
    # alerts of the flight.
    end_s = m.get("simulated_seconds") or (
        float(m["duration_h"]) * 3600.0 if m.get("duration_h") else None)
    for i, e in enumerate(events, start=1):
        cleared = e.get("cleared_s") is not None
        if not cleared:
            uncleared += 1
            colour_rows.append((i, _PALE_W))
        if cleared:
            dur = _dur(e.get("duration_s"))
        elif end_s is not None and e.get("t_s") is not None:
            dur = Paragraph(
                f'{_dur(max(0.0, float(end_s) - float(e["t_s"])))}'
                f'<br/>to shutdown', cell)
        else:
            dur = "to shutdown"
        rows.append([
            _clock(e.get("t_s")), e.get("phase", "---"),
            Paragraph(str(e.get("legend", "---")), cell),
            # Wrapped, so a long chapter title stays inside its column instead
            # of printing across the duration beside it.
            Paragraph(str(e.get("ata", "---")), cell),
            dur,
            "Yes" if cleared else "No, active at shutdown",
        ])
    # ATA wide enough that a standard chapter title ("73 Engine fuel and
    # control") sits on one line.
    f.append(_table(
        rows, [20 * mm, 22 * mm, W - 138 * mm, 34 * mm, 24 * mm, 38 * mm],
        colour_rows=colour_rows, size=7.6))

    f.append(Spacer(1, 4 * mm))
    if uncleared:
        f.append(_callout(
            f"<b>{uncleared} alert{'s' if uncleared > 1 else ''} remained "
            f"active at the end of the flight and "
            f"{'are' if uncleared > 1 else 'is'} carried forward to "
            f"Section 15.</b>", st, "warn", W))
    else:
        f.append(_callout("All alerts cleared before landing.", st, "ok", W))
    return f


# ---------------------------------------------------------------------------
# 07 Stabilised cruise reading -- ECTM
# ---------------------------------------------------------------------------
def _s07(rep: dict, st: dict, W: float) -> list:
    fr = rep.get("flight_record", {}) or {}
    cd = fr.get("cruise_datum")
    f = _section("07", "STABILISED CRUISE READING", st, W)

    if not cd:
        f.append(_callout(
            "<b>No stabilised cruise reading was captured on this flight.</b> "
            + str(fr.get("cruise_reason", ""))
            + " No trend point is contributed by this sortie.",
            st, "warn", W))
        return f

    f.append(Paragraph("7.1 Conditions at Time of Reading", st["h3"]))
    f.append(_kv([
        ("Altitude", _num(cd.get("altitude_ft"), 0, "ft")),
        ("Outside Air Temperature (OAT)", _num(cd.get("oat_c"), 0, "C")),
        ("Airspeed", _num(cd.get("airspeed_kt") if cd.get("airspeed_kt") is not None
                          else (None if cd.get("airspeed_kmh") is None
                                else float(cd["airspeed_kmh"]) / 1.852), 0, "kt")),
        ("Engine RPM", _num(cd.get("rpm"), 0, "rpm")),
        ("Held stable for", _num(cd.get("stable_for_s"), 0, "s stable")),
        ("Time (from engine start)", _clock(cd.get("t_s"))),
    ], 62 * mm, W - 62 * mm))

    f.append(Paragraph("7.2 Parameter Readings", st["h3"]))
    rows = [["Parameter", "Raw Value", "Standard-Day Corrected",
             "Delta from Baseline"]]
    for r in cd.get("readings", []):
        rows.append([
            r.get("name", "---"),
            _num(r.get("raw"), 1, r.get("unit", "")),
            # Pressures and flows take no temperature correction, so their
            # standard-day value IS the measured one -- said, not dashed.
            (_num(r.get("corrected"), 1, r.get("unit", ""))
             if r.get("corrected") is not None else "as measured"),
            ("---" if r.get("delta") is None
             else f'{r["delta"]:+.1f} {r.get("unit", "")}'.strip()),
        ])
    if len(rows) == 1:
        rows.append(["---", "---", "---", "---"])
    f.append(_table(rows, [W - 108 * mm, 34 * mm, 40 * mm, 34 * mm],
                    zebra=True, align_right=[1, 2, 3], size=7.6))

    if cd.get("note"):
        f.append(Spacer(1, 4 * mm))
        f.append(_callout(str(cd["note"]), st, "info", W))
    return f


# ---------------------------------------------------------------------------
# 08 Trend over recent flights
# ---------------------------------------------------------------------------
def _s08(rep: dict, st: dict, W: float) -> list:
    f = _section("08", "TREND OVER RECENT FLIGHTS", st, W)
    series = (rep.get("trend", {}) or {}).get("series", []) or []
    if not series:
        f.append(_callout(
            "Fewer than two flights of history are held for this engine, so no "
            "trend can be computed. A single reading is not a trend.",
            st, "info", W))
        return f

    cw, iw = W - 62 * mm, 58 * mm
    cells = []
    for s in series[:3]:
        pts = [(float(p[0]), float(p[1])) for p in s.get("points", [])]
        # A per-100-hour rate is quoted only when enough hours support it.
        # Otherwise the OBSERVED change and the span it was seen over, which is
        # what the flights actually showed -- scaling 24 minutes of flying to
        # 100 hours is an extrapolation of 250x, and printed beside a measured
        # value it reads as one.
        rate = s.get("drift_per_100h")
        unit = s.get("unit", "")
        if rate is None:
            rows = [
                ("Change observed", f'{s.get("change", 0):+.2f} {unit}'.strip()),
                ("Over", _num(s.get("span_hours"), 2, "flight hours")),
                ("Rate per 100 h", "not yet -- too few hours"),
                ("Points", str(len(pts))),
            ]
        else:
            rows = [
                ("Drift rate", f'{rate:+.2f} {unit} per 100 h'.strip()),
                ("Measured over", _num(s.get("span_hours"), 1, "h")),
                # A channel drifting away from its limit has no crossing to
                # quote, and "---" there read as a figure nobody computed.
                ("Reaches limit in",
                 _num(s.get("reach_limit_h"), 0, "h")
                 if s.get("reach_limit_h") is not None else "not approaching"),
                ("Points", str(len(pts))),
            ]
        info = _kv(rows, 28 * mm, iw - 28 * mm, size=7.2)
        cells.append([_trend_panel(pts, title=s.get("name", ""),
                                   w=cw, h=52 * mm), info])
    grid = Table(cells, colWidths=[cw, iw], hAlign="LEFT")
    grid.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    f.append(grid)
    f.append(Spacer(1, 3 * mm))
    enough = any(x.get("drift_per_100h") is not None for x in series[:3])
    f.append(_callout(
        "Each point is one flight's stabilised cruise reading, corrected to "
        "standard day and expressed as a delta from the post-overhaul "
        "baseline. The line is a least-squares fit through them."
        + ("" if enough else
           " <b>These flights span too few hours for a per-100-hour rate to "
           "mean anything</b>, so the change actually observed is reported "
           "instead of a projection built on it."),
        st, "info" if enough else "warn", W))
    return f


# ---------------------------------------------------------------------------
# 09 Engine health indices
# ---------------------------------------------------------------------------
def _s09(rep: dict, st: dict, W: float) -> list:
    h = rep.get("health", {}) or {}
    chi = h.get("chi")
    band, action = band_for(chi)
    f = _section("09", "ENGINE HEALTH INDICES", st, W)

    bands = [["Range", "Band", "Action"]]
    for floor, label, act in HEALTH_BANDS:
        bands.append([f"{floor:.2f} and above" if floor else "below 0.50",
                      label, act])
    top = Table([[
        _health_ring(chi, band),
        _table(bands, [26 * mm, 24 * mm, 46 * mm], zebra=True, size=7.2),
    ]], colWidths=[W - 100 * mm, 100 * mm], hAlign="LEFT")
    top.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    f.append(Paragraph("9.1 Overall Health Index", st["h3"]))
    f.append(top)
    f.append(Spacer(1, 2 * mm))
    # The band's own action, and the plan's beside it: "GOOD. No action
    # required." above costed jobs in Section 15 contradicted the document.
    # The composite is a blend, so an individual finding can call for work
    # the blend does not, and the callout says which is which.
    n_act = len(rep.get("actions") or [])
    good = band in ("EXCELLENT", "GOOD")
    tail = ""
    if n_act and good:
        tail = (f" The overall index alone calls for no action, but {n_act} "
                f"action{'s' if n_act > 1 else ''} raised by individual "
                f"findings {'are' if n_act > 1 else 'is'} listed in "
                f"Section 15.")
    f.append(_callout(f"Overall index <b>{_num(chi, 2)}</b>, band "
                      f"<b>{band}</b>. {action}.{tail}",
                      st, ("info" if n_act else "ok") if good else "warn", W))

    f.append(Paragraph("9.2 Subsystem Health Indices", st["h3"]))
    prev = rep.get("health_previous", {}) or {}
    rows = [["Subsystem and contributing indicator", "Index", "Band",
             "Change Since Previous Flight"]]
    flagged = []
    cell = _styles()["cell"]

    def _row(k, label, sub):
        v = h.get(k)
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return
        b, _ = band_for(v)
        p = prev.get(k)
        delta = ("---" if not isinstance(p, (int, float))
                 else f"{float(v) - float(p):+.2f}")
        text = (f"&nbsp;&nbsp;&nbsp;&nbsp;{label}" if sub else f"<b>{label}</b>")
        rows.append([Paragraph(text, cell), _num(v, 2), b, delta])
        if float(v) < 0.70:
            flagged.append((len(rows) - 1, colors.HexColor("#fdf3e6")))

    # Each subsystem, then the indices it is the minimum of. The health block
    # holds both under short and long names; tabulating every key printed each
    # subsystem twice and the EGT efficiency factor as a CRITICAL subsystem.
    shown = set()
    for key, label, parts in HEALTH_TREE:
        _row(key, label, False)
        shown.add(key)
        for k, name in parts:
            _row(k, name, True)
            shown.add(k)
    # Any other named subsystem a payload carries (a hand-written or older one)
    # is still listed, once, under its own name.
    for k in sorted(h):
        if k in shown or k in _NOT_AN_INDEX or k not in SUBSYSTEM_NAMES:
            continue
        if SUBSYSTEM_NAMES[k] in {r for r, _, _ in
                                  ((lbl, 0, 0) for _, lbl, _ in HEALTH_TREE)}:
            continue
        # The same index under its short name listed Electrical twice.
        if _SAME_AS.get(k) in shown:
            continue
        _row(k, SUBSYSTEM_NAMES[k], False)
    f.append(_table(rows, [W - 105 * mm, 25 * mm, 30 * mm, 50 * mm],
                    zebra=True, align_right=[1, 3], colour_rows=flagged,
                    size=7.8))
    return f


# ---------------------------------------------------------------------------
# 10 Fault detection results -- PS section C, all eight
# ---------------------------------------------------------------------------
def _s10(rep: dict, st: dict, W: float) -> list:
    fr = rep.get("flight_record", {}) or {}
    dq = fr.get("data_quality", {}) or {}
    dead = set(dq.get("invalid_channels", []) or [])
    found = {str(d.get("name")): d for d in (rep.get("faults", []) or [])}
    f = _section("10", "FAULT DETECTION RESULTS", st, W)

    f.append(Paragraph("10.1 All Eight Monitored Fault Modes", st["h3"]))
    rows = [["Fault Type", "Indicator", "Measured", "Limit", "Status",
             "Time to Action"]]
    colour_rows, blind, reached, trending = [], [], [], []
    bold_rows: list[int] = []
    cell = _styles()["cell"]

    for i, (key, label) in enumerate(PS_FAULTS, start=1):
        ch = FAULT_CHANNEL.get(key)
        if ch and ch in dead:
            rows.append([label, "---", "---", "---", "Not assessable", "---"])
            colour_rows.append((i, _BAND))
            blind.append(label)
            continue

        d = found.get(key) or {}
        status = str(d.get("status") or "no data")
        unit = d.get("unit") or ""
        hta = d.get("hours_to_action")
        # A correlation or ratio with no unit needs two places: at one, 0.76
        # against a limit of 0.85 printed as "0.8 against 0.8, REACHED".
        dec = 2 if not unit else 1
        if hta is not None:
            when = _num(hta, 1, "h")
        else:
            when = {"reached": "Now", "trending": "Not yet projected",
                    "not trending": "None projected",
                    "improving": "None projected"}.get(status, "---")
        rows.append([
            label,
            Paragraph(str(d.get("indicator") or "---"), cell),
            _num(d.get("value"), dec, unit),
            _num(d.get("threshold"), dec, unit),
            status.upper(),
            when,
        ])
        if status == "reached":
            colour_rows.append((i, _PALE_W))
            # Bold as well as tinted: a pale row among pale rows is not
            # something a reader's eye stops at.
            bold_rows.append(i)
            reached.append(label)
        elif status == "trending":
            colour_rows.append((i, colors.HexColor("#fdf3e6")))
            trending.append(label)

    f.append(_table(rows, [W - 150 * mm, 38 * mm, 24 * mm, 24 * mm,
                           31 * mm, 25 * mm],
                    colour_rows=colour_rows, highlight=bold_rows,
                    align_right=[2, 3, 5], size=7.2))

    f.append(Spacer(1, 4 * mm))
    if reached:
        f.append(_callout(
            "<b>Indicator limit reached: " + ", ".join(reached) + ".</b> "
            "The measured indicator has crossed the limit this system raises "
            "the mode at. See section 15.", st, "warn", W))
    elif trending:
        f.append(_callout(
            "No mode has reached its limit. <b>" + ", ".join(trending)
            + "</b> is moving toward one, with the time-to-action shown above.",
            st, "caution" if False else "info", W))
    else:
        f.append(_callout(
            "No monitored fault mode has reached or is trending toward its "
            "limit on this flight.", st, "ok", W))

    if blind:
        f.append(Spacer(1, 3 * mm))
        f.append(_callout(
            "The channel" + ("s" if len(dead) > 1 else "") + " "
            + ", ".join(sorted(dead)) + " could not be read on this flight "
            "(see Section 13), so " + ", ".join(blind) + " could not be "
            "assessed. This is not a negative finding.", st, "warn", W))
    return f


# ---------------------------------------------------------------------------
# 11 Remaining life and failure risk
# ---------------------------------------------------------------------------
# Where a remaining-life figure came from, in words.
_RUL_SOURCE = {
    "physics_fallback": "physics model, from this engine's health trend",
    "physics": "physics model, from this engine's health trend",
    "network": "trained LSTM network on this engine's history",
    "lstm": "trained LSTM network on this engine's history",
    "fused": "LSTM network and physics model combined",
}


def _s11(rep: dict, st: dict, W: float) -> list:
    r = rep.get("remaining_life", {}) or {}
    m = rep.get("mission", {}) or {}
    f = _section("11", "REMAINING LIFE AND<br/>FAILURE RISK", st, W)

    f.append(Paragraph("11.1 Estimated Remaining Useful Life (RUL)", st["h3"]))
    if not r.get("reportable", True) or r.get("hours") is None:
        f.append(_callout(
            "<b>Not reportable.</b> No RUL estimate was produced for this flight. "
            + str(r.get("reason", "the model declined to produce one")),
            st, "warn", W))
    else:
        hrs = float(r["hours"])
        dec = 1 if hrs < 10 else 0
        src = str(r.get("source") or "")
        phys = r.get("physics_hours")
        lo, hi = r.get("lower"), r.get("upper")
        # The prediction interval is the PHYSICS estimator's: the network is
        # served without a calibrated bound. Printed under the network's figure
        # it read as "44.6 h, interval 8 to 10 h" -- an interval that does not
        # contain its own estimate. So each figure is printed with the
        # estimator it came from, the interval beside the one it belongs to,
        # and the figure the maintenance triggers act on is named.
        lines = []
        if src:
            lines.append("Estimated by: "
                         + _RUL_SOURCE.get(src, src.replace("_", " ")))
        band_ok = lo is not None and hi is not None and src != "lstm"
        if src == "lstm" and isinstance(phys, (int, float)):
            pd = 1 if phys < 10 else 0
            lines.append(f"Physics model: {_num(phys, pd)} h"
                         + (f" (interval {_num(lo, pd)} to {_num(hi, pd)} h)"
                            if lo is not None and hi is not None else ""))
            lines.append("The network carries no calibrated interval. "
                         "Maintenance triggers act on the physics figure.")
        elif band_ok:
            lines.append(f"Prediction interval {_num(lo, dec)} to "
                         f"{_num(hi, dec)} h")
        # Always stated, measured or not: an interval is only as good as its
        # coverage. Where none was measured the page says so, instead of
        # printing a dash where the caveat belongs.
        cov = r.get("coverage")
        if isinstance(cov, (int, float)):
            pct = float(cov) * 100.0 if float(cov) <= 1.0 else float(cov)
            lines.append(f"Measured interval coverage: {pct:.0f} %")
        else:
            lines.append(("Physics interval coverage" if src == "lstm"
                          else "Interval coverage") + ": not yet measured")
        note = "<br/>".join(lines)
        head = Table([[
            Paragraph(f'{_num(hrs, dec)} flight hours', st["big"]),
            Paragraph(note, st["note"]),
        ]], colWidths=[W * 0.42, W * 0.58], hAlign="LEFT")
        head.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ]))
        f.append(head)
        # The band only when it belongs to the plotted estimate.
        f.append(_rul_curve(hrs, lo if band_ok else None,
                            hi if band_ok else None,
                            m.get("flight_hours"), w=W, h=66 * mm))

    surv = rep.get("survival", {}) or {}
    hz = surv.get("horizons", {}) or {}
    f.append(Paragraph("11.2 Probability of Failure (More Reliable)",
                       st["h3"]))
    if not hz:
        f.append(_callout(
            "No calibrated failure probability is available for this flight.",
            st, "info", W))
        return f
    def _hours(key: str) -> float:
        """The horizon as a number, from either spelling of the key.

        The serving layer keys these "12h"/"25h"/"50h"; a hand-written payload
        keys them "12"/"25"/"50". float() on the first spelling raises
        ValueError and takes the export down -- another failure that only
        appears on live data.
        """
        try:
            return float(str(key).rstrip("hH"))
        except ValueError:
            return float("inf")

    rows = [["Time Window", "Probability of Failure"]]
    for k in sorted(hz, key=_hours):
        h = _hours(k)
        label = (f"Within next {h:.0f} flight hours" if h != float("inf")
                 else f"Within next {k}")
        rows.append([label, f"{float(hz[k]) * 100:.1f} %"])
    f.append(_table(rows, [W - 60 * mm, 60 * mm], align_right=[1]))
    f.append(Spacer(1, 3 * mm))
    f.append(_callout(
        "Probability of failure is a more reliable indicator than the "
        "single-figure RUL estimate above, and should be used for dispatch "
        "decisions. The hours figure is close to its measured ceiling on this "
        "data; the probability is not.", st, "info", W))
    return f


# ---------------------------------------------------------------------------
# 12 Life consumed against limits
# ---------------------------------------------------------------------------
def _s12(rep: dict, st: dict, W: float) -> list:
    f = _section("12", "LIFE CONSUMED AGAINST LIMITS", st, W)
    items = rep.get("life_limits", []) or []
    if not items:
        f.append(_callout(
            "No life limits are configured for this engine, so consumption "
            "cannot be reported.", st, "warn", W))
        return f

    rows = [["Item", "Used", "Limit", "% Used"]]
    colour_rows, parts = [], []
    for it in items:
        used, lim = it.get("used"), it.get("limit")
        pct = (float(used) / float(lim) * 100.0) if used and lim else None
        row = [it.get("item", "---"), _num(used, 1, it.get("unit", "")),
               _num(lim, 0, it.get("unit", "")),
               "---" if pct is None else f"{pct:.1f} %"]
        (parts if it.get("life_limited") else rows).append(row)
        if pct is not None and pct >= 80.0:
            colour_rows.append((len(rows) - 1, _PALE_W))
    f.append(Paragraph("12.1 Overhaul and Calendar Limits", st["h3"]))
    f.append(_table(rows, [W - 105 * mm, 35 * mm, 35 * mm, 35 * mm],
                    zebra=True, align_right=[1, 2, 3],
                    colour_rows=colour_rows))
    if parts:
        f.append(Paragraph("12.2 Life-Limited Parts", st["h3"]))
        f.append(_table([["Part", "Used", "Limit", "% Used"]] + parts,
                        [W - 105 * mm, 35 * mm, 35 * mm, 35 * mm],
                        zebra=True, align_right=[1, 2, 3]))
    return f


# ---------------------------------------------------------------------------
# 13 Data quality -- what the report could NOT see
# ---------------------------------------------------------------------------
def _s13(rep: dict, st: dict, W: float) -> list:
    fr = rep.get("flight_record", {}) or {}
    dq = fr.get("data_quality", {}) or {}
    f = _section("13", "DATA QUALITY AND COVERAGE", st, W)

    gaps = dq.get("gaps", []) or []
    dead = dq.get("invalid_channels", []) or []
    gap_txt = ("None" if not gaps else
               f'{len(gaps)} gap{"s" if len(gaps) > 1 else ""}, '
               f'{_dur(dq.get("gap_seconds"))} total')
    f.append(_kv([
        ("Percentage of flight successfully recorded",
         f'{_num(dq.get("coverage_pct"), 1)} %'),
        ("Samples recorded", _num(dq.get("ticks"), 0)),
        ("Data dropouts", gap_txt),
        ("Sensors flagged invalid",
         "None" if not dead else ", ".join(dead)),
        ("Stabilised cruise reading captured",
         "Yes" if dq.get("cruise_datum_captured") else "No"),
    ], W - 55 * mm, 55 * mm))

    if gaps:
        f.append(Paragraph("13.2 Recording Gaps", st["h3"]))
        rows = [["From", "To", "Duration"]]
        for g in gaps[:12]:
            rows.append([_clock(g["from_s"]), _clock(g["to_s"]),
                         _dur(g["seconds"])])
        f.append(_table(rows, [W / 3, W / 3, W / 3], zebra=True))

    f.append(Spacer(1, 4 * mm))
    if dead:
        blind = [label for key, label in PS_FAULTS
                 if FAULT_CHANNEL.get(key) in set(dead)]
        f.append(_callout(
            "<b>This report did not see everything.</b> "
            + ", ".join(dead) + " produced no reading for the whole flight"
            + (f", so {', '.join(blind)} could not be assessed in Section 10."
               if blind else ".")
            + " A finding of 'not detected' for those is not available.",
            st, "warn", W))
    else:
        f.append(_callout(
            "All monitored channels produced readings for this flight. No "
            "finding in this report is limited by missing data.",
            st, "ok", W))
    return f


# ---------------------------------------------------------------------------
# 14 Mission replay and simulation
# ---------------------------------------------------------------------------
def _s14(rep: dict, st: dict, W: float) -> list:
    f = _section("14", "MISSION REPLAY AND SIMULATION", st, W)
    rp = rep.get("replay", {}) or {}

    f.append(Paragraph("14.1 Mission Replay", st["h3"]))
    f.append(_callout(
        "<b>REPLAYED DATA -- NOT LIVE.</b> Every value below was recorded "
        "during the flight named on the cover and re-computed through the "
        "twin. It is not a current reading.", st, "warn", W))
    f.append(Spacer(1, 3 * mm))
    if rp.get("track"):
        f.append(_track_map(rp.get("track"), W, 62 * mm))
    else:
        # No navigation track exists for this sortie -- the recorder keeps
        # engine channels, not position -- and inventing one would put a
        # fabricated flight path into a maintenance record. The recorded
        # altitude profile is what replay actually re-runs, so that is shown.
        prof = rep.get("profile", {}) or {}
        alt = [(p[0], p[1]) for p in prof.get("altitude_ft", [])]
        if alt:
            f.append(_overlay(
                alt, [(p[0], p[1]) for p in prof.get("airspeed_kt", [])] or alt,
                w=W, h=58 * mm, label_a="Altitude (ft)",
                label_b="Airspeed (kt)", title="", dual_scale=True))
            f.append(Paragraph(
                "Recorded altitude and airspeed profile, available for replay. "
                "No position track is drawn: the recorder keeps engine "
                "channels, not navigation.", st["note"]))
        else:
            f.append(_track_map(None, W, 62 * mm))
    f.append(Spacer(1, 3 * mm))
    f.append(_kv([
        ("Recording ID", rp.get("recording_id", "---")),
        ("Time range (UTC)", rp.get("window", "---")),
        ("Samples available", _num(rp.get("samples"), 0)),
        ("Replay available at", rp.get("href", "---")),
    ], 62 * mm, W - 62 * mm))

    f.append(Paragraph("14.2 What-If Simulation (Digital Twin)", st["h3"]))
    rows = [["Scenario", "Result"]]
    for s in rep.get("whatif", []) or []:
        rows.append([s.get("scenario", "---"),
                     Paragraph(str(s.get("result", "---")),
                               _styles()["cell"])])
    if len(rows) == 1:
        f.append(_callout(
            "No what-if scenarios were run against this flight.",
            st, "info", W))
    else:
        f.append(_table(rows, [W * 0.42, W * 0.58], zebra=True, size=7.8))
    return f


# ---------------------------------------------------------------------------
# 15 Maintenance actions, review and sign-off
# ---------------------------------------------------------------------------
def _s15(rep: dict, st: dict, W: float) -> list:
    fr = rep.get("flight_record", {}) or {}
    f = _section("15", "MAINTENANCE ACTIONS,<br/>REVIEW AND SIGN-OFF", st, W)

    f.append(Paragraph("15.1 Recommended Actions", st["h3"]))
    acts = rep.get("actions", []) or []
    adv = rep.get("advisory", {}) or {}
    if not acts and adv.get("action"):
        acts = [{"action": adv["action"], "ata": adv.get("ata", "---"),
                 "deadline": adv.get("deadline", "---"),
                 "cost": adv.get("cost", "---"),
                 "evidence": adv.get("reason", "---")}]
    if not acts:
        f.append(_callout("No maintenance action is recommended arising from "
                          "this flight.", st, "ok", W))
    else:
        rows = [["Action", "ATA", "Deadline", "Est. Cost", "Evidence"]]
        cell = _styles()["cell"]
        for a in acts:
            rows.append([
                Paragraph(str(a.get("action") or "---"), cell),
                Paragraph(str(a.get("ata") or "---"), cell),
                Paragraph(str(a.get("deadline") or "---"), cell),
                Paragraph(str(a.get("cost") or "---"), cell),
                Paragraph(str(a.get("evidence", "---")), cell),
            ])
        f.append(_table(rows, [W - 128 * mm, 20 * mm, 28 * mm, 26 * mm,
                               54 * mm], zebra=True, size=7.4))

    # FRACAS: an uncleared alert without an action is an open loop, and the
    # document should say so rather than let it pass unremarked.
    open_alerts = [e for e in (fr.get("events", []) or [])
                   if e.get("cleared_s") is None]
    if open_alerts and not acts:
        f.append(Spacer(1, 3 * mm))
        f.append(_callout(
            f"<b>{len(open_alerts)} alert(s) were still active at landing and "
            f"no action has been raised against them.</b> This loop is open.",
            st, "warn", W))

    f.append(Paragraph("15.2 Review and Sign-Off", st["h3"]))
    # Header cells are Paragraphs so a long column name WRAPS instead of
    # running under its neighbour. A plain string in a narrow column does not
    # overflow visibly in reportlab -- it overprints, which is worse.
    hdr = ParagraphStyle("sh", fontName="Helvetica-Bold", fontSize=6.6,
                         leading=8.2, textColor=colors.white)
    blank = [[Paragraph(x, hdr) for x in (
        "Name and Role", "Date (UTC)",
        "Decision<br/>(no action / monitor / inspect / ground aircraft)",
        "Action Taken", "Deferred To", "Closure Ref.")]]
    for _ in range(3):
        blank.append(["", "", "", "", "", ""])
    t = _table(blank, [30 * mm, 22 * mm, W - 152 * mm, 30 * mm, 24 * mm,
                       24 * mm], size=7.0)
    t.setStyle(TableStyle([("ROWBACKGROUNDS", (0, 1), (-1, -1),
                            [colors.white]),
                           ("GRID", (0, 0), (-1, -1), 0.3, _RULE),
                           ("TOPPADDING", (0, 1), (-1, -1), 9),
                           ("BOTTOMPADDING", (0, 1), (-1, -1), 9)]))
    f.append(t)

    f.append(Paragraph("15.3 Record Information", st["h3"]))
    rp = rep.get("replay", {}) or {}
    f.append(_kv([
        ("Recording ID", rp.get("recording_id", "---")),
        ("Time range (UTC)", rp.get("window", "---")),
        ("Retention", rep.get("retention", "Retain for life of airframe")),
        ("Report integrity hash (SHA-256)", digest(rep)),
    ], 62 * mm, W - 62 * mm, size=7.4))
    f.append(Spacer(1, 3 * mm))
    f.append(_callout(
        "This document is a controlled maintenance record. The hash above "
        "ties this printout to the audit-log entry recording its export; it is "
        "not a signature and makes no claim about who produced either.",
        st, "info", W))
    return f


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
def _fr(rep: dict, key: str):
    return (rep.get("flight_record") or {}).get(key)


# Whether a section has a FINDING, decided from the payload rather than from
# the rendered flowables. Reading emptiness back out of the output would mean
# guessing which callouts count as content, and a section that says "no alert
# was raised" is a finding, not a blank.
#
# Sections 01, 09, 11, 13 and 15 have no predicate: identity, health,
# prognostics, coverage and the sign-off block are printed on every report
# whatever the flight did.
def _s00(rep: dict, st: dict, W: float) -> list:
    """Every finding of this flight, before the sections that show the working.

    The findings were all in the document -- a reached limit in section 10, an
    exceedance in 05, an alert still standing in 06, a drift in 08 -- each
    marked by a pale tint inside its own table. A reader had to assemble them.
    The first question anybody asks of a post-flight report is the one it
    answered nowhere: what did this flight find?

    No new evidence is introduced here. Every line names the section that
    carries the measurement it came from.
    """
    f = _section("00", "SUMMARY OF FINDINGS", st, W)
    cell = _styles()["cell"]
    fr = rep.get("flight_record", {}) or {}
    names = dict(PS_FAULTS)
    found = []                    # (rank, status, what, evidence, section)

    for d in rep.get("faults", []) or []:
        status = str(d.get("status") or "")
        if status not in ("reached", "trending"):
            continue
        unit = d.get("unit") or ""
        dec = 2 if not unit else 1
        ev = (f'{_num(d.get("value"), dec, unit)} against a '
              f'{_num(d.get("threshold"), dec, unit)} limit')
        hta = d.get("hours_to_action")
        if status == "trending" and hta is not None:
            ev += f', reaching it in {_num(hta, 1, "h")}'
        found.append((0 if status == "reached" else 2,
                      "LIMIT REACHED" if status == "reached" else "TRENDING",
                      names.get(str(d.get("name")), str(d.get("name"))),
                      ev, "10"))

    for e in fr.get("exceedances", []) or []:
        unit = e.get("unit", "")
        name = str(e.get("parameter", ""))
        found.append((1, f'EXCEEDANCE L{e.get("severity", 1)}',
                      name[:1].upper() + name[1:],
                      f'{_num(e.get("peak"), 1, unit)} against a '
                      f'{_num(e.get("limit"), 1, unit)} limit, '
                      f'{_dur(e.get("seconds_above"))} beyond it in '
                      f'{e.get("phase", "flight")}', "05"))

    for tr in (rep.get("trend") or {}).get("series", []) or []:
        reach = tr.get("reach_limit_h")
        if reach is None:
            continue
        found.append((2, "DRIFTING", str(tr.get("name", "")),
                      f'{tr.get("drift_per_100h", 0):+.0f} {tr.get("unit", "")} '
                      f'per 100 h across {len(tr.get("points") or [])} '
                      f'flights, reaching its limit in {_num(reach, 0, "h")}',
                      "08"))

    for e in (fr.get("events") or []):
        if e.get("cleared_s") is not None:
            continue
        found.append((3, "ALERT STANDING", str(e.get("legend", "")),
                      f'raised at {_clock(e.get("t_s"))} in '
                      f'{e.get("phase", "flight")}, still active at shutdown',
                      "06"))

    acts = rep.get("actions", []) or []
    # A certified-limit EXCEEDANCE is past a limit too (REP-07). Counting only
    # reached fault thresholds, a flight whose one problem was CHT at 145 degC
    # against a 135 degC limit got the calm "info" styling.
    reached = sum(1 for r, *_ in found if r in (0, 1))
    if not found:
        f.append(_callout(
            "No monitored limit was reached, no exceedance was recorded and "
            "no alert was standing at shutdown.", st, "ok", W))
    else:
        f.append(_callout(
            f'<b>{len(found)} finding{"s" if len(found) != 1 else ""} on this '
            f'flight</b>'
            + (f', {reached} at or past a limit' if reached else '')
            + (f'. {len(acts)} maintenance action'
               f'{"s" if len(acts) != 1 else ""} raised, costed and dated in '
               f'Section 15.' if acts
               else '. No maintenance action was raised.'),
            st, "warn" if reached else "info", W))

    if found:
        f.append(Spacer(1, 5 * mm))
        f.append(Paragraph("0.1 What This Flight Found", st["h3"]))
        rows = [["Status", "Finding", "Evidence", "Shown in"]]
        colour, bold = [], []
        for i, (rank, status, what, ev, where) in enumerate(
                sorted(found, key=lambda x: x[0]), start=1):
            rows.append([Paragraph(f"<b>{status}</b>", cell),
                         Paragraph(what, cell), Paragraph(ev, cell),
                         f"Section {where}"])
            colour.append((i, _PALE_W if rank <= 1
                           else colors.HexColor("#fdf3e6")))
            if rank <= 1:
                bold.append(i)
        f.append(_table(rows, [30 * mm, 40 * mm, W - 92 * mm, 22 * mm],
                        colour_rows=colour, highlight=bold, size=7.6))

    h = rep.get("health", {}) or {}
    r = rep.get("remaining_life", {}) or {}
    hz = (rep.get("survival") or {}).get("horizons") or {}
    p25 = hz.get("25h", hz.get("25"))
    rul = "---" if r.get("hours") is None else _num(r.get("hours"), 0, "h")
    phys = r.get("physics_hours")
    if isinstance(phys, (int, float)):
        rul += f' by the network, {_num(phys, 0, "h")} by the physics model'
    f.append(Spacer(1, 5 * mm))
    f.append(Paragraph("0.2 Headline Figures", st["h3"]))
    f.append(_kv([
        ("Overall health index",
         f'{_num(h.get("chi"), 2)}  {h.get("band", "")}'.strip()),
        ("Remaining useful life", rul),
        ("Probability of failure within 25 flight hours",
         "---" if p25 is None else f"{float(p25) * 100:.1f} %"),
        ("Maintenance actions raised", str(len(acts))),
    ], 78 * mm, W - 78 * mm))
    return f


_HAS_FINDING = {
    "02": lambda r: bool((_fr(r, "usage") or {}).get("phases")),
    "03": lambda r: any((r.get("history") or {}).values()),
    "04": lambda r: bool(_fr(r, "twin_vs_actual")),
    "05": lambda r: bool(_fr(r, "exceedances")),
    "06": lambda r: bool(_fr(r, "events")),
    "07": lambda r: bool(_fr(r, "cruise_datum")),
    "08": lambda r: bool((r.get("trend") or {}).get("series")),
    "10": lambda r: bool(r.get("faults")),
    "12": lambda r: bool(r.get("life_limits")),
    "14": lambda r: bool(r.get("replay") or r.get("whatif")),
}

SECTIONS = (
    # 00 first: the findings, ahead of the sections that evidence them.
    ("00", _s00), ("01", _s01), ("02", _s02), ("03", _s03), ("04", _s04), ("05", _s05),
    ("06", _s06), ("07", _s07), ("08", _s08), ("09", _s09), ("10", _s10),
    ("11", _s11), ("12", _s12), ("13", _s13), ("14", _s14), ("15", _s15),
)


def _has_finding(report: dict, number: str) -> bool:
    test = _HAS_FINDING.get(number)
    return test is None or bool(test(report))


def _partition(report: dict):
    """(sections with a finding, sections without), both in numeric order.

    Kept because the emptiness decision is worth testing on its own, but the
    document no longer REORDERS around it -- see build().
    """
    told, silent = [], []
    for number, fn in SECTIONS:
        (told if _has_finding(report, number) else silent).append((number, fn))
    return told, silent


def build(report: dict) -> bytes:
    """Render the post-flight report.

    EVERY section is emitted whether or not it has data -- a missing section
    reads as "nothing to say", where one that states "no exceedances were
    observed" is a finding, and that difference is why 05, 13 and 15.2 are
    unconditional.

    But a finding-free section does not get a page to itself. Sections with
    something to report come first, one per page; the silent ones are packed
    together at the back. Their NUMBERS do not move: a maintainer refers to a
    finding by its section, and "05" is Limit Exceedances in every report this
    system produces.

    Built twice. The first pass exists only to count pages, because the footer
    says "07 / 16" and the total is not known until the story has been laid
    out -- and a page count that is wrong is worse than none, since it is the
    reader's only check that no page is missing from a filed document.
    """
    if not AVAILABLE:  # pragma: no cover
        raise RuntimeError(UNAVAILABLE_MESSAGE)

    pages = _render(report, total=None)[1]
    return _render(report, total=pages)[0]


def _render(report: dict, *, total: int | None) -> tuple[bytes, int]:
    buf = io.BytesIO()
    m = 15 * mm
    W = A4[0] - 2 * m
    st = _styles()
    mission = str(report.get("mission_id", report.get("twin_id", "---")))

    # Provenance goes in the TITLE, which is what a PDF reader shows in its
    # window chrome and what a file manager indexes -- not only in the body,
    # where it can be scrolled past. A synthetic report that reads like a real
    # one is a forgery waiting to happen.
    simulated = " [SIMULATED]" if report.get("faults_injected") else ""
    # Creator names the software that produced the file. ReportLab leaves it
    # as the literal string "(unspecified)", which is what a reader sees under
    # File > Properties -- an unfinished-looking field on a document that gets
    # filed against an airframe. It carries the build version for the same
    # reason section 15 does: a finding has to be traceable to the software
    # that made it. Keywords are what a document management system indexes on,
    # so the mission and the airframe belong there and not only in the body.
    doc = BaseDocTemplate(
        buf, pagesize=A4,
        leftMargin=m, rightMargin=m, topMargin=m + 6 * mm,
        bottomMargin=m + 4 * mm,
        title=f"Post-Flight Engine Health Report {mission}{simulated}",
        author="DRDO Digital Twin Ground Station",
        subject="Mission-wise engine health report",
        creator=("DRDO Engine Digital Twin Ground Station "
                 f"{report.get('gcs_version', '---')}"),
        keywords=[k for k in (
            mission,
            str(report.get("twin_id", "")),
            str(report.get("classification", "")),
            "post-flight", "engine health", "condition monitoring",
        ) if k],
        # Show the report title in the reader's window bar instead of the
        # filename, which is a generated string nobody can read.
        displayDocTitle=True,
        lang="en-IN",
    )
    frame = Frame(m, m + 4 * mm, W, A4[1] - 2 * m - 10 * mm, id="body",
                  leftPadding=0, rightPadding=0,
                  topPadding=0, bottomPadding=0)
    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[
            Frame(m, m, W, A4[1] - 2 * m, id="cover", leftPadding=0,
                  rightPadding=0, topPadding=0, bottomPadding=0)],
                     onPage=_cover_painter(
                         report.get("cover_background", COVER_BG))),
        PageTemplate(id="inner", frames=[frame],
                     onPage=_Furniture(mission, total)),
    ])

    story: list = []
    story += _cover(report, st, W)
    story.append(NextPageTemplate("inner"))
    story.append(PageBreak())

    # STRICT NUMERIC ORDER, 01 to 15.
    #
    # An earlier version moved the sections with findings to the front and
    # grouped the silent ones at the back. It did remove the blank pages, and
    # it made the document unreadable: page seven carried section 12 and the
    # last page carried 05, 06 and 08, so a reader flipping through saw the
    # numbers jump. A report is read in order, and a maintainer citing
    # "section 5" expects it in the fifth position.
    #
    # The blank-page problem is solved instead by not giving a section its own
    # page when it has nothing to say: a silent section follows the previous
    # one down the page, and only a section with a finding starts a new one.
    prev_had_finding = True
    for i, (number, section) in enumerate(SECTIONS):
        mine = _has_finding(report, number)
        if i:
            if mine or prev_had_finding:
                story.append(PageBreak())
            else:
                # Two silent sections in a row share the page.
                story.append(Spacer(1, 7 * mm))
        story += section(report, st, W)
        prev_had_finding = mine

    doc.build(story)
    return buf.getvalue(), doc.page


__all__ = ["AVAILABLE", "HEALTH_BANDS", "PS_FAULTS", "TOTAL_PAGES",
           "UNAVAILABLE_MESSAGE", "band_for", "build", "digest"]
