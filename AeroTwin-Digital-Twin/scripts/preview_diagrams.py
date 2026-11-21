# -*- coding: utf-8 -*-
"""Render the generated .drawio files to a single HTML page of SVGs.

Not a general drawio renderer -- it understands only the shapes this project's
generator emits (rounded rectangles, rhombus decision nodes, plain text and
orthogonal block-arrow edges). It exists so the diagrams can be checked in a
browser without installing drawio, which is the difference between "the
geometry validates" and "it actually looks right".

    python scripts/preview_diagrams.py [file.drawio]
        ->  docs/diagrams/preview.html, or <file>.preview.html
"""
import html
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "docs" / "diagrams"
OUT = SRC / "preview.html"


def style_dict(s):
    d = {}
    for part in (s or "").split(";"):
        if "=" in part:
            k, _, v = part.partition("=")
            d[k] = v
    return d


def lines(value):
    """drawio labels are escaped HTML. Return (text, size, colour, bold).

    A <font> can span several <br>-separated lines, so the style has to be
    carried across the break rather than re-read per line -- doing the latter
    silently renders every line but the first in the wrong colour, which is a
    convincing-looking bug because the first line is correct.
    """
    v = html.unescape(value or "")
    out, buf = [], ""
    size = colour = None
    bold = False
    # The style is captured when a line's text STARTS, not when it ends -- the
    # closing </font> comes after the text it styles, so reading the state at
    # flush time loses it on the last line of every chip.
    pending = (None, None, False)
    for tok in re.split(r"(<[^>]+>)", v):
        if not tok:
            continue
        if not tok.startswith("<"):
            if not buf.strip() and tok.strip():
                pending = (size, colour, bold)
            buf += tok
            continue
        t = tok.lower()
        if t.startswith("<br"):
            out.append((buf.strip(),) + pending)
            buf = ""
        elif t.startswith("<b>"):
            bold = True
        elif t.startswith("</b>"):
            bold = False
        elif t.startswith("<font"):
            m = re.search(r"font-size:\s*(\d+)", tok)
            size = int(m.group(1)) if m else size
            m = re.search(r"color:\s*(#[0-9A-Fa-f]{3,8})", tok)
            colour = m.group(1) if m else colour
            if "font-weight:normal" in tok.replace(" ", ""):
                bold = False
        elif t.startswith("</font"):
            size = colour = None
    out.append((buf.strip(),) + pending)
    return [ln for ln in out if ln[0]]


def rounded(x, y, w, h, fill, stroke, sw, arc):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{arc}" '
            f'ry="{arc}" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="{sw}"/>')


def anchor(box, fx, fy):
    x, y, w, h = box
    return x + fx * w, y + fy * h


def render(model):
    pw = int(model.get("pageWidth"))
    ph = int(model.get("pageHeight"))
    parts = [f'<svg viewBox="0 0 {pw} {ph}" width="100%" '
             f'style="background:#FFFFFF;border:1px solid #ccd">']
    geo = {}
    shapes, edges = [], []
    for c in model.iter("mxCell"):
        g = c.find("mxGeometry")
        if c.get("edge") == "1":
            edges.append(c)
            continue
        if g is None or c.get("vertex") != "1":
            continue
        try:
            box = (float(g.get("x")), float(g.get("y")),
                   float(g.get("width")), float(g.get("height")))
        except (TypeError, ValueError):
            continue
        geo[c.get("id")] = box
        shapes.append((c, box))

    for c, (x, y, w, h) in shapes:
        st = style_dict(c.get("style"))
        fill = st.get("fillColor", "none")
        stroke = st.get("strokeColor", "none")
        sw = st.get("strokeWidth", "1")
        is_text = c.get("style", "").startswith("text;")
        if "rhombus" in c.get("style", ""):
            cx, cy = x + w / 2, y + h / 2
            parts.append(
                f'<polygon points="{cx},{y} {x + w},{cy} {cx},{y + h} {x},{cy}"'
                f' fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')
        elif not is_text:
            arc = 8 if st.get("rounded") == "1" else 0
            parts.append(rounded(x, y, w, h, fill, stroke, sw, arc))

        ls = lines(c.get("value"))
        if not ls:
            continue
        base_fs = float(st.get("fontSize", 12))
        fc = st.get("fontColor", "#000000")
        align = st.get("align", "center")
        valign = st.get("verticalAlign", "middle")
        mono = st.get("fontFamily") == "Courier New"
        pad = float(st.get("spacingLeft", 0) or 0)
        tx = {"left": x + pad + 2, "center": x + w / 2,
              "right": x + w - 4}[align]
        ta = {"left": "start", "center": "middle", "right": "end"}[align]

        # drawio wraps (whiteSpace=wrap). Approximate it, otherwise every long
        # sentence looks like it overflows its chip and the preview cannot
        # distinguish that from a chip that genuinely is too small.
        if "whiteSpace=wrap" in (c.get("style") or ""):
            wrapped = []
            for txt, size, col, bold in ls:
                fs = size or base_fs
                per = max(8, int((w - 2 * max(pad, 8)) / (fs * 0.52)))
                words, cur = txt.split(), ""
                for word in words:
                    trial = f"{cur} {word}".strip()
                    if len(trial) > per and cur:
                        wrapped.append((cur, size, col, bold))
                        cur = word
                    else:
                        cur = trial
                wrapped.append((cur, size, col, bold))
            ls = wrapped

        heights = [(s or base_fs) * 1.32 for _, s, _, _ in ls]
        total = sum(heights)
        if valign == "top":
            cy = y + float(st.get("spacingTop", 4) or 4) + heights[0] * 0.78
        else:
            cy = y + (h - total) / 2 + heights[0] * 0.78
        for (txt, size, col, bold), lh in zip(ls, heights):
            fs = size or base_fs
            colour = col or fc
            weight = "700" if (bold or st.get("fontStyle") == "1") else "400"
            fam = ("ui-monospace,Consolas,monospace" if mono
                   else "Segoe UI,Helvetica,Arial,sans-serif")
            parts.append(
                f'<text x="{tx:.0f}" y="{cy:.0f}" font-size="{fs}" '
                f'fill="{colour}" font-weight="{weight}" '
                f'font-family="{fam}" text-anchor="{ta}">'
                f'{html.escape(txt)}</text>')
            cy += lh

    parts.append('<defs><marker id="a" markerWidth="7" markerHeight="7" '
                 'refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 z" '
                 'fill="context-stroke"/></marker></defs>')
    for e in edges:
        s, t = geo.get(e.get("source")), geo.get(e.get("target"))
        if not s or not t:
            continue
        st = style_dict(e.get("style"))
        col = st.get("strokeColor", "#888")
        sw = st.get("strokeWidth", "1")
        x1, y1 = anchor(s, float(st.get("exitX", 0.5)),
                        float(st.get("exitY", 1)))
        x2, y2 = anchor(t, float(st.get("entryX", 0.5)),
                        float(st.get("entryY", 0)))
        if abs(y1 - y2) < 2 or abs(x1 - x2) < 2:
            d = f"M{x1:.0f},{y1:.0f} L{x2:.0f},{y2:.0f}"
        elif float(st.get("exitY", 1)) in (0.0, 1.0):
            my = (y1 + y2) / 2
            d = (f"M{x1:.0f},{y1:.0f} L{x1:.0f},{my:.0f} "
                 f"L{x2:.0f},{my:.0f} L{x2:.0f},{y2:.0f}")
        else:
            mx = (x1 + x2) / 2
            d = (f"M{x1:.0f},{y1:.0f} L{mx:.0f},{y1:.0f} "
                 f"L{mx:.0f},{y2:.0f} L{x2:.0f},{y2:.0f}")
        parts.append(f'<path d="{d}" fill="none" stroke="{col}" '
                     f'stroke-width="{sw}" marker-end="url(#a)"/>')
    parts.append("</svg>")
    return "\n".join(parts)


book = Path(sys.argv[1]) if len(sys.argv) > 1 else SRC / "ps26054_diagrams.drawio"
if len(sys.argv) > 1:
    OUT = book.with_suffix(".preview.html")
root = ET.parse(book).getroot()
body = []
for d in root.findall("diagram"):
    body.append(f"<h2>{html.escape(d.get('name'))}</h2>")
    body.append(render(d.find("mxGraphModel")))

OUT.write_text(
    "<title>PS 26054 diagram preview</title>"
    "<style>body{font:14px Segoe UI,Arial;margin:24px;background:#EEF1F4;"
    "color:#14212F}h2{margin:28px 0 8px;font-size:15px;letter-spacing:.06em;"
    "text-transform:uppercase;color:#44566B}svg{display:block}</style>"
    "<h1 style='font-size:19px'>PS 26054 &mdash; diagram preview</h1>"
    "<p style='color:#44566B'>Approximate render of "
    "<code>ps26054_diagrams.drawio</code>. Open the .drawio itself for the "
    "real thing; this is for checking layout at a glance.</p>"
    + "\n".join(body), encoding="utf-8")
print(f"Saved {OUT}")
