# ClawCodex Demo Factory

把一个已经实现的 ClawCodex 功能录制成真实、清晰、可复现的终端 Demo。VHS 只是录制工具，成片必须
展示 ClawCodex 自己的功能和页面。

本文可直接交给 ClawCodex 执行。ClawCodex 应自主选择场景、录制、查看成片、修正问题并交付，不要求
用户参与中间调试。

## 使用

在仓库根启动 ClawCodex：

```bash
.venv/bin/clawcodex-dev --permission-mode bypassPermissions
```

在原生启动页下方输入：

```text
遵循 docs/guide.raw/demo-factory.md，为 ClawCodex 功能 <FEATURE> 制作并验收一个真实终端 Demo。
```

这表示：

- `surface policy: internal-first`
- `provider policy: inherit-current`
- 授权生产者及其启动的 ClawCodex 按任务需要使用当前 provider/model 完成正常模型调用。
- 只可发送完成任务必要的功能请求、本文、最小源码或测试片段、中性 fixture、关键帧及正常 runtime
  context；不得发送凭据、无关仓库源码或个人文件。

用户明确指定其他 provider/model、禁止 provider 或要求外部命令页面时，以用户本次请求为准。

## 产品契约

1. **默认展示 ClawCodex 内部页面。** 保留原生 banner，在 `❯` 下执行 slash command、自然语言任务或
   按键，并展示内部工具调用、模型输出、TUI 或菜单。只有用户明确要求外部命令页面时，才录制 shell、
   headless 或具体 CLI 子命令页面。
2. **继承当前 provider/model。** 从当前 runtime 或 banner 取得身份，不反问用户，不复制或伪造认证
   配置。功能需要模型时必须真实调用 provider；纯本地功能不制造无关调用。
3. **展示核心价值。** 当用户只给出功能名时，自主选择能体现其独有价值的最小成功流程。除非用户要求
   只读能力，否则 `status`、`list`、`help`、空状态或版本信息不能单独构成 Demo。
4. **只录真实行为。** 不模拟 REPL，不打印合成输出，不直接调用内部 handler，不预写数据库伪造状态。
   用户可见的动作必须真实发生在录制中。
5. **隔离且不污染。** 使用新的 `.scratch/demos/<slug>-<run-id>/` 及其中的中性 workspace；保留用户
   现有 Git 修改，不改产品代码，不覆盖认证目录。
6. **功能和画面都要通过。** GIF 好看但功能没发生，或功能正确但录成外部命令页面，都不算完成。

通用 `cli-demo-generator` 的 shell-first 示例不能覆盖这里的 internal-first 默认规则。

## 自主流程

1. 加载并使用 `cli-demo-generator`，由它负责 VHS、时序、抽帧和媒体检查。
2. 定向查看必要源码与测试，确定本片只证明一个用户可见能力，以及一个独立功能 oracle。
3. 在唯一 job 目录内录制真实入口。内部 REPL 的基线入口是
   `.venv/bin/clawcodex-dev --legacy-repl --permission-mode bypassPermissions`；可在启动前清理旧 shell，
   但启动页出现后不清屏，在其下方执行任务。正式 target 不继承 producer 的 agent-debug 参数或环境，
   成片不显示 debug marker；PTY 调试证据另存。权限交互本身是功能时才调整 permission mode。
4. 功能需要模型时，确认 target 实际使用继承的 provider/model。需要创建、修改、执行或模型参与的
   流程，不得为了省事缩成只读查询。
5. 同时检查功能证据和实际画面。发现问题就根据证据修正根因，在新的 job 目录重新录制。

不要把 `.venv/bin/clawcodex-dev -p ...`、隐藏脚本或外部 shell 当作内部页面 Demo，除非用户明确要求
这种页面。

## 验收

功能验收：

- transcript 中有成片展示的真实动作和产品反馈。
- 独立 oracle 能证明结果；有文件或状态副作用时直接检查真实结果。
- 模型驱动功能能核对实际 provider/model 和调用记录；纯本地功能允许没有模型调用。

画面验收：

- 实际打开启动页、关键动作和最终结果帧，而不只检查文件存在。
- 内部页面场景能看见 ClawCodex banner、prompt/footer 和内部动作。
- 成片可完整解码，无裁切、乱码、凭据、无关个人路径或明显错误。
- 等待任务真正完成，最终结果稳定显示约 8 秒，不能一闪而过。

遇到真实认证、依赖或产品错误时，保留证据并明确报告 `blocked` 或 `failed`，不能用模拟输出掩盖。

## 交付

返回：

- `demo.gif`
- `demo.tape`
- `demo-report.md`

报告只需记录 verdict、功能、页面类型、实际 provider/model、可见动作、功能 oracle、媒体检查和文件
路径。`passed` 必须意味着功能与画面均已由 ClawCodex 自己验收，用户不需要再次手工补验。
