"""The manufacturer's performance table, as a lookup the physics can use.

Source: BRP-Rotax Operator's Manual 915 i Series, Ed. 0 Rev. 4, PDF pages
111-130 -- 941 operating points at 4500, 5000, 5500 and 5800 rpm, eight
throttle positions, sea level to 22,999 ft and ISA-15 to ISA+30, each giving
power, fuel flow, plenum pressure and plenum temperature. Extracted verbatim to
``configs/engines/rotax_915is_om_performance.csv``; provenance beside it.

WHAT IT IS USED FOR, AND WHAT IT IS NOT
The model's sea-level torque curve is pinned to the certified ratings (EASA
TCDS E.121) and is left alone. The table supplies what no certificate
publishes and what a MALE UAV spends its life in: how the engine behaves AWAY
from sea level ISA. Every quantity is returned as a RATIO to the same engine's
sea-level ISA value at the same speed and throttle position, so the certified
anchors are untouched by construction:

  * power           -- altitude lapse and hot/cold-day effect, at any lever
  * plenum pressure -- the turbocharger's real knee, which is gradual
  * specific fuel consumption
  * plenum air temperature, as a rise above ambient in kelvin (absolute,
    because a ratio of temperatures near 250 K says nothing useful)

Before this, power above 15,000 ft was modelled as a hard knee with ambient
pressure lapse and read up to 38 % low against this table (55.7 kW against
89.5 kW at 23,000 ft), and a hot day cost no power at all (review PHY-01,
PHY-04).

THROTTLE IS A DIFFERENT SCALE
The manual's throttle is the FADEC's linearised throttle position, on which
the last six per cent of travel is the boost range: 94.1 % gives 74 kW and
100 % gives 104 kW at 5800 rpm. The model's lever is not that scale. The two
are matched by SEA-LEVEL POWER FRACTION: a model lever that gives 71 % of
sea-level full-throttle power at some speed is the manual's throttle position
that gives 71 % at that speed. That is the only mapping that leaves sea-level
behaviour exactly where the certified ratings put it.

GAPS
The manual does not print every cell: the 56.5 % row is missing at altitude
(the engine makes almost nothing there), 4500 rpm has only the ISA-15 and ISA
blocks, and 5000 rpm has no ISA+30 block and a partial ISA+15 one. Gaps are
filled -- the low throttle row by holding its ratio to the 72 % row, a missing
temperature cell by the 5500 rpm temperature ratio -- and every filled cell is
flagged in ``printed``. Tests compare the model only with printed values.

RANGE
Inside 4500-5800 rpm, 0-22,999 ft and ISA-15 to ISA+30 the lookup is linear
interpolation. Outside it the nearest edge is used: clamped, never
extrapolated. Below 4500 rpm that means the 4500 rpm ratios, which is a
stated approximation for idle and descent, not manufacturer data.

SPEED
The engine model calls this several times per step against a 20 ms budget.
Numpy's per-call overhead on 2x2x2 corner blocks made one lookup cost 0.42 ms,
so the per-step path runs on nested lists; numpy is used only to load, fill
and validate.
"""

from __future__ import annotations

import bisect
import csv
import functools
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from common import config
from layer2_physics.atmosphere import FT_PER_M, Ambient, isa_temperature_k

RPM_AXIS = np.array([4500.0, 5000.0, 5500.0, 5800.0])
THROTTLE_AXIS = np.array([56.5, 72.0, 84.5, 94.1, 97.4, 98.8, 99.4, 100.0])
ALTITUDE_AXIS = np.array(
    [0.0, 2999.0, 5997.0, 8999.0, 11998.0, 15000.0, 17001.0, 18999.0, 21001.0, 22999.0]
)
ISA_DEV_AXIS = np.array([-15.0, 0.0, 15.0, 30.0])
_ISA = 1  # index of ISA+0 on ISA_DEV_AXIS
_REFERENCE_RPM = 2  # 5500 rpm: the one speed with every temperature block printed

_RPM = tuple(float(v) for v in RPM_AXIS)
_THR = tuple(float(v) for v in THROTTLE_AXIS)
_ALT = tuple(float(v) for v in ALTITUDE_AXIS)
_DEV = tuple(float(v) for v in ISA_DEV_AXIS)
_TOP = float(len(_THR) - 1)


@dataclass(frozen=True)
class Envelope:
    """How the engine differs from its own sea-level ISA behaviour.

    Ratios are against the same speed and throttle position at sea level ISA.
    The neutral value (all ratios 1, no temperature) is what an engine without
    a manufacturer table gets, so callers need no special case.
    """

    power: float = 1.0
    plenum: float = 1.0
    bsfc: float = 1.0
    mat_rise_k: float | None = None
    om_throttle_pct: float | None = None


NEUTRAL = Envelope()


@dataclass(frozen=True, eq=False)
class PerformanceTable:
    path: Path
    power_kw: np.ndarray       # (rpm, throttle, altitude, isa_dev)
    fuel_kg_h: np.ndarray
    plenum_bar: np.ndarray
    mat_rise_k: np.ndarray     # plenum temperature minus ambient temperature
    p_amb_bar: np.ndarray      # (altitude,)
    printed: np.ndarray        # True where the manual printed the value
    phi: np.ndarray            # (rpm, throttle) sea-level ISA power fraction
    # Nested-list copies of the four fields and of phi, for the per-step path.
    fast: tuple = ()
    max_pr: tuple = ()         # (rpm,) highest printed full-throttle pressure ratio


def isa_deviation_c(ambient: Ambient) -> float:
    """Ambient temperature minus the ISA temperature at the pressure altitude."""
    return float(ambient.oat_c - (isa_temperature_k(ambient.altitude_ft / FT_PER_M) - 273.15))


def outside_table(rpm: float, altitude_ft: float, isa_dev_c: float) -> tuple[str, ...]:
    """The ways an operating point lies beyond the printed table, in words.

    Inside 4500-5800 rpm, 0-22,999 ft and ISA-15 to ISA+30 the envelope is
    interpolated manufacturer data. Beyond it the nearest edge is used (RANGE,
    above): a stated approximation, not the manual. The twin keeps running
    there -- a UAV does descend below 4500 rpm -- but whoever reads a
    prediction made there is owed the fact that it is no longer backed by the
    manufacturer's figures. Empty when the point is inside.
    """
    out: list[str] = []
    if rpm < _RPM[0]:
        out.append(f"engine speed {rpm:.0f} rpm is below the table's {_RPM[0]:.0f} rpm")
    elif rpm > _RPM[-1]:
        out.append(f"engine speed {rpm:.0f} rpm is above the table's {_RPM[-1]:.0f} rpm")
    if altitude_ft > _ALT[-1]:
        out.append(f"altitude {altitude_ft:,.0f} ft is above the table's {_ALT[-1]:,.0f} ft")
    elif altitude_ft < _ALT[0]:
        out.append(f"altitude {altitude_ft:,.0f} ft is below the table's sea level")
    if isa_dev_c < _DEV[0]:
        out.append(f"ISA{isa_dev_c:+.0f} is colder than the table's ISA{_DEV[0]:+.0f}")
    elif isa_dev_c > _DEV[-1]:
        out.append(f"ISA{isa_dev_c:+.0f} is hotter than the table's ISA{_DEV[-1]:+.0f}")
    return tuple(out)


def _nearest(value: float, axis: np.ndarray, tol: float, what: str) -> int:
    i = int(np.argmin(np.abs(axis - value)))
    if abs(axis[i] - value) > tol:
        raise ValueError(f"performance table {what} {value} is not on the expected axis")
    return i


@functools.lru_cache(maxsize=4)
def _load(path_str: str) -> PerformanceTable:
    path = Path(path_str)
    shape = (len(RPM_AXIS), len(THROTTLE_AXIS), len(ALTITUDE_AXIS), len(ISA_DEV_AXIS))
    power = np.full(shape, np.nan)
    fuel = np.full(shape, np.nan)
    plenum = np.full(shape, np.nan)
    rise = np.full(shape, np.nan)
    p_amb = np.full(len(ALTITUDE_AXIS), np.nan)

    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            alt = float(row["alt_ft"])
            t_amb = float(row["t_amb_c"])
            r = _nearest(float(row["rpm"]), RPM_AXIS, 1.0, "rpm")
            t = _nearest(float(row["throttle_pct"]), THROTTLE_AXIS, 0.05, "throttle")
            a = _nearest(alt, ALTITUDE_AXIS, 2.0, "altitude")
            dev = t_amb - (isa_temperature_k(alt / FT_PER_M) - 273.15)
            d = _nearest(dev, ISA_DEV_AXIS, 3.0, "ISA deviation")
            if np.isfinite(power[r, t, a, d]):
                raise ValueError(f"performance table has a duplicate cell {(r, t, a, d)}")
            power[r, t, a, d] = float(row["power_kw"])
            fuel[r, t, a, d] = float(row["fuel_kg_h"])
            plenum[r, t, a, d] = float(row["p_plenum_bar"])
            rise[r, t, a, d] = float(row["t_plenum_k"]) - 273.15 - t_amb
            p_amb[a] = float(row["p_amb_bar"])

    printed = np.isfinite(power)
    ratio_fields = (power, fuel, plenum)

    # 1) The 56.5 % row at altitude: hold its ratio to the 72 % row at the
    #    highest altitude where both were printed.
    for r in range(shape[0]):
        for d in range(shape[3]):
            last = None
            for a in range(shape[2]):
                have0 = np.isfinite(power[r, 0, a, d])
                have1 = np.isfinite(power[r, 1, a, d])
                if have0 and have1:
                    last = a
                elif not have0 and have1 and last is not None:
                    for q in ratio_fields:
                        q[r, 0, a, d] = q[r, 1, a, d] * q[r, 0, last, d] / q[r, 1, last, d]
                    rise[r, 0, a, d] = rise[r, 1, a, d] + (rise[r, 0, last, d] - rise[r, 1, last, d])

    # 2) Missing temperature cells: the engine's own ISA value, carried to the
    #    other temperature by the 5500 rpm temperature ratio at the same
    #    throttle position and altitude.
    ref = _REFERENCE_RPM
    for r, t, a, d in zip(*np.nonzero(~np.isfinite(power)), strict=True):
        if not np.isfinite(power[r, t, a, _ISA]) or not np.isfinite(power[ref, t, a, d]):
            raise ValueError(f"performance table cannot fill cell {(r, t, a, d)}")
        for q in ratio_fields:
            q[r, t, a, d] = q[r, t, a, _ISA] * q[ref, t, a, d] / q[ref, t, a, _ISA]
        rise[r, t, a, d] = rise[r, t, a, _ISA] + (rise[ref, t, a, d] - rise[ref, t, a, _ISA])

    for name, q in (("power", power), ("fuel", fuel), ("plenum", plenum), ("rise", rise)):
        if not np.all(np.isfinite(q)):
            raise ValueError(f"performance table {name} still has gaps after filling")
    if not np.all(np.isfinite(p_amb)):
        raise ValueError("performance table is missing an ambient pressure")

    # Sea-level ISA power fraction against throttle position. Inverted to map
    # the model's lever onto the manual's scale, so it must rise strictly.
    phi = power[:, :, 0, _ISA] / power[:, -1:, 0, _ISA]
    if not np.all(np.diff(phi, axis=1) > 0.0):
        raise ValueError("performance table power does not rise with throttle at sea level")

    wot_pr = plenum[:, -1, :, :] / p_amb[None, :, None]
    max_pr = tuple(float(v) for v in np.where(printed[:, -1, :, :], wot_pr, 0.0).max(axis=(1, 2)))

    return PerformanceTable(
        path=path, power_kw=power, fuel_kg_h=fuel, plenum_bar=plenum,
        mat_rise_k=rise, p_amb_bar=p_amb, printed=printed, phi=phi,
        fast=(power.tolist(), fuel.tolist(), plenum.tolist(), rise.tolist(),
              [tuple(row) for row in phi.tolist()]),
        max_pr=max_pr,
    )


@functools.lru_cache(maxsize=8)
def _resolve(file_name: str) -> str:
    return str(config.config_dir() / "engines" / file_name)


def table_for(engine: dict) -> PerformanceTable | None:
    """The engine's manufacturer table, or None when its definition has none."""
    spec = engine.get("performance_table")
    if not spec:
        return None
    return _load(_resolve(str(spec["file"])))


# ---------------------------------------------------------------------------
# Interpolation (plain Python on purpose -- see SPEED above)
# ---------------------------------------------------------------------------


def _frac(value: float, axis: tuple) -> float:
    """Fractional index of ``value`` on an ascending axis, clamped to its ends."""
    n = len(axis) - 1
    if value <= axis[0]:
        return 0.0
    if value >= axis[n]:
        return float(n)
    i = bisect.bisect_right(axis, value) - 1
    return i + (value - axis[i]) / (axis[i + 1] - axis[i])


def _split(fi: float, n: int) -> tuple[int, float]:
    i0 = min(int(fi), n - 2)
    return i0, fi - i0


def _tri(q: list, ti: float, ai: float, di: float) -> float:
    """Linear interpolation of one speed's (throttle, altitude, isa_dev) block."""
    t0, wt = _split(ti, len(q))
    a0, wa = _split(ai, len(q[0]))
    d0, wd = _split(di, len(q[0][0]))
    out = 0.0
    for t, w_t in ((t0, 1.0 - wt), (t0 + 1, wt)):
        qa0 = q[t][a0]
        qa1 = q[t][a0 + 1]
        v0 = qa0[d0] + (qa0[d0 + 1] - qa0[d0]) * wd
        v1 = qa1[d0] + (qa1[d0 + 1] - qa1[d0]) * wd
        out += w_t * (v0 + (v1 - v0) * wa)
    return out


def _rpm_weights(rpm: float) -> tuple[tuple[int, float], ...]:
    r0, wr = _split(_frac(rpm, _RPM), len(_RPM))
    if wr <= 0.0:
        return ((r0, 1.0),)
    if wr >= 1.0:
        return ((r0 + 1, 1.0),)
    return ((r0, 1.0 - wr), (r0 + 1, wr))


def envelope(
    engine: dict,
    rpm: float,
    throttle_fraction: float,
    altitude_ft: float,
    isa_dev_c: float,
) -> Envelope:
    """The engine's behaviour at a condition, relative to sea level ISA.

    ``throttle_fraction`` is the model lever's SEA-LEVEL power fraction at this
    speed (``perf_maps._throttle_factor``), which is how it is placed on the
    manual's throttle scale.
    """
    tab = table_for(engine)
    if tab is None:
        return NEUTRAL
    power_l, fuel_l, plenum_l, rise_l, phi_l = tab.fast
    ai = _frac(float(altitude_ft), _ALT)
    di = _frac(float(isa_dev_c), _DEV)
    isa = float(_ISA)
    power = plenum = bsfc = rise = th = 0.0
    for r, w in _rpm_weights(float(rpm)):
        phi = phi_l[r]
        f = min(max(float(throttle_fraction), phi[0]), 1.0)
        ti = _frac(f, phi)
        pq, mq, lq = power_l[r], fuel_l[r], plenum_l[r]
        p = _tri(pq, ti, ai, di)
        p0 = _tri(pq, ti, 0.0, isa)
        m = _tri(mq, ti, ai, di)
        m0 = _tri(mq, ti, 0.0, isa)
        power += w * p / p0
        plenum += w * _tri(lq, ti, ai, di) / _tri(lq, ti, 0.0, isa)
        # At the lowest throttle high up the engine makes almost nothing and
        # BSFC runs into four figures; bounded so a near-zero power cell cannot
        # dominate a fuel-flow figure the model computes from its own power.
        ratio = (m / max(p, 1e-3)) / (m0 / max(p0, 1e-3))
        bsfc += w * min(max(ratio, 0.7), 2.5)
        rise += w * _tri(rise_l[r], ti, ai, di)
        t0, wt = _split(ti, len(_THR))
        th += w * (_THR[t0] + (_THR[t0 + 1] - _THR[t0]) * wt)
    return Envelope(power=power, plenum=plenum, bsfc=bsfc, mat_rise_k=rise, om_throttle_pct=th)


def wot_plenum_ratio(engine: dict, rpm: float, altitude_ft: float, isa_dev_c: float) -> float:
    """Full-throttle plenum pressure here, over full throttle at sea level ISA.

    Below 1.0 the turbocharger cannot hold the sea-level boost: the knee.
    """
    tab = table_for(engine)
    if tab is None:
        return 1.0
    plenum_l = tab.fast[2]
    ai = _frac(float(altitude_ft), _ALT)
    di = _frac(float(isa_dev_c), _DEV)
    return sum(
        w * _tri(plenum_l[r], _TOP, ai, di) / plenum_l[r][-1][0][_ISA]
        for r, w in _rpm_weights(float(rpm))
    )


def sea_level_wot_plenum_bar(engine: dict, rpm: float) -> float | None:
    """Full-throttle plenum pressure at sea level ISA, from the manual."""
    tab = table_for(engine)
    if tab is None:
        return None
    plenum_l = tab.fast[2]
    return sum(w * plenum_l[r][-1][0][_ISA] for r, w in _rpm_weights(float(rpm)))


def max_pressure_ratio(engine: dict, rpm: float) -> float | None:
    """Highest compressor pressure ratio the manual prints at a speed."""
    tab = table_for(engine)
    if tab is None:
        return None
    return sum(w * tab.max_pr[r] for r, w in _rpm_weights(float(rpm)))


# ---------------------------------------------------------------------------
# Printed-cell references, for validation. These read the manual's numbers
# directly and never go through ``envelope``, so a test built on them checks
# the model against the manual rather than against itself.
# ---------------------------------------------------------------------------


def wot_power_ratio_printed(engine: dict, rpm: float, altitude_ft: float) -> float | None:
    """Full-throttle ISA power at an altitude over sea level, printed cells only."""
    tab = table_for(engine)
    if tab is None:
        return None
    r = _nearest(float(rpm), RPM_AXIS, 1.0, "rpm")
    if not tab.printed[r, -1, :, _ISA].all():
        raise ValueError(f"full-throttle ISA row at {rpm:.0f} rpm is not fully printed")
    row = tab.power_kw[r, -1, :, _ISA]
    return float(np.interp(altitude_ft, ALTITUDE_AXIS, row) / row[0])


def _eta_ratios(tab: PerformanceTable, displacement_l: float, a0: float, a1: float) -> dict:
    """Full-throttle ISA volumetric efficiency over sea level, per rated speed.

    Air mass flow from the manual's own closure relation (power = a0 + a1 *
    airflow [g/min]); charge density from the printed plenum pressure and
    temperature.
    """
    out = {}
    for r in (2, 3):  # 5500 and 5800 rpm, the two speeds the engine is rated at
        swept = displacement_l * 1e-3 * RPM_AXIS[r] / 120.0
        eta = []
        for a in range(len(ALTITUDE_AXIS)):
            air = (tab.power_kw[r, -1, a, _ISA] - a0) / a1 / 60000.0
            t_amb = isa_temperature_k(ALTITUDE_AXIS[a] / FT_PER_M)
            t_plenum = t_amb + tab.mat_rise_k[r, -1, a, _ISA]
            rho = tab.plenum_bar[r, -1, a, _ISA] * 1e5 / (287.0 * t_plenum)
            eta.append(air / (swept * rho))
        out[r] = np.asarray(eta) / eta[0]
    return out


def _eta_args(engine: dict, tab: PerformanceTable) -> tuple:
    intake = engine["intake"]
    return (
        str(tab.path),
        float(engine["geometry"]["displacement_total_L"]),
        float(intake["airflow_power_intercept_kW"]),
        float(intake["airflow_power_slope_kW_per_g_min"]),
    )


@functools.lru_cache(maxsize=4)
def _eta_fit(path_str: str, displacement_l: float, a0: float, a1: float) -> tuple[float, float]:
    """Fitted as 1 + b*h + c*h^2 (h in thousands of feet) through sea level.

    The manufacturer's fuel-flow column gives the same lapse independently
    (-14.8 % at 22,999 ft and 5800 rpm at constant mixture, against -13.5 %
    from the fit), which is why the fit is trusted.
    """
    ratios = _eta_ratios(_load(path_str), displacement_l, a0, a1)
    h = np.tile(ALTITUDE_AXIS / 1000.0, len(ratios))
    y = np.concatenate([ratios[r] for r in sorted(ratios)]) - 1.0
    design = np.column_stack([h, h * h])
    (b, c), *_ = np.linalg.lstsq(design, y, rcond=None)
    return float(b), float(c)


def eta_vol_altitude_ratio(engine: dict, altitude_ft: float) -> float | None:
    """Volumetric efficiency at altitude over sea level, from the manual (fitted)."""
    tab = table_for(engine)
    if tab is None:
        return None
    b, c = _eta_fit(*_eta_args(engine, tab))
    h = min(max(float(altitude_ft), _ALT[0]), _ALT[-1]) / 1000.0
    return 1.0 + b * h + c * h * h


def eta_vol_ratio_printed(engine: dict, altitude_ft: float) -> float | None:
    """The same ratio straight from printed cells, mean of 5500 and 5800 rpm."""
    tab = table_for(engine)
    if tab is None:
        return None
    ratios = _eta_ratios(tab, *_eta_args(engine, tab)[1:])
    return float(np.mean([np.interp(altitude_ft, ALTITUDE_AXIS, v) for v in ratios.values()]))
