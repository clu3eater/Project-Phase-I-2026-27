"""Replay of flights flown on this station (layer4_core/sortie_replay.py)."""

from __future__ import annotations

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from layer4_core import sortie_replay as sr


@pytest.fixture()
def recordings(tmp_path, monkeypatch):
    monkeypatch.setenv("DT_DATA_DIR", str(tmp_path))
    d = tmp_path / "recordings"
    d.mkdir()
    n = 400
    t = [float(i) for i in range(n)]
    # parked 100 s, engine runs 100..300, airborne 150..250, CHT over 135 at 200..210
    rpm = [0.0 if i < 100 or i >= 300 else 5000.0 for i in range(n)]
    alt = [2000.0 if 150 <= i < 250 else 0.0 for i in range(n)]
    cht = [140.0 if 200 <= i < 210 else (100.0 if rpm[i] else 20.0) for i in range(n)]
    tab = pa.table({"t_s": t, "rpm": rpm, "altitude_ft": alt, "cht_max": cht,
                    "egt_max": [800.0] * n, "chi": [0.95] * n})
    pq.write_table(tab, d / "MALE-01_20260925T100000Z.parquet")
    parked = pa.table({"t_s": t, "rpm": [0.0] * n, "altitude_ft": [0.0] * n})
    pq.write_table(parked, d / "MALE-02_20260925T090000Z.parquet")
    return d


def test_only_sessions_where_the_engine_ran_are_listed(recordings):
    ix = sr.index()
    assert [x["tail"] for x in ix] == ["MALE-01"]
    assert ix[0]["kind"] == "sortie"


def test_a_sortie_is_cropped_to_the_engine_run_and_its_events_found(recordings):
    s = sr.session("MALE-01_20260925T100000Z")
    assert s["live"] is False
    assert s["duration_s"] == pytest.approx(259, abs=2)     # 70 .. 329 s
    labels = [e["label"] for e in s["events"]]
    for want in ("Engine start", "Airborne", "Landed", "Engine shut down",
                 "Peak CHT", "CHT over limit"):
        assert want in labels, labels
    over = next(e for e in s["events"] if e["label"] == "CHT over limit")
    assert "10 s" in over["detail"]


def test_a_path_is_never_read_from_the_request(recordings):
    with pytest.raises(KeyError):
        sr.session("../../etc/passwd")
    with pytest.raises(KeyError):
        sr.session("MALE-09_20260925T100000Z")
