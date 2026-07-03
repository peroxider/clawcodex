import { useEffect, useState } from "react";
import type { ChapterStepProps } from "../../registry/types";
import "./Coldopen.css";

/**
 * 01-coldopen · 钩子章
 * ─────────────────────────────────────────
 * 3 步 · ~9s
 *   step 0: 「你睡了」+ 时钟 22:47
 *   step 1: 「早上醒来,PR 自己开了」+ 时钟跳 08:12 + PR 卡片滑入
 *   step 2: 品牌 ClawCodex DevMind + 一句话定性
 *
 * 主导动作:mask reveal(光标闪烁)、PR 卡片 slide-in、对号描边、时钟数字 flip
 * 反 AI 味:无渐变、无圆角彩边、无 emoji;所有色彩/字号走 token
 */

function Clock({ time }: { time: string }) {
  // 时钟数字在 step 切换时通过 key 触发 flip 动画
  return (
    <div className="cd-clock cd-flip-in" key={time}>
      {time}
    </div>
  );
}

export default function ColdopenChapter({ step }: ChapterStepProps) {
  // step 1 时让 step 0 的时钟先 fade-out,再 mount 新的
  const [showOldClock, setShowOldClock] = useState(true);

  useEffect(() => {
    if (step === 0) {
      setShowOldClock(true);
      return;
    }
    if (step === 1) {
      // 让 step 0 的时钟播一段 flip-out,然后切到 08:12
      setShowOldClock(false);
      return;
    }
    setShowOldClock(false);
  }, [step]);

  // ─── step 0 ───
  if (step === 0) {
    return (
      <div className="cd-scene">
        <div className="cd-corner">
          <span className="ord">01</span>
          <span className="sep">/</span>
          <span>04</span>
          <span className="sep">·</span>
          <span>COLDOPEN</span>
        </div>
        {showOldClock && <Clock time="22:47" />}
        <div className="cd-step0 scene-pad">
          <div className="kicker">
            <span className="kicker-line" />
            <span>凌晨</span>
          </div>
          <h1 className="cd-hero0">
            你睡了<span className="blink" aria-hidden />
          </h1>
          <div className="cd-sub0">
            <span className="arrow">›</span>
            agent 在干活
          </div>
        </div>
      </div>
    );
  }

  // ─── step 1 ───
  if (step === 1) {
    return (
      <div className="cd-scene">
        <div className="cd-corner">
          <span className="ord">01</span>
          <span className="sep">/</span>
          <span>04</span>
          <span className="sep">·</span>
          <span>COLDOPEN</span>
        </div>
        <Clock time="08:12" />
        <div className="cd-step1">
          <div className="cd-step1-left">
            <div className="kicker">
              <span className="kicker-line" />
              <span>早上</span>
            </div>
            <h2 className="cd-hero1">
              <span className="pulse">PR</span> 自己开了
            </h2>
            <div className="cd-sub0">
              <span className="arrow">›</span>
              等你起来 review
            </div>
          </div>
          <div className="cd-step1-right cd-pr-enter">
            <div className="cd-pr">
              <div className="cd-pr-head">
                <span className="merge-dot" />
                <span className="pr-label">PULL REQUEST</span>
                <span className="pr-num">#427</span>
              </div>
              <div className="cd-pr-title">
                <span className="branch">feat/orchestrator-042</span>
                add retry policy for tracker adapters
              </div>
              <div className="cd-pr-meta">
                <span>+183 −42</span>
                <span>4 files</span>
                <span className="cd-pr-check">
                  <svg viewBox="0 0 24 24">
                    <path d="M5 12.5l4 4 10-10" />
                  </svg>
                  CI PASS
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ─── step 2 ───
  return (
    <div className="cd-scene">
      <div className="cd-corner">
        <span className="ord">01</span>
        <span className="sep">/</span>
        <span>04</span>
        <span className="sep">·</span>
        <span>COLDOPEN</span>
      </div>
      <div className="cd-step2 scene-pad">
        <div className="cd-pre-brand">— THE TEAM THAT WORKS WHILE YOU SLEEP —</div>
        <h1 className="cd-brand">
          ClawCodex<span className="accent">.</span>DevMind
        </h1>
        <div className="cd-tag">把单个 agent 升级为一支可值守的工程团队</div>
        <div className="cd-meta">
          <span>ORCHESTRATOR</span>
          <span className="sq" />
          <span>SOP</span>
          <span className="sq" />
          <span>PR REVIEW</span>
          <span className="sq" />
          <span>VERIFICATION</span>
        </div>
      </div>
    </div>
  );
}