"""F-66 P66-F — Trae Agent CLI 包装 (ACP 适配模式).

把字节开源的 ``trae-agent`` (``trae-cli``) 包装为**伪 ACP server**，
让 clawcodex 内部按 P66-A 设计的统一 :class:`ACPTransport` /
:class:`ACPServer` 接口即可调用 Trae Agent 能力 (代码编辑、命令执行、
Trajectory 记录)，无需为 Trae 单独写一套协议。

设计动机:
  ``trae-agent`` 截至 2026-07 仍是纯 CLI 工具 (无 stdio JSON-RPC 服务，
  无 ACP 实现，见 trae-agent #344)。但其 ``trae-cli run`` 子命令的
  输入/输出/中间轨迹已经接近 ACP 协议的事件流 — 因此用一个薄适配层
  把 CLI 调用的进程 + trajectory JSONL 文件投影为 ACP 消息流。

ACP 消息 → trae-cli 调用映射:

  | ACP 消息           | trae-cli 子命令                              | 异步语义          |
  |-------------------|---------------------------------------------|------------------|
  | session/create    | (无 CLI 调用，只生成 sid + trajectory 路径)  | 同步返回 sid     |
  | session/resume    | trae-cli interactive --resume-trajectory    | 后台进程          |
  | message/send (首) | trae-cli run "<task>"                       | 后台进程,tail     |
  | message/stream    | (无 CLI 调用，只 tail jsonl)                | 异步迭代器        |
  | session/end       | subprocess.terminate()                      | 同步清理          |

落点: ``extensions/trae/acp_cli_adapter.py`` — Layer 2 解耦，通过
``extensions/capabilities/acp_protocol`` 的 Protocol 接入。

风险缓解 (文档 §1.10.7):
  - trae-agent 接口变化 → 集中改 :meth:`_build_run_cmd` 一处
  - Trajectory JSONL 字段变更 → :meth:`_trajectory_to_acp` 容错降级
  - 字节后续实现原生 ACP → 适配器薄薄一层可平滑替换 backend
  - Windows 下 subprocess → 文档标注 experimental，Mac/Linux 优先
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

from extensions.capabilities.acp_protocol import (
    ACPMessage,
    ACPMessageType,
    ACPSession,
)

logger = logging.getLogger(__name__)

__all__ = [
    "TraeCliConfig",
    "TraeCliACPAdapter",
    "TrajectoryParseError",
]

# trajectory 文件等待出现的最大轮询次数 (50 × 0.1s = 5s)
_TRAJ_WAIT_ROUNDS = 50
_TRAJ_POLL_INTERVAL_S = 0.1


class TrajectoryParseError(Exception):
    """Raised when a trajectory JSONL line cannot be parsed (non-fatal by default)."""


@dataclass
class TraeCliConfig:
    """trae-cli 启动配置 (可从 trae_config.yaml 反序列化得到)。

    锁版本策略: ``trae_cli_path`` 默认 ``trae-cli`` (PATH 查找)；若接口
    变化集中改 :meth:`TraeCliACPAdapter._build_run_cmd` 一处即可。
    """

    trae_cli_path: str = "trae-cli"
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-6"
    api_key_env: str = "ANTHROPIC_API_KEY"
    mcp_servers: list[dict[str, Any]] = field(default_factory=list)
    extra_flags: list[str] = field(default_factory=list)


class TraeCliACPAdapter:
    """把 trae-cli 包装为伪 ACP server。

    实现了 :class:`ACPServer` Protocol 的关键生命周期方法
    (create/resume/process/end)，但**不**实现 :class:`ACPTransport`
    (它是 server 角色，不是传输角色)。

    内部映射:
      session/create  → 生成 session_id + trajectory 文件路径 (无 CLI 调用)
      message/stream  → tail <jsonl> 逐行解析为 ACP 消息
      session/end     → subprocess.terminate() + 清理 trajectory 文件
      session/resume  → trae-cli interactive --resume-trajectory <jsonl>

    进程清理保证: :meth:`end_session` 先 terminate 再 kill，避免残留
    (文档 §1.10.6 验收标准)。
    """

    def __init__(
        self,
        config: TraeCliConfig,
        workspace: str,
        *,
        process_factory: Any | None = None,
    ) -> None:
        """
        Args:
            config: trae-cli 启动配置。
            workspace: 工作目录 (trae-cli --working-dir)。
            process_factory: 可选的 subprocess.Popen 替代 (单测注入 mock)。
                生产路径为 ``None``，使用真实 ``subprocess.Popen``。
        """
        self._cfg = config
        self._workspace = workspace
        self._procs: dict[str, subprocess.Popen] = {}
        self._trajectories: dict[str, Path] = {}
        self._sessions: dict[str, ACPSession] = {}
        # 单测注入: 替代 subprocess.Popen 的可调用对象
        self._process_factory = process_factory or subprocess.Popen

    # ===== ACPServer 接口 =====

    async def create_session(self, workspace_path: str) -> ACPSession:
        """对应 ACP session/create — 生成 sid + trajectory 路径，无 CLI 调用。

        与文档差异: 返回 :class:`ACPSession` (而非裸 sid) 以对齐
        :class:`ACPServer` Protocol 签名。sid 仍可通过 ``session.id`` 取得。
        """
        sid = str(uuid.uuid4())
        traj_dir = Path(workspace_path) / ".trae" / "trajectories"
        traj_dir.mkdir(parents=True, exist_ok=True)
        traj = traj_dir / f"{sid}.jsonl"
        self._trajectories[sid] = traj
        session = ACPSession(
            id=sid,
            workspace_path=workspace_path,
            metadata={"trajectory": str(traj)},
        )
        self._sessions[sid] = session
        return session

    async def resume_session(self, session_id: str) -> ACPSession | None:
        """对应 ACP session/resume — 用 interactive 模式续接 saved trajectory。

        若 trajectory 文件不存在或 session 未知，返回 ``None``。
        """
        traj = self._trajectories.get(session_id)
        session = self._sessions.get(session_id)
        if traj is None or session is None:
            return None
        if not traj.exists():
            return None
        cmd = [
            self._cfg.trae_cli_path,
            "interactive",
            "--resume-trajectory",
            str(traj),
            "--working-dir",
            self._workspace,
            *self._cfg.extra_flags,
        ]
        await self._spawn(session_id, cmd, env=self._env())
        return session

    async def process_message(self, msg: ACPMessage) -> AsyncIterator[ACPMessage]:
        """对应 ACP message/stream — 启动 trae-cli run，逐行 tail trajectory。

        首次对某 session 调用时启动 ``trae-cli run`` 子进程；后续调用
        (同 session) 复用已启动的进程并继续 tail。

        ``msg.type`` 应为 :attr:`ACPMessageType.MESSAGE_SEND`；
        ``msg.content`` 作为 task 文本传入 ``trae-cli run "<task>"``。
        """
        sid = msg.session_id
        if not sid:
            return
            yield  # noqa: E701 — make this an async generator for type checker
        task = msg.content if isinstance(msg.content, str) else json.dumps(msg.content or "")
        if sid not in self._procs:
            cmd = self._build_run_cmd(sid, task)
            await self._spawn(sid, cmd, env=self._env())
        async for evt in self._tail_trajectory(sid):
            yield self._trajectory_to_acp(sid, evt)

    async def end_session(self, session_id: str) -> None:
        """对应 ACP session/end — terminate 进程，清理 trajectory 文件。

        先 ``terminate()`` 等 5s，超时再 ``kill()``，保证无残留进程。
        """
        proc = self._procs.pop(session_id, None)
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                logger.warning("trae-cli pid=%s killed after terminate timeout", proc.pid)
        # 清理 trajectory 文件 (可选 — 失败不阻断)
        traj = self._trajectories.pop(session_id, None)
        if traj and traj.exists():
            try:
                traj.unlink()
            except OSError as exc:
                logger.warning("failed to remove trajectory %s: %s", traj, exc)
        self._sessions.pop(session_id, None)

    async def invoke_skill(self, skill_name: str, params: dict[str, Any]) -> dict[str, Any]:
        """Stub — P66-D skill 桥接的占位，由上层 ACPServer 装配注入实现。"""
        return {"error": "skill bridge not wired in P66-F adapter", "skill": skill_name}

    async def handle_session(self, transport: Any) -> None:
        """Stub — transport-driven 主循环由 P66-A 框架层提供，P66-F 仅做 backend。"""
        raise NotImplementedError(
            "TraeCliACPAdapter is a backend; transport loop is provided by P66-A framework."
        )

    # ===== 内部实现 =====

    def _build_run_cmd(self, sid: str, task: str) -> list[str]:
        """构造 ``trae-cli run`` 命令行 (接口变化集中改这一处)。

        ``task`` 作为位置参数；trajectory/provider/model 作为 flag。
        """
        traj = self._trajectories[sid]
        return [
            self._cfg.trae_cli_path,
            "run",
            task,
            "--working-dir",
            self._workspace,
            "--trajectory-file",
            str(traj),
            "--provider",
            self._cfg.provider,
            "--model",
            self._cfg.model,
            *self._cfg.extra_flags,
        ]

    async def _spawn(self, sid: str, cmd: list[str], env: dict[str, str]) -> bool:
        """启动 trae-cli 子进程 (单测可通过 process_factory 注入 mock)。"""
        self._procs[sid] = self._process_factory(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        logger.info("trae-cli spawned: sid=%s pid=%s cmd=%s", sid, self._procs[sid].pid, cmd)
        return True

    async def _tail_trajectory(self, sid: str) -> AsyncIterator[dict[str, Any]]:
        """tail -F trajectory jsonl，逐行 yield dict。

        等 trajectory 文件出现 (最多 5s)，然后循环 readline 直到进程结束。
        JSON 解析失败的行降级跳过 (文档 §1.10.7 字段变更风险缓解)。
        """
        traj = self._trajectories[sid]
        proc = self._procs[sid]
        # 等待 trajectory 文件出现
        for _ in range(_TRAJ_WAIT_ROUNDS):
            if traj.exists():
                break
            if proc.poll() is not None:
                # 进程已退出且文件从未创建 — 放弃
                return
            await asyncio.sleep(_TRAJ_POLL_INTERVAL_S)
        if not traj.exists():
            logger.warning("trajectory file never appeared: %s", traj)
            return
        with traj.open("r", encoding="utf-8") as f:
            while True:
                line = f.readline()
                if not line:
                    if proc.poll() is not None:
                        # 进程已退出且无更多数据
                        return
                    await asyncio.sleep(_TRAJ_POLL_INTERVAL_S)
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    # 容错: 跳过坏行而非抛错 (文档 §1.10.7)
                    logger.debug("skip unparseable trajectory line: %r", line[:200])
                    continue

    def _trajectory_to_acp(self, sid: str, evt: dict[str, Any]) -> ACPMessage:
        """trajectory 事件 → ACP 消息映射 (容错降级)。

        若事件包含 ``tool_name`` → :attr:`ACPMessageType.TOOL_CALL`；
        否则 → :attr:`ACPMessageType.MESSAGE_STREAM`。
        字段缺失时降级为通用消息，不抛 :class:`KeyError`。
        """
        tool = evt.get("tool_name")
        content = evt.get("content", "")
        msg_id = evt.get("id") or str(uuid.uuid4())
        if tool:
            return ACPMessage(
                type=ACPMessageType.TOOL_CALL,
                id=msg_id,
                session_id=sid,
                tool_calls=[{"name": tool, "arguments": evt.get("tool_input", {})}],
                content=content,
                metadata={
                    "step": evt.get("step", "unknown"),
                    "model": evt.get("model"),
                },
            )
        return ACPMessage(
            type=ACPMessageType.MESSAGE_STREAM,
            id=msg_id,
            session_id=sid,
            content=content,
            metadata={
                "step": evt.get("step", "unknown"),
                "model": evt.get("model"),
            },
        )

    def _env(self) -> dict[str, str]:
        """构造子进程环境变量 (含 provider/model/mcp_servers)。"""
        env = dict(os.environ)
        env["TRAE_PROVIDER"] = self._cfg.provider
        env["TRAE_MODEL"] = self._cfg.model
        if self._cfg.mcp_servers:
            env["TRAE_MCP_SERVERS"] = json.dumps(self._cfg.mcp_servers)
        # P66-E 互操作: 若 mcp_servers 含 clawcodex bridge，env 已自带
        return env
