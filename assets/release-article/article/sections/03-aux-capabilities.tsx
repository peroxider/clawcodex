import { Section, Subsection, CodeBlock } from "reacticle";

// 一节一文件 · Section 03 · 四个辅助能力
//
// Outline plan 锚点:
/*   保留信息:source.md"四个辅助能力"段全段(PR auto-fix / LiteLLM / Cron+IM / 运行时切模型)
     需要的组件:Section 正文 + 4 个 Subsection(每能力一节)
     是否需要 Raw:否(清单式内容) */

export function SectionAuxCapabilities() {
  return (
    <Section index="03" title="四个辅助能力">
      <p>
        编排器与 SOP 编译器是 ClawCodex DevMind 的两条主轴,但 fork 在主轴之外还长出四块
        实用能力 —— 它们围绕"长期可被多 agent 体系使用"这条原则拼成,而不是把每个能力
        单独堆成新工具。下面逐个说。
      </p>

      <Subsection index="3.1" title="自动化工程闭环 · PR 评审 + 验证门禁">
        <p>
          <strong>PR Review Auto-Fix</strong>:
          reviewer 留下评论、或 CI 跑挂,agent 会自动读反馈、迭代修复、补测试、重跑门禁,
          反复直到过线。整个循环接在编排器主管道之后,不另起进程。
        </p>
        <p>
          <strong>Verification Gate</strong>:
          <code>pre-commit</code> / <code>pre-push</code> / <code>post-sync</code>{" "}
          三道钩子跑 <code>pytest</code>(或用户自配的命令),失败即 block push,
          不让脏 PR 进入评审队列。运行结果以 Markdown + JSON 双格式写入
          <code>.reports/</code>,并自动注入 PR body —— reviewer 不必跳出 GitHub/GitCode
          就能看见每条 case 的状态。
        </p>
      </Subsection>

      <Subsection index="3.2" title="LiteLLM · 100+ LLM 后端">
        <p>
          启动时一行参数切到任何模型后端:
        </p>
        <CodeBlock
          language="bash"
          title="切到 LiteLLM 后端,路由到任意支持的 LLM"
          code={`clawcodex-dev --provider litellm --model gpt-4o

# 也可在 REPL 内即时切:
#   /provider litellm
#   /model claude-3-5-sonnet`}
        />
        <p>
          覆盖范围:Bedrock · Vertex · Azure · OpenAI · Together · Anyscale · 等等。跨
          provider 的内容块差异(image / document)由路由器做格式转换 —— 写 agent 的人
          不必再为"Anthropic 的 image 块 vs OpenAI 的 image_url"写两遍。
        </p>
      </Subsection>

      <Subsection index="3.3" title="分布式 Cron + IM 网关">
        <p>
          <strong>Cron</strong>:文件锁 + 抖动调度防重跑;5 字段标准 cron 表达式,加上
          <code>@daily</code> / <code>@hourly</code> / <code>@reboot</code>{" "}
          别名;任务历史以 NDJSON 落盘,可被 jq / 任何日志聚合工具直接消费。
        </p>
        <p>
          <strong>IM 网关</strong>:统一接 WeChat · 飞书 · Slack · Discord;
          REPL 和 Orchestrator 都能挂上去 —— 这意味着你可以在微信上发出
          <code>/pause AGENTSDK-NN</code> 让编排器停下来,或者在飞书上直接 tail
          agent 的运行日志。
        </p>
      </Subsection>

      <Subsection index="3.4" title="运行时切换模型 · /provider /model">
        <p>
          REPL / TUI 内 <code>/provider litellm</code> ·{" "}
          <code>/model gpt-4o</code> 即时切。ModelRegistry 热替换,会话不中断 —— 这意味着
          你不必为"先用 Claude 试,效果不理想换 GPT-4o 重新跑"付出重启 + 重新加载上下文的
          代价。编排器侧同样支持,在 workflow.md 里按角色声明默认模型,运行期可被 IM
          网关或 CLI 临时覆盖。
        </p>
      </Subsection>
    </Section>
  );
}