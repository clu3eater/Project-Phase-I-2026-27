"""Close the white space a figure leaves when it does not fit at the foot of a page.

A rendered PDF is measured page by page. Where a page stops early and the next
page opens with a figure, the paragraph that follows that figure is moved in
front of it, so text fills the space and the figure moves down -- the same
"float" that LaTeX and Word layout perform. Both builders call `apply_floats`
on their block lists before rendering, and `plan` after each render.
"""
from __future__ import annotations

import re

from pypdf import PdfReader

PAGE_H = 792.0                    # Letter, points
TOP, BOTTOM = PAGE_H - 72, 72     # 1 in margins
FIG = re.compile(r"(?:@@F:[\w.]+@@)?Fig (\d+(?:\.\d+)*) ")
CHAPTER = re.compile(r"(?:@@C:\w+@@)?\s*(Chapter \d|CONCLUSION|REFERENCES)", re.I)
MIN_GAP = 0.12                    # a fifth of a page or so is worth closing


def measure(pdf_path) -> list[tuple[float, str | None, bool]]:
    """Per page: fraction of the text area left empty at the bottom, and the
    number of a figure whose caption is the first text on the page (if any),
    and whether the page opens a new chapter."""
    pages = []
    for page in PdfReader(pdf_path).pages:
        frags: list[tuple[float, str]] = []

        def visit(text, cm, tm, font, size):
            if not text.strip():
                return
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]  # text origin in page space
            if BOTTOM - 4 <= y <= TOP + 30:
                frags.append((y, text.strip()))

        page.extract_text(visitor_text=visit)
        if not frags:
            pages.append((1.0, None, False))
            continue
        low = min(y for y, _ in frags)
        gap = max(0.0, (low - BOTTOM) / (TOP - BOTTOM))
        top_y = max(y for y, _ in frags)
        top_text = "".join(t for y, t in frags if top_y - y < 3)
        m = FIG.search(top_text)
        pages.append((gap, m.group(1) if m else None, bool(CHAPTER.match(top_text))))
    return pages


def apply_floats(blocks: list, hoist: dict[str, int]) -> list:
    """Return blocks with up to hoist[fig] following paragraphs moved before each figure.

    A negative count lifts the figure above that many preceding paragraphs instead,
    for a figure with no text after it to move. A "w:<fig>" entry scales its width."""
    out = [("fig", b[1], b[2], b[3], b[4] * hoist[f"w:{b[1]}"]) if b[0] == "fig" and f"w:{b[1]}" in hoist
           else b for b in blocks]
    i = 0
    while i < len(out):
        b = out[i]
        if b[0] == "fig" and hoist.get(b[1], 0) < 0:
            k, j = 0, i - 1
            while k < -hoist[b[1]] and j >= 0 and out[j][0] in ("p", "ul"):
                k, j = k + 1, j - 1
            if k:
                out[i - k:i + 1] = [b] + out[i - k:i]
        i += 1
    i = 0
    while i < len(out):
        b = out[i]
        if b[0] == "fig" and hoist.get(b[1]):
            k, j = 0, i + 1
            while k < hoist[b[1]] and j < len(out) and out[j][0] in ("p", "ul"):
                k, j = k + 1, j + 1
            if k:
                moved = out[i + 1:i + 1 + k]
                out[i:i + 1 + k] = moved + [b]
                i += k
        i += 1
    return out


def movable_after(chapters) -> dict[str, tuple[int, int]]:
    """Paragraphs (after, before) each figure that can move past it."""
    avail = {}
    for ch in chapters:
        for blocks in [ch["intro"]] + [s["blocks"] for s in ch["sections"]]:
            for i, b in enumerate(blocks):
                if b[0] == "fig":
                    n, j = 0, i + 1
                    while j < len(blocks) and blocks[j][0] in ("p", "ul"):
                        n, j = n + 1, j + 1
                    m, j = 0, i - 1
                    while j >= 0 and blocks[j][0] in ("p", "ul"):
                        m, j = m + 1, j - 1
                    avail[b[1]] = (n, m)
    return avail


def score(pages) -> float:
    """White space inside chapters. A chapter's last page may end early, so it is not counted."""
    total = 0.0
    for p in range(len(pages) - 1):
        gap = pages[p][0]
        if gap >= MIN_GAP and not pages[p + 1][2]:
            total += gap
    return total


def report(pages) -> list[str]:
    out = []
    for p in range(len(pages) - 1):
        gap, _, _ = pages[p]
        _, fig, chap = pages[p + 1]
        if gap >= MIN_GAP and not chap:
            out.append(f"p{p + 1}:{gap:.0%}" + (f" before Fig {fig}" if fig else ""))
    return out


def optimise(render, chapters, start=None, max_trials=150, log=print) -> dict[str, int]:
    """Search figure placements that reduce white space inside chapters.

    `render(hoist)` lays the document out and returns the PDF path. Gaps are
    visited in page order; for each, moving one paragraph either way across the
    figure is tried, and a move is kept only if the total white space shrinks."""
    avail = movable_after(chapters)
    hoist = dict(start or {})
    pages = measure(render(hoist))
    best = score(pages)
    tried: set[tuple[str, int]] = set()
    trials = 0
    while trials < max_trials:
        targets = [pages[p + 1][1] for p in range(len(pages) - 1)
                   if pages[p][0] >= MIN_GAP and pages[p + 1][1] and not pages[p + 1][2]]
        moved = False
        for fig in targets:
            after, before = avail.get(fig, (0, 0))
            cur = hoist.get(fig, 0)
            options = [(fig, v) for v in (cur + 1, cur - 1, cur + 2, cur - 2)
                       if -before <= v <= after and (fig, v) not in tried]
            options += [(f"w:{fig}", w) for w in (0.85, 0.75)
                        if (f"w:{fig}", w) not in tried and hoist.get(f"w:{fig}", 1) > w]
            for key, v in options:
                tried.add((key, v))
                trial = dict(hoist, **{key: v})
                trials += 1
                tp = measure(render(trial))
                ts = score(tp)
                if ts < best - 0.02:
                    log(f"  {key}: {hoist.get(key, 0)} -> {v}, white space {best:.2f} -> {ts:.2f}")
                    hoist, pages, best, moved = trial, tp, ts, True
                    break
                if trials >= max_trials:
                    break
            if moved or trials >= max_trials:
                break
        if not moved:
            break
    render(hoist)  # leave the chosen layout as the last render
    return {k: v for k, v in hoist.items() if (v != 1 if k.startswith("w:") else v != 0)}
