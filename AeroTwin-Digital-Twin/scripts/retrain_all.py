"""Run the whole Layer 3 pipeline end to end and collect the numbers.

Every model in this system is trained or scored by a separate script, which is
right -- each is independently runnable and independently arguable. But after a
fleet regeneration they all have to be re-run, in order, and the results
gathered in one place, because no number from before the regeneration is
comparable any more.

Order matters in two places: ``eval_fusion`` needs the Tier 3 model that
``train_tier3`` writes, and nothing else does.

A stage that fails does NOT stop the run. The alternative -- aborting the whole
pipeline because one evaluation raised -- means a two-hour job produces nothing
at all, and the failure is usually confined to one stage. Failures are recorded
and reported at the end rather than buried in a log.

    python scripts/retrain_all.py
    python scripts/retrain_all.py --quick     # short epochs, for a smoke run
    python scripts/retrain_all.py --only train_tier3
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOGS = REPO / "data" / "training_logs"

# (name, extra args). Ordered: train_tier3 must precede export_edge and
# eval_fusion; train_rul must precede train_survival, which has to learn the
# same fleet.
#
# export_edge and train_survival were not stages. Both write models the live
# twin SERVES -- the on-aircraft ONNX scorer and the survival head -- so a fleet
# regeneration through this script left the twin serving models trained on the
# previous physics, with nothing to say so. Found when the physics was
# recalibrated to the manufacturer's performance table (DEV-226).
STAGES: list[tuple[str, list[str]]] = [
    # The out-of-distribution check is fitted on the same training rows the
    # models learn from, so it belongs in the same run as the models.
    ("fit_ood", []),
    ("eval_tier2", []),
    ("train_tier3", []),
    ("export_edge", []),
    ("eval_fusion", []),
    ("eval_health", []),
    # Measures the first-passage RUL interval against the served one on the
    # regenerated fleet; nothing adopts it unless this says so.
    ("eval_rul_interval", []),
    ("train_rul", []),
    ("train_survival", []),
    ("eval_federated", []),
    ("validate_physics_om", []),
]

# Stages that accept --quick / --epochs.
TRAINERS = {"train_tier3", "train_rul"}


def run_stage(name: str, extra: list[str], quick: bool) -> dict:
    LOGS.mkdir(parents=True, exist_ok=True)
    log = LOGS / f"{name}.log"
    cmd = [sys.executable, "-u", str(REPO / "scripts" / f"{name}.py"), *extra]
    if quick and name in TRAINERS:
        cmd.append("--quick")

    started = time.time()
    print(f"\n{'=' * 78}\n  {name}\n{'=' * 78}", flush=True)
    with log.open("w", encoding="utf-8") as fh:
        proc = subprocess.run(
            cmd, cwd=REPO, stdout=fh, stderr=subprocess.STDOUT, text=True
        )
    elapsed = time.time() - started

    tail = ""
    try:
        lines = log.read_text(encoding="utf-8", errors="ignore").splitlines()
        tail = "\n".join(lines[-40:])
    except OSError:
        pass
    print(tail, flush=True)
    status = "ok" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})"
    print(f"  -> {name}: {status} in {elapsed:.0f}s   log: {log}", flush=True)

    return {"stage": name, "returncode": proc.returncode,
            "elapsed_s": round(elapsed, 1), "log": str(log)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quick", action="store_true",
                    help="short epochs on the trainers, for a smoke run")
    ap.add_argument("--only", action="append", default=None,
                    help="run only these stages (repeatable)")
    args = ap.parse_args()

    stages = [s for s in STAGES if not args.only or s[0] in args.only]
    if not stages:
        print(f"no stage matched {args.only}; known: {[s[0] for s in STAGES]}")
        return 2

    started = time.time()
    results = [run_stage(name, extra, args.quick) for name, extra in stages]

    print(f"\n{'=' * 78}\n  SUMMARY\n{'=' * 78}")
    for r in results:
        mark = "ok  " if r["returncode"] == 0 else "FAIL"
        print(f"  [{mark}] {r['stage']:<18} {r['elapsed_s']:>8.0f}s")
    failed = [r["stage"] for r in results if r["returncode"] != 0]
    print(f"\n  total {time.time() - started:.0f}s")
    if failed:
        print(f"  {len(failed)} stage(s) FAILED: {', '.join(failed)}")
    else:
        print("  all stages completed")
    print("=" * 78)

    (LOGS / "summary.json").write_text(json.dumps(results, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
