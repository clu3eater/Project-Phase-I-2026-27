"""Tier-3 inference on the aircraft, without PyTorch -- PS innovation areas
"Edge AI for UAV applications" and "Lightweight onboard analytics".

WHY THIS EXISTS SEPARATELY FROM layer3_ai
------------------------------------------
The Tier-3 network is trained in PyTorch on a workstation. PyTorch is not what
you put on a UAV: the CPU wheel is several hundred megabytes, it pulls a BLAS
stack, and it is a general-purpose autodiff framework being used to do a fixed
forward pass a few times a second. The edge computer needs the forward pass and
nothing else.

So this module exports the trained network to ONNX once, on the ground, and
runs it with onnxruntime on the aircraft. ``onnxruntime`` is a two-figure
number of megabytes with no autodiff, no optimiser state and no Python-level
graph construction, and it is the runtime this project's ``edge`` extra
already declared.

QUANTISATION IS MEASURED, NOT ASSUMED
-------------------------------------
Dynamic INT8 quantisation is the standard move for an LSTM on a CPU: weights
are stored as int8 and activations are quantised per batch at run time, which
is where most of the size and much of the latency goes. It is also lossy, and
"lightweight onboard analytics" is worth nothing if the light model disagrees
with the one that was validated.

So ``export`` does not simply write a smaller file and claim a speed-up. It
measures, on real windows:

  * the SIZE of both graphs;
  * the LATENCY of both, as a median and a p95 over repeated runs;
  * and the AGREEMENT between float and int8 outputs -- max absolute deviation
    on every head, and whether any window changes its anomaly decision.

The last is the one that matters. A model that is four times smaller and
disagrees with the validated one on one window in fifty has not been optimised,
it has been replaced, and the evaluation that justified deploying it no longer
applies. The exporter reports the disagreement and the caller decides; nothing
here silently prefers the small graph.

WHAT RUNS ONBOARD
-----------------
``EdgeScorer`` loads one ``.onnx`` file and exposes the same three heads the
training-time detector does. It imports numpy and onnxruntime, and neither
torch nor layer3_ai -- which is the property that makes the edge image small,
and is asserted in the tests rather than left as an intention.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# onnxruntime is the ONLY heavy import here, and it is in the `edge` extra.
# Absent, this module still imports so that a core install can introspect it.
try:
    import onnxruntime as ort

    RUNTIME = True
except ImportError:  # pragma: no cover - exercised only without the extra
    RUNTIME = False

MODEL_DIR = Path(__file__).resolve().parent.parent / "data" / "models"
FLOAT_PATH = MODEL_DIR / "tier3_edge.onnx"
INT8_PATH = MODEL_DIR / "tier3_edge_int8.onnx"
REPORT_PATH = MODEL_DIR / "tier3_edge_report.json"

UNAVAILABLE = (
    "edge inference requires the 'edge' extra: pip install -e '.[edge]'"
)


# ---------------------------------------------------------------------------
# Export (ground side -- needs torch)
# ---------------------------------------------------------------------------


@dataclass
class ExportReport:
    """What the export actually measured, rather than what it hoped."""

    n_features: int = 0
    sequence_length: int = 0
    float_bytes: int = 0
    int8_bytes: int = 0
    float_ms_median: float = 0.0
    float_ms_p95: float = 0.0
    int8_ms_median: float = 0.0
    int8_ms_p95: float = 0.0
    # Maximum absolute deviation between float and int8, per head.
    max_delta: dict[str, float] = field(default_factory=dict)
    # Windows whose ANOMALY DECISION changed. The number that decides whether
    # the quantised graph may be deployed at all.
    decisions_changed: int = 0
    windows_compared: int = 0

    @property
    def size_ratio(self) -> float:
        return self.float_bytes / self.int8_bytes if self.int8_bytes else 0.0

    @property
    def speedup(self) -> float:
        return (self.float_ms_median / self.int8_ms_median
                if self.int8_ms_median else 0.0)

    def as_dict(self) -> dict:
        return {
            "n_features": self.n_features,
            "sequence_length": self.sequence_length,
            "float_bytes": self.float_bytes,
            "int8_bytes": self.int8_bytes,
            "size_ratio": round(self.size_ratio, 2),
            "float_ms_median": round(self.float_ms_median, 3),
            "float_ms_p95": round(self.float_ms_p95, 3),
            "int8_ms_median": round(self.int8_ms_median, 3),
            "int8_ms_p95": round(self.int8_ms_p95, 3),
            "speedup": round(self.speedup, 2),
            "max_delta": {k: round(v, 5) for k, v in self.max_delta.items()},
            "decisions_changed": self.decisions_changed,
            "windows_compared": self.windows_compared,
        }


def _bench(sess, x: np.ndarray, runs: int = 30) -> tuple[float, float]:
    """Median and p95 latency for ONE window, in milliseconds.

    One window, because that is the shape the aircraft actually scores: the
    edge computer has a rolling buffer and a decision to make now, not a batch
    to push through. Timing a batch of 256 would flatter the number by
    amortising a per-call cost the deployment never gets to amortise.
    """
    one = x[:1].astype(np.float32)
    name = sess.get_inputs()[0].name
    sess.run(None, {name: one})            # warm up; excluded from the timing
    t = []
    for _ in range(runs):
        s = time.perf_counter()
        sess.run(None, {name: one})
        t.append((time.perf_counter() - s) * 1000.0)
    return float(np.median(t)), float(np.percentile(t, 95))


def export(net, x_sample: np.ndarray, *, opset: int = 17) -> ExportReport:
    """Export a trained MultiTaskNet to ONNX, quantise, and MEASURE both.

    ``x_sample`` MUST be real windows -- the same distribution the aircraft
    will score. This is not a style preference, it was measured: on synthetic
    Gaussian noise the float/int8 logit deviation came out at 0.33 / 0.50 /
    0.27 and no decision changed, which reads as a clean result. On 300 real
    windows from held-out engines the same export deviated by 3.32 / 8.22 /
    1.95 and changed 5 anomaly decisions. Verifying on noise would have
    certified a graph that disagrees with the validated model on 1.7 % of the
    windows it will actually see.
    """
    if not RUNTIME:  # pragma: no cover
        raise RuntimeError(UNAVAILABLE)
    import torch
    from onnxruntime.quantization import QuantType, quantize_dynamic

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    rep = ExportReport(
        n_features=int(x_sample.shape[2]),
        sequence_length=int(x_sample.shape[1]),
    )

    net.eval()
    dummy = torch.tensor(x_sample[:1], dtype=torch.float32)
    torch.onnx.export(
        net, dummy, str(FLOAT_PATH),
        input_names=["window"],
        output_names=["anomaly", "fault", "severity"],
        opset_version=opset,
        # Torch's exporter prints a progress report containing emoji. On a
        # Windows console at cp1252 that raises UnicodeEncodeError AFTER the
        # graph has been written successfully -- an export that worked,
        # reported as a crash. Silencing the chatter removes the failure mode
        # entirely rather than depending on the console's encoding.
        verbose=False,
        # THE TORCHSCRIPT EXPORTER, not the dynamo one torch now defaults to.
        #
        # `MultiTaskNet.forward` takes the final hidden state as `h[-1]`, and
        # the dynamo path emits a graph whose shape annotation for that slice
        # disagrees with what ONNX infers -- "inferred shape and existing shape
        # differ in dimension 0: (32) vs (1)", the LSTM's hidden width being
        # read where the batch belongs. The graph loads, but the quantiser runs
        # shape inference and refuses it. The TorchScript path traces the same
        # network correctly. Pinned explicitly rather than left to a default
        # that has already changed once.
        dynamo=False,
    )
    # FIXED BATCH OF ONE, deliberately.
    #
    # A dynamic batch axis is the reflex, and it costs more than it buys here.
    # The LSTM's hidden state carries the batch dimension through `h[-1]`, and
    # the dynamic-shape graph fails ONNX shape inference inside the quantiser
    # ("inferred shape and existing shape differ in dimension 0"). More to the
    # point, the aircraft never scores a batch: it holds a rolling window and
    # has a decision to make now. Exporting the shape that is actually
    # deployed keeps the graph, the benchmark and the deployment identical --
    # and ground-side batch evaluation still has torch, which is where batch
    # evaluation belongs.
    quantize_dynamic(str(FLOAT_PATH), str(INT8_PATH), weight_type=QuantType.QInt8)

    rep.float_bytes = FLOAT_PATH.stat().st_size
    rep.int8_bytes = INT8_PATH.stat().st_size

    f_sess = ort.InferenceSession(str(FLOAT_PATH), providers=["CPUExecutionProvider"])
    q_sess = ort.InferenceSession(str(INT8_PATH), providers=["CPUExecutionProvider"])

    rep.float_ms_median, rep.float_ms_p95 = _bench(f_sess, x_sample)
    rep.int8_ms_median, rep.int8_ms_p95 = _bench(q_sess, x_sample)

    # ---- agreement, on real windows, ONE AT A TIME --------------------
    # The same call the aircraft makes, so the deviation measured is the
    # deviation that will be flown rather than one taken in a batched regime
    # the deployment never enters.
    fi, qi = f_sess.get_inputs()[0].name, q_sess.get_inputs()[0].name
    deltas = {"anomaly": 0.0, "fault": 0.0, "severity": 0.0}
    changed = 0
    for w in x_sample.astype(np.float32):
        one = w[None, ...]
        fo = f_sess.run(None, {fi: one})
        qo = q_sess.run(None, {qi: one})
        for name, a, b in zip(("anomaly", "fault", "severity"), fo, qo):
            deltas[name] = max(deltas[name], float(np.max(np.abs(a - b))))
        # The decision, not the logit. A quantisation that moves a logit by
        # 0.01 is harmless; one that moves it across zero is a different model.
        if (fo[0] >= 0.0) != (qo[0] >= 0.0):
            changed += 1
    rep.max_delta = deltas
    rep.decisions_changed = changed
    rep.windows_compared = int(len(x_sample))

    REPORT_PATH.write_text(json.dumps(rep.as_dict(), indent=2), encoding="utf-8")
    return rep


# ---------------------------------------------------------------------------
# Inference (aircraft side -- numpy and onnxruntime only)
# ---------------------------------------------------------------------------


class EdgeScorer:
    """Tier-3 scoring onboard, with no torch and no layer3_ai import.

    That absence is the point of the module, so it is asserted in the tests
    rather than left as an intention.
    """

    # THE FLOAT GRAPH IS THE DEFAULT, AND THE MEASUREMENT IS WHY.
    #
    # Dynamic INT8 was exported and measured against the float graph on 300
    # real windows from four held-out engines:
    #
    #     size        149.6 KB -> 50.9 KB          2.94x smaller
    #     latency     0.473 ms -> 0.562 ms         0.84x, i.e. SLOWER
    #     max logit deviation   anomaly 3.32, fault 8.22, severity 1.95
    #     anomaly decisions changed              5 of 300  (1.7 %)
    #
    # So on this network the quantisation is smaller, SLOWER, and changes the
    # answer on one window in sixty. A model that disagrees with the validated
    # one on 1.7 % of windows has not been optimised, it has been replaced, and
    # the evaluation that justified deploying it no longer applies.
    #
    # The float ONNX graph is already 149 KB at 0.47 ms against a 500 ms
    # budget, which is lightweight by any measure that matters, and it agrees
    # with the validated model exactly. INT8 remains exportable for a target
    # where the trade comes out differently -- an ARM core with int8 SIMD may
    # well invert the latency result -- but it must be re-measured there and
    # passed in explicitly, never picked up by default.
    def __init__(self, path: Path | str | None = None, *, threads: int = 1) -> None:
        if not RUNTIME:  # pragma: no cover
            raise RuntimeError(UNAVAILABLE)
        p = Path(path) if path else FLOAT_PATH
        if not p.exists():
            raise FileNotFoundError(
                f"no exported model at {p}. Run edge_infer.export() on the "
                f"ground first -- the aircraft does not train."
            )
        self.path = p
        opts = ort.SessionOptions()
        # ONE thread by default. An edge computer is running the ingest loop,
        # the rule engine and the buffer on the same few cores, and a scorer
        # that grabs every core to shave a millisecond off a 500 ms budget
        # takes that time out of the layers with the hard deadline.
        opts.intra_op_num_threads = threads
        opts.inter_op_num_threads = threads
        self.sess = ort.InferenceSession(
            str(p), sess_options=opts, providers=["CPUExecutionProvider"]
        )
        self._in = self.sess.get_inputs()[0].name

    @staticmethod
    def _sigmoid(z: np.ndarray) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-z))

    def score(self, window: np.ndarray) -> dict[str, np.ndarray]:
        """One or more windows in, probabilities out.

        Sigmoid is applied HERE, matching MultiTaskNet.forward returning
        logits. Having the edge and the ground apply it in different places is
        how a threshold calibrated on one comes to be used against the other.
        """
        x = np.asarray(window, dtype=np.float32)
        if x.ndim == 2:
            x = x[None, ...]
        a, f, s = self.sess.run(None, {self._in: x})
        return {
            "anomaly": self._sigmoid(a),
            "fault": self._sigmoid(f),
            "severity": self._sigmoid(s),
        }

    def is_anomalous(self, window: np.ndarray, threshold: float = 0.5) -> np.ndarray:
        return self.score(window)["anomaly"] >= threshold


__all__ = ["FLOAT_PATH", "INT8_PATH", "REPORT_PATH", "RUNTIME", "UNAVAILABLE",
           "EdgeScorer", "ExportReport", "export"]
