/**
 * 02-orchestrator · narrations
 * ─────────────────────────────────────────
 * B 站节奏章 · 16 步 · ~56s
 *
 * 整章分四段:
 *   step 0    章标 + 一句话定性
 *   step 1-3  流水线 + 4 平台 + worktree 拉出
 *   step 4-10 真实 log 逐行揭示(7 行)
 *   step 11-12 评审自动修复 + 同分支
 *   step 13   CI 反馈环
 *   step 14-15 takeover(引导 + 终端)
 *   step 16   13 态澄清队列
 *
 * 屏幕内容由 step 推进;每行口播对应 1 step。
 */
export const narrations: string[] = [
  // step 0 — 章标
  "它有个 Orchestrator,编排器。",
  // step 1 — 4 平台
  "一条常驻流水线,盯 4 个 issue 平台——GitHub、Gitee、GitCode、Linear。",
  // step 2 — 流程
  "哪个 issue 冒头,worktree 拉出来,agent 进场。",
  // step 3 — 转场
  "真实跑起来长这样——",
  // step 4-10 — 真实 log 7 行(README L166-173)
  "Read,132 行代码。",
  "Grep 关键字,3 个匹配。",
  "Edit,加 18 行删 4 行。",
  "Bash 跑 pytest,4 个 test 全过。",
  "Verification gate OK。",
  "Commit,Push,PR opened。",
  // step 11 — 转折
  "reviewer 评论落地?",
  // step 12 — 同分支
  "它接住,自己改,再 commit,同分支。",
  // step 13 — 反馈环
  "CI 报错?再读再改再跑。",
  // step 14-15 — takeover
  "你也能随时插一脚。",
  "issue takeover,REPL 接管,完事切回。",
  // step 16 — 13 态
  "13 种状态机管全程。",
];