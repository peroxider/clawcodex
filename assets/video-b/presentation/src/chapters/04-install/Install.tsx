import type { ReactElement, ReactNode } from "react";
import type { ChapterStepProps } from "../../registry/types";
import { narrations } from "./narrations";
import "./Install.css";

/**
 * 04-install · 安装 + 完整面貌章(精简版)
 * ─────────────────────────────────────────
 * 5 步 · ~20s
 *
 *   step 0  章标 INSTALL. · "装它只要 1 行"
 *   step 1  4 平台一行命令(并排 2 终端)
 *   step 2  "想改源码:" 大字过渡
 *   step 3  源码 3 步 + version + clawcodex 启动
 *   step 4  outro · GitCode 超链接
 */

const TOTAL = narrations.length;

const CURL_CMD =
  "curl -fsSL https://raw.githubusercontent.com/peroxider/clawcodex/main/install.sh | bash";

const IWR_CMD =
  "iwr https://raw.githubusercontent.com/peroxider/clawcodex/main/install.ps1 -useb | iex";

const GITCODE_URL = "https://gitcode.com/chadwweng/clawcodex";

function CornerMark(): ReactElement {
  return (
    <div className="in-corner">
      <span className="ord">04</span>
      <span className="sep">/</span>
      <span>04</span>
      <span className="sep">·</span>
      <span>INSTALL</span>
    </div>
  );
}

function StepMark({ step, total }: { step: number; total: number }): ReactElement {
  return (
    <div className="in-stepmark">
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

function Terminal({
  title,
  ok,
  children,
}: {
  title: string;
  ok?: string;
  children: ReactNode;
}): ReactElement {
  return (
    <div className="terminal">
      <div className="bar">
        <span className="dot" />
        <span>{title}</span>
        {ok ? <span className="ok">{ok}</span> : null}
      </div>
      {children}
      <span className="cursor" />
    </div>
  );
}

function renderStep(step: number): ReactElement {
  switch (step) {
    case 0:
      return (
        <div className="in-step0 scene-pad">
          <div className="kicker">
            <span className="line" />
            <span>最后一步</span>
          </div>
          <h1 className="title">
            Install<span className="accent">.</span>
          </h1>
          <div className="sub">装它只要 <span className="accent">1 行</span></div>
          <div className="meta">
            <span>4 PLATFORMS</span>
            <span className="sq" />
            <span>ONE COMMAND</span>
            <span className="sq" />
            <span>100+ LLM</span>
          </div>
        </div>
      );

    case 1:
      return (
        <div className="in-step1 scene-pad">
          <div className="platform-tags">
            <span className="tag">Linux</span>
            <span className="tag">WSL</span>
            <span className="tag is-power">PowerShell</span>
          </div>
          <div className="install-ways">
            <div className="install-way">
              <div className="way-mark">
                <span className="way-num">01</span>
                <span className="way-name">Linux / WSL</span>
                <span className="way-sub">POSIX · curl</span>
              </div>
              <Terminal title="INSTALL · SHELL">
                <ShellLine>
                  <span className="prompt">$</span>
                  <span className="cmd">{CURL_CMD}</span>
                </ShellLine>
                <ShellLine delay={200}>
                  <span className="prompt ok">✓</span>
                  <span className="out ok">installed · clawcodex-dev ready</span>
                </ShellLine>
              </Terminal>
            </div>
            <div className="install-way">
              <div className="way-mark is-power">
                <span className="way-num">02</span>
                <span className="way-name">PowerShell</span>
                <span className="way-sub">Windows · iwr</span>
              </div>
              <Terminal title="INSTALL · POWERSHELL">
                <ShellLine>
                  <span className="prompt">PS&gt;</span>
                  <span className="cmd">{IWR_CMD}</span>
                </ShellLine>
                <ShellLine delay={200}>
                  <span className="prompt ok">✓</span>
                  <span className="out ok">installed · clawcodex-dev ready</span>
                </ShellLine>
              </Terminal>
            </div>
          </div>
        </div>
      );

    case 2:
      return (
        <div className="in-step2 scene-pad">
          <div className="source-mark">SOURCE</div>
          <h2 className="hero">
            想改源码<span className="accent">:</span>
          </h2>
          <div className="arrow-down" />
        </div>
      );

    case 3: {
      const lines: Array<{ num: string; cmd: ReactNode; ok?: boolean }> = [
        { num: "01", cmd: "git clone https://gitcode.com/chadwweng/clawcodex" },
        { num: "02", cmd: "uv venv" },
        { num: "03", cmd: 'uv pip install -e ".[all]"' },
        { num: "04", cmd: <>clawcodex <span className="flag">--version</span></> },
        { num: "05", cmd: "clawcodex" },
      ];
      return (
        <div className="in-step3 scene-pad">
          <Terminal title="FROM SOURCE · CLONE · INSTALL · RUN">
            {lines.map((s, idx) => (
              <ShellLine key={s.num} delay={idx * 140}>
                <span className="prompt num">{s.num}</span>
                <span className="prompt">$</span>
                <span className="cmd">{s.cmd}</span>
              </ShellLine>
            ))}
            <ShellLine delay={lines.length * 140 + 80}>
              <span className="prompt ok">✓</span>
              <span className="out ok">editable install · ready to hack</span>
            </ShellLine>
          </Terminal>
        </div>
      );
    }

    default:
      return (
        <div className="in-step4 scene-pad">
          <div className="outro-card">
            <div className="row">
              <span className="kicker">// PROJECT</span>
            </div>
            <a
              className="link"
              href={GITCODE_URL}
              target="_blank"
              rel="noreferrer"
            >
              gitcode.com<span className="slash">/</span>chadwweng<span className="slash">/</span>clawcodex
            </a>
            <div className="brand">
              ClawCodex<span className="accent">.</span>DevMind
            </div>
            <div className="tag">现在去装一个 →</div>
          </div>
        </div>
      );
  }
}

export default function InstallChapter({ step }: ChapterStepProps): ReactElement {
  return (
    <div className="in-scene">
      <CornerMark />
      <StepMark step={step} total={TOTAL} />
      {renderStep(step)}
    </div>
  );
}