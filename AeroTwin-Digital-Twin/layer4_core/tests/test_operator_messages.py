r"""Nothing an operator is shown may carry a host path or a raw exception.

Caught by screenshotting the prognostics page, which was displaying:

    STAT: not scored: Tier-2 unavailable: [Errno 2] No such file or directory:
    'C:\Users\sarsw\AppData\Local\Temp\console_shot...

on a defence console, overflowing its panel. It tells the operator nothing they
can act on, and tells anyone who can see the screen the account name and the
filesystem layout of the host. The detail belongs in the log, where the person
who can act on it will look.
"""

from __future__ import annotations

import logging
import re

import pytest

from layer4_core.live import _operator_reason

# A path, a drive letter, a home directory, a repr with escaped separators, or
# an errno. Any of these in operator-facing text is the defect.
LEAKS = re.compile(r"[A-Za-z]:[\/]|/home/|/Users/|\\|Errno|Traceback|\.joblib|\.pt\b")


@pytest.mark.parametrize("exc", [
    FileNotFoundError(2, "No such file or directory", r"C:\Users\sarsw\models\t.joblib"),
    OSError(5, "Input/output error", "/var/lib/astra/models/tier3.pt"),
    ValueError("feature width 34 does not match checkpoint 36"),
    KeyError("ensemble"),
    TypeError("expected ndarray"),
    MemoryError(),
    RuntimeError("CUDA error: device-side assert triggered"),
])
def test_no_operator_message_leaks_a_path_or_a_raw_exception(exc):
    msg = _operator_reason(exc)
    assert not LEAKS.search(msg), f"{type(exc).__name__} leaked: {msg!r}"
    assert str(exc) not in msg or not str(exc), "the raw exception text is shown"


@pytest.mark.parametrize("exc", [
    FileNotFoundError(2, "missing", "x.joblib"),
    ValueError("width"),
    OSError("io"),
    RuntimeError("?"),
])
def test_every_message_is_a_readable_phrase(exc):
    msg = _operator_reason(exc)
    assert msg and msg == msg.strip()
    assert 4 <= len(msg) <= 70, f"{msg!r} is not a phrase a panel can hold"
    assert not msg.endswith("."), "these are appended to a sentence by the caller"


def test_the_states_are_distinguishable():
    """A missing model and a mismatched one need different actions."""
    missing = _operator_reason(FileNotFoundError(2, "missing", "x"))
    mismatch = _operator_reason(ValueError("width"))
    unreadable = _operator_reason(OSError("io"))
    assert len({missing, mismatch, unreadable}) == 3, (
        "install the model, retrain it, or fix the disk are three different "
        "jobs and must not read the same on the console")


def test_the_detail_still_reaches_the_log(caplog):
    """Sanitising the screen must not throw the diagnosis away."""
    import layer4_core.live as live

    with caplog.at_level(logging.WARNING, logger=live._log.name):
        live._log.warning("Tier-2 ensemble not loaded",
                          exc_info=FileNotFoundError(2, "No such file", "/models/t.joblib"))
    assert any("/models/t.joblib" in r.getMessage() or
               (r.exc_info and "/models/t.joblib" in str(r.exc_info[1]))
               for r in caplog.records), "the path must survive in the log"
