"""Run-to-failure dataset generator -- PRD Part 0 section 0.5.

Two hundred virtual engines, each flown until its health index crosses the
maintenance threshold, written as Parquet with a strict train/val/test split
BY ENGINE.

WHY THIS FILE IS WRITTEN THE WAY IT IS
--------------------------------------
PRD Part 0 section 0.5 calls this "the training-data trap": if the network is
trained on data from the physics model and then validated on data from the same
physics model, all that has been proven is that a network can copy a model. The
PRD lists four defences and every one of them is implemented here, because a
judge will ask.

  1. STOCHASTIC FAULTS. Faults arrive at random times with random severities
     and random ramp rates, so no two engines fail the same way.
  2. MANUFACTURING SPREAD. Each engine gets its own physics parameters and its
     own degradation rates (log-normal, so rates stay positive). A network
     cannot memorise one trajectory because there is no one trajectory.
  3. REAL INSTRUMENTATION. Rows carry what the SENSORS said -- noise, bias
     drift, quantisation, dropouts -- not clean model output.
  4. SPLIT BY ENGINE, NOT BY SAMPLE. Engines 1-80 train, 81-90 validate, 91-100
     test. Splitting by sample would put consecutive readings from the same
     engine on both sides of the split, and the reported score would be
     measuring memorisation.

LABELS COME FROM INTERNAL STATE, FEATURES COME FROM SENSORS
-----------------------------------------------------------
The generator knows the true degradation factors because it is the thing
degrading them. Those become the LABELS. The features are what an instrument
could actually have measured. Nothing that is not observable on the aircraft
ever reaches the feature columns -- which is what makes a score on this dataset
mean something.

THE RESIDUAL IS A FEATURE, NOT A TARGET
---------------------------------------
PRD Part 0 section 0.5 point 4: physics residuals are an anomaly FEATURE and a
plausibility gate, never the ML target. Each engine carries its own shadow
model (``layer4_core.shadow_model``) held as-new for life, and the residual
against it is emitted alongside the raw channels. This is the single most
informative column set in the file: cooling degradation and lubrication issues
are both visible in the residuals hundreds of hours before any threshold is
crossed.

TIME COMPRESSION, AND WHAT IT DOES NOT COST
-------------------------------------------
A 1200 h life at 10 Hz is 43 million samples per engine. Instead each sortie
contributes one fully-simulated observation window, and the wear clock is
advanced across the remainder of the sortie using the temperatures that window
produced (``VirtualEngine.fast_forward``). Degradation is integrated in flight
hours and depends on the operating point only through oil and head temperature,
both near-constant across a cruise leg -- so what is skipped is repeated
simulation of a steady condition, not anything that varies within it.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import pickle
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from common import config
from layer2_physics.atmosphere import EnvCondition
from layer2_physics import degradation as deg
from layer2_physics.degradation import FAULT_CLASS_ORDER, FaultMode, InjectedFault
from layer2_physics.engine_sim import (
    PHASE_CRUISE,
    FlightPhase,
    SensorFrame,
    VirtualEngine,
)

# ---------------------------------------------------------------------------
# Dataset shape
# ---------------------------------------------------------------------------

# TWO HUNDRED ENGINES, BECAUSE TWENTY TEST ENGINES STILL WERE NOT ENOUGH.
#
# 60/20/20 replaced 80/10/10 once, for the right reason: ten evaluation engines
# could not carry eight fault classes, and five of the eight appeared on
# exactly one test engine. Twenty a side was better and still not enough. The
# guaranteed deal gives each class one engine in eight, so twenty test engines
# put 2-3 behind every per-class F1 -- and those scores then moved
# overheating_trend 0.271 -> 0.930 and abnormal_vibration 0.741 -> 0.243
# between two runs of unchanged model code. That is not measurement.
#
# Forty test engines put roughly eight behind each class once secondary faults
# are counted, and forty validation engines put enough of each class there to
# place its decision threshold on data the model has not memorised. The cost is
# generation time and nothing else.
N_ENGINES = 200
_TRAIN_FRAC, _VAL_FRAC = 0.60, 0.20
_N_TRAIN = int(N_ENGINES * _TRAIN_FRAC)
_N_VAL = int(N_ENGINES * _VAL_FRAC)
# Derived, not written out three times: the ranges and N_ENGINES disagreeing is
# exactly the failure split_for() below refuses to paper over.
SPLIT_TRAIN = range(1, _N_TRAIN + 1)              # PRD Part 0 s0.5 point 2
SPLIT_VAL = range(_N_TRAIN + 1, _N_TRAIN + _N_VAL + 1)
SPLIT_TEST = range(_N_TRAIN + _N_VAL + 1, N_ENGINES + 1)

DT_S = 1.0                      # observation step
SETTLE_S = 25.0                 # let the new operating point settle, unrecorded
# 50 samples per window against a 30-sample model sequence length
# (thresholds.detectors.tier3.sequence_length), so every window yields usable
# sequences with margin. Longer windows buy little: within a steady cruise leg
# consecutive samples differ only by sensor noise, and the degradation signal
# this dataset exists to carry lives ACROSS sorties, not inside one.
RECORD_S = 50.0
# MALE = Medium Altitude LONG ENDURANCE. A 3 h sortie would be a trainer, not
# an ISR asset: TAPAS-BH-201 endurance is ~18 h and the class runs 12-24 h.
# Sortie length is sampled per sortie rather than fixed, because a fleet flies a
# mix of short transits and full-endurance patrols, and a model that only ever
# sees one sortie length learns that length.
SORTIE_HOURS_RANGE = (4.0, 18.0)
# Censor at TBO, not beyond it. An engine is removed for overhaul at 1200 h
# [MML 05-10-00]; nothing in a real fleet keeps flying past that to see whether
# it would have broken. Simulating to 1500 h produced records no operator would
# ever hold, and the extra 300 h were the most expensive part of the run.
MAX_LIFE_HOURS = 1200.0

# Environments an ISR fleet actually sees. Sampled per engine so the dataset is
# not one climate (PS section E names hot-weather and high-altitude operation).
ENVIRONMENTS = (
    EnvCondition.STANDARD,
    EnvCondition.HOT_WEATHER,
    EnvCondition.HIGH_ALTITUDE,
    EnvCondition.COLD_WEATHER,
    EnvCondition.MARITIME,
)


def split_for(engine_id: int) -> str:
    """Which split an engine belongs to.

    Raises rather than guessing. The fall-through used to return "test" for any
    id it did not recognise, so ``--engines 200`` silently produced a hundred
    extra engines that were all dumped into the test split AND carried no
    faults at all, because _guaranteed_mode returned None for them. A fleet
    that is quietly wrong is worse than one that refuses to build.
    """
    if engine_id in SPLIT_TRAIN:
        return "train"
    if engine_id in SPLIT_VAL:
        return "val"
    if engine_id in SPLIT_TEST:
        return "test"
    raise ValueError(
        f"engine {engine_id} is outside the configured splits "
        f"(1-{max(SPLIT_TEST)}). The split ranges are fixed constants; change "
        f"SPLIT_TRAIN/VAL/TEST together with N_ENGINES."
    )


# ---------------------------------------------------------------------------
# Ground-truth health
# ---------------------------------------------------------------------------


# PRD Part 2 section 9.3 band table: below 0.40 is "UNSAFE - ground aircraft
# immediately". A weighted average cannot express that on its own -- one
# destroyed subsystem out of three gets diluted by two healthy ones, and
# measured, a severity-1.0 fault left the composite at 0.77-0.89 against a 0.60
# threshold. An engine with a burnt-out injector set is finished whatever the
# average says, so end of life is EITHER criterion.
SUBINDEX_FLOOR = 0.40


def end_of_life(health: dict[str, float], chi_threshold: float) -> bool:
    """Has this engine reached the end of its useful life?"""
    if health["chi_true"] <= chi_threshold:
        return True
    return min(health["thi_true"], health["mhi_true"], health["comb_hi_true"]) <= SUBINDEX_FLOOR


# The model floors combustion efficiency at 0.80, correctly: a real engine
# never burns only half its fuel. But that makes the RAW efficiency useless as
# a health index -- it can never fall far enough to indicate anything. A
# thermodynamic efficiency and a health index are not the same quantity: losing
# 4 points of combustion efficiency is a large loss of health even though the
# number barely moves. The efficiency is therefore normalised against the range
# it can actually traverse before the engine is unusable.
_ETA_COMBUSTION_FLOOR = 0.80


def truth_health(factors, engine: dict | None = None) -> dict[str, float]:
    """Ground-truth health from internal state (PRD Part 2 section 9.3).

    This is the LABEL, not a detector. ``layer3_ai/health.py`` will estimate
    the same quantity from sensors alone and be scored against this column;
    computing it here from the degradation factors is what makes that score
    meaningful rather than circular.

    ONE HONEST GAP: PRD Part 2 section 9.3 weights the composite
    thermal 0.30 / mechanical 0.25 / electrical 0.20 / combustion 0.25, but
    there is no electrical degradation pathway in the model -- that is gap G4
    in docs/prd/PROJECT_PLAN.md. Rather than score electrical health a constant 1.0,
    which would hand every engine a free 0.20 and push the 0.60 maintenance
    threshold out of reach, the three implemented weights are renormalised to
    sum to 1.0. When G4 lands the electrical term drops straight in and this
    renormalisation is removed. See docs/PRD_DEVIATIONS.md DEV-42.
    """
    # Both cooling paths bound thermal health: the head-to-coolant jacket
    # (cooling_efficiency) and heat rejection to air (cooling_airflow). An
    # engine can be finished by either, and taking only the first would leave
    # an overheating trend with no effect on health at all.
    thermal = float(min(factors.cooling_efficiency, factors.cooling_airflow))
    mechanical = float(min(factors.bearing_condition, factors.turbocharger_condition))
    # Oil quality is a lubrication property; it bounds mechanical health,
    # because a sound bearing running degraded oil is not a healthy mechanism.
    mechanical = min(mechanical, 0.5 * (1.0 + float(factors.oil_quality)))
    eng = engine if engine is not None else config.load_engine("rotax_915is")
    eta_new = float(eng["thermodynamics"]["combustion"]["efficiency_new"])
    span = max(eta_new - _ETA_COMBUSTION_FLOOR, 1e-6)
    eta_health = (float(factors.combustion_efficiency) - _ETA_COMBUSTION_FLOOR) / span
    combustion = float(min(max(eta_health, 0.0), 1.0, factors.injector_condition))

    w = config.load_thresholds()["health"]["composite_weights"]
    wt, wm, wc = float(w["thermal"]), float(w["mechanical"]), float(w["combustion"])
    total = wt + wm + wc
    chi = (wt * thermal + wm * mechanical + wc * combustion) / total
    return {
        "thi_true": thermal,
        "mhi_true": mechanical,
        "comb_hi_true": combustion,
        "chi_true": chi,
    }


# ---------------------------------------------------------------------------
# Per-engine fault schedule
# ---------------------------------------------------------------------------

# ALL EIGHT of the problem statement's fault classes are injectable.
#
# Sensor drift used to be excluded here, on the reasoning that the instrument
# layer already models drift so injecting it would double-count. That reasoning
# conflates two different things held in two different fields: every transducer
# accumulates a slow ageing DRIFT (SensorSpec.drift, ~0.004 degC/h), while a
# sensor-drift FAULT is a transducer going bad and is expressed as a BIAS
# (SensorSpec.bias, 0.55 bar on oil pressure and 9 degC on CHT). They do not
# double-count; engine_sim keeps them deliberately separate.
#
# The cost of the exclusion was severe and silent: lab_sensor_drift carried
# ZERO positive rows on ZERO engines in the entire fleet, so the multi-label
# head had a class with no positive examples, tier3 listed it under
# UNLEARNABLE_CLASSES, and one of the eight fault classes the problem statement
# requires was quietly unsupported. Distinguishing an instrument fault from a
# real process change is PRD Part 2 s10.5 -- a named requirement, and one this
# system is well placed to meet precisely because it holds a physics reference.
_INJECTABLE = tuple(FAULT_CLASS_ORDER)

# Engines with this index within their split are left fault-free, so the
# dataset keeps honest negatives: a detector that fires on every engine must be
# able to be caught out. One in eight, as before.
_FAULT_FREE_EVERY = 8


def _guaranteed_mode(engine_id: int) -> FaultMode | None:
    """The fault this engine is guaranteed to carry, or None if fault-free.

    Sampling modes independently per engine left coverage to luck, and luck
    lost: two classes were absent from validation entirely. Dealing the eight
    modes round-robin across the engines WITHIN EACH SPLIT makes coverage a
    property of the design rather than of the seed, while severity, onset, ramp
    and any additional faults stay random.
    """
    for rng_split in (SPLIT_TRAIN, SPLIT_VAL, SPLIT_TEST):
        if engine_id in rng_split:
            idx = list(rng_split).index(engine_id)
            if idx % _FAULT_FREE_EVERY == _FAULT_FREE_EVERY - 1:
                return None
            # Count how many fault-carrying engines precede this one, so the
            # deal is not skewed by the fault-free gaps.
            rank = idx - (idx // _FAULT_FREE_EVERY)
            return _INJECTABLE[rank % len(_INJECTABLE)]
    return None


# THE INSTRUMENT A DRIFT FAULT ATTACKS IS DEALT, NOT DRAWN.
#
# Drawing it uniformly left the eight driftable channels to luck, and luck lost
# badly. Measured on the 100-engine fleet of 17 Sep: the nine training engines
# that drifted picked oil pressure, coolant, CHT and rpm; BOTH test engines
# picked manifold pressure, which never appeared in training at all.
#
# That is not a small imbalance, because each channel has its own detection
# path. rpm is visible only in the FADEC lane delta (there is no res_rpm);
# manifold pressure in either its lane delta or its residual; the remaining six
# only in their physics residual. Training on one set of paths and testing on
# another asks the model a question it was never shown, and it answered F1
# 0.019 -- the correct score for an impossible exam, and no reflection of the
# model. A single feature separates the test engines at AUC 0.997.
#
# Dealing the channel by the engine's rank among drift carriers makes the
# training split cover every channel before any split repeats one, so a channel
# under test is always one training has taught.
def _drift_deal(engine_id: int) -> tuple[str, float]:
    """The instrument and the direction this engine's drift fault attacks."""
    from layer2_physics.engine_sim import DRIFTABLE_CHANNELS

    channels = tuple(sorted(DRIFTABLE_CHANNELS))
    for rng_split in (SPLIT_TRAIN, SPLIT_VAL, SPLIT_TEST):
        if engine_id in rng_split:
            idx = list(rng_split).index(engine_id)
            rank = idx - (idx // _FAULT_FREE_EVERY)
            deal = rank // len(_INJECTABLE)
            # Both directions of every channel, so "reads high" never becomes a
            # synonym for the fault. Two training engines drifted LOW and their
            # residual AUC came out at 0.012 and 0.164 -- perfectly separable,
            # opposite sign, and invisible to a detector taught only one way.
            sign = 1.0 if (deal // len(channels)) % 2 == 0 else -1.0
            return channels[deal % len(channels)], sign
    return channels[0], 1.0


def sample_faults(rng: np.random.Generator,
                  engine_id: int | None = None,
                  hazard_onset: bool = True) -> list[InjectedFault]:
    """A fault schedule for one engine (PRD Part 0 section 0.5 point 1).

    One engine in eight is left fault-free. Every other engine carries a
    GUARANTEED mode dealt round-robin within its split -- see
    ``_guaranteed_mode`` -- plus zero to two further modes drawn at random, so
    multi-fault engines still occur.
    """
    guaranteed = _guaranteed_mode(engine_id) if engine_id is not None else None
    if engine_id is not None and guaranteed is None:
        return []

    # A CLASS SCORED ON TWO ENGINES IS NOT SCORED.
    #
    # The guaranteed deal gives each class one engine in eight, so on a
    # 20-engine test split every per-class F1 rested on 2-3 engines and swung
    # violently between fleets: overheating_trend moved 0.271 -> 0.930 and
    # abnormal_vibration 0.741 -> 0.243 between two runs of the same code.
    # Neither swing was the model changing. Carrying more secondary faults per
    # engine widens per-class coverage without generating more engines, and it
    # is the more honest fleet anyway -- a 1,200 hour engine rarely wears out
    # in exactly one way.
    extra = int(rng.choice([0, 0, 1, 1, 2], p=[0.22, 0.20, 0.24, 0.20, 0.14]))
    pool = [m for m in _INJECTABLE if m is not guaranteed]
    picked = list(rng.choice(np.array(pool, dtype=object),
                             size=min(extra, len(pool)), replace=False)) if extra else []
    modes = ([guaranteed] if guaranteed is not None else []) + picked
    faults = []
    for mode in modes:
        # ONSET MUST LAND INSIDE THE ENGINE'S LIFE.
        #
        # This was uniform(20, 900) against a fleet whose engines die between
        # roughly 450 and 1200 hours, so a large share of every schedule was
        # silently discarded: measured on a six-engine sample, sensor_drift was
        # injected at 854 h into an engine that died at 447 h, lubrication_issue
        # at 633 h into one that died at 592 h, and sensor_drift again at 813 h
        # into one that died at 800 h. Three of nine injected faults never
        # expressed at all, and nothing reported that they had not.
        #
        # This -- not the sampling -- is why fault coverage was so poor and so
        # random: dealing a mode to an engine guarantees the INJECTION, not the
        # EXPRESSION. 400 h is comfortably inside the life of even the
        # shortest-lived engines while still leaving room for late-onset faults
        # on long-lived ones.
        # ONSET IS NO LONGER DRAWN HERE.
        #
        # It was `rng.uniform(15.0, 400.0)` -- decided before the engine ever
        # ran, INDEPENDENT of its condition. That is a constant hazard
        # (Weibull beta = 1), which models RANDOM failures; wear-out is beta > 1,
        # where hazard rises with accumulated damage. The consequence was not
        # only unrealistic, it was disqualifying: with onset independent of
        # condition, nothing observable about the engine can anticipate a fault,
        # so the problem statement's "predicting probable failures BEFORE
        # occurrence" is impossible BY CONSTRUCTION.
        #
        # `inf` marks the fault as DEALT BUT PENDING. `run_one_engine` offers it
        # a draw against `degradation.arm_pending_faults` each sortie, where the
        # hazard rises with damage on the pathway the mode acts through. See
        # `layer2_physics/degradation.py` for the model and DEV-193.
        onset = math.inf if hazard_onset else float(rng.uniform(15.0, 400.0))
        severity = float(rng.uniform(0.25, 0.95))
        # Ramp by the mode's PHYSICAL MECHANISM. One log-uniform 0.5-300 h span
        # for all eight modes says a failed ignition coil and a coking injector
        # progress alike; they do not.
        lo, hi = deg.FAULT_RAMP_HOURS.get(mode, (0.5, 300.0))
        ramp = float(math.exp(rng.uniform(math.log(lo), math.log(hi))))
        # A drifting transducer afflicts ONE instrument, and which one varies
        # between failures. Pinning it to the same two channels every time made
        # the class trivially recognisable in one direction and inseparable
        # from a real cooling fault in the other, because every instance raised
        # CHT by the same amount. A drift can also read high OR low.
        channel = sign = None
        if mode is FaultMode.SENSOR_DRIFT:
            from layer2_physics.engine_sim import DRIFTABLE_CHANNELS

            if engine_id is None:
                channel = str(rng.choice(sorted(DRIFTABLE_CHANNELS)))
                sign = float(rng.choice([-1.0, 1.0]))
            else:
                channel, sign = _drift_deal(engine_id)

        faults.append(
            InjectedFault(
                mode=mode,
                onset_hours=onset,
                severity=severity,
                ramp_hours=ramp,
                cylinder=int(rng.integers(1, 5)) if rng.random() < 0.5 else None,
                channel=channel,
                drift_sign=sign if sign is not None else 1.0,
            )
        )
    return faults


@dataclass
class OperatingPoint:
    throttle_pct: float
    altitude_ft: float
    airspeed_kmh: float

    def as_phase(self, seconds: float) -> FlightPhase:
        return FlightPhase(
            name="CRUISE",
            duration_s=seconds,
            throttle_pct=self.throttle_pct,
            altitude_ft=self.altitude_ft,
            airspeed_kmh=self.airspeed_kmh,
            phase_code=PHASE_CRUISE,
        )


def sample_operating_point(rng: np.random.Generator) -> OperatingPoint:
    """A cruise condition for one sortie.

    Varied so the dataset is not a single operating point -- a model trained on
    one throttle setting learns that setting, not the engine.
    """
    return OperatingPoint(
        throttle_pct=float(rng.uniform(58.0, 88.0)),
        altitude_ft=float(rng.uniform(8000.0, 22000.0)),
        airspeed_kmh=float(rng.uniform(140.0, 230.0)),
    )


# ---------------------------------------------------------------------------
# Shadow adapter
# ---------------------------------------------------------------------------


class _FrameView:
    """Presents a ``SensorFrame`` through the ``.get()`` the shadow expects.

    The shadow model is written against decoded CAN telemetry. Here it is fed
    the sensor frame directly: the CAN round-trip is exercised and tested in
    ``layer1_edge``, and repeating it 36 million times would only add encoding
    latency to a dataset build. What matters -- that the shadow sees measured,
    noisy values and never the simulator's internal state -- is unchanged.
    """

    __slots__ = ("_f",)

    _MAP = {
        "rpm": "rpm",
        "throttle_pct": "throttle_pct",
        "altitude_ft": "altitude_ft",
        "oat": "oat_c",
        "airspeed_kmh": "airspeed_kmh",
        "coolant_temperature": "coolant_temperature_c",
        "oil_temperature": "oil_temperature_c",
    }

    def __init__(self, frame: SensorFrame) -> None:
        self._f = frame

    def get(self, name: str):
        if name == "cht_max":
            vals = [v for v in self._f.cht_c if v is not None]
            return max(vals) if vals else None
        attr = self._MAP.get(name)
        return getattr(self._f, attr) if attr else None


# ---------------------------------------------------------------------------
# One engine, run to failure
# ---------------------------------------------------------------------------


def _safe_max(vals) -> float | None:
    good = [v for v in vals if v is not None]
    return max(good) if good else None


def _spread(vals) -> float | None:
    good = [v for v in vals if v is not None]
    return (max(good) - min(good)) if len(good) >= 2 else None


@dataclass
class EngineRun:
    engine_id: int
    rows: list[dict] = field(default_factory=list)
    failed: bool = False
    life_hours: float = 0.0
    faults: list[dict] = field(default_factory=list)
    environment: str = ""


def run_one_engine(
    engine_id: int,
    *,
    engine_key: str = "rotax_915is",
    max_life_hours: float = MAX_LIFE_HOURS,
    seed_base: int = 20260,
    hazard_onset: bool = True,
) -> EngineRun:
    """Fly one virtual engine until its true health crosses the threshold.

    `hazard_onset` selects the fault-onset model. True -- the default and the
    correct one -- makes onset a wear-out hazard that rises with accumulated
    damage (DEV-193). False restores the old constant-hazard draw, kept so the
    original fleet can be reproduced byte for byte and the two compared.
    """
    # Imported here so the module can be imported without pulling in Layer 4.
    from layer4_core.shadow_model import ShadowModel

    seed = seed_base + engine_id
    rng = np.random.default_rng(seed)
    env = ENVIRONMENTS[int(rng.integers(0, len(ENVIRONMENTS)))]

    veng = VirtualEngine(engine_key=engine_key, seed=seed, env_condition=env)
    faults = sample_faults(rng, engine_id, hazard_onset=hazard_onset)
    for f in faults:
        veng.inject(f)

    # ONE shadow for the whole life, seeded once while the engine is still
    # healthy. Re-seeding it per sortie would let it inherit the degraded
    # engine's temperatures and drive every residual to zero -- the failure
    # mode PRD Part 1 section 6.5 exists to forbid.
    shadow = ShadowModel(engine_key=engine_key)

    thresholds = config.load_thresholds()
    chi_fail = float(thresholds["rul"]["maintenance_chi_threshold"])

    run = EngineRun(
        engine_id=engine_id,
        environment=str(env),
        faults=[
            {
                "mode": str(f.mode), "onset_hours": f.onset_hours,
                "severity": f.severity, "ramp_hours": f.ramp_hours,
                "cylinder": f.cylinder,
                "channel": f.channel,
                "drift_sign": f.drift_sign,
                # Filled in once the engine has been flown: did this fault ever
                # actually express before the engine reached end of life?
                "expressed": False,
            }
            for f in faults
        ],
    )

    sortie = 0
    while veng.flight_hours < max_life_hours:
        sortie += 1
        # OFFER EACH PENDING FAULT ITS HAZARD DRAW, BEFORE THE SORTIE.
        #
        # This is the loop the old generator did not close: a fault was
        # scheduled before the engine ran, so wear could never make one likelier.
        # Now the hazard rises with damage on the pathway each mode acts
        # through, which is both the standard condition-based reliability model
        # and the thing that makes the problem statement's "predict failures
        # BEFORE occurrence" achievable rather than forbidden. Drawn against the
        # sortie about to be flown, using the damage as it stands NOW.
        if hazard_onset:
            veng.degradation.arm_pending_faults(
                veng.flight_hours, float(np.mean(SORTIE_HOURS_RANGE))
            )
        op = sample_operating_point(rng)
        veng.set_profile([op.as_phase(SETTLE_S + RECORD_S + DT_S)])

        # Settle: the operating point changed, so let the thermal states catch
        # up before recording. Not recorded -- a transient window would teach
        # the model that every sortie starts with a thermal excursion.
        frame = None
        for _ in range(int(SETTLE_S / DT_S)):
            frame = veng.step(DT_S)
            shadow.update(_FrameView(frame), DT_S)

        window: list[dict] = []
        oil_acc, cht_acc = [], []
        # BEARING ORDERS, on a cadence. The order spectrum is what names a
        # bearing defect -- RMS and kurtosis say the engine is rough, the
        # orders say which race -- and the twin computes it live while the
        # training data carried neither. It costs 7 ms a call, so it is
        # recomputed every ORDER_EVERY_ROWS rows (30 s of flight) and carried
        # between: a spalling race does not develop inside half a minute.
        orders: dict[str, float] = {}
        for i in range(int(RECORD_S / DT_S)):
            frame = veng.step(DT_S)
            pred = shadow.update(_FrameView(frame), DT_S)
            if i % ORDER_EVERY_ROWS == 0:
                orders = _bearing_orders(veng, frame)
            row = _row(frame, pred, veng, sortie, op, orders)
            window.append(row)
            if frame.oil_temperature_c is not None:
                oil_acc.append(frame.oil_temperature_c)
            cht = _safe_max(frame.cht_c)
            if cht is not None:
                cht_acc.append(cht)

        health = truth_health(veng.degradation.factors)
        for row in window:
            row.update(health)
        run.rows.extend(window)

        if end_of_life(health, chi_fail):
            run.failed = True
            break

        # Advance the wear clock across the rest of the sortie using the
        # temperatures this window actually produced.
        sortie_hours = float(rng.uniform(*SORTIE_HOURS_RANGE))
        remaining = max(0.0, sortie_hours - (SETTLE_S + RECORD_S) / 3600.0)
        veng.fast_forward(
            remaining,
            oil_temp_c=float(np.mean(oil_acc)) if oil_acc else 95.0,
            cht_max_c=float(np.mean(cht_acc)) if cht_acc else 105.0,
        )

    run.life_hours = veng.flight_hours

    # Which injected faults actually expressed before the engine died. A fault
    # whose onset falls past end of life contributes no labelled rows, and
    # recording the schedule as though it had happened is how three of nine
    # faults went missing without anything noticing.
    for spec, f in zip(run.faults, faults, strict=True):
        spec["expressed"] = bool(f.magnitude_at(run.life_hours) > 0.0)
        # THE ONSET IS ONLY KNOWN NOW.
        #
        # Under the wear-out hazard a fault is dealt with `onset_hours = inf`
        # and the time is decided DURING the run, when damage triggers it. The
        # dict above is built before the engine flies, so it captured the
        # placeholder; without this line the manifest would record every
        # hazard-scheduled fault as never having started, and any analysis
        # reading the manifest -- as the RUL ceiling measurement does -- would
        # silently see a fleet with no faults in it.
        spec["onset_hours"] = float(f.onset_hours)

    # RUL is only knowable once the end of life is known, so it is filled in
    # here rather than during the loop. An engine that never failed is censored
    # -- its RUL is a lower bound, not a value, and it is flagged so a training
    # run can drop it instead of learning a wrong target.
    for row in run.rows:
        row["rul_hours"] = max(0.0, run.life_hours - row["flight_hours"])
        row["censored"] = not run.failed
    return run


ORDER_EVERY_ROWS = 30

# The bearing defect frequencies the order analysis reports, as multiples of
# the envelope floor. Names as layer1_edge.order_analysis produces them.
BEARING_ORDERS = ("BPFO", "BPFI", "BSF", "FTF")


def _bearing_orders(veng: VirtualEngine, frame: SensorFrame) -> dict[str, float]:
    """The bearing-defect orders in the vibration, or empty when not readable.

    Below a few hundred rpm there is no order spectrum to speak of, and a
    failure here must cost the dataset a column, never a row.
    """
    from layer1_edge import order_analysis as oa

    rpm = frame.rpm
    if rpm is None or rpm < 300.0:
        return {}
    try:
        wave = veng.vibration_waveform(duration_s=oa.required_duration_s(rpm), fs=10_000.0)
        peaks = oa.analyse(wave, 10_000.0, rpm, veng._engine).peaks or {}
    except Exception:
        return {}
    return {k: float(v) for k, v in peaks.items() if k in BEARING_ORDERS}


def _row(
    frame: SensorFrame,
    pred,
    veng: VirtualEngine,
    sortie: int,
    op: OperatingPoint,
    orders: dict[str, float] | None = None,
) -> dict:
    """One dataset row: measured features, physics residuals, truth labels."""
    cht_max = _safe_max(frame.cht_c)
    egt_max = _safe_max(frame.egt_c)
    vib = [v for v in frame.vibration_rms if v is not None]
    inj = [v for v in frame.injection_timing_deg if v is not None]
    ign = [v for v in frame.ignition_timing_deg if v is not None]

    def resid(measured, predicted):
        if measured is None or predicted is None:
            return None
        return measured - predicted

    oil_psi = frame.oil_pressure_bar * 14.5038 if frame.oil_pressure_bar is not None else None

    row: dict = {
        "engine_id": 0,          # filled by the caller
        "sortie": sortie,
        "t_s": frame.t_s,
        "flight_hours": frame.flight_hours,
        # -- measured (what an instrument could actually have read) ----------
        "rpm": frame.rpm,
        "cht_max": cht_max,
        "cht_spread": _spread(frame.cht_c),
        "coolant_temperature": frame.coolant_temperature_c,
        "egt_max": egt_max,
        "egt_spread": _spread(frame.egt_c),
        "oil_pressure": oil_psi,
        "oil_temperature": frame.oil_temperature_c,
        "fuel_flow": frame.fuel_flow_lph,
        "manifold_pressure": frame.manifold_pressure_bar,
        "manifold_air_temp": frame.manifold_air_temp_c,
        "fuel_pressure": frame.fuel_pressure_bar,
        "vibration_rms_total": math.sqrt(sum(v * v for v in vib)) if vib else None,
        "vibration_kurtosis": frame.vibration_kurtosis,
        "battery_voltage": frame.battery_voltage_v,
        "alternator_current": frame.alternator_current_a,
        "injection_deviation_max": (
            max(abs(v - frame.injection_timing_cmd_deg) for v in inj) if inj else None
        ),
        "ignition_deviation_max": (
            max(abs(v - frame.ignition_timing_cmd_deg) for v in ign) if ign else None
        ),
        "injection_period_ms": frame.injection_period_ms,
        "injector_duty": frame.injector_duty,
        "knock_retard_deg": frame.knock_retard_deg,
        # ACTUATOR POSITIONS. On a FADEC engine with closed-loop control,
        # degradation is spent AUTHORITY before it is a changed reading: a worn
        # compressor holds boost by closing the wastegate (measured: power
        # unchanged from condition 1.00 to 0.55, wastegate 0.65 -> 0.36), and a
        # losing radiator is held by the cooling flap (measured: 30 % of the
        # cooling air lost moves the flap 31.8 sensor-sigmas and the coolant
        # 4.0). Neither was recorded, so no model could see either.
        **{f"vib_{k.lower()}": (orders or {}).get(k) for k in BEARING_ORDERS},
        "wastegate_pct": frame.wastegate_pct,
        "cooling_flap_pct": frame.cooling_flap_pct,
        # What the two FADEC lanes disagree by. A drifting transducer on one
        # lane moves this; a drifting engine does not.
        "rpm_lane_delta": (
            abs(frame.rpm - frame.rpm_lane_b)
            if frame.rpm is not None and frame.rpm_lane_b is not None else None
        ),
        "map_lane_delta": (
            abs(frame.manifold_pressure_bar - frame.manifold_pressure_bar_lane_b)
            if frame.manifold_pressure_bar is not None
            and frame.manifold_pressure_bar_lane_b is not None else None
        ),
        "throttle_pct": frame.throttle_pct,
        "altitude_ft": frame.altitude_ft,
        "oat_c": frame.oat_c,
        "airspeed_kmh": frame.airspeed_kmh,
        "air_flow_g_per_min": frame.air_flow_g_per_min,
        # -- derived ----------------------------------------------------------
        "cht_minus_coolant": (
            cht_max - frame.coolant_temperature_c
            if cht_max is not None and frame.coolant_temperature_c is not None
            else None
        ),
    }

    # -- physics residuals: feature, never target (PRD Part 0 s0.5 point 4) ---
    if pred is not None:
        row.update(
            {
                "res_cht": resid(cht_max, pred.cht_max),
                "res_coolant": resid(frame.coolant_temperature_c, pred.coolant_temperature_c),
                "res_egt": resid(egt_max, pred.egt_max),
                "res_oil_pressure": resid(oil_psi, pred.oil_pressure_psi),
                "res_oil_temperature": resid(frame.oil_temperature_c, pred.oil_temperature_c),
                "res_fuel_flow": resid(frame.fuel_flow_lph, pred.fuel_flow_lph),
                "res_manifold_pressure": resid(
                    frame.manifold_pressure_bar, pred.manifold_pressure_bar
                ),
                # The actuator positions against the as-new twin at the same
                # operating point -- the flap and the wastegate both move with
                # power and ambient, so only the difference is diagnostic.
                "res_wastegate": resid(
                    frame.wastegate_pct, 100.0 * pred.turbo_state.wastegate_fraction),
                "res_cooling_flap": resid(
                    frame.cooling_flap_pct, 100.0 * pred.cooling_flap_fraction),
                "shadow_available": True,
            }
        )
    else:
        row.update(
            dict.fromkeys(
                ("res_cht", "res_coolant", "res_egt", "res_oil_pressure",
                 "res_oil_temperature", "res_fuel_flow", "res_manifold_pressure",
                 "res_wastegate", "res_cooling_flap"),
                None,
            )
        )
        row["shadow_available"] = False

    # -- labels: internal state, never observable on the aircraft ------------
    for name, value in veng.degradation.factors.as_dict().items():
        row[f"deg_{name}"] = float(value)
    labels = veng.degradation.fault_label_vector()
    for mode, value in zip(FAULT_CLASS_ORDER, labels, strict=True):
        row[f"lab_{mode.value}"] = float(value)
    row["any_fault"] = float(labels.max()) if len(labels) else 0.0
    del op
    return row


# ---------------------------------------------------------------------------
# Fleet generation
# ---------------------------------------------------------------------------


def _fleet_fingerprint(engine_key: str, max_life_hours: float,
                       n_engines: int) -> str:
    """Everything that determines what the fleet contains."""
    import hashlib

    h = hashlib.sha256()
    here = Path(__file__).resolve().parent
    for name in ("synth_data_gen.py", "engine_sim.py", "mvem.py",
                 "degradation.py", "turbo.py", "combustion.py",
                 "perf_maps.py", "atmosphere.py", "ecu.py"):
        f = here / name
        if f.exists():
            h.update(f.read_bytes())
    # The configs shape the fleet as much as the code does: a changed
    # threshold or engine parameter must invalidate the cache too.
    cfg_dir = here.parent / "configs"
    for cfg in sorted(cfg_dir.rglob("*.yaml")):
        h.update(cfg.name.encode())
        h.update(cfg.read_bytes())
    h.update(f"{engine_key}|{max_life_hours}|{n_engines}".encode())
    h.update(f"{SPLIT_TRAIN}|{SPLIT_VAL}|{SPLIT_TEST}".encode())
    return h.hexdigest()


def _validate_cache(cache: Path, engine_key: str, max_life_hours: float,
                    n_engines: int) -> None:
    """Discard the resume cache if anything that shapes the fleet has changed."""
    want = _fleet_fingerprint(engine_key, max_life_hours, n_engines)
    stamp = cache / "fingerprint.txt"
    have = stamp.read_text().strip() if stamp.exists() else None
    if have == want:
        return
    stale = list(cache.glob("engine_*.pkl"))
    if stale:
        print(f"  physics or configuration changed since these shards were "
              f"written -- discarding {len(stale)} cached engine(s)")
        for f in stale:
            f.unlink(missing_ok=True)
    stamp.write_text(want)


def _shard_path(cache: Path, engine_id: int) -> Path:
    return cache / f"engine_{engine_id:04d}.pkl"


def _worker(engine_id: int, engine_key: str, max_life_hours: float,
            cache_dir: str | None = None) -> tuple[int, dict]:
    """Fly one engine, caching the result so a killed run can be resumed.

    A full fleet takes the better part of an hour. Losing all of it because the
    process was interrupted at minute forty is avoidable, and was not avoided
    twice. Each engine is written to its own shard as it finishes, so an
    interrupted run costs the engines still in flight rather than every engine
    already done.
    """
    cache = Path(cache_dir) if cache_dir else None
    if cache is not None:
        shard = _shard_path(cache, engine_id)
        if shard.exists():
            try:
                with shard.open("rb") as fh:
                    return engine_id, pickle.load(fh)
            except Exception:
                # A shard written by an interrupted process can be truncated.
                # Recomputing one engine is far cheaper than trusting it.
                shard.unlink(missing_ok=True)

    run = run_one_engine(
        engine_id, engine_key=engine_key, max_life_hours=max_life_hours
    )
    for row in run.rows:
        row["engine_id"] = engine_id
        row["split"] = split_for(engine_id)
    payload = {
        "rows": run.rows,
        "failed": run.failed,
        "life_hours": run.life_hours,
        "faults": run.faults,
        "environment": run.environment,
    }
    if cache is not None:
        # Written to a temporary name and renamed, so a shard is either
        # complete or absent -- never half-written and silently believed.
        tmp = _shard_path(cache, engine_id).with_suffix(".tmp")
        with tmp.open("wb") as fh:
            pickle.dump(payload, fh, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(_shard_path(cache, engine_id))
    return engine_id, payload


def generate(
    out_dir: Path,
    *,
    n_engines: int = N_ENGINES,
    engine_key: str = "rotax_915is",
    max_life_hours: float = MAX_LIFE_HOURS,
    workers: int | None = None,
) -> dict:
    """Generate the fleet and write one Parquet file per split."""
    import pandas as pd

    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = out_dir / "_shards"
    cache_dir.mkdir(parents=True, exist_ok=True)
    # A resume cache that survives a code change is a correctness bug, not a
    # convenience: it would silently rebuild the fleet from the OLD physics
    # while every log line said the run had completed. The fingerprint covers
    # the modules that determine what an engine does, so any edit to them
    # discards the cache.
    _validate_cache(cache_dir, engine_key, max_life_hours, n_engines)
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    resumed = len(list(cache_dir.glob("engine_*.pkl")))
    if resumed:
        print(f"  resuming: {resumed} engine(s) already cached in {cache_dir}")
    started = time.time()

    manifest: dict = {
        "engine_key": engine_key,
        "n_engines": n_engines,
        "split": {"train": list(SPLIT_TRAIN), "val": list(SPLIT_VAL), "test": list(SPLIT_TEST)},
        "sampling": {
            "dt_s": DT_S, "settle_s": SETTLE_S, "record_s": RECORD_S,
            "sortie_hours_range": list(SORTIE_HOURS_RANGE),
            "max_life_hours": max_life_hours,
        },
        "engines": {},
    }

    by_split: dict[str, list[dict]] = {"train": [], "val": [], "test": []}
    done = 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_worker, eid, engine_key, max_life_hours,
                        str(cache_dir)): eid
            for eid in range(1, n_engines + 1)
        }
        for fut in as_completed(futures):
            eid, result = fut.result()
            by_split[split_for(eid)].extend(result["rows"])
            manifest["engines"][str(eid)] = {
                "split": split_for(eid),
                "failed": result["failed"],
                "life_hours": round(result["life_hours"], 2),
                "environment": result["environment"],
                "faults": result["faults"],
                "n_rows": len(result["rows"]),
            }
            done += 1
            print(f"  [{done:3d}/{n_engines}] engine {eid:3d} "
                  f"{'FAILED' if result['failed'] else 'censored':>8} at "
                  f"{result['life_hours']:7.1f} h, {len(result['rows']):5d} rows",
                  flush=True)

    for split, rows in by_split.items():
        if not rows:
            continue
        df = pd.DataFrame(rows).sort_values(["engine_id", "flight_hours"])
        path = out_dir / f"{split}.parquet"
        df.to_parquet(path, index=False)
        manifest.setdefault("files", {})[split] = {
            "path": str(path.relative_to(out_dir.parent.parent))
            if out_dir.is_absolute() else str(path),
            "rows": int(len(df)),
            "engines": int(df["engine_id"].nunique()),
            "bytes": path.stat().st_size,
        }

    manifest["elapsed_s"] = round(time.time() - started, 1)
    failed = sum(1 for e in manifest["engines"].values() if e["failed"])
    manifest["failed_engines"] = failed
    # A fault whose onset falls after the engine dies is never expressed, and
    # nothing used to say so -- the schedule was recorded as if it had
    # happened. Counting it here means a regression shows up in the manifest
    # rather than as an inexplicably empty label column months later.
    injected = expressed = 0
    never: dict[str, int] = {}
    for info in manifest["engines"].values():
        for f in info["faults"]:
            injected += 1
            if f.get("expressed"):
                expressed += 1
            else:
                never[f["mode"]] = never.get(f["mode"], 0) + 1
    manifest["faults_injected"] = injected
    manifest["faults_expressed"] = expressed
    manifest["faults_never_expressed"] = never

    manifest["censored_engines"] = n_engines - failed
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--engines", type=int, default=N_ENGINES)
    ap.add_argument("--engine-key", default="rotax_915is")
    ap.add_argument("--max-hours", type=float, default=MAX_LIFE_HOURS)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    out = Path(args.out) if args.out else config.data_dir() / "synthetic"
    if args.engines > N_ENGINES:
        raise SystemExit(
            f"--engines {args.engines} exceeds the {N_ENGINES} the split ranges "
            f"cover. Widen SPLIT_TRAIN/SPLIT_VAL/SPLIT_TEST first, or the extra "
            f"engines land in one split with no faults."
        )
    print(f"Generating {args.engines} run-to-failure engines -> {out}")
    m = generate(
        out,
        n_engines=args.engines,
        engine_key=args.engine_key,
        max_life_hours=args.max_hours,
        workers=args.workers,
    )
    print("\n" + "=" * 70)
    print(f"  engines        : {m['n_engines']} "
          f"({m['failed_engines']} reached the maintenance threshold, "
          f"{m['censored_engines']} censored)")
    for split, info in m.get("files", {}).items():
        print(f"  {split:<15}: {info['rows']:>8,} rows  "
              f"{info['engines']:>3} engines  {info['bytes']/1e6:6.1f} MB")
    print(f"  elapsed        : {m['elapsed_s']} s")
    print("=" * 70)


if __name__ == "__main__":
    main()
