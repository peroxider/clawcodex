import { Section, Aside } from "reacticle";

// 一节一文件 · Section 06 · 已知限制 + 项目元信息
//
// Outline plan 锚点:
/*   保留信息:source.md"已知限制"4 条 + "项目元信息" + "v0.1.0 MVP 已交付"6 项
     需要的组件:Section 正文 + 列表(限制 4 条)+ 列表(交付 6 项)+ Aside(gitcode 链接)
     是否需要 Raw:否 */

export function SectionLimitsMeta() {
  return (
    <Section index="06" title="已知限制 + 项目元信息">
      <p>
        这是 v0.1.0 MVP 的诚实声明 —— 哪些能跑、哪些还要补、到哪里去取代码,放在同一个
        段落里集中看,比拆成几页容易复盘。
      </p>

      <h3 style={{ marginTop: "var(--ra-space-5, 1.5rem)" }}>v0.1.0 MVP 已交付</h3>
      <ol style={{ paddingLeft: "var(--ra-space-5, 1.5rem)" }}>
        <li>
          <strong>多 Provider</strong> —— Anthropic、OpenAI、GLM(智谱)三家原生 +
          LiteLLM 路由覆盖 100+ LLM 后端
        </li>
        <li>
          <strong>交互式 REPL</strong> —— prompt-toolkit 集成、Rich 输出、命令历史、
          自动补全、slash 命令(<code>/help</code> · <code>/exit</code> ·{" "}
          <code>/clear</code> · <code>/save</code> · <code>/load</code> ·{" "}
          <code>/multiline</code>)
        </li>
        <li>
          <strong>会话持久化</strong> —— 唯一 session ID、对话历史、save / load / clear
        </li>
        <li>
          <strong>配置系统</strong> —— JSON 存储、API key 混淆、Provider 专属设置、
          session 自动保存
        </li>
        <li>
          <strong>编排器 + SOP 编译器</strong> —— 长跑守护进程、LiveView 仪表盘、PR
          评审自动修复、提交前测试门禁、workflow.md → 多 agent 团队
        </li>
        <li>
          <strong>代码质量与测试</strong> —— 类型注解完整、Provider 抽象基类、数据类
          化设计、统一错误处理;<strong>270+ orchestration tests passing</strong>
        </li>
      </ol>

      <h3 style={{ marginTop: "var(--ra-space-5, 1.5rem)" }}>已知限制</h3>
      <p>
        我们刻意把没有做完整的事先说出来,而不是藏到 changelog 的角落:
      </p>
      <ul style={{ paddingLeft: "var(--ra-space-5, 1.5rem)" }}>
        <li>
          <strong>上下文构建</strong> —— 尚处早期 MVP 形态,项目级深度摘要
          (类似 <code>/init</code> 之后的 CLAUDE.md / AGENTS.md)还要继续做
        </li>
        <li>
          <strong>权限框架</strong> —— 已存在但未全链路打通;tool 级别的 ask / allow /
          deny 流程覆盖度还要补
        </li>
        <li>
          <strong>slash 命令</strong> —— <code>/resume</code> · <code>/compact</code> ·{" "}
          <code>/doctor</code> 尚未实现
        </li>
        <li>
          <strong>流式输出</strong> —— Provider 已暴露 streaming 接口,但当前 CLI 默认仍
          是 turn-based 输出;接入 streaming 是 v0.2 优先级
        </li>
      </ul>

      <h3 style={{ marginTop: "var(--ra-space-5, 1.5rem)" }}>项目元信息</h3>
      <ul style={{ paddingLeft: "var(--ra-space-5, 1.5rem)" }}>
        <li><strong>主仓库</strong>:https://gitcode.com/chadwweng/clawcodex</li>
        <li><strong>GitHub 镜像</strong>:https://github.com/peroxider/clawcodex(仅一键安装脚本)</li>
        <li><strong>License</strong>:MIT</li>
        <li><strong>状态</strong>:活跃开发</li>
        <li><strong>Python</strong>:3.10+ 推荐(3.11)</li>
        <li><strong>开源替代</strong>:Claude Code Python 重构版 + 编排器 + SOP 编译器,代码减 4,530 LOC</li>
      </ul>

      <Aside tone="principle" label="装好以后看这里">
        <p style={{ margin: 0 }}>
          装好以后,起编排器观测面:<code>clawcodex-dev orchestrator dashboard --port 8080</code>{" "}
          —— 浏览器开 8080 看 LiveView,agent 在干啥一目了然。要参与开发,主仓库在{" "}
          <a href="https://gitcode.com/chadwweng/clawcodex" target="_blank" rel="noopener noreferrer">
            gitcode.com/chadwweng/clawcodex
          </a>
          ,issue / PR / CI 都在那里。
        </p>
      </Aside>
    </Section>
  );
}