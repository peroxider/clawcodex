# F-157: 多模型并行调度 — TUI/REPL 展示方案

## 1. 设计原则

1. **纯方向键操作**：`← → ↑ ↓ Enter` 完成所有操作，零学习成本，零键位冲突
2. **两阶段自动切换**：流式阶段 → 完成选择阶段，无需手动切换
3. **零 TUI 侵入**：所有展示组件在 `extensions/multimodel/display/` 和 `clawcodex_ext/tui/widgets/multimodel/` 中实现，不修改现有 `src/tui/` 文件
4. **Headless 兼容**：非 TUI 模式有纯文本和 JSON 两种输出格式

## 2. 两阶段交互设计

### 2.1 阶段一：流式阶段（并行输出中）

所有模型并行输出时，用户通过 `← →` 切换查看各模型的实时输出。

```
┌─────────────────────────────────────────────────────────────┐
│  ◄  sonnet-4-6  │  gpt-4o  │  deepseek-v4-flash  ►        │
│                    ← → 切换                                  │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  sonnet-4-6 输出中...                                        │
│                                                              │
│  Here's a Python quicksort:                                  │
│  ```python                                                   │
│  def quicksort(arr):                                          │
│  ...                                                          │
│                                                              │
│  ↑ ↓ 滚动当前 Tab 内容                                        │
│                                                              │
│  ─────────────────────────────────────────────────           │
│  ● sonnet-4-6  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ 45%         │
│  ● gpt-4o  ████████████████████░░░░░░░░░░░░░░░░ 65%         │
│  ● deepseek  ████████████░░░░░░░░░░░░░░░░░░░░░░ 30%         │
└─────────────────────────────────────────────────────────────┘
```

| 按键 | 行为 |
|------|------|
| `←` | 切换到上一个模型 Tab（到头循环到最后一个） |
| `→` | 切换到下一个模型 Tab（到尾循环到第一个） |
| `↑` | 向上滚动当前 Tab 内容 |
| `↓` | 向下滚动当前 Tab 内容 |
| `Enter` | 无操作，底部提示「等待所有模型完成…」 |
| `F3` | 切换宽屏分栏模式（终端 ≥ 180 列时可用） |

**Tab 切换时**：底部状态栏的 `●` 高亮跟随移动，但所有模型的进度条持续更新，不因切换 Tab 而中断渲染。

### 2.2 阶段二：完成选择阶段

所有模型输出完成后，UI 自动过渡到选择列表。

```
所有模型输出完成
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  ✅ 全部完成 (3/3)  总耗时 3.1s                             │
│                                                              │
│  ┌─ sonnet-4-6 (2.3s, 342 tok) ───────────────────────────┐ │
│  │  ▸ 按 → 展开查看                                          │ │
│  │  Python quicksort, Lomuto partition, random pivot...     │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌─ gpt-4o (1.8s, 298 tok) ─◄ 高亮 ──────────────────────┐ │
│  │  ▸ 按 → 展开查看  [Enter 采纳此结果]                      │ │
│  │  Python quicksort, median-of-three pivot...              │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌─ deepseek-v4-flash (3.1s, 412 tok) ────────────────────┐ │
│  │  ▸ 按 → 展开查看                                          │ │
│  │  Python quicksort, 3-way partition, handles dupes...     │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  ↑ ↓ 选择  Enter 确认  → 展开  ← 收起  F2 差异对比           │
└─────────────────────────────────────────────────────────────┘
```

| 按键 | 行为 |
|------|------|
| `↑` | 上移选择高亮 |
| `↓` | 下移选择高亮 |
| `→` | 展开当前模型的完整内容 |
| `←` | 收起当前模型的完整内容 |
| `Enter` | 采纳当前高亮模型的结果，回到正常对话 |
| `F2` | 进入差异对比模式（对比两个已展开的模型） |
| `F3` | 切换宽屏分栏模式 |
| `q` / `Esc` | 退出选择，不采纳任何结果，继续对话 |

## 3. 展开/收起详情

按 `→` 展开当前高亮模型的完整内容，`←` 收起。

### 展开状态

```
┌─ gpt-4o (1.8s, 298 tok) ────◄ 展开 ──────────────────────┐
│  ▸ [Enter 采纳此结果]  [← 收起]                             │
│                                                             │
│  Here's a Python quicksort implementation:                   │
│                                                             │
│  ```python                                                   │
│  def quicksort(arr):                                         │
│      if len(arr) <= 1:                                       │
│          return arr                                          │
│      pivot = arr[len(arr) // 2]                              │
│      left = [x for x in arr if x < pivot]                   │
│      middle = [x for x in arr if x == pivot]                 │
│      right = [x for x in arr if x > pivot]                  │
│      return quicksort(left) + middle + quicksort(right)     │
│  ```                                                         │
│                                                             │
│  Time complexity: O(n log n) average, O(n²) worst case      │
│  Space complexity: O(n) for the auxiliary arrays            │
│                                                             │
│  ── 统计 ─────────────────────────────────────              │
│  文本: 412 chars | 代码: 18 lines | 耗时: 1.8s             │
└─────────────────────────────────────────────────────────────┘
```

### 展开状态下的交互

| 按键 | 行为 |
|------|------|
| `↑` | 移动高亮到上一个模型（当前卡片保持展开） |
| `↓` | 移动高亮到下一个模型（当前卡片保持展开） |
| `←` | 收起当前高亮卡片 |
| `Enter` | 采纳当前高亮模型的结果 |
| `F2` | 进入差异对比模式（比较已展开的模型） |

**可同时展开多个模型**，方便并排对比阅读。

## 4. 宽屏分栏模式

按 `F3` 切换，终端宽度 ≥ 180 列时可用。

```
┌────────────────────┬────────────────────┬────────────────────┐
│  sonnet-4-6        │  gpt-4o            │  deepseek-v4-flash │
│  ● ● ● ● ● ● ●   │  ● ● ● ● ● ● ●   │  ● ● ● ● ● ● ●   │
│                    │                    │                    │
│  Here's a Python   │  Here's a Python   │  Here's a Python   │
│  quicksort:        │  quicksort:        │  quicksort:        │
│                    │                    │                    │
│  ```python         │  ```python         │  ```python         │
│  def quicksort(    │  def quicksort(    │  def quicksort(    │
│      arr):         │      arr):         │      arr):         │
│      if len(arr)   │      if len(arr)   │      if len(arr)   │
│          <= 1:     │          <= 1:     │          <= 1:     │
│          return    │          return    │          return    │
│          arr       │          arr       │          arr       │
│  ...               │  ...               │  ...               │
│                    │                    │                    │
│  ⏳ 2.3s  342 tok  │  ⏳ 1.8s  298 tok  │  ⏳ 3.1s  412 tok  │
└────────────────────┴────────────────────┴────────────────────┘
```

**同步滚动**：所有分栏共享滚动位置，保持行对齐，方便逐行对比。

## 5. 差异对比模式

按 `F2` 进入，选择两个模型做行级 diff。

```
┌─────────────────────────────────────────────────────────────┐
│  ── Diff 模式 ────────────────────────────────────── F2 退出│
│                                                             │
│  对比: [sonnet-4-6]  vs  [gpt-4o]                           │
├─────────────────────────────────────────────────────────────┤
│  def quicksort(arr):                    def quicksort(arr): │
│      if len(arr) <= 1:                    if len(arr) <= 1: │
│          return arr                            return arr   │
│      pivot = arr[0]                    │   pivot = arr[len(arr)//2]│
│      left = [x for x in       │   │   left = [x for x in   │
│               arr[1:] if x <=  │   │            arr if x <   │
│               pivot]           │   │            pivot]       │
│  │  right = [x for x in      │   │   right = [x for x in   │
│  │           arr[1:] if x >   │   │            arr if x >   │
│  │           pivot]           │   │            pivot]       │
│  ...                             ...                         │
│                                                             │
│  ↑ ↓ 滚动  ← → 切换对比对  F2 退出                          │
└─────────────────────────────────────────────────────────────┘
```

**复用** `src/tui/widgets/structured_diff.py` 已有的 diff 组件，输入两个模型的文本，输出行级 diff 渲染。

## 6. 采纳后的对话视图

```
按 Enter 确认采纳 gpt-4o 的结果
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  ✓ 已采纳 gpt-4o 的结果                                     │
│                                                             │
│  ── 已采纳 ─────────────────────────────────               │
│  Here's a Python quicksort implementation:                   │
│                                                             │
│  ```python                                                   │
│  def quicksort(arr):                                         │
│      ...                                                     │
│  ```                                                         │
│                                                              │
│  ── 备选结果（可查看） ────────────────────                 │
│  • sonnet-4-6 (2.3s)                                        │
│  • deepseek-v4-flash (3.1s)                                 │
│                                                              │
│  > _                                                        │
└─────────────────────────────────────────────────────────────┘
```

- 已采纳的结果作为正常 `AssistantMessage` 进入对话历史
- 其他结果收起为可展开的备选列表，用户随时按 `→` 查看

## 7. 实现架构

```
extensions/multimodel/
  display/
    __init__.py
    protocol.py              # MultiModelDisplayProtocol
    tab_display.py           # TabbedDisplay — 流式 Tab 切换
    side_by_side.py          # SideBySideDisplay — 宽屏分栏
    diff_display.py          # DiffDisplay — 差异对比
    summary.py               # SummaryBuilder — 汇总页
    keyboard.py              # 快捷键绑定
    bridge.py                # MultiModelBridge — 连接 agent bridge ↔ display

clawcodex_ext/tui/
  widgets/
    multimodel/
      __init__.py
      tab_bar.py             # 模型 TabBar 组件
      tab_panel.py           # 单个模型 Tab 内容区
      progress_bar.py        # 后台模型进度条
      summary_panel.py       # 汇总对比面板
      diff_panel.py          # 差异对比面板
      selection_list.py      # 完成后的选择列表
      result_card.py         # 单个模型结果卡片（可展开/收起）
```

## 8. 数据流

```
AgentBridge (单线程 worker)
  │
  │  query() 返回 MultiModelResult（含 slot_name 标识）
  ▼
MultiModelBridge
  │
  ├── 流式阶段：
  │   ├── 按 slot_name 分发到对应 Tab 的 AssistantTextMessage
  │   ├── 更新底部进度条
  │   └── 键盘事件 → ← → 切换 Tab
  │
  ├── 完成阶段：
  │   ├── 自动切换为 selection_list 视图
  │   ├── ↑ ↓ 选择模型
  │   ├── → 展开/← 收起
  │   └── Enter → 回调采纳结果给 AgentBridge
  │
  └── 采纳后：
      └── 将选中结果写入正常对话历史，关闭多模型面板
```

## 9. 与现有架构的兼容性

| 组件 | 改动方式 | 改动量 |
|------|---------|--------|
| `TranscriptView` | 扩展 `mount_row()` 支持 `MultiModelPanel` 作为一整行 | ~20 行 |
| `REPLScreen` | 注册多模型快捷键，条件性挂载多模型面板 | ~30 行 |
| `AgentBridge` | 新增 `MultiModelResult` 事件类型 | ~15 行 |
| `AssistantTextMessage` | 复用，传入 `agent_name` 作为模型名 | 不变 |
| 新的多模型组件 | 纯新增，`Horizontal` + `Vertical` 组合 | ~500 行 |

所有改动在 `clawcodex_ext/tui/` 和 `extensions/multimodel/display/` 中，**完全不碰 `src/tui/`**。

## 10. Headless 模式下的展示

### 10.1 Text 格式

```
───── sonnet-4-6 (2.3s, 342 tok) ─────
[内容...]

───── gpt-4o (1.8s, 298 tok) ─────
[内容...]

───── deepseek-v4-flash (3.1s, 412 tok) ─────
[内容...]
```

### 10.2 JSON 格式

```json
{
  "multimodel": true,
  "strategy": "parallel",
  "results": [
    {"slot": "sonnet-4-6", "duration_ms": 2300, "tokens": {"input": 150, "output": 342}, "content": "..."},
    {"slot": "gpt-4o", "duration_ms": 1800, "tokens": {"input": 150, "output": 298}, "content": "..."},
    {"slot": "deepseek-v4-flash", "duration_ms": 3100, "tokens": {"input": 150, "output": 412}, "content": "..."}
  ]
}
```

### 10.3 Stream-JSON 格式

```json
{"type": "multimodel_progress", "slot": "sonnet-4-6", "status": "streaming", "chunk": "..."}
{"type": "multimodel_progress", "slot": "gpt-4o", "status": "streaming", "chunk": "..."}
{"type": "multimodel_complete", "slot": "deepseek-v4-flash", "duration_ms": 3100}
{"type": "multimodel_summary", "winning_slot": "sonnet-4-6", "all_results": [...]}
```

## 11. 按键总表（完整无冲突）

| 按键 | 流式阶段 | 完成阶段 |
|------|---------|---------|
| `←` | 切换到上一个 Tab | 收起当前模型详情 |
| `→` | 切换到下一个 Tab | 展开当前模型详情 |
| `↑` | 向上滚动内容 | 上移选择高亮 |
| `↓` | 向下滚动内容 | 下移选择高亮 |
| `Enter` | —（等完成） | 采纳当前模型 |
| `F2` | — | 差异对比模式 |
| `F3` | 切换宽屏分栏 | 切换宽屏分栏 |
| `q` / `Esc` | — | 退出选择，不采纳继续对话 |