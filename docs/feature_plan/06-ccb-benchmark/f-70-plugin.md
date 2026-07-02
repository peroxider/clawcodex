# F-70: Plugin 插件系统基础框架

> 状态: 🔄 进行中（P70-A/C/D 已完成；P70-B 插件发现目录扫描、P70-E 清单格式待补全）
> 章节: docs/feature_plan/06-ccb-benchmark/f-70-plugin.md
> 最后更新: 2026-06-28

## §1 设计规划

### 1.1 目标

对标 CCB Plugin Marketplace 体系，为 clawcodex 提供插件注册、发现、生命周期管理和沙箱隔离能力。

### 1.2 背景

CCB 具备完整的 Plugin Marketplace 体系（安装/卸载/启用/禁用/浏览）。clawcodex 目前所有扩展能力通过硬编码集成或 `clawcodex_ext/` 二开目录实现，缺乏标准化的第三方插件安装与生命周期管理接口。

### 1.3 子特性分解

| 编号 | 子特性 | 状态 | 预计工时 |
|:----:|--------|:----:|:--------:|
| P70-A | BasePlugin 协议接口定义 | ✅ 已完成（`src/plugins/` 8 文件 1,070 行） | 3-5d |
| P70-B | Plugin 发现（entry_points + 目录扫描） | 🔄 部分完成 | 2-3d |
| P70-C | Plugin 生命周期管理（install/uninstall/enable/disable） | ✅ 已完成 | 5-7d |
| P70-D | 子进程沙箱隔离 | ✅ 已完成 | 5-7d |
| P70-E | Plugin 清单格式（plugin.yaml / pyproject.toml 扩展） | 🔄 部分完成 | 2-3d |

**已落地**: `src/plugins/` 8 文件 1,070 行：注册表/加载器/依赖/校验/市场/LSP 集成/MCP 集成等基础框架已存在。

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
plugin_system/
├── base.py              # BasePlugin + PluginContext（协议类）
├── registry.py          # PluginRegistry（注册/发现/生命周期管理）
├── loader.py            # PluginLoader（importlib + entry_points 发现）
├── sandbox.py           # PluginSandbox（可选子进程隔离）
├── manager.py           # PluginManager（CLI 命令绑定）
└── schema.py            # PluginManifest（pydantic model 插件元数据）
```

### 1.7 插件发现路径

```python
# 1. Python entry_points (pip 安装的包)
plugins = entry_points(group="clawcodex.plugins")

# 2. 用户目录手动安装
~/.clawcodex/plugins/my-plugin/plugin.yaml + __init__.py

# 3. 项目级插件
.clawcodex/plugins/...
```

### 1.8 依赖

- `importlib.metadata`（Python 3.8+ 标准库）
- `PyYAML`（yaml 配置解析，已有依赖）
- F-102 Agent Loop Hook 扩展点（前置依赖，P102-D formal registry）

## §2 进度跟踪

### 2.1 已完成

| 日期 | 里程碑 | 涉及文件 |
|------|--------|---------|
| 2026-06 | 注册表/加载器/依赖/校验基础 | `src/plugins/` 8 文件 1,070 行 |
| 2026-06-27 | P70-C 生命周期管理 + P70-D 子进程沙箱隔离实现 | `src/plugins/{loader,manager,sandbox}.py` (+103/+178/+91/-34) |
| 2026-06-27 | Plugin 生命周期 + Manager 单元测试（792 行） | `tests/plugin/test_plugin_lifecycle_extended.py` (435) + `test_plugin_manager.py` (357) |
| 2026-06-27 | 修复 sandbox 权限检查顺序 + lifecycle 测试 None 守卫（3 个失败用例） | `src/plugins/sandbox.py` + `tests/plugin/test_plugin_lifecycle_extended.py` |
| 2026-06-28 | PR #35 `!35 merge clawcodex/f-70-plugin into dev-decoupling-refactor-0573f4c` 合并入 base | merge commit `282da02b` |

### 2.2 关键能力

- **生命周期钩子**：`on_load` / `on_unload` / `on_enable` / `on_disable` 全部实现并经单元测试覆盖
- **沙箱隔离**：`PluginSandbox.execute_in_sandbox()` 支持网络限制、操作类别白名单、subprocess 隔离；权限检查顺序修正后错误信息更精准（"Network access is disabled" 优先于 "Permission denied"）
- **PluginManager**：统一 CLI 命令绑定 + 生命周期协调（`src/plugins/manager.py` 450 行）
- **PluginLoader**：importlib + entry_points 双通道发现（`src/plugins/loader.py` 536 行）

### 2.3 下一步计划

1. P70-B Plugin 发现（目录扫描）补全
2. P70-E Plugin 清单格式（plugin.yaml / pyproject.toml 扩展）补全

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
| 2026-06-24 | 补全详细设计（协议+架构+发现路径） | 对齐 FEATURE_PLAN.legacy.md |
| 2026-06-27 | 落地 P70-C 生命周期 + P70-D 沙箱隔离（PR #35 工作） | `2b3c1258 feat(plugins): P70-C lifecycle management + P70-D sandbox isolation` |
| 2026-06-27 | 修复 3 个 sandbox 权限检查 + lifecycle 测试失败用例 | `d3bdde5d fix(plugins): sandbox permission check ordering + lifecycle test compatibility` |
| 2026-06-28 | PR #35 merge commit `282da02b` 合入 base，标记 P70-C/D 完成 | `!35 merge clawcodex/f-70-plugin into dev-decoupling-refactor-0573f4c` |
| 2026-06-28 | 更新文档状态为已完成 + 补全进度跟踪表 | 同步实现状态 |
