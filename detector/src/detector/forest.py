"""Isolation Forest detector: unsupervised, trained on normal windows only.

Standard-scales features (the scaler is fitted on normal and stored in the
instance, so serving applies exactly the training transform — the "scaler
lives in the artefact" rule from ADR-0003), then scores with the negated
``score_samples`` so higher means more anomalous, matching the Scorer
contract.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

N_ESTIMATORS = 200


class ForestDetector:
    """Fitted IsolationForest + its scaler. Picklable as one artefact."""

    def __init__(self, feature_names: list[str], scaler: Any, forest: Any) -> None:
        self.feature_names = feature_names
        self._scaler = scaler
        self._forest = forest

    def score(self, features: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        scaled = self._scaler.transform(features)
        # score_samples: higher = more normal. Negate for the Scorer contract.
        # score_samples is untyped (sklearn), so pin the dtype explicitly.
        return np.asarray(-self._forest.score_samples(scaled), dtype=np.float64)


def fit_forest(
    normal: npt.NDArray[np.float64], feature_names: list[str], seed: int
) -> ForestDetector:
    """Fit on normal windows only; the seed makes the forest reproducible."""
    scaler = StandardScaler().fit(normal)
    forest = IsolationForest(
        n_estimators=N_ESTIMATORS, random_state=seed, contamination="auto"
    ).fit(scaler.transform(normal))
    return ForestDetector(feature_names, scaler, forest)
