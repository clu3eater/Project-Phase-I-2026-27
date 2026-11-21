"""What the OPERATOR sees, as distinct from what the model computed.

Governed by ``docs/WHO_READS_THIS_SCREEN.md``.

THE PROBLEM THIS SOLVES
-----------------------
Measured on the live stream over twenty seconds, on a HEALTHY engine with no
fault injected:

    BSFC deterioration          -4.52 % .. +6.88 %   swing 11.40 points
    mission success probability 56.79 % .. 86.52 %   swing 29.73 points
    remaining useful life       29.46 h .. 30.40 h   changed 35 frames in 40
    composite health index       0.78   ..  0.89

Nothing was wrong with the engine. Every one of those numbers was noise, and
every one of them was being printed in the largest type on the dashboard.

An operator watching mission success probability swing between 57 % and 87 %
twice a second does not conclude that the mission is uncertain. They conclude
the number is worthless and stop reading the panel -- including on the day it
is telling them something true. That is the display equivalent of a chattering
alarm, which alarm-management practice has treated as a defect to eliminate,
never to tune, for thirty years.

WHY IT IS NOT A DISPLAY BUG
---------------------------
RUL, health, efficiency and mission probability are SLOW quantities: they
describe an engine ageing over tens or hundreds of hours. Sampling them at 2 Hz
and printing the instantaneous value shows sensor noise on a DERIVED quantity,
amplified by every division in the chain. BSFC is fuel flow over shaft power --
both noisy, the ratio noisier than either -- and deterioration is that ratio
over another ratio. Eleven points of swing is what that arithmetic produces.

PRD Part 2 section 9.4 already requires the fix, and it had simply never been
applied to the display:

    CHI_ema(t) = alpha * CHI(t) + (1 - alpha) * CHI_ema(t-1),  alpha = 0.1
    "slow response, filters noise"; trend over a 10-FLIGHT-HOUR window.

Ten flight hours, not half a second.

WHAT THIS MODULE DOES NOT DO
----------------------------
It does not change what the model computed. The raw sections of the snapshot
are untouched and the engineer's screens continue to read them, because for a
propulsion engineer validating a model the noise IS the data. This module adds
a parallel, operator-facing view beside them.

IT MUST NEVER TOUCH THE ALERTING PATH
-------------------------------------
Smoothing buys stability by paying in LAG, and lag on a safety annunciation is
the one place that trade is unacceptable: an operator would learn of a real
excursion several seconds after it happened.

So the split is deliberate and load-bearing:

  ALERTS      Tier-1 rules run on the RAW ingest readings in ``live._tick``
              (``self.rules.evaluate``), reach the master annunciators
              directly, and never pass through this module. A genuine
              exceedance still fires on the frame it occurs.

  STATE WORD  ``fusion.level_name`` is the unsmoothed fused level. The word an
              operator reads is immediate; only the numeric SCORE beside it is
              smoothed, and that score is a diagnostic figure nobody acts on.

  TRENDS      Everything in this module -- health index, RUL, efficiency,
              mission probability. All slow, all only meaningful over hours,
              none of them an annunciation.

The rule is therefore: smooth what is read as a TREND, never what is read as an
ALARM.

THE THREE MECHANISMS
--------------------
1. SMOOTH   an exponential moving average, alpha from the PRD.
2. QUANTISE to a step the quantity actually supports. A deterioration figure
            that swings +/-5 points on a healthy engine is not a one-decimal
            quantity, and printing it to one decimal claims a precision the
            measurement does not have.
3. HYSTERESIS the displayed value follows only once the smoothed value is a
            full step away from what is SHOWN. Merely comparing quantised
            values gives no deadband at all -- a value near a boundary
            rounds either way on alternate frames, for ever.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from common import config


def _cfg() -> dict:
    """Everything this module displays is configured, not written in here.

    The display steps, the smoothing constant and the operator instructions all
    live in ``configs/thresholds.yaml`` beside the bands they belong to. A
    number tuned in one file and a sentence written in another drift apart, and
    the sentence is what an operator acts on.
    """
    return config.load_thresholds()["health"]["operator_display"]


def alpha() -> float:
    """PRD Part 2 section 9.4 METHOD 1 -- the PRD annotates it "filters noise"."""
    return float(_cfg()["ema_alpha"])


@dataclass
class Smoothed:
    """One displayed quantity: smoothed, quantised, and held still.

    ``step`` is the display resolution -- the smallest change worth showing an
    operator. It is chosen from the quantity's real precision, not from what
    looks tidy: see the table in ``OperatorView``.
    """

    step: float
    # How far the smoothed value must get from the DISPLAYED one, in steps,
    # before the display follows. Configured, not written in here.
    hysteresis: float = 1.0
    ema: float | None = None
    shown: float | None = None

    def update(self, value: float | None, a: float | None = None) -> float | None:
        if value is None:
            # A gap is a gap. Holding the last value across one would be the
            # substitution that PRD Part 4 s7.2 forbids -- the operator would
            # read a stale number as a live one.
            return self.shown
        w = alpha() if a is None else a
        self.ema = value if self.ema is None else (
            w * value + (1.0 - w) * self.ema
        )
        if self.shown is None:
            self.shown = round(self.ema / self.step) * self.step
            return self.shown

        # HYSTERESIS, not merely quantisation.
        #
        # Comparing the QUANTISED value against the shown one and moving on any
        # difference is no deadband at all: an EMA hovering near a step
        # boundary rounds to either side on alternate frames and the figure
        # flips for ever. Measured, that left a noisy quantity still changing
        # on 31 frames out of 40 -- the chatter this exists to remove.
        #
        # So the raw smoothed value must get a full ``hysteresis`` band away
        # from what is currently DISPLAYED before the display follows it. The
        # cost is that the shown figure can lag by up to that band, which is
        # exactly what a deadband trades and why this is applied only to
        # trends and never to the alerting path.
        if abs(self.ema - self.shown) >= self.step * self.hysteresis:
            self.shown = round(self.ema / self.step) * self.step
        return self.shown


def direction(now: float | None, before: float | None,
              noise: float) -> str:
    """"rising" / "falling" / "steady", where steady means "inside the noise".

    An operator asked "is it getting worse?" needs a direction, not a
    derivative. Reporting a slope smaller than the quantity's own scatter is
    reporting the scatter.
    """
    if now is None or before is None:
        return "unknown"
    d = now - before
    if abs(d) < noise:
        return "steady"
    return "rising" if d > 0 else "falling"


class OperatorView:
    """Builds the operator-facing view of the slow quantities.

    Every display step, the smoothing constant and the direction noise floors
    come from ``health.operator_display`` in the threshold file, where each is
    annotated with the MEASURED scatter that set it. Nothing here is written
    into the code: a display resolution is a tuning decision about a physical
    quantity, and tuning decisions belong beside the thresholds they sit with.
    """

    def __init__(self) -> None:
        c = _cfg()
        st = c["steps"]
        h = float(c["hysteresis_steps"])
        self.chi = Smoothed(float(st["chi"]), h)
        self.rul_h = Smoothed(float(st["rul_hours"]), h)
        self.bsfc_det = Smoothed(float(st["bsfc_deterioration_pct"]), h)
        self.mission_p = Smoothed(float(st["mission_success_pct"]), h)
        self.fusion = Smoothed(float(st["fusion_score"]), h)

        # A direction taken over two seconds is a direction taken over noise.
        self.window = int(c["direction_window_frames"])
        self.noise = {k: float(v) for k, v in c["direction_noise"].items()}

        # Value one window ago, for the direction word.
        self._chi_hist: list[float] = []
        self._det_hist: list[float] = []

    def update(
        self,
        *,
        chi: float | None,
        rul_hours: float | None,
        rul_reportable: bool,
        bsfc_deterioration_pct: float | None,
        mission_success: float | None,
        fusion_score: float | None,
    ) -> dict:
        """One frame in, the operator's view of the slow quantities out."""
        chi_s = self.chi.update(chi)
        # An RUL the model declined to report is not smoothed into existence.
        rul_s = self.rul_h.update(rul_hours) if rul_reportable else None
        det_s = self.bsfc_det.update(bsfc_deterioration_pct)
        mis_s = self.mission_p.update(
            None if mission_success is None else mission_success * 100.0
        )
        fus_s = self.fusion.update(fusion_score)

        for hist, val in ((self._chi_hist, chi_s), (self._det_hist, det_s)):
            if val is not None:
                hist.append(val)
                if len(hist) > self.window:
                    del hist[0]

        return {
            "chi": None if chi_s is None else round(chi_s, 2),
            "chi_direction": direction(
                chi_s, self._chi_hist[0] if self._chi_hist else None,
                self.noise["chi"]),
            # Reported in whole hours: the step is 5 h and printing a decimal
            # on a 5 h step invites the operator to read precision into it.
            "rul_hours": None if rul_s is None else int(round(rul_s)),
            "bsfc_deterioration_pct": None if det_s is None else int(round(det_s)),
            "efficiency_direction": direction(
                det_s, self._det_hist[0] if self._det_hist else None,
                self.noise["bsfc_deterioration_pct"]),
            "mission_success_pct": None if mis_s is None else int(round(mis_s)),
            "fusion_score": None if fus_s is None else round(fus_s, 2),
        }




# ---------------------------------------------------------------------------
# What the operator is told to DO
# ---------------------------------------------------------------------------
#
# The health band carries a machine token -- "maintain_within_25h",
# "ground_immediately". Those are correct as configuration keys and useless as
# operator text.
#
# PRD Part 2 s9.5 writes its own examples, and every one of them ends in an
# instruction:
#
#     "Oil pressure correlation degraded. Schedule inspection within 10 flight
#      hours."
#     "CHT at 127 degC -- monitor closely, reduce power if trend continues"
#     "CHT CRITICAL at 137 degC! Reduce power immediately!"
#
# ISA-18.2 says the same thing formally: an alarm is an abnormal condition
# REQUIRING A RESPONSE, and should carry a recommended response procedure. An
# indication with no response attached is not an alarm, it is decoration that
# costs attention.
# The sentences themselves live on the BANDS in configs/thresholds.yaml, beside
# the token each one translates, so the two cannot drift apart. A sentence
# written in Python and a threshold tuned in YAML diverge the first time either
# is touched, and the sentence is the half an operator acts on.
def instruction(action_token: str) -> str:
    """The band's machine token as a sentence an operator can act on."""
    for band in config.load_thresholds()["health"]["chi_bands"]:
        if band.get("action") == action_token and band.get("instruction"):
            return str(band["instruction"])
    # No silent blank: an unmapped token is shown as itself rather than as an
    # empty instruction line, which would read as "nothing to do".
    return action_token.replace("_", " ")


def margin(value: float | None, limit: float | None, *,
           unit: str, name: str, minimum: bool = False) -> dict | None:
    """One parameter as a MARGIN rather than a reading.

    A temperature without its limit is a number. With its limit it is a
    margin, and a margin is a decision -- "22 degC to the coolant limit" tells
    an operator something "98 degC" does not, unless they have memorised the
    certificate.
    """
    if value is None or limit is None:
        return None
    left = (value - limit) if minimum else (limit - value)
    return {
        "name": name,
        "value": round(float(value), 1),
        "limit": round(float(limit), 1),
        "margin": round(float(left), 1),
        "unit": unit,
        "exceeded": left < 0.0,
    }


__all__ = ["OperatorView", "Smoothed", "alpha", "direction",
           "instruction", "margin"]
