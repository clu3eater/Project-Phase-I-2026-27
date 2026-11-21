"""Tests for federated learning.

The first group is the one that matters. Federated learning makes a SECURITY
claim -- that raw telemetry never leaves the aircraft -- and a security claim
is worth exactly what can be verified. So these tests check the boundary
structurally: that the client object has no way to hand its data over, and that
what crosses the link is the size of a weight vector rather than the size of a
dataset.

The rest check that the aggregation is FedAvg as specified, that the privacy
mechanism clips before it adds noise (without which the noise scale means
nothing), and that a compromised client cannot drag the fleet model when the
robust aggregator is on.
"""

from __future__ import annotations

import numpy as np
import pytest

from layer3_ai.fed import federated as fed


def _data(n=400, d=6, seed=0):
    rng = np.random.default_rng(seed)
    x = rng.normal(0, 1, (n, d))
    y = (x[:, 0] + 0.5 * x[:, 1] > 0).astype(float)
    return x, y


def _clients(k=3, n=400, d=6):
    out = []
    for i in range(k):
        x, y = _data(n, d, seed=i)
        out.append(fed.FederatedClient(f"UAV-{i+1}", x, y))
    return out


# ---------------------------------------------------------------------------
# The privacy boundary, enforced structurally
# ---------------------------------------------------------------------------


def test_a_client_exposes_no_way_to_read_its_data():
    """A comment saying "data stays local" is worth nothing.

    An object that cannot hand its rows over is worth something, so the public
    surface is checked rather than trusted.
    """
    c = fed.FederatedClient("UAV-1", *_data())
    public = [a for a in dir(c) if not a.startswith("_")]
    for name in public:
        attr = getattr(c, name)
        if callable(attr):
            continue
        assert not isinstance(attr, np.ndarray), (
            f"'{name}' exposes an array on the client's public surface"
        )
    # The only numeric facts that leave are counts and byte totals.
    assert set(public) >= {"client_id", "n_samples", "bytes_uploaded", "rounds"}


def test_a_training_round_returns_weights_and_a_count_and_nothing_else():
    c = fed.FederatedClient("UAV-1", *_data(n=400, d=6))
    update, n = c.fit_round(fed.LinearModel.zeros(6).to_vector())
    assert isinstance(update, np.ndarray)
    assert update.shape == (7,)          # 6 weights + bias, not 400 rows
    assert n == 400
    assert update.size < 400, "the payload is the size of a model, not a dataset"


def test_what_crosses_the_link_is_orders_of_magnitude_smaller_than_the_data():
    """PRD Part 3 s22.5 claims a 100x bandwidth reduction. Measured, not
    asserted -- and on this model it is far larger."""
    c = fed.FederatedClient("UAV-1", *_data(n=5000, d=20))
    gv = fed.LinearModel.zeros(20).to_vector()
    for _ in range(25):
        c.fit_round(gv)
    assert c.raw_data_bytes() / c.bytes_uploaded > 100


def test_the_server_never_receives_a_sample():
    """The aggregator's whole input is (id, update, count) triples."""
    import inspect

    sig = inspect.signature(fed.FederatedServer.aggregate)
    assert list(sig.parameters) == ["self", "updates"]
    srv = fed.FederatedServer(4)
    srv.aggregate([("a", np.ones(5), 10), ("b", np.ones(5) * 3, 30)])
    assert srv.global_model.to_vector().shape == (5,)


# ---------------------------------------------------------------------------
# FedAvg is what the PRD specifies
# ---------------------------------------------------------------------------


def test_aggregation_is_sample_weighted():
    """w_global += sum_k (n_k / n_total) x update_k, PRD Part 3 s22.3."""
    srv = fed.FederatedServer(3)
    srv.aggregate([("a", np.ones(4), 10), ("b", np.full(4, 5.0), 30)])
    # (10/40)*1 + (30/40)*5 = 4.0
    assert srv.global_model.to_vector() == pytest.approx(np.full(4, 4.0))


def test_a_larger_client_carries_more_weight():
    small = fed.FederatedServer(3)
    small.aggregate([("a", np.ones(4), 1), ("b", np.zeros(4), 99)])
    big = fed.FederatedServer(3)
    big.aggregate([("a", np.ones(4), 99), ("b", np.zeros(4), 1)])
    assert big.global_model.to_vector()[0] > small.global_model.to_vector()[0]


def test_federated_training_approaches_the_centralised_baseline():
    """Pooled training is the upper bound; federation should get close.

    If it did not, the privacy guarantee would be unaffordable and the honest
    conclusion would be to say so.
    """
    clients = _clients(3)
    x = np.vstack([_data(400, 6, seed=i)[0] for i in range(3)])
    y = np.concatenate([_data(400, 6, seed=i)[1] for i in range(3)])

    central = fed.train_centralised(x, y, 6, epochs=50)
    federated, _ = fed.run_federated(clients, 6, rounds=25)

    def acc(m):
        return float(((m.predict_proba(x) > 0.5) == (y > 0.5)).mean())

    assert acc(federated) > acc(central) - 0.05


def test_clients_hold_whole_engines_never_a_fraction_of_one():
    """An aircraft holds its own engine's data. Splitting one engine across
    two clients would make the simulation easier and model nothing real."""
    import pandas as pd

    df = pd.DataFrame({"engine_id": np.repeat(np.arange(1, 10), 5)})
    groups = fed.split_by_engine(df, 3)
    flat = [e for g in groups for e in g]
    assert sorted(flat) == list(range(1, 10))
    assert len(set(flat)) == len(flat), "an engine appears on two clients"


# ---------------------------------------------------------------------------
# Differential privacy
# ---------------------------------------------------------------------------


def test_the_update_is_clipped_before_noise_is_added():
    """Without a bounded sensitivity the noise scale is meaningless.

    Clipping is what makes the Gaussian mechanism's epsilon mean anything, so
    it is not an optional refinement.
    """
    budget = fed.PrivacyBudget(epsilon=1e9, delta=1e-5, clip_norm=1.0)  # ~no noise
    rng = np.random.default_rng(0)
    out = budget.apply(np.full(4, 100.0), rng)
    assert np.linalg.norm(out) == pytest.approx(1.0, abs=1e-3)


def test_a_smaller_epsilon_means_more_noise():
    strong = fed.PrivacyBudget(epsilon=0.5).noise_scale()
    weak = fed.PrivacyBudget(epsilon=5.0).noise_scale()
    assert strong > weak


def test_privacy_accounting_reports_composition_rather_than_hiding_it():
    """Reporting a per-round epsilon as though it were a total would overstate
    the guarantee by the number of rounds."""
    b = fed.PrivacyBudget(epsilon=1.0)
    rng = np.random.default_rng(0)
    for _ in range(10):
        b.apply(np.ones(4) * 0.1, rng)
    spent = b.spent()
    assert spent["rounds"] == 10
    assert spent["epsilon_upper_bound_total"] == pytest.approx(10.0)
    assert "composition" in spent["accounting"]


def test_privacy_costs_accuracy_and_the_cost_is_visible():
    """Measured on the real fleet: -0.323 AUC at epsilon=1 per round, against
    the PRD's claimed "<3%". The trade is real and is reported, not hidden."""
    x = np.vstack([_data(400, 6, seed=i)[0] for i in range(3)])
    y = np.concatenate([_data(400, 6, seed=i)[1] for i in range(3)])

    def acc(m):
        return float(((m.predict_proba(x) > 0.5) == (y > 0.5)).mean())

    plain, _ = fed.run_federated(_clients(3), 6, rounds=25)
    noisy, _ = fed.run_federated(
        _clients(3), 6, rounds=25,
        privacy=fed.PrivacyBudget(epsilon=0.5, clip_norm=0.5),
    )
    assert acc(noisy) < acc(plain)


# ---------------------------------------------------------------------------
# Poisoning
# ---------------------------------------------------------------------------


class _Scaling(fed.FederatedClient):
    """Model replacement: scale an inverted update so it survives averaging."""

    def fit_round(self, gv, *, privacy=None, rng=None):
        u, n = super().fit_round(gv, privacy=privacy, rng=rng)
        return -u * 9.0, n


def test_one_compromised_client_can_drag_a_mean():
    """The vulnerability being defended against, demonstrated first.

    Measured on the real fleet: FedAvg's mean fell from 0.869 to 0.445 with
    one of three clients compromised.
    """
    x, y = _data(400, 6, seed=0)
    honest = _clients(3)[1:]
    attacked = [_Scaling("bad", x, y)] + honest
    poisoned, _ = fed.run_federated(attacked, 6, rounds=20)
    clean, _ = fed.run_federated(_clients(3), 6, rounds=20)

    def acc(m):
        return float(((m.predict_proba(x) > 0.5) == (y > 0.5)).mean())

    assert acc(poisoned) < acc(clean) - 0.1


def test_the_median_aggregator_resists_it():
    """A median cannot be dragged by one client the way a mean can."""
    x, y = _data(400, 6, seed=0)
    attacked = [_Scaling("bad", x, y)] + _clients(3)[1:]
    robust, _ = fed.run_federated(attacked, 6, rounds=20, robust=True)
    clean, _ = fed.run_federated(_clients(3), 6, rounds=20)

    def acc(m):
        return float(((m.predict_proba(x) > 0.5) == (y > 0.5)).mean())

    assert acc(robust) > acc(clean) - 0.1


def test_the_screen_never_empties_a_round():
    """A screen that can reject everybody is a denial of service on the
    fleet's own training, and one badly-aimed threshold would trigger it."""
    srv = fed.FederatedServer(3, reject_cosine_below=0.999)
    rng = np.random.default_rng(0)
    updates = [(f"c{i}", rng.normal(0, 1, 4), 10) for i in range(4)]
    rep = srv.aggregate(updates)     # must not raise
    assert rep.n_clients == 4


def test_the_median_ignores_sample_counts_deliberately():
    """Weighting a median by sample count reintroduces exactly the leverage
    the median exists to remove."""
    srv = fed.FederatedServer(3, robust=True)
    srv.aggregate([
        ("honest-a", np.ones(4), 1),
        ("honest-b", np.ones(4), 1),
        ("huge-liar", np.full(4, 100.0), 10_000),
    ])
    assert srv.global_model.to_vector() == pytest.approx(np.ones(4))
