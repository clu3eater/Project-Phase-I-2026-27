"""The operator's view must hold still, and must say what to do.

Governed by ``docs/WHO_READS_THIS_SCREEN.md``.

These tests pin the two properties that document exists about: a number an
operator reads does not dance, and a sentence an operator reads is an
instruction rather than a description of our method.
"""

from __future__ import annotations

import pytest

from common import config
from layer4_core import operator_view as ov


def _noisy(n: int, centre: float, swing: float) -> list[float]:
    """A quantity with no trend and a lot of scatter -- a healthy engine."""
    return [centre + (swing if i % 2 else -swing) for i in range(n)]


# ---------------------------------------------------------------------------
# It holds still
# ---------------------------------------------------------------------------


def test_a_noisy_quantity_stops_moving_on_the_display():
    """The measurement that started all of this.

    BSFC deterioration swung 11.4 points on a HEALTHY engine and changed on 39
    frames out of 40, in the largest type on the dashboard. An operator
    watching that learns the number is worthless and stops reading the panel --
    including on the day it is right.
    """
    s = ov.Smoothed(step=1.0)
    shown = [s.update(v) for v in _noisy(60, centre=0.5, swing=5.0)]
    settled = shown[20:]
    changes = sum(1 for a, b in zip(settled, settled[1:]) if a != b)
    assert changes == 0, f"display still moved {changes} times on noise alone"


def test_the_deadband_stops_the_last_digit_chattering():
    """Smoothing alone is not enough.

    An EMA hovering exactly between two steps still flips between them for
    ever, which is a chattering alarm with extra arithmetic. The displayed
    figure moves only once the smoothed value has genuinely crossed.
    """
    s = ov.Smoothed(step=1.0)
    for _ in range(200):
        s.update(0.5)          # sits precisely on the boundary
    before = s.shown
    for _ in range(20):
        s.update(0.5)
    assert s.shown == before


def test_a_real_change_still_gets_through():
    """Stability must not become deafness. A quantity that genuinely moves has
    to arrive, or the smoothing has hidden the thing it was meant to reveal."""
    s = ov.Smoothed(step=1.0)
    for _ in range(60):
        s.update(0.0)
    assert s.shown == 0.0
    for _ in range(80):
        s.update(20.0)
    assert s.shown is not None and s.shown >= 18.0


def test_a_gap_is_not_filled_in():
    """PRD Part 4 s7.2, remove-never-substitute. Holding the last value across
    a dropout would let an operator read a stale number as a live one."""
    s = ov.Smoothed(step=1.0)
    for _ in range(40):
        s.update(10.0)
    held = s.shown
    assert s.update(None) == held      # returns the last shown, unchanged
    assert s.ema is not None and s.ema == pytest.approx(10.0, abs=0.5)


# ---------------------------------------------------------------------------
# Direction, not derivative
# ---------------------------------------------------------------------------


def test_movement_inside_the_noise_reads_as_steady():
    """Reporting a slope smaller than the quantity's own scatter is reporting
    the scatter."""
    assert ov.direction(1.4, 1.0, noise=1.5) == "steady"


def test_movement_outside_the_noise_reads_as_a_direction():
    assert ov.direction(4.0, 1.0, noise=1.5) == "rising"
    assert ov.direction(1.0, 4.0, noise=1.5) == "falling"


def test_an_unknown_history_is_not_reported_as_steady():
    """"Steady" is a claim. Before there is history to compare against, the
    honest answer is that we do not know yet."""
    assert ov.direction(1.0, None, noise=0.5) == "unknown"


# ---------------------------------------------------------------------------
# It instructs rather than explains
# ---------------------------------------------------------------------------


def test_every_band_carries_an_operator_instruction():
    """PRD Part 2 s9.5 writes every one of its own examples as an instruction,
    and ISA-18.2 requires an indication to carry a recommended response or it
    is decoration that costs attention. A band with no instruction leaves the
    operator holding a word they cannot act on."""
    for band in config.load_thresholds()["health"]["chi_bands"]:
        assert band.get("instruction"), f"{band['label']} has no instruction"
        assert ov.instruction(band["action"]) == band["instruction"]


def test_instructions_are_sentences_not_tokens():
    """"maintain_within_25h" is a configuration key. It is not English."""
    for band in config.load_thresholds()["health"]["chi_bands"]:
        text = ov.instruction(band["action"])
        assert "_" not in text, f"machine token reached the operator: {text}"
        assert text[0].isupper() and text.rstrip().endswith(("." , "!")), text


def test_an_unmapped_token_is_shown_rather_than_blanked():
    """A blank instruction line reads as "nothing to do", which is the most
    dangerous thing an unknown state could say."""
    assert ov.instruction("some_new_state") == "some new state"


# ---------------------------------------------------------------------------
# Margins
# ---------------------------------------------------------------------------


def test_a_margin_is_the_distance_to_the_limit():
    m = ov.margin(93.0, 120.0, unit="C", name="Coolant")
    assert m["margin"] == pytest.approx(27.0)
    assert m["exceeded"] is False


def test_a_minimum_limit_inverts_the_sense():
    """Oil pressure fails LOW. A margin computed as limit-minus-value would
    report a healthy engine as being over its limit."""
    m = ov.margin(59.0, 29.0, unit="psi", name="Oil press", minimum=True)
    assert m["margin"] == pytest.approx(30.0)
    assert m["exceeded"] is False
    bad = ov.margin(20.0, 29.0, unit="psi", name="Oil press", minimum=True)
    assert bad["exceeded"] is True


def test_a_missing_reading_produces_no_margin_at_all():
    """Better no row than a row computed from a value that is not there."""
    assert ov.margin(None, 120.0, unit="C", name="Coolant") is None
    assert ov.margin(93.0, None, unit="C", name="Coolant") is None


# ---------------------------------------------------------------------------
# Nothing in this module is written into the code
# ---------------------------------------------------------------------------


def test_every_display_step_is_configured():
    """A display resolution is a tuning decision about a physical quantity and
    belongs beside the thresholds, not in a Python literal."""
    cfg = config.load_thresholds()["health"]["operator_display"]
    view = ov.OperatorView()
    assert view.chi.step == float(cfg["steps"]["chi"])
    assert view.rul_h.step == float(cfg["steps"]["rul_hours"])
    assert view.bsfc_det.step == float(cfg["steps"]["bsfc_deterioration_pct"])
    assert view.mission_p.step == float(cfg["steps"]["mission_success_pct"])
    assert view.window == int(cfg["direction_window_frames"])
    assert ov.alpha() == float(cfg["ema_alpha"])


def test_the_smoothing_constant_is_the_one_the_prd_specifies():
    """PRD Part 2 s9.4 METHOD 1: alpha = 0.1, annotated "slow response,
    filters noise"."""
    assert ov.alpha() == pytest.approx(0.1)


def test_an_unreportable_rul_is_not_smoothed_into_existence():
    """A prediction the model declined to make must not acquire a value by
    passing through a filter."""
    view = ov.OperatorView()
    for _ in range(50):
        out = view.update(
            chi=0.9, rul_hours=300.0, rul_reportable=False,
            bsfc_deterioration_pct=0.0, mission_success=0.9, fusion_score=0.1,
        )
    assert out["rul_hours"] is None


def test_the_hysteresis_band_is_configured_and_at_least_one_step():
    """Below one step there is no deadband, only rounding.

    A smoothed value sitting near a step boundary then rounds either way on
    alternate frames and the figure flips for ever -- measured at the naive
    setting, pure noise still moved the display on 31 frames out of 40.
    """
    cfg = config.load_thresholds()["health"]["operator_display"]
    h = float(cfg["hysteresis_steps"])
    assert h >= 1.0, "a hysteresis below one step is not a deadband"
    assert ov.OperatorView().chi.hysteresis == h
