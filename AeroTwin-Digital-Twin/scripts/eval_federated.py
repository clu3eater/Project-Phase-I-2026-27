"""Measure what federated training costs -- PRD Part 3 s22.

Run:  python scripts/eval_federated.py

Federated learning does not improve accuracy and this script does not pretend
it does. Pooled training is the upper bound; federation gives that up so that
raw telemetry never leaves the aircraft. The number worth reporting is
therefore the PRICE of that guarantee, measured on engines no model saw during
training.

Also measures, rather than asserts:
  * how many bytes actually cross the link versus centralising the telemetry
  * what differential privacy at the specified epsilon costs in accuracy
  * whether a poisoned client can drag the fleet model, and whether the
    median defence stops it
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from common import config                        # noqa: E402
from layer3_ai import features as feat           # noqa: E402
from layer3_ai import tier2_statistical as t2    # noqa: E402
from layer3_ai.fed import federated as fed       # noqa: E402

N_CLIENTS = 3          # PRD Part 0: "3 simulated clients"
ROUNDS = 25


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    d = config.data_dir() / "synthetic"
    manifest = json.loads((d / "manifest.json").read_text())
    assign = feat.stratified_engine_split(manifest)
    full = pd.concat(
        [pd.read_parquet(d / f"{s}.parquet") for s in ("train", "val", "test")],
        ignore_index=True,
    )
    full["split"] = full["engine_id"].map(assign)
    tr = feat.baseline_residuals(full[full["split"] == "train"].reset_index(drop=True))
    te = feat.baseline_residuals(full[full["split"] == "test"].reset_index(drop=True))
    return tr, te


def main() -> None:
    fs = feat.extended()
    train, test = load()

    xtr, ytr = feat.build(train, fs), feat.anomaly_mask(train).astype(float)
    xte, yte = feat.build(test, fs), feat.anomaly_mask(test).astype(float)
    n_features = len(fs)

    print(f"train {len(xtr):,} rows / {train.engine_id.nunique()} engines   "
          f"test {len(xte):,} rows / {test.engine_id.nunique()} engines")
    print(f"features {n_features}, model payload "
          f"{fed.LinearModel.zeros(n_features).payload_bytes} bytes\n")

    # --- clients hold whole engines, never a fraction of one ---------------
    groups = fed.split_by_engine(train, N_CLIENTS)
    clients = []
    for i, engines in enumerate(groups):
        m = train["engine_id"].isin(engines).to_numpy()
        clients.append(
            fed.FederatedClient(f"UAV-{i+1}", xtr[m], ytr[m], epochs=2, lr=0.5)
        )
        print(f"  UAV-{i+1}: {len(engines)} engines, {int(m.sum()):,} rows "
              f"({m.sum() * 100 / len(train):.0f}% of the fleet)")
    print()

    def auc(model: fed.LinearModel) -> float:
        return t2.roc_auc(model.predict_proba(xte), yte.astype(bool))

    rows = []

    central = fed.train_centralised(xtr, ytr, n_features, epochs=ROUNDS * 2)
    rows.append(("centralised (upper bound)", auc(central), "all telemetry pooled"))

    plain, srv = fed.run_federated(clients, n_features, rounds=ROUNDS)
    rows.append((f"federated, {N_CLIENTS} clients", auc(plain), "weights only"))

    for eps in (5.0, 1.0):
        cl = [fed.FederatedClient(c.client_id, xtr[train["engine_id"].isin(g).to_numpy()],
                                  ytr[train["engine_id"].isin(g).to_numpy()],
                                  epochs=2, lr=0.5)
              for c, g in zip(clients, groups, strict=True)]
        budget = fed.PrivacyBudget(epsilon=eps, delta=1e-5, clip_norm=1.0)
        dp, _ = fed.run_federated(cl, n_features, rounds=ROUNDS, privacy=budget)
        rows.append((f"federated + DP (eps={eps:g}/round)", auc(dp),
                     f"sigma={budget.noise_scale():.2f}"))

    print("=" * 78)
    print(f"  {'configuration':<34}{'ROC-AUC':>9}   note")
    for name, a, note in rows:
        print(f"  {name:<34}{a:>9.3f}   {note}")
    print("=" * 78)

    base = rows[0][1]
    print(f"\n  cost of keeping data on the aircraft : "
          f"{rows[1][1] - base:+.3f} AUC")
    print(f"  additional cost of DP at eps=1        : "
          f"{rows[-1][1] - rows[1][1]:+.3f} AUC")

    # --- bandwidth, measured -----------------------------------------------
    raw = sum(c.raw_data_bytes() for c in clients)
    sent = sum(c.bytes_uploaded for c in clients)
    print(f"\n  telemetry that stayed on the aircraft : {raw/1e6:8.2f} MB")
    print(f"  weights actually transmitted          : {sent/1e3:8.2f} kB "
          f"over {ROUNDS} rounds x {N_CLIENTS} clients")
    print(f"  reduction                             : {raw/max(sent,1):8.0f}x")

    # --- poisoning ----------------------------------------------------------
    print("\n" + "=" * 78)
    print("  MODEL POISONING")
    print("=" * 78)
    # The realistic attack on FedAvg is not inverted labels -- averaging
    # dilutes those. It is MODEL REPLACEMENT: one client scales its update by
    # roughly the number of clients so that after averaging its contribution
    # survives intact and the others are cancelled.
    def fresh(i, g):
        m = train["engine_id"].isin(g).to_numpy()
        return fed.FederatedClient(f"UAV-{i+1}", xtr[m], ytr[m], epochs=2, lr=0.5)

    class ScalingAttacker(fed.FederatedClient):
        """One compromised aircraft amplifying an inverted update."""

        def fit_round(self, global_vector, *, privacy=None, rng=None):
            u, n = super().fit_round(global_vector, privacy=privacy, rng=rng)
            return -u * (N_CLIENTS * 3.0), n

    g0 = groups[0]
    m0 = train["engine_id"].isin(g0).to_numpy()

    def attacked():
        return [ScalingAttacker("UAV-1(compromised)", xtr[m0], ytr[m0],
                                epochs=2, lr=0.5)] + [
            fresh(i + 1, g) for i, g in enumerate(groups[1:])
        ]

    p_mean, _ = fed.run_federated(attacked(), n_features, rounds=ROUNDS)
    print(f"  FedAvg mean, 1 of 3 compromised      : {auc(p_mean):.3f}"
          f"   (honest: {rows[1][1]:.3f})")

    p_med, srv_med = fed.run_federated(
        attacked(), n_features, rounds=ROUNDS, robust=True,
        reject_cosine_below=0.0,
    )
    rejected = sum(len(h.rejected) for h in srv_med.history)
    print(f"  coordinate-wise median defence       : {auc(p_med):.3f}"
          f"   ({rejected} updates rejected on direction)")
    print()
    print("  A median cannot be dragged by one client the way a mean can. It is")
    print("  not a defence against an adversary who stays near the consensus and")
    print("  biases it slowly, and no claim is made that it is.")


if __name__ == "__main__":
    main()
