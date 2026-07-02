# F-64: Voice Mode 语音输入

> 状态: 🔄 进行中（P64-A/B/C 已实现，待真机集成验证；P64-D MiniMax 集成规划中）
> 章节: docs/feature_plan/06-ccb-benchmark/f-64-voice-mode.md
> 最后更新: 2026-07-02

## §1 设计规划

### 1.1 目标

对标 CCB Voice Mode，实现语音输入与语音交互能力。

### 1.2 已实现部分

`clawcodex_ext/services/voice/` 已实现完整接口层 + 运行时集成（F-64 P64-A/B/C）：

| 模块 | 文件 | 状态 |
|------|------|:----:|
| 语音活动检测 | `detection.py` — VoiceActivityDetector / VoiceActivityState / VoiceActivityConfig | ✅ |
| 语音识别抽象 | `stt.py` — STTProvider 抽象类 + STTConfig + STTResult | ✅ |
| 三层门控 | `voice_mode_enabled.py` — feature flag + kill-switch + OAuth 门控 | ✅ |
| Provider 注册表 | `provider_registry.py` — STT 后端工厂注册 + 懒加载 | ✅ |
| Anthropic STT | `anthropic_stt.py` — Nova 3 WebSocket 流式传输 (P64-A + P64-C) | ✅ |
| Doubao ASR | `doubao_stt.py` — AsyncGenerator 适配器 (P64-A) | ✅ |
| 音频异步队列 | `audio_chunk_queue.py` — push→pull 异步桥接 (P64-C) | ✅ |
| 跨平台录音 | `audio_recorder.py` — PyAudio + SoX 双后端 (P64-B) | ✅ |
| Push-to-Talk | `push_to_talk.py` — 录音会话控制器 (P64-B) | ✅ |
| /voice 命令 | `clawcodex_ext/command_system/voice_command.py` — 开关 + 后端选择 | ✅ |
| Settings 持久化 | `src/config.py` set_voice_provider / set_voice_enabled | ✅ |

### 1.3 子特性分解

| 子特性 | 描述 | 状态 | 预计工时 |
|--------|------|:----:|:--------:|
| P64-A | 运行时集成 — ASR 引擎接入 | ✅ | 3-5天 |
| P64-B | Push-to-Talk 交互 | ✅ | 2-3天 |
| P64-C | WebSocket 音频传输 | ✅ | 2-3天 |
| P64-D | MiniMax 语音 API 集成规划（Realtime 双工 + T2A TTS） | 📝 设计中 | 3-5天 |

**估算总工时**: 1-2 周（P64-A/B/C 实际落地）；P64-D 预计 3-5 天规划 + 实施

## §2 进度跟踪

### 2.1 已完成

| 日期 | 里程碑 | 涉及文件 |
|------|--------|---------|
| 2026-06 | 语音活动检测 | detection.py |
| 2026-06 | STT 抽象层 | stt.py |
| 2026-07-02 | P64-A 运行时集成 (门控 + 注册表 + 双 STT provider) | voice_mode_enabled.py / provider_registry.py / anthropic_stt.py / doubao_stt.py |
| 2026-07-02 | P64-B Push-to-Talk (录音 + 会话控制器) | audio_recorder.py / push_to_talk.py |
| 2026-07-02 | P64-C WebSocket 音频传输 (异步队列 + 流式) | audio_chunk_queue.py / anthropic_stt.py |
| 2026-07-02 | /voice 命令 + settings 持久化 | voice_command.py / builtins.py / config.py / settings/types.py |
| 2026-07-02 | 单元测试 (51 用例) + 稳定性门禁通过 | tests/voice/test_voice.py |

### 2.2 验证结果

- **单元测试**：`tests/voice/test_voice.py` 51 个用例全部通过（覆盖门控、注册表、音频队列、Push-to-Talk 生命周期、/voice 命令、settings 往返、持久化接口）
- **稳定性门禁**：Stage 1-5 全部通过（343 passed；2 个 bridge 循环导入测试为基线问题，与本次改动无关）

### 2.3 下一步计划

- 真机集成验证：在具备麦克风 + OAuth 登录的环境中端到端验证 Anthropic 后端
- Doubao 凭证文件配置 + `doubaoime-asr` 可选依赖安装验证
- REPL/TUI 热键绑定：将空格键 Push-to-Talk 接入前端输入处理（当前控制器已就绪，待前端集成）
- Stage 6 perf 守卫：voice 模块懒加载已在 registry 设计中保证（工厂延迟导入），需确认 REPL 冷启动无回归

## §3 实现架构

### 3.1 三层门控（参考 CCB voiceModeEnabled.ts）

```
is_voice_available()       = feature_flag ∧ ¬kill_switch        (provider 无关)
is_voice_mode_enabled()    = feature_flag ∧ ¬kill-switch ∧ OAuth (Anthropic 路径)
is_voice_enabled()         = settings.voice_enabled             (主开关)
get_voice_provider()       = settings.voice_provider ?? "anthropic"
```

### 3.2 三后端数据流（P64-D 扩展后）

```
Anthropic:  按键 → useVoice → PyAudio/SoX → AudioChunkQueue → WebSocket → Nova 3 → 转录
Doubao:     按键 → useVoice → PyAudio/SoX → AudioChunkQueue → transcribeRealtime → 转录
MiniMax:    按键 → useVoice → PyAudio/SoX → AudioChunkQueue → Realtime WS → Realtime API → 转录（+可选 TTS 回放）
```

P64-D 详见 §5。

### 3.3 解耦落地位置

| 层 | 位置 | 说明 |
|----|------|------|
| Layer 1 (clawcodex_ext) | `clawcodex_ext/services/voice/` | 全部 voice 模块在补丁层，不侵入 src/services/voice/ |
| Layer 1 (clawcodex_ext) | `clawcodex_ext/command_system/voice_command.py` | /voice 命令在补丁层，注册到 builtins |
| src/ 最小补丁 | `src/config.py` set_voice_* + `clawcodex_ext/settings/types.py` | 仅 settings 持久化接口（遵循 set_effort 模式） |

## §4 P64-D：MiniMax 语音 API 集成规划

### 4.1 背景与选型依据

MiniMax（MiniMax）在 2026 年公开的语音产品矩阵覆盖 **TTS（T2A 系列）+ Realtime 多模态对话** 两条主线。本节规划在 F-64 现有 STT 抽象（`STTProvider` / `VoiceStreamConnection`）之上接入 MiniMax，使 CCB 用户可在不依赖 Anthropic OAuth 或 Doubao 私有凭证的前提下获得中文优先、低延迟、情感可调的语音识别与可选回复能力。

**调研结论**（截至 2026-07-02）：

| 能力 | MiniMax 公开状态 | 是否适合 F-64 直接集成 |
|------|------------------|------------------------|
| **T2A HTTP（`POST /v1/t2a_v2`）** — 文本合成语音，支持 8 个模型（`speech-2.8-hd`/`turbo`、`2.6-hd/turbo`、`02-hd/turbo`、`01-hd/turbo`），300+ 音色，30+ 语言，流式 `hex` 输出 | ✅ 公开 | ✅ 用于 **语音回复（可选）** |
| **T2A WebSocket** — 同 T2A HTTP 的低延迟流式版本，TTFA 优于 HTTP | ✅ 公开 | ✅ 备选流式通道 |
| **T2A Async** — 长文本（>3000 字符，文档示例 200,000 字符）异步合成 | ✅ 公开 | ⏳ 不在 F-64 范围，留待后续 batch-mode TTS |
| **Voice Cloning** — 上传 10s–5min MP3/M4A/WAV 样本（<20MB）克隆音色 | ✅ 公开 | ⏳ 不在 F-64 范围（需用户素材上传 UX） |
| **Realtime API（HTTP + WebSocket）** — 多模态实时对话：text/voice 输入 → text/voice 输出，超低延迟 | ✅ 公开 | ✅ **作为 P64-D 主路径**：原生支持语音输入并产出文本转录，天然替代 STT 流程 |
| **ASR/STT（独立语音转文字）** | ❌ 未公开（issue openclaw/openclaw#73957 显示官方尚未对外暴露 ASR 端点） | ⛔ 当前不可用 |

> **关键设计决策**：P64-D 不实现"传统的 STT 调用"，而是通过 **Realtime API 的语音输入 → 文本输出**模式实现"语音→文字"。Realtime API 在 MiniMax 端内置 ASR + LLM + TTS 全栈，对客户端只暴露"推 PCM → 拉文本/音频 delta"的事件流。这天然契合 F-64 Push-to-Talk 控制器的 `feed_audio → on_transcript` 数据流。

### 4.2 端点与认证

| 区域 | 端点（Realtime WebSocket） | T2A HTTP |
|------|-----------------------------|----------|
| Global | `wss://api.minimax.io/ws/realtime`（待平台文档确认） | `https://api.minimax.io/v1/t2a_v2` |
| Mainland China | `wss://api.minimaxi.chat/ws/realtime` | `https://api.minimaxi.chat/v1/t2a_v2` |
| Western US（低延迟 T2A） | — | `https://api-uw.minimax.io/v1/t2a_v2` |

**认证方式**：HTTP Bearer Token（`Authorization: Bearer <MINIMAX_API_KEY>`），不需要 OAuth。
**附加字段**：`group_id`（MiniMax 项目分组 ID）作为请求体或 URL query，用于计费隔离。
**凭证来源**：
- 环境变量 `MINIMAX_API_KEY` + `MINIMAX_GROUP_ID`（推荐，CI/headless 友好）
- 或 `~/.clawcodex/tts/minimax/credentials.json`（结构：`{"api_key": "...", "group_id": "...", "endpoint_region": "global|cn|uw"}`）

> 复用现有 `~/.clawcodex/tts/<backend>/credentials.json` 目录约定，与 Doubao 一致。

### 4.3 子特性分解

| 子特性 | 描述 | 范围 |
|--------|------|------|
| **P64-D1** | MiniMax Realtime API STT 适配器（voice-in → text-out） | **核心**：实现 `MiniMaxSTTProvider` + `MiniMaxStreamConnection`，遵循现有 `STTProvider` ABC |
| P64-D2 | MiniMax T2A 语音回复模块（可选，text → voice-out） | 扩展：用于 agent 语音回复场景（不在 F-64 必选范围内，但为未来 F-65/F-66 留口子） |
| P64-D3 | /voice 子命令扩展（`minimax` / `minimax-realtime` / `minimax-tts`） | 路由：注册到 `provider_registry`，支持 `clawcodex-dev /voice minimax` |
| P64-D4 | 配置与凭证管理（settings.voice_provider 扩展） | 配置：环境变量 + credentials.json 双源，遵循 set_voice_provider 模式 |

**P64-D1 实施步骤**（最小可用）：
1. 新增 `clawcodex_ext/services/voice/minimax_stt.py` — `MiniMaxSTTProvider` + `MiniMaxStreamConnection`
2. 注册到 `provider_registry._register_builtins()`：`register_stt_provider("minimax", _minimax_factory)`
3. 在 `voice_mode_enabled.py` 的 `VOICE_PROVIDERS` 加入 `"minimax"`
4. 在 `clawcodex_ext/command_system/voice_command.py` 加入 minimax 帮助文本
5. 单元测试：mock Realtime WebSocket，断言 `feed_audio → on_transcript` 流转
6. 集成测试（手动）：在 MiniMax 控制台获取 API key + group_id，运行端到端 Push-to-Talk

### 4.4 实现架构

#### 4.4.1 模块清单（全部在 Layer 1）

```
clawcodex_ext/services/voice/
├── minimax_stt.py            # NEW — MiniMaxSTTProvider + MiniMaxStreamConnection
├── provider_registry.py      # MOD — 注册 minimax factory
└── __init__.py               # MOD — 导出新类型

clawcodex_ext/command_system/
└── voice_command.py          # MOD — /voice 帮助文本 + minimax provider

src/config.py                 # (无改动，沿用 set_voice_provider)
clawcodex_ext/settings/types.py # (无改动，沿用 voice_provider 字段)
```

> 整个 P64-D 在 `clawcodex_ext/` 落地，**不修改 `src/`**，符合解耦原则。

#### 4.4.2 Realtime API 协议假设（待官方文档核实）

参考 OpenAI Realtime API 风格（MiniMax 文档未完全公开前先按行业惯例设计，实现时若发现差异再调整）：

| 方向 | 事件 | Payload |
|------|------|---------|
| Client → Server | `session.create` | `{model, modalities: ["text","audio"], voice, input_audio_format: "pcm16", sample_rate: 16000}` |
| Client → Server | `input_audio_buffer.append` | `{audio: <base64 PCM chunk>}` |
| Client → Server | `input_audio_buffer.commit` | `{}`（用户松开 Push-to-Talk） |
| Server → Client | `conversation.item.created` | 转录项创建 |
| Server → Client | `response.text.delta` / `response.audio.delta` | 增量文本/音频（取决于输出模态） |
| Server → Client | `response.done` | 转录完成，含 final text |

> **实现策略**：先按上述事件名实现 alpha 版本；若 MiniMax 真实事件名不同（如 `transcript.partial` / `transcript.final`），只需调整 `_handle_message` 解析器，业务流不变。

#### 4.4.3 与现有抽象的对齐

```python
# minimax_stt.py 伪代码
class MiniMaxStreamConnection:
    """Voice-in → text-out via MiniMax Realtime WebSocket."""
    
    def __init__(self, *, on_transcript, on_error, on_ready=None, config=None):
        self._on_transcript = on_transcript   # (text, is_final) -> None
        self._on_error = on_error             # (msg) -> None
        self._audio_queue = AudioChunkQueue() # 复用 P64-C
        self._ws = None
        self._final_text = ""
        self._ready_event = asyncio.Event()
        self._closed = False

    def feed_audio(self, chunk: bytes) -> None:
        # base64 编码后由 _pump_audio 异步发送 input_audio_buffer.append
        self._audio_queue.push(chunk)

    async def finalize(self) -> str:
        # 发送 input_audio_buffer.commit，await response.done，拼接 final_text
        self._audio_queue.push(None)
        if self._pump_tasks:
            await asyncio.gather(*self._pump_tasks, return_exceptions=True)
        await self.close()
        return self._final_text

class MiniMaxSTTProvider(STTProvider):
    """MiniMax Realtime API 后端 — API key 鉴权，无 OAuth 依赖。"""
    
    def __init__(self, *, endpoint: str | None = None, credentials_path: Path | None = None):
        self._endpoint = endpoint or self._resolve_endpoint()
        self._credentials_path = credentials_path or Path("~/.clawcodex/tts/minimax/credentials.json")
        self._connection: MiniMaxStreamConnection | None = None
    
    def _resolve_endpoint(self) -> str:
        # 根据 credentials.json 中的 endpoint_region 字段或 env MINIMAX_REGION 选择
        ...
    
    def _resolve_credentials(self) -> tuple[str, str]:
        # 优先 env，再 fallback 到 credentials.json
        api_key = os.environ.get("MINIMAX_API_KEY") or self._load_from_file().get("api_key")
        group_id = os.environ.get("MINIMAX_GROUP_ID") or self._load_from_file().get("group_id")
        if not api_key:
            raise MiniMaxCredentialsError("MINIMAX_API_KEY not set; configure env or credentials.json")
        return api_key, group_id
```

**关键设计要点**：
- **复用 `AudioChunkQueue`**（P64-C 抽象）—— recorder → queue → WebSocket pump 模式不变
- **复用 `STTProvider` ABC** —— Push-to-Talk 控制器与 minimax 后端零耦合
- **复用 `VoiceStreamConnection` 同款接口** —— `feed_audio / finalize / close / wait_until_ready`，控制器零修改
- **依赖懒加载** —— `websockets` 在 factory 内 import，缺包时 `get_stt_provider("minimax")` 抛 `ImportError`，由控制器提示 `pip install websockets`

### 4.5 风险与约束

| # | 风险 | 缓解策略 |
|---|------|----------|
| 1 | **MiniMax Realtime API 事件协议未完全公开** | alpha 阶段先按 OpenAI Realtime 风格实现 + 全量 mock 测试；真实联调时把协议差异收敛到 `_handle_message` 单文件，调用方不受影响 |
| 2 | **MiniMax ASR 单独端点未对外暴露** | 走 Realtime API 双工通道规避（语音输入 + 文本输出模式天然含 ASR 能力） |
| 3 | **API key + group_id 双凭证管理** | 借鉴 Doubao `credentials.json` 模式；环境变量优先，文件 fallback；凭证路径在错误消息中明示 |
| 4 | **Realtime API 流式文本延迟抖动** | `STTConfig.interim_results=True` 已默认开启；interim/final 两级回调天然支持打字机式 UI 更新 |
| 5 | **网络抖动导致 WebSocket 断连** | 在 `_pump_transcripts` 中捕获 `ConnectionClosed`，触发 `on_error` 并由控制器决定是否回退到 batch `transcribe()` 重试 |
| 6 | **MiniMax 模型/音色列表变更** | `MiniMaxSTTProvider` 暴露 `model` 参数（默认 `speech-2.8-turbo`），`/voice` 命令可覆盖；音色列表以 MiniMax 官方文档为准，不硬编码 |
| 7 | **CCB Voice Mode 文档中"minimax"与"MiniMax"命名冲突** | 文档统一使用 **MiniMax**，provider 注册名沿用小写 `minimax`；`voice_command.py` 中 user-facing 文案使用 "MiniMax (Realtime)" 明确说明 |

### 4.6 验收标准

- [ ] **功能**：`/voice minimax` 切换后端成功；按 Push-to-Talk 录制中文音频，3 秒内看到 interim 文本开始出现，松开键 1 秒内收到 final 转录
- [ ] **凭证**：未设置 `MINIMAX_API_KEY` 且 `credentials.json` 缺失时，控制器友好提示 `"Configure MINIMAX_API_KEY env or ~/.clawcodex/tts/minimax/credentials.json"`，不抛裸 `KeyError`
- [ ] **协议适配**：`_handle_message` 单文件可承载事件名差异；切换真实 MiniMax 协议只需改该文件
- [ ] **降级**：WebSocket 断连时触发 `on_error`，控制器可选择重试或切回 anthropic/doubao，不卡死
- [ ] **测试**：单元测试覆盖率 ≥ 现有 doubao_stt.py 的水平（mock WebSocket + 真实 queue 流转）
- [ ] **门禁**：Stage 1-5 全过；Stage 6 perf 守卫不退化（minimax factory 懒加载保证 REPL 冷启动无回归）
- [ ] **文档**：`/voice help` 输出包含 `minimax — MiniMax Realtime API (voice → text, API key auth)`

### 4.7 已拟定的设计决定

| # | 决定 | 理由 |
|---|------|------|
| 1 | **走 Realtime API 而非等待 ASR 独立端点** | Realtime API 已公开且原生支持 voice-in/text-out；避免阻塞 F-64 进度 |
| 2 | **provider 名 `minimax`（小写）** | 与 `anthropic` / `doubao` 风格一致；命令路径简洁 |
| 3 | **凭证支持 env + 文件双源** | 与 Doubao 一致；CI 环境更友好 |
| 4 | **复用 `AudioChunkQueue` 与 `STTProvider` ABC** | 控制器零改动，仅追加注册项；遵循项目"扩展上游 → 补丁层"原则 |
| 5 | **暂不实现 P64-D2 TTS 回放** | F-64 是 STT-only；TTS 回放属于未来"语音对话模式"（F-65/F-66），避免范围蔓延 |
| 6 | **不在 `src/` 修改** | P64-D 全模块落在 `clawcodex_ext/`，符合解耦黄金法则 #1 |
| 7 | **WebSocket 协议假设允许 alpha 偏离** | 优先把架构/抽象/凭证/UI 落地，协议细节通过 `_handle_message` 单点适配；后续联调时收敛 |

### 4.8 依赖与协同

- **上游依赖**：`extensions/providers_ext/litellm_provider/` 不涉及（MiniMax 不通过 LiteLLM 暴露语音）；`clawcodex_ext/services/voice/` 是核心宿主
- **协同特性**：
  - **F-37 PR Review Auto-Fix** — 评审 PR 时可用 MiniMax 做演示（待规划）
  - **F-65/F-66 语音对话/ACP 协议** — P64-D2 TTS 回放将直接复用 P64-D 的 T2A 凭证
  - **Stage 6 perf** — minimax factory 必须在 `provider_registry._register_builtins` 中懒加载，禁止模块级 import
- **待澄清问题**（提请 P64-D 实施时确认）：
  1. MiniMax Realtime API WebSocket 实际事件名是否与 OpenAI Realtime 一致？
  2. `group_id` 是否必填？是否在 URL query 还是 header？
  3. 流式音频编码是 PCM16 还是 Opus？sample_rate 默认多少？
  4. 是否支持 function calling / tool use（未来若要 agent 双工语音对话）？

## §5 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
| 2026-07-02 | P64-A/B/C 全部实现 + 单元测试 + 门禁通过 | F-64 落地 |
| 2026-07-02 | 新增 §4 P64-D MiniMax 语音 API 集成规划（Realtime API 主路径 + T2A 可选回复） | MiniMax 调研 + F-64 扩展规划 |
