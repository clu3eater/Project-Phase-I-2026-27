"""Evidence for the post-baseline investigation. READ-ONLY: changes nothing.

Everything here comes from held-out predictions on the 20 test engines. No
threshold is fitted here, no model is retrained, and the test set is never
modified.
"""

from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd
import torch

from common import config
from layer3_ai import features as feat
from layer3_ai import tier3_deep as t3

D = config.data_dir() / "synthetic"


def load_test():
    man = json.loads((D / "manifest.json").read_text())
    assign = feat.stratified_engine_split(man)
    full = pd.concat(
        [pd.read_parquet(D / f"{s}.parquet") for s in ("train", "val", "test")],
        ignore_index=True,
    )
    full["split"] = full["engine_id"].map(assign)
    te = feat.baseline_residuals(full[full["split"] == "test"].reset_index(drop=True))
    return man, assign, te


def tier3_predictions(te):
    ck = torch.load(config.data_dir() / "models" / "tier3.pt",
                    map_location="cpu", weights_only=False)
    fs = feat.extended()
    det = t3.Tier3Detector(fs)
    det.autoencoder.load_state_dict(ck["autoencoder"])
    det.net.load_state_dict(ck["net"])
    det.net.eval()
    det.autoencoder.eval()
    L = int(config.load_thresholds()["detectors"]["tier3"]["sequence_length"])
    X, y, idx = feat.build_sequences(
        te, fs, length=L, stride=5, label_columns=feat.FAULT_LABEL_COLUMNS
    )
    with torch.no_grad():
        out = det.net(torch.tensor(X, dtype=torch.float32))
    prob = torch.sigmoid(out["fault"]).numpy()
    anom = torch.sigmoid(out["anomaly"]).numpy().ravel()
    ae = det.autoencoder.reconstruction_error(torch.tensor(X, dtype=torch.float32))
    ae = ae.numpy() if hasattr(ae, "numpy") else np.asarray(ae)
    return X, y, idx, prob, anom, ae, np.asarray(ck["fault_thresholds"], float), \
        float(ck["ae_threshold"]), det


NAMES = [c[4:] for c in feat.FAULT_LABEL_COLUMNS]


def section(t):
    print("\n" + "=" * 78)
    print("  " + t)
    print("=" * 78)


def q_fault_classes(te, y, idx, prob, thr, man):
    """Per class: is the loss precision or recall, and where does it go?"""
    section("A. FAULT CLASSES - where each one actually loses")
    truth, pred = y > 0.05, prob > thr[None, :]
    eng = te["engine_id"].to_numpy()[idx]

    print(f"  {'class':<24}{'F1':>7}{'P':>7}{'R':>7}{'supp':>7}{'engs':>6}"
          f"  {'loses to':<34}")
    for i, n in enumerate(NAMES):
        tp = int((truth[:, i] & pred[:, i]).sum())
        fp = int((~truth[:, i] & pred[:, i]).sum())
        fn = int((truth[:, i] & ~pred[:, i]).sum())
        p = tp / max(tp + fp, 1)
        r = tp / max(tp + fn, 1)
        f1 = 2 * p * r / max(p + r, 1e-9)
        n_eng = len(set(eng[truth[:, i]].tolist()))
        # Where do the false positives really belong?
        fpm = (~truth[:, i]) & pred[:, i]
        other = {NAMES[j]: int(truth[fpm, j].sum()) for j in range(len(NAMES))
                 if j != i}
        other["HEALTHY"] = int((~truth[fpm].any(axis=1)).sum())
        top = sorted(other.items(), key=lambda kv: -kv[1])[:2]
        lose = ", ".join(f"{k} {v}" for k, v in top if v)
        print(f"  {n:<24}{f1:>7.3f}{p:>7.3f}{r:>7.3f}{int(truth[:, i].sum()):>7}"
              f"{n_eng:>6}  {lose:<34}")

    print("\n  Per-class result BY ENGINE (is it one engine or the class?)")
    for i, n in enumerate(NAMES):
        rows = []
        for e in sorted(set(eng[truth[:, i]].tolist())):
            m = eng == e
            t_, p_ = truth[m, i], pred[m, i]
            if t_.sum() == 0:
                continue
            rows.append(f"{e}:{(t_ & p_).sum() / t_.sum():.2f}")
        print(f"    {n:<24}recall per engine  {'  '.join(rows)}")


def q_anomaly(te, y, idx, anom, ae, ae_thr):
    """Which windows does the anomaly head miss?"""
    section("B. TIER-3 ANOMALY - what the misses have in common")
    truth = (y > 0.05).any(axis=1)
    eng = te["engine_id"].to_numpy()[idx]
    hours = te["flight_hours"].to_numpy()[idx]
    sev = y.max(axis=1)

    # The head's own operating threshold is fitted on train; approximate with
    # the same 0.5 the report uses for the confusion counts.
    pred = anom > 0.5
    miss = truth & ~pred
    print(f"  positives {int(truth.sum())}, missed {int(miss.sum())} "
          f"({100*miss.sum()/max(truth.sum(),1):.1f}%)")
    print("\n  MISSED windows by fault severity (the label magnitude):")
    for lo, hi in ((0.05, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)):
        m = truth & (sev >= lo) & (sev < hi)
        if m.sum() < 10:
            continue
        print(f"    severity {lo:.2f}-{hi:.2f}: {int(m.sum()):>5} windows, "
              f"missed {100*(miss & m).sum()/m.sum():>5.1f}%")
    print("\n  MISSED windows by engine:")
    for e in sorted(set(eng.tolist())):
        m = truth & (eng == e)
        if m.sum() < 10:
            continue
        print(f"    engine {e:>3}: {int(m.sum()):>5} positives, "
              f"missed {100*(miss & m).sum()/m.sum():>5.1f}%")


def q_rul_design(te, man):
    """Is the RUL target design itself the limit?"""
    section("C. RUL - is the TARGET reachable as designed?")
    from layer3_ai import rul_physics as rp

    tcfg = config.load_thresholds()
    rul_max = float(tcfg["rul"]["prediction_horizon_hours"])
    tgt = rp.piecewise_rul_target(te["rul_hours"].to_numpy(),
                                  te["chi_true"].to_numpy(), rul_max=rul_max)
    cens = te["censored"].to_numpy().astype(bool)
    print(f"  horizon cap            {rul_max:.0f} h")
    print(f"  rows                   {len(te):,}  ({100*cens.mean():.1f}% censored)")
    live = ~cens
    print(f"  uncensored target: min {tgt[live].min():.0f}  "
          f"median {np.median(tgt[live]):.0f}  max {tgt[live].max():.0f}  "
          f"sd {tgt[live].std():.1f}")
    at = float((tgt[live] >= rul_max - 1e-6).mean())
    print(f"  sitting exactly at the cap: {100*at:.1f}%")
    print()
    print("  What RMSE do the targets themselves permit?")
    sd = tgt[live].std()
    for r2 in (0.85, 0.90, 0.95):
        print(f"    to reach R2 {r2:.2f} the RMSE must be < {sd*np.sqrt(1-r2):>6.1f} h")
    print(f"    the PRD asks RMSE < 25 h, which implies "
          f"R2 > {1 - (25/sd)**2:.3f}")
    print("    -> the two PRD targets are not consistent with each other; the")
    print("       RMSE target is the far stricter of the two.")
    print()
    print("  Trivial baselines on the same target (no model at all):")
    mean_pred = np.full(live.sum(), tgt[live].mean())
    print(f"    predict the mean always : RMSE {np.sqrt(((mean_pred-tgt[live])**2).mean()):>6.1f} h  R2  0.000")
    print(f"    predict the cap always  : RMSE {np.sqrt(((rul_max-tgt[live])**2).mean()):>6.1f} h")


def q_physics_rul(te):
    """Why is the physics extrapolation so weak?"""
    section("D. RUL - why the physics estimator is weak")
    from layer3_ai import rul_physics as rp

    chi = te["chi_true"].to_numpy()
    hours = te["flight_hours"].to_numpy()
    eng = te["engine_id"].to_numpy()
    print("  The extrapolator fits a health DECLINE RATE and divides the margin")
    print("  by it. Its accuracy therefore depends on the rate being stable.")
    print()
    print(f"  {'engine':>7}{'CHI start':>11}{'CHI end':>10}{'life h':>9}"
          f"{'rate sd/mean':>14}")
    for e in sorted(set(eng.tolist()))[:10]:
        m = eng == e
        h, c = hours[m], chi[m]
        if len(h) < 50:
            continue
        # Local decline rate over successive 50-sample blocks.
        rates = []
        for a in range(0, len(h) - 50, 50):
            dh = h[a + 50] - h[a]
            if dh > 1e-6:
                rates.append(-(c[a + 50] - c[a]) / dh)
        rates = np.asarray(rates)
        pos = rates[rates > 0]
        cv = (pos.std() / pos.mean()) if len(pos) > 2 and pos.mean() > 0 else np.nan
        print(f"  {e:>7}{c[0]:>11.3f}{c[-1]:>10.3f}{h[-1]:>9.0f}{cv:>14.2f}")
    print()
    print("  A coefficient of variation near or above 1 means the decline rate")
    print("  is as variable as it is large, so extrapolating it linearly to a")
    print("  threshold cannot be accurate however the estimator is written.")


def main() -> None:
    man, assign, te = load_test()
    X, y, idx, prob, anom, ae, thr, ae_thr, det = tier3_predictions(te)
    print(f"test engines: {sorted(set(te.engine_id.tolist()))}")
    print(f"windows: {len(y):,}")
    q_fault_classes(te, y, idx, prob, thr, man)
    q_anomaly(te, y, idx, anom, ae, ae_thr)
    q_rul_design(te, man)
    q_physics_rul(te)


if __name__ == "__main__":
    main()
