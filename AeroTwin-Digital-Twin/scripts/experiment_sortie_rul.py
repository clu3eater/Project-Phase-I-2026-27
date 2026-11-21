"""DEV-183: give the RUL estimator the long view that is already in the data.

THE HYPOTHESIS, STATED BEFORE IT IS TESTED
-------------------------------------------
RUL is the RATE of degradation. The shipped estimator reads a 30-sample window
-- about 30 seconds, or 0.0013 % of an engine's life -- and a window that short
observes a STATE, not a rate. DEV-182 measured the consequence: the same
architecture scores 1.09-1.36x published state of the art on C-MAPSS, where it
is handed whole cycles, and alpha-lambda 0.20 on this engine, where it is
handed 30 seconds.

So the prediction is that the deficit is observability, and that feeding the
SAME network a sequence of per-sortie summaries -- which the dataset already
contains, 17 to 115 of them per engine spanning hundreds of flight hours --
closes a large part of the gap without touching the architecture.

If it does not, the hypothesis is wrong and DEV-182's conclusion needs
revisiting. Recorded that way deliberately: an experiment that cannot fail
tells you nothing.

WHAT IS DELIBERATELY NOT DONE
-----------------------------
`flight_hours` is NOT a feature. It is known, and it correlates with RUL
almost by definition, so including it teaches "RUL = TBO - hours" -- the
circularity PRD Part 0 s0.5 exists to prevent and the exact failure DEV-45
found in the fault labels. The elapsed time BETWEEN sorties is used, but only
as the denominator of a rate, never as an absolute clock.

The architecture, its hyperparameters and the loss are untouched.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import config  # noqa: E402
from layer3_ai import features as feat  # noqa: E402
from layer3_ai import prognostic_metrics as pmx  # noqa: E402
from layer3_ai import rul_physics as rp  # noqa: E402
from layer3_ai.rul_lstm import RulLstm  # noqa: E402

# How many consecutive sorties the network sees. 12 is roughly a fifth of a
# median engine's 58 sorties -- long enough to contain a trend, short enough
# that an engine still contributes many training windows.
N_SORTIES = 12


def sortie_table(df: pd.DataFrame, fs) -> pd.DataFrame:
    """One row per (engine, sortie): the summary, and the RATE of change.

    Two halves, and the second is the point. The mean of each channel over a
    sortie is a STATE. The change in that mean since the previous sortie,
    divided by the flight hours between them, is a RATE -- which is the
    quantity RUL actually depends on and the one a 30-second window cannot
    contain at any sampling rate.
    """
    cols = list(fs.columns)
    agg = {c: "mean" for c in cols}
    agg["flight_hours"] = "max"
    agg["rul_hours"] = "last"
    agg["censored"] = "last"
    agg["chi_true"] = "last"

    g = (df.groupby(["engine_id", "sortie"], as_index=False)
           .agg(agg)
           .sort_values(["engine_id", "sortie"])
           .reset_index(drop=True))

    # Spread within the sortie: a degrading engine gets noisier as well as
    # hotter, and the mean alone throws that away.
    sd = (df.groupby(["engine_id", "sortie"], as_index=False)[cols]
            .std()
            .sort_values(["engine_id", "sortie"])
            .reset_index(drop=True))
    for c in cols:
        g[f"sd_{c}"] = sd[c].fillna(0.0).to_numpy()

    # Per-hour rate of change against the previous sortie of the SAME engine.
    by = g.groupby("engine_id")
    dt = by["flight_hours"].diff()
    dt = dt.where(dt > 1e-6)
    for c in cols:
        g[f"rate_{c}"] = (by[c].diff() / dt).fillna(0.0).to_numpy()

    return g


def build_sequences(g: pd.DataFrame, cols: list[str], n_sorties: int):
    """Sequences of consecutive sorties within one engine. Engines never cross."""
    xs, ys, us, ts, cs = [], [], [], [], []
    for eid, e in g.groupby("engine_id"):
        e = e.sort_values("sortie")
        x = e[cols].to_numpy(dtype=np.float32)
        y = e["rul_hours"].to_numpy(dtype=np.float32)
        h = e["flight_hours"].to_numpy(dtype=float)
        cen = e["censored"].to_numpy()
        for i in range(n_sorties, len(e) + 1):
            xs.append(x[i - n_sorties:i])
            ys.append(y[i - 1])
            us.append(eid)
            ts.append(h[i - 1])
            cs.append(cen[i - 1])
    return (np.asarray(xs, dtype=np.float32), np.asarray(ys, dtype=np.float32),
            np.asarray(us), np.asarray(ts, dtype=float), np.asarray(cs))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--sorties", type=int, default=N_SORTIES)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    began = time.time()

    d = config.data_dir() / "synthetic"
    man = json.loads((d / "manifest.json").read_text())
    assign = feat.stratified_engine_split(man)
    full = pd.concat(
        [pd.read_parquet(d / f"{s}.parquet") for s in ("train", "val", "test")],
        ignore_index=True,
    )
    full["split"] = full["engine_id"].map(assign)

    tcfg = config.load_thresholds()
    rul_max = float(tcfg["rul"]["prediction_horizon_hours"])
    targets = tcfg["rul"]["targets"]
    fs = feat.extended()

    frames = {}
    for split in ("train", "val", "test"):
        part = feat.baseline_residuals(
            full[full["split"] == split].reset_index(drop=True))
        part["rul_hours"] = rp.piecewise_rul_target(
            part["rul_hours"].to_numpy(), part["chi_true"].to_numpy(),
            rul_max=rul_max)
        frames[split] = sortie_table(part, fs)

    cols = ([c for c in fs.columns]
            + [f"sd_{c}" for c in fs.columns]
            + [f"rate_{c}" for c in fs.columns])

    # Scale on TRAIN only.
    tr = frames["train"]
    mu = tr[cols].mean().to_numpy(dtype=np.float32)
    sd = tr[cols].std().replace(0.0, 1.0).to_numpy(dtype=np.float32)
    for k in frames:
        frames[k][cols] = (frames[k][cols] - mu) / sd

    Xtr, Ytr, _, _, Ctr = build_sequences(frames["train"], cols, args.sorties)
    Xva, Yva, _, _, Cva = build_sequences(frames["val"], cols, args.sorties)
    Xte, Yte, Ute, Tte, Cte = build_sequences(frames["test"], cols, args.sorties)

    # Censored windows are dropped from TRAINING and from SCORING alike, which
    # is what the shipped pipeline does -- a censored engine's "RUL" is a lower
    # bound, not a label.
    ktr, kva, kte = Ctr < 0.5, Cva < 0.5, Cte < 0.5
    Xtr, Ytr = Xtr[ktr], Ytr[ktr]
    Xva, Yva = Xva[kva], Yva[kva]
    Xte, Yte, Ute, Tte = Xte[kte], Yte[kte], Ute[kte], Tte[kte]

    print(f"sorties per window {args.sorties}   features {len(cols)}")
    print(f"  windows: train {len(Xtr):,}  val {len(Xva):,}  test {len(Xte):,}")
    print(f"  test engines {len(np.unique(Ute))}")
    if len(Xtr) < 50 or len(Xte) < 20:
        print("  !! too few windows to draw a conclusion from")
        return 1

    model = RulLstm(Xtr.shape[2])
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    lossf = nn.MSELoss()
    Xt, Yt = torch.tensor(Xtr), torch.tensor(Ytr)
    Xv, Yv = torch.tensor(Xva), torch.tensor(Yva)

    best_val, best_state = float("inf"), None
    for ep in range(args.epochs):
        model.train()
        perm = torch.randperm(len(Xt))
        for i in range(0, len(Xt), 128):
            b = perm[i:i + 128]
            opt.zero_grad()
            lossf(model(Xt[b]), Yt[b]).backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            vl = float(lossf(model(Xv), Yv)) if len(Xv) else float("nan")
        if vl == vl and vl < best_val:
            best_val, best_state = vl, {k: v.clone() for k, v in
                                        model.state_dict().items()}
        if (ep + 1) % 10 == 0:
            print(f"  epoch {ep+1:>3}  val MSE {vl:>9.1f}")
    if best_state is not None:
        model.load_state_dict(best_state)

    model.eval()
    with torch.no_grad():
        pred = np.concatenate([
            model(torch.tensor(Xte[i:i + 512])).numpy()
            for i in range(0, len(Xte), 512)
        ])
    pred = np.clip(pred, 0.0, rul_max)

    m = rp.rul_metrics(pred, Yte, unit=Ute, t_h=Tte, horizon_hours=rul_max)
    pm = m["prognostic"]
    ratio = m["rmse"] / m["target_sigma"]

    # The shipped baseline, measured on the same engines in DEV-178.
    BASE = {"rmse_sigma_ratio": 0.874, "alpha_lambda": 0.200,
            "relative_accuracy": 0.519, "rmse": 121.3}

    print()
    print("=" * 76)
    print("  DEV-183: sequence of SORTIES vs the shipped 30-second window")
    print("=" * 76)
    rows = [
        ("RMSE / sigma", ratio, BASE["rmse_sigma_ratio"],
         float(targets["rmse_sigma_ratio"]), "<"),
        ("alpha-lambda", pm["alpha_lambda"], BASE["alpha_lambda"],
         float(targets["alpha_lambda"]), ">"),
        ("relative accuracy", pm["relative_accuracy"], BASE["relative_accuracy"],
         float(targets["relative_accuracy"]), ">"),
    ]
    print(f"  {'metric':<22}{'sorties':>10}{'shipped':>10}{'target':>10}   verdict")
    print("  " + "-" * 64)
    for label, got, base, want, comp in rows:
        ok = got > want if comp == ">" else got < want
        better = got > base if comp == ">" else got < base
        print(f"  {label:<22}{got:>10.3f}{base:>10.3f}{want:>10.2f}   "
              f"{'MET' if ok else 'not met':<8}"
              f"{'(improved)' if better else '(WORSE)'}")
    print()
    print(f"  raw RMSE {m['rmse']:.1f} h (shipped {BASE['rmse']:.1f})   "
          f"sigma {m['target_sigma']:.1f}   R2 {m['r2']:.3f}")
    print(f"  late {m['late_fraction']:.3f}   NASA {m['nasa_score']:.1f}   "
          f"horizon {pm['prognostic_horizon_h']:.1f} h   "
          f"convergence {pm['convergence']:.1f}")

    if args.json is not None:
        rec = {"sorties": args.sorties, "seed": args.seed, "epochs": args.epochs,
               "features": len(cols), "test_windows": int(len(Xte)),
               "rmse": round(m["rmse"], 3), "target_sigma": round(m["target_sigma"], 3),
               "rmse_sigma_ratio": round(ratio, 4), "r2": round(m["r2"], 4),
               "late_fraction": m["late_fraction"], "nasa_score": m["nasa_score"],
               **{k: pm[k] for k in ("alpha_lambda", "relative_accuracy",
                                     "prognostic_horizon_h", "convergence",
                                     "scored_engines")}}
        args.json.parent.mkdir(parents=True, exist_ok=True)
        with args.json.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
        print(f"  appended -> {args.json}")

    print(f"\n  {time.time()-began:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
