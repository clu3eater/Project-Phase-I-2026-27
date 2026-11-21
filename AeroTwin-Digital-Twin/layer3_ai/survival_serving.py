# -*- coding: utf-8 -*-
"""Serve the calibrated failure probability to the running twin.

The survival head is the strongest result this project has -- AUC 0.95 to 0.97
at the 12, 25 and 50 hour horizons, calibrated -- and until this module existed
it could not be shown anywhere. It was trained in one process and scored in the
same process, so nothing in the live system could produce the number. A result
that only exists in a JSON file is not a capability.

This is deliberately the same shape as `layer3_ai/rul_serving.LstmRulServer`:
it loads a checkpoint if there is one, and if anything at all is wrong it stays
unavailable and says why, rather than serving a number the caller cannot tell
apart from a good one. A probability is the worst kind of value to guess at,
because it looks equally confident whether or not it means anything.

Two failure modes are checked rather than trusted:

  no checkpoint      the caller keeps whatever it was doing before
  feature mismatch   the head is fed a plain vector, so a caller that
                     assembles the columns in a different order gets a
                     confident answer to a different question with nothing to
                     signal it. The order recorded at save time must match.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from common import config
from layer3_ai.rul_survival import SurvivalHead

log = logging.getLogger(__name__)

DEFAULT_CHECKPOINT = "survival_head.pkl"

# Horizons an operator actually decides on. The head is fitted further out, but
# 200 h and 400 h carry little or no skill and publishing them beside the near
# ones invites them to be read as equally trustworthy.
DISPATCH_HORIZONS = (12.0, 25.0, 50.0)


class SurvivalServer:
    """Calibrated P(fail within h) for one live feature vector."""

    def __init__(self, checkpoint: Path | str | None = None) -> None:
        self.path = Path(checkpoint) if checkpoint else (
            config.data_dir() / "models" / DEFAULT_CHECKPOINT)
        self.head: SurvivalHead | None = None
        self.features: list[str] = []
        self.reason = "not loaded"
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self.reason = f"no checkpoint at {self.path}"
            log.info("survival head unavailable: %s", self.reason)
            return
        try:
            self.head, self.features = SurvivalHead.load(self.path)
        except Exception as exc:                      # noqa: BLE001
            self.reason = f"checkpoint unreadable: {exc}"
            log.warning("survival head unavailable: %s", self.reason)
            self.head = None
            return
        if not self.features:
            self.reason = "checkpoint records no feature order"
            log.warning("survival head unavailable: %s", self.reason)
            self.head = None
            return
        self.reason = "ready"

    @property
    def available(self) -> bool:
        return self.head is not None

    def predict(self, features: dict[str, float | None]) -> dict[str, Any]:
        """One snapshot's failure probabilities, or an explained refusal.

        `features` is keyed by name and reordered here against the order
        recorded in the checkpoint, so the caller cannot silently get the
        columns wrong. A missing feature is a refusal, not a zero: zero is a
        real value for most of these channels and would be scored as one.
        """
        if not self.available:
            return {"available": False, "reason": self.reason, "horizons": {}}

        missing = [f for f in self.features if features.get(f) is None]
        if missing:
            return {"available": False,
                    "reason": f"{len(missing)} feature(s) missing, first "
                              f"{missing[0]!r}",
                    "horizons": {}}

        row = np.array([float(features[f]) for f in self.features],
                       dtype=float)
        try:
            probs = self.head.predict_one(row)
        except Exception as exc:                      # noqa: BLE001
            return {"available": False, "reason": f"inference failed: {exc}",
                    "horizons": {}}

        # MONOTONIC IN THE HORIZON. Each horizon has its own independently
        # calibrated classifier, so nothing in the fitting makes P(fail within
        # 25 h) >= P(fail within 12 h) -- and a live run produced exactly that
        # inversion: 1.6 %, 0.0 %, 2.6 %. It is not a rounding artefact but an
        # impossibility, because the 25-hour window CONTAINS the 12-hour one.
        #
        # Enforced with a running maximum, which is the standard repair for a
        # set of independently calibrated survival heads: it never lowers a
        # probability, so the correction can only be conservative.
        out, running, held = {}, 0.0, []
        for h, p in sorted(probs.items()):
            if h not in DISPATCH_HORIZONS:
                continue
            raw = float(p)
            if raw < running:
                # This horizon's own head came out BELOW a shorter one. The
                # repair holds it at the higher figure, which is why two
                # horizons can print the same number -- and an unexplained
                # repeat reads as a copied placeholder rather than as a
                # correction. Say which ones were held.
                held.append(f"{h:g}h")
            running = max(running, raw)
            out[f"{h:g}h"] = round(running, 4)
        return {
            "available": True,
            "reason": "ready",
            "horizons": out,
            # Which horizons are showing a neighbour's figure because their own
            # head disagreed with a shorter window. Empty when every head was
            # already monotonic, which is the normal case.
            "held_monotonic": held,
            # The number an operator acts on before launch. The longest
            # dispatch horizon is the conservative one: an engine that will
            # not last 50 h will not last 12 either.
            "next_sortie_risk": out.get("50h"),
        }


__all__ = ["SurvivalServer", "DEFAULT_CHECKPOINT", "DISPATCH_HORIZONS"]
