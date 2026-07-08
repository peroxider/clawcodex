#!/usr/bin/env python3
"""
端到端演示：逻辑看板维护"去洗车店洗车"任务流程

用法：
  cd /mnt/c/WorkSpace/clawcodex
  python3 demo_car_wash.py
"""

from __future__ import annotations

from pathlib import Path
import shutil
import tempfile

# ── 启用逻辑看板 ──
from clawcodex_ext.feature_gate import get_registry

get_registry()._overrides["logical_kanban"] = True

from src.tool_system.context import ToolContext
from src.tool_system.tools import (
    TaskCreateTool,
    TaskUpdateTool,
    TaskListTool,
)


# ── 辅助打印 ──
def print_list(ctx: ToolContext, label: str) -> None:
    tasks = TaskListTool.call({}, ctx).output.get("tasks", [])
    print(f"  【{label}】")
    print(f"  {'ID':<20} {'Status':<14} {'derived':<14} {'Subject':<24} {'Notes'}")
    print(f"  {'-' * 20} {'-' * 14} {'-' * 14} {'-' * 24} {'-' * 30}")
    for t in sorted(tasks, key=lambda x: x.get("id", "")):
        lkb = t.get("lkb") or {}
        den = lkb.get("latestDenialReason") or {}
        msg = den.get("humanMessage", "")[:28] if den else ""
        print(
            f"  {t['id']:<20} {t.get('status', '?'):<14}"
            f" {lkb.get('derivedStatus', '?'):<14}"
            f" {t.get('subject', ''):<24} {msg}"
        )
    print()


def print_action(ctx: ToolContext, label: str, result) -> None:
    print(f"  ▶ {label}")
    if result.is_error:
        lkb = result.output.get("lkb") or {}
        msg = lkb.get("humanMessage") or result.output.get("reason", {}).get("message", "")
        repairs = lkb.get("repairSuggestions") or []
        print(f"    ❌ 拒绝 → {msg}")
        for r in repairs:
            desc = r.get("description", "")
            print(f"       修复: [{r.get('action', '?')}] {desc}")
    else:
        print(f"    ✅ 通过")
    print()


def create(subject: str, ctx: ToolContext) -> str:
    return TaskCreateTool.call({"subject": subject, "description": subject}, ctx).output["task"][
        "id"
    ]


# ======================================================================
#  主流程
# ======================================================================
def main():
    tmp = Path(tempfile.mkdtemp())
    print("=" * 72)
    print("  逻辑看板端到端演示：去 50 米外洗车店洗车")
    print("=" * 72)
    print()
    print("  场景：")
    print("    ▸ 洗车店离家 50 米")
    print("    ▸ 工人代洗车，车主不需在场")
    print("    ▸ 最终目标：车洗干净 + 人到家")
    print()

    # ── 方案 A：走路去（错误） ──────────────────────────
    print("─" * 72)
    print("【方案 A】走路去洗车店（错误示范）")
    print("─" * 72)

    ctx_a = ToolContext(workspace_root=tmp / "plan_A")
    A1 = create("走路去洗车店", ctx_a)
    A2 = create("洗车店洗车", ctx_a)

    # 洗车需要车到店（依赖 A1）
    TaskUpdateTool.call({"taskId": A2, "addBlockedBy": [A1]}, ctx_a)
    print_list(ctx_a, "初始")

    r_a1 = TaskUpdateTool.call({"taskId": A1, "status": "completed"}, ctx_a)
    print_action(ctx_a, "走路到店 → completed", r_a1)

    result = TaskUpdateTool.call({"taskId": A2, "status": "in_progress"}, ctx_a)
    print_action(ctx_a, "尝试洗车（车还在家）", result)
    print_list(ctx_a, "结果")

    print("  ⛔ 人到了但车没到 → 洗车任务没有物理前提\n")

    # ── 方案 B：开车去（正确） ──────────────────────────
    print("─" * 72)
    print("【方案 B】开车去洗车店（✅ 正确方案）")
    print("─" * 72)

    ctx_b = ToolContext(workspace_root=tmp / "plan_B")
    B1 = create("开车去洗车店", ctx_b)
    B2 = create("洗车店洗车（代洗）", ctx_b)
    B3 = create("走路回家（车留店）", ctx_b)
    B4 = create("走路回洗车店取车", ctx_b)
    B5 = create("开车回家", ctx_b)

    TaskUpdateTool.call({"taskId": B2, "addBlockedBy": [B1]}, ctx_b)
    TaskUpdateTool.call({"taskId": B3, "addBlockedBy": [B2]}, ctx_b)
    TaskUpdateTool.call({"taskId": B4, "addBlockedBy": [B3]}, ctx_b)
    TaskUpdateTool.call({"taskId": B5, "addBlockedBy": [B2, B4]}, ctx_b)
    print_list(ctx_b, "初始（依赖已建立）")

    steps = [
        ("① 开车去洗车店", B1, "completed"),
        ("② 开始洗车", B2, "in_progress"),
        ("③ 走路回家（车留店洗）", B3, "completed"),
        ("(等待) 洗车完成", B2, "completed"),
        ("④ 走路回店取车", B4, "completed"),
        ("⑤ 开车回家", B5, "completed"),
    ]
    for label, tid, status in steps:
        result = TaskUpdateTool.call({"taskId": tid, "status": status}, ctx_b)
        print_action(ctx_b, label, result)
        print_list(ctx_b, f"执行后")

    print("  🏁 全部完成！车洗干净，人到家。\n")

    # ── 错误尝试：车洗一半想开走 ───────────────────────
    print("─" * 72)
    print("【错误尝试】车洗到一半就想开回家")
    print("─" * 72)

    ctx_d = ToolContext(workspace_root=tmp / "plan_D")
    D1 = create("开车去洗车店", ctx_d)
    D2 = create("洗车店洗车", ctx_d)
    D3 = create("开车回家", ctx_d)

    TaskUpdateTool.call({"taskId": D2, "addBlockedBy": [D1]}, ctx_d)
    TaskUpdateTool.call({"taskId": D3, "addBlockedBy": [D2]}, ctx_d)
    TaskUpdateTool.call({"taskId": D1, "status": "completed"}, ctx_d)
    TaskUpdateTool.call({"taskId": D2, "status": "in_progress"}, ctx_d)

    print_list(ctx_d, "车在洗但没洗完")
    result = TaskUpdateTool.call({"taskId": D3, "status": "in_progress"}, ctx_d)
    print_action(ctx_d, "尝试开车回家", result)
    print("  ✅ 被看板拦截！因为洗车任务还没完成\n")

    # ── 总结 ──
    print("=" * 72)
    print("  总结")
    print("=" * 72)
    print()
    print("  正确流程：")
    print("    ① 开车去洗车店（50 米）")
    print("    ② 工人代洗车")
    print("    ③ 走路回家（车留店）")
    print("    ④ 洗好 → 走路回店取车")
    print("    ⑤ 开车回家")
    print()
    print("  逻辑看板做了什么：")
    print("    ✅ 阻止了车没到就洗车        (依赖 B1→B2)")
    print("    ✅ 阻止了车没洗好就开走      (依赖 B2→B5)")
    print("    ✅ 保证开车回家前人已到店     (依赖 B4→B5)")
    print("    ✅ 每一步有 validationRunId   → 可审计追溯")
    print()

    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
