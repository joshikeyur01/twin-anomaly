"""Runtime configuration, loaded from environment variables.

MODEL_PATH pins an exact artefact filename (compose mounts models/ at
/models). The detection threshold is deliberately absent here: it lives in
the manifest beside the artefact, because a model and its operating point
are chosen together (ADR-0004).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AnomalyConfig:
    mqtt_host: str
    mqtt_port: int
    asset_name: str
    http_port: int
    model_path: Path

    @classmethod
    def from_env(cls) -> AnomalyConfig:
        return cls(
            mqtt_host=os.getenv("MQTT_HOST", "localhost"),
            mqtt_port=int(os.getenv("MQTT_PORT", "1883")),
            asset_name=os.getenv("ASSET_NAME", "ur5"),
            http_port=int(os.getenv("HTTP_PORT", "8005")),
            model_path=Path(os.getenv("MODEL_PATH", "models/isoforest-v1.joblib")),
        )
