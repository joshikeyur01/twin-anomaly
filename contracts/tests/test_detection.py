"""Detection contract tests: round-trips, validator fences, evolution.

Same rule as test_contracts.py: deleting a field or loosening a validator
must break something here before it breaks a service.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from contracts import (
    AnomalyScore,
    FaultCommand,
    FaultKind,
    FaultState,
    JointWindow,
    WindowScoreRequest,
    anomaly_score_topic,
    fault_cmd_topic,
    fault_state_topic,
)


class TestFaultCommand:
    def test_roundtrip(self) -> None:
        cmd = FaultCommand(kind=FaultKind.STUCK, joint="elbow_joint", duration_s=5)
        again = FaultCommand.model_validate_json(cmd.model_dump_json())
        assert again == cmd
        assert again.command_id == cmd.command_id

    def test_cli_defaults(self) -> None:
        # The bare invocation `just inject friction` must be a valid payload.
        cmd = FaultCommand(kind=FaultKind.FRICTION)
        assert cmd.joint is None and cmd.severity == 1.0
        assert cmd.duration_s == 10.0 and cmd.seed == 0
        assert len(cmd.command_id) == 32  # uuid4 hex

    def test_clear_takes_no_joint(self) -> None:
        assert FaultCommand(kind=FaultKind.NONE).kind is FaultKind.NONE
        with pytest.raises(ValidationError, match="clear takes no joint"):
            FaultCommand(kind=FaultKind.NONE, joint="elbow_joint")

    def test_dropout_cannot_target_a_joint(self) -> None:
        with pytest.raises(ValidationError, match="cannot target a joint"):
            FaultCommand(kind=FaultKind.DROPOUT, joint="elbow_joint")

    def test_bounds(self) -> None:
        with pytest.raises(ValidationError):
            FaultCommand(kind=FaultKind.ENCODER, severity=0)
        with pytest.raises(ValidationError):
            FaultCommand(kind=FaultKind.ENCODER, severity=11)
        with pytest.raises(ValidationError):
            FaultCommand(kind=FaultKind.ENCODER, duration_s=301)
        with pytest.raises(ValidationError):
            FaultCommand(kind=FaultKind.ENCODER, seed=-1)

    def test_tomorrows_producer_todays_consumer(self) -> None:
        cmd = FaultCommand.model_validate_json(
            '{"kind": "stuck", "command_id": "ab", "ramp_s": 0.5, "schema_version": 2}'
        )
        assert cmd.schema_version == 2  # unknown field ignored, never rejected


class TestFaultState:
    def test_active_label_roundtrip(self) -> None:
        state = FaultState(
            active=True,
            kind=FaultKind.ENCODER,
            severity=2.0,
            command_id="ab" * 16,
            started_ns=100,
            stamp_ns=1_100,
        )
        assert FaultState.model_validate_json(state.model_dump_json()) == state

    def test_active_requires_a_real_kind(self) -> None:
        with pytest.raises(ValidationError, match="cannot have kind none"):
            FaultState(active=True, kind=FaultKind.NONE, command_id="x", started_ns=0, stamp_ns=0)

    def test_inactive_must_be_none(self) -> None:
        # The end-of-fault message says "normal", in the same vocabulary
        # the dataset labels use.
        with pytest.raises(ValidationError, match="must have kind none"):
            FaultState(active=False, kind=FaultKind.STUCK, command_id="x", started_ns=0, stamp_ns=0)
        end = FaultState(
            active=False, kind=FaultKind.NONE, command_id="x", started_ns=0, stamp_ns=5
        )
        assert end.severity == 0.0


class TestScoring:
    def test_joint_window_channels_align(self) -> None:
        with pytest.raises(ValidationError, match="lengths differ"):
            JointWindow(positions=[0.1, 0.2], velocities=[0.0], efforts=[0.0, 0.0])
        with pytest.raises(ValidationError, match="empty window"):
            JointWindow(positions=[], velocities=[], efforts=[])

    def test_request_must_be_rectangular(self) -> None:
        square = JointWindow(positions=[0.1, 0.2], velocities=[0.0, 0.0], efforts=[0.0, 0.0])
        long = JointWindow(positions=[0.1] * 3, velocities=[0.0] * 3, efforts=[0.0] * 3)
        with pytest.raises(ValidationError, match="disagree on window length"):
            WindowScoreRequest(
                window_start_ns=0,
                sample_period_ns=20_000_000,
                joints={"elbow_joint": square, "wrist_1_joint": long},
            )
        with pytest.raises(ValidationError, match="no joints"):
            WindowScoreRequest(window_start_ns=0, sample_period_ns=20_000_000, joints={})

    def test_score_roundtrip_and_ordering(self) -> None:
        score = AnomalyScore(
            score=0.87,
            threshold=0.6,
            verdict=True,
            artefact="isoforest-v1",
            features_version="0.1.0",
            window_start_ns=0,
            window_end_ns=2_000_000_000,
        )
        assert AnomalyScore.model_validate_json(score.model_dump_json()) == score
        with pytest.raises(ValidationError, match="must be after"):
            AnomalyScore(
                score=0.1,
                threshold=0.6,
                verdict=False,
                artefact="isoforest-v1",
                features_version="0.1.0",
                window_start_ns=5,
                window_end_ns=5,
            )


class TestTopics:
    def test_topic_scheme(self) -> None:
        assert fault_cmd_topic("ur5") == "twin/ur5/fault/cmd"
        assert fault_state_topic("ur5") == "twin/ur5/fault/state"
        assert anomaly_score_topic("ur5") == "twin/ur5/anomaly/score"
