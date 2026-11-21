"""What the edge stack actually costs -- measured, on this machine.

Run:  python scripts/edge_footprint.py

"Dependency-light enough for a Raspberry Pi" is an assertion until somebody
measures it. This measures it: resident memory as each layer loads, inference
latency, and whether repeated scoring leaks.

WHAT THIS DOES AND DOES NOT ESTABLISH
--------------------------------------
It establishes that the SOFTWARE fits a Pi-class budget: the memory ceiling,
the model size and the per-inference cost are all measured rather than
estimated.

It does NOT establish on-target deployment. This runs on x86-64, and an ARM
core will differ -- most likely slower per inference and, for the INT8 graph,
possibly faster than float where x86 was slower, because ARM's int8 SIMD
changes that trade. Nothing here should be read as a flight-hardware result;
it is the ground-side evidence that the target is reachable, and the on-target
figure has to be taken on the target.
"""

from __future__ import annotations

import gc
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# A Raspberry Pi 4 ships in 2, 4 and 8 GB. The smallest is the one to size
# against -- a budget that only fits the largest variant is not a budget.
PI_SMALLEST_MB = 2048


def main() -> int:
    try:
        import psutil
    except ImportError:
        print("this measurement needs psutil: pip install psutil")
        return 1

    proc = psutil.Process(os.getpid())

    def mb() -> float:
        return proc.memory_info().rss / 1024 / 1024

    base = mb()

    from layer1_edge import edge_infer as ei
    from layer1_edge.edge_rules import RuleEngine

    gc.collect()
    imported = mb()

    rules = RuleEngine()
    if not ei.FLOAT_PATH.exists():
        print("no exported model; run scripts/export_edge.py first")
        return 1
    scorer = ei.EdgeScorer()
    gc.collect()
    ready = mb()

    w = np.zeros((30, 23), dtype=np.float32)
    scorer.score(w)
    t = []
    for _ in range(200):
        a = time.perf_counter()
        scorer.score(w)
        t.append((time.perf_counter() - a) * 1000.0)
    gc.collect()
    after = mb()

    d = {
        "baseline_mb": round(base, 1),
        "after_imports_mb": round(imported, 1),
        "ready_mb": round(ready, 1),
        "after_200_inferences_mb": round(after, 1),
        "growth_over_200_mb": round(after - ready, 2),
        "inference_ms_median": round(float(np.median(t)), 3),
        "inference_ms_p95": round(float(np.percentile(t, 95)), 3),
        "onnx_kb": round(ei.FLOAT_PATH.stat().st_size / 1024, 1),
        "n_rules": len(rules.rules) if hasattr(rules, "rules") else None,
        "pi_smallest_mb": PI_SMALLEST_MB,
        "share_of_smallest_pi_pct": round(after / PI_SMALLEST_MB * 100, 2),
        "platform": f"{os.name} {sys.platform}",
    }

    print("EDGE STACK FOOTPRINT")
    print(f"  interpreter baseline       {d['baseline_mb']:7.1f} MB")
    print(f"  after edge imports         {d['after_imports_mb']:7.1f} MB")
    print(f"  rules + ONNX session up    {d['ready_mb']:7.1f} MB")
    print(f"  after 200 inferences       {d['after_200_inferences_mb']:7.1f} MB")
    print(f"  growth over 200            {d['growth_over_200_mb']:7.2f} MB")
    print()
    print(f"  Tier-3 inference           {d['inference_ms_median']:.3f} ms median, "
          f"{d['inference_ms_p95']:.3f} p95")
    print(f"  ONNX graph on disk         {d['onnx_kb']:.1f} KB")
    print()
    print(f"  {d['share_of_smallest_pi_pct']:.1f} % of a 2 GB Raspberry Pi 4")
    if d["growth_over_200_mb"] > 5.0:
        print(f"  WARNING: {d['growth_over_200_mb']:.1f} MB growth over 200 "
              f"inferences suggests a leak; a twelve-hour sortie is ~86,000.")
    print()
    print("  Measured on x86-64. NOT an on-target result: an ARM core will "
          "differ, and the on-target figure has to be taken on the target.")

    out = REPO / "data" / "models" / "edge_footprint.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(d, indent=2), encoding="utf-8")
    print(f"\n  written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
