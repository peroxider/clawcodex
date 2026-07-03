"""F-66 P66-E — Trae IDE MCP 反向桥.

让 Trae IDE 用户在对话窗口内直接调用 clawcodex 的下游能力
(Orchestrator、SOP Compiler、Skills 桥接、稳定性门禁)，无需离开 IDE。
Trae IDE 短期内不会实现 ACP（见 trae-agent #344），但已原生支持 MCP
(``byted-solo.builtin-mcp`` 扩展)，故采用 MCP 反向路线 — 由 clawcodex
暴露 stdio MCP server，让 Trae 主动连接。

落点: ``extensions/trae/mcp_bridge.py`` — Layer 2 解耦，不污染
``src/`` 或 ``clawcodex_ext/``。

``mcp`` 是可选依赖 (``pip install mcp``)。未安装时 :class:`TraeMcpBridge`
仍可实例化，工具规格与分发逻辑可独立单元测试；仅 :meth:`run_stdio` 在
调用时才要求 ``mcp`` 已安装。

Trae IDE 侧接入 (Trae CN 通过 wsl.exe 调用，Trae AI 可通过 byted-solo.builtin-mcp 直连):

    配置示例 (``%APPDATA%\\Trae CN\\User\\mcp.json``)::

    {
      "mcpServers": {
        "clawcodex": {
          "command": "C:\\\\Windows\\\\System32\\\\wsl.exe",
          "args": [
            "-d", "Ubuntu-24.04", "--",
            "bash", "-lc",
            "cd /path/to/clawcodex && python3 -m extensions.trae.mcp_bridge"
          ],
          "env": {"CLAWCODEX_AUTO_WIN_TO_WSL": "1"}
        }
      }
    }

    纯 Linux 部署 (无 Windows 路径转换需求)::

    {
      "name": "clawcodex",
      "command": "python",
      "args": ["-m", "extensions.trae.mcp_bridge"],
      "env": {
        "CLAWCODEX_WORKSPACE": "${workspaceFolder}",
        "CLAWCODEX_REPORTS_DIR": "${workspaceFolder}/.reports/"
      }
    }
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from extensions.capabilities.acp_protocol import ACPToolSpec

logger = logging.getLogger(__name__)

__all__ = [
    "TraeMcpBridge",
    "BridgeConfig",
    "MCP_UNAVAILABLE",
    "mcp_available",
    "build_tool_specs",
    "_win_to_wsl",
]

# 模块级常量 — 单测可不安装 mcp 即可断言降级路径
MCP_UNAVAILABLE = "mcp SDK not installed (pip install mcp). TraeMcpBridge.run_stdio() unavailable."


def mcp_available() -> bool:
    """Return True if the optional ``mcp`` SDK is importable."""
    try:
        import mcp  # noqa: F401
    except ImportError:
        return False
    return True


@dataclass
class BridgeConfig:
    """MCP 桥运行配置（可从环境变量构造）。"""

    workspace: str = ""
    reports_dir: str = ""
    stability_gate_args: list[str] = field(
        default_factory=lambda: [
            sys.executable,
            "-m",
            "pytest",
            "tests/stability_gate/",
            "-q",
            "--tb=line",
            "-x",
        ]
    )
    stability_gate_cwd: str = ""
    stability_gate_timeout_s: float = 120.0
    # fire-and-forget 进度轮询间隔（文档 §1.9.6 风险缓解）
    progress_poll_interval_s: float = 0.5
    # 是否把 Windows 风格路径自动转 WSL 风格（Trae CN 是 Windows 进程，
    # 传入的 ${workspaceFolder} 是 C:\xxx 形式；bridge 在 WSL 跑需 /mnt/c/xxx）
    auto_win_to_wsl: bool = True

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "BridgeConfig":
        env = env if env is not None else dict(os.environ)
        workspace = env.get("CLAWCODEX_WORKSPACE", "")
        reports_dir = env.get("CLAWCODEX_REPORTS_DIR", "")
        # Trae CN 经 wsl.exe 启动时，env 里的 Windows 路径需转 WSL 路径
        if env.get("CLAWCODEX_AUTO_WIN_TO_WSL", "1") not in ("0", "false", "False"):
            workspace = _win_to_wsl(workspace) if workspace else workspace
            reports_dir = _win_to_wsl(reports_dir) if reports_dir else reports_dir
        return cls(
            workspace=workspace,
            reports_dir=reports_dir,
            stability_gate_cwd=workspace,
        )


def _win_to_wsl(path: str) -> str:
    """Convert a Windows path ``C:\\foo\\bar`` to WSL ``/mnt/c/foo/bar``.

    非 Windows 路径（已 / 开头、空串、UNC 之外的形态）原样返回。
    反斜杠统一转正斜杠。-drive 形如 ``D:\\proj`` → ``/mnt/d/proj``。
    """
    if not path:
        return path
    p = path.strip().strip('"').strip("'")
    # 已经是 WSL/POSIX 路径
    if p.startswith("/") or p.startswith("\\\\wsl"):
        return p
    # 形如 C:\xxx 或 C:/xxx
    if len(p) >= 2 and p[1] == ":" and p[0].isalpha():
        drive = p[0].lower()
        rest = p[2:].replace("\\", "/")
        if rest.startswith("/"):
            rest = rest[1:]
        return f"/mnt/{drive}/{rest}"
    return p


# ---------------------------------------------------------------------------
# 工具规格 — 与 mcp 安装与否无关，单测可直接断言
# ---------------------------------------------------------------------------

TOOL_ORCH_RUN = "clawcodex_orchestrator_run_issue"
TOOL_SOP_COMPILE = "clawcodex_sop_compile"
TOOL_SKILL_INVOKE = "clawcodex_skill_invoke"
TOOL_STABILITY_GATE = "clawcodex_stability_gate"


def build_tool_specs() -> list[ACPToolSpec]:
    """Return the 4 MCP tool specifications exposed to Trae.

    公开为独立函数以便单测在不实例化 bridge 的情况下断言 schema。
    """
    return [
        ACPToolSpec(
            name=TOOL_ORCH_RUN,
            description=(
                "从当前 workspace 派生 git workspace，运行 clawcodex agent "
                "处理 issue，自动推 PR。等价于 "
                "`clawcodex-dev orchestrator server start` 的单次触发。"
                "返回 run_id，实际进度通过 .reports/{run_id}.ndjson 轮询。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "issue_url": {
                        "type": "string",
                        "description": "GitHub/Gitee/GitCode/Linear issue URL",
                    },
                    "workflow_path": {
                        "type": "string",
                        "description": "可选 SOP workflow.md 路径",
                    },
                },
                "required": ["issue_url"],
            },
        ),
        ACPToolSpec(
            name=TOOL_SOP_COMPILE,
            description=(
                "将 SDK 规格编译为可复用 Agent（调用 sop_converter."
                "convert_sop_to_agent），返回 agent 定义与 skill 列表。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "sdk_spec": {
                        "type": "string",
                        "description": "OpenAPI dict JSON / URL / method list",
                    },
                    "requirements": {
                        "type": "string",
                        "description": "业务需求描述，用于 skill 分组",
                    },
                    "agent_name": {"type": "string"},
                },
                "required": ["sdk_spec"],
            },
        ),
        ACPToolSpec(
            name=TOOL_SKILL_INVOKE,
            description=(
                "调用已注册的 Skill（透传到 F-66 P66-D skill 桥接层，"
                "经 SkillRegistryExt 解析 skill markdown prompt）。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "skill_name": {"type": "string"},
                    "params": {"type": "object", "default": {}},
                },
                "required": ["skill_name"],
            },
        ),
        ACPToolSpec(
            name=TOOL_STABILITY_GATE,
            description=(
                "在当前 workspace 跑一次稳定性门禁，返回 Stage 1-9 "
                "通过/失败摘要。等价于 `pytest tests/stability_gate/ -q`。"
            ),
            input_schema={"type": "object", "properties": {}},
        ),
    ]


# ---------------------------------------------------------------------------
# Bridge 主体
# ---------------------------------------------------------------------------


class TraeMcpBridge:
    """MCP server bridge — 让 Trae IDE 通过 MCP 协议调用 clawcodex 能力。

    设计要点:
      - ``mcp`` 可选: 未安装时仍可构造、列出工具、调用分发逻辑（单测友好）；
        仅 :meth:`run_stdio` 在调用时才要求 ``mcp`` 已安装。
      - Orchestrator 集成 fire-and-forget: ``enqueue_issue`` 返回 run_id
        立即返回，长任务不阻塞 MCP 响应（文档 §1.9.6 风险缓解）。
      - SOP 编译走真实 :func:`convert_sop_to_agent` 接口（适配现有代码，
        而非文档规划稿中尚不存在的 ``SOPCompiler.compile``）。
      - Skill 调用走 :class:`SkillRegistryExt` 解析已注册 skill 的 prompt。
      - 稳定性门禁通过 subprocess 跑 pytest，捕获 stdout/stderr 摘要。
    """

    def __init__(
        self,
        config: BridgeConfig | None = None,
        *,
        orchestrator_enqueue: Callable[[str, str | None], str] | None = None,
        sop_compiler: Callable[..., dict[str, Any]] | None = None,
        skill_invoker: Callable[[str, dict[str, Any]], str] | None = None,
        stability_runner: Callable[[], str] | None = None,
    ) -> None:
        self._config = config or BridgeConfig.from_env()
        # 可注入的依赖 — 单测可注入 mock；生产路径懒加载真实实现
        self._orchestrator_enqueue = orchestrator_enqueue
        self._sop_compiler = sop_compiler
        self._skill_invoker = skill_invoker
        self._stability_runner = stability_runner
        # run_id → ndjson 进度文件路径（fire-and-forget 进度查询用）
        self._runs: dict[str, Path] = {}
        # 懒构造 mcp Server（仅在 run_stdio 时）
        self._server: Any | None = None

    # ---- 工具列表 --------------------------------------------------------

    def list_tools(self) -> list[ACPToolSpec]:
        """Return tool specs (mcp-agnostic, used by both MCP layer & tests)."""
        return build_tool_specs()

    # ---- 工具分发 --------------------------------------------------------

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Dispatch a tool call by name. Returns text content.

        4 个分支:
          * ``clawcodex_orchestrator_run_issue`` — fire-and-forget 入队
          * ``clawcodex_sop_compile`` — 真实 SOP 编译
          * ``clawcodex_skill_invoke`` — Skill 桥接
          * ``clawcodex_stability_gate`` — pytest 子进程
        """
        if name == TOOL_ORCH_RUN:
            return await self._handle_orch_run(arguments)
        if name == TOOL_SOP_COMPILE:
            return await self._handle_sop_compile(arguments)
        if name == TOOL_SKILL_INVOKE:
            return await self._handle_skill_invoke(arguments)
        if name == TOOL_STABILITY_GATE:
            return await self._handle_stability_gate(arguments)
        raise ValueError(f"unknown tool: {name}")

    # ---- 各分支实现 ------------------------------------------------------

    async def _handle_orch_run(self, arguments: dict[str, Any]) -> str:
        issue_url = arguments.get("issue_url")
        if not issue_url:
            return "error: issue_url is required"
        workflow_path = arguments.get("workflow_path")
        enqueue = self._orchestrator_enqueue or self._default_orchestrator_enqueue
        # fire-and-forget: enqueue 立即返回 run_id，长任务在后台跑
        try:
            run_id = enqueue(issue_url, workflow_path)
        except Exception as exc:  # noqa: BLE001 — boundary, surface to Trae
            logger.exception("orchestrator enqueue failed for %s", issue_url)
            return f"error: enqueue failed: {exc}"
        # 记录进度文件路径供后续轮询（Trae 可另开 tools/call 查询）
        reports = Path(self._config.reports_dir or ".reports")
        self._runs[run_id] = reports / f"{run_id}.ndjson"
        return f"queued run_id={run_id} (progress: {self._runs[run_id]})"

    async def _handle_sop_compile(self, arguments: dict[str, Any]) -> str:
        sdk_spec = arguments.get("sdk_spec")
        if not sdk_spec:
            return "error: sdk_spec is required"
        compile_fn = self._sop_compiler or self._default_sop_compiler
        try:
            result = compile_fn(
                sdk_spec=sdk_spec,
                requirements=arguments.get("requirements", ""),
                agent_name=arguments.get("agent_name", ""),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("sop compile failed")
            return f"error: compile failed: {exc}"
        if isinstance(result, dict) and result.get("status") == "error":
            return f"error: {result.get('error', 'unknown')}"
        # 紧凑摘要（避免 Trae 对话框被巨量 JSON 撑爆）
        skill_count = len(result.get("skills", [])) if isinstance(result, dict) else 0
        agent_name = result.get("agent_type", "") if isinstance(result, dict) else ""
        persist = result.get("persist_status", "") if isinstance(result, dict) else ""
        return f"compiled agent={agent_name} skills={skill_count} persist={persist}"

    async def _handle_skill_invoke(self, arguments: dict[str, Any]) -> str:
        skill_name = arguments.get("skill_name")
        if not skill_name:
            return "error: skill_name is required"
        params = arguments.get("params", {}) or {}
        invoke = self._skill_invoker or self._default_skill_invoker
        try:
            return invoke(skill_name, params)
        except Exception as exc:  # noqa: BLE001
            logger.exception("skill invoke failed: %s", skill_name)
            return f"error: skill '{skill_name}' failed: {exc}"

    async def _handle_stability_gate(self, _arguments: dict[str, Any]) -> str:
        runner = self._stability_runner or self._default_stability_runner
        try:
            return runner()
        except Exception as exc:  # noqa: BLE001
            logger.exception("stability gate failed")
            return f"error: stability gate failed: {exc}"

    # ---- 默认生产实现（懒加载真实模块）----------------------------------

    def _default_orchestrator_enqueue(self, issue_url: str, workflow_path: str | None) -> str:
        """Default orchestrator enqueue — generates run_id and records intent.

        真正的 Orchestrator 构造需要 WorkflowConfig/Tracker/Workspace 等
        重型依赖，不适合在 MCP server 进程内长驻。生产部署应通过
        ``orchestrator_enqueue=`` 注入一个把任务投递到 orchestrator daemon
        的薄薄一层（如写 issue 到 LocalTracker 的 inbox 目录，或调 daemon
        的 control socket）。此处默认实现仅生成 run_id 并记录到 reports
        目录，供 Trae 端后续轮询 — daemon 侧需另行监听 inbox。

        回滚安全: 不导入 orchestrator 重型模块，避免 MCP 进程膨胀。
        """
        run_id = str(uuid.uuid4())
        reports = Path(self._config.reports_dir or ".reports")
        reports.mkdir(parents=True, exist_ok=True)
        ndjson = reports / f"{run_id}.ndjson"
        record = {
            "run_id": run_id,
            "issue_url": issue_url,
            "workflow_path": workflow_path,
            "event": "queued",
        }
        ndjson.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
        logger.info(
            "orchestrator enqueue (default): run_id=%s issue=%s → %s",
            run_id,
            issue_url,
            ndjson,
        )
        return run_id

    def _default_sop_compiler(self, **kwargs: Any) -> dict[str, Any]:
        """Default SOP compiler — calls the real ``convert_sop_to_agent``."""
        from extensions.sop_converter.convert_sop_skill import convert_sop_to_agent

        return convert_sop_to_agent(
            sdk_spec=kwargs["sdk_spec"],
            requirements=kwargs.get("requirements", ""),
            agent_name=kwargs.get("agent_name", ""),
        )

    def _default_skill_invoker(self, skill_name: str, params: dict[str, Any]) -> str:
        """Default skill invoker — resolves the skill prompt via SkillRegistryExt.

        返回 skill 的 prompt 文本（若 skill 不存在则报错）。真正的"执行"
        需要把 prompt 喂给 agent loop，这里仅做桥接到 prompt 层 —
        与 P66-D 设计一致（MCP 工具暴露 skill 入口，执行层由调用方决定）。
        """
        from extensions.skills_ext.registry_ext import SkillRegistryExt

        registry = SkillRegistryExt(project_root=self._config.workspace or ".")
        skills = registry.get_all_skills()
        for skill in skills:
            if getattr(skill, "name", None) == skill_name:
                prompt = getattr(skill, "prompt", "") or ""
                # params 作为 metadata 附加（不替换 prompt 模板）
                if params:
                    prompt = f"{prompt}\n\n--- params ---\n{json.dumps(params, ensure_ascii=False)}"
                return prompt or f"(skill '{skill_name}' has empty prompt)"
        return f"error: skill '{skill_name}' not found in registry"

    def _default_stability_runner(self) -> str:
        """Default stability gate runner — subprocess pytest, parse summary."""
        args = list(self._config.stability_gate_args)
        cwd = self._config.stability_gate_cwd or None
        try:
            proc = subprocess.run(
                args,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=self._config.stability_gate_timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return f"error: stability gate timed out after {self._config.stability_gate_timeout_s}s"
        except FileNotFoundError as exc:
            return f"error: pytest not found: {exc}"
        # pytest -q 末尾形如 "5 passed in 1.20s" 或 "2 failed, 3 passed in 1.20s"
        out = (proc.stdout or "") + (proc.stderr or "")
        last = out.strip().splitlines()[-1] if out.strip() else "(no output)"
        return f"exit={proc.returncode} | {last}"

    # ---- MCP server 装配（仅 mcp 已安装时）-------------------------------

    def _build_mcp_server(self) -> Any:
        """Construct the ``mcp.server.Server`` and register handlers.

        延迟到 :meth:`run_stdio` 调用时才执行，避免 ``mcp`` 未安装时
        模块导入失败。单测通过 :meth:`list_tools` / :meth:`call_tool`
        绕过此路径。
        """
        if not mcp_available():
            raise ImportError(MCP_UNAVAILABLE)
        from mcp.server import Server
        from mcp.types import TextContent, Tool

        server: Server = Server("clawcodex-trae-bridge")

        @server.list_tools()
        async def _list_tools() -> list[Tool]:
            return [
                Tool(
                    name=spec.name,
                    description=spec.description,
                    inputSchema=spec.input_schema,
                )
                for spec in build_tool_specs()
            ]

        @server.call_tool()
        async def _call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
            text = await self.call_tool(name, arguments or {})
            return [TextContent(type="text", text=text)]

        return server

    async def run_stdio(self) -> None:
        """通过 stdio 暴露 MCP server，供 Trae IDE builtin-mcp 调用。

        入口点: ``python -m extensions.trae.mcp_bridge``。
        要求 ``mcp`` 已安装；未安装时抛 :class:`ImportError` 并提示安装方式。
        """
        if self._server is None:
            self._server = self._build_mcp_server()
        from mcp.server.stdio import stdio_server

        async with stdio_server() as (read_stream, write_stream):
            await self._server.run(
                read_stream,
                write_stream,
                self._server.create_initialization_options(),
            )


# ---------------------------------------------------------------------------
# 模块入口 — `python -m extensions.trae.mcp_bridge`
# ---------------------------------------------------------------------------


def _main() -> int:
    logging.basicConfig(
        level=os.environ.get("CLAWCODEX_BRIDGE_LOG", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    if not mcp_available():
        print(MCP_UNAVAILABLE, file=sys.stderr)
        return 2
    config = BridgeConfig.from_env()
    bridge = TraeMcpBridge(config=config)
    try:
        asyncio.run(bridge.run_stdio())
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
