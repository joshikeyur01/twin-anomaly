"""Detector fitting, scoring, and the Scorer contract — no artefacts."""

from __future__ import annotations

import numpy as np

from detector import (
    ForestDetector,
    RuleDetector,
    Scorer,
    choose_threshold,
    fit_forest,
    fit_rule,
    verdicts,
)

RNG = np.random.default_rng(0)
NAMES = ["elbow_joint__vel_rms", "elbow_joint__pos_std", "n_samples"]


def _normal(n: int = 300) -> np.ndarray:
    # Tight cluster: velocity ~1, small position noise, ~50 samples/window.
    return np.column_stack(
        [
            RNG.normal(1.0, 0.02, n),
            RNG.normal(0.01, 0.002, n),
            RNG.normal(50.0, 0.5, n),
        ]
    ).astype(np.float64)


def _anomalies() -> np.ndarray:
    # One row per fault signature: stuck (vel~0), encoder (pos noise up),
    # dropout (few samples).
    return np.array(
        [
            [0.0, 0.01, 50.0],  # stuck: velocity collapsed
            [1.0, 0.2, 50.0],  # encoder: position std up
            [1.0, 0.01, 3.0],  # dropout: n_samples collapsed
        ],
        dtype=np.float64,
    )


class TestRule:
    def test_is_a_scorer(self) -> None:
        rule = fit_rule(_normal(), NAMES)
        assert isinstance(rule, RuleDetector)
        assert isinstance(rule, Scorer)

    def test_normal_scores_low_anomalies_high(self) -> None:
        normal = _normal()
        rule = fit_rule(normal, NAMES)
        threshold = choose_threshold(rule.score(normal))
        assert verdicts(rule.score(_anomalies()), threshold).all()
        # ~1% of normal flagged by construction (p99 threshold).
        assert verdicts(rule.score(normal), threshold).mean() <= 0.05


class TestForest:
    def test_is_a_scorer(self) -> None:
        forest = fit_forest(_normal(), NAMES, seed=0)
        assert isinstance(forest, ForestDetector)
        assert isinstance(forest, Scorer)

    def test_seed_is_reproducible(self) -> None:
        normal = _normal()
        a = fit_forest(normal, NAMES, seed=7).score(_anomalies())
        b = fit_forest(normal, NAMES, seed=7).score(_anomalies())
        assert np.array_equal(a, b)

    def test_anomalies_rank_above_normal(self) -> None:
        # Unit-level sanity: fault windows score higher than the bulk of
        # normal. Clean p99-threshold detection is a claim for the real
        # corpus (the evaluation notebook), not a 3-feature toy blob where
        # IsolationForest's normal tail overlaps synthetic outliers.
        normal = _normal()
        forest = fit_forest(normal, NAMES, seed=0)
        assert (forest.score(_anomalies()) > np.median(forest.score(normal))).all()


def test_choose_threshold_is_the_quantile() -> None:
    scores = np.arange(100, dtype=np.float64)
    assert choose_threshold(scores, quantile=0.5) == np.quantile(scores, 0.5)
