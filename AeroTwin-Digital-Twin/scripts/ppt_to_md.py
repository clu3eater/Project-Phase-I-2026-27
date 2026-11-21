# -*- coding: utf-8 -*-
"""Write docs/SIH_PPT_CONTENT.md from the deck itself.

The content doc used to be maintained by hand beside the deck, which meant it
described whichever version of the deck was current when it was last edited.
It is now extracted from the .pptx, so the two cannot disagree: change the
deck, re-run this, and the markdown follows.

Reading order is recovered from geometry. Shapes are grouped into rows by
vertical position, but a row is not always the reading order -- a slide with
two columns puts unrelated things side by side, and reading it row by row
interleaves the working flow with the technology stack. So a row of section
headings opens columns, and everything below is filed under the heading whose
column it sits in until the next heading row.

    python scripts/gen_ppt_v2.py      # build the deck
    python scripts/ppt_to_md.py       # then mirror it into markdown
"""
import re
from pathlib import Path

from pptx import Presentation
from pptx.util import Emu

ROOT = Path(__file__).resolve().parent.parent
DECK = ROOT / "docs" / "SIH_26054_Idea_Presentation.pptx"
OUT = ROOT / "docs" / "SIH_PPT_CONTENT.md"

# Shapes within this vertical distance share a row. Kept tight: at 0.30 a
# section heading swallowed the row of boxes 0.27in beneath it, and the whole
# group was then filed under the wrong column.
ROW_TOLERANCE_IN = 0.22
FOOTER_TOP_IN = 6.85        # below this is the footer strip and slide number
BADGE_MAX_IN = 0.90         # the L0..L5 layer tags on the architecture slide
BULLET = "▪"


def is_heading(text, width):
    """A short, full-caps, single-line box is a section heading on these
    slides -- the deck uses no other device to mark one."""
    # Long enough for a two-part heading: "SYSTEM ARCHITECTURE | SIX LAYERS,
    # DATA ENTERS AT L0 AND MOVES UPWARD" is 69 characters and is still a
    # heading. Nothing else in this deck is set entirely in capitals.
    if "\n" in text or len(text) > 90:
        return False
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters) and width > 0.9


def lead_in(body):
    """Bold the lead-in phrase, the way the slide sets it off."""
    m = re.match(r"^([A-Z][^.:]{2,44}[.:])\s\s*(.+)$", body)
    return f"**{m.group(1).rstrip('.:')}** — {m.group(2)}" if m else body


def unwrap(lines):
    """Rejoin lines that are only wrapped, not separate points.

    A trailing comma or dash is the only safe evidence of a wrap. Treating a
    lower-case start as evidence glues every label to its caption instead --
    "Engine runs" + "wear builds up" is two things, not one sentence.
    """
    out = [lines[0]]
    for ln in lines[1:]:
        if out[-1].endswith((",", "-", "—")):
            out[-1] = f"{out[-1]} {ln}"
        else:
            out.append(ln)
    return out


def render(text):
    """One shape's text as markdown lines."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []

    if lines[0].startswith(BULLET):
        out = []
        for ln in lines:
            body = ln.lstrip(BULLET).strip()
            if body.endswith(":"):
                out.append(f"- **{body.rstrip(':')}** — "
                           "*(left blank — from the portal)*")
            else:
                out.append(f"- {lead_in(body)}")
        return out

    # "Key : value" throughout means a metadata block, not prose.
    if all(" : " in ln or ln.rstrip().endswith(":") for ln in lines):
        out = []
        for ln in lines:
            key, _, val = ln.partition(":")
            val = val.strip()
            out.append(f"- **{key.strip()}** — "
                       + (val if val else "*(left blank — from the portal)*"))
        return out

    lines = unwrap(lines)
    if len(lines) == 1:
        return [lead_in(lines[0])]
    # A lead-in on the FIRST line means the box is a set of "Lead-in.
    # Sentence." points. One on the second means the box is a statement and
    # its answer, and bolding the answer buries the claim being answered.
    if lead_in(lines[0]) != lines[0]:
        out = []
        for ln in lines:
            if out:
                out.append("")
            out.append(lead_in(ln))
        return out
    if len(lines) == 2:
        if len(lines[0]) <= 45:
            return [f"- **{lines[0]}** — {lines[1]}"]  # a caption and its body
        return [f"**{lines[0]}**", lines[1]]           # a claim and its answer
    # Several full sentences in one box are separate points, not a label and
    # its caption, so they must not be folded together.
    if all(len(ln) > 50 for ln in lines):
        out = []
        for ln in lines:
            if out:
                out.append("")
            out.append(ln)
        return out
    return [f"- **{lines[0]}** — " + "; ".join(lines[1:])]


def is_sub_head(text, width):
    """A short single line inside a column is that sub-column's caption.

    Not the same test as is_heading: these are not set in capitals -- the
    Strategic / Operational / Economic captions on the benefits grid are
    ordinary title case, and requiring capitals misses them entirely.
    """
    return (is_heading(text, width)
            or ("\n" not in text and len(text) <= 24
                and not text.startswith(BULLET)))


def pair_grid(items):
    """A column holding N captions then N bodies is a small grid; zip it.

    Left alone it prints three captions followed by three unrelated lists,
    which loses which body belongs to which caption.
    """
    heads = [i for i in items if is_sub_head(i[2], i[1])]
    rest = [i for i in items if not is_sub_head(i[2], i[1])]
    if len(heads) > 1 and len(heads) == len(rest):
        return [x for pair in zip(sorted(heads), sorted(rest)) for x in pair]
    return items


def rows_of(shapes):
    """Group (top, left, width, text) tuples into rows, ordered left to right.

    The top is kept on each item, because a column's contents have to be
    re-grouped into rows a second time once they have been filed under their
    heading.
    """
    rows, cur, anchor = [], [], None
    for item in shapes:
        if anchor is not None and item[0] - anchor > ROW_TOLERANCE_IN:
            rows.append(sorted(cur, key=lambda r: r[1]))
            cur, anchor = [], item[0]
        anchor = item[0] if anchor is None else anchor
        cur.append(item)
    if cur:
        rows.append(sorted(cur, key=lambda r: r[1]))
    return rows


def is_badge_row(row):
    """A narrow box with a very short label, then a name, then components.

    The architecture slide tags each band this way. Read as an ordinary row it
    comes out as six disconnected fragments with no sign of what they belong
    to. The badge is recognised by its size and the length of its label rather
    than by capitals, because the layer names beside it are title case.
    """
    return (len(row) >= 3 and row[0][2] < BADGE_MAX_IN
            and len(row[0][3]) <= 4 and "\n" not in row[0][3])


def join_blocks(chunks):
    """Concatenate blocks with a blank line between them.

    Two runs of list items are the exception: a blank line there closes the
    list and opens a second one, which splits the technologies stack and the
    six methodology steps in half.
    """
    out = []
    for block in chunks:
        # Strip only LEADING and trailing blanks. Dropping every blank also
        # removed the separators inside a block, which glued each benefits
        # caption to the list above it and ran the references together.
        while block and block[0] == "":
            block.pop(0)
        while block and block[-1] == "":
            block.pop()
        if not block:
            continue
        if out and not (out[-1].startswith("- ") and block[0].startswith("- ")):
            if out[-1] != "":
                out.append("")
        out += block
    return out


def emit_rows(rows):
    """Render consecutive rows, pairing a caption row with the row beneath.

    A row of short captions above a row of lists is a small grid. Rendered in
    order it gives three captions and then three unrelated lists, and which
    body belongs to which caption is lost.
    """
    chunks, i = [], 0
    while i < len(rows):
        row = rows[i]
        nxt = rows[i + 1] if i + 1 < len(rows) else None
        if (nxt and len(row) > 1 and len(row) == len(nxt)
                and not is_badge_row(row)
                and all(is_sub_head(c[3], c[2]) for c in row)
                and not any(is_sub_head(c[3], c[2]) for c in nxt)):
            block = []
            for cap, body in zip(row, nxt):
                block += ["", f"**{cap[3]}**"] + render(body[3])
            chunks.append(block)
            i += 2
            continue
        chunks.append(render_row(row))
        i += 1

    return join_blocks(chunks)


def render_row(row):
    """One row of a column, or of a single-column slide."""
    if is_badge_row(row):
        out = [f"**{row[0][3]} · {row[1][3]}**"]
        for item in row[2:]:
            for ln in render(item[3]):
                out.append(ln if ln.startswith("- ") else f"- {ln}")
        return out + [""]
    # Three or more single-line boxes side by side are a row of chips -- the
    # simulation scenarios, the parameters -- not a row of captions each
    # introducing something. Rendered as captions they come out as a run of
    # bold fragments, and the ones just over the caption length limit are not
    # even bold, so the row looks arbitrary.
    if len(row) >= 3 and all("\n" not in i[3] and not i[3].startswith(BULLET)
                             for i in row):
        return [f"- {i[3]}" for i in row]

    chunks = []
    for item in pair_grid([(i[1], i[2], i[3]) for i in row]):
        if is_heading(item[2], item[1]):
            # Same level as a heading that opened a column. The risks heading
            # sits inside one and its two siblings on the slide do not, and
            # rendering it a level deeper made them look unrelated.
            chunks.append([f"### {item[2]}"])
        elif is_sub_head(item[2], item[1]):
            chunks.append([f"**{item[2]}**"])
        else:
            chunks.append(render(item[2]))
    return join_blocks(chunks)


def render_table(shape):
    """A pptx table as a markdown table, first row taken as the header."""
    rows = [[c.text.strip().replace("\n", " ") for c in r.cells]
            for r in shape.table.rows]
    if not rows:
        return []
    head, body = rows[0], rows[1:]
    out = ["| " + " | ".join(head) + " |",
           "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in body]
    return out + [""]


def slide_markdown(slide, number):
    shapes, tables = [], []
    for sh in slide.shapes:
        top = Emu(sh.top).inches
        if top >= FOOTER_TOP_IN:
            continue
        # A table is a GraphicFrame with no text_frame; its rows carry real
        # content and have to be pulled out separately or they vanish.
        if getattr(sh, "has_table", False):
            tables.append((top, render_table(sh)))
            continue
        if not sh.has_text_frame or not sh.text_frame.text.strip():
            continue
        text = sh.text_frame.text.strip()
        width = Emu(sh.width).inches
        if width < 1.1 and text.islower() and " " not in text:
            continue        # a word sitting on a connector, not content
        shapes.append((top, Emu(sh.left).inches, width, text))
    shapes.sort()
    if not shapes:
        return []

    out = [f"## Slide {number} — {shapes.pop(0)[3].splitlines()[0]}", ""]
    cols = None

    pending = []

    def flush():
        """Emit whatever is buffered: loose rows, then any open columns."""
        # `out +=` rebinds the name, so both have to be declared.
        nonlocal cols, out, pending
        if pending:
            out += emit_rows(pending) + [""]
            pending = []
        for head, _, items in cols or []:
            out += [f"### {head}", ""]
            # A column's contents are re-grouped into their own rows, so that
            # a badge row inside one column is not mixed with whatever happens
            # to sit at the same height in the column beside it.
            out += emit_rows(rows_of(sorted(items))) + [""]
        cols = None

    for row in rows_of(shapes):
        if all(is_heading(i[3], i[2]) for i in row) and not is_badge_row(row):
            flush()
            if len(row) == 1:
                out += [f"### {row[0][3]}", ""]
            else:
                cols = [(i[3], i[1] + i[2] / 2, []) for i in row]
            continue

        if cols:
            for item in row:
                centre = item[1] + item[2] / 2
                nearest = min(cols, key=lambda c: abs(centre - c[1]))
                nearest[2].append(item)
            continue

        pending.append(row)

    flush()
    for _, lines in sorted(tables):
        out += lines
    return out


FOOTER = """## Diagrams — which file goes on which slide

Generated by `python scripts/gen_diagrams.py` into `docs/diagrams/`, as one
multi-page book (`ps26054_diagrams.drawio`) and one file per diagram. Open
`docs/diagrams/preview.html` to see them all without draw.io.

| Slide | Diagram file | What it carries |
|---|---|---|
| 2 | `1_problem-and-solution.drawio` | today's threshold loop against ours, with the nine parameters and eight faults |
| **3** | **`system_flowchart.drawio`** | **the architecture drawing — six lettered bands with the full decision flow** |
| 3 | `4_how-health-is-measured.drawio` | the residual, worked through one temperature reading |
| 4 | `3_working-flow.drawio` | CAN frame to maintenance action, six stages |
| 4 | `6_technology-stack.drawio` | every framework, security protocol and standard |
| 5 / 6 | `5_warning-timeline.drawio` | why a wear-out model buys hours of notice |

`system_flowchart.drawio` is the authoritative architecture drawing: it is the
one with the arrows and the decision diamonds. `2_system-architecture.drawio`
is a flatter version of the same stack, kept because it reads better shrunk to
a quarter-slide. If the two disagree, the flowchart is right.

## Deliberately left blank

Team ID, Team Name and the prototype and video links come from the portal. A
placeholder that looks like content is worse than an empty field, so they stay
empty until the real values exist.

## Deliberately absent

No accuracy figures. An idea submission is judged on the thinking, and a number
quoted on a slide is a number that can be contradicted at the demo.
"""


def main():
    prs = Presentation(DECK)
    body = ["# SIH 2026 — Idea Presentation content", "",
            "## PS 26054 · AI-Enabled Real-Time Digital Twin for Aero Piston "
            "Engines in MALE UAVs", "",
            f"Extracted from `{DECK.relative_to(ROOT).as_posix()}` "
            f"({len(prs.slides)} slides) by `scripts/ppt_to_md.py`. "
            "Edit the deck generator, not this file — it is overwritten.", "",
            "## What the template asks for, and where it is answered", "",
            "The official format fixes both the slide count and the section "
            "names: six slides including the title, points and diagrams "
            "rather than paragraphs, and no change to the idea-detail "
            "pointers.", "",
            "| Slide | Template section | What it must answer |",
            "|---|---|---|",
            "| 1 | Title page | PS ID, title, theme, category, team |",
            "| 2 | Idea title | Detailed explanation of the solution · how it "
            "addresses the problem · innovation and uniqueness |",
            "| 3 | Technical approach | Technologies used (languages, "
            "frameworks, hardware) · methodology and process |",
            "| 4 | Feasibility and viability | Feasibility · potential "
            "challenges and risks · strategies for overcoming them |",
            "| 5 | Impact and benefits | Impact on the target audience · "
            "benefits (social, economic, environmental) |",
            "| 6 | Research and references | Details and links of the "
            "reference and research work |", "",
            "`scripts/check_ppt.py` verifies the slide count, that each "
            "section the template names is present, that nothing sits under "
            "the footer bar in the exported PDF, and that every "
            "problem-statement term appears as real text rather than inside "
            "a picture.", ""]
    for i, slide in enumerate(prs.slides, 1):
        body += slide_markdown(slide, i) + ["---", ""]
    body.append(FOOTER)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(body))
    OUT.write_text(text, encoding="utf-8")
    print(f"Saved {OUT}  ({len(prs.slides)} slides, "
          f"{len(text.split())} words)")


if __name__ == "__main__":
    main()
