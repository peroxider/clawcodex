# F-81: Native 原生模块系统

> 状态: ✅ 已实现（P0 + P1 + P2 全部子特性落地）
> 章节: docs/feature_plan/06-ccb-benchmark/f-81-native-modules.md
> 最后更新: 2026-07-02

## §1 设计规划

### 1.1 目标

对标 CCB Rust/NAPI 原生模块（audio-capture-napi / color-diff-napi / image-processor-napi / url-handler-napi / modifiers-napi），用纯 Python 等价实现音频捕获、图像差异对比、URL Scheme 注册、修饰键检测等能力。

### 1.2 CCB 对标分析

| CCB 模块 | 原始语言 | Python 替代方案 | 可行性 |
|----------|:--------:|-----------------|:------:|
| `audio-capture-napi` | Rust/NAPI | `pyaudio` / `sounddevice` + `webrtcvad` VAD 检测 | ✅ 完全可行 |
| `color-diff-napi` | Rust/NAPI | `PIL.ImageChops.difference` + NumPy `mean_squared_error` | ✅ 完全可行 |
| `image-processor-napi` | Rust/NAPI | `Pillow` (crop/resize/encode/decode) | ✅ 完全可行 |
| `modifiers-napi` | Rust/NAPI | `pynput` / `evdev`（键盘修饰键状态检测） | ⚠️ 部分可行 |
| `url-handler-napi` | Rust/NAPI | `webbrowser` + `xdg-open` / `desktop-entry` | ✅ 完全可行 |

### 1.3 子特性分解

| 子特性 | 说明 | 优先级 | 状态 |
|--------|------|:------:|:----:|
| F-81.1 | `clawcodex_ext/native/__init__.py` — 统一的原生模块注册表与懒加载基础设施 | P0 | ✅ |
| F-81.2 | `clawcodex_ext/native/audio.py` — 麦克风音频捕获（前置 F-64 Voice Mode） | P0 | ✅ |
| F-81.3 | `clawcodex_ext/native/image.py` — 截图差异对比与图像处理（前置 F-61 Computer Use） | P0 | ✅ |
| F-81.4 | `clawcodex_ext/native/url_handler.py` — OS URL Scheme 注册（`clawcodex://`） | P1 | ✅ |
| F-81.5 | `clawcodex_ext/native/modifiers.py` — 键盘修饰键检测（辅助 F-61） | P1 | ✅ |
| F-81.6 | fallback 策略：当可选依赖缺失时降级为纯 Python 兜底 | P2 | ✅ |

### 1.4 架构设计

```
clawcodex_ext/native/
├── __init__.py          # NativeModule Protocol + NativeModuleRegistry + lazy loader + load/load_or_fallback
├── audio.py             # 音频捕获（pyaudio/sounddevice） + AudioFallback
├── image.py             # 图像差异对比 + 处理（Pillow + NumPy） + ImageFallback
├── url_handler.py       # URL Scheme 注册（webbrowser + xdg-utils/reg.exe）
└── modifiers.py         # 键盘修饰键检测（pynput/evdev） + ModifiersFallback
```

```python
@runtime_checkable
class NativeModule(Protocol):
    name: str
    def is_available(self) -> bool: ...
    def get_version(self) -> str: ...

class NativeModuleRegistry:
    """统一的原生模块注册表，懒加载 + 降级检查.

    注册表直接持有类对象（非路径字符串），避免嵌套类 qualname 含
    ``<locals>`` 段时反射查找失败。内置模块在 ``__init__`` 中以
    *占位类* 登记，首次 ``load()`` 才触发子模块 import.
    """
    _registry: ClassVar[dict[str, type]] = {}

    @classmethod
    def register(cls, name: str) -> Callable[[type], type]:
        """类装饰器：自注册 NativeModule 实现类."""

    @classmethod
    def get_class(cls, name: str) -> type: ...
    @classmethod
    def is_registered(cls, name: str) -> bool: ...
    @classmethod
    def names(cls) -> list[str]: ...
```

#### 公共加载 API

| 函数 | 签名 | 语义 |
|------|------|------|
| `load(name)` | `-> NativeModule \| None` | 懒加载可用实例；未注册 / `is_available()=False` / `ImportError` 均返回 `None` |
| `load_or_fallback(name)` | `-> NativeModule` | 永远返回非 None；主实现不可用时调用类的 `fallback()` 工厂；无 fallback 则抛 `NativeModuleError` |
| `available_names()` | `-> list[str]` | 已注册的全部模块名（不论是否当前可用） |

### 1.5 音频捕获模块（F-81.2）

**实现要点**：

- 双后端策略：优先 `pyaudio`，回退 `sounddevice`；二者皆缺则 `is_available()=False`
- `record()` 返回完整 WAV 字节（PCM16，默认 16kHz 单声道，适合语音识别）
- `stream()` 异步生成器持续 yield PCM16 块（暂未集成 VAD，留待 F-64 子任务）
- F-81.6 fallback：`AudioFallback` 返回静音 WAV，所有 `record`/`stream` 不抛异常

```python
class AudioCaptureModule:
    name = "audio_capture"
    def is_available(self) -> bool: ...
    def get_version(self) -> str: ...

    async def record(self, duration_sec: float = 5.0, sample_rate: int = 16000, channels: int = 1) -> bytes: ...
    async def stream(self, sample_rate: int = 16000, channels: int = 1) -> AsyncIterator[bytes]: ...

    @classmethod
    def fallback(cls) -> "AudioFallback": ...

class AudioFallback:  # F-81.6
    name = "audio_capture"
    def is_available(self) -> bool: return False
    def get_version(self) -> str: return "fallback-silent"
    async def record(...) -> bytes: ...   # 静音 WAV
    async def stream(...) -> AsyncIterator[bytes]: ...  # 无限静音块
```

### 1.6 图像差异对比模块（F-81.3）

**实现要点**：

- `compute_diff()` 返回归一化 MSE `mean((arr1-arr2)**2) / 255**2`，范围 [0.0, 1.0]
- 尺寸不一致时取最小公共尺寸对齐，避免广播报错
- `crop_and_resize()` 用 `Image.LANCZOS` 重采样，同时支持落盘 + 返回字节
- F-81.6 fallback：`ImageFallback` 用 `hashlib.sha256` 字节级比较（完全相同→0.0，否则→1.0），失去像素精度但能区分极端

```python
class ImageProcessorModule:
    name = "image_processor"
    def is_available(self) -> bool: ...
    def get_version(self) -> str: ...

    def compute_diff(self, img1_path: str, img2_path: str) -> float: ...
    def images_equal(self, img1_path: str, img2_path: str, threshold: float = 0.01) -> bool: ...
    def crop_and_resize(self, image_path: str, box: tuple[int,int,int,int],
                        size: tuple[int,int] | None = None,
                        output_path: str | None = None, quality: int = 85) -> bytes: ...
    def encode(self, image_path: str, fmt: str = "JPEG", quality: int = 85,
               output_path: str | None = None) -> bytes: ...

    @classmethod
    def fallback(cls) -> "ImageFallback": ...
```

### 1.7 URL Handler 模块（F-81.4）

**实现要点**：

- 基于 Python 标准库 `webbrowser`，`is_available()` 恒 `True`
- 平台分支注册：
  - **Linux** — 写 `~/.local/share/applications/<protocol>-handler.desktop` + `xdg-mime default` 关联
  - **Windows** — 用 `reg.exe` 写 `HKCU\Software\Classes\<protocol>` （无需管理员权限）
  - **macOS** — 需 .app bundle + `lsregister`，纯 CLI 场景返回 `False`（不抛异常）
- `open_clawcodex(path)` 便捷包装：打开 `clawcodex://<path>`
- 无 fallback（永远可用）

```python
class UrlHandlerModule:
    name = "url_handler"
    def is_available(self) -> bool: return True
    def get_version(self) -> str: ...
    def register_protocol(self, protocol: str = "clawcodex", executable: str = "clawcodex") -> bool: ...
    def open_url(self, url: str) -> bool: ...
    def open_clawcodex(self, path: str) -> bool: ...
```

### 1.8 修饰键检测模块（F-81.5）

**实现要点**：

- 后端选择：Linux 优先 `evdev`（直读 `/dev/input/event*`），fallback `pynput`；macOS/Windows 用 `pynput`
- 模块级单例追踪器（`_PynputStateTracker` / `_EvdevStateTracker`）后台线程累积 up/down 事件，避免每次 `current_state()` 重启线程
- `ModifierState` 数据类（`__slots__` 优化）：`shift` / `ctrl` / `alt` / `meta` 四键 + `any_pressed()` 便捷方法
- F-81.6 fallback：`ModifiersFallback` 所有状态恒 `False`

```python
class ModifierState:
    __slots__ = ("shift", "ctrl", "alt", "meta")
    def __init__(self, shift=False, ctrl=False, alt=False, meta=False) -> None: ...
    def any_pressed(self) -> bool: ...

class ModifiersModule:
    name = "modifiers"
    def is_available(self) -> bool: ...
    def get_version(self) -> str: ...
    def current_state(self) -> ModifierState: ...
    @classmethod
    def fallback(cls) -> "ModifiersFallback": ...

class ModifiersFallback:  # F-81.6
    name = "modifiers"
    def is_available(self) -> bool: return False
    def current_state(self) -> ModifierState: ...  # 全 False
```

### 1.9 依赖

| 依赖 | 用途 | 必需性 | 缺失时行为 |
|------|------|:------:|-----------|
| `pyaudio` | 音频捕获主后端 | 可选 | 尝试 `sounddevice`；二者皆缺→`AudioFallback` |
| `sounddevice` | 音频捕获备后端 | 可选 | 同上 |
| `Pillow` | 图像处理 | 可选 | `ImageFallback`（字节 sha256 对比） |
| `numpy` | 图像 MSE 计算 | 可选 | 同上 |
| `pynput` | 修饰键检测（跨平台） | 可选 | Linux 尝试 `evdev`；皆缺→`ModifiersFallback` |
| `evdev` | 修饰键检测（Linux 优选） | 可选 | 回退 `pynput` |
| `webbrowser` | URL 打开 | 标准库 | 永远可用 |
| `xdg-utils` / `reg.exe` | URL Scheme 注册 | 平台工具 | 缺失时 `register_protocol` 返回 `False`，不抛异常 |

均为 optional-dependencies，缺失时模块 `is_available()` 返回 `False`，`load_or_fallback()` 返回兜底实例。

## §2 进度跟踪

### 实现状态（2026-07-02）

| 子特性 | 文件 | 状态 |
|--------|------|:----:|
| F-81.1 注册表 + 懒加载 | `clawcodex_ext/native/__init__.py` | ✅ |
| F-81.2 音频捕获 | `clawcodex_ext/native/audio.py` | ✅ |
| F-81.3 图像差异 + 处理 | `clawcodex_ext/native/image.py` | ✅ |
| F-81.4 URL Scheme 注册 | `clawcodex_ext/native/url_handler.py` | ✅ |
| F-81.5 修饰键检测 | `clawcodex_ext/native/modifiers.py` | ✅ |
| F-81.6 fallback 降级 | 各模块 `fallback()` 类方法 | ✅ |

### 文件清单

| 路径 | 行数 | 用途 |
|------|-----:|------|
| `clawcodex_ext/native/__init__.py` | ~230 | Protocol + Registry + 懒加载占位 + `load`/`load_or_fallback` |
| `clawcodex_ext/native/audio.py` | ~266 | `AudioCaptureModule` + `AudioFallback` |
| `clawcodex_ext/native/image.py` | ~215 | `ImageProcessorModule` + `ImageFallback` |
| `clawcodex_ext/native/url_handler.py` | ~161 | `UrlHandlerModule`（Linux/Windows/macOS） |
| `clawcodex_ext/native/modifiers.py` | ~293 | `ModifiersModule` + `ModifierState` + `ModifiersFallback` + 后台追踪器 |
| `tests/clawcodex_ext/native/__init__.py` | 1 | 测试包标识 |
| `tests/clawcodex_ext/native/test_registry.py` | ~139 | F-81.1 注册表/懒加载/降级 |
| `tests/clawcodex_ext/native/test_audio.py` | ~66 | F-81.2 音频 + fallback |
| `tests/clawcodex_ext/native/test_image.py` | ~115 | F-81.3 图像主路径 + fallback |
| `tests/clawcodex_ext/native/test_url_handler.py` | ~79 | F-81.4 URL 注册 + 平台分支 |
| `tests/clawcodex_ext/native/test_modifiers.py` | ~62 | F-81.5 修饰键 + fallback |

### 测试矩阵

| 测试文件 | 用例数 | 覆盖范围 |
|----------|-----:|----------|
| `test_registry.py` | 9 | 内置模块登记、未知名 load、ImportError 吞掉、fallback 工厂、无 fallback 抛错、Protocol 满足性 |
| `test_audio.py` | 5 | 注册、fallback 静音 WAV 解析、stream 静音块、load_or_fallback、不可用抛 NativeModuleError |
| `test_image.py` | 7 | 注册、fallback 字节 sha256 对比（相同/不同）、fallback crop 原字节、主路径 MSE（相同/不同）、crop_and_resize JPEG SOI |
| `test_url_handler.py` | 9 | 注册、永远可用、webbrowser 委托、clawcodex:// 前缀、Error 处理、Linux .desktop 写入 + xdg-mime 调用、不支持平台、load_or_fallback |
| `test_modifiers.py` | 8 | 注册、ModifierState 默认/any_pressed/相等、fallback 全 False、load_or_fallback、不可用抛错、后端检测 |
| **合计** | **39** | 全部通过（1.82s） |

### 验证

| 检查项 | 命令 | 结果 |
|--------|------|:----:|
| 单元测试 | `python3 -m pytest tests/clawcodex_ext/native/ -q` | ✅ 39 passed |
| Lint | `ruff check clawcodex_ext/native/ tests/clawcodex_ext/native/` | ✅ All checks passed |
| 稳定性门禁 Stage 1 | 核心模块导入 | ✅ passed |
| 稳定性门禁 Stage 5 | 扩展模块 | ✅ passed |
| 运行时冒烟 | `import clawcodex_ext.native; load + load_or_fallback` | ✅ 4 模块名正确，降级行为符合预期 |

### 设计要点

- **注册模式 (Golden Rule #5)** —— 模块通过 `@NativeModuleRegistry.register("name")` 装饰器自注册，新增模块无需修改 `__init__.py`
- **懒加载** —— `__init__.py` 用占位类（`_LazyPlaceholder` 子类）登记内置模块路径，首次 `load()` 才触发子模块 import，避免冷启动拉入 `pyaudio`/`Pillow` 等重型可选依赖
- **直接持有类对象** —— 注册表 `dict[str, type]` 直接存类引用（非路径字符串），避免嵌套类 `__qualname__` 含 `<locals>` 段时 `getattr` 反射查找失败
- **降级 (F-81.6)** —— 每个模块提供 `fallback()` 类方法，`load_or_fallback(name)` 在主实现不可用时返回纯 Python 兜底实例：
  - 音频 → `AudioFallback`（静音 WAV）
  - 图像 → `ImageFallback`（字节 sha256 对比，0.0 或 1.0）
  - 修饰键 → `ModifiersFallback`（全 False）
  - URL → 无 fallback（标准库 `webbrowser` 永远可用）
- **不侵入 `src/` (Golden Rule #1/#6)** —— 整套子系统位于 `clawcodex_ext/native/`（Layer 1 补丁层），对上游零侵入

### 与原始设计文档的偏差

| 偏差点 | 原始设计 | 实际实现 | 原因 |
|--------|----------|----------|------|
| Registry 存储类型 | `dict[str, tuple[str, str]]`（路径字符串） | `dict[str, type]`（类对象） | 嵌套类 qualname 含 `<locals>` 段，反射查找失败；直接存类对象更稳健 |
| `register` 签名 | `register(name, mod_cls)` 普通方法 | `register(name)` 装饰器工厂 | 符合项目既有注册模式（见 `extensions/capabilities/adapter_protocol.py`） |
| 音频 `stream` 签名 | `stream() -> AsyncIterator[bytes]` | `stream(sample_rate=16000, channels=1) -> AsyncIterator[bytes]` | 暴露参数让调用方控制采样率 |
| 图像 `compute_diff` 尺寸处理 | 未定义 | 取最小公共尺寸对齐 | 避免两张不同分辨率截图广播报错 |
| URL `register_protocol` | 仅 Linux 分支 | Linux + Windows + macOS 三平台 | 文档原例只示范 Linux，实现补全 Windows（reg.exe）与 macOS（返回 False） |
| 修饰键状态读取 | 未细化 | 模块级单例后台 listener 纯程累积事件 | `pynput`/`evdev` 不直接暴露"当前状态"，需监听事件 |
| F-81.6 fallback 入口 | 文档未明确 | `load_or_fallback(name)` 公共函数 + 各模块 `fallback()` 类方法 | 提供统一降级 API，调用方无需 try/except |

### 后续待办（非本特性范围）

- **VAD 集成**（F-64 子任务）—— `audio.stream()` 当前输出原始帧，待接入 `webrtcvad` 做语音活动检测后再分片
- **macOS URL Scheme** —— 需打包 .app bundle + `lsregister`，超出 CLI 范围，留待 GUI 分发方案
- **修饰键 evdev root 权限** —— Linux `/dev/input/event*` 通常需 `input` 组权限，文档化建议用户加入对应组或使用 `pynput` 后端

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
| 2026-06-24 | 补全详细设计（架构+5 子模块+代码示例） | 对齐 FEATURE_PLAN.legacy.md |
| 2026-07-02 | 落地实现全部 6 子特性 + 39 单元测试 + 更新进度跟踪 | F-81 特性实现 |
| 2026-07-02 | 文档刷新：补全公共 API 表、测试矩阵、偏差说明、文件清单、后续待办 | 实现对齐文档 |
