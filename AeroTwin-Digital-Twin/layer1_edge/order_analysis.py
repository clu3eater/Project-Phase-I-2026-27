"""Envelope order analysis -- turning a vibration waveform into a diagnosis.

WHY THIS EXISTS
---------------
`engine_sim.vibration_waveform()` generates a 10 kHz signal containing 1x
unbalance, 2x misalignment, gear mesh, firing frequency and -- when the
bearing is worn -- BPFO and BPFI impulses on a structural resonance. Its own
docstring says it exists because the problem statement's "vibration
signatures" (section B) and "abnormal vibration patterns" (section C) need
FFT, envelope and order analysis of an actual waveform.

Nothing called it. There was no FFT, Hilbert, Welch or envelope analysis
anywhere in the tree, and `TwinState.dominant_frequency_hz` and
`spectral_peaks` were declared and never assigned. Vibration diagnosis ran on
two scalars, RMS and kurtosis. Those say a bearing is rough. They cannot say
WHICH race is failing, and that is the difference between "inspect the engine"
and "the outer race is spalling".

WHY ORDER ANALYSIS AND NOT AN FFT
---------------------------------
A plain spectrum smears when shaft speed moves, and on a UAV in a climb it
moves constantly. Resampling to equal increments of CRANK ANGLE converts the
signal to the order domain, where a defect frequency becomes a fixed ORDER --
a pure function of bearing geometry, independent of rpm:

    BPFO order = (n_balls / 2) * (1 - d / D)
    BPFI order = (n_balls / 2) * (1 + d / D)

For this bearing (9 balls, 8.1 mm on a 40 mm pitch) that is 3.5888x and
5.4112x, whatever the engine happens to be doing.

WHY THAT SEPARATES A BEARING FROM COMBUSTION
--------------------------------------------
This is a RECIPROCATING engine, so its vibration is dominated by combustion --
far louder than any bearing defect. But a four-stroke fires every two
revolutions, so combustion and its harmonics land on INTEGER AND HALF-INTEGER
orders (0.5, 1.0, 1.5, 2.0 ...). BPFO at 3.5888 and BPFI at 5.4112 do not. In
the order domain the loud thing and the interesting thing sit in different
bins, which is precisely why this technique works on engines at all.

The separation is 0.0888 orders from the nearest half-integer, and order
resolution is 1/(revolutions analysed) -- so a window must cover roughly 34
revolutions to resolve it. `required_duration_s` computes that from rpm rather
than assuming it; at idle the waveform's 0.4 s default gives 13 revolutions
and would put BPFO in the same bin as the 3.5x structural order.

WHY THE BAND IS FOUND AND NOT FIXED
-----------------------------------
Bearing impulses ring a structural resonance, and envelope analysis must
band-pass to that resonance before demodulating. The simulator happens to use
2600 Hz. Hardcoding 2600 would tune this to our own generator, and it would
then score perfectly for a reason that has nothing to do with the method --
the DEV-95 mistake exactly. So the band is located by SPECTRAL KURTOSIS, which
measures impulsiveness per band and is the standard answer to this question.
On real hardware the resonance sits elsewhere and the same code finds it.

WHY THE BAND'S WIDTH IS SEARCHED AND NOT FIXED
----------------------------------------------
The first version searched sixteen bands of one fixed width (Nyquist/16, or
281 Hz here) and took the most impulsive. That is not a kurtogram, and it fails
for a reason that only shows up when the engine speeds up.

A defect impulse rings down and repeats at the defect frequency, so its energy
sits in the carrier plus SIDEBANDS spaced f_defect apart. A passband narrower
than that spacing admits the carrier and at most one sideband, and a carrier
with one sideband is not an impulse train -- it is a smoothly modulated tone,
whose kurtosis is NEGATIVE. So the correct band scores WORSE than its noisy
neighbours, and the search confidently returns the wrong answer.

That failure is a function of speed, because f_defect scales with rpm while a
fixed band width does not. Measured on the pure bearing component alone, the
spectral kurtosis of a narrow band around the carrier falls 2.32 -> 0.43 ->
-0.26 at 1400 -> 3500 -> 5500 rpm, while the same signal in a WIDE band holds
4.67 -> 3.33 -> 2.48. Idle worked by luck; cruise could not work at all.

So width is a search dimension, not a constant: a dyadic tree of levels from
the whole spectrum down, each level also offset by half a band so a resonance
landing on a boundary is not split in two (2600 Hz sits almost exactly on the
level-1 edge here). And the tree stops descending at a width the physics fixes
-- `DEMOD_BANDWIDTH_MARGIN` times the fastest defect frequency we intend to
demodulate -- because below that no band can represent the modulation whatever
its kurtosis says. That floor is derived from rpm and bearing geometry on every
call, so it tracks the engine instead of assuming a speed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

_log = logging.getLogger(__name__)

# Combustion, unbalance and misalignment live on these. A peak here is the
# engine running, not a bearing failing.
STRUCTURAL_ORDERS = (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0)

# Samples per revolution after angular resampling. 256 resolves orders up to
# 128, which covers gear mesh at 36x with room to spare.
SAMPLES_PER_REV = 256

# Revolutions needed to separate a defect order from the nearest structural
# one. Order resolution is 1/N_rev, and 0.0888 orders of separation needs
# roughly a third of that as resolution.
MIN_REVOLUTIONS = 40

# A demodulation band must span at least this many multiples of the fastest
# defect frequency it is meant to reveal. Below roughly 2x the band admits the
# carrier and a single sideband, which reconstructs as a modulated tone rather
# than an impulse train and scores NEGATIVE kurtosis. 3 is the usual rule of
# thumb -- carrier plus a sideband pair plus room for the ring-down -- and it
# also bounds the depth of the search tree, which is what keeps this inside the
# edge node's tick budget.
DEMOD_BANDWIDTH_MARGIN = 3.0

# Deepest dyadic split of the spectrum. Level L gives 2**L bands; the bandwidth
# floor above normally stops the descent long before this, which is only a
# backstop for a very slow engine.
MAX_KURTOGRAM_LEVEL = 5

# Fraction trimmed from each end of a band's envelope before its kurtosis is
# taken. Band-passing in the frequency domain is a CIRCULAR convolution, so the
# first and last samples wrap; left in, that edge transient is itself a large
# impulse and every band scores as though it were impulsive.
_ENVELOPE_EDGE_TRIM = 0.05


@dataclass
class OrderAnalysis:
    """What the edge node learned from one window of vibration."""

    rpm: float = 0.0
    revolutions: float = 0.0
    order_resolution: float = 0.0
    band_hz: tuple[float, float] = (0.0, 0.0)
    band_kurtosis: float = 0.0
    dominant_frequency_hz: float | None = None
    # order name -> amplitude, relative to the envelope spectrum floor
    peaks: dict[str, float] = field(default_factory=dict)
    resolved: bool = False
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "rpm": round(self.rpm, 1),
            "revolutions": round(self.revolutions, 1),
            "order_resolution": round(self.order_resolution, 4),
            "band_hz": [round(self.band_hz[0], 1), round(self.band_hz[1], 1)],
            "band_kurtosis": round(self.band_kurtosis, 2),
            "dominant_frequency_hz": (
                round(self.dominant_frequency_hz, 1)
                if self.dominant_frequency_hz else None
            ),
            "spectral_peaks": {k: round(v, 3) for k, v in self.peaks.items()},
            "resolved": self.resolved,
            "reason": self.reason,
        }


def bearing_orders(engine: dict) -> dict[str, float]:
    """Defect orders from bearing geometry. Independent of speed, by design."""
    b = engine["vibration"]["bearing"]
    nb = float(b["n_balls"])
    ratio = float(b["ball_diameter_mm"]) / float(b["pitch_diameter_mm"])
    return {
        "BPFO": (nb / 2.0) * (1.0 - ratio),                 # outer race
        "BPFI": (nb / 2.0) * (1.0 + ratio),                 # inner race
        "BSF": (1.0 / (2.0 * ratio)) * (1.0 - ratio ** 2),  # rolling element
        "FTF": 0.5 * (1.0 - ratio),                         # cage
    }


def required_duration_s(rpm: float, revolutions: int = MIN_REVOLUTIONS) -> float:
    """How long a window must be, at this speed, to resolve a defect order.

    Computed rather than assumed: at 2000 rpm this is 1.2 s, and the
    waveform's 0.4 s default would give 13 revolutions -- putting BPFO in the
    same bin as the 3.5x structural order.
    """
    return revolutions / (max(rpm, 1.0) / 60.0)


def spectral_kurtosis(env: np.ndarray, trim: float = _ENVELOPE_EDGE_TRIM) -> float | None:
    """Kurtosis of a band's squared envelope: 0 for noise, large for impulses.

    Antoni's definition, on the COMPLEX envelope: `E|z|^4 / (E|z|^2)^2 - 2`,
    which is zero for circular Gaussian noise. The first version took the
    excess kurtosis of `abs()` applied to a real band-passed signal, which is
    full-wave rectification rather than demodulation; a folded Gaussian has
    kurtosis +0.86, so a band of pure noise scored as though something were
    happening in it. Returns None when the band holds no usable energy.
    """
    if trim:
        cut = int(len(env) * trim)
        if cut:
            env = env[cut:len(env) - cut]
    if len(env) < 16:
        return None
    power = env * env
    mean = float(power.mean())
    if mean <= 1e-24:
        return None
    return float((power * power).mean() / (mean * mean) - 2.0)


def kurtogram_band(
    x: np.ndarray,
    fs: float,
    *,
    min_bandwidth_hz: float = 0.0,
    min_hz: float = 500.0,
    max_level: int = MAX_KURTOGRAM_LEVEL,
) -> tuple[tuple[float, float], float]:
    """Find the band where bearing impulses ring: both WHERE and HOW WIDE.

    A dyadic kurtogram tree. Level 0 is the whole usable spectrum, level L
    splits it into 2**L bands, and each level beyond the first is also swept
    with the grid offset by half a band so that a resonance sitting on a
    boundary is not divided between two neighbours. Every candidate is
    demodulated and scored by `spectral_kurtosis`; the best (centre, width)
    pair wins.

    `min_bandwidth_hz` stops the descent. It is not a tuning knob: a band
    narrower than a few times the defect repetition rate cannot represent the
    modulation at all, so scoring one is meaningless. `analyse` derives it from
    rpm and bearing geometry.

    Each candidate is demodulated at its own DECIMATED rate -- the band's bins
    are inverse-transformed on their own, giving the complex envelope sampled
    just fast enough for that bandwidth. A frequency shift only rotates phase,
    so the magnitude is unchanged, and the cost of a level becomes one
    transform over the spectrum rather than one full-length transform per band.
    Measured on this engine that is 8.9 ms at idle against 57 ms for the
    single-width version it replaces, so a wider search also became a cheaper
    one.
    """
    n = len(x)
    nyq = fs / 2.0
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(n, 1.0 / fs)

    # A floor no band could satisfy would return nothing at all; the widest
    # available band is always a legitimate answer, so never exclude it.
    floor = min(max(min_bandwidth_hz, 0.0), max(nyq - min_hz, 0.0))

    best: tuple[float, float] = (min_hz, nyq)
    best_k = -np.inf
    for level in range(max_level + 1):
        n_bands = 2 ** level
        bandwidth = nyq / n_bands
        if bandwidth < floor:
            break
        offsets = (0.0, 0.5 * bandwidth) if level else (0.0,)
        for offset in offsets:
            for i in range(n_bands):
                lo, hi = offset + i * bandwidth, offset + (i + 1) * bandwidth
                if hi > nyq + 1e-9:
                    continue
                lo = max(lo, min_hz)
                if hi - lo < max(floor, 1e-9):
                    continue
                mask = (freqs >= lo) & (freqs < hi)
                width = int(mask.sum())
                if width < 16:
                    continue
                # Taper the band edges rather than the time record. A window
                # over the whole record modulates it by its own shape, and the
                # kurtosis then reports the window: measured, a Hann window
                # added ~2.2 to EVERY band and buried the differences the
                # search exists to find.
                sub = spec[mask] * 2.0 * np.hanning(width + 2)[1:-1]
                k = spectral_kurtosis(np.abs(np.fft.ifft(sub)))
                if k is not None and k > best_k:
                    best_k, best = k, (float(lo), float(hi))

    if best_k == -np.inf:
        _log.debug("kurtogram found no scorable band; falling back to %s", best)
        return best, 0.0
    return best, float(best_k)


def envelope(x: np.ndarray, fs: float, lo: float, hi: float) -> np.ndarray:
    """Band-pass, then take the amplitude envelope (rectified demodulation).

    Done in the frequency domain: zeroing everything outside the band on the
    one-sided spectrum and inverting gives the band-passed signal, and its
    magnitude is a full-wave-rectified envelope. That is demodulation by
    rectification, not the analytic signal -- `irfft` reconstructs a REAL
    signal, so what comes back oscillates at the carrier rather than riding
    above it. It recovers the modulation correctly, which is why the order
    spectrum downstream is right, at the cost of carrier harmonics far above
    any order being read. Stated accurately here because the band SEARCH needs
    the true complex envelope and now computes one (`spectral_kurtosis`); the
    two steps demodulate differently and a reader should not have to guess
    which claim is the accurate one.
    """
    n = len(x)
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(n, 1.0 / fs)
    spec[(freqs < lo) | (freqs > hi)] = 0.0
    return np.abs(np.fft.irfft(spec, n=n)) * 2.0


def order_spectrum(
    env: np.ndarray, fs: float, rpm: float, *, spr: int = SAMPLES_PER_REV
) -> tuple[np.ndarray, np.ndarray]:
    """Resample the envelope to equal crank angle, then transform.

    With rpm known from the CAN bus there is no need for tacholess speed
    estimation. Speed is treated as constant across the window, which holds
    because the window is short -- and because the alternative, integrating
    instantaneous rpm, needs a rate this bus does not carry.
    """
    duration = len(env) / fs
    revs = duration * rpm / 60.0
    if revs < 2:
        return np.array([]), np.array([])

    n_out = int(revs * spr)
    t_in = np.arange(len(env)) / fs
    t_out = np.linspace(0.0, duration, n_out, endpoint=False)
    resampled = np.interp(t_out, t_in, env)
    resampled = resampled - resampled.mean()

    win = np.hanning(len(resampled))
    mag = np.abs(np.fft.rfft(resampled * win)) / (len(resampled) / 2.0)
    orders = np.fft.rfftfreq(len(resampled), 1.0 / spr)
    return orders, mag


def analyse(
    x: np.ndarray,
    fs: float,
    rpm: float,
    engine: dict,
    *,
    tolerance_orders: float | None = None,
) -> OrderAnalysis:
    """The whole chain: find the band, demodulate, order-transform, read peaks.

    Amplitudes are RELATIVE to the median of the order spectrum, so a peak of
    6.0 means six times the surrounding floor. An absolute acceleration would
    depend on sensor mounting and gain and could not be compared between
    installations or against a threshold.
    """
    out = OrderAnalysis(rpm=rpm)
    if rpm <= 0 or len(x) < 64:
        out.reason = "no usable window"
        return out

    duration = len(x) / fs
    out.revolutions = duration * rpm / 60.0
    if out.revolutions < 2:
        out.reason = f"window covers only {out.revolutions:.1f} revolutions"
        return out

    out.order_resolution = 1.0 / out.revolutions
    if out.revolutions < MIN_REVOLUTIONS - 0.5:
        # Reported, not refused: the spectrum is still computed, but a caller
        # plotting a BPFO peak from 13 revolutions is reading a bin that also
        # contains the 3.5x structural order.
        out.reason = (
            f"{out.revolutions:.0f} revolutions gives {out.order_resolution:.3f} "
            f"order resolution; {MIN_REVOLUTIONS} revolutions "
            f"({required_duration_s(rpm):.1f} s at {rpm:.0f} rpm) are needed to "
            f"separate a defect order from the nearest structural one"
        )

    # Two bins either side of the target: wide enough for a small speed
    # drift within the window, narrow enough not to sweep in a neighbour.
    if tolerance_orders is None:
        tolerance_orders = 2.0 * out.order_resolution

    # The band must be wide enough to demodulate the FASTEST defect we intend
    # to read -- BPFI here -- or the search scores bands that cannot express
    # the modulation. Derived per call, so it tracks speed instead of assuming
    # one; this is what the fixed-width version could not do.
    fastest_defect_hz = max(bearing_orders(engine).values()) * rpm / 60.0
    out.band_hz, out.band_kurtosis = kurtogram_band(
        x, fs, min_bandwidth_hz=DEMOD_BANDWIDTH_MARGIN * fastest_defect_hz
    )
    env = envelope(x, fs, *out.band_hz)
    orders, mag = order_spectrum(env, fs, rpm)
    if orders.size == 0:
        out.reason = out.reason or "order spectrum empty"
        return out

    wanted = bearing_orders(engine)
    wanted["GMF"] = float(engine["vibration"]["reduction_gear_teeth"])
    wanted["FIRING"] = int(engine["geometry"]["cylinders"]) / 2.0

    # A peak is scored against its LOCAL neighbourhood, not the global median.
    # The first version used the median of the whole spectrum, and the envelope
    # spectrum of a heavily modulated engine sits far above that everywhere --
    # so every order scored 15-28x and a HEALTHY bearing was diagnosed with
    # four simultaneous defects. A defect is a peak that stands above what
    # surrounds it, which is a local question.
    for name, order in wanted.items():
        peak_sel = np.abs(orders - order) <= tolerance_orders
        near_sel = (np.abs(orders - order) <= 0.5) & ~peak_sel
        if not peak_sel.any() or near_sel.sum() < 4:
            continue
        local = float(np.median(mag[near_sel]))
        if local <= 1e-12:
            continue
        out.peaks[name] = float(mag[peak_sel].max() / local)

    body = mag.copy()
    body[orders < 0.4] = 0.0          # ignore the DC shoulder
    out.dominant_frequency_hz = float(orders[int(np.argmax(body))] * rpm / 60.0)
    out.resolved = out.revolutions >= MIN_REVOLUTIONS - 0.5
    if out.resolved:
        out.reason = "resolved"
    return out


def diagnose(a: OrderAnalysis, *, ratio: float = 4.0) -> list[str]:
    """Name the defect, or say nothing.

    A bearing order standing well clear of the envelope floor is a bearing
    defect. The structural orders are the engine running normally and are
    never reported as findings.
    """
    labels = (("BPFO", "bearing outer race"), ("BPFI", "bearing inner race"),
              ("BSF", "rolling element"), ("FTF", "bearing cage"))
    return [
        f"{label} defect ({name} {a.peaks[name]:.1f}x envelope floor)"
        for name, label in labels
        if a.peaks.get(name, 0.0) >= ratio
    ]
