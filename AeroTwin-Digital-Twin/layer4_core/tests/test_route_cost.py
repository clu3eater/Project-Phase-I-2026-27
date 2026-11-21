"""What a proposed mission costs the engine.

These are the checks that matter for a planning number: that it is derived from
the physics rather than from a coefficient, that it moves in the right
direction when the conditions get harder, and that every assumption it had to
make is reported rather than buried.
"""

from __future__ import annotations

import pytest

from layer4_core.route_cost import (
    RouteAssumptions,
    Waypoint,
    assess_route,
    great_circle_km,
)

# Two real places, so the distance can be checked against an atlas rather than
# against the function that produced it.
DELHI = Waypoint("DELHI", 28.6139, 77.2090, 2000.0)
JAIPUR = Waypoint("JAIPUR", 26.9124, 75.7873, 15000.0)


def test_distance_matches_the_map():
    """Delhi to Jaipur is about 235 km great-circle."""
    assert great_circle_km(DELHI, JAIPUR) == pytest.approx(235.0, abs=5.0)


def test_a_route_needs_two_points():
    c = assess_route([DELHI])
    assert c.feasible is False
    assert "two waypoints" in c.reasons[0]


@pytest.mark.slow
def test_fuel_and_time_are_consistent_with_each_other():
    c = assess_route([DELHI, JAIPUR], RouteAssumptions(true_airspeed_kmh=175.0))
    assert c.hours == pytest.approx(c.distance_km / 175.0, rel=1e-6)
    # A 915 iS burns tens of litres an hour at cruise, not hundreds or units.
    assert 15.0 < c.fuel_l / c.hours < 60.0, f"{c.fuel_l / c.hours:.1f} L/h"


@pytest.mark.slow
def test_a_hot_day_costs_more_engine_life_than_a_cold_one():
    """The number has to CARRY information, or it should not be shown.

    Measured on this route: 1.000x at ISA-20, 1.008x at ISA, 1.026x at ISA+30.
    The spread is small because a healthy cooling system holds its temperatures
    -- which is the physically honest answer, and the reason the figure gets
    interesting on an engine whose cooling is no longer healthy.
    """
    route = [DELHI, JAIPUR, DELHI]
    cold = assess_route(route, RouteAssumptions(isa_deviation_c=-20.0))
    hot = assess_route(route, RouteAssumptions(isa_deviation_c=30.0))
    assert hot.life_ratio > cold.life_ratio, (
        f"hot {hot.life_ratio:.3f} vs cold {cold.life_ratio:.3f}: the life "
        "figure does not respond to conditions and would be decoration")


@pytest.mark.slow
def test_a_route_beyond_the_tanks_is_refused_with_the_numbers():
    far = Waypoint("FAR", 19.0760, 72.8777, 15000.0)      # Mumbai
    c = assess_route([DELHI, far, DELHI], RouteAssumptions(usable_fuel_l=50.0))
    assert c.feasible is False
    assert any("usable" in r for r in c.reasons), c.reasons


@pytest.mark.slow
def test_every_assumption_is_reported_with_the_answer():
    """An assumption a reader cannot see is one they cannot disagree with.

    Ground speed and the absence of wind are AIRFRAME matters, and this
    repository models an engine.
    """
    c = assess_route([DELHI, JAIPUR])
    for key in ("true_airspeed_kmh", "usable_fuel_l", "isa_deviation_c", "wind"):
        assert key in c.assumptions, f"{key} is assumed and not declared"
    assert "no wind" in c.assumptions["note"]


@pytest.mark.slow
def test_the_limiting_component_is_named():
    """A verdict without the component that produced it cannot be acted on."""
    c = assess_route([DELHI, JAIPUR])
    assert c.limiting_component, "no limiting component reported"
    assert 0.0 <= c.limiting_margin <= 1.0


@pytest.mark.slow
def test_legs_sum_to_the_route():
    c = assess_route([DELHI, JAIPUR, DELHI])
    assert sum(l.distance_km for l in c.legs) == pytest.approx(c.distance_km, rel=1e-9)
    assert sum(l.fuel_l for l in c.legs) == pytest.approx(c.fuel_l, rel=1e-9)
    assert sum(l.hours for l in c.legs) == pytest.approx(c.hours, rel=1e-9)


# ---------------------------------------------------------------------------
# The reach envelope -- how far this engine can still go
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_a_worn_engine_reaches_less_far_than_a_new_one():
    """The first version of this got the SIGN wrong and has to stay fixed.

    Flown at a fixed throttle, a degraded engine burns less fuel than an as-new
    one -- because it is making less power and flying slower, not because it is
    more efficient. That produced a worn engine with a LARGER radius: 365 km of
    reach gained by wearing the engine out.

    An aircraft holds its airspeed, so the airframe demands a POWER and the
    engine opens the throttle until it makes it. Measured that way: 32.0 L/h
    as-new against 34.5 L/h heavily worn, and 328 km of radius against 304.
    """
    from layer2_physics.degradation import DegradationFactors

    from layer4_core.route_cost import reach_envelope

    worn = DegradationFactors(combustion_efficiency=0.90,
                              turbocharger_condition=0.80,
                              injector_condition=0.85)
    e = reach_envelope(worn)
    assert e.fuel_flow_lph > e.fuel_flow_new_lph, (
        f"worn burns {e.fuel_flow_lph:.1f} L/h against {e.fuel_flow_new_lph:.1f} "
        "as-new: the comparison is holding throttle instead of power again")
    assert e.radius_km < e.radius_new_km
    assert e.lost_km > 0 and 0 < e.lost_pct < 100


@pytest.mark.slow
def test_an_as_new_engine_has_lost_nothing():
    from layer4_core.route_cost import reach_envelope

    e = reach_envelope(None)
    assert e.lost_km == pytest.approx(0.0, abs=1e-6)
    assert e.radius_km == pytest.approx(e.radius_new_km, rel=1e-9)
    assert e.holds_cruise is True


@pytest.mark.slow
def test_more_wear_costs_more_reach():
    """Monotonic, or the picture drawn from it means nothing."""
    from layer2_physics.degradation import DegradationFactors

    from layer4_core.route_cost import reach_envelope

    light = reach_envelope(DegradationFactors(combustion_efficiency=0.96,
                                              turbocharger_condition=0.93))
    heavy = reach_envelope(DegradationFactors(combustion_efficiency=0.90,
                                              turbocharger_condition=0.80,
                                              injector_condition=0.85))
    assert heavy.radius_km < light.radius_km, (
        f"heavy {heavy.radius_km:.0f} km is not less than light "
        f"{light.radius_km:.0f} km")


@pytest.mark.slow
def test_the_basis_of_the_radius_is_stated():
    """A circle on a map with no stated basis is a claim, not a figure."""
    from layer4_core.route_cost import reach_envelope

    e = reach_envelope(None)
    for word in ("cruise", "reserve", "wind"):
        assert word in e.basis, f"the basis does not mention {word}: {e.basis}"
