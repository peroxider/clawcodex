import type { ChapterDef } from "./types";
import ColdopenChapter from "../chapters/01-coldopen/Coldopen";
import { narrations as coldopenNarrations } from "../chapters/01-coldopen/narrations";
import OrchestratorChapter from "../chapters/02-orchestrator/Orchestrator";
import { narrations as orchestratorNarrations } from "../chapters/02-orchestrator/narrations";
import SopCompilerChapter from "../chapters/03-sop-compiler/SopCompiler";
import { narrations as sopCompilerNarrations } from "../chapters/03-sop-compiler/narrations";
import InstallChapter from "../chapters/04-install/Install";
import { narrations as installNarrations } from "../chapters/04-install/narrations";

/**
 * Order = order of presentation.
 *
 * Each chapter MUST provide a `narrations: Narration[]` array. Its length
 * is the chapter's step count — there is no `totalSteps` to maintain
 * separately. This guarantees the audio synthesis pipeline, the runtime
 * stepper, and the chapter `.tsx` switch on `step` cannot drift apart.
 *
 * Visual styling (color, fonts) comes entirely from the active theme —
 * chapters never hard-code palette / font names. See THEMES.md.
 */
export const CHAPTERS: ChapterDef[] = [
  {
    id: "coldopen",
    title: "钩子 — 你睡了,agent 在干活",
    narrations: coldopenNarrations,
    Component: ColdopenChapter,
  },
  {
    id: "orchestrator",
    title: "编排器 — 长跑守护进程",
    narrations: orchestratorNarrations,
    Component: OrchestratorChapter,
  },
  {
    id: "sop-compiler",
    title: "SOP 编译器 — 多 agent 团队",
    narrations: sopCompilerNarrations,
    Component: SopCompilerChapter,
  },
  {
    id: "install",
    title: "安装 + 完整面貌",
    narrations: installNarrations,
    Component: InstallChapter,
  },
];