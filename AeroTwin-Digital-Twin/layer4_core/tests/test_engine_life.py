"""The engine's life outlives the station process.

`LiveTwin.save_engine_life` / `_restore_engine_life` carry wear, hours and the
health trend across a ground-station restart. These tests pin the part that is
easy to lose without anyone noticing: the engine's own residual reference.
Re-formed at every start, it took whatever wear the engine already had for
build offset and subtracted it out of every residual the RUL network and the
survival head read -- a worn engine came back from each restart looking new.
"""

from __future__ import annotations

import pytest

from layer4_core.live import LiveTwin


@pytest.fixture
def life_file(tmp_path, monkeypatch):
    path = tmp_path / "UAV-TEST.pkl"
    monkeypatch.setattr(LiveTwin, "_life_path", lambda self: path)
    return path


def test_the_residual_reference_survives_a_restart(life_file):
    first = LiveTwin(twin_id="UAV-TEST", seed=11, persist=True)
    ref = first.rul_net.baseline
    ref._median = {"res_oil_pressure": -1.5}
    ref.frozen = True
    first.save_engine_life()
    first.sim.close()
    assert life_file.exists()

    second = LiveTwin(twin_id="UAV-TEST", seed=11, persist=True)
    try:
        assert second.engine_life_restored is not None
        again = second.rul_net.baseline
        assert again.frozen
        assert again.observe({"res_oil_pressure": 8.5}, 2.0)["res_oil_pressure"] == (
            pytest.approx(10.0))
    finally:
        second.sim.close()


def test_a_different_engine_does_not_inherit_the_reference(life_file):
    first = LiveTwin(twin_id="UAV-TEST", seed=11, persist=True)
    first.rul_net.baseline._median = {"res_oil_pressure": -1.5}
    first.rul_net.baseline.frozen = True
    first.save_engine_life()
    first.sim.close()

    other = LiveTwin(twin_id="UAV-TEST", seed=12, persist=True)
    try:
        assert other.engine_life_restored is None
        assert not other.rul_net.baseline.frozen
    finally:
        other.sim.close()
