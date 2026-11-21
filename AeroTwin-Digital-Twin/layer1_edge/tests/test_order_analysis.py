"""Envelope order analysis: naming the defect, not just noticing the noise.

The property that matters is NOT "it finds a peak". It is that a HEALTHY
bearing produces no finding. The first implementation scored every order at
15-28x a global-median floor and diagnosed four simultaneous defects on a
perfectly good engine -- which is worse than no analysis, because an operator
who is told the bearings are failing when they are not stops reading.
"""

from __future__ import annotations

import numpy as np
import pytest

from common import config
from layer1_edge.order_analysis import (
    DEMOD_BANDWIDTH_MARGIN,
    MIN_REVOLUTIONS,
    analyse,
    bearing_orders,
    diagnose,
    kurtogram_band,
    required_duration_s,
    spectral_kurtosis,
)
from layer2_physics.degradation import FaultMode, InjectedFault
from layer2_physics.engine_sim import VirtualEngine

FS = 10_000.0


def _engine():
    return config.load_engine("rotax_915is")


def _waveform(bearing_condition: float, seed: int = 7, rpm: float | None = None):
    """A window of vibration at a chosen speed and bearing condition.

    `bearing_condition` is assigned directly and the waveform taken in the same
    breath, with no `step` in between -- the degradation model recomputes that
    factor from flight hours on every step, so a value set and then stepped
    over is silently discarded. `test_a_worn_bearing_is_found_at_cruise`
    carries the same case through a real injected fault instead, which is
    slower and answers the objection this helper invites.
    """
    v = VirtualEngine(engine_key="rotax_915is", seed=seed)
    for _ in range(40):
        v.step(0.5)
    if rpm is not None:
        v.model.omega = rpm * 2.0 * np.pi / 60.0
    v.degradation.factors.bearing_condition = bearing_condition
    rpm = v.model.omega * 60.0 / (2.0 * np.pi)
    x = v.vibration_waveform(duration_s=required_duration_s(rpm), fs=FS)
    return x, rpm


# Idle, climb, cruise, and the top of the certified range. The analysis used to
# be exercised only at the ~1400 rpm the warm-up profile happens to sit at.
ENVELOPE_RPM = (1400.0, 2200.0, 3500.0, 4800.0, 5500.0, 5800.0)


def test_defect_orders_are_speed_independent():
    """The whole reason for working in orders rather than Hz."""
    o = bearing_orders(_engine())
    assert o["BPFO"] == pytest.approx(3.5888, abs=1e-3)
    assert o["BPFI"] == pytest.approx(5.4112, abs=1e-3)
    # And they must not collide with combustion, which sits on integers and
    # half-integers because a four-stroke fires every two revolutions.
    for name in ("BPFO", "BPFI"):
        nearest_half = round(o[name] * 2) / 2
        assert abs(o[name] - nearest_half) > 0.05, f"{name} collides with structure"


def test_window_length_is_computed_from_speed_not_assumed():
    """0.4 s at idle is 13 revolutions and cannot resolve a defect order."""
    assert required_duration_s(1400) > 1.5
    assert required_duration_s(5800) < 0.5
    # The waveform default would be far too short at idle.
    assert 0.4 * 1400 / 60.0 < MIN_REVOLUTIONS


def test_a_healthy_bearing_produces_no_finding():
    """THE REGRESSION. A false positive here is worse than no analysis."""
    x, rpm = _waveform(1.00)
    a = analyse(x, FS, rpm, _engine())
    assert a.resolved, a.reason
    assert diagnose(a) == [], f"healthy engine diagnosed with {diagnose(a)}"
    assert a.peaks["BPFO"] < 3.0


def test_a_worn_bearing_is_found_and_the_race_is_named():
    """Not 'vibration is high' -- WHICH race, which is the point."""
    x, rpm = _waveform(0.45)
    a = analyse(x, FS, rpm, _engine())
    assert a.resolved, a.reason
    found = diagnose(a)
    assert found, "a badly worn bearing produced no finding"
    assert any("outer race" in f for f in found), found
    # The simulator injects BPFO at gain 1.0 and BPFI at 0.6, so the outer
    # race must dominate. Getting this backwards would mean the analysis is
    # finding something, but not the thing that is actually wrong.
    assert a.peaks["BPFO"] > a.peaks["BPFI"]


def test_severity_orders_correctly():
    """More wear must give a larger peak, or the number means nothing."""
    healthy = analyse(*_waveform(1.00)[:1], FS, _waveform(1.00)[1], _engine())
    worn = analyse(*_waveform(0.45)[:1], FS, _waveform(0.45)[1], _engine())
    assert worn.peaks["BPFO"] > healthy.peaks["BPFO"] * 2.0


def test_structural_orders_are_never_reported_as_defects():
    """Combustion and gear mesh are the engine working, not a fault."""
    x, rpm = _waveform(0.45)
    a = analyse(x, FS, rpm, _engine())
    for finding in diagnose(a):
        assert "FIRING" not in finding and "GMF" not in finding


def test_an_under_length_window_is_reported_not_silently_trusted():
    """A BPFO bin from 13 revolutions also contains the 3.5x structural order."""
    v = VirtualEngine(engine_key="rotax_915is", seed=7)
    for _ in range(40):
        v.step(0.5)
    rpm = v.model.omega * 60.0 / (2.0 * np.pi)
    a = analyse(v.vibration_waveform(duration_s=0.4, fs=FS), FS, rpm, _engine())
    assert a.resolved is False
    assert "revolutions" in a.reason and "resolution" in a.reason


# ---------------------------------------------------------------------------
# The band-selection regression. Everything above this line passed while the
# analysis was blind at cruise, because everything above it runs at idle.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rpm", ENVELOPE_RPM)
def test_a_worn_bearing_is_found_across_the_whole_speed_range(rpm):
    """THE REGRESSION. It worked at idle and at no other speed.

    The band search used sixteen bands of one fixed width. A band narrower
    than the defect repetition rate passes a carrier and one sideband, which
    is a modulated tone rather than an impulse train, so the CORRECT band
    scored worse than its neighbours -- and since the repetition rate rises
    with rpm while a fixed width does not, the failure only appears when the
    engine speeds up. Measured before the fix, BPFO at cruise: 1.2x, 1.2x,
    1.3x. There is nothing to diagnose in those numbers.
    """
    a = analyse(_waveform(0.45, rpm=rpm)[0], FS, rpm, _engine())
    assert a.resolved, a.reason
    found = diagnose(a)
    assert found, f"a badly worn bearing produced no finding at {rpm:.0f} rpm"
    assert any("outer race" in f for f in found), found
    assert a.peaks["BPFO"] > a.peaks["BPFI"], (
        f"inner race beat outer at {rpm:.0f} rpm; the simulator injects BPFO "
        f"at gain 1.0 and BPFI at 0.6"
    )


@pytest.mark.parametrize("rpm", ENVELOPE_RPM)
def test_a_healthy_bearing_stays_quiet_across_the_whole_speed_range(rpm):
    """The false positive is the expensive failure, so widen its test too.

    A search that reaches wider bands sees more of the spectrum, and the thing
    that must not follow is a finding on a good engine at any speed.
    """
    a = analyse(_waveform(1.00, rpm=rpm)[0], FS, rpm, _engine())
    assert diagnose(a) == [], f"healthy engine diagnosed at {rpm:.0f} rpm"


@pytest.mark.parametrize("rpm", ENVELOPE_RPM)
def test_the_chosen_band_can_actually_demodulate_the_defect(rpm):
    """The property the fixed-width search violated, asserted directly.

    A passband must span several multiples of the fastest defect frequency or
    it cannot represent the modulation at all -- whatever its kurtosis says.
    At 5500 rpm BPFI is 496 Hz and the old fixed width was 281 Hz, so the band
    was narrower than the thing it was supposed to reveal.
    """
    x, _ = _waveform(0.45, rpm=rpm)
    fastest_hz = max(bearing_orders(_engine()).values()) * rpm / 60.0
    (lo, hi), _ = kurtogram_band(
        x, FS, min_bandwidth_hz=DEMOD_BANDWIDTH_MARGIN * fastest_hz
    )
    assert hi - lo >= DEMOD_BANDWIDTH_MARGIN * fastest_hz, (
        f"band {lo:.0f}-{hi:.0f} Hz is narrower than "
        f"{DEMOD_BANDWIDTH_MARGIN:.0f}x the {fastest_hz:.0f} Hz BPFI it must demodulate"
    )


def test_the_band_search_responds_to_the_bearing_and_not_only_to_the_engine():
    """It returned the same band whether the bearing was healthy or destroyed.

    That is the symptom that gave the defect away: a band chosen by
    impulsiveness must find MORE impulsiveness on a wrecked bearing than on a
    good one at the same operating point. It did not, because the score was
    dominated by artefacts common to both -- the analysis window's own taper,
    and rectification of a real signal in place of a complex envelope.
    """
    rpm = 5500.0
    fastest_hz = max(bearing_orders(_engine()).values()) * rpm / 60.0
    floor = DEMOD_BANDWIDTH_MARGIN * fastest_hz
    _, healthy_k = kurtogram_band(
        _waveform(1.00, rpm=rpm)[0], FS, min_bandwidth_hz=floor
    )
    _, worn_k = kurtogram_band(
        _waveform(0.30, rpm=rpm)[0], FS, min_bandwidth_hz=floor
    )
    assert worn_k > healthy_k, (
        f"a destroyed bearing scored no more impulsive ({worn_k:.2f}) than a "
        f"healthy one ({healthy_k:.2f}); the band search is reading something "
        f"other than the bearing"
    )


def test_spectral_kurtosis_reads_zero_for_noise_and_high_for_impulses():
    """The scoring function itself, on signals whose answer is known.

    The first version rectified a real band-passed signal, and a folded
    Gaussian has kurtosis +0.86 -- so a band of pure noise scored as though
    something were happening in it, and every band carried the same offset.
    """
    rng = np.random.default_rng(3)
    n = 8192
    noise = np.abs(rng.normal(size=n) + 1j * rng.normal(size=n))
    assert abs(spectral_kurtosis(noise)) < 0.2, spectral_kurtosis(noise)

    # A constant envelope is what a pure tone demodulates to: the LEAST
    # impulsive thing there is, and it must score below noise, not above.
    assert spectral_kurtosis(np.ones(n)) < 0.0

    impulses = np.full(n, 0.01)
    impulses[::128] = 1.0
    assert spectral_kurtosis(impulses) > 10.0, spectral_kurtosis(impulses)


def test_the_kurtogram_never_returns_an_empty_band():
    """A bandwidth floor no band can satisfy must not leave the caller with
    nothing. The widest available band is always a legitimate answer."""
    x, rpm = _waveform(0.45, rpm=3500.0)
    (lo, hi), k = kurtogram_band(x, FS, min_bandwidth_hz=1e9)
    assert hi > lo
    assert np.isfinite(k)


@pytest.mark.slow
def test_a_worn_bearing_is_found_at_cruise_with_a_real_injected_fault():
    """The failure exactly as it was reported, with no shortcut anywhere.

    The other tests set `bearing_condition` directly. That is valid only
    because they take the waveform before the next step overwrites it, and it
    is fair to ask whether the fix survives a bearing that got there honestly.
    So this one flies a real injected fault to cruise and reads the result
    through the same call the live twin makes. Measured before the fix at this
    operating point: BPFO 1.3x and no finding at all.
    """
    v = VirtualEngine(engine_key="rotax_915is", seed=7)
    v.inject(InjectedFault(mode=FaultMode.ABNORMAL_VIBRATION, onset_hours=0.0,
                           severity=0.6, ramp_hours=0.02))
    for _ in range(1800):
        frame = v.step(0.5)

    rpm = float(frame.rpm)
    assert rpm > 4000.0, f"never reached cruise: {rpm:.0f} rpm"
    assert v.degradation.factors.bearing_condition < 0.5, "the fault never expressed"

    wave = v.vibration_waveform(duration_s=required_duration_s(rpm), fs=FS)
    a = analyse(wave, FS, rpm, v._engine)
    found = diagnose(a)
    assert a.resolved, a.reason
    assert any("outer race" in f for f in found), (
        f"at {rpm:.0f} rpm with bearing_condition "
        f"{v.degradation.factors.bearing_condition:.3f}, diagnosis was {found} "
        f"(BPFO {a.peaks.get('BPFO', 0):.2f}x, band {a.band_hz})"
    )
