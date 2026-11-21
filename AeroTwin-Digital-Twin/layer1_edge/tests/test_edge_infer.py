"""Tier-3 inference onboard -- the ONNX path that replaces PyTorch on the aircraft.

The point of this module is an ABSENCE: the aircraft must score the network
without importing torch or layer3_ai. An intention like that decays silently,
so it is asserted here rather than written in a comment.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from layer1_edge import edge_infer as ei

pytestmark = pytest.mark.skipif(
    not ei.RUNTIME, reason="the 'edge' extra is not installed"
)

HAS_MODEL = ei.FLOAT_PATH.exists()
needs_model = pytest.mark.skipif(
    not HAS_MODEL, reason="run scripts/export_edge.py to produce the ONNX graph"
)


def _window_shape() -> tuple[int, int]:
    """The window the SERVED graph expects, read from the graph itself.

    This was written out as (30, 23) in four places. 23 was the feature count
    at the time, the contract has since grown to 34, and all four tests then
    failed with "Got invalid dimensions for input: window" against a graph
    that was entirely correct -- the export, the checkpoint and the contract
    all agreed at 34 and only the tests disagreed.

    A test that pins a number the contract owns does not protect the contract;
    it fails every time the contract legitimately changes and teaches whoever
    is on call to edit the test. The width comes from the graph now, so this
    module checks that the aircraft can score what it was given rather than
    re-asserting a constant from the day it was written. The contract itself is
    pinned where it belongs, in layer3_ai/tests against feat.extended().
    """
    import onnxruntime as ort

    sess = ort.InferenceSession(str(ei.FLOAT_PATH),
                                providers=["CPUExecutionProvider"])
    _, length, width = sess.get_inputs()[0].shape
    return int(length), int(width)


# ---------------------------------------------------------------------------
# The absence that is the point
# ---------------------------------------------------------------------------


def test_scoring_onboard_imports_neither_torch_nor_layer3():
    """The edge image exists to be small.

    torch's CPU wheel is several hundred megabytes and layer3_ai pulls it in.
    A stray import in the inference path puts both on the aircraft, and nothing
    would fail loudly if it did -- it would just quietly stop fitting.
    """
    code = (
        "import sys;"
        "from layer1_edge import edge_infer;"
        "bad=[m for m in ('torch','layer3_ai','sklearn') if m in sys.modules];"
        "print(','.join(bad))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "", (
        f"importing edge_infer dragged in: {out.stdout.strip()}"
    )


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


@needs_model
def test_it_scores_a_single_window():
    """One window is the shape the aircraft actually holds."""
    s = ei.EdgeScorer()
    L, n = _window_shape()
    out = s.score(np.zeros((L, n), dtype=np.float32))
    assert set(out) == {"anomaly", "fault", "severity"}
    assert out["fault"].shape == (1, 8), "eight PS fault modes"


@needs_model
def test_every_head_returns_a_probability():
    """MultiTaskNet.forward returns LOGITS and the sigmoid is applied here.

    Having the edge and the ground apply it in different places is how a
    threshold calibrated on one comes to be used against the other.
    """
    s = ei.EdgeScorer()
    out = s.score(np.zeros(_window_shape(), dtype=np.float32))
    for name, v in out.items():
        assert np.all((v >= 0.0) & (v <= 1.0)), f"{name} is not a probability"


@needs_model
def test_it_defaults_to_the_float_graph_not_the_quantised_one():
    """Measured on 300 real windows from held-out engines, dynamic INT8 was
    2.94x smaller, 0.84x the speed -- SLOWER -- and changed 5 anomaly
    decisions in 300. A graph that disagrees with the validated model on
    1.7 % of windows has not been optimised, it has been replaced."""
    assert ei.EdgeScorer().path == ei.FLOAT_PATH


@needs_model
def test_the_quantised_graph_is_still_loadable_when_asked_for():
    """It is kept because the trade may invert on an ARM target with int8
    SIMD. It must be passed explicitly, never picked up by default."""
    if not ei.INT8_PATH.exists():
        pytest.skip("no int8 graph exported")
    s = ei.EdgeScorer(ei.INT8_PATH)
    assert s.path == ei.INT8_PATH
    assert s.score(np.zeros(_window_shape(), dtype=np.float32))["fault"].shape == (1, 8)


@needs_model
def test_it_stays_inside_the_edge_latency_budget():
    """PRD Part 1 gives the edge loop 5 ms; Tier-3 runs far less often than
    the rules, but a scorer that blows the budget starves them."""
    import time

    s = ei.EdgeScorer()
    w = np.zeros(_window_shape(), dtype=np.float32)
    s.score(w)
    t = []
    for _ in range(30):
        a = time.perf_counter()
        s.score(w)
        t.append((time.perf_counter() - a) * 1000.0)
    assert float(np.median(t)) < 5.0, f"median {np.median(t):.2f} ms"


@needs_model
def test_it_runs_single_threaded_by_default():
    """The edge computer runs ingest, rules and the buffer on the same few
    cores. A scorer that grabs every core to shave a millisecond off a loose
    budget takes that time from the layers with the hard deadline."""
    s = ei.EdgeScorer()
    assert s.sess.get_session_options().intra_op_num_threads == 1


def test_a_missing_model_fails_with_an_instruction():
    """The aircraft does not train, so "no model" is a deployment error and
    the message should say what to do about it."""
    with pytest.raises(FileNotFoundError, match="on the ground"):
        ei.EdgeScorer(ei.MODEL_DIR / "does_not_exist.onnx")


# ---------------------------------------------------------------------------
# The export report is a measurement, not a claim
# ---------------------------------------------------------------------------


@needs_model
def test_the_export_report_records_agreement_not_just_size():
    """A smaller file with no agreement figure beside it is a claim, not a
    measurement."""
    import json

    if not ei.REPORT_PATH.exists():
        pytest.skip("no export report")
    d = json.loads(ei.REPORT_PATH.read_text(encoding="utf-8"))
    for k in ("size_ratio", "speedup", "max_delta",
              "decisions_changed", "windows_compared"):
        assert k in d, f"export report omits {k}"
    assert d["windows_compared"] > 0, "agreement measured on no windows"
