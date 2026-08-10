"""Shared test fixtures: a synthetic scorer that needs no artefact on disk."""

from __future__ import annotations

import numpy as np
import pytest

import features
from anomaly_svc.scorer import Scorer
from contracts import UR5_JOINT_NAMES
from detector import Manifest, fit_rule
from features import feature_names

FEATURE_NAMES = feature_names(list(UR5_JOINT_NAMES))


@pytest.fixture
def scorer() -> Scorer:
    rng = np.random.default_rng(0)
    rule = fit_rule(rng.normal(size=(200, len(FEATURE_NAMES))), FEATURE_NAMES)
    manifest = Manifest(
        stem="rule-v1",
        model_kind="rule",
        features_version=features.__version__,
        threshold=1.0,
        seed=0,
        trained_at="2026-07-18",
        dataset_fingerprint="fp",
        n_train=200,
    )
    return Scorer(rule, manifest)
