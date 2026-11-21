"""The physics-informed loss must constrain the model, and must be honest.

Two properties matter and they are separate: that the constraint actually binds
(a physics loss that changes nothing is decoration), and that the comparison
reporting whether it helps cannot flatter it.
"""

from __future__ import annotations

import numpy as np
import pytest

from layer3_ai import pinn

pytestmark = pytest.mark.skipif(
    not pinn.TORCH, reason="the 'ml' extra is not installed"
)


def _synthetic(n: int = 1500, seed: int = 0):
    """A fleet where CHT genuinely rises with throttle and with ambient.

    Built so the constraints are TRUE of the data. A test in which the physics
    is false of the data would measure the penalty fighting the evidence, which
    is not what the penalty is for.
    """
    rng = np.random.default_rng(seed)
    rpm = rng.uniform(4000, 5800, n)
    thr = rng.uniform(20, 100, n)
    man = rng.uniform(0.8, 1.5, n)
    alt = rng.uniform(0, 20000, n)
    oat = rng.uniform(-20, 45, n)
    truth = 60 + 0.35 * thr + 0.30 * oat + 0.004 * rpm - 0.0003 * alt
    physics = truth - (0.02 * thr - 0.4)      # a biased physics model
    y = truth + rng.normal(0, 1.5, n)
    x = np.stack([rpm, thr, man, alt, oat, physics], 1).astype(np.float32)
    return x, y.astype(np.float32), physics.astype(np.float32)


def _synthetic_at(throttle: np.ndarray, *, seed: int = 0, noise: float = 1.5):
    """The same engine, at a throttle profile the caller chooses.

    Lets a test train inside a narrow band and evaluate outside it, which is
    where a physics constraint earns its keep.
    """
    rng = np.random.default_rng(seed)
    n = len(throttle)
    rpm = rng.uniform(4000, 5800, n)
    man = rng.uniform(0.8, 1.5, n)
    alt = rng.uniform(0, 20000, n)
    oat = rng.uniform(-20, 45, n)
    truth = 60 + 0.35 * throttle + 0.30 * oat + 0.004 * rpm - 0.0003 * alt
    physics = truth - (0.02 * throttle - 0.4)
    y = truth + rng.normal(0, noise, n)
    x = np.stack([rpm, throttle, man, alt, oat, physics], 1).astype(np.float32)
    return x, y.astype(np.float32), physics.astype(np.float32)


def _standardise(xtr, xte):
    mu, sd = xtr.mean(0), xtr.std(0) + 1e-8
    return (xtr - mu) / sd, (xte - mu) / sd


# ---------------------------------------------------------------------------
# The constraint binds
# ---------------------------------------------------------------------------


def test_the_physics_loss_reduces_impossible_derivatives_where_data_is_thin():
    """The whole claim, tested where the claim applies.

    On data that densely covers the input space the unconstrained fit gets the
    signs right on its own and the penalty has nothing to do -- measured, both
    models scored a 0 % violation rate, which says the FIXTURE was easy, not
    that the penalty works.

    The penalty exists for the other case: an operating point the fleet rarely
    visits, where an unconstrained fit is free to invent a slope from noise.
    So the model is trained on a NARROW throttle band and its derivatives are
    then examined across the full range, which is exactly the extrapolation a
    UAV engine forces on any model fitted to mostly-cruise data.
    """
    import torch

    rng = np.random.default_rng(4)
    n = 1200
    # Training: throttle confined to a cruise band, and noisy enough that the
    # local slope is not identifiable from the data alone.
    thr_tr = rng.uniform(55, 65, n)
    x_tr, y_tr, _ = _synthetic_at(thr_tr, seed=4, noise=6.0)
    # Evaluation: the whole envelope, including take-off and idle.
    thr_te = rng.uniform(20, 100, n)
    x_te, _, _ = _synthetic_at(thr_te, seed=5, noise=6.0)

    mu, sd = x_tr.mean(0), x_tr.std(0) + 1e-8
    xtr_n, xte_n = (x_tr - mu) / sd, (x_te - mu) / sd
    y_n = (y_tr - y_tr.mean()) / (y_tr.std() + 1e-8)
    xt = torch.tensor(xte_n, dtype=torch.float32)

    free = pinn.train(xtr_n, y_n, physics_weight=0.0, epochs=80)
    bound = pinn.train(xtr_n, y_n, physics_weight=5.0, epochs=80)
    v_free = pinn.violation_rate(free, xt)
    v_bound = pinn.violation_rate(bound, xt)
    assert v_bound < v_free, (
        f"the penalty did not bind: {v_bound:.3f} vs {v_free:.3f}"
    )


def test_the_penalty_is_zero_when_both_signs_are_correct():
    """Only the NEGATIVE part is penalised. The physics fixes the sign, not the
    magnitude, and pushing on magnitude would assert a coefficient nobody
    measured."""
    import torch
    from torch import nn

    class Rising(nn.Module):
        def forward(self, x):
            return x[:, pinn.I_THROTTLE] + x[:, pinn.I_OAT]

    x = torch.rand(64, len(pinn.INPUTS))
    assert float(pinn.physics_violation(Rising(), x)) == pytest.approx(0.0, abs=1e-6)


def test_the_penalty_is_positive_when_a_sign_is_impossible():
    import torch
    from torch import nn

    class Falling(nn.Module):
        def forward(self, x):
            return -x[:, pinn.I_THROTTLE]

    x = torch.rand(64, len(pinn.INPUTS))
    assert float(pinn.physics_violation(Falling(), x)) > 0.5


def test_the_network_is_twice_differentiable():
    """The penalty differentiates the network with respect to its inputs and
    then backpropagates through that. ReLU's second derivative is zero almost
    everywhere, which would make the penalty piecewise constant and give the
    optimiser nothing to descend -- hence tanh."""
    import torch

    m = pinn.HybridThermalNet()
    x = torch.rand(32, len(pinn.INPUTS))
    pen = pinn.physics_violation(m, x)
    pen.backward()
    grads = [p.grad for p in m.parameters() if p.grad is not None]
    assert grads, "the penalty produced no parameter gradient"
    assert any(float(g.abs().sum()) > 0 for g in grads)


# ---------------------------------------------------------------------------
# The comparison cannot flatter itself
# ---------------------------------------------------------------------------


def test_the_physics_baseline_is_scored_in_real_units():
    """`x` is standardised for the optimiser. Scoring the physics baseline
    against a standardised copy of itself would measure nothing, so the raw
    prediction is passed separately -- and every RMSE comes back in degC."""
    x, y, phys = _synthetic()
    cut = 1000
    xtr, xte = _standardise(x[:cut], x[cut:])
    r = pinn.compare(xtr, y[:cut], xte, y[cut:], phys[cut:], epochs=25)
    # The physics model here carries a deliberate bias of roughly 0.02*thr-0.4,
    # i.e. a degree or so. An RMSE in the standardised domain would be O(1)
    # by construction and would not distinguish the two.
    direct = float(np.sqrt(np.mean((phys[cut:] - y[cut:]) ** 2)))
    assert r.physics_rmse == pytest.approx(direct, rel=1e-6)


def test_all_three_models_are_scored_on_the_same_held_out_rows():
    x, y, phys = _synthetic()
    cut = 1000
    xtr, xte = _standardise(x[:cut], x[cut:])
    r = pinn.compare(xtr, y[:cut], xte, y[cut:], phys[cut:], epochs=25)
    assert r.n_train == cut
    assert r.n_test == len(x) - cut
    for v in (r.physics_rmse, r.data_rmse, r.hybrid_rmse):
        assert v > 0.0 and np.isfinite(v)


def test_the_winner_is_whichever_is_actually_lowest():
    """A physics-informed model that is worse than the physics is a result.
    Reporting it as the winner regardless would make every other measurement
    in this repository less believable."""
    r = pinn.CompareResult(physics_rmse=1.0, data_rmse=5.0, hybrid_rmse=9.0)
    assert r.winner == "physics"
    r = pinn.CompareResult(physics_rmse=9.0, data_rmse=1.0, hybrid_rmse=5.0)
    assert r.winner == "data"
    r = pinn.CompareResult(physics_rmse=9.0, data_rmse=5.0, hybrid_rmse=1.0)
    assert r.winner == "hybrid"


def test_the_two_networks_differ_only_in_the_physics_weight():
    """Any difference between them must be attributable to the loss, not to a
    different architecture, initialisation or schedule."""
    import inspect

    src = inspect.getsource(pinn.compare)
    assert "physics_weight=weight" in src
    # Same seed, same epochs, same lr -- all defaults, passed through **kw to
    # both calls rather than set per-model.
    assert src.count("pinn.train") == 0
    assert "train(x_train, y_n, physics_weight=weight, **kw)" in src


def test_the_physics_prediction_is_an_input_not_a_target():
    """Regressing the residual was the first design here and it was wrong: the
    constraints are laws about TEMPERATURE and say nothing about the error a
    physics model makes."""
    assert "cht_physics" in pinn.INPUTS
    assert pinn.I_PHYSICS == len(pinn.INPUTS) - 1
