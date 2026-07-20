"""Pydantic contracts for everything crossing MQTT or REST.

Every payload that crosses a service boundary is one of these models — raw
dicts stop at the transport callback. The gRPC side of the contract lives in
``contracts/proto``; this module is the JSON side.

Wire compatibility: ``JointTelemetry`` models the exact payload the vendored
twin-hello bridge already publishes. ``schema_version`` is additive with a
default, so legacy messages without it parse as version 1 (ADR-0003). For the
same reason no model here forbids extra fields: consumers must ignore fields
they don't know yet.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

SCHEMA_VERSION = 1

# Shared vocabulary: joint order is load-bearing (FK in state-svc, bone order
# in viz-svc), so it is a contract, not a service detail.
UR5_JOINT_NAMES: tuple[str, ...] = (
    "shoulder_pan_joint",
    "shoulder_lift_joint",
    "elbow_joint",
    "wrist_1_joint",
    "wrist_2_joint",
    "wrist_3_joint",
)


class JointField(StrEnum):
    """The three per-joint telemetry channels the bridge publishes."""

    POSITION = "position"
    VELOCITY = "velocity"
    EFFORT = "effort"


# ─── topics ──────────────────────────────────────────────────────────────────

_TELEMETRY_TOPIC = re.compile(
    r"^twin/(?P<asset>[^/]+)/joint/(?P<joint>[^/]+)"
    r"/(?P<field>position|velocity|effort)$"
)


def telemetry_topic(asset: str, joint: str, field: JointField) -> str:
    """Topic the bridge publishes one ``JointTelemetry`` payload to."""
    return f"twin/{asset}/joint/{joint}/{field}"


def telemetry_wildcard(asset: str = "+") -> str:
    """Subscription filter matching every telemetry topic for an asset."""
    return f"twin/{asset}/joint/+/+"


def parse_telemetry_topic(topic: str) -> tuple[str, str, JointField]:
    """Split a telemetry topic into (asset, joint, field); raise on anything else."""
    match = _TELEMETRY_TOPIC.match(topic)
    if match is None:
        raise ValueError(f"not a telemetry topic: {topic!r}")
    return match["asset"], match["joint"], JointField(match["field"])


def command_topic(asset: str) -> str:
    """Topic command-svc publishes ``JointCommand`` setpoints to."""
    return f"twin/{asset}/cmd/joints"


# ─── payloads ────────────────────────────────────────────────────────────────


class JointTelemetry(BaseModel):
    """One joint field at one instant — the payload on each telemetry topic.

    Field names and types must not change: this is the twin-hello wire format,
    and the vendored bridge publishes it verbatim.
    """

    schema_version: int = Field(default=SCHEMA_VERSION, ge=1)
    value: float
    stamp_ns: int = Field(..., ge=0)


class CommandKind(StrEnum):
    HOME = "home"
    MOVE_JOINTS = "move_joints"


class JointCommand(BaseModel):
    """A setpoint request: REST body at command-svc, then MQTT payload on
    ``twin/<asset>/cmd/joints``, then forwarded to ROS 2 by the bridge."""

    schema_version: int = Field(default=SCHEMA_VERSION, ge=1)
    kind: CommandKind
    positions: dict[str, float] | None = Field(
        default=None, description="Target angle in radians, keyed by joint name."
    )
    duration_s: float = Field(default=2.0, gt=0, le=30)

    @model_validator(mode="after")
    def _positions_match_kind(self) -> JointCommand:
        if self.kind is CommandKind.MOVE_JOINTS and not self.positions:
            raise ValueError("move_joints requires positions")
        if self.kind is CommandKind.HOME and self.positions:
            raise ValueError("home takes no positions")
        return self


class CommandReceipt(BaseModel):
    """command-svc's REST response: what was accepted and where it went."""

    schema_version: int = Field(default=SCHEMA_VERSION, ge=1)
    command_id: str = Field(..., description="uuid4 hex assigned by command-svc.")
    kind: CommandKind
    topic: str
