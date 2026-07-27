"""SMOKE-LKB-002: 《Agent 的 Loop》发布演练 — 真实 AgentLoop + 脚本化 LLM。

End-to-end smoke test (spec §13.7) driving the LKB Plan Graph through the
REAL agent loop (``run_query_as_agent_loop``) with a scripted provider that
mocks the LLM's returns.  Each drill phase is one or more *scenes*: a user
message enters the loop, the scripted provider (the mocked LLM) emits
TaskCreate/TaskUpdate/TaskList tool calls, and the test asserts the
resulting Board state through internal readers (Store snapshot / read model
/ audit events).

Design notes:

* Task ids are server-generated (``T-<hex8>``); the script never hardcodes
  them.  Tool-input factories are evaluated lazily when the provider pops
  the action, resolving ids from the current session projection
  (``ctx.tasks``) by subject prefix (``"T0"`` .. ``"T8"``).
* Multiple executors use independent ``ToolContext`` objects. The Claim
  race uses two OS processes, each with its own Repository and real loop;
  the final recovery read uses a third process with a fresh Session.
* Recovery uses the public ``/lkb revalidate`` command, never the domain
  application service.
* T4's "demo script fails first, then passes" is modelled faithfully at
  the file level (two real ``subprocess`` runs, both outputs kept).
* The six phases run once in a single serial smoke test.  Assertions stay
  adjacent to each phase so failures remain local, while expensive earlier
  phases (especially the multi-process claim race) are not replayed for
  every later checkpoint.
* The smoke does NOT reproduce the drill's "2000+ words per chapter"
  content requirement; it writes real deliverable files and binds their
  sha256 into task metadata instead.

Run:  pytest extensions/lkb/tests/smoke/test_agent_loop_drill.py -q -s
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import multiprocessing
import os
import queue
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from clawcodex_ext.command_system.lkb_command import _lkb_call
from clawcodex_ext.providers.base import ChatResponse
from clawcodex_ext.query.agent_loop_compat import run_query_as_agent_loop
from clawcodex_ext.tool_system.context import ToolContext
from clawcodex_ext.tool_system.defaults import build_default_registry
from clawcodex_ext.types.messages import UserMessage

from lkb.ascii_board import render_board
from lkb.graph_types import NodeRef
from lkb.read_model import build_board_view
from lkb.repository import JsonFileLkbRepository

# ── drill script data ─────────────────────────────────────────────────

# prefix, subject, description
_TASKS = [
    (
        "T0",
        "收集参考资料并撰写术语表",
        "收集 Agent Loop 参考资料，产出 docs/drill/glossary.md",
    ),
    ("T1", "制定文章大纲与章节契约", "产出 docs/drill/outline.md：各章主题、边界、术语用法"),
    ("T2", "撰写第一章「什么是 Agent 的 Loop」", "写入 docs/drill/chapter-1.md"),
    ("T3", "撰写第二章「Loop 中的状态与上下文」", "写入 docs/drill/chapter-2.md"),
    (
        "T4",
        "编写并实际运行 Agent Loop 演示脚本",
        "docs/drill/demo_loop.py；首跑允许失败，修复后通过",
    ),
    ("T5", "全文交叉引用与术语一致性校对", "产出 docs/drill/cross-ref-report.md"),
    ("T6", "撰写第三章「多 Agent 协作与任务调度」", "写入 docs/drill/chapter-3.md"),
    ("T7", "发布前整体审校", "产出 docs/drill/review.md 审校批准"),
    (
        "T8",
        "汇总终稿并撰写发布说明",
        "产出 docs/drill/final.md 与 docs/drill/release-notes.md",
    ),
]

# (dependent, prerequisite)
_DEPS = [
    ("T2", "T1"),
    ("T3", "T1"),
    ("T4", "T2"),
    ("T5", "T2"),
    ("T5", "T3"),
    ("T5", "T0"),
    ("T6", "T3"),
    ("T7", "T4"),
    ("T7", "T5"),
    ("T7", "T6"),
    ("T8", "T7"),
]

_OUTLINE_V1 = """# 《Agent 的 Loop》大纲 v1

## 章节契约
- 第一章：什么是 Agent 的 Loop —— 定义感知-决策-行动循环。
- 第二章：Loop 中的状态与上下文 —— 状态载体与上下文窗口管理。
- 第三章：多 Agent 协作与任务调度 —— 领取、依赖与发布节奏。

## 术语用法
- Loop：单次「观察 → 决策 → 工具调用 → 观察结果」迭代。
- Context：模型每轮可见的消息序列。
"""

_OUTLINE_V2 = """# 《Agent 的 Loop》大纲 v2（迟到的变更）

## 章节契约
- 第一章：什么是 Agent 的 Loop —— 定义感知-决策-行动循环（不变）。
- 第二章：Loop 中的工具调用与权限 —— 由「状态与上下文」改写：工具
  调用的门禁、权限模式与拒绝处理。
- 第三章：多 Agent 协作与任务调度 —— 领取、依赖与发布节奏（不变）。

## 术语用法
- Loop：单次「观察 → 决策 → 工具调用 → 观察结果」迭代。
- Tool Gate：工具执行前的统一校验点。
"""

_GLOSSARY = """# 术语表

- Agent：在 Loop 中调用工具完成目标的执行体。
- Loop：观察-决策-行动-再观察的迭代。
- Claim：对任务的原子领取。
- Revalidate：上游变更后按依赖顺序确认任务仍然有效。
"""

_CROSS_REF = """# 交叉引用与术语一致性校对报告

- 三章对「Loop」的定义一致（见术语表）。
- 第一章引用的演示脚本与 docs/drill/demo_loop.py 行为一致（run2 通过）。
- 结论：无冲突术语，交叉引用闭环。
"""

_REVIEW_V1 = """# 发布前整体审校（v1）

- 大纲契约：符合。
- 章节完整性：符合。
- 演示脚本：run2 通过。
- 结论：APPROVED，允许发布。
"""

_REVIEW_V2 = """# 发布前整体审校（v2，变更后重审）

- 大纲契约 v2：符合（第二章已改写为工具调用与权限）。
- 演示脚本：run3 复跑通过。
- 结论：APPROVED，允许恢复发布。
"""

_FINAL_V1 = """# 《Agent 的 Loop》终稿 v1

（首轮终稿按 outline v1 汇总三章正文，见 chapter-1/2/3。）
"""

_RELEASE_NOTES_V1 = """# 发布说明 v1

- 首次发布：T0~T8 全部完成。
"""

_CHAPTER_2_V2 = """# 第二章 Loop 中的工具调用与权限

Agent Loop 的每次工具调用都要经过统一门禁。门禁依据工具 schema、当前权限模式、
任务所有权和依赖状态决定调用能否执行；被拒绝的调用必须原样返回给模型，供下一轮
观察和修正。权限拒绝不能被文字声明绕过，也不能通过重复调用掩盖。

LKB 把领取、依赖、完成与失效传播纳入同一状态模型，使工具调用结果、任务状态
和发布条件保持一致。本章是迟到变更后的真实 v2 交付物。
"""

_CROSS_REF_V2 = """# 交叉引用与术语一致性校对报告 v2

- 第二章已改为「Loop 中的工具调用与权限」，与 outline v2 一致。
- 三章对「Loop」和「Tool Gate」的用法与术语表一致。
- 演示脚本 run3 通过，全文交叉引用已按 v2 复核。
- 结论：v2 交叉引用闭环。
"""

_FINAL_V2 = """# 《Agent 的 Loop》终稿 v2

终稿按 outline v2 汇总三章正文；第二章现为「Loop 中的工具调用与权限」。
"""

_RELEASE_NOTES_V2 = """# 发布说明 v2

- 迟到变更：第二章由状态与上下文改为工具调用与权限。
- T1 重开后按拓扑序恢复，所有受影响交付物均已重写或重新确认。
- 独立任务 T0 未受影响。
"""

_DEMO_V1 = '''"""Agent Loop 演示（v1，故意失败版）：状态收敛检查。"""

import sys

state = {"goal": "write-chapter", "done": False}
for step in range(3):
    # BUG: 达成条件时忘记置 done，Loop 无法收敛退出
    if step == 2 and state["goal"] == "write-chapter":
        pass
print("loop finished without convergence")
sys.exit("demo failed: loop did not converge")
'''

_DEMO_V2 = '''"""Agent Loop 演示（v2，修复版）：状态收敛检查。"""

import sys

state = {"goal": "write-chapter", "done": False}
for step in range(3):
    if step == 2 and state["goal"] == "write-chapter":
        state["done"] = True
        break
if not state["done"]:
    sys.exit("demo failed: loop did not converge")
print(f"LOOP OK: converged after {step + 1} steps")
'''


def _chapter(title: str) -> str:
    return (
        f"# {title}\n\n"
        "Agent 的 Loop 是「观察 → 决策 → 行动 → 再观察」的迭代过程：\n"
        "每一轮迭代都把上一步的工具结果重新纳入上下文，使下一步决策\n"
        "始终基于最新状态。任务的领取、依赖与完成状态通过逻辑看板\n"
        "（LKB）统一管理，保证多 Agent 协作时语义一致、拒绝可解释。\n"
        "本章正文在冒烟中以真实写入的文件代替完整长文。\n"
    )


# ── scripted provider (the mocked LLM) ────────────────────────────────


def _chat_response(content: str, finish: str, tool_uses=None) -> ChatResponse:
    return ChatResponse(
        content=content,
        model="drill-mock-llm",
        usage={"input_tokens": 1, "output_tokens": 1},
        finish_reason=finish,
        tool_uses=tool_uses,
    )


def _messages_have_tool_result(messages, expected_tool_use_id: str) -> bool:
    for message in messages or ():
        content = (
            message.get("content")
            if isinstance(message, dict)
            else getattr(message, "content", None)
        )
        blocks = content if isinstance(content, list) else (content,)
        for block in blocks:
            block_type = (
                block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
            )
            tool_use_id = (
                block.get("tool_use_id")
                if isinstance(block, dict)
                else getattr(block, "tool_use_id", None)
            )
            if block_type == "tool_result" and tool_use_id == expected_tool_use_id:
                return True
    return False


def _advertised_tool_names(tools) -> set[str]:
    names: set[str] = set()
    for tool in tools or ():
        if isinstance(tool, dict):
            name = tool.get("name")
        else:
            name = getattr(tool, "name", None)
        if isinstance(name, str):
            names.add(name)
    return names


class DrillProvider:
    """Queue-based scripted LLM — the mock of the model's returns.

    Each ``chat`` pops one action:

    * ``("tool", name, input_or_factory)`` → ``finish_reason="tool_use"``.
      Factories are evaluated lazily at pop time so task ids resolve from
      the *current* session projection, never hardcoded.
    * ``("say", text)`` → ``finish_reason="stop"`` (ends the loop run).

    ``before_tool`` (optional hook, e.g. a process ``Barrier``) fires
    right before a tool_use response is returned — used to synchronize
    concurrent claims from two independent loop runs.
    """

    def __init__(self, label, actions, transcript, before_tool=None):
        self.label = label
        self.actions = list(actions)
        self.transcript = transcript
        self.before_tool = before_tool
        self.calls = 0
        self.awaiting_tool_use_id: str | None = None

    def chat(self, messages, tools=None, **kwargs):
        self.calls += 1
        if self.awaiting_tool_use_id is not None:
            assert _messages_have_tool_result(messages, self.awaiting_tool_use_id), (
                f"{self.label}: AgentLoop did not feed tool_result "
                f"{self.awaiting_tool_use_id!r} back to the provider"
            )
            self.awaiting_tool_use_id = None
        if not self.actions:
            raise AssertionError(
                f"{self.label}: scripted action queue exhausted without an explicit stop"
            )
        action = self.actions.pop(0)
        if action[0] == "say":
            self.transcript.append({"actor": self.label, "kind": "say", "text": action[1]})
            return _chat_response(action[1], "stop")
        _, name, spec = action
        advertised = _advertised_tool_names(tools)
        assert name in advertised, (
            f"{self.label}: {name} was not advertised to the provider: {advertised}"
        )
        if callable(spec):
            spec = spec()
        if self.before_tool is not None:
            self.before_tool()
        self.transcript.append(
            {"actor": self.label, "kind": "tool_call", "tool": name, "input": spec}
        )
        tool_use_id = f"drill-{self.label}-{self.calls}"
        self.awaiting_tool_use_id = tool_use_id
        return _chat_response(
            "",
            "tool_use",
            tool_uses=[{"id": tool_use_id, "name": name, "input": spec}],
        )

    def chat_stream(self, messages, tools=None, **kwargs):
        return iter(())

    def chat_stream_response(self, messages, tools=None, **kwargs):
        raise NotImplementedError


# ── fixture + helpers ─────────────────────────────────────────────────


@pytest.fixture
def drill(tmp_path: Path, tmp_home: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Fresh Board + 4 executor contexts + shared transcript."""
    from clawcodex_ext.feature_gate import get_registry
    import lkb.repository as repository_module

    monkeypatch.setitem(get_registry()._overrides, "LKB_PLAN_GRAPH", True)

    ws = tmp_path / "ws"
    (ws / "docs" / "drill").mkdir(parents=True)
    repo = JsonFileLkbRepository(home=tmp_home)
    monkeypatch.setattr(repository_module, "_repository_singleton", repo)
    board_id = repo.resolve_board(ws, session_id="drill-session").board_id

    def _ctx(agent_id: str) -> ToolContext:
        ctx = ToolContext(workspace_root=ws)
        ctx.agent_id = agent_id
        ctx.session_id = "drill-session"
        return ctx

    d = {
        "repo": repo,
        "board_id": board_id,
        "home": tmp_home,
        "ws": ws,
        "ctxs": {a: _ctx(a) for a in ("agent-a", "agent-b", "agent-c", "operator")},
        "names": {},
        "transcript": [],
    }
    # One shared registry; the provider only feeds the (unused) Agent tool.
    d["registry"] = build_default_registry(
        provider=DrillProvider("bootstrap", [], d["transcript"]), load_agent_tools=False
    )
    return d


def run_scene(d, actor: str, actions: list, user_msg: str, *, before_tool=None, max_turns=None):
    """One drill scene: a user message enters the real agent loop; the
    scripted provider (mocked LLM) drives the queued tool calls."""
    ctx = d["ctxs"][actor]
    provider = DrillProvider(actor, actions, d["transcript"], before_tool=before_tool)
    events: list = []
    result = asyncio.run(
        run_query_as_agent_loop(
            initial_messages=[UserMessage(content=user_msg)],
            provider=provider,
            tool_registry=d["registry"],
            tool_context=ctx,
            system_prompt="你是 LKB 发布演练的多 Agent 团队成员，全程使用任务工具管理计划与执行状态。",
            max_turns=max_turns or (len(actions) + 2),
            on_event=events.append,
        )
    )
    assert not provider.actions, f"{actor}: unconsumed scripted actions: {provider.actions}"
    assert provider.awaiting_tool_use_id is None, f"{actor}: final tool result was never observed"
    expected_tool_results = sum(1 for action in actions if action[0] == "tool")
    actual_tool_results = sum(1 for event in events if getattr(event, "kind", "") == "tool_result")
    assert actual_tool_results == expected_tool_results, (
        f"{actor}: expected {expected_tool_results} tool results, got {actual_tool_results}"
    )
    d["transcript"].append(
        {
            "kind": "scene_end",
            "actor": actor,
            "user_msg": user_msg,
            "turns": result.num_turns,
            "tool_results": [
                {
                    # tool_result events carry an empty tool_name; recover it
                    # from the matching tool_use event via tool_use_id.
                    "tool": _tool_names_by_use_id(events).get(getattr(e, "tool_use_id", None), "?"),
                    "is_error": bool(getattr(e, "is_error", False)),
                    "output": str(getattr(e, "tool_output", "") or getattr(e, "error", "") or "")[
                        :300
                    ],
                }
                for e in events
                if getattr(e, "kind", "") == "tool_result"
            ],
        }
    )
    return result, events


def _tool_names_by_use_id(events) -> dict:
    return {
        getattr(e, "tool_use_id", None): getattr(e, "tool_name", "?")
        for e in events
        if getattr(e, "kind", "") == "tool_use"
    }


def _tool_outputs(events, tool: str) -> list[dict]:
    names = _tool_names_by_use_id(events)
    outputs: list[dict] = []
    for event in events:
        if getattr(event, "kind", "") != "tool_result":
            continue
        if names.get(getattr(event, "tool_use_id", None)) != tool:
            continue
        raw = getattr(event, "tool_output", None)
        if isinstance(raw, dict):
            outputs.append(raw)
            continue
        if isinstance(raw, str):
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                outputs.append(parsed)
    return outputs


def _child_repository(home: str) -> JsonFileLkbRepository:
    """Build a process-local repository and feature registry."""
    os.environ["HOME"] = home
    os.environ["USERPROFILE"] = home
    os.environ["CLAWCODEX_HOME"] = home
    os.environ["CLAWCODEX_FEATURE_LKB_PLAN_GRAPH"] = "1"

    import lkb.repository as repository_module
    from clawcodex_ext.feature_gate import get_registry

    get_registry()._overrides["LKB_PLAN_GRAPH"] = True
    repository = JsonFileLkbRepository(home=Path(home))
    repository_module._repository_singleton = repository
    return repository


def _claim_loop_process(args: tuple, result_queue) -> None:
    """Run one real AgentLoop claim in an isolated process."""
    home, workspace, session_id, plan_id, task_id, actor, barrier = args
    try:
        _child_repository(home)
        context = ToolContext(workspace_root=Path(workspace))
        context.agent_id = actor
        context.session_id = session_id
        context.lkb_plan_id = plan_id
        transcript: list[dict] = []
        provider = DrillProvider(
            actor,
            [
                ("tool", "TaskUpdate", {"taskId": task_id, "owner": actor}),
                ("say", "已如实记录系统返回"),
            ],
            transcript,
            before_tool=lambda: barrier.wait(timeout=120),
        )
        registry = build_default_registry(provider=provider, load_agent_tools=False)
        events: list = []
        asyncio.run(
            run_query_as_agent_loop(
                initial_messages=[UserMessage(content="两个子代理同时领取 T1")],
                provider=provider,
                tool_registry=registry,
                tool_context=context,
                system_prompt="你是 LKB 发布演练的子代理。",
                max_turns=4,
                on_event=events.append,
            )
        )
        denied = _scene_denied(events)
        outputs = _tool_outputs(events, "TaskUpdate")
        result_queue.put(
            {
                "actor": actor,
                "decision": "denied" if denied else "committed",
                "outputs": outputs,
                "transcript": transcript,
                "actions_remaining": len(provider.actions),
                "awaiting_tool_result": provider.awaiting_tool_use_id is not None,
            }
        )
    except Exception as exc:  # noqa: BLE001 - marshal child failure to parent
        result_queue.put({"actor": actor, "error": f"{type(exc).__name__}: {exc}"})


def _restart_reader_process(args: tuple, result_queue) -> None:
    """Open the completed Board from a new process, session and ToolContext."""
    home, workspace, session_id, expected_board_id, plan_id = args
    try:
        repository = _child_repository(home)
        context = ToolContext(workspace_root=Path(workspace))
        context.agent_id = "restart-reader"
        context.session_id = session_id
        context.lkb_plan_id = plan_id
        transcript: list[dict] = []
        provider = DrillProvider(
            "restart-reader",
            [("tool", "TaskList", {}), ("say", "重启读取完成")],
            transcript,
        )
        registry = build_default_registry(provider=provider, load_agent_tools=False)
        events: list = []
        asyncio.run(
            run_query_as_agent_loop(
                initial_messages=[UserMessage(content="新会话读取当前 LKB Board")],
                provider=provider,
                tool_registry=registry,
                tool_context=context,
                system_prompt="只通过公开工具读取恢复后的 LKB Board。",
                max_turns=4,
                on_event=events.append,
            )
        )
        task_list = _tool_outputs(events, "TaskList")
        board_text = str(_lkb_call("board", SimpleNamespace(tool_context=context)).value)
        resolved_board_id = repository.resolve_board(
            Path(workspace),
            session_id=session_id,
        ).board_id
        envelope = repository._get_store(expected_board_id).load()
        snapshot = repository.load_snapshot(expected_board_id)
        result_queue.put(
            {
                "resolved_board_id": resolved_board_id,
                "plan_id": context.lkb_plan_id,
                "task_list": task_list,
                "board_text": board_text,
                "states": {
                    ref.id: node.state
                    for ref, node in snapshot.nodes.items()
                    if ref.graph == plan_id and ref.kind == "task"
                },
                "derived": {
                    ref.id: (node.payload or {}).get("derived_status")
                    for ref, node in snapshot.nodes.items()
                    if ref.graph == plan_id and ref.kind == "task"
                },
                "claim_count": len(envelope.claims),
                "store_revision": envelope.store_revision,
                "plan_revision": snapshot.graphs[plan_id].revision,
                "session_binding": envelope.board.get("session_plan_bindings", {}).get(session_id),
                "plan_session_ids": envelope.graphs[plan_id].get("plan", {}).get("session_ids", []),
                "actions_remaining": len(provider.actions),
                "awaiting_tool_result": provider.awaiting_tool_use_id is not None,
            }
        )
    except Exception as exc:  # noqa: BLE001 - marshal child failure to parent
        result_queue.put({"error": f"{type(exc).__name__}: {exc}"})


def _multiprocessing_context():
    try:
        return multiprocessing.get_context("fork")
    except ValueError:
        return multiprocessing.get_context("spawn")


def _collect_process_results(processes, result_queue, expected: int) -> list[dict]:
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=180)
        assert not process.is_alive(), f"child process {process.pid} did not exit"
        assert process.exitcode == 0, f"child process {process.pid} exited {process.exitcode}"
    results: list[dict] = []
    for _ in range(expected):
        try:
            results.append(result_queue.get(timeout=10))
        except queue.Empty as exc:
            raise AssertionError(f"only {len(results)}/{expected} child results arrived") from exc
    return results


def _tid(d, prefix: str) -> str:
    """Resolve the server-generated task id from the session projection."""
    if prefix not in d["names"]:
        ctx = d["ctxs"]["agent-a"]
        for tid, task in ctx.tasks.items():
            if str(task.get("subject", "")).startswith(f"{prefix} "):
                d["names"][prefix] = tid
                break
        else:
            raise AssertionError(f"{prefix} not in projection: {sorted(ctx.tasks)}")
    return d["names"][prefix]


def _plan_id(d) -> str:
    for ctx in d["ctxs"].values():
        pid = getattr(ctx, "lkb_plan_id", None)
        if pid:
            return pid
    raise AssertionError("plan id not resolved yet (run phase 1 first)")


def _env(d):
    return d["repo"]._get_store(d["board_id"]).load()


def _view(d):
    return build_board_view(_env(d), plan_id=_plan_id(d))


def _revision_pair(d) -> tuple[int, int]:
    snapshot = d["repo"].load_snapshot(d["board_id"])
    return snapshot.store_revision, snapshot.graphs[_plan_id(d)].revision


def _badge(d, prefix: str) -> str:
    tid = _tid(d, prefix)
    for row in _view(d).rows:
        if row.task_id == tid:
            return row.badge
    raise AssertionError(f"{prefix} ({tid}) not in board view")


def _node(d, prefix: str):
    snap = d["repo"].load_snapshot(d["board_id"])
    return snap.nodes[NodeRef(_plan_id(d), "task", _tid(d, prefix))]


def _audit(d) -> list:
    return list(_env(d).events)


def _denials(d, code: str, prefix: str | None = None) -> list:
    """Audit denial events carrying `code` (optionally scoped to a task)."""
    out = []
    for e in _audit(d):
        if e.get("decision") != "denied" or code not in str(e.get("reason", "")):
            continue
        if prefix is not None and not str(e.get("subject_ref", "")).endswith(
            f":task:{_tid(d, prefix)}"
        ):
            continue
        out.append(e)
    return out


def _scene_denied(events, tool: str = "TaskUpdate") -> bool:
    names = _tool_names_by_use_id(events)
    return any(
        getattr(e, "kind", "") == "tool_result"
        and getattr(e, "is_error", False)
        and names.get(getattr(e, "tool_use_id", None)) == tool
        for e in events
    )


def _write(d, rel: str, content: str) -> Path:
    path = d["ws"] / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _lkb_mutation(d, command: str, *, actor: str):
    """Execute a mutating public ``/lkb`` command and record its result."""
    text = str(_lkb_call(command, SimpleNamespace(tool_context=d["ctxs"][actor])).value)
    committed = text.startswith("Revalidated ")
    operation = command.split(maxsplit=1)[0]
    d["transcript"].append(
        {
            "kind": "lkb-command",
            "op": operation,
            "command": command,
            "actor": actor,
            "decision": "committed" if committed else "denied",
            "reason": text,
        }
    )
    return SimpleNamespace(decision="committed" if committed else "denied", reason=text)


def _revalidate(d, prefix: str, *, actor: str = "agent-a"):
    return _lkb_mutation(d, f"revalidate {_tid(d, prefix)}", actor=actor)


def _run_demo(d, out_name: str) -> subprocess.CompletedProcess:
    """Really run the demo script and keep the full output on disk."""
    proc = subprocess.run(
        [sys.executable, "demo_loop.py"],
        cwd=d["ws"] / "docs" / "drill",
        capture_output=True,
        text=True,
        timeout=60,
    )
    (d["ws"] / "docs" / "drill" / out_name).write_text(
        f"exit={proc.returncode}\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}\n",
        encoding="utf-8",
    )
    return proc


def _lkb_board_text(d, actor: str = "agent-a") -> str:
    return str(_lkb_call("board", SimpleNamespace(tool_context=d["ctxs"][actor])).value)


def _print_board(d, title: str, capsys) -> None:
    if capsys is not None:
        capsys.readouterr()
        print(f"\n=== {title} ===")
        print(render_board(_view(d), width=110))


# Scene action helpers (closures capture the drill dict at scene build time)


def _act_claim(d, prefix: str, actor: str):
    return ("tool", "TaskUpdate", lambda: {"taskId": _tid(d, prefix), "owner": actor})


def _act_start(d, prefix: str):
    return ("tool", "TaskUpdate", lambda: {"taskId": _tid(d, prefix), "status": "in_progress"})


def _act_complete(d, prefix: str, metadata: dict | None = None):
    def _input():
        inp = {"taskId": _tid(d, prefix), "status": "completed"}
        if metadata is not None:
            inp["metadata"] = metadata
        return inp

    return ("tool", "TaskUpdate", _input)


def _act_dep(d, dep: str, prereq: str):
    return (
        "tool",
        "TaskUpdate",
        lambda: {"taskId": _tid(d, dep), "addBlockedBy": [_tid(d, prereq)]},
    )


def _act_meta(d, prefix: str, metadata: dict):
    return ("tool", "TaskUpdate", lambda: {"taskId": _tid(d, prefix), "metadata": metadata})


# ── phase 1: build the task graph ─────────────────────────────────────


def _phase1(d) -> None:
    actions = []
    for prefix, subject, desc in _TASKS:

        def _create(s=f"{prefix} {subject}", de=desc):
            return {"subject": s, "description": de}

        actions.append(("tool", "TaskCreate", _create))
    for dep, prereq in _DEPS:
        actions.append(_act_dep(d, dep, prereq))
    actions.append(("tool", "TaskList", {}))
    actions.append(("say", "任务图已建立：T0/T1 就绪，T2~T8 阻塞"))
    _, events = run_scene(
        d,
        "agent-a",
        actions,
        "阶段一·规划建图：建立 T0~T8 及依赖",
        max_turns=len(actions) + 2,
    )
    task_list_outputs = _tool_outputs(events, "TaskList")
    assert len(task_list_outputs) == 1
    d["phase1_task_list"] = task_list_outputs[0]


def _assert_phase1(d, capsys) -> None:
    assert _badge(d, "T0") == "ready"
    assert _badge(d, "T1") == "ready"
    for p in ("T2", "T3", "T4", "T5", "T6", "T7", "T8"):
        assert _badge(d, p) == "blocked", f"{p}: expected blocked, got {_badge(d, p)}"
    # TaskList projection carries the compact lkb summary.
    tasks = d["ctxs"]["agent-a"].tasks
    assert tasks[_tid(d, "T5")]["lkb"]["derivedStatus"] == "blocked"
    assert set(tasks[_tid(d, "T5")]["lkb"]["activeBlockers"]) == {
        _tid(d, "T2"),
        _tid(d, "T3"),
        _tid(d, "T0"),
    }
    board_summary = d["phase1_task_list"]["lkbBoard"]
    assert board_summary["boardId"] == d["board_id"]
    assert board_summary["planId"] == _plan_id(d)
    assert board_summary["counts"] == {
        "ready": 2,
        "running": 0,
        "blocked": 7,
        "needsRecheck": 0,
    }
    # /lkb board command renders the same board.
    board_text = _lkb_board_text(d)
    assert f"LKB BOARD: {d['ws'].name} /" in board_text
    assert "Ready 2 | Running 0 | Blocked 7 | Recheck 0 | Issues 7" in board_text
    assert all(len(line) <= 110 for line in board_text.splitlines())
    _print_board(d, "Phase 1: initial blocked graph", capsys)


# ── phase 2: protection-mechanism probes ──────────────────────────────


def _phase2(d) -> None:
    plan = lambda: _plan_id(d)  # noqa: E731 - terse closure

    # (a) cycle probe: T1 depends_on T8 must be denied.
    _, events = run_scene(
        d,
        "agent-a",
        [
            (
                "tool",
                "TaskUpdate",
                lambda: {"taskId": _tid(d, "T1"), "addBlockedBy": [_tid(d, "T8")]},
            ),
            ("say", "已如实记录系统返回"),
        ],
        "探针(a)：尝试让 T1 依赖 T8",
    )
    assert _scene_denied(events), "cycle probe must surface a tool-level denial"
    assert _denials(d, "dependency_cycle", "T1"), "audit must record dependency_cycle"
    env = _env(d)
    assert not any(
        e.get("type") == "depends_on"
        and str(e.get("source", "")) == f"{plan()}:task:{_tid(d, 'T1')}"
        and str(e.get("target", "")) == f"{plan()}:task:{_tid(d, 'T8')}"
        for e in env.edges.values()
    ), "denied edge must not exist in the graph"

    # (b) concurrent claim of T1 from two independent processes, each
    # running its own real AgentLoop + ToolContext + Repository.
    mp_ctx = _multiprocessing_context()
    barrier = mp_ctx.Barrier(2, timeout=120)
    result_queue = mp_ctx.Queue()
    actors = ("agent-a", "agent-b")
    processes = [
        mp_ctx.Process(
            target=_claim_loop_process,
            args=(
                (
                    str(d["home"]),
                    str(d["ws"]),
                    f"claim-process-{actor}",
                    _plan_id(d),
                    _tid(d, "T1"),
                    actor,
                    barrier,
                ),
                result_queue,
            ),
        )
        for actor in actors
    ]
    results = _collect_process_results(processes, result_queue, len(processes))
    assert all("error" not in result for result in results), results
    assert all(result["actions_remaining"] == 0 for result in results)
    assert all(not result["awaiting_tool_result"] for result in results)
    for result in results:
        d["transcript"].extend(result["transcript"])
        d["transcript"].append(
            {
                "kind": "scene_end",
                "actor": result["actor"],
                "user_msg": "探针(b)：两个独立进程同时领取 T1",
                "turns": 2,
                "tool_results": [
                    {
                        "tool": "TaskUpdate",
                        "is_error": result["decision"] == "denied",
                        "output": json.dumps(output, ensure_ascii=False)[:300],
                    }
                    for output in result["outputs"]
                ],
            }
        )
    winners = [result["actor"] for result in results if result["decision"] == "committed"]
    losers = [result["actor"] for result in results if result["decision"] == "denied"]
    assert len(winners) == 1 and len(losers) == 1, (
        f"expected exactly one claim winner, got winners={winners} losers={losers}"
    )
    d["t1_owner"] = winners[0]
    assert _denials(d, "already_claimed", "T1")
    active = [
        c
        for c in _env(d).claims.values()
        if c.get("status") == "active"
        and str(c.get("task_ref", "")) == f"{plan()}:task:{_tid(d, 'T1')}"
    ]
    assert len(active) == 1

    # (c) claim a currently blocked task.
    _, events = run_scene(
        d,
        "agent-c",
        [
            ("tool", "TaskUpdate", lambda: {"taskId": _tid(d, "T2"), "owner": "agent-c"}),
            ("say", "已如实记录系统返回"),
        ],
        "探针(c)：领取仍被阻塞的 T2",
    )
    assert _scene_denied(events)
    assert _denials(d, "blocked", "T2")
    assert d["ctxs"]["agent-c"].tasks[_tid(d, "T2")]["lkb"]["activeBlockers"] == [_tid(d, "T1")]

    # (d) start a task that was never claimed.
    _, events = run_scene(
        d,
        "agent-c",
        [
            ("tool", "TaskUpdate", lambda: {"taskId": _tid(d, "T0"), "status": "in_progress"}),
            ("say", "已如实记录系统返回"),
        ],
        "探针(d)：直接开始未领取的 T0",
    )
    assert _scene_denied(events)
    assert _denials(d, "owner_required", "T0")


def _assert_phase2(d, capsys) -> None:
    assert d["t1_owner"] in ("agent-a", "agent-b")
    _print_board(d, "Phase 2: probes done (T1 claimed, denials audited)", capsys)


# ── phase 3: parallel execution, round 1 ──────────────────────────────


def _phase3(d) -> None:
    owner = d["t1_owner"]

    # T1: start → write outline → complete with deliverable metadata.
    outline = _write(d, "docs/drill/outline.md", _OUTLINE_V1)
    _, events = run_scene(
        d,
        owner,
        [
            _act_start(d, "T1"),
            _act_complete(
                d,
                "T1",
                metadata={
                    "deliverable": {
                        "path": "docs/drill/outline.md",
                        "sha256": _sha256(outline),
                    }
                },
            ),
            ("say", "T1 完成"),
        ],
        "阶段三：T1 启动、写入大纲并完成",
    )
    assert not _scene_denied(events)
    assert _badge(d, "T2") == "ready"
    assert _badge(d, "T3") == "ready"

    # T2 (agent-b): claim → start → write chapter-1 → complete via a single
    # atomic patch (status + deliverable metadata in one TaskUpdate).
    run_scene(
        d,
        "agent-b",
        [_act_claim(d, "T2", "agent-b"), _act_start(d, "T2"), ("say", "T2 进行中")],
        "阶段三：agent-b 领取并启动 T2",
    )
    ch1 = _write(d, "docs/drill/chapter-1.md", _chapter("第一章 什么是 Agent 的 Loop"))
    before_patch = _revision_pair(d)
    _, events = run_scene(
        d,
        "agent-b",
        [
            _act_complete(
                d,
                "T2",
                metadata={
                    "deliverable": {"path": "docs/drill/chapter-1.md", "sha256": _sha256(ch1)}
                },
            ),
            ("say", "T2 完成"),
        ],
        "阶段三：agent-b 完成 T2（patch_task 原子提交）",
    )
    assert not _scene_denied(events)
    assert _node(d, "T2").state == "completed"
    after_patch = _revision_pair(d)
    assert after_patch == (before_patch[0] + 1, before_patch[1] + 1), (
        f"atomic TaskUpdate must publish one Store/Plan revision: {before_patch} -> {after_patch}"
    )

    # T3 (agent-c): claim → start → write chapter-2 → metadata → complete.
    run_scene(
        d,
        "agent-c",
        [_act_claim(d, "T3", "agent-c"), _act_start(d, "T3"), ("say", "T3 进行中")],
        "阶段三：agent-c 领取并启动 T3",
    )
    ch2 = _write(d, "docs/drill/chapter-2.md", _chapter("第二章 Loop 中的状态与上下文"))
    _, events = run_scene(
        d,
        "agent-c",
        [
            _act_meta(
                d,
                "T3",
                {"deliverable": {"path": "docs/drill/chapter-2.md", "sha256": _sha256(ch2)}},
            ),
            _act_complete(d, "T3"),
            ("say", "T3 完成"),
        ],
        "阶段三：agent-c 完成 T3",
    )
    assert not _scene_denied(events)
    assert _node(d, "T3").state == "completed"

    # T4 (agent-c): claim → start, keep a real failed run, fix the demo,
    # run it successfully, then complete with both run hashes recorded.
    run_scene(
        d,
        "agent-c",
        [
            _act_claim(d, "T4", "agent-c"),
            _act_start(d, "T4"),
            ("say", "T4 进行中"),
        ],
        "阶段三：agent-c 领取并启动 T4",
    )
    _write(d, "docs/drill/demo_loop.py", _DEMO_V1)
    run1 = _run_demo(d, "run1.txt")
    assert run1.returncode != 0, "first demo run must fail (drill allows it)"
    _write(d, "docs/drill/demo_loop.py", _DEMO_V2)
    run2 = _run_demo(d, "run2.txt")
    assert run2.returncode == 0, f"fixed demo must pass: {run2.stderr}"
    assert "LOOP OK" in run2.stdout
    _, events = run_scene(
        d,
        "agent-c",
        [
            _act_complete(
                d,
                "T4",
                metadata={
                    "deliverable": {
                        "path": "docs/drill/demo_loop.py",
                        "sha256": _sha256(d["ws"] / "docs" / "drill" / "demo_loop.py"),
                        "run1_sha256": _sha256(d["ws"] / "docs" / "drill" / "run1.txt"),
                        "run2_sha256": _sha256(d["ws"] / "docs" / "drill" / "run2.txt"),
                    }
                },
            ),
            ("say", "T4 完成"),
        ],
        "阶段三：修复后完成 T4",
    )
    assert not _scene_denied(events)
    assert _node(d, "T4").state == "completed"


def _assert_phase3(d, capsys) -> None:
    for rel in ("run1.txt", "run2.txt"):
        assert (d["ws"] / "docs" / "drill" / rel).is_file(), rel
    run1_text = (d["ws"] / "docs" / "drill" / "run1.txt").read_text(encoding="utf-8")
    assert "did not converge" in run1_text
    _print_board(d, "Phase 3: T1~T4 completed (T4 after fail→fix→pass)", capsys)


# ── phase 4: first release ────────────────────────────────────────────


def _phase4(d) -> None:
    # T0 (independent, agent-a).
    run_scene(
        d,
        "agent-a",
        [_act_claim(d, "T0", "agent-a"), _act_start(d, "T0"), ("say", "T0 进行中")],
        "阶段四：agent-a 领取并启动 T0",
    )
    glos = _write(d, "docs/drill/glossary.md", _GLOSSARY)
    run_scene(
        d,
        "agent-a",
        [
            _act_meta(
                d,
                "T0",
                {"deliverable": {"path": "docs/drill/glossary.md", "sha256": _sha256(glos)}},
            ),
            _act_complete(d, "T0"),
            ("say", "T0 完成"),
        ],
        "阶段四：agent-a 完成 T0",
    )

    # T5 (agent-b) — depends on T2, T3, T0 (all completed by now).
    run_scene(
        d,
        "agent-b",
        [_act_claim(d, "T5", "agent-b"), _act_start(d, "T5"), ("say", "T5 进行中")],
        "阶段四：agent-b 领取并启动 T5",
    )
    xref = _write(d, "docs/drill/cross-ref-report.md", _CROSS_REF)
    _, events = run_scene(
        d,
        "agent-b",
        [
            _act_complete(
                d,
                "T5",
                metadata={
                    "deliverable": {
                        "path": "docs/drill/cross-ref-report.md",
                        "sha256": _sha256(xref),
                    }
                },
            ),
            ("say", "T5 完成"),
        ],
        "阶段四：agent-b 完成 T5（patch_task 原子提交）",
    )
    assert not _scene_denied(events)

    # T6 (agent-c).
    run_scene(
        d,
        "agent-c",
        [_act_claim(d, "T6", "agent-c"), _act_start(d, "T6"), ("say", "T6 进行中")],
        "阶段四：agent-c 领取并启动 T6",
    )
    ch3 = _write(d, "docs/drill/chapter-3.md", _chapter("第三章 多 Agent 协作与任务调度"))
    run_scene(
        d,
        "agent-c",
        [
            _act_meta(
                d,
                "T6",
                {"deliverable": {"path": "docs/drill/chapter-3.md", "sha256": _sha256(ch3)}},
            ),
            _act_complete(d, "T6"),
            ("say", "T6 完成"),
        ],
        "阶段四：agent-c 完成 T6",
    )

    # T7 (agent-a): write the review, then complete with its artifact hash.
    review = _write(d, "docs/drill/review.md", _REVIEW_V1)
    _, events = run_scene(
        d,
        "agent-a",
        [
            _act_claim(d, "T7", "agent-a"),
            _act_start(d, "T7"),
            _act_complete(
                d,
                "T7",
                metadata={
                    "deliverable": {
                        "path": "docs/drill/review.md",
                        "sha256": _sha256(review),
                    }
                },
            ),
            ("say", "T7 完成"),
        ],
        "阶段四：完成发布前整体审校 T7",
    )
    assert not _scene_denied(events)

    # T8 (agent-a) — depends on T7.
    run_scene(
        d,
        "agent-a",
        [_act_claim(d, "T8", "agent-a"), _act_start(d, "T8"), ("say", "T8 进行中")],
        "阶段四：agent-a 领取并启动 T8",
    )
    final = _write(d, "docs/drill/final.md", _FINAL_V1)
    notes = _write(d, "docs/drill/release-notes.md", _RELEASE_NOTES_V1)
    _, events = run_scene(
        d,
        "agent-a",
        [
            _act_complete(
                d,
                "T8",
                metadata={
                    "deliverable": {
                        "path": "docs/drill/final.md",
                        "sha256": _sha256(final),
                        "release_notes_sha256": _sha256(notes),
                    }
                },
            ),
            ("say", "T8 完成，第一轮发布就绪"),
        ],
        "阶段四：agent-a 完成 T8（第一轮发布）",
    )
    assert not _scene_denied(events)


def _assert_phase4(d, capsys) -> None:
    view = _view(d)
    assert all(r.badge == "verified" for r in view.rows), [(r.task_id, r.badge) for r in view.rows]
    assert view.summary.issues == 0
    # ≥3 distinct executors claimed tasks (drill rule: multi-agent).
    owners = {str(c.get("owner_ref", "")).split(":")[-1] for c in _env(d).claims.values()}
    assert {"agent-a", "agent-b", "agent-c"} <= owners
    assert "outline v1" in (d["ws"] / "docs" / "drill" / "final.md").read_text(encoding="utf-8")
    assert "变更发布" not in (d["ws"] / "docs" / "drill" / "release-notes.md").read_text(
        encoding="utf-8"
    )
    _print_board(d, "Phase 4: first release — all verified", capsys)


# ── phase 5: the late change ──────────────────────────────────────────


def _phase5(d) -> None:
    # operator reopens T1 (TaskUpdate status=pending → reopen_task), then
    # records the change request in task metadata.  The TaskUpdate input
    # schema has no `reason` field, so the change rationale travels in
    # metadata (see spec §13.7 known limitations).
    _, events = run_scene(
        d,
        "operator",
        [
            ("tool", "TaskUpdate", lambda: {"taskId": _tid(d, "T1"), "status": "pending"}),
            _act_meta(
                d,
                "T1",
                {
                    "change_request": "第二章由「Loop 中的状态与上下文」改写为「Loop 中的工具调用与权限」",
                    "requested_by": "operator",
                },
            ),
            ("say", "变更已下达：重开 T1"),
        ],
        "阶段五：迟到的变更 — operator 重开 T1",
    )
    assert not _scene_denied(events)
    # 落实变更：实际修改大纲文件。
    _write(d, "docs/drill/outline.md", _OUTLINE_V2)


def _assert_phase5(d, capsys) -> None:
    t1 = _node(d, "T1")
    assert t1.state == "pending"
    assert t1.owner is None, "reopen must clear the owner (commit 08a624ee contract)"
    assert "工具调用与权限" in str(t1.payload or {})
    # Downstream completed tasks keep base=completed, gain needs_recheck.
    for p in ("T2", "T3", "T4", "T5", "T6", "T7", "T8"):
        node = _node(d, p)
        assert node.state == "completed", f"{p} base status changed: {node.state}"
        assert (node.payload or {}).get("derived_status") == "needs_recheck", (
            f"{p} expected needs_recheck, got {(node.payload or {}).get('derived_status')!r}"
        )
    # Independent T0 is untouched.
    t0 = _node(d, "T0")
    assert t0.state == "completed"
    assert not (t0.payload or {}).get("derived_status")
    # ``evidence`` is a retired, schema-reserved compatibility slot.  The
    # current Plan Graph chain leaves it empty and never gates progress on it.
    assert not _env(d).evidence
    # The changed outline invalidates the old chapter/final; recovery must
    # rewrite them rather than merely clearing needs_recheck.
    assert "工具调用与权限" in (d["ws"] / "docs" / "drill" / "outline.md").read_text(
        encoding="utf-8"
    )
    assert "状态与上下文" in (d["ws"] / "docs" / "drill" / "chapter-2.md").read_text(
        encoding="utf-8"
    )
    assert "outline v1" in (d["ws"] / "docs" / "drill" / "final.md").read_text(encoding="utf-8")
    # Invalidation propagation is audited.
    assert any(e.get("type") == "invalidation_propagation" for e in _audit(d))
    _print_board(d, "Phase 5: T1 reopened — downstream needs_recheck, T0 intact", capsys)


# ── phase 6: recover the release ──────────────────────────────────────


def _phase6(d) -> None:
    # Probe: skipping un-revalidated upstream must be denied (topo gate).
    r = _revalidate(d, "T8")
    assert r.decision == "denied"
    assert "upstream not verified" in (r.reason or "")

    # Re-claim T1 (reopen cleared the owner) → start → complete against
    # outline v2, recording the new artifact revision in metadata.
    outline_v2 = d["ws"] / "docs" / "drill" / "outline.md"
    _, events = run_scene(
        d,
        "agent-a",
        [
            _act_claim(d, "T1", "agent-a"),
            _act_start(d, "T1"),
            _act_complete(
                d,
                "T1",
                metadata={
                    "deliverable": {
                        "path": "docs/drill/outline.md",
                        "sha256": _sha256(outline_v2),
                    }
                },
            ),
            ("say", "T1 重新完成"),
        ],
        "阶段六：重领 T1 并按 outline v2 重新完成",
    )
    assert not _scene_denied(events)

    # Recover every downstream task in topological order. Files that must
    # change are rewritten before revalidation; unchanged deliverables are
    # explicitly revalidated against the new upstream state.
    r = _revalidate(d, "T2", actor="agent-b")
    assert r.decision == "committed", f"revalidate T2: {r.reason}"

    chapter2 = _write(d, "docs/drill/chapter-2.md", _CHAPTER_2_V2)
    r = _revalidate(d, "T3", actor="agent-c")
    assert r.decision == "committed", f"revalidate T3: {r.reason}"
    _, events = run_scene(
        d,
        "agent-c",
        [
            _act_meta(
                d,
                "T3",
                {"deliverable": {"path": "docs/drill/chapter-2.md", "sha256": _sha256(chapter2)}},
            ),
            ("say", "T3 v2 交付物已更新"),
        ],
        "阶段六：重写第二章并更新交付物哈希",
    )
    assert not _scene_denied(events)

    run3 = _run_demo(d, "run3.txt")
    assert run3.returncode == 0
    r = _revalidate(d, "T4", actor="agent-c")
    assert r.decision == "committed", f"revalidate T4: {r.reason}"
    _, events = run_scene(
        d,
        "agent-c",
        [
            _act_meta(
                d,
                "T4",
                {
                    "deliverable": {
                        "path": "docs/drill/demo_loop.py",
                        "sha256": _sha256(d["ws"] / "docs" / "drill" / "demo_loop.py"),
                        "run3_sha256": _sha256(d["ws"] / "docs" / "drill" / "run3.txt"),
                    }
                },
            ),
            ("say", "T4 演示脚本已复跑"),
        ],
        "阶段六：复跑演示脚本并更新运行哈希",
    )
    assert not _scene_denied(events)

    cross_ref = _write(d, "docs/drill/cross-ref-report.md", _CROSS_REF_V2)
    r = _revalidate(d, "T5", actor="agent-b")
    assert r.decision == "committed", f"revalidate T5: {r.reason}"
    _, events = run_scene(
        d,
        "agent-b",
        [
            _act_meta(
                d,
                "T5",
                {
                    "deliverable": {
                        "path": "docs/drill/cross-ref-report.md",
                        "sha256": _sha256(cross_ref),
                    }
                },
            ),
            ("say", "T5 v2 校对报告已更新"),
        ],
        "阶段六：按新第二章重做全文交叉引用校对",
    )
    assert not _scene_denied(events)

    r = _revalidate(d, "T6", actor="agent-c")
    assert r.decision == "committed", f"revalidate T6: {r.reason}"

    review2 = _write(d, "docs/drill/review-v2.md", _REVIEW_V2)
    r = _revalidate(d, "T7")
    assert r.decision == "committed", f"revalidate T7: {r.reason}"
    _, events = run_scene(
        d,
        "agent-a",
        [
            _act_meta(
                d,
                "T7",
                {
                    "deliverable": {
                        "path": "docs/drill/review-v2.md",
                        "sha256": _sha256(review2),
                    }
                },
            ),
            ("say", "T7 v2 审校完成"),
        ],
        "阶段六：完成 v2 发布前审校",
    )
    assert not _scene_denied(events)

    final = _write(d, "docs/drill/final.md", _FINAL_V2)
    notes = _write(d, "docs/drill/release-notes.md", _RELEASE_NOTES_V2)
    r = _revalidate(d, "T8")
    assert r.decision == "committed", f"revalidate T8: {r.reason}"
    _, events = run_scene(
        d,
        "agent-a",
        [
            _act_meta(
                d,
                "T8",
                {
                    "deliverable": {
                        "path": "docs/drill/final.md",
                        "sha256": _sha256(final),
                        "release_notes_sha256": _sha256(notes),
                    }
                },
            ),
            ("say", "T8 v2 终稿与发布说明已更新"),
        ],
        "阶段六：汇总 v2 终稿并更新发布说明",
    )
    assert not _scene_denied(events)


def _assert_phase6(d, capsys) -> None:
    view = _view(d)
    assert all(r.badge == "verified" for r in view.rows), [(r.task_id, r.badge) for r in view.rows]
    assert view.summary.issues == 0

    # Cross-session restart recovery: a new process owns a fresh Repository,
    # Session, ToolContext and AgentLoop. It resolves the Board by workspace,
    # calls TaskList, and renders /lkb board without any old Context cache.
    before_restart_envelope = _env(d)
    before_restart = d["repo"].load_snapshot(d["board_id"])
    mp_ctx = _multiprocessing_context()
    result_queue = mp_ctx.Queue()
    restart_process = mp_ctx.Process(
        target=_restart_reader_process,
        args=(
            (
                str(d["home"]),
                str(d["ws"]),
                "drill-restart-session",
                d["board_id"],
                _plan_id(d),
            ),
            result_queue,
        ),
    )
    restart = _collect_process_results([restart_process], result_queue, 1)[0]
    assert "error" not in restart, restart
    assert restart["actions_remaining"] == 0
    assert not restart["awaiting_tool_result"]
    assert restart["resolved_board_id"] == d["board_id"]
    assert restart["plan_id"] == _plan_id(d)
    assert restart["store_revision"] == before_restart_envelope.store_revision + 1
    assert restart["plan_revision"] == before_restart.graphs[_plan_id(d)].revision + 1
    assert restart["session_binding"] == _plan_id(d)
    assert "drill-restart-session" in restart["plan_session_ids"]
    assert restart["claim_count"] == len(before_restart_envelope.claims)
    assert set(restart["states"]) == {_tid(d, p) for p, *_rest in _TASKS}
    assert set(restart["states"].values()) == {"completed"}
    assert not any(restart["derived"].values())
    assert len(restart["task_list"]) == 1
    restart_list = restart["task_list"][0]
    assert restart_list["lkbBoard"]["boardId"] == d["board_id"]
    assert restart_list["lkbBoard"]["planId"] == _plan_id(d)
    assert len(restart_list["tasks"]) == len(_TASKS)
    assert f"LKB BOARD: {d['ws'].name} /" in restart["board_text"]
    assert "Ready 0 | Running 0 | Blocked 0 | Recheck 0 | Issues 0" in restart["board_text"]

    # Full audit chain: every probe denial + invalidation + revalidates.
    for code in (
        "dependency_cycle",
        "already_claimed",
        "blocked",
        "owner_required",
    ):
        assert _denials(d, code), f"audit missing denial code {code}"
    assert any(e.get("type") == "invalidation_propagation" for e in _audit(d))
    revalidated = [
        t
        for t in d["transcript"]
        if t.get("kind") == "lkb-command"
        and t.get("op") == "revalidate"
        and t.get("decision") == "committed"
    ]
    assert len(revalidated) == 7, f"expected 7 revalidates (T2..T8), got {len(revalidated)}"
    denied_revalidates = [
        t
        for t in d["transcript"]
        if t.get("kind") == "lkb-command"
        and t.get("op") == "revalidate"
        and t.get("decision") == "denied"
    ]
    assert len(denied_revalidates) == 1

    # All real deliverables (incl. both failing and passing demo outputs).
    for rel in (
        "outline.md",
        "glossary.md",
        "chapter-1.md",
        "chapter-2.md",
        "chapter-3.md",
        "cross-ref-report.md",
        "review.md",
        "review-v2.md",
        "final.md",
        "release-notes.md",
        "demo_loop.py",
        "run1.txt",
        "run2.txt",
        "run3.txt",
    ):
        assert (d["ws"] / "docs" / "drill" / rel).is_file(), f"missing deliverable {rel}"

    chapter2_text = (d["ws"] / "docs" / "drill" / "chapter-2.md").read_text(encoding="utf-8")
    final_text = (d["ws"] / "docs" / "drill" / "final.md").read_text(encoding="utf-8")
    notes_text = (d["ws"] / "docs" / "drill" / "release-notes.md").read_text(encoding="utf-8")
    cross_ref_text = (d["ws"] / "docs" / "drill" / "cross-ref-report.md").read_text(
        encoding="utf-8"
    )
    assert "工具调用与权限" in chapter2_text
    assert "状态与上下文" not in chapter2_text.splitlines()[0]
    assert "终稿 v2" in final_text and "工具调用与权限" in final_text
    assert "发布说明 v2" in notes_text and "迟到变更" in notes_text
    assert "校对报告 v2" in cross_ref_text and "工具调用与权限" in cross_ref_text

    for prefix, rel in (
        ("T3", "chapter-2.md"),
        ("T5", "cross-ref-report.md"),
        ("T8", "final.md"),
    ):
        deliverable = (_node(d, prefix).payload or {})["metadata"]["deliverable"]
        assert deliverable["sha256"] == _sha256(d["ws"] / "docs" / "drill" / rel)
    t8_deliverable = (_node(d, "T8").payload or {})["metadata"]["deliverable"]
    assert t8_deliverable["release_notes_sha256"] == _sha256(
        d["ws"] / "docs" / "drill" / "release-notes.md"
    )

    assert not _env(d).evidence

    # Every tool-level protection probe surfaced its refusal to the loop.
    denied_tool_results = [
        r
        for s in d["transcript"]
        if s.get("kind") == "scene_end"
        for r in s["tool_results"]
        if r["is_error"]
    ]
    assert len(denied_tool_results) == 4, (
        f"expected exactly 4 recorded tool-level denials, got {len(denied_tool_results)}"
    )
    assert denied_revalidates[0]["command"] == f"revalidate {_tid(d, 'T8')}"

    final_board = _lkb_board_text(d)
    assert f"LKB BOARD: {d['ws'].name} /" in final_board
    assert "Ready 0 | Running 0 | Blocked 0 | Recheck 0 | Issues 0" in final_board
    assert "\x1b[" not in final_board
    assert all(len(line) <= 110 for line in final_board.splitlines())
    _print_board(d, "Phase 6: release recovered — all verified, issues 0", capsys)
    if capsys is not None:
        capsys.readouterr()
        print("\n=== Drill transcript (abbrev) ===")
        for entry in d["transcript"]:
            kind = entry.get("kind")
            if kind == "tool_call":
                print(f"[{entry['actor']}] {entry['tool']} {entry['input']}")
            elif kind == "lkb-command":
                print(
                    f"[{entry['actor']}] /lkb {entry['command']}"
                    f" -> {entry['decision']} {entry.get('reason') or ''}"
                )
            elif kind == "scene_end":
                errs = [r for r in entry["tool_results"] if r["is_error"]]
                if errs:
                    print(f"[{entry['actor']}] denials: {[e['output'][:80] for e in errs]}")


def test_agent_loop_drill(drill, capsys) -> None:
    """Run the complete six-phase drill once, asserting every checkpoint."""
    d = drill
    phases = (
        (_phase1, _assert_phase1),
        (_phase2, _assert_phase2),
        (_phase3, _assert_phase3),
        (_phase4, _assert_phase4),
        (_phase5, _assert_phase5),
        (_phase6, _assert_phase6),
    )
    for execute, verify in phases:
        execute(d)
        verify(d, capsys)
