"""Figures for the AI4TS @ AAAI-27 paper, drawn only from recorded result files.

    .venv/Scripts/python.exe paper/figures/make_figures.py

Reads data/benchmarks/survival.json. Nothing here trains or re-scores a model.

FORMAT RULES THIS FILE IS HELD TO (AAAI-27 author kit)
- "Labels and other text with the actual illustration must be at least
  nine-point type." Every figure is drawn at the size it is printed (7.0 in for
  the full-width figure, 3.3 in for a column), so the sizes below are the
  printed sizes, and none is below 9 pt.
- Fonts that are "CID and Identity-H" must be converted to outlines or removed,
  even inside figures. Matplotlib embeds TrueType as exactly that, so figures
  are written as 600 dpi PNG, a format the kit lists as acceptable, which
  carries no fonts at all.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
DPI = 600

# Reference palette, light mode, first three categorical slots (the subset that
# validates all-pairs for colour-vision deficiency). Markers differ as well, so
# identity never rests on colour alone and the figure survives grey printing.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#d9d8d3"

MIN_PT = 9.0          # AAAI floor for any text inside a figure
TITLE_PT = 9.6        # box titles in the pipeline diagram
BODY_PT = MIN_PT      # everything else

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Times New Roman", "Times", "Nimbus Roman", "DejaVu Serif"],
    "font.size": MIN_PT,
    "axes.labelsize": MIN_PT,
    "axes.titlesize": MIN_PT,
    "legend.fontsize": MIN_PT,
    "legend.title_fontsize": MIN_PT,
    "xtick.labelsize": MIN_PT,
    "ytick.labelsize": MIN_PT,
    "axes.edgecolor": INK_2,
    "axes.labelcolor": INK,
    "xtick.color": INK_2,
    "ytick.color": INK_2,
    "mathtext.fontset": "stix",  # Times-like maths to match the text
})


def _save(fig, stem: str) -> None:
    # Fixed canvas, no tight-bbox cropping: the PNG is exactly the printed
    # size, so a 9 pt label stays 9 pt when LaTeX places it at that width.
    fig.savefig(HERE / f"{stem}.png", dpi=DPI)
    plt.close(fig)


def reliability_figure() -> None:
    data = json.loads((REPO / "data" / "benchmarks" / "survival.json")
                      .read_text(encoding="utf-8"))
    run = next(r for r in data["results"]
               if r.get("calibration") == "out-of-fold calibration")
    min_n = 10
    fig, ax = plt.subplots(figsize=(3.3, 2.75))
    fig.subplots_adjust(left=0.155, right=0.975, bottom=0.165, top=0.975)
    ax.plot([0, 1], [0, 1], ls=(0, (4, 3)), lw=0.9, color=INK_2, zorder=1)
    ax.text(0.99, 0.03, "dashed: perfect\ncalibration", ha="right",
            va="bottom", color=INK_2)
    for (h, marker), color in zip((("25", "o"), ("50", "s"), ("100", "^")),
                                  SERIES):
        bins = [b for b in run["reliability"][h] if b["n"] >= min_n]
        xs = [b["predicted"] for b in bins]
        ys = [b["observed"] for b in bins]
        ns = [b["n"] for b in bins]
        ax.plot(xs, ys, color=color, lw=1.2, zorder=2)
        ax.scatter(xs, ys, s=[10 + 2.4 * n ** 0.5 for n in ns], marker=marker,
                   color=color, edgecolor="white", linewidth=0.8, zorder=3,
                   label=f"{h} h")
    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.02, 1.02)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_xlabel("Predicted probability of failure within $H$")
    ax.set_ylabel("Observed failure frequency")
    ax.grid(True, color=GRID, lw=0.5)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    leg = ax.legend(title="Horizon $H$", loc="upper left", frameon=False,
                    handletextpad=0.3, borderaxespad=0.2, markerscale=0.8)
    leg._legend_box.align = "left"
    _save(fig, "fig_reliability")


# 1 data unit = 0.5 in on both axes of the pipeline canvas, so a 9 pt body line
# (x1.15 leading) is ~0.29 units tall and a 9.6 pt title ~0.32 units.
_BODY_LINE = BODY_PT * 1.15 / 72 / 0.5
_TITLE_LINE = TITLE_PT * 1.2 / 72 / 0.5


def _box(ax, x, y, w, h, text, face, edge=INK_2):
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                                boxstyle="round,pad=0.02,rounding_size=0.08",
                                facecolor=face, edgecolor=edge, lw=0.8))
    title, *body = text.split("\n")
    n = len(body)
    block = _TITLE_LINE + _BODY_LINE * n + 0.06
    ax.text(x, y + block / 2 - _TITLE_LINE / 2, title, ha="center",
            va="center", fontsize=TITLE_PT, fontweight="bold", color=INK)
    ax.text(x, y - block / 2 + _BODY_LINE * n / 2, "\n".join(body),
            ha="center", va="center", fontsize=BODY_PT, color=INK,
            linespacing=1.15)


def _arrow(ax, p, q):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=8,
                                 lw=0.9, color=INK_2, shrinkA=0, shrinkB=0))


def pipeline_figure() -> None:
    width_in, height_in = 7.0, 2.55
    fig = plt.figure(figsize=(width_in, height_in))
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, width_in / 0.5)
    ax.set_ylim(0.2, 0.2 + height_in / 0.5)
    ax.axis("off")
    neutral, det, prog = "#f1f0ec", "#e3edf9", "#ddf3ea"
    bh = 1.5
    y_top, y_mid, y_bot = 3.85, 2.45, 1.05
    # columns: sensors | tier 1 + twin | residuals | models | outputs
    w = (1.9, 2.45, 2.45, 2.55, 3.25)
    gap = 0.33
    lefts = [0.05]  # keep the first box's border off the image edge
    for wi in w[:-1]:
        lefts.append(lefts[-1] + wi + gap)
    cx = [lo + wi / 2 for lo, wi in zip(lefts, w)]

    _box(ax, cx[0], y_mid, w[0], bh, "Sensors\nCAN bus,\n1 Hz frames", neutral)
    _box(ax, cx[1], y_top, w[1], bh,
         "Tier 1: limits\ncertified limits,\nwith persistence", det)
    _box(ax, cx[1], y_bot, w[1], bh,
         "Shadow twin\nas-new mean-value\nphysics model", neutral)
    _box(ax, cx[2], y_mid, w[2], bh,
         "Residuals\nmeasured minus\ntwin, relative to\nown baseline", neutral)
    _box(ax, cx[3], y_top, w[3], bh,
         "Tiers 2 and 3\nstatistical\nensemble; LSTM\nautoencoder, head", det)
    _box(ax, cx[4], y_top, w[4], bh,
         "Safety-gated fusion\nmodels alone: up to\nCAUTION; EMERGENCY\nneeds a crossed limit", det)
    _box(ax, cx[3], y_bot, w[3], bh,
         "Sortie features\nlevel, scatter,\nrate of 34 features", prog)
    _box(ax, cx[4], y_bot, w[4], bh,
         "Failure risk\nP(fail within $H$),\n$H$ = 12 to 400 h,\nonly where skilful", prog)

    def right(i):
        return cx[i] + w[i] / 2

    def left(i):
        return cx[i] - w[i] / 2

    half = bh / 2
    _arrow(ax, (right(0), y_mid + 0.45), (left(1), y_top - 0.35))
    _arrow(ax, (right(0), y_mid - 0.45), (left(1), y_bot + 0.35))
    _arrow(ax, (right(0), y_mid), (left(2), y_mid))
    _arrow(ax, (right(1), y_bot + 0.35), (cx[2] - 0.6, y_mid - half))
    _arrow(ax, (right(2), y_mid + 0.45), (left(3), y_top - 0.35))
    _arrow(ax, (right(2), y_mid - 0.45), (left(3), y_bot + 0.35))
    _arrow(ax, (right(3), y_top), (left(4), y_top))
    _arrow(ax, (right(3), y_bot), (left(4), y_bot))
    # Tier 1 score bypasses the model tiers and enters fusion directly
    top, rail = y_top + half, y_top + half + 0.27
    ax.plot([cx[1], cx[1], cx[4]], [top, rail, rail], color=INK_2, lw=0.9)
    _arrow(ax, (cx[4], rail), (cx[4], top))
    ax.text(cx[3], rail + 0.04, "rule score", ha="center", va="bottom",
            fontsize=BODY_PT, color=INK_2)
    _save(fig, "fig_pipeline")


def ceiling_figure() -> None:
    """How much of point RUL is predictable at all (F100, RMSE / sigma).

    Values as recorded in layer3_ai/rul_survival.py (module docstring) and
    docs/SOFTWARE_DOCUMENTATION.md s6.5 -- one oracle ablation run, in which the
    hidden-state oracle scored 0.760. The sensor LSTM figure is the matched-
    window result of data/benchmarks/a1_matched.json (serving path).
    """
    rows = [  # (label, rmse/sigma, kind)
        ("Sensor LSTM (deployed)", 0.799, "sensor"),
        ("Oracle: hidden wear state", 0.760, "causal"),
        ("+ engine's past wear rate", 0.771, "causal"),
        ("+ true fault schedule", 0.752, "future"),
        ("+ future flight profile", 0.693, "future"),
        ("+ whole-life wear rate", 0.490, "future"),
    ]
    colour = {"sensor": SERIES[2], "causal": SERIES[0], "future": SERIES[1]}
    legend_name = {"sensor": "sensors only", "causal": "known at prediction time",
                   "future": "uses future information"}
    fig, ax = plt.subplots(figsize=(3.3, 2.45))
    fig.subplots_adjust(left=0.455, right=0.93, bottom=0.17, top=0.80)
    ys = list(range(len(rows)))[::-1]
    seen = set()
    for y, (label, v, kind) in zip(ys, rows):
        ax.barh(y, v, height=0.62, color=colour[kind],
                label=None if kind in seen else legend_name[kind])
        seen.add(kind)
        ax.text(v + 0.015, y, f"{v:.3f}", va="center", ha="left", color=INK)
    ax.set_yticks(ys)
    ax.set_yticklabels([r[0] for r in rows])
    ax.set_xlim(0, 1.0)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_xlabel(r"RMSE / $\sigma$  (lower is better)")
    ax.tick_params(axis="y", length=0)
    ax.grid(True, axis="x", color=GRID, lw=0.5)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.legend(loc="lower left", bbox_to_anchor=(-0.84, 1.0), ncol=2,
              frameon=False, handlelength=1.0, handletextpad=0.4,
              columnspacing=0.8, borderaxespad=0.1)
    _save(fig, "fig_ceiling")


def cooling_figure() -> None:
    """Radiator blockage at maximum continuous power, shadow-twin test rig.

    Values as recorded in layer4_core/tests/test_test_rig.py (docstring of
    test_a_partly_blocked_radiator_is_caught_by_authority_before_temperature)
    and docs/SOFTWARE_DOCUMENTATION.md s22.3.
    """
    block = [0, 30, 45, 70]
    coolant = [98.4, 100.3, 101.9, 143.7]
    flap = [0.49, 0.68, 0.84, 1.00]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(3.3, 1.95))
    fig.subplots_adjust(left=0.14, right=0.985, bottom=0.235, top=0.86,
                        wspace=0.42)
    a1.axhline(120, color=INK_2, lw=0.9, ls=(0, (4, 3)))
    a1.text(2, 122, "limit 120", color=INK_2, va="bottom")
    a1.plot(block, coolant, "o-", color=SERIES[0], lw=1.2, ms=4.5)
    a1.set_ylim(90, 150)
    a1.set_yticks([90, 120, 150])
    a1.set_title("Coolant (°C)", loc="left", color=INK)
    a2.axhline(1.0, color=INK_2, lw=0.9, ls=(0, (4, 3)))
    a2.text(2, 1.02, "fully open", color=INK_2, va="bottom")
    a2.plot(block, flap, "s-", color=SERIES[0], lw=1.2, ms=4.5)
    a2.set_ylim(0.3, 1.15)
    a2.set_yticks([0.4, 0.7, 1.0])
    a2.set_title("Cooling-flap travel", loc="left", color=INK)
    a1.annotate("+1.9", (30, 100.3), xytext=(30, 107), ha="center", color=INK)
    a2.annotate("+0.19", (30, 0.68), xytext=(22, 0.83), ha="center", color=INK)
    for a in (a1, a2):
        a.set_xticks(block)
        a.set_xlim(-5, 75)
        a.grid(True, color=GRID, lw=0.5)
        a.set_axisbelow(True)
        for side in ("top", "right"):
            a.spines[side].set_visible(False)
    fig.supxlabel("Radiator blockage (%)", y=0.02, fontsize=MIN_PT)
    _save(fig, "fig_cooling")


if __name__ == "__main__":
    reliability_figure()
    pipeline_figure()
    ceiling_figure()
    cooling_figure()
    print("wrote", ", ".join(p.name for p in sorted(HERE.glob("fig_*.png"))))
