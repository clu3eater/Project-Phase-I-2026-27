# -*- coding: utf-8 -*-
"""Serving the calibrated failure probability."""
from __future__ import annotations

from layer3_ai import survival_serving as sv


def test_probability_never_falls_as_the_window_grows(monkeypatch):
    """P(fail within 25 h) cannot be below P(fail within 12 h).

    The longer window CONTAINS the shorter one. Each horizon has its own
    independently calibrated classifier, so nothing in the fitting enforces
    this, and a live run produced 1.6 %, 0.0 %, 2.6 % -- not a rounding
    artefact but an impossibility, and the kind a reader spots immediately.

    The repair is a running maximum, which can only raise a probability, so it
    is conservative by construction.
    """
    server = sv.SurvivalServer.__new__(sv.SurvivalServer)
    server.features = ["a"]
    server.reason = "ready"

    class _Head:
        def predict_one(self, row):
            return {12.0: 0.0164, 25.0: 0.0, 50.0: 0.0258}

    server.head = _Head()
    out = server.predict({"a": 1.0})["horizons"]

    values = [out[k] for k in ("12h", "25h", "50h")]
    assert values == sorted(values), values
    assert values[1] >= 0.0164, "the inversion was not corrected"
    # And it must not invent risk where the head reported none.
    assert values[0] == 0.0164
