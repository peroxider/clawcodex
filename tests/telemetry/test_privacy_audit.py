"""End-to-end privacy audit tests for telemetry reporter payloads."""
from __future__ import annotations

from clawcodex.telemetry.aggregator import DailyAggregator
from clawcodex.telemetry.config import ReportingConfig
from clawcodex.telemetry.events import EventType, TelemetryEvent
from clawcodex.telemetry.redaction import RedactionConfig, Redactor
from clawcodex.telemetry.reporters.dry_run import DryRunReporter
from clawcodex.telemetry.reporters.issue import IssueReporter
from clawcodex.telemetry.storage import LocalJsonlStorage


class _NoopClient:
    def __init__(self) -> None:
        self.find_titles: list[str] = []
        self.created: list[dict[str, str]] = []

    async def find_issue_by_title(self, title: str, *, state: str = "open") -> None:
        self.find_titles.append(title)
        return None

    async def create_issue(self, *, title: str, body: str, labels: list[str] | None = None) -> dict[str, str]:
        payload = {"number": "1", "title": title, "body": body}
        self.created.append(payload)
        return payload


class _PlatformClient(_NoopClient):
    class platform:
        open_state = "open"


def test_reporter_payload_omits_sensitive_raw_event_fields(tmp_path) -> None:
    date = "2026-06-15"
    storage = LocalJsonlStorage(tmp_path / "telemetry", 7)
    sensitive_values = [
        "write a private prompt about payroll",
        "assistant output with customer secret",
        "full transcript should not leave disk",
        "tool output containing file body",
        "CLAWCODEx_SECRET_TOKEN",
        "ghp_12345678901234567890",
        "/home/alice/project/private.txt",
        "private source file contents",
    ]
    storage.append(
        "events",
        TelemetryEvent(
            type=EventType.SESSION_START,
            session_id="session-1",
            fields={
                "platform": "linux",
                "provider": "anthropic",
                "model": "claude-sonnet",
                "prompt": sensitive_values[0],
                "assistant_output": sensitive_values[1],
                "transcript": sensitive_values[2],
                "tool_output": sensitive_values[3],
                "env": {"CLAWCODEx_SECRET": sensitive_values[4]},
                "api_key": sensitive_values[5],
                "absolute_path": sensitive_values[6],
                "file_contents": sensitive_values[7],
            },
        ).to_dict(),
        date=date,
    )
    storage.append(
        "events",
        TelemetryEvent(
            type=EventType.COMMAND_RUN,
            session_id="session-1",
            fields={
                "command_name": "print",
                "success": True,
                "exit_status": 0,
                "duration_s": 1.25,
                "command_args": "--secret ghp_12345678901234567890",
                "cwd": "/home/alice/project",
            },
        ).to_dict(),
        date=date,
    )

    summary = DailyAggregator(storage).aggregate(date)
    reporter = DryRunReporter()
    rendered = reporter.render(summary, date)

    assert "Sessions: 1" in rendered
    assert "Command runs: 1" in rendered
    assert "anthropic 1" in rendered
    assert "print: 1" in rendered
    for value in sensitive_values:
        assert value not in rendered
    assert "--secret" not in rendered
    assert "/home/alice/project" not in rendered


def test_issue_secret_scan_blocks_upload_without_persisting_body(tmp_path) -> None:
    date = "2026-06-15"
    storage = LocalJsonlStorage(tmp_path / "telemetry", 7)
    client = _PlatformClient()
    reporter = IssueReporter(
        storage=storage,
        redactor=Redactor(RedactionConfig(), (str(tmp_path),)),
        config=ReportingConfig(
            reporting_enabled=True,
            kind="issue",
            platform="github",
            owner="acme",
            repo="widget",
            api_key="token",
        ),
        client=client,
    )
    rendered = "# Summary\nleaked AKIAIOSFODNN7EXAMPLE\nprivate prompt body\n"

    assert reporter.emit(rendered, date=date) is False

    assert not client.find_titles
    assert not client.created
    rows = storage.read_day("reporter_errors", date)
    assert rows and rows[0]["reason"] == "secret_scan"
    assert "rendered" not in rows[0]
    assert "AKIAIOSFODNN7EXAMPLE" not in str(rows[0])
    assert "private prompt body" not in str(rows[0])
