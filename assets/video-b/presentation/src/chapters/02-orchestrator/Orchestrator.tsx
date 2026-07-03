import type { ChapterStepProps } from "../../registry/types";
import { narrations } from "./narrations";
import "./Orchestrator.css";

/**
 * 02-orchestrator · 编排器核心章
 * ─────────────────────────────────────────
 * 16 步 · ~56s
 *
 *   step 0    章标 + 一句话定性
 *   step 1    4 平台
 *   step 2    流水线 5 节点
 *   step 3    转场
 *   step 4-10 真实 log 7 行(逐行揭示)
 *   step 11   reviewer 评论落地
 *   step 12   同分支 commit
 *   step 13   CI 反馈环
 *   step 14   引导大字
 *   step 15   takeover 终端
 *   step 16   13 态
 */

const TOTAL = narrations.length;

// ─── 真实 log 数据(README L166-173) ───
const LOG_LINES: Array<{
  ts: string;
  marker: "◐" | "✓";
  body: React.ReactNode;
}> = [
  {
    ts: "14:02:11",
    marker: "◐",
    body: (
      <>
        Read <span className="file">src/services/lock.py</span>
        <span className="meta"> · <span className="num">132</span> lines</span>
      </>
    ),
  },
  {
    ts: "14:02:13",
    marker: "◐",
    body: (
      <>
        Grep <span className="file"><span className="em">"asyncio.Lock"</span></span>
        <span className="meta"> · <span className="num">3</span> hits</span>
      </>
    ),
  },
  {
    ts: "14:02:18",
    marker: "◐",
    body: (
      <>
        Edit <span className="file">src/services/lock.py</span>
        <span className="meta"> · <span className="num">+18</span> <span className="num">−4</span></span>
      </>
    ),
  },
  {
    ts: "14:02:24",
    marker: "◐",
    body: (
      <>
        Bash <span className="file">pytest tests/test_lock.py</span>
        <span className="meta"> · <span className="num">4</span> passed</span>
      </>
    ),
  },
  {
    ts: "14:02:24",
    marker: "✓",
    body: (
      <>
        Verification gate <span className="em">OK</span>
        <span className="meta"> (pytest -x)</span>
      </>
    ),
  },
  {
    ts: "14:02:25",
    marker: "◐",
    body: (
      <>
        Git <span className="em">commit</span>
        <span className="meta"> -m <span className="file">"fix: per-key lock granularity in flush_batch"</span></span>
      </>
    ),
  },
  {
    ts: "14:02:31",
    marker: "✓",
    body: (
      <>
        PR <span className="em">opened</span>
        <span className="meta"> · auto-review-loop subscribed</span>
      </>
    ),
  },
];

// ─── 13 态澄清队列(article §1.1) ───
const STATES: Array<{ code: string; desc: string; terminal?: boolean }> = [
  { code: "WAITING_USER", desc: "等用户" },
  { code: "WAITING_FILE", desc: "等文件" },
  { code: "WAITING_MENTION", desc: "等 @ 提及" },
  { code: "DEFERRED", desc: "暂缓" },
  { code: "ESCALATED", desc: "升级" },
  { code: "RESUMED", desc: "恢复" },
  { code: "RETRY", desc: "重试" },
  { code: "TIMEOUT", desc: "超时" },
  { code: "CANCELLED", desc: "取消" },
  { code: "ABANDONED", desc: "弃用" },
  { code: "STALE", desc: "失效" },
  { code: "MERGED", desc: "已合", terminal: true },
  { code: "CLOSED", desc: "关闭", terminal: true },
];

function CornerMark() {
  return (
    <div className="or-corner">
      <span className="ord">02</span>
      <span className="sep">/</span>
      <span>04</span>
      <span className="sep">·</span>
      <span>ORCHESTRATOR</span>
    </div>
  );
}

function StepMark({ step, total }: { step: number; total: number }) {
  return (
    <div className="or-stepmark">
      <div className="num">
        <span>{String(step + 1).padStart(2, "0")}</span>
        <span className="slash">/</span>
        <span className="total">{String(total).padStart(2, "0")}</span>
      </div>
      <div className="label">STEP</div>
    </div>
  );
}

export default function OrchestratorChapter({ step }: ChapterStepProps) {
  // ─── step 0: 章标 ───
  if (step === 0) {
    return (
      <div className="or-scene">
        <CornerMark />
        <StepMark step={step} total={TOTAL} />
        <div className="or-step0 scene-pad">
          <div className="kicker">
            <span className="line" />
            <span>第一个看家本领</span>
          </div>
          <h1 className="title">
            Orchestrator<span className="accent">.</span>
          </h1>
          <div className="sub">长跑守护进程 · issue → PR 流水线</div>
          <div className="meta">
            <span>4 TRACKERS</span>
            <span className="sq" />
            <span>13 STATES</span>
            <span className="sq" />
            <span>0 → 1 PR</span>
          </div>
        </div>
      </div>
    );
  }

  // ─── step 1: 4 平台 ───
  if (step === 1) {
    return (
      <div className="or-scene">
        <CornerMark />
        <StepMark step={step} total={TOTAL} />
        <div className="or-step1 scene-pad">
          <h2 className="heading">
            一条常驻流水线,盯 <span className="accent">4</span> 个 issue 平台
          </h2>
          <div className="platforms">
            <div className="or-platform">
              <div className="glyph">⌥</div>
              <div className="name">GitHub</div>
              <div className="desc">Issue → PR</div>
              <div className="role">PRIMARY</div>
            </div>
            <div className="or-platform">
              <div className="glyph">⊕</div>
              <div className="name">Gitee</div>
              <div className="desc">Issue → PR</div>
              <div className="role">PRIMARY</div>
            </div>
            <div className="or-platform">
              <div className="glyph">◧</div>
              <div className="name">GitCode</div>
              <div className="desc">Issue → PR</div>
              <div className="role">PRIMARY</div>
            </div>
            <div className="or-platform">
              <div className="glyph">≡</div>
              <div className="name">Linear</div>
              <div className="desc">Issue → PR</div>
              <div className="role">PRIMARY</div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ─── step 2: 流水线 ───
  if (step === 2) {
    return (
      <div className="or-scene">
        <CornerMark />
        <StepMark step={step} total={TOTAL} />
        <div className="or-step2 scene-pad">
          <h2 className="heading">哪个 issue 冒头,worktree 拉出来,agent 进场</h2>
          <div className="or-pipeline">
            <div className="or-node">
              <div className="icon">⤵</div>
              <div className="label">ISSUE</div>
            </div>
            <div className="or-arrow">›</div>
            <div className="or-node">
              <div className="icon">◫</div>
              <div className="label">QUEUE</div>
            </div>
            <div className="or-arrow">›</div>
            <div className="or-node">
              <div className="icon">⎇</div>
              <div className="label">WORKTREE</div>
            </div>
            <div className="or-arrow">›</div>
            <div className="or-node">
              <div className="icon">◉</div>
              <div className="label">AGENT</div>
            </div>
            <div className="or-arrow">›</div>
            <div className="or-node">
              <div className="icon">⊕</div>
              <div className="label">PR</div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ─── step 3: 转场 ───
  if (step === 3) {
    return (
      <div className="or-scene">
        <CornerMark />
        <StepMark step={step} total={TOTAL} />
        <div className="or-step3 scene-pad">
          <div className="kicker">// REAL RUN</div>
          <h2 className="heading">
            真实跑起来长这样<span className="accent">——</span>
          </h2>
          <div className="arrow-down" />
        </div>
      </div>
    );
  }

  // ─── step 4-10: 真实 log 逐行揭示 ───
  if (step >= 4 && step <= 10) {
    // step 4 → 第 1 行; step 10 → 第 7 行
    const visibleCount = step - 3;
    return (
      <div className="or-scene">
        <CornerMark />
        <StepMark step={step} total={TOTAL} />
        <div className="or-log or-enter">
          <div className="header">
            <span><span className="dot" />issue tail · gitcode/AGENTSDK-15</span>
            <span>attempts: 2</span>
          </div>
          {LOG_LINES.slice(0, visibleCount).map((line, idx) => (
            <div className="line" key={idx} style={{ animationDelay: `${idx * 60}ms` }}>
              <span className="ts">{line.ts}</span>
              <span className={`marker ${line.marker === "✓" ? "is-ok" : ""}`}>
                {line.marker}
              </span>
              <span className="body">{line.body}</span>
            </div>
          ))}
          {step === 10 && <span className="cursor" />}
        </div>
      </div>
    );
  }

  // ─── step 11: reviewer 评论落地 ───
  if (step === 11) {
    return (
      <div className="or-scene">
        <CornerMark />
        <StepMark step={step} total={TOTAL} />
        <div className="or-step11 scene-pad">
          <div className="kicker">// 4 HOURS LATER</div>
          <h2 className="heading">
            reviewer 评论<span className="accent">落地?</span>
          </h2>
          <div className="pr-card">
            <div className="pr-head">
              <span className="branch">clawcodex/AGENTSDK-15</span>
              <span>·</span>
              <span>PR #15</span>
            </div>
            <div className="pr-title">add retry policy for tracker adapters</div>
            <div className="pr-comments">
              <span className="pulse" />
              <span>+ 3 review comments landed</span>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ─── step 12: 同分支 commit ───
  if (step === 12) {
    return (
      <div className="or-scene">
        <CornerMark />
        <StepMark step={step} total={TOTAL} />
        <div className="or-step12 scene-pad">
          <h2 className="heading">
            它接住,自己改,再 commit,<span className="accent">同分支</span>
          </h2>
          <div className="or-branch">
            <div className="or-branch-line" />
            <div className="or-commit-row">
              <div className="or-commit">
                <div className="dot" />
                <div className="hash">a3f1c20</div>
                <div className="label">INIT</div>
              </div>
              <div className="or-commit">
                <div className="dot" />
                <div className="hash">b8e9d44</div>
                <div className="label">FIX 1</div>
              </div>
              <div className="or-commit">
                <div className="dot" />
                <div className="hash">c42f017</div>
                <div className="label">FIX 2</div>
              </div>
              <div className="or-commit is-fresh">
                <div className="dot" />
                <div className="hash">d91ab73</div>
                <div className="label">+ REVIEW FIX</div>
              </div>
            </div>
            <div className="or-branch-name">
              ⎇ <span className="accent">clawcodex/AGENTSDK-15</span> · same branch
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ─── step 13: CI 反馈环 ───
  if (step === 13) {
    return (
      <div className="or-scene">
        <CornerMark />
        <StepMark step={step} total={TOTAL} />
        <div className="or-step13 scene-pad">
          <h2 className="heading">
            CI 报错?再读再改<span className="accent">再跑</span>
          </h2>
          <div className="or-loop">
            <svg viewBox="0 0 720 480" preserveAspectRatio="none">
              <defs>
                <path
                  id="loopPath"
                  d="M 360 60 L 660 240 L 360 420 L 60 240 Z"
                  fill="none"
                />
              </defs>
              <use
                href="#loopPath"
                stroke="rgba(65, 255, 151, 0.5)"
                strokeWidth="1.5"
                className="path-anim"
              />
              {/* 箭头标记(简单) */}
              <text x="370" y="48" fill="var(--accent)" fontSize="18" fontFamily="JetBrains Mono">›</text>
              <text x="668" y="244" fill="var(--accent)" fontSize="18" fontFamily="JetBrains Mono">›</text>
              <text x="370" y="448" fill="var(--accent)" fontSize="18" fontFamily="JetBrains Mono">›</text>
              <text x="38" y="244" fill="var(--accent)" fontSize="18" fontFamily="JetBrains Mono">›</text>
            </svg>
            <div className="node n1">
              <div className="icon">R</div>
              <div className="label">READ</div>
            </div>
            <div className="node n2">
              <div className="icon">E</div>
              <div className="label">EDIT</div>
            </div>
            <div className="node n3">
              <div className="icon">B</div>
              <div className="label">BASH</div>
            </div>
            <div className="node n4">
              <div className="icon">C</div>
              <div className="label">CI</div>
            </div>
            <div className="node n5">
              <div className="icon">↻</div>
              <div className="label">LOOP</div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ─── step 14: 引导大字 ───
  if (step === 14) {
    return (
      <div className="or-scene">
        <CornerMark />
        <StepMark step={step} total={TOTAL} />
        <div className="or-step14 scene-pad">
          <div className="kicker">// HUMAN-IN-THE-LOOP</div>
          <h2 className="heading">
            你也能<span className="accent">随时</span>插一脚
          </h2>
        </div>
      </div>
    );
  }

  // ─── step 15: takeover 终端 ───
  if (step === 15) {
    return (
      <div className="or-scene">
        <CornerMark />
        <StepMark step={step} total={TOTAL} />
        <div className="or-step15 scene-pad">
          <h3 className="heading">REPL 接管,完事切回</h3>
          <div className="or-terminal">
            <div className="line">
              <span className="prompt">$</span>
              <span className="cmd">
                clawcodex-dev orchestrator issue <span className="flag">takeover</span>
                <span className="flag"> --id </span>gitcode/AGENTSDK-15
              </span>
            </div>
            <div className="out is-ok">
              <span>agent paused · REPL attached · ready for input</span>
            </div>
            <div className="line" style={{ marginTop: 6 }}>
              <span className="prompt">›</span>
              <span className="cmd"># 你来改完,Ctrl-D 退出</span>
            </div>
            <div className="out is-ok">
              <span>agent resumed · pushing your edits · same branch</span>
            </div>
            <span className="cursor" />
          </div>
        </div>
      </div>
    );
  }

  // ─── step 16: 13 态 ───
  return (
    <div className="or-scene">
      <CornerMark />
      <div className="or-step16 scene-pad">
        <h2 className="heading">
          <span className="accent">13</span> 种状态机管全程
        </h2>
        <div className="sub">// CLARIFY QUEUE · NEVER STUCK</div>
        <div className="or-states">
          {STATES.map((s) => (
            <div
              className={`or-state${s.terminal ? " is-terminal" : ""}`}
              key={s.code}
            >
              <div className="code">{s.code}</div>
              <div className="desc">{s.desc}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}