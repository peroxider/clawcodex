# F-161 桌面宠物通知代理（Desktop Pet Notification Agent）

> 状态: 规划中 · P1 · 目标版本: TBD
> 设计文档版本: v1 — 2026-07-22

---

## 1. 概述

桌面宠物是 ClawCodex 后台守护进程的**视觉通知代理**。当 ClawCodex 作为独立守护进程在后台运行时，桌面宠物在用户桌面上以精灵形态呈现，用于：

- 社区雷达搜索到新 issue 时提醒用户
- 子更新（sub-update）处理完成时通知用户
- 守护进程生命周期事件（启动/停止/出错）的视觉反馈
- 持续提供守护进程运行状态的"一眼可读"指示

**核心定位：** 不是装饰品，而是后台的"眼睛"——让用户在不主动查看终端时也能感知到 ClawCodex 的活动。

---

## 2. 目标

### 2.1 核心目标

1. **实时通知** — 守护进程事件发生后 1s 内，宠物给出视觉反馈
2. **状态一目了然** — 只看宠物一眼，就能知道守护进程是否在正常工作
3. **非侵入** — 不打断用户当前工作流，通知自动消失
4. **跨平台** — 覆盖 Windows 桌面 + Linux 终端两大场景

### 2.2 非目标

- 不做系统托盘图标（未来可加，依赖 `pystray`）
- 不做开机自启（由用户 OS 配置）
- 不做多宠物/换装系统
- 不做点击交互游戏化（仅通知代理）
- 不做粒子效果/复杂动画

---

## 3. 子特性

| ID | 特性 | 优先级 | 依赖 |
|----|------|--------|------|
| F-161-A | **IPC 通信** — 守护进程与宠物进程间的本地 TCP 通道 | P0 | 无 |
| F-161-B | **Windows 桌面窗口** — tkinter 透明浮动窗口 | P0 | Python tkinter |
| F-161-C | **Linux 终端显示** — tmux pane / 内嵌终端 | P0 | 无 |
| F-161-D | **精灵渲染** — 复用 buddy ASCII sprite 数据 | P0 | `clawcodex_ext.buddy.sprites` |
| F-161-E | **状态机动画** — 空闲/通知/错误三种状态 | P0 | F-161-D |
| F-161-F | **通知气泡** — 事件驱动的文本气泡 | P0 | F-161-A |
| F-161-G | **窗口拖拽 + 位置记忆** | P1 | F-161-B |
| F-161-H | **右键菜单** — 状态/静音/退出 | P1 | F-161-B |
| F-161-I | **REPL observer 回连** — REPL 的 buddy 反应通过 IPC 发到宠物 | P2 | F-161-A |
| F-161-J | **GTK Layer Shell 后端** — Wayland 原生支持 | P2 | `gtk-layer-shell` |

---

## 4. 架构设计

### 4.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    ClawCodex 进程模型                         │
│                                                             │
│  ┌──────────────────────┐    Local TCP (127.0.0.1:9877)     │
│  │  后台守护进程         │ ────────────────────────────────▶ │
│  │  (daemon)            │                                   │
│  │                      │   事件:                            │
│  │  ├─ 社区雷达          │   ┌──────────────────────────┐   │
│  │  ├─ 子更新引擎        │   │  {"type":"notify",       │   │
│  │  ├─ issue tracker    │   │   "severity":"info",      │   │
│  │  └─ 状态管理          │   │   "title":"社区雷达",     │   │
│  └──────────────────────┘   │   "text":"发现3个新issue"}│   │
│                              └──────────────────────────┘   │
│                          ┌──────────────────────────────────┐│
│                          │  桌面宠物进程                     ││
│                          │  (desktop-pet)                   ││
│                          │                                  ││
│                          │  ├─ ipc_server.py  ← TCP 接收    ││
│                          │  ├─ pet_window.py  ← 窗口/终端   ││
│                          │  ├─ pet_renderer.py ← 精灵渲染   ││
│                          │  └─ pet_notifier.py ← 通知管理   ││
│                          └──────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

### 4.2 IPC 协议

**传输层：** Local TCP `127.0.0.1:9877`（可配置）

**消息格式（JSON-LD，每行一个 JSON）：**

```json
{"type":"notify","severity":"info","title":"社区雷达","text":"发现 3 个新 issue","ts":1778000000000}
{"type":"notify","severity":"success","title":"子更新","text":"F-38 自动修复完成","ts":1778000001000}
{"type":"notify","severity":"warning","title":"错误","text":"API 调用失败，已重试 3 次","ts":1778000002000}
{"type":"state","status":"idle","ts":1778000003000}
{"type":"state","status":"scanning","detail":"雷达扫描中...","ts":1778000004000}
{"type":"daemon","action":"started","pid":12345,"ts":1778000005000}
{"type":"daemon","action":"stopped","ts":1778000006000}
{"type":"ping","ts":1778000007000}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | `"notify"` / `"state"` / `"daemon"` / `"ping"` | 消息类型 |
| `severity` | `"info"` / `"success"` / `"warning"` / `"error"` | 通知级别 |
| `title` | str | 简短标题（可选） |
| `text` | str | 正文（可选） |
| `status` | `"idle"` / `"scanning"` / `"busy"` | 守护进程状态 |
| `action` | `"started"` / `"stopped"` | 守护进程生命周期 |
| `ts` | int | Unix 毫秒时间戳 |

**宠物进程响应：** 只接收不回复（单向通知）。宠物进程启动时监听 `127.0.0.1:9877`，守护进程连接后发送事件。

### 4.3 宠物状态机

```
        ┌──────────────────────────────────────────────────┐
        │                   状态机                           │
        │                                                   │
        │  daemon:started                                    │
        │  ┌──────────┐     ┌──────────────────────────┐     │
        │  │ 未启动     │────▶│    空闲待机               │     │
        │  │ (无窗口)   │     │    呼吸动画（3帧循环）     │     │
        │  └──────────┘     └──────────────────────────┘     │
        │                        │          │                │
        │              notify    │          │  daemon:stopped │
        │              received  │          │                │
        │                        ▼          ▼                │
        │              ┌──────────────┐  ┌──────────┐        │
        │              │  通知提醒     │  │  已停止   │        │
        │              │  ┌────────┐  │  │  灰色/睡眠│        │
        │              │  │气泡消息 │  │  └──────────┘        │
        │              │  └────────┘  │                       │
        │              │  + 精灵闪烁  │                       │
        │              │  + 状态变化  │                       │
        │              └──────────────┘                       │
        │                    │  after 5s                      │
        │                    ▼                                │
        │              ┌──────────────┐                       │
        │              │  空闲待机     │                       │
        │              └──────────────┘                       │
        └─────────────────────────────────────────────────────┘
```

**各状态行为：**

| 状态 | 动画 | 精灵外观 | 持续时间 |
|------|------|---------|---------|
| 空闲待机 | 3 帧循环，800ms/帧 | 正常颜色 | 持续 |
| 通知提醒 | 快速闪烁（200ms 交替） | 高亮/描边 | 5s 后自动回空闲 |
| 已停止 | 静态（无动画） | 灰色/半透明 | 持续 |

---

## 5. 平台实现

### 5.1 Windows 桌面窗口

```
extensions/desktop_pet/backends/tkinter_backend.py
```

| 属性 | 值 |
|------|-----|
| 框架 | tkinter（Python 标准库，零额外依赖） |
| 无边框 | `overrideredirect(True)` |
| 透明色 | `wm_attributes('-transparentcolor', 'black')` |
| 始终置顶 | `wm_attributes('-topmost', True)` |
| 窗口尺寸 | ~240×280px（精灵 12 列×4-5 行，24px 等宽字体，含气泡空间） |
| 默认位置 | 屏幕右下角，距边缘 20px |
| 拖动 | 绑定 `<Button-1>` + `<B1-Motion>` |
| 右键菜单 | tkinter `Menu`（Status / Mute / 穿透模式 / Quit） |
| 位置记忆 | 退出时写 `~/.clawcodex/pet_window.json`，启动时恢复 |

**窗口布局：**

```
┌──────────────────────┐
│  ┌────────────────┐  │  ← 气泡区域（通知时显示，5s 消失）
│  │ 发现3个新issue  │  │
│  └────────────────┘  │
│                      │
│  ┌────────────────┐  │  ← 精灵区域（Canvas，等宽字体渲染）
│  │    __          │  │
│  │  <(◉ )___      │  │
│  │   (  ._>       │  │
│  │    `--´        │  │
│  └────────────────┘  │
│                      │
│  [状态: 扫描中]      │  ← 状态条
└──────────────────────┘
```

### 5.2 Linux 终端显示

```
extensions/desktop_pet/backends/terminal_backend.py
```

| 属性 | 值 |
|------|-----|
| 框架 | 纯终端 ANSI 控制序列 |
| 显示模式 | tmux 右侧 pane（推荐）/ 单独终端窗口 |
| 精灵渲染 | ASCII 字符，ANSI 颜色 |
| 刷新 | 每 800ms 重绘一帧，事件驱动立即刷新 |
| 通知 | 精灵右侧/下方显示状态行 + 滚动通知行 |

**终端布局（tmux 分屏）：**

```
┌─ 主 pane ────────────────┬─ 宠物 pane (24列) ─┐
│                           │                     │
│  clawcodex-dev daemon     │  ┌──────┐           │
│  Daemon running on 8777   │  │ 精灵  │           │
│  [雷达] 扫描完成           │  │      │           │
│  [INFO] 发现 3 个新 issue  │  └──────┘           │
│                           │  [状态] 空闲         │
│                           │  [通知] 3 个新 issue │
│                           │                     │
│  ❯ _                      │  PID: 12345         │
└───────────────────────────┴─────────────────────┘
```

**ANSI 控制：**

```python
# 使用 \033[s / \033[u 保存/恢复光标位置
# 使用 \033[line;colH 定位到宠物区域
# 精灵区域保持固定，不随终端滚动
```

### 5.3 后端选择逻辑

```python
# pet_window.py
def detect_backend() -> str:
    if sys.platform == "win32":
        return "tkinter"          # Windows 原生 tkinter
    elif os.environ.get("WAYLAND_DISPLAY"):
        return "gtk"              # Linux Wayland → GTK Layer Shell
    elif os.environ.get("DISPLAY"):
        return "tkinter"          # Linux X11 → tkinter
    else:
        return "terminal"         # 纯终端（无图形环境）
```

---

## 6. 文件结构

```
extensions/desktop_pet/
├── __init__.py               # 包入口，暴露 start() / stop()
├── pet_window.py             # 统一入口，自动选择后端
├── backends/
│   ├── __init__.py
│   ├── tkinter_backend.py    # Windows/Linux X11 桌面窗口
│   ├── terminal_backend.py   # Linux 终端显示（tmux pane）
│   └── gtk_backend.py        # Linux Wayland（GTK Layer Shell，未来）
├── pet_renderer.py           # ASCII sprite → 像素/ANSI 渲染
├── pet_notifier.py           # 事件通知 → 气泡 + 动画状态切换
├── ipc_server.py             # Local TCP 服务器，接收 daemon 事件
├── cli.py                    # "clawcodex-dev desktop-pet" 子命令
└── README.md                 # 使用说明
```

---

## 7. 实施计划

### Phase 1（基础可用）

| 步骤 | 内容 | 预估工作量 |
|------|------|-----------|
| 1 | `ipc_server.py` — Local TCP 服务器，JSON-LD 解析 | 1d |
| 2 | `pet_renderer.py` — 读取 `clawcodex_ext.buddy` 数据，渲染精灵 | 1d |
| 3 | `backends/tkinter_backend.py` — 透明窗口 + 精灵显示 + 动画 | 2d |
| 4 | `backends/terminal_backend.py` — 终端 ANSI 渲染 + tmux 适配 | 1d |
| 5 | `pet_notifier.py` — 通知气泡 + 状态机 | 1d |
| 6 | `cli.py` — `clawcodex-dev desktop-pet start/stop/status` | 1d |
| 7 | `__init__.py` + `pet_window.py` — 后端选择 + 统一入口 | 0.5d |
| **合计** | | **~7.5d** |

### Phase 2（体验完善）

| 步骤 | 内容 | 预估工作量 |
|------|------|-----------|
| 8 | 窗口拖拽 + 位置记忆 | 0.5d |
| 9 | 右键菜单（状态/静音/穿透/退出） | 0.5d |
| 10 | REPL observer 回连 IPC | 1d |
| 11 | 通知队列（多条通知排队显示） | 0.5d |
| 12 | 守护进程自动拉起宠物 | 1d |
| **合计** | | **~3.5d** |

### Phase 3（平台扩展）

| 步骤 | 内容 | 预估工作量 |
|------|------|-----------|
| 13 | `backends/gtk_backend.py` — Wayland 原生 | 2d |
| 14 | 通知声音（可选的） | 1d |
| **合计** | | **~3d** |

---

## 8. 验收标准

### 功能性验收

- [ ] `clawcodex-dev desktop-pet start` 启动宠物窗口/终端
- [ ] 宠物显示 buddy 精灵（读取 `clawcodex_ext.buddy` 数据）
- [ ] 3 帧动画循环，每 800ms 切换
- [ ] 守护进程发送 notify 事件 → 宠物显示气泡 + 闪烁
- [ ] 守护进程发送 state 事件 → 宠物状态行更新
- [ ] 守护进程发送 daemon:stopped → 宠物进入灰色/停止态
- [ ] 宠物窗口可拖动，右键菜单可退出
- [ ] 位置记忆：重启后恢复上次位置

### 平台验收

- [ ] Windows 原生 Python：透明窗口 + 始终置顶
- [ ] WSLg (WSL2)：透明窗口通过 X11 转发正常显示
- [ ] Linux X11：tkinter 透明窗口正常工作
- [ ] Linux 纯终端：tmux 分屏 + ANSI 精灵渲染
- [ ] 无显示环境：优雅降级提示

### 边界情况

- [ ] 宠物未孵蛋（无 companion）：显示默认提示
- [ ] 守护进程未启动：宠物显示"等待连接"
- [ ] 守护进程断开重连：宠物自动恢复
- [ ] 通知风暴：5s 内多条通知 → 合并显示
- [ ] 多显示器：出现在主显示器右下角

---

## 9. 风险与约束

### 风险

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| Wayland 安全策略限制窗口覆盖 | 高 | 高 | Phase 3 用 GTK Layer Shell 协议绕过 |
| Linux 终端 ANSI 渲染与用户输出冲突 | 中 | 中 | 推 tmux 分屏模式，inline 模式作为降级 |
| WSLg 性能（tkinter 通过 X11 转发） | 中 | 低 | 帧率降低到 1fps 仍然可接受（动画不要求流畅） |
| 用户无 tkinter（Linux 非 GUI 安装） | 中 | 中 | 自动降级为 terminal 后端 |
| IPC 端口冲突 | 低 | 低 | 支持配置端口，自动检测冲突 |

### 约束

1. **不新增永久依赖** — 核心功能使用 Python 标准库（tkinter），不要求 `pip install` 额外包
2. **不修改 `src/` 和 `clawcodex_ext/` 现有代码** — 纯新扩展 `extensions/desktop_pet/`
3. **不与现有 buddy 子系统冲突** — 宠物仅消费 buddy 数据，不修改其行为
4. **守护进程的 IPC 发送方应可配置** — 不强制 daemon 必须发送，通过配置控制

---

## 10. 依赖关系

### 上游依赖

| 依赖 | 说明 | 状态 |
|------|------|------|
| `clawcodex_ext.buddy.types` | Species / Rarity / Eye / Hat 等类型 | ✅ 已就绪 |
| `clawcodex_ext.buddy.companion` | `get_companion()` 读取伴侣 | ✅ 已就绪 |
| `clawcodex_ext.buddy.sprites` | `render_sprite()` 渲染 ASCII 精灵 | ✅ 已就绪 |
| `clawcodex_ext.buddy.observer` | `fire_companion_observer()` 事件检测 | ✅ 已就绪（回调需改造） |

### 协同特性

| 特性 | 关系 |
|------|------|
| 守护进程（独立 daemon 模式） | 宠物的事件源，需 daemon 在关键节点调用 IPC 发送 |
| 社区雷达 | 雷达发现 issue 时 → 发送 notify 事件 |
| 子更新引擎 | 更新完成时 → 发送 notify 事件 |

---

## 11. 已拟定的设计决定

1. **IPC 选择 Local TCP 而非 Unix Domain Socket** — 跨平台一致性（Windows 无 UDS），且未来支持远程连接
2. **单向通信（daemon → pet）** — 宠物只接收不发送，简化协议
3. **JSON-LD 格式** — 每行一个 JSON，可 tail -f 查看，可管道消费
4. **tkinter 优先于 pygame** — 零额外依赖，够用
5. **Linux 终端优先于 Wayland 窗口** — Linux 用终端显示，避免 Wayland 透明窗口兼容性问题
6. **独立进程而非嵌入 REPL** — tkinter 的 `mainloop()` 阻塞，无法与 REPL/TUI 事件循环共存
7. **默认端口 9877** — 避免与常见服务端口冲突

---

## 12. 设计文档与参考

| 文档 | 说明 |
|------|------|
| `clawcodex_ext/buddy/` | Buddy 子系统数据层 |
| `clawcodex_ext/buddy/sprites.py` | ASCII 精灵库（18 种物种 × 3 帧） |
| `clawcodex_ext/buddy/observer.py` | 每轮观察者（当前回调为空） |
| `docs/feature_plan/01-overview.md` | 项目概述与架构约束 |
| `docs/decoupling/` | 解耦方案文档 |