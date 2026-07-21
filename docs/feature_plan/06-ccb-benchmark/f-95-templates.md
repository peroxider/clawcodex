# F-95: TEMPLATES 模板系统

> 状态: ✅ 已完成(`clawcodex_ext/services/templates/` 14 模块 + `/template` 命令族 + renderer/generator/catalogue/compatibility/schema)
> 章节: `docs/feature_plan/06-ccb-benchmark/f-95-templates.md`
> 最后更新: 2026-07-21
> 缺口来源: gap-analysis-2026q2.md §3.3(`#### F-95: TEMPLATES 模板系统`,已分解到本文档 §0)

## §0 缺口摘要

> 本节为 gap-analysis-2026q2.md §3.3 F-95 派工条目的分解版本;详细设计与基线请阅读 §1。

### 0.1 缺口描述

基础已经完整,但**主要缺口是产品化层**:

- 已有 `clawcodex_ext/services/templates/models.py:Template`(id / title / description / fields / metadata / source dataclass);
- 已有 `registry.py:TemplateRegistry`(RLock + register / get / list / discover + `.yml/.yaml/.json` 多文件);
- 已有 `discovery.py`(user / project / managed 路径解析);
- 已有 `bootstrap.py`(built-in → user → project → managed 多源合并,last-wins);
- 已有 `resolver.py:TemplateResolver.resolve()`(list-replace / dict-recursive / scalars override-wins 深度合并);
- 已有 `built_in.py` 五个内置 agent 模板(general-purpose / explore / plan / fix / review);
- 已有 `extensions/orchestrator/templates/` 中 workflow / issue-card markdown 模板;

完全缺失:

- 跨 `TemplateKind`(agent / skill / workflow / prompt / issue / generic);
- 变量 schema:`TemplateVariable` / required / pattern / choices / secret / default;
- 无代码执行的安全渲染器(`{{ name }}` 占位符替换,禁 Jinja eval);
- 从模板生成 skill / workflow / agent 文件的落地 API(`TemplateGenerator`);
- catalogue 搜索 / 标签 / 预览 / 版本与兼容性校验;
- `/template` CLI / TUI 命令族;
- 与 F-92 Skill Search 索引协同。

### 0.2 对标

- CCB `TEMPLATES` 统一 catalogue,跨 agent / skill / workflow / orchestrator 类型;
- CCB 严格变量替换(无 Jinja eval 代码执行)+ `secret=True` 变量脱敏;
- CCB path containment(生成路径必须限制在 workspace 或允许 config dir);
- CCB overwrite 显式(写文件默认不覆盖,`--overwrite` 才覆盖);
- CCB 失败模式:`TemplateNotFoundError` 返回相似模板建议 / `TemplateRenderError` 列出缺失变量等。

### 0.3 解耦落地路径(全部增量在 `clawcodex_ext/services/templates/`,不动现有 registry)

- `models.py` 扩展 `TemplateKind` / `TemplateVariable` / `TemplateManifest` / `RenderedTemplate`;
- `renderer.py:TemplateRenderer` — 安全替换渲染器(`{{ name }}` + 上限 size)+ secret redaction;
- `generator.py:TemplateGenerator` — 写 agent / skill / workflow / prompt 文件 + path containment;
- `catalogue.py:TemplateCatalogue` — list / search / describe / preview;
- `compatibility.py` — `min_clawcodex_version` / `schema_version` 校验;
- `extensions/orchestrator/templates/*.template.md` — 现有 markdown 模板统一纳入 bootstrap;
- `clawcodex_ext/command_system/template_commands.py` — `/template list|show|search|preview|render|create|install|validate`;
- `clawcodex_ext/tui/template_picker.py` — 交互式 picker(可后续)。

### 0.4 依赖

- 现有 `TemplateRegistry` / `TemplateResolver` / `bootstrap` / `built_in` 不动,只做增量;
- F-92 Skill Search(模板生成的 skill 自动纳入 TF-IDF 索引);
- F-91 MCP Skills(可从 MCP descriptor 生成模板);
- F-93 TeamMem(team 可共享推荐模板或 project template 约定);
- F-110 Workflow Engine(workflow 模板可直接生成 declarative workflow 配置)。

### 0.5 估算工时

1 周(单人)。

---

## §1 设计规划

### 1.1 目标

对标 CCB `TEMPLATES` 能力,把 ClawCodex 现有的 agent template registry 扩展为统一模板系统:不仅能为 AgentDefinition 提供字段默认值,还要支持 template catalogue、变量渲染、模板实例生成、skill/workflow/agent 跨类型模板、CLI/TUI 选择器、与 F-91/F-92 Skill 系统联动。

F-95 的目标是让用户能够通过模板快速生成一致的 agent、skill、workflow、orchestrator issue card 或 prompt 片段,同时保留当前已经实现的轻量 `Template` / `TemplateRegistry` / `TemplateResolver` 设计。

### 1.2 当前基线

已完成基础:

1. `clawcodex_ext/services/templates/models.py` 定义 `Template` 数据模型,包含 `id/title/description/fields/metadata/source`;
2. `registry.py` 支持 in-memory registry、single-file persistence、目录扫描、线程安全 register/list/get;
3. `discovery.py` 支持 user/project/managed 模板路径解析;
4. `bootstrap.py` 支持 built-in → user → project → managed 多源 bootstrap 与覆盖优先级;
5. `resolver.py` 支持 base template + inline override 深度合并;
6. `built_in.py` 已提供 `general-purpose/explore/plan/fix/review` 五个内置 agent 模板;
7. `extensions/orchestrator/templates/` 已有 workflow / issue-card markdown 模板。

主要缺口:

- 当前 `Template` 主要是 agent config fields,缺少跨类型 template kind;
- 缺少变量 schema、required vars、渲染器与安全替换规则;
- 缺少 `/template` CLI/TUI 命令族;
- 缺少“从模板生成 skill / workflow / agent 文件”的落地 API;
- 缺少模板 catalogue 的搜索、标签、预览、版本与兼容性校验;
- 缺少与 F-92 Skill Search 的索引协同。

### 1.3 子特性分解

| 编号 | 子特性 | 预计工作量 |
|:----:|--------|:----------:|
| P95-A | 扩展数据模型:`TemplateKind`, `TemplateVariable`, `RenderedTemplate` | 1 天 |
| P95-B | 安全渲染器:`TemplateRenderer` + strict variable substitution | 1.5 天 |
| P95-C | 生成器:`TemplateGenerator` 生成 agent/skill/workflow/prompt 文件 | 2 天 |
| P95-D | Catalogue 与搜索:tags/category/kind/source/filter + F-92 index adapter | 1 天 |
| P95-E | CLI/TUI:`/template list/show/render/create/install` | 1.5 天 |
| P95-F | Orchestrator 模板统一纳入 registry | 1 天 |
| P95-G | 版本/兼容性校验:`min_clawcodex_version`, `schema_version` | 0.5 天 |
| P95-H | 单元 + 集成测试 | 2 天 |

**估算总工时**:1 周。

### 1.4 架构设计

```
Template sources
  ├─ built-in Python templates
  ├─ ~/.clawcodex/templates/*.yaml
  ├─ <project>/.clawcodex/templates/*.yaml
  ├─ /etc/clawcodex/templates/*.yaml
  └─ extensions/orchestrator/templates/*.template.md
             │
             ▼
TemplateRegistry(existing)
  ├─ Template(id/title/fields/metadata/source)
  ├─ discovery/bootstrap/resolver(existing)
  └─ extended kind/vars/schema metadata
             │
             ├────────────▶ TemplateCatalogue(search/filter/preview)
             │
             ├────────────▶ TemplateRenderer(vars → rendered content)
             │
             └────────────▶ TemplateGenerator
                              ├─ AgentDefinition file
                              ├─ Skill SKILL.md / manifest
                              ├─ Workflow markdown/yaml
                              └─ Prompt snippet
```

#### 包结构

```
clawcodex_ext/services/templates/
├── models.py                    # 扩展 TemplateKind / TemplateVariable
├── renderer.py                  # P95-B: safe rendering
├── generator.py                 # P95-C: materialize files
├── catalogue.py                 # P95-D: filtering/search/preview
├── compatibility.py             # P95-G: version/schema checks
├── registry.py                  # 已有:register/discover/list
├── resolver.py                  # 已有:field merge
└── bootstrap.py                 # 已有:multi-source bootstrap

clawcodex_ext/command_system/
└── template_commands.py         # P95-E: /template command family

clawcodex_ext/tui/
└── template_picker.py           # P95-E: interactive picker(optional)

extensions/orchestrator/templates/
└── *.template.md                # P95-F: imported as prompt/workflow templates

tests/clawcodex_ext/services/templates/
├── test_renderer.py
├── test_generator.py
├── test_catalogue.py
└── test_template_commands.py
```

### 1.5 核心数据模型

```python
TemplateKind = Literal["agent", "skill", "workflow", "prompt", "issue", "generic"]


@dataclass(frozen=True)
class TemplateVariable:
    name: str
    description: str
    required: bool = True
    default: str | int | float | bool | None = None
    pattern: str | None = None
    choices: tuple[str, ...] = ()
    secret: bool = False


@dataclass(frozen=True)
class TemplateManifest:
    id: str
    title: str
    kind: TemplateKind
    description: str | None = None
    variables: tuple[TemplateVariable, ...] = ()
    tags: tuple[str, ...] = ()
    category: str | None = None
    schema_version: str = "1"
    min_clawcodex_version: str | None = None
    output_path_template: str | None = None


@dataclass(frozen=True)
class RenderedTemplate:
    template_id: str
    kind: TemplateKind
    content: str
    output_path: Path | None
    variables_used: Mapping[str, object]
    warnings: tuple[str, ...] = ()
```

保持兼容策略:

- 现有 `Template.metadata` 承载 `kind/tags/category/schema_version/min_clawcodex_version/variables`;
- `Template.fields` 继续作为 agent config 默认值或渲染输入默认值;
- 不破坏 `TemplateResolver.resolve()` 的纯合并语义;
- 渲染器是新增层,不改变 registry 的轻量职责。

### 1.6 模板文件格式

#### Agent config 模板(现有兼容)

```yaml
id: python-fix
kind: agent
title: Python Fix Agent
description: Focused Python bug-fix agent.
fields:
  tools: ["Read", "Grep", "Edit", "Bash"]
  permission_mode: acceptEdits
  max_turns: 30
metadata:
  tags: [python, fix]
  schema_version: "1"
```

#### Skill 生成模板

```yaml
id: skill-from-tool
kind: skill
title: Skill from Tool
variables:
  - name: skill_name
    description: Skill directory name.
    required: true
    pattern: "^[a-zA-Z0-9_-]+$"
  - name: description
    description: Short skill description.
    required: true
fields:
  output_path_template: ".claude/skills/{{ skill_name }}/SKILL.md"
  content_template: |
    # {{ skill_name }}

    {{ description }}

    ## When to use

    Use this skill when {{ use_case }}.
```

#### Workflow markdown 模板

```yaml
id: orchestrator-workflow
kind: workflow
title: Orchestrator Workflow
fields:
  output_path_template: "workflow.md"
  content_template_ref: "extensions/orchestrator/templates/workflow.template.md"
```

### 1.7 渲染与安全规则

| 规则 | 说明 |
|------|------|
| strict variables | 模板引用未提供且无默认值的变量时报错 |
| no code execution | 不支持 Python eval/Jinja 任意表达式;仅 `{{ name }}` 占位符替换 |
| output path containment | 生成路径必须限制在 workspace 或允许的 config dir 内 |
| secret redaction | `secret=True` 变量不写入 audit/log/preview |
| deterministic preview | preview 不写文件,只返回 content/path/warnings |
| overwrite explicit | 写文件默认不覆盖,覆盖需 `--overwrite` |

### 1.8 核心接口

```python
class TemplateRenderer:
    """安全、无代码执行的变量替换渲染器。"""

    def render(
        self,
        template: Template,
        variables: Mapping[str, object],
        *,
        workspace_root: Path | None = None,
    ) -> RenderedTemplate: ...

    def preview(
        self,
        template: Template,
        variables: Mapping[str, object],
    ) -> RenderedTemplate: ...


class TemplateGenerator:
    """把模板渲染结果写入 agent/skill/workflow/prompt 文件。"""

    def generate(
        self,
        rendered: RenderedTemplate,
        *,
        overwrite: bool = False,
    ) -> Path: ...


class TemplateCatalogue:
    """模板浏览、过滤、搜索 API。"""

    def list(
        self,
        *,
        kind: TemplateKind | None = None,
        source: str | None = None,
        tags: Iterable[str] = (),
    ) -> list[Template]: ...

    def search(self, query: str, *, top_k: int = 20) -> list[Template]: ...

    def describe(self, template_id: str) -> TemplateManifest: ...
```

### 1.9 CLI/TUI 行为

```
/template list [--kind agent|skill|workflow|prompt] [--source project]
/template show <template-id>
/template search "python review"
/template preview <template-id> --var key=value
/template render <template-id> --var key=value --output path
/template create skill --name browser-automation
/template install <path-or-url>   # 仅本地 path 初版;远程安装另行审批
/template validate <file>
```

TUI 可以在后续提供 picker:

- 按 kind/source/category 分组;
- 展示变量表单;
- preview diff;
- 写入前确认 output path 与 overwrite。

### 1.10 失败模式

| 错误 | 场景 | 处理 |
|------|------|------|
| `TemplateNotFoundError` | id 不存在 | 返回相似模板建议 |
| `TemplateValidationError` | YAML/JSON schema 不合法 | 标出字段路径 |
| `TemplateRenderError` | required variable 缺失 | 列出缺失变量 |
| `TemplateUnsafePathError` | output path 逃逸 workspace | 拒绝写入 |
| `TemplateOverwriteError` | 目标文件存在 | 需要显式 overwrite |
| `TemplateCompatibilityError` | schema_version / min version 不兼容 | 拒绝或 warning |
| `TemplateCatalogueStaleError` | index 过期 | 重扫 registry |

### 1.11 验收标准

1. 现有 `TemplateRegistry` / `TemplateResolver` 测试继续通过;
2. `/template list` 能列出 built-in/user/project/managed 模板并按 source 过滤;
3. `/template search python` 能按 title/description/tags 返回相关模板;
4. `TemplateRenderer` 对未提供 required variable fail fast;
5. 渲染器不执行任意表达式,仅替换 `{{ name }}`;
6. `TemplateGenerator` 默认不覆盖已有文件;
7. skill 模板可生成 `.claude/skills/<name>/SKILL.md`,并可被 F-92 纳入搜索;
8. orchestrator markdown 模板能作为 workflow/issue kind 出现在 catalogue;
9. path traversal 输出路径用例全部拒绝;
10. 单元测试覆盖 renderer/generator/catalogue/CLI 关键路径。

## §2 落地步骤

| 步骤 | 内容 | 涉及子特性 | 工时 |
|:----:|------|:----------:|:----:|
| 1 | 扩展 metadata 解析为 `TemplateManifest` / `TemplateVariable` | P95-A/G | 1 天 |
| 2 | 实现无代码执行的 `TemplateRenderer` | P95-B | 1.5 天 |
| 3 | 实现 `TemplateGenerator` 写文件与 path containment | P95-C | 2 天 |
| 4 | 实现 `TemplateCatalogue` list/search/describe | P95-D | 1 天 |
| 5 | 把 `extensions/orchestrator/templates/` 纳入 bootstrap/catalogue | P95-F | 1 天 |
| 6 | 增加 `/template` 命令族 | P95-E | 1.5 天 |
| 7 | 补齐测试与 fixture | P95-H | 2 天 |

## §3 风险与缓解

| 风险 | 等级 | 缓解 |
|------|:----:|------|
| 模板渲染引入代码执行风险 | 🔴 | 禁用 Jinja 任意表达式,只做占位符替换 |
| 生成文件覆盖用户内容 | 🟠 | 默认不覆盖 + preview + explicit overwrite |
| 输出路径逃逸 workspace | 🔴 | resolve + containment check + 禁止绝对路径默认写入 |
| registry 与 generator 职责混淆 | 🟡 | registry 只发现/保存;renderer/generator 单独模块 |
| 现有 agent template 兼容性破坏 | 🟠 | metadata 扩展,不改变 `Template.fields` 语义 |
| template catalogue 搜索重复实现 | 🟡 | F-92 落地后复用 tokenizer/index adapter |

## §4 与其他特性的关系

| 协同 | 说明 |
|------|------|
| **F-91 MCP Skills** | 可从 MCP skill descriptor 生成本地 skill 模板 |
| **F-92 Skill Search** | 模板生成 skill 后纳入 TF-IDF 索引;catalogue 也可复用搜索 |
| **F-93 TeamMem** | team 可共享推荐模板或 project template 约定 |
| **F-87 Ultraplan** | plan 模板可生成标准化分阶段 workflow |
| **F-110 Workflow Engine** | workflow 模板可直接生成 declarative workflow 配置 |
| **Orchestrator** | 现有 issue/workflow template 统一纳入 F-95 catalogue |

---

## §5 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-07-21 | 代码落地并标记完成 | `clawcodex_ext/services/templates/` 14 模块 + `/template list/show/search/preview/render/create/install/validate` 命令族 + `tests/command_system/test_template_commands.py` |
| 2026-07-01 | 初始创建(从 gap-analysis 派工) | 基础 registry/discovery/resolver 已存在,需补齐产品化闭环 |

**关联文档**: [README.md 缺口矩阵](./README.md#a-全特性对照矩阵), [F-92 Skill Search](./f-92-skill-search.md), [F-91 MCP Skills](./f-91-mcp-skill-discovery.md)
