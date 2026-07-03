import type { ReactElement, ReactNode } from "react";
import type { ChapterStepProps } from "../../registry/types";
import { narrations } from "./narrations";
import "./SopCompiler.css";

const TOTAL = narrations.length;

const WORKFLOW_LINES = [
  "name: review-fix-loop",
  "roles:",
  "  - planner",
  "  - implementer",
  "  - verifier",
  "flow:",
  "  issue → plan → code → verify → pr",
];

const OUTPUTS = [
  { glyph: "A", title: "AGENT", desc: "每个角色一个定义" },
  { glyph: "/", title: "SKILL", desc: "一个入口命令" },
  { glyph: "◇", title: "GRAPH", desc: "一张编排图" },
  { glyph: "⇄", title: "MSG", desc: "通信机制" },
];

const MODULES = ["sdk_parser", "skill_grouper", "agent_builder"];

function CornerMark(): ReactElement {
  return (
    <div className="sop-corner">
      <span className="ord">03</span>
      <span className="sep">/</span>
      <span>04</span>
      <span className="sep">·</span>
      <span>SOP COMPILER</span>
    </div>
  );
}

function StepMark({ step, total }: { step: number; total: number }): ReactElement {
  return (
    <div className="sop-stepmark">
      <div className="num">
        <span>{String(step + 1).padStart(2, "0")}</span>
        <span className="slash">/</span>
        <span className="total">{String(total).padStart(2, "0")}</span>
      </div>
      <div className="label">STEP</div>
    </div>
  );
}

function ShellLine({ children, delay = 0 }: { children: ReactNode; delay?: number }): ReactElement {
  return (
    <div className="line" style={{ animationDelay: `${delay}ms` }}>
      {children}
    </div>
  );
}

function renderStep(step: number): ReactElement {
  switch (step) {
    case 0:
      return (
        <div className="sop-step0 scene-pad">
          <div className="kicker">
            <span className="line" />
            <span>第二个看家本领</span>
          </div>
          <h1 className="title">SOP Compiler<span className="accent">.</span></h1>
          <div className="sub">把流程规范 · 编译成多 agent 团队</div>
          <div className="meta">
            <span>workflow.md</span>
            <span className="sq" />
            <span>multi-agent</span>
            <span className="sq" />
            <span>recoverable</span>
          </div>
        </div>
      );

    case 1:
      return (
        <div className="sop-step1 scene-pad">
          <h2 className="heading">你写个 <span className="accent">workflow.md</span>,描述流程</h2>
          <div className="workflow-card">
            <div className="filebar">
              <span className="dot" />
              <span>workflow.md</span>
              <span className="tag">PROCEDURE</span>
            </div>
            <div className="code">
              {WORKFLOW_LINES.map((line, idx) => (
                <ShellLine key={line} delay={idx * 80}>
                  <span className="ln">{String(idx + 1).padStart(2, "0")}</span>
                  <span className={line.includes("→") ? "flow accent" : "body"}>{line}</span>
                </ShellLine>
              ))}
            </div>
          </div>
        </div>
      );

    case 2:
      return (
        <div className="sop-step2 scene-pad">
          <h2 className="heading">它编译成一组<span className="accent">多 agent 团队</span></h2>
          <div className="compile-flow">
            <div className="source box">
              <div className="glyph">MD</div>
              <div className="label">workflow.md</div>
            </div>
            <div className="compiler">
              <div className="ring" />
              <div className="core">compile</div>
              <div className="modules">
                {MODULES.map((module) => <span key={module}>{module}</span>)}
              </div>
            </div>
            <div className="team box">
              <div className="glyph">TEAM</div>
              <div className="label">agents</div>
            </div>
          </div>
        </div>
      );

    case 3:
      return (
        <div className="sop-step3 scene-pad">
          <h2 className="heading">编译结果是<span className="accent">四件套</span></h2>
          <div className="outputs">
            {OUTPUTS.map((item, idx) => (
              <div className="output-card" key={item.title} style={{ animationDelay: `${idx * 120}ms` }}>
                <div className="glyph">{item.glyph}</div>
                <div className="title">{item.title}</div>
                <div className="desc">{item.desc}</div>
              </div>
            ))}
          </div>
        </div>
      );

    case 4:
      return (
        <div className="sop-step4 scene-pad">
          <h2 className="heading">agent 间 <span className="accent">SendMessage</span> 互相通信</h2>
          <div className="comm-map">
            <div className="agent a1"><span>P</span><small>planner</small></div>
            <div className="agent a2"><span>I</span><small>implementer</small></div>
            <div className="agent a3"><span>V</span><small>verifier</small></div>
            <div className="agent a4"><span>R</span><small>reviewer</small></div>
            <svg viewBox="0 0 1100 540" preserveAspectRatio="none">
              <path d="M 550 80 L 970 270 L 550 460 L 130 270 Z" className="route" />
              <path d="M 550 80 L 550 460 M 130 270 L 970 270" className="route ghost" />
              <text x="610" y="172" className="msg">SendMessage</text>
              <text x="660" y="380" className="msg">task-notification</text>
            </svg>
          </div>
        </div>
      );

    case 5:
      return (
        <div className="sop-step5 scene-pad">
          <div className="recover">
            <div className="status before">CRASH</div>
            <div className="pulse-line" />
            <div className="status after">RESUME</div>
          </div>
          <h2 className="heading">崩了能<span className="accent">恢复</span></h2>
          <div className="sub">为什么 · 怎么保障</div>
          <div className="recover-mechanisms">
            <div className="recover-mech" style={{ animationDelay: "0ms" }}>
              <div className="glyph">// 01 · JOURNAL</div>
              <div className="title">消息落盘</div>
              <div className="desc">每条 <span className="accent">SendMessage</span> 写入 NDJSON,事件可按时间线完整重放</div>
            </div>
            <div className="recover-mech" style={{ animationDelay: "120ms" }}>
              <div className="glyph">// 02 · CHECKPOINT</div>
              <div className="title">状态快照</div>
              <div className="desc">关键步骤固化 <span className="accent">checkpoint</span>,断点处的上下文/角色/进度一并落盘</div>
            </div>
            <div className="recover-mech" style={{ animationDelay: "240ms" }}>
              <div className="glyph">// 03 · CONTINUE</div>
              <div className="title">断点续跑</div>
              <div className="desc">崩溃后从最近 checkpoint <span className="accent">continue</span>,已完成步骤不回退、不重算</div>
            </div>
          </div>
        </div>
      );

    case 6:
      return (
        <div className="sop-step6 scene-pad">
          <div className="kicker">// ONE COMMAND</div>
          <h2 className="heading">一行命令<span className="accent">:</span></h2>
        </div>
      );

    default:
      return (
        <div className="sop-step7 scene-pad">
          <div className="terminal">
            <div className="bar">
              <span className="dot" />
              <span>SOP CONVERT</span>
              <span className="ok">READY</span>
            </div>
            <ShellLine>
              <span className="prompt">$</span>
              <span className="cmd">clawcodex-dev sop convert <span className="file">your_workflow.md</span> <span className="flag">--out</span> ./.clawcodex</span>
            </ShellLine>
            <ShellLine delay={180}>
              <span className="prompt">›</span>
              <span className="out">parse workflow.md · 3 roles found</span>
            </ShellLine>
            <ShellLine delay={320}>
              <span className="prompt">›</span>
              <span className="out">build agents · generate skill · write graph</span>
            </ShellLine>
            <ShellLine delay={460}>
              <span className="prompt ok">✓</span>
              <span className="out ok">team compiled · ./.clawcodex ready</span>
            </ShellLine>
            <span className="cursor" />
          </div>
        </div>
      );
  }
}

export default function SopCompilerChapter({ step }: ChapterStepProps): ReactElement {
  return (
    <div className="sop-scene">
      <CornerMark />
      <StepMark step={step} total={TOTAL} />
      {renderStep(step)}
    </div>
  );
}
