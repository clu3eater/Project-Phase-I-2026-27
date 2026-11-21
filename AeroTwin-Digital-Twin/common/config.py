"""Configuration loading for the digital twin.

Decision D6 (docs/prd/PROJECT_PLAN.md): every threshold and physical constant lives in
``configs/*.yaml``. Nothing in this repository may hard-code a limit, a weight
or an engine dimension. This module is the only sanctioned way to read them.

Adding an engine to the fleet is therefore a new YAML file and a new twin
registry entry -- zero code change (PRD Part 1 section 2.4, section 6.3).
"""

from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any

import yaml


def repo_root() -> Path:
    """Absolute path of the repository root.

    Resolved from this file's location so that the system behaves identically
    whether it is launched from the repo root, from a service directory, or
    from inside a container.
    """
    return Path(__file__).resolve().parent.parent


def config_dir() -> Path:
    """Directory holding the YAML configuration tree.

    Overridable with ``DT_CONFIG_DIR`` so a deployment can point at a
    site-specific configuration set without touching the image.
    """
    override = os.environ.get("DT_CONFIG_DIR")
    return Path(override) if override else repo_root() / "configs"


def data_dir() -> Path:
    override = os.environ.get("DT_DATA_DIR")
    return Path(override) if override else repo_root() / "data"


class ConfigError(RuntimeError):
    """Raised when a configuration file is missing, malformed or incomplete."""


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"configuration file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh)
    if not isinstance(loaded, dict):
        raise ConfigError(f"configuration file is not a mapping: {path}")
    return loaded


@functools.cache
def load_thresholds() -> dict[str, Any]:
    """Alert thresholds, health-index parameters, detector tuning and security.

    The file is written for the reference engine. The ACTIVE engine may carry a
    ``thresholds_override:`` section, laid over it key by key: a diesel that
    vibrates harder than the Rotax by design must not raise a vibration warning
    and score mechanical health 0.56 on the day it is installed.
    """
    cfg = _load_yaml(config_dir() / "thresholds.yaml")
    try:
        over = load_engine(active_engine()).get("thresholds_override")
    except Exception:  # noqa: BLE001 - reported by validate(), not here
        # An unloadable engine (missing, malformed YAML, broken `extends:`) is
        # reported by validate(), which names it; the thresholds themselves
        # must still load for that report to be made.
        over = None
    if isinstance(over, dict) and over:
        cfg = _deep_merge(cfg, over)
    _validate_thresholds(cfg)
    return cfg


# The engine of the aircraft the ground station has loaded. Set by the station
# each time it loads an aircraft, so the alert limits and health bands are the
# ones for THAT aircraft's engine; every aircraft carries its own engine type
# (configs/fleet.yaml).
_runtime_engine: str | None = None


def active_engine() -> str:
    """The engine whose limits apply now.

    The aircraft loaded on the ground station first; otherwise ``DT_ENGINE``
    (for scripts and tools run outside the station); otherwise the reference.
    """
    if _runtime_engine:
        return _runtime_engine
    env = os.environ.get("DT_ENGINE", "").strip()
    return env or REFERENCE_ENGINE


def set_runtime_engine(engine_key: str | None) -> None:
    """The station loaded an aircraft with this engine: its limits apply now."""
    global _runtime_engine
    if engine_key is not None and engine_key not in available_engines():
        raise ConfigError(f"no engine definition '{engine_key}'")
    if engine_key != _runtime_engine:
        _runtime_engine = engine_key
        clear_cache()


@functools.cache
def load_checklists() -> dict[str, Any]:
    """Abnormal and emergency procedures, one per alert (configs/checklists.yaml).

    Validated here rather than trusted: a procedure with no steps, or a step
    with no action, would put an empty checklist in front of an operator at
    the moment they need it most.
    """
    cfg = _load_yaml(config_dir() / "checklists.yaml")
    procs = cfg.get("procedures")
    if not isinstance(procs, list) or not procs:
        raise ConfigError("checklists.yaml: no procedures")
    seen: set[str] = set()
    for p in procs:
        pid = p.get("id")
        if not pid or pid in seen:
            raise ConfigError(f"checklists.yaml: missing or duplicate id {pid!r}")
        seen.add(pid)
        if not p.get("title") or not p.get("legends"):
            raise ConfigError(f"checklists.yaml: {pid} needs a title and legends")
        for phase in ("airborne", "ground"):
            steps = p.get(phase)
            if not isinstance(steps, list) or not steps:
                raise ConfigError(f"checklists.yaml: {pid} has no {phase} steps")
            for st in steps:
                if not isinstance(st, dict) or not str(st.get("do", "")).strip():
                    raise ConfigError(f"checklists.yaml: {pid} has a {phase} step with no action")
    return cfg


def checklist_for(legend: str) -> dict[str, Any] | None:
    """The procedure that answers an alert legend, or None."""
    import fnmatch

    for p in load_checklists()["procedures"]:
        if any(fnmatch.fnmatchcase(legend, pat) for pat in p["legends"]):
            return p
    return None


@functools.cache
def load_report_identity() -> dict[str, Any]:
    """Who and where this ground station is, for the report cover.

    A property of the DEPLOYMENT, not of the flight. A second ground station
    at another site runs the same binary and must not export a report claiming
    to have come from this one.
    """
    return dict(load_thresholds().get("report", {}) or {})


# The engine every other definition is measured against. Its key tree is the
# de-facto schema: the running code indexes those keys without defaults.
REFERENCE_ENGINE = "rotax_915is"


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """``over`` laid on ``base``: mappings merge key by key, anything else
    (a number, a list, ``null``) replaces the base value outright."""
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _load_engine_raw(engine_key: str, chain: tuple[str, ...] = ()) -> dict[str, Any]:
    """An engine file with its ``extends:`` parents resolved.

    ADDING AN ENGINE USED TO MEAN COPYING ALL 600 LINES OF THE ROTAX FILE.
    The one other definition shipped, the Austro stub, had not: it carried the
    sections its author thought of and passed the section check, then died on
    the first physics tick with ``KeyError: 'rail_pressure_bar'`` -- 62 keys
    short. ``extends: <engine>`` lets a new file state only what differs and
    inherit the rest, so a new engine is complete by construction and the
    file reads as the list of ways it differs from the base.
    """
    if engine_key in chain:
        raise ConfigError(
            f"engine 'extends' chain loops: {' -> '.join((*chain, engine_key))}")
    cfg = _load_yaml(config_dir() / "engines" / f"{engine_key}.yaml")
    parent = cfg.pop("extends", None)
    if parent:
        base = _load_engine_raw(str(parent), (*chain, engine_key))
        lineage = [str(parent), *base.pop("extends_chain", [])]
        cfg = _deep_merge(base, cfg)
        cfg["extends_chain"] = lineage
    return cfg


@functools.cache
def load_engine(engine_key: str = REFERENCE_ENGINE) -> dict[str, Any]:
    """Engine definition. ``engine_key`` is the file stem under configs/engines/.

    A file may name a parent with ``extends: <engine_key>``; see
    ``_load_engine_raw``.
    """
    cfg = _load_engine_raw(engine_key)
    _validate_engine(cfg, engine_key)
    return cfg


def available_engines() -> list[str]:
    """File stems of every engine definition present -- the fleet's engine catalogue.

    Files whose name starts with ``_`` (the template) are not engines.
    """
    return sorted(p.stem for p in (config_dir() / "engines").glob("*.yaml")
                  if not p.stem.startswith("_"))


def _key_paths(node: Any, prefix: str = "") -> set[str]:
    out: set[str] = set()
    if isinstance(node, dict):
        for k, v in node.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            out.add(path)
            out |= _key_paths(v, path)
    return out


def check_engine(engine_key: str) -> list[str]:
    """Every problem that would stop this engine running, as sentences.

    Empty means usable. The reference engine's key tree is the schema: any
    key it has and this one lacks is reported (children of a missing section
    are folded into the section). Checked at startup, and shown in the console
    before an engine can be selected, so a gap is named on the ground instead
    of surfacing as a KeyError inside a physics tick.
    """
    try:
        eng = load_engine(engine_key)
    except Exception as exc:  # noqa: BLE001 - reported as a problem
        return [str(exc)]
    if engine_key == REFERENCE_ENGINE:
        return []
    ref = load_engine(REFERENCE_ENGINE)
    have = _key_paths(eng)
    # Optional: a section explicitly set to null opts out (no performance
    # table, for instance), and so does everything under it.
    nulled = {p for p in have if _get_path(eng, p) is None}
    missing = sorted(_key_paths(ref) - have)
    missing = [m for m in missing
               if not any(m == n or m.startswith(n + ".") for n in nulled)]
    top = [m for m in missing if not any(m.startswith(o + ".") for o in missing)]
    return [f"missing key '{m}' (present in {REFERENCE_ENGINE}; add it, or put "
            f"'extends: {REFERENCE_ENGINE}' at the top of the file)" for m in top]


def _get_path(cfg: dict[str, Any], dotted: str) -> Any:
    node: Any = cfg
    for part in dotted.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    return node


def engine_catalogue() -> list[dict[str, Any]]:
    """What the console lists: each engine, its name, and whether it runs."""
    out = []
    for key in available_engines():
        problems = check_engine(key)
        ident: dict[str, Any] = {}
        chain: list[str] = []
        try:
            eng = load_engine(key)
            ident = dict(eng.get("identity", {}) or {})
            chain = list(eng.get("extends_chain", []))
        except Exception:  # noqa: BLE001 - already in problems
            pass
        out.append({
            "key": key,
            "display_name": str(ident.get("display_name") or key),
            "engine_type": str(ident.get("engine_type") or ""),
            "ignition": str(ident.get("ignition") or ""),
            # Absent means the manufacturer-data reference; only an explicit
            # `validated: false` marks a stub.
            "validated": ident.get("validated", True) is not False,
            "extends": chain,
            "usable": not problems,
            "problems": problems,
        })
    return out


def dbc_path(engine: dict[str, Any] | None = None) -> Path:
    """Absolute path to the CAN database referenced by an engine definition."""
    engine = engine or load_engine()
    rel = engine.get("can", {}).get("dbc", "configs/can/engine.dbc")
    candidate = Path(rel)
    return candidate if candidate.is_absolute() else repo_root() / rel


class _Missing:
    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<missing>"


_MISSING = _Missing()


def get(cfg: dict[str, Any], dotted: str, default: Any = _MISSING) -> Any:
    """Read ``cfg`` by dotted path, e.g. ``get(t, "parameters.cht.alert_max")``.

    Raises rather than silently returning ``None`` when a key is absent and no
    default is supplied: a missing threshold must fail loudly at start-up, not
    quietly disable an alert at 20,000 ft.
    """
    node: Any = cfg
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            if default is _MISSING:
                raise ConfigError(f"missing configuration key: {dotted}")
            return default
        node = node[part]
    return node


# ----------------------------------------------------------------------------
# Validation. These run at import/first-use so that a malformed configuration
# is caught on the ground rather than in flight.
# ----------------------------------------------------------------------------

_REQUIRED_PARAMETERS = (
    "rpm",
    "cht",
    "egt",
    "oil_pressure",
    "oil_temperature",
    "fuel_flow",
    "vibration_rms",
    "battery_voltage",
    "injection_timing",
    # Not named in the problem statement but inseparable from it: on a FADEC
    # engine "injection timing parameters" only mean something alongside the
    # injection period and the ignition schedule they are scheduled with.
    "injection_period",
    "ignition_timing",
)

_REQUIRED_FAULTS = (
    "misfire",
    "injector_abnormal",
    "cooling_degradation",
    "lubrication_issue",
    "sensor_drift",
    "combustion_instability",
    "overheating_trend",
    "abnormal_vibration",
)


def _validate_thresholds(cfg: dict[str, Any]) -> None:
    params = cfg.get("parameters", {})
    missing = [p for p in _REQUIRED_PARAMETERS if p not in params]
    if missing:
        raise ConfigError(
            "thresholds.yaml is missing required monitored parameters "
            f"(problem statement section B): {missing}"
        )

    faults = cfg.get("faults", {})
    missing_faults = [f for f in _REQUIRED_FAULTS if f not in faults]
    if missing_faults:
        raise ConfigError(
            "thresholds.yaml is missing required fault definitions "
            f"(problem statement section C): {missing_faults}"
        )

    weights = cfg.get("health", {}).get("composite_weights", {})
    total = sum(float(v) for v in weights.values())
    if abs(total - 1.0) > 1e-9:
        raise ConfigError(
            f"health.composite_weights must sum to 1.0 (PRD Part 2 section 9.3), got {total}"
        )

    levels = cfg.get("alert_levels", [])
    if [lvl.get("level") for lvl in levels] != [1, 2, 3, 4, 5]:
        raise ConfigError("alert_levels must define exactly levels 1..5 in order")

    # Every parameter must expose a plausibility band, otherwise the sensor
    # validation of PRD Part 1 section 8.3 silently degrades to a no-op.
    for name, spec in params.items():
        if "plausible_range" not in spec and "range" not in spec:
            raise ConfigError(f"parameter '{name}' has neither plausible_range nor range")


_REQUIRED_ENGINE_SECTIONS = (
    "identity",
    "geometry",
    "ratings",
    "fuel_properties",
    "thermodynamics",
    "intake",
    "thermal",
    "exhaust",
    "oil_system",
    "vibration",
    "electrical",
    "degradation",
)


def _validate_engine(cfg: dict[str, Any], key: str) -> None:
    missing = [s for s in _REQUIRED_ENGINE_SECTIONS if s not in cfg]
    if missing:
        raise ConfigError(f"engine '{key}' is missing required sections: {missing}")

    ignition = cfg["identity"].get("ignition")
    if ignition not in {"SPARK", "COMPRESSION"}:
        raise ConfigError(
            f"engine '{key}': identity.ignition must be SPARK or COMPRESSION, got {ignition!r}. "
            "This field selects the combustion sub-model (PRD Part 1 section 1.2)."
        )

    geom = cfg["geometry"]
    if geom["cylinders"] < 1 or geom["displacement_total_L"] <= 0:
        raise ConfigError(f"engine '{key}': implausible geometry")


def clear_cache() -> None:
    """Drop cached configuration -- used by tests and by runtime config reload."""
    load_thresholds.cache_clear()
    load_report_identity.cache_clear()
    load_checklists.cache_clear()
    load_engine.cache_clear()


# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------


# Sections the running system reads. A missing one used to surface as a
# KeyError deep inside a physics tick, minutes after start and far from the
# cause; a config fault should refuse to start and name the key instead.
_REQUIRED_THRESHOLD_SECTIONS = (
    "parameters", "alert_levels", "alerting", "detectors", "faults",
    "fusion", "health", "pipeline", "rul", "security", "advisory",
    "feature_norm", "schema_version",
)
# Parameters the alert engine and the twin read by name, with the sub-keys
# each one is indexed by elsewhere in the code.
_REQUIRED_PARAMETERS = {
    "oil_pressure": ("high_speed_min_psi", "low_speed_min_psi",
                     "low_speed_rpm", "unit"),
    "cht": ("unit",),
    "egt": ("unit",),
    "oil_temperature": ("unit",),
    "rpm": ("unit",),
    "fuel_flow": ("unit",),
}


def validate(engine_key: str = "rotax_915is") -> None:
    """Fail fast, and say which key.

    Called at startup. Every check here corresponds to something the running
    code indexes without a default, so a failure means the system WOULD have
    raised later at a less useful moment.
    """
    problems: list[str] = []

    try:
        thr = load_thresholds()
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        raise ConfigError(f"cannot load thresholds.yaml: {exc}") from exc
    try:
        eng = load_engine(engine_key)
    except Exception as exc:  # noqa: BLE001
        raise ConfigError(f"cannot load engine '{engine_key}': {exc}") from exc
    problems += [f"engine '{engine_key}': {p}" for p in check_engine(engine_key)]

    for sect in _REQUIRED_THRESHOLD_SECTIONS:
        if sect not in thr:
            problems.append(f"thresholds.yaml is missing section '{sect}'")
    # Engine sections are NOT re-checked here. `load_engine()` already runs
    # `_validate_engine()` above, and that list is deliberately narrower --
    # engine configs are not interchangeable in shape. The Austro AE330 is a
    # turbo-diesel and correctly has no `ignition_system` section, so a
    # one-size list would refuse a perfectly valid engine. Reaching this line
    # at all means load_engine() was satisfied.

    params = thr.get("parameters", {})
    for name, keys in _REQUIRED_PARAMETERS.items():
        if name not in params:
            problems.append(f"thresholds parameters is missing '{name}'")
            continue
        for k in keys:
            if k not in params[name]:
                problems.append(f"thresholds parameters.{name} is missing '{k}'")

    # The oil-pressure limits are rpm-dependent, and getting the two the wrong
    # way round produced a false exceedance on every clean sortie (DEV-143).
    op = params.get("oil_pressure", {})
    lo, hi = op.get("low_speed_min_psi"), op.get("high_speed_min_psi")
    if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and lo >= hi:
        problems.append(
            f"parameters.oil_pressure.low_speed_min_psi ({lo}) must be BELOW "
            f"high_speed_min_psi ({hi}); the low-rpm limit is the looser one"
        )

    if problems:
        raise ConfigError(
            "configuration is not usable:\n  - " + "\n  - ".join(problems)
        )
