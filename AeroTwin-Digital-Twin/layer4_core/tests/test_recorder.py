"""The flight data recorder -- what makes mission replay real.

`replay.py` could only ever replay the SYNTHETIC TRAINING FLEET, because
nothing recorded a real sortie. These tests hold the recorder to the two
properties that make a recording trustworthy: it is column-compatible with the
fleet, and it is actually FULL.

The second is not obvious and is the one that bit. The first version mapped
columns by name, and the twin groups its readings (`cht`, `electrical`,
`environmental`, `timing`, `vibration`) while the fleet flattens them. It wrote
NULL into sixteen of thirty-eight columns and looked entirely healthy: right
row count, right schema, right file size. A recording that appears complete and
is 42 % empty is worse than one that fails.
"""

from __future__ import annotations

import time

import pytest

from layer4_core.live import LiveTwin
from layer4_core.recorder import (
    COLUMNS,
    FlightRecorder,
    recordings,
    recover_orphans,
)


@pytest.mark.slow
def _record(tmp_path, seconds: float = 12.0) -> tuple:
    r = FlightRecorder("MALE-01", directory=tmp_path)
    twin = LiveTwin(speed=400.0)
    twin._on_tick = r.record
    twin.start()
    try:
        time.sleep(seconds)
    finally:
        twin.stop()
    return r, r.close()


@pytest.mark.slow
def test_a_recording_is_full_not_merely_present(tmp_path):
    """EVERY column carries data. The regression that motivated this file."""
    import pandas as pd

    r, path = _record(tmp_path)
    assert path is not None and r.rows > 0
    df = pd.read_parquet(path)

    # `chi` is the health the system ASSESSED, and the engine's condition is
    # judged only warm, loaded and steady (health.assessment). Twelve seconds
    # of the twin is the start and the warm-up, where it is withheld -- a null
    # there is the right record, not a hole. Every other column must carry data.
    empty = [c for c in df.columns if df[c].isna().all() and c != "chi"]
    assert not empty, f"columns recorded as all-null: {empty}"
    assert df.drop(columns=["chi"]).notna().mean().mean() > 0.99


@pytest.mark.slow
def test_a_recording_carries_no_ground_truth(tmp_path):
    """A real aircraft does not know the answer.

    Writing lab_/deg_/_true columns as nulls would leave ground-truth-shaped
    holes and invite somebody to score a model against them.
    """
    import pandas as pd

    _, path = _record(tmp_path)
    df = pd.read_parquet(path)
    bad = [c for c in df.columns
           if c.startswith(("lab_", "deg_")) or c.endswith("_true")]
    assert not bad, f"ground truth leaked into a real recording: {bad}"
    # chi IS present: the health the system ESTIMATED at the time.
    assert "chi" in df.columns


@pytest.mark.slow
def test_the_schema_matches_the_training_fleet_column_names(tmp_path):
    """So replay.py reads a recorded sortie with no changes."""
    import pandas as pd

    _, path = _record(tmp_path)
    df = pd.read_parquet(path)
    assert list(df.columns) == list(COLUMNS)
    for shared in ("t_s", "flight_hours", "rpm", "cht_max", "res_cht"):
        assert shared in df.columns


@pytest.mark.slow
def test_a_sortie_that_recorded_nothing_leaves_no_file(tmp_path):
    """Rather than an empty file an investigator would open and mistrust."""
    r = FlightRecorder("MALE-02", directory=tmp_path)
    assert r.close() is None
    assert not r.path.exists()


@pytest.mark.slow
def test_recordings_are_discoverable(tmp_path):
    _, path = _record(tmp_path)
    found = recordings(tmp_path)
    assert len(found) == 1
    assert found[0]["aircraft_id"] == "MALE-01"
    assert found[0]["rows"] > 0
    assert found[0]["columns"] == len(COLUMNS)


@pytest.mark.slow
def test_injector_duty_is_recorded_as_a_fraction_not_a_percent(tmp_path):
    """The one channel the twin and the fleet name alike and scale differently.

    The twin carries `timing.injector_duty_pct`, a PERCENT around 13.5. The
    fleet column is `injector_duty`, a FRACTION between 0.221 and 0.651. The
    names differ only by a suffix, so the percent was written straight into the
    fraction column -- roughly sixty times too large, in a column that looks
    populated and passes every non-null and schema check above.

    Asserting a plausible RANGE rather than a value: the point is the scale,
    and a duty cycle above 1.0 is not a fraction whatever the engine is doing.
    """
    import pandas as pd

    _, path = _record(tmp_path)
    duty = pd.read_parquet(path)["injector_duty"].dropna()
    assert len(duty) > 0, "no injector_duty recorded, so nothing was checked"
    assert duty.max() <= 1.0, (
        f"injector_duty max {duty.max():.3f} exceeds 1.0 -- a percent has "
        f"been written into a fraction column"
    )
    assert duty.min() >= 0.0


# ---------------------------------------------------------------------------
# Surviving a kill -- the guarantee the docstring claimed and did not have
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_a_recording_survives_the_process_being_killed(tmp_path):
    """The old writer held one ParquetWriter open for the whole sortie.

    A Parquet file's FOOTER is written by close(), so a file from a killed
    process is not a damaged Parquet file -- it is not a Parquet file, and the
    ENTIRE sortie is unreadable. Three consecutive recordings on the
    development machine were lost exactly that way.

    close() is deliberately never called here, the way it is never called when
    something is killed.
    """
    import pandas as pd

    r = FlightRecorder("MALE-09", directory=tmp_path)
    twin = LiveTwin(speed=400.0)
    twin._on_tick = r.record
    twin.start()
    try:
        time.sleep(8.0)
    finally:
        twin.stop()
    written = r.flush()
    assert written, "nothing was flushed"

    # The recorder is now abandoned, as a killed process abandons it.
    parts = sorted(tmp_path.glob("*.part*.parquet"))
    assert parts, "a flush left nothing readable behind"
    for part in parts:
        # Each part must read ON ITS OWN -- the property the single long-lived
        # writer did not have.
        assert len(pd.read_parquet(part)) > 0

    # A fresh recorder for the same flight recovers what reached the disk.
    survivor = FlightRecorder("MALE-09", directory=tmp_path)
    survivor.path = r.path
    recovered = survivor.recover()
    assert recovered is not None and recovered.exists()
    assert len(pd.read_parquet(recovered)) == r.rows
    assert not list(tmp_path.glob("*.part*.parquet")), "parts left behind"


@pytest.mark.slow
def test_a_clean_close_leaves_one_file_and_no_fragments(tmp_path):
    """The normal path must not litter the directory with parts."""
    import pandas as pd

    r, path = _record(tmp_path, seconds=8.0)
    assert path is not None and path.exists()
    assert not list(tmp_path.glob("*.part*.parquet")), "parts survived close()"
    assert len(pd.read_parquet(path)) == r.rows


@pytest.mark.slow
def test_orphan_parts_from_a_previous_run_are_rebuilt_at_startup(tmp_path):
    """Recovery only helps if something looks for the parts.

    `FlightRecorder.recover` knows its OWN path, and a new run has a new
    timestamp in its name -- so it would never touch what the last run left
    behind. The scan is what makes the guarantee reach a sortie that has
    already ended.
    """
    import pandas as pd

    r = FlightRecorder("MALE-11", directory=tmp_path)
    twin = LiveTwin(speed=400.0)
    twin._on_tick = r.record
    twin.start()
    try:
        time.sleep(8.0)
    finally:
        twin.stop()
    assert r.flush() and not r.path.exists(), "close() was not supposed to run"

    restored = recover_orphans(tmp_path)
    assert restored == [r.path], restored
    # Every part, not the last flush: eight seconds at 400x can pass
    # FLUSH_ROWS, and then the run left two parts (measured 240 + 146).
    assert len(pd.read_parquet(r.path)) == r.rows
    assert not list(tmp_path.glob("*.part*.parquet"))


def test_stray_parts_beside_a_finished_recording_are_discarded(tmp_path):
    """A completed file wins over a half-written retry.

    Otherwise a crash during the final combine would leave both, and the next
    startup would have to guess which was authoritative.
    """
    finished = tmp_path / "MALE-12_20260101T000000Z.parquet"
    finished.write_bytes(b"not really parquet, but it exists")
    stray = tmp_path / "MALE-12_20260101T000000Z.part0000.parquet"
    stray.write_bytes(b"fragment")

    assert recover_orphans(tmp_path) == []
    assert finished.exists(), "the completed recording was removed"
    assert not stray.exists(), "the stray fragment was kept"
