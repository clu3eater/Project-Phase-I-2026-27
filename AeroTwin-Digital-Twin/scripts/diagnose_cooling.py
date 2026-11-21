"""Why cooling_degradation collapsed: per-engine breakdown of the Tier-3 head.

The retrained Tier-3 classifier scores 0.112 F1 on ``cooling_degradation``
against 0.987 on ``overheating_trend``, and drags macro-F1 to 0.750. Two facts
predict that:

  * the sensor audit puts those two thermal faults at cosine 0.761 -- the
    closest pair in the whole fleet;
  * ``cooling_degradation`` and ``overheating_trend`` NEVER co-occur in
    training (0 rows of 9,350) but co-occur on 54 % of cooling rows in test,
    all on one engine.

If the diagnosis is right, the class is detected perfectly well on the test
engines that carry it ALONE, and fails only on the engine that carries both.
That distinguishes "the model cannot see cooling degradation" -- which would be
a real capability gap -- from "the model has never been shown these two faults
together", which is a dataset coverage gap and a different problem with a
different fix.

    python scripts/diagnose_cooling.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import torch

from common import config
from layer3_ai import features as feat
from layer3_ai import tier3_deep as t3

CD = "cooling_degradation"
OT = "overheating_trend"


def main() -> int:
    ck = torch.load(config.data_dir() / "models" / "tier3.pt",
                    map_location="cpu", weights_only=False)
    fs = feat.extended()
    det = t3.Tier3Detector(fs)
    det.autoencoder.load_state_dict(ck["autoencoder"])
    det.net.load_state_dict(ck["net"])
    det.autoencoder.eval()
    det.net.eval()
    thr = np.asarray(ck["fault_thresholds"], dtype=float)

    length = int(config.load_thresholds()["detectors"]["tier3"]["sequence_length"])
    te = pd.read_parquet(config.data_dir() / "synthetic" / "test.parquet")
    X, y, idx = feat.build_sequences(
        te, fs, length=length, stride=5, label_columns=feat.FAULT_LABEL_COLUMNS,
    )
    engines = te["engine_id"].to_numpy()[idx]

    with torch.no_grad():
        out = det.net(torch.tensor(X, dtype=torch.float32))
    prob = torch.sigmoid(out["fault"]).numpy()

    names = [c[4:] for c in feat.FAULT_LABEL_COLUMNS]
    ci, oi = names.index(CD), names.index(OT)
    truth = y > 0.05
    pred = prob > thr[None, :]

    print("=" * 78)
    print(f"  {CD}: per-engine breakdown on the test split")
    print("=" * 78)
    print(f"  {'engine':>7}  {'windows':>7}  {'true':>5}  {'caught':>6}  "
          f"{'recall':>7}  {'also overheating?':>18}")
    print("  " + "-" * 72)

    for e in sorted(set(engines.tolist())):
        m = engines == e
        n_true = int(truth[m, ci].sum())
        if n_true == 0:
            continue
        caught = int((truth[m, ci] & pred[m, ci]).sum())
        also_ot = bool(truth[m, oi].any())
        print(f"  {e:>7}  {int(m.sum()):>7}  {n_true:>5}  {caught:>6}  "
              f"{caught / n_true:>7.3f}  {'YES -- unseen pair' if also_ot else 'no':>18}")

    # What is it called instead?
    m = truth[:, ci]
    if m.any():
        print("\n  When a true cooling_degradation window is MISSED, what does the")
        print("  model predict instead?")
        print("  " + "-" * 72)
        missed = m & ~pred[:, ci]
        counts = [(names[j], int(pred[missed, j].sum())) for j in range(len(names))]
        for name, c in sorted(counts, key=lambda kv: -kv[1]):
            if c:
                print(f"    {name:<28} {c:>6} of {int(missed.sum())} missed windows")

    alone = np.array([not truth[engines == e, oi].any() for e in engines])
    for label, mask in (("engines carrying cooling ALONE", m & alone),
                        ("engine carrying BOTH thermal faults", m & ~alone)):
        if mask.any():
            r = (truth[mask, ci] & pred[mask, ci]).sum() / mask.sum()
            print(f"\n  recall, {label:<38} {r:.3f}  ({int(mask.sum())} windows)")

    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
