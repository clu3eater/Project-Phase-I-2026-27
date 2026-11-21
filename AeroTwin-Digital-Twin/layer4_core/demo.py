"""The hosted demonstration copy: one switch, off unless it is asked for.

``DT_DEMO_MODE=1`` turns a ground station into the copy that is put on a
public address for evaluators. Everything it changes is listed here, and
nothing changes without it:

  * THE FOUR ACCOUNTS HAVE A KNOWN PASSWORD. ``DT_DEMO_PASSWORD`` (default
    ``sih2026``), set on every start, with no forced change. An evaluator
    arrives from a link in a slide deck and must be able to sign in at once.
  * THE LOGIN SCREEN LISTS THEM. ``GET /api/demo`` hands the console the
    accounts to show; on a real station it says only ``{"demo": false}``.
  * NO ACCOUNT CAN BE LOCKED, RE-PASSWORDED OR DISABLED. Every evaluator shares
    these four accounts, so one person's typos, or one person changing a
    password, would lock out everyone who comes after.
  * SEARCH ENGINES ARE TOLD NOT TO LIST IT (``X-Robots-Tag``). The address is
    meant to be reached from the deck, not found.
  * IT STARTS READY TO FLY. On a fresh squadron the aircraft on the ground
    station is signed off by the maintainer and an ISR patrol is planned and
    allotted to the operator, through the same steps the crew would take, so
    an evaluator who signs in as the operator can start the engine at once.
    The other aircraft still await inspection, so the maintainer has work.
  * IT STARTS AGAIN FRESH WHEN LEFT ALONE. Once someone has signed in, and then
    nothing has been asked of the server and no console has been open for
    ``DT_DEMO_IDLE_RESET_MIN`` minutes (default 30), the process exits. The
    supervisor that runs it starts a new container from the image, so the next
    evaluator finds the squadron exactly as shipped -- not the engine the last
    one broke. Damage still does not heal inside a run; the whole run is
    replaced.

A fielded station never sets this. It is a demonstration convenience with the
security posture of one: the passwords are printed on the screen.
"""

from __future__ import annotations

import logging
import os
import threading
import time

_log = logging.getLogger(__name__)

# Label on the login screen, user ID, role. The same four accounts a real
# station seeds, so every screen behaves exactly as it does there.
ACCOUNTS: tuple[tuple[str, str, str], ...] = (
    ("OPERATOR", "op.rao", "ROLE_OPERATOR"),
    ("ENGINEER", "eng.menon", "ROLE_ENGINEER"),
    ("MAINTENANCE", "mt.iyer", "ROLE_MAINTENANCE"),
    ("COMMANDER", "cdr.sharma", "ROLE_COMMANDER"),
)

REFUSAL = "Not available in the demonstration copy."


def enabled() -> bool:
    return os.environ.get("DT_DEMO_MODE") == "1"


def password() -> str:
    return os.environ.get("DT_DEMO_PASSWORD", "sih2026")


def accounts() -> list[dict]:
    """What the login screen lists. Empty on a real station."""
    if not enabled():
        return []
    pw = password()
    return [{"label": label, "username": user, "password": pw}
            for label, user, _ in ACCOUNTS]


def seed_accounts() -> None:
    """Give the four accounts the demonstration password, usable at once.

    Written over whatever the store holds, on every start, so an account can
    never be left disabled or on some other password by an earlier run.
    """
    from layer4_core import security as sec

    existing = sec._users()   # creates (and seeds) the store on a fresh directory
    with sec._USER_LOCK, sec._connect_users() as cx:
        for _, user, role in ACCOUNTS:
            sec._upsert(cx, user, {
                "role": role,
                "hash": sec._hash_pw(password()),
                "disabled": False,
                "must_change": False,
                # Kept, not zeroed: zeroing would revive tokens revoked earlier.
                "token_epoch": existing.get(user, {}).get("token_epoch", 0),
            })
        cx.commit()
    # The random first-run passwords are not the ones in use; a file listing
    # them would only mislead whoever finds it.
    (sec._users_db().parent / "FIRST_RUN_CREDENTIALS.txt").unlink(missing_ok=True)
    _log.warning("DEMONSTRATION MODE: the four accounts use the published "
                 "demonstration password; never run a real station like this")


def stage_ready_to_fly(ops) -> None:
    """One aircraft released and a mission allotted to the operator.

    Done through the squadron's own actions -- the maintainer's release, the
    commander's plan and allotment -- so the logbook reads exactly as it would
    had the crew done it, and every rule those actions enforce still applies.
    Only on a squadron with no missions yet: a store that already has history
    is left as it is. Never fatal; a demonstration that starts one step further
    back is still a demonstration.
    """
    from layer4_core.ops import OpsError

    try:
        if ops.missions(limit=1):
            return
        tail = ops.active_tail()
        if not ops.aircraft(tail)["released"]:
            ops.release(tail, by="mt.iyer", role="ROLE_MAINTENANCE", note="BFI")
        types = ops.mission_types()
        mtype = "ISR_PATROL" if "ISR_PATROL" in types else next(iter(types))
        m = ops.create_mission(
            by="cdr.sharma", name="", mtype=mtype, environment=None,
            duration_h=None, altitude_ft=None, area="Northern border sector",
            priority="ROUTINE", notes="Demonstration sortie")
        ops.approve(m["id"], by="cdr.sharma", tail=tail, operator="op.rao")
        _log.warning("DEMONSTRATION MODE: %s released and %s allotted to op.rao",
                     tail, m["id"])
    except OpsError:
        _log.exception("could not stage the ready-to-fly demonstration")


# ---------------------------------------------------------------------------
# Starting again when left alone
# ---------------------------------------------------------------------------

_last_activity = time.monotonic()
_used = False
_open_consoles = 0
_lock = threading.Lock()


def touch() -> None:
    """Someone signed in, asked for something, or has a console open."""
    global _last_activity, _used
    with _lock:
        _last_activity = time.monotonic()
        _used = True


def console_opened() -> None:
    global _open_consoles
    touch()
    with _lock:
        _open_consoles += 1


def console_closed() -> None:
    global _open_consoles
    touch()
    with _lock:
        _open_consoles = max(0, _open_consoles - 1)


def _idle_seconds() -> float:
    return 60.0 * float(os.environ.get("DT_DEMO_IDLE_RESET_MIN", "30"))


def _watch() -> None:
    limit = _idle_seconds()
    while True:
        time.sleep(30.0)
        with _lock:
            idle = time.monotonic() - _last_activity
            due = _used and _open_consoles == 0 and idle >= limit
        if due:
            _log.warning("DEMONSTRATION MODE: unused for %.0f min; exiting so "
                         "the next visitor gets a fresh copy", idle / 60.0)
            logging.shutdown()
            # Not a clean shutdown on purpose: nothing from this run is kept,
            # and the supervisor starts a new container from the image.
            os._exit(3)


def start_idle_reset() -> None:
    if _idle_seconds() <= 0:
        return
    threading.Thread(target=_watch, name="demo-idle-reset", daemon=True).start()
