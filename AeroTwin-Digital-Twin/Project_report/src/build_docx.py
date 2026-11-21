"""Build the editable Word version of the report from the same content as the PDF.

Needs python-docx (pip install python-docx). Run build.py first: the cached
page numbers in the contents and figure list are taken from its body render,
and Word recomputes them when the fields are updated (update_docx.ps1).

Usage: python build_docx.py
"""
from __future__ import annotations

import re
from pathlib import Path

import sys as _sys
from pathlib import Path as _Path

# python-docx and pypdfium2 are installed in build/pylib (pip install --target build/pylib ...)
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "build" / "pylib"))

from docx import Document  # noqa: E402
from docx.enum.section import WD_SECTION
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_COLOR_INDEX, WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from PIL import Image

import json
import os
import subprocess
import sys

import build
import layout
import meta

REPORT = build.REPORT
FIG = build.FIG
OUT = REPORT / "AeroTwin_Project_Phase1_Report.docx"
LOGO = REPORT.parent / "poster" / "assets" / "mgm_logo.png"
FONT = "Times New Roman"
TEXT_W = 8.5 - 1.5 - 1.2  # inches between the margins
MAX_FIG_H = 7.4
HOIST: dict = {}  # figure placement chosen by the layout search
CHECK_PDF = build.BUILD / "docx_check.pdf"


# --------------------------------------------------------------------------- styles
def set_font(style_or_run, name=FONT, size=None, bold=None, italic=None, color=None):
    f = style_or_run.font
    f.name = name
    rpr = style_or_run.element.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.insert(0, fonts)
    for a in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
        fonts.attrib.pop(qn(f"w:{a}"), None)
    for a in ("ascii", "hAnsi", "eastAsia", "cs"):
        fonts.set(qn(f"w:{a}"), name)
    if size is not None:
        f.size = Pt(size)
    if bold is not None:
        f.bold = bold
    if italic is not None:
        f.italic = italic
    f.color.rgb = color or RGBColor(0, 0, 0)


def setup_styles(doc: Document) -> None:
    st = doc.styles
    normal = st["Normal"]
    set_font(normal, size=12)
    pf = normal.paragraph_format
    pf.line_spacing = Pt(18)  # exactly 1.5 x 12 pt, as in the PDF
    pf.space_after = Pt(8)
    pf.space_before = Pt(0)

    h1 = st["Heading 1"]
    set_font(h1, size=16, bold=True)
    h1.font.all_caps = True
    h1.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    h1.paragraph_format.space_before = Pt(0)
    h1.paragraph_format.space_after = Pt(26)
    h1.paragraph_format.keep_with_next = True
    h1.paragraph_format.line_spacing = 1.15

    h2 = st["Heading 2"]
    set_font(h2, size=14, bold=True)
    h2.paragraph_format.space_before = Pt(20)
    h2.paragraph_format.space_after = Pt(10)
    h2.paragraph_format.keep_with_next = True
    h2.paragraph_format.line_spacing = 1.15

    for name in ("Figure Caption", "Table Caption"):
        s = st.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        s.base_style = normal
        set_font(s, size=12, bold=True)
        s.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        s.paragraph_format.space_after = Pt(16)
        s.paragraph_format.line_spacing = 1.15

    lb = st["List Bullet"]
    set_font(lb, size=12)
    lb.paragraph_format.line_spacing = Pt(18)
    lb.paragraph_format.space_after = Pt(2)

    for lvl, (bold, indent) in {1: (True, 0.0), 2: (False, 0.35)}.items():
        name = f"toc {lvl}"
        try:
            s = st[name]
        except KeyError:
            s = st.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        s.base_style = normal
        set_font(s, size=12, bold=bold)
        s.paragraph_format.left_indent = Inches(indent)
        s.paragraph_format.space_after = Pt(0)
        s.paragraph_format.space_before = Pt(0)
        s.paragraph_format.line_spacing = Pt(15)
        s.paragraph_format.tab_stops.add_tab_stop(Inches(TEXT_W), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)

    try:
        tof = st["table of figures"]
    except KeyError:
        tof = st.add_style("table of figures", WD_STYLE_TYPE.PARAGRAPH)
    tof.base_style = normal
    set_font(tof, size=11)
    tof.paragraph_format.space_after = Pt(2)
    tof.paragraph_format.space_before = Pt(0)
    tof.paragraph_format.line_spacing = Pt(14)
    tof.paragraph_format.tab_stops.add_tab_stop(Inches(TEXT_W), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)


# --------------------------------------------------------------------------- helpers
PLACEHOLDER = re.compile(r"(\*\*.+?\*\*|\[(?:Director|Roll|Div|Class)[^\]]*\])")


def rich(par, text: str, *, size=None, bold=None, italic=None):
    """Add text with **bold** and highlighted [placeholders]."""
    for part in PLACEHOLDER.split(text):
        if not part:
            continue
        if part.startswith("**"):
            r = par.add_run(part[2:-2])
            r.bold = True
        else:
            r = par.add_run(part)
            if part.startswith("[") and PLACEHOLDER.fullmatch(part):
                r.font.highlight_color = WD_COLOR_INDEX.YELLOW
                r.bold = True if bold is None else bold
            elif bold is not None:
                r.bold = bold
        if size:
            r.font.size = Pt(size)
        if italic is not None:
            r.italic = italic
    return par


def para(doc, text="", *, align=WD_ALIGN_PARAGRAPH.JUSTIFY, size=None, bold=None, italic=None,
         before=None, after=None, spacing=None, style=None, keep=False):
    p = doc.add_paragraph(style=style)
    p.alignment = align
    if before is not None:
        p.paragraph_format.space_before = Pt(before)
    if after is not None:
        p.paragraph_format.space_after = Pt(after)
    if spacing is not None:
        p.paragraph_format.line_spacing = spacing
    if keep:
        p.paragraph_format.keep_with_next = True
    if text:
        rich(p, text, size=size, bold=bold, italic=italic)
    return p


_AFTER_BDR = ("w:shd", "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap", "w:overflowPunct",
              "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN", "w:bidi", "w:adjustRightInd",
              "w:snapToGrid", "w:spacing", "w:ind", "w:contextualSpacing", "w:mirrorIndents",
              "w:suppressOverlap", "w:jc", "w:textDirection", "w:textAlignment", "w:textboxTightWrap",
              "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange")


def ppr_add(ppr, el):
    """Insert a pBdr or shd element where the schema puts it in w:pPr."""
    tag = el.tag.split("}")[1]
    successors = _AFTER_BDR if tag == "pBdr" else _AFTER_BDR[1:]
    ppr.insert_element_before(el, *successors)


def rule(doc):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.line_spacing = 1.0
    ppr = p._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    b = OxmlElement("w:bottom")
    for k, v in {"val": "single", "sz": "12", "space": "1", "color": "000000"}.items():
        b.set(qn(f"w:{k}"), v)
    bdr.append(b)
    ppr_add(ppr, bdr)
    r = p.add_run()
    r.font.size = Pt(4)


def hyperlink(par, url: str, text: str | None = None):
    r_id = par.part.relate_to(url, RT.HYPERLINK, is_external=True)
    h = OxmlElement("w:hyperlink")
    h.set(qn("r:id"), r_id)
    r = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    c = OxmlElement("w:color")
    c.set(qn("w:val"), "0563C1")
    u = OxmlElement("w:u")
    u.set(qn("w:val"), "single")
    rpr.append(c)
    rpr.append(u)
    r.append(rpr)
    t = OxmlElement("w:t")
    t.text = text or url
    t.set(qn("xml:space"), "preserve")
    r.append(t)
    h.append(r)
    par._p.append(h)


def fld(run, kind: str, text: str = "", *, preserve=True):
    if kind in ("begin", "separate", "end"):
        e = OxmlElement("w:fldChar")
        e.set(qn("w:fldCharType"), kind)
        if kind == "begin":
            e.set(qn("w:dirty"), "true")
    else:
        e = OxmlElement("w:instrText")
        e.set(qn("xml:space"), "preserve")
        e.text = text
    run._r.append(e)


def field_list(doc, instr: str, rows, style_for):
    """A TOC-type field whose cached result is `rows` of (level, text, page)."""
    for i, (lvl, text, page) in enumerate(rows):
        p = doc.add_paragraph(style=style_for(lvl))
        if i == 0:
            r = p.add_run()
            fld(r, "begin")
            fld(p.add_run(), "instr", instr)
            fld(p.add_run(), "separate")
        p.add_run(f"{text}\t{page}")
        if i == len(rows) - 1:
            fld(p.add_run(), "end")


def page_field(par):
    fld(par.add_run(), "begin")
    fld(par.add_run(), "instr", " PAGE ")
    fld(par.add_run(), "separate")
    par.add_run("1")
    fld(par.add_run(), "end")


def section_numbering(section, fmt: str | None, start: int | None):
    sp = section._sectPr
    for old in sp.findall(qn("w:pgNumType")):
        sp.remove(old)
    if fmt:
        pg = OxmlElement("w:pgNumType")
        pg.set(qn("w:fmt"), fmt)
        if start is not None:
            pg.set(qn("w:start"), str(start))
        sp.append(pg)


def margins(section):
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.top_margin = section.bottom_margin = Inches(1)
    section.left_margin, section.right_margin = Inches(1.5), Inches(1.2)
    section.footer_distance = Inches(0.5)


def footer_number(section):
    section.footer.is_linked_to_previous = False
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    page_field(p)
    for r in p.runs:
        set_font(r, name="Calibri", size=12)


def picture(doc, path: Path, width_in: float, *, before=4):
    with Image.open(path) as im:
        ratio = im.height / im.width
    w = min(width_in, TEXT_W)
    if w * ratio > MAX_FIG_H:
        w = MAX_FIG_H / ratio
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.keep_with_next = True
    p.paragraph_format.space_before = Pt(before)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.line_spacing = 1.0
    p.add_run().add_picture(str(path), width=Inches(w))


def shade(cell, hex_fill):
    tcpr = cell._tc.get_or_add_tcPr()
    s = OxmlElement("w:shd")
    s.set(qn("w:val"), "clear")
    s.set(qn("w:color"), "auto")
    s.set(qn("w:fill"), hex_fill)
    tcpr.append(s)


def data_table(doc, head, rows, caption):
    t = doc.add_table(rows=1 + len(rows), cols=len(head))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for ri, row in enumerate([head] + rows):
        for ci, val in enumerate(row):
            cell = t.cell(ri, ci)
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT if ci == 0 else WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.0
            # short tables stay whole; long ones may continue on the next page
            p.paragraph_format.keep_with_next = len(rows) <= 6 or ri == 0 or ri == len(rows)
            r = p.add_run(val)
            r.font.size = Pt(11)
            if ri == 0:
                r.bold = True
                shade(cell, "F0F0F0")
    for ri, row in enumerate(t.rows):
        trpr = row._tr.get_or_add_trPr()
        trpr.append(OxmlElement("w:cantSplit"))
        if ri == 0:
            trpr.append(OxmlElement("w:tblHeader"))  # repeat the header row on each page
    num = caption.split()[1]
    c = doc.add_paragraph(style="Table Caption")
    c.paragraph_format.space_before = Pt(6)
    c.add_run(caption)
    return num


# --------------------------------------------------------------------------- parts
def cover(doc):
    def line(text, size, bold=True, after=0, italic=False):
        para(doc, text, align=WD_ALIGN_PARAGRAPH.CENTER, size=size, bold=bold, italic=italic,
             after=after, spacing=1.15)

    line(meta.REPORT_TYPE, 14, after=8)
    line(f"“{meta.TITLE}”", 20, after=8)
    line("Submitted to", 14, after=8)
    line("DR. BABASAHEB AMBEDKAR TECHNOLOGICAL", 14)
    line("UNIVERSITY, LONERE", 14, after=8)
    line("in partial fulfillment of the requirement for the degree of", 12, after=8)
    line("BACHELOR OF TECHNOLOGY", 16)
    line("in", 14, bold=False)
    line(meta.BRANCH.upper(), 16)
    line("By", 14, bold=False, after=6)
    for n, _ in meta.STUDENTS:
        line(n, 14)
    line("", 8)
    line("Under the Guidance", 14)
    line("of", 14, bold=False, after=6)
    line(meta.GUIDE, 14)
    line(f"(Department of {meta.BRANCH})", 12, bold=False)
    p = para(doc, align=WD_ALIGN_PARAGRAPH.CENTER, before=4, after=2, spacing=1.0)
    p.add_run().add_picture(str(LOGO), height=Inches(1.15))
    line(f"DEPARTMENT OF {meta.BRANCH.upper()}", 14)
    line("MAHATMA GANDHI MISSION'S COLLEGE OF ENGINEERING", 11)
    line("NANDED (M.S.)", 11, after=8)
    line(f"Academic Year {meta.YEAR}", 14)

    # certificate
    p = para(doc, "Certificate", align=WD_ALIGN_PARAGRAPH.CENTER, size=36, bold=True, italic=True,
             after=6, spacing=1.0)
    p.paragraph_format.page_break_before = True
    p.runs[0].underline = True
    p = para(doc, align=WD_ALIGN_PARAGRAPH.CENTER, after=10, spacing=1.0)
    p.add_run().add_picture(str(LOGO), height=Inches(1.1))
    para(doc, "This is to certify that the project entitled", align=WD_ALIGN_PARAGRAPH.CENTER,
         size=13, italic=True, after=4)
    para(doc, f"“{meta.TITLE}”", align=WD_ALIGN_PARAGRAPH.CENTER, size=12, bold=True, after=12,
         spacing=1.15)
    p = para(doc, size=13, after=0)
    names = [n for n, _ in meta.STUDENTS]
    r = p.add_run("being submitted by ")
    r.italic, r.font.size = True, Pt(13)
    for i, n in enumerate(names):
        r = p.add_run(n)
        r.bold, r.italic, r.font.size = True, True, Pt(13)
        sep = ", " if i < len(names) - 2 else (" and " if i == len(names) - 2 else "")
        if sep:
            r = p.add_run(sep)
            r.italic, r.font.size = True, Pt(13)
    r = p.add_run(f" to the Dr. Babasaheb Ambedkar Technological University, Lonere, for the award of the "
                  f"degree of Bachelor of Technology in {meta.BRANCH}, is a record of bonafide work carried "
                  "out by them under my supervision and guidance. The matter contained in this report has not "
                  "been submitted to any other university or institute for the award of any degree.")
    r.italic, r.font.size = True, Pt(13)
    para(doc, meta.GUIDE, align=WD_ALIGN_PARAGRAPH.CENTER, size=14, bold=True, before=50, after=0, spacing=1.15)
    para(doc, "Project Guide", align=WD_ALIGN_PARAGRAPH.CENTER, size=14, bold=True, after=40, spacing=1.15)
    t = doc.add_table(rows=1, cols=2)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for cell, (name, role, l1) in zip(t.rows[0].cells, [(meta.HOD, "H.O.D", meta.BRANCH),
                                                       (meta.DIRECTOR, "Director", "MGM's College of Engg., Nanded")]):
        for i, (txt, sz, b) in enumerate([(name, 14, True), (role, 12, True), (l1, 12, False)]):
            p = cell.paragraphs[0] if i == 0 else cell.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.15
            rich(p, txt, size=sz, bold=b)


def heading1(doc, text, *, page_break=True):
    h = doc.add_heading(text, level=1)
    h.paragraph_format.page_break_before = page_break
    return h


def front(doc, toc_rows, lof_rows):
    heading1(doc, "Acknowledgement", page_break=False)
    for t in meta.ACK:
        p = para(doc, t)
        p.paragraph_format.first_line_indent = Inches(0.5)
    p = para(doc, "With Deep Reverence,", before=10)
    p.paragraph_format.first_line_indent = Inches(0.5)
    for n, r in meta.STUDENTS:
        para(doc, f"{n}_{r}", align=WD_ALIGN_PARAGRAPH.RIGHT, bold=True, after=0)
    para(doc, f"[ {meta.CLASS_DIV} ]", align=WD_ALIGN_PARAGRAPH.RIGHT, bold=True, before=8)

    heading1(doc, "Abstract")
    for t in meta.ABSTRACT:
        para(doc, t)

    heading1(doc, "Table of Contents")
    t = list_table(doc, [4.95, 0.85], len(toc_rows))
    for row, (kind, text, page) in zip(t.rows, toc_rows):
        a, b = row.cells
        gap = 5 if kind == "b" else 0
        list_cell(a, text, bold=kind == "b", indent=0.4 if kind == "s" else 0, before=gap)
        list_cell(b, page, bold=kind == "b", right=True, before=gap)

    heading1(doc, "List of Figures")
    t = list_table(doc, [0.9, 4.1, 0.8], len(lof_rows) + 1)
    for cell, text in zip(t.rows[0].cells, ("Figure No.", "Name of Figure", "Page No.")):
        list_cell(cell, text, bold=True, right=text == "Page No.", after=6)
    for row, (num, title, page) in zip(t.rows[1:], lof_rows):
        for cell, text, right in zip(row.cells, (num, title, str(page)), (False, False, True)):
            list_cell(cell, text, size=11, right=right)


def list_table(doc, widths, nrows):
    """Borderless table used for the contents and figure list, as in the PDF."""
    t = doc.add_table(rows=nrows, cols=len(widths))
    t.autofit = False
    t.alignment = WD_TABLE_ALIGNMENT.LEFT
    for row in t.rows:
        for cell, w in zip(row.cells, widths):
            cell.width = Inches(w)
    return t


def list_cell(cell, text, *, bold=False, right=False, indent=0, before=0, after=0, size=12):
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT if right else WD_ALIGN_PARAGRAPH.LEFT
    pf = p.paragraph_format
    pf.space_before, pf.space_after = Pt(before), Pt(after)
    pf.line_spacing = Pt(14.5 if size == 12 else 13.5)
    pf.left_indent = Inches(indent)
    run = p.add_run(text)
    run.bold, run.font.size = bold, Pt(size)


def body(doc, chapters):
    for ch in chapters:
        if ch["num"] == 0:
            heading1(doc, ch["title"])
            blocks(doc, layout.apply_floats(ch["intro"], HOIST))
            continue
        lab = para(doc, f"Chapter {ch['num']}", align=WD_ALIGN_PARAGRAPH.LEFT, size=11, italic=True,
                   after=10, keep=True)
        lab.paragraph_format.page_break_before = ch is not chapters[0]
        heading1(doc, ch["title"], page_break=False)
        blocks(doc, layout.apply_floats(ch["intro"], HOIST))
        rule(doc)
        for s in ch["sections"]:
            doc.add_heading(f"{s['num']} {s['title']}", level=2)
            blocks(doc, layout.apply_floats(s["blocks"], HOIST), organization=s["title"] == "Report Organization")
            rule(doc)

    heading1(doc, "References")
    for i, (text, url) in enumerate(meta.REFERENCES, 1):
        p = para(doc, f"[{i}]\t{text}", after=0 if url else 10)
        p.paragraph_format.left_indent = Inches(0.45)
        p.paragraph_format.first_line_indent = Inches(-0.45)
        p.paragraph_format.tab_stops.add_tab_stop(Inches(0.45))
        p.paragraph_format.keep_together = True
        if url:
            p.paragraph_format.keep_with_next = True
            lp = para(doc, "Link: ", after=10, align=WD_ALIGN_PARAGRAPH.LEFT)
            lp.paragraph_format.left_indent = Inches(0.45)
            hyperlink(lp, url)


def blocks(doc, items, organization=False):
    for b in items:
        kind = b[0]
        if kind == "p":
            para(doc, b[1])
        elif kind == "ul":
            for item in b[1]:
                p = para(doc, item, style="List Bullet", bold=True if organization else None,
                         align=WD_ALIGN_PARAGRAPH.LEFT if organization else WD_ALIGN_PARAGRAPH.JUSTIFY,
                         keep=organization, before=8 if organization else None)
        elif kind == "fig":
            _, num, file, cap, width = b
            picture(doc, FIG / file, width)
            c = doc.add_paragraph(style="Figure Caption")
            c.add_run(f"Fig {num} {cap}")
        elif kind == "table":
            data_table(doc, b[1], b[2], b[3])
        elif kind == "code":
            p = doc.add_paragraph()
            pf = p.paragraph_format
            pf.line_spacing, pf.space_before, pf.space_after = Pt(12), Pt(4), Pt(12)
            pf.keep_together = True
            pf.left_indent = Inches(0.1)
            ppr = p._p.get_or_add_pPr()
            sh = OxmlElement("w:shd")
            for k, v in {"val": "clear", "color": "auto", "fill": "F5F5F5"}.items():
                sh.set(qn(f"w:{k}"), v)
            bdr = OxmlElement("w:pBdr")
            for side in ("top", "left", "bottom", "right"):
                e = OxmlElement(f"w:{side}")
                for k, v in {"val": "single", "sz": "4", "space": "4", "color": "999999"}.items():
                    e.set(qn(f"w:{k}"), v)
                bdr.append(e)
            ppr_add(ppr, bdr)
            ppr_add(ppr, sh)
            for i, ln in enumerate(b[1]):
                r = p.add_run(ln)
                set_font(r, name="Consolas", size=9.5)
                if i < len(b[1]) - 1:
                    r.add_break()
        elif kind == "sub":
            para(doc, b[1], bold=True, align=WD_ALIGN_PARAGRAPH.LEFT, before=8, after=2, keep=True)
        elif kind == "link":
            p = para(doc, "Reference Link: ", align=WD_ALIGN_PARAGRAPH.LEFT, after=10)
            hyperlink(p, b[1])


# --------------------------------------------------------------------------- main
def toc_rows(chapters, pos, front_pages):
    """Contents and figure rows in exactly the PDF's format (see build.build)."""
    starts = [pos[f"C:{c['num']}"] for c in chapters if c["num"]] + [pos["C:0"], pos["C:R"]]
    rows = [("b", "Acknowledgement", front_pages["ack"]), ("b", "Abstract", front_pages["abs"]),
            ("b", "Table of Contents", front_pages["toc"]), ("b", "List of Figures", front_pages["lof"])]
    lof = []
    for k, ch in enumerate(c for c in chapters if c["num"]):
        rows.append(("b", f"Chapter {ch['num']}. {ch['title']}", f"{starts[k]}-{starts[k + 1] - 1}"))
        for sec in ch["sections"]:
            rows.append(("s", f"{sec['num']} {sec['title']}", str(pos[f"S:{sec['num']}"])))
            for blk in sec["blocks"]:
                if blk[0] == "fig":
                    lof.append((blk[1], blk[3], pos[f"F:{blk[1]}"]))
    rows += [("b", "Conclusion", str(pos["C:0"])), ("b", "References", str(pos["C:R"]))]
    return rows, lof


def word_positions(pdf, chapters):
    """Where each chapter, section and figure landed in Word's own layout."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(pdf))
    pages = [[ln.strip() for ln in doc[i].get_textpage().get_text_range().splitlines()]
             for i in range(len(doc))]
    doc.close()
    body0 = next(i for i, ls in enumerate(pages) if "Chapter 1" in ls)
    heads = {}
    for ch in chapters:
        for sec in ch["sections"]:
            heads[f"S:{sec['num']}"] = f"{sec['num']} {sec['title']}"[:40]
            for blk in sec["blocks"]:
                if blk[0] == "fig":
                    heads[f"F:{blk[1]}"] = f"Fig {blk[1]} {blk[3]}"[:30]
    pos = {}
    for i in range(body0, len(pages)):
        n = i - body0 + 1
        for ln in pages[i]:
            m = re.fullmatch(r"Chapter (\d+)", ln)
            if m:
                pos.setdefault(f"C:{m.group(1)}", n)
            if ln.upper() == "CONCLUSION":
                pos.setdefault("C:0", n)
            if ln.upper() == "REFERENCES":
                pos.setdefault("C:R", n)
            for key, text in heads.items():
                if key not in pos and ln.startswith(text):
                    pos[key] = n
    missing = [k for k in list(heads) + ["C:0", "C:R"] if k not in pos]
    if missing:
        raise SystemExit(f"could not find in Word layout: {missing}")

    def find(name):
        return next(i for i in range(body0) if name in (ln.upper() for ln in pages[i]))

    ack, toc, lof = find("ACKNOWLEDGEMENT"), find("TABLE OF CONTENTS"), find("LIST OF FIGURES")
    R = build.roman
    front_pages = {"ack": R(1), "abs": R(find("ABSTRACT") - ack + 1),
                   "toc": R(toc - ack + 1) + (f"-{R(lof - ack)}" if lof - toc > 1 else ""),
                   "lof": R(lof - ack + 1)}
    return pos, front_pages


def main(hoist=None, positions=None):
    HOIST.clear()
    HOIST.update(hoist or {})
    chapters = build.parse((build.HERE / "content.md").read_text(encoding="utf-8"))
    doc = Document()
    setup_styles(doc)
    margins(doc.sections[0])
    cover(doc)

    front_sec = doc.add_section(WD_SECTION.NEW_PAGE)
    margins(front_sec)
    section_numbering(front_sec, "upperRoman", 1)
    footer_number(front_sec)
    if positions is None:   # first pass: the PDF's numbers, replaced once Word lays it out
        positions = (build.positions(build.BUILD / "body.pdf"),
                     {"ack": "I", "abs": "II", "toc": "III-IV", "lof": "V"})
    toc, lof = toc_rows(chapters, *positions)
    front(doc, toc, lof)

    body_sec = doc.add_section(WD_SECTION.NEW_PAGE)
    margins(body_sec)
    section_numbering(body_sec, "decimal", 1)
    footer_number(body_sec)
    body(doc, chapters)

    doc.core_properties.title = meta.TITLE
    doc.core_properties.author = ", ".join(n for n, _ in meta.STUDENTS)
    tmp = OUT.with_suffix(".tmp.docx")
    doc.save(tmp)
    os.replace(tmp, OUT)


def word_layout(hoist, positions=None) -> Path:
    """Build the .docx with this figure placement and lay it out in Word."""
    main(hoist, positions)
    tmp = build.BUILD / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    subprocess.run(["cscript", "//nologo", str(build.HERE / "update_docx.vbs")], check=True,
                   capture_output=True, env=dict(os.environ, TEMP=str(tmp), TMP=str(tmp)))
    return CHECK_PDF


if __name__ == "__main__":
    # Same figure placement as the PDF, so both files have the same content in the same order.
    chapters = build.parse((build.HERE / "content.md").read_text(encoding="utf-8"))
    hoist = json.loads(build.FLOATS.read_text()) if build.FLOATS.exists() else {}
    positions = None
    for _ in range(3):   # page numbers settle once the contents table has its final size
        word_layout(hoist, positions)
        found = word_positions(CHECK_PDF, chapters)
        if found == positions:
            break
        positions = found
    pages = layout.measure(CHECK_PDF)
    print("remaining gaps:", layout.report(pages))
    print("chapter ends:", [(p + 1, f"{pages[p][0]:.0%}") for p in range(len(pages) - 1) if pages[p + 1][2]])
    print("saved", OUT, "-", len(pages), "pages")
