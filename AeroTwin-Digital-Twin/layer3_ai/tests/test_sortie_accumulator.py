# -*- coding: utf-8 -*-
"""The live accumulator must agree with the training table, exactly.

`sortie_table` computes the survival head's inputs from a finished fleet in
pandas. `SortieAccumulator` computes the same numbers from a live stream. The
model is fed a plain vector, so if the two definitions differ even slightly the
served probability is a confident answer to a different question -- and nothing
about the output looks wrong. That is precisely how the injector-duty units bug
survived: the column was populated, the schema matched, every existing check
passed, and the value was sixty times too large.

So this file does not test the accumulator against hand-written expectations.
It replays real rows through it and asserts it reproduces what pandas produced
from the same rows.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from layer3_ai import features as feat
from layer3_ai import sortie_features as sf


def _frame(n_engines: int = 3, n_sorties: int = 4, per_sortie: int = 25):
    """A small frame with the columns the feature set expects."""
    rng = np.random.RandomState(0)
    cols = list(feat.extended().columns)
    rows = []
    for e in range(1, n_engines + 1):
        hours = 0.0
        for s in range(1, n_sorties + 1):
            # Vary the sortie length so flight_hours steps unevenly: a fixed
            # step would let a wrong rate denominator pass unnoticed.
            step = 0.4 + 0.3 * ((e + s) % 3)
            for k in range(per_sortie):
                hours += step
                r = {c: float(rng.normal(10.0 + e + s, 1.5)) for c in cols}
                r.update(engine_id=e, sortie=s, flight_hours=hours)
                rows.append(r)
    return pd.DataFrame(rows), cols


def test_sortie_accumulator_matches_the_training_table():
    """Same rows in, same feature vector out -- to floating tolerance."""
    df, cols = _frame()
    health = df[cols[0]].to_numpy() * 0.5
    table = sf.sortie_table(df, feat.extended(), health=health)

    acc = sf.SortieAccumulator(cols, health=True)
    df = df.copy()
    df[sf.HEALTH_COLUMN] = health

    checked = 0
    for engine in sorted(df["engine_id"].unique()):
        acc = sf.SortieAccumulator(cols, health=True)
        eng = df[df["engine_id"] == engine]
        for sortie in sorted(eng["sortie"].unique()):
            block = eng[eng["sortie"] == sortie]
            for _, row in block.iterrows():
                acc.observe(row.to_dict(), float(row["flight_hours"]))

            live = acc.features()
            assert live is not None
            want = table[(table["engine_id"] == engine)
                         & (table["sortie"] == sortie)].iloc[0]

            for c in acc.columns:
                assert c in live, f"{c} missing from the live vector"
                assert live[c] == pytest.approx(float(want[c]), rel=1e-9,
                                                abs=1e-9), (
                    f"engine {engine} sortie {sortie}: {c} live "
                    f"{live[c]!r} vs table {float(want[c])!r}")
                checked += 1
            acc.end_sortie()
    assert checked > 500, f"only {checked} values compared"


def test_spread_uses_the_sample_definition_pandas_uses():
    """ddof=1, not numpy's default of 0.

    The difference is invisible on a long sortie and grows as it shortens, so
    it would show up first on exactly the short flights a dispatch decision is
    made from.
    """
    df, cols = _frame(n_engines=1, n_sorties=1, per_sortie=4)
    table = sf.sortie_table(df, feat.extended())
    acc = sf.SortieAccumulator(cols, health=False)
    for _, row in df.iterrows():
        acc.observe(row.to_dict(), float(row["flight_hours"]))
    live = acc.features()

    c = cols[0]
    raw = df[c].to_numpy()
    assert live[f"sd_{c}"] == pytest.approx(float(raw.std(ddof=1)))
    assert live[f"sd_{c}"] != pytest.approx(float(raw.std(ddof=0)))
    assert live[f"sd_{c}"] == pytest.approx(float(table[f"sd_{c}"].iloc[0]))


def test_the_first_sortie_of_an_engine_has_a_zero_rate_not_a_missing_one():
    """There is no previous sortie to differ from, and the model has no
    missing-value path -- 0.0 is the value sortie_table substitutes too."""
    df, cols = _frame(n_engines=1, n_sorties=1, per_sortie=6)
    acc = sf.SortieAccumulator(cols, health=False)
    for _, row in df.iterrows():
        acc.observe(row.to_dict(), float(row["flight_hours"]))
    live = acc.features()
    assert all(live[f"rate_{c}"] == 0.0 for c in cols)


def test_a_row_with_a_missing_channel_is_skipped_not_imputed():
    """The level is a mean; substituting zero for an absent oil pressure moves
    it toward a value the engine never produced."""
    df, cols = _frame(n_engines=1, n_sorties=1, per_sortie=5)
    acc = sf.SortieAccumulator(cols, health=False)
    rows = list(df.iterrows())
    for _, row in rows[:3]:
        acc.observe(row.to_dict(), float(row["flight_hours"]))
    assert acc.samples == 3

    broken = rows[3][1].to_dict()
    broken[cols[0]] = None
    acc.observe(broken, float(rows[3][1]["flight_hours"]))
    assert acc.samples == 3, "a row with a missing channel was counted"


def test_nothing_observed_yields_no_vector_rather_than_zeros():
    """An all-zero vector would be scored as a real engine reading zero."""
    _, cols = _frame(n_engines=1, n_sorties=1, per_sortie=1)
    assert sf.SortieAccumulator(cols, health=False).features() is None
