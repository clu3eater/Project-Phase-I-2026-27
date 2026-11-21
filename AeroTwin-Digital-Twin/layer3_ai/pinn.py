"""Physics-informed hybrid model -- PS innovation areas "Physics-informed AI"
and "Hybrid thermodynamic + data-driven models".

WHAT "PHYSICS-INFORMED" MEANS HERE, AND WHAT IT DOES NOT
--------------------------------------------------------
The phrase is used loosely enough to be worthless. It is worth being exact
about which of the three usual things this is:

  1. A network given physics-derived FEATURES. Common, useful, and not what
     anybody means by a PINN. This project already does it -- the residuals
     against the as-new twin are inputs to Tiers 2 and 3, and adding them was
     measured at ROC-AUC 0.945 -> 0.971.

  2. A network whose OUTPUT is a correction to a physics model, rather than the
     quantity itself. That is the hybrid half.

  3. A network whose LOSS penalises violations of a governing physical
     relationship, evaluated through the network's own derivatives. That is the
     physics-informed half, and it is the part that is usually skipped.

This module does 2 AND 3, because on their own neither is the claim.

THE HYBRID: THE PHYSICS PREDICTION IS AN INPUT, THE TEMPERATURE IS THE OUTPUT
-----------------------------------------------------------------------------
The MVEM already predicts cylinder-head temperature from the operating point,
and it is anchored to twelve published points. A network asked to predict CHT
from nothing would spend its capacity relearning the manifold-pressure and
airflow relationships the physics already has right.

So the physics prediction is handed to the network AS AN INPUT and the network
predicts the measured temperature. The physics carries the envelope; the
network learns what wear does to it, and can fall back on the physics term
wherever it has nothing better to offer.

WHY NOT REGRESS THE RESIDUAL DIRECTLY
--------------------------------------
That was the first design here, and it was wrong in a way worth recording,
because it looked right and the measurement is what exposed it.

Predicting the residual makes the physics-informed loss meaningless. The
constraints below are laws about TEMPERATURE -- more fuel burned is more heat
into the head -- and they say nothing whatever about the ERROR a physics model
makes. The residual is free to fall with throttle, and usually does, because
the physics already accounts for the rise. Applying a temperature law to a
residual network reported 98.8 % of held-out points as "physically impossible"
when nothing impossible was happening: the constraint was simply about a
different quantity from the one the network predicted.

Predicting the temperature, with the physics prediction as an input, makes the
constraint a statement about the model's actual output and therefore checkable.

THE PHYSICS-INFORMED LOSS: TWO SIGNS THAT CANNOT BE WRONG
----------------------------------------------------------
Two relationships hold for any air-cooled-cylinder engine regardless of its
condition, and both are statements about DERIVATIVES rather than values:

    d(CHT)/d(throttle)  >=  0     more fuel burned is more heat into the head
    d(CHT)/d(OAT)       >=  0     a hotter ambient cools the head less

They are enforced by differentiating the network with respect to its own
inputs (``torch.autograd.grad``) and penalising negative gradients. This is
what separates a physics-informed loss from a physics-flavoured one: the
constraint is evaluated on the model's behaviour, at collocation points that
need no labels, not on the training targets.

The value shows up where data is thin. A purely data-driven correction fitted
to a fleet that mostly cruises can learn a locally negative throttle response
from noise, and then predicts that opening the throttle COOLS the engine. The
penalty makes that solution expensive without asserting what the magnitude
should be.

WHETHER IT ACTUALLY HELPS IS MEASURED, NOT CLAIMED
---------------------------------------------------
``compare`` fits three models on the same split -- physics alone, data-driven
alone, and the hybrid with the physics loss -- and scores all three on engines
none of them trained on. If the hybrid does not win, this module reports that
it does not win. A physics-informed model that is worse than the physics is a
result, and hiding it would make every other measurement in this repository
less believable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Torch is in the `ml` extra. The module imports without it so a core install
# can still introspect the interface.
try:
    import torch
    from torch import nn

    TORCH = True
except ImportError:  # pragma: no cover - exercised only without the extra
    TORCH = False
    nn = object  # type: ignore[assignment]

# Inputs to the correction network, in order. Operating point plus environment:
# the quantities the physics is a function of, so the correction is a function
# of the same thing and the two are comparable.
INPUTS = ("rpm", "throttle_pct", "manifold_pressure", "altitude_ft", "oat_c",
          # The physics model's own prediction. Making it an input rather than
          # an additive offset lets the network learn HOW MUCH to trust it at a
          # given operating point instead of being forced to trust it exactly.
          "cht_physics")

# Index of the inputs the monotonicity constraints apply to.
I_THROTTLE = INPUTS.index("throttle_pct")
I_OAT = INPUTS.index("oat_c")
I_PHYSICS = INPUTS.index("cht_physics")

UNAVAILABLE = "the physics-informed model requires the 'ml' extra: pip install -e '.[ml]'"


@dataclass
class CompareResult:
    """Three models on the same held-out engines."""

    physics_rmse: float = 0.0
    data_rmse: float = 0.0
    hybrid_rmse: float = 0.0
    # Fraction of collocation points where the model's own derivative has the
    # physically impossible sign. The quantity the physics loss exists to move.
    data_violations: float = 0.0
    hybrid_violations: float = 0.0
    n_train: int = 0
    n_test: int = 0
    engines_test: list[int] = field(default_factory=list)

    @property
    def winner(self) -> str:
        r = {"physics": self.physics_rmse, "data": self.data_rmse,
             "hybrid": self.hybrid_rmse}
        return min(r, key=r.get)

    def as_dict(self) -> dict:
        return {
            "physics_rmse": round(self.physics_rmse, 4),
            "data_rmse": round(self.data_rmse, 4),
            "hybrid_rmse": round(self.hybrid_rmse, 4),
            "data_violations": round(self.data_violations, 4),
            "hybrid_violations": round(self.hybrid_violations, 4),
            "winner": self.winner,
            "n_train": self.n_train,
            "n_test": self.n_test,
            "engines_test": self.engines_test,
        }


if TORCH:

    class HybridThermalNet(nn.Module):
        """Small MLP predicting measured CHT, given the physics prediction.

        Deliberately small. The physics carries the envelope and arrives as an
        input, so this only has to learn what wear does to it -- a smoother and
        lower-dimensional function than the temperature itself. A large network
        would have the capacity to relearn, and then contradict, the physics.
        """

        def __init__(self, n_in: int = len(INPUTS), hidden: int = 32) -> None:
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(n_in, hidden), nn.Tanh(),
                nn.Linear(hidden, hidden), nn.Tanh(),
                nn.Linear(hidden, 1),
            )

        def forward(self, x: "torch.Tensor") -> "torch.Tensor":
            # Tanh, not ReLU: the physics loss differentiates this network with
            # respect to its inputs, and ReLU's second derivative is zero
            # almost everywhere, which makes the gradient penalty piecewise
            # constant and gives the optimiser nothing to descend.
            return self.net(x).squeeze(-1)


def physics_violation(model, x: "torch.Tensor") -> "torch.Tensor":
    """Mean penalty for derivatives with a physically impossible sign.

    Evaluated at COLLOCATION POINTS -- inputs with no label attached. That is
    the whole advantage: the constraint can be enforced anywhere in the input
    space, including operating points the fleet never visited, which is where
    an unconstrained fit is free to invent nonsense.
    """
    x = x.clone().requires_grad_(True)
    y = model(x)
    g, = torch.autograd.grad(y.sum(), x, create_graph=True)
    # d(CHT)/d(throttle) >= 0 and d(CHT)/d(OAT) >= 0. Only the NEGATIVE part is
    # penalised: the physics fixes the sign, not the magnitude, and pushing on
    # the magnitude would be asserting a coefficient we have not measured.
    pen = torch.relu(-g[:, I_THROTTLE]) + torch.relu(-g[:, I_OAT])
    return pen.mean()


def violation_rate(model, x: "torch.Tensor") -> float:
    """Fraction of points whose derivative has the impossible sign."""
    x = x.clone().requires_grad_(True)
    y = model(x)
    g, = torch.autograd.grad(y.sum(), x, create_graph=False)
    bad = (g[:, I_THROTTLE] < 0) | (g[:, I_OAT] < 0)
    return float(bad.float().mean())


def train(
    x: np.ndarray,
    y: np.ndarray,
    *,
    physics_weight: float = 0.0,
    epochs: int = 60,
    lr: float = 3e-3,
    seed: int = 11,
    hidden: int = 32,
):
    """Fit a correction network. ``physics_weight`` 0 gives the pure-data model.

    The two models compared later differ ONLY in this weight, so any difference
    between them is attributable to the physics loss and not to a different
    architecture, initialisation or schedule.
    """
    if not TORCH:  # pragma: no cover
        raise RuntimeError(UNAVAILABLE)
    torch.manual_seed(seed)
    model = HybridThermalNet(x.shape[1], hidden=hidden)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    xt = torch.tensor(x, dtype=torch.float32)
    yt = torch.tensor(y, dtype=torch.float32)

    for _ in range(epochs):
        opt.zero_grad()
        loss = torch.mean((model(xt) - yt) ** 2)
        if physics_weight > 0.0:
            # Collocation points drawn across the observed input range,
            # including combinations the fleet never flew.
            lo, hi = xt.min(0).values, xt.max(0).values
            c = lo + (hi - lo) * torch.rand(min(512, len(xt)), xt.shape[1])
            loss = loss + physics_weight * physics_violation(model, c)
        loss.backward()
        opt.step()
    model.eval()
    return model


def compare(
    x_train: np.ndarray, y_train: np.ndarray,
    x_test: np.ndarray, y_test: np.ndarray,
    physics_test: np.ndarray,
    *,
    physics_weight: float = 1.0,
    engines_test: list[int] | None = None,
    **kw,
) -> CompareResult:
    """Physics alone vs data-driven vs hybrid, on engines none of them saw.

    ``y`` is the MEASURED temperature in degC. ``physics_test`` is the physics
    model's own prediction for the test rows, IN THE SAME UNITS -- passed
    separately because ``x`` is standardised for the optimiser, and scoring the
    baseline against a standardised copy of itself would measure nothing.

    Every RMSE below is in degC, so the three numbers are comparable and mean
    something to a thermal engineer.
    """
    if not TORCH:  # pragma: no cover
        raise RuntimeError(UNAVAILABLE)
    r = CompareResult(n_train=len(x_train), n_test=len(x_test),
                      engines_test=engines_test or [])

    # Physics alone: the physics model's own prediction, unaided.
    r.physics_rmse = float(np.sqrt(np.mean((physics_test - y_test) ** 2)))

    # The TARGET is standardised for the optimiser and predictions are put back
    # into degC before scoring. A tanh network fitted directly against
    # temperatures near 100 spends its first epochs learning the offset.
    mu, sd = float(y_train.mean()), float(y_train.std() + 1e-8)
    y_n = (y_train - mu) / sd

    xt = torch.tensor(x_test, dtype=torch.float32)
    for weight, attr, vattr in ((0.0, "data_rmse", "data_violations"),
                                (physics_weight, "hybrid_rmse", "hybrid_violations")):
        m = train(x_train, y_n, physics_weight=weight, **kw)
        with torch.no_grad():
            pred = m(xt).numpy() * sd + mu
        setattr(r, attr, float(np.sqrt(np.mean((pred - y_test) ** 2))))
        setattr(r, vattr, violation_rate(m, xt))
    return r


__all__ = ["INPUTS", "TORCH", "UNAVAILABLE", "CompareResult", "compare",
           "physics_violation", "train", "violation_rate"]
if TORCH:
    __all__.append("HybridThermalNet")
