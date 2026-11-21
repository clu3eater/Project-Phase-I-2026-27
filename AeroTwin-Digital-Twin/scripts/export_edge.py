"""Export the trained Tier-3 network for the aircraft, and measure the export.

Run:  python scripts/export_edge.py

Produces ``data/models/tier3_edge.onnx`` (deployed), its INT8 sibling (kept but
NOT deployed -- see the report), and ``tier3_edge_report.json``.

The windows used for verification are REAL, drawn from engines the model never
trained on. That is not fussiness: measured on synthetic Gaussian noise the
float/int8 deviation looks clean at 0.33 / 0.50 / 0.27 with no decision
changed, and on real held-out windows the same export deviates by 3.32 / 8.22 /
1.95 and changes five anomaly decisions in three hundred. Verifying on noise
would certify a graph that disagrees with the validated model on 1.7 % of what
it will actually see.
"""

from __future__ import annotations

import pickle
import sys
import warnings
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

warnings.filterwarnings("ignore")

# Engines held out of training. Verification on training engines would measure
# how well the quantisation reproduces what the model memorised.
HELD_OUT = (81, 85, 90, 95)
N_WINDOWS = 300


def main() -> int:
    import pandas as pd
    import torch

    from layer1_edge import edge_infer as ei
    from layer3_ai import features as feat
    from layer3_ai import tier3_deep as t3

    ckpt = REPO / "data" / "models" / "tier3.pt"
    if not ckpt.exists():
        print(f"no trained model at {ckpt}; run scripts/train_tier3.py first")
        return 1

    det = t3.Tier3Detector()
    sd = torch.load(ckpt, map_location="cpu", weights_only=False)
    det.net.load_state_dict(sd["net"] if isinstance(sd, dict) and "net" in sd else sd)
    fs, L = det.features, det.sequence_length

    rows: list[dict] = []
    for e in HELD_OUT:
        shard = REPO / "data" / "synthetic" / "_shards" / f"engine_{e:04d}.pkl"
        if not shard.exists():
            print(f"missing shard {shard.name}; run the fleet generator first")
            return 1
        with open(shard, "rb") as fh:
            rows += pickle.load(fh)["rows"]

    df = feat.add_structured_residual_features(pd.DataFrame(rows))
    x = fs.normalise(df[list(fs.columns)].to_numpy(dtype=np.float32))
    step = max(1, (len(x) - L) // N_WINDOWS)
    windows = np.stack(
        [x[i:i + L] for i in range(0, len(x) - L, step)][:N_WINDOWS]
    ).astype(np.float32)

    print(f"verifying on {len(windows)} real windows from engines "
          f"{', '.join(str(e) for e in HELD_OUT)}")
    d = ei.export(det.net, windows).as_dict()

    print()
    print(f"  float32   {d['float_bytes'] / 1024:8.1f} KB   "
          f"{d['float_ms_median']:.3f} ms median   {d['float_ms_p95']:.3f} p95")
    print(f"  int8      {d['int8_bytes'] / 1024:8.1f} KB   "
          f"{d['int8_ms_median']:.3f} ms median   {d['int8_ms_p95']:.3f} p95")
    print(f"  size {d['size_ratio']}x smaller, speed-up {d['speedup']}x")
    print(f"  max logit deviation  {d['max_delta']}")
    print(f"  anomaly decisions changed  {d['decisions_changed']} "
          f"of {d['windows_compared']}")
    print()

    changed = d["decisions_changed"] / max(1, d["windows_compared"])
    if changed > 0.0 or d["speedup"] < 1.0:
        print("  VERDICT: deploy the FLOAT graph.")
        if d["speedup"] < 1.0:
            print(f"           int8 is {1 / d['speedup']:.2f}x SLOWER here -- the "
                  f"quantise/dequantise cost per call exceeds the gemm saving "
                  f"on a network this small.")
        if changed > 0.0:
            print(f"           int8 changes {changed:.1%} of anomaly decisions, "
                  f"so it is a different model and the evaluation that "
                  f"justified deployment no longer applies.")
        print("           int8 is kept for targets where the trade may invert "
              "(ARM with int8 SIMD), but must be re-measured there.")
    else:
        print("  VERDICT: int8 is smaller, faster and decision-identical here.")
    print(f"\n  report written to {ei.REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
