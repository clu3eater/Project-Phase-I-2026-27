"""Authenticated telemetry over an untrusted link -- PS "Secure telemetry
architecture", PRD Part 3 s20 threats 1 and 3.

WHAT WAS ALREADY COVERED, AND WHAT WAS NOT
-------------------------------------------
Part 3 s20.1 lists five threats. Three were already answered:

    THREAT 2  unauthorised access   JWT RS256 + RBAC, server-side (security.py)
    THREAT 4  denial of service     RateLimiter on every authenticated route
    THREAT 5  insider misuse        SHA-256 hash-chained audit log

Two were not, and both are about the DOWNLINK rather than the console:

    THREAT 1  interception          the telemetry stream was plain
    THREAT 3  tampering             nothing bound a frame to its origin

This module answers threat 3, and the TLS configuration in ``twin_api`` answers
threat 1. They are separate mechanisms because they defend different things:
TLS stops a passive listener reading the stream, and stops nothing at all once
an endpoint is impersonated. Authentication of the frames themselves is what
survives a terminated TLS session, a replayed capture, or a compromised relay
in between -- and a UAV downlink passes through relays by design.

WHY HMAC AND NOT THE RSA KEY THE API ALREADY HAS
-------------------------------------------------
The console's tokens are RS256 because a token is verified by parties who must
not be able to mint one. Telemetry is the opposite situation: the two endpoints
are the airframe and its own ground station, a key can be provisioned into the
airframe at build, and the frame rate is 2 Hz sustained for a twelve-hour
sortie. An RSA signature per frame would cost milliseconds of edge CPU for a
property a MAC gives in microseconds.

So this is HMAC-SHA256 with a per-airframe key. It authenticates the sender and
detects any modification; it deliberately does NOT provide non-repudiation,
because with a symmetric key the ground station could have produced the frame
itself. Where non-repudiation is the requirement -- the maintenance record --
this system uses the hash-chained audit log instead, which is the right tool
for that and is already built.

REPLAY IS A SEPARATE ATTACK AND NEEDS A SEPARATE ANSWER
--------------------------------------------------------
A MAC proves a frame is authentic. It says nothing about WHEN, so a captured
frame stays valid for ever and an adversary can hold a healthy engine's
telemetry and replay it over a failing one -- which defeats the entire health
monitoring system while every signature verifies.

Each frame therefore carries a strictly increasing sequence number inside the
authenticated payload, and the verifier refuses anything not ahead of what it
has already accepted. The window tolerates gaps, because a UAV link drops
frames constantly and refusing to resynchronise after a dropout would turn
every fade into an outage.
"""

from __future__ import annotations

import hmac
import json
import secrets
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

KEY_DIR = Path(__file__).resolve().parent.parent / "data" / "keys"
KEY_PATH = KEY_DIR / "downlink.key"

# 256 bits, matching the digest. A shorter key is the weak point in an
# otherwise sound construction, and there is no reason to economise here.
KEY_BYTES = 32


class LinkError(Exception):
    """A frame that must not be trusted. Carries WHICH check failed."""


def generate_key(path: Path | None = None) -> bytes:
    """Provision a downlink key. Done once, on the ground, per airframe."""
    p = Path(path) if path else KEY_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(KEY_BYTES)
    p.write_bytes(key)
    # Same posture as the JWT signing key: readable by the owner only, and
    # git-ignored. A key in a repository is not a key.
    try:
        p.chmod(0o600)
    except OSError:  # pragma: no cover - Windows without ACL support
        pass
    return key


def load_key(path: Path | None = None) -> bytes:
    p = Path(path) if path else KEY_PATH
    if not p.exists():
        return generate_key(p)
    key = p.read_bytes()
    if len(key) < KEY_BYTES:
        raise LinkError(
            f"downlink key at {p} is {len(key)} bytes; {KEY_BYTES} required"
        )
    return key


@dataclass
class Frame:
    """One authenticated telemetry frame."""

    seq: int
    t_s: float
    payload: dict
    mac: str

    def as_dict(self) -> dict:
        return {"seq": self.seq, "t_s": self.t_s,
                "payload": self.payload, "mac": self.mac}


def _digest(key: bytes, seq: int, t_s: float, payload: dict) -> str:
    """MAC over the sequence number, the timestamp AND the payload.

    All three are inside the authenticated message. A MAC over the payload
    alone would let an adversary renumber a frame or restamp it while the
    signature still verified, which is the replay attack wearing a different
    hat.

    ``sort_keys`` because two encoders that order a dict differently produce
    different bytes for the same telemetry, and the verifier would reject
    honest frames -- a correctness bug that presents as an attack.
    """
    body = json.dumps(
        {"seq": seq, "t_s": round(float(t_s), 6), "payload": payload},
        sort_keys=True, separators=(",", ":"), default=str,
    ).encode("utf-8")
    return hmac.new(key, body, sha256).hexdigest()


class Signer:
    """Airframe side: stamps and authenticates each outgoing frame."""

    def __init__(self, key: bytes | None = None, *, start: int = 0) -> None:
        self.key = key if key is not None else load_key()
        self._seq = int(start)

    def sign(self, payload: dict, t_s: float | None = None) -> Frame:
        self._seq += 1
        t = time.time() if t_s is None else float(t_s)
        return Frame(seq=self._seq, t_s=t, payload=payload,
                     mac=_digest(self.key, self._seq, t, payload))


class Verifier:
    """Ground side: refuses anything not authentic, fresh and in order."""

    def __init__(self, key: bytes | None = None, *,
                 max_age_s: float | None = 300.0,
                 state_path: Path | None = None) -> None:
        self.key = key if key is not None else load_key()
        self.max_age_s = max_age_s
        # The replay high-water mark survives a restart when a state file is
        # given (SEC-05). Held only in memory, a restart reset it to zero and
        # every frame captured before the restart could be replayed.
        self.state_path = Path(state_path) if state_path is not None else None
        self.last_seq = 0
        if self.state_path is not None and self.state_path.exists():
            try:
                self.last_seq = int(self.state_path.read_text().strip() or 0)
            except (OSError, ValueError):
                self.last_seq = 0
        # Counters, so a link under attack is visible rather than merely quiet.
        self.accepted = 0
        self.rejected_mac = 0
        self.rejected_replay = 0
        self.rejected_stale = 0

    def verify(self, frame: Frame | dict) -> dict:
        """Return the payload, or raise. Never returns partial trust."""
        f = frame if isinstance(frame, Frame) else Frame(
            seq=int(frame["seq"]), t_s=float(frame["t_s"]),
            payload=frame["payload"], mac=str(frame["mac"]),
        )

        expected = _digest(self.key, f.seq, f.t_s, f.payload)
        # CONSTANT-TIME comparison. A byte-by-byte `==` leaks how much of a
        # forged MAC was correct through its timing, which is enough to
        # construct one a byte at a time.
        if not hmac.compare_digest(expected, f.mac):
            self.rejected_mac += 1
            raise LinkError("MAC mismatch: the frame is forged or modified")

        if f.seq <= self.last_seq:
            self.rejected_replay += 1
            raise LinkError(
                f"replay: sequence {f.seq} is not ahead of {self.last_seq}"
            )

        if self.max_age_s is not None:
            age = time.time() - f.t_s
            if age > self.max_age_s:
                self.rejected_stale += 1
                raise LinkError(
                    f"stale: frame is {age:.0f} s old, limit {self.max_age_s:.0f} s"
                )

        # Accepted. The gap is not an error: a UAV link drops frames constantly
        # and refusing to resynchronise after a fade would turn every dropout
        # into an outage.
        self.last_seq = f.seq
        self.accepted += 1
        if self.state_path is not None:
            tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
            tmp.write_text(str(self.last_seq))
            tmp.replace(self.state_path)
        return f.payload

    @property
    def stats(self) -> dict:
        return {
            "accepted": self.accepted,
            "rejected_mac": self.rejected_mac,
            "rejected_replay": self.rejected_replay,
            "rejected_stale": self.rejected_stale,
            "last_seq": self.last_seq,
        }


__all__ = ["KEY_BYTES", "KEY_PATH", "Frame", "LinkError", "Signer", "Verifier",
           "generate_key", "load_key"]
