# F-179: 上下文即代码（CaC）— 声明式 Context Pack 与校验 CLI（DC-014）

> 状态: 📋 规划中  
> 设计来源: [动态上下文总览](../dynamic-context-index.md) — DC-014

## §0 元信息

| 字段 | 值 |
|------|---|
| 覆盖 DC | DC-014 上下文即代码 |
| Wave | Wave 3 / P3 |
| 前置依赖 | F-119、F-130、F-158~F-178 |
| 落地形态 | YAML/TOML schema、编译器、lint/test/diff/apply CLI |

## §1 设计规划

将 Mode、继承关系、工具权限、约束和策略定义为可版本控制的 Context Pack。编译器把声明式配置转换为运行时 ContextNode；临时会话调整只走运行时 API，禁止回写 pack。

## §2 子特性与验收

| 编号 | 子特性 | 验收 |
|------|--------|------|
| P179-A | Pack schema 与继承 | 非法继承、循环和未知 section 会被 lint 拒绝 |
| P179-B | 编译与 dry-run | `ctx apply --dry-run` 可展示有效上下文 |
| P179-C | 测试与 diff | 可对 mock 输入断言 section 的包含/排除 |

## §3 风险

声明文件可能膨胀；提供起步模板、层级深度限制和明确的临时覆盖边界。

## §4 实施规格

**文件落点**：`extensions/context_packs/{schema,parser,compiler,lint,cli}.py`、`tests/context_packs/`；项目内 pack 位于 `.ctx/packs/<id>/pack.yaml`。schema 固定校验 id、version、extends、sections、tools、constraints、policies 与 permissions，继承深度上限为 3，禁止循环继承和未声明的 section 引用。

`ctx lint` 仅校验；`ctx compile` 输出可复现 hash；`ctx diff` 输出有效 section/权限变化；`ctx apply --dry-run` 不写 registry，`ctx apply` 才通过 F-119 编译为 ContextNode。运行时 override 必须位于 session overlay，绝不回写源 pack。

实施顺序：JSON Schema + parser → compiler/lint → CLI → fixture 测试与文档模板。验收包括：相同输入 hash 稳定、循环继承失败、dry-run 无副作用、权限扩大在 diff 中高亮。
