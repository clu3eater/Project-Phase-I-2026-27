"""Measure the twin's tick latency under load, and say honestly what that is.

"Real-Time" is the first phrase of the problem statement's title, and until
this script existed the only latency figures in the repository came from an
unloaded run on a developer machine. A number nobody measured under load is
not evidence of a real-time property; it is evidence of a quiet afternoon.

WHAT THIS MEASURES, AND WHAT IT DOES NOT
-----------------------------------------
It measures **tick compute**: the wall time to advance the physics, encode and
decode the CAN frame, run the edge rules, score the three anomaly tiers, serve
RUL and the survival head, evaluate the advisory, and update the snapshot --
the whole of `LiveTwin._tick`.

It does **not** measure sensor-to-screen. The transport, the browser and the
render are outside it, and so is the real sensor bus. Anyone quoting this as
end-to-end latency is quoting it wrongly.

It runs on whatever CPU you run it on. That is x86-64 here, not the ARM class
of a deployed edge computer, so the figure bounds the algorithmic cost rather
than predicting on-target performance. `--throttle` pins the process to a
single core, which is the closest honest proxy available without the hardware:
it removes the parallelism a laptop has and an edge board largely does not.

USAGE
-----
    python scripts/latency_bench.py                  # 3000 ticks, no readers
    python scripts/latency_bench.py --clients 3      # 3 concurrent snapshot readers
    python scripts/latency_bench.py --throttle       # pin to one core
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# The tick budget. PRD Part 1 s6.4 gives the physics 10-20 ms; the gate in
# run.py asserts p95 < 200 ms for the whole tick, which is the number a
# 1 Hz twin actually has to hold.
BUDGET_P95_MS = 200.0


def _pin_to_one_core() -> bool:
    """Remove the parallelism an edge board mostly does not have."""
    try:
        if hasattr(os, "sched_setaffinity"):             # Linux
            os.sched_setaffinity(0, {0})
            return True
    except OSError:
        pass
    try:
        # Windows has no sched_setaffinity. The raw kernel32 call needs its
        # argument types declared or ctypes truncates the process handle and
        # the call fails silently, which is how this returned False on a
        # machine that was perfectly capable of pinning.
        import psutil
        psutil.Process().cpu_affinity([0])
        return True
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticks", type=int, default=3000)
    ap.add_argument("--clients", type=int, default=0,
                    help="concurrent snapshot readers, as console clients")
    ap.add_argument("--throttle", action="store_true",
                    help="pin to a single core as an edge-class proxy")
    ap.add_argument("--out", default="data/models/latency_bench.json")
    args = ap.parse_args()

    pinned = _pin_to_one_core() if args.throttle else False
    if args.throttle and not pinned:
        print("  ! could not pin to one core; figures are unthrottled")

    os.environ.setdefault("DT_CRUISE_HOURS", "0.05")
    from layer4_core.live import LiveTwin

    twin = LiveTwin(speed=400.0)

    # Readers hit `snapshot()` the way the console does. The point is to make
    # the tick contend for the lock rather than to measure the reader.
    stop = threading.Event()
    reads = [0]

    def reader() -> None:
        while not stop.is_set():
            twin.snapshot()
            reads[0] += 1
            time.sleep(0.05)

    threads = [threading.Thread(target=reader, daemon=True)
               for _ in range(args.clients)]
    for t in threads:
        t.start()

    samples: list[float] = []
    try:
        for _ in range(args.ticks):
            began = time.perf_counter()
            twin._tick()
            samples.append((time.perf_counter() - began) * 1000.0)
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=1.0)
        try:
            twin.stop()
        except Exception:
            pass

    # Discard the first 5%: the first ticks pay for lazy imports and the ONNX
    # session warming up, and reporting those as steady state overstates the
    # cost of every tick that follows.
    warm = max(1, len(samples) // 20)
    steady = sorted(samples[warm:])

    def pct(p: float) -> float:
        return round(steady[min(len(steady) - 1,
                                int(len(steady) * p / 100.0))], 3)

    result = {
        "ticks": len(steady),
        "clients": args.clients,
        "client_reads": reads[0],
        "throttled_to_one_core": pinned,
        "p50_ms": pct(50), "p95_ms": pct(95), "p99_ms": pct(99),
        "max_ms": round(steady[-1], 3),
        "mean_ms": round(statistics.fmean(steady), 3),
        "budget_p95_ms": BUDGET_P95_MS,
        "within_budget": pct(95) < BUDGET_P95_MS,
        "platform": f"{platform.machine()} {platform.system()}",
        "python": platform.python_version(),
        "measures": "LiveTwin._tick compute only -- NOT sensor-to-screen",
        "caveat": ("x86-64, not the ARM class of a deployed edge computer; "
                   "bounds algorithmic cost, does not predict on-target"),
    }

    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"\n  ticks {result['ticks']}  clients {args.clients}"
          f"  reads {reads[0]}"
          f"{'  [pinned to 1 core]' if pinned else ''}")
    print(f"  p50 {result['p50_ms']} ms   p95 {result['p95_ms']} ms   "
          f"p99 {result['p99_ms']} ms   max {result['max_ms']} ms")
    verdict = "WITHIN" if result["within_budget"] else "OVER"
    print(f"  {verdict} the {BUDGET_P95_MS:g} ms p95 budget")
    print(f"  {result['measures']}")
    print(f"  written to {args.out}\n")
    return 0 if result["within_budget"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
