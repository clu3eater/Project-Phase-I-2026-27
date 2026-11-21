"""Flight history and the ECTM trend built from it.

The property that matters is not "it stores rows". It is that the trend
REFUSES to compare two flights flown in different conditions, because a
difference that is mostly weather, plotted as if it were engine deterioration,
is how a trend programme produces false findings and gets ignored.
"""

from __future__ import annotations

from layer4_core.history import COMPARABLE_BAND, TRENDED, FlightHistory

# A stabilised cruise datum. The first keys are CONDITIONS; the rest are the
# readings that get trended.
BASE = {
    "altitude_ft": 12000.0, "oat_c": -5.0, "airspeed_kmh": 180.0,
    "throttle_pct": 72.0, "rpm": 5200.0, "manifold_pressure_bar": 1.25,
    "cht_max_c": 104.0, "cht_spread_c": 6.0,
    "egt_max_c": 840.0, "egt_spread_c": 25.0,
    "oil_pressure_psi": 58.0, "oil_temperature_c": 95.0,
    "coolant_temperature_c": 88.0, "fuel_flow_lph": 31.0, "power_kw": 78.0,
}


def _hist(tmp_path) -> FlightHistory:
    return FlightHistory(tmp_path / "flights.db")


def test_a_flight_with_no_stabilised_datum_contributes_nothing(tmp_path):
    """DEV-141: absence beats a best-effort average.

    A number that cannot be compared with the next flight's number is worse
    than no number, because it will be plotted anyway.
    """
    h = _hist(tmp_path)
    assert h.record(None, engine_key="rotax_915is") is None
    assert h.flights() == []


def test_history_survives_a_new_process(tmp_path):
    """The whole point: the ground station used to lose this on restart."""
    path = tmp_path / "flights.db"
    first = FlightHistory(path)
    first.record(BASE, engine_key="rotax_915is", flight_hours=10.0)

    # A completely separate instance, as after a restart.
    again = FlightHistory(path)
    rows = again.flights()
    assert len(rows) == 1
    assert rows[0]["flight_hours"] == 10.0
    assert rows[0]["cht_max_c"] == 104.0


def test_drift_is_measured_against_the_baseline_flight(tmp_path):
    """An engine is trended against its own first flight, not a fleet mean."""
    h = _hist(tmp_path)
    h.record(BASE, engine_key="rotax_915is", flight_hours=10.0)

    later = dict(BASE, cht_max_c=112.0, fuel_flow_lph=32.4)   # same conditions
    h.record(later, engine_key="rotax_915is", flight_hours=310.0)

    t = h.trend()
    assert t["flights_recorded"] == 2
    assert t["flights_comparable"] == 1
    c = t["comparisons"][0]
    assert c["comparable"] is True
    assert c["deltas"]["cht_max_c"] == 8.0
    assert c["deltas"]["fuel_flow_lph"] == 1.4
    # An unchanged reading must read as zero drift, not as absent.
    assert c["deltas"]["oil_pressure_psi"] == 0.0


def test_a_hot_day_is_refused_rather_than_reported_as_degradation(tmp_path):
    """THE POINT OF THE MODULE.

    Same engine, same everything, flown on a much hotter day and hotter as a
    result. Reporting that +14 C as deterioration is exactly the false finding
    ECTM exists to avoid, so the comparison is refused and says why.
    """
    h = _hist(tmp_path)
    h.record(BASE, engine_key="rotax_915is", flight_hours=10.0)

    hot_day = dict(BASE, oat_c=BASE["oat_c"] + COMPARABLE_BAND["oat_c"] + 10.0,
                   cht_max_c=BASE["cht_max_c"] + 14.0)
    h.record(hot_day, engine_key="rotax_915is", flight_hours=40.0)

    c = h.trend()["comparisons"][0]
    assert c["comparable"] is False
    assert "oat_c" in c["reason"]
    assert "weather" in c["reason"]
    # And crucially it reports NO deltas, rather than a number a reader would
    # plot without noticing the caveat beside it.
    assert c["deltas"] == {}


def test_every_trended_reading_is_a_measurement_not_a_condition():
    """A condition must never appear as a trended reading.

    Trending altitude or throttle would plot what the pilot did, which is the
    reading-without-context problem this project keeps running into.
    """
    for cond in ("altitude_ft", "oat_c", "airspeed_kmh", "throttle_pct", "rpm"):
        assert cond not in TRENDED


def test_trend_is_honest_when_there_is_nothing_yet(tmp_path):
    t = _hist(tmp_path).trend()
    assert t["baseline"] is None
    assert t["comparisons"] == []
    assert "no flights" in t["note"]


def test_subsystem_health_survives_to_the_next_flight(tmp_path):
    """Section 9's change column needs the PREVIOUS flight's subsystems.

    Overall chi cannot answer it: an engine whose cooling fell while its
    lubrication improved has a flat chi and two findings. Only `band` and
    `action` are dropped -- they are strings derived from chi, and subtracting
    them next flight is meaningless.
    """
    store = FlightHistory(tmp_path / "h.db")
    cruise = {"altitude_ft": 18000.0, "oat_c": -20.0, "airspeed_kmh": 180.0,
              "throttle_pct": 68.0, "cht_max_c": 100.0, "egt_max_c": 700.0,
              "oil_pressure_psi": 58.0}

    assert store.previous_health("rotax_915is") == {}, "no history, no change column"

    store.record(cruise, engine_key="rotax_915is", flight_hours=10.0,
                 health_chi=0.87,
                 health={"cooling": 0.81, "lubrication": 0.90, "chi": 0.87,
                         "chi_raw": 0.88, "band": "GOOD", "action": "none"})

    prev = store.previous_health("rotax_915is")
    assert prev == {"cooling": 0.81, "lubrication": 0.90}, prev


def test_a_trend_appears_once_two_comparable_flights_exist(tmp_path):
    """The end-to-end path section 8 depends on, not just the adapter."""
    from layer4_core.twin_api import _trend_series

    store = FlightHistory(tmp_path / "h.db")
    base = {"altitude_ft": 18000.0, "oat_c": -20.0, "airspeed_kmh": 180.0,
            "throttle_pct": 68.0, "cht_max_c": 100.0, "egt_max_c": 700.0,
            "oil_pressure_psi": 58.0}
    for i, hours in enumerate((10.0, 30.0, 50.0)):
        row = dict(base)
        row["cht_max_c"] = 100.0 + i * 2.0      # +2 C per flight, +4 C over 40 h
        store.record(row, engine_key="rotax_915is", flight_hours=hours,
                     health_chi=0.9 - i * 0.01, health={"cooling": 0.8})

    got = _trend_series(store, "rotax_915is")
    assert got["series"], got.get("reason")
    cht = [x for x in got["series"] if "Cylinder Head" in x["name"]][0]
    # Flight 1 is the baseline, so flights 2 and 3 are the comparable pair and
    # their deltas are +2 C and +4 C.
    #
    # `flight_hours` is the DURATION of each flight, not cumulative engine
    # hours, so the hours separating those two datums are the hours flown in
    # between -- flight 3's own 50 h. An earlier version subtracted the two
    # durations (50 - 30 = 20) and reported +10 C per 100 h, which is the same
    # arithmetic that turned two 23-minute sorties into a drift of +101,694 C
    # per 100 h on real data.
    assert cht["span_hours"] == 50.0, cht["span_hours"]
    assert cht["drift_per_100h"] == 4.0, cht["drift_per_100h"]
