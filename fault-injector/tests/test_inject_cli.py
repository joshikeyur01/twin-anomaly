"""CLI surface and argument->contract mapping; publishing needs a broker
and is covered by the stack integration test instead."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from contracts import FaultKind
from fault_injector.cli import FAULTS, build_parser, command_from_args


def test_cli_surface_is_fixed() -> None:
    parser = build_parser()
    for fault in FAULTS:
        args = parser.parse_args([fault, "--joint", "elbow_joint", "--duration", "5"])
        assert args.fault == fault
        assert args.duration == 5.0
    assert parser.parse_args(["clear"]).fault == "clear"


def test_clear_maps_to_none() -> None:
    cmd = command_from_args(build_parser().parse_args(["clear"]))
    assert cmd.kind is FaultKind.NONE and cmd.joint is None


def test_flags_reach_the_contract() -> None:
    argv = ["encoder", "--joint", "elbow_joint", "--severity", "2.5"]
    args = build_parser().parse_args([*argv, "--duration", "30", "--seed", "7"])
    cmd = command_from_args(args)
    assert cmd.kind is FaultKind.ENCODER
    assert cmd.joint == "elbow_joint"
    assert cmd.severity == 2.5 and cmd.duration_s == 30.0 and cmd.seed == 7


def test_contract_validators_are_the_argument_validation() -> None:
    # dropout --joint parses fine as argv; the contract rejects it.
    args = build_parser().parse_args(["dropout", "--joint", "elbow_joint"])
    with pytest.raises(ValidationError, match="cannot target a joint"):
        command_from_args(args)
