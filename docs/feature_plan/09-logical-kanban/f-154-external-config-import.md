# F-154 External Configuration Import for Ontology / Operation Schema / Method Library

## Goal

让用户 / 团队 / 社区可以**直接提供并消费外部配置文件**，把已有的领域知识接入 LKB，无需修改 LKB 源码或经由 LLM 自动生成。覆盖三类外部配置：

1. **Domain Ontology** — 领域概念、关系、分类（OWL / Turtle / RDF 格式）。
2. **Operation Schema** — 可分解操作的 precondition / effect（JSON / YAML 格式）。
3. **Method Library** — 工程分解模板（JSON 格式，F-150 内部 schema 的外部化）。

设计核心：**声明式、可 lint、显式导入、不执行任意代码**。

## Scope

### In-Scope

- 三种外部配置类型的格式规范（schema）文档。
- 统一导入接口 `ExternalConfigImporter`：
  - `import_file(path: Path) -> ImportResult`
  - `import_directory(path: Path, *, recursive: bool = True) -> list[ImportResult]`
  - `import_package(entry_point: str) -> ImportResult` — 通过 Python `entry_points` 注册的 `lkb_config_*` 包。
  - `import_url(url: str) -> ImportResult` — 远程 HTTP/HTTPS（如 GitHub raw）— 可选。
- 格式校验 / Lint：
  - JSON Schema 校验（method library / operation schema）。
  - RDFLib 解析（domain ontology）。
  - 跨文件引用一致性（ontology class 被 operation 引用、method 引用 operation）。
  - 命名规范（method_id / operation_id 唯一且符合规范）。
  - 版本兼容性（声明的 `min_lkb_version` 与运行版本匹配）。
- 优先级与冲突解决：
  - 加载顺序：`builtin < project < user < explicit_import`。
  - 显式 import 默认 strict（冲突报错）；可通过 `--force` 覆盖。
- 安全约束：
  - 单文件大小限制（默认 10MB）。
  - 禁止代码执行（不允许 `*.py`、不允许 JSON 内的 `__import__` 等）。
  - 路径白名单（默认仅允许相对路径，禁止 `/etc/`、`~` 之外的绝对路径需要确认）。
- CLI 命令：
  ```
  clawcodex-dev lkb import <path|url|entry-point>...
  clawcodex-dev lkb import --lint-only <path>     # 仅校验不导入
  clawcodex-dev lkb import --recursive <dir>      # 递归目录
  clawcodex-dev lkb import --force <path>         # 冲突时覆盖
  clawcodex-dev lkb import --list                 # 列出已注册的 entry_points
  clawcodex-dev lkb export --format=json <output> # 把当前 active library 导出
  ```
- `entry_points` 机制：第三方 Python 包可通过 `pyproject.toml` 声明 `[project.entry-points."lkb.configs"]` 注册预打包配置。
- 导入审计事件 `lkb_external_config_imported`，payload 含 `source` / `kind` / `version` / `item_count` / `lint_issues`。

### Out-of-Scope

- 远程签名 / 加密验证（不在 MVP；后续通过 GPG / sigstore 扩展）。
- 跨注册中心发现（PyPI / 自建 registry）— 仅本地文件 + `entry_points`。
- 双向同步（导入后再导出回原格式可能丢信息）— 导入为主，导出为辅。
- 自动升级 / 版本迁移工具 — 报错让用户手动处理。

## 当前基线

- F-150 已实现 `load_method_library(path: Path) -> tuple[EngineeringMethod, ...]`（JSON 单文件加载）。
- F-153 Phase 6 已设计"项目级 > 用户级 > 内置种子"的三层加载顺序（路径：`.lkb/methods/*.json`、`~/.cache/clawcodex/lkb/methods/*.json`）。
- F-150 的 method schema 是内部 dataclass，序列化时输出 JSON，但**未文档化为可消费 schema**。
- 没有统一的 ontology / operation schema 加载机制。
- 没有 lint / 版本校验。
- 没有 `entry_points` 注册机制。

**缺口**：用户无法把自己的领域知识（已存在的 ontology 文件、operation schema、method library）平滑接入 LKB；要么复制粘贴到内置种子（不现实），要么手动改源码（违反解耦原则）。

## 实施进度

### Phase 1 — 格式规范（~1 周）

1. **Method Library JSON Schema** (`docs/schemas/logical-kanban/method-library.schema.json`)：
   - 完整描述 `EngineeringMethod` / `SubtaskTemplate` / `AcceptanceTemplate` 的 JSON 表示。
   - 必填字段、可选字段、默认值。
   - 版本字段 `"schema_version": "1.0.0"`。
   - `min_lkb_version` 字段声明最低兼容版本。
2. **Operation Schema JSON Schema** (`docs/schemas/logical-kanban/operation-schema.schema.json`)：
   - 单个 operation 结构：
     ```json
     {
       "operation_id": "OP-deploy-service",
       "description": "...",
       "preconditions": ["ServiceBuilt()", "TestsPassed()"],
       "effects": ["ServiceRunning()"],
       "estimated_duration_minutes": 30,
       "required_resources": ["ci-runner"],
       "version": "1.0.0"
     }
     ```
   - 文件可包含多个 operation 的列表。
3. **Domain Ontology 格式**：
   - 优先使用 [Turtle (TTL)](https://www.w3.org/TR/turtle/) 格式（人类可读、广泛支持）。
   - 文档化最小可用子集：`owl:Class` / `owl:ObjectProperty` / `rdfs:subClassOf` / `rdfs:domain` / `rdfs:range`。
   - 提供最小模板 `docs/templates/logical-kanban/ontology-template.ttl`。
4. **Manifest 文件**（多文件目录场景）：
   ```json
   {
     "manifest_version": "1.0",
     "name": "my-team-lkb-config",
     "version": "1.2.0",
     "min_lkb_version": "0.5.0",
     "contents": [
       {"path": "ontology/domain.ttl", "kind": "ontology"},
       {"path": "operations/deploy.json", "kind": "operation_schema"},
       {"path": "methods/release.json", "kind": "method_library"}
     ]
   }
   ```

### Phase 2 — Importer Service（~1.5 周）

1. 新建 `clawcodex_ext/logical_kanban/external_config.py`：
   - `ExternalConfigImporter` 类。
   - `import_file(path)`：根据扩展名（`.json` / `.ttl` / `.yaml`）分发到对应 handler。
   - `import_directory(path, recursive)`：扫描目录，发现 `lkb-manifest.json` 后按 manifest 加载，否则按扩展名加载所有文件。
   - `import_package(entry_point)`：调用 `importlib.metadata.entry_points(group="lkb.configs")` 获取。
   - `import_url(url)`：HTTP GET（限制 HTTPS only + Content-Length 校验）。
   - 返回 `ImportResult`：`success: bool` / `kind: str` / `item_count: int` / `lint_issues: list[LintIssue]` / `source: str`。
2. 各种 handler：
   - `_load_method_library_json(path) -> tuple[EngineeringMethod, ...]` — 调用现有 `load_method_library`，但增加 schema_version 校验。
   - `_load_operation_schema_json(path) -> tuple[OperationSchema, ...]`。
   - `_load_ontology_turtle(path) -> OntologyGraph` — 用 RDFLib。
3. `OperationSchema` / `OntologyGraph` 数据类。
4. 注册到 LKB：
   - `OperationSchema` 注入到 `Layer1RuleEngine` 的 `preconditions` 验证（F-150 的 R-METHOD-001/002/003 沿用）。
   - `OntologyGraph` 暴露为 `AmbiguityDetector` 的可选输入（让 ontology 概念名解析"中间件"等术语）。
5. **新增 `Layer1RuleEngine` 规则（必做）**：
   - **R-METHOD-004**：当 `OperationSchema` 已注册时，`ProposedTask.lkbMetadata.assumptions` 引用的 operation 必须存在于已加载的 operation schema 集中；缺失记 `error`（阻断 commit）。
   - **R-METHOD-005**：当 `OntologyGraph` 已加载时，`ProposedTask.lkbMetadata.assertions` 中的术语若引用 ontology class，class 必须存在；缺失记 `warning`（不阻断，仅记录）。
   - 这两条规则是 F-150 / F-153 未覆盖的"外部 operation/ontology 注入"边界，否则 OperationSchema 与 OntologyGraph 加载后无规则消费，悬空。

### Phase 3 — Lint 校验（~1 周）

1. 新建 `clawcodex_ext/logical_kanban/external_config_lint.py`：
   - `lint_method_library(methods) -> list[LintIssue]`：
     - method_id 命名规范（`M-<kebab-case>-NNN`）。
     - subtask_templates 至少 3 个。
     - 内部引用一致（blocked_by 引用的 subtask 必须存在）。
   - `lint_operation_schema(ops)`：
     - operation_id 命名规范。
     - preconditions / effects 命题格式合法。
   - `lint_ontology(g)`：
     - RDFLib 解析无错。
     - owl:Class / owl:ObjectProperty 类型一致。
     - rdfs:domain / rdfs:range 引用的 class 已声明。
   - `lint_cross_references(methods, ops, g)`：
     - method.assumptions 引用 operation.preconditions 时 operation 必须存在。
     - operation.effects 引用 ontology class 时 class 必须存在。
   - 严重度：`error`（阻断导入）/ `warning`（导入但记录）。
2. `LintReport` 数据类：包含 `error_count` / `warning_count` / `issues: tuple[LintIssue, ...]`。

### Phase 4 — 优先级与冲突解决（~0.5 周）

1. `ExternalConfigImporter` 接受 `priority: Literal["builtin", "project", "user", "explicit"]`。
2. 同名冲突：
   - 严格模式（默认）：抛 `ConfigConflictError`，提示冲突双方。
   - `--force`：覆盖已有。
3. 三层自动加载（沿用 F-153 Phase 6）：
   - 启动时扫描：
     - 项目级 `<cwd>/.lkb/configs/`
     - 用户级 `~/.cache/clawcodex/lkb/configs/`
     - 内置种子（不可覆盖）。
   - 显式 import 在三者之上。
4. `lkb config list` CLI 列出当前已加载的所有配置（按 source + kind 分组）。

### Phase 5 — entry_points 注册（~0.5 周）

1. `entry_points` group 命名：`lkb.configs`。
2. 第三方包声明示例（写在包的 `pyproject.toml`）：
   ```toml
   [project.entry-points."lkb.configs"]
   my_team_methods = "my_team_lkb_configs.methods:get_method_library"
   ```
3. 入口点函数签名：`() -> tuple[EngineeringMethod, ...] | OperationSchema | OntologyGraph`。
4. CLI：`clawcodex-dev lkb import --list` 列出所有可用 entry_points。

### Phase 6 — 安全与限额（~0.5 周）

1. 单文件大小默认 10MB（可配置 `--max-size=20MB`）。
2. 路径校验：禁止 `/etc/`、`/proc/`、`/sys/`；禁止符号链接跳出当前 working dir。
3. URL 限制：仅 HTTPS；Content-Length 必须 ≤ `--max-size`。
4. 文件类型白名单：`.json` / `.ttl` / `.yaml`；拒绝 `.py` / `.exe` / `.so`。
5. JSON 不允许的字段：`__reduce__` / `__class__` 等 Python pickle 攻击向量（deep check）。

### Phase 7 — CLI 与审计（~0.5 周）

1. 在 `clawcodex_ext/cli/lkb_method_cmd/commands.py`（沿用 F-153 Phase 4 创建的子命令模块）追加 7 个 import/export 子命令，每个子命令的实现要点：
   - `lkb import <path|url|entry-point>...`：批量导入；支持多源（混用文件 + URL + entry_point）。
   - `lkb import --lint-only <path>`：仅运行 lint 校验，不实际导入，返回退出码（0=clean，1=warning，2=error）。
   - `lkb import --recursive <dir>`：递归扫描目录，识别 `lkb-manifest.json` 或按文件类型分发。
   - `lkb import --force <path>`：覆盖已有同名 method/operation/ontology，输出 `--dry-run` 预览（打印将被覆盖的 entity ID + source）。
   - `lkb import --list`：列出 `importlib.metadata.entry_points(group="lkb.configs")` 注册的所有可用 entry_points。
   - `lkb export --format=json <output>`：把当前 active library（含 builtin + project + user + explicit 四层合并结果）导出为 JSON，写到 `<output>`；ontology 用 Turtle 单独导出（`--format=ttl`）。
   - `lkb config list`：列出当前已加载的所有配置，按 source + kind 分组输出表格。
2. 错误信息友好性要求：
   - Lint error 必须包含 `file:line` / offending field path / 修复建议示例。
   - `ConfigConflictError` 必须列出冲突双方 `method_id` + `source` 路径。
3. `audit.py` 新增事件类型 `lkb_external_config_imported`，payload 含 source / kind / version / item_count / lint_issue_count / lint_error_count。
4. Lint error 阻断 commit 但不阻断 import（用户可选择 --force 导入后人工修正）。

### Phase 8 — 测试与文档（~1.5 周）

1. 单元测试：
   - 三种格式的 happy path + 错误用例。
   - Lint 校验（每条规则至少 1 个测试）。
   - 冲突检测 + --force。
   - entry_points mock 测试。
   - 安全校验（恶意路径、过大文件、URL 注入）。
   - 跨格式引用一致性。
2. 集成测试：
   - 端到端：用户提供 ttl + json + yaml → import → LLM 在 decompose 时引用方法 + ontology。
3. 文档：
   - `docs/feature_plan/09-logical-kanban/f-154-user-guide.md` — 完整使用指南。
   - `docs/schemas/logical-kanban/method-library.schema.json` — JSON Schema。
   - `docs/schemas/logical-kanban/operation-schema.schema.json` — JSON Schema。
   - `docs/templates/logical-kanban/ontology-template.ttl` — 最小 ontology 模板。
   - `docs/feature_plan/09-logical-kanban/f-154-entry-points.md` — 第三方包打包指南。
4. 示例仓库（**硬交付，与 user-guide 一一对应**）：`examples/external-configs/` 必须包含 3 个场景的完整可运行配置：
   - `examples/external-configs/k8s-deploy/`：Kubernetes 部署场景，含 ontology（Pod / Service / Deployment 等 K8s 概念）+ operation schema（`OP-rolling-update` / `OP-canary-deploy` / `OP-rollback`）+ method library（M-deploy-canary-001 等）。
   - `examples/external-configs/data-engineering/`：数据工程场景，含 ontology（Pipeline / DAG / Dataset）+ operation schema（`OP-ingest-batch` / `OP-transform-spark`）+ method library。
   - `examples/external-configs/security-fix/`：安全修复场景，含 ontology（CVE / Vulnerability / Patch）+ operation schema（`OP-apply-patch` / `OP-rotate-credential`）+ method library（M-fix-cve-001）。
5. 用户指南 `f-154-user-guide.md` 的 3 个真实场景示例必须引用同一份 `examples/external-configs/` fixture（一份 fixture 三处引用），确保文档与代码同步。

## 验收标准

- [ ] 三种外部配置格式的 schema 文档完整且可独立消费。
- [ ] `ExternalConfigImporter` 支持 file / directory / entry_point / url 四种来源。
- [ ] Lint 校验覆盖 method / operation / ontology / cross-reference 四类。
- [ ] 加载顺序 `builtin < project < user < explicit` 实现，冲突 strict / force 双模式。
- [ ] `entry_points` group `lkb.configs` 注册机制可用，第三方包可通过 pyproject.toml 声明。
- [ ] 安全约束：单文件 ≤10MB（可配置）、路径白名单、HTTPS-only URL、文件类型白名单、JSON pickle 攻击防护。
- [ ] CLI 7 个子命令（`import` / `import --lint-only` / `import --recursive` / `import --force` / `import --list` / `export` / `config list`）可用。
- [ ] 审计事件 `lkb_external_config_imported` 在每次导入时发射。
- [ ] 现有 319 + 13 + F-150/151/152/153 测试全部通过，无回归。
- [ ] 新增至少 40 个 F-154 单元测试（覆盖三种格式 + lint + 安全 + entry_points + 端到端）。
- [ ] 用户指南 `f-154-user-guide.md` 含 3 个真实场景示例（k8s / data-eng / security），与 `examples/external-configs/` 中的 fixture 一一对应。
- [ ] `Layer1RuleEngine` 新增 R-METHOD-004（operation schema 引用校验，error 级）和 R-METHOD-005（ontology class 引用校验，warning 级），对应 Phase 2 第 5 步；否则 OperationSchema 与 OntologyGraph 加载后悬空。

## 风险与约束

| 风险 | 缓解 |
|------|------|
| 外部文件 schema 演进不兼容 | 强制 `schema_version` 字段；不匹配时报错而非 silently 接受 |
| 跨格式引用出错（method 引用不存在的 operation） | cross-reference lint 校验 + 导入时一次性解析所有引用 |
| 第三方包通过 entry_points 注入恶意代码 | 入口点签名限制（必须返回数据对象而非执行副作用）；白名单允许的 entry_points 来源（本地 installed packages） |
| ontology 大文件导致加载慢 | 大小限制 + 流式解析（RDFLib 支持） |
| URL 远程拉取引入网络依赖 | URL 导入显式 `--url` flag；默认仅本地 + entry_points |
| 路径遍历攻击（`../etc/passwd`） | 路径白名单 + realpath 校验 + 拒绝符号链接 |
| 命名冲突导致方法库污染 | strict mode 默认拒绝冲突；显式 --force 才覆盖 |
| 文档与实现脱节 | 用户指南中的示例必须与测试用例一一对应（同一份 fixture） |
| import 钩子被滥用于修改 LKB 内置行为 | 不允许 entry_points 修改任何 LKB 状态；仅返回数据对象 |

## 已拟定的设计决定

1. **三格式而非单一格式**：ontology（OWL/Turtle）必须用 RDF 标准，因为已有大量现成本体可复用；operation schema / method library 用 JSON 因为 F-150 内部就是 JSON，易衔接。
2. **声明式 + 无代码执行**：所有外部格式均为纯数据，不允许嵌入 Python 代码。这从根本上避免远程代码执行风险。
3. **`entry_points` 是 Python 生态系统的标准扩展机制**：避免自建 plugin 注册系统，第三方包开发者零学习成本。
4. **lint error 阻断，warning 仅记录**：method_id 冲突、跨引用错误 = error；命名建议、文档缺失 = warning。
5. **导入是数据导入而非配置覆盖**：用户提供的 ontology / method 是**补充**而非**替换** LKB 内置种子；这与 F-153 三层加载顺序一致。
6. **schema 文档就是规范**：JSON Schema 文件同时用于运行时校验与用户文档；双重用途减少维护负担。

## 依赖与协同

**依赖**：
- F-150（method library JSON 序列化基础）
- F-153（method_governance 状态机 + 三层加载顺序）
- F-132（Layer1RuleEngine 用于 operation schema 校验）
- RDFLib（外部依赖，用于 ontology 解析）
- `importlib.metadata`（标准库，用于 entry_points）

**被依赖**：
- （后续）第三方 LKB 配置包（lkb-config-k8s、lkb-config-data-eng 等）
- F-152（SchedulingSolver 可使用 operation schema 中的 `estimated_duration`）

**协同**：
- 与 F-149（automatic task decomposition）：import 的 method 直接被 F-149 + F-151 的 prompt 摘要复用。
- 与 F-134（fuzzy patterns）：ontology 中的概念名可作为 `AmbiguityDetector` 的术语词典，提升术语识别准确率。
- 与 F-141（causal layer）：ontology 中的因果关系（`causes` / `enables`）可直接喂入因果层。

## 文件变更清单

```
NEW  docs/schemas/logical-kanban/method-library.schema.json        # ~150 行 JSON Schema
NEW  docs/schemas/logical-kanban/operation-schema.schema.json      # ~120 行 JSON Schema
NEW  docs/templates/logical-kanban/ontology-template.ttl            # ~30 行 Turtle
NEW  docs/feature_plan/09-logical-kanban/f-154-user-guide.md                    # ~400 行
NEW  docs/feature_plan/09-logical-kanban/f-154-entry-points.md                  # ~150 行
NEW  clawcodex_ext/logical_kanban/external_config.py                            # ~500 行
NEW  clawcodex_ext/logical_kanban/external_config_lint.py                       # ~350 行
NEW  clawcodex_ext/logical_kanban/operation_schema.py                           # ~150 行（dataclass）
NEW  clawcodex_ext/logical_kanban/ontology_graph.py                             # ~100 行（dataclass + RDFLib wrapper）
MOD  clawcodex_ext/logical_kanban/method_library.py                            # +30 行（schema_version 校验 + min_lkb_version）
MOD  clawcodex_ext/logical_kanban/audit.py                                     # +30 行（lkb_external_config_imported 事件）
MOD  clawcodex_ext/logical_kanban/__init__.py                                   # +10 行（export）
MOD  clawcodex_ext/cli/lkb_method_cmd/commands.py                              # +200 行（import / export / config 子命令）
MOD  clawcodex_ext/cli/subcommand_registry.py                                  # +2 行（lkb_method_cmd 已自动加载）
MOD  pyproject.toml                                                            # +3 行（rdflib 可选依赖 + lkb.configs entry_points 声明示例）
NEW  tests/logical_kanban/test_f154_external_config.py                         # ~500 行（含 fixtures）
NEW  examples/external-configs/                                                # 示例目录（methods.json + ops.json + domain.ttl）
```

## 估算工作量

| 阶段 | 工时 |
|------|------|
| Phase 1 — 格式规范 | 1 周 |
| Phase 2 — Importer Service | 1.5 周 |
| Phase 3 — Lint 校验 | 1 周 |
| Phase 4 — 优先级与冲突解决 | 0.5 周 |
| Phase 5 — entry_points 注册 | 0.5 周 |
| Phase 6 — 安全与限额 | 0.5 周 |
| Phase 7 — CLI 与审计 | 0.5 周 |
| Phase 8 — 测试与文档 | 1.5 周 |
| **总计** | **7 周** |

## 与其他 F-N 的依赖图（更新）

```
F-149 DecompositionPlan / ProposedTask / TaskDecomposer
   │
   ▼
F-150 method_library + EngineeringMethod + 白名单扩展
   │
   ├─▶ F-151 prompt 注入 + method_ref 字段
   │
   ├─▶ F-152 SchedulingSolver + Schedule 字段
   │
   ├─▶ F-153 治理 + CLI + 覆盖率（依赖 F-150 + F-151）
   │
   └─▶ F-154 外部配置导入（依赖 F-150 + F-153）
       ▲
       └─ 第三方包（lkb-config-xxx）通过 entry_points 注册
```

## 推荐实施顺序

1. **F-150** 先完成（method library JSON 基础）
2. **F-153** 完成 method_governance（提供 lint 钩子）
3. **F-154** 可启动（依赖 F-150 的 JSON 序列化 + F-153 的 lint 基础）

或与 F-151 / F-152 并行（F-154 不依赖它们）。