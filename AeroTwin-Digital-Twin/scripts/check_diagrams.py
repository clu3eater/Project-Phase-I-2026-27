# -*- coding: utf-8 -*-
"""Check the drawio diagrams for the faults that XML validation cannot see.

A .drawio file can be perfectly well-formed and still be wrong in ways a
reviewer notices in the first two seconds:

  layout       a shape off the page, two shapes on top of each other
  connection   an edge pointing at an id that no longer exists, a box with no
               line touching it, an arrow too short to see

The connection checks only run on pages that are actually FLOWCHARTS. A page
where most boxes are wired together is a flow, and a box without an edge there
is a mistake -- that is how the unconnected security, flight-history and
battery boxes were caught in system_flowchart.drawio. A page that is a
catalogue (the parameter list, the technology stack) has no edges by design,
and demanding them would be noise.

Containers are detected by geometry rather than by id: a box that fully
encloses another box is a band, so it is exempt from the overlap and
connection rules.

    python scripts/check_diagrams.py [file.drawio ...]

Exits non-zero if anything fails, so it can gate a commit.
"""
import html
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

DIAGRAMS = Path(__file__).resolve().parent.parent / "docs" / "diagrams"

# Below this an arrow is only an arrowhead. The hand-drawn flowchart packs
# boxes tightly and uses 12-16px connectors throughout, which do render, so
# the bar is set at the point where the line genuinely disappears.
MIN_ARROW_PX = 8
# Height of the strip a container's own label occupies, top-aligned.
BAND_HEADER_PX = 28
# A page counts as a flow when at least this share of its boxes are wired.
FLOW_SHARE = 0.5


def label_width(cell):
    """Roughly how far a container's own heading text runs from its left edge.

    An estimate is enough: the question is only whether an arrow passes over
    words or over the empty right-hand end of the band.
    """
    txt = re.sub(r"<[^>]+>", "", html.unescape(cell.get("value") or "")).strip()
    st = style_of(cell)
    fs = float(st.get("fontSize", 12))
    pad = float(st.get("spacingLeft", 0) or 0)
    return pad + len(txt) * fs * 0.58


def style_of(cell):
    return dict(p.split("=", 1) for p in (cell.get("style") or "").split(";")
                if "=" in p)


def anchor(box, fx, fy):
    return box[0] + fx * box[2], box[1] + fy * box[3]


# A band is many times larger than what it holds. Requiring only "bigger"
# lets a box that has accidentally landed on top of a smaller one be reclassed
# as a container, which silently excuses the very overlap being looked for.
CONTAINER_AREA_RATIO = 5.0


def encloses(outer, inner, pad=2):
    return (inner[0] >= outer[0] - pad and inner[1] >= outer[1] - pad
            and inner[0] + inner[2] <= outer[0] + outer[2] + pad
            and inner[1] + inner[3] <= outer[1] + outer[3] + pad
            and (outer[2] * outer[3])
            >= CONTAINER_AREA_RATIO * (inner[2] * inner[3]))


def overlaps(a, b, pad=1):
    return (a[0] < b[0] + b[2] - pad and b[0] < a[0] + a[2] - pad
            and a[1] < b[1] + b[3] - pad and b[1] < a[1] + a[3] - pad)


def check_page(model, name):
    pw, ph = int(model.get("pageWidth")), int(model.get("pageHeight"))
    boxes, cells, edges = {}, {}, []
    for c in model.iter("mxCell"):
        g = c.find("mxGeometry")
        if c.get("edge") == "1":
            edges.append(c)
        elif c.get("vertex") == "1" and g is not None and g.get("x"):
            boxes[c.get("id")] = (float(g.get("x")), float(g.get("y")),
                                  float(g.get("width")), float(g.get("height")))
            cells[c.get("id")] = c

    # Captions carry no shape; containers enclose other boxes. Neither is a
    # node in the flow, so neither has to be connected or kept clear.
    captions = {i for i in boxes
                if (cells[i].get("style") or "").startswith("text;")}
    containers = {i for i in boxes if i not in captions
                  and any(encloses(boxes[i], boxes[j])
                          for j in boxes if j != i)}
    nodes = [i for i in boxes if i not in captions and i not in containers]

    problems = []

    for cid, b in boxes.items():
        if (b[0] < -1 or b[1] < -1 or b[0] + b[2] > pw + 1
                or b[1] + b[3] > ph + 1):
            problems.append(f"OFF PAGE      {cid} at ({b[0]:.0f},{b[1]:.0f})")

    for i, a in enumerate(nodes):
        for c in nodes[i + 1:]:
            if overlaps(boxes[a], boxes[c]):
                problems.append(f"OVERLAP       {a} sits on top of {c}")

    linked, decorative = set(), 0
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if s is None and t is None:
            decorative += 1
            continue
        for n in (s, t):
            if n is not None and n not in boxes:
                problems.append(f"DEAD EDGE     {e.get('id')} -> missing {n}")
        linked.update(n for n in (s, t) if n)

    # Flow-ness is judged per BAND, not per page. A band whose members are
    # mostly wired is a flow, so an unwired member there is a mistake. A band
    # where nothing is wired is a list -- the nine monitored parameters, the
    # eight fault chips, the dashboard contents -- and demanding edges of it
    # would bury the real findings under noise.
    def innermost(cid):
        holders = [g for g in containers if encloses(boxes[g], boxes[cid])]
        return min(holders, key=lambda g: boxes[g][2] * boxes[g][3],
                   default=None)

    members = {}
    for cid in nodes:
        members.setdefault(innermost(cid), []).append(cid)

    wired = [n for n in nodes if n in linked]
    is_flow = bool(nodes) and len(wired) >= FLOW_SHARE * len(nodes)

    for group, mem in members.items():
        hit = [m for m in mem if m in linked]
        if len(hit) < FLOW_SHARE * len(mem):
            continue        # a list, by design
        for cid in mem:
            # Banners, notes and summary strips run most of the page width and
            # are captions with a border, not steps in the flow.
            if cid in linked or boxes[cid][2] > 0.5 * pw:
                continue
            problems.append(f"ORPHAN BOX    {cid} has no edge touching it")

    seen = {}
    for e in edges:
        s, t = boxes.get(e.get("source")), boxes.get(e.get("target"))
        if not s or not t:
            continue

        pair = (e.get("source"), e.get("target"))
        if pair in seen:
            problems.append(f"DUPLICATE     {e.get('id')} repeats "
                            f"{seen[pair]} ({pair[0]} -> {pair[1]})")
        seen[pair] = e.get("id")
        if (pair[1], pair[0]) in seen:
            problems.append(f"TWO-WAY       {e.get('id')} and "
                            f"{seen[(pair[1], pair[0])]} point both ways")

        st = style_of(e)
        if "exitX" not in st or "entryX" not in st:
            continue
        ex, ey = float(st["exitX"]), float(st["exitY"])
        x1, y1 = anchor(s, ex, ey)
        x2, y2 = anchor(t, float(st["entryX"]), float(st["entryY"]))
        span = abs(x1 - x2) + abs(y1 - y2)
        if span < MIN_ARROW_PX:
            problems.append(f"STUB ARROW    {e.get('id')} only {span:.0f}px")

        # An arrow leaving the right face to reach something on the left has
        # to double back around its own box. Same for one leaving the bottom
        # to reach something above. Both render as a loop nobody can follow.
        if ex == 1.0 and x2 < s[0]:
            problems.append(f"DOUBLES BACK  {e.get('id')} exits right but "
                            f"{e.get('target')} is to the left")
        if ex == 0.0 and x2 > s[0] + s[2]:
            problems.append(f"DOUBLES BACK  {e.get('id')} exits left but "
                            f"{e.get('target')} is to the right")
        if ey == 1.0 and y2 + 1 < s[1]:
            problems.append(f"DOUBLES BACK  {e.get('id')} exits below but "
                            f"{e.get('target')} is above")
        if ey == 0.0 and y2 > s[1] + s[3] + 1:
            problems.append(f"DOUBLES BACK  {e.get('id')} exits above but "
                            f"{e.get('target')} is below")

        # Approximate the route drawio picks, then see what it runs over. An
        # arrow crossing an unrelated box reads as connecting to that box.
        #
        # The approach segment follows the FACE it uses: an edge entering a
        # left or right face arrives horizontally at the entry y, one entering
        # a top or bottom face arrives vertically at the entry x. Modelling
        # every edge as a midpoint dog-leg instead reports crossings that do
        # not happen -- it claimed cDet -> cFP cut through the misfire chip,
        # when the real route passes above the whole chip row.
        nx, ny = float(st["entryX"]), float(st["entryY"])
        exit_v, entry_v = ey in (0.0, 1.0), ny in (0.0, 1.0)

        # Explicit waypoints override the automatic route entirely. Ignoring
        # them invents crossings: cTA -> cRUL is hand-routed around the
        # explainable-AI box, and looked like it went straight through it.
        way = []
        g = e.find("mxGeometry")
        if g is not None:
            for kid in g:
                if kid.tag == "Array":
                    way = [(float(q.get("x")), float(q.get("y")))
                           for q in kid if q.get("x")]

        if way:
            pts, vert = [(x1, y1)], exit_v
            for wx, wy in way + [(x2, y2)]:
                px, py = pts[-1]
                if abs(px - wx) > 1 and abs(py - wy) > 1:
                    pts.append((px, wy) if vert else (wx, py))
                pts.append((wx, wy))
                vert = abs(pts[-1][0] - pts[-2][0]) < 1
            segs = [(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
                    for i in range(len(pts) - 1)]
        elif exit_v and not entry_v:
            segs = [(x1, y1, x1, y2), (x1, y2, x2, y2)]
        elif not exit_v and entry_v:
            segs = [(x1, y1, x2, y1), (x2, y1, x2, y2)]
        elif exit_v:
            mid = (y1 + y2) / 2
            segs = [(x1, y1, x1, mid), (x1, mid, x2, mid), (x2, mid, x2, y2)]
        else:
            mid = (x1 + x2) / 2
            segs = [(x1, y1, mid, y1), (mid, y1, mid, y2), (mid, y2, x2, y2)]
        # A band's label sits in the top strip of its container. An edge
        # running through there strikes the heading out, which no amount of
        # valid XML will tell you -- it only shows up when the file is opened.
        for cid in containers:
            bx, by, _, _ = boxes[cid]
            # The heading occupies only as much of the top strip as its text
            # actually spans -- a band is full width but its label is not, and
            # the right-hand end is empty by design. Treating the whole width
            # as heading flags every arrow that reaches a box parked up there.
            tw = label_width(cells[cid])
            if any(abs(ay - cy) < 2 and abs(ax - cx) > BAND_HEADER_PX
                   and by <= ay <= by + BAND_HEADER_PX
                   and min(ax, cx) < bx + tw and bx < max(ax, cx)
                   for ax, ay, cx, cy in segs):
                problems.append(f"CROSSES LABEL {e.get('id')} runs through "
                                f"the {cid} heading")
                break

        for cid in nodes:
            if cid in pair:
                continue
            bx, by, bw, bh = boxes[cid]
            for ax, ay, cx, cy in segs:
                if (min(ax, cx) < bx + bw - 3 and bx < max(ax, cx) - 3
                        and min(ay, cy) < by + bh - 3
                        and by < max(ay, cy) - 3):
                    problems.append(f"CROSSES       {e.get('id')} routes "
                                    f"through {cid}")
                    break
            else:
                continue
            break

    kind = "flow" if is_flow else "catalogue"
    print(f"  {name:<32} {len(nodes):>3} nodes  "
          f"{len(edges) - decorative:>3} edges  {pw}x{ph}  [{kind}]")
    for p in problems:
        print(f"      {p}")
    if not problems:
        print("      ok")
    return len(problems)


def main(argv):
    paths = ([Path(a) for a in argv] if argv
             else sorted(DIAGRAMS.glob("*.drawio")))
    total = 0
    for path in paths:
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError as exc:
            print(f"\n{path.name}\n      BAD XML  {exc}")
            total += 1
            continue
        print(f"\n{path.name}")
        for d in root.findall("diagram"):
            total += check_page(d.find("mxGraphModel"), d.get("name"))
    print(f"\n{'ALL CHECKS PASS' if total == 0 else f'{total} PROBLEM(S)'}")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
