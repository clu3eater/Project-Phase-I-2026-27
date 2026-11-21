"""CAN transmitter -- puts the virtual engine on a real CAN bus.

WHAT THIS IS, AND WHAT IT IS NOT
--------------------------------
There is no physical engine in this project, so the data originates in the
physics model. But the TRANSPORT is not simulated: this module encodes real
CANaerospace frames with ``cantools`` and transmits them through ``python-can``
onto an actual bus object. The bus happens to be an in-process virtual bus.

That distinction is the whole point. ``python-can`` abstracts the interface, so
the bus is chosen by one configuration string:

    interface="virtual"    in-process, no hardware, no kernel module  (demo)
    interface="socketcan"  Linux SocketCAN, real or vcan0            (RPi/rig)
    interface="pcan"       PEAK PCAN-USB adapter                     (bench)

Nothing else in the system changes. The simulator encodes the same frames, the
ingest layer decodes the same frames, and the twin sees the same telemetry.
Swapping to a PiCAN2 on a real 915 iS Display CAN bus is a configuration edit,
not a rewrite -- which is what makes this a prototype of the real thing rather
than a mock-up of it.

Sanctioned by the problem statement ("Demonstration using SIMULATED OR REAL
engine datasets"), by PRD Part 1 section 3.3 ("Virtual CAN Bus Development
Environment ... without physical hardware") and by PRD Part 0 section 0.12,
which names the in-process python-can bus as the fallback when a demo machine
will not allow a kernel module. Decision D1.

CANAEROSPACE FRAME DISCIPLINE
-----------------------------
Every standard message carries the four-byte header the protocol requires:

    Node-ID       which unit transmitted this
    Data Type     2 = FLOAT
    Service Code  status of the data / transmitting unit
    Message Code  rolling counter, per message

The last two are not decoration. A dropped sensor sample is transmitted as a
GAP in the message-code sequence rather than as a silently substituted value,
so the receiver can tell "no data" from "zero" -- which is exactly the
distinction PRD Part 4 section 7.1 requires the HMI to make.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any

import can
import cantools

from common import config
from layer2_physics.engine_sim import SensorFrame

# CANaerospace node identifiers for the units on this bus.
NODE_ECU_A = 11
NODE_ECU_B = 12
NODE_HUMS = 20
NODE_VMC = 30

DATA_TYPE_FLOAT = 2

# ECU messages without a CANaerospace header. Either lane can send them, so they
# stop only when both lanes are off the bus.
_ECU_MESSAGES = frozenset({"ECU_COMMANDS", "ECU_STATUS", "MANIFOLD_AIR"})

# Service codes. 0 is "data valid"; anything else tells the receiver the
# transmitting unit knows something is wrong with this value.
SERVICE_OK = 0
SERVICE_DEGRADED = 1
SERVICE_INVALID = 2

KELVIN = 273.15


@dataclass
class SignalRoute:
    """Where one engineering value goes on the bus, and how often."""

    message: str
    signal: str
    node: int
    rate_hz: float
    convert: Any = None  # engineering units -> bus units


def _c_to_k(v: float) -> float:
    return v + KELVIN


def _bar_to_hpa(v: float) -> float:
    return v * 1000.0


class CanSimulator:
    """Encodes ``SensorFrame`` objects into CANaerospace frames and sends them."""

    def __init__(
        self,
        *,
        interface: str = "virtual",
        channel: str = "dt_engine",
        bitrate: int = 1_000_000,
        engine_key: str = "rotax_915is",
        receive_own_messages: bool = True,
    ) -> None:
        self.db = cantools.database.load_file(str(config.dbc_path()))
        self.engine = config.load_engine(engine_key)
        kwargs: dict[str, Any] = {"interface": interface, "channel": channel}
        if interface == "virtual":
            kwargs["receive_own_messages"] = receive_own_messages
        else:
            kwargs["bitrate"] = bitrate
        self.bus = can.Bus(**kwargs)
        self._message_code: dict[str, int] = {}
        self.frames_sent = 0
        self.frames_suppressed = 0
        self.encode_failures = 0
        self._last_sent: dict[str, float] = {}
        # FADEC nodes whose lane is off the bus this frame, and what they did
        # not send because of it.
        self._silent_nodes: set[int] = set()
        self.frames_lane_silent = 0

    # ------------------------------------------------------------------
    def close(self) -> None:
        self.bus.shutdown()

    def __enter__(self) -> CanSimulator:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    def _next_code(self, name: str) -> int:
        code = (self._message_code.get(name, -1) + 1) % 256
        self._message_code[name] = code
        return code

    def _send_float(
        self,
        message_name: str,
        signal_name: str,
        value: float | None,
        node: int,
        *,
        service: int = SERVICE_OK,
    ) -> bool:
        """Transmit one CANaerospace Normal Operation Data message.

        A ``None`` value means the instrument dropped the sample. We do NOT
        substitute a number: the frame is simply not transmitted, so the
        receiver sees a gap in the message-code sequence and can report the
        channel as stale rather than believing a fabricated reading.
        """
        if node in self._silent_nodes:
            self.frames_lane_silent += 1
            return False
        if value is None or not math.isfinite(value):
            self.frames_suppressed += 1
            return False
        msg = self.db.get_message_by_name(message_name)
        try:
            data = msg.encode(
                {
                    "NODE_ID": node,
                    "DATA_TYPE": DATA_TYPE_FLOAT,
                    "SERVICE_CODE": service,
                    "MESSAGE_CODE": self._next_code(message_name),
                    signal_name: float(value),
                }
            )
        except cantools.database.errors.EncodeError:
            # A value outside the bus definition must not take down the
            # transmitter. Suppress the frame and count it: the receiver sees a
            # message-code gap and reports the channel stale, which is the
            # honest outcome. Silently clamping would fabricate a reading.
            self.encode_failures += 1
            self.frames_suppressed += 1
            return False
        self.bus.send(can.Message(arbitration_id=msg.frame_id, data=data, is_extended_id=False))
        self.frames_sent += 1
        return True

    def _send_raw(self, message_name: str, values: dict[str, float]) -> bool:
        if message_name in _ECU_MESSAGES and {NODE_ECU_A, NODE_ECU_B} <= self._silent_nodes:
            self.frames_lane_silent += 1
            return False
        msg = self.db.get_message_by_name(message_name)
        clean = {k: v for k, v in values.items() if v is not None and math.isfinite(v)}
        if len(clean) != len(values):
            self.frames_suppressed += 1
            return False
        try:
            data = msg.encode(clean)
        except cantools.database.errors.EncodeError:
            self.encode_failures += 1
            self.frames_suppressed += 1
            return False
        self.bus.send(
            can.Message(arbitration_id=msg.frame_id, data=data, is_extended_id=False)
        )
        self.frames_sent += 1
        return True

    # ------------------------------------------------------------------
    def send_frame(self, f: SensorFrame) -> int:
        """Transmit one instant of telemetry. Returns the number of frames sent."""
        before = self.frames_sent
        self._silent_nodes = {
            node for node, up in zip((NODE_ECU_A, NODE_ECU_B), f.lanes_transmitting, strict=True)
            if not up
        }

        # --- ECS channel A: standard CANaerospace Normal Operation Data ----
        self._send_float("ECSA_ENGINE_SPEED", "ENGINE_SPEED", f.rpm, NODE_ECU_A)
        gear = float(self.engine["geometry"]["gear_ratio_crank_to_prop"])
        prop = f.rpm / gear if f.rpm is not None else None
        self._send_float("ECSA_PROPELLER_SPEED", "PROPELLER_SPEED", prop, NODE_ECU_A)

        egt_valid = [v for v in f.egt_c if v is not None]
        self._send_float(
            "ECSA_EGT", "EGT", _c_to_k(max(egt_valid)) if egt_valid else None, NODE_ECU_A
        )
        self._send_float("ECSA_FUEL_FLOW", "FUEL_FLOW", f.fuel_flow_lph, NODE_HUMS)
        self._send_float(
            "ECSA_MANIFOLD_PRESSURE",
            "MANIFOLD_PRESSURE",
            _bar_to_hpa(f.manifold_pressure_bar) if f.manifold_pressure_bar is not None else None,
            NODE_ECU_A,
        )
        # Oil pressure and oil temperature are Lane B sensors, so they travel on
        # their ECS channel B identifiers from the Lane B node. They used to go
        # out on channel-A identifiers stamped with the Lane B Node-ID, which no
        # receiver checking the transmitter could accept.
        self._send_float(
            "ECSB_OIL_PRESSURE",
            "OIL_PRESSURE",
            # `is not None`, not truthiness: 0.0 bar is a READING -- total oil
            # loss -- and must reach the OILP rules as a value. Treated as
            # missing, the frame was never sent and the most dangerous engine
            # failure surfaced as a caution-level DATA STALE (CAN-01).
            _bar_to_hpa(f.oil_pressure_bar) if f.oil_pressure_bar is not None else None,
            NODE_ECU_B,  # OPS is a Lane B sensor [IM Rev.5 failure matrix]
        )
        self._send_float(
            "ECSB_OIL_TEMPERATURE",
            "OIL_TEMPERATURE",
            _c_to_k(f.oil_temperature_c) if f.oil_temperature_c is not None else None,
            NODE_ECU_B,  # OTS is a Lane B sensor
        )
        cht_valid = [v for v in f.cht_c if v is not None]
        self._send_float(
            "ECSA_CHT", "CHT", _c_to_k(max(cht_valid)) if cht_valid else None, NODE_HUMS
        )
        self._send_float(
            "ECSA_COOLANT_TEMPERATURE",
            "COOLANT_TEMPERATURE",
            _c_to_k(f.coolant_temperature_c) if f.coolant_temperature_c is not None else None,
            NODE_ECU_A,  # CTS is a Lane A sensor
        )
        self._send_float(
            "FUEL_SYSTEM_PRESSURE",
            "FUEL_SYSTEM_PRESSURE",
            _bar_to_hpa(f.fuel_pressure_bar) if f.fuel_pressure_bar is not None else None,
            NODE_ECU_A,
        )
        self._send_float("DC_VOLTAGE", "DC_VOLTAGE", f.battery_voltage_v, NODE_ECU_A)
        self._send_float("DC_CURRENT", "DC_CURRENT", f.alternator_current_a, NODE_ECU_A)
        self._send_float(
            "BATTERY_CURRENT", "BATTERY_CURRENT", f.battery_current_a, NODE_ECU_A
        )

        # --- ECS channel B: the redundant FADEC lane ------------------------
        # Both lanes measure the redundant sensors independently, which gives
        # the ingest layer a genuine two-source cross-check [OM section 7.5.1].
        # Lane B's OWN sensors. These were lane A's numbers sent twice, so the
        # two lanes could never disagree and the cross-check detected nothing.
        self._send_float("ECSB_ENGINE_SPEED", "ENGINE_SPEED", f.rpm_lane_b, NODE_ECU_B)
        self._send_float(
            "ECSB_MANIFOLD_PRESSURE",
            "MANIFOLD_PRESSURE",
            _bar_to_hpa(f.manifold_pressure_bar_lane_b)
            if f.manifold_pressure_bar_lane_b is not None else None,
            NODE_ECU_B,
        )

        # --- HUMS extensions, user-defined range ----------------------------
        self._send_raw(
            "CHT_PER_CYLINDER",
            {f"CHT_CYL{i + 1}": _c_to_k(v) for i, v in enumerate(f.cht_c) if v is not None}
            if all(v is not None for v in f.cht_c)
            else {"CHT_CYL1": None},  # type: ignore[dict-item]
        )
        self._send_raw(
            "EGT_PER_CYLINDER",
            {f"EGT_CYL{i + 1}": _c_to_k(v) for i, v in enumerate(f.egt_c) if v is not None}
            if all(v is not None for v in f.egt_c)
            else {"EGT_CYL1": None},  # type: ignore[dict-item]
        )
        if all(v is not None for v in f.vibration_rms) and f.vibration_kurtosis is not None:
            self._send_raw(
                "VIBRATION",
                {
                    "VIB_RMS_X": f.vibration_rms[0],
                    "VIB_RMS_Y": f.vibration_rms[1],
                    "VIB_RMS_Z": f.vibration_rms[2],
                    "VIB_KURTOSIS": f.vibration_kurtosis,
                },
            )
        if all(v is not None for v in f.injection_timing_deg):
            self._send_raw(
                "INJECTION_TIMING",
                {f"INJ_TIMING_CYL{i + 1}": v for i, v in enumerate(f.injection_timing_deg)},
            )
        if all(v is not None for v in f.ignition_timing_deg):
            self._send_raw(
                "IGNITION_TIMING",
                {f"IGN_TIMING_CYL{i + 1}": v for i, v in enumerate(f.ignition_timing_deg)},
            )
        self._send_raw(
            "ECU_COMMANDS",
            {
                "IGN_TIMING_CMD": f.ignition_timing_cmd_deg,
                "INJ_TIMING_CMD": f.injection_timing_cmd_deg,
                "INJECTION_PERIOD": f.injection_period_ms,
                "KNOCK_INTENSITY": f.knock_intensity,
            },
        )
        self._send_raw(
            "ECU_STATUS",
            {
                "ECU_MODE": f.ecu_mode,
                "ACTIVE_LANE": f.active_lane,
                "LANE_A_HEALTH": f.lane_a_health,
                "LANE_B_HEALTH": f.lane_b_health,
                "WARN_LAMP_A": f.warn_lamp_a,
                "WARN_LAMP_B": f.warn_lamp_b,
                "ECU_ERROR_FLAGS": f.ecu_error_flags,
                "THROTTLE_POS": f.throttle_pct,
                "WASTEGATE_POS": f.wastegate_pct,
                "KNOCK_RETARD": f.knock_retard_deg,
                "ECU_SEQ_COUNTER": self._next_code("ECU_STATUS"),
            },
        )
        self._send_raw(
            "MANIFOLD_AIR",
            {
                "MAT1": f.manifold_air_temp_c,
                "MAT2": f.manifold_air_temp_c_lane_b,  # lane B's MATS
                "AIR_FLOW": f.air_flow_g_per_min,
                "INJECTOR_DUTY": 100.0 * f.injector_duty,
            },
        )
        # The airframe's own actuators. Where a losing radiator shows first.
        self._send_raw(
            "AIRFRAME_COOLING",
            {"COOLING_FLAP_PCT": f.cooling_flap_pct,
             "OIL_FLAP_PCT": f.oil_flap_pct},
        )
        self._send_raw(
            "AIR_DATA",
            {
                "ALTITUDE_FT": f.altitude_ft,
                "OAT": f.oat_c,
                "AIRSPEED_KMH": f.airspeed_kmh,
                "HUMIDITY": f.humidity_pct,
                "FLIGHT_PHASE": f.flight_phase,
            },
        )
        return self.frames_sent - before

    # ------------------------------------------------------------------
    def bus_load_fraction(self, frames_per_second: float, bitrate: int = 1_000_000) -> float:
        """Estimated bus utilisation.

        A standard 11-bit CAN frame with 8 data bytes is 64 data bits plus
        roughly 47 bits of arbitration, control, CRC, ACK and inter-frame
        space, before bit stuffing.
        """
        return frames_per_second * (64 + 47) / bitrate


def stream(
    veng: Any,
    sim: CanSimulator,
    *,
    dt: float = 0.1,
    max_seconds: float | None = None,
    realtime: bool = False,
):
    """Step the virtual engine and transmit each frame. Yields the sent frames."""
    from layer2_physics.engine_sim import run_profile

    for frame in run_profile(veng, dt=dt, max_seconds=max_seconds):
        sim.send_frame(frame)
        if realtime:
            time.sleep(dt)
        yield frame
