# ClawCodex 扩展层迁移规划

# 完整 impl 文件归属矩阵

> 对 `clawcodex_ext/` 全部 53 个非空子目录 + `services/` 27 个子目录 + `services/` 8 个顶层文件做 **100% 覆盖校验**（无遗漏、无重复归属）。
> 每位工程师负责的文件 = **完整 impl 文件归属矩阵中自己名下所有路径下的全部 `.py` 文件** + 完整 tests 目录归属矩阵 中自己名下的全部测试目录。

### P1 — L1 Agent 核心（impl 合计 34,260 行 / 3 项）

| 归属路径 | 行数 |
|---|---:|
| `clawcodex_ext/tool_system/` | 22,507 |
| `clawcodex_ext/agent/` | 11,003 |
| `clawcodex_ext/remote/` | 750 |

### P2 — L1 Command/Query/Bridge/Providers（impl 合计 34,017 行 / 6 项）

| 归属路径 | 行数 |
|---|---:|
| `clawcodex_ext/command_system/` | 10,718 |
| `clawcodex_ext/providers/` | 7,493 |
| `clawcodex_ext/query/` | 6,754 |
| `clawcodex_ext/bridge/` | 6,388 |
| `clawcodex_ext/types/` | 1,381 |
| `clawcodex_ext/transports/` | 1,283 |

### P3 — L1 Services Group A + Buddy（impl 合计 25,294 行 / 5 项）

| 归属路径 | 行数 |
|---|---:|
| `clawcodex_ext/services/mcp/` | 8,003 |
| `clawcodex_ext/services/voice/` | 5,960 |
| `clawcodex_ext/services/channels/` | 5,495 |
| `clawcodex_ext/services/im_gateway/` | 4,435 |
| `clawcodex_ext/buddy/` | 1,401 |

### P4 — L1 Services Group B（impl 合计 31,175 行 / 30 项）

| 归属路径 | 行数 |
|---|---:|
| `clawcodex_ext/services/compact/` | 3,602 |
| `clawcodex_ext/services/templates/` | 2,784 |
| `clawcodex_ext/services/tool_execution/` | 2,756 |
| `clawcodex_ext/services/ultraplan/` | 2,625 |
| `clawcodex_ext/services/lodestone/` | 2,413 |
| `clawcodex_ext/services/chrome/` | 2,327 |
| `clawcodex_ext/services/skill_search/` | 1,934 |
| `clawcodex_ext/services/swarm/` | 1,681 |
| `clawcodex_ext/services/context_collapse/` | 1,522 |
| `clawcodex_ext/services/api/` | 1,244 |
| `clawcodex_ext/services/computer_use/` | 1,103 |
| `clawcodex_ext/services/langfuse/` | 933 |
| `clawcodex_ext/services/kairos/` | 727 |
| `clawcodex_ext/services/session_storage.py` | 654 |
| `clawcodex_ext/services/pipe_ipc/` | 559 |
| `clawcodex_ext/services/monitor/` | 545 |
| `clawcodex_ext/services/proactive/` | 497 |
| `clawcodex_ext/services/session_migrate.py` | 473 |
| `clawcodex_ext/services/ide/` | 439 |
| `clawcodex_ext/services/pricing.py` | 398 |
| `clawcodex_ext/services/session_resume.py` | 370 |
| `clawcodex_ext/services/cost_restore.py` | 267 |
| `clawcodex_ext/services/analytics/` | 248 |
| `clawcodex_ext/services/cost_tracker.py` | 248 |
| `clawcodex_ext/services/bridge/` | 233 |
| `clawcodex_ext/services/periodic/` | 164 |
| `clawcodex_ext/services/feature_gate/` | 141 |
| `clawcodex_ext/services/tail_follower.py` | 133 |
| `clawcodex_ext/services/session_title.py` | 104 |
| `clawcodex_ext/services/oauth/` | 51 |

### P5 — L1 CLI 与入口层（impl 合计 14,540 行 / 6 项）

| 归属路径 | 行数 |
|---|---:|
| `clawcodex_ext/cli/` | 9,251 |
| `clawcodex_ext/entrypoints/` | 3,108 |
| `clawcodex_ext/native/` | 1,191 |
| `clawcodex_ext/runtime/` | 651 |
| `clawcodex_ext/cli_core/` | 268 |
| `clawcodex_ext/daemon/` | 71 |

### P6 — L1 TUI/REPL/前端（impl 合计 33,526 行 / 5 项）

| 归属路径 | 行数 |
|---|---:|
| `clawcodex_ext/tui/` | 19,330 |
| `clawcodex_ext/repl/` | 10,043 |
| `clawcodex_ext/frontend/` | 1,844 |
| `clawcodex_ext/debug/` | 1,381 |
| `clawcodex_ext/diagnostics/` | 928 |

### P7 — L1 权限/鉴权/钩子（impl 合计 12,952 行 / 4 项）

| 归属路径 | 行数 |
|---|---:|
| `clawcodex_ext/permissions/` | 7,742 |
| `clawcodex_ext/hooks/` | 3,651 |
| `clawcodex_ext/auth/` | 1,551 |
| `clawcodex_ext/bootstrap/` | 8 |

### P8 — L1 智能子系统（impl 合计 33,887 行 / 12 项）

| 归属路径 | 行数 |
|---|---:|
| `clawcodex_ext/skills/` | 11,797 |
| `clawcodex_ext/context_system/` | 5,018 |
| `clawcodex_ext/goal/` | 4,366 |
| `clawcodex_ext/intent_forecast/` | 3,178 |
| `clawcodex_ext/multimodel/` | 2,340 |
| `clawcodex_ext/memdir/` | 2,038 |
| `clawcodex_ext/away_summary/` | 1,910 |
| `clawcodex_ext/dreaming/` | 1,837 |
| `clawcodex_ext/coordinator/` | 746 |
| `clawcodex_ext/session_intelligence/` | 359 |
| `clawcodex_ext/logical_kanban/` | 166 |
| `clawcodex_ext/memory/` | 132 |

### P9 — L1 调度/基础设施（impl 合计 20,850 行 / 12+ 项）

| 归属路径 | 行数 |
|---|---:|
| `clawcodex_ext/utils/` | 6,713 |
| `clawcodex_ext/cron_system/` | 3,886 |
| `clawcodex_ext/tasks/` | 1,985 |
| `clawcodex_ext/configuration/` | 1,462 |
| `clawcodex_ext/feature_gate/` | 1,172 |
| `clawcodex_ext/settings/` | 1,028 |
| `clawcodex_ext/state/` | 1,021 |
| `clawcodex_ext/orchestrator/` | 539 |
| `clawcodex_ext/messaging/` | 384 |
| `clawcodex_ext/assistant/` | 265 |
| `clawcodex_ext/compact_service/` | 239 |
| `clawcodex_ext/models/` | 146 |

基础项

| 归属路径 | 行数 | 说明 |
|---|---:|---|
| `clawcodex_ext/__init__.py` + 顶层 11 个 `.py`（`init.py` / `config.py` / `_version.py` / `llm.py` / `mcp_ext.py` / `task_registry.py` / `tasks_core.py` / `telemetry_lifecycle.py` / `tool_stats.py` / `outputStyles.py`） | 1,800 | 启动入口，team lead 锁定，仅做 re-export |
| `clawcodex_ext/services/__init__.py` | 1 | services 聚合入口，team lead 预填全部子包 re-export |
| `clawcodex_ext/capabilities/` | 145 | Layer 1→2 Protocol 契约边界，team lead 锁定（改动需全员评审） |
| `clawcodex_ext/constants/` | 64 | 全局共享常量，被各处 import，team lead 锁定 |
| `clawcodex_ext/agent_mention/` | 0 | 空目录，跳过 |

### impl 归属汇总

| 工人 | impl 行数 |
|---|---:|
| P1 | 34,260 |
| P2 | 34,017 |
| P3 | 25,294 |
| P4 | 31,175 |
| P5 | 14,540 |
| P6 | 33,526 |
| P7 | 12,952 |
| P8 | 33,887 |
| P9 | 20,850 |

> **说明**：P3 / P5 / P7 impl 行数偏低（12K–18K），因其 impl 体量本就小；三人的总工作量由**测试目录**补齐。

---

# 完整 tests 目录归属矩阵

### P1 — L1 Agent & Tool（tests 合计 17,778 行 / 9 项）

| 归属路径 | 行数 |
|---|---:|
| `tests/agent/` | 6,172 |
| `tests/tool/` | 5,410 |
| `tests/tool_system/` | 1,448 |
| `tests/bash/` | 1,448 |
| `tests/sessions/` | 1,209 |
| `tests/remote/` | 1,013 |
| `tests/clawcodex_ext/agent_tests/` | 523 |
| `tests/clawcodex_ext/tool_system/` | 308 |
| `tests/clawcodex_ext/agent/` | 247 |

### P2 — L1 Command/Query/Bridge/Providers（tests 合计 24,288 行 / 8 项）

| 归属路径 | 行数 |
|---|---:|
| `tests/bridge/` | 9,801 |
| `tests/provider/` | 4,736 |
| `tests/query/` | 3,158 |
| `tests/plugin/` | 2,759 |
| `tests/command_system/` | 2,170 |
| `tests/clawcodex_ext/providers/` | 762 |
| `tests/transports/` | 491 |
| `tests/clawcodex_ext/query/` | 411 |

### P3 — L1 Services Group B（tests 合计 30,696 行 / 2 项）

| 归属路径 | 行数 |
|---|---:|
| `tests/services/` | 29,583 |
| `tests/clawcodex_ext/services/` | 1,113 |


### P4 — L1 CLI 与入口层（tests 合计 18,178 行 / 5 项）

| 归属路径 | 行数 |
|---|---:|
| `tests/stability_gate/` | 9,040 |
| `tests/cli/` | 7,180 |
| `tests/trae/` | 899 |
| `tests/runtime/` | 596 |
| `tests/clawcodex_ext/native/` | 463 |


### P5 — L1 调度/基础设施（tests 合计 34,635 行 / 31 项）

| 归属路径 | 行数 |
|---|---:|
| `tests/cron/` | 4,618 |
| `tests/telemetry/` | 3,866 |
| `tests/tasks/` | 3,000 |
| `tests/voice/` | 2,493 |
| `tests/abort/` | 2,326 |
| `tests/compact/` | 2,136 |
| `tests/provider/` | 1,876 |
| `tests/input/` | 1,858 |
| `tests/config/` | 1,296 |
| `tests/feature_gate/` | 1,167 |
| `tests/message/` | 1,166 |
| `tests/ci/` | 888 |
| `tests/system_prompt/` | 828 |
| `tests/utils/` | 813 |
| `tests/token_tests/` | 743 |
| `tests/state/` | 656 |
| `tests/cache/` | 576 |
| `tests/cost_tracker/` | 528 |
| `tests/clawcodex_ext/tasks/` | 505 |
| `tests/assistant/` | 478 |
| `tests/image/` | 471 |
| `tests/file_ops/` | 307 |
| `tests/messaging/` | 279 |
| `tests/snapshot/` | 274 |
| `tests/model/` | 271 |
| `tests/release_smoke/` | 260 |
| `tests/fast/` | 256 |
| `tests/ide/` | 210 |
| `tests/output/` | 207 |
| `tests/signal_tests/` | 165 |
| `tests/analytics/` | 118 |

### P6 — L1 TUI/REPL/前端（tests 合计 18,376 行 / 5 项）

| 归属路径 | 行数 |
|---|---:|
| `tests/tui/` | 9,421 |
| `tests/repl/` | 3,883 |
| `tests/debug/` | 2,433 |
| `tests/frontend/` | 1,669 |
| `tests/diagnostics/` | 970 |


### P7 — L1 智能子系统（tests 合计 37,054 行 / 13 项）

| 归属路径 | 行数 |
|---|---:|
| `tests/logical_kanban/` | 12,867 |
| `tests/skills/` | 9,160 |
| `tests/goal/` | 2,980 |
| `tests/away_summary/` | 2,672 |
| `tests/advisor/` | 2,212 |
| `tests/dreaming/` | 2,030 |
| `tests/intent_forecast/` | 1,652 |
| `tests/memdir/` | 1,445 |
| `tests/coordinator/` | 637 |
| `tests/multimodel/` | 572 |
| `tests/context/` | 521 |
| `tests/clawcodex_ext/logical_kanban/` | 245 |
| `tests/session_intelligence/` | 61 |

### P8 — L1 权限/鉴权/钩子（tests 合计 18,697 行 / 7 项）

| 归属路径 | 行数 |
|---|---:|
| `tests/permissions/` | 3,420 |
| `tests/hooks/` | 1,869 |
| `tests/auth/` | 1,057 |
| `tests/bootstrap/` | 535 |
| `tests/git_fixtures/` | 488 |
| `tests/parity` | 5,758 |
| `tests/integration` | 5,570 |

### P9 — L1 Services Group A（tests 合计 5,870 行 / 3 项）

| 归属路径 | 行数 |
|---|---:|
| `tests/mcp/` | 5,063 |
| `tests/streaming/` | 514 |
| `tests/proactive/` | 293 |


顶层 test 文件（不在子目录内）

| 文件 | 归属 | 行数 |
|---|---|---:|
| `tests/test_session_chain.py` | **P1** | 496 |
| `tests/test_agent_name.py` | **P1** | 453 |
| `tests/test_mcp_ext.py` | **P3** | 281 |
| `tests/test_llm.py` | **P2** | 186 |
| `tests/conftest.py` | **LOCK** | 146 |

### 待拆（**无清晰单一 owner**）

| 归属路径 | 行数 | 备注 |
|---|---:|---|
| `tests/misc` | 22,618 | 待拆 |


### LOCK / 共享

| 归属路径 | 行数 | 备注 |
|---|---:|---|
| `tests/fixtures` | 90 | 共享 fixture / helper，任何 worker 不修改 |
| `tests/helpers` | 78 | 共享 fixture / helper，任何 worker 不修改 |
| `tests/conftest.py` | 146 | 顶层 conftest，团队负责人锁定 |

### tests 归属汇总

| 归属 | tests 行数 |
|---|---:|
| P1 | 17,778 |
| P2 | 24,288 |
| P3 | 30,696 |
| P4 | 18,178 |
| P5 | 34,635 |
| P6 | 18,376 |
| P7 | 37,054 |
| P8 | 18,697 |
| P9 | 5,870 |
| 待拆 | 22,618 |
| LOCK / 共享 | 314 |


| 归属 |  总行数统计 |
|---|-------:|
| P1 | 52,038 |
| P2 | 58,305 |
| P3 | 55,990 |
| P4 | 49,353 |
| P5 | 49,175 |
| P6 | 51,902 |
| P7 | 50,006 |
| P8 | 52,584 |
| P9 | 26,720 |