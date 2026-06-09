"""Example fixture data for the Visualizer."""

import json
import time
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent


def create_demo_session(output_dir: Path | None = None) -> str:
    """Create a demo session with sample data for testing the visualizer.

    Returns the session_id of the created session.
    """
    if output_dir is None:
        output_dir = Path.home() / ".clawcodex" / "sessions"

    session_id = f"demo-{int(time.time())}"
    session_dir = output_dir / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    now = time.time()

    # metadata.json
    metadata = {
        "session_id": session_id,
        "title": "Demo Session — Full Pipeline",
        "workspace": str(output_dir),
        "model": "claude-3-sonnet",
        "provider": "anthropic",
        "status": "completed",
        "agent_name": "clawcodex-overview",
        "start_time": now - 120,
        "end_time": now,
        "duration_ms": 120000,
        "turn_count": 8,
        "tool_count": 12,
        "tags": ["demo", "test"],
    }
    (session_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )

    # transcript.jsonl — simulated conversation
    transcript_lines = [
        json.dumps({
            "role": "user",
            "content": "Please analyze the codebase and suggest improvements",
            "timestamp": now - 120,
        }),
        json.dumps({
            "role": "assistant",
            "content": "I'll start by reading the main files...",
            "timestamp": now - 118,
            "tool_calls": [{
                "id": "tc-001",
                "type": "function",
                "function": {"name": "Read", "arguments": {"file_path": "src/main.py"}},
            }],
        }),
        json.dumps({
            "role": "tool",
            "tool_call_id": "tc-001",
            "content": "# main.py\nimport sys\n...",
            "timestamp": now - 117,
        }),
        json.dumps({
            "role": "assistant",
            "content": "Now let me check the test coverage...",
            "timestamp": now - 115,
            "tool_calls": [{
                "id": "tc-002",
                "type": "function",
                "function": {"name": "Bash", "arguments": {"command": "pytest --cov"}},
            }],
        }),
        json.dumps({
            "role": "tool",
            "tool_call_id": "tc-002",
            "content": "Coverage: 67% - needs improvement",
            "timestamp": now - 110,
        }),
        json.dumps({
            "role": "assistant",
            "content": "Let me also search for potential issues...",
            "timestamp": now - 108,
            "tool_calls": [{
                "id": "tc-003",
                "type": "function",
                "function": {"name": "Grep", "arguments": {"pattern": "TODO|FIXME|HACK", "path": "src"}},
            }],
        }),
        json.dumps({
            "role": "tool",
            "tool_call_id": "tc-003",
            "content": "Found 5 TODOs and 2 FIXMEs",
            "timestamp": now - 105,
        }),
        json.dumps({
            "role": "assistant",
            "content": "Based on my analysis, here are the key improvements...",
            "timestamp": now - 100,
        }),
    ]
    (session_dir / "transcript.jsonl").write_text(
        "\n".join(transcript_lines), encoding="utf-8"
    )

    # events.ndjson — simulated tool events
    events = [
        {"event": "tool_call", "tool_name": "Read", "tool_call_id": "tc-001",
         "timestamp": now - 118, "approved": True, "turn": 1,
         "params": {"file_path": "src/main.py"}},
        {"event": "tool_result", "tool_call_id": "tc-001",
         "timestamp": now - 117, "duration_ms": 800},
        {"event": "tool_call", "tool_name": "Bash", "tool_call_id": "tc-002",
         "timestamp": now - 115, "approved": True, "turn": 2,
         "params": {"command": "pytest --cov"}},
        {"event": "tool_result", "tool_call_id": "tc-002",
         "timestamp": now - 110, "duration_ms": 5000},
        {"event": "tool_call", "tool_name": "Grep", "tool_call_id": "tc-003",
         "timestamp": now - 108, "approved": True, "turn": 3,
         "params": {"pattern": "TODO|FIXME|HACK"}},
        {"event": "tool_result", "tool_call_id": "tc-003",
         "timestamp": now - 105, "duration_ms": 2500},
    ]
    events_text = "\n".join(json.dumps(e) for e in events)
    (session_dir / "events.ndjson").write_text(events_text, encoding="utf-8")

    return session_id
