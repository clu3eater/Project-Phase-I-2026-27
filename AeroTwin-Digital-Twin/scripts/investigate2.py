"""Second evidence pass: decompose the fusion confound, and the zero-recall
engines. READ-ONLY.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import torch

from common import config
from layer3_ai import features as feat
from layer3_ai import tier3_deep as t3

D = config.data_dir() / "synthetic"
NAMES = [c[4:] for c in feat.FAULT_LABEL_COLUMNS]


def load():
    man = json.loads((D / "manifest.json").read_text())
    assign = feat.stratified_engine_split(man)
    full = pd.concat(
        [pd.read_parquet(D / f"{s}.parquet") for s in ("train", "val", "test")],
        ignore_index=True,
    )
    full["split"] = full["engine_id"].map(assign)
    te = feat.baseline_residuals(full[full["split"] == "test"].reset_index(drop=True))
    ck = torch.load(config.data_dir() / "models" / "tier3.pt",
                    map_location="cpu", weights_only=False)
    fs = feat.extended()
    det = t3.Tier3Detector(fs)
    det.autoencoder.load_state_dict(ck["autoencoder"])
    det.net.load_state_dict(ck["net"])
    det.net.eval(); det.autoencoder.eval()
    L = int(config.load_thresholds()["detectors"]["tier3"]["sequence_length"])
    X, y, idx = feat.build_sequences(
        te, fs, length=L, stride=5, label_columns=feat.FAULT_LABEL_COLUMNS
    )
    with torch.no_grad():
        out = det.net(torch.tensor(X, dtype=torch.float32))
    return (man, te, X, y, idx,
            torch.sigmoid(out["fault"]).numpy(),
            torch.sigmoid(out["anomaly"]).numpy().ravel(),
            np.asarray(ck["fault_thresholds"], float))


def auc(score, label):
    from sklearn.metrics import roc_auc_score
    if label.all() or not label.any():
        return float("nan")
    return float(roc_auc_score(label, score))


def main() -> None:
    man, te, X, y, idx, prob, anom, thr = load()
    eng = te["engine_id"].to_numpy()[idx]
    truth_any = (y > 0.05).any(axis=1)
    engines = sorted(set(eng.tolist()))

    print("=" * 78)
    print("  E. IS THE 'FUSION DEGRADATION' POPULATION OR MODEL?")
    print("=" * 78)
    print("  The previous 0.997 AUC was measured on TEN engines; this baseline")
    print("  uses TWENTY. Resampling ten-engine subsets of the SAME model and")
    print("  the SAME predictions separates the two explanations: if ten-engine")
    print("  AUC routinely reaches 0.99+, the drop is the population, not the")
    print("  features.")
    print()
    rng = np.random.default_rng(0)
    aucs = []
    for _ in range(400):
        pick = set(rng.choice(engines, size=10, replace=False).tolist())
        m = np.array([e in pick for e in eng])
        a = auc(anom[m], truth_any[m])
        if np.isfinite(a):
            aucs.append(a)
    aucs = np.asarray(aucs)
    print(f"  anomaly-head AUC on the full 20 engines : {auc(anom, truth_any):.4f}")
    print(f"  same model, 10-engine subsets (n=400)   : "
          f"min {aucs.min():.4f}  p05 {np.quantile(aucs,0.05):.4f}  "
          f"median {np.median(aucs):.4f}  p95 {np.quantile(aucs,0.95):.4f}  "
          f"max {aucs.max():.4f}")
    print(f"  fraction of 10-engine subsets scoring >= 0.99: "
          f"{100*(aucs>=0.99).mean():.1f}%")
    print(f"  fraction scoring >= 0.976 (this baseline)    : "
          f"{100*(aucs>=0.976).mean():.1f}%")

    print()
    print("  Per-engine anomaly AUC (which engines carry the loss):")
    for e in engines:
        m = eng == e
        a = auc(anom[m], truth_any[m])
        n_pos = int(truth_any[m].sum())
        if np.isnan(a):
            print(f"    engine {e:>3}: {'all-healthy' if n_pos == 0 else 'all-fault':>12}"
                  f"  ({int(m.sum())} windows)")
        else:
            print(f"    engine {e:>3}: AUC {a:.3f}   {n_pos:>5} positives "
                  f"of {int(m.sum()):>5}")

    # ---- the zero-recall engines --------------------------------------
    print()
    print("=" * 78)
    print("  F. THE ZERO-RECALL ENGINES")
    print("=" * 78)
    truth, pred = y > 0.05, prob > thr[None, :]
    for cls, bad in (("cooling_degradation", [83, 99]),
                     ("overheating_trend", [82])):
        i = NAMES.index(cls)
        print(f"\n  {cls}")
        for e in sorted(set(eng[truth[:, i]].tolist())):
            m = (eng == e) & truth[:, i]
            if not m.any():
                continue
            sev = y[m, i]
            co = [NAMES[j] for j in range(len(NAMES))
                  if j != i and (y[(eng == e), j] > 0.05).any()]
            mark = "  <-- MISSED ENTIRELY" if e in bad else ""
            print(f"    engine {e:>3}: {int(m.sum()):>4} windows  "
                  f"severity {sev.mean():.2f} (max {sev.max():.2f})  "
                  f"mean p {prob[m, i].mean():.3f}  thr {thr[i]:.2f}  "
                  f"recall {(truth[m, i] & pred[m, i]).sum()/m.sum():.2f}"
                  f"{mark}")
            if co:
                print(f"              co-occurring: {', '.join(co)}")

    # ---- what the injected schedule said -------------------------------
    print()
    print("  What the generator injected on those engines:")
    for e in (83, 99, 82):
        info = man["engines"][str(e)]
        print(f"    engine {e:>3} (life {info['life_hours']:.0f} h):")
        for f in info["faults"]:
            print(f"        {f['mode']:<24} onset {f['onset_hours']:>7.1f} h  "
                  f"severity {f['severity']:.2f}  ramp {f['ramp_hours']:>6.1f} h  "
                  f"expressed {f['expressed']}")


if __name__ == "__main__":
    main()
