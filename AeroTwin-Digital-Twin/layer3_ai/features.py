"""The feature contract -- PRD Part 2 sections 11.1 and 12.3.

Every model in Layer 3 takes its input from here, and so does live inference in
the twin. That is the entire point of the module: if training features and
serving features are built by two different pieces of code, they will drift
apart, and the failure is silent. The model keeps returning confident numbers;
they are simply about a different engine than the one on the aircraft. This is
the single most common way a working prognostics system rots in service, so
there is exactly one definition of each feature and both paths call it.

TWO FEATURE SETS, AND WHY BOTH EXIST
------------------------------------
``PRD7`` is the seven raw channels named in PRD Part 2 section 11.1:
rpm, CHT, EGT, oil pressure, oil temperature, fuel flow, vibration RMS.

``EXTENDED`` adds the physics residuals from the shadow model, plus the derived
quantities the Layer 1 detectors already rely on.

Keeping the PRD set as a named baseline is deliberate. The residual features
are the argument for having built a digital twin at all, and an argument is
worth more when it is measured than when it is asserted -- so both sets are
built, both are trained, and ``scripts/eval_tier2.py`` reports the difference.

WHY RAW CHANNELS ARE WEAK ON THEIR OWN
--------------------------------------
Raw CHT depends far more on what the throttle is doing than on whether the
engine is healthy. An unsupervised detector fed raw channels therefore learns
to flag unusual OPERATING POINTS -- a climb, a hot day, an unusual altitude --
and reports them as engine anomalies. Residuals are operating-point normalised
by construction, because the shadow model is driven by that same operating
point. That is why they carry the health signal and the raw channels mostly
carry the flight profile.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from common import config

# ---------------------------------------------------------------------------
# The PRD's seven channels (PRD Part 2 section 11.1, feature_norm in
# configs/thresholds.yaml keys these by name).
# ---------------------------------------------------------------------------

PRD7: tuple[tuple[str, str], ...] = (
    # (dataset column, feature_norm key)
    ("rpm", "rpm"),
    ("cht_max", "cht_avg"),
    ("egt_max", "egt_avg"),
    ("oil_pressure", "oil_pressure"),
    ("oil_temperature", "oil_temperature"),
    ("fuel_flow", "fuel_flow"),
    ("vibration_rms_total", "vibration_rms"),
)

# Physics residuals: measured minus as-new prediction. Already centred on zero
# for a healthy engine, so only a scale is needed.
RESIDUALS: tuple[tuple[str, str], ...] = (
    ("res_cht", "cht_avg"),
    ("res_coolant", "cht_avg"),
    ("res_egt", "egt_avg"),
    ("res_oil_pressure", "oil_pressure"),
    ("res_oil_temperature", "oil_temperature"),
    ("res_fuel_flow", "fuel_flow"),
)

# Derived quantities that already earn their place in the Layer 1 detectors.
# Each carries an explicit centre and scale because none of them is a raw
# channel with an entry in feature_norm.
DERIVED: tuple[tuple[str, float, float], ...] = (
    # name, centre, scale
    ("cht_minus_coolant", 12.0, 10.0),
    ("cht_spread", 8.0, 8.0),
    ("egt_spread", 45.0, 50.0),
    ("injection_deviation_max", 0.5, 3.0),
    ("knock_retard_deg", 3.0, 5.0),
    ("injector_duty", 0.35, 0.25),
    ("vibration_kurtosis", 3.0, 3.0),
    # The FDI structured-residual signature -- see add_structured_residual_features.
    ("res_isolation", 0.4, 0.6),
    ("res_n_excursions", 0.5, 1.0),
    ("res_top_abs", 1.2, 1.0),
    # ACTUATOR AUTHORITY. On a FADEC engine with closed-loop control the
    # degradation is spent authority before it is a changed reading, and
    # neither actuator was visible to any model. Measured across 18 operating
    # points, 30 % of the cooling air lost moves the flap 31.8 sensor-sigmas
    # and the best temperature channel 4.0; a turbocharger worn from condition
    # 1.00 to 0.55 moves brake power by 0.1 kW and the wastegate by 0.29 of its
    # travel. Centres and scales are the healthy operating ranges measured on
    # the fleet: flap 0.15-0.86, wastegate 0.36-0.80.
    ("wastegate_pct", 55.0, 25.0),
    ("cooling_flap_pct", 45.0, 30.0),
    ("res_wastegate", 0.0, 10.0),
    ("res_cooling_flap", 0.0, 10.0),
    # What the two FADEC lanes disagree by. A transducer drifting on one lane
    # moves this; the engine drifting does not. Healthy separation is the two
    # instruments' own noise: rpm sigma 4.0 each, so |difference| averages 6.4.
    ("rpm_lane_delta", 6.0, 6.0),
    ("map_lane_delta", 0.005, 0.005),
    # Scatter of the exhaust residual over the last minute -- combustion
    # instability is cycle-to-cycle variation, which no instantaneous residual
    # carries. The twin computes exactly this live (live.py egt_scatter_c).
    ("egt_scatter", 6.0, 6.0),
    # rpm_scatter and egt_spread_scatter were added here and MEASURED OUT again.
    #
    # The reasoning was sound and the single-feature evidence was real: the
    # simulator injects combustion instability as scatter on speed as well as
    # on exhaust, nothing measured the speed, and on the test engines speed
    # scatter separated the class at AUC 0.707 and the scatter of the
    # cross-cylinder spread at 0.736 against the exhaust residual's 0.599.
    #
    # It did not survive the network. combustion_instability went 0.372 ->
    # 0.283, macro-F1 0.607 -> 0.588 and the fused detector 0.910 -> 0.893.
    # Two more columns cost more in dilution than the signal in them was worth
    # at this much data. The columns are still COMPUTED (SCATTER_SOURCES) so
    # the measurement can be repeated cheaply, but they are not served.
    # BEARING DEFECT ORDERS, each as a multiple of the envelope floor. RMS and
    # kurtosis say the engine is rough; the order spectrum says which race is
    # spalling, which is the difference between "abnormal vibration" and a
    # named part. The twin has computed these live since the order-analysis
    # work and the training data never carried them, which is why the class sat
    # at 0.741 on magnitudes alone. Configured bands: degraded 2.0x, fault 5.0x.
    ("vib_bpfo", 1.5, 1.5),
    ("vib_bpfi", 1.5, 1.5),
    ("vib_bsf", 1.5, 1.5),
    ("vib_ftf", 1.5, 1.5),
)

# Columns that must never reach a model's input. Ground truth the aircraft
# cannot observe, plus identifiers a model could use to memorise an engine.
FORBIDDEN_PREFIXES = ("deg_", "lab_", "chi_", "thi_", "mhi_", "comb_hi_")
FORBIDDEN_EXACT = frozenset(
    {"rul_hours", "censored", "any_fault", "engine_id", "split", "sortie", "t_s"}
)


def _norm() -> dict:
    return config.load_thresholds()["feature_norm"]


@dataclass(frozen=True)
class FeatureSet:
    """A named, ordered, normalised set of model inputs."""

    name: str
    columns: tuple[str, ...]
    centres: tuple[float, ...]
    scales: tuple[float, ...]

    def __len__(self) -> int:
        return len(self.columns)

    def normalise(self, raw: np.ndarray) -> np.ndarray:
        """z-score using FIXED centres and scales, not per-batch statistics.

        Per-batch normalisation would make a sample's features depend on
        whichever other samples happened to arrive with it -- fine in training,
        meaningless at inference where samples arrive one at a time. Fixed
        constants from configuration make the transform identical in both.
        """
        c = np.asarray(self.centres, dtype=float)
        s = np.asarray(self.scales, dtype=float)
        return (raw - c) / s

    def validate(self) -> None:
        bad = [
            c for c in self.columns
            if c.startswith(FORBIDDEN_PREFIXES) or c in FORBIDDEN_EXACT
        ]
        if bad:
            raise ValueError(f"feature set '{self.name}' leaks ground truth: {bad}")


def prd7() -> FeatureSet:
    """The seven raw channels of PRD Part 2 section 11.1."""
    n = _norm()
    return FeatureSet(
        name="PRD7",
        columns=tuple(col for col, _ in PRD7),
        centres=tuple(float(n[k]["center"]) for _, k in PRD7),
        scales=tuple(float(n[k]["scale"]) for _, k in PRD7),
    )


def extended() -> FeatureSet:
    """The PRD seven plus physics residuals and derived diagnostics."""
    n = _norm()
    cols = [c for c, _ in PRD7] + [c for c, _ in RESIDUALS] + [c for c, _, _ in DERIVED]
    centres = (
        [float(n[k]["center"]) for _, k in PRD7]
        # A residual is a difference, so its expected value is zero, not the
        # channel's operating centre.
        + [0.0 for _ in RESIDUALS]
        + [c for _, c, _ in DERIVED]
    )
    scales = (
        [float(n[k]["scale"]) for _, k in PRD7]
        # Residuals are far smaller than the channels they come from; scaling
        # them by the channel's own spread would flatten them to nothing.
        + [float(n[k]["scale"]) / 5.0 for _, k in RESIDUALS]
        + [s for _, _, s in DERIVED]
    )
    return FeatureSet(
        name="EXTENDED",
        columns=tuple(cols),
        centres=tuple(centres),
        scales=tuple(scales),
    )


# THE FLIGHT CONDITION, for the Tier-2 detector (DEV-252). The ensemble scores
# how unusual a sample is among healthy ones, and the physics residuals of a
# healthy engine still move with condition: measured on held-out engines, a
# healthy engine at part throttle (55-70 %) was flagged 13.6 % of the time,
# above 14,000 ft 10.7 %, in air below -10 degC 10.1 %, against 0-3 % elsewhere.
# Given the condition as inputs, the detector learns what healthy looks like
# AT that condition instead of calling a rare condition a fault.
OPERATING_CONDITION: tuple[tuple[str, float, float], ...] = (
    # name, centre, scale -- the fleet's own flight envelope
    ("throttle_pct", 70.0, 20.0),
    ("altitude_ft", 10000.0, 6000.0),
    ("oat_c", -10.0, 15.0),
    ("airspeed_kmh", 150.0, 40.0),
)


def extended_ops() -> FeatureSet:
    """EXTENDED plus the flight condition it was measured at (Tier-2 only)."""
    e = extended()
    return FeatureSet(
        name="EXTENDED_OPS",
        columns=e.columns + tuple(c for c, _, _ in OPERATING_CONDITION),
        centres=e.centres + tuple(c for _, c, _ in OPERATING_CONDITION),
        scales=e.scales + tuple(s for _, _, s in OPERATING_CONDITION),
    )


FEATURE_SETS = {"PRD7": prd7, "EXTENDED": extended, "EXTENDED_OPS": extended_ops}


def build(df, feature_set: FeatureSet) -> np.ndarray:
    """Normalised feature matrix from a dataset frame.

    Missing values are filled with the feature's own centre, i.e. zero after
    normalisation. That is the honest choice for a model input: it says "no
    information" rather than inventing a reading, and it matches what the
    ingest layer does when a channel is unusable -- remove, never substitute
    (PRD Part 4 section 7.2).
    """
    feature_set.validate()
    missing = [c for c in feature_set.columns if c not in df.columns]
    if missing:
        raise KeyError(f"frame is missing feature columns: {missing}")
    raw = df.loc[:, list(feature_set.columns)].to_numpy(dtype=float, copy=True)
    centres = np.asarray(feature_set.centres, dtype=float)
    idx = np.isnan(raw)
    if idx.any():
        raw[idx] = np.take(centres, np.where(idx)[1])
    return feature_set.normalise(raw)


def build_one(values: dict, feature_set: FeatureSet) -> np.ndarray:
    """One sample, for live inference from the twin.

    Same constants, same order, same missing-value rule as :func:`build` --
    which is the reason this function lives beside it rather than in the
    serving code.
    """
    feature_set.validate()
    row = np.array(
        [
            values.get(c) if values.get(c) is not None else centre
            for c, centre in zip(feature_set.columns, feature_set.centres, strict=True)
        ],
        dtype=float,
    )
    return feature_set.normalise(row)


# ---------------------------------------------------------------------------
# Sequences for the recurrent models
# ---------------------------------------------------------------------------


def build_sequences(
    df,
    feature_set: FeatureSet,
    *,
    length: int = 30,
    stride: int = 1,
    label_columns: tuple[str, ...] = (),
):
    """Sliding windows that never cross an engine or a sortie boundary.

    THE TRAP THIS AVOIDS
    A naive sliding window over the frame would splice the last samples of one
    sortie onto the first samples of the next. Those two rows are 50 seconds
    apart on the clock and up to EIGHTEEN FLIGHT HOURS apart in the engine's
    life, so the window would present a step change in wear as if it happened
    within half a minute. The model would learn that discontinuity as the
    signature of a fault, score beautifully in training, and fire on every
    sortie boundary in service. Windows are therefore cut inside one
    (engine, sortie) group only.

    Returns ``(X, y, index)`` where ``X`` is (n, length, n_features), ``y`` is
    (n, len(label_columns)) taken from the LAST row of each window -- the
    prediction is about the present, not the middle of the window -- and
    ``index`` holds the frame row number of each window's last sample, so a
    prediction can be traced back to the sample it describes.
    """
    feature_set.validate()
    x_all = build(df, feature_set)
    labels = (
        df.loc[:, list(label_columns)].to_numpy(dtype=float)
        if label_columns
        else np.zeros((len(df), 0))
    )

    seqs: list[np.ndarray] = []
    ys: list[np.ndarray] = []
    idx_out: list[int] = []
    group_cols = ["engine_id", "sortie"] if "sortie" in df.columns else ["engine_id"]
    for _, pos in df.groupby(group_cols, sort=True).indices.items():
        pos = np.sort(pos)
        if len(pos) < length:
            continue
        for start in range(0, len(pos) - length + 1, stride):
            win = pos[start : start + length]
            seqs.append(x_all[win])
            ys.append(labels[win[-1]])
            idx_out.append(int(win[-1]))

    if not seqs:
        n_f = len(feature_set)
        return (
            np.zeros((0, length, n_f)),
            np.zeros((0, len(label_columns))),
            np.zeros(0, dtype=int),
        )
    return np.stack(seqs), np.stack(ys), np.asarray(idx_out, dtype=int)


def _manifest_split(manifest: dict) -> dict[int, str] | None:
    """The split the generator recorded, if it recorded one."""
    out: dict[int, str] = {}
    for eid_s, info in manifest.get("engines", {}).items():
        sp = info.get("split")
        if sp not in ("train", "val", "test"):
            return None
        out[int(eid_s)] = sp
    return out or None


def _covers_every_class(manifest: dict, assign: dict[int, str],
                        minimum: int = 1) -> bool:
    """Does every fault class appear in validation AND test?

    That is the property this module's stratifier exists to guarantee. Early
    stopping and threshold selection both run on validation, so a class absent
    there cannot be tuned for -- which is what made the ID-ordered split
    unusable in the first place.
    """
    seen: dict[str, set[str]] = {}
    for eid_s, info in manifest.get("engines", {}).items():
        split = assign.get(int(eid_s))
        for f in info.get("faults") or []:
            if not f.get("expressed", True):
                continue
            seen.setdefault(f["mode"], set()).add(split)
    modes = {f["mode"] for i in manifest.get("engines", {}).values()
             for f in (i.get("faults") or []) if f.get("expressed", True)}
    if not modes:
        return False
    return all({"val", "test"} <= seen.get(m, set()) for m in modes)


def stratified_engine_split(
    manifest: dict, *, n_val: int = 10, n_test: int = 10
) -> dict[int, str]:
    """Assign engines to train/val/test so every split covers the fault types.

    THE PROBLEM THIS FIXES
    PRD Part 0 section 0.5 requires the split to be BY ENGINE, and it must be --
    splitting by sample leaks an engine's own future into its training data.
    But it also names the engines by ID: train 1-80, val 81-90, test 91-100.
    Which engine got which ID is arbitrary, and on this fleet the arbitrary
    assignment left validation with **zero** examples of two fault classes:
    injector_abnormal is 10.3 % of training rows and 0 % of validation rows,
    overheating_trend 9.8 % and 0 %.

    That is not a cosmetic imbalance. Early stopping and threshold selection
    both run on validation, so a model that has become worse at the classes
    validation cannot see still looks like it is improving. Measured: training
    to convergence with the ID-ordered split produced a WORSE test model than
    stopping at eight epochs -- anomaly ROC-AUC 0.926 against 0.983 -- because
    validation loss was selecting for the wrong thing.

    The engine-level separation, which is the actual requirement, is untouched:
    no engine's samples appear in two splits. Only the arbitrary ID ordering is
    replaced, by stratifying on each engine's fault composition so all three
    splits look like the fleet. See docs/PRD_DEVIATIONS.md DEV-52.
    """
    engines = manifest["engines"]

    # IF THE GENERATED SPLIT ALREADY COVERS EVERY CLASS, HONOUR IT.
    #
    # This function exists to guarantee coverage, and it was written when the
    # generator left coverage to chance. The generator now DEALS the fault
    # modes round-robin within each split (DEV-94) and produces 60/20/20, so
    # the guarantee is already met at source -- and re-splitting here actively
    # undoes it, because the hardcoded n_val=n_test=10 halves the evaluation
    # fleet back to the very size DEV-94 was raised from.
    #
    # Measured on the current fleet: the generated split carries every one of
    # the eight classes in both validation and test, on 2-4 engines each, with
    # 20 engines a side. The re-split replaced that with 10 a side -- so five
    # of six training scripts were silently scoring on half the evidence the
    # dataset was built to provide.
    #
    # A split-fixing function whose fix makes the split worse should stand
    # down, so it does. The stratifier below remains for a fleet that has NOT
    # been dealt coverage at source.
    generated = _manifest_split(manifest)
    if generated is not None and _covers_every_class(manifest, generated):
        return generated

    # Group by fault signature. An engine's primary fault is the earliest one
    # it develops, which is what dominates its trajectory.
    groups: dict[str, list[int]] = {}
    for eid_s, info in engines.items():
        faults = info.get("faults") or []
        key = min(faults, key=lambda f: f["onset_hours"])["mode"] if faults else "none"
        groups.setdefault(key, []).append(int(eid_s))

    total = len(engines)
    want = {"test": n_test, "val": n_val}
    assigned: dict[int, str] = {}
    # Walk the groups largest first and take a proportional share of each for
    # test and val, so a rare fault class still reaches both.
    for split in ("test", "val"):
        remaining = want[split]
        for key in sorted(groups, key=lambda k: -len(groups[k])):
            pool = [e for e in sorted(groups[key]) if e not in assigned]
            if not pool or remaining <= 0:
                continue
            share = max(1, round(len(groups[key]) / total * want[split]))
            for e in pool[: min(share, remaining)]:
                assigned[e] = split
                remaining -= 1
        # Any shortfall is filled from whatever is left, largest group first.
        if remaining > 0:
            for key in sorted(groups, key=lambda k: -len(groups[k])):
                for e in sorted(groups[key]):
                    if e not in assigned and remaining > 0:
                        assigned[e] = split
                        remaining -= 1
    for eid_s in engines:
        assigned.setdefault(int(eid_s), "train")
    return assigned


FAULT_LABEL_COLUMNS: tuple[str, ...] = (
    "lab_misfire",
    "lab_injector_abnormal",
    "lab_cooling_degradation",
    "lab_lubrication_issue",
    "lab_sensor_drift",
    "lab_combustion_instability",
    "lab_overheating_trend",
    "lab_abnormal_vibration",
)


# ---------------------------------------------------------------------------
# What counts as "normal" for unsupervised training
# ---------------------------------------------------------------------------

# Fit only on data the engine itself certifies as healthy. PRD Part 2
# section 11.1 Tier 2: "Learns normal behavior from data" -- so the training
# set must contain no faults, or the detector learns to call them normal.
HEALTHY_CHI_ABOVE = 0.90
HEALTHY_MAX_FAULT = 0.02

# PRD Part 2 section 9.3 band table: 0.80 is the GOOD/FAIR boundary, where the
# recommended action changes from "none" to "monitor closely".
DEGRADED_CHI_BELOW = 0.80
FAULT_EXPRESSED_ABOVE = 0.20


def baseline_residuals(df, *, hours: float = 60.0, columns=None):
    """Subtract each engine's OWN early-life residual median.

    Manufacturing spread gives every engine a constant residual offset against
    the as-new reference model -- measured on this fleet, engine-mean oil
    pressure residual spans -25 to +1 psi with no fault present anywhere. A
    detector thresholded on the absolute residual therefore fires on whichever
    engines happen to sit at the edge of the build tolerance, and that is
    exactly what pushed the false-positive rate above target.

    What carries health information is the CHANGE in a residual from where that
    engine started, not its absolute value.

    This is not hindsight leakage: the deployed twin holds a running residual
    mean per engine from installation (``layer4_core.twin_state.Residual``), so
    the baseline is available in service from the first flight hours. Only data
    from the engine's own early life is used -- never anything from its future,
    and never anything from another engine.
    """
    cols = list(columns) if columns is not None else [c for c, _ in RESIDUALS]
    out = df.copy()
    for _, idx in df.groupby("engine_id", sort=True).indices.items():
        idx = np.sort(idx)
        early = idx[df["flight_hours"].to_numpy()[idx] <= hours]
        if len(early) < 20:
            early = idx[: max(20, len(idx) // 20)]
        for c in cols:
            if c not in out.columns:
                continue
            base = np.nanmedian(df[c].to_numpy()[early])
            if np.isfinite(base):
                vals = np.array(out[c].to_numpy(), dtype=float, copy=True)
                vals[idx] = vals[idx] - base
                out[c] = vals
    return add_structured_residual_features(out)


# Spread of each baselined residual on a HEALTHY engine, measured on this
# fleet. Fixed constants rather than statistics of whatever frame is passed:
# normalising by the current split's own spread would give train and test
# different feature definitions.
_RESIDUAL_SCALE: dict[str, float] = {
    "res_cht": 2.896,
    "res_coolant": 1.026,
    "res_egt": 20.619,
    "res_oil_pressure": 11.418,
    "res_oil_temperature": 0.903,
    "res_fuel_flow": 1.078,
    "res_manifold_pressure": 0.031,
}


def add_structured_residual_features(df):
    """The FDI structured-residual SIGNATURE, not just the magnitudes.

    Classical fault detection isolates a SENSOR fault from a PROCESS fault by
    the PATTERN of which residuals move, not by how far any one of them moves:
    a residual bank in which each element is insensitive to one fault and
    sensitive to others gives every fault a distinct signature. Our bank is
    already structured that way -- each residual is one channel measured
    against the physics -- but nothing computed the signature, so the network
    saw seven magnitudes and no relationship between them.

    That gap is measurable. A drifting instrument moves ONE residual; a real
    process fault moves the physically coupled set. Measured on pure
    single-fault engines, the residual belonging to the drifting channel was
    the largest in only 2 of 14 cases, and drift isolation (0.43) sat BELOW
    every process fault (0.80-1.58) and barely above healthy (0.23).

    Three signature features, none of which any single residual carries:

      res_isolation      how far the largest excursion stands above the next.
                         One channel alone is sensor-like; a coupled set is
                         process-like.
      res_n_excursions   how many residuals are outside 2 sigma at once.
      res_top_abs        the size of the largest excursion, so isolation is
                         read against a magnitude rather than in a vacuum.

    Computed here rather than in the generator so it needs no regeneration,
    and AFTER baselining, because an isolation measured on residuals that
    still carry each engine's build offset would mostly describe the build.
    """
    import numpy as np

    cols = [c for c in _RESIDUAL_SCALE if c in df.columns]
    if len(cols) < 3:
        return df
    out = df.copy()
    z = np.abs(np.column_stack([
        out[c].to_numpy(dtype=float) / _RESIDUAL_SCALE[c] for c in cols
    ]))
    z = np.nan_to_num(z, nan=0.0, posinf=0.0, neginf=0.0)
    part = np.partition(z, -2, axis=1)
    top, second = part[:, -1], part[:, -2]
    out["res_isolation"] = top - second
    out["res_n_excursions"] = (z > 2.0).sum(axis=1).astype(float)
    out["res_top_abs"] = top
    out = add_egt_scatter(out)
    return out


EGT_SCATTER_WINDOW_S = 60.0


# Rough running is SCATTER, and scatter has to be measured on every channel
# that carries it.
#
# The exhaust residual was the only one measured, and combustion_instability
# still scored 0.372 on the 200-engine fleet. Measured on the test engines, the
# exhaust scatter separates the class at AUC 0.599 -- but the simulator also
# injects a 30 rpm speed scatter for the same fault (engine_sim: "rough running
# is cycle-to-cycle variation in each cylinder's burn... and on speed") and
# NOTHING measured it. Speed scatter alone reaches AUC 0.707, and the scatter of
# the cross-cylinder exhaust spread 0.736, because the per-cylinder variation is
# independent and taking a max across cylinders suppresses exactly what the
# spread preserves.
#
# All three are the same quantity on three signals, so they share one
# implementation rather than three that can drift apart.
SCATTER_SOURCES: tuple[tuple[str, str], ...] = (
    ("res_egt", "egt_scatter"),
    ("rpm", "rpm_scatter"),
    ("egt_spread", "egt_spread_scatter"),
)


def rolling_scatter(df, source: str, name: str,
                    window_s: float = EGT_SCATTER_WINDOW_S):
    """Standard deviation of ``source`` over the last ``window_s``, per engine.

    Defined in TIME, not rows, because the dataset steps at 1 s and the twin at
    0.5 s, and a window measured in samples would be two different features.
    """
    import numpy as np
    import pandas as pd

    if source not in df.columns:
        return df
    out = df if name in df.columns else df.copy()
    if "engine_id" not in out.columns or "t_s" not in out.columns:
        out[name] = out[source].rolling(60, min_periods=10).std()
        return out
    scatter = np.full(len(out), np.nan)
    res = out[source].to_numpy(dtype=float)
    t = out["t_s"].to_numpy()
    for _, idx in out.groupby("engine_id", sort=False).indices.items():
        idx = np.sort(idx)
        step = float(np.median(np.diff(t[idx]))) if len(idx) > 2 else 1.0
        n = max(int(round(window_s / max(step, 1e-6))), 5)
        series = pd.Series(res[idx])
        scatter[idx] = series.rolling(n, min_periods=max(5, n // 6)).std().to_numpy()
    out[name] = scatter
    return out


def add_egt_scatter(df, window_s: float = EGT_SCATTER_WINDOW_S):
    """Every scatter feature the contract carries, on one pass of the frame.

    Kept under its original name because the training scripts call it that; it
    now adds all of SCATTER_SOURCES rather than the exhaust one alone.
    """
    out = df
    for source, name in SCATTER_SOURCES:
        out = rolling_scatter(out, source, name, window_s)
    return out


def structured_residuals_one(residuals: dict) -> dict:
    """The same three signature features, for ONE live sample.

    Lives beside the batch version and shares `_RESIDUAL_SCALE` with it for the
    same reason `build_one` lives beside `build`: a serving path that
    re-implements a training feature with its own constants is a train/serve
    skew waiting to be discovered in the field.
    `test_structured_residuals_one_matches_the_batch_version` asserts the two
    agree, so the duplication is checked rather than trusted.

    Expects residuals ALREADY BASELINED, as the batch version does -- an
    isolation measured on residuals still carrying an engine's build offset
    mostly describes the build.
    """
    import numpy as np

    present = [c for c in _RESIDUAL_SCALE if residuals.get(c) is not None]
    if len(present) < 3:
        return {"res_isolation": 0.0, "res_n_excursions": 0.0, "res_top_abs": 0.0}
    z = np.abs(np.array(
        [float(residuals[c]) / _RESIDUAL_SCALE[c] for c in present], dtype=float
    ))
    z = np.nan_to_num(z, nan=0.0, posinf=0.0, neginf=0.0)
    part = np.partition(z, -2)
    return {
        "res_isolation": float(part[-1] - part[-2]),
        "res_n_excursions": float((z > 2.0).sum()),
        "res_top_abs": float(part[-1]),
    }


def healthy_mask(df) -> np.ndarray:
    """Rows from a genuinely healthy engine -- the unsupervised training set.

    Both conditions are needed. A high composite health index alone is not
    enough, because a fault that has just begun barely moves the composite --
    and those are exactly the rows that would teach the detector to ignore
    early faults, which is the only kind worth detecting.
    """
    return (
        (df["chi_true"] >= HEALTHY_CHI_ABOVE)
        & (df["any_fault"] <= HEALTHY_MAX_FAULT)
    ).to_numpy()


def anomaly_mask(df) -> np.ndarray:
    """Rows the detector SHOULD fire on.

    An expressed fault, or an engine that has degraded past the GOOD/FAIR
    boundary of PRD Part 2 section 9.3 whatever the cause.

    Scoring only against injected faults would be wrong in a way that quietly
    punishes a correct detector: an engine at CHI 0.65 from ordinary wear is
    genuinely not healthy, and flagging it is the right answer, not a false
    positive. The problem statement asks for degradation TRACKING, not fault
    spotting alone.
    """
    return (
        (df["any_fault"] >= FAULT_EXPRESSED_ABOVE)
        | (df["chi_true"] <= DEGRADED_CHI_BELOW)
    ).to_numpy()


def ambiguous_mask(df) -> np.ndarray:
    """Neither clearly healthy nor clearly degraded.

    Excluded from precision/recall rather than assigned to whichever class
    makes the numbers look better. Both choices would be defensible and both
    would be arguable, so the honest thing is to report the count and leave
    them out.
    """
    return ~healthy_mask(df) & ~anomaly_mask(df)
