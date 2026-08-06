"""The scorer contract every detector honours.

Higher score = more anomalous, always. A detector is a fitted object that
maps a feature matrix to a score per row; the threshold that turns scores
into verdicts is chosen separately (``choose_threshold``) and travels in the
manifest, never baked into the model — a model and its operating point are
decided together but stored apart (ADR-0004).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np
import numpy.typing as npt

# Fraction of normal windows allowed to exceed the threshold when it is
# chosen — i.e. the target false-positive rate on the training distribution.
DEFAULT_NORMAL_QUANTILE = 0.99


@runtime_checkable
class Scorer(Protocol):
    """A fitted detector. Instances are pickled whole into the artefact."""

    feature_names: list[str]

    def score(self, features: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]: ...


def choose_threshold(
    normal_scores: npt.NDArray[np.float64], quantile: float = DEFAULT_NORMAL_QUANTILE
) -> float:
    """Pick the operating point from held-out normal scores.

    The quantile is the false-positive rate we accept on normal data: 0.99
    means ~1% of normal windows will be flagged. Choosing it from normal
    (never from fault data) keeps the threshold honest about the one
    distribution we can assume we have plenty of.
    """
    return float(np.quantile(normal_scores, quantile))


def verdicts(scores: npt.NDArray[np.float64], threshold: float) -> npt.NDArray[np.bool_]:
    return scores >= threshold
