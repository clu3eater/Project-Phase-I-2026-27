"""The problem statement is a contract. This test enforces it.

Requirements that are MANDATORY in the problem statement -- the nine monitored
parameters of section B and the eight faults of section C -- must be present in
the configuration and on the bus at all times. This test exists because a
refactor silently dropped injection timing from the CAN database while leaving
its threshold in place, and nothing caught it until an audit was run by hand.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cantools
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from common import config  # noqa: E402
from layer2_physics.atmosphere import ENV_PROFILES, EnvCondition  # noqa: E402
from layer2_physics.degradation import FAULT_CLASS_ORDER  # noqa: E402


@pytest.fixture(scope="module")
def can_signals() -> set[str]:
    db = cantools.database.load_file(str(REPO / "configs" / "can" / "engine.dbc"))
    return {s.name for m in db.messages for s in m.signals}


# Problem statement section B: "Monitoring of following engine parameter are
# required". Eight bullets, nine signals -- "Oil Pressure & Temperature" is one
# bullet covering two independent measurements.
PS_SECTION_B = [
    ("RPM", "rpm", "ENGINE_SPEED"),
    ("Cylinder Head Temperature", "cht", "CHT_CYL1"),
    ("Exhaust Gas Temperature", "egt", "EGT_CYL1"),
    ("Oil Pressure", "oil_pressure", "OIL_PRESSURE"),
    ("Oil Temperature", "oil_temperature", "OIL_TEMPERATURE"),
    ("Fuel flow", "fuel_flow", "FUEL_FLOW"),
    ("Vibration signatures", "vibration_rms", "VIB_RMS_X"),
    ("Battery / Alternator health", "battery_voltage", "DC_VOLTAGE"),
    ("Injection timing parameters", "injection_timing", "INJ_TIMING_CYL1"),
]


@pytest.mark.parametrize("label,threshold_key,signal", PS_SECTION_B)
def test_required_parameter_has_a_threshold(label, threshold_key, signal):
    params = config.load_thresholds()["parameters"]
    assert threshold_key in params, (
        f"problem statement section B requires {label!r}, but "
        f"thresholds.yaml has no parameter {threshold_key!r}"
    )
    spec = params[threshold_key]
    assert "plausible_range" in spec or "range" in spec


@pytest.mark.parametrize("label,threshold_key,signal", PS_SECTION_B)
def test_required_parameter_is_carried_on_the_bus(label, threshold_key, signal, can_signals):
    assert signal in can_signals, (
        f"problem statement section B requires {label!r}, but the CAN database "
        f"carries no signal {signal!r}. A threshold with no signal is a "
        f"parameter we claim to monitor and cannot."
    )


# Problem statement section C: "The detection/prediction of following
# parameters are required". Eight faults.
PS_SECTION_C = [
    "misfire",
    "injector_abnormal",
    "cooling_degradation",
    "lubrication_issue",
    "sensor_drift",
    "combustion_instability",
    "overheating_trend",
    "abnormal_vibration",
]


@pytest.mark.parametrize("fault", PS_SECTION_C)
def test_required_fault_is_configured_and_injectable(fault):
    faults = config.load_thresholds()["faults"]
    assert fault in faults, f"section C requires {fault!r} in thresholds.yaml"
    assert any(f.value == fault for f in FAULT_CLASS_ORDER), (
        f"section C requires {fault!r} to be injectable for ground-truth generation"
    )


def test_exactly_eight_faults_are_modelled():
    """More would dilute the classifier; fewer would fail the problem statement."""
    assert len(FAULT_CLASS_ORDER) == 8


# Problem statement section E: engine behaviour must be simulable under four
# named conditions.
@pytest.mark.parametrize(
    "condition",
    [
        EnvCondition.HIGH_ALTITUDE,
        EnvCondition.ENDURANCE,
        EnvCondition.HOT_WEATHER,
        EnvCondition.RAPID_THROTTLE,
    ],
)
def test_required_environmental_condition_exists(condition):
    assert condition in ENV_PROFILES, (
        f"problem statement section E requires simulation of {condition.value}"
    )


def test_coding_degradation_is_covered_under_both_readings():
    """The problem statement says "Coding degradation", which is a typo.

    Two readings are defensible and we cover both rather than guess:
      "COOLING degradation" -> the cooling_degradation fault, and the cooling
                               pathway that drives it
      "COKING degradation"  -> carbon coking, covered by the
                               combustion_deposits and injector_fouling
                               pathways
    Whichever the author meant, the system detects it.
    """
    from layer2_physics.degradation import Pathway

    faults = config.load_thresholds()["faults"]
    assert "cooling_degradation" in faults
    assert Pathway.COOLING in Pathway
    assert Pathway.COMBUSTION_DEPOSITS in Pathway
    assert Pathway.INJECTOR_FOULING in Pathway


def test_engine_agnostic_claim_holds_for_every_configured_engine():
    """PS section A: "Modular architecture for future scalability".

    Our specific claim is that adding an engine is a YAML file with zero code
    change. That is only true if every configured engine actually loads and
    runs, so this test keeps us honest about it.
    """
    from layer2_physics import mvem
    from layer2_physics.atmosphere import ambient_at

    keys = config.available_engines()
    assert len(keys) >= 2, "the engine-agnostic claim needs more than one engine"
    amb = ambient_at(10000.0, airspeed_kmh=180.0)
    for key in keys:
        m = mvem.build(key)
        m.initialise_warm(amb)
        out = m.step(0.5, throttle_pct=80.0, ambient=amb)
        assert out.physics_constraint_violations == 0, key
        assert out.power_kw > 0.0, key
