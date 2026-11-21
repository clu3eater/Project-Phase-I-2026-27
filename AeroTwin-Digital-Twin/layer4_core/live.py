"""The live pipeline -- every layer running together, once per tick.

This is the first place the whole system runs as one thing rather than as six
tested pieces. Each tick:

    physics -> CAN encode -> CAN decode+validate -> Tier-1 rules
            -> shadow model -> twin sync -> health -> Tier-2 -> fusion

Everything the console shows comes from here, and nothing here is mocked. The
CAN frames are really encoded and really decoded; the twin really compares
measurement against an as-new reference; the alerts really come from the rule
engine that a healthy engine leaves silent.

WHY A THREAD AND A SNAPSHOT
---------------------------
The simulation has to advance on a steady clock whether or not anyone is
watching, and a web request must never block on a physics step. So the loop
owns the state and publishes an immutable snapshot; readers take the snapshot
and never touch the running objects. A request arriving mid-tick gets the
previous complete state rather than a half-updated one.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import zlib
from collections import deque
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np

from common import config
from layer1_edge.can_ingest import CanIngest
from layer1_edge.can_simulator import CanSimulator
from layer1_edge.edge_rules import RuleEngine
from layer1_edge.mavlink_efi import EfiDownlink
from layer1_edge import order_analysis as oa
from layer2_physics import atmosphere as atmo
from layer2_physics import om_table
from layer2_physics.degradation import FaultMode, InjectedFault
from layer2_physics.engine_sim import VirtualEngine
from layer3_ai import advisory as adv
from layer3_ai import battery as bat
from layer3_ai import efficiency as eff
from layer3_ai import explain as ex
from layer3_ai import fault_namer as fn
from layer3_ai import features as feat
from layer3_ai import fusion as fu
from layer3_ai import health as hl
from layer3_ai import rul_fault as rf
from layer3_ai import rul_physics as rp
from layer3_ai import rul_serving as rs
from layer3_ai import sortie_features as sf
from layer3_ai import survival_serving as sv
from layer3_ai import tier2_statistical as t2
from layer4_core import flight_record as fr
from layer4_core import operator_view as ov
from layer4_core.mission import MissionReliability, rul_consumption_rate
from layer4_core.shadow_model import ShadowModel
from layer4_core.twin_state import FAULT_KEYS, HealthIndices, RemainingLife, create_twin


_log = logging.getLogger(__name__)

# How many consecutive tick failures before the twin declares itself DEGRADED
# and `/api/healthz` stops reporting ok. Deliberately small: at the loop's own
# rate this is a fraction of a second, and a twin that has missed five ticks
# running is already showing an operator a stale engine. It is not zero because
# one transient failure -- a momentary bus glitch -- must not take the system
# down; the distinction between a blip and a fault is exactly what was missing.
_TICK_FAILURE_LIMIT = 5

# Ticks between envelope order analyses. It needs ~40 revolutions of
# 10 kHz waveform and costs far more than the 10-20 ms physics budget,
# so it runs on a cadence. Bearing wear develops over hundreds of
# hours; analysing it twice a second would buy nothing and cost the
# tick rate. On a real aircraft this runs on the edge node instead.
_ORDER_EVERY_TICKS = 120

# The word shown to an operator for each fused level. Only the quiet state
# differs from the enum name; the alerting levels already carry MIL-STD-411F's
# own vocabulary and must not be renamed.
_DISPLAY_LEVEL = {"NONE": "NORMAL"}


def _pct_to_fraction(x: float | None) -> float | None:
    """Percent -> fraction, for a channel the twin and the fleet name alike
    but scale differently. None stays None: `features.build_one` substitutes
    the feature's own centre for a missing value, which says "no information"
    rather than inventing a duty cycle of zero."""
    return None if x is None else float(x) / 100.0


def _reportable_life(served: Any, physics: Any) -> tuple[float | None, str, str]:
    """(hours, source, why) for the remaining life the operator is shown.

    Two gates, both from measurement rather than taste.

    The network is served only once its OWN inputs are valid: the feature
    window full and the early-life residual baseline frozen. Measured on a
    healthy engine on 17 Sep, served before that gate, the figure went 10.3 h,
    then 95.9 h, then 346.9 h inside six minutes of one flight on an engine
    that had not changed -- and 8.5 h of remaining life on a new engine is a
    number an operator would ground the aircraft over.

    And no figure is shown without its interval. PRD Part 4 s7.4a forbids a
    bare remaining life outright, and the network is saved without its
    conformal multiplier, so the interval can only come from the physics
    estimator. Without one, the honest output is the reason, not a number.
    """
    own = served.lower_hours is not None and served.upper_hours is not None
    interval = physics.lower_hours is not None and physics.upper_hours is not None
    if served.hours is not None and getattr(served, "baseline_frozen", False) and (own or interval):
        return float(served.hours), "lstm", served.reason
    if physics.reportable and interval:
        return float(physics.hours), "physics_fallback", physics.reason
    why = physics.reason or "no remaining-life estimate is available"
    if served.hours is not None and not getattr(served, "baseline_frozen", False):
        why = f"{why}; the network's residual baseline is still forming"
    elif served.hours is not None and not (own or interval):
        why = f"{why}; no calibrated interval exists for the network's figure"
    return None, "none", why


def _withhold_unassessed(health: dict, status: dict) -> dict:
    """The published health dict, with its assessment status attached.

    Before the engine has once been warm and loaded there is no condition to
    report, so every index is withheld rather than showing a cold engine's
    figures as its health -- the red subsystem bars on every start.
    """
    out = {**health, "assessment": status}
    if status.get("state") == "assessing":
        for k, val in health.items():
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                out[k] = None
        out["band"] = None
        out["action"] = None
    return out


def _detection_confidence(deep_source: str, network_confidence: float,
                          in_distribution: bool = True) -> float:
    """How far to believe the tier that actually produced the deep score.

    PRD Part 4 s7.4b asks whether the DETECTION models can be trusted. It was
    wired to the remaining-life TREND's confidence, which is a different
    question: a healthy engine has no decline to extrapolate, so that number is
    0 by definition and the console declared "rule-based fallback" while the
    trained network was scoring the same engine at 0.96 (measured 17 Sep).

    A model asked about something it was never shown is not a trustworthy model
    however well it scored on what it was, so a sample outside the training
    distribution earns no confidence at all.
    """
    if not in_distribution:
        return 0.0
    return float(network_confidence) if deep_source.startswith("Tier-3 network") else 0.0


def _alert_as_dict(a: Any) -> dict:
    """Render one alert as a plain dict for the flight record.

    `layer1_edge.edge_rules.Alert` is a DATACLASS, not a Pydantic model. The
    previous `dict(a)` fallback therefore raised `TypeError: 'Alert' object is
    not iterable` on every tick from the moment the first alert appeared --
    which froze the whole twin permanently, because `_run` catches the
    exception and the tick counter never advances past the failing line.

    It survived review because it only executes when `alerts.active` is
    NON-EMPTY: a healthy engine never reaches it. The system broke the instant
    it did the one thing it exists to do. Regression test:
    `test_live_survives_its_first_alert`.
    """
    if hasattr(a, "model_dump"):          # a Pydantic model
        return a.model_dump(mode="json")
    if is_dataclass(a) and not isinstance(a, type):
        return asdict(a)
    if isinstance(a, dict):
        return a
    # Last resort: never let a rendering detail stop the engine.
    return {"legend": str(a)}


@dataclass
class Snapshot:
    """One complete, self-consistent view of the system."""

    t_s: float = 0.0
    # A clock for the console, which shows time-of-day and nothing else.
    wall_utc: str = ""
    # A DATE for anything filed. The post-flight report is read months later
    # against an airframe log, and "15:30:22Z" does not say which day.
    wall_iso: str = ""
    started_iso: str = ""
    twin: dict = field(default_factory=dict)
    mission: dict = field(default_factory=dict)
    explanation: dict = field(default_factory=dict)
    maintenance: dict = field(default_factory=dict)
    battery: dict = field(default_factory=dict)
    efficiency: dict = field(default_factory=dict)
    # The operator-facing view: the SAME quantities, smoothed, quantised
    # and held still enough to read. See docs/WHO_READS_THIS_SCREEN.md.
    display: dict = field(default_factory=dict)
    # Per-fault time-to-action: when each of the eight PS fault modes
    # reaches the threshold at which the system itself would raise it.
    fault_forecast: list = field(default_factory=list)
    # The post-flight record: phase-tagged events, exceedances with
    # time-above, and the stabilised cruise datum. Accumulated over the
    # whole flight and not reconstructible from a snapshot afterwards.
    flight_record: dict = field(default_factory=dict)
    health: dict = field(default_factory=dict)
    rul: dict = field(default_factory=dict)
    # Calibrated P(fail within h) for the horizons a dispatch decision is
    # taken on. Reported BESIDE rul, not instead of it: hours-remaining sits
    # near its information ceiling on this data and the probability is the
    # number that is accurate, so an operator should see both and be able to
    # tell which is which.
    survival: dict = field(default_factory=dict)
    fusion: dict = field(default_factory=dict)
    trend: dict = field(default_factory=dict)
    pipeline: dict = field(default_factory=dict)
    history: dict = field(default_factory=dict)
    # The same channels as `history`, but decimated across the WHOLE sortie
    # rather than the last few minutes. The console reads `history`; the
    # post-flight report reads this one.
    flight_series: dict = field(default_factory=dict)
    faults_injected: list = field(default_factory=list)
    # Where the sortie is: "running" until the engine has been shut down at
    # the end of it, then "complete" -- with its start, end and flight time.
    sortie: dict = field(default_factory=dict)


def _operator_reason(exc: BaseException) -> str:
    r"""What to SHOW when a model will not load or score.

    A raw exception is written for whoever reads the log, and an operator is
    not that person. Screenshotting the console caught this one on the
    prognostics page:

        STAT: not scored: Tier-2 unavailable: [Errno 2] No such file or
        directory: 'C:\Users\sarsw\AppData\Local\Temp\console_shot...

    -- a local filesystem path, an account name and a doubled-backslash repr,
    printed on a defence console and running past the edge of its panel. It
    tells the operator nothing they can act on and tells anyone watching the
    screen the layout of the host.

    The detail is not discarded; it goes to the log at WARNING, where the
    engineer who can act on it will look. What reaches the screen is the state
    and its consequence.
    """
    if isinstance(exc, FileNotFoundError):
        return "not installed on this aircraft"
    if isinstance(exc, (KeyError, ValueError, TypeError)):
        return "rejected: does not match the served feature contract"
    if isinstance(exc, (MemoryError, OSError)):
        return "could not be read from storage"
    return "unavailable"


class LiveTwin:
    """Runs one engine and its twin continuously in the background."""

    def __init__(
        self,
        *,
        twin_id: str = "UAV-ENG-001",
        aircraft_id: str = "MALE-01",
        engine_key: str = "rotax_915is",
        dt: float = 0.5,
        speed: float = 20.0,
        channel: str = "live",
        seed: int | None = None,
        cruise_hours: float | None = None,
        persist: bool = False,
        life_dir: "os.PathLike[str] | str | None" = None,
    ) -> None:
        # A FIXED SEED MADE EVERY RUN IDENTICAL.
        #
        # It was 11, hardcoded, so two flights flown an hour apart produced
        # bit-identical readings and therefore bit-identical charts in the
        # post-flight report. Reproducibility is worth having -- it is what
        # makes a test meaningful -- but it belongs behind an explicit choice,
        # not in the default, because "the report looks the same every time"
        # reads as a system that is not actually measuring anything.
        #
        # BUT THE ENGINE MUST BE THE SAME ENGINE. The seed also drew the
        # engine's manufacturing spread and its wear rates, so every station
        # start simulated a different engine under the same serial number --
        # and the trend across flights compared them: "EGT +19 C, power
        # +10.9 kW since the first comparable flight" was the difference
        # between two unrelated random engines. So the ENGINE now comes from
        # the serial (DT_ENGINE_SEED overrides), and only the instrument NOISE
        # is drawn fresh each run. An explicit `seed` fixes both, for tests.
        noise_seed = seed
        if seed is None:
            seed = int(os.environ.get("DT_ENGINE_SEED")
                       or zlib.crc32(twin_id.encode("utf-8")))
            noise_seed = int.from_bytes(os.urandom(4), "big")
        self.seed = seed
        self.twin_id = twin_id
        self.dt = dt
        # Wall-clock seconds per simulated second. A demo that advances in real
        # time would take twenty minutes to show a climb, so it runs fast --
        # but the SIMULATED clock is what every timestamp reports, so nothing
        # downstream can mistake the two.
        self.speed = speed
        self.engine_key = engine_key

        self._started_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.sim = CanSimulator(interface="virtual", channel=channel)
        self.ingest = CanIngest(interface="virtual", channel=channel, engine_key=engine_key)
        # Sensors that have stopped following the engine (audit 15 Sep, P0-5).
        from layer4_core.sensor_response import SensorResponseMonitor
        self.response = SensorResponseMonitor(self.ingest)
        # How far each instrument reads from the twin, and whether the
        # instrument can be blamed for it (audit 15 Sep, P0-4).
        from layer4_core.sensor_bias import BiasMonitor
        self.bias = BiasMonitor(self.ingest)
        self.rules = RuleEngine()
        self.shadow = ShadowModel(engine_key=engine_key)
        # A COMPLETE SORTIE, or the report is a chart that stops mid-climb.
        #
        # The loop is compute-bound at roughly 15x real time however high
        # `speed` is set -- a physics tick costs about 28 ms, and asking for
        # 1200x does not make it cheaper. So the default one-hour cruise needs
        # some six minutes of wall clock to fly through, and every
        # demonstration was stopped long before descent. The post-flight
        # report then showed take-off and climb and nothing else, with the
        # traces cut off at the right-hand edge.
        self.cruise_hours = (
            float(os.environ.get("DT_CRUISE_HOURS", "0"))
            or (cruise_hours if cruise_hours is not None else 1.0)
        )
        self.veng = VirtualEngine(engine_key=engine_key, seed=seed,
                                  cruise_hours=self.cruise_hours)
        if noise_seed != seed:
            # The instruments' noise, fresh this run; the engine above is not.
            self.veng.rng = np.random.default_rng(noise_seed)
            self.veng.rng_lane_b = np.random.default_rng(
                np.random.SeedSequence(noise_seed).spawn(1)[0])
        # SET FROM THE WEB THREAD, ACTED ON BY THE TWIN THREAD.
        #
        # `restart_sortie` re-initialises the engine model's state vector, and
        # the twin thread is integrating that same model continuously. Calling
        # it from a request handler would rewrite the state underneath a step
        # in progress. So a login raises this flag and the twin performs the
        # restart itself, between ticks, where nothing is half-done.
        self._restart_requested = False
        # A profile the next restart flies instead of the one already set:
        # (phases, kind, env_condition, label). See `begin_profile`.
        self._pending_profile: tuple | None = None
        # What the current run of the engine IS: "demo" (the self-flying
        # demonstration profile), "parked", "mission" or "ground_run".
        self._profile_kind = "demo"
        self._profile_label = ""
        # Changes asked for on a request thread and applied by the twin thread
        # between ticks (instrument and lane failures, their repair).
        self._pending_ops: list = []
        # WHEN THE ENGINE'S CONDITION CAN BE JUDGED. See `_assessable`.
        _ha = config.load_thresholds()["health"]["assessment"]
        self._assess_min_rpm = float(_ha["min_rpm"])
        self._assess_min_oil_c = float(
            config.load_thresholds()["parameters"]["oil_temperature"]["takeoff_min"])
        self._assess_settle_s = float(_ha["settle_s"])
        self._assess_rpm_band = float(_ha["rpm_band_pct"]) / 100.0
        self._assess_since: float | None = None
        self._assess_rpm: deque[tuple[float, float]] = deque()
        # Recent (time, altitude) for the level-flight test of the residual
        # reference. See `_serve_rul`.
        self._alt_trace: deque[tuple[float, float]] = deque()
        # Tier-2 and Tier-3 scores smoothed over assessed samples. See fusion.
        self._stat_ema: float | None = None
        self._deep_ema: float | None = None
        self._tier_alpha = float(
            config.load_thresholds()["fusion"]["tier_smoothing_alpha"])
        # The statistical score's decision line in the fusion layer: the
        # predictive-caution gate. Each condition's measured limit is mapped
        # onto it (DEV-252).
        self._stat_gate = float(config.load_thresholds()["detectors"]["fusion"][
            "l3_predictive"]["s_statistical_above"])
        self._deep_gate = float(config.load_thresholds()["detectors"]["fusion"][
            "l3_predictive"]["s_deep_above"])
        # Beyond this horizon the life network was trained to say only "not
        # yet" (rul.prediction_horizon_hours), and before a wear trend exists
        # there is no count-down to report.
        _rc = config.load_thresholds()["rul"]
        self._life_horizon_h = float(_rc["prediction_horizon_hours"])
        self._life_onset_chi = float(_rc["health_onset_threshold"])
        # The last assessment made warm, held through every period that
        # cannot be judged: {"health", "trend", "rul", "served", "t_s"}.
        self._held: dict | None = None
        self._assessed_now = False
        # The operating regime the fault trends and the sortie vector were
        # gathered in. See `_regime_change`.
        self._fault_regime: tuple | None = None
        # Readings the survival head's sortie vector needs before it is the
        # vector the head was trained on: 50 at one settled point.
        self._sortie_min_samples = 50
        self._chi_decision_now = 1.0
        # THE SORTIE HAS AN END. See `_sortie_status` and the SHUTDOWN phase.
        self._sortie_state = "running"
        self._sortie_started_t = 0.0
        self._sortie_ended_t: float | None = None
        self._sortie_recorded = False
        self._sortie_end_pending = False
        # Called once per flight with the flight's final snapshot and why it
        # ended ("complete", "interrupted"): the station writes the flight to
        # its history there. Set by the API; None writes nothing.
        self.on_sortie_end = None
        self.state, self.sync = create_twin(
            twin_id, aircraft_id=aircraft_id, engine_key=engine_key
        )
        self.health = hl.HealthEstimator(use_residuals=True)
        self.rul = rp.PhysicsRul(engine_key=engine_key)
        # The trained network, loaded once. If the checkpoint is absent or
        # its feature order disagrees with this build, `available` stays
        # False and every tick falls through to the physics estimate above --
        # which is precisely the behaviour that shipped before A1.
        self.rul_net = rs.LstmRulServer(
            sequence_length=int(
                config.load_thresholds()["detectors"]["tier3"][
                    "sequence_length"]
            ),
            # It observes assessed ticks only, one per `dt` of engine time.
            baseline_settle_samples=int(round(
                float(config.load_thresholds()["health"]["assessment"][
                    "residual_reference_settle_s"]) / max(self.dt, 1e-6))),
        )
        # THE TIER-3 NETWORK, SCORED LIVE (ML-01). The fused-detection panel
        # used to be fed two hand-made formulas while the trained network sat
        # on disk. Its exported float graph is scored on the SAME normalised
        # window the RUL network is given -- both were trained on
        # feat.extended() with baselined residuals -- and the input width is
        # checked against that window rather than assumed.
        # THE FITTED TIER-2 ENSEMBLE, not a stand-in for one (audit 15 Sep,
        # P1-2). Saved by scripts/eval_tier2.py with the threshold it was
        # chosen against; without the file there is no statistical tier, and
        # the snapshot says so rather than showing a proxy under its name.
        self.tier2 = None
        self.tier2_threshold: float | None = None
        self.tier2_reason = "not loaded"
        # One limit per flight condition (DEV-252). An older file carries none
        # and is scored against its single limit.
        self.tier2_limits: dict[int, float] = {}
        self.tier2_bins: dict | None = None
        self._stat_limit: dict = {}
        try:
            import joblib

            _blob = joblib.load(config.data_dir() / "models" / "tier2_extended.joblib")
            self.tier2 = _blob["ensemble"]
            self.tier2_threshold = float(_blob["threshold"])
            self.tier2_limits = {int(k): float(v)
                                 for k, v in (_blob.get("regime_thresholds") or {}).items()}
            self.tier2_bins = _blob.get("regime_bins")
            self.tier2_reason = "loaded"
        except Exception as exc:  # noqa: BLE001 - reported, not handled
            # The engineer gets the path; the operator gets the consequence.
            _log.warning("Tier-2 ensemble not loaded", exc_info=exc)
            self.tier2_reason = _operator_reason(exc)
        self._stat_source = "not yet scored"

        # IS THIS SAMPLE LIKE THE DATA THE MODELS WERE TRAINED ON? (audit
        # 15 Sep, P1-6). Nothing asked, so a score carried the same authority
        # on a condition the fleet never contained as in the middle of the
        # training set. Outside it, the tier scores are not evidence and the
        # confidence says so.
        self.ood = None
        self.ood_reason = "not loaded"
        try:
            from layer3_ai.ood import OodDetector

            self.ood = OodDetector.load(config.data_dir() / "models")
            self.ood_reason = "loaded"
        except Exception as exc:  # noqa: BLE001 - reported, not handled
            self.ood_reason = f"unavailable: {exc}"
        self._ood_verdict = None

        self.tier3 = None
        self.tier3_reason = "not loaded"
        self._deep_source = "not yet scored"
        # The trained fault head's probabilities, when it has scored.
        self._fault_probs: dict[str, float] | None = None
        try:
            from layer1_edge.edge_infer import EdgeScorer

            _sc = EdgeScorer()
            _width = _sc.sess.get_inputs()[0].shape[-1]
            if isinstance(_width, int) and _width != len(self.rul_net.fs.columns):
                self.tier3_reason = (f"input width {_width} does not match the "
                                     f"serving feature set "
                                     f"({len(self.rul_net.fs.columns)})")
            else:
                self.tier3, self.tier3_reason = _sc, "loaded"
        except Exception as exc:  # noqa: BLE001 - reported, not handled
            self.tier3_reason = f"unavailable: {exc}"
        # How far the DETECTION models may be believed (PRD Part 4 s7.4b). The
        # network's OWN measured anomaly-head F1 from its training report, not a
        # number chosen here, and 0 when the network is not what is scoring.
        self._tier3_confidence = 0.0
        self._fault_cal: dict[str, dict[str, float]] = {}
        try:
            _report = json.loads(
                (config.data_dir() / "models" / "tier3_report.json").read_text(
                    encoding="utf-8"))
            self._tier3_confidence = float(_report["anomaly_head"]["f1"])
            # Each fault class's DECISION threshold and measured precision, from
            # the same report. The raw per-class scores are not probabilities
            # to be read against 50 %: combustion instability is called at 0.98
            # and overheating at 0.04, so "combustion instability 29 %" on a
            # healthy engine was a number below its own call level shown as a
            # finding, and the 3D engine lit parts at a flat 0.30.
            self._fault_cal = {
                k: {"threshold": float(v["threshold"]),
                    "precision": float(v["precision"])}
                for k, v in _report["fault"]["per_class"].items()
            }
        except Exception as exc:  # noqa: BLE001 - reported, not fatal
            _log.info("no Tier-3 report to read a model confidence from: %s", exc)
        # WHICH FAULT IT IS (DEV-253). The network above answers "is something
        # wrong?" well and "which fault?" at macro-F1 0.61; this namer, which
        # also reads the engine's history, measured 0.78 on the same unseen
        # engines. When it is on disk it names the faults, with its OWN
        # thresholds and measured precision; without it the network does.
        self.fault_namer: fn.FaultNamer | None = None
        self.namer_history = fn.SortieHistory()
        self._namer_probs: dict[str, float] | None = None
        try:
            import joblib

            self.fault_namer = fn.FaultNamer(
                joblib.load(config.data_dir() / "models" / "fault_namer.joblib"))
            _per = self.fault_namer.report.get("per_class", {})
            self._fault_cal = {
                k: {"threshold": float(self.fault_namer.thresholds[k]),
                    "precision": float(_per.get(k, {}).get("test_precision", 0.0))}
                for k in self.fault_namer.classes
            }
        except Exception as exc:  # noqa: BLE001 - reported, not fatal
            _log.info("fault namer not loaded; the network names faults: %s", exc)
        # The calibrated failure probability -- the accurate answer to the
        # question a dispatcher actually asks, and until now the one result
        # nothing running could produce. Its inputs are per-sortie aggregates,
        # so the accumulator carries the current sortie and the previous
        # sortie's levels; `end_sortie()` rolls them over.
        self.survival = sv.SurvivalServer()
        self.sortie = sf.SortieAccumulator(
            list(feat.extended().columns), health=True)
        self._sortie_values: dict[str, float | None] = {}
        # PS section C asks for PREDICTION of each fault, not only
        # detection. Detection says a fault is present; a maintenance
        # planner holding that cannot schedule anything.
        self.fault_rul = rf.FaultRul()
        # What the POST-FLIGHT report is made of: events tagged with the
        # phase they happened in, exceedances with time-above as well as
        # peak, and one stabilised cruise datum for trend monitoring.
        # None of it can be reconstructed from a snapshot after the fact.
        self.record = fr.FlightRecord()
        self.fusion = fu.ScoreFusion()
        self.mission = MissionReliability()
        self.advisory = adv.AdvisoryEngine()
        self.battery = bat.BatteryHealth(engine_key)
        self.efficiency = eff.EfficiencyTracker(engine_key)
        # The OPERATOR's view of the slow quantities. Separate from the
        # model's own output, which the engineer's screens keep reading
        # unsmoothed -- for a propulsion engineer the noise IS the data.
        self.operator = ov.OperatorView()

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._snapshot = Snapshot()
        self._injected: list[dict] = []
        self._trend: list[dict] = []
        self._series: dict[str, list] = {
            "t": [], "cht": [], "cht_pred": [], "egt": [], "coolant": [],
            "oil_pressure": [], "chi": [], "rpm": [],
            # PS section F asks for efficiency TRENDS, not an efficiency
            # reading. Deterioration against the as-new twin is the series
            # worth keeping: absolute BSFC mostly plots what the pilot is
            # doing, and a trend of that teaches an operator nothing.
            "bsfc_deterioration": [], "thermal_efficiency": [],
            # Every parameter that gets a tile on the dashboard needs its own
            # series, or the tile shows a number with no trend beside it --
            # which is the reading-without-context problem again.
            "fuel_flow": [], "oil_temperature": [],
            # The FLIGHT, not just the engine. The post-flight report plots an
            # altitude and airspeed profile and reports the environment the
            # sortie was flown in, and neither is derivable from an engine
            # channel: a cylinder head is hotter on a hot day at low airspeed,
            # and a reader who cannot see that reads it as deterioration.
            "altitude_ft": [], "airspeed_kt": [], "oat_c": [],
            "humidity_pct": [], "ambient_pressure_hpa": [],
            "manifold_pressure": [], "vibration_rms_total": [],
        }
        # WHOLE-FLIGHT series for the post-flight report, kept apart from
        # `_series` above. That one is a ring buffer of the last 240 ticks,
        # which is right for a console showing the last couple of minutes and
        # wrong for a report: plotting 240 samples of the descent across an
        # axis spanning eighteen hours draws the entire flight as a smear
        # against the right-hand edge.
        #
        # Bounded by decimation rather than by discarding: once the buffer is
        # full, every second sample is dropped and the stride doubles, so the
        # series always spans the whole sortie for a fixed memory cost.
        self._flight_series: dict[str, list] = {}
        self._flight_stride = 1
        self._flight_seen = 0

        self._latencies: list[float] = []
        # Running EMA of each health sub-index, so the explanation reasons
        # over the same smoothed picture the console displays.
        self._index_ema: dict[str, float] = {}
        self._ticks = 0
        # Tick-failure accounting. `_consecutive` drives the DEGRADED
        # flag and resets on the first good tick; `_total` is
        # life-of-process and never resets, so a loop that fails
        # intermittently is still visible after it recovers.
        self._consecutive_failures = 0
        self._total_failures = 0
        # Optional observer called with each completed snapshot.
        # Used by the flight data recorder; kept generic so the
        # pipeline does not import a writer it does not need.
        self._on_tick = None
        # MAVLink EFI_STATUS to a ground station, when configured. A downlink
        # that cannot open must not stop the twin: the failure is logged and
        # the twin runs without it.
        self.mavlink: EfiDownlink | None = None
        try:
            self.mavlink = EfiDownlink.from_config()
        except (OSError, KeyError, ValueError):
            _log.exception("MAVLink downlink not started")
        # Whether this engine has a manufacturer performance table to be
        # outside of. An engine defined without one makes no such claim.
        self._has_om_table = om_table.table_for(self.veng._engine) is not None
        # Maintenance recorded by the ground crew, applied on the tick thread
        # (see record_maintenance), and the record of the work applied so far.
        self._maintenance_pending: list[dict] = []
        self._maintenance_log: list[dict] = []
        # Engine hours at the last overhaul, on the engine's own clock -- the
        # one the overhaul limit handed to mission planning is counted on.
        self._overhaul_engine_hours = 0.0
        # Envelope order analysis. On a real aircraft this runs on the
        # EDGE node, which has the 10 kHz waveform; only the RESULT
        # crosses the 10 Hz bus. Here both live in one process, so the
        # cadence is what keeps the honesty: it is NOT computed every
        # tick, because it needs ~40 revolutions of signal and costs far
        # more than the 10-20 ms physics budget of PRD Part 1 s6.4.
        self._order: oa.OrderAnalysis | None = None
        self._order_tick = -10**9
        # Rolling windows for the four fault indicators the CAN bus does not
        # carry and the edge ingest never derived. Without them misfire, sensor
        # drift, combustion instability and abnormal vibration sat at "no data"
        # on every flight, whatever was wrong with the engine.
        from collections import deque as _dq
        self._misfire_hits = _dq(maxlen=120)          # 60 s at dt 0.5
        # 60 s of exhaust residual, for the scatter feature the fleet carries.
        # Speed and cross-cylinder-spread scatter were computed here too, for
        # the two columns the contract briefly carried. They cost the twin work
        # every tick and the network scored WORSE with them (features.py), so
        # the windows are gone with the columns.
        self._egt_scatter_window = _dq(maxlen=max(10, int(round(60.0 / max(dt, 1e-6)))))
        self._egt_resid = _dq(maxlen=120)
        # Charge-pressure shortfall against the twin, as a fraction, cruise only.
        self._boost_drop = _dq(maxlen=120)
        # Wastegate position against the as-new twin, percentage points (PHY-07).
        self._wg_closure = _dq(maxlen=120)
        self._resid_windows = {
            n: _dq(maxlen=600) for n in
            ("cht", "coolant", "egt", "oil_pressure", "oil_temperature")
        }
        self._misfire_sigma = float(
            config.load_thresholds()["faults"]["misfire"]["egt_drop_sigma"])
        # THE ENGINE'S LIFE OUTLIVES THE PROCESS. See `_restore_engine_life`.
        self._persist = persist
        self._life_dir = life_dir
        self.engine_life_restored: dict | None = None
        if persist:
            self._restore_engine_life()

    # ------------------------------------------------------------------
    # Engine life across station restarts
    # ------------------------------------------------------------------
    _LIFE_SCHEMA = 1

    def _life_path(self):
        # One file per ENGINE on this airframe slot. A station switched to
        # another engine type and back must find the first engine's wear where
        # it left it, not overwritten by the other's. The reference engine
        # keeps the original name, so an existing station's history is kept.
        suffix = ("" if self.engine_key == config.REFERENCE_ENGINE
                  else f"__{self.engine_key}")
        from pathlib import Path
        base = (Path(self._life_dir) if self._life_dir is not None
                else config.data_dir() / "twin_state")
        return base / f"{self.twin_id}{suffix}.pkl"

    def _restore_engine_life(self) -> None:
        """Pick the engine up where the last run of the station left it.

        Every station start used to begin the engine at zero hours and as-new,
        so its wear, its health trend and the maintenance done on it lasted
        exactly as long as the server process -- a twin of an engine that is
        replaced every time the ground station reboots. The file is written by
        this class only (at each sortie's end and at shutdown), and is read
        only if it is the same engine: the same type and the same identity.
        """
        import pickle

        path = self._life_path()
        if not path.exists():
            return
        try:
            with path.open("rb") as f:
                blob = pickle.load(f)
            if (blob.get("schema") != self._LIFE_SCHEMA
                    or blob.get("engine_key") != self.engine_key
                    or blob.get("seed") != self.seed):
                _log.info("saved engine life is for a different engine; not restored",
                          extra={"path": str(path)})
                return
            self.veng.degradation = blob["degradation"]
            self.veng.model.degradation = self.veng.degradation.factors
            self.veng.flight_hours = float(blob["flight_hours"])
            self.veng.sensors = blob["sensors"]
            self.health = blob["health"]
            self.rul = blob["rul"]
            # The engine's own early-life residual reference. Without it a
            # restart re-formed the reference from the engine as it now is, so
            # wear already present was taken for build offset and subtracted
            # out of every residual the RUL network and the survival head read.
            if blob.get("residual_baseline") is not None:
                self.rul_net.baseline = blob["residual_baseline"]
            # The flights the fault namer's trends are taken over.
            if blob.get("fault_history") is not None:
                self.namer_history = blob["fault_history"]
            self._overhaul_engine_hours = float(blob.get("overhaul_engine_hours", 0.0))
            self._maintenance_log = list(blob.get("maintenance_log", []))
            self._restore_metadata(blob.get("metadata"))
            self.engine_life_restored = {"flight_hours": self.veng.flight_hours,
                                         "saved_utc": blob.get("saved_utc")}
            _log.info("engine life restored", extra=self.engine_life_restored)
        except Exception:
            # A damaged file must not stop the station; it starts as-new and
            # says so in the log.
            _log.exception("could not restore the saved engine life")

    # THE LOGBOOK HOURS SURVIVE A RESTART TOO. The engine's wear and its own
    # hour meter were saved, but the twin's record of them -- total hours, hours
    # since the 100 h inspection, hours at the last overhaul -- was not, so a
    # 900 h engine came back reading 0 h total and 0 h since inspection, and
    # the 100 h check it was due for never came due.
    _METADATA_FIELDS = ("total_flight_hours", "total_cycles", "hours_at_last_overhaul",
                        "last_maintenance_date", "last_overhaul_date")

    def _metadata_blob(self) -> dict:
        md, hist = self.state.metadata, self.state.history
        out = {k: getattr(md, k, None) for k in self._METADATA_FIELDS}
        out["hours_since_inspection"] = float(hist.hours_since_inspection)
        return out

    def _restore_metadata(self, blob: dict | None) -> None:
        md, hist = self.state.metadata, self.state.history
        if not blob:
            # Saved before the logbook was: the hour meter is the best record.
            md.total_flight_hours = float(self.veng.flight_hours)
            return
        for k in self._METADATA_FIELDS:
            if k in blob and blob[k] is not None and hasattr(md, k):
                setattr(md, k, blob[k])
        hist.hours_since_inspection = float(blob.get("hours_since_inspection") or 0.0)

    def age_engine(self, hours: float, *, inspection_every_h: float = 100.0,
                   oil_temp_c: float = 100.0, cht_max_c: float = 112.0) -> None:
        """Give a newly registered engine the life it has already had.

        A squadron's aircraft are not all new. Wear is advanced on the wear
        model's own clock (`VirtualEngine.fast_forward`), with the oil changed
        at every 100 h inspection as the maintenance schedule requires, so a
        900 h engine arrives with 900 h of bearing, deposit and turbocharger
        wear, fresh-ish oil and whatever is left to its next inspection. Only
        called for an engine that has no saved life of its own.
        """
        left = float(hours)
        while left > 1e-9:
            step = min(inspection_every_h, left)
            self.veng.fast_forward(step, oil_temp_c=oil_temp_c, cht_max_c=cht_max_c)
            left -= step
            if left > 1e-9:
                self.veng.degradation.perform_maintenance("A1")
        md, hist = self.state.metadata, self.state.history
        md.total_flight_hours = float(self.veng.flight_hours)
        hist.hours_since_inspection = float(hours) % inspection_every_h

    def save_engine_life(self) -> None:
        """Write the engine's life -- wear, hours, instruments, trend, work."""
        if not self._persist:
            return
        import pickle

        path = self._life_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            blob = {
                "schema": self._LIFE_SCHEMA, "engine_key": self.engine_key,
                "seed": self.seed, "twin_id": self.twin_id,
                "saved_utc": datetime.now(UTC).isoformat(timespec="seconds"),
                "flight_hours": float(self.veng.flight_hours),
                "degradation": self.veng.degradation,
                "sensors": self.veng.sensors,
                "health": self.health,
                "rul": self.rul,
                "residual_baseline": self.rul_net.baseline,
                "fault_history": self.namer_history,
                "overhaul_engine_hours": float(self._overhaul_engine_hours),
                "maintenance_log": list(self._maintenance_log),
                "metadata": self._metadata_blob(),
            }
            tmp = path.with_suffix(".tmp")
            with tmp.open("wb") as f:
                pickle.dump(blob, f)
            os.replace(tmp, path)
        except Exception:
            _log.exception("could not save the engine life")

    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="live-twin")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        self.save_engine_life()
        self.sim.close()
        self.ingest.close()
        if self.mavlink is not None:
            self.mavlink.close()

    def snapshot(self) -> Snapshot:
        with self._lock:
            return self._snapshot

    def inject(self, mode: str, severity: float, ramp_hours: float = 0.05,
               channel: str | None = None) -> dict:
        """Inject a fault into the running engine, for the demonstration.

        Onset is 'now' in the engine's own flight-hour clock, so the operator
        sees the signature develop rather than appear.

        SENSOR DRIFT IS INJECTABLE, AND USED NOT TO BE.
        ------------------------------------------------
        The console greyed it out as "modelled by the instrument layer, not
        injectable", which was true of the fleet generator once and is not true
        of anything now: the generator deals a drift channel and a direction to
        every drifting engine, and the class went from F1 0.019 to 0.53 on the
        strength of it. Leaving the demonstration unable to produce the one
        fault whose detection was rebuilt today meant the fix could be measured
        and not shown.

        A drift afflicts ONE instrument, so `channel` says which. The default
        is manifold pressure because both FADEC lanes measure it -- the lane
        disagreement is then the visible tell, which is the mechanism worth
        demonstrating. Any channel in DRIFTABLE_CHANNELS is accepted; the ones
        without a second lane are detected through their physics residual
        instead, which is the harder and more interesting case.
        """
        from layer2_physics.engine_sim import DRIFTABLE_CHANNELS

        m = FaultMode(mode)
        ch = sign = None
        if m is FaultMode.SENSOR_DRIFT:
            ch = channel or "manifold_pressure"
            if ch not in DRIFTABLE_CHANNELS:
                raise ValueError(
                    f"{ch!r} is not an instrument this engine can drift; "
                    f"choose one of {sorted(DRIFTABLE_CHANNELS)}")
            # Reads HIGH. A drift can go either way and the fleet deals both,
            # but a demonstration wants the direction an observer can predict.
            sign = 1.0
        fault = InjectedFault(
            mode=m, onset_hours=self.veng.flight_hours, severity=float(severity),
            ramp_hours=float(ramp_hours), channel=ch, drift_sign=sign or 1.0,
        )
        self.veng.inject(fault)
        rec = {
            "mode": str(m), "severity": float(severity),
            "onset_hours": round(self.veng.flight_hours, 4),
            "ramp_hours": float(ramp_hours),
            **({"channel": ch} if ch else {}),
        }
        with self._lock:
            self._injected.append(rec)
        return rec

    # INSTRUMENT FAILURES, for demonstrating the sensor checks. The simulator
    # has modelled a frozen and a stuck instrument, and every FADEC lane
    # failure in the manufacturer's matrix it can represent, all along -- and
    # nothing but the test suite could reach either. Console channel -> the
    # simulator's instrument and which of its probes.
    SENSOR_FAILURES: dict[str, tuple[str, int]] = {
        "oil_pressure": ("oil_pressure", 0), "oil_temperature": ("oil_temperature", 0),
        "coolant_temperature": ("coolant_temperature", 0), "fuel_flow": ("fuel_flow", 0),
        "manifold_pressure": ("manifold_pressure", 0), "rpm": ("rpm", 0),
        **{f"cht_{i + 1}": ("cht", i) for i in range(4)},
        **{f"egt_{i + 1}": ("egt", i) for i in range(4)},
    }

    def fail_sensor(self, channel: str, mode: str) -> dict:
        """Fail one instrument: "frozen" repeats its last reading exactly (a
        latched converter); "stuck" stops following the engine but keeps its
        noise (a detached probe). Applied between ticks, like maintenance."""
        if channel not in self.SENSOR_FAILURES:
            raise ValueError(f"no instrument {channel!r} can be failed")
        if mode not in ("frozen", "stuck"):
            raise ValueError(f"unknown instrument failure {mode!r}")
        name, key = self.SENSOR_FAILURES[channel]
        with self._lock:
            self._pending_ops.append(lambda: self.veng.fail_sensor(name, mode, key))
            self._injected.append({"mode": f"{channel} sensor {mode}",
                                   "severity": 1.0,
                                   "onset_hours": float(self.veng.flight_hours)})
        return {"channel": channel, "mode": mode}

    def fail_lane(self, item: str, lane: str) -> dict:
        """Fail one FADEC item on one lane, with the manufacturer's listed
        consequences (warning lamps, lane mode) -- see VirtualEngine."""
        from layer2_physics.engine_sim import LANE_FAILURES_SUPPORTED
        rows = config.load_engine(self.engine_key)["failure_matrix"]["items"]
        if not any(r["item"] == item and str(r["lane"]) == lane for r in rows):
            raise ValueError(f"{item} on lane {lane} is not in the failure matrix")
        if item not in LANE_FAILURES_SUPPORTED:
            raise ValueError(f"a {item} failure is not simulated")
        with self._lock:
            self._pending_ops.append(lambda: self.veng.fail_lane_item(item, lane))
            self._injected.append({"mode": f"FADEC {item} lane {lane} failed",
                                   "severity": 1.0,
                                   "onset_hours": float(self.veng.flight_hours)})
        return {"item": item, "lane": lane}

    # Sudden failures, for the demonstration: what each one does, in the words
    # of the engineer who injects it.
    FAILURES: dict[str, tuple[str, str]] = {
        "fuel_starvation": ("Fuel starvation",
                            "No fuel reaches the injectors: combustion stops, rpm runs down, "
                            "fuel flow and pressure fall to zero."),
        "ignition_failure": ("Ignition failure, both lanes",
                             "Both FADEC lanes lose ignition: the engine stops."),
        "oil_loss": ("Oil loss",
                     "The sump empties: oil pressure collapses in about ten seconds. Run on "
                     "and the bearings seize after about 40 s."),
        "coolant_loss": ("Coolant loss",
                         "The coolant is lost: head temperatures climb within a minute."),
    }

    def fail(self, name: str) -> dict:
        """A sudden failure: the engine stops making power (or soon will)."""
        if name not in self.FAILURES:
            raise ValueError(f"unknown failure {name!r}")
        with self._lock:
            self._pending_ops.append(lambda: self.veng.fail(name))
            self._injected.append({"mode": f"{self.FAILURES[name][0]} (failure)",
                                   "severity": 1.0,
                                   "onset_hours": float(self.veng.flight_hours)})
        return {"failure": name}

    def clear_faults(self) -> None:
        self.veng.degradation.clear_faults()
        def repair() -> None:
            for name, key in self.SENSOR_FAILURES.values():
                self.veng.repair_sensor(name, key)
            self.veng.clear_lane_failures()
            self.veng.clear_failures()
        with self._lock:
            self._pending_ops.append(repair)
            self._injected.clear()

    # WHICH HEALTH INDICES EACH JOB SHOULD MOVE, so the record of the work can
    # show the maintainer the part's health before the job and after it. The
    # composite is always included. A turbocharger has no index of its own;
    # its effect reaches the composite through boost and EGT.
    MAINTENANCE_AFFECTS: dict[str, tuple[str, ...]] = {
        "A1": ("lhi", "oti", "chi"),
        "A2": ("thi", "thermal", "chi"),
        "A3": ("comb_hi", "fshi", "combustion", "chi"),
        "A4": ("csi", "combustion", "chi"),
        "A5": ("mhi", "mechanical", "chi"),
        "A6": ("chi",),
        "A7": ("thermal", "mechanical", "electrical", "combustion", "chi"),
    }
    # Engine time for temperatures and filters to settle after a repair before
    # the "after" reading is taken. A flushed radiator does not cool the head
    # the same second the job is signed off; ~3 min of running does (measured:
    # thermal index 0.45 -> 0.95 over that interval after a cooling flush).
    MAINTENANCE_SETTLE_HOURS = 0.05

    def _health_reading(self, keys) -> dict:
        h = self._snapshot.health or {}
        return {k: (round(float(h[k]), 4) if isinstance(h.get(k), (int, float)) else None)
                for k in keys}

    def _verify_maintenance(self) -> None:
        """Take the settled "after" reading for work applied long enough ago."""
        now_h = float(self.veng.flight_hours)
        with self._lock:
            waiting = [r for r in self._maintenance_log
                       if r.get("status") == "applied" and "health_after" not in r
                       # records from before readings were kept have no
                       # "before" to compare with, so take no "after" either
                       and "health_before" in r
                       and now_h - float(r.get("applied_flight_hours", now_h))
                       >= self.MAINTENANCE_SETTLE_HOURS]
        for rec in waiting:
            after = self._health_reading(rec.get("affects", ("chi",)))
            before = rec.get("health_before") or {}
            deltas = {k: round(after[k] - before[k], 4) for k in after
                      if after.get(k) is not None and before.get(k) is not None}
            with self._lock:
                rec["health_after"] = after
                rec["health_delta"] = deltas
                rec["verified_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def record_maintenance(self, action_id: str, *, repaired: bool | None = None,
                           by: str = "", note: str = "",
                           health_before: dict | None = None) -> dict:
        """Record completed maintenance. It is applied on the next tick.

        Queued rather than applied here, because this runs on a request thread
        while the engine, the health trend and the remaining-life filter belong
        to the tick loop. Changed underneath a tick, that tick would see a
        half-repaired engine.

        `repaired` matters only for the two inspections (A5, A6), which restore
        nothing unless parts were replaced; it defaults to False for them and
        True for every other action.
        """
        actions = {a["id"]: a for a in config.load_thresholds()["advisory"]["actions"]}
        if action_id not in actions:
            raise ValueError(f"unknown maintenance action {action_id!r}")
        if repaired is None:
            repaired = action_id not in self.veng.degradation.INSPECTIONS
        rec = {
            "action_id": action_id,
            "name": str(actions[action_id]["name"]),
            "repaired": bool(repaired),
            "by": by,
            "note": note,
            "recorded_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "queued",
        }
        if health_before:
            # Work done while this aircraft was not on the ground station: the
            # "before" is its last assessed condition, kept by the squadron log.
            rec["_health_before"] = dict(health_before)
        with self._lock:
            self._maintenance_pending.append(rec)
        return dict(rec)

    def _apply_maintenance(self) -> None:
        """Apply the maintenance recorded since the last tick, on the tick thread.

        What resets depends on what the work changed. A job that restores
        nothing -- an inspection with no parts replaced -- restarts nothing,
        because the degradation it found is still there and its trend is still
        the evidence. A job that restores the engine restarts the composite
        health trend, the remaining-life filter and the network's window, and
        the per-fault trend of each fault the work removed: a slope fitted
        across a repair describes neither the engine before it nor after it.
        """
        with self._lock:
            pending, self._maintenance_pending = self._maintenance_pending, []
        for rec in pending:
            aid = rec["action_id"]
            deg = self.veng.degradation
            done = deg.perform_maintenance(aid, repaired=rec["repaired"])
            md, hist = self.state.metadata, self.state.history
            now = datetime.now(UTC)
            md.last_maintenance_date = now
            if aid in ("A1", "A7"):
                # The oil change is part of the 100 h check the clock counts to.
                hist.hours_since_inspection = 0.0
            if aid == "A7":
                md.hours_at_last_overhaul = md.total_flight_hours
                md.last_overhaul_date = now
                self._overhaul_engine_hours = self.veng.flight_hours
                # The failure-probability latch described the engine before its
                # overhaul; it must not hold the overhauled one on the ground.
                self.advisory._p_fail_tripped = False
            affects = self.MAINTENANCE_AFFECTS.get(aid, ("chi",))
            health_before = self._health_reading(affects)
            given = rec.pop("_health_before", None)
            if given and all(v is None for v in health_before.values()):
                health_before = {k: given.get(k) for k in affects}
            restarted: list[str] = []
            if done["restored"] or done["faults_removed"]:
                self.health.restart_trend()
                self.rul.restart()
                self.rul_net.reset()
                modes = (list(rf.INDICATORS) if aid == "A7"
                         else [str(m) for m in deg.MAINTENANCE_REMOVES[aid]])
                self.fault_rul.restart(modes)
                restarted = ["composite health", "remaining life", *modes]
            rec.update(
                status="applied",
                applied_flight_hours=round(self.veng.flight_hours, 3),
                restored=done["restored"],
                faults_removed=done["faults_removed"],
                trends_restarted=restarted,
                affects=list(affects),
                health_before=health_before,
            )
            with self._lock:
                self._maintenance_log.append(rec)
                if done["faults_removed"]:
                    self._injected = [f for f in self._injected
                                      if f["mode"] not in done["faults_removed"]]
            _log.info("maintenance applied", extra={
                "action_id": aid, "restored": done["restored"],
                "faults_removed": done["faults_removed"]})

    def acknowledge(self) -> None:
        """Push-to-reset both master annunciators (MIL-STD-411F 5.2.7).

        The rule engine keeps time on the TELEMETRY clock (`tel.t_s`), so the
        reset is stamped on that clock too. Called with no argument, as it was,
        `reset_master_warning` raised TypeError on every press: the console
        ignored the failed request and the lamp kept flashing (HMI-01). Master
        caution was never reset at all.
        """
        now = float(getattr(self.ingest.telemetry, "t_s", 0.0) or 0.0)
        with self._lock:
            self.rules.reset_master_warning(now)
            self.rules.reset_master_caution(now)

    # ------------------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            began = time.perf_counter()
            try:
                self._tick()
            except Exception as exc:
                # A SINGLE bad tick must not kill the engine; a PERSISTENT
                # failure must not be silent. The previous version of this
                # handler did the first and not the second -- it stored the
                # message in a snapshot field and carried on, with no log and
                # no counter. When DEV-149 made every tick raise, the twin
                # froze on stale values, `/api/healthz` went on reporting
                # `{"ok": true}`, and the only evidence anywhere was a string
                # nobody was reading. This line's comment used to read
                # "keep the demo alive", which is exactly what it did.
                self._consecutive_failures += 1
                self._total_failures += 1
                # Log the FIRST failure with a full traceback, then throttle:
                # a loop failing many times a second must not also write a
                # traceback each time to the log it is meant to be found in.
                if self._consecutive_failures == 1:
                    _log.exception(
                        "tick failed",
                        extra={"tick": self._ticks, "consecutive": 1},
                    )
                elif self._consecutive_failures == _TICK_FAILURE_LIMIT:
                    _log.error(
                        "tick has failed %d times running; the twin is "
                        "DEGRADED and its readings are stale",
                        self._consecutive_failures,
                        extra={"tick": self._ticks,
                               "consecutive": self._consecutive_failures,
                               "error": f"{type(exc).__name__}: {exc}"},
                    )
                with self._lock:
                    self._snapshot.pipeline["error"] = f"{type(exc).__name__}: {exc}"
                    self._snapshot.pipeline["consecutive_failures"] = \
                        self._consecutive_failures
                    self._snapshot.pipeline["total_failures"] = self._total_failures
                    # The flag /api/healthz reads. Past the limit the twin is
                    # not merely "erroring" -- it is no longer a live picture
                    # of the engine and must stop presenting itself as one.
                    self._snapshot.pipeline["degraded"] = (
                        self._consecutive_failures >= _TICK_FAILURE_LIMIT
                    )
            else:
                if self._consecutive_failures:
                    _log.info(
                        "tick recovered after %d consecutive failures",
                        self._consecutive_failures,
                        extra={"tick": self._ticks},
                    )
                self._consecutive_failures = 0
                with self._lock:
                    self._snapshot.pipeline["error"] = None
                    self._snapshot.pipeline["consecutive_failures"] = 0
                    self._snapshot.pipeline["degraded"] = False
                # Observers see only COMPLETE, successful snapshots -- a
                # recorder must never capture a half-updated tick. Isolated,
                # because a recorder fault is not an ENGINE fault and must not
                # trip the consecutive-failure escalation above.
                if self._on_tick is not None:
                    try:
                        self._on_tick(self.snapshot())
                    except Exception:
                        _log.exception("tick observer failed")
                if self._sortie_end_pending:
                    self._sortie_end_pending = False
                    self._close_sortie("complete")
            elapsed = time.perf_counter() - began
            self._latencies.append(elapsed * 1000.0)
            if len(self._latencies) > 600:
                self._latencies = self._latencies[-600:]
            sleep = max(0.0, self.dt / self.speed - elapsed)
            self._stop.wait(sleep)

    @property
    def _in_distribution(self) -> bool:
        """False only when the check ran and said the sample is unfamiliar."""
        return self._ood_verdict is None or self._ood_verdict.inside

    def _fault_indicators(self, res, phase) -> dict:
        """The four fault indicators that are measured but were never computed.

        Each comes from a signal this pipeline already holds; none is a
        stand-in. A window too short to judge returns None, which the forecast
        reports as "no data" rather than as a healthy reading. The statistical
        three are judged in stabilised cruise only, because a climb or a
        throttle change moves every residual and is not a fault.

          misfire      share of recent samples in which one cylinder's EGT
                       stands well below the other three (config Method B: a
                       misfiring cylinder runs cold).
          combustion   scatter of the EGT residual -- measured minus the
                       twin's prediction -- over the last minute.
          drift        recent variance of each channel's residual against its
                       own earlier variance this flight; the worst channel.
          vibration    strongest bearing-defect order in the latest order
                       analysis, relative to the envelope floor -- the quantity
                       oa.diagnose() names a defect from.
        """
        import numpy as _np
        from layer2_physics.engine_sim import PHASE_CRUISE

        out = {"misfire_rate_pct": None, "egt_scatter_c": None,
               "residual_variance_ratio": None, "vibration_peak_ratio": None}
        cruising = phase == PHASE_CRUISE

        if cruising:
            t = self.ingest.telemetry
            egts = [t.get(f"egt_{i}") for i in (1, 2, 3, 4)]
            if all(e is not None for e in egts):
                hit = False
                for i, e in enumerate(egts):
                    others = [x for j, x in enumerate(egts) if j != i]
                    mu = float(_np.mean(others))
                    sigma = max(float(_np.std(others)), 10.0)
                    if mu - float(e) > self._misfire_sigma * sigma:
                        hit = True
                        break
                self._misfire_hits.append(1.0 if hit else 0.0)
            if len(self._misfire_hits) >= 30:
                out["misfire_rate_pct"] = 100.0 * float(_np.mean(self._misfire_hits))

            if res.egt.usable and res.egt.delta is not None:
                self._egt_resid.append(float(res.egt.delta))
            mp = res.manifold_pressure
            if mp.usable and mp.delta is not None and mp.predicted:
                self._boost_drop.append(-float(mp.delta) / float(mp.predicted))
            # A worn turbocharger is compensated by the closed-loop boost
            # control: below its limit the wastegate closes further and the
            # boost is held, so boost drop alone sees nothing until the
            # turbocharger runs out of capability (review PHY-07). How much MORE
            # closed the wastegate is than the as-new twin's at the same point is
            # the early sign. Only where the twin's wastegate still has
            # authority: at the limit both are shut and the difference is empty.
            twin_out = self.shadow.last_output
            wg_meas = t.get("wastegate_pct")
            if twin_out is not None and wg_meas is not None:
                wg_twin = 100.0 * float(twin_out.turbo_state.wastegate_fraction)
                if wg_twin > 5.0:
                    self._wg_closure.append(wg_twin - float(wg_meas))
            if len(self._egt_resid) >= 30:
                out["egt_scatter_c"] = float(_np.std(self._egt_resid))

            worst = None
            for name, buf in self._resid_windows.items():
                one = getattr(res, name)
                if one.usable and one.delta is not None:
                    buf.append(float(one.delta))
                if len(buf) < 180:
                    continue
                arr = _np.array(buf, dtype=float)
                recent = float(_np.var(arr[-60:]))
                blocks = [float(_np.var(arr[k:k + 60]))
                          for k in range(0, len(arr) - 60, 60)]
                base = max(float(_np.median(blocks)), 1e-3)
                ratio = recent / base
                worst = ratio if worst is None else max(worst, ratio)
            out["residual_variance_ratio"] = worst

        # Cruise only, like the other three: a climb moves every order and the
        # healthy engine read "trending" from take-off onward (RT-06).
        if cruising and self._order is not None and self._order.peaks:
            bearing = [self._order.peaks.get(k) for k in ("BPFO", "BPFI", "BSF", "FTF")]
            bearing = [float(b) for b in bearing if b is not None]
            if bearing:
                out["vibration_peak_ratio"] = max(bearing)
        return out

    def _order_peak(self, name: str) -> float | None:
        """One bearing-defect order from the latest order analysis, if there is one."""
        order = self._order
        if order is None or not order.peaks:
            return None
        value = order.peaks.get(name)
        return None if value is None else float(value)

    def _actuator_residual(self, channel: str, predicted: float | None) -> float | None:
        """Measured actuator position minus the as-new twin's at this point.

        Both flaps and the wastegate move with power and ambient, so the
        position alone says little; the difference from what an as-new engine
        would need is the whole signal.
        """
        measured = self.ingest.telemetry.get(channel)
        if measured is None or predicted is None:
            return None
        return float(measured) - float(predicted)

    def _lane_delta(self, channel: str) -> float | None:
        ch = self.ingest.telemetry.channels.get(channel)
        return None if ch is None or ch.lane_delta is None else float(ch.lane_delta)

    def _scatter(self, window, value: float | None) -> float | None:
        """Scatter of one signal over the last minute, all phases.

        Matched to `features.rolling_scatter`, which uses the same 60 s window
        on the training data. Defined in time rather than samples because the
        fleet steps at 1 s and this loop at `self.dt`.
        """
        import numpy as _np

        if value is not None:
            window.append(float(value))
        need = max(5, int(round(60.0 / max(self.dt, 1e-6))) // 6)
        if len(window) < need:
            return None
        return float(_np.std(list(window), ddof=1))

    def _egt_scatter(self, residual: float | None) -> float | None:
        """Scatter of the exhaust residual. Kept for the health extras below."""
        return self._scatter(self._egt_scatter_window, residual)

    def _serve_rul(self, r, res, batt) -> rs.ServedRul:
        """One sample into the trained network, keyed by DATASET column name.

        The names on the left are the training fleet's column names and the
        expressions on the right are where the twin keeps the same quantity --
        the twin GROUPS its readings (`cht.spread`, `timing.injector_duty_pct`)
        where the fleet flattens them. That mismatch is exactly what put NULL
        into sixteen of thirty-eight columns in DEV-167, so it is written out
        explicitly here rather than resolved by matching names.

        Residuals go in RAW: `LstmRulServer` baselines them, because the
        baseline is part of the feature definition and a caller that has to
        remember it is a caller that will one day forget.
        """
        def v(x):
            return x.value if hasattr(x, "value") else x

        def d(residual):
            return getattr(residual, "delta", None)

        twin_now = self.shadow.last_output

        values = {
            # PRD7
            "rpm": v(r.rpm),
            "cht_max": v(r.cht_max),
            "egt_max": v(r.egt_max),
            "oil_pressure": v(r.oil_pressure),
            "oil_temperature": v(r.oil_temperature),
            "fuel_flow": v(r.fuel_flow),
            "vibration_rms_total": r.vibration.rms_total,
            # residuals, un-baselined by design
            "res_cht": d(res.cht),
            "res_coolant": d(res.coolant),
            "res_egt": d(res.egt),
            "res_oil_pressure": d(res.oil_pressure),
            "res_oil_temperature": d(res.oil_temperature),
            "res_fuel_flow": d(res.fuel_flow),
            "res_manifold_pressure": d(res.manifold_pressure),
            # derived
            "cht_minus_coolant": res.cht_minus_coolant,
            "cht_spread": v(r.cht.spread),
            "egt_spread": v(r.egt.spread),
            "injection_deviation_max": v(r.timing.injection_deviation_max),
            "knock_retard_deg": v(r.timing.knock_retard_deg),
            # UNITS. The twin carries a PERCENT (`injector_duty_pct`, ~13.5);
            # the training column `injector_duty` is a FRACTION (0.221-0.651,
            # centre 0.35, scale 0.25). Fed the percent unconverted, this one
            # feature normalises to ~52 against a training range of about 0.3
            # and swamps the other twenty-two. The same path table in
            # `layer4_core/recorder.py` maps the same percent onto the same
            # fraction column. That one is now fixed too, and pinned by
            # test_injector_duty_is_recorded_as_a_fraction_not_a_percent,
            # which fails with values of 9.5 to 52.5 if the conversion is
            # removed.
            "injector_duty": _pct_to_fraction(v(r.timing.injector_duty_pct)),
            "vibration_kurtosis": v(r.vibration.kurtosis),
            # ACTUATOR AUTHORITY, and what it is against the as-new twin. On a
            # FADEC engine the degradation is spent authority before it is a
            # changed reading, and until now no model could see either actuator.
            "wastegate_pct": self.ingest.telemetry.get("wastegate_pct"),
            "cooling_flap_pct": self.ingest.telemetry.get("cooling_flap_pct"),
            "res_wastegate": self._actuator_residual(
                "wastegate_pct",
                None if twin_now is None else 100.0 * twin_now.turbo_state.wastegate_fraction),
            "res_cooling_flap": self._actuator_residual(
                "cooling_flap_pct",
                None if twin_now is None else 100.0 * twin_now.cooling_flap_fraction),
            # What the two FADEC lanes disagree by, on the two channels both
            # lanes measure. A transducer drifting on one lane moves this.
            "rpm_lane_delta": self._lane_delta("rpm"),
            "map_lane_delta": self._lane_delta("manifold_pressure"),
            # Scatter of the exhaust residual over the last minute, the same
            # quantity and the same window the training data carries.
            "egt_scatter": self._egt_scatter(d(res.egt)),
            # The same bearing orders the fleet now carries, from this twin's
            # own order analysis (recomputed on its own cadence, like the fleet).
            **{f"vib_{k.lower()}": self._order_peak(k)
               for k in ("BPFO", "BPFI", "BSF", "FTF")},
        }
        # The survival head needs the same 23 channels this dict already
        # holds, plus the health estimate, which is not known until the trend
        # is computed further down the tick. Kept here rather than rebuilt so
        # the two paths cannot drift apart channel by channel.
        self._sortie_values = dict(values)
        # The residual reference learns from STEADY LEVEL FLIGHT only -- the
        # condition that dominates the whole-life median training used. Level
        # is judged from the altitude the aircraft reports: within 50 ft over
        # the last 30 s of engine time (DEV-254).
        _alt = self.ingest.telemetry.get("altitude_ft")
        _now = self.veng.t_s
        if _alt is not None:
            self._alt_trace.append((_now, float(_alt)))
        while self._alt_trace and _now - self._alt_trace[0][0] > 30.0:
            self._alt_trace.popleft()
        _level = (len(self._alt_trace) >= 2 and _now - self._alt_trace[0][0] >= 25.0
                  and abs(self._alt_trace[-1][1] - self._alt_trace[0][1]) <= 50.0)
        try:
            return self.rul_net.observe(values, self.veng.flight_hours,
                                        learn_reference=_level)
        except Exception:
            # A diagnostic that fails must not stop the engine, and must not
            # silently become "no estimate" either -- the physics path below
            # still answers, and this is logged with a traceback the first time.
            _log.exception("RUL network inference failed")
            return rs.ServedRul(source="none", reason="inference failed")

    def request_sortie_restart(self) -> None:
        """Fly the sortie again from the beginning, with the engine stopped.

        Called when an operator signs in. The complaint this answers: the
        station began its sortie when the SERVER started, so by the time anyone
        had logged in the aircraft was several minutes into the climb and every
        value was already at its cruise figure. Nobody ever saw the engine
        start, because it had started while the login page was on screen.

        Safe to call from a request handler -- it only raises a flag; see
        `_restart_requested`. The engine's WEAR is not reset, only the flight:
        the same worn engine flies the sortie again. See
        `VirtualEngine.restart_sortie`.
        """
        self._restart_requested = True

    # ------------------------------------------------------------------
    # The operator's commands. A squadron's engine is started by a person, for
    # a reason, and waits for them: the station no longer flies a sortie by
    # itself because somebody opened a browser.
    # ------------------------------------------------------------------
    # Engine time at the warm-up hold before an engine that has not been given
    # launch clearance is shut down.
    WARMUP_HOLD_LIMIT_S = 1800.0

    def begin_profile(self, phases: list, *, kind: str, env_condition=None,
                      label: str = "") -> None:
        """Fly ``phases`` from a cold, stopped engine, starting next tick.

        ``kind`` is what this run of the engine is for -- "mission",
        "ground_run" or "parked" -- and is reported in the sortie status so the
        console and the squadron log can tell a flight from a ground run.
        Before the twin thread has started, it is applied at once.
        """
        pending = (list(phases), str(kind), env_condition, str(label))
        if self._thread is None:
            self._apply_profile(pending, closing=False)
            return
        with self._lock:
            self._pending_profile = pending
            self._restart_requested = True

    def park(self) -> None:
        """On the ground, engine stopped, until somebody starts it."""
        from layer2_physics.engine_sim import parked_profile
        self.begin_profile(parked_profile(), kind="parked")

    def launch(self) -> bool:
        """Launch clearance: leave the warm-up hold. False if not holding."""
        if not self.veng.current_phase().hold:
            return False
        with self._lock:
            self._pending_ops.append(self.veng.release_hold)
        return True

    def rtb(self) -> bool:
        """Recall: go to the descent from wherever the flight is."""
        name = self.veng.current_phase().name
        if name not in ("TAKEOFF", "CLIMB", "CRUISE"):
            return False
        with self._lock:
            self._pending_ops.append(lambda: self.veng.jump_to("DESCENT"))
        return True

    def abort_on_ground(self) -> bool:
        """Shut down without flying: cool down at idle, then stop."""
        from layer2_physics.engine_sim import HOLD_PHASE
        name = self.veng.current_phase().name
        if name not in ("STARTUP", HOLD_PHASE, "TAXI", "RUN-UP"):
            return False
        with self._lock:
            self._pending_ops.append(lambda: self.veng.jump_to("COOL-DOWN"))
        return True

    def _apply_profile(self, pending: tuple, *, closing: bool = True) -> None:
        phases, kind, env, label = pending
        if closing and self._sortie_state == "running":
            self._close_sortie("interrupted")
        if env is not None:
            self.veng.env_condition = env
        self.veng.set_profile(phases)
        self._profile_kind, self._profile_label = kind, label
        self._begin_sortie()
        if kind == "parked":
            self._sortie_state = "parked"
        self.veng.restart_sortie()

    def _regime_change(self, frame) -> None:
        """Start span-fitted quantities again when the operating point moves.

        The fault forecaster fitted a line from the take-off through the climb
        into the cruise and extended a change of THROTTLE as wear: a healthy
        engine half an hour old was forecast to need action for overheating in
        0 h. And the survival head -- trained on sorties of 50 readings at ONE
        settled point, rpm scatter 4 -- was handed a vector spanning climb and
        cruise, whose spread it read as instability: failure risk 1 % in the
        climb, 32 % one minute into the cruise, on the same healthy engine.

        A regime is the flight phase and the lever to within 10 %. Only
        assessed samples reach either, so a transition between regimes never
        does; when an assessed regime differs from the last, both start again.
        The survival sortie is DISCARDED, not closed, so the change does not
        become a "rate" either.
        """
        if not self._assessed_now:
            return
        thr = getattr(frame, "throttle_pct", None)
        regime = (getattr(frame, "flight_phase", None),
                  None if thr is None else int(round(float(thr) / 10.0)))
        if regime == self._fault_regime:
            return
        if self._fault_regime is not None:
            self.fault_rul.restart(list(rf.INDICATORS))
            self.sortie.discard()
        self._fault_regime = regime

    def _close_sortie(self, reason: str) -> None:
        """Hand the flight just ended to whoever keeps the station's history."""
        # The namer's history takes the flight whether or not anyone records
        # it; closing an empty flight is a no-op, so a second call is harmless.
        self.namer_history.close_sortie()
        if self._sortie_recorded or self.on_sortie_end is None:
            return
        try:
            self.on_sortie_end(self.snapshot(), reason)
            self._sortie_recorded = True
        except Exception:
            # Bookkeeping must not stop the engine -- nor be silent.
            _log.exception("could not record the flight that just ended")
        self.save_engine_life()

    def _begin_sortie(self) -> None:
        """A new flight: a fresh flight record and a fresh sortie-long series.

        The record keeps the FIRST stabilised cruise datum of a flight, the one
        the trend across flights compares. Carried from flight to flight, the
        first flight's datum was the only one ever kept -- every later flight
        was reported against it and none of them was ever captured.
        """
        self.record = fr.FlightRecord()
        self._flight_series = {}
        self._flight_stride = 1
        self._flight_seen = 0
        # The flight's own start, for the report's flight window: the record
        # begins here, and "started" used to be when the station was switched
        # on, hours before a sortie flown later in the day.
        self._started_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.sortie.end_sortie()
        self._sortie_state = "running"
        self._sortie_started_t = float(self.veng.t_s)
        self._sortie_ended_t = None
        self._sortie_recorded = False
        self._sortie_end_pending = False

    def _sortie_status(self, t_s: float) -> dict:
        end = self._sortie_ended_t
        ph = self.veng.current_phase()
        return {
            "state": self._sortie_state,
            "kind": self._profile_kind,
            "label": self._profile_label,
            # The PROFILE's phase by name: WARM-UP, RUN-UP, COOL-DOWN and
            # PARKED all share the bus's GROUND code.
            "phase": ph.name,
            "phase_elapsed_s": round(float(self.veng._phase_t), 1),
            "holding": bool(ph.hold and not getattr(self.veng, "_hold_released", False)),
            "started_t_s": round(self._sortie_started_t, 1),
            "ended_t_s": None if end is None else round(end, 1),
            "flight_time_s": round((end if end is not None else t_s)
                                   - self._sortie_started_t, 1),
            "recorded": self._sortie_recorded,
        }

    def _twin_compare(self) -> dict[str, dict]:
        """Each strip reading against what the twin says it should be now.

        expected = the as-new engine at this operating point (the shadow
        model's prediction) + this engine's own build offset. The deviation is
        graded against thresholds.yaml `twin_compare` -- the same figures the
        fault definitions use -- and only while the engine is warm, loaded and
        steady: in warm-up and transients the difference is the operating
        point, not the engine, and a symbol that flickers through every
        take-off is one an operator learns to ignore.
        """
        cfg = config.load_thresholds().get("twin_compare") or {}
        chans = cfg.get("channels") or {}
        alpha = min(1.0, float(self.dt) / max(float(cfg.get("smoothing_s", 10.0)), 1e-6))
        res = self.state.residuals
        rpm = self.state.reported.rpm.value if self.state.reported.rpm.usable else None
        graded_now = bool(getattr(self, "_assessed_now", False))
        ema = self.__dict__.setdefault("_twin_ema", {})
        out: dict[str, dict] = {}
        # A stopped engine has no twin to be compared with: the shadow model
        # carries on predicting the running engine it last saw, and a parked
        # aircraft read "twin 574 degC, -523 K". Nothing is shown, not that.
        running = rpm is not None and rpm >= 500.0
        for key, c in chans.items():
            pair = self._twin_pair(c, res) if running else None
            if pair is None:
                ema.pop(key, None)
                out[key] = {"available": False}
                continue
            measured, expected = pair
            dev = measured - expected
            min_rpm = c.get("min_rpm")
            graded = graded_now and (min_rpm is None or (rpm is not None and rpm >= float(min_rpm)))
            # The difference SHOWN is exactly now minus twin, so the three
            # numbers on a row always add up. The GRADE is taken on its ~10 s
            # average, so one noisy sample does not flip a row to "drifting".
            if graded:
                ema[key] = dev if key not in ema else ema[key] + alpha * (dev - ema[key])
                judged = ema[key]
            else:
                ema.pop(key, None)
                judged = dev
            sense = c.get("sense", "both")
            bad = (judged if sense == "above" else -judged if sense == "below" else abs(judged))
            if c.get("relative"):
                # Graded as a fraction of what the twin expects (fuel flow,
                # vibration), shown in the reading's own unit.
                bad = bad / abs(expected) if abs(expected) > 1e-9 else 0.0
            level = None
            if graded:
                level = ("fault" if bad >= float(c["fault"])
                         else "degraded" if bad >= float(c["degraded"]) else "normal")
            digits = 3 if c.get("unit") == "bar" else 2 if c.get("unit") in ("V", "L/h", "m/s2") else 1
            out[key] = {
                "available": True,
                "measured": round(measured, digits),
                "expected": round(expected, digits),
                "deviation": round(round(measured, digits) - round(expected, digits), digits),
                "unit": c.get("unit", ""),
                "graded": graded,
                "level": level,
                "offset_known": bool(self.rul_net.baseline.ready),
            }
        return out

    def _twin_pair(self, c: dict, res) -> tuple[float, float] | None:
        """(measured, what the twin expects) for one twin_compare channel.

        residual  the shadow's prediction plus this engine's build offset
        shadow    a shadow output (times the installation's gain) the residual
                  set does not carry: vibration, the bus
        command   injection timing: the FADEC's command is its twin, the worst
                  cylinder's measured timing is compared against it
        """
        kind = c.get("kind", "residual")
        if kind == "residual":
            r = getattr(res, c["residual"], None)
            if r is None or not r.usable or r.delta is None or r.predicted is None:
                return None
            offset = float(self.rul_net.baseline.offset(c["baseline"]))
            return float(r.predicted) + float(r.delta), float(r.predicted) + offset
        if kind == "shadow":
            o = self.shadow.last_output
            node = self.state.reported
            for part in c["measured"].split("."):
                node = getattr(node, part, None)
            m = node.value if hasattr(node, "usable") and node.usable else (
                node if isinstance(node, (int, float)) else None)
            if o is None or m is None:
                return None
            return float(m), float(getattr(o, c["output"])) * float(c.get("gain", 1.0))
        if kind == "command":
            t = self.state.reported.timing
            cmd, dev = t.injection_commanded, t.injection_deviation_max
            if not cmd.usable or cmd.value is None or dev is None:
                return None
            return float(cmd.value) + float(dev), float(cmd.value)
        return None

    def _assessable(self, t_s: float, rpm: float | None, oil_c: float | None) -> bool:
        """Is the engine at a condition its health can be judged at?

        Warm (oil at the take-off minimum [OM s2.1]) and loaded (above the
        rpm the manufacturer's oil-pressure minimum changes at), continuously
        for `settle_s` -- configured under health.assessment, with the reasons.
        The short windows are emptied as the engine enters the gate, so rpm
        stability and the oil/rpm correlation are taken over warm running only.
        """
        warm = (rpm is not None and oil_c is not None
                and rpm >= self._assess_min_rpm
                and oil_c >= self._assess_min_oil_c)
        if not warm:
            self._assess_since = None
            self._assess_rpm.clear()
            return False
        if self._assess_since is None:
            self._assess_since = t_s
            self.health.new_flight()
        # AND STEADY. ECTM takes its points where speed has held within a small
        # band for a set time. Without this the gate let in the change from
        # cruise to descent, the statistical tier scored that transient 0.92,
        # and the held assessment then kept ADVISORY on through the whole
        # descent, landing and shutdown.
        self._assess_rpm.append((t_s, rpm))
        while self._assess_rpm and t_s - self._assess_rpm[0][0] > self._assess_settle_s:
            self._assess_rpm.popleft()
        speeds = [r for _, r in self._assess_rpm]
        # Judged on a ~2 s rolling mean, not on single samples: the rpm
        # instrument's own scatter (about 1 % at a ground run-up) put single
        # readings outside a 3 % band on an engine held at one speed, so a
        # ground run was often never judged at all. A real transient -- a
        # power change, cruise to descent -- is several percent and lasts far
        # longer than 2 s, so it still keeps the gate shut.
        k = max(1, min(len(speeds), int(round(2.0 / max(self.dt, 1e-3)))))
        if len(speeds) >= k:
            csum = np.cumsum([0.0, *speeds])
            speeds = list((csum[k:] - csum[:-k]) / k)
        steady = (max(speeds) - min(speeds)) <= (
            self._assess_rpm_band * sum(speeds) / len(speeds))
        return steady and t_s - self._assess_since >= self._assess_settle_s

    def _health_update(self, r, res, batt) -> hl.HealthSnapshot:
        def v(m):
            return m.value if m.usable else None
        return self.health.update({
            "rpm": v(r.rpm), "cht_max": v(r.cht_max), "cht_spread": r.cht.spread,
            "coolant_temperature": v(r.coolant_temperature),
            "egt_spread": r.egt.spread, "oil_pressure": v(r.oil_pressure),
            "oil_temperature": v(r.oil_temperature), "fuel_flow": v(r.fuel_flow),
            "vibration_rms_total": r.vibration.rms_total,
            "vibration_kurtosis": v(r.vibration.kurtosis),
            "battery_voltage": v(r.electrical.bus_voltage),
            "alternator_current": v(r.electrical.alternator_current),
            "battery_soh": batt.soh,
            "res_cht": res.cht.delta, "res_coolant": res.coolant.delta,
            "res_egt": res.egt.delta, "res_oil_pressure": res.oil_pressure.delta,
            "res_oil_temperature": res.oil_temperature.delta,
            "res_fuel_flow": res.fuel_flow.delta,
            "oil_pressure_predicted": self.state.simulated.oil_pressure_predicted,
            "fuel_flow_predicted": self.state.simulated.fuel_flow_predicted,
            "egt_predicted": self.state.simulated.egt_predicted,
        })

    def _assessment_status(self, t_s: float) -> dict:
        """What the health figures on screen are: judged now, held, or none yet."""
        gate = (f"judged with the oil at or above {self._assess_min_oil_c:.0f} °C "
                f"and the engine above {self._assess_min_rpm:.0f} rpm")
        if getattr(self, "_assessed_now", False):
            return {"state": "live", "age_s": 0.0, "reason": gate}
        if self._held is not None:
            return {"state": "held",
                    "age_s": round(max(0.0, t_s - self._held["t_s"]), 1),
                    "reason": "engine not warm and loaded: last assessment held; "
                              + gate}
        return {"state": "assessing", "age_s": None,
                "reason": "engine not yet warm: condition not assessed; " + gate}

    def _tick(self) -> None:
        # Maintenance recorded since the last tick goes in before the engine
        # steps, so the whole of this tick sees one engine: the repaired one.
        self._apply_maintenance()
        self._verify_maintenance()
        with self._lock:
            ops, self._pending_ops = self._pending_ops, []
        for op in ops:
            op()
        if self._restart_requested:
            self._restart_requested = False
            with self._lock:
                pending, self._pending_profile = self._pending_profile, None
            if pending is not None:
                self._apply_profile(pending)
            else:
                # A flight cut short is still a flight: its cruise datum, if it
                # reached one, is as good as a completed flight's.
                if self._sortie_state == "running":
                    self._close_sortie("interrupted")
                self._begin_sortie()
                self.veng.restart_sortie()
            # A NEW RUN OF THE ENGINE, SO NOTHING JUDGED ON THE LAST ONE CARRIES
            # OVER AS EVIDENCE. Every check that compares a reading with the
            # ones before it -- rate, frozen run, response window, rpm
            # stability -- would otherwise compare the cruise with the starter.
            # The engine's wear, trend and last condition assessment do carry
            # over: they are about the engine, not about this run of it.
            self.ingest.new_power_up()
            # The as-new twin re-seeds its temperatures from the first running
            # frame, as it did at first start. Kept, it cooled down from the
            # last cruise while the real engine warmed up from cold, and the
            # stuck-sensor check read the difference as a dead head probe.
            self.shadow.reset()
            self.response.reset()
            self.health.new_flight()
            self._assess_since = None
            self._assess_rpm.clear()
        # NOBODY IDLES AN ENGINE ON THE GROUND FOR HOURS. A start that is
        # never given launch clearance is shut down after the hold limit, as a
        # crew would, rather than accumulating idle hours indefinitely.
        _ph = self.veng.current_phase()
        if (_ph.hold and not getattr(self.veng, "_hold_released", False)
                and self.veng._phase_t > self.WARMUP_HOLD_LIMIT_S):
            _log.warning("no launch clearance within the hold limit: engine shut down",
                         extra={"held_s": round(self.veng._phase_t)})
            self.veng.jump_to("COOL-DOWN")
        frame = self.veng.step(self.dt)
        if (self._sortie_state == "running"
                and self.veng.current_phase().name == "SHUTDOWN"
                and self.veng.model.stopped):
            self._sortie_state = "complete"
            self._sortie_ended_t = float(frame.t_s)
            self.sortie.end_sortie()
            # Written after this tick's snapshot exists, in the loop, so the
            # record carries the flight's final state.
            self._sortie_end_pending = True

        # --- envelope order analysis, on a cadence -------------------------
        # PS section B asks for vibration SIGNATURES and section C for
        # abnormal vibration PATTERNS. RMS and kurtosis say a bearing is
        # rough; only the order spectrum says which race. See
        # layer1_edge/order_analysis.py for why orders rather than Hz.
        if self._ticks - self._order_tick >= _ORDER_EVERY_TICKS:
            self._order_tick = self._ticks
            try:
                rpm_now = float(frame.rpm)
                if rpm_now > 300.0:
                    wave = self.veng.vibration_waveform(
                        duration_s=oa.required_duration_s(rpm_now), fs=10_000.0
                    )
                    self._order = oa.analyse(
                        wave, 10_000.0, rpm_now, self.veng._engine
                    )
                    found = oa.diagnose(self._order)
                    if found:
                        _log.info("order analysis finding",
                                  extra={"rpm": round(rpm_now),
                                         "findings": found,
                                         "band_hz": self._order.band_hz})
            except Exception:
                # A diagnostic that fails must not stop the engine. It has its
                # own guard so it cannot trip the consecutive-failure
                # escalation, which is about the PIPELINE, not an analysis.
                _log.exception("order analysis failed")
                self._order = None
        self.sim.send_frame(frame)
        tel = self.ingest.poll(now=frame.t_s)
        derived = self.ingest.derived()
        # The instrument offsets measured on the PREVIOUS tick: the rules run
        # before the twin has this tick's prediction, and one tick of lag on a
        # slowly-estimated offset costs nothing.
        derived.update(self.bias.indicators())
        alerts = self.rules.evaluate(tel, derived)
        pred = self.shadow.update(tel, self.dt)
        self.sync.sync(tel, derived=derived, physics=pred, alerts=alerts)
        # Judged against the twin's prediction, so after the sync. A sensor found
        # not responding is INVALID at the ingest from here on, which raises
        # SENSOR FAULT, until it follows the engine again.
        self.response.update(frame.t_s, self.state.simulated)
        self.bias.update(self.state.residuals)

        # Where the physics is running beyond the manufacturer's performance
        # table. Worked from what the aircraft measures -- engine speed,
        # pressure altitude, outside air temperature -- so a fielded twin can
        # say it as well as this one. Nothing is claimed while the model is not
        # running, because there is then no prediction to qualify.
        _sim = self.state.simulated
        _rpm, _alt, _oat = tel.get("rpm"), tel.get("altitude_ft"), tel.get("oat")
        _sim.outside_manufacturer_data = (
            list(om_table.outside_table(
                _rpm, _alt,
                _oat - (atmo.isa_temperature_k(_alt / atmo.FT_PER_M) - 273.15)))
            if self._has_om_table and _sim.model_available
            and None not in (_rpm, _alt, _oat)
            else []
        )

        # MAVLink EFI_STATUS to a ground station, when one is configured. It
        # carries validated channels only, so it goes out straight after
        # ingest and owes nothing to anything the twin estimates.
        if self.mavlink is not None:
            self.mavlink.maybe_send(tel)


        r = self.state.reported

        # The two fields TwinState has always declared and nothing ever set.
        # They come from the edge node's order analysis, not from a CAN
        # channel -- the 10 kHz waveform is not on the 10 Hz bus, which is
        # exactly what the comment beside their declaration says.
        if self._order is not None:
            r.vibration.dominant_frequency_hz = self._order.dominant_frequency_hz
            r.vibration.spectral_peaks = dict(self._order.peaks)
        res = self.state.residuals

        def v(m):
            return m.value if m.usable else None

        # ---- efficiency (PS section F) ---------------------------------
        #
        # SHAFT POWER IS NOT ON THE BUS. A UAV piston installation carries no
        # torque sensor, so brake power cannot be measured -- which is exactly
        # why a digital twin is the right instrument for this: the twin
        # estimates the quantity the aircraft cannot measure, from rpm,
        # manifold pressure and the engine's own performance map.
        #
        # The fuel flow is MEASURED and the power is ESTIMATED, so the BSFC
        # reported here is a hybrid figure. That is stated rather than hidden,
        # because an efficiency number whose provenance is unclear is one an
        # engineer cannot argue with.
        sim = self.state.simulated
        amb = self.veng._ambient
        rho_man = None
        if pred is not None and amb is not None:
            try:
                from layer2_physics.atmosphere import air_density
                rho_man = air_density(
                    pred.manifold_pressure_bar * 1e5,
                    pred.turbo_state.manifold_air_temp_k, 0.0,
                )
            except Exception:
                rho_man = None
        effi = self.efficiency.update(
            fuel_flow_lph=v(r.fuel_flow),
            power_kw=sim.power_predicted_kw,
            rpm=v(r.rpm),
            air_mass_flow_kg_s=(pred.air_mass_flow_kg_s if pred else None),
            inlet_density_kg_m3=rho_man,
            fuel_flow_predicted_lph=sim.fuel_flow_predicted,
            power_predicted_kw=sim.power_predicted_kw,
        )

        # Battery state of health -- only observable while the pack is
        # actually discharging, so this returns the last measurement plus its
        # age rather than a continuously-refreshed number.
        batt = self.battery.update(
            bus_voltage=v(r.electrical.bus_voltage),
            alternator_current=v(r.electrical.alternator_current),
            rpm=v(r.rpm),
            flight_hours=self.veng.flight_hours,
            battery_current=tel.get("battery_current"),
        )

        # ---- the engine's condition: judged warm and loaded, or held --------
        #
        # The health indices measure the engine against its healthy self at a
        # running condition. On the starter, at idle, and through the warm-up
        # the engine is not at that condition, and the indices said so as if
        # it were wear: a healthy engine read 0.80-0.88 on every start, its
        # subsystem bars went red, and after a restart it read 0.66 POOR --
        # while the remaining-life network, fed idle and warm-up samples it was
        # never trained on, swung 115 -> 390 -> 695 h inside two minutes.
        #
        # So the condition is judged only inside the gate (`_assessable`), and
        # outside it the last warm assessment is HELD -- published as held,
        # with its age -- which is what the engine's condition actually is:
        # nothing about the engine changed because it was shut down.
        assess = self._assessable(frame.t_s, v(r.rpm), v(r.oil_temperature))
        if not assess and self._held is not None:
            snap_health = self._held["health"]
        else:
            snap_health = self._health_update(r, res, batt)
        if assess:
            trend = self.health.track(snap_health.chi, self.veng.flight_hours)
            rul = self.rul.update(trend["chi_ema"], self.veng.flight_hours)
            # THE TRAINED NETWORK, WHICH NOTHING USED TO LOAD (DEV-191).
            #
            # Measured on the same held-out engines: physics RMSE 162.5 / R2
            # -0.396, network RMSE 113.9 / R2 +0.327. Physics still runs and
            # is still the fallback -- the network can only ADD a source here,
            # never remove one. It declines to answer until it has a full
            # window, and while it declines the served value is physics.
            served = self._serve_rul(r, res, batt)
            self._held = {"health": snap_health, "trend": trend, "rul": rul,
                          "served": served, "t_s": frame.t_s}
        elif self._held is not None:
            trend = self._held["trend"]
            rul = self._held["rul"]
            served = self._held["served"]
        else:
            # Never yet warm since the station started: there is no condition
            # to report, and none is invented. The indices above are computed
            # so the rest of the tick has numbers to run on, and the snapshot
            # withholds them from the operator (see `_assessment_status`).
            why = "engine not yet warm: condition not assessed"
            trend = {"chi_ema": snap_health.chi, "cusum": 0.0,
                     "onset_detected": 0.0, "baseline": None}
            rul = rp.RulEstimate(reason=why)
            served = rs.ServedRul(source="none", reason=why)
        self._assessed_now = assess
        # ONE OPERATING POINT AT A TIME, for everything fitted over a span:
        # the fault trends and the survival head's sortie vector. See
        # `_regime_change`.
        self._regime_change(frame)

        # The SMOOTHED index is what drives the band, the advisory and the
        # fused verdict -- PRD Part 2 s9.4 Method 1 says decisions are taken on
        # it, not on the raw sample. Fed the raw value, the advisory flipped
        # between INFO and ADVISORY every thirty seconds as the flight profile
        # changed throttle: CHI 0.743 -> 0.822 -> 0.791 -> 0.806 across four
        # consecutive observations of a steadily degrading engine. An advisory
        # that chatters is one an operator learns to ignore.
        chi_decision = float(trend["chi_ema"])
        self._chi_decision_now = chi_decision
        band, action = hl.band_for(chi_decision)

        # health_est is the smoothed index, which is what the head was trained
        # on -- `scripts/train_survival.py` feeds it `track(...)["chi_ema"]`.
        # Feeding the raw chi here would be a train/serve mismatch of exactly
        # the kind that produces a confident number meaning something else.
        survival = {"available": False, "reason": "no reading", "horizons": {}}
        # The row the network was just given: raw channels, BASELINED
        # residuals, and the structured residual signature. Taken from there
        # rather than rebuilt, because the baseline is stateful -- forming a
        # second one here would advance it twice per tick and quietly corrupt
        # the RUL path as well as this one.
        built = getattr(self.rul_net, "last_row", None)
        if built:
            row = dict(built)
            row[sf.HEALTH_COLUMN] = chi_decision
            # Only a row the network was given THIS tick, i.e. an assessed one.
            # Held, `last_row` is the last warm row, and observing it again on
            # every tick of the warm-up would weight the sortie's features with
            # hundreds of copies of one sample.
            if self._assessed_now:
                self.sortie.observe(row, self.veng.flight_hours)
            feats = self.sortie.features()
            if feats is not None and self.sortie.samples < self._sortie_min_samples:
                # The head was trained on 50 one-second readings taken at one
                # settled operating point (data/synthetic manifest: settle 25
                # s, record 50 s). Fewer than that is not the vector it knows.
                survival = {"available": False, "horizons": {},
                            "samples": self.sortie.samples,
                            "reason": (f"{self.sortie.samples} of "
                                       f"{self._sortie_min_samples} steady readings "
                                       f"at this operating point")}
            elif feats is not None:
                survival = self.survival.predict(feats)
                survival["samples"] = self.sortie.samples

        # BEFORE WEAR BEGINS THERE IS NO COUNT-DOWN TO REPORT. The network was
        # trained with remaining life capped at the prediction horizon: on a
        # healthy engine its right answer is "at least 400 h -- not now", and
        # a figure of 228 h [0 - 365] printed beside a 0.95 health index read
        # as a quarter of the engine's life being gone. Three pages gave three
        # answers (the overview "not yet", prognostics 228 h, the report
        # 244 h). Until the health trend has left the as-new band or its onset
        # detector has fired, every page says the same thing: beyond the
        # horizon.
        _degrading = (bool(self.health.onset_detected)
                      or chi_decision < self._life_onset_chi)
        if not _degrading:
            _why = (f"beyond the {self._life_horizon_h:.0f} h prediction horizon: "
                    f"health {chi_decision:.2f} shows no wear trend yet")
            served = rs.ServedRul(source="none", reason=_why)
            rul = rp.RulEstimate(reason=_why)
        _life_hours, _life_source, _life_why = _reportable_life(served, rul)
        self.sync.apply_predictions(
            health=HealthIndices(
                composite=round(chi_decision, 4),
                thermal=round(snap_health.thermal, 4),
                mechanical=round(snap_health.mechanical, 4),
                electrical=round(snap_health.electrical, 4),
                combustion=round(snap_health.combustion, 4),
                band=band,
            ),
            rul=RemainingLife(
                hours=_life_hours,
                # The interval stays the PHYSICS one. `train_rul.py` saves the
                # network without its conformal multiplier, so no calibrated
                # bound for the network exists to serve; inventing one would be
                # decoration on an uncertainty that was measured and discarded.
                # The network's own calibrated bound when it has one, and the
                # physics interval otherwise -- never a bound belonging to a
                # different estimate than the number beside it.
                lower_hours=(served.lower_hours if _life_source == "lstm"
                             and served.lower_hours is not None else rul.lower_hours),
                upper_hours=(served.upper_hours if _life_source == "lstm"
                             and served.upper_hours is not None else rul.upper_hours),
                confidence=rul.confidence,
                source=_life_source,
                limited_by=_life_why,
            ),
            degradation_factors=self.veng.degradation.factors.as_dict(),
            model_confidence=_detection_confidence(
                self._deep_source, self._tier3_confidence, self._in_distribution),
        )

        # The advisory grades health only once the engine has been judged
        # warm at least once (see TwinSync.health_assessed).
        self.sync.health_assessed = bool(assess or self._held is not None)
        self.sync.refresh_advisory()

        # Tier scores (ML-01). STAT is a normalised physics-residual score: the
        # Tier-2 ensemble is refitted inside each evaluation run and no fitted
        # copy is persisted, so it cannot run live and must not be labelled as
        # the ensemble. DEEP is the trained Tier-3 network once its window is
        # full. Until then DEEP falls back to a proxy. Both proxies are scaled
        # against a quantity that MEANS something rather than a tuning constant:
        #
        #   s_stat  the normalised model residual against its healthy spread
        #   s_deep  how far health has travelled from as-new toward the
        #           maintenance threshold
        #
        # The first attempt scaled s_deep as (1 - CHI) x 1.4, which needed
        # CHI < 0.50 to reach the 0.70 gate -- far PAST the 0.60 maintenance
        # threshold, so the predictive path could never fire while there was
        # still time to act on it. Measured against the threshold instead, an
        # engine at CHI 0.72 reaches the gate, which is inside the POOR band
        # where the configured action is already "maintain within 25 h".
        chi_floor = float(config.load_thresholds()["rul"]["maintenance_chi_threshold"])
        # THE FITTED ENSEMBLE scores this sample, on the same baselined
        # features it was fitted on. It used to be a physics-residual proxy
        # standing in for a tier that was never saved (audit 15 Sep, P1-2).
        # With no ensemble on disk there is no statistical tier, and the score
        # is 0 with the reason carried beside it rather than a proxy wearing
        # the tier's name.
        s_stat = 0.0
        self._stat_source = f"not scored: Tier-2 {self.tier2_reason}"
        _row = getattr(self.rul_net, "last_row", None)
        self._ood_verdict = None
        if self.ood is not None and _row:
            try:
                from layer3_ai import features as _feat

                self._ood_verdict = self.ood.verdict(
                    _feat.build_one(_row, self.rul_net.fs))
            except Exception as exc:  # noqa: BLE001 - reported, not handled
                _log.debug("no distribution check this tick: %s", exc)
        if self.tier2 is not None and _row:
            try:
                # The flight condition, as MEASURED -- what an aircraft sends.
                # The ensemble is fitted with it as input (DEV-252); a missing
                # value is the feature's centre, exactly as in training.
                tel = self.ingest.telemetry
                cond = {"throttle_pct": tel.get("throttle_pct"),
                        "altitude_ft": tel.get("altitude_ft"),
                        "oat_c": tel.get("oat"),
                        "airspeed_kmh": tel.get("airspeed_kmh")}
                raw = float(np.clip(self.tier2.score_one({**_row, **cond}), 0.0, 1.0))
                # THE LINE THE RATE WAS MEASURED AT. The limit saved with the
                # model -- per flight condition where there is one -- is mapped
                # onto the fusion gate, so "above the gate" live means exactly
                # "above the limit whose false-alarm rate was measured". The
                # saved limit used to be loaded and never read.
                limit = self.tier2_threshold
                cell = -1
                if self.tier2_limits:
                    cell = t2.regime_code(cond["throttle_pct"], cond["altitude_ft"],
                                          cond["oat_c"], self.tier2_bins)
                    limit = self.tier2_limits.get(cell, limit)
                s_stat = (t2.score_to_gate(raw, limit, self._stat_gate)
                          if limit is not None else raw)
                self._stat_limit = {"raw": round(raw, 3), "limit": round(limit, 3)
                                    if limit is not None else None,
                                    "condition_cell": cell if cell >= 0 else None}
                self._stat_source = ("Tier-2 ensemble (isolation forest + CBLOF), "
                                     + ("limit for this flight condition" if cell in self.tier2_limits
                                        else "single limit"))
            except Exception as exc:  # noqa: BLE001 - reported, then left unscored
                _log.warning("Tier-2 scoring failed", exc_info=exc)
                self._stat_source = (
                    f"not scored: Tier-2 {_operator_reason(exc)}")
        # The SMOOTHED index, the one decisions are taken on (PS1-13).
        s_deep = float(
            np.clip((1.0 - chi_decision) / max(1.0 - chi_floor, 1e-6), 0.0, 1.0)
        )
        self._fault_probs = None
        if self.tier3 is None:
            self._deep_source = f"health-index proxy (Tier-3 {self.tier3_reason})"
        elif not self.rul_net.warm:
            self._deep_source = "health-index proxy (Tier-3 window filling)"
        else:
            try:
                win = np.stack(list(self.rul_net._window))[
                    -self.rul_net.sequence_length:]
                scored = self.tier3.score(win)
                s_deep = float(np.ravel(scored["anomaly"])[0])
                # The trained fault head, in the order the physics labels it.
                self._fault_probs = dict(zip(
                    FAULT_KEYS, (float(v) for v in np.ravel(scored["fault"])), strict=True))
                self._deep_source = "Tier-3 network (ONNX)"
            except Exception as exc:  # noqa: BLE001 - reported, then proxied
                _log.warning("Tier-3 network scoring failed", exc_info=exc)
                self._deep_source = (
                    f"health-index proxy (Tier-3 {_operator_reason(exc)})")
        # The namer reads the same row the networks were given, and only on an
        # ASSESSED tick -- the engine warm, loaded and steady, as in training.
        # Between assessments its last answer is held, like the health index.
        _source = ("Tier-3 fault head" if self._fault_probs is not None
                   else f"not scored: {self._deep_source}")
        if self.fault_namer is not None:
            if self._assessed_now and _row:
                try:
                    self.namer_history.observe(_row, self.veng.flight_hours)
                    self._namer_probs = self.fault_namer.probabilities(
                        _row, self.namer_history.features(),
                        sorties_done=len(self.namer_history.means))
                    # The calling line of the model actually served: a young
                    # engine is named by the sample-only twin, with its own.
                    self._fault_cal = {
                        k: {"threshold": self.fault_namer.threshold(k),
                            "precision": self.fault_namer.precision(k)}
                        for k in self.fault_namer.classes}
                except Exception as exc:  # noqa: BLE001 - reported, then held
                    _log.warning("fault namer failed", exc_info=exc)
            if self._namer_probs is not None:
                self._fault_probs = dict(self._namer_probs)
                # DETECT, THEN NAME -- on a young engine. A trend fault cannot
                # be judged from one moment: its sample-only twin called
                # overheating on 73 % of a healthy new engine's cruise. So
                # there it names a fault only while a detector agrees
                # something is wrong: a rule, or either model tier at its gate.
                twins = self.fault_namer.served_by_twin()
                if twins:
                    alarmed = (bool(self.rules.active_fault_modes())
                               or (self._stat_ema or 0.0) >= self._stat_gate
                               or (self._deep_ema or 0.0) >= self._deep_gate)
                    if not alarmed:
                        for k in twins:
                            self._fault_probs[k] = 0.0
                _source = ("fault namer (per-fault gradient boosting with engine history)"
                           + ("" if self._assessed_now else ", held"))
                if self.fault_namer.withheld:
                    _source += ("; not judged until "
                                f"{self.fault_namer.min_history} completed flights: "
                                + ", ".join(k.replace("_", " ") for k in self.fault_namer.withheld))
        # No engine reference yet: no learned model may name a fault either --
        # its inputs are raw residuals it was never trained on (DEV-254).
        if not self.rul_net.baseline.ready:
            self._fault_probs = None
            _source = "not judged: waiting for this engine's first level flight to set its reference"
        # AFTER the models have scored this tick, so the probabilities shown are
        # this tick's and not the last one's.
        self.sync.apply_fault_evidence(
            network=self._fault_probs, source=_source,
            rule_levels=self.rules.active_fault_modes())

        # ONE SAMPLE OF ONE MODEL TIER IS NOT A FINDING. The Tier-2 score of a
        # healthy engine in a steady cruise scattered 0.03-0.61 sample to
        # sample, and every sample over 0.5 raised ADVISORY on its own -- an
        # advisory with no alert behind it, flickering on and off in the
        # climb. The tiers are smoothed the way the health index is (PRD Part 2
        # s9.4 decides on the smoothed value), and only on assessed samples, so
        # an idle or a transition never moves them.
        # ...and only on samples inside the data the tiers were fitted on: the
        # take-off at full power is outside it (the distribution check names
        # injector duty and wastegate), and its scores started the averages at
        # 0.7, on the edge of ADVISORY, before the climb had begun.
        # ...and only once the engine HAS a reference. Before its first level
        # flight every residual is raw, unlike anything the models were trained
        # on, and a brand-new engine's take-off and climb read as anomalies
        # (DEV-254). The rules run throughout; only the learned tiers wait.
        if self._assessed_now and self._in_distribution and self.rul_net.baseline.ready:
            a = self._tier_alpha
            self._stat_ema = (s_stat if self._stat_ema is None
                              else a * s_stat + (1 - a) * self._stat_ema)
            self._deep_ema = (s_deep if self._deep_ema is None
                              else a * s_deep + (1 - a) * self._deep_ema)
        s_stat = self._stat_ema if self._stat_ema is not None else 0.0
        s_deep = self._deep_ema if self._deep_ema is not None else 0.0
        fused = self.fusion.fuse(
            rule_level=int(alerts.highest_level),
            s_statistical=s_stat, s_deep=s_deep,
            model_confidence=_detection_confidence(
                self._deep_source, self._tier3_confidence, self._in_distribution),
        )

        # Mission reliability is assessed AFTER the maintenance plan below, so
        # a grounding decision reaches every mission card (SAF-02).

        # Why the system concluded what it did. PRD Part 4: a recommendation
        # the operator cannot interrogate must not be presented at all.
        #
        # BUILT FROM SMOOTHED INDICES, and that is what makes it readable.
        #
        # Computed per-sample, this paragraph was rewritten on EVERY FRAME --
        # measured, 40 different texts in 20 seconds. Rounding the numbers in
        # it was not enough, because the noise reaches deeper than the
        # formatting: the SHARES swung 35-55 % and the second-ranked subsystem
        # changed identity between frames, so the sentence genuinely said
        # something different each time. A paragraph being retyped underneath
        # the reader is not an explanation, however exact its arithmetic.
        #
        # The console already displays a smoothed health index, so explaining
        # the smoothed one is also the consistent choice: the explanation now
        # accounts for the number actually on the screen rather than for an
        # instantaneous value nobody saw.
        explanation = ex.explain_snapshot(
            self._smooth_indices(snap_health.as_dict()),
            self.state.residuals.model_dump(mode="json"),
            self.state.advisory.model_dump(mode="json"),
        )
        # Whether the breakdown is worth showing at all. Below the configured
        # floor the shortfall is a ratio of near-zero to near-zero and its
        # four-way split swings every frame -- not wrong, meaningless, because
        # there is no degradation to attribute. The console shows the reason
        # instead, and the numbers are still on the wire for anyone analysing.
        _od = config.load_thresholds()["health"]["operator_display"]
        explanation["attributable"] = bool(
            explanation["health"]["shortfall"]
            >= float(_od["explanation_shortfall_floor"])
        )
        explanation["share_step_pct"] = int(_od["explanation_share_step_pct"])

        # The advisory's explanation field has stood deliberately empty since
        # twin_state was written, as a visible reminder that PRD Part 4 forbids
        # presenting a recommendation the operator cannot interrogate. It can
        # now be filled with the exact subsystem attribution.
        self.state.advisory.shap_explanation = {
            c["name"]: c["share"]
            for c in explanation["health"]["contributions"]
        }

        # What to DO about it, costed and scheduled.
        #
        # The measured misfire rate and bearing ratio come from the per-fault
        # tracker, which holds each indicator's latest measurement. Both are
        # measured only in cruise, so read live they are None from the top of
        # descent -- and an action raised in cruise vanished before the engine
        # stopped. One tick of lag is immaterial.
        _mis = self.fault_rul.forecast("misfire").value
        _brg = self.fault_rul.forecast("abnormal_vibration").value

        # ONE remaining-life figure for decisions (SAF-04). The screen showed
        # the network's value while mission and advisory decided on physics
        # (held-out R2 -0.40). Decisions now take the most conservative of the
        # estimates available -- physics lower bound, physics point, network
        # point -- and the snapshot publishes that floor beside the displayed
        # value, so what decides is visible.
        rul_display = served.hours if served.reportable else rul.hours
        _cands = [x for x in (rul.lower_hours, rul.hours,
                              served.hours if served.reportable else None)
                  if x is not None]
        rul_floor = min(_cands) if _cands else None

        # Measured quantities only (ML-02). The simulator's TRUE degradation
        # factors used to be passed here -- numbers no real aircraft has -- and
        # oil change and turbocharger inspection fired on nothing else, so the
        # demo showed advice the product could never give. The truth is still
        # published for validation, labelled as such, but decides nothing.
        # Recent cruise windows, not flight-long running means: a mean over the
        # whole sortie dilutes a fault that began mid-flight.
        boost_drop = (float(np.mean(self._boost_drop))
                      if len(self._boost_drop) >= 30 else None)
        egt_rise = (float(np.mean(self._egt_resid))
                    if len(self._egt_resid) >= 30 else None)
        wg_closure = (float(np.mean(self._wg_closure))
                      if len(self._wg_closure) >= 30 else None)
        _cool = self.fault_rul.forecast("cooling_degradation").value
        plan = self.advisory.recommend(
            degradation={},
            health=snap_health.as_dict() | {"chi": chi_decision},
            residuals=self.state.residuals.model_dump(mode="json"),
            # The DISPLAYED estimate -- the network when it reports, physics
            # otherwise -- so the number on screen is the number that decides
            # (SAF-04). Not the planning floor: that includes a physics
            # extrapolation (held-out R2 -0.40) which, fitted over minutes of
            # an abrupt fault, grounded an engine at health 0.83 on "7 h".
            # The floor stays where erring short is right: mission planning.
            rul_hours=rul_display,
            # The calibrated horizon probability decides alongside the point
            # RUL. Both are passed: the RUL is late 55% of the time, so it
            # stays as a floor rather than the sole basis for an overhaul call.
            survival=survival,
            egt_spread=r.egt.spread,
            oil_rpm_correlation=self.health._correlation(),
            misfire_rate=None if _mis is None else float(_mis) / 100.0,
            bearing_envelope_x=_brg,
            hours_since_inspection=float(self.state.history.hours_since_inspection),
            boost_drop_fraction=boost_drop,
            egt_rise_c=egt_rise,
            cht_residual_c=_cool,
            wastegate_closure_pct=wg_closure,
        )

        # Mission reliability -- the third pillar of the PS title. Assessed
        # against every standard profile so the operator sees not just whether
        # the requested mission is flyable but which ones are.
        subsystems = {
            "thermal": snap_health.thermal, "mechanical": snap_health.mechanical,
            "electrical": snap_health.electrical, "combustion": snap_health.combustion,
        }
        # Overhaul limit still to run: hours against TBO, and zero once the
        # calendar limit has passed (SAF-07).
        _md = getattr(self.state, "metadata", None)
        tbo_left = None
        if _md is not None and hasattr(_md, "tbo_hours"):
            # Counted from the last overhaul (see _apply_maintenance), not from new.
            tbo_left = max(0.0, float(_md.tbo_hours)
                           - (float(self.veng.flight_hours) - self._overhaul_engine_hours))
            _yrs = _md.tbo_years_remaining()
            if _yrs is not None and _yrs <= 0.0:
                tbo_left = 0.0
        _ground = plan.actions[0].reason if plan.grounding_required and plan.actions else None
        assessments = self.mission.assess_all(
            chi=chi_decision, subsystems=subsystems, rul_hours=rul_display,
            rul_lower_hours=rul_floor, rul_confidence=rul.estimator_confidence,
            active_alerts=len(alerts.active),
            highest_alert_level=int(alerts.highest_level),
            grounded=plan.grounding_required, grounding_reason=_ground,
            tbo_remaining_hours=tbo_left,
        )
        mission = {
            "profiles": [a.as_dict() for a in assessments],
            "life_consumption_rate": rul_consumption_rate(
                rul.rate_per_hour, chi_decision, self.mission.chi_threshold
            ),
            "limiting_subsystem": assessments[0].limiting_subsystem,
            "grounded": plan.grounding_required,
            "tbo_remaining_hours": tbo_left,
            # What the verdicts above were computed FROM, so a squadron board
            # can assess a mission of any length for this aircraft later, when
            # it is parked and another aircraft is on the ground station.
            "inputs": {
                "chi": chi_decision, "subsystems": subsystems,
                "rul_hours": rul_display, "rul_lower_hours": rul_floor,
                "rul_confidence": rul.estimator_confidence,
                "active_alerts": len(alerts.active),
                "highest_alert_level": int(alerts.highest_level),
                "grounded": plan.grounding_required, "grounding_reason": _ground,
                "tbo_remaining_hours": tbo_left,
            },
        }

        # ---- per-fault time-to-action (PS section C) -----------------------
        #
        # Only indicators that are genuinely measured are fed. A mode with no
        # signal returns "no data" and says so, which is the honest answer --
        # feeding it a stand-in would produce a forecast about nothing.
        _lim_all = config.load_engine(self.engine_key)["limits"]
        _lim_cht = float(config.load_thresholds()["parameters"]["cht"]["critical_max"])
        extra = self._fault_indicators(res, getattr(frame, "flight_phase", None))
        # A FAULT TREND IS A TREND AT ONE OPERATING POINT.
        #
        # The forecaster fits a line through its one-minute points and
        # extrapolates it to the action level. Fed every tick, the line ran
        # from the take-off through the climb into the cruise, and extended a
        # change of THROTTLE as wear: on a healthy engine half an hour old it
        # forecast "overheating trend: action in 0 h" (thermal margin "moving
        # -43 C/h" -- the heads warming from climb into cruise), cooling
        # degradation in 2 h and injectors in 5 h. Wear takes tens to hundreds
        # of hours; a change of operating point takes a minute.
        #
        # So it sees only assessed samples (warm, loaded, steady), and a change
        # of regime -- flight phase, or the lever by more than a band -- starts
        # its trends again, for the reason its own `restart` gives for a
        # repair: a line across the change joins two different conditions and
        # forecasts nothing about either. A fault developing at a steady
        # cruise still trends, and is still forecast.
        _fault_values = {} if not self._assessed_now else {
            # The INSTANTANEOUS residual, not the flight-long running mean. A
            # sortie-long mean dilutes a fault that began mid-flight: measured,
            # a severe cooling fault still read 4.9 degC twelve minutes in.
            # FaultRul's recent-sample quantile and one-minute trend buckets
            # do the smoothing.
            "cooling_degradation":
                res.cht.delta if res.cht.usable else None,
            # Oil pressure against the as-new twin, above 3500 rpm only: that
            # is where the certified 2.0 bar minimum applies and where the
            # relief valve makes pressure a property of the oil system rather
            # than of engine speed (PS1-03).
            # The DEPARTURE either way, carried on the falling scale the
            # thresholds are written in (-5 / -10 psi): oxidised, thickened oil
            # raises pressure at a given speed as surely as a worn pump lowers
            # it, and a signed value let a +9 psi lubrication fault read as an
            # engine drifting away from its fault line.
            "lubrication_issue": (
                -abs(res.oil_pressure.delta)
                if res.oil_pressure.usable
                and (self.ingest.telemetry.get("rpm") or 0.0) >= 3500.0
                else None
            ),
            "injector_abnormal": r.egt.spread,
            "overheating_trend": (
                None if not r.cht_max.usable else _lim_cht - r.cht_max.value
            ),
            "abnormal_vibration": extra["vibration_peak_ratio"],
            # The OFFSET, not the scatter. This was the residual variance ratio
            # -- how noisy a channel had become -- so a transducer reading
            # steadily 6 psi low scored as engine wear and never as drift
            # (audit 15 Sep, P0-4). Only offsets a second source blames on the
            # instrument feed the fault class; an offset nothing can attribute
            # is reported, not claimed.
            "sensor_drift": self.bias.indicators()["instrument_offset_fraction_fs"],
            "combustion_instability": extra["egt_scatter_c"],
            "misfire": extra["misfire_rate_pct"],
        }
        # Called every tick, with nothing when not assessed, so the clock that
        # ages a reading keeps running (FaultRul.observe).
        self.fault_rul.observe(self.veng.flight_hours, _fault_values)

        # ---- accumulate the post-flight record ----------------------------
        _phase = getattr(frame, "flight_phase", None)
        # observe_tick does the phase accounting AND the usage counts, so it
        # replaces the bare observe_phase call: hours alone do not describe a
        # life, and two engines with identical hours have not lived identical
        # ones if a larger share of them was spent above maximum continuous.
        self.record.observe_tick(
            frame.t_s, _phase, self.dt,
            throttle_pct=getattr(frame, "throttle_pct", None),
            power_pct=getattr(frame, "power_pct",
                              getattr(frame, "throttle_pct", None)),
        )
        self.record.observe_alerts(
            frame.t_s, _phase,
            [_alert_as_dict(a) for a in alerts.active],
        )
        # Flight-wide, not from the ring buffer: the report's environment table
        # describes the SORTIE, and an endurance flight spans far more weather
        # than its last few minutes.
        _alt_now = getattr(frame, "altitude_ft", None)
        self.record.observe_environment(
            oat_c=getattr(frame, "oat_c", None),
            humidity_pct=getattr(frame, "humidity_pct", None),
            altitude_ft=_alt_now,
            pressure_hpa=(None if _alt_now is None else
                          atmo.isa_pressure_pa(float(_alt_now) * 0.3048) / 100.0),
        )

        # Which channels produced a reading at all. A report silent about a
        # dead sensor reads as a clean bill of health, and section 10 refuses
        # to report "not detected" for a fault whose channel is listed here.
        for _ch, _rd in (
            ("rpm", r.rpm), ("cht_max", r.cht_max), ("egt_max", r.egt_max),
            ("oil_pressure", r.oil_pressure),
            ("oil_temperature", r.oil_temperature),
            ("fuel_flow", getattr(r, "fuel_flow", None)),
            ("coolant_temperature", r.coolant_temperature),
        ):
            self.record.observe_channel(_ch, v(_rd) if _rd is not None else None)
        # Vibration is reported as a group, so its liveness is the presence of
        # rms_total rather than a band's usable flag.
        _vib = getattr(r, "vibration", None)
        self.record.observe_channel(
            "vibration_rms_total",
            None if _vib is None else getattr(_vib, "rms_total", None))

        # The real engine against the twin's own prediction of it. This is the
        # comparison that makes the document a DIGITAL TWIN report rather than
        # a general engine log, and it was the one thing section 04 could not
        # draw because nothing was accumulating it.
        #
        # The pair comes from the RESIDUALS, which already carry `measured` and
        # `predicted` side by side. My first attempt passed the measured value
        # as both halves -- it printed "the twin tracked the engine within
        # 0.0 %", which is not a flattering result but a false one.
        _rs = self.state.residuals
        _actual, _twin = {}, {}
        for _label, _attr in (
            ("Cylinder Head Temp (C)", "cht"),
            ("Coolant Temp (C)", "coolant"),
            ("Exhaust Gas Temp (C)", "egt"),
            ("Oil Pressure (psi)", "oil_pressure"),
            ("Oil Temperature (C)", "oil_temperature"),
            ("Fuel Flow (L/h)", "fuel_flow"),
            # The residual is in BAR, not kPa. 1.24 with a kPa label reads as an
            # engine drawing a deep vacuum rather than one under boost.
            ("Manifold Pressure (bar)", "manifold_pressure"),
        ):
            _band = getattr(_rs, _attr, None)
            if _band is None or not getattr(_band, "usable", False):
                continue
            _actual[_label] = getattr(_band, "measured", None)
            _twin[_label] = getattr(_band, "predicted", None)
        self.record.observe_twin(_actual, _twin)

        _p = config.load_thresholds()["parameters"]
        _op = _p["oil_pressure"]
        _rpm_now = v(r.rpm)
        _oil_min = (
            float(_op["high_speed_min_psi"])
            if _rpm_now is not None and _rpm_now >= float(_op["low_speed_rpm"])
            else float(_op["low_speed_min_psi"])
        )
        _grades = config.load_thresholds().get("exceedance_grades", {}) or {}
        _ph_now = self.veng.current_phase()
        _firing = bool(_ph_now.ignition) and _ph_now.name != "STARTUP"
        for name, val, limit, unit, minimum in (
            ("cylinder head temperature", v(r.cht_max),
             float(_p["cht"]["critical_max"]), "C", False),
            ("coolant temperature", v(r.coolant_temperature),
             float(_lim_all["coolant_temperature_max_C"]), "C", False),
            ("exhaust gas temperature", v(r.egt_max),
             float(_lim_all["egt_max_C"]), "C", False),
            ("oil temperature", v(r.oil_temperature),
             float(_lim_all["oil_temperature_C"][1]), "C", False),
            # OIL PRESSURE'S MINIMUM IS RPM-DEPENDENT, and applying the
            # high-speed figure everywhere makes every ground idle an
            # exceedance. Measured before this was fixed: a clean sortie
            # reported "oil pressure 14.9 psi against 29.0, 119.5 s above,
            # first in GROUND" -- a finding that is simply not true, and the
            # kind that teaches a maintainer to stop reading the report.
            #
            # [OM s2.1] above 3500 rpm the minimum is 2.0 bar (29 psi); below
            # it, 0.8 bar (11.6 psi). Both figures are already in the threshold
            # file with the rpm that separates them.
            #
            # AND ONLY WITH THE ENGINE TURNING. A stopped engine has no oil
            # pressure by definition; counted, every sortie's record gained an
            # "oil pressure -0.9 psi" exceedance that grew for as long as the
            # aircraft sat shut down after landing.
            # Nor on the starter or running down after the ignition is cut,
            # as an engine monitor inhibits it there: pressure is still
            # building, or already falling away, by design.
            ("oil pressure",
             v(r.oil_pressure) if (self._sortie_state == "running"
                                   and _firing
                                   and (v(r.rpm) or 0.0) > 500.0) else None,
             _oil_min, "psi", True),
        ):
            _g = _grades.get(name) or {}
            _lv = None
            if "l2" in _g and "l3" in _g:
                _sg = -1.0 if minimum else 1.0
                _lv = (limit, limit + _sg * float(_g["l2"]),
                       limit + _sg * float(_g["l3"]))
            self.record.observe_exceedance(
                frame.t_s, _phase, parameter=name, value=val, limit=limit,
                unit=unit, dt=self.dt, minimum=minimum,
                # Graded 1-3 against configured margins (REP-02). Without
                # them every exceedance printed as L1 -- CHT at 145 degC
                # against a 135 degC limit included.
                level_limits=_lv,
            )

        _env = getattr(frame, "altitude_ft", None)
        self.record.observe_cruise(
            frame.t_s, _phase,
            throttle_pct=getattr(frame, "throttle_pct", None),
            altitude_ft=_env,
            sample={
                "altitude_ft": _env,
                "oat_c": getattr(frame, "oat_c", None),
                "airspeed_kmh": getattr(frame, "airspeed_kmh", None),
                "throttle_pct": getattr(frame, "throttle_pct", None),
                "rpm": v(r.rpm),
                "manifold_pressure_bar": v(r.manifold_pressure),
                "cht_max_c": v(r.cht_max),
                "cht_spread_c": r.cht.spread,
                "egt_max_c": v(r.egt_max),
                "egt_spread_c": r.egt.spread,
                "oil_pressure_psi": v(r.oil_pressure),
                "oil_temperature_c": v(r.oil_temperature),
                "coolant_temperature_c": v(r.coolant_temperature),
                "fuel_flow_lph": v(r.fuel_flow),
                "power_kw": getattr(pred, "power_kw", None),
            },
        )

        self._ticks += 1
        self._push_series(frame, snap_health, r, effi)

        # ---- the operator's view of the slow quantities --------------------
        #
        # Measured raw on a HEALTHY engine over 20 s: BSFC deterioration swung
        # 11.4 points, mission success probability 29.7, and the RUL changed on
        # 35 frames out of 40. Those were being printed in the largest type on
        # the dashboard. An operator watching a success probability swing
        # between 57 % and 87 % twice a second learns that the number is
        # worthless -- and stops looking at the panel that carries it, on every
        # future day including the one where it is right.
        _profiles = mission.get("profiles") or []
        _assessment = self._assessment_status(frame.t_s)
        _unassessed = _assessment["state"] == "assessing"
        display = self.operator.update(
            # Nothing to smooth before the first warm assessment: a cold
            # engine's indices would otherwise be averaged into the first
            # real figure the operator sees.
            chi=None if _unassessed else chi_decision,
            rul_hours=rul.hours,
            rul_reportable=rul.reportable,
            bsfc_deterioration_pct=effi.bsfc_deterioration_pct,
            mission_success=(_profiles[0].get("success_probability")
                             if _profiles else None),
            fusion_score=fused.score,
        )
        display["band"] = None if _unassessed else band
        # Judged now, held from the last warm running, or not yet judged --
        # so a held figure is never mistaken for a live one.
        display["assessment"] = _assessment
        # The band carries a machine token; the operator gets the sentence.
        display["instruction"] = (
            "Engine warming up: its condition is assessed once it is warm and "
            "under load." if _unassessed else ov.instruction(action))
        # THE LIVE ENGINE AGAINST ITS TWIN, beside each reading it concerns.
        display["twin"] = self._twin_compare()
        # A temperature without its limit is a number. With its limit it is a
        # margin, and a margin is a decision.
        _lim = config.load_engine(self.engine_key)["limits"]

        # THE OIL-PRESSURE MINIMUM DEPENDS ON ENGINE SPEED.
        #
        # OM s2.1: above 3500 rpm the range is 2.0-5.0 bar (29-72.5 psi); below
        # it the minimum is 0.8 bar (11.6 psi). The rule engine honours that --
        # OILP_AT_SPEED fires only when rpm > 3500 AND oil < 29 psi -- but this
        # margin took the high-speed figure at EVERY speed, and so did the
        # console's tile. Caught on a screenshot at 3285 rpm and 22.9 psi:
        # the console showed OIL PRESS in red, tagged BELOW LIMIT, directly
        # beside an alert panel correctly reading "every parameter is inside
        # its limit". The engine was fine and two parts of the same display
        # disagreed about it.
        #
        # Published as well as used, so the console reads the limit that
        # applies now instead of re-deriving the condition in TypeScript. The
        # /api/engine docstring already says why: "a console with its own copy
        # of the numbers will disagree with the system eventually, and the
        # operator will believe the console." It had the number; what it did
        # not have was the condition attached to it.
        _oilp = config.load_thresholds()["parameters"]["oil_pressure"]
        _rpm_now = r.rpm.value if r.rpm.usable else None
        _oil_min = (
            float(_oilp["high_speed_min_psi"])
            if _rpm_now is not None and _rpm_now > float(_oilp["low_speed_rpm"])
            else float(_oilp["critical_min"])
        )
        display["oil_pressure_min_psi"] = _oil_min
        display["margins"] = [
            m for m in (
                ov.margin(r.coolant_temperature.value
                          if r.coolant_temperature.usable else None,
                          float(_lim["coolant_temperature_max_C"]),
                          unit="C", name="Coolant"),
                ov.margin(r.cht_max.value if r.cht_max.usable else None,
                          float(config.load_thresholds()["parameters"]["cht"]
                                ["critical_max"]),
                          unit="C", name="Cyl head"),
                ov.margin(r.egt_max.value if r.egt_max.usable else None,
                          float(_lim["egt_max_C"]), unit="C", name="EGT"),
                ov.margin(r.oil_temperature.value
                          if r.oil_temperature.usable else None,
                          float(_lim["oil_temperature_C"][1]),
                          unit="C", name="Oil temp"),
                # PSI, not bar. The ingest path converts to psi (can_ingest
                # multiplies by 14.5038) and the parameter readout is labelled
                # psi, so the margin is taken against the PSI threshold -- the
                # same number the readout shows its limit from. Reading the
                # certificate's bar figure here gave "59.2 against a limit of
                # 2.0", a margin of +57 on a parameter whose real margin was
                # +2.1 bar, which is the kind of number an operator would have
                # flown on.
                ov.margin(r.oil_pressure.value if r.oil_pressure.usable else None,
                          _oil_min, unit="psi", name="Oil press", minimum=True),
            ) if m is not None
        ]
        lat = np.array(self._latencies) if self._latencies else np.array([0.0])

        snapshot = Snapshot(
            t_s=frame.t_s,
            wall_utc=time.strftime("%H:%M:%SZ", time.gmtime()),
            wall_iso=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            started_iso=self._started_iso,
            twin=self.state.model_dump(mode="json"),
            mission=mission,
            explanation=explanation,
            battery=batt.as_dict() | {"confidence": round(self.battery.confidence(), 3)},
            efficiency=effi.as_dict(),
            display=display,
            fault_forecast=self.fault_rul.all_forecasts(),
            flight_record=self.record.as_dict(),
            # The work recorded as done, beside the work still advised.
            maintenance={**plan.as_dict(),
                         "performed": [dict(r) for r in self._maintenance_log],
                         "pending": [dict(r) for r in self._maintenance_pending]},
            # "chi" is the decision value the band and advisory use; the raw
            # per-sample index is carried alongside for the trend chart, where
            # its noise is information rather than a distraction.
            health=_withhold_unassessed(
                {**snap_health.as_dict(), "chi": round(chi_decision, 4),
                 "chi_raw": round(snap_health.chi, 4),
                 "band": band, "action": action},
                self._assessment_status(frame.t_s)),
            # `/api/...` serves this dict as `remaining_life`, so the SERVED
            # estimate belongs here -- not only in the twin state. Before A1
            # this carried the physics figure with no way to tell which
            # estimator produced it (DEV-191).
            #
            # EACH ESTIMATE CARRIES ITS OWN INTERVAL, OR NONE.
            #
            # This served `hours` from the network and `lower`/`upper` from the
            # PHYSICS estimator, on the reasoning that the network's checkpoint
            # had no conformal multiplier to bound itself with. It has one now
            # (rul_serving: "the checkpoint now carries the split-conformal
            # multiplier train_rul.py fits"), and the comment had not followed.
            #
            # The cost was visible on the console: 137 flight hours over
            # "[0 - 0], 95% confidence interval", because the network was
            # reporting and the physics estimator -- with no measurable trend
            # yet -- was not. A bound borrowed from an estimator that is not
            # reporting is not a confidence interval for the number above it,
            # and labelling it one is exactly the invention this system
            # refuses everywhere else.
            #
            # `physics_hours` keeps the older estimate visible beside the
            # served one, because an engineer comparing the two is the first
            # person who will want to.
            rul={
                "hours": (served.hours if served.reportable else rul.hours),
                "source": (
                    "lstm" if served.reportable
                    else "physics_fallback" if rul.reportable
                    else "none"
                ),
                "lower": (served.lower_hours if served.reportable
                          else rul.lower_hours),
                "upper": (served.upper_hours if served.reportable
                          else rul.upper_hours),
                "confidence": rul.confidence,
                "reason": (served.reason if served.reportable else rul.reason),
                "reportable": (served.reportable or rul.reportable),
                "rate_per_hour": rul.rate_per_hour,
                "physics_hours": rul.hours,
                # The figure mission and advisory actually decide on.
                "decision_floor_hours": rul_floor,
                "network": served.as_dict(),
            },
            # P(fail within h), calibrated, for the horizons a dispatch
            # decision is actually taken on. Reported beside RUL rather than
            # instead of it: hours-remaining is near its ceiling on this data
            # and the probability is the number that is accurate, so an
            # operator should see both and know which is which.
            survival=survival,
            fusion={
                "score": round(fused.score, 4), "level": int(fused.level),
                # The ENUM name and the OPERATOR-FACING word are not the same
                # thing. FusedLevel.NONE reads correctly in code -- no alert was
                # raised -- but on a status readout "NONE" is ambiguous between
                # "nothing is wrong" and "no data", and those are the two states
                # a crew station must never confuse (s7.2). MIL-STD-411F's word
                # for the quiet state is NORMAL, so that is what is displayed.
                "level_name": _DISPLAY_LEVEL.get(fused.level.name,
                                                 fused.level.name),
                "predictive": fused.predictive,
                "rule_confirmed": fused.rule_confirmed, "reason": fused.reason,
                # Per fault class: the score at which the network CALLS it, and
                # how often it is right when it does (tier3_report.json).
                "fault_calibration": self._fault_cal,
                "s_rule": round(fused.s_rule, 3),
                "s_statistical": round(fused.s_statistical, 3),
                "s_deep": round(fused.s_deep, 3),
                # Where each tier score came from, so the panel says what it
                # shows (ML-01). Both name the model that produced them, or say
                # plainly that nothing did.
                "statistical_source": self._stat_source,
                # The raw ensemble score and the measured limit it was held
                # against this tick (DEV-252), so "why did it alarm?" has an
                # answer in numbers, not only in the mapped score above.
                "statistical_limit": self._stat_limit,
                # Whether the models were asked about something they were shown.
                "in_distribution": self._in_distribution,
                # Whether this engine's residual reference exists yet; until
                # it does the learned tiers hold and the rules alone decide.
                "engine_reference": {
                    "ready": self.rul_net.baseline.ready,
                    "frozen": self.rul_net.baseline.frozen,
                    "reason": ("formed" if self.rul_net.baseline.frozen else
                               "forming from level flight" if self.rul_net.baseline.ready else
                               "waiting for the first level flight: learned tiers hold, rules decide")},
                "distribution_check": (
                    self._ood_verdict.as_dict() if self._ood_verdict is not None
                    else {"available": False, "reason": self.ood_reason}),
                "deep_source": self._deep_source,
                "rule_based_fallback": fused.rule_based_fallback,
            },
            trend={**trend, "onset_hours": self.health.onset_hours},
            pipeline={
                "ticks": self._ticks,
                "flight_hours": round(self.veng.flight_hours, 4),
                # What the overhaul limit is counted against.
                "hours_since_overhaul": round(
                    self.veng.flight_hours - self._overhaul_engine_hours, 4),
                "frames_decoded": tel.frames_decoded,
                "frames_lost": tel.frames_lost,
                "decode_errors": tel.decode_errors,
                "frames_rejected": tel.frames_rejected,
                "frame_rejects": dict(tel.rejects),
                "sequence_resets": tel.sequence_resets,
                # The FADEC's own report, or None when it has never reported.
                "ecu": None if tel.ecu is None else dict(vars(tel.ecu)),
                "redundancy_lost": sorted(
                    n for n, c in tel.channels.items() if c.redundancy_lost),
                "sensors_not_responding": self.response.not_responding(),
                "sensor_bias": self.bias.as_dict(),
                "sensor_offsets_unattributed": self.bias.unattributed(),
                "channels_total": r.channels_total,
                "channels_usable": r.channels_usable,
                "data_quality": round(r.data_quality, 4),
                "shadow_available": self.shadow.status.usable,
                "hz": round(1.0 / self.dt, 1),
                "latency_p50_ms": round(float(np.percentile(lat, 50)), 2),
                "latency_p95_ms": round(float(np.percentile(lat, 95)), 2),
                "engine": self.engine_key,
                "speed_x": self.speed,
            },
            history={k: list(vals) for k, vals in self._series.items()},
            flight_series={k: list(vals)
                           for k, vals in self._flight_series.items()},
            faults_injected=list(self._injected),
            sortie=self._sortie_status(frame.t_s),
        )
        with self._lock:
            self._snapshot = snapshot

    def _smooth_indices(self, indices: dict) -> dict:
        """The health indices, EMA-smoothed, for the explanation to reason over.

        Same constant as everything else the operator reads -- PRD Part 2
        s9.4 METHOD 1, alpha from the threshold file. Only the numeric indices
        are smoothed; anything else in the dict passes through untouched.
        """
        a = ov.alpha()
        out = dict(indices)
        for k, v in indices.items():
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                continue
            prev = self._index_ema.get(k)
            cur = float(v) if prev is None else a * float(v) + (1.0 - a) * prev
            self._index_ema[k] = cur
            out[k] = cur
        return out

    def _push_series(self, frame, snap_health, r, effi=None) -> None:
        """A rolling window for the trend charts, decimated to stay small.

        The console redraws at 2 Hz; sending every sample of a long mission
        would make the payload grow without bound and the chart unreadable.
        """
        keep = 240
        s = self._series
        s["t"].append(round(frame.t_s, 1))
        s["cht"].append(r.cht_max.value if r.cht_max.usable else None)
        s["cht_pred"].append(self.state.simulated.cht_predicted)
        s["egt"].append(r.egt_max.value if r.egt_max.usable else None)
        s["coolant"].append(
            r.coolant_temperature.value if r.coolant_temperature.usable else None
        )
        s["oil_pressure"].append(r.oil_pressure.value if r.oil_pressure.usable else None)
        # THE SMOOTHED INDEX, the one on the gauge and the one every decision
        # is taken on. The per-sample index drew a saw-tooth between 0.9 and
        # 1.0 under a gauge that read a steady 95, which looked like a sick
        # engine's chart and was noise. A gap before the first warm
        # assessment, and the held value while held.
        s["chi"].append(None if self._held is None and not self._assessed_now
                        else round(self._chi_decision_now, 4))
        s["rpm"].append(r.rpm.value if r.rpm.usable else None)
        s["fuel_flow"].append(r.fuel_flow.value if r.fuel_flow.usable else None)
        s["oil_temperature"].append(
            r.oil_temperature.value if r.oil_temperature.usable else None
        )
        # None where efficiency is not derivable -- at idle BSFC is undefined,
        # and the chart must show a GAP there rather than carrying the last
        # value forward across it.
        s["bsfc_deterioration"].append(
            None if effi is None else effi.bsfc_deterioration_pct
        )
        s["thermal_efficiency"].append(
            None if effi is None else effi.thermal_efficiency
        )
        # Flight condition and environment, straight off the frame. getattr
        # rather than attribute access because a frame from a replayed
        # recording carries fewer fields than a live one, and a missing
        # channel must become a gap in the chart rather than an exception.
        _kmh = getattr(frame, "airspeed_kmh", None)
        s["altitude_ft"].append(getattr(frame, "altitude_ft", None))
        s["airspeed_kt"].append(None if _kmh is None else round(_kmh / 1.852, 1))
        s["oat_c"].append(getattr(frame, "oat_c", None))
        s["humidity_pct"].append(getattr(frame, "humidity_pct", None))
        # The frame carries no ambient pressure -- it is not a sensor on this
        # engine. It comes from the standard atmosphere at the altitude being
        # flown, which is the same model the physics layer breathes through, so
        # the report is not quoting a reading nobody took.
        _alt_ft = getattr(frame, "altitude_ft", None)
        s["ambient_pressure_hpa"].append(
            None if _alt_ft is None
            else round(atmo.isa_pressure_pa(float(_alt_ft) * 0.3048) / 100.0, 1)
        )
        _mp = getattr(r, "manifold_pressure", None)
        s["manifold_pressure"].append(
            _mp.value if _mp is not None and _mp.usable else None
        )
        # `vibration` is a nested group, not a band: rms_x/y/z are bands and
        # `rms_total` is the plain float computed from them. Guessing
        # `vibration_rms_total` on the readings object is why section 3 plotted
        # an empty panel -- and, worse, why the data-quality section declared
        # the vibration channel DEAD and section 10 refused to assess abnormal
        # vibration on a sortie where the sensor was working perfectly.
        _vb = getattr(r, "vibration", None)
        s["vibration_rms_total"].append(
            None if _vb is None else getattr(_vb, "rms_total", None)
        )
        for k in s:
            if len(s[k]) > keep:
                s[k] = s[k][-keep:]

        self._append_flight_series(frame, r, snap_health)

    _FLIGHT_KEEP = 480

    def _append_flight_series(self, frame, r, snap_health) -> None:
        """One decimated sample of the WHOLE flight, for the report."""
        self._flight_seen += 1
        if (self._flight_seen - 1) % self._flight_stride:
            return

        s = self._series
        f = self._flight_series
        if not f:
            f.update({k: [] for k in s})
        for k in s:
            f.setdefault(k, []).append(s[k][-1] if s[k] else None)

        if len(f["t"]) > self._FLIGHT_KEEP:
            # Halve in place and double the stride. The series keeps covering
            # the whole flight; only its resolution falls, which is the right
            # thing to trade on a chart 60 mm wide.
            for k in f:
                f[k] = f[k][::2]
            self._flight_stride *= 2


def available_faults() -> list[dict[str, Any]]:
    """The eight problem-statement faults, for the demonstration control."""
    labels = config.load_thresholds()["faults"]
    out = []
    for m in FaultMode:
        cfg = labels.get(m.value, {})
        out.append({
            "mode": m.value,
            "label": m.value.replace("_", " ").upper(),
            # All eight are injectable. Sensor drift was excluded while the
            # fleet generator excluded it; the generator deals a channel and a
            # direction now, and the class is trained and scored like the rest.
            "injectable": True,
            "note": "" if m is not FaultMode.SENSOR_DRIFT else (
                "afflicts one instrument; defaults to manifold pressure, "
                "where the two FADEC lanes disagree"
            ),
            "description": cfg.get("description") or _FAULT_EFFECT.get(m.value, ""),
        })
    return out


# What each fault DOES to the engine, in the words of whoever injects it: the
# engineer picks a fault by its effect, and a list of eight bare names gave
# nothing to pick by. Overridden by a `description:` under faults.<mode> in
# thresholds.yaml when one is written.
_FAULT_EFFECT = {
    "misfire": "One cylinder stops firing cleanly: its exhaust runs cold against the others, rpm roughens.",
    "injector_abnormal": "One injector delivers the wrong amount: exhaust temperatures split between cylinders.",
    "cooling_degradation": "Coolant loses its capacity to carry heat: head and coolant temperatures climb at the same power.",
    "lubrication_issue": "Oil supply degrades: pressure falls for the engine speed and oil temperature rises.",
    "sensor_drift": "An instrument drifts away from the truth while the engine itself is healthy.",
    "combustion_instability": "Combustion becomes uneven cycle to cycle: exhaust spread and vibration rise.",
    "overheating_trend": "The engine runs progressively hotter overall: every temperature trends upward.",
    "abnormal_vibration": "A mechanical source of vibration develops: level and impulsiveness rise.",
}
