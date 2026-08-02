"""The overlap-any labelling boundary policy."""

from __future__ import annotations

from features import FaultInterval, label_window


def _iv(start: int, end: int, kind: str = "stuck") -> FaultInterval:
    return FaultInterval(start_ns=start, end_ns=end, kind=kind, severity=1.0, command_id="x")


def test_no_intervals_is_normal() -> None:
    assert label_window(100, 200, []) is None


def test_any_overlap_labels_the_window() -> None:
    owner = label_window(100, 200, [_iv(150, 300)])
    assert owner is not None and owner.kind == "stuck"


def test_boundary_touch_is_not_overlap() -> None:
    # Half-open windows: a fault starting exactly at the window end does not
    # bleed into it.
    assert label_window(100, 200, [_iv(200, 300)]) is None


def test_greatest_overlap_wins() -> None:
    owner = label_window(100, 200, [_iv(90, 160, "encoder"), _iv(150, 400, "friction")])
    assert owner is not None and owner.kind == "encoder"  # 60 ns vs 50 ns


def test_ties_go_to_the_earlier_fault() -> None:
    owner = label_window(100, 200, [_iv(50, 150, "encoder"), _iv(150, 250, "friction")])
    assert owner is not None and owner.kind == "encoder"  # both 50 ns; first listed wins
