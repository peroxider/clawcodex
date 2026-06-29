# `clawcodex_ext.*` Facade 模式

> 状态: ✅ 已完成
> 章节: docs/decoupling/facade-patterns.md
> 最后更新: 2026-06-29

## §1 背景

`clawcodex_ext.*`（Layer 1）的 facade 模块是从 Layer 0（`src/`）到 Layer 2（`extensions/`）的层间桥。P3 整改中创建了 8 个新 facade，本文档整理三类典型模式与选型指南。

## §2 三类 Facade 模式

### 2.1 模式 A：`from X import *` 直接 re-export（推荐）

**形式**:
```python
"""Compatibility facade — see :mod:`src.X.Y`."""
from src.X.Y import *  # noqa: F401,F403
```

**特点**:
- 2-3 行 module，无需额外维护
- 任何 `from src.X.Y import Z` 调用方改为 `from clawcodex_ext.X.Y import Z` 后，行为完全一致（同一对象，sys.modules 命中后 `is` 关系 True）
- 适合：源模块本身稳定、不需要 Layer 1 包装/扩展

**P3 应用**（8 个新 facade）:
- `clawcodex_ext/bridge/repl_bridge_transport.py` (P3-step4)
- `clawcodex_ext/bootstrap/state.py` (P3-step5)
- `clawcodex_ext/outputStyles.py` (P3-step5)
- `clawcodex_ext/config.py` (P3-step5)
- `clawcodex_ext/transports/serial_batch_event_uploader.py` (P3-step5)
- `clawcodex_ext/transports/websocket_transport.py` (P3-step5)
- `clawcodex_ext/utils/session_ingress_auth.py` (P3-step5)
- `clawcodex_ext/bootstrap/__init__.py` (空 package marker, P3-step5)

**P3 之前已存在**（沿用此模式的 clawcodex_ext 真实模块）:
- `clawcodex_ext/bridge/debug_utils.py`, `bridge/types.py`, `bridge/session_id_compat.py` 等
- `clawcodex_ext/utils/env.py`, `utils/message_mappers.py`, `utils/abort_controller.py` 等
- `clawcodex_ext/permissions/types.py`
- `clawcodex_ext/skills/bundled_skills.py`
- `clawcodex_ext/services/session_storage.py`（注：实际上用 lazy proxy 形式，详见 §2.3）

### 2.2 模式 B：同包 sibling import

**形式**:
```python
# 在 extensions/ports/bridge/bridge_main.py 中
from extensions.ports.bridge.session_runner import (
    PermissionRequest, SessionSpawnerDeps, create_session_spawner,
)
```

**特点**:
- 当被引用模块本身就是 Layer 2 文件（如 `extensions/ports/bridge/session_runner.py` 已被 P3-step4 改为 Layer 2），不应用 `clawcodex_ext.*` 间接化，而用同包 sibling
- 避免 Layer 2 内部模块反向走 Layer 1 facade（让 Layer 1 只引用 Layer 0，不被 Layer 2 内部引用）
- 适合：被引用模块位于同 Layer 2 子树内

**P3 应用**（2 处）:
- `extensions/ports/bridge/bridge_main.py` — `src.bridge.session_runner` → `extensions.ports.bridge.session_runner`
- `extensions/ports/bridge/repl_bridge.py` — `src.bridge.session_runner` → `extensions.ports.bridge.session_runner`

**注**: `src.bridge.session_runner` 本身是 `extensions/ports/bridge/session_runner.py` 的 re-export 指向 — 原本 bridge_main 通过 src 拿 Layer 2 自己的实现，绕了一大圈；改为同包 sibling 后语义直接清晰。

### 2.3 模式 C：lazy proxy via `__getattr__`

**形式**:
```python
# clawcodex_ext/services/session_storage.py
from __future__ import annotations

from typing import Any

# 内部委托给 src 实现，但通过 __getattr__ 解析符号
def __getattr__(name: str) -> Any:
    # 实际：clawcodex_ext 自己有完整实现，但部分历史代码
    # 通过此 lazy proxy 解析到 src 兼容版本
    ...
```

**特点**:
- 每次属性访问都从源模块重新取，不会缓存绑定 — 因此**对 monkey-patch 友好**
- 测试用 `unittest.mock.patch("src.X.Y.name")` 替换时，facade 引用也会跟着变
- 适合：被广泛 monkey-patch 的源模块、需要兼容旧测试的迁移

**P3 应用**:
- `clawcodex_ext/services/session_storage.py`（P3 之前已存在此模式，P3 整改利用其现成 lazy proxy）

**何时不适用**: 如果源模块经常整体重新加载或有副作用初始化，lazy proxy 每次访问都重新触发会引入性能损耗。

## §3 选型决策树

新增 `clawcodex_ext.*` facade 时，按以下顺序判断：

```
1. 被引用模块是否在 extensions/ 子树内？
   YES → 模式 B (同包 sibling import)
   NO  → 继续 ↓

2. 源模块是否会被测试广泛 monkey-patch？
   YES → 模式 C (lazy proxy) — 兼容 mock.patch
   NO  → 继续 ↓

3. 源模块是否稳定且小（< 200 行）？
   YES → 模式 A (from X import *) — 最低维护成本
   NO  → 考虑：在 clawcodex_ext/ 中实现完整覆盖层（非简单 facade）
```

**默认推荐**: 模式 A。P3 整改中 8 个新 facade 全部用模式 A。

## §4 已知限制

### 4.1 模式 A 的 monkey-patch 失效陷阱

**问题**: 模式 A 用 `from X.Y import *` 在 facade 加载时**缓存**符号引用。如果测试用 `unittest.mock.patch("src.X.Y.Z", mock_value)` 替换源模块属性，facade 的 `clawcodex_ext.X.Y.Z` 仍指向**旧对象**（缓存的），patch 失效。

**示例（P3-step5 踩坑）**:
```python
# 旧: extensions/remote_api/runner.py
from src.outputStyles import resolve_output_style  # patch src.outputStyles.resolve_output_style 生效

# 新 (模式 A): 改为 facade 后
from clawcodex_ext.outputStyles import resolve_output_style  # patch src.outputStyles 不再生效
# 因为 facade 的 resolve_output_style 是 src.outputStyles 在 import 时的引用快照
```

**缓解**:
1. 把测试改为 patch `clawcodex_ext.X.Y.Z`（P3 规则不动测试，因此不推荐）
2. 改用模式 C (lazy proxy) — 每次属性访问都从 src.X.Y 重新取
3. 保留为 P3-skip，不迁移（公开 API + 测试 mock 兼容需要）— 当前 P3 处理方式

**当前 P3-skip 案例**: `extensions/remote_api/runner.py:195-196`（详见 [known-issues.md §P3-skip](known-issues.md#p3-skip-公开-api--测试-mock-兼容)）

### 4.2 模式 A 的 submodule shadowing 风险

**问题**: 当 `clawcodex_ext.X.Y` 的 `__init__.py` 用 `from .Y import Y` 重新导出**同名子模块**时，调用方写 `import clawcodex_ext.X.Y as Z` 会拿到**重新导出的值**（函数/类）而非**子模块对象**。

**示例**:
```python
# clawcodex_ext/tool_system/__init__.py
from .build_tool import build_tool  # build_tool 是函数，重新导出后覆盖子模块
from .registry import ToolRegistry
```

```python
# 调用方
import clawcodex_ext.tool_system.build_tool as bt_mod  # bt_mod 现在是 build_tool 函数
# 而不是 build_tool 子模块对象（无法访问子模块内部的 Tool, Tools 等）
```

**影响**:
- `from clawcodex_ext.tool_system.build_tool import Tool, Tools` 模式**不受影响**（按符号名取，不依赖子模块对象）— P3 step 3/4/5/6 全部用此模式
- `import clawcodex_ext.X.Y as M` 模式**会受影响** — 暂无 P3 范围内的调用方，但 latent 风险

**缓解**: 详见 [known-issues.md §P3-out-1](known-issues.md#p3-out-1-修复-submodule-shadowing-风险)。

## §5 新 facade 的代码模式模板

### 5.1 普通 module（源是 .py 文件）

```python
# clawcodex_ext/X/Y.py
"""Compatibility facade — see :mod:`src.X.Y`."""
from src.X.Y import *  # noqa: F401,F403
```

### 5.2 Package（源是 directory）

新建 `clawcodex_ext/X/__init__.py`：
```python
# clawcodex_ext/X/__init__.py
"""Compatibility facade package — see :mod:`src.X`."""
```

新建 `clawcodex_ext/X/Y.py`：
```python
# clawcodex_ext/X/Y.py
"""Compatibility facade — see :mod:`src.X.Y`."""
from src.X.Y import *  # noqa: F401,F403
```

**示例**: `clawcodex_ext/bootstrap/`（P3-step5）— `__init__.py` 空 marker + `state.py` facade。

## §6 验证 facade 正确性

新 facade 创建后必跑等价性探针：

```python
import src.X.Y as src_mod
import clawcodex_ext.X.Y as ext_mod

# 关键符号必须 is 一致
assert ext_mod.SomeClass is src_mod.SomeClass
assert ext_mod.some_function is src_mod.some_function
```

P3 整改中每个新 facade 都通过此探针验证（详见各 step commit message 验证基线段落）。
