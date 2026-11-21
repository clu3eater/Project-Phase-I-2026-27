"""MAVLink 2 EFI_STATUS -- the engine's state in a ground station's language.

WHY THIS EXISTS
---------------
The CAN bus is how the ENGINE talks. A ground control station talks MAVLink.
The problem statement asks for ECU/FADEC communication interfaces and for a
twin that can sit in a defence GCS, and the architecture diagram has shown a
"MAVLink bridge" since the first draft with no code behind it. This is that
bridge, for the one message MAVLink defines for an engine: EFI_STATUS, id 225,
"EFI status output". QGroundControl and Mission Planner decode it as it arrives,
so nothing on the ground has to know this project exists.

THE MESSAGE IS THE PUBLISHED ONE, AND THAT IS CHECKED
------------------------------------------------------
`FIELDS` and `EXTENSIONS` are copied from mavlink/mavlink,
message_definitions/v1.0/common.xml (read 2026-09-15), in declaration order.
The byte layout follows mavlink.io/en/guide/serialization.html:

  * fields go on the wire largest type first, keeping declaration order within
    a size; extension fields follow, in declaration order;
  * CRC_EXTRA is the X.25 CRC of "EFI_STATUS " followed by "type name " for
    each non-extension field in wire order, folded to one byte;
  * trailing zero bytes of the payload are truncated before sending, and the
    receiver pads them back.

CRC_EXTRA is COMPUTED from the field list rather than typed in. A slip in
copying the list then fails the test against the published value, instead of
producing packets that every ground station silently discards.

NOTHING IS MADE UP TO FILL A FIELD
----------------------------------
EFI_STATUS has seventeen values and this engine's bus does not carry all of
them: there is no ambient pressure channel, no spark dwell, no ECU load figure
and no throttle output separate from the lever position. Those go out as NaN.
A plausible constant in a field a ground station plots is a fabricated
reading, which PRD Part 4 section 7.2 forbids. The two extension fields whose
definition reserves zero for "unknown", ignition_voltage and fuel_pressure, use
zero as the definition says; a fuel pressure that genuinely reads zero goes
out as 0.0001 kPa, also as the definition says.

Every other value is a validated channel from `CanIngest`, converted to the
unit the definition names. An invalid or stale channel is not usable, so it
goes out as NaN as well. EFI_STATUS has one head temperature and one exhaust
temperature; the hottest cylinder is sent, because that is the one a limit
applies to.
"""

from __future__ import annotations

import math
import socket
import struct
import time
from dataclasses import dataclass

from common import config

MSG_ID = 225
MSG_NAME = "EFI_STATUS"
MAGIC_V2 = 0xFD
HEADER_LEN = 10
CHECKSUM_LEN = 2

_SIZE = {"float": 4, "uint8_t": 1}
_CODE = {"float": "f", "uint8_t": "B"}

# (type, name, units), in common.xml declaration order.
FIELDS: tuple[tuple[str, str, str], ...] = (
    ("uint8_t", "health", ""),
    ("float", "ecu_index", ""),
    ("float", "rpm", ""),
    ("float", "fuel_consumed", "cm^3"),
    ("float", "fuel_flow", "cm^3/min"),
    ("float", "engine_load", "%"),
    ("float", "throttle_position", "%"),
    ("float", "spark_dwell_time", "ms"),
    ("float", "barometric_pressure", "kPa"),
    ("float", "intake_manifold_pressure", "kPa"),
    ("float", "intake_manifold_temperature", "degC"),
    ("float", "cylinder_head_temperature", "degC"),
    ("float", "ignition_timing", "deg"),
    ("float", "injection_time", "ms"),
    ("float", "exhaust_gas_temperature", "degC"),
    ("float", "throttle_out", "%"),
    ("float", "pt_compensation", ""),
)
# After <extensions/>: sent last, in this order, and not part of CRC_EXTRA.
EXTENSIONS: tuple[tuple[str, str, str], ...] = (
    ("float", "ignition_voltage", "V"),
    ("float", "fuel_pressure", "kPa"),
)


def x25_crc(data: bytes, crc: int = 0xFFFF) -> int:
    """MAVLink's checksum, CRC-16/MCRF4XX, accumulated byte by byte.

    Written the way MAVLink's checksum.h accumulates it, so one running value
    can be carried across the header, the payload and the CRC_EXTRA byte.
    """
    for byte in data:
        tmp = byte ^ (crc & 0xFF)
        tmp = (tmp ^ (tmp << 4)) & 0xFF
        crc = ((crc >> 8) ^ (tmp << 8) ^ (tmp << 3) ^ (tmp >> 4)) & 0xFFFF
    return crc


def wire_order(fields: tuple[tuple[str, str, str], ...]) -> tuple[tuple[str, str, str], ...]:
    """Largest type first. `sorted` is stable, so declaration order holds within a size."""
    return tuple(sorted(fields, key=lambda f: -_SIZE[f[0]]))


def crc_extra(name: str, fields: tuple[tuple[str, str, str], ...]) -> int:
    """The per-message seed byte, from the message's own definition."""
    text = name + " " + "".join(f"{t} {n} " for t, n, _ in wire_order(fields))
    crc = x25_crc(text.encode("ascii"))
    return (crc & 0xFF) ^ (crc >> 8)


WIRE = wire_order(FIELDS) + EXTENSIONS
NAMES = tuple(n for _, n, _ in WIRE)
CRC_EXTRA = crc_extra(MSG_NAME, FIELDS)
_FORMAT = "<" + "".join(_CODE[t] for t, _, _ in WIRE)
PAYLOAD_LEN = struct.calcsize(_FORMAT)
BASE_PAYLOAD_LEN = sum(_SIZE[t] for t, _, _ in FIELDS)


def encode(values: dict[str, float], *, seq: int, system_id: int, component_id: int) -> bytes:
    """One complete MAVLink 2 EFI_STATUS packet, unsigned."""
    missing = [n for n in NAMES if n not in values]
    if missing:
        raise KeyError(f"EFI_STATUS needs {missing}")
    if not (1 <= system_id <= 255 and 1 <= component_id <= 255):
        raise ValueError("MAVLink system and component ids are 1-255")
    health = int(values["health"])
    payload = struct.pack(
        _FORMAT, *(health if n == "health" else float(values[n]) for n in NAMES)
    )
    # MAVLink 2 truncates trailing zero bytes; the first byte is never removed.
    end = len(payload)
    while end > 1 and payload[end - 1] == 0:
        end -= 1
    payload = payload[:end]
    header = bytes((
        MAGIC_V2, len(payload), 0, 0, seq & 0xFF, system_id, component_id,
        MSG_ID & 0xFF, (MSG_ID >> 8) & 0xFF, (MSG_ID >> 16) & 0xFF,
    ))
    crc = x25_crc(bytes((CRC_EXTRA,)), x25_crc(header[1:] + payload))
    return header + payload + struct.pack("<H", crc)


def decode(packet: bytes) -> dict[str, float] | None:
    """The fields of an EFI_STATUS packet, or None if it is not a valid one.

    Signed packets (incompatibility flag set) are refused rather than parsed
    with the signature mistaken for payload.
    """
    if len(packet) < HEADER_LEN + CHECKSUM_LEN or packet[0] != MAGIC_V2:
        return None
    n = packet[1]
    if packet[2] != 0 or len(packet) < HEADER_LEN + n + CHECKSUM_LEN:
        return None
    if packet[7] | packet[8] << 8 | packet[9] << 16 != MSG_ID:
        return None
    crc = x25_crc(bytes((CRC_EXTRA,)), x25_crc(packet[1:HEADER_LEN + n]))
    if struct.unpack_from("<H", packet, HEADER_LEN + n)[0] != crc:
        return None
    body = packet[HEADER_LEN:HEADER_LEN + n].ljust(PAYLOAD_LEN, b"\0")[:PAYLOAD_LEN]
    out: dict[str, float] = dict(zip(NAMES, struct.unpack(_FORMAT, body), strict=True))
    out["seq"] = packet[4]
    out["system_id"] = packet[5]
    out["component_id"] = packet[6]
    return out


@dataclass
class EfiStatusSource:
    """Builds EFI_STATUS values from validated CAN telemetry.

    Call `values` on every telemetry update, not only when a packet is due:
    fuel consumed is integrated from the measured fuel flow, and skipping ticks
    would drop fuel. It counts fuel only while the flow channel is valid, so
    after a fuel-flow sensor fault the total is a floor, not an estimate.
    """

    ecu_index: float = 0.0
    fuel_consumed_cm3: float = 0.0
    _last_t: float | None = None

    def values(self, tel, *, healthy: bool | None = None) -> dict[str, float]:
        nan = math.nan

        def got(name: str, scale: float = 1.0) -> float:
            v = tel.get(name)
            return nan if v is None else float(v) * scale

        t = float(tel.t_s)
        flow_lph = tel.get("fuel_flow")
        if flow_lph is not None and self._last_t is not None and t > self._last_t:
            self.fuel_consumed_cm3 += float(flow_lph) * 1000.0 / 3600.0 * (t - self._last_t)
        self._last_t = t

        bar = tel.get("fuel_pressure")
        if bar is None:
            fuel_kpa = 0.0  # the definition's "unknown"
        else:
            fuel_kpa = float(bar) * 100.0
            if fuel_kpa == 0.0:
                fuel_kpa = 0.0001  # a real zero, as the definition asks

        if healthy is None:
            # The ECU's own verdict on itself, which is what an EFI reports. No
            # report, or none recently (flags None), is not a healthy ECU.
            healthy = getattr(tel, "ecu_error_flags", None) == 0

        return {
            "health": 1 if healthy else 0,
            "ecu_index": float(self.ecu_index),
            "rpm": got("rpm"),
            "fuel_consumed": self.fuel_consumed_cm3,
            "fuel_flow": got("fuel_flow", 1000.0 / 60.0),
            "engine_load": nan,
            "throttle_position": got("throttle_pct"),
            "spark_dwell_time": nan,
            "barometric_pressure": nan,
            "intake_manifold_pressure": got("manifold_pressure", 100.0),
            "intake_manifold_temperature": got("manifold_air_temperature"),
            "cylinder_head_temperature": got("cht_max"),
            "ignition_timing": got("ignition_timing_cmd"),
            "injection_time": got("injection_period"),
            "exhaust_gas_temperature": got("egt_max"),
            "throttle_out": nan,
            "pt_compensation": nan,
            "ignition_voltage": 0.0,  # not on this bus; zero is "unknown"
            "fuel_pressure": fuel_kpa,
        }


class EfiDownlink:
    """Sends EFI_STATUS over UDP to a ground station, at a wall-clock rate.

    The rate is on the wall clock, not the simulated one: the live twin runs
    faster than real time, and a ground station cares how many packets reach
    it per second. `rate_hz` of 0 sends on every call.
    """

    def __init__(
        self,
        host: str,
        port: int,
        *,
        rate_hz: float = 2.0,
        system_id: int = 1,
        component_id: int = 1,
    ) -> None:
        self._addr = (host, int(port))
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._period = 0.0 if not rate_hz else 1.0 / float(rate_hz)
        self._next: float | None = None
        self.system_id = int(system_id)
        self.component_id = int(component_id)
        self.seq = 0
        self.sent = 0
        self.send_errors = 0
        self.source = EfiStatusSource()

    @classmethod
    def from_config(cls, thresholds: dict | None = None) -> EfiDownlink | None:
        """The configured downlink, or None when it is switched off."""
        cfg = (thresholds or config.load_thresholds()).get("mavlink") or {}
        if not cfg.get("enabled"):
            return None
        return cls(
            str(cfg["host"]), int(cfg["port"]),
            rate_hz=float(cfg.get("rate_hz", 2.0)),
            system_id=int(cfg.get("system_id", 1)),
            component_id=int(cfg.get("component_id", 1)),
        )

    def maybe_send(self, tel, *, healthy: bool | None = None) -> bool:
        """Fold this telemetry in; send a packet if one is due. True if sent."""
        values = self.source.values(tel, healthy=healthy)
        now = time.monotonic()
        if self._next is not None and now < self._next:
            return False
        self._next = now + self._period
        packet = encode(values, seq=self.seq, system_id=self.system_id,
                        component_id=self.component_id)
        self.seq = (self.seq + 1) & 0xFF
        try:
            self._sock.sendto(packet, self._addr)
        except OSError:
            # A ground station that is not listening must not stop the twin.
            self.send_errors += 1
            return False
        self.sent += 1
        return True

    def close(self) -> None:
        self._sock.close()


__all__ = [
    "CRC_EXTRA", "EXTENSIONS", "EfiDownlink", "EfiStatusSource", "FIELDS", "MSG_ID",
    "PAYLOAD_LEN", "crc_extra", "decode", "encode", "x25_crc",
]
