"""Damage does not heal when a fault is cleared.

Reported from the console: inject a fault and remaining life falls; clear it
and life climbs back. An engine that has been damaged is still damaged.

The cause was that a fault CLAMPED a condition index rather than damaging the
quantity the index is derived from. Injector condition is recomputed from
accumulated flow variance on every step, so the clamp disappeared with the
fault: measured 0.325 with the fault active and 0.981 one step after clearing
it. Cooling, combustion, bearing and turbocharger damage already persisted
because those factors ARE the accumulators.

Clearing an injected fault means the fault stops progressing, not that the
engine was repaired. Only maintenance repairs it, and each job restores only
what it physically renews.
"""

from __future__ import annotations

import numpy as np
import pytest

from common import config
from layer2_physics.degradation import DegradationEngine, FaultMode, InjectedFault

FACTORS = ("cooling_efficiency", "oil_quality", "combustion_efficiency",
           "injector_condition", "bearing_condition", "turbocharger_condition",
           "cooling_airflow")


def _engine() -> DegradationEngine:
    return DegradationEngine(engine=config.load_engine("rotax_915is"),
                             rng=np.random.default_rng(0))


def _run(mode: FaultMode, hours: float = 1.0, severity: float = 0.9):
    d = _engine()
    d.inject(InjectedFault(mode=mode, onset_hours=0.0, severity=severity, ramp_hours=0.01))
    steps = max(1, int(hours / 0.05))
    for _ in range(steps):
        d.advance(0.05, oil_temp_c=95.0, cht_max_c=110.0)
    during = {k: getattr(d.factors, k) for k in FACTORS}
    d.clear_faults()
    d.advance(0.05, oil_temp_c=95.0, cht_max_c=110.0)
    return d, during, {k: getattr(d.factors, k) for k in FACTORS}


@pytest.mark.parametrize("mode", list(FaultMode))
def test_no_factor_recovers_when_a_fault_is_cleared(mode):
    """The general rule, checked for every fault the system can inject."""
    _d, during, after = _run(mode)
    healed = {k: (during[k], after[k]) for k in FACTORS
              if after[k] > during[k] + 1e-9}
    assert not healed, f"{mode.value} healed on clear: {healed}"


def test_a_cleared_injector_fault_leaves_the_engine_fouled():
    """The case that was reported: 0.325 during, 0.981 one step after clearing."""
    _d, during, after = _run(FaultMode.INJECTOR_ABNORMAL)
    assert during["injector_condition"] < 0.5
    assert after["injector_condition"] == pytest.approx(during["injector_condition"], abs=0.01)


def test_cleaning_the_injectors_is_what_restores_them():
    """Maintenance repairs; clearing the fault does not."""
    d, _during, after = _run(FaultMode.INJECTOR_ABNORMAL)
    assert after["injector_condition"] < 0.5
    done = d.perform_maintenance("A3")
    assert "injector_condition" in done["restored"]
    assert d.factors.injector_condition > 0.99
    # And the deposit itself is gone, not just the index.
    d.advance(0.05, oil_temp_c=95.0, cht_max_c=110.0)
    assert d.factors.injector_condition > 0.99
