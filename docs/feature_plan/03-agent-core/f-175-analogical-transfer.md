# F-175: 类比迁移 — 结构映射与反例校验（DC-013）

> 状态: 📋 规划中  
> 设计来源: [动态上下文总览](../dynamic-context-index.md) — DC-013

## §0 元信息

| 字段 | 值 |
|------|---|
| 覆盖 DC | DC-013 类比迁移 |
| Wave | Wave 3 / P2 |
| 前置依赖 | F-166 Episodic Memory、F-158 置信度协议 |
| 落地形态 | 案例检索器 + 结构映射器 + 不可类比边界检查 |

## §1 设计规划

对新问题检索相似历史案例，但只迁移经结构映射验证的关系；输出必须区分可迁移部分、不可迁移部分和待验证假设。核心流程为：检索候选案例 → 提取问题/约束/因果结构 → 生成映射 → 执行反例检查 → 将结论标记为 `INFERRED`，直到被工具验证。

## §2 子特性与验收

| 编号 | 子特性 | 验收 |
|------|--------|------|
| P175-A | Episodic 案例检索 | 按结构标签而非关键词返回候选案例 |
| P175-B | Isomapping 校验 | 输出源—目标映射及不可迁移边界 |
| P175-C | 反例与置信度门控 | 反例存在时降级或拒绝迁移 |

## §3 风险

表面相似会导致错误迁移；必须保留反例检查，且不得将类比结果提升为 VERIFIED。

## §4 实施规格

**文件落点**：`extensions/analogical_transfer/{models,retriever,isomorphism,service}.py`、`tests/analogical_transfer/`。`Analogy` 固定包含 `source_memory_id`、`target_problem`、`mapping`、`non_transferable`、`counterexamples`、`confidence` 和 provenance。

`transfer(problem, *, max_candidates=5) -> Analogy | None` 必须先调用 F-166 的 episodic 检索，再以约束、因果关系和成功判据三项评分；任一关键映射缺失、存在未解决反例或评分低于 `0.75` 时返回 `None`。调用方只能把成功结果作为 INFERRED 证据。

实施顺序：模型与检索适配器 → 同构/反例校验器 → F-158 marker 集成 → 单元与 E2E 测试。验收包括：错误的表面类比被拒绝；输出列出不可迁移项；来源记忆可追溯；检索故障时 fail closed。
