# F-177: 上下文时序回放 — Snapshot、diff 与分支探索（DC-015）

> 状态: 📋 规划中  
> 设计来源: [动态上下文总览](../dynamic-context-index.md) — DC-015

## §0 元信息

| 字段 | 值 |
|------|---|
| 覆盖 DC | DC-015 上下文时序回放 |
| Wave | Wave 3 / P2 |
| 前置依赖 | F-119 Prompt Dump、F-130 切换历史 |
| 落地形态 | ContextSnapshot 存储、timeline API、diff/replay CLI |

## §1 设计规划

在每轮结束、模式切换和关键工具调用时记录上下文哈希、有效 section、模式栈和决策引用。`replay(turn_id)` 重建当时的可用上下文，`diff(t1, t2)` 展示变化，`branch_from` 用于受控的替代路径探索。

## §2 子特性与验收

| 编号 | 子特性 | 验收 |
|------|--------|------|
| P177-A | Snapshot 生命周期 | 关键事件均产生可定位 snapshot |
| P177-B | 回放与 diff | 可重建有效 section 并显示差异 |
| P177-C | 外部状态标记 | 文件/网络等不可重放依赖明确标注 |

## §3 风险

快照会造成存储膨胀；默认保存 hash 与 section 引用，内容由 registry 反查，并配置保留期限。

## §4 实施规格

**文件落点**：`extensions/context_timeline/{models,store,recorder,replay}.py`、`tests/context_timeline/`。`ContextSnapshot` 至少记录 `session_id`、`turn_id`、`event_kind`、`context_hash`、section refs、mode stack、decision refs、外部依赖摘要与 schema version；采用 NDJSON append-only 存储并按 session 建索引。

Recorder 挂接 F-102 的 `post_llm`、工具完成和 F-130 切换事件。`replay(session_id, turn_id, strict=True)` 在 section hash 不一致或外部依赖不可用时返回明确的 `stale_dependencies`，严格模式不得伪造原始运行环境；`diff` 只比较可重建字段。

实施顺序：schema/原子写入 → recorder → replay/diff CLI → retention/脱敏。验收包括：事件顺序稳定、损坏尾行可恢复、删除会话后索引同步清理、外部状态漂移清晰展示。
