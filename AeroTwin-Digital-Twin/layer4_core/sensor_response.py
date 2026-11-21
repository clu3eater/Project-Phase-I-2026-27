"""Does each sensor still follow the engine? (audit 15 Sep, P0-5)

A sensor can stop responding and still look alive. A seized or detached
transducer keeps its electrical noise, so it passes the range, rate and
frozen-reading checks at the ingest, and on a sensor fitted to one FADEC lane
nothing cross-checks it. Its reading is plausible and wrong: a stuck head
temperature probe hides an overheat.

The as-new twin is the missing reference. Over the last ``window_s``, if the
twin's prediction for a channel moves by at least ``excitation_x`` times the
instrument's noise (standard deviation) and the reading by no more than
``flat_x`` times it, the sensor is not following the engine. Its reading is then
removed at the ingest, and restored when a later window shows it following the
engine again. With the engine at a steady point there is no verdict either way.

WHY SPREAD, NOT CORRELATION
---------------------------
The slope of the reading against the prediction was tried first and rejected.
Under a real cooling fault at severity 0.8 the head temperature's slope fell to
0.09, beside a stuck sensor's 0.03, so it would have removed the reading of an
engine that really was overheating. The spread of the reading does not do that.
Measured over 60 s windows with the prediction moving at least 5 noise, on seeds
11, 3 and 7 and cooling, lubrication and overheating faults at severity 0.8: a
working sensor's spread was never below 3.98 noise and a stuck sensor's never
above 1.23. The 2.0 between them is a design choice [MOD] on that evidence,
which comes from one flight profile.

The noise figures are the simulated instruments'. On hardware they must be
measured.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from common import config

# Channel -> (noise key in thresholds.pipeline.response_noise, twin prediction).
# Per-cylinder probes are judged against the twin's head and exhaust
# temperature: every cylinder moves with the operating point. Manifold pressure
# is left to the FADEC lane cross-check, which already compares two sensors.
CHANNELS: dict[str, tuple[str, str]] = {
    **{f"cht_{i}": ("cht", "cht_predicted") for i in (1, 2, 3, 4)},
    "cht_max": ("cht", "cht_predicted"),
    **{f"egt_{i}": ("egt", "egt_predicted") for i in (1, 2, 3, 4)},
    "egt_max": ("egt", "egt_predicted"),
    "coolant_temperature": ("coolant_temperature", "coolant_predicted"),
    "oil_pressure": ("oil_pressure", "oil_pressure_predicted"),
    "oil_temperature": ("oil_temperature", "oil_temperature_predicted"),
    "fuel_flow": ("fuel_flow", "fuel_flow_predicted"),
}


@dataclass
class ResponseCheck:
    """The response test for one channel, over a sliding time window."""

    noise: float
    window_s: float
    excitation_x: float
    flat_x: float
    min_samples: int = 20
    responding: bool | None = None       # the last verdict; None before any
    reading_spread: float | None = None
    predicted_spread: float | None = None
    _buf: deque = field(default_factory=deque, repr=False)

    # How close, in noise, the reading's mean must sit to the twin's over a
    # window with the engine steady for a condemned sensor to be believed again.
    agree_x: float = 3.0
    # How long "not following" must hold before it is a verdict. A probe lags
    # the metal it sits in (a head thermocouple by ~10 s) and the twin's
    # prediction does not, so in the first seconds of a power change the
    # reading moves less than the prediction for a perfectly good probe:
    # measured, the head probe was removed for one second at every top of
    # descent. A stuck probe stays stuck, so waiting costs little.
    persist_s: float = 15.0
    _flat_since: float | None = None

    def update(self, t: float, measured: float | None, predicted: float | None) -> bool | None:
        """Add one sample. True: responding. False: not responding. None: no verdict."""
        if measured is not None and predicted is not None:
            self._buf.append((t, float(measured), float(predicted)))
        while self._buf and t - self._buf[0][0] > self.window_s:
            self._buf.popleft()
        if (len(self._buf) < self.min_samples
                or self._buf[-1][0] - self._buf[0][0] < 0.9 * self.window_s):
            return None
        arr = np.asarray(self._buf, dtype=float)
        predicted_spread = float(np.std(arr[:, 2]))
        if predicted_spread < self.excitation_x * self.noise:
            self._flat_since = None
            # A STEADY ENGINE CAN STILL CLEAR A SENSOR, THOUGH NEVER CONDEMN ONE.
            #
            # Only movement can show a sensor is NOT following the engine. But
            # a reading that sits on the twin's own value, within a few noise,
            # for a whole window is following it -- and without this, a sensor
            # removed once stayed removed until the next large power change.
            # In a one-hour cruise there is none, so one verdict blanked the
            # oil pressure for the rest of the sortie. A sensor genuinely stuck
            # away from the engine's value does not agree, and stays removed;
            # one stuck ON it is condemned again the next time the engine moves.
            if self.responding is False:
                offset = abs(float(np.mean(arr[:, 1])) - float(np.mean(arr[:, 2])))
                if offset <= self.agree_x * self.noise:
                    self.responding = True
                    return True
            return None
        self.predicted_spread = predicted_spread
        self.reading_spread = float(np.std(arr[:, 1]))
        if self.reading_spread > self.flat_x * self.noise:
            self._flat_since = None
            self.responding = True
            return True
        if self._flat_since is None:
            self._flat_since = t
        if t - self._flat_since < self.persist_s:
            return None
        self.responding = False
        return False

    def reset(self) -> None:
        """A new engine run: nothing from the last one is evidence about this one."""
        self._buf.clear()
        self._flat_since = None
        self.responding = None
        self.reading_spread = None
        self.predicted_spread = None


class SensorResponseMonitor:
    """Runs the response check on every listed channel and acts on the ingest."""

    def __init__(self, ingest: Any, thresholds: dict | None = None) -> None:
        p = (thresholds or config.load_thresholds())["pipeline"]
        noise = p["response_noise"]
        self.ingest = ingest
        self.checks = {
            ch: ResponseCheck(
                noise=float(noise[key]), window_s=float(p["response_window_s"]),
                excitation_x=float(p["response_excitation_x"]),
                flat_x=float(p["response_flat_x"]),
                agree_x=float(p.get("response_agree_x", ResponseCheck.agree_x)),
                persist_s=float(p.get("response_persist_s", ResponseCheck.persist_s)),
            )
            for ch, (key, _prediction) in CHANNELS.items()
        }

    def reset(self) -> None:
        """Start every check again, on a restart of the engine.

        A window spanning the restart holds the last run's cruise and this
        run's cold start together, and its spreads describe neither.
        """
        for check in self.checks.values():
            check.reset()

    def update(self, t: float, simulated: Any) -> list[str]:
        """One tick, after the twin has its prediction. Returns the channels
        currently found not responding."""
        model = bool(getattr(simulated, "model_available", False))
        for ch, check in self.checks.items():
            predicted = getattr(simulated, CHANNELS[ch][1]) if model else None
            verdict = check.update(t, self.ingest.raw(ch), predicted)
            if verdict is False:
                self.ingest.condemn(ch, (
                    f"not responding: reading spread {check.reading_spread:.2f} while the "
                    f"twin predicts {check.predicted_spread:.2f} over {check.window_s:.0f} s"))
            elif verdict is True:
                self.ingest.absolve(ch)
        return self.not_responding()

    def not_responding(self) -> list[str]:
        return sorted(ch for ch, c in self.checks.items() if c.responding is False)
