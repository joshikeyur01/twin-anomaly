"""FaultSession semantics under a fake clock: every labelled interval in
the dataset must be opened at injection time and closed exactly once."""

from __future__ import annotations

import pytest

from contracts import FaultCommand, FaultKind
from fault_injector.session import FaultSession
from fault_injector.transforms import JointSnapshot

NS = 1_000_000_000


class FakeClock:
    def __init__(self) -> None:
        self.now_ns = 100 * NS

    def __call__(self) -> int:
        return self.now_ns


def snap(positions: tuple[float, ...] = (0.1, -1.2)) -> JointSnapshot:
    return JointSnapshot(
        stamp_ns=1,
        names=("shoulder_pan_joint", "elbow_joint"),
        positions=positions,
        velocities=(0.0, 0.4),
        efforts=(1.5, -0.3),
    )


def test_idle_is_passthrough_and_silent() -> None:
    session = FaultSession(clock=FakeClock())
    assert session.apply(snap()) == snap()
    assert not session.active
    assert session.heartbeat() is None
    assert session.clear() is None
    assert session.expire_if_due() is None


def test_activate_labels_at_injection_time() -> None:
    clock = FakeClock()
    session = FaultSession(clock=clock)
    opening = session.activate(FaultCommand(kind=FaultKind.STUCK, joint="elbow_joint"))
    assert opening.active and opening.kind is FaultKind.STUCK
    assert opening.started_ns == opening.stamp_ns == clock.now_ns
    assert session.active


def test_activate_rejects_none() -> None:
    with pytest.raises(ValueError, match="use clear"):
        FaultSession(clock=FakeClock()).activate(FaultCommand(kind=FaultKind.NONE))


def test_apply_uses_active_transform_then_recovers() -> None:
    session = FaultSession(clock=FakeClock())
    session.activate(FaultCommand(kind=FaultKind.STUCK))
    assert session.apply(snap(positions=(0.1, -1.2))) is not None
    frozen = session.apply(snap(positions=(9.0, 9.0)))
    assert frozen is not None and frozen.positions == (0.1, -1.2)
    session.clear()
    live = session.apply(snap(positions=(9.0, 9.0)))
    assert live is not None and live.positions == (9.0, 9.0)


def test_heartbeat_carries_the_command() -> None:
    clock = FakeClock()
    session = FaultSession(clock=clock)
    cmd = FaultCommand(kind=FaultKind.ENCODER, severity=2.0, duration_s=10)
    session.activate(cmd)
    clock.now_ns += 3 * NS
    beat = session.heartbeat()
    assert beat is not None and beat.active
    assert beat.command_id == cmd.command_id
    assert beat.started_ns == 100 * NS and beat.stamp_ns == 103 * NS


def test_clear_closes_with_the_ended_commands_id() -> None:
    clock = FakeClock()
    session = FaultSession(clock=clock)
    cmd = FaultCommand(kind=FaultKind.FRICTION, duration_s=10)
    session.activate(cmd)
    clock.now_ns += 2 * NS
    closing = session.clear()
    assert closing is not None and not closing.active
    assert closing.kind is FaultKind.NONE
    assert closing.command_id == cmd.command_id
    assert closing.started_ns == 100 * NS and closing.stamp_ns == 102 * NS
    assert not session.active


def test_expiry_honours_duration() -> None:
    clock = FakeClock()
    session = FaultSession(clock=clock)
    session.activate(FaultCommand(kind=FaultKind.DROPOUT, duration_s=5))
    clock.now_ns += 4 * NS
    assert session.expire_if_due() is None  # still running
    assert session.apply(snap()) is None  # and still dropping
    clock.now_ns += 1 * NS
    closing = session.expire_if_due()
    assert closing is not None and not closing.active
    assert session.apply(snap()) == snap()  # forwarding again
    assert session.expire_if_due() is None  # closes exactly once
