"""Runtime configuration, loaded from environment variables.

Window length, hop, and the labelling boundary policy are deliberately NOT
config: they live in the ``features`` package and change only with its
version (ADR-0003). Config here is connection and output plumbing only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    influx_url: str
    influx_token: str
    influx_org: str
    influx_bucket: str
    out_dir: Path

    @classmethod
    def from_env(cls) -> PipelineConfig:
        return cls(
            influx_url=os.getenv("INFLUX_URL", "http://localhost:8086"),
            influx_token=os.getenv("INFLUX_TOKEN", "dev-token-change-me"),
            influx_org=os.getenv("INFLUX_ORG", "twin"),
            influx_bucket=os.getenv("INFLUX_BUCKET", "telemetry"),
            out_dir=Path(os.getenv("DATASET_OUT_DIR", "data")),
        )
