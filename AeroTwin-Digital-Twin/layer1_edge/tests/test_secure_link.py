"""Authenticated telemetry -- PRD Part 3 s20 threats 1 and 3.

The tests are written as the attacks they defend against, because a security
mechanism tested only on the happy path is tested on the case nobody was
worried about.
"""

from __future__ import annotations

import time

import pytest

from layer1_edge import secure_link as sl


@pytest.fixture
def key() -> bytes:
    return b"k" * sl.KEY_BYTES


def _payload(cht: float = 110.0) -> dict:
    return {"rpm": 5400, "cht_max": cht, "oil_pressure": 59.2}


# ---------------------------------------------------------------------------
# It works
# ---------------------------------------------------------------------------


def test_an_honest_frame_round_trips(key):
    s, v = sl.Signer(key), sl.Verifier(key)
    f = s.sign(_payload())
    assert v.verify(f) == _payload()
    assert v.stats["accepted"] == 1


def test_a_stream_of_frames_stays_in_order(key):
    s, v = sl.Signer(key), sl.Verifier(key)
    for i in range(20):
        assert v.verify(s.sign(_payload(100 + i)))["cht_max"] == 100 + i
    assert v.stats == {"accepted": 20, "rejected_mac": 0,
                       "rejected_replay": 0, "rejected_stale": 0,
                       "last_seq": 20}


def test_a_dropped_frame_does_not_break_the_link(key):
    """A UAV link drops frames constantly. Refusing to resynchronise after a
    fade would turn every dropout into an outage."""
    s, v = sl.Signer(key), sl.Verifier(key)
    v.verify(s.sign(_payload()))
    for _ in range(50):
        s.sign(_payload())          # lost in the fade, never delivered
    v.verify(s.sign(_payload()))    # the link comes back
    assert v.stats["accepted"] == 2
    assert v.stats["rejected_replay"] == 0


# ---------------------------------------------------------------------------
# THREAT 3 -- tampering
# ---------------------------------------------------------------------------


def test_a_modified_payload_is_refused(key):
    """The attack the whole module exists for: an adversary rewrites a
    cylinder-head temperature so a failing engine looks healthy."""
    s, v = sl.Signer(key), sl.Verifier(key)
    f = s.sign(_payload(cht=131.0)).as_dict()
    f["payload"]["cht_max"] = 105.0
    with pytest.raises(sl.LinkError, match="forged or modified"):
        v.verify(f)
    assert v.stats["rejected_mac"] == 1
    assert v.stats["accepted"] == 0


def test_a_renumbered_frame_is_refused(key):
    """The sequence number is INSIDE the authenticated message. A MAC over the
    payload alone would let an adversary renumber a frame while the signature
    still verified -- replay wearing a different hat."""
    s, v = sl.Signer(key), sl.Verifier(key)
    f = s.sign(_payload()).as_dict()
    f["seq"] = 9999
    with pytest.raises(sl.LinkError, match="forged or modified"):
        v.verify(f)


def test_a_restamped_frame_is_refused(key):
    """So is the timestamp, for the same reason."""
    s, v = sl.Signer(key), sl.Verifier(key)
    f = s.sign(_payload()).as_dict()
    f["t_s"] = f["t_s"] + 3600.0
    with pytest.raises(sl.LinkError, match="forged or modified"):
        v.verify(f)


def test_a_frame_from_the_wrong_key_is_refused(key):
    """An impersonated airframe, or a compromised relay injecting its own."""
    other = sl.Signer(b"x" * sl.KEY_BYTES)
    v = sl.Verifier(key)
    with pytest.raises(sl.LinkError, match="forged or modified"):
        v.verify(other.sign(_payload()))


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


def test_a_replayed_frame_is_refused(key):
    """A MAC proves a frame is AUTHENTIC and says nothing about when.

    Without this check a captured frame stays valid for ever, and an adversary
    can hold a healthy engine's telemetry and replay it over a failing one --
    defeating the whole health monitor while every signature verifies.
    """
    s, v = sl.Signer(key), sl.Verifier(key)
    f = s.sign(_payload())
    v.verify(f)
    with pytest.raises(sl.LinkError, match="replay"):
        v.verify(f)
    assert v.stats["rejected_replay"] == 1


def test_an_out_of_order_frame_is_refused(key):
    s, v = sl.Signer(key), sl.Verifier(key)
    a, b = s.sign(_payload()), s.sign(_payload())
    v.verify(b)
    with pytest.raises(sl.LinkError, match="replay"):
        v.verify(a)


def test_an_old_frame_is_refused_even_with_a_fresh_sequence(key):
    """Freshness is checked separately from ordering. A capture replayed with
    renumbering would pass the sequence test."""
    s = sl.Signer(key)
    v = sl.Verifier(key, max_age_s=10.0)
    old = s.sign(_payload(), t_s=time.time() - 3600.0)
    with pytest.raises(sl.LinkError, match="stale"):
        v.verify(old)
    assert v.stats["rejected_stale"] == 1


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_the_mac_comparison_is_constant_time():
    """A byte-by-byte `==` leaks how much of a forged MAC was correct through
    its timing, which is enough to construct one a byte at a time."""
    import inspect

    src = inspect.getsource(sl.Verifier.verify)
    assert "compare_digest" in src
    assert "expected == f.mac" not in src


def test_key_material_is_full_length():
    k = sl.generate_key(sl.KEY_DIR / "test_downlink.key")
    try:
        assert len(k) == sl.KEY_BYTES == 32
    finally:
        (sl.KEY_DIR / "test_downlink.key").unlink(missing_ok=True)


def test_a_short_key_is_refused_rather_than_padded(tmp_path):
    """Silently accepting a weak key is worse than failing: the construction
    would look sound and be the one thing an attacker targets."""
    p = tmp_path / "short.key"
    p.write_bytes(b"tooshort")
    with pytest.raises(sl.LinkError, match="required"):
        sl.load_key(p)


def test_the_downlink_key_is_git_ignored():
    """A key in a repository is not a key."""
    import subprocess

    out = subprocess.run(
        ["git", "check-ignore", "data/keys/downlink.key"],
        cwd=str(sl.KEY_DIR.parent.parent), capture_output=True, text=True,
    )
    assert out.returncode == 0, "data/keys/downlink.key is NOT git-ignored"


def test_key_ordering_does_not_change_the_mac(key):
    """Two encoders that order a dict differently would produce different
    bytes for the same telemetry, and the verifier would reject honest
    frames -- a correctness bug that presents as an attack."""
    s, v = sl.Signer(key), sl.Verifier(key)
    f = s.sign({"a": 1, "b": 2})
    f.payload = {"b": 2, "a": 1}
    assert v.verify(f) == {"b": 2, "a": 1}


def test_the_replay_high_water_mark_survives_a_restart(tmp_path):
    """SEC-05. Held only in memory, a restart reset it to zero and every frame
    captured before the restart could be replayed."""
    from layer1_edge.secure_link import LinkError, Signer, Verifier

    key = b"k" * 32
    signer = Signer(key)
    frames = [signer.sign({"n": i}) for i in range(3)]
    v = Verifier(key, state_path=tmp_path / "seq")
    for f in frames:
        v.verify(f)
    restarted = Verifier(key, state_path=tmp_path / "seq")
    with pytest.raises(LinkError):
        restarted.verify(frames[0])
