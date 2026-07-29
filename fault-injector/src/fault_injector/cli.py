"""`just inject` — publish a typed FaultCommand over MQTT. No ROS needed.

The CLI is a thin producer: build the contract model, publish QoS 1, print
the command_id so every experiment is traceable from terminal history. The
contract's validators are the argument validation — a nonsense combination
(dropout with a joint) fails here with the same message it would anywhere.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import aiomqtt
from pydantic import ValidationError

from contracts import FaultCommand, FaultKind, fault_cmd_topic
from fault_injector.config import InjectorConfig

FAULTS = ("friction", "encoder", "stuck", "dropout")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="just inject",
        description="Apply a parameterised fault to the running sim (or clear one).",
    )
    sub = parser.add_subparsers(dest="fault", required=True)
    for fault in FAULTS:
        p = sub.add_parser(fault)
        p.add_argument("--joint", default=None, help="target joint (default: all)")
        p.add_argument("--severity", type=float, default=1.0)
        p.add_argument("--duration", type=float, default=10.0, help="seconds")
        p.add_argument("--seed", type=int, default=0, help="rng seed for stochastic faults")
    sub.add_parser("clear", help="end the active fault immediately")
    return parser


def command_from_args(args: argparse.Namespace) -> FaultCommand:
    """argparse surface -> contract model; validators do the real checking."""
    if args.fault == "clear":
        return FaultCommand(kind=FaultKind.NONE)
    return FaultCommand(
        kind=FaultKind(args.fault),
        joint=args.joint,
        severity=args.severity,
        duration_s=args.duration,
        seed=args.seed,
    )


async def _publish(config: InjectorConfig, cmd: FaultCommand) -> str:
    topic = fault_cmd_topic(config.asset_name)
    async with aiomqtt.Client(config.mqtt_host, port=config.mqtt_port) as client:
        await client.publish(topic, cmd.model_dump_json(), qos=1)
    return topic


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cmd = command_from_args(args)
    except ValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    config = InjectorConfig.from_env()
    try:
        topic = asyncio.run(_publish(config, cmd))
    except aiomqtt.MqttError as exc:
        print(
            f"cannot reach broker at {config.mqtt_host}:{config.mqtt_port} — "
            f"is the stack up? ({exc})",
            file=sys.stderr,
        )
        return 1
    print(f"{cmd.kind.value} -> {topic} (command_id={cmd.command_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
