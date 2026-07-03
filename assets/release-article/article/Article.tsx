import { Article, Hero, Lead, Raw } from "reacticle";
import { SectionOrchestrator } from "./sections/01-orchestrator";
import { SectionSopCompiler } from "./sections/02-sop-compiler";
import { SectionAuxCapabilities } from "./sections/03-aux-capabilities";
import { SectionDecoupling } from "./sections/04-decoupling";
import { SectionInstall } from "./sections/05-install";
import { SectionLimitsMeta } from "./sections/06-limits-meta";

// Article.tsx is the ASSEMBLER. Imports + orders Section components; must NOT
// contain Section bodies inline. 一节一文件铁律（多 Agent 并行前提）。
export function ArticleDoc() {
  return (
    <Article toc width="regular">
      <Hero
        eyebrow="Release Notes · v0.1.0"
        title="ClawCodex DevMind"
        subtitle="把单个 agent 升级为可值守工程团队"
        meta={[
          { label: "版本", value: "v0.1.0 MVP" },
          { label: "日期", value: "2026-04-19" },
          { label: "License", value: "MIT" },
          { label: "测试", value: "270+ passing" },
        ]}
      />
      <Lead>
        Claude Code Python 重构版的下游 fork · 在上游能力之上,新增编排器与 SOP 编译器,
        把单 agent 升级为可值守的工程团队。一行命令安装,4 跟踪器 · 100+ LLM 后端 ·
        3 行启动一条自主工程流水线。
      </Lead>

      {/* Hero Metrics:三数横排(用 Raw 而非堆卡片 —— 服务阅读、不装饰) */}
      <Raw title="Hero Metrics · 一图概览">
        <div
          role="group"
          aria-label="三个核心数字"
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            gap: "var(--ra-space-6, 2rem)",
            marginTop: "var(--ra-space-5, 1.5rem)",
            marginBottom: "var(--ra-space-6, 2rem)",
            padding:
              "var(--ra-space-5, 1.5rem) var(--ra-space-6, 2rem)",
            border: "1px solid var(--ra-color-border, currentColor)",
            background:
              "color-mix(in srgb, var(--ra-color-surface, transparent) 60%, transparent)",
            borderRadius: "var(--ra-radius-md, 0)",
          }}
        >
          <Metric
            big="4"
            label="支持的 issue 跟踪器"
            sub="GitHub · Gitee · GitCode · Linear"
          />
          <Metric
            big="100+"
            label="LLM 后端"
            sub="LiteLLM 路由:Bedrock · Vertex · Azure · OpenAI · Together · Anyscale · ..."
          />
          <Metric
            big="3 行"
            label="启动一条流水线"
            sub="start · list · tail —— 不再是 demo"
          />
        </div>
      </Raw>

      <SectionOrchestrator />
      <SectionSopCompiler />
      <SectionAuxCapabilities />
      <SectionDecoupling />
      <SectionInstall />
      <SectionLimitsMeta />

      {/* ─── Colophon ─── */}
      <Raw title="">
        <footer
          style={{
            marginTop: "var(--ra-space-7, 3rem)",
            paddingTop: "var(--ra-space-4, 1rem)",
            borderTop: "1px solid var(--ra-color-border, currentColor)",
            color: "var(--ra-color-muted, inherit)",
            fontSize: "var(--ra-text-xs, 0.78rem)",
            textAlign: "center",
            letterSpacing: "0.02em",
            opacity: 0.85,
          }}
        >
          Made with{" "}
          <a
            href="https://github.com/ConardLi/garden-skills"
            target="_blank"
            rel="noopener noreferrer"
            style={{
              color: "inherit",
              textDecoration: "underline",
              textUnderlineOffset: "0.2em",
            }}
          >
            beautiful-article
          </a>{" "}
          · tufte theme
        </footer>
      </Raw>
    </Article>
  );
}

function Metric({
  big,
  label,
  sub,
}: {
  big: string;
  label: string;
  sub: string;
}) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "var(--ra-space-2, 0.5rem)",
      }}
    >
      <span
        style={{
          fontFamily: "var(--ra-font-display, serif)",
          fontSize: "clamp(2.2rem, 4vw, var(--ra-text-5xl, 3.5rem))",
          fontWeight: "var(--ra-font-weight-bold, 700)",
          color: "var(--ra-color-fg, inherit)",
          lineHeight: 1,
          letterSpacing: "-0.02em",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {big}
      </span>
      <span
        style={{
          fontSize: "var(--ra-text-sm, 0.95rem)",
          color: "var(--ra-color-fg, inherit)",
          fontWeight: 600,
        }}
      >
        {label}
      </span>
      <span
        style={{
          fontSize: "var(--ra-text-xs, 0.78rem)",
          color: "var(--ra-color-muted, inherit)",
          lineHeight: 1.5,
        }}
      >
        {sub}
      </span>
    </div>
  );
}