"""Register a ground station with the central fleet server.

    python scripts/register_station.py GCS-01 --name "Hyderabad GCS"

Prints the station key ONCE. Only its SHA-256 is stored, so a lost key is
reissued rather than recovered -- which is the property that makes the stored
table useless to whoever reads it.

WHY A TOOL AND NOT A SELF-SERVICE ENDPOINT
------------------------------------------
A station that can enrol itself is a station an attacker can enrol. Enrolment
is a deliberate administrative act, performed against the database by someone
who already has access to it, and the resulting key is carried to the station
out of band. Same reasoning that keeps the twin's own user seeding off the API
surface.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import secrets
import sys

DSN = os.environ.get("DT_FLEET_DSN",
                     "postgresql://twin:twin@localhost:5432/fleet")


async def _register(station_id: str, name: str, rotate: bool) -> int:
    try:
        import asyncpg
    except ImportError:
        print("asyncpg is not installed. Install the fleet extra:\n"
              '    pip install -e ".[fleet]"', file=sys.stderr)
        return 2

    key = secrets.token_urlsafe(32)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()

    try:
        cx = await asyncpg.connect(DSN)
    except Exception as exc:  # noqa: BLE001
        print(f"cannot reach the fleet database at {DSN.split('@')[-1]}: {exc}",
              file=sys.stderr)
        return 1

    try:
        existing = await cx.fetchrow(
            "SELECT station_id FROM stations WHERE station_id = $1", station_id)
        if existing and not rotate:
            print(f"station {station_id!r} already exists. "
                  f"Use --rotate to issue a new key.", file=sys.stderr)
            return 1
        if existing:
            await cx.execute(
                "UPDATE stations SET api_key_hash = $2, "
                "name = COALESCE($3, name) WHERE station_id = $1",
                station_id, digest, name or None)
            action = "rotated"
        else:
            await cx.execute(
                "INSERT INTO stations (station_id, name, api_key_hash) "
                "VALUES ($1, $2, $3)", station_id, name or station_id, digest)
            action = "registered"
    finally:
        await cx.close()

    print(f"\nStation {action}: {station_id}")
    print("\n  Set these on the ground station and restart it:\n")
    print(f"    DT_STATION_ID={station_id}")
    print(f"    DT_STATION_KEY={key}")
    print("    DT_FLEET_URL=http://<fleet-server>:8100")
    print("\n  This key is shown ONCE. Only its hash is stored; a lost key is")
    print("  reissued with --rotate, never recovered.\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("station_id", help="e.g. GCS-01")
    ap.add_argument("--name", default="", help="human-readable station name")
    ap.add_argument("--rotate", action="store_true",
                    help="issue a new key for an existing station")
    a = ap.parse_args()
    return asyncio.run(_register(a.station_id, a.name, a.rotate))


if __name__ == "__main__":
    raise SystemExit(main())
