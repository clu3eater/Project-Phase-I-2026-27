"""Train the per-fault namer (layer3_ai/fault_namer.py) on the stratified engine split.

Run:  python scripts/train_fault_namer.py

Protocol, identical in spirit to scripts/train_tier3.py:
  * the same stratified ENGINE split -- no engine in two sets;
  * features built by replaying each engine's samples, in time order, through
    the live class `SortieHistory`: one definition for training and serving;
  * one HistGradientBoosting classifier per fault;
  * per fault, the choice "current sample only" vs "with history" and the
    decision threshold are both made on VALIDATION engines;
  * reported once, on TEST engines never touched by any choice.

Writes data/models/fault_namer.joblib and data/models/fault_namer_report.json.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import joblib  # noqa: E402

from common import config  # noqa: E402
from layer3_ai import features as feat  # noqa: E402
from layer3_ai.fault_namer import MIN_HISTORY_SORTIES, SortieHistory, history_columns  # noqa: E402

LABEL_ABOVE = 0.05      # same positive definition as tier3_deep.multilabel_metrics
TRAIN_ROWS = 160_000    # sampled after the replay; the replay itself sees every row
EVAL_ROWS = 80_000
GBM = dict(max_iter=250, learning_rate=0.08, random_state=0)


def _splits() -> dict[str, pd.DataFrame]:
    spec = importlib.util.spec_from_file_location("tr3", REPO / "scripts" / "train_tier3.py")
    tr3 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tr3)
    return tr3.load_splits()


def replay(df: pd.DataFrame) -> pd.DataFrame:
    """History features for every row, from that engine's past and present only."""
    df = df.sort_values(["engine_id", "flight_hours", "t_s"]).reset_index(drop=True)
    cols = history_columns()
    out = np.full((len(df), len(cols)), np.nan)
    done = np.zeros(len(df), dtype=int)     # completed sorties behind each sample
    recs = df.to_dict("records")
    hist, eng, sortie = None, None, None
    for i, r in enumerate(recs):
        if r["engine_id"] != eng:
            hist, eng, sortie = SortieHistory(), r["engine_id"], None
        if r["sortie"] != sortie:
            if sortie is not None:
                hist.close_sortie()
            sortie = r["sortie"]
        hist.observe(r, float(r["flight_hours"]))
        f = hist.features()
        out[i] = [f[c] for c in cols]
        done[i] = len(hist.means)
    frame = pd.concat([df, pd.DataFrame(out, columns=cols)], axis=1)
    frame["sorties_done"] = done
    return frame


def _f1(p: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    tp, fp, fn = int((p & y).sum()), int((p & ~y).sum()), int((~p & y).sum())
    pr = tp / (tp + fp) if tp + fp else 0.0
    rc = tp / (tp + fn) if tp + fn else 0.0
    return (2 * pr * rc / (pr + rc) if pr + rc else 0.0), pr, rc


def _tune(p: np.ndarray, y: np.ndarray) -> float:
    grid = np.linspace(0.05, 0.95, 19)
    return float(grid[int(np.argmax([_f1(p > t, y)[0] for t in grid]))])


def main() -> int:
    t0 = time.time()
    frames = _splits()
    base = list(feat.extended().columns)
    hcols = history_columns()
    labels = list(feat.FAULT_LABEL_COLUMNS)
    D = {}
    for s in ("train", "val", "test"):
        full = replay(frames[s])
        n = TRAIN_ROWS if s == "train" else EVAL_ROWS
        D[s] = full.sample(n=min(n, len(full)), random_state=0)
        print(f"  {s:<5} replayed {len(full):,} rows from {full.engine_id.nunique()} engines "
              f"({time.time() - t0:.0f}s)", flush=True)

    models, choice, thresholds, report = {}, {}, {}, {}
    sample_models, sample_thresholds, young_allowed = {}, {}, {}
    mature = {s: D[s]["sorties_done"].to_numpy() >= MIN_HISTORY_SORTIES for s in D}
    for lab in labels:
        name = lab[4:]
        y = {s: D[s][lab].to_numpy() > LABEL_ABOVE for s in D}
        X = {s: {"sample": D[s][base].to_numpy(float), "history": D[s][base + hcols].to_numpy(float)} for s in D}
        A = HistGradientBoostingClassifier(**GBM).fit(X["train"]["sample"], y["train"])
        B = HistGradientBoostingClassifier(**GBM).fit(X["train"]["history"], y["train"])
        pA = {s: A.predict_proba(X[s]["sample"])[:, 1] for s in ("val", "test")}
        pB = {s: B.predict_proba(X[s]["history"])[:, 1] for s in ("val", "test")}
        thrA = _tune(pA["val"], y["val"])
        m = mature["val"]
        thrB = _tune(pB["val"][m], y["val"][m]) if m.any() else thrA

        def served(s, rule):
            # "history": the history model on engines with history, the
            # sample-only twin on young ones -- exactly what the aircraft runs.
            if rule == "sample":
                return pA[s] > thrA
            return np.where(mature[s], pB[s] > thrB, pA[s] > thrA)


        f1v = {r: _f1(served("val", r), y["val"])[0] for r in ("sample", "history")}
        tag = max(f1v, key=f1v.get)
        # Reported under the served rule. Live adds one more condition on young
        # engines -- a history fault is named only while a detector agrees
        # something is wrong (layer4_core.live, DEV-254) -- which can only
        # remove calls, so this is the upper bound of what young engines see.
        pt = served("test", tag)
        f1t, pr, rc = _f1(pt, y["test"])
        young = ~mature["test"]
        f1y, pry, rcy = _f1(pt[young], y["test"][young]) if young.any() else (float("nan"),) * 3
        models[name] = B if tag == "history" else A
        choice[name] = tag
        thresholds[name] = thrB if tag == "history" else thrA
        sample_models[name], sample_thresholds[name] = A, thrA
        # How the sample-only twin does on YOUNG validation engines, reported
        # for the record. Young faults are rare in the fleet (lubrication has
        # none there), so this cannot be the gate; the live detector gate is.
        yv = ~mature["val"]
        yf1 = _f1(pA["val"][yv] > thrA, y["val"][yv])[0] if yv.any() else 0.0
        ypos = int(y["val"][yv].sum())
        young_allowed[name] = True
        report[name] = {"features": tag, "threshold": thresholds[name], "sample_threshold": thrA,
                        "val_f1": round(f1v[tag], 4), "test_f1": round(f1t, 4),
                        "test_precision": round(pr, 4), "test_recall": round(rc, 4),
                        "young_test_f1": round(f1y, 4), "young_test_precision": round(pry, 4),
                        "test_support": int(y["test"].sum()), "young_rows": int(young.sum()),
                        "young_val_f1": round(yf1, 4), "young_val_positives": ypos,
                        "young_engines": "named only while a detector agrees (live)"
                        if tag == "history" else "named as on any engine"}
        print(f"  {name:<24} {tag:<8} thr {thresholds[name]:.2f}/{thrA:.2f}  val F1 {f1v[tag]:.3f}  "
              f"TEST F1 {f1t:.3f} (P {pr:.3f} R {rc:.3f})  young engines: test F1 {f1y:.3f}, "
              f"val F1 {yf1:.3f} over {ypos} positives", flush=True)

    macro = float(np.mean([r["test_f1"] for r in report.values()]))
    print(f"\nTEST macro-F1 {macro:.3f}  (Tier-3 network on the same split: see "
          f"data/models/tier3_report.json)  total {time.time() - t0:.0f}s")
    out = config.data_dir() / "models"
    joblib.dump({"version": 2, "classes": [c[4:] for c in labels], "models": models,
                 "choice": choice, "thresholds": thresholds, "base_columns": base,
                 "history_columns": hcols, "sample_models": sample_models,
                 "sample_thresholds": sample_thresholds, "young_allowed": young_allowed,
                 "min_history_sorties": MIN_HISTORY_SORTIES,
                 "report": {"macro_f1_test": macro, "per_class": report}},
                out / "fault_namer.joblib")
    (out / "fault_namer_report.json").write_text(json.dumps({
        "macro_f1_test": macro, "per_class": report, "label_above": LABEL_ABOVE,
        "protocol": ("stratified engine split; rule and thresholds chosen on VAL; reported on TEST. "
                     f"'history' = history model on engines with >= {MIN_HISTORY_SORTIES} completed "
                     "sorties, its sample-only twin before that -- the rule the aircraft runs"),
        "fitted_utc": datetime.now(UTC).isoformat(timespec="seconds"),
    }, indent=2))
    print(f"saved -> {out / 'fault_namer.joblib'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
