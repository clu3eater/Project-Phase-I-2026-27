"""The post-flight report as a filed document.

A report that exists only on a screen is not one a maintenance organisation can
use. These tests pin the properties that make the PDF safe to file: that it
says what it is, that it does not invent numbers it does not have, and that a
printout can be matched back to the audit-log entry recording its export.
"""

from __future__ import annotations

import pytest

from layer4_core import report_pdf

pytestmark = pytest.mark.skipif(
    not report_pdf.AVAILABLE, reason="the 'reports' extra is not installed"
)


def _text(pdf: bytes) -> str:
    """The document as a reader would see it.

    PDF content streams are compressed, so searching the raw bytes finds only
    the metadata and silently passes tests that should fail. The text is
    extracted properly instead -- these assertions are about what is ON THE
    PAGE, and nothing else is worth asserting.
    """
    import io

    from pypdf import PdfReader

    pages = PdfReader(io.BytesIO(pdf)).pages
    return "\n".join(pg.extract_text() for pg in pages)


def _payload(**over) -> dict:
    """A payload shaped exactly like /api/report returns."""
    base = {
        "twin_id": "UAV-ENG-001",
        "aircraft_id": "MALE-01",
        "engine": "Rotax 915 iS",
        "generated_utc": "11:22:33Z",
        "mission": {
            "simulated_seconds": 4210.5, "flight_hours": 12.4,
            "start_stop_cycles": 88, "thermal_cycles": 91,
        },
        "health": {"chi": 0.873, "thermal": 0.91, "lubrication": 0.84},
        "remaining_life": {
            "hours": 312.4, "lower": 196.0, "upper": 428.8,
            "reportable": True, "reason": "",
        },
        "extremes": {
            "max_cht_c": 118.2, "max_coolant_c": 104.9, "max_egt_c": 892,
            "max_rpm": 5794, "max_vibration": 2.31,
            "time_above_max_continuous_s": 142,
        },
        "advisory": {"severity": "CAUTION", "action": "Inspect coolant circuit",
                     "reason": "coolant margin below 15 %"},
        "alerts": {"active": []},
        "faults_injected": [],
        "data_quality": 0.998,
        "tbo_hours_remaining": 1187.6,
    }
    base.update(over)
    return base


def test_it_produces_a_real_pdf():
    pdf = report_pdf.build(_payload())
    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 1500


def test_a_simulated_report_says_so_in_its_title():
    """The demonstration path of this whole system is synthetic.

    A synthetic report that reads like a real one is a forgery waiting to
    happen, so the provenance is in the document TITLE -- which is what a PDF
    reader shows in its window chrome and what a file manager indexes -- and
    not only in the body where it can be scrolled past.
    """
    pdf = report_pdf.build(
        _payload(faults_injected=[{"mode": "cooling_degradation",
                                   "severity": 0.4}])
    )
    assert b"SIMULATED" in pdf


def test_a_clean_report_is_not_labelled_simulated():
    """The label has to mean something, so it must not be always-on."""
    pdf = report_pdf.build(_payload(faults_injected=[]))
    # The banner text is the phrase that would appear; its absence is the check.
    assert b"SIMULATED DATA" not in pdf


def test_an_unreportable_rul_is_not_rendered_as_a_number():
    """PRD Part 4 s7.2, remove-never-substitute, applies on paper too.

    Printing a plausible-looking figure for a prediction the system declined to
    make is how an engine gets released to fly on a number nobody computed.
    """
    pdf = report_pdf.build(_payload(remaining_life={
        "hours": None, "lower": None, "upper": None,
        "reportable": False, "reason": "insufficient degradation signal",
    }))
    body = _text(pdf)
    assert "Not reportable" in body
    assert "insufficient degradation signal" in body
    # And no invented figure anywhere near it.
    assert "312" not in body


def test_a_reported_rul_carries_its_interval():
    """s7.4a: an RUL without an interval is not a prediction.

    The measured coverage on unseen engines is 84-87 % against a 95 % nominal
    (DEV-105), so the interval is the honest part and must travel with the
    point estimate rather than living on another page.
    """
    pdf = report_pdf.build(_payload())
    body = _text(pdf)
    assert "interval" in body
    assert "coverage" in body, "the coverage caveat is missing"
    # Rendered as "312 flight hours (interval 196 to 429 h)" -- the bound is
    # 428.8 and rounds up, which is the conservative direction for an upper
    # bound and the wrong one for a lower, so both are checked explicitly.
    assert "312 flight hours" in body
    assert "interval 196 to 429 h" in body


def test_a_clean_flight_states_its_silence():
    """s4.1.1a on paper: a blank section reads as an omission.

    "No alert was raised" and an empty box look identical to a reader deciding
    whether the report is complete.
    """
    pdf = report_pdf.build(_payload(alerts={"active": []}))
    assert "No alert was raised" in _text(pdf)


def test_the_digest_covers_the_data_and_changes_with_it():
    """The digest is what matches a printout to the audit-log entry."""
    a = _payload()
    b = _payload(tbo_hours_remaining=1187.7)
    assert report_pdf.digest(a) == report_pdf.digest(_payload())
    assert report_pdf.digest(a) != report_pdf.digest(b)
    assert len(report_pdf.digest(a)) == 64


def test_key_ordering_does_not_change_the_digest():
    """Two reports with the same content must hash the same however the dict
    happened to be built, or the digest is a test of ordering rather than of
    content."""
    a = {"x": 1, "y": {"p": 1, "q": 2}}
    b = {"y": {"q": 2, "p": 1}, "x": 1}
    assert report_pdf.digest(a) == report_pdf.digest(b)


def test_it_survives_a_sparse_report():
    """Fields go missing when the twin has only just started.

    The generator must produce a document with dashes in it rather than raising
    -- an export that fails when the data is thin fails exactly when somebody
    is trying to record why.
    """
    pdf = report_pdf.build({"twin_id": "X", "generated_utc": "00:00:00Z"})
    assert pdf.startswith(b"%PDF-")


def test_no_character_renders_as_a_replacement_glyph():
    """The document must be legible without an embedded font.

    reportlab's built-in Helvetica does not carry a middot, and the console's
    separator silently became a replacement glyph in the header line of every
    exported report. A document that is going to be printed, scanned and filed
    should not depend on font substitution to read correctly.
    """
    body = _text(report_pdf.build(_payload(
        advisory={"severity": "CAUTION", "action": "Inspect coolant circuit"},
    )))
    assert "\ufffd" not in body
    for ch in ("\u00b7", "\u2014", "\u2013"):
        assert ch not in body, f"non-ASCII {ch!r} reached the page"


# ---------------------------------------------------------------------------
# The two sections real post-flight practice requires
# ---------------------------------------------------------------------------


def _with_record(**over) -> dict:
    rec = {
        "phases_flown": ["GROUND", "TAXI", "TAKE-OFF", "CLIMB", "CRUISE"],
        "events": [],
        "exceedances": [],
        "cruise_datum": None,
        "cruise_reason": "no stable cruise segment",
    }
    rec.update(over)
    return _payload(flight_record=rec)


def test_the_stabilised_cruise_datum_is_reported():
    """ECTM works by recording the same parameters at the same condition once
    per flight. Without that datum a report has extremes and instantaneous
    values, and NEITHER can be trended: the peak depends on how hard the
    aircraft was flown, the instantaneous value on when export was pressed."""
    body = _text(report_pdf.build(_with_record(cruise_datum={
        "t_s": 886.0, "stable_for_s": 120.0, "altitude_ft": 18000.0,
        "oat_c": -20.7, "airspeed_kmh": 180.0, "throttle_pct": 68.0,
        "rpm": 4765.0, "manifold_pressure_bar": 1.276, "cht_max_c": 100.6,
        "cht_spread_c": 0.5, "egt_max_c": 721.0, "egt_spread_c": 12.0,
        "oil_pressure_psi": 57.9, "oil_temperature_c": 93.0,
        "coolant_temperature_c": 88.0, "fuel_flow_lph": 22.98,
        "power_kw": 57.6,
    })))
    assert "STABILISED CRUISE READING" in body
    assert "18,000 ft" in body and "4,765 rpm" in body
    # The stability is the whole point, so how long it held is stated.
    assert "120 s stable" in body


def test_a_flight_with_no_stable_cruise_says_so_rather_than_inventing_one():
    """Averaging the whole flight instead would produce a number that trends
    against nothing, which is worse than no number."""
    body = _text(report_pdf.build(_with_record()))
    assert "No stabilised cruise reading was captured" in body
    assert "no stable cruise segment" in body, "the reason, not just the gap"
    assert "No trend point is contributed" in body


def test_events_carry_their_flight_phase_and_ata_chapter():
    """An Airbus PFR lists each fault "with the associated time, flight phase
    and ATA reference". "EGT high" tells a maintainer almost nothing; "EGT
    high, 04:12, CLIMB, ATA 77" tells them where to look."""
    body = _text(report_pdf.build(_with_record(events=[{
        "t_s": 252.0, "phase": "CLIMB", "level": 3, "legend": "EGT HIGH",
        "advisory": "reduce power", "ata": "77 Engine indicating",
        "cleared_s": 318.0, "duration_s": 66.0, "standing": False,
    }])))
    assert "00:04:12" in body, "the flight's own clock, not raw seconds"
    assert "CLIMB" in body
    assert "77 Engine indicating" in body
    assert "66 s" in body, "a transient's duration is the finding"


def test_an_exceedance_carries_time_above_as_well_as_peak():
    """Inspection thresholds are set on both: two seconds over a limit and
    four minutes at the same peak are different findings."""
    body = _text(report_pdf.build(_with_record(exceedances=[{
        "parameter": "cylinder head temperature", "unit": "C",
        "limit": 135.0, "peak": 141.2, "over_by": 6.2,
        "seconds_above": 214.0, "first_t_s": 400.0, "phase": "CLIMB",
    }])))
    assert "141.2" in body and "3 min 34 s" in body, "time beyond, as a duration"
    assert "00:06:40" in body


def test_a_clean_flight_states_both_silences():
    """s4.1.1a on paper. An empty section reads as an omission, not as a clean
    sortie -- and a reader deciding whether the report is complete cannot tell
    the difference."""
    body = _text(report_pdf.build(_with_record()))
    assert "No limit exceedances were observed" in body
    assert "No alert was raised" in body


def test_life_to_date_extremes_are_not_labelled_as_this_flight():
    """OperationalHistory is explicit that these are life-to-date. Under a
    POST-FLIGHT heading a maintainer would read a six-month-old peak as
    something that happened this morning."""
    body = _text(report_pdf.build(_with_record()))
    assert "Life-to-date extremes" in body
    assert "not this flight" in body


def test_the_cover_identity_comes_from_the_payload_not_the_generator():
    """Every field on the cover must vary with the flight it describes.

    A cover that always names the same airframe is worse than one that names
    none: it is a filed maintenance record asserting something false about a
    real aircraft. The check is a whole second identity, not one changed field,
    because a generator with ANY literal in its cover would pass a narrower
    one.
    """
    a = _text(report_pdf.build(_payload(
        mission_id="MISSION-20260908-UAV-ENG-007", aircraft_id="MALE-07",
        engine="ROTAX_915IS", engine_serial="RTX915-0047",
        location="Pokhran Test Range, Rajasthan", date="2026-09-08",
        gcs_version="1.0")))
    b = _text(report_pdf.build(_payload(
        mission_id="MISSION-20270114-UAV-ENG-042", aircraft_id="MALE-42",
        engine="ROTAX_916IS", engine_serial="RTX916-9001",
        location="Chandipur Interim Test Range, Odisha", date="2027-01-14",
        gcs_version="2.3")))

    for mine in ("MISSION-20260908-UAV-ENG-007", "MALE-07", "RTX915-0047",
                 "Pokhran Test Range, Rajasthan", "2026-09-08"):
        assert mine in a, f"{mine} missing from its own report"
        assert mine not in b, f"{mine} leaked into a different flight's report"
    for theirs in ("MISSION-20270114-UAV-ENG-042", "MALE-42", "RTX916-9001",
                   "Chandipur Interim Test Range, Odisha", "2027-01-14"):
        assert theirs in b and theirs not in a


def test_an_unknown_cover_field_is_not_silently_invented():
    """A payload with no location must not acquire one.

    The generator carries a default only for the classification marking, where
    the safe default is the restrictive one. Everything else that is absent is
    shown as absent.
    """
    body = _text(report_pdf.build(_payload()))
    assert "---" in body, "an absent field must render as the missing marker"
    assert "Pokhran" not in body, "a location was invented for a flight with none"


def test_both_time_zones_appear_and_neither_is_bare():
    """UTC is the record time; IST is shown beside it, and both are labelled.

    DGCA CAR 66 keeps the aircraft maintenance engineer's logbook in UTC and is
    explicit that an entry must not mix local and Zulu. So the document may
    carry both -- the crew reading it at an Indian base works in IST -- but
    neither may appear without its zone, because an unlabelled time is exactly
    the mixing the rule forbids.
    """
    body = _text(report_pdf.build(_payload(
        window_utc="2026-09-08T04:12:00Z to 2026-09-08T22:36:00Z",
        window_local="08 Sep 2026 09:42 to 09 Sep 2026 04:06 IST",
        local_timezone="IST", date="2026-09-08")))

    assert "Flight window (UTC)" in body, "the record time must say it is UTC"
    assert "Flight window (IST)" in body, "the local time must name its zone"
    assert "record time" in body, "which of the two is the record is stated"
    assert "Date (UTC)" in body, "a bare date on the cover could be read as IST"


def test_the_local_window_offset_is_india_not_a_whole_hour():
    """+05:30. A half-hour offset is the one every generic converter gets wrong.

    Checked against the API helper rather than the renderer, because the
    renderer only prints what it is handed.
    """
    from layer4_core.twin_api import _local_window

    got = _local_window("2026-09-08T04:12:00Z", "2026-09-08T22:36:00Z",
                        {"local_timezone": "IST",
                         "local_utc_offset_minutes": 330})
    assert got == "08 Sep 2026 09:42 to 09 Sep 2026 04:06 IST", got

    # A sortie that crosses midnight local must print the second date, or
    # "09:42 to 04:06" reads as backwards rather than as the next day.
    assert got.count("2026") == 2

    same_day = _local_window("2026-09-08T04:12:00Z", "2026-09-08T09:00:00Z",
                             {"local_timezone": "IST",
                              "local_utc_offset_minutes": 330})
    assert same_day == "08 Sep 2026 09:42 to 14:30 IST", same_day


def test_a_live_shaped_health_block_does_not_take_the_export_down():
    """The health dict is not a bag of subsystem indices.

    It also carries `chi_raw`, and `band` and `action` which are STRINGS
    derived from chi. Treating every key as a subsystem put a band label
    through the band lookup and raised TypeError -- on live data only, because
    a hand-written payload holds nothing but floats. This is the shape the
    running twin actually emits.
    """
    body = _text(report_pdf.build(_payload(health={
        "lhi": 1.0, "oti": 1.0, "fshi": 0.995, "mhi": 0.954, "ehi": 0.567,
        "rsi": 0.742, "thermal": 0.983, "mechanical": 0.742,
        "electrical": 0.567, "combustion": 0.944,
        "chi": 0.8139, "chi_raw": 0.8298, "band": "GOOD", "action": "none",
    })))
    assert "ENGINE HEALTH INDICES" in body
    assert "0.81" in body, "the overall index is still reported"
    # Every real subsystem is listed, under a name a technician on the ramp
    # can read. "Esf" and "Lhi" are the engineer's shorthand and on a
    # maintenance record they look like typos.
    for real in ("Lubrication", "Oil temperature", "Fuel system", "Thermal",
                 "Mechanical", "Electrical", "Combustion"):
        assert real in body, f"{real} is a subsystem and is missing"
    assert "Lhi" not in body, "the raw index key reached the page"
    # "Band" and "Action" are column headings in the bands legend, so their
    # presence proves nothing. `chi_raw` has no other reason to be on the page,
    # which makes it the one that can actually be asserted on.
    assert "Chi Raw" not in body, "chi_raw rendered as though it were a subsystem"


# ---------------------------------------------------------------------------
# The producers that feed the document, tested apart from the renderer
# ---------------------------------------------------------------------------


class _Store:
    """A FlightHistory stand-in returning the shape `trend()` really returns."""

    def __init__(self, payload):
        self._payload = payload

    def trend(self, engine_key=None, limit=200):
        return self._payload


def test_a_trend_needs_two_comparable_flights_and_says_so_when_it_has_one():
    """One point is not a trend, and a line through it is an invention.

    History refuses the comparison when two flights were flown at conditions
    too far apart, so "flights recorded" and "flights comparable" are different
    numbers -- and it is the second that decides whether a chart exists.
    """
    from layer4_core.twin_api import _trend_series

    got = _trend_series(_Store({
        "trended": ["cht_max_c"], "flights_recorded": 4,
        "comparisons": [
            {"comparable": True, "flight_hours": 10.0, "deltas": {"cht_max_c": 1.0}},
            {"comparable": False, "reason": "oat differs by 19 C", "deltas": {}},
            {"comparable": False, "reason": "altitude differs", "deltas": {}},
        ],
    }), "rotax_915is")
    assert got["series"] == []
    assert "at least two" in got["reason"]


def test_drift_is_reported_per_100_hours_over_the_hours_actually_flown():
    """Per-flight drift would make a fleet of short sorties look stable.

    `flight_hours` on a record is the duration of THAT flight, not cumulative
    engine hours -- so the hours separating two datums are the durations of the
    flights BETWEEN them, summed. An earlier version subtracted one per-flight
    duration from another, which for two 23-minute sorties gave a span of
    0.0118 h and turned a 12 C difference into a reported drift of +101,694 C
    per 100 h.

    Four flights of 10, 20, 30 and 50 hours: 100 hours separate the first datum
    from the last, and CHT rises 3 C across them.
    """
    from layer4_core.twin_api import _trend_series

    got = _trend_series(_Store({
        "trended": ["cht_max_c", "oil_pressure_psi"], "flights_recorded": 4,
        "comparisons": [
            {"comparable": True, "flight_hours": 10.0,
             "deltas": {"cht_max_c": 0.0, "oil_pressure_psi": 0.0}},
            {"comparable": True, "flight_hours": 20.0,
             "deltas": {"cht_max_c": 1.0, "oil_pressure_psi": -0.1}},
            {"comparable": True, "flight_hours": 30.0,
             "deltas": {"cht_max_c": 2.0, "oil_pressure_psi": -0.2}},
            {"comparable": True, "flight_hours": 50.0,
             "deltas": {"cht_max_c": 3.0, "oil_pressure_psi": -0.3}},
        ],
    }), "rotax_915is")

    cht = [x for x in got["series"] if "Cylinder Head" in x["name"]][0]
    assert cht["span_hours"] == 100.0, cht["span_hours"]
    assert cht["drift_per_100h"] == 3.0, cht["drift_per_100h"]
    assert cht["unit"] == "C"
    assert len(cht["points"]) == 4
    # Worst drift first: an operator reads the top of the section.
    assert abs(got["series"][0]["drift_per_100h"]) >=         abs(got["series"][-1]["drift_per_100h"])


def test_a_rate_is_not_quoted_from_too_few_hours():
    """Scaling 24 minutes of flying to 100 hours is a 250x extrapolation.

    Printed beside measured values it reads as one of them. Below the floor the
    section reports the CHANGE and the span it was seen over, which is what the
    flights actually showed.
    """
    from layer4_core.twin_api import _trend_series

    got = _trend_series(_Store({
        "trended": ["cht_max_c"], "flights_recorded": 3,
        "comparisons": [
            {"comparable": True, "flight_hours": 0.38,
             "deltas": {"cht_max_c": -6.0}},
            {"comparable": True, "flight_hours": 0.38,
             "deltas": {"cht_max_c": 6.0}},
        ],
    }), "rotax_915is")

    cht = got["series"][0]
    assert cht["drift_per_100h"] is None, "a rate was quoted from 0.38 hours"
    assert cht["change"] == 12.0
    # The span is still REPORTED even though it is too short to divide by:
    # "over 0.38 flight hours" is the fact that explains why there is no rate,
    # and withholding it would leave the refusal unexplained.
    assert cht["span_hours"] == 0.38, cht["span_hours"]


def test_life_limits_claim_no_part_this_build_does_not_track():
    """An empty parts table is true; an invented one is a false record."""
    from layer4_core.twin_api import _life_limits

    rows = _life_limits({"tbo_hours": 1200.0, "tbo_calendar_years": 15.0},
                        {"flight_hours": 431.0})
    items = {r["item"] for r in rows}
    assert "Time between overhaul" in items
    assert not any(r.get("life_limited") for r in rows),         "a life-limited part was claimed that nothing in this build tracks"


def test_standard_day_correction_fires_on_a_hot_day_and_not_on_a_standard_one():
    """ECTM compares the same reading at the same condition across months.

    A cylinder head read on a day 25 C hotter than standard is not comparable
    with one read on a standard day, and a trend built from the two is mostly
    weather. The correction is the ISA temperature deviation at the altitude
    the datum was taken at.
    """
    from layer4_core.twin_api import _cruise_readings

    # 18,000 ft: ISA is 15 - 0.0019812*18000 = -20.66 C.
    standard = _cruise_readings({"altitude_ft": 18000.0, "oat_c": -20.66,
                                 "cht_max_c": 101.0})
    cht = [r for r in standard if "Cylinder Head Temp" in r["name"]][0]
    assert abs(cht["corrected"] - 101.0) < 0.1, "a standard day needs no correction"

    hot = _cruise_readings({"altitude_ft": 18000.0, "oat_c": 4.34,
                            "cht_max_c": 101.0})
    cht = [r for r in hot if "Cylinder Head Temp" in r["name"]][0]
    # 25 C hotter than standard, so the reading is corrected DOWN by 25.
    assert abs(cht["corrected"] - 76.0) < 0.1, cht["corrected"]


def test_only_temperatures_are_corrected_for_the_day():
    """A temperature deviation applied to a fuel flow would be worse than
    leaving it uncorrected, so those rows carry no correction and the column
    honestly shows a dash."""
    from layer4_core.twin_api import _cruise_readings

    rows = {r["name"]: r for r in _cruise_readings({
        "altitude_ft": 18000.0, "oat_c": 4.34, "cht_max_c": 101.0,
        "fuel_flow_lph": 23.0, "oil_pressure_psi": 58.0, "rpm": 4763.0,
    })}
    assert rows["Cylinder Head Temp (max)"]["corrected"] is not None
    for uncorrected in ("Fuel Flow", "Oil Pressure", "Engine RPM"):
        assert rows[uncorrected]["corrected"] is None, uncorrected


def test_silent_sections_are_grouped_and_findings_come_first():
    """A section with nothing to report must not take a page from one that has
    something. Numbers do not move -- 05 is Limit Exceedances in every report --
    but a clean sortie should not open with five near-blank pages."""
    told, silent = report_pdf._partition(_payload(
        flight_record={"events": [], "exceedances": [], "cruise_datum": None,
                       "cruise_reason": "no stable cruise"},
        trend={"series": []},
    ))
    numbers_told = [n for n, _ in told]
    numbers_silent = [n for n, _ in silent]
    assert "05" in numbers_silent and "06" in numbers_silent
    assert "08" in numbers_silent
    # Identity and sign-off are printed on every report whatever happened.
    assert "01" in numbers_told and "15" in numbers_told
    assert set(numbers_told).isdisjoint(numbers_silent)
    assert len(numbers_told) + len(numbers_silent) == len(report_pdf.SECTIONS)
