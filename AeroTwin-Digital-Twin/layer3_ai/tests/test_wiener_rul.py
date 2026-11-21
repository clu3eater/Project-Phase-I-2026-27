"""The first-passage interval, checked against simulation rather than algebra.

`wiener_fht_quantiles` claims the inverse Gaussian distribution of the first
time a drifting random walk crosses a threshold. The claim is tested the direct
way: simulate thousands of such walks and compare where they actually cross.
"""

from __future__ import annotations

import numpy as np
import pytest

from layer3_ai import rul_physics as rp


def _first_passage(margin: float, mu: float, sigma2: float, *, n: int = 4000,
                   dt: float = 0.5, t_max: float = 2500.0, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    x = np.full(n, margin)
    hit = np.full(n, np.nan)
    for k in range(int(t_max / dt)):
        x += -mu * dt + np.sqrt(sigma2 * dt) * rng.standard_normal(n)
        new = np.isnan(hit) & (x <= 0.0)
        hit[new] = (k + 1) * dt
    return hit


def test_the_quantiles_are_where_simulated_walks_actually_cross():
    margin, mu, sigma2 = 0.30, 0.001, 2.0e-5
    sim = _first_passage(margin, mu, sigma2)
    assert np.isnan(sim).mean() < 0.01
    lo, med, hi = rp.wiener_fht_quantiles(margin, mu, sigma2, (0.025, 0.5, 0.975))
    emp = np.nanquantile(sim, [0.025, 0.5, 0.975])
    assert lo == pytest.approx(emp[0], rel=0.08)
    assert med == pytest.approx(emp[1], rel=0.05)
    assert hi == pytest.approx(emp[2], rel=0.08)


def test_with_no_wandering_every_quantile_is_the_straight_line_time():
    assert rp.wiener_fht_quantiles(0.2, 0.001, 0.0, (0.1, 0.9)) == pytest.approx((200.0, 200.0))


def test_the_estimator_recovers_the_decline_it_was_fed():
    rng = np.random.default_rng(4)
    w = rp.WienerRul(bucket_h=1.0)
    mu, sigma2, noise, dt = 0.0008, 1.0e-7, 0.002, 0.05
    h, est = 0.97, None
    for k in range(int(80 / dt)):
        h += -mu * dt + np.sqrt(sigma2 * dt) * rng.standard_normal()
        est = w.update(h + noise * rng.standard_normal(), k * dt)
    assert est is not None and est.reportable
    assert -est.rate_per_hour == pytest.approx(mu, rel=0.25)
    assert est.lower_hours <= est.hours <= est.upper_hours


def test_a_healthy_engine_gets_no_number():
    w = rp.WienerRul(bucket_h=1.0)
    rng = np.random.default_rng(2)
    est = None
    for k in range(int(40 / 0.05)):
        est = w.update(0.97 + 0.002 * rng.standard_normal(), k * 0.05)
    assert est is not None and est.hours is None
