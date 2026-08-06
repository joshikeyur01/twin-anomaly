"""The honest baseline: a per-feature normal-envelope rule.

The ROADMAP sketched this as "velocity-RMS over a constant", but our faults
mostly *reduce* velocity (stuck, friction) or leave it alone (encoder), so a
one-sided high-velocity threshold would be a strawman the models trivially
beat. The fair simple rule a reasonable engineer writes instead: learn each
feature's normal band and flag a window that falls outside any of them.

score(window) = max over features of how many band-widths the feature sits
outside its normal [p_lo, p_hi] envelope. Three lines of real logic, no
training beyond quantiles — exactly the bar the models must clear to earn
their place (ADR-0004).
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

# A feature's deviation is measured in units of its own normal spread, but
# floored at this fraction of the widest feature's spread so a near-constant
# feature can't divide a hair of noise into an enormous score and swamp the
# threshold. Without it the rule flags nothing — the small-band features win.
REL_FLOOR = 0.02


class RuleDetector:
    """Per-feature envelope rule. Picklable; scored by this same code."""

    def __init__(
        self,
        feature_names: list[str],
        low: npt.NDArray[np.float64],
        high: npt.NDArray[np.float64],
        scale: npt.NDArray[np.float64],
    ) -> None:
        self.feature_names = feature_names
        self._low = low
        self._high = high
        self._scale = scale

    def score(self, features: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        below = (self._low - features) / self._scale
        above = (features - self._high) / self._scale
        outside = np.maximum(np.maximum(below, above), 0.0)
        return np.max(outside, axis=1).astype(np.float64)


def fit_rule(
    normal: npt.NDArray[np.float64],
    feature_names: list[str],
    p_lo: float = 0.01,
    p_hi: float = 0.99,
) -> RuleDetector:
    """Learn each feature's normal band from normal windows only."""
    low = np.quantile(normal, p_lo, axis=0)
    high = np.quantile(normal, p_hi, axis=0)
    # Deviations are normalised by each feature's normal standard deviation so
    # features on different scales (n_samples ~ tens vs pos_std ~ hundredths)
    # are comparable. The relative floor stops a feature with almost no normal
    # variation from turning numerical noise into a runaway score.
    std = np.std(normal, axis=0)
    scale = np.maximum(std, REL_FLOOR * float(np.max(std)))
    return RuleDetector(feature_names, low, high, scale)
