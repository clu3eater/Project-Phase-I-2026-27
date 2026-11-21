"""Same model, same data, two protocols: how much does a random row split inflate?

Run:  python scripts/eval_split_inflation.py   (measured 23 Sep 2026: random rows
      accuracy 0.960 / macro-F1 0.961; unseen engines 0.628 / 0.615)

Most competing teams train a Random Forest fault classifier and report accuracy
on a random row-level train_test_split. Rows from one engine then sit in both
train and test, so the model is graded partly on engines it has memorised.
This trains the identical classifier on ASTRA's fleet both ways.
"""
import sys
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import train_test_split

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"E:\DRDO")
from common import config  # noqa: E402
from layer3_ai import features as feat  # noqa: E402

d = config.data_dir() / "synthetic"
full = pd.concat([pd.read_parquet(d / f"{s}.parquet") for s in ("train", "val", "test")], ignore_index=True)
full = feat.baseline_residuals(full)
labs = list(feat.FAULT_LABEL_COLUMNS)
y = np.where(full[labs].max(axis=1) > 0.05, full[labs].to_numpy().argmax(axis=1) + 1, 0)  # 0 = healthy
X = feat.build(full, feat.extended())
rng = np.random.default_rng(0)
take = rng.choice(len(full), size=min(150_000, len(full)), replace=False)
X, y, eng = X[take], y[take], full["engine_id"].to_numpy()[take]
names = ["healthy"] + [c[4:] for c in labs]


def run(tag, tr, te):
    clf = RandomForestClassifier(n_estimators=200, n_jobs=4, random_state=0, min_samples_leaf=2)
    clf.fit(X[tr], y[tr])
    p = clf.predict(X[te])
    print(f"{tag:<44} accuracy {accuracy_score(y[te], p):.3f}   macro-F1 {f1_score(y[te], p, average='macro'):.3f}"
          f"   (train rows {len(tr):,}, test rows {len(te):,})", flush=True)


idx = np.arange(len(y))
tr, te = train_test_split(idx, test_size=0.2, random_state=42, stratify=y)
run("random row split (what most teams do)", tr, te)
engines = np.unique(eng)
test_eng = set(rng.choice(engines, size=len(engines) // 5, replace=False))
te2 = np.array([i for i in idx if eng[i] in test_eng]); tr2 = np.array([i for i in idx if eng[i] not in test_eng])
run("unseen engines (what ASTRA reports)", tr2, te2)
