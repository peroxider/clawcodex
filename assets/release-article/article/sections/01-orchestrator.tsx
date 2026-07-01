import { Section, Aside, CodeBlock, Raw, Table } from "reacticle";

// 一节一文件 · Section 01 · 编排器 · 长跑守护进程
//
// Outline plan 锚点:
/*   保留信息:source.md"编排器"段全段(4 跟踪器 / 6 状态 / 6 杀手级特性 /
                CLI 三类子命令 / 8 行真实日志样本)
     需要的组件:Section 正文 + CodeBlock + Aside + Raw
     Raw 用途:用 SVG 画"issue → workspace → commit → PR → review-loop"
              流水线节奏图(细线 + 节点),印证"全流程无人值守" */

export function SectionOrchestrator() {
  return (
    <Section index="01" title="编排器 · 长跑守护进程">
      <p>
        编排器(Orchestrator)是一个长跑守护进程 —— 它轮询四个 issue 跟踪器,挑出待办,
        给每个 issue 复制一个隔离的 workspace,让 agent 在里面接手写代码,跑测试,
        提交,推送,开 PR。整个链条不需要人坐在旁边,这是它与传统 CI 调度最根本的区别:
        它不只是在某次 push 上挂一条流水线,而是<span style={{ fontWeight: 600 }}>自己决定
        哪些 issue 值得动手、自己决定用什么节奏跑、自己决定 PR 长成什么样</span>。
      </p>

      <p>
        这种"自驱"并不是魔法。CLI 把这条链切成三个子命令面 —— 服务面(启停 + 状态)
        · 任务面(列出 / 跟踪 / 暂停 / 接管 / 重跑 issue) · 观测面(LiveView 仪表盘)
        —— 让运维和工程介入都有抓手。
      </p>

      <h3 style={{ marginTop: "var(--ra-space-5, 1.5rem)" }}>支持的 issue 跟踪器</h3>
      <Table
        caption="编排器通过适配器接入四个 issue 跟踪器,新加一个只需实现 TrackerAdapter 协议"
        columns={[
          { key: "tracker", label: "跟踪器", width: "30%" },
          { key: "host", label: "所在平台 / 协议", width: "70%" },
        ]}
        rows={[
          { tracker: "GitHub", host: "REST v3 + GraphQL v4 · 主流开源仓库" },
          { tracker: "Gitee", host: "REST v5 · 国内镜像" },
          { tracker: "GitCode", host: "REST v1 · 本项目主仓库所在平台" },
          { tracker: "Linear", host: "GraphQL · 现代 SaaS issue 平台" },
        ]}
      />

      <h3 style={{ marginTop: "var(--ra-space-5, 1.5rem)" }}>六个 issue 状态</h3>
      <p>
        从入队到收尾,每个 issue 都走完这条生命周期:<code>pending</code> ·
        <code>running</code> · <code>synced</code> · <code>completed</code> ·
        <code>failed</code> · <code>abandoned</code>。前三个是活跃态,后三个是终态;
        LiveView 仪表盘订阅推送事件,任意状态的切换都在浏览器里即时可见。
      </p>

      <h3 style={{ marginTop: "var(--ra-space-5, 1.5rem)" }}>六个杀手级特性</h3>
      <ol style={{ paddingLeft: "var(--ra-space-5, 1.5rem)" }}>
        <li>
          <strong>LiveView HTTP/SSE 仪表盘</strong> ——
          浏览器直接看 agent 在干啥(<code>:8080</code> 端口),事件流实时推送
        </li>
        <li>
          <strong>Takeover</strong> —— 暂停 agent 启动 REPL 人工接管,完事再切回
          自动模式;不必销毁 issue 上下文
        </li>
        <li>
          <strong>PR 评审自动修复</strong> —— reviewer 评论 + CI 失败自动读反馈、
          迭代修复、加测试、重跑门禁,反复直到过线
        </li>
        <li>
          <strong>提交前测试门禁</strong> —— <code>pre-commit</code> /{" "}
          <code>pre-push</code> 跑 <code>pytest</code>,不过不发 PR
        </li>
        <li>
          <strong>重跑标签机制</strong> —— issue 加 <code>agent:retry</code>{" "}
          标签即自动重跑(关闭旧 PR · 重建 workspace · 重新走流水线)
        </li>
        <li>
          <strong>13 态澄清队列</strong> —— agent 卡住不会干等,3 通道
          (交互 · 文件 · @提及)求解,13 种状态机走完整
        </li>
      </ol>

      <h3 style={{ marginTop: "var(--ra-space-5, 1.5rem)" }}>CLI 入口</h3>
      <CodeBlock
        language="bash"
        title="三类子命令面:server · issue · dashboard"
        code={`# 服务面:启停 + 状态
clawcodex-dev orchestrator server {start,status,stop} --workflow <file>

# 任务面:每个 issue 的生命周期动作
clawcodex-dev orchestrator issue {list,show,tail,stop,pause,resume,takeover,clarify,inject,workspace,retry}

# 观测面:LiveView 仪表盘
clawcodex-dev orchestrator dashboard [--port 8080]`}
      />

      {/* 真实日志样本:用 Aside 框起来,tone=note 让它作为"真实证据"而非断言 */}
      <Aside tone="note" label="一次真实运行的 20 秒">
        <pre
          style={{
            margin: 0,
            fontFamily: "var(--ra-font-mono, monospace)",
            fontSize: "var(--ra-text-xs, 0.78rem)",
            lineHeight: 1.7,
            whiteSpace: "pre-wrap",
            color: "var(--ra-color-fg, inherit)",
          }}
        >
{`14:02:11  ◐ Read src/services/lock.py · 132 lines
14:02:13  ◐ Grep "asyncio.Lock" · 3 hits
14:02:18  ◐ Edit src/services/lock.py · +18 -4
14:02:24  ◐ Bash pytest tests/test_lock.py · 4 passed
14:02:24  ✓ Verification gate OK (pytest -x)
14:02:25  ◐ Git commit -m "fix: per-key lock granularity in flush_batch"
14:02:26  ◐ Git push origin clawcodex/AGENTSDK-NN
14:02:31  ✓ PR opened · auto-review-loop subscribed`}
        </pre>
      </Aside>

      {/* 流水线节奏图:印证"全流程无人值守"。细线 + 节点,1px hairline。 */}
      <Raw title="流水线节奏:从 issue 到 PR 的无人值守循环">
        <svg
          viewBox="0 0 1100 240"
          preserveAspectRatio="xMidYMid meet"
          aria-label="编排器流水线节奏图:issue → workspace → implement → verify → commit → push → PR → review-loop"
          style={{
            display: "block",
            width: "100%",
            height: "auto",
            marginTop: "var(--ra-space-4, 1rem)",
            color: "var(--ra-color-fg, inherit)",
          }}
        >
          {/* baseline hairline */}
          <line
            x1="60"
            y1="160"
            x2="1040"
            y2="160"
            stroke="var(--ra-color-border, currentColor)"
            strokeWidth="1"
            opacity="0.5"
          />

          {/* 节点:8 个,等距分布 */}
          {(() => {
            const nodes = [
              { x: 90, label: "issue", note: "tracked" },
              { x: 220, label: "workspace", note: "isolated copy" },
              { x: 360, label: "implement", note: "agent loop" },
              { x: 500, label: "verify", note: "pre-commit / pytest" },
              { x: 640, label: "commit", note: "single amend" },
              { x: 780, label: "push", note: "fork branch" },
              { x: 920, label: "PR", note: "auto-review subscribed" },
            ];
            return nodes.map((n, i) => (
              <g key={n.label}>
                {/* dot */}
                <circle
                  cx={n.x}
                  cy={160}
                  r="6"
                  fill="var(--ra-color-accent, currentColor)"
                />
                {/* label */}
                <text
                  x={n.x}
                  y={130}
                  textAnchor="middle"
                  fill="var(--ra-color-fg, currentColor)"
                  fontSize="13"
                  fontFamily="var(--ra-font-mono, monospace)"
                  fontWeight="600"
                >
                  {n.label}
                </text>
                {/* note */}
                <text
                  x={n.x}
                  y={190}
                  textAnchor="middle"
                  fill="var(--ra-color-muted, currentColor)"
                  fontSize="10"
                  fontFamily="var(--ra-font-mono, monospace)"
                  letterSpacing="0.1em"
                >
                  {n.note}
                </text>
                {/* connector to next */}
                {i < nodes.length - 1 && (
                  <line
                    x1={n.x + 8}
                    y1={160}
                    x2={nodes[i + 1].x - 8}
                    y2={160}
                    stroke="var(--ra-color-border, currentColor)"
                    strokeWidth="1"
                    opacity="0.6"
                  />
                )}
              </g>
            ));
          })()}

          {/* review-loop 回环(从 PR 折回 implement) */}
          <path
            d="M 920 152 Q 920 60 360 60 Q 350 60 350 152"
            fill="none"
            stroke="var(--ra-color-accent, currentColor)"
            strokeWidth="1.2"
            strokeDasharray="4 6"
            opacity="0.7"
          />
          <text
            x="640"
            y="50"
            textAnchor="middle"
            fill="var(--ra-color-accent, currentColor)"
            fontSize="11"
            fontFamily="var(--ra-font-mono, monospace)"
            letterSpacing="0.18em"
          >
            REVIEW-LOOP  (评论 · CI 失败 → 自动迭代)
          </text>
          <polygon
            points="350,148 354,156 346,156"
            fill="var(--ra-color-accent, currentColor)"
            opacity="0.85"
          />
        </svg>
      </Raw>
    </Section>
  );
}