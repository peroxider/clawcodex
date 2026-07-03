import { Section, Aside, CodeBlock, Table } from "reacticle";

// 一节一文件 · Section 05 · 一键安装
//
// Outline plan 锚点:
/*   保留信息:source.md"一键安装"段全段(3 平台表格 + 辅助命令 3 条 + 预置要求 4 条)
     需要的组件:Section 正文 + Table(3 平台)+ CodeBlock(辅助命令)+ 列表(预置要求)+ Aside
     是否需要 Raw:否 */

export function SectionInstall() {
  return (
    <Section index="05" title="一键安装 · 装它只要 1 行">
      <p>
        安装摩擦是 fork 价值的第一个试金石 —— 用户不必读完上面的架构就能验证这个项目。
        按你用的操作系统,从下面挑一行复制粘贴回车即可。
      </p>

      <h3 style={{ marginTop: "var(--ra-space-5, 1.5rem)" }}>三个平台并列</h3>
      <Table
        caption="按操作系统选一行;Windows 用 PowerShell,其它一律 POSIX curl"
        columns={[
          { key: "platform", label: "平台", width: "28%" },
          { key: "command", label: "命令", width: "72%" },
        ]}
        rows={[
          {
            platform: "macOS · Linux · WSL",
            command: (
              <code style={{ fontSize: "0.9em" }}>
                curl -fsSL https://raw.githubusercontent.com/peroxider/clawcodex/main/install.sh | bash
              </code>
            ),
          },
          {
            platform: "Windows · PowerShell",
            command: (
              <code style={{ fontSize: "0.85em", wordBreak: "break-all" }}>
                powershell -NoProfile -ExecutionPolicy Bypass -Command "iwr https://raw.githubusercontent.com/peroxider/clawcodex/main/install.ps1 -UseBasicParsing -OutFile $env:TEMP\cc.ps1; & $env:TEMP\cc.ps1"
              </code>
            ),
          },
          {
            platform: "源码 · Git clone",
            command: (
              <code style={{ fontSize: "0.85em", wordBreak: "break-all" }}>
                git clone https://gitcode.com/chadwweng/clawcodex.git && cd clawcodex && uv venv && uv pip install -e ".[all]"
              </code>
            ),
          },
        ]}
      />

      <h3 style={{ marginTop: "var(--ra-space-5, 1.5rem)" }}>辅助命令</h3>
      <p>
        一行安装之后,常用三件事:
      </p>
      <CodeBlock
        language="bash"
        title="装好以后的三件套:doctor / dry-run / version"
        code={`bash install.sh doctor      # 预检环境(Python 版本、磁盘、Git、网络)
bash install.sh --dry-run  # 模拟安装,不改文件系统
clawcodex-dev --version    # 验证安装版本`}
      />

      <h3 style={{ marginTop: "var(--ra-space-5, 1.5rem)" }}>预置要求</h3>
      <p>
        极简:
      </p>
      <ul style={{ paddingLeft: "var(--ra-space-5, 1.5rem)" }}>
        <li><strong>Python 3.10+</strong>(uv 自动装,不必手动下)</li>
        <li><strong>Git 2.x</strong>(Mac 自带,Linux 发行版自带,Windows 走 Git for Windows)</li>
        <li><strong>500 MB 磁盘</strong>(含 venv 与扩展)</li>
        <li><strong>全用户本地安装,无需 sudo</strong></li>
      </ul>

      <Aside tone="note" label="安装后能立刻做什么">
        <p style={{ margin: 0 }}>
          装好以后,<code>clawcodex-dev</code> 直接可用 —— 跑 REPL、起编排器、用
          LiteLLM 路由任意 LLM,都不必再装额外二进制。orchestrator 子命令
          (<code>server</code> · <code>issue</code> · <code>dashboard</code>)和 sop
          编译器(<code>sop convert</code>)同一可执行文件提供,不必额外 init。
        </p>
      </Aside>
    </Section>
  );
}