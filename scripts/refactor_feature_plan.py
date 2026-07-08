"""
Refactor FEATURE_PLAN.md into a consistent format.

Goals:
1. Consistent F-N numbering format
2. Consistent status emojis (✅ 📋 🔄 🔭 ⛔)
3. Consistent description style and structure
4. Reasonable section lengths per feature
"""

import re
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Feature:
    f_number: str
    title: str
    status: str  # emoji: ✅ 📋 🔄 🔭 ⛔
    status_text: str
    priority: str = "P?"
    goal: str = ""
    content_lines: list[str] = field(default_factory=list)
    section_level: int = 3
    original_anchor: str = ""


def parse_feature_status(line: str) -> tuple[str, str]:
    """Extract status emoji and text from a line."""
    # Look for status patterns
    patterns = [
        (r"✅\s*已完成?", "✅", "已完成"),
        (r"✅\s*完成", "✅", "已完成"),
        (r"📋\s*设计完成", "📋", "设计完成"),
        (r"📋\s*规划中", "📋", "规划中"),
        (r"📋\s*待开始", "📋", "待开始"),
        (r"📋\s*待实现", "📋", "待实现"),
        (r"🔄\s*部分完成", "🔄", "部分完成"),
        (r"🔄\s*进行中", "🔄", "进行中"),
        (r"🔭\s*长期规划", "🔭", "长期规划"),
        (r"⛔\s*已被取代", "⛔", "已被取代"),
        (r"⛔\s*已废弃", "⛔", "已废弃"),
    ]
    for pat, emoji, text in patterns:
        if re.search(pat, line):
            return emoji, text
    # Try looser patterns
    if "✅" in line:
        return "✅", "已完成"
    if "📋" in line:
        return "📋", "规划中"
    if "🔄" in line:
        return "🔄", "进行中"
    if "🔭" in line:
        return "🔭", "长期规划"
    if "⛔" in line:
        return "⛔", "已被取代"
    return "📋", "规划中"


def extract_priority(line: str) -> str:
    """Extract P0/P1/P2/P3 priority from a line."""
    m = re.search(r"优先级\s*[:：]\s*(P[0-4])", line, re.I)
    if m:
        return m.group(1).upper()
    m = re.search(r"\b(P[0-4])\b", line)
    if m:
        return m.group(1).upper()
    return "P?"


def extract_goal(lines: list[str]) -> str:
    """Extract goal/target from feature lines."""
    for line in lines:
        line = line.strip()
        if (
            line.startswith("**目标**")
            or line.startswith("**目标**:")
            or line.startswith("目标：")
            or line.startswith("目标:")
        ):
            # Extract after the marker
            parts = line.split("**目标**", 1)
            if len(parts) > 1:
                goal = parts[1].strip().lstrip(":：").strip()
                if goal:
                    return goal
            # Try other formats
            m = re.search(r"目标[：:]\s*(.+)", line)
            if m:
                return m.group(1).strip()
        if line.startswith("> **目标**") or line.startswith("> 目标："):
            m = re.search(r"目标[：:]\s*(.+)", line)
            if m:
                return m.group(1).strip()
    # Look for a line with just "目标: ..."
    for line in lines:
        m = re.search(r"(?i)(?:^|\s)目标\s*[:：]\s*(.+)", line)
        if m:
            return m.group(1).strip()
    return ""


def is_archive_link(line: str) -> bool:
    """Check if line is a reference to archived features."""
    return "ARCHIVED_FEATURES.md" in line or "ARCHIVED_PROGRESS.md" in line


def is_f_number_header(line: str) -> tuple[bool, str, str]:
    """Check if line is a feature header and return F-number and title."""
    # Match patterns like:
    # ### F-36 LocalTracker (✅)
    # #### 1.1.1 LocalTracker (F-36)
    # #### F-36 LocalTracker ✅
    # ### F-36 LocalTracker
    # etc.

    patterns = [
        # F-NNN in parens at end
        r"^(#{3,4})\s+(?:\d+\.\d+(?:\.\d+)?\s+)?(.+?)\s*\((F-\d+(?:\.\d+)?)\s*[:：]?\s*(✅|📋|🔄|🔭|⛔)?\s*\)\s*$",
        # F-NNN at start
        r"^(#{3,4})\s+(F-\d+(?:\.\d+)?)[:：\s]+(.+?)\s*$",
        # Numbered section with F-NNN in parens
        r"^(#{3,4})\s+(?:\d+\.\d+(?:\.\d+)?\s+)?(.+?)\s*\((F-\d+(?:\.\d+)?)\)\s*$",
    ]

    for pat in patterns:
        m = re.match(pat, line)
        if m:
            groups = m.groups()
            if groups[1].startswith("F-"):
                return True, groups[1], groups[2] if len(groups) > 2 else groups[1]
            else:
                # F-number is in a different position
                f_num = [g for g in groups if g and g.startswith("F-")]
                if f_num:
                    return True, f_num[0], groups[1] if groups[1] != f_num[0] else groups[2]
    return False, "", ""


def clean_f_number(f_num: str) -> str:
    """Normalize F-number to standard format."""
    f_num = f_num.strip()
    # F-50.10 -> F-50.10 (keep as is)
    # F-1.10 -> F-1.10
    # F-22-G1 -> F-22-G1 (keep sub-feature IDs)
    return f_num


def rewrite_feature(feature: Feature) -> list[str]:
    """Rewrite a feature block in consistent format."""
    out = []

    # Header
    out.append(f"### {feature.f_number} {feature.title} {feature.status}")
    out.append("")

    # Attribute table
    out.append("| 属性 | 值 |")
    out.append("|------|-----|")
    out.append(f"| 状态 | {feature.status} {feature.status_text} |")
    out.append(f"| 优先级 | {feature.priority} |")
    if feature.goal:
        out.append(f"| 目标 | {feature.goal} |")
    out.append("")

    # For completed features, keep it very short
    if feature.status == "✅":
        # Extract archive link if present
        archive_line = ""
        for line in feature.content_lines:
            if is_archive_link(line) and "详见" in line:
                archive_line = line.strip().lstrip(">").strip()
                break
        if not archive_line:
            for line in feature.content_lines:
                if "ARCHIVED" in line and ("详见" in line or "见" in line):
                    archive_line = line.strip().lstrip(">").strip()
                    break

        # Extract brief implementation note
        impl_note = ""
        for line in feature.content_lines:
            line = line.strip()
            if (
                line
                and not line.startswith("#")
                and not line.startswith(">")
                and not line.startswith("|")
                and not line.startswith("```")
                and not is_archive_link(line)
            ):
                if len(line) > 20 and (
                    "实现" in line
                    or "完成" in line
                    or "已" in line
                    or "代码" in line
                    or "行" in line
                ):
                    impl_note = line
                    break

        out.append("#### 概述")
        if impl_note:
            # Clean up the note
            note = impl_note.strip("*").strip()
            out.append(note)
        else:
            out.append(f"{feature.title} 已实现并归档。")
        out.append("")

        if archive_line:
            out.append(f"> {archive_line}")
            out.append("")

        out.append("---")
        out.append("")
        return out

    # For superseded features
    if feature.status == "⛔":
        out.append("#### 概述")
        out.append(f"{feature.title} 已被其他特性取代，不再作为独立特性实施。")
        out.append("")
        # Extract replacement info
        for line in feature.content_lines:
            if "已被" in line or "取代" in line or "吸收" in line:
                line = line.strip().lstrip(">").strip()
                if (
                    line
                    and not line.startswith("#")
                    and not line.startswith("|")
                    and not line.startswith("```")
                ):
                    out.append(line)
                    break
        out.append("")
        out.append("---")
        out.append("")
        return out

    # For long-term features
    if feature.status == "🔭":
        out.append("#### 概述")
        # Extract first meaningful paragraph
        for line in feature.content_lines:
            line = line.strip()
            if (
                line
                and not line.startswith("#")
                and not line.startswith(">")
                and not line.startswith("|")
                and not line.startswith("```")
                and not line.startswith("`")
                and len(line) > 20
            ):
                out.append(line)
                break
        out.append("")
        out.append("---")
        out.append("")
        return out

    # For in-progress and planning features - condense
    out.append("#### 概述")

    # Extract first meaningful paragraph
    found_desc = False
    for line in feature.content_lines:
        line = line.strip()
        if (
            line
            and not line.startswith("#")
            and not line.startswith(">")
            and not line.startswith("|")
            and not line.startswith("```")
            and not line.startswith("`")
            and not line.startswith("**")
            and len(line) > 15
        ):
            out.append(line)
            found_desc = True
            break
    if not found_desc:
        out.append(f"{feature.title} 的设计与实现规划。")
    out.append("")

    # Key status points (for in-progress)
    if feature.status == "🔄":
        out.append("#### 实现状态")
        # Extract key done items
        done_items = []
        for line in feature.content_lines:
            line = line.strip()
            if "✅" in line and len(line) < 150:
                # Extract the text after ✅
                text = re.sub(r".*✅\s*", "", line).strip()
                if text and not text.startswith("```"):
                    done_items.append(f"- ✅ {text}")
            elif (
                "已完成" in line
                and len(line) < 150
                and not line.startswith("#")
                and not line.startswith("|")
            ):
                if line not in done_items:
                    done_items.append(f"- {line}")
            if len(done_items) >= 5:
                break
        if done_items:
            out.extend(done_items[:5])
            out.append("")

        # Extract remaining items
        remain_items = []
        for line in feature.content_lines:
            line = line.strip()
            if (
                ("待" in line or "剩余" in line or "TODO" in line or "待补" in line or "缺" in line)
                and len(line) < 150
                and not line.startswith("#")
                and not line.startswith("|")
                and not line.startswith("```")
            ):
                if "待" in line or "缺" in line or "TODO" in line:
                    text = re.sub(r"^[-*]\s*", "", line)
                    remain_items.append(f"- 📋 {text}")
            if len(remain_items) >= 5:
                break
        if remain_items:
            out.extend(remain_items[:5])
            out.append("")

    # For planning features, extract key design decisions or sub-features
    if feature.status == "📋":
        out.append("#### 设计要点")
        # Extract sub-feature table or key points
        sub_features = []
        for line in feature.content_lines:
            line = line.strip()
            # Look for numbered sub-features like P108-A, P5-A, etc.
            m = re.match(r"^[-*]\s*(P\d+[-_][A-Z]\d?)\s*[—:]\s*(.+)", line)
            if m:
                sub_features.append(f"- **{m.group(1)}**: {m.group(2)}")
            elif re.match(r"^\d+\.\s+", line) and len(line) < 100 and not line.startswith("```"):
                sub_features.append(f"- {re.sub(r'^\d+\.\s*', '', line)}")
            if len(sub_features) >= 8:
                break
        if sub_features:
            out.extend(sub_features[:8])
            out.append("")
        else:
            # Try to extract any meaningful bullet points
            for line in feature.content_lines:
                line = line.strip()
                if line.startswith("- ") or line.startswith("* "):
                    if len(line) < 120 and not line.startswith("```") and not line.startswith("|"):
                        sub_features.append(line)
                    if len(sub_features) >= 5:
                        break
            if sub_features:
                out.extend(sub_features[:5])
                out.append("")

    # Extract key files if mentioned
    files = []
    for line in feature.content_lines:
        line = line.strip()
        if line.startswith("|") and (
            ".py" in line or ".ts" in line or ".json" in line or ".yaml" in line or ".yml" in line
        ):
            continue  # Skip table rows, handle separately
        # Look for file paths in backticks
        for match in re.finditer(r"`([^`]+\.(?:py|ts|json|yaml|yml|md))`", line):
            path = match.group(1)
            if path not in [f[0] for f in files] and len(path) < 100:
                files.append((path, "实现文件"))
        if len(files) >= 8:
            break

    if files:
        out.append("#### 关键文件")
        out.append("| 文件 | 说明 |")
        out.append("|------|------|")
        for path, desc in files[:8]:
            out.append(f"| `{path}` | {desc} |")
        out.append("")

    out.append("---")
    out.append("")
    return out


def main():
    input_path = Path(r"C:\WorkSpace\clawcodex\docs\FEATURE_PLAN.md")
    output_path = Path(r"C:\WorkSpace\clawcodex\docs\FEATURE_PLAN_REFACTORED.md")

    with open(input_path, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.split("\n")

    # State machine for parsing
    out_lines = []
    features = []
    current_feature = None
    in_toc = False

    # First pass: identify all feature sections
    i = 0
    while i < len(lines):
        line = lines[i]

        # Check if this is a feature header
        is_feat, f_num, title = is_f_number_header(line)
        if is_feat:
            # Save previous feature if exists
            if current_feature is not None:
                features.append(current_feature)

            # Parse status from this line and surrounding lines
            status, status_text = parse_feature_status(line)
            priority = "P?"
            goal = ""

            # Look ahead for status, priority, goal
            look_ahead = lines[i : i + 15]
            for j, la in enumerate(look_ahead):
                if j == 0:
                    # First line might have status
                    s, st = parse_feature_status(la)
                    if s != "📋":
                        status, status_text = s, st
                # Priority
                if priority == "P?":
                    priority = extract_priority(la)
                # Goal
                if not goal:
                    goal = extract_goal([la])

            current_feature = Feature(
                f_number=clean_f_number(f_num),
                title=title.strip(),
                status=status,
                status_text=status_text,
                priority=priority,
                goal=goal,
                content_lines=[],
                section_level=line.count("#"),
            )
            i += 1
            continue

        # Check for section headers that might indicate end of feature
        if current_feature is not None:
            # Check if we hit a new section at same or higher level
            if line.startswith("#"):
                level = line.count("#")
                if level <= current_feature.section_level:
                    # New section at same or higher level - end current feature
                    features.append(current_feature)
                    current_feature = None
                    # Don't increment i, reprocess this line
                    continue

            current_feature.content_lines.append(line)

        i += 1

    if current_feature is not None:
        features.append(current_feature)

    # Group features by chapter based on original document structure
    # For now, let's just do a second pass to rebuild the document
    # with only the rewritten features

    print(f"Found {len(features)} features")
    for f in features[:10]:
        print(f"  {f.f_number}: {f.title} [{f.status} {f.status_text}] P={f.priority}")

    # Build the new document
    out_lines = []

    # Header
    out_lines.append("# ClawCodex 特性规划与设计文档")
    out_lines.append("")
    out_lines.append("> 文档路径: `docs/FEATURE_PLAN.md`")
    out_lines.append("> 版本: v4.0（格式重构版）")
    out_lines.append("> 更新日期: 2026-06-23")
    out_lines.append("")
    out_lines.append("---")
    out_lines.append("")

    # TOC
    out_lines.append("## 目录")
    out_lines.append("")

    # Build TOC from features
    chapters = {}
    for f in features:
        # Determine chapter based on F-number range
        # This is a heuristic - we'll map based on known ranges
        pass

    # For now, just list all features in the TOC
    for f in features:
        out_lines.append(
            f"- [{f.f_number} {f.title}](#{f.f_number.lower().replace('.', '')}-{'-'.join(f.title.split()[:3])})"
        )
    out_lines.append("")
    out_lines.append("---")
    out_lines.append("")

    # Project overview (keep minimal)
    out_lines.append("## 项目概述与边界约束")
    out_lines.append("")
    out_lines.append("### 1.1 项目定位")
    out_lines.append("")
    out_lines.append(
        "ClawCodex 是 Anthropic Claude Code 的 Python 移植版，同时扩展多 Provider 支持，目标成为功能完整的 AI Agent CLI 工具。"
    )
    out_lines.append("")
    out_lines.append("### 1.2 当前架构（三层解耦）")
    out_lines.append("")
    out_lines.append("```")
    out_lines.append("src/")
    out_lines.append("├── upstream/            # Layer 1: 上游快照")
    out_lines.append("├── capabilities/        # Layer 2: 协议接口定义")
    out_lines.append("├── orchestrator/        # Layer 3: 自主模式编排")
    out_lines.append("├── api/                 # Layer 3: 公共 Python API")
    out_lines.append("└── ...                  # 其余上游原有模块")
    out_lines.append("```")
    out_lines.append("")
    out_lines.append(
        "**核心约束**：所有 downstream/custom 开发默认进入 `clawcodex_ext/*`，`src/*` 仅接受 thin forwarding seams 和最小适配层。"
    )
    out_lines.append("")
    out_lines.append("---")
    out_lines.append("")

    # Archived notice
    out_lines.append("## 已归档功能模块")
    out_lines.append("")
    out_lines.append("> **已实现功能已归档至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md)**")
    out_lines.append("> 以下列出的特性若标记为 ✅ 已完成，其详细设计与实现记录均已在归档文档中。")
    out_lines.append("")
    out_lines.append("---")
    out_lines.append("")

    # Write all features in consistent format
    for f in features:
        out_lines.extend(rewrite_feature(f))

    # Footer
    out_lines.append("## 附录：F-Number 快速索引")
    out_lines.append("")
    out_lines.append("| F-编号 | 特性 | 状态 | 优先级 |")
    out_lines.append("|--------|------|:----:|:------:|")
    for f in features:
        out_lines.append(
            f"| {f.f_number} | {f.title} | {f.status} {f.status_text} | {f.priority} |"
        )
    out_lines.append("")

    # Write output
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out_lines))

    print(f"\nOutput written to {output_path}")
    print(f"Total lines: {len(out_lines)}")


if __name__ == "__main__":
    main()
