"""Federated learning across a UAV fleet -- PRD Part 3 section 22.

The point of federated learning here is not accuracy. A model trained on
pooled telemetry will always be at least as good as one trained federally, and
pretending otherwise would be dishonest. The point is that **raw telemetry
never leaves the aircraft**: each airframe trains on its own data and uploads
only weights.

For a defence fleet that is the whole argument. Engine telemetry is
operationally revealing -- sortie length, altitude band, power setting, how
hard an asset is being worked and where. Centralising it to train a model
creates a target that did not previously exist. Federated training buys data
sovereignty, and the accuracy given up to get it is the price, which is why
this module MEASURES that price rather than glossing it.

WHY FEDAVG IS IMPLEMENTED AND NOT IMPORTED
------------------------------------------
PRD Part 0 names Flower. FedAvg is a weighted average of weight vectors:

    w_global = sum_k (n_k / n_total) * w_k

Wrapping a weighted average in a framework obscures the one thing a reviewer
needs to see -- that nothing but weights moves. The same reasoning retired ADTK
(DEV-7) and PyOD (DEV-46), and it applies with more force here, because the
claim being made is a SECURITY claim and a security claim is worth exactly what
the reader can verify. Every parameter of PRD Part 3 section 22 is preserved.
See docs/PRD_DEVIATIONS.md DEV-75.

THE BOUNDARY IS STRUCTURAL, NOT A CONVENTION
--------------------------------------------
``FederatedClient`` exposes exactly one method that the server may call, and it
returns weights and a sample count. There is no accessor that returns rows, and
a test asserts it. A comment saying "data stays local" is worth nothing; an
object that cannot hand its data over is worth something.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


# ---------------------------------------------------------------------------
# The model being federated
# ---------------------------------------------------------------------------


@dataclass
class LinearModel:
    """Logistic regression -- deliberately the simplest thing that works.

    A network would demonstrate nothing extra about federation and would make
    the weight vector too large to inspect. Here the whole model is
    ``n_features + 1`` numbers, so a reviewer can read the payload that
    crosses the link and confirm for themselves that it is not data.
    """

    weights: np.ndarray
    bias: float = 0.0

    @classmethod
    def zeros(cls, n_features: int) -> LinearModel:
        return cls(weights=np.zeros(n_features), bias=0.0)

    def copy(self) -> LinearModel:
        return LinearModel(weights=self.weights.copy(), bias=float(self.bias))

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        z = np.clip(x @ self.weights + self.bias, -60.0, 60.0)
        return 1.0 / (1.0 + np.exp(-z))

    def to_vector(self) -> np.ndarray:
        """The payload that actually crosses the link."""
        return np.concatenate([self.weights, [self.bias]])

    @classmethod
    def from_vector(cls, v: np.ndarray) -> LinearModel:
        return cls(weights=np.asarray(v[:-1], dtype=float), bias=float(v[-1]))

    @property
    def payload_bytes(self) -> int:
        return int(self.to_vector().nbytes)


def _train_local(
    model: LinearModel, x: np.ndarray, y: np.ndarray, *, epochs: int, lr: float
) -> LinearModel:
    """A few epochs of gradient descent on one client's own data."""
    m = model.copy()
    n = max(len(x), 1)
    for _ in range(epochs):
        p = m.predict_proba(x)
        err = p - y
        m.weights -= lr * (x.T @ err) / n
        m.bias -= lr * float(err.mean())
    return m


# ---------------------------------------------------------------------------
# Differential privacy
# ---------------------------------------------------------------------------


@dataclass
class PrivacyBudget:
    """Gaussian-mechanism differential privacy on the uploaded update.

    PRD Part 3 section 22.4 asks for epsilon = 1.0. Two things have to happen
    for that to mean anything:

      * the update is CLIPPED to a bounded L2 norm, which is what makes the
        sensitivity finite -- without it the noise scale is meaningless
      * noise is calibrated to that sensitivity, not chosen for convenience

    The accounting here is the single-release Gaussian mechanism. Composition
    across rounds is NOT accounted for, and that is stated rather than hidden:
    a real deployment needs a moments accountant (Abadi et al.), and reporting
    a per-round epsilon as though it were a total would overstate the guarantee.
    """

    epsilon: float = 1.0
    delta: float = 1e-5
    clip_norm: float = 1.0
    rounds_applied: int = 0

    def noise_scale(self) -> float:
        """sigma for the Gaussian mechanism at this (epsilon, delta)."""
        return (
            self.clip_norm
            * math.sqrt(2.0 * math.log(1.25 / self.delta))
            / max(self.epsilon, 1e-9)
        )

    def apply(self, update: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        """Clip, then add calibrated noise. Clipping first is not optional."""
        norm = float(np.linalg.norm(update))
        if norm > self.clip_norm:
            update = update * (self.clip_norm / norm)
        self.rounds_applied += 1
        return update + rng.normal(0.0, self.noise_scale(), size=update.shape)

    def spent(self) -> dict[str, float]:
        """What has actually been spent, said plainly."""
        return {
            "epsilon_per_round": self.epsilon,
            "delta": self.delta,
            "rounds": self.rounds_applied,
            # Naive sequential composition. A real deployment uses a moments
            # accountant, which is tighter; this is the honest upper bound and
            # is reported so nobody mistakes the per-round figure for a total.
            "epsilon_upper_bound_total": self.epsilon * self.rounds_applied,
            "accounting": "sequential composition (upper bound)",
        }


# ---------------------------------------------------------------------------
# A client: one aircraft
# ---------------------------------------------------------------------------


class FederatedClient:
    """One UAV. Its data never leaves it.

    The privacy claim is enforced by the shape of this class rather than by a
    comment: there is no method that returns rows. ``fit_round`` takes a weight
    vector and returns a weight vector and a count, which is the entire
    protocol surface.
    """

    def __init__(
        self,
        client_id: str,
        x: np.ndarray,
        y: np.ndarray,
        *,
        epochs: int = 2,
        lr: float = 0.5,
    ) -> None:
        self.client_id = client_id
        # Underscore-prefixed and never returned. The only way out is as a
        # count or a gradient.
        self._x = np.asarray(x, dtype=float)
        self._y = np.asarray(y, dtype=float)
        self.epochs = epochs
        self.lr = lr
        self.bytes_uploaded = 0
        self.rounds = 0

    @property
    def n_samples(self) -> int:
        """A count, not data. FedAvg needs it for the weighting."""
        return len(self._x)

    def fit_round(
        self,
        global_vector: np.ndarray,
        *,
        privacy: PrivacyBudget | None = None,
        rng: np.random.Generator | None = None,
    ) -> tuple[np.ndarray, int]:
        """Train locally, return the UPDATE and a sample count. Nothing else.

        The delta is returned rather than the absolute weights because that is
        what differential privacy is applied to: an update has bounded
        sensitivity once clipped, whereas an absolute weight vector does not.
        """
        g = LinearModel.from_vector(global_vector)
        local = _train_local(g, self._x, self._y, epochs=self.epochs, lr=self.lr)
        update = local.to_vector() - global_vector
        if privacy is not None:
            update = privacy.apply(update, rng or np.random.default_rng(0))
        self.rounds += 1
        self.bytes_uploaded += int(update.nbytes)
        return update, self.n_samples

    def raw_data_bytes(self) -> int:
        """What centralised training WOULD have had to transmit.

        Reported so the bandwidth claim is measured rather than asserted.
        """
        return int(self._x.nbytes + self._y.nbytes)


# ---------------------------------------------------------------------------
# The server: the ground control station
# ---------------------------------------------------------------------------


@dataclass
class RoundReport:
    round: int
    n_clients: int
    total_samples: int
    bytes_uploaded: int
    rejected: list[str] = field(default_factory=list)
    update_norm: float = 0.0


class FederatedServer:
    """Aggregates client updates. Never sees a row of telemetry.

    ``robust`` switches FedAvg's mean for a coordinate-wise median, which is
    the standard defence against a poisoned update: a mean can be dragged
    anywhere by one malicious client, a median cannot. It costs a little
    accuracy on honest data, so it is off by default and measured rather than
    assumed (PRD Part 3 section 22.4).
    """

    def __init__(
        self,
        n_features: int,
        *,
        robust: bool = False,
        reject_cosine_below: float | None = None,
    ) -> None:
        self.global_model = LinearModel.zeros(n_features)
        self.robust = robust
        self.reject_cosine_below = reject_cosine_below
        self.history: list[RoundReport] = []

    def _screen(
        self, updates: list[tuple[str, np.ndarray, int]]
    ) -> tuple[list[tuple[str, np.ndarray, int]], list[str]]:
        """Reject updates pointing away from the consensus direction.

        A poisoned client sends an update whose direction disagrees with every
        honest one. Comparing each against the mean of the others catches the
        obvious case cheaply. It is not a defence against a careful adversary
        who stays close to the consensus while biasing it slowly, and saying so
        matters more than the check itself.
        """
        if self.reject_cosine_below is None or len(updates) < 3:
            return updates, []

        kept: list[tuple[str, np.ndarray, int]] = []
        rejected: list[str] = []
        vecs = [u for _, u, _ in updates]
        for i, (cid, u, n) in enumerate(updates):
            others = [v for j, v in enumerate(vecs) if j != i]
            # MEDIAN of the others, not the mean. With a small fleet the
            # reference is computed from very few peers, and a mean lets the
            # one dishonest client contaminate the very consensus it is being
            # judged against -- measured on three clients, that rejected
            # everybody and left nothing to aggregate.
            ref = np.median(np.stack(others), axis=0)
            denom = np.linalg.norm(u) * np.linalg.norm(ref)
            cos = float(u @ ref / denom) if denom > 1e-12 else 1.0
            if cos >= self.reject_cosine_below:
                kept.append((cid, u, n))
            else:
                rejected.append(cid)

        # Never reject everyone. A screen that can empty the round is a
        # denial-of-service on the fleet's own training, and one badly-aimed
        # threshold would trigger it.
        if not kept:
            return updates, []
        return kept, rejected

    def aggregate(self, updates: list[tuple[str, np.ndarray, int]]) -> RoundReport:
        """FedAvg: w_global += sum_k (n_k / n_total) * update_k."""
        kept, rejected = self._screen(updates)
        if not kept:
            raise ValueError("every client update was rejected")

        total = sum(n for _, _, n in kept)
        if self.robust:
            # Coordinate-wise median. Sample counts are deliberately ignored --
            # weighting a median by sample count reintroduces the leverage the
            # median exists to remove.
            agg = np.median(np.stack([u for _, u, _ in kept]), axis=0)
        else:
            agg = np.zeros_like(kept[0][1])
            for _, u, n in kept:
                agg += (n / total) * u

        self.global_model = LinearModel.from_vector(
            self.global_model.to_vector() + agg
        )
        rep = RoundReport(
            round=len(self.history) + 1,
            n_clients=len(kept),
            total_samples=total,
            bytes_uploaded=sum(int(u.nbytes) for _, u, _ in kept),
            rejected=rejected,
            update_norm=float(np.linalg.norm(agg)),
        )
        self.history.append(rep)
        return rep


# ---------------------------------------------------------------------------
# Running the protocol
# ---------------------------------------------------------------------------


def run_federated(
    clients: list[FederatedClient],
    n_features: int,
    *,
    rounds: int = 20,
    privacy: PrivacyBudget | None = None,
    robust: bool = False,
    reject_cosine_below: float | None = None,
    seed: int = 0,
) -> tuple[LinearModel, FederatedServer]:
    """The five-stage protocol of PRD Part 3 section 22.3, once per round."""
    rng = np.random.default_rng(seed)
    server = FederatedServer(
        n_features, robust=robust, reject_cosine_below=reject_cosine_below
    )
    for _ in range(rounds):
        gv = server.global_model.to_vector()
        updates = []
        for c in clients:
            u, n = c.fit_round(gv, privacy=privacy, rng=rng)
            updates.append((c.client_id, u, n))
        server.aggregate(updates)
    return server.global_model, server


def train_centralised(
    x: np.ndarray, y: np.ndarray, n_features: int, *, epochs: int = 40, lr: float = 0.5
) -> LinearModel:
    """The baseline federation is measured against.

    Pooled training is the upper bound. Reporting the federated result without
    it would hide the cost of the privacy guarantee, which is the one number a
    reviewer should want.
    """
    return _train_local(LinearModel.zeros(n_features), x, y, epochs=epochs, lr=lr)


def split_by_engine(
    df, n_clients: int, *, engine_col: str = "engine_id"
) -> list[list[int]]:
    """Assign whole engines to clients, never splitting one across two.

    An aircraft holds its own engine's data and nobody else's. Splitting an
    engine across clients would make the simulation easier and would model
    nothing real.
    """
    engines = sorted(df[engine_col].unique())
    return [list(engines[i::n_clients]) for i in range(n_clients)]


__all__ = [
    "FederatedClient",
    "FederatedServer",
    "LinearModel",
    "PrivacyBudget",
    "RoundReport",
    "run_federated",
    "split_by_engine",
    "train_centralised",
]
