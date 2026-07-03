import { Section, Aside, CodeBlock, Raw } from "reacticle";

// 一节一文件 · Section 02 · SOP 编译器
//
// Outline plan 锚点:
/*   保留信息:source.md"SOP 编译器"段全段(4 模块名 / 输出三件套 / 协同方式 / 示例命令)
     需要的组件:Section 正文 + CodeBlock(sop convert 命令)+ Aside(模块名列表)
     Raw 用途:用 SVG 画"workflow.md → sdk_parser → skill_grouper →
              agent_builder → {agent 定义 · 入口 skill · 编排图}"数据流 */

export function SectionSopCompiler() {
  return (
    <Section index="02" title="SOP 编译器 · workflow.md → 多 agent 团队">
      <p>
        编排器解决了"谁来跑"的问题,但大型工程任务不是单个 agent 能吞下的。
        ClawCodex DevMind 的第二块差异化能力 —— <strong>SOP 编译器</strong>
         —— 解决的是"如何把一个流程规范编译成一组可协同的 agent"。
      </p>

      <p>
        流程规范写在 <code>workflow.md</code> 里:每个角色干谁、读什么工具、调什么
        skill、按什么顺序交接。SOP 编译器读这份文档,把它编译成一套
        <span style={{ fontWeight: 600 }}>agent 定义 + 入口 skill + 编排图</span>
        ,三件套可以读可以执行可以观测。换句话说,把工程 SOP
        当成 source code,把多 agent 团队当成 compiled artifact。
      </p>

      <h3 style={{ marginTop: "var(--ra-space-5, 1.5rem)" }}>四个核心模块</h3>
      <Aside tone="principle" label="编译流水线">
        <p style={{ margin: 0 }}>
          <code>sdk_parser.py</code> 解析 workflow.md ·{" "}
          <code>skill_grouper.py</code> 把工具与 skill 按角色聚类 ·{" "}
          <code>agent_builder.py</code> 构造 agent 定义 ·{" "}
          <code>templates.py</code> 持有 Jinja 模板链。
          四个模块的依赖单向,易于单测与替换。
        </p>
      </Aside>

      <h3 style={{ marginTop: "var(--ra-space-5, 1.5rem)" }}>编译输出三件套</h3>
      <ol style={{ paddingLeft: "var(--ra-space-5, 1.5rem)" }}>
        <li>
          <strong>agent 定义</strong> —— 每个角色一份 YAML/JSON,记录模型偏好、可用
          tool、可用 skill、与谁握手
        </li>
        <li>
          <strong>入口 skill</strong> —— 每个角色一个 SKILL.md,作为 agent
          启动时拉起的上下文(与上游 Claude Code skill 协议一致)
        </li>
        <li>
          <strong>编排图</strong> —— 一张可读、可执行、可观测的图,标注任务交接顺序与
          失败转移路径
        </li>
      </ol>

      <h3 style={{ marginTop: "var(--ra-space-5, 1.5rem)" }}>协同方式</h3>
      <p>
        Worker 之间的消息流是 task-notification XML,而不是松散的 JSON 字段 —— 这种约束让
        编排图可以静态分析,也让 mock 与回放成为可能。Coordinator 工具集保持轻量:
        只读三件套(Read / WebSearch / WebFetch)+ 通信三件套(Agent / SendMessage /
        TaskStop),避免在 SOP 编译产物里引入"全能工具"反而让多 agent 协同变得不可预测。
      </p>

      <h3 style={{ marginTop: "var(--ra-space-5, 1.5rem)" }}>示例命令</h3>
      <CodeBlock
        language="bash"
        title="把一份订单处理 SOP 编译成可运行的多 agent 团队"
        code={`clawcodex-dev sop convert examples/sop/order_processing.md --out ./.clawcodex

# 产物:
#   .clawcodex/agents/        # 4 个角色的 agent 定义
#   .clawcodex/skills/        # 4 个 SKILL.md 入口
#   .clawcodex/orchestration.json  # 编排图`}
      />

      {/* 数据流图:workflow.md → 四个模块 → 三件套产物 */}
      <Raw title="数据流:从 SOP 文档到多 agent 团队">
        <svg
          viewBox="0 0 1100 360"
          preserveAspectRatio="xMidYMid meet"
          aria-label="SOP 编译器数据流图:workflow.md → 四个核心模块 → 三件套产物"
          style={{
            display: "block",
            width: "100%",
            height: "auto",
            marginTop: "var(--ra-space-4, 1rem)",
            color: "var(--ra-color-fg, inherit)",
          }}
        >
          {/* 输入源 */}
          <g>
            <rect
              x="20"
              y="160"
              width="160"
              height="60"
              fill="var(--ra-color-surface, transparent)"
              stroke="var(--ra-color-border, currentColor)"
              strokeWidth="1.2"
            />
            <text
              x="100"
              y="195"
              textAnchor="middle"
              fill="var(--ra-color-fg, currentColor)"
              fontSize="16"
              fontFamily="var(--ra-font-mono, monospace)"
              fontWeight="600"
            >
              workflow.md
            </text>
          </g>

          {/* 四个模块(竖直堆叠) */}
          {(() => {
            const mods = [
              "sdk_parser.py",
              "skill_grouper.py",
              "agent_builder.py",
              "templates.py",
            ];
            return mods.map((m, i) => (
              <g key={m}>
                <rect
                  x="280"
                  y={40 + i * 70}
                  width="240"
                  height="48"
                  fill="var(--ra-color-accent, currentColor)"
                  opacity="0.10"
                />
                <rect
                  x="280"
                  y={40 + i * 70}
                  width="240"
                  height="48"
                  fill="none"
                  stroke="var(--ra-color-border, currentColor)"
                  strokeWidth="1"
                />
                <text
                  x="400"
                  y={70 + i * 70}
                  textAnchor="middle"
                  fill="var(--ra-color-fg, currentColor)"
                  fontSize="14"
                  fontFamily="var(--ra-font-mono, monospace)"
                >
                  {m}
                </text>
                {/* 输入箭头:从 workflow.md 到第一个模块 */}
                {i === 0 && (
                  <line
                    x1="180"
                    y1="190"
                    x2="278"
                    y2="190"
                    stroke="var(--ra-color-border, currentColor)"
                    strokeWidth="1"
                    opacity="0.7"
                  />
                )}
                {/* 模块间依赖箭头(向下) */}
                {i < mods.length - 1 && (
                  <line
                    x1="400"
                    y1={88 + i * 70}
                    x2="400"
                    y2={110 + i * 70}
                    stroke="var(--ra-color-border, currentColor)"
                    strokeWidth="1"
                    opacity="0.6"
                  />
                )}
              </g>
            ));
          })()}

          {/* 三件套产物(右侧并列) */}
          {(() => {
            const out = [
              "agent 定义 ×N",
              "入口 skill ×N",
              "编排图",
            ];
            return out.map((o, i) => (
              <g key={o}>
                <rect
                  x="680"
                  y={80 + i * 80}
                  width="380"
                  height="56"
                  fill="var(--ra-color-accent, currentColor)"
                  opacity={0.18 + i * 0.06}
                />
                <rect
                  x="680"
                  y={80 + i * 80}
                  width="380"
                  height="56"
                  fill="none"
                  stroke="var(--ra-color-accent, currentColor)"
                  strokeWidth="1.2"
                />
                <text
                  x="870"
                  y={115 + i * 80}
                  textAnchor="middle"
                  fill="var(--ra-color-fg, currentColor)"
                  fontSize="16"
                  fontFamily="var(--ra-font-mono, monospace)"
                  fontWeight="600"
                >
                  {o}
                </text>
                {/* 从模块簇到产物的扇形箭头 */}
                <line
                  x1="520"
                  y1="190"
                  x2="678"
                  y2={108 + i * 80}
                  stroke="var(--ra-color-border, currentColor)"
                  strokeWidth="1"
                  opacity="0.55"
                />
              </g>
            ));
          })()}
        </svg>
      </Raw>
    </Section>
  );
}