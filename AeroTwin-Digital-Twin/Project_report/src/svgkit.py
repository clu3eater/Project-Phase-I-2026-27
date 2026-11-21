"""A small SVG drawing kit for the report's diagrams.

Every diagram is drawn on a canvas about 760 px wide, which the report scales
to the 5.75 in text width (0.545 pt per px). Text is therefore kept at 13 px or
more so it prints at about 7 pt or larger.
"""
from __future__ import annotations

from html import escape

FONT = "Arial, Helvetica, sans-serif"
INK = "#111111"
GREY = "#f3f3f3"
BLUE = "#e7eef9"
AMBER = "#fdf1d6"
GREEN = "#e6f3e6"
DARK = "#1f3a5f"


def text_width(s: str, size: float, bold: bool = False) -> float:
    """Rough width of Arial text, used only to size label backgrounds."""
    return len(s) * size * (0.56 if bold else 0.52)


class Svg:
    def __init__(self, w: int, h: int) -> None:
        self.w, self.h = w, h
        self.els: list[str] = []

    # ---- primitives -------------------------------------------------------
    def rect(self, x, y, w, h, *, fill="#fff", stroke=INK, sw=1.6, rx=0, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.els.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
                        f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')

    def text(self, x, y, s, *, size=14, bold=False, anchor="middle", fill=INK,
             italic=False, family=FONT):
        st = ' font-style="italic"' if italic else ""
        wt = ' font-weight="bold"' if bold else ""
        self.els.append(f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}"'
                        f'{wt}{st} text-anchor="{anchor}" fill="{fill}">{escape(s)}</text>')

    def lines(self, x, y, rows, *, size=14, lh=None, bold=False, anchor="middle", fill=INK,
              italic=False, family=FONT):
        lh = lh or size * 1.25
        for i, r in enumerate(rows):
            self.text(x, y + i * lh, r, size=size, bold=bold, anchor=anchor, fill=fill,
                      italic=italic, family=family)

    def line(self, x1, y1, x2, y2, *, sw=1.6, dash=None, head=None, tail=None, stroke=INK):
        self.path(f"M{x1},{y1} L{x2},{y2}", sw=sw, dash=dash, head=head, tail=tail, stroke=stroke)

    def poly(self, pts, *, sw=1.6, dash=None, head="arrow", tail=None, stroke=INK):
        d = "M" + " L".join(f"{x},{y}" for x, y in pts)
        self.path(d, sw=sw, dash=dash, head=head, tail=tail, stroke=stroke)

    def path(self, d, *, sw=1.6, dash=None, head=None, tail=None, stroke=INK, fill="none"):
        a = f' stroke-dasharray="{dash}"' if dash else ""
        if head:
            a += f' marker-end="url(#{head})"'
        if tail:
            a += f' marker-start="url(#{tail})"'
        self.els.append(f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{a}/>')

    def label(self, x, y, s, *, size=12.5, bold=False, bg="#fff", fill=INK, anchor="middle"):
        """Text on a small white plate, for labels that sit on a connector."""
        w = text_width(s, size, bold) + 8
        x0 = x - w / 2 if anchor == "middle" else (x - 4 if anchor == "start" else x - w + 4)
        self.rect(x0, y - size + 1, w, size + 5, fill=bg, stroke="none", sw=0)
        self.text(x, y + 1, s, size=size, bold=bold, anchor=anchor, fill=fill)

    def ellipse(self, cx, cy, rx, ry, *, fill="#fff", stroke=INK, sw=1.6):
        self.els.append(f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="{fill}" '
                        f'stroke="{stroke}" stroke-width="{sw}"/>')

    def circle(self, cx, cy, r, *, fill="#fff", stroke=INK, sw=1.6):
        self.els.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}" stroke="{stroke}" '
                        f'stroke-width="{sw}"/>')

    def polygon(self, pts, *, fill="#fff", stroke=INK, sw=1.6):
        p = " ".join(f"{x},{y}" for x, y in pts)
        self.els.append(f'<polygon points="{p}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')

    # ---- composite shapes ---------------------------------------------------
    def box(self, x, y, w, h, title, rows=(), *, fill="#fff", rx=6, tsize=14.5, size=13,
            stereo=None, sw=1.6, title_fill=INK):
        self.rect(x, y, w, h, fill=fill, rx=rx, sw=sw)
        n = len(rows) + 1 + (1 if stereo else 0)
        lh = size * 1.25
        block = (n - 1) * lh
        cy = y + h / 2 - block / 2 + tsize * 0.35
        if stereo:
            self.text(x + w / 2, cy, f"«{stereo}»", size=size - 1, italic=True, fill="#333")
            cy += lh
        self.text(x + w / 2, cy, title, size=tsize, bold=True, fill=title_fill)
        for i, r in enumerate(rows):
            self.text(x + w / 2, cy + (i + 1) * lh, r, size=size, fill="#222")

    def diamond(self, cx, cy, w, h, rows, *, size=13, fill=AMBER):
        self.polygon([(cx, cy - h / 2), (cx + w / 2, cy), (cx, cy + h / 2), (cx - w / 2, cy)],
                     fill=fill)
        lh = size * 1.2
        y0 = cy - (len(rows) - 1) * lh / 2 + size * 0.35
        for i, r in enumerate(rows):
            self.text(cx, y0 + i * lh, r, size=size)

    def actor(self, x, y, name, *, size=14):
        """UML stick figure; (x, y) is the top of the head."""
        self.circle(x, y + 10, 10, fill="#fff")
        self.line(x, y + 20, x, y + 48)
        self.line(x - 18, y + 30, x + 18, y + 30)
        self.line(x, y + 48, x - 14, y + 70)
        self.line(x, y + 48, x + 14, y + 70)
        for i, part in enumerate(name.split("\n")):
            self.text(x, y + 88 + i * size * 1.2, part, size=size, bold=True)

    def usecase(self, cx, cy, rows, *, rx=104, ry=26, size=13, fill="#fff"):
        self.ellipse(cx, cy, rx, ry, fill=fill)
        lh = size * 1.2
        y0 = cy - (len(rows) - 1) * lh / 2 + size * 0.35
        for i, r in enumerate(rows):
            self.text(cx, y0 + i * lh, r, size=size)

    def cylinder(self, x, y, w, h, rows, *, size=12.5, fill=GREY):
        ry = 8
        self.path(f"M{x},{y + ry} L{x},{y + h - ry} A{w / 2},{ry} 0 0 0 {x + w},{y + h - ry} "
                  f"L{x + w},{y + ry}", fill=fill)
        self.ellipse(x + w / 2, y + ry, w / 2, ry, fill=fill)
        lh = size * 1.2
        y0 = y + ry + (h - ry) / 2 - (len(rows) - 1) * lh / 2 + size * 0.35
        for i, r in enumerate(rows):
            self.text(x + w / 2, y0 + i * lh, r, size=size)

    def node3d(self, x, y, w, h, title, *, stereo="device", d=12, fill=GREY, size=14):
        """UML deployment node (a box with a 3-D top and side)."""
        self.polygon([(x, y), (x + d, y - d), (x + w + d, y - d), (x + w, y)], fill="#e2e2e2")
        self.polygon([(x + w, y), (x + w + d, y - d), (x + w + d, y + h - d), (x + w, y + h)],
                     fill="#d4d4d4")
        self.rect(x, y, w, h, fill=fill)
        self.text(x + 10, y + 20, f"«{stereo}»", size=size - 2, italic=True, anchor="start",
                  fill="#333")
        self.text(x + 10, y + 38, title, size=size, bold=True, anchor="start")

    def component(self, x, y, w, h, title, rows=(), *, fill=BLUE, size=13, tsize=14):
        """UML component: a box with «component» and the two-tab icon."""
        self.rect(x, y, w, h, fill=fill, rx=3)
        ix, iy = x + w - 24, y + 7
        self.rect(ix, iy, 16, 20, fill="#fff", sw=1.2)
        self.rect(ix - 5, iy + 4, 10, 4, fill="#fff", sw=1.2)
        self.rect(ix - 5, iy + 12, 10, 4, fill="#fff", sw=1.2)
        lh = size * 1.22
        block = len(rows) * lh + 16
        cy = y + h / 2 - block / 2 + 8
        self.text(x + w / 2 - 6, cy, "«component»", size=size - 1.5, italic=True, fill="#333")
        self.text(x + w / 2 - 6, cy + tsize * 1.2, title, size=tsize, bold=True)
        for i, r in enumerate(rows):
            self.text(x + w / 2 - 6, cy + tsize * 1.2 + (i + 1) * lh, r, size=size, fill="#222")

    def uml_class(self, x, y, w, name, attrs, ops, *, size=12.5, stereo=None, fill="#fff"):
        """Three-compartment UML class box. Returns its height."""
        lh = size * 1.32
        head = 26 + (lh if stereo else 0)
        h = head + max(1, len(attrs)) * lh + 8 + max(1, len(ops)) * lh + 8
        self.rect(x, y, w, h, fill=fill)
        self.rect(x, y, w, head, fill=BLUE)
        ty = y + 18
        if stereo:
            self.text(x + w / 2, ty, f"«{stereo}»", size=size - 1, italic=True, fill="#333")
            ty += lh
        self.text(x + w / 2, ty, name, size=size + 1.5, bold=True)
        ay = y + head
        self.line(x, ay, x + w, ay, sw=1.2)
        for i, a in enumerate(attrs):
            self.text(x + 7, ay + 5 + (i + 1) * lh - 4, a, size=size, anchor="start")
        oy = ay + max(1, len(attrs)) * lh + 8
        self.line(x, oy, x + w, oy, sw=1.2)
        for i, o in enumerate(ops):
            self.text(x + 7, oy + 5 + (i + 1) * lh - 4, o, size=size, anchor="start")
        return h

    def start_node(self, cx, cy, r=10):
        self.circle(cx, cy, r, fill=INK)

    def end_node(self, cx, cy, r=12):
        self.circle(cx, cy, r, fill="#fff")
        self.circle(cx, cy, r - 5, fill=INK)

    # ---- output -------------------------------------------------------------
    def svg(self) -> str:
        defs = f"""<defs>
<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{INK}"/></marker>
<marker id="open" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10" fill="none" stroke="{INK}" stroke-width="1.4"/></marker>
<marker id="tri" viewBox="0 0 12 12" refX="11" refY="6" markerWidth="11" markerHeight="11" orient="auto-start-reverse"><path d="M0,0 L12,6 L0,12 z" fill="#fff" stroke="{INK}" stroke-width="1.3"/></marker>
<marker id="diamond" viewBox="0 0 16 10" refX="1" refY="5" markerWidth="14" markerHeight="9" orient="auto-start-reverse"><path d="M1,5 L8,0.5 L15,5 L8,9.5 z" fill="{INK}"/></marker>
<marker id="one" viewBox="0 0 14 14" refX="13" refY="7" markerWidth="14" markerHeight="14" orient="auto-start-reverse"><path d="M13,7 L0,7 M6,1 L6,13 M10,1 L10,13" fill="none" stroke="{INK}" stroke-width="1.4"/></marker>
<marker id="many" viewBox="0 0 16 14" refX="15" refY="7" markerWidth="16" markerHeight="14" orient="auto-start-reverse"><path d="M15,1 L3,7 L15,13 M15,7 L0,7 M3,1 L3,13" fill="none" stroke="{INK}" stroke-width="1.4"/><circle cx="-2" cy="7" r="0" fill="none"/></marker>
<marker id="zmany" viewBox="0 0 22 14" refX="21" refY="7" markerWidth="22" markerHeight="14" orient="auto-start-reverse"><path d="M21,1 L11,7 L21,13 M21,7 L0,7" fill="none" stroke="{INK}" stroke-width="1.4"/><circle cx="6" cy="7" r="3.6" fill="#fff" stroke="{INK}" stroke-width="1.4"/></marker>
<marker id="zone" viewBox="0 0 22 14" refX="21" refY="7" markerWidth="22" markerHeight="14" orient="auto-start-reverse"><path d="M21,7 L0,7 M15,1 L15,13" fill="none" stroke="{INK}" stroke-width="1.4"/><circle cx="6" cy="7" r="3.6" fill="#fff" stroke="{INK}" stroke-width="1.4"/></marker>
</defs>"""
        body = "\n".join(self.els)
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
                f'viewBox="0 0 {self.w} {self.h}">\n<rect width="100%" height="100%" fill="#fff"/>\n'
                f'{defs}\n{body}\n</svg>')
