# F-64: Voice Mode 语音输入

> 状态: 🔄 进行中（接口层已完成）
> 章节: docs/feature_plan/06-ccb-benchmark/f-64-voice-mode.md
> 最后更新: 2026-06-24

## §1 设计规划

### 1.1 目标

对标 CCB Voice Mode，实现语音输入与语音交互能力。

### 1.2 已实现部分

`src/services/voice/` 已实现检测层和 STT 抽象类（共 188 行）：

| 模块 | 文件 | 状态 |
|------|------|:----:|
| 语音活动检测 | `detection.py` (114行) — VoiceActivityDetector / VoiceActivityState / VoiceActivityConfig | ✅ |
| 语音识别抽象 | `stt.py` (56行) — STTProvider 抽象类 + STTConfig + STTResult | ✅ |

### 1.3 子特性分解

| 子特性 | 描述 | 状态 | 预计工时 |
|--------|------|:----:|:--------:|
| P64-A | 运行时集成 — ASR 引擎接入 | 📋 | 3-5天 |
| P64-B | Push-to-Talk 交互 | 📋 | 2-3天 |
| P64-C | WebSocket 音频传输 | 📋 | 2-3天 |

**估算总工时**: 1-2 周

## §2 进度跟踪

### 2.1 已完成

| 日期 | 里程碑 | 涉及文件 |
|------|--------|---------|
| 2026-06 | 语音活动检测 | detection.py |
| 2026-06 | STT 抽象层 | stt.py |

### 2.2 下一步计划

运行时集成（ASR 引擎接入）

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
