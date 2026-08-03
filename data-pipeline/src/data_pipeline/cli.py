"""`just dataset` — batch InfluxDB telemetry into labelled parquet windows.

Query (query.py) -> build (build.py, pure) -> write. Output is named
``data/<name>-<features version>.parquet``: the feature version is in the
filename because a dataset is only meaningful paired with the code that
windowed it (STYLE.md).
"""

from __future__ import annotations

import argparse
import sys

import features
from data_pipeline.build import build_table, label_balance, write_table
from data_pipeline.config import PipelineConfig
from data_pipeline.query import fetch_fault_intervals, fetch_windows_input


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="just dataset",
        description="Batch InfluxDB telemetry into labelled parquet windows in data/.",
    )
    parser.add_argument(
        "--since",
        required=True,
        help="start of the export range, RFC 3339 (e.g. 2026-07-18T00:00:00Z)",
    )
    parser.add_argument(
        "--until",
        default=None,
        help="end of the export range, RFC 3339 (default: now)",
    )
    parser.add_argument(
        "--name",
        default="dataset",
        help="output prefix: data/<name>-<features version>.parquet",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = PipelineConfig.from_env()

    stamps, values, joint_names = fetch_windows_input(config, args.since, args.until)
    if stamps.shape[0] == 0:
        print("no telemetry in range — nothing written", file=sys.stderr)
        return 1
    intervals = fetch_fault_intervals(config, args.since, args.until)
    table = build_table(stamps, values, joint_names, intervals)

    out_path = config.out_dir / f"{args.name}-{features.__version__}.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_table(table, str(out_path))

    balance = label_balance(table)
    print(f"wrote {table.num_rows} windows -> {out_path}")
    print(f"  features v{features.__version__}, {len(intervals)} fault interval(s)")
    print(f"  label balance: {balance}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
