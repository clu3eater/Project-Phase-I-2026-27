"""Run THIS project's RUL architecture on C-MAPSS and compare to the world.

WHAT THIS ANSWERS
-----------------
"Are we near what other groups achieve?" -- a question our own simulator
cannot answer, because a score on a fixture we wrote reports how hard we made
the fixture. C-MAPSS is the surface published RUL results are reported on, so
it is the only place the comparison exists.

WHAT IT DOES NOT ANSWER
-----------------------
Whether the 915 iS engine model, its health index or its RUL are validated by
real data. A turbofan's gas path shares no sensor and no failure mode with a
four-cylinder piston engine. This benchmarks the METHOD, and nothing else --
see layer3_ai/cmapss.py.

THE ARCHITECTURE IS NOT RE-TUNED
--------------------------------
`rul_lstm.RulLstm` is used exactly as the project ships it, at its own
hyperparameters. Tuning it for C-MAPSS would measure how well we can fit
C-MAPSS, which is a different and much less interesting question than how our
estimator, as built, compares.

    python scripts/benchmark_cmapss.py --subset FD001
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from layer3_ai import cmapss  # noqa: E402
from layer3_ai import prognostic_metrics as pmx  # noqa: E402
from layer3_ai.rul_lstm import RulLstm  # noqa: E402

# Published state of the art, for the comparison this script exists to make.
# RMSE in cycles, from the recent C-MAPSS literature (transformer and
# LSTM-attention families, 2021-2025).
SOTA_RMSE = {"FD001": 12.6, "FD002": 13.1, "FD003": 12.7, "FD004": 14.0}

# The sensors that are CONSTANT in FD001/FD003 and carry no information.
# Dropping them is universal practice in the literature; keeping them would
# feed the network columns with zero variance.
WINDOW = 30


def _windows(unit, cycle, x, y, length):
    """Sliding windows within each unit. Units are never crossed."""
    xs, ys, us, ts = [], [], [], []
    for u in np.unique(unit):
        m = unit == u
        order = np.argsort(cycle[m])
        xu, yu, cu = x[m][order], y[m][order], cycle[m][order]
        if len(xu) < length:
            # Left-pad short units with their first row rather than dropping
            # them: a test unit is short precisely because it was censored
            # early, and dropping those biases the fleet toward long lives.
            pad = length - len(xu)
            xu = np.vstack([np.repeat(xu[:1], pad, axis=0), xu])
            yu = np.concatenate([np.repeat(yu[:1], pad), yu])
            cu = np.concatenate([np.repeat(cu[:1], pad), cu])
        for i in range(length, len(xu) + 1):
            xs.append(xu[i - length:i])
            ys.append(yu[i - 1])
            us.append(u)
            ts.append(cu[i - 1])
    return (np.asarray(xs, dtype=np.float32), np.asarray(ys, dtype=np.float32),
            np.asarray(us), np.asarray(ts, dtype=float))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--subset", default="FD001", choices=cmapss.SUBSETS)
    ap.add_argument("--norm", default="regime", choices=("global", "regime"),
                    help="regime clusters the three operating settings and "
                         "scales within each cluster; global scales every row "
                         "together. Regime is the default: it is better on "
                         "both six-regime subsets and bit-identical on the "
                         "one-regime ones, so it is never worse. Pass "
                         "--norm global to reproduce the old baseline.")
    ap.add_argument("--drop-const", action="store_true",
                    help="with --norm regime, drop channels that are constant "
                         "within every regime: they report the operating "
                         "condition, not the engine")
    ap.add_argument("--epochs", type=int, default=200,
                    help="maximum epochs; early stopping usually ends it "
                         "sooner. The old fixed-25 baseline is --epochs 25 "
                         "--patience 0 --val-frac 0")
    ap.add_argument("--patience", type=int, default=15,
                    help="stop after this many epochs with no validation "
                         "improvement; 0 disables early stopping")
    ap.add_argument("--refit", action="store_true",
                    help="after early stopping finds the best epoch, retrain "
                         "from scratch on ALL train units for that many "
                         "epochs, so the stopping point costs no data")
    ap.add_argument("--val-frac", type=float, default=0.15,
                    help="fraction of TRAIN units held out for validation")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--json", type=Path, default=None,
                    help="append the full result to this JSON-lines file, so a "
                         "target derived from it can be traced to the run")
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    began = time.time()

    s = cmapss.load(args.subset)
    y_tr = cmapss.train_targets(s.train_unit, s.train_cycle)
    y_te = cmapss.test_targets(s.test_unit, s.test_cycle, s.test_rul)

    # Drop zero-variance columns, fit scaling on TRAIN only.
    keep = s.train_x.std(axis=0) > 1e-8
    xtr, xte = s.train_x[:, keep], s.test_x[:, keep]
    op_tr, op_te = s.train_x[:, :3], s.test_x[:, :3]
    regimes = cmapss.n_operating_regimes(op_tr)

    dropped = 0
    if args.norm == "regime":
        # Scale each row against rows flown under the SAME operating
        # condition. On a one-regime subset this is identical to global
        # scaling, which is the check that it is doing what it claims.
        sc = cmapss.fit_regime_scaler(op_tr, xtr, seed=args.seed)
        xtr, xte = (cmapss.apply_regime_scaler(sc, op_tr, xtr),
                    cmapss.apply_regime_scaler(sc, op_te, xte))
        if args.drop_const:
            # A channel constant WITHIN every regime is reporting the
            # operating condition, not the engine. It clears the global
            # zero-variance filter only because the regimes differ from each
            # other -- which is why all 24 channels survive that filter on the
            # six-regime subsets. After per-regime scaling it is a constant,
            # so it is capacity spent on a channel that cannot carry
            # degradation.
            live = ~sc.regime_only()
            dropped = int((~live).sum())
            xtr, xte = xtr[:, live], xte[:, live]
    else:
        mu, sd = xtr.mean(axis=0), xtr.std(axis=0)
        xtr, xte = (xtr - mu) / sd, (xte - mu) / sd
    print(f"{args.subset}: {int(keep.sum())} of {len(keep)} channels "
          f"informative, {regimes} operating regime(s), "
          f"{args.norm} normalisation"
          + (f", {dropped} regime-only channels dropped" if dropped else ""))

    # Hold out whole UNITS for validation, never rows. Windows from one
    # engine overlap heavily, so splitting rows would put near-copies of the
    # same window on both sides and the validation score would be measuring
    # memorisation. The split is off TRAIN only; test is never touched.
    units = np.unique(s.train_unit)
    rng = np.random.RandomState(args.seed)
    held = set(rng.permutation(units)[:max(1, int(round(args.val_frac
                                                        * len(units))))])
    is_val = np.array([u in held for u in s.train_unit])

    Xtr, Ytr, _, _ = _windows(s.train_unit[~is_val], s.train_cycle[~is_val],
                              xtr[~is_val], y_tr[~is_val], WINDOW)
    Xva, Yva, _, _ = _windows(s.train_unit[is_val], s.train_cycle[is_val],
                              xtr[is_val], y_tr[is_val], WINDOW)
    Xte, Yte, Ute, Tte = _windows(s.test_unit, s.test_cycle, xte, y_te, WINDOW)
    print(f"  windows: train {len(Xtr):,}  val {len(Xva):,} "
          f"({len(held)} held-out units)  test {len(Xte):,}")

    model = RulLstm(Xtr.shape[2])
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    lossf = nn.MSELoss()
    Xt, Yt = torch.tensor(Xtr), torch.tensor(Ytr)
    Xv, Yv = torch.tensor(Xva), torch.tensor(Yva)

    def val_rmse() -> float:
        model.eval()
        with torch.no_grad():
            p = torch.cat([model(Xv[i:i + 1024])
                           for i in range(0, len(Xv), 1024)])
            out = float(torch.sqrt(lossf(p, Yv)))
        model.train()
        return out

    best, best_ep, best_state, since = float("inf"), 0, None, 0
    for ep in range(args.epochs):
        perm = torch.randperm(len(Xt))
        total = 0.0
        for i in range(0, len(Xt), 256):
            b = perm[i:i + 256]
            opt.zero_grad()
            loss = lossf(model(Xt[b]), Yt[b])
            loss.backward()
            opt.step()
            total += float(loss.detach()) * len(b)

        v = val_rmse()
        if v < best - 1e-4:
            best, best_ep, since = v, ep + 1, 0
            best_state = {k: t.detach().clone()
                          for k, t in model.state_dict().items()}
        else:
            since += 1
        if (ep + 1) % 5 == 0:
            print(f"  epoch {ep+1:>3}  train MSE {total/len(Xt):>9.1f}"
                  f"   val RMSE {v:>7.2f}   best {best:>7.2f} @{best_ep}")
        if args.patience and since >= args.patience:
            print(f"  early stop at epoch {ep+1}: no val gain for "
                  f"{args.patience} epochs")
            break

    # Restore the best epoch, not the last. Without this, early stopping only
    # decides WHEN to stop and the weights kept are still whatever the final
    # epoch left behind, which can be past the point the model started
    # overfitting.
    if args.refit and args.patience:
        # Early stopping costs data: 15 % of the units are held out to decide
        # when to stop, and on a 100-unit subset that is 15 engines the model
        # never sees. Refitting spends the validation split only to LEARN the
        # stopping point, then trains from scratch on every unit for exactly
        # that many epochs -- the schedule without the data cost. Nothing is
        # tuned against test either way.
        print(f"  refit: retraining on all {len(units)} units for {best_ep} "
              f"epochs")
        Xall, Yall, _, _ = _windows(s.train_unit, s.train_cycle, xtr, y_tr,
                                    WINDOW)
        torch.manual_seed(args.seed)
        model = RulLstm(Xall.shape[2])
        opt = torch.optim.Adam(model.parameters(), lr=1e-3)
        Xa, Ya = torch.tensor(Xall), torch.tensor(Yall)
        model.train()
        for ep in range(best_ep):
            perm = torch.randperm(len(Xa))
            for i in range(0, len(Xa), 256):
                b = perm[i:i + 256]
                opt.zero_grad()
                lossf(model(Xa[b]), Ya[b]).backward()
                opt.step()
    elif args.patience and best_state is not None:
        model.load_state_dict(best_state)
        print(f"  using epoch {best_ep} (val RMSE {best:.2f})")
    else:
        # --patience 0 means no early stopping AND no rewind: train the full
        # schedule and keep the last epoch, which is what the old fixed-25
        # baseline did. Restoring the best epoch here would quietly make that
        # flag reproduce something else.
        print(f"  using final epoch {args.epochs} "
              f"(best val was {best:.2f} @{best_ep})")

    model.eval()
    with torch.no_grad():
        pred = np.concatenate([
            model(torch.tensor(Xte[i:i + 1024])).numpy()
            for i in range(0, len(Xte), 1024)
        ])
    pred = np.clip(pred, 0.0, cmapss.RUL_CAP_CYCLES)

    # The headline figure the literature reports: one prediction per test
    # unit, at its LAST cycle, against the label file.
    last_p, last_t = [], []
    for u in np.unique(Ute):
        m = np.where(Ute == u)[0]
        j = m[np.argmax(Tte[m])]
        last_p.append(pred[j])
        last_t.append(Yte[j])
    last_p, last_t = np.array(last_p), np.array(last_t)
    rmse_last = float(np.sqrt(np.mean((last_p - last_t) ** 2)))

    rmse_all = float(np.sqrt(np.mean((pred - Yte) ** 2)))
    sigma = float(np.std(Yte))

    trajs = pmx.trajectories_from_frame(Ute, Tte, pred, Yte)
    rep = pmx.evaluate(trajs, informative_below_h=cmapss.RUL_CAP_CYCLES - 1e-6)

    sota = SOTA_RMSE[args.subset]
    print()
    print("=" * 74)
    print(f"  {args.subset}: this project's architecture, untuned, vs published work")
    print("=" * 74)
    print(f"  RMSE, last cycle per unit (the reported figure) : {rmse_last:>8.2f}")
    print(f"  published state of the art                      : {sota:>8.2f}")
    print(f"  ratio                                           : "
          f"{rmse_last / sota:>8.2f}x")
    print()
    print(f"  RMSE over all windows                           : {rmse_all:>8.2f}")
    print(f"  target sigma                                    : {sigma:>8.2f}")
    print(f"  RMSE / sigma (all windows)                      : "
          f"{rmse_all / sigma:>8.3f}")
    print()
    print("  Saxena metrics on the same predictions:")
    for k in ("alpha_lambda", "prognostic_horizon_h", "relative_accuracy",
              "convergence", "late_fraction"):
        print(f"    {k:<26}{rep.as_dict()[k]:>10}")
    if args.json is not None:
        record = {
            "subset": args.subset, "seed": args.seed, "epochs": args.epochs,
            # Without this the file cannot tell a global run from a regime
            # run, and the whole point of the record is the comparison.
            "norm": args.norm, "regimes": int(regimes),
            "max_epochs": args.epochs, "patience": args.patience,
            "val_frac": args.val_frac, "best_epoch": best_ep,
            "refit": bool(args.refit),
            "val_rmse": round(best, 4),
            "drop_const": bool(args.drop_const), "dropped_channels": dropped,
            "rmse_last_cycle": round(rmse_last, 4),
            "sota_rmse": sota,
            "ratio_to_sota": round(rmse_last / sota, 4),
            "rmse_all_windows": round(rmse_all, 4),
            "target_sigma": round(sigma, 4),
            "rmse_sigma_ratio": round(rmse_all / sigma, 4),
            **{k: rep.as_dict()[k] for k in (
                "alpha", "lambda", "min_bound_h", "alpha_lambda",
                "prognostic_horizon_h", "relative_accuracy", "convergence",
                "late_fraction", "scored_engines")},
        }
        args.json.parent.mkdir(parents=True, exist_ok=True)
        with args.json.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        print(f"  appended -> {args.json}")

    print()
    print(f"  {time.time()-began:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
