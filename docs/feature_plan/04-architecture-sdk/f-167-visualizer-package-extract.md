# F-167 Visualizer 独立包化（商业化脱离）

> **状态**: ✅ 已落地（2026-07-23；F-167-A~G 全部实现）
> **领域**: 04-architecture-sdk（Decoupling / Commercialization）
> **最后更新**: 2026-07-23
> **关联 Feature**: F-156 Asciicast v2 录制器、F-94 Session Visualizer、F-120 Agent Dashboard
> **上游依据**: `docs/COMMERCIALIZATION_EXECUTIVE_SUMMARY.md` §4.2.2 / `docs/COMMERCIALIZATION_PLAN.md` §4

---

## §1 验收结论与问题定义

### 1.1 商业化层面的诊断

`COMMERCIALIZATION_EXECUTIVE_SUMMARY.md` §4.2.2 把 visualizer 列为 **低成本脱离** 模块：

> 依赖链条：`visualizer → capabilities.dashboard_entry/recorder → recording.renderers`  
> `capabilities` 是纯 Protocol 定义（无实现），`recording.renderers` 是渲染工具函数。

文档估算工作量 **~500-800 行**，但此估算假设所有剥离点是均匀的。本规划的关键洞察是：

1. **21/25 文件零硬二层依赖** — `ws.py` / `parsers/*` / `builders/*` / `models/*` / `orchestrator_link.py` / `import_router.py` / `fixtures/__init__.py` / `templates/` / `static/` 等全部只依赖 `fastapi` / `pydantic` / 标准库 / 内部 `.*` 相对引用，**无任何二层硬耦合**。
2. **硬二层耦合仅 1 个文件** — `asciicast_dashboard_source.py` 对 `extensions.capabilities` / `extensions.recording.renderers` 有 3 处真实 import，且都是**最弱形态**（Protocol / dataclass / 14 行纯函数）。
3. **入口/可选注册触及 3 个文件** — `cli.py` 装饰器（`clawcodex_ext.cli.subcommand_registry`）、`__init__.py` 反向注册（`extensions.agent_dashboard.register_dashboard_source`）、`server.py` 可选注入（`extensions.agent_dashboard.get_default_store`，已 try/except 包裹）— 这三处不是协议耦合，而是入口挂载点，F-167 通过 entry-points / try-import 改造脱钩。
4. **asciicast 适配器反向归属错位** — `extensions/visualizer/asciicast_dashboard_source.py` 实际是被 `extensions/recording/_factories.py:_visualizer_factory` 在录制时反向调用，用来把 dashboard 渲染成 ascii 帧。这段代码**应当归 recording 包**，不属于 visualizer 包本体。

因此真正工作量的分布不是均匀的：

| 工作块 | 估算 | 性质 |
|---|---|---|
| Protocol inline（dashboard_entry + recorder） | ~300 行 | 拷贝 + 命名空间收口 |
| `panel` 函数内联 | ~25 行 | 拷贝 |
| `asciicast_dashboard_source` 归位 recording | ~200 行 | 文件迁移 + 反向注册改写 |
| `cli.py` 入口脱钩（`register` 装饰器） | ~50 行 | 注册模式替换为可选插件入口 |
| `__init__.py` 反向注册（约 `register_dashboard_source`）改为可选 | ~50 行 | 同上 |
| `pyproject.toml` / `setup.py` / 入口点声明 | ~150 行 | 包元数据 |
| 测试拆分（visualizer 测试可独立跑） | ~150 行 | `tests/visualizer/` → `tests/`（独立仓库） |
| **合计** | **~925 行** | 比原始估 ~500-800 行略高 |

### 1.2 子特性分解

| 子特性 | 内容 | 工作量 | 优先级 |
|---|---|---|---|
| F-167-A | DashboardEntry/Source/Sink Protocol 内联 | ~300 行 | P0 |
| F-167-B | AsciicastCapture/Event/Header Protocol + RecordableSource 内联 | ~200 行（含于 A） | P0 |
| F-167-C | `panel()` 纯函数内联（脱 recording.renderers） | ~25 行 | P0 |
| F-167-D | `asciicast_dashboard_source.py` 归位 `extensions/recording/` | ~200 行（含测试改写） | P0 |
| F-167-E | visualizer 包独立 `pyproject.toml` + 入口点 | ~150 行 | P0 |
| F-167-F | `cli.py` 改为可选插件入口（脱 `clawcodex_ext.cli.subcommand_registry`） | ~50 行 | P1 |
| F-167-G | `__init__.py` 反向注册改为可选（脱 `agent_dashboard.register_dashboard_source`） | ~50 行 | P1 |

---

## §2 目标与非目标

### 2.1 目标

| 目标 | 验收 |
|---|---|
| Protocol 自给 | `visualizer` 包内含完整的 `DashboardEntry` / `DashboardSource` / `DashboardSink` / `AsciicastCapture` / `AsciicastEvent` 定义，独立运行不依赖 `extensions.capabilities` |
| 渲染内联 | `panel()` 函数进入 `visualizer/_rendering.py`（或直连 `asciicast_dashboard_source.py`），不依赖 `extensions.recording.renderers` |
| 录制器归位 | asciicast dashboard 适配器归 `extensions/recording/visualizer_dashboard_source.py`，由 recording factory 直接构造 |
| 入口可选 | `clawcodex viz` 命令通过**插件入口**注册；当 user 未安装 `clawcodex-visualizer` 时 CLI 不报错 |
| 包独立 | `pyproject.toml` 含 `[project.scripts] clawcodex-visualizer = "clawcodex_visualizer.cli:main"` 入口，独立 `pip install` 可工作 |
| 零回归 | `tests/visualizer/` 全部 ~30 测试用例在原始仓库 / 独立包两种形态下保持 PASS |
| 文档同步 | `docs/COMMERCIALIZATION_EXECUTIVE_SUMMARY.md` §4.2.2 把工作量改成「✅ 已落地」并链接本 F-167 |

### 2.2 非目标

- ❌ 不重写 `ws.py` / `parsers/` / `builders/` / `models/`（21/25 文件已零二层依赖，无需触碰）
- ❌ 不修改 `orchestrator_link.py`（只依赖标准库 + 内部 `.*`）
- ❌ 不触碰 `server.py` 中 `get_default_store()` 的 try/except 逻辑（B 组耦合，与独立包化无关）
- ❌ 不分离 templates / static 资源（继续随包发布）
- ❌ 不立即改 `extensions/recording/` 自身的 Capability 输出（仍是 Protocol hub，本包复制局部）
- ❌ 不引入新的可视化框架（保持 fastapi + jinja2）
- ❌ 不解决 `server.py:get_default_store()` 那一行可选依赖（保留 try/except 现有处理，与独立包化无关）
- ❌ 不拆分 `extensions/visualizer` → `clawcodex-visualizer/<原文件名>.py` 全量扁平化（保留子包结构以最小化 diff）

---

## §3 当前依赖全景（实测验证）

### 3.1 自动化扫描结论

对 `extensions/visualizer/` 下全部 25 个 Python 文件做 `from`/`import` 全量扫描。按耦合性质分两组：

**A. 硬二层协议耦合（capabilities / recording.renderers / agent_dashboard 注册协议）— 1 文件**

| 文件 | 引用的外部模块 | 类型 | 行数 |
|---|---|---|---|
| `asciicast_dashboard_source.py` | `extensions.capabilities.dashboard_entry` (`DASHBOARD_STATUSES`, `DashboardEntry`, `DashboardSource`, `normalize_source_name`) | Protocol + dataclass + 辅助函数 | 6 处 import |
| `asciicast_dashboard_source.py` | `extensions.capabilities.recorder` (`AsciicastCapture`, `AsciicastEvent`) | Protocol + dataclass | 2 处 import |
| `asciicast_dashboard_source.py` | `extensions.recording.renderers.panel` | 纯函数（14 行） | 1 处 import |

**B. 入口/可选挂载点（registry / 反向注册 / try-import）— 3 文件**

| 文件 | 引用的外部模块 | 类型 | 行数 | 备注 |
|---|---|---|---|---|
| `cli.py` | `clawcodex_ext.cli.subcommand_registry.register` | 注册装饰器（仅 1 行调用） | 1 处 import | F-167-F 改 entry-points |
| `__init__.py` | `extensions.agent_dashboard.register_dashboard_source` | 反向注册（try/except） | 1 处 import | F-167-G 改 entry-points |
| `server.py` | `extensions.agent_dashboard.get_default_store` | 可选注入（已有 try/except） | 1 处 import | 保留现有 try/except，与独立包化无关 |

注：B 组耦合**不是协议耦合**，是入口挂载点，独立包化通过 entry-points 与 dynamic import 即可脱钩，不需拷贝任何代码。

### 3.2 零外部二层依赖文件清单（21/25）

```
extensions/visualizer/
├── ws.py                  ← fastapi + 标准库
├── orchestrator_link.py   ← 标准库 + urllib.parse
├── import_router.py       ← fastapi + pydantic + httpx + 标准库
├── builders/
│   ├── agent_tree_builder.py
│   ├── agent_tree_layout.py
│   ├── anomaly_builder.py
│   ├── export_builder.py          ← PIL + reportlab（已声明为可选依赖）
│   ├── operation_categorizer.py
│   ├── stats_builder.py
│   └── timeline_builder.py
├── models/viz_models.py           ← pydantic
├── parsers/                       ← 7 个文件全标准库 + dataclass
├── templates/                     ← Jinja2 模板
├── static/                        ← 前端静态资源
└── fixtures/__init__.py           ← 标准库
```

**这 21 个文件没有任何二层 import，可立刻零修改搬迁到独立包**，无需任何额外工作。`server.py` 因 B 组有 1 行 `get_default_store()` 注入也被列入本组（该行是 try/except 包裹的可选依赖，不属于耦合）。

### 3.3 反向依赖（visualizer 被谁调用）

| 调用方 | 调用内容 | 备注 |
|---|---|---|
| `clawcodex_ext.cli.subcommand_registry.register_viz_subcommand` | 装饰器一次性注册 | 1 行；脱钩后改 entry_points |
| `extensions.recording._factories._visualizer_factory` | 构造 `AsciicastDashboardSource` | 反向；F-167-D 改为 recording 自包含 |
| `extensions.recording.examples.logical_kanban_repl_demo` | 同上 | 用作 demo；改为 recording 内置或可选 |

注：**F-156 Asciicast v2 录制器的最新落地**已经把 visualizer 适配器纳入 recording 体系；这意味着 F-167-D 实质上把当前已经"半归属 recording"的代码完成"全归属"，与 F-156 后续维护方向一致。

---

## §4 解耦分层方案

### 4.1 内联策略（最小化 Protocol 复制）

**F-167-A/B：DashboardEntry/Source/Sink + Asciicast* Protocol 内联**

不要在 visualizer 包内部"重新发明"协议 — 直接从 `extensions/capabilities/dashboard_entry.py` 和 `extensions/capabilities/recorder.py` 拷贝 ~222 行 + ~155 行 到 `clawcodex_visualizer/protocols/dashboard.py` 与 `clawcodex_visualizer/protocols/recorder.py`。

**不引入 vendor automation**（避免依赖管理恶化）：这两份 Protocol 长期稳定，F-156 录制器上线后 F-94/F-120 都未对它们做实质性修改。手工同步成本可接受（每 6 个月对照一次）。

**顶层 `clawcodex_visualizer.protocols.__init__` 暴露两套名字**：

```python
from clawcodex_visualizer.protocols.dashboard import (
    DashboardEntry, DashboardSource, DashboardSink,
    DASHBOARD_STATUSES, normalize_source_name, filter_entries,
)
from clawcodex_visualizer.protocols.recorder import (
    AsciicastCapture, AsciicastEvent, AsciicastHeader, RecordableSource,
)
```

下游使用方按需 import（例如 recording 的 `_visualizer_factory` 改为 `from clawcodex_visualizer.protocols.recorder import AsciicastCapture`）。

### 4.2 panel 函数内联（F-167-C）

`extensions/recording/renderers.py:78-91` 的 `panel()` 函数只有 14 行：

```python
def panel(title: str, rows: list[str], width: int = 80) -> str:
    rule = "─" * max(width, len(title) + 4)
    out = [rule, f"  {title}", rule]
    for row in rows:
        out.append(row)
    out.append(rule)
    return "\n".join(out)
```

直接拷贝到 `clawcodex_visualizer._rendering.panel`（private，标记为 not-part-of-public-api）。`asciicast_dashboard_source.py` 改 import 路径。

**recording/renderers.py 同步去除 `panel()`**（保留 `format_phase_marker` 等其它函数）。

### 4.3 反向依赖归位（F-167-D）

`extensions/visualizer/asciicast_dashboard_source.py`（~158 行）整文件迁移到 `extensions/recording/visualizer_dashboard_source.py`，路径修正：

```diff
-from extensions.capabilities.dashboard_entry import (...)
-from extensions.capabilities.recorder import (AsciicastCapture, AsciicastEvent)
-from extensions.recording.renderers import panel
+from clawcodex_visualizer.protocols.dashboard import (...)
+from clawcodex_visualizer.protocols.recorder import (AsciicastCapture, AsciicastEvent)
+from clawcodex_visualizer._rendering import panel
```

`extensions/visualizer/__init__.py` 的反向注册模块被删除（或保持 no-op），`_visualizer_factory` 改：

```python
try:
    from extensions.recording.visualizer_dashboard_source import AsciicastDashboardSource
    ADAPTER_CLS = AsciicastDashboardSource
except ImportError:
    class _StubAdapter: ...
    ADAPTER_CLS = _StubAdapter
```

### 4.4 入口脱钩（F-167-F）

把 `clawcodex_ext.cli.subcommand_registry.register` 替换为 **Python entry points**：

```toml
# clawcodex-visualizer/pyproject.toml
[project.entry-points."clawcodex.commands"]
viz = "clawcodex_visualizer.cli:register_viz_subcommand"
```

`clawcodex_ext.cli` 端做 entry-points 发现（已经具备部分插件机制，按既有约定扩展）。这样：

- `pip install clawcodex-visualizer` 后 `clawcodex viz` 自动可用
- 未安装时 CLI 不报错、不出现孤儿命令
- 入口与具体注册中心解耦，与 setuptools/pip 标准插件机制一致

### 4.5 可选反向注册脱钩（F-167-G）

`extensions/visualizer/__init__.py` 当前 `try: register_dashboard_source(...)` 反向注册到 `extensions.agent_dashboard`。在独立包场景下：

- 改由调用方在 `clawcodex_dev.init` 中显式 import 完成注册
- 或保留 try/except + import warning，行为不变

**保守路线**：保留 try/except，仅去掉对 `extensions.agent_dashboard` 模块路径的硬编码，改用 entry-points 动态发现。

---

## §5 目标包结构

```
clawcodex-visualizer/
├── pyproject.toml                    # 包元数据 + entry-points
├── README.md
├── src/
│   └── clawcodex_visualizer/
│       ├── __init__.py
│       ├── server.py                 # 原 extensions/visualizer/server.py
│       ├── ws.py                     # 原 extensions/visualizer/ws.py
│       ├── orchestrator_link.py      # 原 extensions/visualizer/orchestrator_link.py
│       ├── import_router.py          # 原 extensions/visualizer/import_router.py
│       ├── cli.py                    # 适配 entry-points
│       ├── protocols/
│       │   ├── __init__.py
│       │   ├── dashboard.py          # 从 extensions/capabilities/dashboard_entry.py 拷贝
│       │   └── recorder.py           # 从 extensions/capabilities/recorder.py 拷贝
│       ├── _rendering.py             # panel() 渲染函数
│       ├── builders/                 # 原 extensions/visualizer/builders/*
│       ├── models/                   # 原 extensions/visualizer/models/*
│       ├── parsers/                  # 原 extensions/visualizer/parsers/*
│       └── templates/                # 原 templates/*
│           static/                  # 原 static/*
└── tests/
    ├── test_server.py
    ├── test_ws.py
    ├── test_parsers.py
    ├── test_dashboard_routes.py
    └── test_visualizer_source.py
```

独立仓库模式，依赖：

```toml
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "pydantic>=2.6",
    "httpx>=0.27",       # 仅 import_router
    "jinja2>=3.1",
    "Pillow>=10",        # builders/export_builder.py
    "reportlab>=4",      # builders/export_builder.py
]
```

注：不依赖 `clawcodex_ext`、不依赖 `extensions.capabilities`、不依赖 `extensions.recording`、不依赖 `src/`。

---

## §6 工作量估算

| 项 | 内容 | 行数 | 备注 |
|---|---|---|---|
| F-167-A | Protocol + dataclass 内联（dashboard） | ~300 行（含 __post_init__ 等校验） | 拷贝为主 |
| F-167-B | Protocol + dataclass 内联（recorder） | ~200 行（含 docstring） | 拷贝为主 |
| F-167-C | `panel()` 内联 + import 改写 | ~25 行 | 14 行 panel + 调用方 1 行改 path |
| F-167-D | `asciicast_dashboard_source.py` 归位 recording | ~200 行 | 文件迁移 + factory 改 1 处 + `__init__.py` 去 import |
| F-167-E | `pyproject.toml` + entry-points + README | ~150 行 | 标准 |
| F-167-F | `cli.py` 脱 `subcommand_registry` | ~50 行 | entry-points + `try/except` 兜底 |
| F-167-G | `__init__.py` 反向注册改可选 | ~50 行 | entry-points 发现 |
| 测试拆分 | `tests/visualizer/` → 独立 `tests/` | ~150 行 | conftest + 路径修正 |
| **合计** | | **~1125 行** | 比 COMMERCIALIZATION_PLAN.md §4.2.2 估算的 500-800 行高 ~40%，因细化了 Protocol 拷贝 + entry-points + 测试拆分成本 |

按 dev-rate 1500 行/天（参考 F-156 Asciicast 录制器 5 子系统零 src/ 改动的落地节奏），单人 ~1 个工作日落地。

---

## §7 验收标准

| # | 验收项 | 通过条件 |
|---|---|---|
| AC-1 | visualizer 独立 `pip install -e .` | 6 个 deps 装好后 `clawcodex-visualizer --help` 正常输出 |
| AC-2 | 独立 `python -m clawcodex_visualizer.cli run_viz --port 8765` | 服务启动、浏览器访问 `/` 渲染 dashboard |
| AC-3 | 协议自给 | `python -c "from clawcodex_visualizer.protocols import DashboardSource, AsciicastCapture"` 不依赖 `extensions.*` |
| AC-4 | recording 适配器归位 | `from extensions.recording.visualizer_dashboard_source import AsciicastDashboardSource` 成功，`extensions.visualizer.asciicast_dashboard_source` 不存在 |
| AC-5 | CLI 入口脱钩（未装 visualizer 包时） | `clawcodex dev orchestrator` 等命令启动正常，无 `viz` 子命令 |
| AC-6 | CLI 入口正常（装上 visualizer 包时） | `clawcodex viz` 注册成功，与原 `register_viz_subcommand` 行为一致 |
| AC-7 | 测试套件绿 | `pytest tests/` 全部测试（`tests/visualizer/*` 与 `tests/extensions/recording/test_visualizer_source.py`）PASS |
| AC-8 | 稳定性门禁 | `python -m pytest tests/stability_gate/ -q` 全部 Stage 1-5/7-9 绿 |
| AC-9 | CI 兼容 | `.github/workflows/ci.yml` 三 job（lint / test-gate / audit）绿 |
| AC-10 | docs 同步 | `COMMERCIALIZATION_EXECUTIVE_SUMMARY.md` §4.2.2 工作量更新为「✅ F-167-A~G 已落地」+ 本 F-167 链接 |

---

## §8 风险与约束

| 风险 | 触发条件 | 缓解 |
|---|---|---|
| R-1 Protocol 漂移 | 上游 `extensions/capabilities/dashboard_entry.py` 修改字段或语义 | 6 个月一次 manual diff；critical 字段加 deprecation 通知；`extensions.agent_dashboard` 仍以原 Protocol 为唯一权威，visualizer 包的 Protocol 标 `_local_copy` 警告 |
| R-2 入口插件冲突 | 用户同时安装 `clawcodex-visualizer` 和旧 `clawcodex_ext.cli` 子命令注册 | entry-points 优先级明确高于 runtime registry；旧注册保留作为 fallback |
| R-3 模板/静态资源路径 | 独立包运行时 `templates/` 找不到（错误的 `__file__` 解析） | server.py 使用 `importlib.resources` 而不是 `__file__.parent`，避免 zipapp / py2exe 失败 |
| R-4 recording 重构竞争 | F-156 Asciicast 录制器仍在迭代中（`_visualizer_factory` 签名变化） | F-167-D 落地与 F-156 当前 stable 版对齐，附加 import-time 版本检查 |
| R-5 测试 fixture 路径硬编码 | `tests/visualizer/*` 中含 `pathlib.Path("extensions/visualizer/...")` | 测试拆分前先 grep 替换为 `pathlib.importlib.resources` |
| R-6 pyproject 体积 | `recording` 也内联了部分 Protocol，`extensions/recording` → `clawcodex-recording` 独立化会出现双份 Protocol | F-167 不主动推动 `clawcodex-recording` 独立；保留双份不冲突 |

---

## §9 已拟定的设计决定

1. **不抽 Protocol hub** — 与 F-167 同期的 `decoupling/` 目录已声明解耦方案独立成新包，但 visualizer 的 Protocol 数量仅 ~400 行，单独建 `clawcodex-protocols` 包的边际收益低。等 orchestrator / sop_converter 独立化完成（按 COMMERCIALIZATION_PLAN.md §4.2.4-5 工作量 5K-8K 行）后再统一建 hub。
2. **保留子包结构** — `builders/` `parsers/` `models/` 不扁平化为 `clawcodex_visualizer.builders.*` 同名。原因是文件命名已包含功能子域，扁平化会引入 50+ 处文件改名 + 测试 import 改动，收益极小。
3. **`panel()` 标记 private** — 用 `_rendering.py` 下划线前缀 + 不进 `__all__`；下游用户不应依赖此函数。
4. **`asciicast_dashboard_source` 移到 recording 而非 visualizer** — 因为它的实际使用者是 `extensions.recording._factories._visualizer_factory`，visualizer 包的 Web UI 走自己的 HTML 渲染，根本不调用它。
5. **entry-points 优先于 registry** — 与 LSB / setuptools 标准生态一致；`clawcodex_ext.cli.subcommand_registry` 保留但标注 deprecation。
6. **`pyproject.toml` 不带 CLI bin script** — 避免与上游 `clawcodex-dev` CLI 冲突；仅暴露 `clawcodex_visualizer.cli:register_viz_subcommand` 作为 entry-point target，由上游 `clawcodex_dev` 动态加载。

---

## §10 落地路线（推荐）

按子特性依赖顺序：

```
F-167-C (panel 内联, 25 行)
   ↓
F-167-A/B (Protocol 内联, ~500 行)
   ↓
F-167-D (asciicast_dashboard_source 归位, ~200 行)
   ↓
F-167-E (pyproject + entry-points, ~150 行)
   ↓
F-167-F (cli 入口脱钩, ~50 行)
   ↓
F-167-G (反向注册改可选, ~50 行)
   ↓
测试拆分与 CI 验证
```

每一步均可在 `git log` 中独立提交，每步通过 `pytest tests/stability_gate/ -q` 验证不回归。

---

## §11 与商业化文档的回写计划

F-167 全部落地后，回写 `docs/COMMERCIALIZATION_EXECUTIVE_SUMMARY.md` §4.2.2：

```diff
-**工作量**：~500-800 行（Protocol 内联、渲染函数内联、DashboardSink 抽象）
+**工作量**：~1125 行（详见 F-167），F-167-A~G 已全部落地
```

并在 `docs/feature_plan/README.md` 的「Recording / 可观测性增强」或新增「商业化独立化」章节登记 F-167。

`docs/COMMERCIALIZATION_PLAN.md` §4.5 决策表注脚加：

> visualizer、orchestrator、sop_converter 三者均推荐走"独立 PyPI 包"路径，
> 详见 F-167（visualizer 已落地）、F-168（orchestrator 规划中）、F-169（sop_converter 规划中）。
