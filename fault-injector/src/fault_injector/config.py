"""Runtime configuration, loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InjectorConfig:
    mqtt_host: str
    mqtt_port: int
    asset_name: str
    ros_in_topic: str
    ros_out_topic: str

    @classmethod
    def from_env(cls) -> InjectorConfig:
        return cls(
            mqtt_host=os.getenv("MQTT_HOST", "localhost"),
            mqtt_port=int(os.getenv("MQTT_PORT", "1883")),
            asset_name=os.getenv("ASSET_NAME", "ur5"),
            ros_in_topic=os.getenv("ROS_IN_TOPIC", "/joint_states_raw"),
            ros_out_topic=os.getenv("ROS_OUT_TOPIC", "/joint_states"),
        )
