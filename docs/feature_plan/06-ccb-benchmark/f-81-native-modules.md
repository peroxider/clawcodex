# F-81: Native 原生模块系统

> 状态: 🔭 探索中
> 章节: docs/feature_plan/06-ccb-benchmark/f-81-native-modules.md
> 最后更新: 2026-06-24

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

| 子特性 | 说明 | 优先级 |
|--------|------|:------:|
| F-81.1 | `clawcodex_ext/native/__init__.py` — 统一的原生模块注册表与懒加载基础设施 | P0 |
| F-81.2 | `clawcodex_ext/native/audio.py` — 麦克风音频捕获（前置 F-64 Voice Mode） | P0 |
| F-81.3 | `clawcodex_ext/native/image.py` — 截图差异对比与图像处理（前置 F-61 Computer Use） | P0 |
| F-81.4 | `clawcodex_ext/native/url_handler.py` — OS URL Scheme 注册（`clawcodex://`） | P1 |
| F-81.5 | `clawcodex_ext/native/modifiers.py` — 键盘修饰键检测（辅助 F-61） | P1 |
| F-81.6 | fallback 策略：当可选依赖缺失时降级为纯 Python 兜底 | P2 |

### 1.4 架构设计

```
clawcodex_ext/native/
├── __init__.py          # NativeModuleRegistry + lazy loader
├── audio.py             # 音频捕获（pyaudio/sounddevice）
├── image.py             # 图像差异对比 + 处理（Pillow + NumPy）
├── url_handler.py       # URL Scheme 注册（webbrowser + xdg-utils）
└── modifiers.py         # 键盘修饰键检测（pynput/evdev）
```

```python
class NativeModule(Protocol):
    name: str
    def is_available(self) -> bool: ...
    def get_version(self) -> str: ...

class NativeModuleRegistry:
    """统一的原生模块注册表，懒加载 + 降级检查。"""
    _modules: dict[str, type[NativeModule]] = {}

    @classmethod
    def register(cls, name: str, mod_cls: type[NativeModule]) -> None:
        cls._modules[name] = mod_cls

    @classmethod
    def load(cls, name: str) -> NativeModule | None:
        mod_cls = cls._modules.get(name)
        if mod_cls is None:
            return None
        try:
            instance = mod_cls()
            if instance.is_available():
                return instance
        except ImportError:
            pass
        return None
```

### 1.5 音频捕获模块

```python
class AudioCaptureModule:
    name = "audio_capture"
    def is_available(self) -> bool:
        try: import pyaudio; return True
        except ImportError: return False

    async def record(self, duration_sec: float = 5.0, sample_rate: int = 16000, channels: int = 1) -> bytes:
        """录制麦克风音频，返回 WAV 字节。"""
        import pyaudio
        p = pyaudio.PyAudio()
        stream = p.open(format=pyaudio.paInt16, channels=channels, rate=sample_rate, input=True, frames_per_buffer=1024)
        frames = [stream.read(1024) for _ in range(int(sample_rate / 1024 * duration_sec))]
        stream.stop_stream(); stream.close(); p.terminate()
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(channels); wf.setsampwidth(2); wf.setframerate(sample_rate)
            wf.writeframes(b"".join(frames))
        return buf.getvalue()

    async def stream(self) -> AsyncIterator[bytes]:
        """实时音频流（VAD 检测后输出片段）。"""
        import pyaudio
        p = pyaudio.PyAudio()
        stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=1024)
        try:
            while True:
                yield stream.read(1024)
        finally:
            stream.stop_stream(); stream.close(); p.terminate()
```

### 1.6 图像差异对比模块

```python
class ImageProcessorModule:
    name = "image_processor"
    def is_available(self) -> bool:
        try: import PIL; import numpy; return True
        except ImportError: return False

    def compute_diff(self, img1_path: str, img2_path: str) -> float:
        """计算两张截图的像素差异比率 (0.0 ~ 1.0)。"""
        im1 = Image.open(img1_path).convert("RGB")
        im2 = Image.open(img2_path).convert("RGB")
        arr1 = np.array(im1, dtype=np.float32)
        arr2 = np.array(im2, dtype=np.float32)
        return float(np.mean((arr1 - arr2) ** 2) / (255.0 ** 2))

    def crop_and_resize(self, image_path: str, box: tuple, size: tuple | None = None, output_path: str | None = None) -> bytes:
        im = Image.open(image_path)
        cropped = im.crop(box)
        if size: cropped = cropped.resize(size, Image.LANCZOS)
        if output_path: cropped.save(output_path, "JPEG", quality=85)
        buf = io.BytesIO()
        cropped.save(buf, "JPEG", quality=85)
        return buf.getvalue()
```

### 1.7 URL Handler 模块

```python
class UrlHandlerModule:
    name = "url_handler"
    def is_available(self) -> bool: return True

    def register_protocol(self, protocol: str = "clawcodex") -> bool:
        """注册 clawcodex:// URL Scheme（按 OS 平台）。"""
        if sys.platform == "linux":
            desktop_file = Path.home() / ".local/share/applications"
            desktop_file.mkdir(parents=True, exist_ok=True)
            entry = desktop_file / f"{protocol}-handler.desktop"
            entry.write_text(f"[Desktop Entry]\nType=Application\nName=ClawCodex\nExec=clawcodex %u\nMimeType=x-scheme-handler/{protocol};\n")
            os.system(f"xdg-mime default {protocol}-handler.desktop x-scheme-handler/{protocol}")
            return True
        return False

    def open_url(self, url: str) -> bool:
        return webbrowser.open(url)
```

### 1.8 依赖

- `pyaudio`（音频捕获，可选）
- `Pillow` + `numpy`（图像处理，可选）
- `pynput`（修饰键检测，可选，Linux 需 `evdev`）
- 均为 optional-dependencies，缺失时模块 `is_available()` 返回 False

## §2 进度跟踪

探索阶段，尚未开始实现。

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
| 2026-06-24 | 补全详细设计（架构+5 子模块+代码示例） | 对齐 FEATURE_PLAN.legacy.md |
