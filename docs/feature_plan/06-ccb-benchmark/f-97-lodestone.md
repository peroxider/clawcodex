# F-97: LODESTONE 深度链接

> 状态: 📋 规划中(目标模块 `clawcodex_ext/services/lodestone/` 待建;无既有实现)
> 章节: `docs/feature_plan/06-ccb-benchmark/f-97-lodestone.md`
> 最后更新: 2026-07-01
> 缺口来源: gap-analysis-2026q2.md §3.3(`#### F-97: LODESTONE 深度链接`,已分解到本文档 §0)

## §0 缺口摘要

> 本节为 gap-analysis-2026q2.md §3.3 F-97 派工条目的分解版本;详细设计与基线请阅读 §1。

### 0.1 缺口描述

无既有 anchor 层,输出中的代码引用全是裸文本:

- `path:line[:col]` 在 tool result / REPL 中只能显示纯文本,需手动复制再打开 editor;
- git 引用(`commit abc1234`)无自动跳转到 `gitcode.com/.../commit/abc1234`;
- 多 IDE 环境无统一偏好(想一次配置 `vscode`,fallback 到 `idea` / `subl`);
- tracker issue 引用(`#123` / `BUG-456`)未链接化;
- Team 通信(`SendMessage`)内容里的引用也是裸文本;
- 不同消息形态(纯文本 / Markdown / REPL Panel)渲染能力不同,缺适配层。

可借鉴原语:`src/utils/git.py:FileStatus`(相对路径 + git 信息)、`clawcodex_ext/services/swarm/team_file.py`(仓库定位)、`extensions/orchestrator/git_sync.py`(PR body Markdown 链接经验)、TUI OSC 8 terminal hyperlink。

### 0.2 对标

- CCB `LODESTONE` 统一 anchor schema + resolver + 多目标 renderer;
- CCB `path:line[:col]` / git ref / tracker issue 统一识别与链接化;
- CCB 多目标路由(vscode / idea / subl / `file://` / GitHub / GitCode)带 fallback 顺序;
- CCB 三种输出适配(纯文本 / Markdown / OSC 8 escape)。

### 0.3 解耦落地路径(全部 `clawcodex_ext/services/lodestone/`,新子系统)

- `models.py` — `LodestoneAnchor` / `AnchorTarget` / `AnchorContext`;
- `parser.py:AnchorParser` — 识别 `path:line[:col]` / git ref / tracker issue;
- `target_registry.py:AnchorTargetRegistry` — vscode / idea / subl / `file://` / GitHub / GitCode;
- `resolver.py:AnchorResolver` — context → ordered 候选 target URL;
- `renderer.py:AnchorRenderer` — 纯文本 / Markdown / OSC 8;
- `fingerprint.py` — 本地仓库自动识别 host platform / remote URL;
- `clawcodex_ext/command_system/lodestone_commands.py` — `/link` 命令族 + `LodestoneTool`。

### 0.4 依赖

- 现有 `src/utils/git.py:FileStatus` / `team_file.py` / `git_sync.py` anchor 渲染经验;
- F-82 Remote Control(远程输出的 anchor 需回本地映射);
- F-93 TeamMem(team 历史里的引用链接化);
- F-94 BG_SESSIONS(后台 session transcript 里的引用链接化)。

### 0.5 估算工时

1-2 周(单人)。

---

## §1 设计规划

### 1.1 目标

对标 CCB `LODESTONE` 能力,把 ClawCodex 当前 CLI / TUI 输出的“纯文本代码引用”升级为**统一、可点击、可跳转、可在多个目标编辑器/Tracker 之间路由**的深度链接层。

F-97 的核心思想:**所有出现在 agent 输出、tool result、REPL 输出、TeamMem / background session 历史里的 `path:line[:column]`、`function:line`、`<git sha>:<path>:<line>` 等引用,都应该是 LODESTONE 锚点,可以被解析并渲染为可点击的 URL,而非裸文本。**

LODESTONE 不是一个独立的 IDE 集成,而是一个**轻量级、协议化、可插拔的锚点渲染层**,把渲染决策交给消费方(TUI hyperlink、HTML 输出、桌面通知、Mailbox 消息等)。

### 1.2 背景

ClawCodex 当前痛点:

- `cat file.py:42:13` 在 tool result 中只能显示成纯文本,用户在 TUI 需要手动复制路径再打开 editor;
- git 引用如 `commit abc1234` 缺少自动跳转到 `gitcode.com/.../commit/abc1234` 的能力;
- 多 IDE 同时安装的环境下,用户没有统一偏好(用户更希望一次配置 `vscode`,但希望 fallback 到 `idea` / `subl`);
- tracker issue 引用如 `#123` / `BUG-456` 没有链接化,无法一键跳转;
- Team 通信(`SendMessage`)内容里出现的引用也是裸文本;
- 不同消息形态(纯文本、Markdown、REPL Panel)对链接的渲染能力不同(终端 hyperlink、ANSI escape、Markdown `[text](url)`),需要一个适配层。

已经有可借鉴的原语:

1. `src/utils/git.py:FileStatus` 已能给出文件相对路径 + git 信息;
2. `clawcodex_ext/services/swarm/team_file.py` 已能给出仓库定位;
3. `extensions/orchestrator/git_sync.py` 已经在构建 PR body 时使用 Markdown 链接,提供 anchor 渲染的现成经验;
4. `src/bridge/messaging.RemotePermissionResponse` 已存在“结构化通信”模式可供借鉴;
5. TUI 终端 hyperlink(iTerm2 / WezTerm / VS Code integrated terminal, OSC 8 escape 序列)已可由 Rich/Textual 渲染。

缺口在于:**没有一个统一的 anchor schema + resolver + renderer**。F-97 补齐这一层。

### 1.3 子特性分解

| 编号 | 子特性 | 预计工作量 |
|:----:|--------|:----------:|
| P97-A | 数据模型(`LodestoneAnchor`, `AnchorTarget`, `AnchorContext`) | 1 天 |
| P97-B | Anchor parser(`AnchorParser`):识别 `path:line[:col]`、git ref、tracker issue 等 | 1.5 天 |
| P97-C | Target registry(`AnchorTargetRegistry`):vscode / idea / subl / `file://` / GitHub / GitCode | 1 天 |
| P97-D | Resolver(`AnchorResolver`):context → ordered候选 target URL | 1.5 天 |
| P97-E | Renderer(`AnchorRenderer`):纯文本 / Markdown / OSC 8 三种输出 | 1 天 |
| P97-F | Workspace fingerprints:本地仓库自动识别 host platform、remote URL | 1 天 |
| P97-G | CLI/Tool 接入:`/link` + `LodestoneTool` | 1 天 |
| P97-H | 单元 + 集成测试 | 1.5 天 |

**估算总工时**:1-2 周。

### 1.4 架构设计

```
Code references in any output
  ├─ File:line token ("path.py:42")
  ├─ Function symbol ("foo()")
  ├─ Git ref ("abc1234" or "@abc1234")
  ├─ Tracker issue ("#123", "LIN-456")
  └─ URL fragment already
             │
             ▼
LodestoneParser
  ├─ tokenize(line)
  ├─ classify(AnchorKind)
  └─ build LodestoneAnchor
             │
             ▼
LodestoneResolver
  ├─ workspace fingerprint
  ├─ user preference (config: editor=vscode)
  ├─ environment probe (TERM_PROGRAM, DISPLAY)
  └─ AnchorTargetRegistry.match()
             │
             ▼
LodestoneRenderer(sink="text" | "markdown" | "osc8")
             │
             ▼
final string with clickable link
```

#### 包结构

```
clawcodex_ext/services/lodestone/
├── __init__.py
├── models.py                # P97-A: Anchor / Context / TargetKind
├── parser.py                # P97-B: parse anchor tokens
├── targets.py               # P97-C: 注册 + 内置 target
├── resolver.py              # P97-D: 候选排序与选定
├── renderer.py              # P97-E: 三种 sink
├── fingerprint.py           # P97-F: workspace fingerprint
└── config.py                # 默认配置 + 用户偏好加载

clawcodex_ext/command_system/
└── link_commands.py         # P97-G: /link 命令族

clawcodex_ext/tool_system/tools/
└── lodestone.py             # P97-G: LodestoneTool

extensions/capabilities/
└── lodestone_protocol.py    # P97-D: AnchorSink Protocol

tests/clawcodex_ext/services/lodestone/
├── test_parser.py
├── test_targets.py
├── test_resolver.py
├── test_renderer.py
└── test_fingerprint.py
```

### 1.5 核心数据模型

```python
AnchorKind = Literal[
    "file_path",            # path:line[:col][-end_line[:end_col]]
    "function_ref",         # module.func 或 module::func
    "git_blob",             # @<git_sha>:path
    "git_commit",           # <sha>（7-40 hex）
    "tracker_issue",        # #123, [ORG-123], ORG-123
    "url",                  # 已是 URL
]


@dataclass(frozen=True)
class LodestoneAnchor:
    kind: AnchorKind
    raw: str                                # 原始文本
    file_path: str | None = None
    line: int | None = None
    column: int | None = None
    end_line: int | None = None
    end_column: int | None = None
    symbol: str | None = None
    git_sha: str | None = None
    tracker_key: tuple[str, str | None] | None = None    # ("gitcode", "123")
    url: str | None = None                    # 已是 url
    span: tuple[int, int] | None = None       # raw text 中位置


@dataclass(frozen=True)
class AnchorContext:
    workspace_root: Path | None
    session_id: str | None
    config: LodestoneConfig
    remote_url: str | None = None
    branch: str | None = None
    is_collapsed: bool = False


@dataclass(frozen=True)
class AnchorTarget:
    kind: AnchorKind
    target_id: str                           # 注册 id, e.g. "vscode", "file"
    editor_scheme: str | None = None         # "vscode"
    template: str                            # e.g. "vscode://file/{abs}:{line}:{col}"
    is_remote: bool = False
    requires: tuple[str, ...] = ()           # "DISPLAY", "browser", "git_remote"


@dataclass(frozen=True)
class RenderedAnchor:
    anchor: LodestoneAnchor
    target: AnchorTarget | None
    link_text: str
    rendered: str                            # 最终 string(Markdown / OSC 8 / 纯文本)
    is_anchor: bool                          # 是否成功生成 link
    fallback_reason: str | None = None


@dataclass(frozen=True)
class LodestoneConfig:
    enabled: bool = False
    default_editor: str = "vscode"           # target_id
    fallback_editor: str = "file"
    auto_remote: bool = True                 # 能解析 git remote 时自动选远端 URL
    disabled_kinds: tuple[AnchorKind, ...] = ()
    renderer: Literal["text", "markdown", "osc8", "auto"] = "auto"
    custom_targets: tuple[AnchorTarget, ...] = ()
```

### 1.6 核心接口

```python
class AnchorParser:
    """识别并提取 anchors."""

    def parse(self, text: str) -> list[LodestoneAnchor]: ...

    def parse_first(self, text: str) -> LodestoneAnchor | None: ...


class AnchorTargetRegistry:
    """注册 target + 选 target."""

    def __init__(self, config: LodestoneConfig) -> None: ...

    def register(self, target: AnchorTarget, *, overwrite: bool = False) -> None: ...

    def unregister(self, target_id: str) -> bool: ...

    def list(self) -> list[AnchorTarget]: ...

    def candidates(
        self,
        kind: AnchorKind,
        *,
        ctx: AnchorContext,
    ) -> list[AnchorTarget]: ...

    def pick(
        self,
        kind: AnchorKind,
        *,
        ctx: AnchorContext,
    ) -> AnchorTarget | None: ...


class AnchorResolver:
    """把 anchor + context → 候选 target + 选定."""

    def resolve(
        self,
        anchor: LodestoneAnchor,
        *,
        ctx: AnchorContext,
    ) -> RenderedAnchor: ...

    def resolve_text(
        self,
        text: str,
        *,
        ctx: AnchorContext,
    ) -> str: ...


class AnchorRenderer:
    """把 (anchor, ctx) 渲染为 text/Markdown/OSC 8."""

    def render(
        self,
        anchor: LodestoneAnchor,
        *,
        ctx: AnchorContext,
        sink: Literal["text", "markdown", "osc8"] | None = None,
    ) -> RenderedAnchor: ...


def detect_workspace_fingerprint(root: Path) -> WorkspaceFingerprint: ...
```

### 1.7 内置 Target 列表

| target_id | kind 覆盖 | template | 要求 |
|-----------|----------|----------|------|
| `vscode` | `file_path`, `function_ref` | `vscode://file/{abs}:{line}:{col}` | VS Code 已安装 |
| `vscode-insiders` | `file_path` | `vscode-insiders://file/{abs}:{line}:{col}` | VS Code Insiders |
| `cursor` | `file_path` | `cursor://file/{abs}:{line}:{col}` | Cursor 已安装 |
| `idea` | `file_path` | `idea://open?file={abs}&line={line}&column={col}` | IntelliJ 已安装 |
| `subl` | `file_path` | `subl://open?url=file://{abs}&line={line}&column={col}` | Sublime Text |
| `file` | `file_path` | `file://{abs}` | 任意系统(兜底) |
| `github` | `file_path`, `git_blob`, `git_commit` | `{remote}/blob/{branch}/{rel}#L{line}` | 联网 + 已知 remote |
| `gitcode` | `file_path`, `git_blob`, `git_commit` | `https://gitcode.com/{owner}/{repo}/...` | 联网 + GitCode remote |
| `gitee` | `file_path`, `git_blob`, `git_commit` | `https://gitee.com/{owner}/{repo}/...` | 联网 + Gitee remote |
| `tracker:gitcode` | `tracker_issue` | `https://gitcode.com/{owner}/{repo}/issues/{n}` | GitCode remote |
| `tracker:linear` | `tracker_issue` | `https://linear.app/{workspace}/issue/{key}` | Linear config |

判定顺序:

1. 用户 `default_editor` 配置;
2. 环境探针:`TERM_PROGRAM=vscode` → vscode;`CURSOR_TRACE_ID` → cursor;`DISPLAY` & `idea*` 在 PATH → idea;`subl` 在 PATH → subl;
3. (file_path 本地化目标)若以上都不存在,fallback 到 `file://`;
4. (远程类)若有 git remote 解析,根据 `auto_remote` 选 GitHub/GitCode/Gitee;
5. tracker 类按 config 中显式启用,且 workspace 上有 tracker 配置。

### 1.8 Workspace fingerprint

`WorkspaceFingerprint` 由 `detect_workspace_fingerprint()` 生成:

```python
@dataclass(frozen=True)
class WorkspaceFingerprint:
    workspace_root: Path
    primary_remote_url: str | None          # e.g. "https://gitcode.com/foo/bar.git"
    primary_remote_host: str | None         # "gitcode.com"
    default_branch: str | None
    tracked_branches: tuple[str, ...]
    has_git: bool
    trackers: tuple[str, ...]               # 识别的 tracker 适配器
```

实现要点:

- 优先尝试 `extensions/orchestrator/git_sync.py` 已有的 git 操作原语,不直接调 git CLI;
- 若 `extensions/orchestrator/repo_tracker` 包含该仓库则加入 `trackers`;
- fingerprints 缓存到 `<workspace_root>/.clawcodex/lodestone.json` 24h,避免重复扫。

### 1.9 渲染输出形态

#### 纯文本 (sink="text")

`src/file.py:42:13`  →  `src/file.py:42:13` (不变)

下游只用于 audit / log。

#### Markdown (sink="markdown")

```
[src/file.py:42:13](vscode://file/.../src/file.py:42:13)
```

#### OSC 8 (sink="osc8")

```
\x1b]8;;vscode://file/.../src/file.py:42:13\x1b\\src/file.py:42:13\x1b]8;;\x1b\\
```

由 TUI 根据 `TERM`/`TERM_PROGRAM` 在 `renderer="auto"` 时自动探测。

### 1.10 CLI / Tool 行为

#### `/link` 命令族

```
/link parse "src/file.py:42:13"          # 解析为结构化 anchor
/link resolve "src/file.py:42:13"        # 显示可用 target 与选中
/link open <anchor> [--target vscode]    # 调 xdg-open / open(1) / start
/link config editor=cursor
/link config remote=auto
/link status                              # 显示当前 config + 探测到的 env
/link targets list                       # 列出注册 target
/link targets test <id>                  # 用 fixture 验证 template
```

#### `LodestoneTool` actions

| action | 输入 | 输出 |
|--------|------|------|
| `parse` | `text` | anchor 列表 |
| `resolve` | `anchor`, `target_override?` | 选定 target + URL |
| `render` | `text`, `sink?` | 渲染后 string |
| `open` | `anchor`, `target_override?` | 调用系统默认打开器 |
| `config` | `key`, `value` | 持久化 LODESTONE config |

Agent 默认订阅 `parse` 和 `render`,用于把 `cat file.py:42` 输出自动转为 Markdown。

#### 安全与失败边界(合并本节安全 / 失败模式要点)

| 类别 | 规则 / 处理 |
|------|-------------|
| `LODESTONE=off` | parser 仍工作但不渲染,renderer 输出裸文本 |
| 远程 URL | 默认只对已知白名单 host(gitcode.com / github.com / gitee.com / linear.app)渲染 |
| `file://` scheme | TUI/REPL 默认不渲染为 hyperlink(防意外执行),需显式 `target=file` 才渲染 |
| 路径逃逸 | fingerprint + resolver 校验 file_path 必须位于 `workspace_root` 或显式授权白名单内 |
| 模板渲染 | 仅替换占位符 `{abs}` / `{line}` / `{col}` / `{remote}` / `{branch}` / `{rel}`,禁止代码执行 |
| 自定义 target | 注册时校验 `target_id` 冲突、`template` 占位符均为已知 key |
| `LodestoneDisabled` | flag off 时 renderer 输出原文本,Tool 返回 disabled |
| `WorkspaceOutsideFingerprint` | file_path 越界:不渲染 URL,只输出纯文本 + warning |
| `UnknownTarget` | target_id 未注册 → Tool / CLI 列出可用 target |
| `TemplateFormatError` | template 含未知占位符 → 注册时 fail closed |
| `RemoteParseError` | git remote 不规范 → fingerprint fallback 到 `file` target |
| `OpenLaunchError` | xdg-open / `open` / `start` 失败 → 返回错误并提示手动 URL |
| `AnchorParseError` | 行内 token 歧义 → 退化为 raw 文本,不抛 |

### 1.11 验收标准

1. `LODESTONE=off` 时 `/link parse "src/file.py:42:13"` 仍返回结构化 anchor,但 `/link resolve` 输出 fallback 文本;
2. 默认 `LODESTONE=on` 时 Markdown 输出含 `[src/file.py:42](...)` 形式链接,URL scheme 跟随 `default_editor`;
3. 已知 `vscode://` 支持的 terminal (iTerm2/WezTerm/VS Code) 渲染 OSC 8 链接,可在终端点击;
4. 在 GitCode remote 的项目里,`/link open src/file.py:42` 默认选 `gitcode` target,生成 `gitcode.com/{owner}/{repo}/blob/main/src/file.py#L42`;
5. 用户把 `default_editor` 改为 `cursor`,后续所有文件 anchor 走 cursor scheme;
6. 路径逃逸用例(如输入 `../../etc/passwd`) 全部拒绝 URL 化;
7. tracker issue 引用(`#123`、`[ORG-456]`)在配置 GitCode tracker 后渲染为对应 issue URL;
8. 自定义 target(`/link targets register`)能正确替换 `{abs}` `{line}` `{col}`,失败时给位置提示;
9. `template` 包含未知占位符时 `/link targets register` 拒绝并指出错误位置;
10. `file://` scheme 在未显式 `target=file` 时只渲染 raw text,不输出 hyperlink;
11. OSC 8 终端探测仅在 `vscode://` / iTerm2 / WezTerm 启用,其他终端降级为 Markdown;
12. 单元测试覆盖 parser、targets、resolver、renderer、fingerprint、CLI 安全;
13. 关闭功能后再开启不会丢配置,且 fingerprint 缓存复用。

## §2 落地步骤

| 步骤 | 内容 | 涉及子特性 | 工时 |
|:----:|------|:----------:|:----:|
| 1 | 定义 anchor / target / config 数据模型 | P97-A | 1 天 |
| 2 | 实现 `AnchorParser` 识别多种 token | P97-B | 1.5 天 |
| 3 | 实现 `AnchorTargetRegistry` + 内置 target 表 | P97-C | 1 天 |
| 4 | 实现 `AnchorResolver` + 用户偏好 + env 探测 | P97-D | 1.5 天 |
| 5 | 实现 `AnchorRenderer` 三种 sink | P97-E | 1 天 |
| 6 | 实现 workspace fingerprint | P97-F | 1 天 |
| 7 | 增加 `/link` 命令族 + `LodestoneTool` | P97-G | 1 天 |
| 8 | 补齐单元/集成/安全测试 | P97-H | 1.5 天 |

## §3 风险与缓解

| 风险 | 等级 | 缓解 |
|------|:----:|------|
| 不同终端 hyperlink 实现不一致 | 🟠 | OSC 8 自动探测 + 降级到 Markdown/纯文本 |
| 用户编辑器未在 PATH | 🟢 | fallback `file://` |
| 误把非代码 ref 当 anchor(如 `#hash` 出现在 chat) | 🟡 | parser 优先基于上下文(`workspace_root` 内 + 已知扩展名)判定 |
| 远程 URL 渲染暴露内部仓库 | 🟡 | 仅当 workspace 在该 host 才生成远端 URL |
| 自定义 target 注入恶意 URL | 🔴 | template 白名单占位符 + host 白名单 + `--register-force` 需显式确认 |
| fingerprint 影响 git workflow | 🟡 | 只读操作;解析失败时退化为本地 target |

## §4 与其他特性的关系

| 协同 | 说明 |
|------|------|
| **F-92 Skill Search** | skill 描述中的代码引用可被 LODESTONE 链接化 |
| **F-93 TeamMem** | team memory 写入路径 anchor 时,渲染层把 anchor 落库 + link 化 |
| **F-94 BG_SESSIONS** | BG session 完成通知里 transcript 段落自动 LODESTONE 化 |
| **F-89 Proactive** | Proactive tick 自动 open 修复 PR(diff URL)|
| **F-82 Remote Control** | 远程控制面板渲染 LODESTONE 锚点用 Markdown sink |
| **F-88 Monitor** | Monitor 输出包含远程 issue / git commit,可一键跳 |

---

**关联文档**: [README.md 缺口矩阵](./README.md#a-全特性对照矩阵), [F-92 Skill Search](./f-92-skill-search.md), [F-93 Team Memory](./f-93-team-memory.md), [F-94 BG_SESSIONS](./f-94-bg-sessions.md)
