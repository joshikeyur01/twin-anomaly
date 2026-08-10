"""AnomalyWindow reassembles the MQTT stream and ages out on wall-clock time."""

from __future__ import annotations

from anomaly_svc.window import AnomalyWindow
from contracts import UR5_JOINT_NAMES, JointField, JointTelemetry

SEC = 1_000_000_000
FIELDS = (JointField.POSITION, JointField.VELOCITY, JointField.EFFORT)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_700_000_000 * SEC

    def __call__(self) -> int:
        return self.now

    def advance(self, ns: int) -> None:
        self.now += ns


def _observe_full_sample(window: AnomalyWindow, stamp: int, base: float = 0.1) -> None:
    for joint in UR5_JOINT_NAMES:
        for field, value in zip(FIELDS, (base, base * 2, 0.0), strict=True):
            window.observe(joint, field, JointTelemetry(value=value, stamp_ns=stamp))


def test_incomplete_sample_yields_no_window() -> None:
    window = AnomalyWindow(SEC, clock=FakeClock())
    window.observe("elbow_joint", JointField.POSITION, JointTelemetry(value=0.1, stamp_ns=100))
    assert window.to_window() is None


def test_complete_samples_build_the_matrix() -> None:
    window = AnomalyWindow(SEC, clock=FakeClock())
    _observe_full_sample(window, 100, base=0.1)
    _observe_full_sample(window, 200, base=0.2)
    built = window.to_window()
    assert built is not None
    assert built.n_samples == 2
    assert built.values.shape == (2, len(UR5_JOINT_NAMES), 3)
    elbow = UR5_JOINT_NAMES.index("elbow_joint")
    assert built.values[1, elbow, 0] == 0.2


def test_silence_ages_the_window_out() -> None:
    # The drop-out case: telemetry stops, wall-clock time passes, the window
    # empties even though no new (frozen) stamp ever arrives.
    clock = FakeClock()
    window = AnomalyWindow(SEC, clock=clock)
    _observe_full_sample(window, 100)
    assert window.to_window() is not None
    clock.advance(2 * SEC)  # two seconds of silence
    assert window.to_window() is None
