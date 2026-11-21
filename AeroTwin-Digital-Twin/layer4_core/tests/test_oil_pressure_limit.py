"""The oil-pressure minimum depends on engine speed, everywhere it is shown.

Caught on a screenshot of the running console: at 3285 rpm and 22.9 psi the
OIL PRESS tile was red and tagged BELOW LIMIT, directly beside an alert panel
correctly reading "every parameter is inside its limit". Both were reading the
same engine. The rule engine was right -- OM s2.1 allows a minimum of 0.8 bar
below 3500 rpm -- and the display was wrong, which is the one direction of
error a caution display must not make: an operator who is shown a red limit
that is not real learns to discount red.
"""

from __future__ import annotations

import pytest

from common import config

PAR = config.load_thresholds()["parameters"]["oil_pressure"]


def _applies_at(rpm: float) -> float:
    """The published rule, stated once here so the test cannot drift with it."""
    return (float(PAR["high_speed_min_psi"]) if rpm > float(PAR["low_speed_rpm"])
            else float(PAR["critical_min"]))


def test_the_manual_s_two_limits_are_declared_not_defaulted():
    """edge_rules fell back to 3500/29.0 when these keys were absent.

    A default that happens to be right is not the same as a declared value: the
    console and the twin could not read a number that was not written down, and
    both took alert_min instead.
    """
    assert float(PAR["low_speed_rpm"]) == 3500.0     # [OM s2.1]
    assert float(PAR["high_speed_min_psi"]) == 29.0  # [OM s2.1] 2.0 bar
    assert float(PAR["critical_min"]) == pytest.approx(11.6, abs=0.1)  # 0.8 bar


@pytest.mark.parametrize("rpm,oil_psi,legal", [
    (3285.0, 22.9, True),    # the screenshot: below 3500, above 0.8 bar
    (3499.0, 12.0, True),    # just under the step, just over 0.8 bar
    (3501.0, 22.9, False),   # the SAME pressure, now at speed: not legal
    (5800.0, 45.0, True),    # take-off, healthy
    (2000.0, 10.0, False),   # below 0.8 bar at any speed
])
def test_the_limit_shown_matches_the_limit_the_rules_enforce(rpm, oil_psi, legal):
    assert (oil_psi >= _applies_at(rpm)) is legal


def test_the_rule_engine_and_the_display_agree_at_the_step():
    """The rule fires above the step; the displayed limit rises at the step."""
    from layer1_edge.edge_rules import build_rules

    oilp = [r for r in build_rules() if getattr(r, "rule_id", "") == "OILP_AT_SPEED"]
    assert oilp, "OILP_AT_SPEED has gone; the display limit now has no counterpart"
    assert _applies_at(3499.0) < _applies_at(3501.0), (
        "the displayed minimum must step up exactly where the rule starts firing")


def test_the_twin_publishes_the_limit_rather_than_the_console_deriving_it():
    """A console that re-derives the CONDITION drifts the same way it did."""
    import inspect

    from layer4_core import live

    src = inspect.getsource(live.LiveTwin)
    assert "oil_pressure_min_psi" in src, (
        "the twin must publish the applicable minimum; the console had the "
        "number and not the condition attached to it, which is how it came to "
        "contradict the alert panel")


def test_no_console_page_uses_the_high_speed_minimum_directly():
    """The same defect appeared on two pages and was fixed on one.

    Overview was corrected first; the Engine page kept `alert_min` and went on
    showing OIL PRESS 20.0 psi as LOW against "limit 29" while taxiing at
    2065 rpm, beside an alerts panel correctly reading "No active alerts". A
    speed-dependent limit written out per page will be missed per page, so the
    rule is checked once here across the whole console.
    """
    from common import config

    src = config.repo_root() / "layer5_viz" / "gcs_console" / "src"
    offenders = []
    for f in src.rglob("*.tsx"):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if "oil_pressure?.alert_min" in line and not line.lstrip().startswith(("*", "//")):
                offenders.append(f"{f.relative_to(src)}:{i}")
    assert not offenders, (
        "these use the >3500 rpm minimum at every engine speed; read "
        "snap.display.oil_pressure_min_psi, which the twin publishes: "
        + ", ".join(offenders))
