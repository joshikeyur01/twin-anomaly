"""Unit tests for the point conversion and readiness — no broker, no InfluxDB."""

from __future__ import annotations

from prometheus_client import REGISTRY

from contracts import AnomalyScore, FaultKind, FaultState
from telemetry_svc.config import TelemetryConfig
from telemetry_svc.ingest import Ingestor, _fault_point, _score_point, _to_point


def _rejections(reason: str) -> float:
    value = REGISTRY.get_sample_value("twin_telemetry_rejected_total", {"reason": reason})
    return value or 0.0


class TestToPoint:
    def test_valid_message_becomes_point(self) -> None:
        point = _to_point("twin/ur5/joint/elbow_joint/position", '{"value": 1.57, "stamp_ns": 123}')
        assert point is not None
        line = point.to_line_protocol()  # type: ignore[no-untyped-call]  # influx client is untyped
        assert line == (
            "joint_telemetry,asset=ur5,joint=elbow_joint,metric=position value=1.57 123"
        )

    def test_non_telemetry_topic_dropped(self) -> None:
        before = _rejections("topic")
        assert _to_point("twin/ur5/cmd/joints", '{"value": 1, "stamp_ns": 1}') is None
        assert _rejections("topic") == before + 1

    def test_bad_payload_dropped(self) -> None:
        before = _rejections("payload")
        assert _to_point("twin/ur5/joint/elbow_joint/position", "not json") is None
        assert _to_point("twin/ur5/joint/elbow_joint/position", '{"value": "x"}') is None
        assert _rejections("payload") == before + 2

    def test_legacy_wire_format_accepted(self) -> None:
        # The twin-hello bridge payload: no schema_version.
        point = _to_point("twin/ur5/joint/elbow_joint/velocity", '{"value": 0.5, "stamp_ns": 42}')
        assert point is not None


class TestFaultPoint:
    def test_active_label_becomes_point(self) -> None:
        state = FaultState(
            active=True,
            kind=FaultKind.STUCK,
            joint="elbow_joint",
            severity=2.0,
            command_id="cafe" * 8,
            started_ns=100,
            stamp_ns=103,
        )
        point = _fault_point("ur5", state.model_dump_json())
        assert point is not None
        line = point.to_line_protocol()  # type: ignore[no-untyped-call]  # influx client is untyped
        assert line.startswith("fault_state,asset=ur5,joint=elbow_joint,kind=stuck ")
        assert "active=true" in line
        assert 'command_id="' + "cafe" * 8 + '"' in line
        assert "severity=2" in line and "started_ns=100i" in line
        assert line.endswith(" 103")

    def test_untargeted_fault_tags_joint_all(self) -> None:
        state = FaultState(
            active=True,
            kind=FaultKind.DROPOUT,
            severity=1.0,
            command_id="x",
            started_ns=0,
            stamp_ns=1,
        )
        point = _fault_point("ur5", state.model_dump_json())
        assert point is not None
        line = point.to_line_protocol()  # type: ignore[no-untyped-call]  # influx client is untyped
        assert ",joint=all," in line

    def test_closing_label_becomes_point(self) -> None:
        state = FaultState(
            active=False, kind=FaultKind.NONE, command_id="x", started_ns=0, stamp_ns=9
        )
        point = _fault_point("ur5", state.model_dump_json())
        assert point is not None
        line = point.to_line_protocol()  # type: ignore[no-untyped-call]  # influx client is untyped
        assert "active=false" in line and ",kind=none" in line

    def test_bad_label_dropped(self) -> None:
        before = _rejections("payload")
        assert _fault_point("ur5", "not json") is None
        # active=True with kind none violates the contract's coherence rule.
        assert (
            _fault_point(
                "ur5",
                '{"active": true, "kind": "none", "command_id": "x",'
                ' "started_ns": 0, "stamp_ns": 1}',
            )
            is None
        )
        assert _rejections("payload") == before + 2


class TestScorePoint:
    def test_score_becomes_point(self) -> None:
        score = AnomalyScore(
            score=0.87,
            threshold=0.58,
            verdict=True,
            artefact="isoforest-v1",
            features_version="0.1.0",
            window_start_ns=100,
            window_end_ns=1_000_000_100,
        )
        point = _score_point("ur5", score.model_dump_json())
        assert point is not None
        line = point.to_line_protocol()  # type: ignore[no-untyped-call]  # influx client is untyped
        assert line.startswith("anomaly_score,artefact=isoforest-v1,asset=ur5 ")
        assert "verdict=1i" in line and "score=0.87" in line
        assert line.endswith(" 1000000100")  # timestamped at window end

    def test_bad_score_dropped(self) -> None:
        before = _rejections("payload")
        assert _score_point("ur5", "not json") is None
        assert _rejections("payload") == before + 1


class TestReadiness:
    def test_not_ready_before_connecting(self) -> None:
        ingestor = Ingestor(TelemetryConfig.from_env())
        assert ingestor.readiness() == {"mqtt": False, "influxdb": False}
