"""Charts for the report, drawn with matplotlib from the repository's own
result files (data/models/*.json, data/benchmarks/*.json)."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "Project_report" / "figures"
MODELS = ROOT / "data" / "models"

BLUE, ORANGE, GREY, GREEN, RED = "#2a78d6", "#eb6834", "#9a968a", "#1baf7a", "#d03b3b"
plt.rcParams.update({
    "font.family": "Arial", "font.size": 10, "axes.spines.top": False,
    "axes.spines.right": False, "axes.edgecolor": "#555", "axes.linewidth": 0.8,
    "axes.titleweight": "bold", "axes.titlesize": 10.5, "figure.dpi": 100,
})


def load(name: str) -> dict:
    return json.loads((MODELS / name).read_text())


def save(fig, name: str) -> None:
    fig.savefig(OUT / f"{name}.png", dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def gantt() -> None:
    tasks = [
        ("Problem study and literature survey", date(2026, 7, 13), date(2026, 8, 2), GREY),
        ("Requirement analysis and SRS", date(2026, 7, 27), date(2026, 8, 9), GREY),
        ("System and UML design", date(2026, 8, 3), date(2026, 8, 23), BLUE),
        ("Increment 1: physics model, edge layer", date(2026, 8, 17), date(2026, 9, 13), BLUE),
        ("Increment 2: AI detection, health, RUL", date(2026, 9, 7), date(2026, 10, 4), BLUE),
        ("Increment 3: twin core, API, security", date(2026, 9, 28), date(2026, 10, 25), BLUE),
        ("Increment 4: console, squadron operations", date(2026, 10, 12), date(2026, 11, 8), BLUE),
        ("Testing and evaluation", date(2026, 9, 14), date(2026, 11, 15), GREEN),
        ("Report writing and review", date(2026, 11, 2), date(2026, 11, 29), ORANGE),
    ]
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    for i, (name, a, b, c) in enumerate(tasks):
        ax.barh(i, (b - a).days, left=mdates.date2num(a), height=0.55, color=c, edgecolor="white")
    ax.set_yticks(range(len(tasks)), [t[0] for t in tasks])
    ax.invert_yaxis()
    ax.xaxis_date()
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.grid(axis="x", color="#e1e0d9", linewidth=0.7)
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0)
    save(fig, "fig4_1_2_gantt")


def performance() -> None:
    full, one = load("latency_bench.json"), load("latency_bench_1core.json")
    edge, t3 = load("edge_footprint.json"), load("tier3_edge_report.json")
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(7.4, 2.9), gridspec_kw={"width_ratios": [1.35, 1]})
    labels = ["p50", "p95", "p99"]
    x = range(3)
    v1 = [full["p50_ms"], full["p95_ms"], full["p99_ms"]]
    v2 = [one["p50_ms"], one["p95_ms"], one["p99_ms"]]
    w = 0.36
    b1 = a1.bar([i - w / 2 - 0.01 for i in x], v1, w, color=BLUE, label="all cores, 3 clients")
    b2 = a1.bar([i + w / 2 + 0.01 for i in x], v2, w, color=ORANGE, label="pinned to one core")
    a1.axhline(200, color=RED, linestyle="--", linewidth=1.2)
    a1.text(2.45, 204, "200 ms budget", color=RED, ha="right", va="bottom", fontsize=9)
    for bars in (b1, b2):
        for r in bars:
            a1.text(r.get_x() + r.get_width() / 2, r.get_height() + 3, f"{r.get_height():.0f}",
                    ha="center", fontsize=8.5)
    a1.set_xticks(list(x), labels)
    a1.set_ylabel("Twin tick compute (ms)")
    a1.set_ylim(0, 230)
    a1.set_title("Twin tick latency")
    a1.legend(frameon=False, fontsize=8.5, loc="upper left", bbox_to_anchor=(0.0, 0.80))
    names = ["Model size\n(KB)", "Resident\nmemory (MB)", "Inference\np50 (ms ×100)"]
    vals = [edge["onnx_kb"], edge["after_200_inferences_mb"], edge["inference_ms_median"] * 100]
    shown = [f"{edge['onnx_kb']:.0f}", f"{edge['after_200_inferences_mb']:.0f}",
             f"{edge['inference_ms_median']:.2f}"]
    bars = a2.bar(names, vals, color=[BLUE, BLUE, BLUE], width=0.55)
    for r, t in zip(bars, shown):
        a2.text(r.get_x() + r.get_width() / 2, r.get_height() + 3, t, ha="center", fontsize=9)
    a2.set_title("Edge model footprint")
    a2.set_ylim(0, 185)
    a2.tick_params(axis="x", labelsize=8.5)
    a2.text(1, 168, f"int8 version {t3['size_ratio']:.1f}× smaller;\n"
            f"{t3['decisions_changed']} of {t3['windows_compared']} decisions changed",
            ha="center", fontsize=8.3, color="#333")
    fig.tight_layout()
    save(fig, "fig4_9_performance")


def detection() -> None:
    f = load("fusion_report.json")
    t = f["tiers_alone_on_test"]
    rows = [("Statistical\nensemble", t["Tier 2 statistical"]), ("LSTM\nautoencoder", t["Tier 3 autoencoder"]),
            ("Deep anomaly\nhead", t["Tier 3 anomaly head"]), ("Fused\n(final)", f["test"])]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(7.4, 2.9))
    names = [r[0] for r in rows]
    prec = [r[1]["precision"] for r in rows]
    rec = [r[1]["recall"] for r in rows]
    fpr = [r[1]["fpr"] * 100 for r in rows]
    x = range(len(rows))
    w = 0.36
    a1.bar([i - w / 2 - 0.01 for i in x], prec, w, color=BLUE, label="Precision")
    a1.bar([i + w / 2 + 0.01 for i in x], rec, w, color=GREY, label="Recall")
    a1.set_xticks(list(x), names, fontsize=8.3)
    a1.set_ylim(0, 1.12)
    a1.set_title("Precision and recall (40 unseen engines)")
    a1.legend(frameon=False, fontsize=8.5, ncol=2, loc="upper left")
    bars = a2.bar(names, fpr, color=[GREY, GREY, GREY, BLUE], width=0.55)
    for r, v in zip(bars, fpr):
        a2.text(r.get_x() + r.get_width() / 2, v + 0.12, f"{v:.1f}%", ha="center", fontsize=9)
    a2.set_ylabel("False-positive rate (%)")
    a2.set_ylim(0, 6.3)
    a2.tick_params(axis="x", labelsize=8.3)
    a2.set_title("False alarms on healthy engines")
    fig.tight_layout()
    save(fig, "fig5_2_detection")


def fault_f1() -> None:
    per = load("fault_namer_report.json")["per_class"]
    names = {"misfire": "Misfire", "abnormal_vibration": "Abnormal vibration",
             "lubrication_issue": "Lubrication issue", "injector_abnormal": "Injector abnormality",
             "overheating_trend": "Overheating trend", "cooling_degradation": "Cooling degradation",
             "sensor_drift": "Sensor drift", "combustion_instability": "Combustion instability"}
    rows = sorted(((names[k], v["test_f1"]) for k, v in per.items()), key=lambda r: r[1])
    fig, ax = plt.subplots(figsize=(7.0, 2.9))
    cols = [BLUE if v >= 0.8 else GREY for _, v in rows]
    bars = ax.barh([r[0] for r in rows], [r[1] for r in rows], color=cols, height=0.6)
    for r, (_, v) in zip(bars, rows):
        ax.text(v + 0.01, r.get_y() + r.get_height() / 2, f"{v:.2f}", va="center", fontsize=9)
    ax.axvline(0.8, color="#555", linestyle="--", linewidth=1)
    ax.text(0.805, -0.85, "0.80", fontsize=8.5, color="#555")
    ax.set_xlim(0, 1.08)
    ax.set_xlabel("F1 score on unseen engines")
    ax.tick_params(axis="y", length=0)
    save(fig, "fig5_5_faults")


def hidden_degradation() -> None:
    fig, ax = plt.subplots(figsize=(7.0, 1.9))
    rows = [("Certified limits alarm", 77, ORANGE), ("Degrading, every limit satisfied", 7558, GREY),
            ("…of those, flagged by the system", 6567, BLUE)]
    for i, (n, v, c) in enumerate(rows):
        ax.barh(i, v, color=c, height=0.55)
        ax.text(v + 80, i, f"{v:,}", va="center", fontsize=9.5, fontweight="bold")
    ax.set_yticks(range(3), [r[0] for r in rows])
    ax.invert_yaxis()
    ax.set_xlim(0, 8600)
    ax.set_xlabel("Evaluation windows (12,165 windows, 40 unseen engines)")
    ax.tick_params(axis="y", length=0)
    save(fig, "fig5_1_hidden")


def cooling() -> None:
    block = [0, 30, 45, 70]
    cool = [98.4, 100.3, 101.9, 143.7]
    flap = [0.49, 0.68, 0.84, 1.00]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(7.4, 2.7))
    a1.plot(block, cool, "o-", color=ORANGE, linewidth=2)
    a1.axhline(120, color=RED, linestyle="--", linewidth=1.2)
    a1.text(1, 122, "limit 120 °C", color=RED, fontsize=9)
    for x, y in zip(block, cool):
        a1.text(x, y + 2.5, f"{y}", ha="center", fontsize=8.5)
    a1.set_ylim(90, 155)
    a1.set_xlabel("Radiator blockage (%)")
    a1.set_ylabel("Coolant temperature (°C)")
    a1.set_title("What a limit monitor watches")
    a2.plot(block, flap, "o-", color=BLUE, linewidth=2)
    for x, y in zip(block, flap):
        a2.text(x, y + 0.035, f"{y:.2f}", ha="center", fontsize=8.5)
    a2.set_ylim(0, 1.15)
    a2.set_xlabel("Radiator blockage (%)")
    a2.set_ylabel("Cooling-flap travel (0–1)")
    a2.set_title("What the twin also watches")
    fig.tight_layout()
    save(fig, "fig5_3_cooling")


if __name__ == "__main__":
    for f in (gantt, performance, detection, fault_f1, hidden_degradation, cooling):
        f()
    print("charts done")


def audit() -> None:
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(7.4, 2.7), gridspec_kw={"width_ratios": [1.25, 1]})
    rows = [("No automated tests", 45), ("Random row split", 15), ("Readings from Math.random()", 13),
            ("Sends data to a cloud LLM", 10), ("Tests on unseen engines", 10)]
    names = [r[0] for r in rows][::-1]
    vals = [r[1] for r in rows][::-1]
    bars = a1.barh(names, vals, color=[BLUE, ORANGE, ORANGE, ORANGE, ORANGE], height=0.6)
    for r, v in zip(bars, vals):
        a1.text(v + 0.8, r.get_y() + r.get_height() / 2, str(v), va="center", fontsize=9)
    a1.set_xlim(0, 80)
    a1.set_xlabel("Projects (out of 72)")
    a1.set_title("Audit of 72 public projects")
    a1.tick_params(axis="y", length=0, labelsize=8.6)
    bars = a2.bar(["Random row\nsplit", "Unseen\nengines"], [96.0, 62.8], color=[ORANGE, BLUE], width=0.55)
    for r, v in zip(bars, [96.0, 62.8]):
        a2.text(r.get_x() + r.get_width() / 2, v + 1.5, f"{v:.1f}%", ha="center", fontsize=9)
    a2.set_ylim(0, 110)
    a2.set_ylabel("Accuracy (%)")
    a2.set_title("Same model, two test methods")
    fig.tight_layout()
    save(fig, "fig2_9_audit")


if __name__ == "__main__":
    audit()
