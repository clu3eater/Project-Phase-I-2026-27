"""Adding an engine is a configuration change, and it must actually run.

The Austro stub passed the section check for months and died on the first
physics tick, 62 keys short of what the code reads. These tests hold the route
to what it promises: every definition present loads, is complete, and runs
the full virtual engine; `extends:` inherits; per-engine thresholds apply only
while that engine is active.
"""

from __future__ import annotations

import pytest

from common import config


@pytest.fixture(autouse=True)
def _fresh_cache():
    config.clear_cache()
    yield
    config.clear_cache()


def test_every_engine_definition_is_complete():
    for key in config.available_engines():
        assert config.check_engine(key) == [], key


def test_the_template_is_complete_and_not_listed_as_an_engine():
    assert "_template" not in config.available_engines()
    assert config.check_engine("_template") == []


def test_every_engine_runs_the_full_virtual_engine():
    from layer2_physics.engine_sim import VirtualEngine

    for key in config.available_engines():
        veng = VirtualEngine(engine_key=key, seed=3)
        for _ in range(40):
            veng.step(0.5)


def test_extends_inherits_what_the_file_does_not_state(tmp_path, monkeypatch):
    engines = tmp_path / "engines"
    engines.mkdir()
    real = config.config_dir()
    (engines / "rotax_915is.yaml").write_text(
        (real / "engines" / "rotax_915is.yaml").read_text(encoding="utf-8"),
        encoding="utf-8")
    (engines / "child.yaml").write_text(
        "extends: rotax_915is\n"
        "identity: {display_name: Child, validated: false}\n"
        "ratings: {max_power_kW: 120.0}\n"
        "performance_table: null\n", encoding="utf-8")
    (tmp_path / "thresholds.yaml").write_text(
        (real / "thresholds.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("DT_CONFIG_DIR", str(tmp_path))
    config.clear_cache()

    child = config.load_engine("child")
    assert child["ratings"]["max_power_kW"] == 120.0
    # merged, not replaced: the sibling rating is still there
    assert child["ratings"]["max_power_rpm"] == 5800
    assert child["identity"]["ignition"] == "SPARK"
    assert child["performance_table"] is None
    assert child["extends_chain"] == ["rotax_915is"]
    assert config.check_engine("child") == []


def test_a_missing_key_is_named(tmp_path, monkeypatch):
    engines = tmp_path / "engines"
    engines.mkdir()
    real = config.config_dir()
    for name in ("rotax_915is.yaml",):
        (engines / name).write_text(
            (real / "engines" / name).read_text(encoding="utf-8"), encoding="utf-8")
    # The Austro stub as it was: sections present, keys missing.
    stub = (real / "engines" / "austro_ae330.yaml").read_text(encoding="utf-8")
    stub = stub.replace("extends: rotax_915is", "")
    (engines / "bare.yaml").write_text(stub, encoding="utf-8")
    monkeypatch.setenv("DT_CONFIG_DIR", str(tmp_path))
    config.clear_cache()

    problems = config.check_engine("bare")
    assert any("fuel_properties.rail_pressure_bar" in p for p in problems)
    assert any("'limits'" in p for p in problems)
    # a missing section is reported once, not once per key inside it
    assert not any("'limits." in p for p in problems)


def test_extends_loop_is_refused(tmp_path, monkeypatch):
    engines = tmp_path / "engines"
    engines.mkdir()
    (engines / "a.yaml").write_text("extends: b\n", encoding="utf-8")
    (engines / "b.yaml").write_text("extends: a\n", encoding="utf-8")
    monkeypatch.setenv("DT_CONFIG_DIR", str(tmp_path))
    config.clear_cache()
    with pytest.raises(config.ConfigError, match="loops"):
        config.load_engine("a")


def test_engine_thresholds_apply_only_while_that_engine_is_active(monkeypatch):
    # A runtime engine set by an earlier test (the API loads the aircraft on
    # the station, and so its engine) outranks DT_ENGINE. Cleared, so this
    # test measures what it names rather than what ran before it.
    config.set_runtime_engine(None)
    monkeypatch.setenv("DT_ENGINE", "rotax_915is")
    config.clear_cache()
    rotax = config.load_thresholds()["parameters"]["vibration_rms"]["alert_max"]
    monkeypatch.setenv("DT_ENGINE", "austro_ae330")
    config.clear_cache()
    diesel = config.load_thresholds()["parameters"]["vibration_rms"]["alert_max"]
    assert rotax == 5.0
    assert diesel > rotax
    # everything the override does not name is still the global value
    assert (config.load_thresholds()["parameters"]["vibration_rms"]["unit"]
            == "m/s2")


def test_the_loaded_aircrafts_engine_sets_the_limits(monkeypatch):
    monkeypatch.delenv("DT_ENGINE", raising=False)
    try:
        assert config.active_engine() == config.REFERENCE_ENGINE
        config.set_runtime_engine("austro_ae330")
        assert config.active_engine() == "austro_ae330"
        assert config.load_thresholds()["parameters"]["vibration_rms"]["alert_max"] > 5.0
        with pytest.raises(config.ConfigError):
            config.set_runtime_engine("no_such_engine")
    finally:
        config.set_runtime_engine(None)
    assert config.load_thresholds()["parameters"]["vibration_rms"]["alert_max"] == 5.0


def test_catalogue_marks_the_stub_unvalidated():
    cat = {e["key"]: e for e in config.engine_catalogue()}
    assert cat["rotax_915is"]["validated"] is True
    assert cat["austro_ae330"]["validated"] is False
    assert all(e["usable"] for e in cat.values())
