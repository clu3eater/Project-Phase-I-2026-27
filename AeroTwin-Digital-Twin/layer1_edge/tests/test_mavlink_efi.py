"""MAVLink EFI_STATUS downlink, held to the published protocol.

The constants these tests hold the module to come from outside it:

  * 0x6F91 -- the check value of CRC-16/MCRF4XX over "123456789", from the
    catalogue of parametrised CRC algorithms. MAVLink's checksum is that CRC.
  * 208 -- the CRC_EXTRA that the algorithm in mavlink.io's serialisation guide
    gives for the EFI_STATUS definition in mavlink/mavlink common.xml, worked
    from the XML independently of this module.
  * 65 and 73 -- the payload length in bytes without and with the two extension
    fields, from the same definition: sixteen floats and a uint8, then two
    floats.
"""

from __future__ import annotations

import math
import socket

import pytest

from layer1_edge import mavlink_efi as me
from layer1_edge.can_ingest import CanIngest, Channel, Telemetry, ValueState
from layer1_edge.can_simulator import CanSimulator
from layer2_physics.engine_sim import VirtualEngine, run_profile

FULL = {
    "rpm": 5120.0, "fuel_flow": 27.5, "throttle_pct": 78.0, "manifold_pressure": 1.21,
    "manifold_air_temperature": 38.0, "cht_max": 104.0, "ignition_timing_cmd": 26.0,
    "injection_period": 6.4, "egt_max": 842.0, "fuel_pressure": 3.02,
}


def _telemetry(t_s: float = 10.0, flags: int = 0, **values: float) -> Telemetry:
    tel = Telemetry(t_s=t_s, ecu_error_flags=flags)
    for name, v in values.items():
        tel.channels[name] = Channel(name=name, value=v, state=ValueState.VALID)
    return tel


def _values(tel: Telemetry, **kw) -> dict[str, float]:
    return me.EfiStatusSource().values(tel, **kw)


# ---------------------------------------------------------------------------
# The protocol
# ---------------------------------------------------------------------------


def test_the_checksum_is_the_crc_mavlink_uses():
    assert me.x25_crc(b"123456789") == 0x6F91


def test_crc_extra_and_lengths_match_the_published_definition():
    assert me.MSG_ID == 225
    assert me.CRC_EXTRA == 208
    assert me.BASE_PAYLOAD_LEN == 65
    assert me.PAYLOAD_LEN == 73


def test_fields_go_on_the_wire_largest_first_with_extensions_last():
    """The uint8 health field is declared first but travels after every float."""
    assert me.NAMES[:2] == ("ecu_index", "rpm")
    assert me.NAMES.index("health") == 16
    assert me.NAMES[-2:] == ("ignition_voltage", "fuel_pressure")


def test_a_packet_decodes_to_the_values_that_were_sent():
    vals = _values(_telemetry(**FULL))
    got = me.decode(me.encode(vals, seq=42, system_id=3, component_id=1))
    assert got is not None
    assert (got["seq"], got["system_id"], got["component_id"]) == (42, 3, 1)
    for name in me.NAMES:
        if math.isnan(vals[name]):
            assert math.isnan(got[name]), name
        else:
            assert got[name] == pytest.approx(vals[name], rel=1e-6, abs=1e-4), name


def test_trailing_zero_bytes_are_truncated_and_restored():
    """MAVLink 2 senders must drop trailing zero bytes; receivers pad them back.

    With both extension fields at their "unknown" zero, the eight extension
    bytes go and the non-zero health byte is where truncation stops.
    """
    no_fuel_pressure = {k: v for k, v in FULL.items() if k != "fuel_pressure"}
    vals = _values(_telemetry(**no_fuel_pressure))
    assert vals["ignition_voltage"] == 0.0 and vals["fuel_pressure"] == 0.0
    packet = me.encode(vals, seq=0, system_id=1, component_id=1)
    assert packet[1] == me.BASE_PAYLOAD_LEN
    assert len(packet) == me.HEADER_LEN + me.BASE_PAYLOAD_LEN + me.CHECKSUM_LEN
    got = me.decode(packet)
    assert got is not None
    assert got["fuel_pressure"] == 0.0 and got["ignition_voltage"] == 0.0


def test_a_corrupted_foreign_or_signed_packet_is_refused():
    packet = me.encode(_values(_telemetry(**FULL)), seq=1, system_id=1, component_id=1)
    flipped = bytearray(packet)
    flipped[20] ^= 0x01
    foreign = bytearray(packet)
    foreign[7] = 0x00
    signed = bytearray(packet)
    signed[2] = 0x01
    assert me.decode(bytes(flipped)) is None
    assert me.decode(bytes(foreign)) is None
    assert me.decode(bytes(signed)) is None
    assert me.decode(packet[:-1]) is None


# ---------------------------------------------------------------------------
# What goes into it
# ---------------------------------------------------------------------------


def test_nothing_the_bus_does_not_carry_is_given_a_number():
    vals = _values(_telemetry(**FULL))
    for name in ("engine_load", "spark_dwell_time", "barometric_pressure",
                 "throttle_out", "pt_compensation"):
        assert math.isnan(vals[name]), name
    assert vals["ignition_voltage"] == 0.0

    # A channel the ingest layer rejected is not usable, so it is not sent.
    tel = _telemetry(**FULL)
    tel.channels["cht_max"].state = ValueState.INVALID
    assert math.isnan(_values(tel)["cylinder_head_temperature"])


def test_a_real_zero_fuel_pressure_is_not_sent_as_unknown():
    assert _values(_telemetry(**{**FULL, "fuel_pressure": 0.0}))["fuel_pressure"] == pytest.approx(1e-4)


def test_health_is_the_ecus_own_verdict_unless_the_caller_says_otherwise():
    assert _values(_telemetry(flags=0, **FULL))["health"] == 1
    assert _values(_telemetry(flags=4, **FULL))["health"] == 0
    assert _values(_telemetry(**FULL), healthy=False)["health"] == 0


def test_values_follow_decoded_can_telemetry_in_the_defined_units():
    channel = "dt_mavlink"
    sim = CanSimulator(interface="virtual", channel=channel)
    ing = CanIngest(interface="virtual", channel=channel)
    src = me.EfiStatusSource()
    consumed, last = 0.0, None
    try:
        for frame in run_profile(VirtualEngine(seed=3), dt=0.5, max_seconds=120.0):
            sim.send_frame(frame)
            tel = ing.poll(now=frame.t_s)
            vals = src.values(tel)
            flow = tel.get("fuel_flow")
            if flow is not None and last is not None:
                consumed += flow * 1000.0 / 3600.0 * (tel.t_s - last)
            last = tel.t_s
    finally:
        sim.close()
        ing.close()

    def same(sent: float, channel_name: str, scale: float = 1.0) -> None:
        v = tel.get(channel_name)
        if v is None:
            assert math.isnan(sent), channel_name
        else:
            assert sent == pytest.approx(v * scale), channel_name

    assert consumed > 0.0
    assert vals["fuel_consumed"] == pytest.approx(consumed)
    same(vals["rpm"], "rpm")
    same(vals["fuel_flow"], "fuel_flow", 1000.0 / 60.0)
    same(vals["intake_manifold_pressure"], "manifold_pressure", 100.0)
    same(vals["intake_manifold_temperature"], "manifold_air_temperature")
    same(vals["cylinder_head_temperature"], "cht_max")
    same(vals["exhaust_gas_temperature"], "egt_max")
    same(vals["ignition_timing"], "ignition_timing_cmd")
    same(vals["injection_time"], "injection_period")
    same(vals["throttle_position"], "throttle_pct")


# ---------------------------------------------------------------------------
# The downlink
# ---------------------------------------------------------------------------


def _receiver() -> socket.socket:
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.settimeout(2.0)
    return rx


def test_packets_cross_a_real_udp_socket_with_a_wrapping_sequence():
    rx = _receiver()
    link = me.EfiDownlink("127.0.0.1", rx.getsockname()[1], rate_hz=0, system_id=9)
    tel = _telemetry(**FULL)
    seqs = []
    try:
        for _ in range(257):
            assert link.maybe_send(tel)
        for _ in range(257):
            got = me.decode(rx.recv(512))
            assert got is not None and got["system_id"] == 9
            seqs.append(got["seq"])
    finally:
        link.close()
        rx.close()
    assert seqs == [i & 0xFF for i in range(257)]


def test_the_downlink_holds_its_rate_on_the_wall_clock():
    rx = _receiver()
    link = me.EfiDownlink("127.0.0.1", rx.getsockname()[1], rate_hz=1.0)
    tel = _telemetry(**FULL)
    try:
        assert link.maybe_send(tel)
        assert not link.maybe_send(tel)
        assert link.sent == 1
    finally:
        link.close()
        rx.close()


def test_the_downlink_is_off_unless_configured():
    assert me.EfiDownlink.from_config() is None
    link = me.EfiDownlink.from_config(
        {"mavlink": {"enabled": True, "host": "127.0.0.1", "port": 14550}})
    try:
        assert link is not None
        assert (link.system_id, link.component_id) == (1, 1)
    finally:
        if link is not None:
            link.close()
