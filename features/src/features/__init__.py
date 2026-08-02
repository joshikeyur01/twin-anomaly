"""The feature contract for twin-anomaly.

One implementation of windowing and feature computation, imported by both
``data-pipeline`` (training time) and ``anomaly-svc`` (serving time) —
training/serving skew dies here or ships to production. numpy in, numpy
out; no I/O, no pandas, no pydantic (``tests/test_purity.py`` enforces it).

``__version__`` is the compatibility token between features and model
artefacts: every manifest records the version it was trained against, and
``anomaly-svc`` refuses readiness on a mismatch. Any change to windowing,
feature definitions, normalisation, or the labelling boundary policy bumps
it — there is no such thing as a silent feature fix.
"""

from __future__ import annotations

from features.compute import PER_JOINT_FEATURES, compute_features, feature_names
from features.labels import FaultInterval, label_window
from features.windows import (
    DEFAULT_SPEC,
    WINDOW_HOP_NS,
    WINDOW_LENGTH_NS,
    Window,
    WindowSpec,
    make_windows,
)

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_SPEC",
    "PER_JOINT_FEATURES",
    "WINDOW_HOP_NS",
    "WINDOW_LENGTH_NS",
    "FaultInterval",
    "Window",
    "WindowSpec",
    "__version__",
    "compute_features",
    "feature_names",
    "label_window",
    "make_windows",
]
