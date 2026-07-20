"""Shared contracts for twin-services.

The single source of truth for every cross-service payload: Pydantic models
for MQTT/REST (``contracts.models``) and generated protobuf/gRPC stubs
(``contracts.gen``). Services import shapes from here and never define their
own — CI enforces it.
"""

from contracts.detection import (
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
from contracts.models import (
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

__all__ = [
    "SCHEMA_VERSION",
    "UR5_JOINT_NAMES",
    "AnomalyScore",
    "CommandKind",
    "CommandReceipt",
    "FaultCommand",
    "FaultKind",
    "FaultState",
    "JointCommand",
    "JointField",
    "JointTelemetry",
    "JointWindow",
    "WindowScoreRequest",
    "anomaly_score_topic",
    "command_topic",
    "fault_cmd_topic",
    "fault_state_topic",
    "parse_telemetry_topic",
    "telemetry_topic",
    "telemetry_wildcard",
]
