"""Per-window feature computation. numpy-only, no I/O.

The feature set is deliberately small and legible — five per-joint stats
plus one window-level count — because ADR-0003 has to defend every one of
them against the three-line rule baseline. Effort is carried in the sample
layout but not featurised: our fault transforms don't touch it (ADR-0002),
so an effort feature would be constant noise on this dataset. It stays in
the array for the day a fault does.

Empty windows (full drop-out) never produce NaN: every stat is defined as
0.0 when there are no samples, and ``n_samples`` = 0 carries the signal.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import numpy.typing as npt

from features.windows import Window

# Order is the contract: this list, times the joint list, is the vector
# layout every artefact is trained against. Never reorder — append only.
PER_JOINT_FEATURES = ("pos_std", "pos_ptp", "vel_rms", "vel_std", "vel_mean_abs")


def feature_names(joint_names: Sequence[str]) -> list[str]:
    """The feature vector's column names, in vector order."""
    names = [f"{joint}__{stat}" for joint in joint_names for stat in PER_JOINT_FEATURES]
    names.append("n_samples")
    return names


def compute_features(window: Window, joint_names: Sequence[str]) -> npt.NDArray[np.float64]:
    """One window becomes one feature vector aligned with ``feature_names``."""
    values = window.values
    n = window.n_samples
    out: list[float] = []
    for joint_index in range(len(joint_names)):
        if n == 0:
            out.extend(0.0 for _ in PER_JOINT_FEATURES)
            continue
        position = values[:, joint_index, 0]
        velocity = values[:, joint_index, 1]
        out.append(float(np.std(position)))
        out.append(float(np.ptp(position)))
        out.append(float(np.sqrt(np.mean(np.square(velocity)))))
        out.append(float(np.std(velocity)))
        out.append(float(np.mean(np.abs(velocity))))
    out.append(float(n))
    return np.asarray(out, dtype=np.float64)
