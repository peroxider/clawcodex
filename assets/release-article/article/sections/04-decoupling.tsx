import { Section, Aside, CodeBlock, Raw } from "reacticle";

// 一节一文件 · Section 04 · 三层解耦架构
//
// Outline plan 锚点:
/*   保留信息:source.md"三层解耦架构"段全段(三个 layer 简述 + 黄金法则 4 条)
     需要的组件:Section 正文 + CodeBlock(目录树) + Aside(黄金法则) + Raw(层间 import 流向)
     Raw 用途:用 SVG 画"src → clawcodex_ext → extensions"层间 import 流向图 */

export function SectionDecoupling() {
  return (
    <Section index="04" title="三层解耦架构 · fork 的长期可维护性根本">
      <p>
        ClawCodex DevMind 是 Claude Code Python 重构版的下游 fork。下游 fork 的天然风险
        是:每向上游合并一次,自己的改动就被冲掉一大片;每加一个新特性,都要在几百个文件里
        抄代码。三层解耦架构(<code>src</code> · <code>clawcodex_ext</code> ·{" "}
        <code>extensions</code>)就是为了把这种风险<span style={{ fontWeight: 600 }}>
        降到最低</span>而设的。
      </p>

      <h3 style={{ marginTop: "var(--ra-space-5, 1.5rem)" }}>每一层的角色</h3>
      <p>
        <strong>Layer 0 · src/</strong> —— 上游源码。Claude Code Python 重构版的全部模块
        几乎原封不动在这里,包括代理循环、provider、tool system、session、config、CLI、
        REPL 等。这一层我们<span style={{ fontWeight: 600 }}>几乎不动</span>;改动只接受
        上游合并或必要的最小兼容性 patch。
      </p>
      <p>
        <strong>Layer 1 · clawcodex_ext/</strong> —— 下游补丁层。镜像 src/ 的目录结构,
        通过 <code>from src.xxx import yyy</code> 引用上游模块,在其基础上做包装、扩展或
        替换。这一层优先用猴补丁、注册中心、钩子、依赖注入来覆盖上游行为,而不是直接改
        src/。
      </p>
      <p>
        <strong>Layer 2 · extensions/</strong> —— 三方扩展层。承载全新子系统
        (orchestrator · sop_converter · providers_ext · visualizer · ...)。可以同时引用
        src/ 与 clawcodex_ext/,但<span style={{ fontWeight: 600 }}>不直接依赖具体实现</span>
        —— 跨层契约通过 <code>extensions/capabilities/</code> 里的 Protocol 声明。
      </p>

      <h3 style={{ marginTop: "var(--ra-space-5, 1.5rem)" }}>目录骨架</h3>
      <CodeBlock
        language="text"
        title="三层目录结构(Layer 0 + Layer 1 + Layer 2)"
        code={`src/                 # Layer 0 — Upstream Claude Code
  agent/  auth/  bootstrap/  bridge/  command_system/
  components/  config.py  constants/  context_system/
  coordinator/  entrypoints/  history.py  hooks/
  init.py  keybindings/  memdir/  outputStyles/
  permissions/  plugins/  providers/  query/  services/
  settings/  skills/  tasks/  tool_system/  utils/

clawcodex_ext/       # Layer 1 — Downstream Patches
  agent/  auth/  cli/  command_system/  context_system/
  hooks/  permissions/  providers/  query/  services/
  tool_system/  types/

extensions/          # Layer 2 — Extensions
  orchestrator/      # 编排器:agent_runner · git_sync · report_writer · tracker
  capabilities/      # Protocol 接口定义(层间契约,无实现)
  remote_api/        # 远程 API 服务
  ports/             # 桥接端口:bridge_main · transports
  sop_converter/     # SOP 编译器
  providers_ext/     # 三方 LLM 提供者(LiteLLM)
  visualizer/        # 可视化仪表盘`}
      />

      <Aside tone="principle" label="四条黄金法则">
        <ol style={{ margin: 0, paddingLeft: "var(--ra-space-5, 1.5rem)" }}>
          <li>
            尽量避免在 src/ 下新增模块或修改函数体做功能扩展 —— 优先考虑 clawcodex_ext/
            或 extensions/
          </li>
          <li>
            Layer 1(clawcodex_ext)可导入 src.;Layer 2(extensions)可导入 src. 与
            clawcodex_ext.
          </li>
          <li>
            Layer 2 的新模块优先依赖 extensions/capabilities/ 里的 Protocol,不要直接依赖
            具体实现
          </li>
          <li>
            扩展上游行为优先用注册 / 钩子 / DI,其次才是猴补丁;直接复制 / 修改 src/ 是最后
            手段
          </li>
        </ol>
      </Aside>

      {/* 层间 import 流向图 */}
      <Raw title="层间 import 流向:Layer 2 → Layer 1 → Layer 0">
        <svg
          viewBox="0 0 1100 380"
          preserveAspectRatio="xMidYMid meet"
          aria-label="三层架构 import 流向图"
          style={{
            display: "block",
            width: "100%",
            height: "auto",
            marginTop: "var(--ra-space-4, 1rem)",
            color: "var(--ra-color-fg, inherit)",
          }}
        >
          {/* Layer 0 (底) */}
          <g>
            <rect
              x="100"
              y="260"
              width="900"
              height="80"
              fill="var(--ra-color-accent, currentColor)"
              opacity="0.10"
            />
            <rect
              x="100"
              y="260"
              width="900"
              height="80"
              fill="none"
              stroke="var(--ra-color-border, currentColor)"
              strokeWidth="1.2"
            />
            <text
              x="550"
              y="295"
              textAnchor="middle"
              fill="var(--ra-color-fg, currentColor)"
              fontSize="20"
              fontFamily="var(--ra-font-mono, monospace)"
              fontWeight="600"
            >
              LAYER 0
            </text>
            <text
              x="550"
              y="325"
              textAnchor="middle"
              fill="var(--ra-color-muted, currentColor)"
              fontSize="14"
              fontFamily="var(--ra-font-mono, monospace)"
            >
              src/  ·  Upstream Claude Code  ·  尽量不动
            </text>
          </g>

          {/* Layer 1 (中) */}
          <g>
            <rect
              x="200"
              y="150"
              width="700"
              height="80"
              fill="var(--ra-color-accent, currentColor)"
              opacity="0.18"
            />
            <rect
              x="200"
              y="150"
              width="700"
              height="80"
              fill="none"
              stroke="var(--ra-color-border, currentColor)"
              strokeWidth="1.2"
            />
            <text
              x="550"
              y="185"
              textAnchor="middle"
              fill="var(--ra-color-fg, currentColor)"
              fontSize="20"
              fontFamily="var(--ra-font-mono, monospace)"
              fontWeight="600"
            >
              LAYER 1
            </text>
            <text
              x="550"
              y="215"
              textAnchor="middle"
              fill="var(--ra-color-muted, currentColor)"
              fontSize="14"
              fontFamily="var(--ra-font-mono, monospace)"
            >
              clawcodex_ext/  ·  Downstream Patches  ·  from src.xxx import yyy
            </text>
          </g>

          {/* Layer 2 (顶) */}
          <g>
            <rect
              x="300"
              y="40"
              width="500"
              height="80"
              fill="var(--ra-color-accent, currentColor)"
              opacity="0.28"
            />
            <rect
              x="300"
              y="40"
              width="500"
              height="80"
              fill="none"
              stroke="var(--ra-color-accent, currentColor)"
              strokeWidth="1.6"
            />
            <text
              x="550"
              y="75"
              textAnchor="middle"
              fill="var(--ra-color-fg, currentColor)"
              fontSize="20"
              fontFamily="var(--ra-font-mono, monospace)"
              fontWeight="700"
            >
              LAYER 2
            </text>
            <text
              x="550"
              y="105"
              textAnchor="middle"
              fill="var(--ra-color-muted, currentColor)"
              fontSize="14"
              fontFamily="var(--ra-font-mono, monospace)"
            >
              extensions/  ·  Orchestrator · SOP · Remote API · Visualizer
            </text>
          </g>

          {/* 双向箭头:L2 ↔ L1 ↔ L0 */}
          <g
            stroke="var(--ra-color-accent, currentColor)"
            strokeWidth="1.4"
            fill="none"
          >
            {/* L2 → L1 */}
            <line x1="450" y1="122" x2="450" y2="148" />
            <polyline points="450,148 444,138 456,138" />
            {/* L1 → L0 */}
            <line x1="450" y1="232" x2="450" y2="258" />
            <polyline points="450,258 444,248 456,248" />
          </g>
          <g
            stroke="var(--ra-color-muted, currentColor)"
            strokeWidth="1.2"
            fill="none"
            opacity="0.7"
          >
            {/* L0 → L1 (依赖方向反向) */}
            <line x1="660" y1="258" x2="660" y2="232" />
            <polyline points="660,232 654,242 666,242" />
            {/* L1 → L2 */}
            <line x1="660" y1="148" x2="660" y2="122" />
            <polyline points="660,122 654,132 666,132" />
          </g>

          {/* 流向标签 */}
          <text
            x="480"
            y="140"
            fill="var(--ra-color-accent, currentColor)"
            fontSize="12"
            fontFamily="var(--ra-font-mono, monospace)"
            letterSpacing="0.12em"
          >
            扩展 import
          </text>
          <text
            x="690"
            y="140"
            fill="var(--ra-color-muted, currentColor)"
            fontSize="12"
            fontFamily="var(--ra-font-mono, monospace)"
            letterSpacing="0.12em"
          >
            协议定义
          </text>
          <text
            x="480"
            y="250"
            fill="var(--ra-color-accent, currentColor)"
            fontSize="12"
            fontFamily="var(--ra-font-mono, monospace)"
            letterSpacing="0.12em"
          >
            扩展 import
          </text>
          <text
            x="690"
            y="250"
            fill="var(--ra-color-muted, currentColor)"
            fontSize="12"
            fontFamily="var(--ra-font-mono, monospace)"
            letterSpacing="0.12em"
          >
            上游依赖
          </text>
        </svg>
      </Raw>
    </Section>
  );
}