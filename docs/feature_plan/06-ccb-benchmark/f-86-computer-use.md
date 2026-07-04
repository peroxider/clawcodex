# F-86: Computer Use 跨平台 Executor

> 状态: 🟡 原语层已落地(`clawcodex_ext/services/computer_use/`,ABC + Linux + Null + Dry-run + Factory);macOS / Windows 后端待补
> 章节: `docs/feature_plan/06-ccb-benchmark/f-86-computer-use.md`
> 最后更新: 2026-06-30
> 缺口来源: [README.md §A 缺口矩阵](./README.md#a-全特性对照矩阵)

## §1 设计规划

### 1.1 目标

对标 CCB 的 Computer Use 三平台统一接口(`src/utils/computerUse/`,macOS Quartz / Windows pywin32 / Linux X11),补齐 ClawCodex 的 macOS + Windows 后端,并升级 Linux 后端的 Wayland 覆盖与多显示器支持,使 ClawCodex 在三大主流桌面平台上具备等价于上游的"截屏 + 键鼠模拟 + 剪贴板 + 窗口管理"四件套能力,能够驱动 Anthropic Computer Use / OpenAI Operator 等基于视觉的 Agent 工作流。

### 1.2 背景

**已完成原语层**(自研部分,镜像上游抽象):

| 模块 | 行数 | 角色 |
|------|------|------|
| `clawcodex_ext/services/computer_use/base.py` | ~92 | `ScreenshotProvider` / `InputSimulator` / `ClipboardManager` / `WindowManager` 四个 ABC |
| `clawcodex_ext/services/computer_use/models.py` | ~101 | `MouseButton` / `ScrollDirection` / `ScreenRegion` / `WindowRef` / `InputAction` |
| `clawcodex_ext/services/computer_use/dry_run.py` | ~70 | `DryRunRecorder`(事件回放,用于测试 + 训练数据收集) |
| `clawcodex_ext/services/computer_use/exceptions.py` | ~25 | `ComputerUseError` / `BinaryNotFoundError` / `SafetyViolationError` / `CoordinatesOutOfBoundsError` / `WindowNotFoundError` |
| `clawcodex_ext/services/computer_use/factory.py` | ~52 | `build_computer_use_suite(platform, backend, recorder)` + `ComputerUseSuite` 类型别名 |
| `clawcodex_ext/services/computer_use/platform/__init__.py` | ~78 | `_current_platform()` + `build_provider_suite(platform, backend, recorder)`,自动按 `sys.platform` 派发,未识别平台回退 Null |
| `clawcodex_ext/services/computer_use/platform/linux.py` | ~420 | Linux 后端:`scrot`/`import`(截图)+ `xdotool`(键鼠)+ `xclip`(剪贴板)+ `wmctrl`(窗口),受 `CLAWCODEX_COMPUTER_USE_ALLOW` + `dry_run` 双门控 |
| `clawcodex_ext/services/computer_use/platform/null.py` | ~170 | 测试 / 未知平台空实现,所有副作用走 `DryRunRecorder` |

**现状评估**:

- ABC 设计、参数校验、`is_dry_run` 行为、`SafetyViolationError` 双门控语义与上游一致;
- Linux 后端仅覆盖 X11(`xdotool` + `wmctrl`),Wayland 多显示器与高 DPI 截屏未实现;
- macOS / Windows 调用 `build_provider_suite('darwin' | 'windows')` 直接回退 `build_null_suite()`,无任何真实实现;
- `factory.py` 对未识别平台静默回退 null,导致 macOS / Windows 用户拿到"假成功",需要显式错误提示;
- 三平台共用同一 `DryRunRecorder`,支持跨平台回放 + 训练数据导出;
- `ALLOW_ENV_VAR = "CLAWCODEX_COMPUTER_USE_ALLOW"` 的环境变量门控已落地,真实执行需要同时 `dry_run=False` + env 设为真值。

**缺口**(用户面向层):

1. **macOS 后端**: Quartz `CGEventCreate` + `screencapture` 完全缺失,Agent 在 macOS 上截屏/点击/输入全部走 null;
2. **Windows 后端**: `pywin32` `SendInput` + `Pillow.ImageGrab` 完全缺失,WSL 中转方案不可移植;
3. **Linux Wayland 分支**: `wlr-screencopy-unstable-v1` + `wlr-virtual-pointer-unstable-v1` 未实现,Wayland 用户(包括部分 GNOME 默认会话)拿不到真实鼠标控制;
4. **多显示器支持**: `ScreenRegion` 仅校验坐标 ≤32767,跨屏拼接 / `monitor_id` 字段未实现;
5. **HiDPI / 缩放**: Linux 后端对 fractional scaling(2x、3x)未做坐标归一化,截图像素和点击坐标会错位;
6. **平台自动选择可见性**: `build_provider_suite` 静默回退 null,日志无任何 WARNING,运维无法察觉;
7. **ComputerUse 工具入口**: 内置工具 `ComputerUseTool`(允许 AI 调度截屏 + click/type)尚未挂入 `tool_registry`;
8. **安全策略层**: `SafetyViolationError` 是单层拒绝,缺乏"区域围栏 (geofence)" + "应用白名单 (app allowlist)" + "速率限制";
9. **CI 集成**: 三平台后端均依赖系统二进制,在 CI 中难以跨平台验证;需要 mock backend fixture。

### 1.3 子特性分解

| 编号 | 子特性 | 状态 | 预计工作量 |
|:----:|--------|:----:|:----------:|
| P86-A | macOS 后端 (`platform/macos.py`):Quartz 截图 + CGEvent 键鼠 + NSPasteboard 剪贴板 + Quartz Window List | 📋 | 7-10 天 |
| P86-B | Windows 后端 (`platform/windows.py`):`Pillow.ImageGrab` 截屏 + `ctypes.SendInput` 键鼠 + Win32 clipboard + `EnumWindows` | 📋 | 7-10 天 |
| P86-C | Linux Wayland 分支 (`platform/linux_wayland.py`):wlroots 协议子集(`zwlr-screencopy`, `zwlr-virtual-pointer`) | 📋 | 5-7 天 |
| P86-D | Linux HiDPI + 多显示器(`ScreenRegion` 扩 `monitor_id` + 坐标归一化) | 📋 | 3-5 天 |
| P86-E | Linux X11 后端加固:覆盖 `xrandr` 多显示器分支 + `xdotool` 版本兼容矩阵 | 📋 | 3-5 天 |
| P86-F | 平台自动选择可见性:回退 null 时打 `WARNING`(降级但可见),并暴露 `--computer-use-backend` 显式指定 | 📋 | 1-2 天 |
| P86-G | `ComputerUseTool` 内置工具(`tool_system/tools/computer_use.py`),AI 可调,封装截图 + click + type + key + scroll + drag | 📋 | 5-7 天 |
| P86-H | 安全策略层:`ComputerUsePolicy` dataclass(geofence 矩形 + app allowlist + rate_limit)+ 双门控(`dry_run` + env) | 📋 | 3-5 天 |
| P86-I | 平台后端能力探测 (`probe_capabilities.py`):自动检测二进制是否齐全 + 是否 HiDPI + 显示器数量 | 📋 | 2-3 天 |
| P86-J | CI 跨平台 fixture:`MockScreenshotProvider` / `MockInputSimulator` 接 `DryRunRecorder` | 📋 | 2-3 天 |
| P86-K | 单元测试 + 集成测试(Linux 真实后端跑 VM,macOS/Windows 走 CI matrix + 真实 runner) | 📋 | 5-7 天 |

**估算总工时**: 10-12 周(单人);其中 macOS/Windows 各占约 2 周。

### 1.4 架构设计

#### 1.4.1 三平台后端拓扑

```
                              ┌─────────────────────────────┐
                              │  build_provider_suite()     │
                              │  (factory / __init__)       │
                              └─────────────────────────────┘
                                          │
                  ┌───────────────────────┼───────────────────────┐
                  │                       │                       │
        ┌─────────▼─────────┐    ┌────────▼────────┐    ┌─────────▼─────────┐
        │ platform/darwin   │    │ platform/linux  │    │ platform/windows  │
        │ macos.py          │    │ linux.py + linux│    │ windows.py        │
        │                   │    │ _wayland.py     │    │                   │
        │ ┌──────────────┐  │    │ ┌─────────────┐ │    │ ┌──────────────┐  │
        │ │Screencapture │  │    │ │scrot/import │ │    │ │Pillow.ImageG │  │
        │ │  (CG)        │  │    │ │wlr-screencop│ │    │ │rab           │  │
        │ ├──────────────┤  │    │ ├─────────────┤ │    │ ├──────────────┤  │
        │ │CGEventCreate │  │    │ │xdotool /    │ │    │ │ctypes.SendIn │  │
        │ │  (键鼠)      │  │    │ │wlr-virtual- │ │    │ │put           │  │
        │ ├──────────────┤  │    │ │pointer      │ │    │ ├──────────────┤  │
        │ │NSPasteboard  │  │    │ ├─────────────┤ │    │ │Win32 Clipbrd │  │
        │ │  (剪贴板)    │  │    │ │xclip/       │ │    │ ├──────────────┤  │
        │ ├──────────────┤  │    │ │wl-clipboard │ │    │ │EnumWindows   │  │
        │ ├──────────────┤  │    │ ├─────────────┤ │    │ ├──────────────┤  │
        │ │Quartz Window │  │    │ │wmctrl / sway │ │    │ │SetForeground │  │
        │ │  List        │  │    │ │msg -t        │ │    │ │Window        │  │
        │ └──────────────┘  │    │ └─────────────┘ │    │ └──────────────┘  │
        └───────────────────┘    └─────────────────┘    └───────────────────┘
                  │                       │                       │
                  └───────────────────────┴───────────────────────┘
                                          │
                              ┌───────────▼────────────┐
                              │ ComputerUsePolicy      │
                              │ (P86-H 双门控 + 围栏)  │
                              └────────────────────────┘
                                          │
                              ┌───────────▼────────────┐
                              │ DryRunRecorder         │
                              │ (跨平台统一录制/回放)   │
                              └────────────────────────┘
```

#### 1.4.2 包结构(全部解耦,不动 `src/`)

```
clawcodex_ext/services/computer_use/       ← 现有原语层(扩展)
├── base.py                                # 已有 ABC,补充能力字段
├── models.py                              # 已有,新增 Monitor / ScaleFactor 字段
├── dry_run.py                             # 已有,新增 platform tag
├── exceptions.py                          # 已有,新增 UnsupportedPlatformError / PermissionDeniedError
├── factory.py                             # 已有,新增 platform 显式选择 + warning
├── policy.py                              # P86-H: ComputerUsePolicy dataclass
├── capabilities.py                        # P86-I: probe_capabilities() 输出
├── platform/
│   ├── __init__.py                        # 已有,扩展 darwin/windows 分支
│   ├── linux.py                           # 已有(X11),P86-E 加固
│   ├── linux_wayland.py                   # P86-C: Wayland 后端(wlroots 子集)
│   ├── macos.py                           # P86-A: macOS 后端
│   ├── windows.py                         # P86-B: Windows 后端
│   └── null.py                            # 已有
├── probes/                                # P86-I: 平台探测
│   ├── __init__.py
│   ├── linux_probe.py
│   ├── macos_probe.py
│   └── windows_probe.py
└── fixtures/                              # P86-J: CI 跨平台 mock
    ├── __init__.py
    ├── mock_screenshot.py
    ├── mock_input.py
    └── mock_clipboard.py

clawcodex_ext/tool_system/tools/computer_use.py   # P86-G: ComputerUseTool(AI 可调)
clawcodex_ext/command_system/builtins.py          # 注册 /computer-use 命令(P86-备,可选)
clawcodex_ext/feature_gate/registry.py           # 注册 COMPUTER_USE_MACOS / WINDOWS / WAYLAND 标志
```

#### 1.4.3 解耦要点

| 设计点 | 解耦方式 | 理由 |
|--------|----------|------|
| 三平台 ABC | 复用现有 `base.py` 四个 ABC | 不破坏 Linux 已落地的 `LinuxBackend` |
| Linux Wayland 拆分 | 新建 `linux_wayland.py`,通过 `_current_platform() == 'wayland'` 切换 | 不影响 X11 路径 |
| macOS / Windows 后端 | 新建 `platform/macos.py` / `platform/windows.py`,按 `sys.platform` 派发 | 镜像现有 factory 风格 |
| 双门控 | 保留 `ALLOW_ENV_VAR` + `dry_run`;新增 `ComputerUsePolicy` 提供应用层围栏 | 不破坏现有 `LinuxBackend.is_allowed()` |
| 后端探测 | `capabilities.py` 导出 `probe_capabilities(platform)`,返回缺失依赖列表 | 与 factory 解耦,允许前端先探测后调用 |
| CI mock | `fixtures/mock_*.py` 实现相同 ABC,接 `DryRunRecorder` | 不依赖系统二进制 |
| Feature Flag | F-68 注册 `COMPUTER_USE_MACOS` / `COMPUTER_USE_WINDOWS` / `COMPUTER_USE_WAYLAND`,默认关闭 | 避免无 GUI CI 误触发真实键鼠 |
| `ComputerUseTool` | 新建独立工具模块,F-71 风格 `tool_registry.register()` | 与现有工具统一入口 |

### 1.5 核心数据模型

#### 1.5.1 扩展 `ScreenRegion`(P86-D:多显示器 + HiDPI)

```python
# clawcodex_ext/services/computer_use/models.py(扩展)

from typing import Literal

@dataclass(frozen=True)
class MonitorInfo:
    """单块显示器的描述。"""
    monitor_id: str                       # 系统层 ID(Win32 HMONITOR / NSScreen | CGDirectDisplayID / wl_output)
    name: str = ""                        # 人读名称(可选)
    origin: tuple[int, int] = (0, 0)      # 在虚拟桌面中的左上角(像素)
    size: tuple[int, int] = (1920, 1080)  # 像素尺寸(物理像素)
    scale_factor: float = 1.0             # HiDPI: 物理像素 / 逻辑像素
    primary: bool = False
    refresh_hz: float | None = None

@dataclass(frozen=True)
class ScreenRegion:
    """坐标按 *逻辑像素* 表示,backend 内部按 scale_factor 转换为物理像素。"""
    x: int = 0
    y: int = 0
    width: int = 1920
    height: int = 1080
    monitor_id: str | None = None         # P86-D: 指定显示器;None 表示跟随当前焦点显示器
    coordinate_space: Literal["logical", "physical"] = "logical"  # P86-D: 显式语义

    def __post_init__(self) -> None:
        # 保持原有校验
        if self.width <= 0 or self.height <= 0:
            raise ValueError("ScreenRegion width/height must be positive")
        if self.x < 0 or self.y < 0:
            raise ValueError("ScreenRegion origin must be non-negative")
        if self.coordinate_space == "logical":
            if self.x + self.width > 32767 or self.y + self.height > 32767:
                raise ValueError("ScreenRegion extends past supported bounds")
        else:
            if self.x + self.width > 65535 or self.y + self.height > 65535:
                raise ValueError("physical ScreenRegion exceeds u16 bounds")
```

#### 1.5.2 安全策略层(P86-H)

```python
# clawcodex_ext/services/computer_use/policy.py

from dataclasses import dataclass, field

@dataclass(frozen=True)
class GeofenceRect:
    """允许执行的逻辑像素矩形(可多个)。"""
    x: int
    y: int
    width: int
    height: int

@dataclass(frozen=True)
class ComputerUsePolicy:
    """应用层策略,与 platform 层 dry_run + ALLOW_ENV_VAR 双门控叠加。"""
    enabled: bool = False                       # 总开关
    allow_click: bool = True
    allow_type: bool = True
    allow_screenshot: bool = True
    allow_drag: bool = False                    # 默认禁止,容易误操作
    geofences: tuple[GeofenceRect, ...] = ()    # 空 = 不限
    app_allowlist: tuple[str, ...] = ()         # 窗口标题白名单(模糊匹配);空 = 不限
    rate_limit_per_min: int = 60                # 全局速率上限
    require_dry_run: bool = True                # 若 True,生产环境必须 dry_run=True 才允许

    def check_action(self, action: str, x: int | None = None, y: int | None = None) -> None:
        """校验 action + 坐标,失败抛 SafetyViolationError 或 PermissionDeniedError。"""
```

#### 1.5.3 能力探测(P86-I)

```python
# clawcodex_ext/services/computer_use/capabilities.py

@dataclass(frozen=True)
class PlatformCapabilities:
    platform: str                                # "linux" / "darwin" / "windows" / "wayland"
    display_server: str                          # "x11" / "wayland" / "aqua" / "win32"
    screenshot_backend: str | None               # "scrot" / "wlr-screencopy" / "screencapture" / "imagegrab"
    input_backend: str | None                    # "xdotool" / "wlr-virtual-pointer" / "cgevent" / "sendinput"
    clipboard_backend: str | None
    window_manager_backend: str | None
    monitors: tuple[MonitorInfo, ...] = ()
    scale_factor: float = 1.0
    missing_dependencies: tuple[str, ...] = ()   # 缺失的二进制/库
    available: bool = False                      # 所有依赖齐全才为 True

def probe_capabilities(platform: str | None = None) -> PlatformCapabilities: ...
```

### 1.6 核心接口

#### 1.6.1 macOS 后端(`clawcodex_ext/services/computer_use/platform/macos.py`)

```python
from __future__ import annotations

from ..base import ClipboardManager, InputSimulator, ScreenshotProvider, WindowManager
from ..dry_run import DryRunRecorder
from ..models import MouseButton, ScreenRegion, WindowRef


class MacOSScreenshotProvider(ScreenshotProvider):
    """基于 `screencapture -x -t png <path>` 的截屏。"""

    def __init__(self, recorder: DryRunRecorder) -> None:
        self._recorder = recorder

    def capture_fullscreen(self) -> bytes: ...
    def capture_region(self, region: ScreenRegion) -> bytes: ...
    def capture_window(self, window: WindowRef) -> bytes | None: ...
    @property
    def is_dry_run(self) -> bool: ...


class MacOSInputSimulator(InputSimulator):
    """基于 Quartz `CGEventCreateMouseEvent` + `CGEventCreateKeyboardEvent` 的键鼠。"""

    def __init__(self, recorder: DryRunRecorder, *, dry_run: bool = True) -> None:
        self._recorder = recorder
        self._dry_run = dry_run

    def move_mouse(self, x: int, y: int) -> None: ...
    def click(self, button: MouseButton = MouseButton.LEFT, *, x: int | None = None, y: int | None = None) -> None: ...
    def double_click(self, *, x: int | None = None, y: int | None = None) -> None: ...
    def type_text(self, text: str) -> None: ...
    def press_key(self, key: str) -> None: ...
    def scroll(self, dx: int = 0, dy: int = 1) -> None: ...
    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int) -> None: ...
    @property
    def is_dry_run(self) -> bool: ...


class MacOSClipboardManager(ClipboardManager):
    """基于 AppKit NSPasteboard。"""

    def get_text(self) -> str: ...
    def set_text(self, text: str) -> None: ...
    @property
    def is_dry_run(self) -> bool: ...


class MacOSWindowManager(WindowManager):
    """基于 Quartz `CGWindowListCopyWindowInfo` + `AXUIElement`。"""

    def list_windows(self) -> list[WindowRef]: ...
    def focus_window(self, window: WindowRef) -> bool: ...
    def close_window(self, window: WindowRef) -> bool: ...
    @property
    def is_dry_run(self) -> bool: ...


def build_macos_suite(recorder: DryRunRecorder) -> dict[str, object]:
    return {
        "screenshot": MacOSScreenshotProvider(recorder),
        "input": MacOSInputSimulator(recorder),
        "clipboard": MacOSClipboardManager(recorder),
        "window": MacOSWindowManager(recorder),
    }
```

#### 1.6.2 Windows 后端(`clawcodex_ext/services/computer_use/platform/windows.py`)

```python
class WindowsScreenshotProvider(ScreenshotProvider):
    """基于 `Pillow.ImageGrab.grab(all_screens=True)`。"""

class WindowsInputSimulator(InputSimulator):
    """基于 ctypes `SendInput` (INPUT_MOUSE / INPUT_KEYBOARD)。"""

class WindowsClipboardManager(ClipboardManager):
    """基于 `ctypes.windll.user32.OpenClipboard` / `SetClipboardData`。"""

class WindowsWindowManager(WindowManager):
    """基于 ctypes `EnumWindows` + `SetForegroundWindow`。"""

def build_windows_suite(recorder: DryRunRecorder) -> dict[str, object]: ...
```

#### 1.6.3 Linux Wayland 分支(`platform/linux_wayland.py`)

```python
class WaylandScreenshotProvider(ScreenshotProvider):
    """通过 `wlr-screencopy-unstable-v1` 协议在 wlroots 合成器(Sway / Hyprland)上截屏。
    不可用时降级 `grim`(命令行)。"""

class WaylandInputSimulator(InputSimulator):
    """通过 `wlr-virtual-pointer-unstable-v1` 协议 + `wlr-virtual-keyboard-unstable-v1`。
    不可用时降级 `ydotool` (需要 uinput 权限)。"""

class WaylandClipboardManager(ClipboardManager):
    """通过 `wl-clipboard` (`wl-copy` / `wl-paste`)。"""

class WaylandWindowManager(WindowManager):
    """通过 Sway IPC / Hyprland IPC;其他合成器降级 `swaymsg -t get_tree`。"""

def build_wayland_suite(recorder: DryRunRecorder) -> dict[str, object]: ...
```

#### 1.6.4 工厂扩展(`platform/__init__.py`)

```python
_UNSUPPORTED_PLATFORMS: frozenset[str] = frozenset()
_WAYLAND_INDICATORS = ("WAYLAND_DISPLAY", "XDG_SESSION_TYPE")  # XDG_SESSION_TYPE=wayland

def _detect_display_server() -> str:
    if sys.platform.startswith("linux"):
        if os.environ.get("XDG_SESSION_TYPE") == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
            return "wayland"
        if os.environ.get("DISPLAY"):
            return "x11"
        return "headless"
    if sys.platform == "darwin":
        return "aqua"
    if sys.platform in {"win32", "cygwin"}:
        return "win32"
    return "unknown"


def build_provider_suite(
    platform: str | None = None,
    *,
    backend: LinuxBackend | None = None,
    recorder=None,
    display_server: str | None = None,
) -> dict[str, object]:
    """按 platform + display_server 派发后端,未识别平台显式 warning 后回退 null。"""
    name = (platform or _current_platform()).lower()
    ds = (display_server or _detect_display_server()).lower()
    if name == "linux":
        if ds == "wayland":
            from .linux_wayland import build_wayland_suite  # 延迟 import(避免 Linux-only deps)
            return build_wayland_suite(recorder or DryRunRecorder())
        return build_linux_suite(backend=backend, recorder=recorder)
    if name == "darwin":
        from .macos import build_macos_suite
        try:
            return build_macos_suite(recorder or DryRunRecorder())
        except ImportError as exc:
            logger.warning("macOS backend unavailable (missing %s); falling back to null suite", exc.name)
            return build_null_suite()
    if name in {"win32", "windows"}:
        from .windows import build_windows_suite
        try:
            return build_windows_suite(recorder or DryRunRecorder())
        except ImportError as exc:
            logger.warning("Windows backend unavailable (missing %s); falling back to null suite", exc.name)
            return build_null_suite()
    if name in _UNSUPPORTED_PLATFORMS:
        raise ComputerUseError(f"platform {name!r} is explicitly disabled")
    logger.warning("Unknown platform %r; using null suite", name)
    return build_null_suite()
```

#### 1.6.5 `ComputerUseTool`(`clawcodex_ext/tool_system/tools/computer_use.py`)

```python
class ComputerUseTool(Tool):
    """AI 可调的高级 Computer Use 工具,封装截屏 + click + type + key + scroll + drag。
    输入统一逻辑像素,内部按 ScaleFactor 归一化;每次执行均受 ComputerUsePolicy 校验。"""

    name = "computer_use"
    description = "Capture screenshots and perform mouse/keyboard actions on the current desktop."

    async def run(
        self,
        *,
        action: Literal["screenshot", "click", "double_click", "type", "key", "scroll", "drag"],
        x: int | None = None,
        y: int | None = None,
        button: str | None = None,
        text: str | None = None,
        key: str | None = None,
        dx: int | None = None,
        dy: int | None = None,
        end_x: int | None = None,
        end_y: int | None = None,
        region: dict | None = None,         # ScreenRegion.to_dict()
        scale_factor: float | None = None,
        dry_run: bool = True,
        tool_context: ToolContext,
    ) -> dict:
        ...
```

### 1.7 安全模型

| 层级 | 机制 | 触发条件 |
|------|------|----------|
| L1 平台层 | `ALLOW_ENV_VAR` + `LinuxBackend.dry_run` | 任意真实键鼠必须 `CLAWCODEX_COMPUTER_USE_ALLOW=1` 且 `dry_run=False` |
| L1 平台层 | 二进制存在性 | 缺失 `scrot/xdotool/Quartz/pywin32` → `BinaryNotFoundError` |
| L2 应用层 | `ComputerUsePolicy.enabled` | 总开关 |
| L2 应用层 | `ComputerUsePolicy.allow_<action>` | 每个 action 单独允许 |
| L2 应用层 | `ComputerUsePolicy.geofences` | click/drag 必须落在矩形内,否则 `SafetyViolationError` |
| L2 应用层 | `ComputerUsePolicy.app_allowlist` | focus/close 操作的目标窗口标题必须匹配 |
| L2 应用层 | `ComputerUsePolicy.rate_limit_per_min` | 滑动窗口计数器,超限 `PermissionDeniedError` |
| L3 工具层 | `tool_registry` 启用位 | 仅在 F-68 `COMPUTER_USE_MACOS/WINDOWS/WAYLAND` 开启时注册 |
| L3 工具层 | `ComputerUseTool.dry_run` | 单次调用可显式 dry_run=True 避免真实副作用 |

### 1.8 失败模式与错误分类

| 错误类型 | 触发场景 | 处理策略 |
|----------|----------|----------|
| `BinaryNotFoundError` | 系统未安装 `scrot` / `xdotool` 等 | 提示安装命令(Linux: `apt install scrot xdotool`;macOS: `brew install ...`;Windows: `pip install pywin32 pillow`) |
| `SafetyViolationError` | 平台层 / 应用层未通过双门控 | 抛出,不执行 |
| `CoordinatesOutOfBoundsError` | 坐标超过显示器尺寸 | 抛出 + 返回当前 `MonitorInfo` |
| `WindowNotFoundError` | 窗口标题/ID 找不到 | 抛出 + 返回 `list_windows()` 前 5 项 |
| `UnsupportedPlatformError` | 当前 OS 显式禁用 | 抛出 + 列出可用平台 |
| `PermissionDeniedError` | Policy 拒绝(白名单 / 速率) | 抛出 + 给出拒绝原因 |
| `BackendUnavailableWarning` | 后端依赖不全,静默回退 null | WARNING 日志 + 工具层返回的 `dry_run=True` 等价结果 |

### 1.9 测试策略

| 层级 | 框架 | 覆盖范围 |
|------|------|----------|
| 单元 | pytest | `LinuxBackend` argv 校验、`ScreenRegion` 边界、`DryRunRecorder` 序列化、`ComputerUsePolicy.check_action` |
| 单元 | pytest + monkeypatch | 用 `LinuxBackend.runner=lambda *a, **kw: CompletedProcess(...)` 模拟 `subprocess.run` |
| 集成 | pytest + xvfb | Linux 真实 X11 环境跑 `scrot` / `xdotool`,断言截图非空 + 键鼠事件被记录 |
| 集成 | GitHub Actions matrix | `macos-latest` + `windows-latest` 跑真实后端(只 dry_run,验证流程通畅) |
| 集成 | GitHub Actions Linux + Wayland | Sway headless(需 root 启动 Xvfb + Sway)跑 Wayland 后端 |
| E2E | pytest + playwright | 驱动 Chromium 自截屏自点击,验证闭合 |
| 安全 | 静态 | `grep -E "shell=True"` + 自定义 lint:`computer_use` 模块禁止 `shell=True` |
| CI | mock fixture | `fixtures/mock_*.py` 跨平台跑断言,无外部依赖 |

### 1.10 兼容性矩阵

| 平台 | 显示服务器 | 截图 | 键鼠 | 剪贴板 | 窗口 | 备注 |
|------|-----------|------|------|--------|------|------|
| Linux | X11 | `scrot` / `import` | `xdotool` | `xclip` / `xsel` | `wmctrl` | 已落地 |
| Linux | Wayland (wlroots) | `wlr-screencopy` / `grim` | `wlr-virtual-pointer` / `ydotool` | `wl-copy` / `wl-paste` | Sway/Hyprland IPC | P86-C |
| Linux | Wayland (GNOME) | `gnome-screenshot` / `grim` | `ydotool`(需 uinput) | `wl-copy` / `wl-paste` | `wmctrl` 不可用 → 仅聚焦 | 限制 |
| macOS | Aqua | `screencapture -x` | Quartz `CGEventCreate` | `NSPasteboard` | `CGWindowListCopyWindowInfo` | P86-A |
| Windows | Win32 | `Pillow.ImageGrab` | `ctypes.SendInput` | Win32 `OpenClipboard` | `EnumWindows` | P86-B |
| WSL2 | 转发到 Windows | — | — | — | — | 不支持,显式报错 |
| 其他 | — | 回退 Null | 回退 Null | 回退 Null | 回退 Null | 显式 WARNING |

## §2 落地步骤

> 顺序原则:先 Linux 已有路径加固(P86-D/E)→ 新增 Wayland 分支(P86-C)→ macOS(P86-A)→ Windows(P86-B)→ 工具层 + 安全(P86-G/H)→ 测试(CI matrix)。

| 步骤 | 内容 | 涉及子特性 | 工时 |
|:----:|------|:----------:|:----:|
| 1 | `models.py` 扩展 `MonitorInfo` + `coordinate_space` 字段;`ScreenRegion` 增加 monitor_id;原 `__post_init__` 保持兼容 | P86-D | 3 天 |
| 2 | `factory.py` 扩展 `_detect_display_server()` + `build_provider_suite(display_server=)`,回退 null 显式 WARNING | P86-F | 1-2 天 |
| 3 | `linux.py` 加固:补 `xrandr` 多显示器分支 + 坐标归一化;补 `xdotool` 2.x/3.x 兼容矩阵 | P86-D/E | 3-5 天 |
| 4 | `capabilities.py` + `probes/linux_probe.py`,输出 `PlatformCapabilities` | P86-I | 2-3 天 |
| 5 | `linux_wayland.py` 实现,wlsroots 协议子集 + 缺失依赖降级 `grim`/`ydotool` | P86-C | 5-7 天 |
| 6 | `macos.py` 实现,PyObjC 依赖通过 `pip install pyobjc-framework-Quartz pyobjc-framework-AppKit` 可选安装 | P86-A | 7-10 天 |
| 7 | `windows.py` 实现,`pywin32` + `Pillow` 通过 `[computer_use_windows]` extras 安装 | P86-B | 7-10 天 |
| 8 | `policy.py` + `ComputerUsePolicy.check_action()` + 应用层围栏 | P86-H | 3-5 天 |
| 9 | `tool_system/tools/computer_use.py` 实现 `ComputerUseTool`,注册到 `tool_registry` | P86-G | 5-7 天 |
| 10 | `fixtures/mock_*.py` 提供跨平台 mock 后端 | P86-J | 2-3 天 |
| 11 | CI 矩阵:`ubuntu-latest`(X11)+ `ubuntu-latest` Wayland 容器 + `macos-latest` + `windows-latest`,仅 dry_run | P86-K | 5-7 天 |
| 12 | README 更新 + 文档(平台兼容矩阵 + 安装指引) | P86-备 | 1-2 天 |

**累计工时**:10-12 周(单人全职)。

## §3 风险与缓解

| 风险 | 等级 | 缓解措施 |
|------|:----:|----------|
| macOS Quartz 依赖体积大,CI 安装慢 | 🟠 | `[computer_use_macos]` extras 可选,CI matrix 仅 dry_run,不真依赖 Quartz |
| Windows `ctypes.SendInput` 与 UAC 冲突 | 🟠 | 提示用户必须以相同权限运行;UAC 提权窗口无法驱动,显式说明 |
| Wayland 协议碎片化(GNOME / KDE / wlroots) | 🟠 | 按 wlroots 子集实现,其他合成器降级 `grim`/`ydotool`,文档明示限制 |
| WSL2 无原生 GUI,Linux 后端失效 | 🟡 | 启动时检测 WSL,显式提示并禁用真实后端,只保留 dry_run |
| HiDPI 坐标归一化错误导致点击偏移 | 🔴 | 强制 `coordinate_space="logical"` + 单元测试覆盖 1x/1.5x/2x/3x |
| `dry_run=False` 误用导致真实副作用 | 🔴 | 应用层 Policy `require_dry_run=True`(默认) + 双门控 |
| 截图含敏感信息(密码框)被 LLM 看到 | 🟠 | 文档要求用户自行遮罩;不主动 OCR;可选 `redaction` 字段(P86-后续) |
| 速率限制被绕过(短时间大量 click) | 🟡 | 滑动窗口 + Policy `rate_limit_per_min`;日志审计 |
| macOS `Accessibility` 权限未授予,CGEvent 静默失败 | 🟠 | 启动时探测,提示用户在系统设置授予权限 |
| Windows 多显示器 DPI 不同导致坐标错位 | 🟠 | `MonitorInfo.scale_factor` 逐显示器归一化 |

## §4 与其他特性的关系

| 依赖 / 协同 | 说明 |
|-------------|------|
| **F-68 Feature Gate** | 注册 `COMPUTER_USE_MACOS` / `WINDOWS` / `WAYLAND`,默认关闭,需用户显式开启 |
| **F-71 Tool Gap** | `ComputerUseTool` 走 `tool_registry.register()` 入口,统一风格 |
| **F-84 Daemon** | 后台 Computer Use 任务可挂载到 Daemon Worker(长驻截屏 + 后台监听) |
| **F-85 Pipe IPC** | 跨机器场景下,`PipeMessageType.CU_SCREENSHOT` 同步远端截屏(本机三平台 → 远端) |
| **F-88 Monitor** | `kind='monitor'` 后台 + `ComputerUseTool` 配合可实现"AI 持续观察屏幕 + 自动化操作"闭环 |
| **F-89 Proactive** | Proactive Tick 集成:`probe_capabilities().available` 决定是否能进入"主动操作"模式 |
| **F-90+ 安全** | 红队测试 + 围栏策略需要在生产环境验证 |
| **上游 CCB** | 监控 `src/utils/computerUse/` 的变更(2026 H2 可能新增 Wayland 分支) |

## §5 验收标准

1. **三平台覆盖**: `build_provider_suite("linux")` / `("darwin")` / `("windows")` 在对应平台返回真实后端(非 null),并在缺失依赖时返回 null + WARNING 日志;
2. **Linux Wayland**: 在 Sway headless 容器内 `capture_fullscreen()` 返回非空 PNG,`move_mouse(100, 100)` 不抛异常;
3. **HiDPI**: 在 2x scale_factor 下,逻辑坐标 (100, 100) → 物理坐标 (200, 200);截图与点击位置一致;
4. **多显示器**: `ScreenRegion(monitor_id="DP-2", ...)` 仅截取指定显示器,不包含其他屏内容;
5. **安全围栏**: `geofences=[GeofenceRect(0,0,500,500)]` 下 click(600, 600) 抛 `SafetyViolationError`,坐标不被发送;
6. **速率限制**: `rate_limit_per_min=10` 下 60s 内第 11 次 click 抛 `PermissionDeniedError`;
7. **CI matrix**: `ubuntu-latest` + `macos-latest` + `windows-latest` 三平台 dry_run 测试全部通过,无 binary 缺失错误;
8. **Mock 后端**: `fixtures/mock_screenshot.py` + `DryRunRecorder` 在无 GUI CI 中跑通 100% 单测覆盖率;
9. **ComputerUseTool 注册**: `tool_registry.list_tools()` 包含 `computer_use`,输入 schema 包含 action enum + 坐标 / 文本字段;
10. **文档完整**: README 提供 macOS / Windows / Linux( X11 / Wayland)各自的安装命令 + 已知限制 + WSL2 提示。

## §6 后续展望(P87+)

- **P86-L 红队测试**: 真实环境 fuzz 测试,验证坐标围栏 + 速率限制的健壮性;
- **P86-M OCR 集成**: 截图 + 本地 OCR(Tesseract / Apple Vision / Windows OCR)让 AI 可读 UI;
- **P86-N Redaction**: 截图前自动遮罩敏感区域(用户配置);
- **P86-O 远程 Computer Use**: 与 F-85 LAN 协同,远端 macOS 截屏 + 本地 Windows 操作;
- **P86-P GUI 录制**: `DryRunRecorder` 导出为 MP4 / GIF,用于回放训练数据;
- **P86-Q 应用语义层**: 通过 `Accessibility`(macOS) / `UI Automation`(Windows)识别 UI 元素而非像素坐标,提升稳定性。

---

**关联文档**:

- 缺口分析: [README.md §A 缺口矩阵](./README.md#a-全特性对照矩阵)
- README 索引: [README.md#f-86-computer-use-跨平台-executor](#f-86)
- 现实现代码: `clawcodex_ext/services/computer_use/`(ABC + Linux + Null + DryRun + Factory)
- 对标上游: CCB `src/utils/computerUse/`