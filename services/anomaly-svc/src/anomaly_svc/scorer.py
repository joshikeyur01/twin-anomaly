"""The one scorer: a features.Window (or a POST body) becomes an AnomalyScore.

Both entry points — the live MQTT loop and ``POST /score`` — run this same
code, so the number the service returns for a window is the number the
evaluation notebook computed for it. The artefact is a pickled ``detector``
instance; loading it here and scoring with ``detector``'s own code is what
makes "no train/serve skew" true rather than aspirational.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

import features
from contracts import UR5_JOINT_NAMES, AnomalyScore, WindowScoreRequest
from detector import Manifest, load_detector
from detector import Scorer as DetectorScorer
from features import Window, compute_features

_JOINTS = list(UR5_JOINT_NAMES)


class Scorer:
    def __init__(self, detector: DetectorScorer, manifest: Manifest) -> None:
        self._detector = detector
        self._manifest = manifest

    @classmethod
    def load(cls, model_path: Path) -> Scorer:
        """Load the pinned artefact pair (``<stem>.joblib`` + ``<stem>.json``)."""
        detector, manifest = load_detector(model_path.stem, model_path.parent)
        return cls(detector, manifest)

    @property
    def model_version(self) -> str:
        return self._manifest.stem

    def features_version_matches(self) -> bool:
        """Serving features must be the version the artefact was trained on."""
        return self._manifest.features_version == features.__version__

    def score_window(self, window: Window) -> AnomalyScore:
        vector = compute_features(window, _JOINTS)
        raw = float(self._detector.score(vector.reshape(1, -1))[0])
        return AnomalyScore(
            score=raw,
            threshold=self._manifest.threshold,
            verdict=raw >= self._manifest.threshold,
            artefact=self._manifest.stem,
            features_version=self._manifest.features_version,
            window_start_ns=window.start_ns,
            window_end_ns=window.end_ns,
        )

    def score_request(self, request: WindowScoreRequest) -> AnomalyScore:
        return self.score_window(_request_to_window(request))


def _request_to_window(request: WindowScoreRequest) -> Window:
    """Build a features.Window from an explicit POST body, joints in UR5 order."""
    missing = [j for j in _JOINTS if j not in request.joints]
    if missing:
        raise ValueError(f"window missing joints: {missing}")
    n = len(next(iter(request.joints.values())).positions)
    values = np.empty((n, len(_JOINTS), 3), dtype=np.float64)
    for j, joint in enumerate(_JOINTS):
        channel = request.joints[joint]
        values[:, j, 0] = channel.positions
        values[:, j, 1] = channel.velocities
        values[:, j, 2] = channel.efforts
    stamps = request.window_start_ns + np.arange(n, dtype=np.int64) * request.sample_period_ns
    end_ns = int(request.window_start_ns + n * request.sample_period_ns)
    return Window(request.window_start_ns, end_ns, stamps, values)
