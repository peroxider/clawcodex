# F-178: 认知模式混合 — 可解释的推理风格权重编排（DC-017）

> 状态: 📋 规划中  
> 设计来源: [动态上下文总览](../dynamic-context-index.md) — DC-017

## §0 元信息

| 字段 | 值 |
|------|---|
| 覆盖 DC | DC-017 认知模式混合 |
| Wave | Wave 3 / P3 |
| 前置依赖 | F-130 Profile、F-164 多视角扇出 |
| 落地形态 | CognitiveBlend 配置、权重校验、任务类型推荐表 |

## §1 设计规划

以 `analytical / creative / critical / cautious / exploratory` 的归一化权重表达推理风格。模式切换是离散的 Profile 变更；混合是在该 Profile 内连续调整权重，两者不得混用概念。

## §2 子特性与验收

| 编号 | 子特性 | 验收 |
|------|--------|------|
| P178-A | Blend schema | 权重非负且总和为 1 |
| P178-B | Prompt/agent 编排 | 每次执行记录实际生效配比 |
| P178-C | 推荐与回滚 | 任务类型有默认配比，异常时可回滚默认 Profile |

## §3 风险

配比难以解释或调试；初版仅提供固定推荐档位，禁止未经记录的在线自适应。

## §4 实施规格

**文件落点**：`extensions/cognitive_blend/{models,presets,validator,router}.py`、`tests/cognitive_blend/`。`CognitiveBlend` 使用 Decimal 或整数 basis points 表示权重，拒绝负值、未知维度和总和非 10000 的配置；初版内置 `debug`、`review`、`creative`、`default` 四套预设。

`resolve_blend(task_type, profile_id, override=None) -> ResolvedBlend` 的优先级为显式用户覆盖、已批准 Profile 覆盖、任务预设、默认值；结果和来源写入 F-177 snapshot。高风险任务强制 `critical + cautious >= 0.40`，否则 validator 拒绝编译。

实施顺序：schema/preset → F-130 Profile 适配 → F-164 投票权重适配 → 审计与回滚。验收包括：权重守恒、优先级确定、非法混合被拒绝、每次回答可查询生效配比。
