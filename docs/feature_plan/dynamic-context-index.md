# 动态上下文架构：总览与需求索引

> 状态: 📋 规划中  
> 定位: 动态上下文（DC-A）的架构总览、决策记录与 F-Number 索引；实施规格以各 F 文档为唯一来源。  
> 替代范围: 原动态上下文架构文档中的跨特性总览；原文档现为待删除对象。

## 目标与边界

目标是将上下文从静态字符串变为可组合、可验证、可回放的运行时工件，提升任务切换能力、抗幻觉能力、推理广度与审计性。

不包含模型训练或微调；不取代既有 F-Number 的实现；20 项能力按依赖分波实施，而非一次性交付。

## 核心范式

| 维度 | 目标形态 |
|------|----------|
| 生命周期 | 采集 → 装配 → 执行 → 验证 → 回收 |
| 切换 | 基于 F-119 section registry 的模式/section 热插拔 |
| 可信度 | 置信度声明、工具验证、对抗审视三层防御 |
| 推理 | 多视角、假设并行、反事实、类比迁移 |
| 可观测性 | 上下文快照、继承 diff、边界与来源追踪 |

## DC → F-Number 映射

| DC | F-Number | 需求文档 | 状态 |
|----|----------|----------|:----:|
| DC-001 / DC-002 | F-130 | [上下文模式、继承与切换](03-agent-core/f-130-self-correct-context-switch.md) | 📋 |
| DC-003 | F-159 | [JIT 上下文合成](03-agent-core/f-159-jit-context-synthesis.md) | 📋 |
| DC-004 | F-166 | [记忆分层](03-agent-core/f-166-memory-layering-we.md) | 📋 |
| DC-005 / DC-009 / DC-020 | F-158 | [抗幻觉基线](03-agent-core/f-158-anti-hallucination-baseline.md) | 📋 |
| DC-006 | F-162 | [工具强制验证](03-agent-core/f-162-tool-mandatory-verification.md) | 📋 |
| DC-007 | F-165 | [矛盾检测](03-agent-core/f-165-self-contradiction-detector.md) | 📋 |
| DC-008 | F-163 | [对抗质疑器](03-agent-core/f-163-red-team-critic.md) | 📋 |
| DC-010 | F-164 | [多视角扇出](03-agent-core/f-164-multi-perspective-fan-out.md) | 📋 |
| DC-011 | F-176 | [假设并行情景](03-agent-core/f-176-parallel-hypothetical-scenarios.md) | 📋 |
| DC-012 | F-160 | [反事实推理](03-agent-core/f-160-counterfactual-reasoning.md) | 📋 |
| DC-013 | F-175 | [类比迁移](03-agent-core/f-175-analogical-transfer.md) | 📋 |
| DC-014 | F-179 | [上下文即代码](04-architecture-sdk/f-179-context-as-code.md) | 📋 |
| DC-015 | F-177 | [上下文时序回放](03-agent-core/f-177-context-time-travel.md) | 📋 |
| DC-016 | F-180 | [上下文市场](04-architecture-sdk/f-180-context-marketplace.md) | 📋 |
| DC-017 | F-178 | [认知模式混合](03-agent-core/f-178-cognitive-mode-blending.md) | 📋 |
| DC-018 | F-161 | [涌现式上下文发现](03-agent-core/f-161-emergent-context-discovery.md) | 📋 |
| DC-019 | F-181 | [上下文压力测试](04-architecture-sdk/f-181-context-stress-test.md) | 📋 |

F-130 同时承载 DC-007 的工具重复检测部分；完整语义矛盾检测由 F-165 承载。F-119 是所有特性的 section registry 前置基础设施。

## 关键协同与边界

| 主题 | 约定 |
|------|------|
| Mode switch / blending | F-130 是离散模式切换；F-178 是模式内部的连续配比，不得混用语义。 |
| JIT / discovery / verification | F-159 负责获取；F-161 负责发现缺口；F-162 对关键事实强制验证。 |
| 可信度防线 | F-158 是声明与边界底座；F-162、F-165、F-163 分别处理验证、矛盾与方案对抗。 |
| 推理广度 | F-163 为 1v1 纵深对抗；F-164 为多视角横向比较；F-176 为候选假设的隔离推演。 |
| Pack 生命周期 | F-179 定义格式与编译；F-180 分发和签名；F-181 是上线前质量门禁。 |
| 记忆可信度 | F-166 中 Semantic/Procedural 的晋升必须经过审核；不得将临时或推断内容直接写入长期记忆。 |

## 依赖与实施顺序

```text
F-119 / F-130
        ↓
Wave 1: F-158, F-159, F-160, F-161
        ↓
Wave 2: F-162, F-163, F-164, F-165, F-166
        ↓
Wave 3 reasoning: F-175, F-176, F-177, F-178
        ↓
Wave 3 infrastructure: F-179 → F-180 → F-181
```

Wave 1 优先验证“诚实声明未知、按需取证”；Wave 2 增加验证和多 agent 推理；Wave 3 建设可复用上下文资产、回放与质量门禁。

## 度量与验收总则

| 指标 | 目标 |
|------|------|
| 幻觉防御 | 未验证关键事实被标记、验证或拦截；UNKNOWN 不被升级为断言。 |
| 上下文效率 | JIT 命中缓存，避免无关预加载；超预算时有明确降级。 |
| 推理质量 | 多视角/假设分歧被保留并可追溯，非伪造共识。 |
| 可审计性 | 关键决策可关联 source、memory、mode、snapshot 与验证记录。 |
| Pack 安全 | 未签名远程包、权限扩大、压力测试 blocker 默认拒绝。 |

所有 F 文档须包含：文件落点、数据/接口契约、失败行为、实施顺序、测试与验收条件。跨特性变更还必须更新本索引的映射和依赖关系。

## 全局风险与缓解

| 风险 | 缓解 |
|------|------|
| 上下文/子 agent 成本失控 | 分级触发、并发与 token 预算、缓存和早停。 |
| 模式或继承冲突 | 不变量、deny 优先、显式优先级、可见 diff 与回滚。 |
| 长期记忆或远程 Pack 污染 | 审批晋升、签名、权限声明、默认 fail closed。 |
| 回放不等于外部世界重演 | 快照标注外部依赖和漂移，不伪造可重现性。 |
| 测试集偏差 | 从已审核事故持续扩充 F-181 用例，并保留人工复核。 |

## 维护规则

本文件只维护跨特性决策和索引，不复制各 F 文档的实现细节。变更单项能力时，更新该 F 文档；改变依赖、编号、边界或全局策略时，同时更新本索引和 `README.md`。
