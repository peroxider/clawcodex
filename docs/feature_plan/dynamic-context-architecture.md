# DC-A: Agent 动态上下文架构 — 20 项原理特性规划

> 状态: 📋 脑暴规划 (Brainstorm Planning)
> 章节: `docs/feature_plan/dynamic-context-architecture.md`
> 最后更新: 2026-07-21
> 编号体系: DC-001 ~ DC-020（Dynamic Context 缩写；尚未申请 F-Number，实施前需走 F-Number 申请流程）

## §0 元信息

| 字段 | 值 |
|------|---|
| 文档性质 | 跨子系统的元架构脑暴规划（Meta-Architecture Brainstorm） |
| 目标 | 让 Agent 在不重新训练的前提下，获得更高灵活性、更低幻觉率、更广推理空间 |
| 核心命题 | 把"上下文"从静态字符串升级为**可编程 / 可热插拔 / 可验证 / 可回放的运行时对象** |
| 不申请 F-Number 的原因 | 20 项中部分为原理层抽象，部分为可立即实施的 feature；落地时按子特性单独立项 |
| 与已有特性的关系 | 多项与 F-119 (Prompt Assembly)、F-130 (Self-Correct Context Switch)、F-22 (Cron)、F-118 (Dynamic Decomposition) 存在协同与扩展点 |
| 阅读对象 | 架构师 / Agent 核心维护者 / Prompt 工程负责人 |

---

## §1 背景与目标

### 1.1 现状痛点

当前 Agent 的"上下文"在对话启动时基本一次性固化：system prompt 拼装、历史消息、工具描述混作一锅"上下文汤"，塞入 context window 后便不可干预。具体表现：

1. **静态锁死** — 上下文在会话初决定，无法按子任务切换
2. **不可验证** — 模型"看到"什么、忽略什么，无任何审计痕迹
3. **耦合严重** — 任务描述、知识、约束、风格混在一起，切换需要重建整段 prompt
4. **幻觉难溯源** — 错误的输出无法定位到"是上下文哪一段误导"
5. **推理单一** — 缺乏并行探索 / 对抗质疑 / 反事实等机制

### 1.2 设计目标

- **灵活性 (Flexibility)** — 同一会话内可按子任务切换上下文模式
- **抗幻觉 (Anti-Hallucination)** — 让"诚实地说不知道"成为一等公民行为
- **推理广度 (Reasoning Breadth)** — 多视角 / 反事实 / 类比迁移等机制内建
- **可审计 (Auditability)** — 每段上下文的来源、生效时段、回滚路径可追溯
- **可组合 (Composability)** — 上下文像函数一样可组合、可继承、可热插拔

### 1.3 非目标 (Out of Scope)

- 不涉及模型权重 / 训练 / 微调层面的改动
- 不替代任何已有 F-Number 的核心实现，只在其上叠加元机制
- 不强求一次性落地 20 项；可按组别分批推进

---

## §2 核心范式转移

| 维度 | 传统做法 | 新范式 |
|------|----------|--------|
| 上下文形态 | 一次性拼接的字符串 | **可编译的运行时 artifact** |
| 上下文生命周期 | "拼一次用到结束" | **采集 → 装配 → 执行 → 验证 → 回收** 五阶段 |
| 切换代价 | 整段 prompt 重建 | **Section 级热插拔** (借力 F-119 Registry) |
| 幻觉处理 | 提示词警告 + RLHF | **置信度声明 + 工具强制验证 + 对抗质疑** 三层防御 |
| 推理结构 | 单链 CoT | **多视角扇出 + 假设并行 + 反事实 + 类比迁移** |
| 可观测性 | 日志看输出 | **上下文时序回放 + 边界追踪** |

**一句话总结**：让 Agent 像一个**会换脑子的工程师**——遇到循环就换 Profile、遇到陌生领域就 JIT 查证、遇到事实主张就标置信度、遇到推理僵局就扇出多视角。

---

## §3 设计方案详述 (20 项)

> 每项按"原理 / 核心特性 / 关键机制 / 协同与冲突 / 落地门槛 / 风险"六字段展开。

### 3.A 上下文生命周期管理 (DC-001 ~ DC-004)

---

#### DC-001 上下文模式 (Context Mode) 热切换

**原理**：借鉴 Kubernetes namespace / Linux cgroup 的隔离思路，将"上下文"按场景打包为可独立挂载的**模式 (Mode)**。每个 Mode 自带：工具白名单、知识库、风格约束、行为守则。

**核心特性**：
- 预置模式：`code-review / security-audit / debug / creative / refactor / docs`
- 模式 = 命名空间，可叠加（`security-audit + code-review`）
- 冲突解决策略：显式优先级表 + 用户覆盖接口
- 切换 = 卸载旧 section + 加载新 section（借力 F-119）

**关键机制**：
```
Mode = {
  id, name, description,
  sections: [section_id_or_template],
  tools_allow: [...], tools_deny: [...],
  knowledge_anchors: [...],
  style: { tone, length, format },
  conflicts_with: [...], priority: int
}
ContextStack = List[Mode]  # 后入栈的覆盖前面的
```

**协同 / 冲突**：
- ✅ 强协同 DC-002 (Inheritance Chain)、DC-014 (Context-as-Code)
- ⚠️ 与 DC-017 (Mode Blending) 概念有重叠，需明确"切换"与"混合"的语义边界
- ⚠️ 模式爆炸风险：需通过模板继承收敛

**落地门槛**：中（需 F-119 Registry 已落地）
**风险**：模式冲突矩阵爆炸；缓解 = 默认关闭叠加，仅开放单模式切换

---

#### DC-002 上下文继承链 (Context Inheritance Chain)

**原理**：类似 OO 继承 / CSS 级联——父级是约束，子级可覆盖；可对两个上下文做 diff 看到差异。

**核心特性**：
- `GlobalContext` (项目级) → `TaskContext` (本次任务) → `SubTaskContext` (子任务) → `ReActLoopContext` (单次循环)
- 每层有独立的不变量 (invariants)
- 支持 `inherit(override=...)` 操作
- 提供 `diff(ctx_a, ctx_b)` 接口
- 切换子任务不污染父级（栈语义）

**关键机制**：
```python
class ContextNode:
    parent: ContextNode | None
    sections: dict[str, SectionRef]   # 覆盖或新增
    invariants: list[Invariant]
    scope: "session" | "task" | "subtask" | "loop"

def effective_sections(node) -> list[Section]:
    # 沿 parent 链向上查找，子级覆盖父级
```

**协同 / 冲突**：
- ✅ DC-001 / DC-015 (Time-Travel) 都依赖继承链做 diff
- ⚠️ 与 F-130 Profile 体系重叠 — 需要明确 ContextNode 与 Profile 的关系：
  - 建议：**ContextNode = 运行时实例**，**Profile = 模板**；F-130 模板填充后产出 ContextNode

**落地门槛**：中
**风险**：深层继承链难以调试；缓解 = 限制最大深度 (3 层)

---

#### DC-003 按需 JIT 上下文合成 (Just-In-Time Context Synthesis)

**原理**：不要一次性预加载所有"可能需要"的东西，等模型显式触发需求再生成。直接切断"假装知道"的幻觉源头。

**核心特性**：
- 提供 `RequestContext(intent, hint)` API
- 触发条件：模型声明"我需要 X" / 用户指定 / 检测到知识缺口
- 生成器：基于意图路由到对应 loader（`grep` / `webfetch` / `tool exec`）
- 缓存：按 `(intent, scope)` 缓存合成结果，避免重复抓取
- 与 F-119 的 `register_section` 联动：合成结果可直接注册为动态 section

**关键机制**：
```
模型："我需要了解项目错误处理约定"
  → JIT-Loader 解析 intent → 调用 grep → 摘要 → register_section
模型："需要确认这个 API 最新签名"
  → JIT-Loader 调用 webfetch → 解析 → 注入到 scratchpad
```

**协同 / 冲突**：
- ✅ 强协同 DC-009 (否定式检索)、DC-006 (工具强制验证)
- ✅ DC-018 (涌现式上下文发现) 是其超集——JIT 是"显式触发"，涌现是"模型自主发现"
- ⚠️ 频繁抓取有性能成本；缓解 = 缓存 + 批量合成

**落地门槛**：低（依赖现有 Grep/WebFetch 工具）
**风险**：模型过度触发 JIT 导致延迟膨胀；缓解 = 单次会话上限 + 优先级队列

---

#### DC-004 记忆分层 (Working / Episodic / Semantic)

**原理**：把记忆按生命周期和可信度分层，每层有独立写入策略和读取权限。

**核心特性**：
- **Working Memory**：本会话 scratchpad，决策栈，未解疑问
- **Episodic Memory**：跨会话，"上次处理类似问题时..."
- **Semantic Memory**：项目级，代码结构、约定、术语表
- **Procedural Memory** (可选第四层)：流程化操作的成功路径
- 每层有不同写入策略：working 写最勤，semantic 写最严（需经审核）

**关键机制**：
```python
class MemoryStore:
    working: WorkingMemory   # 进程内 dict，自动 GC
    episodic: EpisodicStore  # .memory/episodic.jsonl
    semantic: SemanticStore  # .memory/semantic/ (curated)
    
def write(layer: str, key, value, *, confidence: float)
def read(layer: str, key) -> value | None
def provenance(layer, key) -> Citation   # 可追溯来源
```

**协同 / 冲突**：
- ✅ DC-020 (边界追踪) 依赖此分层标记每条知识的可信度
- ⚠️ Semantic 层写入审核成本高；建议先做 Working + Episodic 两层

**落地门槛**：低（仅 Working 层）
**风险**：Semantic 层污染；缓解 = 必须由人类或验证流程确认后才晋升

---

### 3.B 抗幻觉机制 (DC-005 ~ DC-009)

---

#### DC-005 置信度声明协议 (Confidence Disclosure Protocol)

**原理**：LLM 不会自然区分"知道 / 推断 / 不知道"，但**让这种区分成为一等公民行为**之后，幻觉可被结构性抑制。

**核心特性**：
- 每个事实主张显式标注：
  - `[VERIFIED]` — 来自刚抓取的代码 / 搜索结果
  - `[INFERRED]` — 从可见证据推断
  - `[UNCERTAIN]` — 可能错，需要查证
  - `[UNKNOWN]` — 完全不知道
- 输出格式：markdown 标注 + 后处理可过滤
- 配合 CLAUDE.md / 输出风格约束强制度
- 配合 Hook 在 reply 前扫描无标注的事实主张

**关键机制**：
```python
class ConfidenceMarker:
    claim: str
    level: Literal["VERIFIED", "INFERRED", "UNCERTAIN", "UNKNOWN"]
    source: Citation | None  # 仅 VERIFIED 必须有 source

def scan_for_unmarked_claims(text: str) -> list[UnmarkedClaim]:
    # Hook 实现：检测无 marker 的具体事实 (API 名、版本号、数字、专有名词)
```

**协同 / 冲突**：
- ✅ DC-006 / DC-007 / DC-009 都是其下游消费者
- ⚠️ 标注噪音可能降低可读性；缓解 = 只对"关键事实"标注，不是每个名词

**落地门槛**：低（仅需 CLAUDE.md + 输出风格）
**风险**：模型机械打标糊弄；缓解 = Hook 抽查 + 显式关联 source 校验

---

#### DC-006 工具强制验证 (Tool-Mandatory Verification)

**原理**：把"关键事实必须经过工具验证"作为**硬约束**，不允许直接断言。

**核心特性**：
- 规则集：API 签名、版本号、配置项、库名、文件路径、函数存在性
- Hook 实现：reply 前扫描输出，若出现规则集关键词但对话历史无对应工具调用，则拦截
- 例外清单：`localhost`、示例代码、通识性陈述
- 与 JIT (DC-003) 联动：触发验证时自动 JIT 抓取

**关键机制**：
```python
VERIFY_RULES = [
    Rule(pattern=r"def\s+\w+\(",   # Python 函数定义
         tool="Read", reason="API 签名需文件确认"),
    Rule(pattern=r"\b\d+\.\d+\.\d+\b",  # semver
         tool="WebFetch", reason="版本号需查证"),
    Rule(pattern=r"import\s+[\w.]+",   # import 路径
         tool="Grep", reason="import 路径需确认存在"),
]

def pre_reply_hook(reply, history) -> Reply:
    for rule in VERIFY_RULES:
        if rule.matches(reply) and not history.has_recent_tool_call(rule.tool):
            return Reply.action("verify", rule)  # 强制先调工具
```

**协同 / 冲突**：
- ✅ 强协同 DC-005 (置信度标注)
- ⚠️ 误伤风险（用户写示例代码也会触发）；缓解 = 例外清单 + 上下文判定

**落地门槛**：低-中
**风险**：过度严格导致正常对话卡顿；缓解 = 灰度开关 + 用户可临时关闭

---

#### DC-007 自相矛盾检测循环 (Self-Contradiction Detection Loop)

**原理**：在"输出 → 反馈 → 修订"循环中加一个**矛盾检测器**，捕获逻辑不一致并自动修订。

**核心特性**：
- 检测维度：
  - 与已知事实冲突（基于 Working Memory 中已 VERIFIED 的事实）
  - 内部不一致（同一回复内前后矛盾）
  - 与前文对话矛盾（之前说过 A，现在说非 A）
- 检测后行为：自动重写 / 标记冲突 / 抛给用户确认
- 实现方式：可由独立 sub-agent 担任 Critic

**关键机制**：
```
Draft Answer
  ↓
[Contradiction Detector]
  ├─ vs 已 VERIFIED 事实 → 冲突 → 重写
  ├─ 内部不一致       → 冲突 → 重写
  └─ vs 历史上下文    → 冲突 → 重写
  ↓
Final Answer
```

**协同 / 冲突**：
- ✅ DC-008 (Red-Team Critic) 是其人格化版本
- ⚠️ 检测本身有成本（额外 LLM 调用）；缓解 = 仅对长输出 / 关键决策启用

**落地门槛**：中
**风险**：检测器自身可能误报；缓解 = confidence score + 阈值

---

#### DC-008 对抗质疑器 (Red-Team Critic)

**原理**：让一个**对抗人格的 sub-agent**专门找茬，比期望单个 LLM 自我对抗更可靠。

**核心特性**：
- 默认三角色：**Proposer / Critic / Synthesizer**
- Critic 必须输出：`{claim, counter_evidence, severity}` 列表
- 多轮迭代：Critic 提出 → Proposer 回应 → 直到 Critic 无新质疑或达最大轮数
- 与 DC-010 (多视角扇出) 区别：对抗是 **1v1 纵深**，多视角是 **N 选 1 横向**

**关键机制**：
```python
def adversarial_review(proposal: str, *, rounds: int = 3) -> FinalDecision:
    for round in range(rounds):
        critique = critic_agent.run(
            f"对以下方案提出 3 条最尖锐的质疑：\n{proposal}",
            persona="red-team"
        )
        if not critique.has_new_objections():
            break
        proposal = proposer_agent.run(
            f"回应以下质疑，修订方案：\n{critique}", 
            prior=proposal
        )
    return synthesizer.synthesize(proposal, critique_history)
```

**协同 / 冲突**：
- ✅ 强协同 DC-007 (矛盾检测)、DC-010 (多视角)
- ⚠️ Token 消耗翻倍；缓解 = 仅在关键决策 / 高风险任务启用

**落地门槛**：中（需多 agent 编排能力，F-118 已部分提供）
**风险**：Critic 角色过度悲观；缓解 = Critic 也需有"承认优点"的部分

---

#### DC-009 否定式检索 (Negative Retrieval)

**原理**：不只检索"什么东西存在"，还检索"这个东西**不存在**"。直接抑制最常见的"臆测存在"型幻觉。

**核心特性**：
- 提问解析：识别"是否用过 / 是否支持 / 是否存在"类问题
- 自动触发：对应的 `Grep("X")` / `WebFetch("X 文档")` 验证
- 输出策略：先给出否定结论，再展示证据 (grep -r "X" . → 0 matches)
- 与 DC-006 (工具强制验证) 区别：否定式检索是**问题驱动**，强制验证是**输出驱动**

**关键机制**：
```python
def negative_retrieval(question: str) -> Answer:
    targets = extract_negation_targets(question)  # ["X", "feature Y"]
    evidence = []
    for target in targets:
        result = grep(target, scope="project")
        evidence.append(NegEvidence(
            target=target,
            count=result.match_count,
            sample=result.first_match_path or "无匹配"
        ))
    return Answer(
        conclusion="未找到 X 的使用证据",
        evidence=evidence,
        confidence=0.9 if all(e.count == 0 for e in evidence) else 0.5
    )
```

**协同 / 冲突**：
- ✅ DC-003 (JIT) / DC-006 (工具强制)
- ⚠️ 对小项目 / 冷门库可能误判"不存在"；缓解 = 同时检查官方文档

**落地门槛**：低
**风险**：用户问"是否应该用 X"被当成"是否用了 X"；缓解 = 明确意图分类

---

### 3.C 推理扩展机制 (DC-010 ~ DC-013)

---

#### DC-010 多视角扇出 (Multi-Perspective Fan-Out)

**原理**：让 N 个不同"视角 / persona"的 sub-agent **独立**推理，再综合——避免单链 CoT 的窄化偏差。

**核心特性**：
- 默认视角池：`senior-engineer / security-reviewer / newcomer / perf-optimizer / maintainer`
- 每个视角独立给结论 + 论据
- Synthesizer 综合：重合结论标高置信，分歧标给人类决策
- 视角可注册扩展

**关键机制**：
```python
def multi_perspective_decide(question: str, *, perspectives: list[Perspective]) -> Decision:
    results = parallel_run([
        perspective_agent.run(question, persona=p) for p in perspectives
    ])
    consensus = find_consensus(results)
    conflicts = [r for r in results if r not in consensus]
    return Decision(
        consensus=consensus,
        conflicts=conflicts,
        confidence=len(consensus) / len(results),
        requires_human=len(conflicts) > 0,
    )
```

**协同 / 冲突**：
- ✅ DC-008 (对抗) 是其纵深版本
- ⚠️ Token 与时延成本高；缓解 = 按风险分级

**落地门槛**：中-高（依赖 F-118 动态分解）
**风险**：视角趋同（不同 persona 走向同一结论）；缓解 = 视角描述要明显差异化

---

#### DC-011 假设并行情景 (Parallel Hypothetical Scenarios)

**原理**：不要在"A 方案不好"上停留，把 A、B、C **都完整推演**到可比较深度再选。

**核心特性**：
- 输入：当前决策点 + 候选方案集
- 输出：每个方案的完整推演 + 优缺点 + 风险评估
- 评估维度：实现成本 / 可维护性 / 风险 / 可逆性 / 依赖
- 强制：每个方案推演深度 ≥ 3 步，禁止浅尝辄止

**关键机制**：
```python
def explore_scenarios(decision: Decision, *, scenarios: list[Scenario]) -> Comparison:
    detailed = parallel_run([
        deep_explore(s, depth=3) for s in scenarios
    ])
    return Comparison(
        scenarios=detailed,
        matrix=score_matrix(detailed, 
            criteria=["cost", "maintainability", "risk", "reversibility", "deps"]),
        recommendation=synthesize(detailed),
    )
```

**协同 / 冲突**：
- ✅ DC-010 / DC-012
- ⚠️ 推演深度难量化；缓解 = 显式定义"深度 ≥ 3 步"的最低标准

**落地门槛**：中
**风险**：推演出大量相似细节浪费 token；缓解 = 共享前置推演结果

---

#### DC-012 反事实推理 (Counterfactual Reasoning)

**原理**：显式训练 agent 思考"如果我错了，最可能错在哪？什么证据会反驳我？"——减少过度自信的最简单动作。

**核心特性**：
- 触发：每个最终结论前强制附加 "Counterfactual Check"
- 格式：列出 2-3 个最可能的反驳证据
- 行为：若反驳证据确实存在 → 弱化结论；若不存在 → 强化结论
- 可作为 Critic (DC-008) 的 prompt 模板

**关键机制**：
```python
COUNTERFACTUAL_TEMPLATE = """
决策：{decision}
请列出：
1. 最可能让此决策错的 2 个原因
2. 什么证据会反驳此决策
3. 如果发现反驳证据，应如何修正
"""
```

**协同 / 冲突**：
- ✅ DC-008 / DC-020 (边界追踪)
- 几乎无冲突，可作为轻量级 baseline

**落地门槛**：低（仅 prompt 工程）
**风险**：模型写反事实但不真正"相信"；缓解 = 强制在最终答案中体现反事实影响

---

#### DC-013 类比迁移 (Analogical Transfer)

**原理**：把陌生问题**类比**到已知问题——瞬间扩展可用知识，但需校验类比真实性。

**核心特性**：
- 检索：跨项目 / 跨领域找结构相似的历史方案
- 输出：类比映射 (A 的 X 元素 ≈ B 的 Y 元素)
- 校验：检查两个问题是否真的结构相似 (避免"看似相关实则不同")
- 失败行为：类比不通过则不采用，标注"无类比"

**关键机制**：
```python
def analogical_transfer(problem: Problem) -> Analogy | None:
    candidates = semantic_search(problem, corpus="memory:episodic")
    for candidate in candidates:
        mapping = propose_mapping(problem, candidate)
        if validate_isomorphism(mapping):  # 结构同构检查
            return Analogy(problem, candidate, mapping)
    return None
```

**协同 / 冲突**：
- ✅ DC-004 (Episodic Memory) 提供语料
- ⚠️ 类比幻觉——表面相似但结构不同；缓解 = 强制 isomapping 校验

**落地门槛**：中（依赖 Episodic Memory 落地）
**风险**：过度依赖类比而忽略新问题特异性；缓解 = 强制标注"哪些部分类比不了"

---

### 3.D 元架构层 (DC-014 ~ DC-020)

---

#### DC-014 上下文即代码 (Context-as-Code, CaC)

**原理**：把上下文定义做成**版本化、声明式、可 diff、可测试**的工件——这是 prompt 工程的 DevOps 化。

**核心特性**：
- 声明式 YAML / TOML 定义：
  ```yaml
  mode: code-review
  inherit: [base-agent, project-conventions]
  tools: [Read, Grep, Bash]
  constraints:
    must_verify_api_signatures: true
    max_tool_calls: 20
  policies:
    on_uncertainty: ask_before_guess
    on_contradiction: re_derive
  ```
- 上下文可被版本控制 (git)、可被单元测试、可被 A/B
- 提供 `ctx test <file>` / `ctx diff a.yml b.yml` / `ctx apply --dry-run` 等 CLI

**关键机制**：
- 解析器：`ContextYAML → ContextNode (DC-002)`
- 校验器：lint + type check + 兼容性检查
- 测试框架：给定 mock 输入，断言生成的 system prompt 包含 / 不包含某些段
- 模板继承：`extends: base-agent` 类似 Helm/Kustomize

**协同 / 冲突**：
- ✅ DC-001 / DC-002 是其 runtime backend
- ✅ DC-019 (压力测试) 是其测试方法
- ⚠️ 与"对话中临时调整"有冲突——临时调整是否也算 code？建议：临时调整走 API，不污染 code

**落地门槛**：高（需新 CLI + 框架）
**风险**：配置膨胀；缓解 = 提供 `ctx init --template <场景>` 起步模板

---

#### DC-015 上下文时序回放 (Context Time-Travel)

**原理**：每一步决策 snapshot 上下文，类似 `git commit` for reasoning——可解释、可重放、可分支。

**核心特性**：
- Snapshot 粒度：每个 turn 结束 / 每次模式切换 / 每次工具调用
- 存储：`turn_id → {timestamp, context_hash, sections_effective, mode, decisions}`
- 回放接口：`replay(turn_id)` 重建当时上下文
- 分支探索：基于历史 snapshot "如果当时选 B 而不是 A" 会怎样？
- 可视化：时间轴 + 上下文 diff 视图

**关键机制**：
```python
@dataclass
class ContextSnapshot:
    turn_id: int
    timestamp: str
    context_hash: str
    sections: dict[str, SectionRef]  # 当时生效的 section
    mode_stack: list[str]
    decisions: list[DecisionTrace]

class ContextTimeline:
    snapshots: list[ContextSnapshot]
    def get(turn_id) -> ContextSnapshot
    def diff(t1: int, t2: int) -> ContextDiff
    def branch_from(turn_id, alternative: str) -> Branch
```

**协同 / 冲突**：
- ✅ DC-002 (Inheritance diff) / F-119 dump_effective_system_prompt
- ✅ 可视化可借力 F-156 (Asciicast) / Dashboard 子系统
- ⚠️ 存储成本；缓解 = 仅存 hash + section ref，section 内容由 registry 反查

**落地门槛**：中
**风险**：回放时外部世界已变 (文件被改)；缓解 = 标注"外部状态可能在回放后已变"

---

#### DC-016 上下文市场 (Context Marketplace)

**原理**：把上下文做成可复用件，跨项目 / 跨 agent 共享——知识沉淀的飞轮。

**核心特性**：
- 上下文 pack 仓库：`.ctx/packs/*.yaml` (本地) + 可选远程 registry
- 预置 pack：`python-best-practices-v3 / react-structure-v1 / postgres-perf-checklist-v2 / team-review-preferences`
- 安装：`ctx pack add <name>`
- 共享机制：导出 / 导入 / 版本化 / 签名

**关键机制**：
```yaml
# pack: python-best-practices-v3
version: 3.0.0
author: team-platform
description: Python 项目通用最佳实践
sections:
  - id: code_style
    content_ref: ./snippets/code_style.md
  - id: error_handling
    content_ref: ./snippets/error_handling.md
tools_required: [Read, Grep]
dependencies:
  - pack: base-agent >= 1.0
```

**协同 / 冲突**：
- ✅ DC-014 (CaC) 是底层格式
- ⚠️ 安全风险：远程 pack 可能含恶意内容；缓解 = 签名 + 沙箱加载 + 权限声明

**落地门槛**：中-高
**风险**：pack 版本冲突；缓解 = 语义化版本 + 兼容性声明

---

#### DC-017 认知模式混合 (Cognitive Mode Blending)

**原理**：不是非此即彼，而是按**比例混合**不同推理风格——更细粒度的"换脑"。

**核心特性**：
- 风格维度：`analytical / creative / critical / cautious / exploratory`
- 配比：`{analytical: 0.6, creative: 0.3, critical: 0.1}`
- 实现：每个风格作为子 agent 投票，按权重汇总
- 动态调整：根据任务反馈在线调整配比

**关键机制**：
```python
@dataclass
class CognitiveBlend:
    analytical: float = 0.0
    creative: float = 0.0
    critical: float = 0.0
    cautious: float = 0.0
    exploratory: float = 0.0
    
    def __post_init__(self):
        assert abs(sum(self.__dict__.values()) - 1.0) < 1e-6
    
    def to_prompt_directive(self) -> str:
        return COGNITIVE_BLEND_TEMPLATE.format(**self.__dict__)
```

**协同 / 冲突**：
- ⚠️ 与 DC-001 (Mode Switch) 区别：Switch 是离散切换，Blending 是连续混合
- 建议：**Blending 是 Switch 的内部机制**——切换 = 离散配比突变

**落地门槛**：中
**风险**：配比调试困难；缓解 = 提供"任务类型 → 推荐配比"的经验表

---

#### DC-018 涌现式上下文发现 (Emergent Context Discovery)

**原理**：不预设上下文，让 agent **自己反思**"我需要什么"——meta-cognition 显式化。

**核心特性**：
- 触发：任务开始时 + 关键决策点
- 反思 prompt："要回答这个问题，我可能需要：X、Y、Z。我现在缺什么？"
- 行动：实际去获取 (借力 DC-003 JIT)
- 重试：拿到所需上下文后重做

**关键机制**：
```python
EMERGENT_DISCOVERY_PROMPT = """
任务：{task}
当前上下文：{current_context_summary}

请反思：
1. 要完成此任务，我需要哪些信息？
2. 当前上下文覆盖了哪些？缺哪些？
3. 对每个缺口，我应该调用哪个工具 / 检索哪个来源？
4. 我是否有信心基于现有上下文回答？(0-1)
"""
```

**协同 / 冲突**：
- ✅ DC-003 (JIT) 是其执行层
- ⚠️ 反思本身消耗 token；缓解 = 仅在长任务 / 陌生领域启用

**落地门槛**：低（仅 prompt + JIT）
**风险**：模型"假反思"；缓解 = 要求列出具体证据缺口，不是泛泛而谈

---

#### DC-019 上下文压力测试 (Context Stress Test)

**原理**：对每个 context pack 生成**对抗性输入**看会不会幻觉——上下文上线前的 fuzz。

**核心特性**：
- 触发：新 pack 提交时 / 定期回归
- 生成：基于历史幻觉模式 + 对抗模板生成诱导输入
- 检测：若任何输入诱导出"自信但错误"的输出 → REJECT
- 报告：失败用例 + 失败原因 + 建议修改

**关键机制**：
```python
@dataclass
class StressTestCase:
    input: str
    expected_safe_behavior: str  # "应该声明不确定 / 应该调用工具 / 应该..."
    hallucination_triggers: list[str]  # 此用例针对的幻觉类型

def stress_test(pack: ContextPack, *, cases: list[StressTestCase]) -> Report:
    failures = []
    for case in cases:
        output = run_agent(case.input, context=pack.compile())
        if not check_safe_behavior(output, case.expected_safe_behavior):
            failures.append((case, output))
    return Report(pack=pack.id, total=len(cases), failed=len(failures), failures=failures)
```

**协同 / 冲突**：
- ✅ DC-014 (CaC) / DC-016 (Marketplace) 的 CI 阶段
- ⚠️ 需积累幻觉模式库；缓解 = 从生产日志中挖掘

**落地门槛**：高（需测试框架 + 模式库）
**风险**：测试集本身有偏；缓解 = 持续更新 + 人类标注

---

#### DC-020 边界追踪 (Frontier Tracking)

**原理**：让 agent **显式维护**一张"知识边界图"——把"不知道自己不知道"变成可审计 artifact。

**核心特性**：
- 输出格式（每个会话至少一次）：
  ```
  KNOWN:       项目用 Python 3.11
  INFERRED:    项目可能用 Poetry (因有 pyproject.toml)
  UNKNOWN:     生产部署架构
  BOUNDARY:    我会在 INFERRED 上谨慎推理，不越过 UNKNOWN 区域
  ```
- 持久化：写入 Semantic Memory (DC-004)
- 自检：每次回答前对照 boundary 自查

**关键机制**：
```python
@dataclass
class KnowledgeFrontier:
    known: list[Fact]            # [{fact, source, confidence}]
    inferred: list[Inference]    # [{claim, basis, confidence}]
    unknown: list[Gap]           # [{area, importance, why_needed}]
    boundary_rules: list[str]    # ["不在 UNKNOWN 上断言", ...]
    
def render_frontier(f: KnowledgeFrontier) -> str:
    # 输出 markdown 段落，可注入 system prompt 末尾
```

**协同 / 冲突**：
- ✅ 几乎所有项的"诚信底座"
- ⚠️ 占用 context window；缓解 = 仅在长会话 / 高风险任务启用

**落地门槛**：低
**风险**：模型机械列举而非真信；缓解 = 自检钩子抽查

---

## §4 交叉特性分析

### 4.1 协同矩阵 (选关键协同)

| 协同项 | 强协同对象 | 协同点 |
|--------|-----------|--------|
| DC-001 模式切换 | DC-002 / DC-014 / DC-017 | 切换 = 离散模式突变；混合 = 连续模式调整；CaC = 模式定义格式 |
| DC-003 JIT | DC-006 / DC-009 / DC-018 | 强制验证/否定检索/涌现发现都通过 JIT 执行抓取 |
| DC-005 置信度 | DC-006 / DC-007 / DC-008 | 置信度是契约，验证/检测/对抗是执行 |
| DC-008 对抗 | DC-007 / DC-010 | 1v1 纵深 vs N 选 1 横向 |
| DC-014 CaC | DC-016 / DC-019 | CaC 是格式，Marketplace 是分发，Stress Test 是 CI |
| DC-015 Time-Travel | DC-002 / F-119 dump | 回放基于继承链 diff 和当前 section dump |
| DC-020 边界追踪 | 几乎所有 | 跨项诚信底座 |

### 4.2 潜在冲突

| 冲突项 | 冲突点 | 解决思路 |
|--------|--------|----------|
| DC-001 模式切换 vs DC-017 模式混合 | 离散 vs 连续 | 明确**切换 = 离散突变**、**混合 = 内部配比**，互为底层 |
| DC-013 类比迁移 vs 严肃推理 | 类比可能引入偏差 | 强制 isomapping 校验 + 标注"哪些部分不可类比" |
| DC-014 CaC vs 临时调整 | 临时调整是否污染 code | 临时调整走运行时 API，不写回 yaml |
| DC-008 对抗 vs 性能 | 多 agent 翻倍成本 | 仅对关键决策 / 高风险任务启用，灰度开关 |

### 4.3 实施依赖链 (粗略 DAG)

```
Level 0 (地基): F-119 (Section Registry), F-130 (Profile)
Level 1 (可立即落): DC-003, DC-004, DC-005, DC-006, DC-009, DC-012, DC-018, DC-020
Level 2 (依赖 L1): DC-001, DC-002, DC-007, DC-013, DC-017
Level 3 (依赖 L2): DC-008, DC-010, DC-011, DC-015
Level 4 (基础设施): DC-014, DC-016, DC-019
```

### 4.4 DC → F-N 映射表（落地粒度收敛）

> **本节为本元架构与 F-Number 体系的对接点**：把 20 项 DC-NN 收敛为 **16 个 F-N 文档**，按 Wave 1/2/3 三波落地。收敛原则：低门槛/低风险项合并（如 DC-005/009/020 合并到 F-131）；独立可拆分的高门槛项单独成 F-N。

| Wave | F-Number | 名称 | 覆盖 DC | 杠杆 | 门槛 | 前置依赖 |
|:----:|---------|------|:-------:|:----:|:----:|----------|
| —    | F-119  | System Prompt 段落拼装基础设施 (已规划) | DC-001~020 全部依赖 | — | — | — |
| —    | F-130  | 自校正上下文切换 (已规划) | DC-001 / DC-002 / DC-007-部分 | 🔴🔴 | 中 | F-119 |
| **Wave 1 (P0, ~1-2 周)** | | | | | | |
| 1    | **F-158** | 抗幻觉基线协议 (置信度 + 否定检索 + 边界追踪) | DC-005 / DC-009 / DC-020 | 🔴🔴🔴 | 🟢 | F-119 + Hooks |
| 1    | **F-159** | JIT 上下文合成 | DC-003 | 🔴🔴 | 🟢 | F-119 |
| 1    | **F-160** | 反事实推理 prompt 模板 | DC-012 | 🔴 | 🟢 | 仅 prompt |
| 1    | **F-161** | 涌现式上下文发现 | DC-018 | 🔴 | 🟢 | F-159 (JIT) |
| **Wave 2 (P1, ~2-3 月)** | | | | | | |
| 2    | **F-162** | 工具强制验证 | DC-006 | 🔴🔴 | 🟡 | F-119 + Hooks |
| 2    | **F-163** | 对抗质疑器 (Red-Team Critic) | DC-008 | 🔴🔴 | 🟡 | F-118 子 agent |
| 2    | **F-164** | 多视角扇出 | DC-010 | 🔴🔴 | 🟡 | F-118 子 agent |
| 2    | **F-165** | 矛盾检测独立版 | DC-007 完整 | 🔴 | 🟡 | F-119 + F-130 检测器 |
| 2    | **F-166** | 记忆分层 (W/E/S) — 先 Working + Episodic | DC-004 | 🟢 | 🟡 | F-119 |
| **Wave 3 (P2/P3, ~半年+)** | | | | | | |
| 3    | **F-167** | 类比迁移 | DC-013 | 🟡 | 🟡 | F-166 (Episodic) |
| 3    | **F-168** | 假设并行情景 | DC-011 | 🟡 | 🟡 | F-118 子 agent |
| 3    | **F-169** | 上下文时序回放 | DC-015 | 🟡 | 🟡 | F-119 + F-130 切换历史 |
| 3    | **F-170** | 认知模式混合 | DC-017 | 🟡 | 🟡 | F-130 Profile 体系 |
| 3    | **F-171** | 上下文即代码 (CaC) | DC-014 | 🟡 | 🔴 | F-158~170 全部 |
| 3    | **F-172** | 上下文市场 Marketplace | DC-016 | 🟢 | 🔴 | F-171 (CaC) |
| 3    | **F-173** | 上下文压力测试 | DC-019 | 🟢 | 🔴 | F-171 (CaC) + 幻觉模式库 |

**收敛说明**：

- **DC-001 / DC-002 / DC-007-部分** 已并入 F-130（不单独立项）；如后续需要完整 DC-002 继承链的 `diff(ctx_a, ctx_b)` 接口或 DC-001 的"多模式叠加"语义，可考虑在 F-130 内追加子特性 P130-I / P130-J，不再开新 F-N
- **DC-005 / DC-009 / DC-020** 合并为 F-158：三者在抗幻觉侧底层机制一致（hook + 输出风格约束 + CLAUDE.md），单文档维护成本低
- **DC-008 对抗** 与 **DC-010 多视角** 同源不同形态，独立 F-N 但共享"多 agent 编排"基础设施（来自 F-118）
- **DC-014 / DC-016 / DC-019** 顺序构建：先 CaC（声明式格式）→ Marketplace（分发渠道）→ Stress Test（质量门禁），三者共用一套 pack 定义语言

**F-N 编号冲突检查**：

- F-158~F-173 当前未在 `docs/feature_plan/README.md` 的 F-Number 状态总表中占用，编号空间连续可用
- F-174+ 保留给尚未规划的 CCB / Orchestrator 后续特性

**不申请 F-N 的情况**：

- DC-001 / DC-002 完全由 F-130 承载（已有 8 个 P130-A~H 子特性覆盖）
- DC-007-部分 由 F-130 P130-A 循环检测器承载（仅工具重复维度），完整版语义走 F-165
- DC-017 模式混合 与 DC-001 模式切换 概念边界模糊，本元架构阶段保留两套独立 F-N 以便落地时决断

---

## §5 优先级与实施路线

### 5.1 优先级总表

> 综合 **杠杆效应 (立竿见影度) × 实施难度** 两个维度排序。

| 排名 | 项 | 杠杆 | 难度 | 推荐阶段 |
|:----:|----|:----:|:----:|----------|
| 1 | DC-005 置信度声明 | 🔴🔴🔴 | 🟢 | **P0 (立即)** |
| 2 | DC-009 否定式检索 | 🔴🔴🔴 | 🟢 | **P0 (立即)** |
| 3 | DC-020 边界追踪 | 🔴🔴🔴 | 🟢 | **P0 (立即)** |
| 4 | DC-006 工具强制验证 | 🔴🔴 | 🟡 | P1 |
| 5 | DC-003 JIT 合成 | 🔴🔴 | 🟡 | P1 |
| 6 | DC-008 对抗质疑器 | 🔴🔴 | 🟡 | P1 |
| 7 | DC-010 多视角扇出 | 🔴🔴 | 🟡 | P1 |
| 8 | DC-002 继承链 | 🔴 | 🟡 | P2 |
| 9 | DC-007 矛盾检测 | 🔴 | 🟡 | P2 |
| 10 | DC-012 反事实推理 | 🔴 | 🟢 | P1 (低成本) |
| 11 | DC-018 涌现发现 | 🔴 | 🟢 | P1 (低成本) |
| 12 | DC-013 类比迁移 | 🟡 | 🟡 | P2 |
| 13 | DC-001 模式切换 | 🟡 | 🟡 | P2 |
| 14 | DC-015 时序回放 | 🟡 | 🟡 | P2 |
| 15 | DC-011 并行情景 | 🟡 | 🟡 | P2 |
| 16 | DC-017 模式混合 | 🟡 | 🟡 | P3 |
| 17 | DC-014 CaC | 🟡 | 🔴 | P3 |
| 18 | DC-016 上下文市场 | 🟢 | 🔴 | P3 |
| 19 | DC-019 压力测试 | 🟢 | 🔴 | P3 |
| 20 | DC-004 记忆分层 | 🟢 | 🟡 | P2 (Working 层先) |

### 5.2 推荐路线

> **本节与 §4.4 映射表配套阅读**：以下 Phase 名已替换为对应的 Wave 编号（F-N 文档编号）。

**Wave 1 (本季度, ~1-2 周)** — 立竿见影组
- **F-158** 抗幻觉基线协议（DC-005 / DC-009 / DC-020）通过 CLAUDE.md + Hook + 输出风格约束立即落地
- **F-159** JIT 上下文合成（DC-003）通过 Grep/WebFetch 工具编排落地
- **F-160** 反事实推理（DC-012）通过 prompt 模板落地
- **F-161** 涌现式上下文发现（DC-018）通过反思 prompt + F-159 落地
- 验证指标：用户报告"幻觉明显减少"

**Wave 2 (下季度, ~2-3 月)** — 工具化组
- **F-162** 工具强制验证（DC-006）通过 pre_reply_hook 实现
- **F-163** 对抗质疑器（DC-008）借助 F-118 子 agent 编排落地
- **F-164** 多视角扇出（DC-010）借助 F-118 子 agent 编排落地
- **F-165** 矛盾检测独立版（DC-007）补全 F-130 检测器
- **F-166** 记忆分层（DC-004）先落地 Working + Episodic 两层
- 验证指标：关键决策类任务可观察对抗/多视角结果

**Wave 3 (半年后)** — 基础设施组
- **F-167** / **F-168** / **F-169** / **F-170** 配合 Wave 1+2 落地逐步建设
- **F-171** (CaC) → **F-172** (Marketplace) → **F-173** (Stress Test) 顺序构建
- 验证指标：存在可复用 / 可测试 / 可审计的上下文体系

### 5.3 快速验证假设 (Quick Wins)

不写代码即可验证的核心假设：

1. **置信度标注是否让用户更信任？** — 在 5 个真实任务上加标注，对比用户满意度
2. **JIT 触发频率是否合理？** — 在现有 Agent 上加 hook 统计"我需要 X"类表达出现频率
3. **反事实 prompt 是否改变结论分布？** — A/B test 反事实 prompt 对最终答案影响
4. **对抗质疑找到过真问题吗？** — 抽样 10 次对抗质疑结果，统计"被质疑修正确实改善最终结果"的比例

---

## §6 验证与度量

### 6.1 度量指标

| 维度 | 指标 | 目标 |
|------|------|------|
| 幻觉率 | 用户标记的"事实错误"次数 / 总事实主张数 | 下降 ≥ 50% |
| 灵活性 | 单会话内成功切换模式的次数 | ≥ 1 (说明机制可用) |
| 推理深度 | 关键决策点平均推理步骤数 | 提升 ≥ 30% |
| 用户满意度 | 5 分制评分 | 提升 ≥ 0.5 分 |
| Token 成本 | 单任务平均 token 消耗 | 不恶化 > 20% |
| 响应时延 | 单 turn 平均延迟 | 不恶化 > 30% |

### 6.2 验证用例

| 用例 | 目的 | 期望 |
|------|------|------|
| V-1 询问项目是否用过某库 | 验证 DC-009 | 自动 grep 给出否定结论 + 证据 |
| V-2 多次失败后自动切换 Profile | 验证 F-130 + DC-007 | 自动切换 debug Profile 并继续 |
| V-3 陌生 API 调用 | 验证 DC-003 / DC-006 | 强制 WebFetch 查证后才输出 |
| V-4 关键代码改动 | 验证 DC-008 对抗 | 至少 1 轮 Proposer↔Critic 交互 |
| V-5 多视角决策分歧 | 验证 DC-010 | 给出 consensus + conflicts，标需人工 |
| V-6 长会话上下文爆炸 | 验证 DC-015 | 可列出每个 turn 的 context snapshot |
| V-7 提交新 Context Pack | 验证 DC-019 | 跑完压力测试，失败则拒绝 |

### 6.3 失败判定

| 失败模式 | 含义 | 应对 |
|----------|------|------|
| 幻觉率不降反升 | 标注让模型"分心" | 回滚标注机制，重新设计 prompt |
| 灵活性 token 暴涨 | 频繁切换导致重复加载 | 加缓存 + 合并切换 |
| 对抗质疑总提"非真问题" | Critic persona 过强 | 调整 Critic prompt，加"承认优点"部分 |
| 用户被置信度标注淹没 | 输出太长降低可读性 | 提供"简洁模式"开关 |

---

## §7 风险与缓解汇总

| 风险类别 | 风险描述 | 缓解策略 |
|----------|----------|----------|
| 性能 | 多机制叠加导致 token / 时延膨胀 | 灰度开关、按风险分级启用、共享前置推演 |
| 复杂度 | 20 项机制交互复杂，难调试 | 强制每项有可独立关闭开关、提供 `ctx profile debug` 诊断 |
| 一致性 | 跨项术语 / API 不统一 | 在 DC-014 CaC 中建立术语表，统一接口命名 |
| 安全 | 远程 Context Pack 可能含恶意指令 | 签名、沙箱加载、最小权限 |
| 用户疲劳 | 输出风格复杂化使用户疲劳 | 提供"极简模式"开关 |
| 指标失真 | 用户习惯了标注反而不再关注 | 定期盲测 + 用户访谈 |

---

## §8 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-07-21 | 初始创建 (20 项脑暴规划) | 用户提出"动态上下文切换/装配/生成"挑战性问题，经头脑风暴形成 DC-001 ~ DC-020 方案集，需落盘为单一规划文档指导后续 F-Number 申请与实施 |
| 2026-07-22 | 新增 §4.4 DC → F-N 映射表 | 把 20 项 DC-NN 收敛为 16 个 F-N 文档（F-158 ~ F-173），按 Wave 1/2/3 三波落地；F-N 编号从 F-158 起（接续 F-157 ToolSearch），同步更新 §5.2 推荐路线与 §9 速查表 |
| 2026-07-22 | F-158 抗幻觉基线协议文档启动（Wave 1 首个落地） | 在 §4.4 映射表基础上规划 F-158，覆盖 DC-005 置信度声明协议 + DC-009 否定式检索 + DC-020 边界追踪三个 P0 高杠杆项；详见 [03-agent-core/f-158-anti-hallucination-baseline.md](../03-agent-core/f-158-anti-hallucination-baseline.md)；解耦落地于 `extensions/anti_hallucination/`，零 `src/` 侵入 |
| 2026-07-22 | F-159 JIT 上下文合成文档启动（Wave 1 第二个落地） | 在 §4.4 映射表基础上规划 F-159，覆盖 DC-003；Intent 路由 + Loader 集合（Grep/WebFetch/Bash）+ 合成缓存 + F-119 register_section 动态注入 + 单 turn/session 配额 + 冷却期；与 F-130 / F-158-A / F-161 强协同；详见 [03-agent-core/f-159-jit-context-synthesis.md](../03-agent-core/f-159-jit-context-synthesis.md)；解耦落地于 `extensions/jit_context/`，零 `src/` 侵入 |
| 2026-07-22 | F-160 反事实推理文档启动（Wave 1 第三个落地） | 在 §4.4 映射表基础上规划 F-160，覆盖 DC-012；门槛最低（仅 prompt 模板 + 1 Hook）；3 类模板（决策 / 断言 / 推荐）+ 6 档 verdict 标注 + 反事实块自检 + INFERRED 降级桥；与 F-119 / F-102 / F-158-A / F-130 / F-163 协同；详见 [03-agent-core/f-160-counterfactual-reasoning.md](../03-agent-core/f-160-counterfactual-reasoning.md)；解耦落地于 `extensions/counterfactual/`，零 `src/` 侵入 |
| 2026-07-22 | F-161 涌现式上下文发现文档启动（Wave 1 第四个落地 / Wave 1 收官） | 在 §4.4 映射表基础上规划 F-161，覆盖 DC-018；是 F-159 JIT 的隐式反思调度前置（meta-cognition 显式化）；反思 prompt（含 4 反思问题 + 反事实协同）+ 3 个内置触发器（task_start / decision_point / periodic）+ 反思缓存 + 4 档信心门控（PROCEED / FORCE_JIT / ASK_USER / BLOCK）+ bridge_to_jit 调用 F-159 synthesize；与 F-119 / F-102 / F-159 / F-158 / F-160 / F-130 协同；详见 [03-agent-core/f-161-emergent-context-discovery.md](../03-agent-core/f-161-emergent-context-discovery.md)；解耦落地于 `extensions/emergent/`，零 `src/` 侵入 |
| 2026-07-22 | F-162 工具强制验证文档启动（Wave 2 P1 首个落地） | 在 §4.4 映射表基础上规划 F-162，覆盖 DC-006；是 F-158 软警告的硬约束升级（双层防御：F-158 标注 + F-162 拦截）；6 类规则（API 签名 / 版本号 / import / 库存在 / 路径 / 配置项）+ 三档拦截模式（warn / block / strict）+ 5 维例外判定（代码块 / 注释 / 示例 / 教程 / 文档）+ JIT 联动（自动抓取证据）+ Profile 映射；与 F-119 / F-102 / F-158 / F-159 / F-130 / F-163 协同；详见 [03-agent-core/f-162-tool-mandatory-verification.md](../03-agent-core/f-162-tool-mandatory-verification.md)；解耦落地于 `extensions/tool_verification/`，零 `src/` 侵入 |
| 2026-07-22 | F-163 对抗质疑器文档启动（Wave 2 P1 第二个落地） | 在 §4.4 映射表基础上规划 F-163，覆盖 DC-008；是 Wave 2 P1 的"方案层"对抗（区别于 F-162 "事实层"硬拦截）；Proposer / Critic / Synthesizer 三角色 + 多轮迭代循环（max 3 轮 + fingerprint 去重早停）+ 结构化质疑输出（claim / counter_evidence / severity / category）+ 5 Profile 触发策略（default / review / strict / debug / creative）+ 与 F-162 audit log schema 兼容；与 F-118 / F-119 / F-102 / F-162 / F-130 / F-164 协同；详见 [03-agent-core/f-163-red-team-critic.md](../03-agent-core/f-163-red-team-critic.md)；解耦落地于 `extensions/red_team_critic/`，零 `src/` 侵入 |

---

## §9 附录: 20 项速查表

| 编号 | F-N 映射 | 名称 | 组别 | 核心杠杆 | 落地门槛 |
|:----:|:--------:|------|------|:--------:|:--------:|
| DC-001 | F-130 (内含) | 上下文模式热切换 | 生命周期 | 🟡 | 中 |
| DC-002 | F-130 (内含) | 上下文继承链 | 生命周期 | 🟡 | 中 |
| DC-003 | F-159 (Wave 1) | JIT 上下文合成 | 生命周期 | 🔴🔴 | 低 |
| DC-004 | F-166 (Wave 2) | 记忆分层 (W/E/S) | 生命周期 | 🟢 | 低-高 |
| DC-005 | F-158 (Wave 1) | 置信度声明协议 | 抗幻觉 | 🔴🔴🔴 | 低 |
| DC-006 | F-162 (Wave 2) | 工具强制验证 | 抗幻觉 | 🔴🔴 | 低-中 |
| DC-007 | F-130 + F-165 | 自相矛盾检测 | 抗幻觉 | 🔴 | 中 |
| DC-008 | F-163 (Wave 2) | 对抗质疑器 | 抗幻觉 | 🔴🔴 | 中 |
| DC-009 | F-158 (Wave 1) | 否定式检索 | 抗幻觉 | 🔴🔴🔴 | 低 |
| DC-010 | F-164 (Wave 2) | 多视角扇出 | 推理扩展 | 🔴🔴 | 中-高 |
| DC-011 | F-168 (Wave 3) | 假设并行情景 | 推理扩展 | 🟡 | 中 |
| DC-012 | F-160 (Wave 1) | 反事实推理 | 推理扩展 | 🔴 | 低 |
| DC-013 | F-167 (Wave 3) | 类比迁移 | 推理扩展 | 🟡 | 中 |
| DC-014 | F-171 (Wave 3) | 上下文即代码 (CaC) | 元架构 | 🟡 | 高 |
| DC-015 | F-169 (Wave 3) | 上下文时序回放 | 元架构 | 🟡 | 中 |
| DC-016 | F-172 (Wave 3) | 上下文市场 | 元架构 | 🟢 | 高 |
| DC-017 | F-170 (Wave 3) | 认知模式混合 | 元架构 | 🟡 | 中 |
| DC-018 | F-161 (Wave 1) | 涌现式上下文发现 | 元架构 | 🔴 | 低 |
| DC-019 | F-173 (Wave 3) | 上下文压力测试 | 元架构 | 🟢 | 高 |
| DC-020 | F-158 (Wave 1) | 边界追踪 | 元架构 | 🔴🔴🔴 | 低 |