"""Runtime configuration, loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BridgeConfig:
    mqtt_host: str
    mqtt_port: int
    asset_name: str
    ros_topic: str
    ros_cmd_topic: str
    health_port: int

    @classmethod
    def from_env(cls) -> BridgeConfig:
        return cls(
            mqtt_host=os.getenv("MQTT_HOST", "localhost"),
            mqtt_port=int(os.getenv("MQTT_PORT", "1883")),
            asset_name=os.getenv("ASSET_NAME", "ur5"),
            ros_topic=os.getenv("ROS_JOINT_TOPIC", "/joint_states"),
            ros_cmd_topic=os.getenv(
                "ROS_CMD_TOPIC", "/joint_trajectory_controller/joint_trajectory"
            ),
            health_port=int(os.getenv("HEALTH_PORT", "8080")),
        )
