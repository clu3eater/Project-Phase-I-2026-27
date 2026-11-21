"""Health indices -- PRD Part 2 sections 9.2 to 9.4.

The composite health index is the one number an operator reads first and the
number every maintenance decision hangs off, so it has to mean the same thing
on a cold cruise and a hot climb.

THE DEFECT IN THE SPECIFIED FORMULAS
------------------------------------
PRD Part 2 section 9.2 defines the sub-indices against ABSOLUTE thresholds:

    THI = 1 - max(0, (CHT_max - 105) / (135 - 105))

Cylinder head temperature depends far more on what the throttle is doing than
on whether the engine is healthy. Measured on 83,000 rows from engines the
simulator certifies as GENUINELY HEALTHY -- no fault, composite truth above
0.90 -- the specified formula scores:

    25.7 % of them "degraded" (THI < 0.85)
     5.6 % of them "fault"    (THI < 0.70)

and THI falls from 1.00 to 0.83 across nothing but a throttle change from 60 %
to 85 %. An index that reads DEGRADED whenever the engine is working hard is a
power gauge wearing a health gauge's label. Worse, it is a power gauge that
cries wolf: an operator learns within a week that the number always sags in the
climb, and stops believing it exactly when it might be telling the truth.

THE FIX
-------
Every index that can be computed from a residual is. The residual is measured
minus what an as-new engine would do AT THE SAME OPERATING POINT
(``layer4_core.shadow_model``), so the operating point cancels by construction.
A CHT residual of +12 K means the same thing at idle and at take-off power.

Both forms are implemented and ``scripts/eval_health.py`` scores them against
ground truth, because "the residual version is better" is worth more as a
measurement than as an argument. The absolute form stays available and is what
runs when no shadow model is present.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

import numpy as np

from common import config


def _h() -> dict:
    return config.load_thresholds()["health"]


# ---------------------------------------------------------------------------
# Individual indices
# ---------------------------------------------------------------------------


def _falling(value: float, nominal: float, limit: float) -> float:
    """1.0 at or below nominal, 0.0 at the limit. The PRD's standard shape."""
    if limit <= nominal:
        return 1.0
    return float(np.clip(1.0 - (value - nominal) / (limit - nominal), 0.0, 1.0))


def thermal_index(
    cht_max: float | None,
    coolant: float | None,
    *,
    res_cht: float | None = None,
    res_coolant: float | None = None,
) -> float:
    """Thermal Health Index (PRD Part 2 section 9.2 Parameter 2).

    Uses residuals when a shadow model is available, absolute temperatures
    otherwise. The parallel coolant index matters because coolant temperature
    is this engine's CERTIFIED thermal limit, not CHT.

    The two are combined by MINIMUM, not by average. Either path overheating is
    a thermal problem, and averaging would let a healthy coolant loop mask a
    head that is running away.
    """
    cfg = _h()["thi"]
    if res_cht is not None or res_coolant is not None:
        # A residual is a departure from as-new at the same operating point.
        # The scale is the headroom the certified limit allows.
        head = (
            _falling(res_cht, 0.0, float(cfg["cht_limit"]) - float(cfg["cht_nominal"]))
            if res_cht is not None else 1.0
        )
        loop = (
            _falling(res_coolant, 0.0,
                     float(cfg["coolant_limit"]) - float(cfg["coolant_nominal"]))
            if res_coolant is not None else 1.0
        )
        return min(head, loop)

    head = (
        _falling(cht_max, float(cfg["cht_nominal"]), float(cfg["cht_limit"]))
        if cht_max is not None else 1.0
    )
    loop = (
        _falling(coolant, float(cfg["coolant_nominal"]), float(cfg["coolant_limit"]))
        if coolant is not None else 1.0
    )
    return min(head, loop)


def cht_spread_index(spread: float | None) -> float:
    """CHT Spread Index. Already operating-point neutral: a spread is a
    difference between cylinders, so common-mode power effects cancel."""
    if spread is None:
        return 1.0
    return _falling(spread, 0.0, float(_h()["csi"]["spread_limit"]))


def combustion_index(egt_spread: float | None) -> float:
    """Combustion Health Index (Parameter 3). Named CombHI, not CHI --
    PRD Part 2 section 9.2 is explicit that the collision is a trap."""
    if egt_spread is None:
        return 1.0
    cfg = _h()["comb_hi"]
    return _falling(
        egt_spread, float(cfg["egt_spread_nominal"]), float(cfg["egt_spread_limit"])
    )


def egt_efficiency_factor(res_egt: float | None, egt_predicted: float | None) -> float:
    """EEF = (EGT_predicted - EGT_actual) / EGT_predicted.

    This one the PRD already defines as a residual, which is why it is the
    soundest index in section 9.2 -- and it is the shape the others should
    have had.
    """
    if res_egt is None or not egt_predicted:
        return 0.0
    return float(-res_egt / egt_predicted)


def lubrication_index(
    oil_pressure: float | None,
    oil_predicted: float | None,
    correlation: float | None,
    *,
    res_oil_pressure: float | None = None,
) -> float:
    """Lubrication Health Index (Parameter 4).

    LHI = (P_actual / P_predicted) x correlation(P_oil, rpm).

    The correlation term is what makes this a health index rather than a
    pressure gauge: on a sound engine oil pressure is strongly rpm-driven, so
    a WEAKENING correlation indicates bearing leakage or pump wear even while
    the pressure itself is still inside limits.

    A departure from the as-new twin counts in EITHER direction. Low pressure
    is pump wear or bearing leakage; high pressure at the same speed and oil
    temperature is oil that has thickened with oxidation, or a restricted
    gallery -- the operating limits carry a maximum as well as a minimum
    [OM s2.1]. The ratio used to be capped at 1, so a severity-0.9
    lubrication fault reading 63 psi against the twin's 54 (about 27 standard
    deviations) scored a perfect 1.000, and pressure above prediction could
    even buy back a weakening correlation.
    """
    cfg = _h()["lhi"]
    if res_oil_pressure is not None and oil_predicted:
        ratio = 1.0 + res_oil_pressure / oil_predicted
    elif oil_pressure is not None and oil_predicted:
        ratio = oil_pressure / oil_predicted
    else:
        ratio = 1.0
    if ratio > 1.0:
        ratio = 1.0 - float(cfg.get("high_pressure_weight", 1.0)) * (ratio - 1.0)
    ratio = float(np.clip(ratio, 0.0, 1.0))
    if correlation is None:
        eta = 1.0
    else:
        nominal = float(cfg["correlation_nominal"])
        eta = float(np.clip(abs(correlation) / nominal, 0.0, 1.0))
    return float(np.clip(ratio * eta, 0.0, 1.0))


def oil_thermal_index(
    oil_temp: float | None, *, res_oil_temperature: float | None = None
) -> float:
    """Oil Thermal Index (Parameter 5)."""
    cfg = _h()["oti"]
    span = float(cfg["oil_limit"]) - float(cfg["oil_nominal"])
    if res_oil_temperature is not None:
        return _falling(res_oil_temperature, 0.0, span)
    if oil_temp is None:
        return 1.0
    return _falling(oil_temp, float(cfg["oil_nominal"]), float(cfg["oil_limit"]))


def fuel_system_index(
    res_fuel_flow: float | None, fuel_predicted: float | None
) -> float:
    """Fuel System Health Index (Parameter 6).

    The PRD defines it through BSFC, which needs shaft power -- not something
    an engine bus publishes. The residual against the as-new fuel flow at the
    same operating point measures the same thing (burning more fuel than this
    condition warrants) from quantities that actually exist.
    """
    if res_fuel_flow is None or not fuel_predicted:
        return 1.0
    excess = max(0.0, res_fuel_flow) / fuel_predicted
    return float(np.clip(1.0 - excess, 0.0, 1.0))


def mechanical_index(
    vib_rms: float | None, kurtosis: float | None = None
) -> float:
    """Mechanical Health Index (Parameter 7).

    Kurtosis is folded in because bearing damage produces IMPULSES, and
    kurtosis rises well before RMS does -- the earliest mechanical warning
    available (PRD Part 2 section 10.8 Method C).
    """
    cfg = _h()["mhi"]
    base = (
        _falling(vib_rms, float(cfg["vib_nominal"]), float(cfg["vib_limit"]))
        if vib_rms is not None else 1.0
    )
    if kurtosis is None:
        return base
    # 3.0 is Gaussian; higher is impulsive. 9.0 is heavily damaged.
    impulse = _falling(kurtosis, 3.0, 9.0)
    return min(base, impulse)


def electrical_index(
    voltage_sigma: float | None,
    alternator_current: float | None,
    rated_current: float = 40.0,
    battery_soh: float | None = None,
    bus_voltage: float | None = None,
    regulated_voltage: float = 28.0,
) -> float:
    """Electrical Health Index (Parameter 8).

    PRD Part 2 s9.2 gives
    ``EHI = 0.5 x V_stability + 0.3 x I_capacity + 0.2 x SOH_battery``
    with ``I_capacity = I_actual / I_rated``. Two corrections were forced by
    measurement.

    I_CAPACITY IS A LOAD MEASURE, NOT A HEALTH MEASURE
    Current drawn depends on what the aircraft is switched on, not on whether
    the alternator is well. A healthy alternator supplying 8 A of a 40 A rating
    is meeting the demand that exists; it is not 20 % healthy. Taken literally
    the term scored a perfectly healthy engine EHI 0.68, which under the
    worst-subsystem rule raised "ELECTRICAL subsystem POOR" on an aircraft with
    nothing wrong with it -- a MIL-STD-411F 4.1.1a violation, and the same
    category error as THI using absolute CHT (DEV-60).

    What actually indicates a failing alternator is an inability to MEET
    demand, which shows as the bus falling away from its regulated voltage. So
    the capacity term is the voltage the alternator is holding, not the current
    it happens to be asked for, and the raw current is kept only to detect a
    dead alternator -- one supplying nothing at all while the bus sags.

    BATTERY SOH
    Now supplied by ``layer3_ai.battery``, which infers pack internal
    resistance from discharge events (gap G4, closed). When no discharge has
    been observed yet it is still None, and the two real terms are renormalised
    rather than the missing one being scored a free 1.0 -- the same rule as
    before, now applying only until the first engine start rather than forever.
    """
    cfg = _h()["ehi"]
    w = cfg["weights"]
    ref = float(cfg["v_sigma_reference"])

    # V_stability as specified is a VARIANCE measure, and a bus stuck at 22 V
    # has excellent variance. "Stable" and "correct" are not the same property,
    # so the term also accounts for how far the bus sits from regulation --
    # otherwise a dead alternator holding a steadily-wrong voltage scores as
    # healthy on the heaviest-weighted term in the index.
    v_stab = (
        float(np.clip(1.0 - (voltage_sigma / ref), 0.0, 1.0))
        if voltage_sigma is not None else 1.0
    )
    if bus_voltage is not None:
        floor_v = 0.85 * regulated_voltage
        level = float(
            np.clip((bus_voltage - floor_v) / max(regulated_voltage - floor_v, 1e-6),
                    0.0, 1.0)
        )
        v_stab = min(v_stab, level)

    if bus_voltage is None:
        capacity = 1.0
    else:
        # Full marks while the bus holds its regulated value; falls away as it
        # sags. 15 % below regulation is a bus that is no longer being
        # supported at all.
        floor = 0.85 * regulated_voltage
        capacity = float(
            np.clip((bus_voltage - floor) / max(regulated_voltage - floor, 1e-6), 0.0, 1.0)
        )
        # A dead alternator with the battery still carrying the load reads a
        # healthy voltage for a while. Near-zero current with the bus already
        # sagging is that case, and it is worth catching before the battery
        # goes flat.
        if (
            alternator_current is not None
            and alternator_current < 0.02 * rated_current
            and bus_voltage < 0.97 * regulated_voltage
        ):
            capacity = min(capacity, 0.2)

    if battery_soh is None:
        wv, wi = float(w["v_stability"]), float(w["i_capacity"])
        return (wv * v_stab + wi * capacity) / (wv + wi)
    return (
        float(w["v_stability"]) * v_stab
        + float(w["i_capacity"]) * capacity
        + float(w["battery_soh"]) * battery_soh
    )


def rpm_stability_index(rpm_sigma: float | None, rpm_nominal: float) -> float:
    """RSI = 1 - sigma_rpm / rpm_nominal (Parameter 1)."""
    if rpm_sigma is None or rpm_nominal <= 0:
        return 1.0
    return float(np.clip(1.0 - rpm_sigma / rpm_nominal, 0.0, 1.0))


# ---------------------------------------------------------------------------
# The composite
# ---------------------------------------------------------------------------


@dataclass
class HealthSnapshot:
    """Every index at one instant, plus the composite and its band."""

    thi: float = 1.0
    csi: float = 1.0
    comb_hi: float = 1.0
    eef: float = 0.0
    lhi: float = 1.0
    oti: float = 1.0
    fshi: float = 1.0
    mhi: float = 1.0
    ehi: float = 1.0
    rsi: float = 1.0

    thermal: float = 1.0
    mechanical: float = 1.0
    electrical: float = 1.0
    combustion: float = 1.0
    chi: float = 1.0
    band: str = "EXCELLENT"
    action: str = "none"
    used_residuals: bool = False

    def as_dict(self) -> dict[str, float]:
        return {
            "thi": self.thi, "csi": self.csi, "comb_hi": self.comb_hi,
            "eef": self.eef, "lhi": self.lhi, "oti": self.oti,
            "fshi": self.fshi, "mhi": self.mhi, "ehi": self.ehi, "rsi": self.rsi,
            "thermal": self.thermal, "mechanical": self.mechanical,
            "electrical": self.electrical, "combustion": self.combustion,
            "chi": self.chi,
        }


def band_for(chi: float) -> tuple[str, str]:
    """CHI band and its recommended action (PRD Part 2 section 9.3)."""
    for b in _h()["chi_bands"]:
        if chi >= float(b["min"]):
            return str(b["label"]), str(b["action"])
    return "UNSAFE", "ground_immediately"


class HealthEstimator:
    """Computes every index of PRD Part 2 section 9.2 and the composite.

    Stateful, because four of the indices are defined over a time window --
    rpm stability, oil-pressure/rpm correlation, oil-pressure trend and fuel
    flow variance are all meaningless from a single sample.
    """

    def __init__(self, *, window: int = 60, use_residuals: bool = True) -> None:
        self.cfg = _h()
        self.use_residuals = use_residuals
        self.window = window
        self._rpm: deque[float] = deque(maxlen=window)
        self._oil: deque[float] = deque(maxlen=window)
        self._fuel: deque[float] = deque(maxlen=window)
        self._volts: deque[float] = deque(maxlen=window)
        self._chi_ema: float | None = None
        self._cusum: float = 0.0
        # The engine's own settled health level, learned from its first
        # samples. See track() for why this cannot be assumed to be 1.0.
        self._baseline: float | None = None
        self._baseline_n: int = 120
        self._baseline_buf: deque[float] = deque(maxlen=120)
        self.onset_detected: bool = False
        self.onset_hours: float | None = None

    # -- windowed quantities ------------------------------------------------
    def _push(self, values: dict) -> None:
        for key, buf in (("rpm", self._rpm), ("oil_pressure", self._oil),
                         ("fuel_flow", self._fuel), ("battery_voltage", self._volts)):
            v = values.get(key)
            if v is not None and not (isinstance(v, float) and math.isnan(v)):
                buf.append(float(v))

    def _correlation(self) -> float | None:
        if len(self._rpm) < 10 or len(self._oil) < 10:
            return None
        n = min(len(self._rpm), len(self._oil))
        x = np.array(list(self._rpm)[-n:])
        y = np.array(list(self._oil)[-n:])
        # Only the band where pressure FOLLOWS speed carries the signal. Above
        # the relief valve's regulating pressure the valve holds it flat by
        # design, and those samples drag the correlation of a healthy engine
        # down (0.94 at 15,000 ft once the propeller holds speed there).
        ceiling = self.cfg["lhi"].get("correlation_below_psi")
        if ceiling is not None:
            keep = y < float(ceiling)
            if int(keep.sum()) < 10:
                return None
            x, y = x[keep], y[keep]
        # The correlation only carries information if rpm actually MOVED. In a
        # steady cruise leg it barely does, and correlating one noise sequence
        # against another returns a number between -1 and +1 that means
        # nothing -- which then multiplies straight into the lubrication index
        # and drags it down on a perfectly healthy engine. Below the configured
        # share of mean rpm there is no signal to correlate, so the term is
        # dropped rather than guessed.
        #
        # 2 %, not the 0.5 % this was: the rpm INSTRUMENT alone scatters about
        # 1 % at a steady run-up. An engine ground run at a held 4,050 rpm
        # correlated that scatter against oil-pressure noise, got -0.13, and
        # the lubrication index grounded a sound engine for a bearing
        # inspection. Speed changes that carry signal -- climb to cruise, a
        # power change -- are several percent.
        min_cv = float(self.cfg["lhi"].get("correlation_min_rpm_cv", 0.02))
        if x.std() < min_cv * max(abs(x.mean()), 1.0) or y.std() < 1e-6:
            return None
        return float(np.corrcoef(x, y)[0, 1])

    def _sigma(self, buf: deque[float]) -> float | None:
        return float(np.std(buf)) if len(buf) >= 5 else None

    # -- the composite ------------------------------------------------------
    def update(self, values: dict) -> HealthSnapshot:
        """One sample in, one full health snapshot out."""
        self._push(values)
        s = HealthSnapshot()
        res = self.use_residuals

        def r(name: str):
            return values.get(name) if res else None

        s.thi = thermal_index(
            values.get("cht_max"), values.get("coolant_temperature"),
            res_cht=r("res_cht"), res_coolant=r("res_coolant"),
        )
        s.csi = cht_spread_index(values.get("cht_spread"))
        s.comb_hi = combustion_index(values.get("egt_spread"))
        s.eef = egt_efficiency_factor(r("res_egt"), values.get("egt_predicted"))
        s.lhi = lubrication_index(
            values.get("oil_pressure"), values.get("oil_pressure_predicted"),
            self._correlation(), res_oil_pressure=r("res_oil_pressure"),
        )
        s.oti = oil_thermal_index(
            values.get("oil_temperature"), res_oil_temperature=r("res_oil_temperature")
        )
        s.fshi = fuel_system_index(r("res_fuel_flow"), values.get("fuel_flow_predicted"))
        s.mhi = mechanical_index(
            values.get("vibration_rms_total"), values.get("vibration_kurtosis")
        )
        s.ehi = electrical_index(
            self._sigma(self._volts), values.get("alternator_current"),
            bus_voltage=values.get("battery_voltage"),
            battery_soh=values.get("battery_soh"),
            regulated_voltage=float(values.get("regulated_voltage") or 28.0),
        )
        s.rsi = rpm_stability_index(self._sigma(self._rpm), values.get("rpm") or 5000.0)
        s.used_residuals = res

        # Roll the sub-indices up into the four the composite needs. Each
        # subsystem takes the MINIMUM of its contributors: a subsystem is only
        # as healthy as its worst symptom, and averaging lets one good number
        # hide a bad one.
        s.thermal = min(s.thi, s.oti)
        s.mechanical = min(s.mhi, s.lhi, s.rsi)
        s.electrical = s.ehi
        s.combustion = min(s.comb_hi, s.fshi, s.csi)

        w = self.cfg["composite_weights"]
        s.chi = float(
            float(w["thermal"]) * s.thermal
            + float(w["mechanical"]) * s.mechanical
            + float(w["electrical"]) * s.electrical
            + float(w["combustion"]) * s.combustion
        )
        s.band, s.action = band_for(s.chi)
        return s

    # -- trend, PRD Part 2 section 9.4 --------------------------------------
    def track(self, chi: float, flight_hours: float | None = None) -> dict[str, float]:
        """Exponentially-weighted trend and CUSUM onset detection.

        CUSUM finds the KNEE -- the flight hour at which health began falling
        rather than the hour it crossed a limit. That is the number a
        maintenance planner can act on, and a raw index never shows it because
        the decline is buried in noise until it is already large.
        """
        t = self.cfg["trend"]
        alpha = float(t["ema_alpha"])
        self._chi_ema = chi if self._chi_ema is None else (
            alpha * chi + (1.0 - alpha) * self._chi_ema
        )
        k = float(t["cusum_drift_allowance_K"])
        hmax = float(t["cusum_threshold_H"])

        # CHI_nominal is THIS ENGINE'S own settled baseline, not 1.0.
        #
        # Reading it as 1.0 (as-new) is wrong and fires on everything. A
        # healthy in-service engine sits near 0.97, so every sample contributes
        # (1.0 - 0.97) - 0.02 = +0.01, the sum climbs without bound, and the
        # detector trips on a perfectly healthy engine after about fifty
        # samples -- on every airframe in the fleet. CUSUM detects a departure
        # from an established level; the level has to be established first.
        self._baseline_buf.append(chi)
        if self._baseline is None:
            if len(self._baseline_buf) < self._baseline_n:
                return {
                    "chi_ema": self._chi_ema, "cusum": 0.0,
                    # None, NOT float("nan"). This is the right meaning --
                    # the baseline is not established yet -- but NaN is not
                    # JSON, so it took /api/state down with a 500 for the
                    # first 120 samples after every start. That is roughly the
                    # first minute, which is exactly when somebody opens the
                    # console.
                    "onset_detected": 0.0, "baseline": None,
                }
            self._baseline = float(np.median(self._baseline_buf))

        self._cusum = max(0.0, self._cusum + (self._baseline - chi) - k)
        if not self.onset_detected and self._cusum > hmax:
            self.onset_detected = True
            self.onset_hours = flight_hours
        return {
            "chi_ema": self._chi_ema,
            "cusum": self._cusum,
            "onset_detected": float(self.onset_detected),
            "baseline": self._baseline,
        }

    def new_flight(self) -> None:
        """Empty the short windows at an engine restart; keep the trend.

        rpm stability and the oil-pressure/rpm correlation are taken over the
        last minute of samples. Across a restart that minute held the last
        run's 5,470 rpm cruise beside this run's 1,900 rpm idle: a 1,500 rpm
        "instability" and a correlation of two unrelated runs, which read as a
        failing engine (health 0.66, POOR) at every sign-in. The engine's
        trend, baseline and onset detection are about the ENGINE and carry on.
        """
        for buf in (self._rpm, self._oil, self._fuel, self._volts):
            buf.clear()

    def restart_trend(self) -> None:
        """Start the trend again from the engine's condition after maintenance.

        CUSUM measures departure from the engine's OWN settled level, and work
        that restores a subsystem moves that level. Kept, the old baseline
        would read the restored engine as healthier than its reference and
        report the next decline late. The level is relearned from the samples
        that follow, exactly as on first start. Faults that the work did not
        remove are still caught by the residual checks, which compare against
        the as-new twin rather than against this baseline.
        """
        self._chi_ema = None
        self._cusum = 0.0
        self._baseline = None
        self._baseline_buf.clear()
        self.onset_detected = False
        self.onset_hours = None


__all__ = [
    "HealthEstimator",
    "HealthSnapshot",
    "band_for",
    "cht_spread_index",
    "combustion_index",
    "egt_efficiency_factor",
    "electrical_index",
    "fuel_system_index",
    "lubrication_index",
    "mechanical_index",
    "oil_thermal_index",
    "rpm_stability_index",
    "thermal_index",
]
