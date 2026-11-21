"""CAN receiver -- decode, validate, and report what is actually trustworthy.

This is the counterpart to ``can_simulator``. It reads CANaerospace frames from
a ``python-can`` bus, decodes them with the DBC, and applies the sensor
validation of PRD Part 1 section 8.3 before anything downstream is allowed to
believe a number:

    Method 1  Range check            value outside the physically possible band
    Method 2  Rate-of-change check   change faster than physics permits
    Method 3  Cross-sensor consistency (the two FADEC lanes must agree)
    Method 5  Multi-source voting    lane A vs lane B disagreement

and it tracks staleness from the CANaerospace message-code sequence, which is
what lets the HMI distinguish the five value states of PRD Part 4 section 7.1:

    VALID     decoded, in range, fresh
    STALE     no update within the expected interval
    INVALID   failed a plausibility check
    MISSING   never received
    SUSPECT   plausible, but the redundant lane disagrees

The critical design rule, from PRD Part 4 section 7.2: an invalid reading is
REMOVED, never replaced by a substitute. A frozen last-good value that still
looks plausible is the most dangerous failure mode a monitoring system has.
"""

from __future__ import annotations

import functools
import math
import os
import time
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import can
import cantools

from common import config
from common.fadec import dual_lane_channels
from layer1_edge.sensor_fusion import LaneVote

KELVIN = 273.15

# CANaerospace data type codes [CANAS 1.6 section 2.2]. Every header message on
# this bus carries a FLOAT.
DATA_TYPE_FLOAT = 2
_DATA_TYPE_NAMES = {0: "NODATA", 1: "ERROR", 2: "FLOAT", 3: "LONG", 4: "ULONG",
                    5: "BLONG", 6: "SHORT", 7: "USHORT"}

# DBC node attribute carrying a station's CANaerospace Node-ID.
NODE_ID_ATTRIBUTE = "CANaerospaceNodeId"

# A frame numbered up to this far behind the newest one is old -- repeated or
# late -- rather than new.
_SEQ_WINDOW = 16
# This many old-numbered frames in a row, each one higher than the last, means
# the transmitter restarted its counter rather than that frames are repeating.
_RESTART_RUN = 3


class ValueState(StrEnum):
    """The five states of PRD Part 4 section 7.1."""

    VALID = "VALID"
    STALE = "STALE"
    INVALID = "INVALID"
    MISSING = "MISSING"
    SUSPECT = "SUSPECT"


@dataclass
class LaneReading:
    """One FADEC lane's own reading of a channel, kept apart from the other lane's."""

    value: float | None = None
    state: ValueState = ValueState.MISSING
    updated_t: float = -1.0
    reason: str = ""
    # The last reading that passed range, rate and frozen checks, even when
    # removed (see CanIngest.raw). Never a value.
    raw: float | None = None
    raw_t: float = -1.0


@dataclass
class Channel:
    """One decoded engineering value and everything known about its integrity."""

    name: str
    value: float | None = None
    state: ValueState = ValueState.MISSING
    updated_t: float = -1.0
    age_s: float = float("inf")
    reason: str = ""
    # The lanes usable at the last resolution, and each lane's own reading.
    lane_a: float | None = None
    lane_b: float | None = None
    lane_delta: float | None = None
    lanes: dict[str, LaneReading] = field(default_factory=dict)
    # A sensor fitted to both lanes is reporting on one lane only.
    redundancy_lost: bool = False
    # As LaneReading.raw: kept for the sensor-response check, never a value.
    raw: float | None = None
    raw_t: float = -1.0

    @property
    def usable(self) -> bool:
        """Whether a detector may consume this value."""
        return self.state in (ValueState.VALID, ValueState.SUSPECT)


@dataclass
class Telemetry:
    """The decoded engine state at one instant, with integrity metadata."""

    t_s: float = 0.0
    channels: dict[str, Channel] = field(default_factory=dict)
    frames_decoded: int = 0
    frames_lost: int = 0
    decode_errors: int = 0
    # Frames refused before any value was taken from them, and why:
    # frame_type, extended_id, node_id, data_type, repeated, late.
    frames_rejected: int = 0
    rejects: dict[str, int] = field(default_factory=dict)
    sequence_resets: int = 0
    flight_phase: int = 0
    # The ECU's own report (ECU_STATUS). None until one arrives, and the flags
    # None again once it is stale: an ECU not reporting is unknown, not healthy.
    ecu: EcuStatus | None = None
    ecu_error_flags: int | None = None

    def get(self, name: str) -> float | None:
        ch = self.channels.get(name)
        return ch.value if ch is not None and ch.usable else None

    def state(self, name: str) -> ValueState:
        ch = self.channels.get(name)
        return ch.state if ch else ValueState.MISSING

    def unusable(self) -> list[str]:
        return [n for n, c in self.channels.items() if not c.usable]


@dataclass
class EcuStatus:
    """What the FADEC says about itself, decoded from ECU_STATUS."""

    updated_t: float
    mode: int
    active_lane: int          # 0 NONE, 1 ONLY_A, 2 ONLY_B, 3 AUTO_AB
    lane_a_health: int
    lane_b_health: int
    warn_lamp_a: int          # 0 OFF, 1 ON, 2 FLASHING
    warn_lamp_b: int
    error_flags: int
    stale: bool = False


@dataclass
class _Sequence:
    """Message-code history of one identifier."""

    last: int
    seen: deque[int] = field(default_factory=deque)
    missing: deque[int] = field(default_factory=deque)
    old_run: int = 0
    old_last: int = -1

    def __post_init__(self) -> None:
        self.seen.append(self.last)

    def prune(self) -> None:
        """Forget codes too far behind the newest to be told apart from new ones."""
        near = lambda c: (self.last - c) % 256 <= _SEQ_WINDOW  # noqa: E731
        self.seen = deque(c for c in self.seen if near(c))
        self.missing = deque(c for c in self.missing if near(c))


# Channels the twin needs, mapped to the threshold entry that bounds them.
# The threshold key is what supplies the plausibility band, so adding a channel
# without a threshold entry is impossible by construction.
_THRESHOLD_KEY = {
    "rpm": "rpm",
    "propeller_rpm": None,
    "cht_max": "cht",
    "cht_1": "cht",
    "cht_2": "cht",
    "cht_3": "cht",
    "cht_4": "cht",
    "coolant_temperature": "coolant_temperature",
    "egt_max": "egt",
    "egt_1": "egt",
    "egt_2": "egt",
    "egt_3": "egt",
    "egt_4": "egt",
    "oil_pressure": "oil_pressure",
    "oil_temperature": "oil_temperature",
    "fuel_flow": "fuel_flow",
    "manifold_pressure": "manifold_pressure",
    "manifold_air_temperature": "manifold_air_temperature",
    "fuel_pressure": "fuel_pressure",
    "vibration_rms_x": "vibration_rms",
    "vibration_rms_y": "vibration_rms",
    "vibration_rms_z": "vibration_rms",
    "vibration_kurtosis": None,
    "battery_voltage": "battery_voltage",
    "alternator_current": "alternator_current",
    "battery_current": None,
    "injection_timing_1": "injection_timing",
    "injection_timing_2": "injection_timing",
    "injection_timing_3": "injection_timing",
    "injection_timing_4": "injection_timing",
    "ignition_timing_1": "ignition_timing",
    "ignition_timing_2": "ignition_timing",
    "ignition_timing_3": "ignition_timing",
    "ignition_timing_4": "ignition_timing",
    "injection_timing_cmd": "injection_timing",
    "ignition_timing_cmd": "ignition_timing",
    "injection_period": "injection_period",
    "injector_duty": None,
    "knock_intensity": None,
    "knock_retard": None,
    "throttle_pct": None,
    "wastegate_pct": None,
    "air_flow": None,
    "altitude_ft": None,
    "oat": None,
    "airspeed_kmh": None,
    # Airframe actuator positions. No plausibility band: the travel is
    # bounded by the actuator itself, and what matters is where it sits
    # against the as-new twin, not an absolute limit.
    "cooling_flap_pct": None,
    "oil_flap_pct": None,
}

# The instrument behind each measured channel, for the frozen-reading check. ECU
# commands hold still legitimately and are never judged frozen; air data and
# ECU status have no entry.
_COMMANDED = frozenset({"injection_timing_cmd", "ignition_timing_cmd", "injection_period"})
_FROZEN_SENSOR = {
    ch: key for ch, key in _THRESHOLD_KEY.items() if key and ch not in _COMMANDED
} | {"battery_current": "battery_current"}


def _phi(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


# Channels that read exactly zero -- not noise about zero -- with the engine
# stopped: the pulse counters (engine_sim._pulse) and the oil-pressure gauge
# with no pump turning (engine_sim._at_rest).
_AT_REST_ZERO = frozenset({"rpm", "fuel_flow", "oil_pressure"})


@functools.lru_cache(maxsize=256)
def repeat_run_probability(noise_over_resolution: float, n: int) -> float:
    """Chance that ``n`` consecutive readings of a steady quantity are identical.

    A reading is the quantity plus Gaussian noise, rounded to the resolution, so
    the chance depends only on noise / resolution and on where the quantity sits
    within one resolution step; the worst position is taken.
    """
    k = float(noise_over_resolution)
    span = int(8.0 * k) + 4
    worst = 0.0
    for i in range(40):
        u = i / 40.0
        total = sum(
            (_phi((j + 0.5 - u) / k) - _phi((j - 0.5 - u) / k)) ** n
            for j in range(-span, span + 1)
        )
        worst = max(worst, total)
    return worst


@functools.lru_cache(maxsize=64)
def frozen_run_limit(noise_over_resolution: float, false_alarm_probability: float) -> int | None:
    """The fewest identical readings a working sensor produces with probability
    below ``false_alarm_probability``; None if no run length up to 1000 is that rare."""
    for n in range(2, 1001):
        if repeat_run_probability(noise_over_resolution, n) <= false_alarm_probability:
            return n
    return None


class CanIngest:
    """Decodes a CANaerospace stream into validated engine telemetry."""

    def __init__(
        self,
        *,
        bus: can.BusABC | None = None,
        interface: str = "virtual",
        channel: str = "dt_engine",
        engine_key: str = "rotax_915is",
    ) -> None:
        self.db = cantools.database.load_file(str(config.dbc_path()))
        self.engine = config.load_engine(engine_key)
        self.thresholds = config.load_thresholds()
        self.params = self.thresholds["parameters"]
        pipeline = self.thresholds["pipeline"]
        self.stale_after_intervals = int(pipeline["stale_after_intervals"])
        self.telemetry_hz = float(pipeline["telemetry_hz"])
        self.lane_vote = LaneVote(tolerance_fraction=float(pipeline["lane_agreement_fraction"]))
        self.lane_floor = {k: float(v) for k, v in pipeline["lane_agreement_floor"].items()}
        self.dual_lane = dual_lane_channels(self.engine)
        if not self.dual_lane <= set(self.lane_floor):
            missing = sorted(self.dual_lane - set(self.lane_floor))
            raise ValueError(f"pipeline.lane_agreement_floor has no entry for {missing}")
        ratios = pipeline["frozen_noise_over_resolution"]
        self._frozen_p = float(pipeline["frozen_false_alarm_probability"])
        self._frozen_limit = {
            ch: limit for ch, key in _FROZEN_SENSOR.items() if key in ratios
            if (limit := frozen_run_limit(float(ratios[key]), self._frozen_p)) is not None
        }
        self._runs: dict[str, tuple[float, int]] = {}
        # Channels removed on evidence from outside the bus (condemn / absolve).
        self._condemned: dict[str, str] = {}

        self.bus = bus or can.Bus(interface=interface, channel=channel, receive_own_messages=True)
        self._owns_bus = bus is None
        self.telemetry = Telemetry()
        self._seq: dict[int, _Sequence] = {}
        self._senders = self._transmitters()
        self._prev: dict[str, tuple[float, float]] = {}  # name -> (value, t)

    def close(self) -> None:
        if self._owns_bus:
            self.bus.shutdown()

    def __enter__(self) -> CanIngest:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    def _plausible(self, name: str, value: float) -> tuple[bool, str]:
        """PRD Part 1 section 8.3 Method 1: is this physically possible at all?"""
        key = _THRESHOLD_KEY.get(name)
        if key is None:
            return True, ""
        spec = self.params.get(key)
        if not spec:
            return True, ""
        band = spec.get("plausible_range") or spec.get("range")
        if not band:
            return True, ""
        lo, hi = float(band[0]), float(band[1])
        if not (lo <= value <= hi):
            return False, f"out of plausible range [{lo}, {hi}]"
        return True, ""

    def _rate_ok(self, name: str, source: str, value: float, t: float) -> tuple[bool, str]:
        """PRD Part 1 section 8.3 Method 2: could it have changed this fast?

        ``source`` is the channel, or the channel on one lane: each lane's
        sensor is judged against its own previous reading.
        """
        key = _THRESHOLD_KEY.get(name)
        if key is None:
            return True, ""
        spec = self.params.get(key)
        if not spec or "max_rate_per_s" not in spec:
            return True, ""
        prev = self._prev.get(source)
        if prev is None:
            return True, ""
        prev_v, prev_t = prev
        dt = t - prev_t
        if dt <= 1e-9:
            return True, ""
        rate = abs(value - prev_v) / dt
        limit = float(spec["max_rate_per_s"])
        if rate > limit * 1.5:  # 1.5x margin absorbs quantisation on fast channels
            return False, f"rate {rate:.1f}/s exceeds physical limit {limit:.1f}/s"
        return True, ""

    def _check(self, name: str, source: str, value: float, t: float) -> str:
        """Why a reading must be removed, or "" when it may be used."""
        # A NaN or an infinity is never a reading (CAN-07). On a channel with no
        # plausibility band configured, `inf` battery current and `nan`
        # propeller speed used to pass straight through as VALID.
        if not math.isfinite(value):
            return "not a finite number"
        ok, reason = self._plausible(name, value)
        if ok:
            ok, reason = self._rate_ok(name, source, value, t)
        if not ok:
            return reason
        return self._frozen(name, source, value)

    def _frozen(self, name: str, source: str, value: float) -> str:
        """A run of identical readings longer than a working sensor produces.

        Audit 15 Sep, P0-5: a frozen plausible value passed every check. The run
        limit follows from the instrument's noise and resolution
        (``frozen_run_limit``); each lane's sensor is judged on its own run.
        """
        limit = self._frozen_limit.get(name)
        if limit is None:
            return ""
        # A pulse-counting instrument reads exactly zero at rest, as long as
        # the engine stays stopped -- a legitimate run, not a latched one.
        if value == 0.0 and name in _AT_REST_ZERO:
            self._runs[source] = (value, 0)
            return ""
        last, run = self._runs.get(source, (None, 0))
        run = run + 1 if value == last else 1
        self._runs[source] = (value, run)
        if run < limit:
            return ""
        return (f"frozen: {run} identical readings in a row, which a working sensor "
                f"produces with probability below {self._frozen_p:g}")

    def _set(self, name: str, value: float, t: float, *, lane: str | None = None) -> None:
        ch = self.telemetry.channels.setdefault(name, Channel(name=name))
        source = name if lane is None else f"{name}/{lane}"
        target = ch if lane is None else ch.lanes.setdefault(lane, LaneReading())
        reason = self._check(name, source, value, t)
        if not reason:
            self._prev[source] = (value, t)
            target.raw, target.raw_t = value, t
            reason = self._condemned.get(name, "")
        target.updated_t = t
        target.reason = reason
        if reason:
            # PRD Part 4 section 7.2: remove it, do not substitute.
            target.value = None
            target.state = ValueState.INVALID
        else:
            target.value = value
            target.state = ValueState.VALID
        if lane is None:
            if not reason:
                ch.age_s = 0.0
            return
        self._resolve(ch, t)

    # ------------------------------------------------------------------
    def condemn(self, name: str, reason: str) -> None:
        """Remove a channel on evidence the bus alone cannot give.

        The twin's sensor-response check uses this (layer4_core/sensor_response).
        The channel stays INVALID, frame after frame, until ``absolve``; its
        readings are still kept as ``raw`` so the check can see it recover.
        """
        self._condemned[name] = reason
        ch = self.telemetry.channels.get(name)
        if ch is None:
            return
        for r in (*ch.lanes.values(), ch):
            if r.state in (ValueState.VALID, ValueState.SUSPECT):
                r.value, r.state, r.reason = None, ValueState.INVALID, reason

    def absolve(self, name: str) -> None:
        """Believe a condemned channel again, from its next reading."""
        self._condemned.pop(name, None)

    def new_power_up(self) -> None:
        """Forget what the sensors read before the engine was restarted.

        The rate and frozen checks compare each reading with the one before
        it. Across a restart the one before it belongs to a different run: oil
        at 102 degC in the cruise, then 15 degC on the starter half a second
        later. That is two engine runs, not a sensor changing at 170 degC/s,
        and judging it as one removed the oil temperature and raised SENSOR
        FAULT at every sign-in. A condemnation is dropped for the same reason
        a FADEC re-runs its built-in test at power-up: the new run is judged
        on its own readings, and a sensor that is still dead is found again
        as soon as the start moves the engine.
        """
        self._prev.clear()
        self._runs.clear()
        self._condemned.clear()

    def condemned(self) -> dict[str, str]:
        return dict(self._condemned)

    def raw(self, name: str) -> float | None:
        """The latest fresh reading that passed range, rate and frozen checks,
        whether or not the channel is condemned.

        For the sensor-response check ONLY. A condemned channel's reading is not
        a value, and nothing that detects faults may use it.
        """
        ch = self.telemetry.channels.get(name)
        if ch is None:
            return None
        newest = max((ch, *ch.lanes.values()), key=lambda r: r.raw_t)
        max_age = self.stale_after_intervals / self.telemetry_hz
        if newest.raw_t < 0.0 or self.telemetry.t_s - newest.raw_t > max_age:
            return None
        return newest.raw

    def _refuse(self, name: str, reason: str, t: float, *, lane: str | None = None) -> None:
        """The transmitter itself said this is not a usable reading."""
        ch = self.telemetry.channels.setdefault(name, Channel(name=name))
        target = ch if lane is None else ch.lanes.setdefault(lane, LaneReading())
        target.value = None
        target.state = ValueState.INVALID
        target.reason = reason
        target.updated_t = t
        if lane is not None:
            self._resolve(ch, t)

    def _resolve(self, ch: Channel, t: float) -> None:
        """Form a lane-tagged channel from the lanes usable NOW.

        PRD Part 1 section 8.3 Methods 3 and 5. A lane counts only while its own
        reading is VALID and fresh. A lane that has gone quiet leaves the vote
        instead of being compared by its last value, and one lane's bad frame
        never deletes the other lane's good reading. Both used to happen: the
        lanes shared one value, and each lane's last number was kept for ever.
        """
        max_age = self.stale_after_intervals / self.telemetry_hz
        fresh = {k: r for k, r in ch.lanes.items()
                 if r.state is ValueState.VALID and t - r.updated_t <= max_age}
        ch.lane_a = fresh["A"].value if "A" in fresh else None
        ch.lane_b = fresh["B"].value if "B" in fresh else None
        both = ch.lane_a is not None and ch.lane_b is not None
        ch.lane_delta = abs(ch.lane_a - ch.lane_b) if both else None
        ch.redundancy_lost = False

        if not fresh:
            newest = max(ch.lanes.values(), key=lambda r: r.updated_t)
            ch.value = None
            ch.updated_t = newest.updated_t
            ch.age_s = t - newest.updated_t
            if newest.state is ValueState.VALID:
                ch.state = ValueState.STALE
                ch.reason = f"no update for {ch.age_s:.2f} s"
            else:
                ch.state = newest.state
                ch.reason = newest.reason
            return

        ch.updated_t = max(r.updated_t for r in fresh.values())
        ch.age_s = t - ch.updated_t
        if both:
            ch.value, disagree = self.lane_vote.fuse(
                ch.lane_a, ch.lane_b, floor=self.lane_floor.get(ch.name, 0.0))
            ch.state = ValueState.SUSPECT if disagree else ValueState.VALID
            ch.reason = (f"FADEC lanes disagree: A={ch.lane_a:.2f} B={ch.lane_b:.2f}"
                         if disagree else "")
            return

        ((lane, reading),) = fresh.items()
        ch.value = reading.value
        ch.state = ValueState.VALID
        ch.reason = ""
        if ch.name in self.dual_lane:
            other = "B" if lane == "A" else "A"
            o = ch.lanes.get(other)
            if o is None:
                why = "never received"
            elif o.state is ValueState.VALID:
                why = f"no update for {t - o.updated_t:.2f} s"
            else:
                why = o.reason or str(o.state)
            ch.redundancy_lost = True
            ch.reason = f"lane {other} unavailable: {why}"

    # ------------------------------------------------------------------
    def _transmitters(self) -> dict[int, frozenset[int]]:
        """The Node-IDs allowed to send each header message, from the bus definition."""
        node_ids: dict[str, int] = {}
        for node in self.db.nodes:
            attrs = node.dbc.attributes if node.dbc is not None else {}
            if NODE_ID_ATTRIBUTE in attrs:
                node_ids[node.name] = int(attrs[NODE_ID_ATTRIBUTE].value)
        # Which FADEC lane each ECU node is, so a reading keeps the identity of
        # the lane that actually sent it.
        self._node_lane = {node_ids[n]: n[-1] for n in ("ECU_A", "ECU_B") if node_ids.get(n, 0) > 0}
        allowed: dict[int, frozenset[int]] = {}
        for m in self.db.messages:
            if "NODE_ID" not in {s.name for s in m.signals}:
                continue
            ids = frozenset(node_ids[s] for s in m.senders if node_ids.get(s, 0) > 0)
            if not ids:
                # Fail at start-up, not by silently accepting every station.
                raise ValueError(f"{m.name}: no transmitter with a CANaerospace Node-ID in the DBC")
            allowed[m.frame_id] = ids
        return allowed

    def _reject(self, why: str) -> None:
        tel = self.telemetry
        tel.frames_rejected += 1
        tel.rejects[why] = tel.rejects.get(why, 0) + 1

    def _in_sequence(self, frame_id: int, code: int) -> bool:
        """Account for one message code. False means the frame must not be used.

        CANaerospace numbers each message and rolls over after 255 [CANAS 1.6
        section 3.3]. A number already received is a repeat -- a transmitter
        resending a frozen buffer, or a duplicating gateway -- and believing it
        makes a dead feed look alive. A number behind the newest is a late frame
        whose value is already superseded; believing it moves the reading back
        in time. Both are dropped, so a feed that only repeats goes STALE.
        """
        tel = self.telemetry
        seq = self._seq.get(frame_id)
        if seq is None:
            self._seq[frame_id] = _Sequence(code)
            return True

        behind = (seq.last - code) % 256
        if behind <= _SEQ_WINDOW:
            seq.old_run = seq.old_run + 1 if seq.old_run and code == (seq.old_last + 1) % 256 else 1
            seq.old_last = code
            if seq.old_run >= _RESTART_RUN:
                tel.sequence_resets += 1
                self._seq[frame_id] = _Sequence(code)
                return True
            if code in seq.missing:
                # Counted lost when the sequence jumped past it; it was only late.
                seq.missing.remove(code)
                tel.frames_lost = max(0, tel.frames_lost - 1)
                self._reject("late")
            elif code in seq.seen:
                self._reject("repeated")
            else:
                self._reject("late")
            return False

        seq.old_run = 0
        ahead = (code - seq.last) % 256
        if ahead > 128:
            # Neither the next frames nor recent ones: the counter was reset.
            tel.sequence_resets += 1
            self._seq[frame_id] = _Sequence(code)
            return True
        tel.frames_lost += ahead - 1
        seq.missing.extend((seq.last + k) % 256 for k in range(1, ahead))
        seq.seen.append(code)
        seq.last = code
        seq.prune()
        return True

    def _decode(self, msg: can.Message, t: float) -> None:
        # Bus error and remote-request frames carry no reading, and CAN FD is not
        # this bus. None of them may be decoded into a value.
        if msg.is_error_frame or msg.is_remote_frame or getattr(msg, "is_fd", False):
            self._reject("frame_type")
            return
        try:
            spec = self.db.get_message_by_frame_id(msg.arbitration_id)
        except KeyError:
            self.telemetry.decode_errors += 1
            return
        # An 11-bit and a 29-bit identifier with the same number are different
        # messages. A 29-bit frame numbered 500 is not engine speed, whatever
        # its payload decodes to.
        if bool(msg.is_extended_id) != bool(spec.is_extended_frame):
            self._reject("extended_id")
            return
        try:
            decoded = spec.decode(msg.data)
        except Exception:
            self.telemetry.decode_errors += 1
            return

        # The transmitting station must be one the bus definition declares for
        # this message. Anything else is a misconfigured or foreign unit.
        node = decoded.get("NODE_ID")
        if node is not None and int(node) not in self._senders.get(spec.frame_id, ()):
            self._reject("node_id")
            return

        code = decoded.get("MESSAGE_CODE", decoded.get("ECU_SEQ_COUNTER"))
        if code is not None and not self._in_sequence(spec.frame_id, int(code)):
            return

        dtype = decoded.get("DATA_TYPE")
        if dtype is not None and int(dtype) != DATA_TYPE_FLOAT:
            # A NODATA payload decodes as 0.0 and a LONG as some number. Neither
            # is a floating-point reading, and a zero must never pass as one.
            self._reject("data_type")
            refused = (f"transmitter sent data type "
                       f"{_DATA_TYPE_NAMES.get(int(dtype), int(dtype))}, not FLOAT")
        else:
            self.telemetry.frames_decoded += 1
            # A non-zero Service Code is the transmitting unit telling us its
            # own data is untrustworthy. Believe it.
            service = decoded.get("SERVICE_CODE")
            refused = (f"transmitter reported service code {int(service)}"
                       if service is not None and int(service) != 0 else "")

        name = spec.name
        # The lane is the FADEC lane that SENT the frame, from its Node-ID -- not
        # the identifier's channel letter, which a HUMS instrument also uses.
        lane = self._node_lane.get(int(node)) if node is not None else None

        def put(channel: str, value: Any, conv=lambda v: float(v), *,
                on_lane: str | None = None) -> None:
            if value is None:
                return
            source = on_lane or lane
            if refused:
                self._refuse(channel, refused, t, lane=source)
                return
            self._set(channel, conv(value), t, lane=source)

        k2c = lambda v: float(v) - KELVIN  # noqa: E731
        hpa2bar = lambda v: float(v) / 1000.0  # noqa: E731

        if name in ("ECSA_ENGINE_SPEED", "ECSB_ENGINE_SPEED"):
            put("rpm", decoded.get("ENGINE_SPEED"))
        elif name in ("ECSA_PROPELLER_SPEED", "ECSB_PROPELLER_SPEED"):
            put("propeller_rpm", decoded.get("PROPELLER_SPEED"))
        elif name in ("ECSA_EGT", "ECSB_EGT"):
            put("egt_max", decoded.get("EGT"), k2c)
        elif name in ("ECSA_FUEL_FLOW", "ECSB_FUEL_FLOW"):
            put("fuel_flow", decoded.get("FUEL_FLOW"))
        elif name in ("ECSA_MANIFOLD_PRESSURE", "ECSB_MANIFOLD_PRESSURE"):
            put("manifold_pressure", decoded.get("MANIFOLD_PRESSURE"), hpa2bar)
        elif name in ("ECSA_OIL_PRESSURE", "ECSB_OIL_PRESSURE"):
            put("oil_pressure", decoded.get("OIL_PRESSURE"), lambda v: float(v) / 1000.0 * 14.5038)
        elif name in ("ECSA_OIL_TEMPERATURE", "ECSB_OIL_TEMPERATURE"):
            put("oil_temperature", decoded.get("OIL_TEMPERATURE"), k2c)
        elif name in ("ECSA_CHT", "ECSB_CHT"):
            put("cht_max", decoded.get("CHT"), k2c)
        elif name in ("ECSA_COOLANT_TEMPERATURE", "ECSB_COOLANT_TEMPERATURE"):
            put("coolant_temperature", decoded.get("COOLANT_TEMPERATURE"), k2c)
        elif name == "FUEL_SYSTEM_PRESSURE":
            put("fuel_pressure", decoded.get("FUEL_SYSTEM_PRESSURE"), hpa2bar)
        elif name == "DC_VOLTAGE":
            put("battery_voltage", decoded.get("DC_VOLTAGE"))
        elif name == "DC_CURRENT":
            put("alternator_current", decoded.get("DC_CURRENT"))
        elif name == "BATTERY_CURRENT":
            put("battery_current", decoded.get("BATTERY_CURRENT"))
        elif name == "CHT_PER_CYLINDER":
            for i in (1, 2, 3, 4):
                put(f"cht_{i}", decoded.get(f"CHT_CYL{i}"), k2c)
        elif name == "EGT_PER_CYLINDER":
            for i in (1, 2, 3, 4):
                put(f"egt_{i}", decoded.get(f"EGT_CYL{i}"), k2c)
        elif name == "VIBRATION":
            put("vibration_rms_x", decoded.get("VIB_RMS_X"))
            put("vibration_rms_y", decoded.get("VIB_RMS_Y"))
            put("vibration_rms_z", decoded.get("VIB_RMS_Z"))
            put("vibration_kurtosis", decoded.get("VIB_KURTOSIS"))
        elif name == "INJECTION_TIMING":
            for i in (1, 2, 3, 4):
                put(f"injection_timing_{i}", decoded.get(f"INJ_TIMING_CYL{i}"))
        elif name == "IGNITION_TIMING":
            for i in (1, 2, 3, 4):
                put(f"ignition_timing_{i}", decoded.get(f"IGN_TIMING_CYL{i}"))
        elif name == "ECU_COMMANDS":
            put("ignition_timing_cmd", decoded.get("IGN_TIMING_CMD"))
            put("injection_timing_cmd", decoded.get("INJ_TIMING_CMD"))
            put("injection_period", decoded.get("INJECTION_PERIOD"))
            put("knock_intensity", decoded.get("KNOCK_INTENSITY"))
        elif name == "ECU_STATUS":
            put("throttle_pct", decoded.get("THROTTLE_POS"))
            put("wastegate_pct", decoded.get("WASTEGATE_POS"))
            put("knock_retard", decoded.get("KNOCK_RETARD"))
            num = lambda k: int(getattr(decoded[k], "value", decoded[k]))  # noqa: E731
            ecu = EcuStatus(
                updated_t=t, mode=num("ECU_MODE"), active_lane=num("ACTIVE_LANE"),
                lane_a_health=num("LANE_A_HEALTH"), lane_b_health=num("LANE_B_HEALTH"),
                warn_lamp_a=num("WARN_LAMP_A"), warn_lamp_b=num("WARN_LAMP_B"),
                error_flags=num("ECU_ERROR_FLAGS"),
            )
            self.telemetry.ecu = ecu
            self.telemetry.ecu_error_flags = ecu.error_flags
        elif name == "MANIFOLD_AIR":
            # MAT1 and MAT2 are the two lanes' manifold air temperature sensors.
            put("manifold_air_temperature", decoded.get("MAT1"), on_lane="A")
            put("manifold_air_temperature", decoded.get("MAT2"), on_lane="B")
            put("air_flow", decoded.get("AIR_FLOW"))
            put("injector_duty", decoded.get("INJECTOR_DUTY"))
        elif name == "AIRFRAME_COOLING":
            put("cooling_flap_pct", decoded.get("COOLING_FLAP_PCT"))
            put("oil_flap_pct", decoded.get("OIL_FLAP_PCT"))
        elif name == "AIR_DATA":
            put("altitude_ft", decoded.get("ALTITUDE_FT"))
            put("oat", decoded.get("OAT"))
            put("airspeed_kmh", decoded.get("AIRSPEED_KMH"))
            phase = decoded.get("FLIGHT_PHASE")
            if phase is not None:
                self.telemetry.flight_phase = int(
                    phase if isinstance(phase, int | float) else phase.value
                )

    # ------------------------------------------------------------------
    def poll(self, *, timeout: float = 0.0, now: float | None = None) -> Telemetry:
        """Drain everything waiting on the bus and return the current state."""
        # On a real bus (`now` is None) each frame is stamped with its RECEIVE
        # time from the driver, on the UTC epoch clock, not with the moment
        # this poll happened to run (CAN-11). Drained in a burst, frames used to
        # share one stamp -- which also let the rate-of-change check skip them.
        # Simulation passes `now` and stays in lockstep with the physics.
        t = time.time() if now is None else now
        while True:
            msg = self.bus.recv(timeout=timeout)
            if msg is None:
                break
            ts = float(getattr(msg, "timestamp", 0.0) or 0.0)
            self._decode(msg, ts if (now is None and ts > 0.0) else t)
            timeout = 0.0  # only the first read may block
        self.telemetry.t_s = t
        self._age_channels(t)
        return self.telemetry

    def iter_log(self, path: str | os.PathLike[str], *, every_s: float = 0.1) -> Iterator[Telemetry]:
        """Decode a recorded bus log, yielding the telemetry every ``every_s`` of log time.

        This is how a capture made on real hardware reaches the twin. python-can
        chooses the reader from the file extension: ``.log`` is the can-utils
        ``candump -L`` format that any SocketCAN machine records with one
        command, and ``.asc`` and ``.blf`` are Vector's. A bench recording needs
        no conversion.

        Frames are stamped with the time IN THE LOG, never the time of replay, so
        the rate-of-change and staleness checks judge the recording as they
        would have judged it live. A gap in the recording is reported once, as
        stale channels, rather than as thousands of empty steps.

        What it decodes is what this project's DBC defines. A recording of a bus
        carrying some other message set shows up as ``decode_errors``, not as
        plausible numbers.
        """
        step = float(every_s)
        if step <= 0.0:
            raise ValueError("every_s must be positive")
        due: float | None = None
        last = 0.0
        for msg in can.LogReader(str(path)):
            t = float(msg.timestamp)
            if due is None:
                due = t + step
            if t >= due:
                self.telemetry.t_s = due
                self._age_channels(due)
                yield self.telemetry
                due += step
                if t >= due:
                    due += step * math.floor((t - due) / step + 1.0)
            self._decode(msg, t)
            last = t
        if due is not None:
            self.telemetry.t_s = last
            self._age_channels(last)
            yield self.telemetry

    def _age_channels(self, t: float) -> None:
        """Mark channels stale once they stop updating.

        PRD Part 4 section 7.1: a value that has stopped arriving must be
        annunciated, never left on screen looking current.
        """
        max_age = self.stale_after_intervals / self.telemetry_hz
        ecu = self.telemetry.ecu
        if ecu is not None:
            # An ECU that has stopped reporting is unknown, never healthy.
            ecu.stale = t - ecu.updated_t > max_age
            self.telemetry.ecu_error_flags = None if ecu.stale else ecu.error_flags
        for ch in self.telemetry.channels.values():
            if ch.lanes:
                self._resolve(ch, t)
                continue
            if ch.updated_t < 0:
                continue
            ch.age_s = t - ch.updated_t
            if ch.state in (ValueState.VALID, ValueState.SUSPECT) and ch.age_s > max_age:
                ch.state = ValueState.STALE
                ch.reason = f"no update for {ch.age_s:.2f} s"

    # ------------------------------------------------------------------
    def derived(self) -> dict[str, float]:
        """Quantities the twin needs that are computed, not transmitted.

        Injection-timing DEVIATION is the headline example: the bus carries the
        commanded value and the four measured values, and the deviation between
        them is what actually diagnoses an injector (PRD Part 2 section 10.2
        Method C).
        """
        t = self.telemetry
        out: dict[str, float] = {}

        cmd = t.get("injection_timing_cmd")
        if cmd is not None:
            devs = [
                t.get(f"injection_timing_{i}") - cmd
                for i in (1, 2, 3, 4)
                if t.get(f"injection_timing_{i}") is not None
            ]
            if devs:
                out["injection_timing_deviation_max"] = max(abs(d) for d in devs)
                out["injection_timing_deviation_spread"] = max(devs) - min(devs)

        cmd = t.get("ignition_timing_cmd")
        if cmd is not None:
            devs = [
                t.get(f"ignition_timing_{i}") - cmd
                for i in (1, 2, 3, 4)
                if t.get(f"ignition_timing_{i}") is not None
            ]
            if devs:
                out["ignition_timing_deviation_max"] = max(abs(d) for d in devs)

        for group in ("cht", "egt"):
            vals = [t.get(f"{group}_{i}") for i in (1, 2, 3, 4)]
            vals = [v for v in vals if v is not None]
            if len(vals) >= 2:
                out[f"{group}_spread"] = max(vals) - min(vals)

        vib = [t.get(f"vibration_rms_{a}") for a in ("x", "y", "z")]
        vib = [v for v in vib if v is not None]
        if vib:
            out["vibration_rms_total"] = math.sqrt(sum(v * v for v in vib))

        return out
