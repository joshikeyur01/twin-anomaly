"""The scorer: one code path for live windows and POST bodies (no skew)."""

from __future__ import annotations

import numpy as np
import pytest

from anomaly_svc.scorer import Scorer
from contracts import UR5_JOINT_NAMES, JointWindow, WindowScoreRequest
from features import Window


def _matched_pair(n: int = 8) -> tuple[Window, WindowScoreRequest]:
    """The same samples as a features.Window and as a POST body."""
    rng = np.random.default_rng(1)
    values = rng.normal(size=(n, len(UR5_JOINT_NAMES), 3)).astype(np.float64)
    window = Window(0, n, np.arange(n, dtype=np.int64), values)
    joints = {
        name: JointWindow(
            positions=values[:, j, 0].tolist(),
            velocities=values[:, j, 1].tolist(),
            efforts=values[:, j, 2].tolist(),
        )
        for j, name in enumerate(UR5_JOINT_NAMES)
    }
    request = WindowScoreRequest(window_start_ns=0, sample_period_ns=27_000_000, joints=joints)
    return window, request


def test_window_and_request_score_identically(scorer: Scorer) -> None:
    # The skew invariant: the same samples score the same however they arrive.
    window, request = _matched_pair()
    assert scorer.score_window(window).score == pytest.approx(scorer.score_request(request).score)


def test_score_carries_model_provenance(scorer: Scorer) -> None:
    _, request = _matched_pair()
    score = scorer.score_request(request)
    assert score.artefact == "rule-v1"
    assert score.features_version == scorer._manifest.features_version
    assert score.verdict == (score.score >= score.threshold)


def test_missing_joint_is_rejected(scorer: Scorer) -> None:
    _, request = _matched_pair()
    del request.joints["wrist_3_joint"]
    with pytest.raises(ValueError, match="missing joints"):
        scorer.score_request(request)


def test_features_version_mismatch_detected(scorer: Scorer) -> None:
    assert scorer.features_version_matches()
    object.__setattr__(scorer._manifest, "features_version", "9.9.9")
    assert not scorer.features_version_matches()
