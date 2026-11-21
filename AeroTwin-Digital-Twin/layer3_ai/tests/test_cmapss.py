"""The C-MAPSS benchmark loader.

The tests that matter here are not "it parses". They are:
  * a partial download must FAIL rather than read as a smaller fleet, because
    a smaller fleet silently produces a number that is not the benchmark;
  * the turbofan data must never become mixable with the piston engine.
"""

from __future__ import annotations

import numpy as np
import pytest

from layer3_ai import cmapss

pytestmark = pytest.mark.skipif(
    not cmapss.is_available(),
    reason="C-MAPSS is third-party and not committed; "
           "run scripts/fetch_benchmarks.py",
)


def test_every_subset_loads_with_the_fleet_size_the_data_actually_holds():
    for name in cmapss.SUBSETS:
        s = cmapss.load(name)
        want_train, want_test = cmapss.EXPECTED_UNITS[name]
        assert s.n_train_units == want_train, name
        assert s.n_test_units == want_test, name
        assert len(s.test_rul) == s.n_test_units, name


def test_the_FD004_readme_is_wrong_and_the_data_is_right():
    """NASA's own readme says 248 train / 249 test; the archive holds 249/248.

    The label file settles it: RUL_FD004.txt carries exactly one line per test
    unit, and it has 248. Pinned as a test so that nobody 'corrects' the
    loader back to the readme and turns a real assertion into a broken one.
    """
    s = cmapss.load("FD004")
    assert (s.n_train_units, s.n_test_units) == (249, 248)
    assert len(s.test_rul) == 248


def test_a_truncated_download_is_refused_not_quietly_benchmarked(tmp_path):
    """The failure this guard exists for: half a fleet still parses fine."""
    full = cmapss.load("FD001")
    root = cmapss.default_root()
    for f in (f"train_FD001.txt", f"test_FD001.txt", f"RUL_FD001.txt"):
        (tmp_path / f).write_bytes((root / f).read_bytes())

    # Keep only the first 50 training units -- a plausible truncated download.
    raw = np.loadtxt(tmp_path / "train_FD001.txt")
    np.savetxt(tmp_path / "train_FD001.txt", raw[raw[:, 0] <= 50])

    with pytest.raises(ValueError, match="refusing to benchmark"):
        cmapss.load("FD001", tmp_path)
    assert full.n_train_units == 100, "fixture must not disturb the real data"


def test_a_missing_dataset_says_how_to_get_it(tmp_path):
    with pytest.raises(FileNotFoundError, match="fetch_benchmarks"):
        cmapss.load("FD001", tmp_path)


def test_training_targets_count_down_to_zero_at_failure():
    """A training unit runs to failure, so its last cycle IS end of life."""
    s = cmapss.load("FD001")
    y = cmapss.train_targets(s.train_unit, s.train_cycle)
    for u in np.unique(s.train_unit)[:5]:
        m = s.train_unit == u
        assert y[m][np.argmax(s.train_cycle[m])] == 0.0
    assert y.max() == cmapss.RUL_CAP_CYCLES


def test_test_targets_are_trajectories_not_single_points():
    """The label file gives RUL at the LAST cycle only. Prognostics metrics
    need the whole trajectory, so earlier rows must count down toward it."""
    s = cmapss.load("FD001")
    y = cmapss.test_targets(s.test_unit, s.test_cycle, s.test_rul)
    u = np.unique(s.test_unit)[0]
    m = s.test_unit == u
    order = np.argsort(s.test_cycle[m])
    traj = y[m][order]
    assert np.all(np.diff(traj) <= 0), "RUL must be non-increasing in time"
    assert traj[-1] == pytest.approx(min(s.test_rul[0], cmapss.RUL_CAP_CYCLES))


def test_the_cap_is_the_one_the_published_figures_use():
    """Comparing without the conventional cap compares nothing."""
    assert cmapss.RUL_CAP_CYCLES == 125.0


def test_the_turbofan_shares_no_channel_with_the_reference_engine():
    """The compatibility claim, asserted rather than left in a docstring.

    C-MAPSS is a high-bypass turbofan; the reference engine is a four-cylinder
    piston engine. If a future change ever gives them a shared feature name,
    somebody is about to mix them, and this test is where that stops.
    """
    from common import config

    piston = set()
    eng = config.load_engine("rotax_915is")
    for group in ("geometry", "limits", "vibration"):
        piston |= {k.lower() for k in eng.get(group, {})}
    piston |= {"cht", "egt", "oil_pressure", "oil_temperature", "fuel_flow",
               "rpm", "vibration_rms", "injection_timing", "manifold_pressure"}

    turbofan = {c.lower() for c in cmapss.COLUMNS}
    assert not (piston & turbofan), (
        f"turbofan and piston channels now overlap: {piston & turbofan}"
    )
