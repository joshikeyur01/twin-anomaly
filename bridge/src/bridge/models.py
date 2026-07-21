"""ROS-side validation model for the bridge.

Only the ROS-facing shape lives here: everything that crosses MQTT uses the
contracts package (JointTelemetry out, JointCommand in), so the wire format
has exactly one definition in the repo.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class JointStateMessage(BaseModel):
    """Validated snapshot of a `sensor_msgs/JointState` at one instant."""

    stamp_ns: int = Field(..., ge=0, description="ROS clock time in nanoseconds.")
    names: list[str] = Field(..., min_length=1)
    positions: list[float]
    velocities: list[float]
    efforts: list[float]

    def field_lengths_match(self) -> bool:
        n = len(self.names)
        return len(self.positions) == len(self.velocities) == len(self.efforts) == n
