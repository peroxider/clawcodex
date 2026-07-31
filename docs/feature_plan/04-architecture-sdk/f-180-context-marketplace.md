# F-180: 上下文市场 — Context Pack 分发、版本与签名（DC-016）

> 状态: 📋 规划中  
> 设计来源: [动态上下文总览](../dynamic-context-index.md) — DC-016

## §0 元信息

| 字段 | 值 |
|------|---|
| 覆盖 DC | DC-016 上下文市场 |
| Wave | Wave 3 / P3 |
| 前置依赖 | F-179 Context-as-Code |
| 落地形态 | 本地 pack 仓库、可选远程 registry、签名与兼容性检查 |

## §1 设计规划

以 F-179 的 Pack 格式作为唯一分发格式。初版只支持 `.ctx/packs/` 本地导入导出；远程 registry 是后续可选能力，必须经签名、权限声明和依赖解析后才能安装。

## §2 子特性与验收

| 编号 | 子特性 | 验收 |
|------|--------|------|
| P180-A | 本地 pack 生命周期 | 可 add/list/remove 并解析依赖 |
| P180-B | 版本与兼容性 | 语义化版本冲突在安装前报告 |
| P180-C | 安全供应链 | 远程包默认不信任，未签名包不得自动加载 |

## §3 风险

远程 pack 可注入恶意提示词或权限声明；默认禁用远程源，并要求显式批准每项工具权限。

## §4 实施规格

**文件落点**：`extensions/context_marketplace/{manifest,repository,resolver,signing,cli}.py`、`tests/context_marketplace/`。manifest 复用 F-179 schema，并增加 publisher、digest、signature、license、dependency constraints 与 requested permissions；本地缓存统一放在 `.ctx/cache/`，安装目录为 `.ctx/packs/`。

`ctx pack add <ref>` 的执行顺序必须是下载到临时目录 → digest/signature 校验 → F-179 lint/compile → 依赖求解 → 展示新增权限 → 用户确认 → 原子安装。缺签名的远程包、循环/冲突依赖和权限升级均 fail closed；本地导入也必须 lint。

实施顺序：本地 export/import → resolver 与 lockfile → 签名校验 → 可选远程 registry。验收包括：安装失败不污染现有包、lockfile 可复现、撤销签名被拒绝、升级显示权限 diff。
