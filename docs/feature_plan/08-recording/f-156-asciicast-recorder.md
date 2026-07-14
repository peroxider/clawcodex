# F-REC: Asciicast v2 录制器

> 状态: ✅ 已完成
> 章节: docs/feature_plan/08-recording/f-156-asciicast-recorder.md
> 最后更新: 2026-07-14
> 设计来源: 2026-07 用户提出「agent 自动录制 ClawCodex 功能演示」需求

## §1 设计规划

### 1.1 背景

ClawCodex 的「功能展示」目前依赖人工截图/录屏，无法由 agent 在 orchestrator
跑完一批 issue 后自动产出**可回放、可嵌入 README 的演示**。

调研结论：

| 候选方案 | 评估 | 结论 |
|---------|------|------|
| OpenMontage | 合成模式要求预先写好命令序列；不能真实驱动 REPL/TUI | ❌ 不适用 |
| asciinema (CLI) | 录制真实 shell；需要交互终端驱动 | ⚠️ 仅适合手动 |
| asciicast v2 + 自定义 .cast 写入 | NDJSON 文件，可在 asciinema player 浏览器播放；体积 ≈ 视频 8% | ✅ 选定 |

**关键决策**：使用 asciicast v2 作为载体（开源 NDJSON 格式、玩家开源、可直接嵌入
GitHub/Notion），由 ClawCodex 各子系统**按结构化事件投影** + **渲染输出捕获**
两种模式输出到同一个 `.cast` 文件。

### 1.2 目标

1. 一次性录制 5 个子系统的功能演示到一份 `.cast`：orchestrator / query loop /
   SOP converter / visualizer dashboard / cron daemon
2. 零 `src/` 编辑（CLAUDE.md 解耦硬约束）；新代码全部落在 `extensions/` 与
   `clawcodex_ext/`
3. 自包含 v2 格式校验器（不依赖 asciinema CLI / Rust toolchain）
4. 每帧立刻 flush（`tail -f` 可读）
5. CLI 入口 `clawcodex record --sources ... --out demo.cast` 零配置可跑

### 1.3 子特性分解

| 编号 | 子特性 | 状态 | 文件位置 |
|:----:|--------|:----:|---------|
| F-REC-A | Protocol 契约层（`RecordableSource` / `AsciicastCapture` / `AsciicastHeader` / `AsciicastEvent`） | ✅ | `extensions/capabilities/recorder.py` |
| F-REC-B | Writer（自包含 NDJSON、per-frame flush、threading.Lock、U+2028/U+2029 转义） | ✅ | `extensions/recording/asciicast_writer.py` |
| F-REC-C | Renderer helpers（phase/tool/cron 标记、ASCII panel、TeeWriter） | ✅ | `extensions/recording/renderers.py` |
| F-REC-D | 自包含 validator（零依赖 v2 schema 检查） | ✅ | `extensions/recording/validate_cast.py` |
| F-REC-E | Source registry（线程安全 register/get/names） | ✅ | `extensions/recording/registry.py` |
| F-REC-F | 5 个 per-subsystem adapter（orchestrator/sop/visualizer/cron/query） | ✅ | `extensions/orchestrator/asciicast_sink.py` / `extensions/sop_converter/asciicast_projector.py` / `extensions/visualizer/asciicast_dashboard_source.py` / `clawcodex_ext/cron_system/asciicast_observer.py` / `extensions/recording/query_forwarder.py` |
| F-REC-G | 5 处一行挂载点（orchestrator / query / sop CLI / cron runtime / report_writer） | ✅ | `extensions/orchestrator/orchestrator.py` / `extensions/api/query.py` / `clawcodex_ext/cli/sop_cmd/commands.py` / `clawcodex_ext/cron_system/runtime.py` / `extensions/orchestrator/report_writer.py` |
| F-REC-H | `clawcodex record` CLI（argparse + duration + SIGINT + multi-source fan-in） | ✅ | `extensions/recording/cli.py` |
| F-REC-I | 测试套件（66 用例：unit + integration + subprocess E2E） | ✅ | `tests/extensions/recording/` |
| F-REC-J | 端到端示例：REPL `/dashboard` 逻辑看板 4-tick 演化录制（可运行 + 可测试） | ✅ | `extensions/recording/examples/logical_kanban_repl_demo.py` |
| F-REC-K | `.cast → MP4` 后处理器（Pillow 渲染 + ffmpeg 编码 + `clawcodex cast-to-mp4` 子命令） | ✅ | `extensions/recording/tools/cast_to_mp4.py` + `extensions/recording/cast_to_mp4_cli.py` |
| F-REC-L | 真实 REPL 交互录制（Rich Console TeeWriter + prompt_async proxy + `clawcodex-dev --record`） | ✅ | `extensions/recording/repl_source.py` + `clawcodex_ext/cli/parser.py` + `clawcodex_ext/frontend/repl.py` |

### 1.4 录制模式

| 模式 | 子系统 | 实现 |
|------|--------|------|
| **结构化事件投影** | orchestrator / query / cron | adapter 监听 `ProgressSink` / `HeadlessSessionOptions.on_event` / 4 个 cron 回调，转成 `m`/`o` 帧 |
| **渲染输出捕获** | SOP converter / visualizer dashboard | `TeeWriter` 镜像 `sys.stdout`，或把 HTML 面板渲染成 ASCII 文本帧 |
| **真实 REPL 捕获** | 默认 inline REPL（prompt_toolkit + rich） | 替换 `repl.console.file` 为 `RichConsoleTeeWriter`，包装 `repl.prompt_session.prompt_async` 为 `PromptSessionProxy`；`"i"` 帧记录用户输入，`"o"` 帧记录 Rich 实际渲染 |

三种模式**共用同一个 writer**，append-only，不需要区分。

### 1.5 影响范围

| 现有模块 | 改动类型 | 说明 |
|---------|---------|------|
| `extensions/orchestrator/orchestrator.py` | +1 kwarg + 3 行挂载 | `asciicast_capture: Any = None` 注入，`_build_session_sink` 末尾条件添加 `AsciicastSink` |
| `extensions/api/query.py` | +1 field + 3 行挂载 | `QueryConfig.capture: Any = None`，`stream()` 内部 lazy import `forward_event` 包装 `on_event` |
| `clawcodex_ext/cli/sop_cmd/commands.py` | +1 field + ~10 行 | `--record <path>` flag，`SopStageProjector` 包住 convert+print |
| `clawcodex_ext/cron_system/runtime.py` | +1 kwarg + 5 行 | `asciicast_observer: Any | None`，构造 scheduler 时挂载 4 个回调 |
| `extensions/orchestrator/report_writer.py` | +2 field + ~25 行 | `cast_path: str | None`，dual-write `.cast` 到 workspace + persistent |
| `extensions/visualizer/__init__.py` | +5 行 | try/except 注册 `AsciicastDashboardSource()` |
| `clawcodex_ext/cli/subcommand_registry.py` | +5 行 | lazy import `extensions.recording.cli` 触发 `@register("record")` |
| `clawcodex_ext/cli/parser.py` | +3 个 flag | `--record` / `--record-width` / `--record-height`（仅默认 REPL，不支持 `--tui`） |
| `clawcodex_ext/cli/dispatch.py` | +3 行 | 把 `--record*` 参数注入 `RuntimeOptions(...)` |
| `clawcodex_ext/runtime/context.py` | +3 行 | `RuntimeOptions` 新增 `record` / `record_width` / `record_height` 字段 |
| `clawcodex_ext/frontend/repl.py` | +6 行 | `install_repl_extensions(...)` 之后 try/except 调用 `install_repl_capture(...)` |

**`src/` 改动：0 行**（CLAUDE.md 解耦硬约束达成）。

### 1.6 验证

```bash
# 1. 单元 + 集成测试
python3 -m pytest tests/extensions/recording/ -q
# 期望: 115 passed

# 2. 稳定性门禁（除 pre-existing flaky Stage 6 perf 外全绿）
python3 -m pytest tests/stability_gate/ --ignore=tests/stability_gate/test_stage6_perf.py -q

# 3. Orchestrator 单元测试（除 pre-existing repro_gate flake 外全绿）
python3 -m pytest tests/orchestrator/ --ignore=tests/orchestrator/manual_e2e_f38.py -q

# 4. 手动 smoke
clawcodex record --list-sources
clawcodex record --sources cron --out /tmp/demo.cast --duration 1s --validate
head -1 /tmp/demo.cast  # header
tail -1 /tmp/demo.cast | python3 -m json.tool  # last frame

# 5. .cast → MP4（需要本机 ffmpeg + Pillow）
python3 -m extensions.recording.examples.logical_kanban_repl_demo \
    --out /tmp/kanban.cast --ticks 4 --frame-delay 0.5
clawcodex cast-to-mp4 --cast /tmp/kanban.cast --out /tmp/kanban.mp4 --fps 2
file /tmp/kanban.mp4    # 应输出 "ISO Media, MP4 v2"

# 6. 真实 REPL 录制
clawcodex-dev --record /tmp/real-repl.cast
# 进入 REPL 后键入任意 prompt，退出后：
python3 -c "from extensions.recording.validate_cast import validate_cast; \
  print(validate_cast('/tmp/real-repl.cast'))"   # []
python3 -c "import json; \
  print([l for l in open('/tmp/real-repl.cast') if '\"i\"' in l][:3])"  # 用户输入
```

### 1.7 风险与约束

| 风险 | 缓解 |
|------|------|
| Stage 6 perf 边界（Conversation import 2.35s vs 2.00s） | Pre-existing flake（clean main 也是 2.21s），与 F-REC 无关；CLAUDE.md CI 阈值已 2× 放宽 |
| Orchestrator `test_repro_gate.test_green_repro_command_passes_and_reports` | Pre-existing 失败（clean main 也 fail），与 F-REC 无关 |
| U+2028/U+2029 在 JSON 中是合法字符但破坏 NDJSON receiver | Writer 主动转义为 `\u2028` / `\u2029` |
| 多 source 同时 emit 跨线程顺序 | Writer `threading.Lock` 序列化；测试验证单线程帧有序 |
| Adapter 抛异常阻塞 orchestrator | 每个 adapter `try/except` 包裹，failure 仅记 warning 不中断主流程 |

### 1.8 开放项（deferred）

- `clawcodex record --auto` 模式：让 orchestrator / SOP 真实运行负载生成 demo
  事件（当前 CLI 只接受已有 source 的 tick，orchestrator / SOP 需要触发器）
- Live `tail -f` over in-progress `.cast`：已具备条件（每帧 flush），仅缺文档示例
- HTTP upload to asciinema.org：deferred，等用户实际需求