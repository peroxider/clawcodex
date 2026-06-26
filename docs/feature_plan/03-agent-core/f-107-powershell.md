# F-107: PowerShell 支持增强

> 状态: 📋 规划中
> 章节: docs/feature_plan/03-agent-core/f-107-powershell.md
> 最后更新: 2026-06-24

## §1 设计规划

### 1.1 目标

让 ClawCodex 的 BashTool 能够感知并适配 Windows 原生 shell（PowerShell），涵盖工具级 shell 选择、PowerShell 兼容的进程启动与 CWD 追踪、命令集分类/安全/只读/语义适配，以及 Windows 平台自动检测与优雅降级。

### 1.2 当前基线

| 组件 | 当前行为 |
|------|---------|
| 进程启动 | 硬编码 `["bash", "-lc", wrapped]` |
| 后台执行 | 硬编码 `["bash", "-lc", wrapped]` |
| 工具名 | `BASH_TOOL_NAME = "Bash"` |
| CWD 追踪 | `pwd > {path}` + bash 包装 |
| 搜索分类 | 仅 POSIX 命令集 |
| 只读验证 | 仅 POSIX 命令集 |
| 命令语义 | 仅 POSIX 退出码解释 |
| 安全分析 | tree-sitter-bash AST 解析器 |

### 1.3 子特性分解

| # | 子特性 | 改动文件 | 改动量 | 风险 | 预计工时 |
|:-:|--------|----------|:------:|:----:|:--------:|
| A | 工具 schema 扩展 + shell 检测 | bash_tool.py | ~80 行 | 低 | 0.5d |
| B | 进程启动层适配 | bash_tool.py, background.py | ~120 行 | 低 | 1d |
| C | 工具 Prompt 适配 | prompt.py | ~60 行 | 低 | 0.5d |
| D | 命令分类适配 | search_classification.py, read_only_validation.py | ~120 行 | 中 | 1d |
| E | 命令语义 & 退出码适配 | command_semantics.py | ~40 行 | 低 | 0.5d |
| F | PowerShell 安全分析 | bash_security.py + powershell_security.py | ~200 行 | 中 | 1.5d |
| G | 技能系统 shell 传播 | skill.py, runtime_substitution.py | ~30 行 | 中 | 0.5d |
| H | Shell 基础设施统一 | shell_resolver.py | ~80 行 | 低 | 0.5d |

**预计总工时**: 6-8 天

### 1.4 实施建议顺序

```
Phase 1 (1-2d): [H] 基础设施统一 → [A] schema + shell 检测 → [B] 进程启动适配
  打通端到端执行路径

Phase 2 (2-3d): [C] Prompt 适配 → [D] 命令分类 → [E] 语义适配
  完善模型侧使用体验

Phase 3 (2-3d): [F] 安全分析 → [G] 技能传播
  补全安全和技能集成
```

## §2 进度跟踪

尚未开始实现。

## §3 实施细节

### 3.1 验收标准

| # | 验收项 |
|:-:|--------|
| 1 | `BashTool.call({"command":"...", "shell":"powershell"})` 调用 pwsh 执行 |
| 2 | `shell:"auto"` 在 win32 上自动选择 PowerShell |
| 3 | PowerShell 纯 cmdlet pipeline 正确分类为 search/read |
| 4 | `Select-String` RC=1 正确解释为"无匹配" |
| 5 | `Remove-Item -Recurse -Force` 标记为 destructive |
| 6 | 技能 frontmatter `shell: powershell` 实际生效 |
| 7 | hooks + BashTool 共用 shell_resolver.py |

### 3.2 不纳入范围

- cmd.exe 支持
- PowerShell 7 vs Windows PowerShell 5.1 差异
- 特有的 `-Encoding`/`-ErrorAction` 自动适配
- PowerShell 工作流（PSWorkflow）/ DSC

### 3.3 依赖与协同

- F-48: P107-H 的 `shell_resolver.py` 落在 `clawcodex_ext/utils/`
- F-43: `/shell` 运行时命令可选依赖
- 现有 `clawcodex_ext/hooks/shell_invocation.py` 代码源

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
