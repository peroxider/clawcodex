# F-181: 上下文压力测试 — Context Pack 的对抗性质量门禁（DC-019）

> 状态: 📋 规划中  
> 设计来源: [动态上下文总览](../dynamic-context-index.md) — DC-019

## §0 元信息

| 字段 | 值 |
|------|---|
| 覆盖 DC | DC-019 上下文压力测试 |
| Wave | Wave 3 / P3 |
| 前置依赖 | F-179 Context-as-Code、F-158 抗幻觉基线 |
| 落地形态 | 对抗用例库、执行器、安全行为判定器、CI 报告 |

## §1 设计规划

在 Context Pack 合并或发布前，以历史幻觉模式和对抗模板生成输入。若输出未满足预期安全行为（声明未知、请求验证或拒绝无证据断言），则测试失败并给出最小复现用例。

## §2 子特性与验收

| 编号 | 子特性 | 验收 |
|------|--------|------|
| P181-A | 用例协议与模式库 | 每例定义诱导输入、预期安全行为与标签 |
| P181-B | 判定器与报告 | 输出失败用例、模型回复和违规规则 |
| P181-C | CI 门禁 | Pack 变更在压力测试失败时不可发布 |

## §3 风险

测试集可能偏离真实风险；持续从已审核的生产失败中扩充用例，并保留人工复核出口。

## §4 实施规格

**文件落点**：`extensions/context_stress/{models,corpus,runner,assertions,reporter}.py`、`tests/context_stress/`；用例保存在 `.ctx/stress/*.yaml`。每例必须声明输入、风险标签、允许工具、预期安全动作、禁止断言与人工审核状态，禁止以模型自评作为唯一判据。

`ctx test <pack> --suite <name>` 在隔离会话编译 F-179 pack，记录模型、pack hash、工具轨迹和断言结果。`SafeBehaviorAssertion` 至少检查：未知事实不被断言、强制验证规则触发、权限不越界、拒绝提示注入；出现 blocker 失败时 CI 返回非零。

实施顺序：用例 schema → deterministic assertions → runner/report JSON → CI gate → 审核后的生产回归集。验收包括：失败可最小复现、同一 pack/hash 的报告可比较、flaky 用例隔离标注、未经审核的生产样本不自动进入门禁。
