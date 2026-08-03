"""The I/O boundary: InfluxDB history -> aligned arrays + fault intervals.

Everything database-shaped lives here so ``build.py`` can stay pure. Not
unit-tested (it needs a live InfluxDB); the live ``just collect`` run and
the stack integration test exercise it. Joint and metric order come from
``contracts``, not from Flux column order, so the (T, J, 3) layout is
canonical regardless of how InfluxDB returns rows.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import numpy.typing as npt
from influxdb_client.client.influxdb_client import InfluxDBClient

from contracts import UR5_JOINT_NAMES, FaultKind, JointField
from data_pipeline.config import PipelineConfig
from features import FaultInterval

_METRICS = (JointField.POSITION, JointField.VELOCITY, JointField.EFFORT)


def _to_ns(when: datetime) -> int:
    # datetime carries microseconds; that is finer than our 50 Hz sampling,
    # so no windowing decision turns on the lost sub-microsecond digits.
    return int(when.timestamp() * 1_000_000) * 1_000


def fetch_windows_input(
    config: PipelineConfig, since: str, until: str | None
) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.float64], list[str]]:
    """Pivot joint_telemetry into a time-sorted (T, J, 3) array."""
    stop = until or "now()"
    flux = (
        f'from(bucket: "{config.influx_bucket}")'
        f" |> range(start: {since}, stop: {stop})"
        ' |> filter(fn: (r) => r._measurement == "joint_telemetry")'
        ' |> pivot(rowKey: ["_time"], columnKey: ["joint", "metric"], valueColumn: "_value")'
        ' |> sort(columns: ["_time"])'
    )
    joint_names = list(UR5_JOINT_NAMES)
    stamps: list[int] = []
    rows: list[list[list[float]]] = []
    with InfluxDBClient(
        url=config.influx_url, token=config.influx_token, org=config.influx_org
    ) as client:
        tables = client.query_api().query(flux)
    for table in tables:
        for record in table.records:
            sample: list[list[float]] = []
            complete = True
            for joint in joint_names:
                channels: list[float] = []
                for metric in _METRICS:
                    value = record.values.get(f"{joint}_{metric.value}")
                    if value is None:
                        complete = False
                        break
                    channels.append(float(value))
                if not complete:
                    break
                sample.append(channels)
            if complete:
                stamps.append(_to_ns(record.get_time()))
                rows.append(sample)
    return (
        np.asarray(stamps, dtype=np.int64),
        np.asarray(rows, dtype=np.float64).reshape(len(rows), len(joint_names), 3),
        joint_names,
    )


def fetch_fault_intervals(
    config: PipelineConfig, since: str, until: str | None
) -> list[FaultInterval]:
    """Reconstruct one interval per experiment from its FaultState labels."""
    stop = until or "now()"
    flux = (
        f'from(bucket: "{config.influx_bucket}")'
        f" |> range(start: {since}, stop: {stop})"
        ' |> filter(fn: (r) => r._measurement == "fault_state")'
        ' |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")'
        ' |> sort(columns: ["_time"])'
    )
    with InfluxDBClient(
        url=config.influx_url, token=config.influx_token, org=config.influx_org
    ) as client:
        tables = client.query_api().query(flux)

    starts: dict[str, int] = {}
    ends: dict[str, int] = {}
    kinds: dict[str, str] = {}
    severities: dict[str, float] = {}
    for table in tables:
        for record in table.records:
            command_id = str(record.values.get("command_id"))
            ends[command_id] = _to_ns(record.get_time())
            starts.setdefault(command_id, int(record.values.get("started_ns", 0)))
            kind = str(record.values.get("kind", FaultKind.NONE.value))
            if kind != FaultKind.NONE.value:
                kinds[command_id] = kind
                severities[command_id] = float(record.values.get("severity", 0.0))

    return [
        FaultInterval(
            start_ns=starts[command_id],
            end_ns=ends[command_id],
            kind=kinds[command_id],
            severity=severities[command_id],
            command_id=command_id,
        )
        for command_id in kinds  # only experiments that were ever active
    ]
