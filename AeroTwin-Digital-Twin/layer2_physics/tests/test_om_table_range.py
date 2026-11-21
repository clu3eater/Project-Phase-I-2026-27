"""Where the manufacturer's performance table stops, the twin must say so.

Rotax OM 915 i Ed.0 Rev.4 prints its performance table for 4500-5800 rpm,
sea level to 22,999 ft and ISA-15 to ISA+30. Beyond those the model holds the
nearest printed edge, which is an approximation, and a prediction made there
has to carry that fact to whoever reads it.
"""

from __future__ import annotations

from layer2_physics import om_table


def test_a_point_inside_the_printed_table_has_nothing_to_declare():
    assert om_table.outside_table(5500.0, 10_000.0, 0.0) == ()
    assert om_table.outside_table(4500.0, 0.0, -15.0) == ()
    assert om_table.outside_table(5800.0, 22_999.0, 30.0) == ()


def test_each_way_out_of_the_table_is_named():
    assert "below the table's 4500 rpm" in om_table.outside_table(2400.0, 5000.0, 0.0)[0]
    assert "above the table's 5800 rpm" in om_table.outside_table(5900.0, 5000.0, 0.0)[0]
    assert "above the table's 22,999 ft" in om_table.outside_table(5500.0, 25_000.0, 0.0)[0]
    assert "hotter than the table's ISA+30" in om_table.outside_table(5500.0, 5000.0, 35.0)[0]
    assert "colder than the table's ISA-15" in om_table.outside_table(5500.0, 5000.0, -20.0)[0]


def test_every_limit_exceeded_at_once_is_reported_at_once():
    assert len(om_table.outside_table(2000.0, 24_000.0, 40.0)) == 3


def test_the_limits_are_the_table_axes_themselves():
    """One source for the range: the axes the lookup interpolates on."""
    rpm, alt, dev = om_table.RPM_AXIS, om_table.ALTITUDE_AXIS, om_table.ISA_DEV_AXIS
    assert om_table.outside_table(rpm[0], alt[-1], dev[0]) == ()
    assert om_table.outside_table(rpm[-1], alt[0], dev[-1]) == ()
