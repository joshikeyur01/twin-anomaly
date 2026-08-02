"""Feature values and the no-NaN contract."""

from __future__ import annotations

import math

import numpy as np

from features import Window, compute_features, feature_names
from features.compute import PER_JOINT_FEATURES


def _window(positions: list[float], velocities: list[float]) -> Window:
    n = len(positions)
    values = np.zeros((n, 1, 3), dtype=np.float64)
    values[:, 0, 0] = positions
    values[:, 0, 1] = velocities
    stamps = np.arange(n, dtype=np.int64)
    return Window(start_ns=0, end_ns=n, stamps_ns=stamps, values=values)


def test_feature_names_layout() -> None:
    names = feature_names(["shoulder_pan_joint", "elbow_joint"])
    assert len(names) == 2 * len(PER_JOINT_FEATURES) + 1
    assert names[0] == "shoulder_pan_joint__pos_std"
    assert names[-1] == "n_samples"


def test_known_values() -> None:
    vector = compute_features(_window([0.0, 1.0, 2.0, 3.0], [1.0, 1.0, 1.0, 1.0]), ["j"])
    pos_std, pos_ptp, vel_rms, vel_std, vel_mean_abs, n = vector
    assert pos_std == math.sqrt(1.25)
    assert pos_ptp == 3.0
    assert vel_rms == 1.0
    assert vel_std == 0.0
    assert vel_mean_abs == 1.0
    assert n == 4.0


def test_vector_length_and_dtype() -> None:
    vector = compute_features(_window([0.1] * 5, [0.0] * 5), ["j"])
    assert vector.dtype == np.float64
    assert vector.shape == (len(PER_JOINT_FEATURES) + 1,)


def test_empty_window_is_zeros_never_nan() -> None:
    empty = Window(
        start_ns=0,
        end_ns=1,
        stamps_ns=np.array([], dtype=np.int64),
        values=np.zeros((0, 2, 3), dtype=np.float64),
    )
    vector = compute_features(empty, ["a", "b"])
    assert vector.shape == (2 * len(PER_JOINT_FEATURES) + 1,)
    assert not np.isnan(vector).any()
    assert vector[-1] == 0.0  # n_samples
