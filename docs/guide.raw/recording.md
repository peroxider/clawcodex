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

### 1.1 录制真实的 REPL 交互

如果你要做特性展示（而不是模拟界面），最直接的方式是启动 REPL 时同时
打开录制：

```bash
clawcodex-dev --record /tmp/real-repl.cast
```

进入 REPL 后正常交互——你键入的每一行、agent 返回的 Rich Panel、tool
block 都会写入 `.cast`。

```bash
# 可选：显式指定 .cast 头里的终端尺寸（默认自动检测当前终端）
clawcodex-dev --record /tmp/real-repl.cast --record-width 120 --record-height 40

# 退出 REPL 后验证
head -1 /tmp/real-repl.cast
python3 -c "from extensions.recording.validate_cast import validate_cast; \
  print(validate_cast('/tmp/real-repl.cast'))"
```

> **限制**：prompt_toolkit 的提示符栏（`❯`、行编辑、补全弹窗）由
> prompt_toolkit 自己渲染，不走 Rich `Console`，因此不会被录制成像素；
> 我们用 `m` marker 标记每次 prompt 的开始/提交边界，回放时仍可定位到
> 交互节点。

### 1.2 与 `clawcodex record` 的关系

| 命令 | 录制对象 | 场景 |
|---|---|---|
| `clawcodex record --sources ... --out x.cast` | 后台子系统事件（orchestrator、cron、query...） | CI / orchestrator 跑完 issue 自动挂 `.cast` |
| `clawcodex record --auto --out x.cast` | 真实 orchestrator batch + dashboard tick | 无人值守的自动化演示 |
| `clawcodex-dev --record x.cast` | **真实 REPL 交互** | 特性展示、人工演示 |


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

## 8. 把 `.cast` 转成 MP4 / 视频

`.cast` 本身是 NDJSON 文本流（不是视频），在需要嵌入 README、PR 评论或
Notion 演示时，可以用 `cast-to-mp4` 子命令把每个 `dashboard:snapshot`
标记渲染成一帧 PNG，再交给 ffmpeg 编码成 MP4 / WebM / MKV 等任意
`libx264` 支持的格式。

```bash
# 先准备一个 .cast（与 §1 相同的命令）
python3 -m extensions.recording.examples.logical_kanban_repl_demo \
    --out /tmp/kanban.cast --ticks 4 --frame-delay 0.5

# 转成 MP4：960×480, h264/yuv420p, 浏览器可直接播放
clawcodex cast-to-mp4 \
    --cast /tmp/kanban.cast \
    --out /tmp/kanban.mp4 \
    --fps 2

# 想保留 PNG 中间帧方便复盘时：
clawcodex cast-to-mp4 \
    --cast /tmp/kanban.cast \
    --out /tmp/kanban.mp4 \
    --fps 2 \
    --keep-pngs
# → /tmp/kanban.mp4.pngs/frame_000.png ... frame_003.png
```

可调参数：

| 参数 | 默认 | 说明 |
|------|------|------|
| `--fps` | 4 | 帧率（每秒多少张 PNG 进入编码器） |
| `--width` / `--height` | 960 / 480 | PNG 分辨率 |
| `--keep-pngs` | 关 | 额外把 PNG 序列复制到 `<out>.pngs/` |

**前置依赖**：本机需要 `ffmpeg` 在 `PATH`；转换器函数使用 Pillow 渲染
PNG（cast-to-mp4 这一路径才会触发，主录制管线 `clawcodex record` 不依赖
Pillow）。

**为什么 Pillow + ffmpeg 而不是 `agg`**：`asciinema/agg` 是官方 GIF
生成器，但只输出 GIF，没有 MP4。`ffmpeg` 通用，能产出任意
`libx264` 容器，对嵌入场景更友好。源：[asciinema 文档 — agg](https://docs.asciinema.org/manual/agg/)、
[ffmpeg 文档 — concat demuxer](https://ffmpeg.org/ffmpeg-formats.html#concat)。

**色彩空间坑**：MP4 在 Chrome / Safari 上必须用 h264 + yuv420p，否则
会显示成黑白棋盘；`cast-to-mp4` 已经把 `format=yuv420p` 和
`+faststart` 写到命令行里，无需手动加。

**emoji fallback**：服务器没有 emoji 字体时，Pillow 会把 `⏳/🔵/✅/❌/🚧`
画成空白方块。`cast-to-mp4` 在写入 PNG 前自动替换成 ASCII 标签（`[pending]` /
`[running]` / `[done]` / `[failed]` / `[blocked]`），浏览器侧
`asciinema-player` 仍按原 `.cast` 的 emoji 渲染，不受影响。

## 9. 故障排查

| 症状 | 原因 | 修复 |
|------|------|------|
| `error: unknown source(s): xxx` | source_id 未注册或拼错 | 跑 `clawcodex record --list-sources` 查可用列表 |
| `.cast` 只有 header 没有事件 | 录制时长太短，adapter 还没触发事件 | 加 `--duration` 到 ≥ 1s，或触发子系统负载 |
| 浏览器播放没颜色 | `width`/`height` 与 ANSI 冲突 | 用 `--width 120 --height 36` 显式声明 |
| 多线程场景下顺序乱 | asciicast v2 不保证跨线程顺序 | 这是 NDJSON 格式的自然限制，按时间戳回放即可 |
| `cast-to-mp4` 提示 `ffmpeg not found` | 本机没装 ffmpeg | `apt install ffmpeg`（Debian/Ubuntu）或 `brew install ffmpeg`（macOS）后重试 |
| `cast-to-mp4` 报 `RuntimeError: cast_to_mp4 requires Pillow` | 转换路径需要 Pillow | `pip install Pillow`（主录制 `clawcodex record` 不依赖 Pillow） |
| MP4 在 Chrome 显示黑屏 | h264 不是 yuv420p 色彩空间 | 已是默认；如手动调整务必保留 `-vf format=yuv420p` |
| `--record` 后 REPL 没输出到 `.cast` | `ctx.options.record` 在 TUI 模式被另一条路径消费 | `--record` 仅支持默认 inline REPL，不支持 `--tui` |
| `--record` 的 `.cast` 里没有 `❯` 提示符 | prompt_toolkit 提示符栏不走 Rich Console | 这是已知限制；我们用 `repl:prompt:start/submit` marker 标记交互节点 |

## 10. 架构概览

```
extensions/capabilities/recorder.py    ← Protocol-only 契约
extensions/recording/                  ← 共享 writer + registry + CLI
├── asciicast_writer.py                ← 持有 .cast 文件 + 锁 + flush
├── renderers.py                       ← phase/tool/cron/panel helpers
├── validate_cast.py                   ← 自包含 v2 schema 校验
├── registry.py                        ← RecordableSource 注册中心
├── cli.py                             ← clawcodex record 入口
├── cast_to_mp4_cli.py                 ← clawcodex cast-to-mp4 入口
├── repl_source.py                     ← F-REC-L：真实 REPL 捕获
├── query_forwarder.py                 ← query 事件 → AsciicastEvent 翻译
├── _factories.py                      ← 5 个 built-in source 工厂
├── tools/                             ← .cast 后续处理工具（opt-in）
│   └── cast_to_mp4.py                 ← Pillow + ffmpeg 渲染与编码
├── examples/                          ← 可运行示例
│   ├── logical_kanban_repl_demo.py    ← 模拟 dashboard tick 演化
│   └── repl_demo_driver.py            ← 真实 REPL capture 驱动（E2E）
└── __init__.py

per-subsystem adapters:
extensions/orchestrator/asciicast_sink.py
extensions/sop_converter/asciicast_projector.py
extensions/visualizer/asciicast_dashboard_source.py
clawcodex_ext/cron_system/asciicast_observer.py

REPL 捕获挂载点（Layer 1）:
clawcodex_ext/cli/parser.py              ← --record / --record-width / --record-height
clawcodex_ext/frontend/repl.py           ← install_repl_capture(repl, ctx)

5 个一行挂载点（后台子系统）:
extensions/orchestrator/orchestrator.py    ← asciicast_capture: kwarg
extensions/api/query.py                    ← QueryConfig.capture field
clawcodex_ext/cli/sop_cmd/commands.py      ← --record flag
clawcodex_ext/cron_system/runtime.py       ← asciicast_observer: kwarg
extensions/orchestrator/report_writer.py   ← cast_path: kwarg + dual-write
```

完整设计文档：[`docs/feature_plan/08-recording/f-156-asciicast-recorder.md`](../feature_plan/08-recording/f-156-asciicast-recorder.md)。