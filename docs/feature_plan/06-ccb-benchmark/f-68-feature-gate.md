# F-68: Feature Gate 运行时特性开关系统

> 状态: 📋 规划中
> 章节: docs/feature_plan/06-ccb-benchmark/f-68-feature-gate.md
> 最后更新: 2026-06-24

## §1 设计规划

### 1.1 目标

对标 CCB Feature Gate（65+ 编译时特性标志），通过运行时装饰器 + 注册表 + JSON/YAML 配置实现等价的特性开关系统，支持热切换。

### 1.2 背景

CCB 通过 Bun 编译期 `-d FEATURE_*` macro define 实现 65+ 编译时特性标志，支持编译级条件编译。Python 无编译宏机制，通过运行时装饰器 + 注册表实现等价能力。

### 1.3 子特性分解

| 编号 | 子特性 | 状态 | 预计工作量 |
|:----:|--------|:----:|:----------:|
| P68-A | FeatureRegistry 核心注册表 | 📋 | 3-5天 |
| P68-B | @feature_gated 装饰器 | 📋 | 2-3天 |
| P68-C | JSON/YAML 配置文件持久化 | 📋 | 1-2天 |
| P68-D | CLI 运行时切换 | 📋 | 1-2天 |
| P68-E | 环境变量覆盖 | 📋 | 1天 |
| P68-F | 依赖性解析与冲突检测 | 📋 | 2-3天 |

### 1.4 架构设计

**包结构**:

```
src/services/feature_gate/
├── __init__.py           # 导出 FeatureRegistry 单例
├── registry.py           # FeatureRegistry 实现
├── decorators.py         # @feature_gated 装饰器
├── config.py             # JSON 配置加载/保存
├── cli.py                # CLI 命令绑定
└── types.py              # FeatureFlag dataclass
```

**FeatureFlag 类型定义**:

```python
@dataclass
class FeatureFlag:
    name: str                           # 唯一标识
    default: bool = False               # 默认启用状态
    deps: list[str] = field(default_factory=list)     # 依赖的特性列表
    mutex_with: list[str] = field(default_factory=list) # 互斥特性列表
    description: str = ""               # 特性说明
```

**FeatureRegistry 实现**:

```python
class FeatureRegistry:
    _features: dict[str, FeatureFlag] = {}
    _overrides: dict[str, bool] = {}

    def register(self, name: str, default: bool = False, ...) -> None:
        if name in self._features:
            raise ValueError(f"Duplicate feature flag: {name}")
        self._features[name] = FeatureFlag(name=name, default=default, ...)

    def is_enabled(self, name: str) -> bool:
        """解析优先级：CLI arg > env var > config file > default"""
        if name in self._overrides:
            return self._overrides[name]
        env_val = os.environ.get(f"CLAWCODEX_FEATURE_{name}")
        if env_val is not None:
            return env_val.lower() in ("1", "true", "yes")
        config_val = self._load_config().get(name)
        if config_val is not None:
            return config_val
        flag = self._features.get(name)
        return flag.default if flag else False

    def check_deps(self, name: str) -> list[str]:
        """检查特性的依赖是否满足，返回缺失的依赖列表。"""
        flag = self._features.get(name)
        if not flag or not flag.deps: return []
        return [dep for dep in flag.deps if not self.is_enabled(dep)]

    def check_mutex(self, name: str) -> list[str]:
        """检查是否与已启用的互斥特性冲突。"""
        flag = self._features.get(name)
        if not flag or not flag.mutex_with: return []
        return [m for m in flag.mutex_with if self.is_enabled(m)]
```

**@feature_gated 装饰器**:

```python
def feature_gated(feature_name: str, fallback=None):
    """条件启用装饰器。"""
    def decorator(obj):
        if not get_registry().is_enabled(feature_name):
            return fallback if fallback is not None else obj
        return obj
    return decorator

def feature_gated_class(name: str, fallback_cls=None):
    """类级别的条件注册辅助函数。"""
    def wrapper(cls):
        registry = get_registry()
        if registry.is_enabled(name):
            missing = registry.check_deps(name)
            if missing: raise RuntimeError(f"Feature '{name}' requires: {missing}")
            conflict = registry.check_mutex(name)
            if conflict: raise RuntimeError(f"Feature '{name}' conflicts with: {conflict}")
            return cls
        return fallback_cls if fallback_cls else cls
    return wrapper
```

### 1.5 集成点

- **CLI 入口**：增加 `--enable` / `--disable` 参数
- **配置持久化**：复用 `~/.clawcodex/` 目录，新增 `features.json`
- **工具注册**：在 `build_default_registry()` 中加入 `feature_gated` 条件注册
- **Agent 循环**：关键决策点查询 `registry.is_enabled()`

### 1.6 依赖

- Python 标准库（`functools` / `inspect` / `os.environ`）
- F-102 Agent Loop Hook 扩展点（前置依赖，pre-LLM 钩子注入点）
- F-70 Plugin 系统（协同）

## §2 进度跟踪

尚未开始。

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
| 2026-06-24 | 补全详细设计（架构+注册表+装饰器+集成点） | 对齐 FEATURE_PLAN.legacy.md |
