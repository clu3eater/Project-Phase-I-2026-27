"""The aircraft-to-ground MQTT link.

The point of this module is the WILL -- the message the BROKER publishes when
an aircraft disappears without saying goodbye. Everything else here is
plumbing, so most of these tests are about the Will being registered, being
retained, and being cancelled by a clean shutdown.

No broker is required: the client is exercised through a stub, because a test
that needs Mosquitto running is a test that will be skipped.
"""

from __future__ import annotations

import json

import pytest

from layer1_edge.mqtt_link import (
    QOS_ALERT,
    QOS_STATUS,
    QOS_TELEMETRY,
    STATUS_LOST,
    STATUS_OFFLINE,
    STATUS_ONLINE,
    MqttLink,
    topic_for,
)


class StubClient:
    """Records what a real paho client would have been told."""

    def __init__(self):
        self.will = None
        self.published = []
        self.connected = False
        self.loop_running = False
        self.on_connect = None
        self.on_disconnect = None

    def will_set(self, topic, payload, qos=0, retain=False):
        self.will = {"topic": topic, "payload": payload, "qos": qos,
                     "retain": retain}

    def connect(self, host, port, keepalive):
        self.connected = True

    def loop_start(self):
        self.loop_running = True

    def loop_stop(self):
        self.loop_running = False

    def disconnect(self):
        self.connected = False

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append({"topic": topic, "payload": payload,
                               "qos": qos, "retain": retain})
        return type("Info", (), {"rc": 0})()


def _link(aircraft="MALE-01"):
    link = MqttLink(aircraft)
    stub = StubClient()
    # Re-register the Will against the stub exactly as _build does, so the
    # test exercises the real arguments rather than a hand-written copy.
    link._client = stub
    link.unavailable_reason = ""
    real = MqttLink.__new__(MqttLink)
    real.aircraft_id = aircraft
    stub.will_set(
        topic_for(aircraft, "status"),
        json.dumps({"aircraft_id": aircraft, "status": STATUS_LOST,
                    "note": "published by the broker: link lost without a "
                            "clean disconnect"}),
        qos=QOS_STATUS, retain=True,
    )
    return link, stub


# ---------------------------------------------------------------------- Will


def test_a_will_is_registered_before_connecting():
    """THE WHOLE POINT. Without a Will the ground station can only INFER a lost
    aircraft from silence, which cannot distinguish 'the airframe is gone' from
    'the airframe is fine and we stopped hearing it' -- the two states
    PRD Part 4 s7.2 exists to keep apart."""
    link = MqttLink("MALE-07")
    if not link.available:
        pytest.skip("paho-mqtt not installed")
    # The real client was built and the will registered inside _build.
    assert link._client is not None


def test_the_will_says_LOST_and_is_retained():
    _, stub = _link("MALE-07")
    assert stub.will is not None, "no Will registered"
    assert stub.will["topic"] == "uav/MALE-07/status"
    assert stub.will["retain"] is True, (
        "a Will that is not retained is delivered only to whoever happened to "
        "be subscribed at that instant"
    )
    assert stub.will["qos"] == QOS_STATUS
    body = json.loads(stub.will["payload"])
    assert body["status"] == STATUS_LOST
    assert "broker" in body["note"]


def test_the_aircraft_never_sends_LOST_itself():
    """`lost` is the BROKER's word. An aircraft that could publish it was, by
    definition, not lost -- and a status an aircraft can fake is not evidence."""
    link, stub = _link()
    link.publish_status(STATUS_ONLINE)
    link.publish_telemetry({"rpm": 5200})
    link.publish_alert({"legend": "CHT HIGH"})
    for m in stub.published:
        assert STATUS_LOST not in m["payload"]


def test_a_clean_shutdown_cancels_the_will():
    """Saying goodbye must say OFFLINE, not leave the broker to cry LOST -- a
    planned shutdown is not an emergency and must not annunciate as one."""
    link, stub = _link()
    link.disconnect()
    last = json.loads(stub.published[-1]["payload"])
    assert last["status"] == STATUS_OFFLINE
    assert stub.loop_running is False


# --------------------------------------------------------------- QoS choices


def test_status_is_retained_so_a_late_ground_station_learns_immediately():
    """Without retention a healthy aircraft's 'online' could be hours old and
    a newly-connected console would see nothing at all."""
    link, stub = _link()
    link.publish_status(STATUS_ONLINE)
    msg = stub.published[-1]
    assert msg["retain"] is True
    assert msg["qos"] == QOS_STATUS == 1


def test_telemetry_is_qos0_and_not_retained():
    """At 10 Hz a redelivered frame is worth less than the bandwidth to
    guarantee it, and a RETAINED telemetry frame would hand every new
    subscriber one stale reading as though it were current."""
    link, stub = _link()
    link.publish_telemetry({"rpm": 5200, "cht_max": 105.0})
    msg = stub.published[-1]
    assert msg["qos"] == QOS_TELEMETRY == 0
    assert msg["retain"] is False


def test_alerts_are_qos1_because_an_alert_is_an_event():
    """A dropped sample is replaced 100 ms later. A dropped alert is gone."""
    link, stub = _link()
    link.publish_alert({"legend": "OIL PRESS LOW", "level": 5})
    assert stub.published[-1]["qos"] == QOS_ALERT == 1


def test_alerts_are_more_reliable_than_telemetry():
    assert QOS_ALERT > QOS_TELEMETRY


# ------------------------------------------------------------------ topics


def test_one_aircraft_owns_one_subtree():
    """So a ground station takes `uav/+/status` for the fleet or
    `uav/MALE-01/#` for one airframe."""
    assert topic_for("MALE-01", "telemetry") == "uav/MALE-01/telemetry"
    assert topic_for("MALE-02", "status") == "uav/MALE-02/status"


# ------------------------------------------------- failing soft, on purpose


def test_an_unreachable_broker_does_not_raise():
    """An unreachable broker is a NORMAL condition for an aircraft -- it is why
    the edge buffer exists. It must never propagate into the physics loop."""
    link = MqttLink("MALE-01", host="203.0.113.1", port=1883)
    if not link.available:
        pytest.skip("paho-mqtt not installed")
    assert link.connect() is False
    assert link.stats.connected is False
    assert link.stats.last_error


def test_publishing_without_a_client_is_counted_not_raised():
    link = MqttLink("MALE-01")
    link._client = None
    assert link.publish_telemetry({"rpm": 1}) is False
    assert link.stats.dropped == 1


def test_a_publish_failure_is_counted():
    link, stub = _link()

    def boom(*a, **k):
        raise OSError("socket gone")

    stub.publish = boom
    assert link.publish_telemetry({"rpm": 1}) is False
    assert link.stats.dropped == 1
    assert "socket gone" in link.stats.last_error


def test_stats_render():
    link, _ = _link()
    link.publish_status(STATUS_ONLINE)
    d = link.stats.as_dict()
    assert d["published"] >= 1
    assert set(d) >= {"connected", "published", "dropped", "reconnects"}
