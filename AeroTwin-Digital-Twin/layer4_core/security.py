"""Authentication, authorisation and the tamper-evident audit log.

Implements `configs/thresholds.yaml` `security:` and PRD Part 4 s10
(role-based views). The alignment claimed there is with STANAG 4586's
separation of the Core UCS from the Human Computer Interface, and is scoped
explicitly to LOI 1-2 -- receipt and display of telemetry and derived
products. This console issues NO vehicle or payload commands (LOI 3-5). The
scope is repeated here because a reader of this module alone would otherwise
see "STANAG 4586" with none of the qualification the standard document gives
it, and read a wire-protocol claim into an architectural one.

THE RULE THAT MATTERS MOST (PRD Part 4 s10c)
---------------------------------------------
    "Authorisation SHALL be enforced server-side regardless of UI state; the
     UI is a convenience, never the security boundary."

So every protected endpoint carries a required scope and checks it against the
token, and the console's habit of hiding controls a role cannot use (s10a) is
a courtesy on top of that check, never a substitute for it. There is a test
that forces a call the UI would never render and asserts the API refuses it,
because that is the only version of this claim worth making.

WHY THE AUDIT LOG IS A HASH CHAIN
----------------------------------
The config asks for an append-only log with a `sha256` hash algorithm. A log
that is merely appended to is not append-only -- anyone who can write the file
can rewrite the middle of it. Each entry therefore carries the hash of the
entry before it, so altering or removing any record breaks every hash after it
and ``AuditLog.verify()`` says exactly where. That is what makes the log
evidence rather than a diary.

An audit log that records only successes is not an audit log, so AUTHZ_DENY is
one of the recorded event types: the attempts that were REFUSED are usually
the interesting ones.

KEYS
----
RS256 needs a keypair. One is generated on first use into the data directory
(git-ignored) rather than shipped, because a private key committed to a
repository is not a private key. For a fielded system this is where an HSM or
the establishment's own PKI attaches; that is a deployment decision and is
recorded as such rather than pretended.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

_log = logging.getLogger(__name__)

from common import config

# ---------------------------------------------------------------------------
# Roles and scopes
# ---------------------------------------------------------------------------


def _sec() -> dict:
    return config.load_thresholds()["security"]


def roles() -> dict[str, list[str]]:
    return dict(_sec()["roles"])


def scopes_for(role: str) -> set[str]:
    r = roles()
    if role not in r:
        return set()
    return set(r[role])


def has_scope(role: str, scope: str) -> bool:
    """Whether a role carries a scope.

    ``*`` is a wildcard and belongs to ROLE_COMMANDER alone. It is checked
    explicitly rather than by string matching, so a role that happens to hold a
    scope literally named "*something" cannot slip through.
    """
    s = scopes_for(role)
    return "*" in s or scope in s


# ---------------------------------------------------------------------------
# Keys and tokens
# ---------------------------------------------------------------------------

_KEY_LOCK = threading.Lock()
_PRIVATE: bytes | None = None
_PUBLIC: bytes | None = None


def _key_paths() -> tuple[Path, Path]:
    d = config.data_dir() / "keys"
    return d / "gcs_signing_key.pem", d / "gcs_signing_key.pub.pem"


_RESTRICTED: set[str] = set()


def _restrict_to_owner(directory: Path) -> None:
    """Owner-only access to the directory holding keys and the user store.

    SEC-06: the private signing key, the user database and the first-run
    credentials file were modifiable by every authenticated Windows user
    (`Authenticated Users:(M)`) and created 0o666 elsewhere, so any local
    account could read the passwords or swap the key and mint its own tokens.
    chmod does nothing useful on Windows, so there the directory gets an
    explicit ACL: inheritance removed and full control for the account running
    the service alone, inherited by every file created inside it. Applied once
    per directory per process; a failure is logged, not fatal.
    """
    key = str(directory.resolve())
    if key in _RESTRICTED:
        return
    _RESTRICTED.add(key)
    try:
        if os.name == "nt":
            import getpass
            import subprocess

            subprocess.run(
                ["icacls", str(directory), "/inheritance:r", "/grant:r",
                 f"{getpass.getuser()}:(OI)(CI)F"],
                check=True, capture_output=True, timeout=15)
        else:
            directory.chmod(0o700)
            for p in directory.iterdir():
                if p.is_file():
                    p.chmod(0o600)
    except Exception as exc:  # noqa: BLE001 - reported, not fatal
        logging.getLogger(__name__).warning(
            "could not restrict access to %s: %s", directory, exc)


def _keys() -> tuple[bytes, bytes]:
    """The RS256 keypair, generated on first use.

    Generated rather than shipped: a private key in a repository is not a
    private key. In deployment this is replaced by the establishment's PKI or
    an HSM, which is a siting decision rather than a code change.
    """
    global _PRIVATE, _PUBLIC
    with _KEY_LOCK:
        if _PRIVATE is not None and _PUBLIC is not None:
            return _PRIVATE, _PUBLIC
        priv_p, pub_p = _key_paths()
        if priv_p.exists() and pub_p.exists():
            _PRIVATE, _PUBLIC = priv_p.read_bytes(), pub_p.read_bytes()
            return _PRIVATE, _PUBLIC

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        priv = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        pub = key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        priv_p.parent.mkdir(parents=True, exist_ok=True)
        _restrict_to_owner(priv_p.parent)
        priv_p.write_bytes(priv)
        pub_p.write_bytes(pub)
        try:  # best effort; Windows ACLs are not POSIX modes
            priv_p.chmod(0o600)
        except OSError:
            pass
        _PRIVATE, _PUBLIC = priv, pub
        return priv, pub


class AuthError(Exception):
    """Authentication or authorisation failed."""


def issue_token(subject: str, role: str, *, refresh: bool = False) -> str:
    """Sign an access or refresh token for a subject in a role."""
    if role not in roles():
        raise AuthError(f"unknown role {role!r}")
    cfg = _sec()["jwt"]
    now = datetime.now(timezone.utc)
    life = (
        timedelta(hours=float(cfg["refresh_token_hours"])) if refresh
        else timedelta(minutes=float(cfg["access_token_minutes"]))
    )
    payload = {
        "sub": subject,
        "role": role,
        "scopes": sorted(scopes_for(role)),
        "iss": str(cfg["issuer"]),
        "iat": int(now.timestamp()),
        "exp": int((now + life).timestamp()),
        "typ": "refresh" if refresh else "access",
        # A unique id per token, so ONE stolen token can be revoked without
        # locking out the operator holding the others. Without a jti the only
        # revocation available is "disable the account", which mid-sortie is
        # the wrong instrument.
        "jti": secrets.token_urlsafe(12),
    }
    priv, _ = _keys()
    return jwt.encode(payload, priv, algorithm=str(cfg["algorithm"]))


def verify_token(token: str, *, typ: str = "access") -> dict:
    """Decode and validate a token, or raise AuthError.

    The algorithm is pinned to the configured one. Accepting whatever the token
    header declares is the classic JWT failure -- an attacker sets ``alg: none``
    or downgrades RS256 to HS256 and signs with the public key.
    """
    cfg = _sec()["jwt"]
    _, pub = _keys()
    try:
        claims = jwt.decode(
            token, pub,
            algorithms=[str(cfg["algorithm"])],   # pinned, not from the header
            issuer=str(cfg["issuer"]),
            options={"require": ["exp", "iat", "sub", "iss"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError(f"invalid token: {exc}") from exc

    # Only ACCESS tokens open a route (SEC-07). The 24 h refresh token carries
    # the same signature and scopes, and with `typ` unchecked it worked
    # everywhere the 15-minute access token did.
    if str(claims.get("typ", "access")) != typ:
        raise AuthError(f"not an {typ} token")

    # A VALID SIGNATURE IS NOT ENOUGH.
    #
    # A JWT is usable until it expires, so a token copied off a compromised
    # ground station stays good for its whole lifetime and nothing could stop
    # it. That is the standard criticism of stateless tokens and it was a real
    # hole here, because a commander's token carries every scope.
    #
    # Three checks close it, cheapest first.
    sub = str(claims.get("sub", ""))
    jti = str(claims.get("jti", ""))

    if jti and jti in _revoked_jti():
        raise AuthError("token revoked")

    user = _users().get(sub)
    if user is None:
        raise AuthError("unknown subject")
    if user.get("disabled"):
        raise AuthError("account disabled")
    # The role in the token must still be the role in the store (SEC-06).
    # Trusting the token's own claim meant a demotion only took effect when
    # the token expired, and anyone holding the signing key chose a role.
    if str(user.get("role", "")) != str(claims.get("role", "")):
        raise AuthError("role changed since the token was issued")

    # token_epoch revokes EVERY token a user holds at once -- the instrument
    # for "this account is compromised", as against "this one token is".
    # Anything issued before the epoch is refused.
    epoch = int(user.get("token_epoch", 0))
    if epoch and int(claims.get("iat", 0)) < epoch:
        raise AuthError("token revoked")

    return claims


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

# RE-ENTRANT, and it has to be. `_users()` takes this lock to read the store,
# and `create_user` / `_update_user` take it to make read-modify-write atomic
# and then call `_users()` inside it. With a plain Lock the same thread waits on
# itself forever: creating an account, changing a password, disabling an
# account or changing a role all hung with no CPU and no error. Found by the
# SEC-02 test, which was the first to create an account through this path.
_USER_LOCK = threading.RLock()

# bcrypt directly rather than through passlib. passlib 1.7.4 (its last release,
# 2020) probes `bcrypt.__about__.__version__`, which bcrypt removed in 4.1, and
# then fails its own wrap-bug detection outright -- so the "standard" password
# library cannot hash a password against a current backend at all. One fewer
# dependency, and the one that remains is maintained.


_BCRYPT_MAX_BYTES = 72


def _hash_pw(password: str) -> str:
    # bcrypt uses only the first 72 bytes. A longer passphrase is REFUSED
    # rather than silently cut (SEC-13): cut, two different 80-byte passwords
    # sharing a 72-byte prefix both verified -- the opposite of what this
    # comment used to promise.
    raw = password.encode("utf-8")
    if len(raw) > _BCRYPT_MAX_BYTES:
        raise ValueError(f"password longer than {_BCRYPT_MAX_BYTES} bytes")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode()


def _verify_pw(password: str, hashed: str) -> bool:
    raw = password.encode("utf-8")
    if len(raw) > _BCRYPT_MAX_BYTES:
        return False  # could never have been set, so it cannot match
    try:
        return bcrypt.checkpw(raw, hashed.encode())
    except (ValueError, TypeError):
        return False


_DUMMY_HASH = bcrypt.hashpw(b"no-such-user", bcrypt.gensalt()).decode()


def _users_path() -> Path:
    """The legacy JSON store. Read once, at migration, then retired."""
    return config.data_dir() / "keys" / "users.json"


def _users_db() -> Path:
    return config.data_dir() / "keys" / "users.db"


# NOT NULL DEFAULT on every flag is the point of this table. The JSON store
# lost `must_change` and nothing noticed, because a missing key reads as False
# and False is the permissive answer. A column cannot go missing.
_USER_DDL = """
CREATE TABLE IF NOT EXISTS users (
    username     TEXT    PRIMARY KEY,
    role         TEXT    NOT NULL,
    hash         TEXT    NOT NULL,
    disabled     INTEGER NOT NULL DEFAULT 0,
    must_change  INTEGER NOT NULL DEFAULT 1,
    token_epoch  INTEGER NOT NULL DEFAULT 0,
    created_utc  TEXT    NOT NULL,
    updated_utc  TEXT    NOT NULL
);
"""

_USER_FIELDS = ("role", "hash", "disabled", "must_change", "token_epoch")


def _now_utc() -> str:
    return (datetime.now(timezone.utc)
            .isoformat(timespec="seconds").replace("+00:00", "Z"))


def _connect_users() -> sqlite3.Connection:
    path = _users_db()
    path.parent.mkdir(parents=True, exist_ok=True)
    _restrict_to_owner(path.parent)
    cx = sqlite3.connect(path, timeout=10.0)
    cx.row_factory = sqlite3.Row
    # WAL so a read during a write does not block the login path, and a
    # half-written row cannot be read. Same reasoning as the edge buffer.
    cx.execute("PRAGMA journal_mode=WAL")
    cx.execute("PRAGMA synchronous=FULL")
    cx.executescript(_USER_DDL)
    return cx


def _row_to_user(r: sqlite3.Row) -> dict:
    return {
        "role": r["role"],
        "hash": r["hash"],
        "disabled": bool(r["disabled"]),
        "must_change": bool(r["must_change"]),
        "token_epoch": int(r["token_epoch"]),
    }


def _upsert(cx: sqlite3.Connection, username: str, rec: dict) -> None:
    now = _now_utc()
    cx.execute(
        """INSERT INTO users
               (username, role, hash, disabled, must_change, token_epoch,
                created_utc, updated_utc)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(username) DO UPDATE SET
               role=excluded.role, hash=excluded.hash,
               disabled=excluded.disabled, must_change=excluded.must_change,
               token_epoch=excluded.token_epoch, updated_utc=excluded.updated_utc
        """,
        (username, rec["role"], rec["hash"],
         # A flag absent from the source is filled with the SAFE value, not
         # with False. An imported account with no must_change flag is one
         # whose password history is unknown, and the conservative reading of
         # "unknown" is "change it".
         int(bool(rec.get("disabled", False))),
         int(bool(rec.get("must_change", True))),
         int(rec.get("token_epoch", 0) or 0),
         now, now),
    )


def _migrate_json_if_present() -> dict | None:
    """Import the legacy file exactly once, then rename it out of the way.

    Renamed rather than deleted: it holds password hashes, and an operator who
    needs to prove what the store contained before a migration should be able
    to. Renamed rather than left in place so it cannot be read as current.
    """
    legacy = _users_path()
    if not legacy.exists():
        return None
    try:
        store = json.loads(legacy.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _log.exception("could not read the legacy user store; leaving it alone")
        return None
    if not isinstance(store, dict) or not store:
        return None

    restored = [u for u, r in store.items()
                if not isinstance(r, dict) or "must_change" not in r]
    with _connect_users() as cx:
        for username, rec in store.items():
            if isinstance(rec, dict) and rec.get("role") and rec.get("hash"):
                _upsert(cx, username, rec)
        cx.commit()
    legacy.rename(legacy.with_suffix(".json.migrated"))
    _log.warning(
        "user store migrated from JSON to SQLite",
        extra={"accounts": len(store), "flags_restored": len(restored)})
    if restored:
        # Said loudly. These accounts were NOT being asked to change their
        # password and should have been.
        _log.warning(
            "accounts imported without a must_change flag; forced password "
            "change has been restored for them",
            extra={"accounts": sorted(restored)})
    return store


def _seed_users() -> dict:
    """One account per role, seeded on first run with RANDOM passwords.

    The passwords are written once to a git-ignored file beside the store and
    are never in source control. Hard-coding a demo password is how a
    "demonstration only" credential reaches a fielded system: it gets copied
    forward because it works, and nobody remembers it was meant to be
    temporary.

    Passwords are stored only as bcrypt hashes, so the store itself discloses
    nothing even if it is read.
    """
    import secrets

    import bcrypt

    creds = {
        "op.rao": "ROLE_OPERATOR",
        "eng.menon": "ROLE_ENGINEER",
        "mt.iyer": "ROLE_MAINTENANCE",
        "cdr.sharma": "ROLE_COMMANDER",
    }
    store, plain = {}, {}
    for user, role in creds.items():
        pw = secrets.token_urlsafe(12)
        plain[user] = pw
        store[user] = {
            "role": role,
            "hash": _hash_pw(pw),
            "disabled": False,
            # These passwords are written to FIRST_RUN_CREDENTIALS.txt in
            # PLAIN TEXT so that a first user can get in at all. A credential
            # written to a file in plain text is not a secret, so it is marked
            # for mandatory change rather than trusted.
            "must_change": True,
            "token_epoch": 0,
        }

    with _connect_users() as cx:
        for username, rec in store.items():
            _upsert(cx, username, rec)
        cx.commit()

    note = _users_db().parent / "FIRST_RUN_CREDENTIALS.txt"
    lines = [
        "Generated on first run. These are DEMONSTRATION credentials for a",
        "local console. Delete this file once you have noted them, and replace",
        "the whole store with your establishment's directory before fielding.",
        "",
    ]
    lines += [f"  {u:<14} {r:<18} {plain[u]}" for u, r in creds.items()]
    note.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return store


def _users() -> dict:
    with _USER_LOCK:
        with _connect_users() as cx:
            rows = cx.execute("SELECT * FROM users").fetchall()
        if rows:
            return {r["username"]: _row_to_user(r) for r in rows}
        # Empty table: either a fresh install, or an existing deployment whose
        # accounts are still in the old JSON file.
        if _migrate_json_if_present():
            with _connect_users() as cx:
                rows = cx.execute("SELECT * FROM users").fetchall()
            if rows:
                return {r["username"]: _row_to_user(r) for r in rows}
        return _seed_users()


def authenticate(username: str, password: str) -> str:
    """Return the user's role, or raise AuthError.

    The failure message is deliberately identical for an unknown user and a
    wrong password. Distinguishing them tells an attacker which usernames
    exist, which is half the work of guessing a credential.
    """
    users = _users()
    rec = users.get(username)
    if rec is None:
        # Verify against a dummy hash anyway, so the response time does not
        # reveal whether the account exists. Returning early here would make
        # "no such user" measurably faster than "wrong password", which is a
        # user-enumeration oracle even when the message is identical.
        _verify_pw(password, _DUMMY_HASH)
        raise AuthError("invalid credentials")
    if not _verify_pw(password, rec["hash"]):
        raise AuthError("invalid credentials")
    return str(rec["role"])


# ---------------------------------------------------------------------------
# Audit log -- append-only, hash-chained
# ---------------------------------------------------------------------------


@dataclass
class AuditEntry:
    seq: int
    utc: str
    event: str
    subject: str
    role: str
    detail: dict
    prev_hash: str
    hash: str
    # 1 = legacy unkeyed SHA-256 entry, 2 = HMAC-SHA256 under the audit key.
    v: int = 1

    def as_dict(self) -> dict:
        d = {
            "seq": self.seq, "utc": self.utc, "event": self.event,
            "subject": self.subject, "role": self.role, "detail": self.detail,
            "prev_hash": self.prev_hash, "hash": self.hash,
        }
        if self.v != 1:
            d["v"] = self.v
        return d


GENESIS = "0" * 64


def _audit_key() -> bytes:
    """The audit-chain HMAC key, generated on first use in the keys directory."""
    d = config.data_dir() / "keys"
    d.mkdir(parents=True, exist_ok=True)
    _restrict_to_owner(d)
    p = d / "audit_hmac.key"
    if p.exists():
        return p.read_bytes()
    k = secrets.token_bytes(32)
    p.write_bytes(k)
    return k


class AuditLog:
    """Append-only, tamper-evident record of everything that matters."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (config.data_dir() / "audit" / "audit.jsonl")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._events = set(_sec()["audit"]["log_events"])
        # (file size, seq, hash) of the last entry this process wrote or read.
        # `_tail` re-read the WHOLE file on every append -- 319 ms per write at
        # 200k lines -- so a flood of audited rejections slowed every audited
        # action (RT-05). The size check re-reads if anything else touched it.
        self._tail_cache: tuple[int, int, str] | None = None
        # KEYED CHAIN AND A SEALED HEAD (SEC-04). The chain was plain SHA-256
        # with no secret, so anyone able to write the file could delete the
        # tail, edit an entry and recompute every hash after it, or delete the
        # whole log, and verify() still said ok. New entries are HMAC-SHA256
        # under a key held in the owner-only keys directory, and the latest
        # (seq, hash) is written beside the log under its own MAC, so a
        # truncated, rewritten or missing log no longer verifies. The limit,
        # stated: whoever can read the key can forge both. Tamper-evidence
        # against the service account itself needs the head anchored off the
        # host -- the fleet server, or the hash printed on a filed report.
        self.head_path = self.path.with_name(self.path.stem + ".head.json")
        self._key = _audit_key()

    # -- writing ---------------------------------------------------------
    @staticmethod
    def _digest(payload: dict) -> str:
        # sort_keys so the hash is over the CONTENT, not over whatever order a
        # dict happened to serialise in. Without it a log could be rewritten
        # byte-for-byte differently and still verify.
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _mac(self, payload: dict) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hmac.new(self._key, raw.encode("utf-8"), hashlib.sha256).hexdigest()

    def _head_mac(self, seq: int, digest: str) -> str:
        return hmac.new(self._key, f"{seq}:{digest}".encode("utf-8"),
                        hashlib.sha256).hexdigest()

    def _write_head(self, seq: int, digest: str) -> None:
        tmp = self.head_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"seq": seq, "hash": digest,
                                   "mac": self._head_mac(seq, digest)}),
                       encoding="utf-8")
        tmp.replace(self.head_path)

    def _read_head(self) -> dict | None:
        if not self.head_path.exists():
            return None
        try:
            return json.loads(self.head_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"seq": -1, "hash": "", "mac": ""}

    def _tail(self) -> tuple[int, str]:
        if not self.path.exists():
            self._tail_cache = None
            return 0, GENESIS
        size = self.path.stat().st_size
        if self._tail_cache is not None and self._tail_cache[0] == size:
            return self._tail_cache[1], self._tail_cache[2]
        last = None
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    last = line
        if last is None:
            return 0, GENESIS
        rec = json.loads(last)
        return int(rec["seq"]), str(rec["hash"])

    def record(self, event: str, *, subject: str = "system",
               role: str = "system", **detail) -> AuditEntry:
        """Append one entry, chained to the one before it.

        Unknown event types are still recorded rather than dropped. A log that
        silently discards what it was not configured to expect is a log with a
        hole in it, and the hole is exactly where an incident lives.
        """
        with self._lock:
            seq, prev = self._tail()
            body = {
                "seq": seq + 1,
                "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "event": event,
                "subject": subject,
                "role": role,
                "detail": detail,
                "prev_hash": prev,
                "v": 2,
            }
            entry = AuditEntry(**body, hash=self._mac(body))
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry.as_dict(), separators=(",", ":")) + "\n")
            self._write_head(int(body["seq"]), str(entry.hash))
            self._tail_cache = (self.path.stat().st_size, int(body["seq"]),
                                str(entry.hash))
            return entry

    # -- reading ---------------------------------------------------------
    def entries(self, limit: int = 500) -> list[dict]:
        if not self.path.exists():
            return []
        out: list[dict] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    out.append(json.loads(line))
        # Clamped (RT-08): limit=0 or -1 used to return the whole log, because
        # out[-0:] and out[1:] are nearly everything.
        limit = max(1, min(int(limit), 5000))
        return out[-limit:]

    def verify(self) -> dict:
        """Walk the chain and report the first break, if any."""
        head = self._read_head()
        if not self.path.exists():
            if head is not None:
                return {"ok": False, "entries": 0, "broken_at": None,
                        "reason": f"log missing, but its sealed head records "
                                  f"{head.get('seq')} entries"}
            return {"ok": True, "entries": 0, "broken_at": None,
                    "reason": "no log yet"}
        prev = GENESIS
        last_seq = 0
        n = 0
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                rec = json.loads(line)
                n += 1
                body = {k: rec[k] for k in
                        ("seq", "utc", "event", "subject", "role", "detail",
                         "prev_hash")}
                keyed = int(rec.get("v", 1)) == 2
                if keyed:
                    body["v"] = 2
                if rec["prev_hash"] != prev:
                    return {"ok": False, "entries": n, "broken_at": rec["seq"],
                            "reason": "chain does not link to the previous entry"}
                expected = self._mac(body) if keyed else self._digest(body)
                if not hmac.compare_digest(expected, str(rec["hash"])):
                    return {"ok": False, "entries": n, "broken_at": rec["seq"],
                            "reason": "entry content does not match its hash"}
                prev = rec["hash"]
                last_seq = int(rec["seq"])
        if head is not None:
            try:
                head_seq = int(head.get("seq", -1))
            except (TypeError, ValueError):
                head_seq = -1
            if not hmac.compare_digest(
                    str(head.get("mac", "")),
                    self._head_mac(head_seq, str(head.get("hash", "")))):
                return {"ok": False, "entries": n, "broken_at": None,
                        "reason": "sealed head does not verify: forged or edited"}
            if head_seq != last_seq or str(head.get("hash")) != prev:
                return {"ok": False, "entries": n, "broken_at": last_seq,
                        "reason": f"log ends at entry {last_seq} but its sealed "
                                  f"head records entry {head_seq}: truncated "
                                  f"or rewritten"}
        return {"ok": True, "entries": n, "broken_at": None,
                "reason": "every entry links to the one before it"}


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


@dataclass
class RateLimiter:
    """A fixed-window limiter, per subject."""

    per_minute: int = field(default_factory=lambda: int(
        _sec()["rate_limit"]["requests_per_minute"]))
    _hits: dict[str, list[float]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if now - t < 60.0]
            if len(hits) >= self.per_minute:
                self._hits[key] = hits
                return False
            hits.append(now)
            self._hits[key] = hits
            return True


@dataclass
class LoginGuard:
    """Per-ACCOUNT lockout with exponential backoff.

    The RateLimiter above is keyed on the client address, which stops one host
    hammering the login route. It does nothing about the attack that matters
    more here: the same account tried slowly from many addresses. Credential
    stuffing is distributed by construction, so a per-IP limit is the wrong
    axis on its own.

    So failures are counted per USERNAME and the account is locked for a period
    that doubles with each further failure, capped. A successful login clears
    the count.

    Deliberately NOT a permanent lockout: a permanent one hands any attacker a
    denial-of-service against a known operator, which on a ground station in
    the middle of a sortie is the worse failure. Backoff makes brute force
    impractical while an operator who mistypes twice waits seconds.

    The lock is reported to the caller as the SAME message as a bad password.
    Saying "this account is locked" confirms the account exists.
    """

    base_seconds: float = 2.0
    max_seconds: float = 300.0
    free_attempts: int = 3
    _fails: dict[str, int] = field(default_factory=dict)
    _until: dict[str, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def locked_for(self, username: str) -> float:
        """Seconds remaining on the lock, 0.0 if the account may try."""
        with self._lock:
            remaining = self._until.get(username, 0.0) - time.monotonic()
            return max(0.0, remaining)

    def record_failure(self, username: str) -> float:
        """Count a failed attempt and return the new lock duration."""
        with self._lock:
            n = self._fails.get(username, 0) + 1
            self._fails[username] = n
            if n <= self.free_attempts:
                return 0.0
            wait = min(self.base_seconds * (2 ** (n - self.free_attempts - 1)),
                       self.max_seconds)
            self._until[username] = time.monotonic() + wait
            return wait

    def record_success(self, username: str) -> None:
        with self._lock:
            self._fails.pop(username, None)
            self._until.pop(username, None)


# ---------------------------------------------------------------------------
# Revocation, password policy and user administration
# ---------------------------------------------------------------------------
#
# None of this existed. There were four seeded accounts, no way to change a
# password, no way to disable one, and no way to invalidate a token that had
# been copied off a machine. For a ground station that is not a small gap: the
# demonstration credentials are written to a file in PLAIN TEXT, and nothing
# obliged anyone to change them afterwards.
#
# What is deliberately NOT here is a full identity provider. A fielded GCS
# federates to the establishment's own directory; inventing a competing user
# store would be the wrong answer. `authenticate` and `_users` are the seam an
# LDAP or OIDC backend replaces.


def _revocation_path() -> Path:
    return _users_path().parent / "revoked_tokens.json"


def _revoked_jti() -> set[str]:
    """Revoked token ids. Persisted: a restart must not un-revoke a token."""
    path = _revocation_path()
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(k) for k in data.get("jti", [])}
    except (OSError, ValueError):
        return set()


def revoke_token(jti: str) -> None:
    """Revoke ONE token -- the instrument for a single stolen credential."""
    with _USER_LOCK:
        current = _revoked_jti()
        current.add(str(jti))
        path = _revocation_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"jti": sorted(current)}, indent=2),
                        encoding="utf-8")


def revoke_all_for(username: str) -> None:
    """Invalidate every token a user currently holds, at once.

    Implemented as a per-user epoch rather than by enumerating tokens: we do
    not know what is outstanding, and a list we cannot complete is worse than
    a timestamp we can. Anything issued before this instant is refused.
    """
    _update_user(username,
                 token_epoch=int(datetime.now(timezone.utc).timestamp()))


# --- password policy -------------------------------------------------------
#
# Deliberately short and explainable. A policy nobody can recite is one people
# defeat with Password1! -- length is the property that actually resists a
# guessing attack, so it carries the weight rather than symbol classes.
MIN_PASSWORD_LENGTH = 12


class PolicyError(ValueError):
    """A proposed password does not meet the policy. The message says why."""


def check_password_policy(password: str, *, username: str = "") -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PolicyError(
            f"password must be at least {MIN_PASSWORD_LENGTH} characters"
        )
    if username and username.lower() in password.lower():
        raise PolicyError("password must not contain the username")
    classes = sum((
        any(c.islower() for c in password),
        any(c.isupper() for c in password),
        any(c.isdigit() for c in password),
        any(not c.isalnum() for c in password),
    ))
    if classes < 3:
        raise PolicyError(
            "password must combine at least three of: lower case, upper case, "
            "digits, symbols"
        )


# --- user administration ---------------------------------------------------


def _write_users(store: dict) -> None:
    """Persist the whole store. Accounts absent from `store` are DELETED.

    The JSON version overwrote the file, so a caller that dropped a key
    dropped the account. Preserved here deliberately rather than quietly
    changed to an upsert, because `delete_user` relies on it.
    """
    with _connect_users() as cx:
        keep = set(store)
        existing = {r["username"] for r in
                    cx.execute("SELECT username FROM users").fetchall()}
        for gone in existing - keep:
            cx.execute("DELETE FROM users WHERE username = ?", (gone,))
        for username, rec in store.items():
            _upsert(cx, username, rec)
        cx.commit()


def _update_user(username: str, **fields) -> dict:
    with _USER_LOCK:
        store = _users()
        if username not in store:
            raise AuthError("no such user")
        store[username].update(fields)
        _write_users(store)
        return dict(store[username])


def must_change_password(username: str) -> bool:
    return bool(_users().get(username, {}).get("must_change"))


def change_password(username: str, old: str, new: str) -> None:
    """Change a password, then invalidate every token issued under the old one.

    The revocation is the part that is easy to leave out and matters most: a
    password changed because it may have been exposed is not actually changed
    until the sessions opened with it stop working.
    """
    authenticate(username, old)           # raises AuthError on a wrong password
    if old == new:
        raise PolicyError("the new password must differ from the old one")
    check_password_policy(new, username=username)
    _update_user(username, hash=_hash_pw(new), must_change=False)
    revoke_all_for(username)


def create_user(username: str, password: str, role: str) -> None:
    if role not in roles():
        raise AuthError(f"unknown role {role!r}")
    if not username or not username.strip():
        raise AuthError("username must not be empty")
    check_password_policy(password, username=username)
    with _USER_LOCK:
        store = _users()
        if username in store:
            raise AuthError("user already exists")
        store[username] = {
            "role": role, "hash": _hash_pw(password),
            "disabled": False, "must_change": True, "token_epoch": 0,
        }
        _write_users(store)


def set_disabled(username: str, disabled: bool) -> None:
    """Disable or re-enable an account.

    Disabling revokes outstanding tokens too. An account that cannot log in but
    whose existing token still works has not been disabled.
    """
    _update_user(username, disabled=bool(disabled))
    if disabled:
        revoke_all_for(username)


def set_role(username: str, role: str) -> None:
    """Change a role, and force re-login so the new scopes actually apply.

    Scopes are baked into the token at issue time, so without the revocation a
    demotion would leave the old, wider scopes live until the token expired --
    which is the failure being guarded against, not a tidiness point.
    """
    if role not in roles():
        raise AuthError(f"unknown role {role!r}")
    _update_user(username, role=role)
    revoke_all_for(username)


def reset_password(username: str, new: str) -> None:
    """An administrator sets a temporary password for someone who lost theirs.

    The user must change it at the next sign-in, and every token issued under
    the old one stops working -- a reset is usually done because the old
    password is suspect.
    """
    check_password_policy(new, username=username)
    _update_user(username, hash=_hash_pw(new), must_change=True)
    revoke_all_for(username)


def list_users() -> list[dict]:
    """Every account, without anything secret. Hashes never leave this module."""
    return [
        {"username": u, "role": v.get("role"),
         "disabled": bool(v.get("disabled")),
         "must_change": bool(v.get("must_change"))}
        for u, v in sorted(_users().items())
    ]


__all__ = [
    "AuditEntry",
    "authenticate",
    "AuditLog",
    "AuthError",
    "GENESIS",
    "LoginGuard",
    "PolicyError",
    "change_password",
    "check_password_policy",
    "create_user",
    "list_users",
    "must_change_password",
    "reset_password",
    "revoke_all_for",
    "revoke_token",
    "set_disabled",
    "set_role",
    "RateLimiter",
    "has_scope",
    "issue_token",
    "roles",
    "scopes_for",
    "verify_token",
]
