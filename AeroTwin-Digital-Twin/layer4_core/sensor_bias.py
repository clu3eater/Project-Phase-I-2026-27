"""How far each instrument reads from the twin, and whether the instrument can be blamed.

Audit 15 Sep, P0-4: the "sensor drift" number on the console was the residual
VARIANCE ratio -- scatter, not offset -- so a transducer reading steadily 6 psi
low scored as engine wear and nothing reported the offset at all. A sensor
drifting low is how an overheat stays hidden.

WHAT CAN AND CANNOT BE DECIDED
------------------------------
An offset against the as-new twin does not by itself name a culprit: a cooling
fault and a biased head-temperature probe both read hot. Measured on this engine
(seed 11, severity 0.8, 300 s windows): a drifting head probe sat 6.9 to 8.2 degC
above the twin and real cooling degradation 9.0 to 14.6 degC; a drifting
oil-pressure sensor 5.6 to 6.4 psi and a real lubrication fault 0.2 to 2.5 psi.
The ranges overlap, and on this engine both move ONE channel: the coolant loop is
thermostatted, so a cooling fault barely moves coolant temperature either.

So the instrument is blamed only where a second source disagrees with it:

    two lanes    the quantity is measured on both FADEC lanes and they disagree
                 (can_ingest marks the channel SUSPECT); heat moves both lanes,
                 a failing transducer moves one

and everywhere else the offset is reported as UNATTRIBUTED -- engine or
instrument, both still open. That is the honest answer for a sensor with no
redundancy, and it is better than today's silent scoring as engine wear.

The offset itself is estimated by the scalar Kalman filter of PRD Part 1
section 8.4 (``sensor_fusion.BiasEstimator``), which the PRD asks for and which
nothing used until now. Its process noise is deliberately small: a filter fast
enough to follow a real excursion would absorb the fault it exists to reveal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from common import config
from layer1_edge.can_ingest import ValueState
from layer1_edge.sensor_fusion import BiasEstimator

# Residual name -> (telemetry channel, thresholds.parameters key). The parameter
# range is the full scale the configured drift fractions are taken of.
CHANNELS: dict[str, tuple[str, str]] = {
    "cht": ("cht_max", "cht"),
    "coolant": ("coolant_temperature", "coolant_temperature"),
    "egt": ("egt_max", "egt"),
    "oil_pressure": ("oil_pressure", "oil_pressure"),
    "oil_temperature": ("oil_temperature", "oil_temperature"),
    "fuel_flow": ("fuel_flow", "fuel_flow"),
    "manifold_pressure": ("manifold_pressure", "manifold_pressure"),
}


@dataclass
class ChannelBias:
    """One instrument's estimated offset from the twin, and who is to blame."""

    channel: str
    offset: float | None = None        # measured minus the as-new twin, channel units
    fraction_fs: float = 0.0           # of the parameter's full scale
    level: str = "none"                # none | drift | fault
    attribution: str = "none"          # none | instrument | unattributed
    evidence: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "offset": None if self.offset is None else round(self.offset, 4),
            "fraction_fs": round(self.fraction_fs, 5),
            "level": self.level,
            "attribution": self.attribution,
            "evidence": self.evidence,
        }


class BiasMonitor:
    """Estimated instrument offsets, and the evidence for blaming the instrument."""

    def __init__(self, ingest: Any, thresholds: dict | None = None) -> None:
        t = thresholds or config.load_thresholds()
        kalman = t["fusion"]["kalman"]
        drift = t["faults"]["sensor_drift"]
        params = t["parameters"]
        self.ingest = ingest
        self.drift_fraction = float(drift["bias_drift_fraction_fs"])
        self.fault_fraction = float(drift["bias_fault_fraction_fs"])
        self.full_scale: dict[str, float] = {}
        self.estimators: dict[str, BiasEstimator] = {}
        for residual, (_channel, param) in CHANNELS.items():
            lo, hi = params[param]["range"]
            self.full_scale[residual] = float(hi) - float(lo)
            self.estimators[residual] = BiasEstimator(
                process_noise=float(kalman["bias_process_noise"]),
                measurement_noise=float(kalman["measurement_noise"]),
            )
        self.bias: dict[str, ChannelBias] = {}

    # ------------------------------------------------------------------
    def update(self, residuals: Any) -> dict[str, ChannelBias]:
        """Fold one tick of residuals in. Returns the offset of every channel."""
        out: dict[str, ChannelBias] = {}
        for residual, (channel, _param) in CHANNELS.items():
            r = getattr(residuals, residual, None)
            est = self.estimators[residual]
            if (r is not None and r.usable
                    and r.measured is not None and r.predicted is not None):
                est.update(float(r.measured), float(r.predicted))
            if est.samples == 0:
                out[residual] = ChannelBias(channel=channel)
                continue
            fraction = abs(est.bias) / self.full_scale[residual]
            level = ("fault" if fraction > self.fault_fraction
                     else "drift" if fraction > self.drift_fraction else "none")
            attribution, evidence = ("none", "")
            if level != "none":
                attribution, evidence = self._blame(channel)
            out[residual] = ChannelBias(
                channel=channel, offset=est.bias, fraction_fs=fraction,
                level=level, attribution=attribution, evidence=evidence,
            )
        self.bias = out
        return out

    def _blame(self, channel: str) -> tuple[str, str]:
        """Only a second source can tell a failing instrument from a failing engine."""
        ch = self.ingest.telemetry.channels.get(channel)
        if ch is not None and ch.state is ValueState.SUSPECT and ch.lane_delta is not None:
            return "instrument", (
                f"the two FADEC lanes disagree by {ch.lane_delta:.3f}; an engine change "
                "moves both lanes together")
        return "unattributed", (
            "nothing else measures this quantity, so a failing engine and a failing "
            "instrument both remain open")

    # ------------------------------------------------------------------
    def indicators(self) -> dict[str, float]:
        """For the rule engine and the fault forecast, as fractions of full scale."""
        blamed = [b.fraction_fs for b in self.bias.values() if b.attribution == "instrument"]
        offset = [b.fraction_fs for b in self.bias.values() if b.level != "none"]
        return {
            "instrument_offset_fraction_fs": max(blamed, default=0.0),
            "sensor_offset_fraction_fs": max(offset, default=0.0),
        }

    def as_dict(self) -> dict[str, Any]:
        return {name: b.as_dict() for name, b in self.bias.items() if b.offset is not None}

    def unattributed(self) -> list[str]:
        return sorted(b.channel for b in self.bias.values() if b.attribution == "unattributed")
