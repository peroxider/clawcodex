// Cover.tsx —— ClawCodex DevMind 发布说明 · 文章封面
//
// 模板 C · 上下分屏(Tufte 推荐):上半色块 + 标题文字,下半视觉主体(3 层架构 SVG)。
// 视觉技术:SVG(细线 + 极简填色 + currentColor + var(--ra-*) token)。
// 硬约束:
//   - 3:4 比例由外壳控制,内部元素全部百分比 / aspect-ratio 自适应
//   - 只用 --ra-* token,切主题封面自动跟随
//   - 不远程图片,offline-first

export function Cover() {
  return (
    <section
      className="ra-cover"
      aria-label="文章封面"
      data-ra-cover=""
      style={{
        position: "relative",
        width: "100%",
        maxWidth: "min(100%, 48rem, calc((100vh - 8rem) * 3 / 4))",
        margin: "0 auto var(--ra-space-7, 3rem) auto",
        aspectRatio: "3 / 4",
        overflow: "hidden",
        background: "transparent",
        color: "var(--ra-color-fg, inherit)",
        borderRadius: "var(--ra-radius-md, 0)",
        border: "1px solid var(--ra-color-border, currentColor)",
        isolation: "isolate",
      }}
    >
      <CoverContent />
    </section>
  );
}

function CoverContent() {
  return (
    <>
      {/* 背景:极细发丝线网格(0.4 opacity,Tufte 数据墨水感) */}
      <svg
        viewBox="0 0 1200 1600"
        preserveAspectRatio="xMidYMid slice"
        aria-hidden="true"
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          color: "var(--ra-color-border, currentColor)",
          opacity: 0.35,
          zIndex: 0,
        }}
      >
        <defs>
          <pattern id="ra-cover-grid" width="60" height="60" patternUnits="userSpaceOnUse">
            <path
              d="M 60 0 L 0 0 0 60"
              fill="none"
              stroke="currentColor"
              strokeWidth="0.4"
            />
          </pattern>
        </defs>
        <rect width="1200" height="1600" fill="url(#ra-cover-grid)" />
      </svg>

      {/* 上半:标题区(占 0% ~ 45% = 720px) */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          height: "45%",
          zIndex: 1,
          display: "flex",
          flexDirection: "column",
          justifyContent: "flex-end",
          padding: "var(--ra-space-7, 3rem)",
          gap: "var(--ra-space-3, 0.75rem)",
        }}
      >
        <span
          style={{
            fontSize: "var(--ra-text-xs, 0.75rem)",
            letterSpacing: "0.22em",
            textTransform: "uppercase",
            color: "var(--ra-color-muted, inherit)",
            opacity: 0.85,
            fontFamily: "var(--ra-font-mono, monospace)",
          }}
        >
          DEV · NOTES · 2026
        </span>
        <h1
          style={{
            margin: 0,
            fontSize: "clamp(2rem, 6vw, var(--ra-text-5xl, 4rem))",
            lineHeight: 1.05,
            fontWeight: "var(--ra-font-weight-bold, 700)",
            color: "var(--ra-color-fg, inherit)",
            fontFamily: "var(--ra-font-display, serif)",
            letterSpacing: "-0.02em",
          }}
        >
          ClawCodex / DevMind
        </h1>
        <p
          style={{
            margin: 0,
            fontSize: "var(--ra-text-base, 1rem)",
            color: "var(--ra-color-muted, inherit)",
            maxWidth: "80%",
            lineHeight: 1.4,
            fontFamily: "var(--ra-font-body, serif)",
          }}
        >
          把单个 agent 升级为可值守工程团队
        </p>
      </div>

      {/* 中间分割线:极细 hairline */}
      <div
        aria-hidden="true"
        style={{
          position: "absolute",
          top: "45%",
          left: "var(--ra-space-7, 3rem)",
          right: "var(--ra-space-7, 3rem)",
          height: "1px",
          background: "var(--ra-color-border, currentColor)",
          opacity: 0.5,
          zIndex: 2,
        }}
      />

      {/* 下半:3 层架构 SVG(占 45% ~ 100% = 720px ~ 1600px) */}
      <div
        style={{
          position: "absolute",
          top: "45%",
          left: 0,
          right: 0,
          bottom: 0,
          zIndex: 1,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: "center",
          padding: "var(--ra-space-6, 2rem)",
        }}
      >
        <svg
          viewBox="0 0 1000 760"
          preserveAspectRatio="xMidYMid meet"
          aria-label="三层架构示意图:src · clawcodex_ext · extensions"
          style={{
            width: "100%",
            height: "auto",
            maxWidth: "90%",
            color: "var(--ra-color-fg, inherit)",
          }}
        >
          {/* 标题(kicker) */}
          <text
            x="500"
            y="60"
            textAnchor="middle"
            fill="var(--ra-color-muted, currentColor)"
            fontSize="14"
            fontFamily="var(--ra-font-mono, monospace)"
            letterSpacing="0.18em"
            opacity="0.75"
          >
            THREE · LAYER · DECOUPLING
          </text>

          {/* Layer 0 · src/  (底,最宽) */}
          <g>
            <rect
              x="100"
              y="540"
              width="800"
              height="100"
              fill="var(--ra-color-accent, currentColor)"
              opacity="0.10"
            />
            <rect
              x="100"
              y="540"
              width="800"
              height="100"
              fill="none"
              stroke="var(--ra-color-border, currentColor)"
              strokeWidth="1.2"
            />
            <text
              x="500"
              y="585"
              textAnchor="middle"
              fill="var(--ra-color-fg, currentColor)"
              fontSize="22"
              fontFamily="var(--ra-font-mono, monospace)"
              fontWeight="600"
            >
              LAYER 0
            </text>
            <text
              x="500"
              y="615"
              textAnchor="middle"
              fill="var(--ra-color-muted, currentColor)"
              fontSize="16"
              fontFamily="var(--ra-font-mono, monospace)"
            >
              src/  ·  Upstream Claude Code
            </text>
          </g>

          {/* Layer 1 · clawcodex_ext/  (中) */}
          <g>
            <rect
              x="200"
              y="380"
              width="600"
              height="100"
              fill="var(--ra-color-accent, currentColor)"
              opacity="0.18"
            />
            <rect
              x="200"
              y="380"
              width="600"
              height="100"
              fill="none"
              stroke="var(--ra-color-border, currentColor)"
              strokeWidth="1.2"
            />
            <text
              x="500"
              y="425"
              textAnchor="middle"
              fill="var(--ra-color-fg, currentColor)"
              fontSize="22"
              fontFamily="var(--ra-font-mono, monospace)"
              fontWeight="600"
            >
              LAYER 1
            </text>
            <text
              x="500"
              y="455"
              textAnchor="middle"
              fill="var(--ra-color-muted, currentColor)"
              fontSize="16"
              fontFamily="var(--ra-font-mono, monospace)"
            >
              clawcodex_ext/  ·  Downstream Patches
            </text>
          </g>

          {/* Layer 2 · extensions/  (顶,最窄 + 最饱和) */}
          <g>
            <rect
              x="300"
              y="220"
              width="400"
              height="100"
              fill="var(--ra-color-accent, currentColor)"
              opacity="0.28"
            />
            <rect
              x="300"
              y="220"
              width="400"
              height="100"
              fill="none"
              stroke="var(--ra-color-accent, currentColor)"
              strokeWidth="1.6"
            />
            <text
              x="500"
              y="265"
              textAnchor="middle"
              fill="var(--ra-color-fg, currentColor)"
              fontSize="22"
              fontFamily="var(--ra-font-mono, monospace)"
              fontWeight="700"
            >
              LAYER 2
            </text>
            <text
              x="500"
              y="295"
              textAnchor="middle"
              fill="var(--ra-color-muted, currentColor)"
              fontSize="16"
              fontFamily="var(--ra-font-mono, monospace)"
            >
              extensions/  ·  Orchestrator · SOP
            </text>
          </g>

          {/* import 方向箭头(从 Layer 2 指向 Layer 1,Layer 1 指向 Layer 0) */}
          <g
            stroke="var(--ra-color-muted, currentColor)"
            strokeWidth="1.2"
            fill="none"
            opacity="0.55"
          >
            {/* Layer 2 → Layer 1 */}
            <line x1="430" y1="322" x2="370" y2="378" />
            <polyline points="370,378 380,374 374,366" />
            {/* Layer 1 → Layer 0 */}
            <line x1="330" y1="482" x2="270" y2="538" />
            <polyline points="270,538 280,534 274,526" />
          </g>

          {/* 编排器外环:覆盖三层 */}
          <circle
            cx="500"
            cy="420"
            r="340"
            fill="none"
            stroke="var(--ra-color-accent, currentColor)"
            strokeWidth="1"
            strokeDasharray="5 9"
            opacity="0.55"
          />

          {/* 编排器标签(右上角,在环外) */}
          <text
            x="880"
            y="180"
            textAnchor="end"
            fill="var(--ra-color-accent, currentColor)"
            fontSize="13"
            fontFamily="var(--ra-font-mono, monospace)"
            letterSpacing="0.18em"
            opacity="0.85"
          >
            7×24 ORCHESTRATOR
          </text>
        </svg>
      </div>
    </>
  );
}