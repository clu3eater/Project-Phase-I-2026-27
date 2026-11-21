"""Structured logging for the twin.

WHY THIS EXISTS
---------------
There was none. No module in the production tree imported `logging`, so when
the pipeline froze (DEV-149) the only evidence anywhere was a string in a
snapshot field that nothing was reading. A defence system whose engine can stop
without leaving a log line is not one an investigator can reason about after
the fact.

WHY JSON LINES AND NOT A THIRD-PARTY LIBRARY
--------------------------------------------
`structlog` and `loguru` are both good and neither is used here. The project
makes a measured claim in docs/INDIGENISATION.md -- no foreign vendor in the
critical path, verified by walking the installed dependency closure -- and that
claim is cheapest to hold when the answer is the standard library. One
formatter class is not worth a dependency.

One JSON object per line, because that is the format every log shipper, `jq`
pipeline and offline analysis script already reads, and because a log that has
to be regex-parsed to be useful will eventually be parsed wrongly.

REDACTION IS NOT OPTIONAL
-------------------------
This process handles bearer tokens and passwords. A log line is a place secrets
leak to permanently, and the leak is usually accidental -- somebody logs a
whole request object. `RedactionFilter` therefore scrubs by KEY NAME on the way
out, so a secret has to be deliberately renamed to escape rather than
deliberately handled to be caught.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any

__all__ = ["setup_logging", "JsonFormatter", "RedactionFilter"]

# Keys whose VALUES never reach a log line, matched case-insensitively anywhere
# in the key. Deliberately broad: a false redaction costs a debugging session,
# a missed one costs a credential.
_SECRET_KEY = re.compile(
    r"pass|passwd|password|secret|token|authorization|auth|credential|"
    r"api_?key|private|cookie|session",
    re.IGNORECASE,
)

# Anything that looks like a bearer token or a JWT in free text, caught even
# when it is not in a named field -- an exception message can carry one.
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]+")
_JWT = re.compile(r"\beyJ[A-Za-z0-9._\-]{10,}")

_REDACTED = "[REDACTED]"

# LogRecord attributes that are not caller-supplied context. Everything else in
# record.__dict__ was passed by the caller via `extra=` and belongs in output.
_STANDARD = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "taskName", "asctime", "message",
}


def _scrub(value: Any) -> Any:
    """Redact secrets in free text, recursing through containers."""
    if isinstance(value, str):
        return _JWT.sub(_REDACTED, _BEARER.sub(f"Bearer {_REDACTED}", value))
    if isinstance(value, dict):
        return {
            k: (_REDACTED if _SECRET_KEY.search(str(k)) else _scrub(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_scrub(v) for v in value]
    return value


class RedactionFilter(logging.Filter):
    """Scrub secrets out of the message and every `extra=` field."""

    def filter(self, record: logging.LogRecord) -> bool:
        for key, val in list(record.__dict__.items()):
            if key in ("msg", "args"):
                continue
            if key not in _STANDARD:
                record.__dict__[key] = (
                    _REDACTED if _SECRET_KEY.search(key) else _scrub(val)
                )
        if isinstance(record.msg, str):
            record.msg = _scrub(record.msg)
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line.

    A traceback is carried as a single `exc` string rather than as embedded
    newlines, so one event stays one line and `grep` on a log file does not
    return half a stack trace.
    """

    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            # UTC, always, with an explicit Z. A log correlated across an
            # aircraft and a ground station cannot afford local time.
            "ts": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, val in record.__dict__.items():
            if key not in _STANDARD and not key.startswith("_"):
                out[key] = val
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        try:
            return json.dumps(out, default=str, ensure_ascii=False)
        except (TypeError, ValueError):
            # A log line must never be the thing that raises.
            return json.dumps(
                {"ts": out["ts"], "level": "ERROR", "logger": record.name,
                 "msg": "log record could not be serialised"}
            )


_CONFIGURED = False


def setup_logging(level: str | None = None, *, force: bool = False) -> None:
    """Install the JSON handler on the root logger. Idempotent.

    Level comes from the argument, else ``DT_LOG_LEVEL``, else INFO. Writes to
    stderr so that stdout stays available for anything that needs to emit data
    -- a container runtime collects both.
    """
    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    lvl = (level or os.environ.get("DT_LOG_LEVEL") or "INFO").upper()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactionFilter())

    root = logging.getLogger()
    for old in list(root.handlers):
        root.removeHandler(old)
    root.addHandler(handler)
    root.setLevel(getattr(logging, lvl, logging.INFO))

    # uvicorn installs its own handlers; let its records propagate to ours so
    # there is ONE log format rather than two interleaved ones.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True

    _CONFIGURED = True
