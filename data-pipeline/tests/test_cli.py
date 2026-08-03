"""The CLI surface is a public interface; pin it before Phase 2 fills it."""

import pytest

from data_pipeline.cli import build_parser
from data_pipeline.config import PipelineConfig


def test_cli_surface_is_fixed() -> None:
    args = build_parser().parse_args(["--since", "2026-07-18T00:00:00Z", "--name", "corpus"])
    assert args.since == "2026-07-18T00:00:00Z"
    assert args.until is None
    assert args.name == "corpus"


def test_since_is_required() -> None:
    # An unbounded export would silently include yesterday's experiments;
    # the range must be explicit.
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_config_defaults_match_compose() -> None:
    config = PipelineConfig.from_env()
    assert config.influx_url == "http://localhost:8086"
    assert config.influx_bucket == "telemetry"
    assert str(config.out_dir) == "data"
