# F-92: experimental_skill_search TF-IDF

> 状态: 📋 规划中(目标模块 `clawcodex_ext/services/skill_search/` 待建)
> 章节: `docs/feature_plan/06-ccb-benchmark/f-92-skill-search.md`
> 最后更新: 2026-07-01
> 缺口来源: gap-analysis-2026q2.md §3.3(`#### F-92: experimental_skill_search TF-IDF`,已分解到本文档 §0)

## §0 缺口摘要

> 本节为 gap-analysis-2026q2.md §3.3 F-92 派工条目的分解版本;详细设计与基线请阅读 §1。

### 0.1 缺口描述

当前 ClawCodex 没有 TF-IDF 检索层:

- `skill_registry.list()` 仅是全量枚举;
- `McpSkillDiscovery`(F-91)注入的 skill 没有排序权重;
- `SkillListTool` 在 skill 数量过大时退化线性扫描;
- `extensions/skills_ext/` 缺乏索引持久化、rank 评分、TTL 重建、并发刷新;

### 0.2 对标

- CCB `experimental_skill_search` TF-IDF + 字段加权(name/title/body/tags)+ 长度归一化;
- CCB index 损坏自动重建 + Feature flag off 时零开销;
- CCB 中英文分词混合(`re` camelCase 拆分 + 字符 bigram + 可选 jieba 升级)。

### 0.3 解耦落地路径(全部 `clawcodex_ext/services/skill_search/`,不动 `src/`)

- `document.py` + `tokenizer.py` — `_tokenize_mixed()` 入口 + 中英文混合;
- `index.py` — TF-IDF inverted index + `index.json` 持久化 + mtime 校验;
- `searcher.py:SkillSearcher` — `search(query, top_k)` + `refresh()` + `ensure_index()`;
- `hook.py` — `skill_registry.register()` / `unregister()` 增量 hook,纳入 MCP 与本地 skill;
- `clawcodex_ext/feature_gate/registry.py` 注册 `SKILL_SEARCH_TFIDF` 默认 off;
- `clawcodex_ext/command_system/skill_search_commands.py` — `/skills search` debug 命令族;
- `clawcodex_ext/tool_system/tools/skill_search.py` — `SkillSearchTool` 给 Agent。

### 0.4 依赖

- 现有 `skill_registry.register()` 入口;
- F-91 MCP Skills 自动发现(F-91 注入的 skill 自动纳入索引);
- F-68 Feature Gate(`SKILL_SEARCH_TFIDF=on`);
- F-93 TeamMem(可复用 tokenizer);
- `extensions/skills_ext/` 现有 skill 加载框架。

### 0.5 估算工时

1 周(单人)。

---

## §1 设计规划

### 1.1 目标

对标 CCB `experimental_skill_search` 能力,为 ClawCodex 的 Skill 系统提供轻量级本地检索层。用户或 Agent 输入自然语言任务描述时,系统可用 TF-IDF 从已安装 skills(MCP 自动发现 + 本地 SKILL.md + 模板生成)中找出最相关的前 N 个,减少上下文注入噪声并提升 skill 选择准确率。

### 1.2 背景

现有 Skill 系统通常按目录枚举或全量注入描述,当 skill 数量增长到 50+ 后会出现:

1. **上下文膨胀**: 全量 skill 描述占用大量 prompt token;
2. **相关性不足**: Agent 需要自己从长列表中挑选 skill,容易错选;
3. **MCP 自动发现放大问题**: F-91 会把 MCP server tools 自动注册为 skill,数量可能增长到数百;
4. **缺本地离线检索**: 不应为 skill 选择额外调用 LLM 或远程 embedding API。

F-92 采用 TF-IDF + BM25 风格长度归一化的纯本地检索,无需外部依赖即可工作。

### 1.3 子特性分解

| 编号 | 子特性 | 预计工作量 |
|:----:|--------|:----------:|
| P92-A | 文档抽取器(`document.py`):Skill manifest / SKILL.md / MCP descriptor → `SkillSearchDocument` | 1 天 |
| P92-B | 分词与归一化(`tokenizer.py`):中英文混合 tokenization + stopwords + camelCase/snake_case 拆词 | 1 天 |
| P92-C | TF-IDF 索引(`index.py`):inverted index + doc frequency + idf + 持久化 JSON | 2 天 |
| P92-D | 查询器(`searcher.py`):query → topK + score breakdown + snippets | 1 天 |
| P92-E | 增量更新(`watcher.py`):skill registry 变更后更新索引 | 1 天 |
| P92-F | Feature Gate(`EXPERIMENTAL_SKILL_SEARCH`) + 默认 off | 0.5 天 |
| P92-G | 单元 + 集成测试 | 1.5 天 |

**估算总工时**:1 周。

### 1.4 架构设计

```
Skill sources
  ├─ ~/.clawcodex/skills/*/SKILL.md
  ├─ project .claude/skills/*/SKILL.md
  ├─ F-91 MCP discovered skill descriptors
  └─ F-95 Templates generated skills
           │
           ▼
SkillSearchDocument extractor
           │
           ▼
Tokenizer(normalize/casefold/split identifiers/stopwords)
           │
           ▼
TF-IDF Index
  ├─ doc_store: doc_id → SkillSearchDocument
  ├─ inverted_index: term → [(doc_id, tf)]
  ├─ idf: term → log((N+1)/(df+1))+1
  └─ persisted: ~/.clawcodex/skill_search/index.json
           │
           ▼
SkillSearcher.search(query, top_k=8)
           │
           ▼
SkillSearchResult(name, score, reason, source)
```

#### 包结构

```
clawcodex_ext/services/skill_search/
├── __init__.py
├── document.py              # P92-A: SkillSearchDocument + source adapters
├── tokenizer.py             # P92-B: normalize + split + stopwords
├── index.py                 # P92-C: TfIdfSkillIndex
├── searcher.py              # P92-D: SkillSearcher
├── watcher.py               # P92-E: registry change hooks
├── store.py                 # atomic JSON persistence
├── config.py                # SkillSearchConfig
└── exceptions.py

clawcodex_ext/skill_system/search_integration.py  # registry hook + query API
clawcodex_ext/feature_gate/registry.py            # P92-F flag

tests/services/skill_search/
├── test_tokenizer.py
├── test_index.py
├── test_searcher.py
└── fixtures/skills/
```

### 1.5 核心数据模型

```python
@dataclass(frozen=True)
class SkillSearchDocument:
    id: str                                # stable hash(source + name)
    name: str
    title: str
    description: str
    body: str                              # SKILL.md main content or MCP description
    source: Literal["local", "project", "mcp", "template"]
    tags: tuple[str, ...] = ()
    updated_at: str | None = None
    weight: float = 1.0                    # 本地显式 skill 权重 > MCP 自动 skill

    def text(self) -> str:
        return "\n".join([self.name, self.title, self.description, self.body, " ".join(self.tags)])


@dataclass(frozen=True)
class SkillSearchResult:
    document: SkillSearchDocument
    score: float
    matched_terms: tuple[str, ...]
    reason: str                            # 人读解释: matched "browser", "playwright"


@dataclass(frozen=True)
class SkillSearchConfig:
    enabled: bool = False
    top_k: int = 8
    min_score: float = 0.05
    index_path: Path = Path("~/.clawcodex/skill_search/index.json")
    refresh_interval_seconds: int = 300
    source_weights: dict[str, float] = field(default_factory=lambda: {
        "project": 1.3,
        "local": 1.1,
        "template": 1.0,
        "mcp": 0.9,
    })
```

### 1.6 核心接口

```python
class TfIdfSkillIndex:
    """轻量本地 TF-IDF skill 索引。"""

    def __init__(self, tokenizer: Tokenizer, *, config: SkillSearchConfig) -> None: ...

    def build(self, documents: Iterable[SkillSearchDocument]) -> None:
        """全量重建索引。"""

    def upsert(self, document: SkillSearchDocument) -> None:
        """增量更新单个 skill。"""

    def remove(self, document_id: str) -> None: ...

    def search(self, query: str, *, top_k: int | None = None) -> list[SkillSearchResult]: ...

    def save(self) -> Path: ...
    @classmethod
    def load(cls, path: Path, tokenizer: Tokenizer) -> "TfIdfSkillIndex": ...


class SkillSearcher:
    """对外高层 API,隐藏 index rebuild / cache / registry hooks。"""

    def __init__(self, registry: SkillRegistry, *, config: SkillSearchConfig) -> None: ...

    async def ensure_index(self) -> None: ...

    async def search(self, query: str, *, top_k: int = 8) -> list[SkillSearchResult]: ...

    async def refresh(self) -> None: ...
```

### 1.7 排名公式

```
score(doc, query) = source_weight(doc.source) * Σ(term ∈ query) tf(term, doc) * idf(term)^2 * field_boost(term)

field_boost:
  name/title match      = 3.0
  description match     = 2.0
  body match            = 1.0
  tags match            = 2.5

长度归一化:
  tf = raw_tf / sqrt(doc_token_count)
```

### 1.8 失败模式

| 错误 | 场景 | 处理 |
|------|------|------|
| `IndexCorruptError` | index.json 解析失败 | 删除并全量重建 |
| `SkillSourceError` | 某个 SKILL.md 解析失败 | 跳过该 skill + WARN |
| `SearchDisabledError` | Feature flag off | 返回空列表并允许 fallback 全量列表 |
| `EmptyQueryError` | query 空 | 返回最近 / pinned skills |

### 1.9 中英文分词策略

为兼顾中英文 skill 文档,默认采用混合 tokenizer:

| 语言 | 分词策略 | 实现 |
|------|----------|------|
| 英文 | 空白 + 标点 + camelCase 拆分 + 小写化 | `re.compile("[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z])")` |
| 中文 | 字 bigram + 可选 jieba(extras) | `itertools.pairwise`;detect via Unicode range |
| 混合 | 同一 query 中两种 token 拼接后统一进入 IDF | `_tokenize_mixed()` 统一入口 |

当安装 `jieba`(`pip install clawcodex[chinese]`)时,自动切到词级分词;否则维持字符 bigram(token 数量 ×14,索引大小可控)。

### 1.10 CLI / Tool 行为

#### `SkillSearchTool`(供 Agent 调用)

| action | 输入 | 输出 |
|--------|------|------|
| `search` | `query`, `top_k?`, `tags?`, `source?` | ranked skill 列表 + 分数 |
| `pin` / `unpin` | `name` | 设置 pinned skills(高优先级)|
| `inspect` | `name` | 索引中字段贡献度 + 命中 term |
| `rebuild` | - | 强制重建索引 |

#### 命令族(`/skills search`)

```
/skills search "browser automation" [--top-k 5]
/skills list [--source mcp]
/skills inspect <name>
/skills rebuild
/skills stats
```

CLI 默认对用户隐藏(纯内部命令),Agent 通过 Tool 接入。

### 1.11 验收标准

1. 100 个 skill 文档全量 build < 200ms;
2. 1000 个 skill 查询 top8 < 50ms;
3. 输入 `browser automation playwright` 排名中 `web_browser` skill 在 top3;
4. MCP 自动发现 skill 与本地 skill 一并可搜索,且同名不冲突;
5. index.json 损坏时自动重建,不影响启动;
6. Feature flag off 时零后台任务,不写 index;
7. 中文混合 query(如 "网页 自动化")与英文 query 命中同一 skill,排名稳定;
8. `pin` skills 在搜索结果中始终排在 unpinned 之上,但仍按 score 排序;
9. `inspect <name>` 给出每个命中 term 的字段贡献度,方便调试;
10. `rebuild` 命令幂等,可在 CI 上跑而不产生副作用;
11. 单元测试覆盖 tokenizer、IDF、rank、index persistence、Tool actions、并发刷新;
12. 集成测试:SkillListTool 搜索 + registry hook + MCP skill 命名空间均参与排序。

## §2 落地步骤

| 步骤 | 内容 | 工时 |
|------|------|------|
| 1 | document/tokenizer 实现 + 单测 | 2 天 |
| 2 | TF-IDF index + persistence | 2 天 |
| 3 | SkillSearcher + registry hook | 1 天 |
| 4 | Feature Gate + CLI debug 命令(`/skills search`) | 1 天 |
| 5 | 性能基准 + 集成测试 | 1 天 |

## §3 风险与缓解

| 风险 | 等级 | 缓解 |
|------|:----:|------|
| 纯 TF-IDF 对语义同义词弱 | 🟡 | 后续可接本地 embedding;当前优先低依赖 |
| 中文分词质量不高 | 🟡 | 字符 bigram + jieba optional extras |
| MCP skill 数量过大 | 🟠 | 增量索引 + topK + TTL rebuild |
| stale index | 🟡 | registry hook + 启动时 mtime 校验 |

## §4 与其他特性的关系

| 协同 | 说明 |
|------|------|
| **F-91 MCP Skills** | 自动发现的 MCP skill 进入检索索引 |
| **F-95 Templates** | 模板生成 skill 文档也纳入索引 |
| **F-69 Budget Mode** | budget aggressive 时只注入 topK skill,节省 token |
| **F-71 Tool Gap** | skill search 可辅助 `ExecuteTool` 选择工具 |

---

**关联文档**: [README.md 缺口矩阵](./README.md#a-全特性对照矩阵)