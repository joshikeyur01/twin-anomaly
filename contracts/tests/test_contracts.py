"""Contract tests: round-trips, wire compatibility, and evolution guards.

If a change here feels annoying, that is the point — these tests are the
fence around the wire format (ADR-0003). Deleting a model field must break
something before it breaks a service.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from contracts import (
    SCHEMA_VERSION,
    UR5_JOINT_NAMES,
    CommandKind,
    CommandReceipt,
    JointCommand,
    JointField,
    JointTelemetry,
    command_topic,
    parse_telemetry_topic,
    telemetry_topic,
    telemetry_wildcard,
)
from contracts.gen import state_pb2


class TestJointTelemetry:
    def test_roundtrip(self) -> None:
        sample = JointTelemetry(value=1.57, stamp_ns=123_456_789)
        again = JointTelemetry.model_validate_json(sample.model_dump_json())
        assert again == sample

    def test_legacy_twin_hello_payload_parses_as_v1(self) -> None:
        # Yesterday's producer: the twin-hello bridge wire format has no
        # schema_version. It must parse forever.
        sample = JointTelemetry.model_validate_json('{"value": 0.5, "stamp_ns": 42}')
        assert sample.schema_version == SCHEMA_VERSION == 1
        assert sample.value == 0.5

    def test_tomorrows_producer_todays_consumer(self) -> None:
        # Unknown fields must be ignored, never rejected (additive evolution).
        sample = JointTelemetry.model_validate_json(
            '{"value": 0.5, "stamp_ns": 42, "schema_version": 2, "torque_ripple": 0.1}'
        )
        assert sample.schema_version == 2

    def test_negative_stamp_rejected(self) -> None:
        with pytest.raises(ValidationError):
            JointTelemetry(value=0.0, stamp_ns=-1)


class TestJointCommand:
    def test_home_takes_no_positions(self) -> None:
        assert JointCommand(kind=CommandKind.HOME).positions is None
        with pytest.raises(ValidationError, match="home takes no positions"):
            JointCommand(kind=CommandKind.HOME, positions={"elbow_joint": 1.0})

    def test_move_joints_requires_positions(self) -> None:
        with pytest.raises(ValidationError, match="move_joints requires positions"):
            JointCommand(kind=CommandKind.MOVE_JOINTS)
        cmd = JointCommand(kind=CommandKind.MOVE_JOINTS, positions={"elbow_joint": 1.0})
        assert cmd.duration_s == 2.0  # default

    def test_duration_bounds(self) -> None:
        with pytest.raises(ValidationError):
            JointCommand(kind=CommandKind.HOME, duration_s=0)
        with pytest.raises(ValidationError):
            JointCommand(kind=CommandKind.HOME, duration_s=31)

    def test_rest_body_shape(self) -> None:
        # The exact JSON command-svc's DoD promises: {"kind": "home"}.
        cmd = JointCommand.model_validate_json('{"kind": "home"}')
        assert cmd.kind is CommandKind.HOME

    def test_receipt_roundtrip(self) -> None:
        receipt = CommandReceipt(command_id="ab" * 16, kind=CommandKind.HOME, topic="t")
        assert CommandReceipt.model_validate_json(receipt.model_dump_json()) == receipt


class TestTopics:
    def test_build_parse_roundtrip(self) -> None:
        for joint in UR5_JOINT_NAMES:
            for field in JointField:
                topic = telemetry_topic("ur5", joint, field)
                assert parse_telemetry_topic(topic) == ("ur5", joint, field)

    @pytest.mark.parametrize(
        "bad",
        [
            "twin/ur5/cmd/joints",
            "twin/ur5/joint/elbow_joint",
            "twin/ur5/joint/elbow_joint/torque",
            "other/ur5/joint/elbow_joint/position",
            "",
        ],
    )
    def test_parse_rejects_non_telemetry(self, bad: str) -> None:
        with pytest.raises(ValueError, match="not a telemetry topic"):
            parse_telemetry_topic(bad)

    def test_wildcard_matches_topic_shape(self) -> None:
        assert telemetry_wildcard("ur5") == "twin/ur5/joint/+/+"
        assert command_topic("ur5") == "twin/ur5/cmd/joints"


class TestProto:
    def test_twinstate_roundtrip(self) -> None:
        state = state_pb2.TwinState(
            schema_version=SCHEMA_VERSION, asset="ur5", stamp_ns=42, rms_window_s=2.0
        )
        state.end_effector.position_m.x = -0.81725
        state.joints.add(name="elbow_joint", position_rad=1.57, velocity_rms=0.1)
        again = state_pb2.TwinState.FromString(state.SerializeToString())
        assert again == state
        assert again.joints[0].name == "elbow_joint"

    def test_field_numbers_are_locked(self) -> None:
        # Renumbering a proto field silently corrupts old payloads (ADR-0003).
        # This pins the numbers so a renumber fails loudly.
        fields = {f.name: f.number for f in state_pb2.TwinState.DESCRIPTOR.fields}
        assert fields == {
            "schema_version": 1,
            "asset": 2,
            "stamp_ns": 3,
            "end_effector": 4,
            "joints": 5,
            "rms_window_s": 6,
        }
