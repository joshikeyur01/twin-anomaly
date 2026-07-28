"""Transforms are pure and ROS-free — these tests must run without rclpy.

Every fault is exercised deterministically: fixed inputs, explicit seeds,
exact expectations. If a transform's behaviour drifts, the dataset's
meaning drifts with it — these tests are the fence.
"""

from __future__ import annotations

from contracts import FaultCommand, FaultKind
from fault_injector.transforms import (
    JointSnapshot,
    from_command,
    make_dropout,
    make_encoder,
    make_friction,
    make_stuck,
    passthrough,
)


def snap(
    positions: tuple[float, ...] = (0.1, -1.2),
    velocities: tuple[float, ...] = (0.0, 0.4),
    stamp_ns: int = 1_700_000_000_000_000_000,
) -> JointSnapshot:
    return JointSnapshot(
        stamp_ns=stamp_ns,
        names=("shoulder_pan_joint", "elbow_joint"),
        positions=positions,
        velocities=velocities,
        efforts=(1.5, -0.3),
    )


class TestPassthrough:
    def test_identity(self) -> None:
        assert passthrough(snap()) is snap() or passthrough(snap()) == snap()

    def test_snapshot_is_immutable(self) -> None:
        try:
            snap().positions = (0.0, 0.0)  # type: ignore[misc]
        except AttributeError:
            return
        raise AssertionError("JointSnapshot must be frozen")


class TestFriction:
    def test_constant_stream_is_fixed_point(self) -> None:
        transform = make_friction(severity=1.0, joint=None)
        for _ in range(3):
            out = transform(snap(velocities=(0.0, 0.0)))
            assert out is not None
            assert out.positions == snap().positions

    def test_step_change_lags(self) -> None:
        transform = make_friction(severity=1.0, joint=None)  # lag = 0.5
        assert transform(snap(positions=(0.0, 0.0))) is not None
        out = transform(snap(positions=(1.0, 1.0)))
        assert out is not None
        assert out.positions == (0.5, 0.5)  # halfway, not there yet

    def test_velocity_attenuated_efforts_untouched(self) -> None:
        out = make_friction(severity=1.0, joint=None)(snap(velocities=(0.8, 0.4)))
        assert out is not None
        assert out.velocities == (0.4, 0.2)
        assert out.efforts == snap().efforts

    def test_severity_scales_lag(self) -> None:
        gentle = make_friction(severity=0.1, joint=None)(snap(velocities=(1.0, 1.0)))
        harsh = make_friction(severity=9.0, joint=None)(snap(velocities=(1.0, 1.0)))
        assert gentle is not None and harsh is not None
        assert gentle.velocities[0] > harsh.velocities[0]

    def test_targets_one_joint(self) -> None:
        out = make_friction(severity=1.0, joint="elbow_joint")(snap(velocities=(0.8, 0.4)))
        assert out is not None
        assert out.velocities == (0.8, 0.2)  # shoulder untouched


class TestEncoder:
    def test_same_seed_same_noise(self) -> None:
        a = make_encoder(severity=1.0, seed=42, joint=None)(snap())
        b = make_encoder(severity=1.0, seed=42, joint=None)(snap())
        assert a is not None and b is not None
        assert a.positions == b.positions
        assert a.positions != snap().positions  # it did perturb

    def test_different_seed_differs(self) -> None:
        a = make_encoder(severity=1.0, seed=1, joint=None)(snap())
        b = make_encoder(severity=1.0, seed=2, joint=None)(snap())
        assert a is not None and b is not None
        assert a.positions != b.positions

    def test_only_positions_perturbed(self) -> None:
        out = make_encoder(severity=1.0, seed=7, joint=None)(snap())
        assert out is not None
        assert out.velocities == snap().velocities
        assert out.efforts == snap().efforts

    def test_targets_one_joint(self) -> None:
        out = make_encoder(severity=1.0, seed=7, joint="elbow_joint")(snap())
        assert out is not None
        assert out.positions[0] == snap().positions[0]
        assert out.positions[1] != snap().positions[1]


class TestStuck:
    def test_freezes_at_first_seen_value(self) -> None:
        transform = make_stuck(joint="elbow_joint")
        assert transform(snap(positions=(0.1, -1.2))) is not None
        out = transform(snap(positions=(0.5, 0.9), velocities=(0.2, 0.7)))
        assert out is not None
        assert out.positions == (0.5, -1.2)  # shoulder live, elbow frozen
        assert out.velocities == (0.2, 0.0)

    def test_all_joints_when_untargeted(self) -> None:
        transform = make_stuck(joint=None)
        assert transform(snap(positions=(0.1, -1.2))) is not None
        out = transform(snap(positions=(9.0, 9.0)))
        assert out is not None
        assert out.positions == (0.1, -1.2)


class TestDropout:
    def test_every_sample_vanishes(self) -> None:
        transform = make_dropout()
        assert transform(snap()) is None
        assert transform(snap(stamp_ns=2)) is None


class TestFromCommand:
    def test_clear_is_passthrough(self) -> None:
        assert from_command(FaultCommand(kind=FaultKind.NONE)) is passthrough

    def test_each_kind_builds_its_fault(self) -> None:
        # Behavioural check, not isinstance: dropout drops, stuck freezes,
        # encoder perturbs, friction attenuates.
        assert from_command(FaultCommand(kind=FaultKind.DROPOUT))(snap()) is None
        stuck = from_command(FaultCommand(kind=FaultKind.STUCK))
        assert stuck(snap()) is not None
        out = from_command(FaultCommand(kind=FaultKind.ENCODER, seed=3))(snap())
        assert out is not None and out.positions != snap().positions
        out = from_command(FaultCommand(kind=FaultKind.FRICTION))(snap(velocities=(1.0, 1.0)))
        assert out is not None and out.velocities == (0.5, 0.5)
