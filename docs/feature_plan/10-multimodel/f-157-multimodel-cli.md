# F-157: 多模型并行调度 — CLI 命令与配置

## 1. CLI 命令

### 1.1 模型组管理

```bash
# 创建模型组
clawcodex-dev multimodel group create my-ensemble \
  --slot sonnet:claude-sonnet-4-6@anthropic \
  --slot gpt4o:gpt-4o@openai \
  --slot deepseek:deepseek-v4-flash@deepseek \
  --strategy parallel \
  --aggregator passthrough

# 创建投票集成组
clawcodex-dev multimodel group create code-review \
  --slot sonnet:claude-sonnet-4-6@anthropic,weight=2 \
  --slot gpt4o:gpt-4o@openai \
  --slot deepseek:deepseek-v4-flash@deepseek \
  --strategy voting \
  --aggregator majority \
  --min-votes 2

# 创建故障转移组
clawcodex-dev multimodel group create high-availability \
  --slot primary:claude-sonnet-4-6@anthropic \
  --slot fallback1:gpt-4o@openai \
  --slot fallback2:deepseek-v4-flash@deepseek \
  --strategy fallback

# 列出所有模型组
clawcodex-dev multimodel group list

# 查看模型组详情
clawcodex-dev multimodel group show my-ensemble

# 删除模型组
clawcodex-dev multimodel group delete my-ensemble

# 更新模型组
clawcodex-dev multimodel group update code-review \
  --add-slot gemini:gemini-2.5-pro@google \
  --remove-slot deepseek
```

### 1.2 运行时切换

```bash
# 启用多模型模式
clawcodex-dev multimodel use my-ensemble

# 停用多模型模式，回到单模型
clawcodex-dev multimodel off

# 查看当前多模型状态
clawcodex-dev multimodel status
```

### 1.3 预设配置模板

```bash
# 快速对比模板（3 个主流模型对比）
clawcodex-dev multimodel preset quick-compare

# 高可靠性模板（投票集成）
clawcodex-dev multimodel preset high-reliability

# 预算友好模板（优先用便宜的，失败后 fallback）
clawcodex-dev multimodel preset budget-safe
```

## 2. REPL 运行时命令

### 2.1 `/multimodel` 命令

```
> /multimodel
  当前: 未启用
  可用模型组: my-ensemble, code-review, high-availability
  输入 /multimodel use <name> 启用

> /multimodel use my-ensemble
  ✓ 已切换到多模型组 my-ensemble
  策略: parallel | 模型: sonnet, gpt4o, deepseek

> /multimodel status
  ┌─────────────────────────────────────────────────────────┐
  │  状态: 已启用                                            │
  │  组:   my-ensemble                                       │
  │  策略: parallel                                          │
  │  模型:                                                   │
  │    • sonnet-4-6       (anthropic)   权重: 1.0           │
  │    • gpt-4o           (openai)      权重: 1.0           │
  │    • deepseek-v4-flash (deepseek)   权重: 1.0           │
  └─────────────────────────────────────────────────────────┘

> /multimodel off
  ✓ 已切换回单模型模式 (claude-sonnet-4-6)
```

### 2.2 持久化配置

```yaml
# ~/.clawcodex/config.yaml
multimodel:
  default_group: ""          # 默认模型组名，空字符串表示不启用
  groups:
    my-ensemble:
      strategy: parallel
      aggregator: passthrough
      max_concurrent: 5
      slots:
        - name: sonnet
          provider: anthropic
          model: claude-sonnet-4-6
          weight: 1.0
          timeout_ms: 120000
        - name: gpt4o
          provider: openai
          model: gpt-4o
          weight: 1.0
          timeout_ms: 120000
        - name: deepseek
          provider: deepseek
          model: deepseek-v4-flash
          weight: 1.0
          timeout_ms: 120000
```

## 3. 配置加载优先级

1. 命令行参数 `--multimodel my-ensemble` 最高
2. REPL 运行时 `/multimodel use <name>` 次之
3. 配置文件 `config.yaml` 的 `multimodel.default_group` 最低

## 4. 实现文件

```
extensions/multimodel/
  cli.py                   # clawcodex-dev multimodel 子命令
  runtime_command.py       # /multimodel slash 命令
  config.py                # 配置加载与验证
  preset.py                # 预设模板定义
```