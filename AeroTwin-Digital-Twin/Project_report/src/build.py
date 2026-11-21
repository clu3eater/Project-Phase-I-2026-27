"""Build the Phase-I project report as a PDF in the department's format.

Three parts are rendered separately with headless Chrome and merged, so that
each keeps its own page numbering: the cover and certificate (no number), the
front matter (I, II, III ...) and the body (1, 2, 3 ...). The table of contents
and list of figures are filled in from the page positions of the first render.

Usage: python build.py
"""
from __future__ import annotations

import html
import json
import sys
import os
import re
import subprocess
from pathlib import Path

from pypdf import PdfReader, PdfWriter

import layout
import meta

HERE = Path(__file__).resolve().parent
# pypdfium2 and python-docx are installed here (pip install --target build/pylib ...)
sys.path.insert(0, str(HERE.parent / "build" / "pylib"))
REPORT = HERE.parent
FIG = REPORT / "figures"
BUILD = REPORT / "build"
OUT = REPORT / "AeroTwin_Project_Phase1_Report.pdf"
FLOATS = REPORT / "build" / "floats_pdf.json"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

CSS = """
@page { size: 8.5in 11in; margin: 1in 1.2in 1in 1.5in; }
@page :first { }
html { font-family: 'Times New Roman', Times, serif; font-size: 12pt; color: #000; }
body { margin: 0; }
p { margin: 0 0 8pt; line-height: 1.5; text-align: justify; }
.ph { background: #fff59d; }
.marker { font-size: 1px; color: #fff; line-height: 0; display: inline; }
.newpage { break-before: page; }
.chap-label { font-style: italic; font-size: 11pt; margin: 0 0 12pt; }
.chap-title { font-size: 16pt; font-weight: bold; text-align: center; text-transform: uppercase;
              margin: 0 0 30pt; }
.front-title { font-size: 16pt; font-weight: bold; text-align: center; text-transform: uppercase;
               margin: 0 0 24pt; }
h2 { font-size: 14pt; font-weight: bold; margin: 24pt 0 14pt; break-after: avoid; }
.rule { border: 0; border-top: 1.5pt solid #000; margin: 4pt 0 0; }
.sub { font-weight: bold; margin: 10pt 0 4pt; text-align: left; break-after: avoid; }
.link { text-align: left; margin-bottom: 10pt; }
.link a { color: #0563c1; text-decoration: underline; }
ul.b { margin: 0 0 8pt; padding-left: 0.35in; line-height: 1.5; }
ul.b li { text-align: justify; }
.org-item { font-weight: bold; margin: 10pt 0 2pt; text-align: left; break-after: avoid; }
figure { margin: 6pt 0 18pt; text-align: center; break-inside: avoid; }
figure img { display: block; margin: 0 auto; max-height: 7.4in; object-fit: contain; }
figcaption { font-weight: bold; font-size: 12pt; margin-top: 6pt; text-align: center; }
table.data { border-collapse: collapse; margin: 8pt auto 4pt; font-size: 11pt; }
table.data th, table.data td { border: 1px solid #000; padding: 3pt 8pt; text-align: center; }
table.data td:first-child, table.data th:first-child { text-align: left; }
table.data th { font-weight: bold; background: #f0f0f0; }
pre.code { font-family: Consolas, "Courier New", monospace; font-size: 9.5pt; line-height: 1.35;
           background: #f5f5f5; border: 1px solid #999; padding: 8pt 10pt; margin: 6pt 0 14pt;
           white-space: pre-wrap; break-inside: avoid; }
.tcap { font-weight: bold; text-align: center; margin: 4pt 0 16pt; break-before: avoid; }
table.data tr { break-inside: avoid; }
.refs p { text-align: justify; padding-left: 0.45in; text-indent: -0.45in; margin-bottom: 12pt; }
.refs .rlink { padding-left: 0.45in; text-indent: 0; margin-top: -10pt; }
"""

FOOT_NONE = "@page { @bottom-center { content: none; } }"
FOOT_ROMAN = ("@page { @bottom-center { content: counter(page, upper-roman); "
              "font-family: Calibri, sans-serif; font-size: 12pt; vertical-align: top; padding-top: 0.45in; } }")
FOOT_ARABIC = ("@page { @bottom-center { content: counter(page); "
               "font-family: Calibri, sans-serif; font-size: 12pt; vertical-align: top; padding-top: 0.45in; } }")


def esc(s: str) -> str:
    """Escape text, then apply [placeholder] highlighting and **bold**."""
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(\[(?:Director|Roll|Div|Class)[^\]]*\])", r'<span class="ph">\1</span>', s)
    return s


# --------------------------------------------------------------------------- content
def parse(md: str):
    """Return a list of chapters: {num, title, intro: [blocks], sections: [...]}."""
    chapters, cur, sec = [], None, None
    blocks = None
    paras: list[str] = []

    def flush():
        nonlocal paras
        if paras:
            blocks.append(("p", " ".join(paras)))
            paras = []

    for raw in md.splitlines():
        line = raw.rstrip()
        if line.startswith("# "):
            if blocks is not None:
                flush()
            num, title = line[2:].split("|", 1)
            cur = {"num": int(num), "title": title, "intro": [], "sections": []}
            chapters.append(cur)
            blocks, sec = cur["intro"], None
        elif line.startswith("## "):
            flush()
            num, title = line[3:].split("|", 1)
            sec = {"num": num, "title": title, "blocks": []}
            cur["sections"].append(sec)
            blocks = sec["blocks"]
        elif not line.strip():
            flush()
        elif line.startswith("FIG|"):
            flush()
            _, num, file, cap, width = line.split("|")
            blocks.append(("fig", num, file, cap, float(width)))
        elif line.startswith("TABLE|"):
            flush()
            blocks.append(("table", line.split("|")[1:], []))
        elif line.startswith("ROW|"):
            blocks[-1][2].append(line.split("|")[1:])
        elif line.startswith("CAPTION|"):
            blocks[-1] = blocks[-1] + (line.split("|", 1)[1],)
        elif line.startswith("CODE|"):
            flush()
            if blocks and blocks[-1][0] == "code":
                blocks[-1][1].append(line[5:])
            else:
                blocks.append(("code", [line[5:]]))
        elif line.startswith("SUB|"):
            flush()
            blocks.append(("sub", line[4:]))
        elif line.startswith("LINK|"):
            flush()
            blocks.append(("link", line[5:]))
        elif line.startswith("- "):
            flush()
            if blocks and blocks[-1][0] == "ul":
                blocks[-1][1].append(line[2:])
            else:
                blocks.append(("ul", [line[2:]]))
        else:
            paras.append(line.strip())
    flush()
    return chapters


def render_blocks(blocks, organization=False) -> str:
    out = []
    for b in blocks:
        kind = b[0]
        if kind == "p":
            out.append(f"<p>{esc(b[1])}</p>")
        elif kind == "ul":
            if organization:
                for item in b[1]:
                    out.append(f'<p class="org-item">&#9679;&nbsp; {esc(item)}</p>')
            else:
                out.append('<ul class="b">' + "".join(f"<li>{esc(i)}</li>" for i in b[1]) + "</ul>")
        elif kind == "fig":
            _, num, file, cap, width = b
            out.append(f'<figure><img src="{(FIG / file).as_uri()}" style="width:{width}in">'
                       f'<figcaption><span class="marker">@@F:{num}@@</span>Fig {num} {esc(cap)}</figcaption></figure>')
        elif kind == "table":
            head = "".join(f"<th>{esc(h)}</th>" for h in b[1])
            rows = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>" for r in b[2])
            cap = b[3]
            num = cap.split()[1]
            keep = ' style="break-inside:avoid"' if len(b[2]) <= 6 else ""
            out.append(f'<div{keep}><table class="data"><thead><tr>{head}</tr></thead>'
                       f'<tbody>{rows}</tbody></table><p class="tcap"><span class="marker">@@T:{num}@@</span>'
                       f'{esc(cap)}</p></div>')
        elif kind == "tcap":
            num = b[1].split()[1]
            out.append(f'<p class="tcap"><span class="marker">@@T:{num}@@</span>{esc(b[1])}</p>')
        elif kind == "code":
            out.append('<pre class="code">' + html.escape("\n".join(b[1])) + "</pre>")
        elif kind == "sub":
            out.append(f'<p class="sub">{esc(b[1])}</p>')
        elif kind == "link":
            out.append(f'<p class="link">Reference Link: <a href="{b[1]}">{b[1]}</a></p>')
    return "\n".join(out)


def body_html(chapters, hoist=None) -> str:
    hoist = hoist or {}
    parts = []
    for ch in chapters:
        if ch["num"] == 0:  # Conclusion: unnumbered, no sections, no rules
            parts.append(f'<div class="newpage"><p class="front-title"><span class="marker">@@C:0@@</span>'
                         f'{esc(ch["title"])}</p>{render_blocks(layout.apply_floats(ch["intro"], hoist))}</div>')
            continue
        h = [f'<div class="newpage"><p class="chap-label">Chapter {ch["num"]}</p>'
             f'<p class="chap-title"><span class="marker">@@C:{ch["num"]}@@</span>{esc(ch["title"])}</p>']
        h.append(render_blocks(layout.apply_floats(ch["intro"], hoist)))
        h.append('<hr class="rule">')
        for s in ch["sections"]:
            h.append(f'<h2><span class="marker">@@S:{s["num"]}@@</span>{s["num"]} {esc(s["title"])}</h2>')
            h.append(render_blocks(layout.apply_floats(s["blocks"], hoist), organization=s["title"] == "Report Organization"))
            h.append('<hr class="rule">')
        h.append("</div>")
        parts.append("\n".join(h))
    refs = "".join('<div style="break-inside:avoid">' + f"<p>[{i}]&nbsp;&nbsp;{esc(r[0])}</p>"
                   + (f'<p class="rlink">Link: <a href="{r[1]}">{r[1]}</a></p>' if r[1] else "") + "</div>"
                   for i, r in enumerate(meta.REFERENCES, 1))
    parts.append(f'<div class="newpage refs"><p class="front-title"><span class="marker">@@C:R@@</span>'
                 f'References</p>{refs}</div>')
    return "\n".join(parts)


# --------------------------------------------------------------------------- front matter
def cover_html() -> str:
    logo = (REPORT.parent / "poster" / "assets" / "mgm_logo.png").as_uri()
    names = "".join(f'<div class="l14b">{esc(n)}</div>' for n, _ in meta.STUDENTS)
    return f"""
<style>
 @page cover {{ margin: 0.75in 1in 0.6in 1in; }}
 .cov {{ page: cover; text-align: center; line-height: 1.22; }}
 .cov div {{ margin: 0; }}
 .l14b {{ font-size: 14pt; font-weight: bold; }} .l14 {{ font-size: 14pt; }}
 .l12b {{ font-size: 12pt; font-weight: bold; }} .l12 {{ font-size: 12pt; }}
 .l16b {{ font-size: 16pt; font-weight: bold; }} .l20b {{ font-size: 20pt; font-weight: bold; line-height: 1.2; }}
 .l11b {{ font-size: 11pt; font-weight: bold; }} .gap {{ height: 7pt; }}
 .cert {{ page: cover; text-align: center; }}
 .cert h1 {{ font-size: 36pt; font-weight: bold; font-style: italic; text-decoration: underline; margin: 0 0 10pt; }}
 .cert .body {{ font-size: 13pt; font-style: italic; text-align: justify; line-height: 1.5; }}
 .cert .nm {{ font-size: 14pt; font-weight: bold; font-style: italic; }}
 .sig {{ display: flex; justify-content: space-between; margin-top: 0.75in; text-align: center; }}
 .sig div {{ width: 46%; }}
</style>
<div class="cov">
 <div class="l14b">{esc(meta.REPORT_TYPE)}</div><div class="gap"></div>
 <div class="l20b">&ldquo;{esc(meta.TITLE)}&rdquo;</div><div class="gap"></div>
 <div class="l14b">Submitted to</div><div class="gap"></div>
 <div class="l14b">DR. BABASAHEB AMBEDKAR TECHNOLOGICAL</div><div class="l14b">UNIVERSITY, LONERE</div><div class="gap"></div>
 <div class="l12b">in partial fulfillment of the requirement for the degree of</div><div class="gap"></div>
 <div class="l16b">BACHELOR OF TECHNOLOGY</div><div class="l14">in</div>
 <div class="l16b">{esc(meta.BRANCH.upper())}</div><div class="l14">By</div><div class="gap"></div>
 {names}<div class="gap"></div>
 <div class="l14b">Under the Guidance</div><div class="l14">of</div><div class="gap"></div>
 <div class="l14b">{esc(meta.GUIDE)}</div>
 <div class="l12">(Department of {esc(meta.BRANCH)})</div>
 <img src="{logo}" style="width:1.75in;height:1.2in;object-fit:contain;margin:4pt 0 2pt">
 <div class="l14b">DEPARTMENT OF {esc(meta.BRANCH.upper())}</div>
 <div class="l11b">MAHATMA GANDHI MISSION'S COLLEGE OF ENGINEERING</div>
 <div class="l11b">NANDED (M.S.)</div><div class="gap"></div>
 <div class="l14b">Academic Year {esc(meta.YEAR)}</div>
</div>
<div class="newpage cert">
 <h1>Certificate</h1>
 <img src="{logo}" style="width:1.6in;height:1.1in;object-fit:contain;margin:0 0 14pt">
 <div style="font-size:13pt;font-style:italic">This is to certify that the project entitled</div>
 <div style="font-size:12pt;font-weight:bold;margin:8pt 0 14pt">&ldquo;{esc(meta.TITLE)}&rdquo;</div>
 <div class="body">being submitted by {meta.cert_names()} to the Dr. Babasaheb Ambedkar Technological University,
 Lonere, for the award of the degree of Bachelor of Technology in {esc(meta.BRANCH)}, is a record of bonafide
 work carried out by them under my supervision and guidance. The matter contained in this report has not
 been submitted to any other university or institute for the award of any degree.</div>
 <div style="margin-top:0.8in;font-size:14pt;font-weight:bold">{esc(meta.GUIDE)}</div>
 <div style="font-size:14pt;font-weight:bold">Project Guide</div>
 <div class="sig">
  <div><div style="font-size:14pt;font-weight:bold">{esc(meta.HOD)}</div><div class="l12b">H.O.D</div>
   <div class="l12">{esc(meta.BRANCH)}</div></div>
  <div><div style="font-size:14pt;font-weight:bold">{esc(meta.DIRECTOR)}</div><div class="l12b">Director</div>
   <div class="l12">MGM's College of Engg., Nanded</div></div>
 </div>
</div>"""


def front_html(toc_rows, lof_rows) -> str:
    ack = "".join(f'<p style="text-indent:0.5in">{esc(p)}</p>' for p in meta.ACK)
    sigs = "".join(f'<div style="font-weight:bold;text-align:right;line-height:1.6">{esc(n)}_{esc(r)}</div>'
                   for n, r in meta.STUDENTS)
    abstract = "".join(f"<p>{esc(p)}</p>" for p in meta.ABSTRACT)
    toc = "".join(
        f'<tr class="{c}"><td>{esc(t)}</td><td class="pg">{p}</td></tr>' for c, t, p in toc_rows)
    lof = "".join(f"<tr><td>{n}</td><td>{esc(t)}</td><td class='pg'>{p}</td></tr>" for n, t, p in lof_rows)
    return f"""
<style>
 @page toc {{ margin-left: 1.25in; }}
 .tocpage {{ page: toc; }}
 .toc {{ width: 100%; border-collapse: collapse; font-size: 12pt; }}
 .toc td {{ padding: 1.6pt 0; vertical-align: top; }} .toc td.pg {{ text-align: right; width: 0.9in; white-space: nowrap; }}
 .toc tr.b td {{ font-weight: bold; padding-top: 5pt; }} .toc tr.s td:first-child {{ padding-left: 0.4in; }}
 .lof {{ width: 100%; border-collapse: collapse; font-size: 11pt; }}
 .lof th {{ text-align: left; font-size: 12pt; padding: 2pt 4pt 6pt; }} .lof td {{ padding: 0.6pt 4pt; vertical-align: top; }}
 .lof td.pg, .lof th.pg {{ text-align: right; white-space: nowrap; }} .lof td:first-child {{ white-space: nowrap; }}
</style>
<p class="front-title">Acknowledgement</p>{ack}
<p style="text-indent:0.5in;margin-top:18pt">With Deep Reverence,</p>{sigs}
<div style="text-align:right;margin-top:10pt;font-weight:bold">[ <span class="ph">{esc(meta.CLASS_DIV)}</span> ]</div>
<div class="newpage"><p class="front-title">Abstract</p>{abstract}</div>
<div class="newpage tocpage"><p class="front-title">Table of Contents</p><table class="toc">{toc}</table></div>
<div class="newpage"><p class="front-title">List of Figures</p>
<table class="lof"><tr><th>Figure No.</th><th>Name of Figure</th><th class="pg">Page No.</th></tr>{lof}</table></div>"""


# --------------------------------------------------------------------------- render
def chrome_pdf(name: str, body: str, foot: str) -> Path:
    BUILD.mkdir(exist_ok=True)
    src = BUILD / f"{name}.html"
    src.write_text(f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}{foot}</style></head>"
                   f"<body>{body}</body></html>", encoding="utf-8")
    pdf = BUILD / f"{name}.pdf"
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    "--allow-file-access-from-files", f"--print-to-pdf={pdf}", src.as_uri()],
                   check=True, capture_output=True, env=_tmp_env())
    return pdf


def _tmp_env() -> dict:
    """Keep Chrome's temporary files on the project drive, not on a full C: drive."""
    tmp = BUILD / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    return dict(os.environ, TEMP=str(tmp), TMP=str(tmp))


def positions(pdf: Path) -> dict[str, int]:
    found: dict[str, int] = {}
    for i, page in enumerate(PdfReader(pdf).pages, 1):
        for m in re.findall(r"@@([A-Z]:[\w.]+)@@", (page.extract_text() or "").replace("\n", "")):
            found.setdefault(m, i)
    return found


def merge(parts: list[Path]) -> None:
    """Join the part PDFs into the report, then prove every page has ink.

    pdfium (Chrome's PDF library) does the merge. pypdf was used before and wrote
    page streams with bad zlib headers: Chrome still drew them, but pdf.js-based
    viewers (VS Code, Firefox) showed every page blank."""
    import pypdfium2 as pdfium

    dst = pdfium.PdfDocument.new()
    sources = [pdfium.PdfDocument(str(p)) for p in parts]
    for src in sources:
        dst.import_pages(src)
    tmp = OUT.with_suffix(".tmp.pdf")
    dst.save(str(tmp))
    dst.close()
    for src in sources:
        src.close()
    blank = blank_pages(tmp)
    if blank:
        tmp.unlink()
        raise SystemExit(f"merge produced blank pages {blank}; report not replaced")
    os.replace(tmp, OUT)


def blank_pages(pdf: Path) -> list[int]:
    """Pages that render with no ink at all (needs pypdfium2; skipped if absent)."""
    try:
        import numpy as np
        import pypdfium2 as pdfium
    except ImportError:
        return []
    doc = pdfium.PdfDocument(str(pdf))
    out = [i + 1 for i in range(len(doc))
           if np.asarray(doc[i].render(scale=0.3).to_pil().convert("L")).min() > 200]
    doc.close()
    return out


def roman(n: int) -> str:
    vals = [(10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    out = ""
    for v, s in vals:
        while n >= v:
            out += s
            n -= v
    return out


def build() -> None:
    chapters = parse((HERE / "content.md").read_text(encoding="utf-8"))
    # Lay out the body, then let text fill the gaps figures leave, until stable.
    def render(h):
        return chrome_pdf("body", body_html(chapters, h), FOOT_ARABIC)

    if "--reuse" in sys.argv and FLOATS.exists():   # same placement as last time, no search
        hoist = json.loads(FLOATS.read_text())
        render(hoist)
    else:
        hoist = layout.optimise(render, chapters)
    FLOATS.write_text(json.dumps(hoist, indent=1), encoding="utf-8")
    body_pdf = BUILD / "body.pdf"
    print("floats:", hoist)
    print("remaining gaps:", layout.report(layout.measure(body_pdf)))
    pos = positions(body_pdf)
    n_body = len(PdfReader(body_pdf).pages)

    # front matter page numbers: Ack I, Abstract II, TOC III(-IV), LoF next
    rows, lof = [], []
    starts = [pos[f"C:{c['num']}"] for c in chapters if c["num"]] + [pos["C:0"], pos["C:R"]]
    for k, ch in enumerate(chapters):
        if ch["num"] == 0:
            continue
        a, b = starts[k], starts[k + 1] - 1
        rows.append(("b", f"Chapter {ch['num']}. {ch['title']}", f"{a}-{b}"))
        for s in ch["sections"]:
            rows.append(("s", f"{s['num']} {s['title']}", str(pos[f"S:{s['num']}"])))
            for blk in s["blocks"]:
                if blk[0] == "fig":
                    lof.append((blk[1], blk[3], pos[f"F:{blk[1]}"]))
    rows.append(("b", "Conclusion", str(pos["C:0"])))
    rows.append(("b", "References", str(pos["C:R"])))

    toc_pages = 2
    for _ in range(2):
        lof_page = 3 + toc_pages
        head = [("b", "Acknowledgement", "I"), ("b", "Abstract", "II"),
                ("b", "Table of Contents", f"III-{roman(2 + toc_pages)}" if toc_pages > 1 else "III"),
                ("b", "List of Figures", roman(lof_page))]
        front_pdf = chrome_pdf("front", front_html(head + rows, lof), FOOT_ROMAN)
        n_front = len(PdfReader(front_pdf).pages)
        new_toc = n_front - 3  # ack + abstract + lof (assumes LoF fits one page)
        if new_toc == toc_pages:
            break
        toc_pages = new_toc

    cover_pdf = chrome_pdf("cover", cover_html(), FOOT_NONE)
    merge([cover_pdf, front_pdf, body_pdf])
    total = len(PdfReader(OUT).pages)
    words = sum(len(re.sub(r"[|#*-]", " ", l).split()) for l in (HERE / "content.md").read_text(encoding="utf-8").splitlines()
                if not l.startswith(("FIG|", "ROW|", "TABLE|", "LINK|")))
    print(f"cover {len(PdfReader(cover_pdf).pages)} + front {n_front} + body {n_body} = {total} pages; "
          f"body words ~{words}; figures {len(lof)}")
    for c, t, p in rows:
        if c == "b":
            print(f"  {t:<45} {p}")


if __name__ == "__main__":
    build()
