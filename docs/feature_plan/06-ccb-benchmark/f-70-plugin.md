# F-70: Plugin 插件系统基础框架

> 状态: ✅ 已完成（P70-A/B/C/D/E 全部落地）
> 章节: docs/feature_plan/06-ccb-benchmark/f-70-plugin.md
> 最后更新: 2026-07-02

## §1 设计规划

### 1.1 目标

对标 CCB Plugin Marketplace 体系，为 clawcodex 提供插件注册、发现、生命周期管理和沙箱隔离能力。

### 1.2 背景

CCB 具备完整的 Plugin Marketplace 体系（安装/卸载/启用/禁用/浏览）。clawcodex 目前所有扩展能力通过硬编码集成或 `clawcodex_ext/` 二开目录实现，缺乏标准化的第三方插件安装与生命周期管理接口。

### 1.3 子特性分解

| 编号 | 子特性 | 状态 | 预计工时 |
|:----:|--------|:----:|:--------:|
| P70-A | BasePlugin 协议接口定义 | ✅ 已完成（`src/plugins/` 13 文件 2,744 行） | 3-5d |
| P70-B | Plugin 发现（entry_points + 目录扫描） | ✅ 已完成（`scan_plugin_directory` 递归 BFS + `discover_all_plugins` 四通道） | 2-3d |
| P70-C | Plugin 生命周期管理（install/uninstall/enable/disable） | ✅ 已完成 | 5-7d |
| P70-D | 子进程沙箱隔离 | ✅ 已完成 | 5-7d |
| P70-E | Plugin 清单格式（plugin.yaml / pyproject.toml 扩展） | ✅ 已完成（`pyproject.toml` → `[tool.clawcodex.plugin]` 表） | 2-3d |

**已落地**: `src/plugins/` 13 文件 2,744 行（`__init__.py` + 12 模块）：注册表/加载器/依赖/校验/市场/LSP 集成/MCP 集成/沙箱/管理器/类型/校验/内置插件等基础框架已存在。配套测试 `tests/plugin/` 12 文件 2,512 行。

### 1.4 BasePlugin 协议

```python
class BasePlugin(ABC):
    name: str = ""; version: str = "0.1.0"; description: str = ""

    @abstractmethod
    async def on_load(self, context: "PluginContext") -> None:
        """插件加载时调用。PluginContext 包含 registry/command_system/config/data_dir。"""

    @abstractmethod
    async def on_unload(self) -> None: ...

    async def on_enable(self) -> None: pass
    async def on_disable(self) -> None: pass

    def get_tools(self) -> list[Any]: return []
    def get_commands(self) -> list[dict]: return []
```

**PluginContext**:
```python
@dataclass
class PluginContext:
    registry: "ToolRegistry"           # 工具注册表
    command_system: "CommandSystem"    # 命令系统
    config: dict[str, Any]             # 插件配置
    data_dir: Path                     # 插件数据持久化目录
```

### 1.5 Plugin 示例

```python
class TodoPlugin(BasePlugin):
    name = "todo-manager"; version = "1.0.0"; description = "Manage todo lists"

    async def on_load(self, ctx: PluginContext):
        self.data_file = ctx.data_dir / "todos.json"

    def get_tools(self):
        return [build_tool(name="todo_add", input_schema={...}, call=self._add_todo, ...)]

    def get_commands(self):
        return [{"name": "todo", "handler": self._cmd_todo, "description": "Manage todos"}]
```

### 1.6 架构

```
src/plugins/  (13 文件)
├── __init__.py          # 公共导出
├── base.py              # BasePlugin + PluginContext（协议类）
├── registry.py          # PluginRegistry（注册/发现/生命周期管理）
├── loader.py            # PluginLoader（importlib + entry_points + 目录扫描发现，582 行）
├── sandbox.py           # PluginSandbox（可选子进程隔离，网络/操作白名单）
├── manager.py           # PluginManager（CLI 命令绑定 + 生命周期协调，450 行）
├── schema.py            # PluginManifestSchema（pydantic model / dataclass fallback）
├── types.py             # PluginManifest / LoadedPlugin / PluginError 数据类
├── validator.py         # 清单字段校验（名称/版本/权限/依赖/hooks/mcp_servers）
├── dependency.py        # 插件依赖解析
├── builtin_plugins.py   # 内置插件定义
├── marketplace.py       # Marketplace 远程仓库接口
├── lsp_integration.py   # LSP 协议集成
└── mcp_integration.py   # MCP 服务器集成
```

### 1.7 插件发现路径

插件发现支持三种来源，由 `discover_all_plugins()` 统一调度四通道：

```python
# 1. Python entry_points (pip 安装的包，group="clawcodex.plugins")
plugins = entry_points(group="clawcodex.plugins")

# 2. 用户目录手动安装
~/.clawcodex/plugins/my-plugin/plugin.yaml (或 plugin.json / pyproject.toml)

# 3. 项目级插件
.clawcodex/plugins/...

# 4. 额外目录 (通过 extra_dirs 参数传入)
```
清单文件名优先级（先匹配者获胜）：`plugin.yaml` > `plugin.yml` > `plugin.json` > `pyproject.toml`。

### 1.8 依赖

- `importlib.metadata`（Python 3.8+ 标准库，entry_points 发现）
- `PyYAML`（yaml 配置解析，已有依赖）
- `tomllib`（Python 3.11+ 标准库，pyproject.toml 解析；P70-E）
- F-102 Agent Loop Hook 扩展点（前置依赖，P102-D formal registry）

## §2 进度跟踪

### 2.1 已完成

| 日期 | 里程碑 | 涉及文件 |
|------|--------|---------|
| 2026-06 | 注册表/加载器/依赖/校验基础 | `src/plugins/` 初始 8 文件 1,070 行 |
| 2026-06-27 | P70-C 生命周期管理 + P70-D 子进程沙箱隔离实现 | `src/plugins/{loader,manager,sandbox}.py` (+103/+178/+91/-34) |
| 2026-06-27 | Plugin 生命周期 + Manager 单元测试（792 行） | `tests/plugin/test_plugin_lifecycle_extended.py` (435) + `test_plugin_manager.py` (357) |
| 2026-06-27 | 修复 sandbox 权限检查顺序 + lifecycle 测试 None 守卫（3 个失败用例） | `src/plugins/sandbox.py` + `tests/plugin/test_plugin_lifecycle_extended.py` |
| 2026-06-28 | PR #35 `!35 merge clawcodex/f-70-plugin into dev-decoupling-refactor-0573f4c` 合并入 base | merge commit `282da02b` |

### 2.2 关键能力

- **生命周期钩子**：`on_load` / `on_unload` / `on_enable` / `on_disable` 全部实现并经单元测试覆盖
- **沙箱隔离**：`PluginSandbox.execute_in_sandbox()` 支持网络限制、操作类别白名单、subprocess 隔离；权限检查顺序修正后错误信息更精准（"Network access is disabled" 优先于 "Permission denied"）
- **PluginManager**：统一 CLI 命令绑定 + 生命周期协调（`src/plugins/manager.py` 450 行）
- **PluginLoader**：importlib + entry_points + 目录扫描扫描四通道发现 + 生命周期事件回调（`src/plugins/loader.py` 582 行）
- **清单格式**（P70-E）：支持 `plugin.yaml` / `plugin.yml` / `plugin.json` / `pyproject.toml` 四种清单文件；`pyproject.toml` 从 `[tool.clawcodex.plugin]` 表提取，兼容 camelCase 和 snake_case 字段命名；Python ≥3.11 使用标准库 `tomllib` 解析

### 2.3 下一步计划

P70-A/B/C/D/E 全部落地，F-70 子特性分解表无剩余项。后续可选增强方向（非 F-70 范围）：

1. **插件签名校验** — Marketplace 分发的插件包增加签名/校验机制（依赖 F-71 Marketplace 上线后再评估）
2. **热重载** — `on_disable`/`on_enable` 之外的 `on_reload` 钩子，支持运行时无重启更新插件
3. **依赖隔离** — 子进程沙箱中为每个插件创建独立 venv（当前 P70-D 沙箱仅做权限白名单隔离）

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
| 2026-06-24 | 补全详细设计（协议+架构+发现路径） | 对齐 FEATURE_PLAN.legacy.md |
| 2026-06-27 | 落地 P70-C 生命周期 + P70-D 沙箱隔离（PR #35 工作） | `2b3c1258 feat(plugins): P70-C lifecycle management + P70-D sandbox isolation` |
| 2026-06-27 | 修复 3 个 sandbox 权限检查 + lifecycle 测试失败用例 | `d3bdde5d fix(plugins): sandbox permission check ordering + lifecycle test compatibility` |
| 2026-06-28 | PR #35 merge commit `282da02b` 合入 base，标记 P70-C/D 完成 | `!35 merge clawcodex/f-70-plugin into dev-decoupling-refactor-0573f4c` |
| 2026-06-28 | 更新文档状态为已完成 + 补全进度跟踪表 | 同步实现状态 |
| 2026-07-02 | 落地 P70-E pyproject.toml 清单格式扩展 | `src/plugins/loader.py` +59 行（`_read_pyproject_manifest` / `MANIFEST_FILES` 加入 `pyproject.toml` / snake_case 兼容） |
| 2026-07-02 | 新增 P70-E pyproject.toml 清单格式单元测试（14 用例） | `tests/plugin/test_plugin_pyproject_manifest.py` (200 行) |
| 2026-07-02 | 更新文档全部章节同步代码实际状态 | 修复 §1.6 架构/§1.7 发现路径/§1.8 依赖/§2.2 关键能力/§2.1 已完成数据 13 文件 2,744 行 |

