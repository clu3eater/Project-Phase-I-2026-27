"""The aircraft-to-ground telemetry link -- MQTT, and specifically its Will.

WHY THIS EXISTS
---------------
DEV-161 recorded MQTT as an open gap and explained why it is not the same
question as the WebSocket the console already uses. Two different links were
being conflated:

  ground server -> browser   WebSocket. Correct: browser-native, one
                             connection, already inside TLS, and the console
                             wants a complete snapshot rather than a topic
                             subscription.

  AIRCRAFT -> ground         Lossy, intermittent, and out of the aircraft's
                             control. This is the hop MQTT is built for.

THE FEATURE THAT MATTERS IS THE WILL
------------------------------------
`edge_buffer.note_link` currently infers a lost aircraft from a TIMEOUT -- no
frame has arrived for N seconds, so assume the worst. That is strictly weaker
than knowing, and it confuses two states a crew station must keep apart
(PRD Part 4 s7.2): "the aircraft is gone" and "the aircraft is fine and the
ground station stopped hearing it".

MQTT's Last Will and Testament closes that. The aircraft registers a message
WITH THE BROKER at connect time; if the connection drops without a clean
disconnect, the broker publishes it on the aircraft's behalf. The ground
station is TOLD the airframe went, by a third party that was watching, rather
than inferring it from silence. Nothing in a WebSocket or a reconnect timer
provides that.

QoS AND RETENTION, AND WHY EACH IS SET WHERE IT IS
---------------------------------------------------
  status     QoS 1, RETAINED. A ground station that connects late must learn
             immediately whether the aircraft is up; a retained message is
             delivered on subscribe rather than at the next change, which for
             a healthy aircraft could be hours.
  telemetry  QoS 0. At 10 Hz, a redelivered frame is worth less than the
             bandwidth to guarantee it -- the next one is 100 ms behind, and
             `edge_buffer` already holds 72 hours for the gaps that matter.
  alerts     QoS 1. An alert is not a sample. Losing one is losing the event.

WHAT THIS DOES NOT DO
---------------------
It does not replace `edge_buffer`. The buffer is the aircraft's own
store-and-forward and remains the thing that survives a power loss; MQTT is the
transport over which it drains. If the broker is unreachable this module
reports that and the buffer keeps accumulating, which is exactly the behaviour
that shipped before.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

_log = logging.getLogger(__name__)


def secure_client(client) -> None:
    """Broker credentials and TLS for a paho client, from the environment.

    SEC-05: the MQTT link connected with no TLS and no login, so telemetry and
    commands crossed the network in clear text to any broker that answered.
    Credentials and certificates come from the environment so no secret sits
    in code or config: DT_MQTT_USERNAME / DT_MQTT_PASSWORD, and DT_MQTT_TLS_CA
    (plus DT_MQTT_TLS_CERT / DT_MQTT_TLS_KEY for mutual TLS). With no CA set the
    link stays plaintext and the log says so.
    """
    import os
    import ssl

    user = os.environ.get("DT_MQTT_USERNAME")
    if user:
        client.username_pw_set(user, os.environ.get("DT_MQTT_PASSWORD", ""))
    ca = os.environ.get("DT_MQTT_TLS_CA")
    if ca:
        client.tls_set(
            ca_certs=ca,
            certfile=os.environ.get("DT_MQTT_TLS_CERT") or None,
            keyfile=os.environ.get("DT_MQTT_TLS_KEY") or None,
            tls_version=ssl.PROTOCOL_TLS_CLIENT,
        )
    else:
        _log.info("MQTT link without TLS: set DT_MQTT_TLS_CA to encrypt it")


# Topic tree. One aircraft owns one subtree, so a ground station subscribes to
# `uav/+/status` for the whole fleet or `uav/MALE-01/#` for one airframe.
TOPIC_ROOT = "uav"


def topic_for(aircraft_id: str, leaf: str) -> str:
    return f"{TOPIC_ROOT}/{aircraft_id}/{leaf}"


# The Will. Published BY THE BROKER if the aircraft disappears without saying
# goodbye -- which is what an aircraft losing its link does.
STATUS_ONLINE = "online"
STATUS_OFFLINE = "offline"
STATUS_LOST = "lost"          # broker-published; the aircraft never sends this

QOS_STATUS = 1
QOS_TELEMETRY = 0
QOS_ALERT = 1


@dataclass
class LinkStats:
    connected: bool = False
    published: int = 0
    dropped: int = 0
    last_error: str = ""
    connected_since: float | None = None
    reconnects: int = 0

    def as_dict(self) -> dict:
        return {
            "connected": self.connected,
            "published": self.published,
            "dropped": self.dropped,
            "last_error": self.last_error,
            "reconnects": self.reconnects,
            "uptime_s": (None if self.connected_since is None
                         else round(time.time() - self.connected_since, 1)),
        }


class MqttLink:
    """Publishes one aircraft's telemetry, with a Will registered at connect.

    Deliberately fails soft. An unreachable broker is a normal condition for an
    aircraft -- it is why the buffer exists -- so every method reports and
    carries on rather than raising into the physics loop. `available` says
    whether the client library is even installed.
    """

    def __init__(
        self,
        aircraft_id: str = "MALE-01",
        *,
        host: str = "127.0.0.1",
        port: int = 1883,
        keepalive: int = 30,
        client_id: str | None = None,
    ) -> None:
        self.aircraft_id = aircraft_id
        self.host = host
        self.port = port
        # Keepalive sets how fast the Will fires: the broker declares the
        # client gone after 1.5x this with no traffic. 30 s gives a 45 s
        # detection, comfortably inside the link_degraded/link_lost timeouts
        # the console already annunciates against.
        self.keepalive = int(keepalive)
        self.client_id = client_id or f"twin-{aircraft_id}"
        self.stats = LinkStats()
        self._client = None
        self.unavailable_reason = ""
        self._build()

    # -- lifecycle ----------------------------------------------------------

    def _build(self) -> None:
        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:
            self.unavailable_reason = f"paho-mqtt not installed: {exc}"
            _log.info("MQTT link unavailable: %s", self.unavailable_reason)
            return

        try:
            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2, client_id=self.client_id,
                clean_session=False,
            )
        except (AttributeError, TypeError):
            # paho 1.x has no CallbackAPIVersion. Supported because a defence
            # deployment does not always get to choose its library version.
            client = mqtt.Client(client_id=self.client_id, clean_session=False)

        # THE WILL, registered before connecting. From here on the broker
        # speaks for this aircraft if it stops speaking for itself.
        client.will_set(
            topic_for(self.aircraft_id, "status"),
            json.dumps({"aircraft_id": self.aircraft_id,
                        "status": STATUS_LOST,
                        "note": "published by the broker: link lost without a "
                                "clean disconnect"}),
            qos=QOS_STATUS,
            retain=True,
        )
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        secure_client(client)
        self._client = client

    @property
    def available(self) -> bool:
        return self._client is not None

    def connect(self) -> bool:
        if not self.available:
            return False
        try:
            self._client.connect(self.host, self.port, self.keepalive)
            self._client.loop_start()
            return True
        except Exception as exc:  # noqa: BLE001 - reported, not handled
            self.stats.last_error = str(exc)
            _log.info("MQTT broker unreachable at %s:%s (%s); the edge buffer "
                      "keeps accumulating", self.host, self.port, exc)
            return False

    def disconnect(self) -> None:
        """A CLEAN goodbye, which tells the broker NOT to fire the Will."""
        if not self.available:
            return
        try:
            self.publish_status(STATUS_OFFLINE)
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:  # noqa: BLE001
            _log.debug("MQTT disconnect failed; the Will will fire instead")

    # -- callbacks ----------------------------------------------------------

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        ok = (getattr(reason_code, "value", reason_code) == 0)
        self.stats.connected = bool(ok)
        if ok:
            if self.stats.connected_since is None:
                self.stats.connected_since = time.time()
            else:
                self.stats.reconnects += 1
            self.publish_status(STATUS_ONLINE)
            _log.info("MQTT connected to %s:%s as %s",
                      self.host, self.port, self.client_id)

    def _on_disconnect(self, client, userdata, *args):
        self.stats.connected = False
        _log.info("MQTT disconnected; the broker will publish the Will if this "
                  "was not a clean shutdown")

    # -- publishing ---------------------------------------------------------

    def _publish(self, leaf: str, payload: Any, *, qos: int, retain: bool) -> bool:
        if not self.available or self._client is None:
            self.stats.dropped += 1
            return False
        try:
            info = self._client.publish(
                topic_for(self.aircraft_id, leaf),
                json.dumps(payload, default=str),
                qos=qos, retain=retain,
            )
            if getattr(info, "rc", 0) != 0:
                self.stats.dropped += 1
                return False
            self.stats.published += 1
            return True
        except Exception as exc:  # noqa: BLE001 - a link fault must not stop
            self.stats.dropped += 1                       # the engine
            self.stats.last_error = str(exc)
            return False

    def publish_status(self, status: str) -> bool:
        """Retained, so a ground station learns the state the moment it joins."""
        return self._publish(
            "status",
            {"aircraft_id": self.aircraft_id, "status": status,
             "t_utc": time.time()},
            qos=QOS_STATUS, retain=True,
        )

    def publish_telemetry(self, frame: dict) -> bool:
        """QoS 0: the next frame is 100 ms behind, and the buffer holds 72 h."""
        return self._publish("telemetry", frame, qos=QOS_TELEMETRY, retain=False)

    def publish_alert(self, alert: dict) -> bool:
        """QoS 1: an alert is an EVENT. Losing one is losing the thing itself."""
        return self._publish("alerts", alert, qos=QOS_ALERT, retain=False)


def subscribe_fleet(
    on_status: Callable[[str, dict], None],
    *,
    host: str = "127.0.0.1",
    port: int = 1883,
    client_id: str = "gcs-fleet-watch",
):
    """Ground-station side: watch every aircraft's status topic.

    Returns the started client, or None where paho is absent. The callback
    receives `(aircraft_id, payload)` and will be handed `status="lost"` by the
    BROKER when an airframe drops -- the message this whole module exists for.
    """
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        _log.info("paho-mqtt not installed; fleet watch unavailable")
        return None

    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    except (AttributeError, TypeError):
        client = mqtt.Client(client_id=client_id)

    def _on_connect(c, u, flags, reason_code, properties=None):
        c.subscribe(f"{TOPIC_ROOT}/+/status", qos=QOS_STATUS)

    def _on_message(c, u, msg):
        parts = msg.topic.split("/")
        aircraft = parts[1] if len(parts) > 2 else "?"
        try:
            on_status(aircraft, json.loads(msg.payload.decode("utf-8")))
        except Exception:  # noqa: BLE001
            _log.exception("fleet status callback failed for %s", aircraft)

    client.on_connect = _on_connect
    client.on_message = _on_message
    secure_client(client)
    try:
        client.connect(host, port, 30)
        client.loop_start()
        return client
    except Exception as exc:  # noqa: BLE001
        _log.info("MQTT broker unreachable for fleet watch: %s", exc)
        return None


__all__ = [
    "QOS_ALERT",
    "QOS_STATUS",
    "QOS_TELEMETRY",
    "STATUS_LOST",
    "STATUS_OFFLINE",
    "STATUS_ONLINE",
    "TOPIC_ROOT",
    "LinkStats",
    "MqttLink",
    "subscribe_fleet",
    "topic_for",
]
