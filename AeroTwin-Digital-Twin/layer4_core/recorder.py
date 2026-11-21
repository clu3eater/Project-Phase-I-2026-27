"""Flight data recorder -- what makes mission replay real.

WHY THIS EXISTS
---------------
The problem statement asks for "replay of historical mission data" and
"supporting post-flight analysis". `layer4_core/replay.py` delivers a scrubber,
event markers and a full investigation view -- over the SYNTHETIC TRAINING
FLEET. Nothing recorded a real sortie, so nothing could replay one. You could
replay the data the models were trained on, which is a different thing from
replaying yesterday's flight.

WHY IT WRITES THE TRAINING-FLEET SCHEMA
---------------------------------------
Deliberately the same column names, so `replay.py` reads a recorded sortie with
no changes at all, and so a real flight can be put through the exact analysis
code the fleet was. A second format would have meant a second reader, and then
two subtly different definitions of `res_cht`.

WHAT IT DOES NOT WRITE, AND WHY THAT MATTERS
--------------------------------------------
The training fleet carries `lab_*`, `deg_*` and `*_true` columns -- the
injected fault, the true degradation state, the true health. Those exist
because a simulator knows the answer. A real aircraft does not. Writing them as
nulls would put ground-truth-shaped holes in a real recording and invite
somebody to score a model against them; omitting them says plainly that a real
flight has MEASUREMENTS and ESTIMATES and no truth. `chi` IS written, because
it is the health the system estimated at the time, which is exactly what an
investigator wants -- what did it think, and when.

WHY PARQUET AND NOT THE SQLITE USED ELSEWHERE
----------------------------------------------
The same criterion as everywhere else in this project, applied to a different
row count. Flight history is one row per sortie, so SQLite. A recording is
2 Hz across ~40 columns for hours -- roughly 330,000 rows for a five-hour
sortie, and columnar by nature, since analysis reads three columns out of
forty. That is Parquet's case exactly, and pyarrow is already a core
dependency because pandas needs it.

BUFFERED, BECAUSE THE TICK LOOP MUST NEVER WAIT ON A DISK
----------------------------------------------------------
Rows accumulate in memory and are flushed as row groups. Flushing every tick
would put file I/O inside the 10-20 ms physics budget of PRD Part 1 s6.4.

EACH FLUSH IS A COMPLETE FILE, WHICH IS WHAT MAKES THE ABOVE TRUE
------------------------------------------------------------------
This module used to hold one ParquetWriter open for the whole sortie and claim
that flushing on a timer meant "a crash costs seconds of recording rather than
the sortie". It did not. A Parquet file's FOOTER is written by close(), and a
Parquet file with no footer is not a damaged Parquet file -- it is not a
Parquet file. Every recording made by a process that was killed was unreadable
in full, and three consecutive ones on the development machine were.

So a flush now writes its own numbered part and closes it at once. Every part
is valid the instant it reaches the disk. `close()` concatenates the parts into
the single file the rest of the system expects; `recover()` does the same for
parts left behind by a process that died, so the cost of a crash is the last
few seconds of buffer, which is what was promised.

The edge buffer chose SQLite WAL to survive power loss. The ground station is
not less exposed than the aircraft -- it is a laptop in a tent -- and it should
not have had a weaker guarantee.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common import config

_log = logging.getLogger(__name__)

# The measurable subset of the training-fleet schema, in schema order, so a
# recording and a fleet shard line up column for column.
MEASURED = (
    "t_s", "flight_hours",
    "rpm", "cht_max", "cht_spread", "coolant_temperature",
    "egt_max", "egt_spread", "oil_pressure", "oil_temperature",
    "fuel_flow", "manifold_pressure", "manifold_air_temp", "fuel_pressure",
    "vibration_rms_total", "vibration_kurtosis",
    "battery_voltage", "alternator_current",
    "injection_deviation_max", "ignition_deviation_max",
    "injection_period_ms", "injector_duty", "knock_retard_deg",
    "throttle_pct", "altitude_ft", "oat_c", "airspeed_kmh",
    "air_flow_g_per_min", "cht_minus_coolant",
)

RESIDUALS = (
    "res_cht", "res_coolant", "res_egt", "res_oil_pressure",
    "res_oil_temperature", "res_fuel_flow", "res_manifold_pressure",
)

# Estimates, not truth. Named without the `_true` suffix the fleet uses, so
# nothing can mistake one for the other.
ESTIMATED = ("chi", "shadow_available")

# Channels the twin carries that the SYNTHETIC FLEET never had. Recording them
# costs nothing now and is the only way a future analysis can use them:
#   propeller_rpm -- an INDEPENDENT estimate of engine speed through the fixed
#     reduction gearbox. DEV-101 records that the rpm residual is zero by
#     construction, because the shadow model is driven BY measured rpm. A
#     second, physically separate speed sensor is the way out of that, and it
#     cannot be explored on data that never contained it.
#   wastegate_pct -- turbo control authority. The fleet simulates turbocharger
#     degradation (deg_turbocharger_condition) while giving the detector no
#     turbo-specific measurement to see it with.
#   cooling_flap_pct, oil_flap_pct -- the airframe cooling authority. The
#     same argument as the wastegate above, and measured the stronger of
#     the two: losing 30 % of the cooling air moves the flap 31.8
#     sensor-sigmas and the coolant temperature 4.0.
EXTRA = ("propeller_rpm", "wastegate_pct", "cooling_flap_pct", "oil_flap_pct")

COLUMNS = MEASURED + RESIDUALS + ESTIMATED + EXTRA

# Column -> where it lives in the twin's reported state.
_PATHS: dict[str, tuple[str, ...]] = {
    "rpm": ("rpm",),
    "cht_max": ("cht_max",),
    "cht_spread": ("cht", "spread"),
    "coolant_temperature": ("coolant_temperature",),
    "egt_max": ("egt_max",),
    "egt_spread": ("egt", "spread"),
    "oil_pressure": ("oil_pressure",),
    "oil_temperature": ("oil_temperature",),
    "fuel_flow": ("fuel_flow",),
    "manifold_pressure": ("manifold_pressure",),
    "manifold_air_temp": ("manifold_air_temperature",),
    "fuel_pressure": ("fuel_pressure",),
    "vibration_rms_total": ("vibration", "rms_total"),
    "vibration_kurtosis": ("vibration", "kurtosis"),
    "battery_voltage": ("electrical", "bus_voltage"),
    "alternator_current": ("electrical", "alternator_current"),
    "injection_deviation_max": ("timing", "injection_deviation_max"),
    "ignition_deviation_max": ("timing", "ignition_deviation_max"),
    "injection_period_ms": ("timing", "injection_period_ms"),
    "injector_duty": ("timing", "injector_duty_pct"),
    "knock_retard_deg": ("timing", "knock_retard_deg"),
    "throttle_pct": ("throttle_pct",),
    "altitude_ft": ("environmental", "altitude_ft"),
    "oat_c": ("environmental", "oat_c"),
    "airspeed_kmh": ("environmental", "airspeed_kmh"),
    "air_flow_g_per_min": ("air_flow_g_per_min",),
    "propeller_rpm": ("propeller_rpm",),
    "wastegate_pct": ("wastegate_pct",),
    "cooling_flap_pct": ("cooling_flap_pct",),
    "oil_flap_pct": ("oil_flap_pct",),
}

FLUSH_ROWS = 240          # two minutes at 2 Hz
FLUSH_SECONDS = 30.0


class FlightRecorder:
    """Writes one sortie to one Parquet file."""

    def __init__(
        self,
        aircraft_id: str = "MALE-01",
        engine_key: str = "rotax_915is",
        directory: Path | str | None = None,
    ) -> None:
        self.aircraft_id = aircraft_id
        self.engine_key = engine_key
        base = Path(directory) if directory else Path(config.data_dir()) / "recordings"
        base.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.path = base / f"{aircraft_id}_{stamp}.parquet"

        self._buf: list[dict[str, Any]] = []
        self._rows = 0
        # Which numbered part comes next. Each flush writes one and closes it,
        # so there is never an open writer to lose.
        self._parts = 0
        self._writer: Any = None
        self._last_flush = time.monotonic()
        self._lock = threading.Lock()

    @property
    def rows(self) -> int:
        """Rows recorded, INCLUDING those still buffered for the next flush.

        Counting only flushed rows made the report say 5,040 samples for a
        recording of 5,132, so the two could not be tied together (REP-06).
        """
        return self._rows + len(self._buf)

    # ------------------------------------------------------------------
    def record(self, snap: Any) -> None:
        """Append one tick. Cheap: a dict into a list, and occasionally a flush."""
        row = self._row_from(snap)
        if row is None:
            return
        with self._lock:
            self._buf.append(row)
            due = (len(self._buf) >= FLUSH_ROWS
                   or time.monotonic() - self._last_flush >= FLUSH_SECONDS)
        if due:
            self.flush()

    @staticmethod
    def _row_from(snap: Any) -> dict[str, Any] | None:
        """Flatten one snapshot into the fleet schema.

        The twin groups its readings (`cht`, `egt`, `electrical`,
        `environmental`, `timing`, `vibration`) and the fleet flattens them, so
        the mapping is explicit rather than by-name. The first version guessed
        by name and silently wrote NULL into sixteen of thirty-eight columns --
        a recording that looks complete and is 42 % empty is worse than one
        that fails, which is why the non-null fraction is asserted in the test.

        Anything genuinely absent stays None rather than 0.0: a missing reading
        and a reading of zero are different facts, and Parquet carries nulls.
        """
        rep = (snap.twin or {}).get("reported") or {}
        if not rep:
            return None
        res = (snap.twin or {}).get("residuals") or {}
        pipe = snap.pipeline or {}

        def num(x: Any) -> float | None:
            """A reading is either {value, state, ...} or already a number."""
            if isinstance(x, dict):
                x = x.get("value")
            return float(x) if isinstance(x, (int, float)) else None

        def at(*path: str) -> float | None:
            node: Any = rep
            for key in path:
                if not isinstance(node, dict):
                    return None
                node = node.get(key)
            return num(node)

        row: dict[str, Any] = {c: None for c in COLUMNS}
        row["t_s"] = snap.t_s
        row["flight_hours"] = pipe.get("flight_hours")

        for col, path in _PATHS.items():
            row[col] = at(*path)

        # UNITS. The twin carries a PERCENT (`injector_duty_pct`, around 13.5)
        # and the fleet column `injector_duty` is a FRACTION (0.221 to 0.651).
        # The names differ by a suffix and the mapping above pairs them, so the
        # percent was written straight into the fraction column -- a value
        # roughly sixty times too large, in a column that looks populated and
        # passes every non-null check. `layer4_core/live.py` already converts
        # on the serving path; the recorder did not, so recordings and the
        # fleet they are meant to line up with disagreed on this one channel.
        if row["injector_duty"] is not None:
            row["injector_duty"] = float(row["injector_duty"]) / 100.0

        for name in RESIDUALS:
            # A residual is a RECORD -- measured, predicted, delta, mean_delta,
            # samples, usable -- not a number. The fleet's res_* column is the
            # DELTA (measured minus as-new at the same operating point), so
            # that is what is recorded and the schemas stay compatible.
            r = res.get(name[4:])
            row[name] = r.get("delta") if isinstance(r, dict) else num(r)

        cht, coolant = row["cht_max"], row["coolant_temperature"]
        if cht is not None and coolant is not None:
            row["cht_minus_coolant"] = cht - coolant

        row["chi"] = (snap.health or {}).get("chi")
        row["shadow_available"] = bool(pipe.get("shadow_available"))
        return row

    # ------------------------------------------------------------------
    def _part_path(self, index: int) -> Path:
        """Numbered so parts concatenate in the order they were written.

        Zero-padded because a crashed sortie is recovered by sorting the
        directory listing, and part10 sorts before part2 as a string.
        """
        return self.path.with_suffix(f".part{index:04d}.parquet")

    def flush(self) -> int:
        """Write the buffered rows as their own complete file.

        Returns rows written. The part is closed before this returns, so it is
        readable from the moment it exists -- which is the whole point.
        """
        import pyarrow as pa
        import pyarrow.parquet as pq

        with self._lock:
            if not self._buf:
                return 0
            batch, self._buf = self._buf, []
            self._last_flush = time.monotonic()
            index = self._parts
            self._parts += 1

        table = pa.Table.from_pylist(batch, schema=self._schema())
        pq.write_table(table, self._part_path(index), compression="zstd")
        self._rows += len(batch)
        return len(batch)

    @staticmethod
    def _schema() -> Any:
        import pyarrow as pa

        return pa.schema([
            pa.field(c, pa.bool_() if c == "shadow_available" else pa.float64())
            for c in COLUMNS
        ])

    def _combine(self) -> int:
        """Concatenate the parts into the final file and remove them.

        Returns the number of rows written. Parts are removed only after the
        combined file is on disk, so an interruption HERE leaves the parts
        rather than losing both.
        """
        import pyarrow.parquet as pq

        parts = sorted(self.path.parent.glob(
            f"{self.path.stem}.part*.parquet"))
        if not parts:
            return 0

        writer = None
        rows = 0
        torn: list[Path] = []
        try:
            for part in parts:
                try:
                    table = pq.read_table(part)
                except Exception:
                    # A PART WITHOUT A FOOTER IS THE SIGNATURE OF THE EXACT
                    # CRASH THIS CODE EXISTS TO RECOVER FROM.
                    #
                    # A parquet file is only readable once its footer has been
                    # written, so a process killed mid-flush leaves its LAST
                    # part torn. Letting that raise cost the whole sortie --
                    # and, because `recover_orphans` runs from the API's
                    # lifespan, the whole ground station: startup died with
                    # "Parquet magic bytes not found in footer" and the
                    # console would not come up at all.
                    #
                    # So the part is skipped and the other sixteen hundred are
                    # recovered, which is what the buffering was always for.
                    torn.append(part)
                    _log.warning("recording part unreadable, skipped",
                                 extra={"part": str(part),
                                        "bytes": part.stat().st_size})
                    continue
                if writer is None:
                    writer = pq.ParquetWriter(self.path, table.schema,
                                              compression="zstd")
                writer.write_table(table)
                rows += table.num_rows
        finally:
            if writer is not None:
                writer.close()
        for part in parts:
            if part in torn:
                # KEPT, NOT DELETED. It is the only evidence of how the last
                # run ended, and an investigator may want it. Renamed out of
                # the `*.part*.parquet` glob so it is not retried on every
                # startup for the rest of the file's life.
                spoil = part.with_suffix(part.suffix + ".torn")
                spoil.unlink(missing_ok=True)
                part.rename(spoil)
                continue
            part.unlink(missing_ok=True)
        return rows

    def recover(self) -> Path | None:
        """Assemble a final file from parts a dead process left behind.

        Called at startup. A sortie whose ground station was killed still
        yields everything that reached the disk, which is what the buffering
        was always supposed to guarantee.
        """
        rows = self._combine()
        if rows:
            _log.warning("recovered a recording left by an unclean shutdown",
                         extra={"path": str(self.path), "rows": rows})
            return self.path
        return None

    def close(self) -> Path | None:
        """Final flush and close. Returns the file, or None if nothing recorded."""
        self.flush()
        self._combine()
        if self._rows == 0:
            # A sortie that recorded nothing leaves no file, rather than an
            # empty one an investigator would open and then mistrust.
            self.path.unlink(missing_ok=True)
            _log.info("recording discarded, no rows",
                      extra={"aircraft_id": self.aircraft_id})
            return None
        _log.info("flight recorded",
                  extra={"path": str(self.path), "rows": self._rows,
                         "aircraft_id": self.aircraft_id})
        return self.path


def recover_orphans(directory: Path | str | None = None) -> list[Path]:
    """Rebuild every recording a killed process left as loose parts.

    `FlightRecorder.recover` only knows about its OWN path, and a new run has a
    new timestamp in its name -- so it would never touch the parts the last run
    abandoned. This scans the directory instead, which is the only thing that
    makes the crash-safety reach a sortie that has already ended.
    """
    base = Path(directory) if directory else Path(config.data_dir()) / "recordings"
    if not base.is_dir():
        return []

    # Group parts by the recording they belong to: NAME.partNNNN.parquet, so
    # the stem before ".part" identifies the sortie.
    stems: set[str] = set()
    for part in base.glob("*.part*.parquet"):
        head = part.name.split(".part")[0]
        if head:
            stems.add(head)

    out = []
    for stem in sorted(stems):
        target = base / f"{stem}.parquet"
        if target.exists():
            # A completed recording plus stray parts: the parts are a
            # half-written retry and the finished file wins.
            for part in base.glob(f"{stem}.part*.parquet"):
                part.unlink(missing_ok=True)
            continue
        r = FlightRecorder.__new__(FlightRecorder)
        r.path = target
        r._lock = threading.Lock()
        if r.recover():
            out.append(target)
    return out


def recordings(directory: Path | str | None = None) -> list[dict]:
    """Every recorded sortie, newest first."""
    base = Path(directory) if directory else Path(config.data_dir()) / "recordings"
    if not base.is_dir():
        return []
    out = []
    for f in sorted(base.glob("*.parquet"), reverse=True):
        try:
            import pyarrow.parquet as pq

            pf = pq.ParquetFile(f)
            out.append({
                "file": f.name,
                "aircraft_id": f.name.split("_")[0],
                "rows": pf.metadata.num_rows,
                "size_kb": round(f.stat().st_size / 1024, 1),
                "columns": len(pf.schema.names),
            })
        except Exception:  # noqa: BLE001
            _log.exception("unreadable recording", extra={"file": str(f)})
    return out
