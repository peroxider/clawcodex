# Trae IDE 对接指南（P66-E）

> 让 Trae CN 在对话框中直接调用 clawcodex 的 Orchestrator / SOP Compiler / Skills / 稳定性门禁能力。

## 架构

```
Trae CN (Windows 进程)
  └─ mcp.json 注册 → wsl.exe -d Ubuntu-24.04 -- bash -lc "python3 -m extensions.trae.mcp_bridge"
       └─ extensions/trae/mcp_bridge.py (WSL 内 stdio MCP server)
            ├─ clawcodex_orchestrator_run_issue  (fire-and-forget, 返回 run_id)
            ├─ clawcodex_sop_compile             (调 convert_sop_to_agent)
            ├─ clawcodex_skill_invoke            (SkillRegistryExt 解析 prompt)
            └─ clawcodex_stability_gate          (subprocess pytest)
```

**为什么走 wsl.exe**:Trae CN 是 Windows 原生进程,而 clawcodex 的依赖（pytest、extensions/sop_converter、extensions/skills_ext）安装在 WSL Ubuntu-24.04 中。MCP stdio 协议通过 stdin/stdout 通信,`wsl.exe` 的 stdin/stdout 会透明转发到 WSL 内进程,因此跨环境可行。

**路径自动转换**:Trae CN 传入的 `${workspaceFolder}` 是 Windows 路径（`C:\xxx`）。`BridgeConfig.from_env` 会自动调用 `_win_to_wsl` 转成 `/mnt/c/xxx`。如需禁用（纯 Linux 部署），设 `CLAWCODEX_AUTO_WIN_TO_WSL=0`。

## 接入步骤

### 1. 确认 WSL 发行版名称

```bash
wsl.exe -l -v
# 输出第一行非表头即发行版名,本机为 Ubuntu-24.04
```

### 2. 写入 Trae CN 的 mcp.json

文件位置:`%APPDATA%\Trae CN\User\mcp.json`（即 `C:\Users\<用户名>\AppData\Roaming\Trae CN\User\mcp.json`）。

```jsonc
{
  "mcpServers": {
    "clawcodex": {
      "command": "C:\\Windows\\System32\\wsl.exe",
      "args": [
        "-d", "Ubuntu-24.04",            // ← 替换为你的发行版名
        "--",
        "bash", "-lc",
        "cd /mnt/c/WorkSpace/clawcodex && CLAWCODEX_WORKSPACE=/mnt/c/WorkSpace/clawcodex CLAWCODEX_REPORTS_DIR=/mnt/c/WorkSpace/clawcodex/.reports/ python3 -m extensions.trae.mcp_bridge"
      ],
      "env": {
        "CLAWCODEX_AUTO_WIN_TO_WSL": "1"  // 自动 Windows→WSL 路径转换
      }
    }
  }
}
```

> **注意**:`cd /mnt/c/WorkSpace/clawcodex` 是 clawcodex 仓库在 WSL 中的路径,需按实际位置修改。`python3` 必须能找到 extensions.trae 模块(在仓库根目录运行即可,无需 pip install)。

### 3. 重启 Trae CN

Trae CN 在启动时加载 mcp.json。修改后需完全退出 Trae CN(托盘右键 Quit)再启动。

### 4. 验证接入

在 Trae CN 对话框中输入:

> 用 clawcodex 跑一次稳定性门禁

Trae AI 应自动调用 `clawcodex_stability_gate` 工具,返回形如 `exit=0 | 345 passed in 48.23s` 的摘要。

或在 Trae CN 的 MCP 面板（设置 → AI → MCP Servers）中确认 `clawcodex` 服务状态为 connected,工具列表显示 4 个 `clawcodex_*` 工具。

## 工具说明

| 工具 | 入参 | 返回 | 耗时 |
|------|------|------|------|
| `clawcodex_orchestrator_run_issue` | `issue_url` (必填), `workflow_path` | `queued run_id=<uuid>` | 即时(fire-and-forget) |
| `clawcodex_sop_compile` | `sdk_spec` (必填), `requirements`, `agent_name` | `compiled agent=... skills=N persist=...` | 几秒 |
| `clawcodex_skill_invoke` | `skill_name` (必填), `params` | skill prompt 文本 | 即时 |
| `clawcodex_stability_gate` | (无) | `exit=0 \| N passed in Xs` | 30-60s |

**长任务查询**:`clawcodex_orchestrator_run_issue` 是 fire-and-forget,返回 run_id 后立即响应。实际进度写入 `<reports_dir>/<run_id>.ndjson`,可在 Trae 中再次询问 "查看 run_id xxx 的进度" 触发文件轮询。

## 故障排查

| 症状 | 原因 | 解决 |
|------|------|------|
| Trae MCP 面板显示 clawcodex failed | wsl.exe 发行版名错误 | `wsl.exe -l -v` 查实际名,改 mcp.json 的 `-d` 参数 |
| 工具调用报 `mcp SDK not installed` | WSL 内未装 mcp | `pip install mcp` |
| stability_gate 报 `pytest not found` | WSL 内未装 pytest | `pip install pytest` |
| 工具调用报 `ModuleNotFoundError: extensions.trae` | cd 路径不对 | 确认 mcp.json 中 `cd` 到 clawcodex 仓库根 |
| Trae 对话框超时 | stability_gate 跑 >120s | 改 mcp.json args 中 `CLAWCODEX_REPORTS_DIR` 不影响;调小测试集或增大 `stability_gate_timeout_s` |

## 回滚

删除 mcp.json 中的 `clawcodex` 节,重启 Trae CN 即可。`extensions/trae/` 全部在 Layer 2,不影响 `src/` 与 `clawcodex_ext/`。

## 验收对照（§1.9.5）

- [x] `python -m extensions.trae.mcp_bridge` 独立启动,响应 `tools/list` 返回 4 个工具
- [x] 单元测试:`tests/trae/test_mcp_bridge.py` 31 passed + 2 skipped
- [x] E2E:Trae CN 完整链路(wsl.exe → bash -lc → python -m)tools/list 返回 4 工具;`clawcodex_stability_gate` 实跑 345 passed
- [x] Windows→WSL 路径自动转换:`_win_to_wsl` + `BridgeConfig.from_env` 验证
- [ ] `mcp inspector` schema 校验 — 待人工执行（需 `npx @modelcontextprotocol/inspector`）
