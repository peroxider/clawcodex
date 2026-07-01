from __future__ import annotations

import json

from src.agent.conversation import Conversation
from src.types.messages import Message

from clawcodex_ext.intent_forecast.config import IntentForecastConfig
from clawcodex_ext.intent_forecast.context import IntentForecastContextBuilder


def test_context_reads_memory_workspace_and_current_messages(tmp_path) -> None:
    (tmp_path / "CLAUDE.md").write_text("memory note", encoding="utf-8")
    conv = Conversation()
    conv.messages = [Message(role="user", content="continue forecast")]

    context = IntentForecastContextBuilder(
        conversation=conv,
        workspace_root=tmp_path,
        config=IntentForecastConfig(),
        sessions_dir=tmp_path / "sessions",
        feedback_base_dir=tmp_path,
    ).build()

    assert context.current_messages[-1]["content"] == "continue forecast"
    assert context.memory_files[0]["path"] == "CLAUDE.md"
    assert "README.md" not in context.workspace["project_files"]


def test_context_falls_back_to_transcript_tail_and_enqueues_summary(tmp_path, monkeypatch) -> None:
    enqueued: list[str] = []
    monkeypatch.setattr(
        "clawcodex_ext.intent_forecast.context.enqueue_summary_job",
        lambda session_id, **kwargs: enqueued.append(session_id),
    )
    sessions = tmp_path / "sessions"
    session_dir = sessions / "s1"
    session_dir.mkdir(parents=True)
    (session_dir / "metadata.json").write_text(
        json.dumps({"session_id": "s1", "last_updated": 10, "title": "T"}),
        encoding="utf-8",
    )
    (session_dir / "transcript.jsonl").write_text(
        '{"role":"user","content":"tail task"}\n',
        encoding="utf-8",
    )

    context = IntentForecastContextBuilder(
        conversation=None,
        workspace_root=tmp_path,
        config=IntentForecastConfig(summary_lazy_generate=True),
        sessions_dir=sessions,
        feedback_base_dir=tmp_path,
    ).build()

    assert context.sessions[0]["transcript_tail"][0]["content"] == "tail task"
    assert enqueued == ["s1"]
