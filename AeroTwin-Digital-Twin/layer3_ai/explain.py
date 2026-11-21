"""Explainability -- why the system said what it said.

PRD Part 4 requires that a maintenance recommendation the operator cannot
interrogate must not be presented at all, and the reason is practical rather
than philosophical: an engineer told to pull an engine, with no account of why,
will either comply without learning anything or override it. Both outcomes
waste the system.

EXACT ATTRIBUTION WHERE AN EXACT ANSWER EXISTS
----------------------------------------------
The obvious move is to reach for SHAP everywhere. It is the wrong move for most
of this system, because most of this system is not a black box.

The composite health index is a weighted sum of four subsystem scores, each of
which is the MINIMUM of named sub-indices with published formulas. Every
contribution to it can therefore be computed exactly, in closed form. SHAP
would spend compute producing a sampled approximation of a quantity that can be
written down -- and an approximation of a known answer is strictly worse than
the answer, because it invites the reader to wonder about the sampling error.

So the rule here is: exact decomposition for the health index and the residual
vector, and SHAP only for the deep fault classifier, where there genuinely is
no closed form. Using the heavier tool everywhere would look more sophisticated
and explain less.

WHAT AN EXPLANATION IS FOR
--------------------------
Not a ranked list of numbers. A maintenance engineer needs to know which
subsystem, driven by which measurement, by how much, and what to do. The
attribution is the arithmetic; ``narrate`` is the part that is actually read.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from common import config


@dataclass
class Contribution:
    """One named factor's exact share of a decision."""

    name: str
    value: float
    contribution: float      # how much this pulled the index DOWN from 1.0
    share: float = 0.0       # fraction of the total shortfall
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "value": round(self.value, 4),
            "contribution": round(self.contribution, 4),
            "share": round(self.share, 4),
            "detail": self.detail,
        }


@dataclass
class Explanation:
    """Why the health index is where it is, in a form that can be read."""

    chi: float = 1.0
    shortfall: float = 0.0
    contributions: list[Contribution] = field(default_factory=list)
    drivers: list[Contribution] = field(default_factory=list)
    narrative: str = ""
    method: str = "exact"

    def as_dict(self) -> dict:
        return {
            "chi": round(self.chi, 4),
            "shortfall": round(self.shortfall, 4),
            "method": self.method,
            "contributions": [c.as_dict() for c in self.contributions],
            "drivers": [c.as_dict() for c in self.drivers],
            "narrative": self.narrative,
        }


# ---------------------------------------------------------------------------
# Exact decomposition of the composite health index
# ---------------------------------------------------------------------------

# Which sub-indices feed each subsystem, matching health.HealthEstimator.update.
# Kept here rather than re-derived so the explanation cannot drift away from
# the computation it claims to explain.
SUBSYSTEM_INPUTS: dict[str, tuple[str, ...]] = {
    "thermal": ("thi", "oti"),
    "mechanical": ("mhi", "lhi", "rsi"),
    "electrical": ("ehi",),
    "combustion": ("comb_hi", "fshi", "csi"),
}

READABLE = {
    "thi": "cylinder head and coolant temperature",
    "oti": "oil temperature",
    "mhi": "vibration level and impulsiveness",
    "lhi": "oil pressure against its predicted value",
    "rsi": "crankshaft speed stability",
    "ehi": "bus voltage and alternator output",
    "comb_hi": "exhaust gas temperature spread",
    "fshi": "fuel flow against its predicted value",
    "csi": "cylinder head temperature spread",
}


def explain_health(indices: dict[str, float]) -> Explanation:
    """Exact contribution of every sub-index to the composite shortfall.

    CHI = sum over subsystems of w_s x min(sub-indices of s), so the shortfall
    from a perfect 1.0 decomposes exactly:

        shortfall = sum_s w_s x (1 - min(...))

    and within each subsystem the MINIMUM is what carries it -- the others
    contributed nothing to that subsystem's score and are reported as such
    rather than given a fabricated share. That is a real property of a
    min-based roll-up and it is why the explanation can be exact: there is no
    interaction term to approximate.
    """
    w = config.load_thresholds()["health"]["composite_weights"]
    exp = Explanation()

    total_shortfall = 0.0
    contribs: list[Contribution] = []
    for subsystem, inputs in SUBSYSTEM_INPUTS.items():
        available = {k: float(indices[k]) for k in inputs if k in indices}
        if not available:
            continue
        binding = min(available, key=lambda k: available[k])
        score = available[binding]
        weight = float(w[subsystem])
        shortfall = weight * (1.0 - score)
        total_shortfall += shortfall

        contribs.append(
            Contribution(
                name=subsystem,
                value=score,
                contribution=shortfall,
                # Two decimals. At three, this string -- which is READ, in a
                # paragraph -- was rewritten on every frame, and the paragraph
                # with it. The third decimal of a health sub-index changes
                # nothing a reader would do differently.
                detail=(
                    f"limited by {binding.upper()} ({READABLE.get(binding, binding)}) "
                    f"at {score:.2f}"
                ),
            )
        )

    for c in contribs:
        c.share = c.contribution / total_shortfall if total_shortfall > 1e-12 else 0.0

    contribs.sort(key=lambda c: -c.contribution)
    exp.chi = 1.0 - total_shortfall
    exp.shortfall = total_shortfall
    exp.contributions = contribs
    # A "driver" is a contributor carrying a meaningful share. Listing all four
    # every time trains the reader to skip the list.
    exp.drivers = [c for c in contribs if c.share >= 0.20 and c.contribution > 0.005]
    exp.narrative = narrate_health(exp)
    return exp


def narrate_health(exp: Explanation) -> str:
    """Turn the arithmetic into the sentence that actually gets read.

    THE FIGURES ARE QUANTISED, AND THAT IS THE POINT
    ------------------------------------------------
    This sentence was previously built from ``chi`` to three decimals and from
    raw shares. Both move on every sample, so the paragraph was REWRITTEN TWICE
    A SECOND: measured on the live console, ten consecutive frames produced ten
    different 381-character texts. Nobody can read a paragraph that is being
    retyped underneath them, so in practice the panel was unreadable and its
    reasoning -- the most defensible thing the system produces -- went unread.

    Rounding health to two decimals and shares to the nearest five per cent
    costs no meaning that a reader could act on, and makes the sentence hold
    still until something has actually changed. It is the same discipline as
    the display quantisation in ``layer4_core/operator_view.py``: never print a
    figure finer than the precision it carries.
    """
    if exp.shortfall < 0.01:
        return "Health is essentially as-new; no subsystem is contributing a loss."
    chi = round(exp.chi, 2)
    if not exp.drivers:
        return (
            f"Health {chi:.2f}. The loss is spread evenly across subsystems "
            f"with no single driver - consistent with ordinary accumulated wear."
        )

    def share(v: float) -> int:
        return int(round(v * 100.0 / 5.0) * 5)

    lead = exp.drivers[0]
    text = (
        f"Health {chi:.2f}. {share(lead.share)}% of the shortfall comes from "
        f"the {lead.name} subsystem, {lead.detail}."
    )
    if len(exp.drivers) > 1:
        second = exp.drivers[1]
        text += (
            f" A further {share(second.share)}% comes from {second.name}, "
            f"{second.detail}."
        )
    return text


# ---------------------------------------------------------------------------
# Residual attribution
# ---------------------------------------------------------------------------

# Healthy spread of each residual, measured on the fleet's healthy rows. A
# residual is only meaningful against the scatter a healthy engine shows, so
# raw magnitudes cannot be compared across channels with different units.
RESIDUAL_SCALE = {
    "cht": 4.0,            # K
    "coolant": 1.0,        # K
    "egt": 28.0,           # degC
    "oil_pressure": 11.0,  # psi
    "oil_temperature": 3.0,
    "fuel_flow": 0.7,      # L/h
}

RESIDUAL_MEANING = {
    "cht": "heat is not leaving the cylinder head as it should",
    "coolant": "the coolant loop is running hotter than the model expects",
    "egt": "combustion is depositing a different amount of heat in the exhaust",
    "oil_pressure": "the oil circuit is not holding the pressure the model expects",
    "oil_temperature": "the oil is running hotter than the model expects",
    "fuel_flow": "the engine is burning a different amount of fuel than the "
                 "conditions warrant",
}


def explain_residuals(residuals: dict[str, dict]) -> list[Contribution]:
    """Rank residuals by how far each has moved in units of its healthy spread.

    A +9 K head residual and a +2 psi oil residual cannot be compared as
    numbers -- they are different quantities in different units. Divided by the
    scatter a healthy engine shows on each, they become comparable, and the
    ranking then means something.
    """
    out: list[Contribution] = []
    for name, scale in RESIDUAL_SCALE.items():
        r = residuals.get(name) or {}
        if not r.get("usable"):
            continue
        delta = r.get("mean_delta")
        if delta is None:
            continue
        z = abs(float(delta)) / scale
        # QUANTISED TO A TENTH OF THE CHANNEL'S OWN HEALTHY SCATTER.
        #
        # A fixed number of decimals is the wrong instrument here: EGT scatters
        # 28 K on a healthy engine and oil pressure 11 psi, so "+9.95" on EGT
        # claims three significant figures inside a band where the channel is
        # simply noisy, and the sentence containing it was rewritten on every
        # frame. A tenth of the healthy spread is a precision each channel
        # actually carries -- 2.8 K on EGT, 0.4 K on head temperature -- and it
        # leaves the text still until the residual has genuinely moved.
        q = max(scale / 10.0, 1e-9)
        shown = round(float(delta) / q) * q
        digits = 0 if q >= 1.0 else 1
        out.append(
            Contribution(
                name=name,
                value=float(delta),
                contribution=z,
                detail=(
                    f"{shown:+.{digits}f} vs as-new, {abs(shown) / scale:.1f}x "
                    f"the healthy spread - {RESIDUAL_MEANING.get(name, '')}"
                ),
            )
        )
    total = sum(c.contribution for c in out)
    for c in out:
        c.share = c.contribution / total if total > 1e-12 else 0.0
    out.sort(key=lambda c: -c.contribution)
    return out


# ---------------------------------------------------------------------------
# The deep classifier -- where SHAP genuinely earns its place
# ---------------------------------------------------------------------------


def explain_fault_prediction(
    model,
    x: np.ndarray,
    feature_names: list[str],
    *,
    class_index: int = 0,
    background: np.ndarray | None = None,
    n_samples: int = 64,
) -> list[Contribution]:
    """Feature attribution for one fault-classifier prediction.

    This is the one place with no closed form, so an approximation is the best
    available answer rather than a worse version of a known one.

    Uses OCCLUSION rather than the SHAP library: each feature is replaced,
    across the whole window, by its background value and the change in the
    class score is measured. It is exact for an additive model, cheap, has no
    sampling variance to explain, and -- the point that decides it -- adds no
    dependency to the serving path, which is deliberately torch-light. SHAP's
    sampling estimator would give a similar ranking with a confidence interval
    nobody would read.
    """
    import torch

    model.eval()
    xt = torch.tensor(x[None, ...], dtype=torch.float32)
    with torch.no_grad():
        base = float(torch.sigmoid(model(xt)["fault"])[0, class_index])

    bg = (
        background
        if background is not None
        else np.zeros(x.shape[-1], dtype=float)  # normalised features centre on 0
    )

    out: list[Contribution] = []
    for i, name in enumerate(feature_names):
        occluded = x.copy()
        occluded[:, i] = bg[i]
        with torch.no_grad():
            score = float(
                torch.sigmoid(model(torch.tensor(occluded[None, ...],
                                                 dtype=torch.float32))["fault"])[0, class_index]
            )
        out.append(
            Contribution(
                name=name,
                value=float(np.mean(x[:, i])),
                contribution=base - score,   # positive = this feature raised the score
                detail=f"removing it moves the score {score - base:+.3f}",
            )
        )
    total = sum(abs(c.contribution) for c in out)
    for c in out:
        c.share = abs(c.contribution) / total if total > 1e-12 else 0.0
    out.sort(key=lambda c: -abs(c.contribution))
    del n_samples
    return out[:10]


# ---------------------------------------------------------------------------
# One explanation for the whole verdict
# ---------------------------------------------------------------------------


def explain_snapshot(health: dict, residuals: dict, advisory: dict) -> dict:
    """Everything behind the current advisory, in one object.

    Assembled from the twin's own state rather than recomputed, so the
    explanation and the display can never disagree about what the system
    concluded -- which would be worse than having no explanation at all.
    """
    exp = explain_health(health)
    res = explain_residuals(residuals)

    lines: list[str] = [exp.narrative]
    if res:
        top = res[0]
        lines.append(
            f"The largest departure from as-new behaviour is {top.name} "
            f"({top.detail})."
        )
    if advisory.get("severity") not in (None, "INFO"):
        lines.append(
            f"This is reported as {advisory['severity']}: "
            f"{advisory.get('recommended_action', '')} "
            f"({advisory.get('time_to_action', '')})."
        )

    return {
        "health": exp.as_dict(),
        "residuals": [c.as_dict() for c in res],
        "narrative": " ".join(lines),
        "method": "exact decomposition (health, residuals); "
                  "occlusion attribution (deep classifier)",
    }


__all__ = [
    "Contribution",
    "Explanation",
    "RESIDUAL_SCALE",
    "SUBSYSTEM_INPUTS",
    "explain_fault_prediction",
    "explain_health",
    "explain_residuals",
    "explain_snapshot",
    "narrate_health",
]
