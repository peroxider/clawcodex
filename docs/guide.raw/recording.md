# ClawCodex 功能录制指南（Asciicast v2）

ClawCodex 内置 asciicast v2 `.cast` 录制器，可以把 orchestrator / query loop /
SOP 编译器 / 视觉化看板 / cron 守护进程等多个子系统的功能演示**自动产出**为可
嵌入 README 的回放文件。

## 1. 5 分钟上手

```bash
# 列出当前可录制的子系统
clawcodex record --list-sources

# 输出示例：
# registered sources:
#   - cron
#   - orchestrator
#   - query
#   - sop
#   - visualizer

# 录制 cron 子系统 1 秒，立刻 validate 格式
clawcodex record --sources cron \
    --out /tmp/cron-demo.cast \
    --duration 1s \
    --validate

# 录制结束后查看
head -1 /tmp/cron-demo.cast  # header (JSON)
tail -1 /tmp/cron-demo.cast | python3 -m json.tool  # 最后一帧
```

`.cast` 文件可以直接给 asciinema player 播放（浏览器内嵌入），也可以用
`asciinema play /tmp/cron-demo.cast` 在本地终端回放（需先 `brew install
asciinema` 或 `apt install asciinema`）。

## 2. 多 source 同时录制

同一份 `.cast` 可以装多个子系统的输出，事件按时间顺序写入：

```bash
# cron + sop + visualizer 三源同录
clawcodex record \
    --sources cron,sop,visualizer \
    --out demo.cast \
    --duration 30s
```

写入 `.cast` 的事件格式：

| code | 含义 | 谁写 |
|------|------|------|
| `m` | 导航标记（marker） | 所有 adapter |
| `o` | 输出帧（可含 ANSI 转义） | SOP / visualizer / query TextDelta |
| `i` | 输入帧 | 暂无，保留供将来 REPL 输入录制 |
| `r` | 终端 resize | 显式调用 `capture.resize()` |

## 3. 在 README 中嵌入

把 `.cast` 上传到 asciinema.org（需账号）或自托管：

```markdown
<script src="https://asciinema.org/a/<your-cast-id>.js" id="asciicast"></script>
```

或者使用 React/Vue 的 `<AsciinemaPlayer>` 组件。

## 4. 在 PR 评论中自动挂 `.cast`

`extensions/orchestrator/report_writer.write()` 的 `cast_path` 参数会被
dual-write 到 workspace 与 persistent 目录，PR 评论自动附带：

```python
from extensions.orchestrator.report_writer import write

result = write(
    run_id="issue-42-2026-07-13",
    workspace_path=workspace,
    tracker="github",
    owner="chadwweng",
    repo="clawcodex",
    issue=issue,
    status="success",
    cast_path=f"{workspace}/.reports/issue-42.cast",
)
# result.persistent_cast_path 即可作为 PR 评论附件
```

## 5. 自包含校验器（CI 用）

`extensions/recording/validate_cast.py` 不依赖 asciinema CLI，纯 Python
实现 v2 schema 检查，CI 可以直接调用：

```python
from pathlib import Path
from extensions.recording.validate_cast import validate_cast

errors = validate_cast(Path("demo.cast"))
if errors:
    for err in errors:
        print(err)
    raise SystemExit(1)
```

CLI 也内置 `--validate` 开关，录制完自动校验。

## 6. 编程式使用

```python
from pathlib import Path
from extensions.capabilities.recorder import AsciicastHeader
from extensions.recording.asciicast_writer import AsciicastWriter

writer = AsciicastWriter(
    Path("demo.cast"),
    AsciicastHeader(width=120, height=36, title="my demo"),
)
with writer as capture:
    capture.marker("phase:1", text="starting phase 1")
    # ... 你的代码 ...
    capture.marker("phase:2")
# demo.cast 已 flush 并 close，可直接给 asciinema player 播放
```

## 7. 端到端示例：REPL 中录制逻辑看板

`extensions/recording/examples/logical_kanban_repl_demo.py` 是一个
**可运行 + 可测试** 的端到端示例，模拟以下 REPL 场景：

> 用户在 ClawCodex REPL 中打开了 `/dashboard`（逻辑看板），看到
> orchestrator 正在处理 3 个 GitHub issue；4 个 tick 内看板状态从
> `pending / running` 演化到 `done / failed / blocked`，最终还有 1
> 个新 issue 加入队列。

直接跑：

```bash
python3 -m extensions.recording.examples.logical_kanban_repl_demo \
    --out /tmp/kanban.cast --ticks 4 --frame-delay 0.5
# [demo] /tmp/kanban.cast — 22 frame(s); validation: OK
```

或者作为 pytest 子进程 E2E 跑（CI 友好）：

```bash
python3 -m pytest tests/extensions/recording/test_logical_kanban_repl_e2e.py -q
# 6 passed in 7s
```

录制的 `.cast` 内容示例（4 个 tick 的统计行）：

```
Logical Kanban (tick 0)    ⏳ pending: 1  🔵 running: 2  ✅ done: 0  ❌ failed: 0  🚧 blocked: 0
Logical Kanban (tick 1)    ⏳ pending: 1  🔵 running: 1  ✅ done: 1  ❌ failed: 0  🚧 blocked: 0
Logical Kanban (tick 2)    ⏳ pending: 0  🔵 running: 0  ✅ done: 2  ❌ failed: 1  🚧 blocked: 0
Logical Kanban (tick 3)    ⏳ pending: 1  🔵 running: 0  ✅ done: 2  ❌ failed: 0  🚧 blocked: 1
```

每个 tick 是一组 ASCII 面板（`─` 框线 + 状态徽章 `⏳/🔵/✅/❌/🚧`），
和 `/dashboard` 命令在终端里显示的视觉风格一致，可以直接喂给
asciinema player 在浏览器中回放。

## 8. 故障排查

| 症状 | 原因 | 修复 |
|------|------|------|
| `error: unknown source(s): xxx` | source_id 未注册或拼错 | 跑 `clawcodex record --list-sources` 查可用列表 |
| `.cast` 只有 header 没有事件 | 录制时长太短，adapter 还没触发事件 | 加 `--duration` 到 ≥ 1s，或触发子系统负载 |
| 浏览器播放没颜色 | `width`/`height` 与 ANSI 冲突 | 用 `--width 120 --height 36` 显式声明 |
| 多线程场景下顺序乱 | asciicast v2 不保证跨线程顺序 | 这是 NDJSON 格式的自然限制，按时间戳回放即可 |

## 9. 架构概览

```
extensions/capabilities/recorder.py    ← Protocol-only 契约
extensions/recording/                  ← 共享 writer + registry + CLI
├── asciicast_writer.py                ← 持有 .cast 文件 + 锁 + flush
├── renderers.py                       ← phase/tool/cron/panel helpers
├── validate_cast.py                   ← 自包含 v2 schema 校验
├── registry.py                        ← RecordableSource 注册中心
├── cli.py                             ← clawcodex record 入口
├── query_forwarder.py                 ← query 事件 → AsciicastEvent 翻译
├── _factories.py                      ← 5 个 built-in source 工厂
└── __init__.py

per-subsystem adapters:
extensions/orchestrator/asciicast_sink.py
extensions/sop_converter/asciicast_projector.py
extensions/visualizer/asciicast_dashboard_source.py
clawcodex_ext/cron_system/asciicast_observer.py

5 个一行挂载点：
extensions/orchestrator/orchestrator.py    ← asciicast_capture: kwarg
extensions/api/query.py                    ← QueryConfig.capture field
clawcodex_ext/cli/sop_cmd/commands.py      ← --record flag
clawcodex_ext/cron_system/runtime.py       ← asciicast_observer: kwarg
extensions/orchestrator/report_writer.py   ← cast_path: kwarg + dual-write
```

完整设计文档：[`docs/feature_plan/08-recording/f-156-asciicast-recorder.md`](../feature_plan/08-recording/f-156-asciicast-recorder.md)。