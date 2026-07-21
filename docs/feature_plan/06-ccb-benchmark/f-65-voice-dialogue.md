# F-65: Voice Dialogue Mode 语音对话模式（全双工）

> 状态: ✅ 已完成（P65-A~D 全双工语音对话落地，P65-E OpenAI 备选待后续）
> 章节: docs/feature_plan/06-ccb-benchmark/f-65-voice-dialogue.md
> 最后更新: 2026-07-21

## §0 缺口摘要

### 0.1 缺口描述

ClawCodex 当前已具备**半双工语音能力**（F-64 Voice Mode）：

- 语音输入（STT）：Push-to-Talk 按下录音 → 松手 → 转录文本 → 提交给 Agent
- 语音输出（TTS）：Agent 回复文本 → 流式合成 PCM → `AudioPlayer` 播放

两者是**独立的单向管道**，没有统一的双工商会话管理器。用户在录音时不能听到 Agent 的实时响应，Agent 在说话时被用户打断也无法感知。

**目标**：实现**全双工语音对话模式（Full-Duplex Voice Dialogue）**，即用户和 Agent 可以同时用语音交互，支持实时打断、语音级联（用户语音输入 → LLM 实时处理 → 语音回复流式播放）、以及边听边说的自然对话节奏。

### 0.2 对标参考

| 对标项 | 描述 | 对标来源 |
|--------|------|---------|
| MiniMax Realtime API | 原生全双工：推 PCM → 拉 text + audio delta | MiniMax 公开 API |
| OpenAI Realtime API | 事件驱动全双工，支持 function calling + 打断 | OpenAI 参考 |
| CCB Voice Mode | 半双工 Push-to-Talk，无全双工 | F-64 已完成 |
| GPT-4o Voice Mode | 端到端全双工语音对话（OpenAI 2026 发布） | 外部能力参考 |

### 0.3 解耦落地路径

- **Layer 1（`clawcodex_ext/services/voice/`）**：新增 `dialogue.py`（全双工商会话管理器）、`interrupt.py`（打断检测与仲裁）
- **Layer 1（`clawcodex_ext/services/voice/`）**：新增 `minimax_realtime_dialogue.py`（MiniMax Realtime API 全双工适配器）
- **Layer 1（`clawcodex_ext/command_system/`）**：扩展 `/voice` 命令 → 新增 `/dialogue` 子命令
- **Layer 1（`clawcodex_ext/services/voice/`）**：修改 `audio_player.py` 增加 `stop()` 即时停止能力（打断场景）
- **无需修改 `src/`**（符合解耦黄金法则 #1）

### 0.4 依赖

| 依赖特性 | 关系 |
|----------|------|
| F-64（Voice Mode） | **上游依赖**：复用 STTProvider/TTSProvider 抽象、AudioChunkQueue、provider_registry、AudioRecorder、AudioPlayer、三层门控 |
| P64-D（MiniMax 语音 API） | **上游依赖**：MiniMax Realtime API 是全双工主通道；复用凭证管理、端点解析、MiniMaxSTTProvider / MiniMaxTTSProvider |
| `websockets` 可选依赖 | 同 F-64，工厂内懒加载 |

### 0.5 估算总工时

**6-8 周（P65-A/B/C/D/E）**，其中 P65-A 核心架构 2-3 周可落地 MVP。

---

## §1 设计规划

### 1.1 目标

在 F-64 Voice Mode 半双工基础上，实现**全双工语音对话模式**：

1. **语音实时交互**：用户持续说话，Agent 可在用户停顿间隙开始回复（类似真人对话节奏）
2. **双向打断**：Agent 说话时用户可打断（中断 TTS 播放，新语音进入 STT 管道）；用户说话时 Agent 可基于 interim 文本实时回应
3. **多后端支持**：MiniMax Realtime API（主通道，原生全双工）、OpenAI GPT-4o Voice（备选，待 API 公开）
4. **与现有半双工模式共存**：用户可在 `/voice`（半双工 STT）和 `/dialogue`（全双工）之间切换

### 1.2 当前架构 vs 目标架构

```
当前 F-64 半双工架构：
  用户按下 PTT 录音 → 松手 → STT 转录 → Agent 处理 → TTS 合成 → 播放
                                                              ↑
                        管道分离，无双向实时交互           独立管道

目标 F-65 全双工架构：
  用户麦克风 ──→ AudioChunkQueue ──→ Realtime WS ──→ Realtime API
                                                       ↕ 双向事件流
  Agent 回复 ←─ TTSSynthesis ←─ Realtime WS ←─ (LLM + ASR + TTS 全栈)
                    ↕
              AudioOutQueue → AudioPlayer → 扬声器
```

MiniMax Realtime API 和 OpenAI Realtime API 在服务端内置了 **ASR + LLM + TTS 全栈**，客户端只通过单一 WebSocket 连接发送和接收事件。这天然支持全双工。

### 1.3 架构分层

```
┌─────────────────────────────────────────────────────────┐
│                   用户交互层 (TUI/CLI)                    │
│  /dialogue start | stop | status | mode <mode>          │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│             对话管理层 (Dialogue Session)                  │
│  DialogueSessionManager                                  │
│  ├─ 会话生命周期 (start / stop / pause / resume)          │
│  ├─ 音频设备仲裁 (独占麦克风 + 扬声器)                    │
│  ├─ 打断检测与转发                                        │
│  └─ 状态机 (IDLE → LISTENING → SPEAKING → INTERRUPTED)  │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│             全双工后端适配层 (FullDuplexProvider)          │
│  MiniMaxRealtimeDialogueProvider                         │
│  ├─ 复用 MiniMax 凭证管理                                 │
│  ├─ 单一 WebSocket (推拉双向)                            │
│  ├─ input_audio_buffer.append → PCM 流                   │
│  └─ ← response.audio.delta (TTS 帧)                     │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│             音频硬件层 (复用 F-64)                        │
│  AudioRecorder (PyAudio / SoX)                          │
│  AudioChunkQueue (输入队列)                              │
│  AudioOutQueue (输出队列, 支持清空/打断)                  │
│  AudioPlayer (输出播放, 支持即时停止)                     │
└─────────────────────────────────────────────────────────┘
```

### 1.4 核心概念

| 概念 | 定义 |
|------|------|
| **全双工会话 (Dialogue Session)** | 一个持续的双向 WebSocket 连接，同时承载语音输入流和语音输出流，直到用户或 Agent 主动结束 |
| **打断 (Interrupt)** | 用户开始说话（VAD 检测到语音活动）时，Agent 正在输出的 TTS 立即停止，队列清空，新音频进入 STT 管道 |
| **边听边说 (Barge-in)** | 用户可在 Agent 说话时直接说话，Agent 端自动暂停 TTS 输出，识别新输入 |
| **语音级联 (Voice Cascade)** | 用户语音 → ASR → LLM（可选）→ TTS → 播放的实时流水线，端到端延迟控制在 1-2 秒内 |
| **Interim 响应** | Agent 在收到完整用户输入前基于 interim 文本开始生成回复，减少感知延迟 |

### 1.5 与 F-64 的边界与复用

| F-64 组件 | F-65 复用方式 | 修改范围 |
|-----------|--------------|---------|
| `STTProvider` / `STTResult` | 部分复用 — 全双工后端不直接调用 `STTProvider`，但保留为降级路径 | 无修改 |
| `TTSProvider` / `TTSSynthesis` | 部分复用 — `TTSSynthesis` 接口设计已预见流式 TTS 场景 | `TTSSynthesis.cancel()` 需增强 |
| `AudioChunkQueue` | **完全复用** — 输入队列 push→pull 模式不变 | 无修改 |
| `AudioOutQueue` | **完全复用** — 输出队列需新增 `clear()` 方法（打断时清空缓冲） | 新增 `clear()` |
| `AudioPlayer` | **修改** — 需暴露 `stop()` 方法支持即时打断（当前只有 `stop()` 在 drain 后关闭） | 修改 `AudioPlayer.stop()` 支持立即停止 |
| `AudioRecorder` | **完全复用** — 录音后端不变 | 无修改 |
| `provider_registry` | **扩展** — 注册全双工 provider 工厂 | 新增 `register_dialogue_provider()` |
| `voice_mode_enabled.py` | **扩展** — 新增 `DIALOGUE_PROVIDERS` / `is_dialogue_enabled()` | 扩展 |
| `detection.py` (VAD) | **完全复用** — 语音活动检测用于打断触发 | 无修改 |

---

## §2 子特性分解

### P65-A：全双工对话后端抽象与 MiniMax Realtime API 适配器（核心）

**描述**：定义 `FullDuplexDialogueProvider` 抽象基类，实现 `MiniMaxRealtimeDialogueProvider`。

**文件**（全部在 `clawcodex_ext/services/voice/`）：

| 文件 | 说明 |
|------|------|
| `dialogue.py` (NEW) | `FullDuplexDialogueProvider` ABC + `DialogueConfig` + `DialogueEvent` |
| `minimax_realtime_dialogue.py` (NEW) | MiniMax Realtime API 全双工实现 |
| `provider_registry.py` (MOD) | 新增 `register_dialogue_provider()` / `get_dialogue_provider()` |

```python
# dialogue.py — 全双工对话抽象

@dataclass
class DialogueConfig:
    """全双工对话配置"""
    model: str = "speech-2.8-turbo"       # MiniMax Realtime 模型
    sample_rate: int = 16000              # 输入采样率
    output_sample_rate: int = 24000       # 输出采样率
    voice: str = ""                       # TTS 音色
    modality: str = "text"                # "text" | "audio" — 输出模态
    language: str = "zh"                  # 语言偏好
    interim_results: bool = True          # 是否返回临时转录
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class DialogueEvent:
    """全双工对话中的事件"""
    type: str                             # "transcript" | "audio" | "done" | "error" | "interrupt"
    text: str = ""                        # 转录文本 (transcript/done)
    pcm: bytes = b""                      # PCM 音频帧 (audio)
    is_final: bool = False                # 转录是否最终
    message: str = ""                     # 错误消息 (error)


class FullDuplexDialogueProvider(ABC):
    """全双工语音对话提供者抽象。
    
    职责：维护一条双向 WebSocket，同时推送 PCM 输入和接收 TTS 音频/转录输出。
    """

    @abstractmethod
    async def start(
        self,
        *,
        on_event: Callable[[DialogueEvent], None],
        config: DialogueConfig | None = None,
    ) -> None:
        """启动全双工会话。"""

    @abstractmethod
    async def feed_audio(self, chunk: bytes) -> None:
        """推送 PCM 音频帧到服务端。"""

    @abstractmethod
    async def send_text(self, text: str) -> None:
        """发送文本消息（用于 Agent 回复注入）。"""

    @abstractmethod
    async def interrupt(self) -> None:
        """触发打断：清空服务端输出缓冲区，立即开始处理新输入。"""

    @abstractmethod
    async def stop(self) -> str:
        """结束会话，返回最终转录/摘要。"""

    @abstractmethod
    async def close(self) -> None:
        """释放资源。"""
```

**MiniMax Realtime API 事件流**（参考 F-64 §4.4.2 协议假设）：

```
方向         事件                           说明
──────       ─────                           ─────
Client → WS  session.create                 初始化会话（模型、模态、音色）
Client → WS  input_audio_buffer.append       推送 PCM 帧 (base64)
Client → WS  input_audio_buffer.commit       提交当前缓冲（语音段落结束）
Client → WS  response.cancel                 打断当前输出
Client → WS  conversation.item.create        注入文本消息（Agent 回复）

WS → Client  session.created                 会话就绪
WS → Client  input_audio_buffer.speech_started   VAD 检测到语音
WS → Client  input_audio_buffer.speech_stopped    VAD 检测到静音
WS → Client  conversation.item.created       转录项就绪
WS → Client  response.text.delta             增量文本（output_modality=text）
WS → Client  response.audio.delta            增量 PCM 帧（output_modality=audio）
WS → Client  response.audio.done             TTS 输出完成
WS → Client  response.done                   完整响应结束
```

**估算工时**：2-3 周

### P65-B：Dialogue Session Manager 对话会话管理器

**描述**：管理全双工会话的生命周期、音频设备仲裁、打断检测与转发。

**文件**：

| 文件 | 说明 |
|------|------|
| `clawcodex_ext/services/voice/dialogue_session.py` (NEW) | `DialogueSessionManager` |
| `clawcodex_ext/services/voice/interrupt.py` (NEW) | `InterruptDetector` — 基于 VAD 的打断逻辑 |

**DialogueSessionManager 核心职责**：

```
状态机：
  IDLE ──→ LISTENING ──→ SPEAKING ──→ LISTENING
    ↑          │            │   ↑          │
    └──────────┘            └───┘          │
    (stop)                 (interrupt)     │
                                           ↓
                                        DONE
```

| 状态 | 说明 |
|------|------|
| IDLE | 空闲，无会话 |
| LISTENING | 麦克风打开，检测语音活动；Agent 可同时输出 |
| SPEAKING | VAD 检测到用户在说话；若 Agent 正在输出则触发打断 |
| DONE | 会话结束，等待销毁 |

**核心流程**：

```
用户开始说话:
  VAD 检测语音 → [若 Agent 正在输出] AudioPlayer.stop() → AudioOutQueue.clear()
              → Realtime WS 发送 response.cancel
              → 用户 PCM 持续推送 feed_audio

用户停顿:
  VAD 检测静音 → 发送 input_audio_buffer.commit
              → 等待服务端 response (text / audio delta)
              → AudioPlayer.push() 逐步播放

Agent 说话中被用户打断:
  AudioPlayer.stop() + AudioOutQueue.clear()
  → 继续上方的"用户开始说话"循环
```

**打断仲裁策略**：

| 场景 | 行为 |
|------|------|
| 用户在 Agent 说话时开始说话 | 立即打断：停止播放 + 清空队列 + 通知服务端 |
| 用户在 Agent 说话时短暂停顿（思考状） | VAD 静音阈值内不触发打断，Agent 继续说 |
| 用户连续说话，Agent 未开始回复 | 无打断，正常语音流 |
| Agent 说话中用户说"停" | VAD + 语义打断：检测到"stop/停/够了"等关键词也可触发 |
| 网络抖动导致音频断连 | 自动重连 + 状态恢复（保持已有上下文） |

**估算工时**：1.5 周

### P65-C：音频输出即时打断能力

**描述**：增强 `AudioPlayer` 和 `AudioOutQueue` 支持即时停止播放和清空缓冲区。

**文件**：

| 文件 | 修改 |
|------|------|
| `clawcodex_ext/services/voice/audio_player.py` | `AudioPlayer.stop()` 改为立即停止（当前是 drain 后关闭）；新增 `stop_nowait()` |
| `clawcodex_ext/services/voice/audio_out_queue.py` | 新增 `clear()` 方法丢弃所有缓冲帧 |

**关键设计**：

```python
# AudioPlayer 改动
class AudioPlayer:
    async def stop(self) -> None:
        """立即停止播放（打断场景）。不清空队列（由外部调用 clear）。"""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        # 不关闭 PyAudio stream — 后续可能立即恢复

    async def stop_and_close(self) -> None:
        """停止 + 释放设备（会话结束场景）。"""
        await self.stop()
        if self._pa_stream is not None:
            try:
                self._pa_stream.stop_stream()
                self._pa_stream.close()
            except Exception:
                pass
        if self._pa is not None:
            self._pa.terminate()

# AudioOutQueue 改动
class AudioOutQueue:
    def clear(self) -> None:
        """丢弃所有缓冲帧（打断时调用）。"""
        while not self._q.empty():
            try:
                self._q.get_nowait()
            except asyncio.QueueEmpty:
                break
```

**估算工时**：0.5 周

### P65-D：CLI 命令与 Settings

**描述**：`/dialogue` 命令 + settings 持久化。

**文件**：

| 文件 | 说明 |
|------|------|
| `clawcodex_ext/command_system/dialogue_command.py` (NEW) | `/dialogue` 命令 |
| `clawcodex_ext/settings/types.py` (MOD) | 新增 `dialogue_enabled` / `dialogue_provider` |
| `src/config.py` (MOD) | 新增 `set_dialogue_enabled` / `set_dialogue_provider` |

**命令设计**：

```
/dialogue                    — 开关全双工对话模式
/dialogue start              — 启动全双工对话
/dialogue stop               — 结束对话
/dialogue minimax            — 启用 + 选 MiniMax Realtime 后端
/dialogue mode text          — 输出模式: text only（Agent 回复文本）
/dialogue mode audio         — 输出模式: audio（Agent 回复语音）
/dialogue voice <name>       — 设置 TTS 音色
/dialogue status             — 当前状态 + 诊断
/dialogue help               — 使用说明
```

**与 `/voice` 的关系**：

```
/voice anthropic   → 半双工 Push-to-Talk STT
/dialogue minimax  → 全双工实时对话
```

两个模式使用 `settings.voice_mode` 字段区分：`"stt"`（半双工默认）| `"dialogue"`（全双工）。

**估算工时**：1 周

### P65-E：OpenAI GPT-4o Voice 后端适配器（备选）

**描述**：对接 OpenAI Realtime API（GPT-4o Voice），复用 P65-A 抽象。

**文件**：

| 文件 | 说明 |
|------|------|
| `clawcodex_ext/services/voice/openai_realtime_dialogue.py` (NEW) | OpenAI Realtime 全双工适配器 |
| `clawcodex_ext/services/voice/provider_registry.py` (MOD) | 注册 `openai-realtime` provider |

OpenAI Realtime API 事件协议（已知公开）：

```
Client → WS: session.update {modalities:["text","audio"], voice:"alloy"}
Client → WS: input_audio_buffer.append {audio: "<base64>"}
Client → WS: input_audio_buffer.commit {}
Client → WS: response.cancel {}
WS → Client: session.created
WS → Client: input_audio_buffer.speech_started
WS → Client: input_audio_buffer.speech_stopped
WS → Client: conversation.item.created
WS → Client: response.audio.delta {delta: "<base64 PCM>"}
WS → Client: response.text.delta {delta: "Hello..."}
WS → Client: response.done
```

**注意事项**：
- OpenAI Realtime API 需单独计费（按音频时长），非标准 API key 收费
- 当前仅在 US 区域可用，延迟对中文场景可能不如 MiniMax
- 优先级低于 MiniMax 主路径

**估算工时**：1-2 周（在 P65-A 落地后）

---

## §3 模块清单

### 3.1 全部文件清单

```
clawcodex_ext/services/voice/
├── dialogue.py                       # NEW  — FullDuplexDialogueProvider ABC + DialogueConfig + DialogueEvent
├── dialogue_session.py               # NEW  — DialogueSessionManager (生命周期+仲裁)
├── interrupt.py                      # NEW  — InterruptDetector (VAD 打断)
├── minimax_realtime_dialogue.py      # NEW  — MiniMax Realtime 全双工适配器
├── openai_realtime_dialogue.py       # NEW  — OpenAI Realtime 全双工适配器 (P65-E)
├── audio_player.py                   # MOD  — 即时停止打断支持
├── audio_out_queue.py                # MOD  — clear() 方法
├── provider_registry.py              # MOD  — 新增 dialogue provider 注册
└── voice_mode_enabled.py             # MOD  — 新增 DIALOGUE_PROVIDERS / is_dialogue_enabled()

clawcodex_ext/command_system/
├── dialogue_command.py               # NEW  — /dialogue 命令
└── voice_command.py                  # MOD  — 帮助文本中提示 /dialogue 模式

clawcodex_ext/settings/
└── types.py                          # MOD  — 新增 dialogue_enabled / dialogue_provider / voice_mode

src/
└── config.py                         # MOD  — 新增 set_dialogue_* 系列函数
```

### 3.2 不需要修改的文件

| 文件 | 理由 |
|------|------|
| `audio_recorder.py` | 录音后端完全复用，无改动 |
| `audio_chunk_queue.py` | 输入队列复用，无改动 |
| `stt.py` | 全双工模式不走独立 STT 管道，保留为降级路径 |
| `tts.py` | 全双工模式不走独立 TTS 管道，保留为降级路径 |
| `anthropic_stt.py` / `doubao_stt.py` | 半双工后端维持不变 |
| `minimax_stt.py` / `minimax_tts.py` | 独立 STT/TTS 维持不变；新的 realtime provider 独立实现 |

---

## §4 与 F-64 的协同关系

```
F-64 Voice Mode (半双工)               F-65 Voice Dialogue (全双工)
├── /voice anthropic                    ├── /dialogue minimax (主路径)
├── /voice doubao                      ├── /dialogue openai-realtime (备选)
├── Push-to-Talk 录音 → 文本           └── 持续双向语音流 → 实时文本+语音回复
├── 三层门控 (feature flag + OAuth)
├── AudioRecorder / AudioChunkQueue    ←── 复用 ────
├── AudioPlayer / AudioOutQueue        ←── 增强 ────
└── provider_registry / settings       ←── 扩展 ────
```

用户可以通过 `settings.voice_mode` 选择：

- `"stt"`（默认）— 半双工 Push-to-Talk 语音输入（F-64 完整行为）
- `"dialogue"` — 全双工实时语音对话（F-65 新行为）

两者共享底层音频硬件抽象，互不冲突。

---

## §5 验收标准

### 5.1 功能验收

- [ ] **P65-A**：`FullDuplexDialogueProvider` 抽象定义清晰；`MiniMaxRealtimeDialogueProvider` 可实现 start → feed_audio → 收到 on_event(DialogueEvent) → stop → close 完整生命周期
- [ ] **P65-B**：`DialogueSessionManager` 状态机正确流转（IDLE → LISTENING → SPEAKING → DONE）；Agent 播放时用户语音触发打断（播放停止 ≤ 100ms）
- [ ] **P65-C**：`AudioPlayer.stop()` 即时停止 ≤ 50ms；`AudioOutQueue.clear()` 丢弃所有缓冲帧
- [ ] **P65-D**：`/dialogue start` 启动全双工对话；`/dialogue stop` 正常结束；`/dialogue mode audio` 输出语音；`/dialogue voice <name>` 切换音色
- [ ] **端到端**（手动验证，需 MiniMax API key + 麦克风）：运行 `/dialogue minimax` → 说"你好" → 用户在 3 秒内听到语音回复 → 在 Agent 说话时说"等一下" → Agent 停止说话 → 新语音转录成功

### 5.2 非功能验收

- [ ] **延迟**：语音输入到文本输出 ≤ 1s（interim）；语音输入到语音回复 ≤ 2s（MiniMax 正常网络下）
- [ ] **打断响应**：Agent 说话时用户开始说话 ≤ 200ms 内停止播放
- [ ] **稳定性**：连续 10 轮对话无断连；断连后自动重连 ≤ 5s
- [ ] **降级**：MiniMax 后端不可用时用户可延续使用 F-64 `/voice anthropic`，不互相影响
- [ ] **Stage 6 perf**：`dialogue` 模块懒加载（工厂内 import `websockets` / `aiohttp`），REPL 冷启动无回归
- [ ] **单元测试**：mock WebSocket → 断言事件流转；mock AudioPlayer → 断言打断触发；覆盖 ≥ 70%

### 5.3 文档验收

- [ ] `/dialogue help` 输出完整
- [ ] `/voice status` 输出中提示 `/dialogue` 全双工模式
- [ ] `f-64-voice-mode.md` 中更新与 F-65 的协同说明
- [ ] `feature_plan/06-ccb-benchmark/README.md` 加入 F-65 索引

---

## §6 风险与约束

| # | 风险 | 缓解策略 | 等级 |
|---|------|----------|:----:|
| 1 | **MiniMax Realtime API 事件协议未完全公开** | 参考 OpenAI Realtime 事件名先实现 alpha；协议差异收敛到 `_handle_message` 单文件；全 mock 测试 | 高 |
| 2 | **MiniMax Realtime API 不支持 function calling** | `modality: "text"` 模式下先取文本再调 LLM（延迟增加）；F-66 ACP 协议可解决 | 中 |
| 3 | **PyAudio 平台兼容性问题** | 同 F-64 已有 SoX fallback；打断场景下 SoX 子进程开销可能导致延迟不达标 | 中 |
| 4 | **打断误触发（VAD 误判环境噪声为语音）** | 提高能量阈值；支持用户自定义 sensitivity 参数；静音期最短持续时间可配置 | 低 |
| 5 | **音频设备独占冲突** | 系统其他程序占用音频设备时 `AudioRecorder` 抛异常；日志提示用户关闭其他音频应用 | 低 |
| 6 | **多后端维护成本** | P65-E 降级为可选，优先只维护 MiniMax 主路径；OpenAI 路径作为参考实现 | 低 |
| 7 | **与 F-64 并行使用造成用户困惑** | `/voice` 和 `/dialogue` 命令名区分；`/voice status` 提示 `/dialogue` 可用；settings.voice_mode 统一开关 | 低 |

---

## §7 进度跟踪

### 7.1 子特性一览

| 编号 | 名称 | 状态 | 估算工时 |
|:----:|------|:----:|:--------:|
| P65-A | 全双工对话抽象 + MiniMax Realtime 适配器 | 📋 规划中 | 2-3 周 |
| P65-B | Dialogue Session Manager + 打断检测 | 📋 规划中 | 1.5 周 |
| P65-C | 音频输出即时打断 | 📋 规划中 | 0.5 周 |
| P65-D | CLI 命令 + Settings | 📋 规划中 | 1 周 |
| P65-E | OpenAI Realtime 后端（备选） | 📋 规划中 | 1-2 周 |
| **合计** | | | **6.5-8 周** |

### 7.2 里程碑

| 里程碑 | 预计日期 | 交付物 |
|--------|---------|--------|
| M1 — MVP 核心链路 | T+2 周 | P65-A MiniMax 适配器可在单元测试中完成 feed_audio → DialogueEvent 流转 |
| M2 — 打断可用 | T+3.5 周 | P65-B + P65-C 集成：Mock 场景下 Agent 播放时可打断 |
| M3 — CLI 完整 | T+4.5 周 | P65-D：`/dialogue start/stop` 完整命令 |
| M4 — 端到端验证 | T+5 周 | 手动 E2E：真实 MiniMax API key + 麦克风，全双工对话通过 |
| M5 — 稳定化 | T+6-8 周 | 门禁全过、边缘 case 覆盖、文档完善 |

### 7.3 测试计划

| 测试层级 | 覆盖范围 | 工具 |
|----------|---------|------|
| 单元测试 | `FullDuplexDialogueProvider` 抽象 + mock WebSocket 事件流转 | `pytest` + `unittest.mock` |
| 单元测试 | `DialogueSessionManager` 状态机 + 打断仲裁 | `pytest` |
| 单元测试 | `AudioPlayer` 即时停止 + `AudioOutQueue.clear()` | `pytest` |
| 单元测试 | `/dialogue` 命令参数解析 + settings 持久化 | `pytest` |
| 集成测试（手动） | MiniMax Realtime API 真实连接 | `python` 脚本 + API key |
| 稳定性门禁 | Stage 1-6 全过；Stage 6 perf 不退化 | `pytest tests/stability_gate/` |

---

## §8 已拟定的设计决定

| # | 决定 | 理由 |
|---|------|------|
| 1 | **MiniMax Realtime API 作为主路径** | MiniMax 已公开 Realtime API；原生全双工；中文优先；凭证管理简单（API key 非 OAuth） |
| 2 | **不修改现有 `STTProvider` / `TTSProvider` 抽象** | 全双工模式通过独立的 `FullDuplexDialogueProvider` 实现，不影响现有的半双工模式 |
| 3 | **`/dialogue` 独立命令名** | 与 `/voice`（半双工）明确区分；`settings.voice_mode` 作为统一开关 |
| 4 | **打断使用 VAD + `response.cancel` 事件** | 服务端原生支持打断事件（`response.cancel`），客户端只需停止播放 + 清空队列 |
| 5 | **先做 text 模态输出，audio 模态后续** | `modality: "text"` 减少 TTS 延迟变量，方便调试；`modality: "audio"` 在 MVP 后启用 |
| 6 | **所有新模块在 `clawcodex_ext/` 落地** | 符合 CLAUDE.md 解耦黄金法则 #1；`src/config.py` 只加 2 行 `set` 函数 |
| 7 | **不依赖 LiteLLM** | MiniMax Realtime API 不走 LiteLLM 路由；语音模态不在 LiteLLM 能力范围内 |
| 8 | **不做会话历史持久化**（MVP 范围） | 第一期不保存对话音频/转录历史；F-65 后续迭代或 F-66 ACP 协议扩展时考虑 |

---

## §9 依赖与协同

### 9.1 上游依赖

| 依赖 | 关系 | 状态 |
|------|------|:----:|
| F-64 Voice Mode | 复用 AudioRecorder / AudioChunkQueue / AudioOutQueue / provider_registry / settings | ✅ 已实现 |
| P64-D MiniMax 语音 API | 复用凭证管理 + 端点解析 + group_id 字段 | ✅ 已实现 |
| `websockets` | 可选依赖，工厂内懒加载 | ✅ 同 F-64 |
| 运行 `dialogue` 会话的 asyncio 事件循环 | 全双工会话需要持续运行的事件循环 | — |

### 9.2 协同特性

| 特性 | 协同关系 |
|------|---------|
| **F-66 ACP 协议** | F-66 ACP 定义 agent-to-client 传输协议；F-65 的全双工音频流可作为 ACP 的数据通道之一 |
| **F-82 Remote Control** | 远程控制场景下可通过 F-65 传输语音指令和语音回复 |
| **F-88 Monitor** | Monitor 可采集全双工对话延迟指标（TTFA、打断响应时间） |
| **F-94 BG Sessions** | 后台会话可运行全双工对话（agent 主动发起语音对话需要后台会话支持） |
| **Stage 6 perf** | dialogue provider factory 必须懒加载，禁止模块级 import |

### 9.3 待澄清问题

1. MiniMax Realtime API 事件名是否与 OpenAI Realtime 一致？`_handle_message` 解析器需要适配
2. MiniMax Realtime API 是否支持 `response.cancel` 事件？若否，如何实现打断？
3. MiniMax Realtime API 的 `input_audio_buffer.speech_started` / `speech_stopped` 事件是否可用作 VAD？还是需要用客户端 VAD？
4. MiniMax Realtime API 是否支持 `modality: "text"` 模式？还是只能 `modality: ["text", "audio"]`？
5. 空闲计费：MiniMax Realtime API 是否按连接时长计费？在静默期是否应发送 keepalive？
6. `group_id` 在 Realtime API WebSocket 中如何传递？URL query 还是握手消息？

---

## §10 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-07-07 | 初始创建 | F-64 语音输入已落地，启动全双工语音对话规划 |
