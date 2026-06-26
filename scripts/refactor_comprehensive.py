import re
from pathlib import Path
from collections import OrderedDict


def main(ctx):
    input_path = Path(r'C:\WorkSpace\clawcodex\docs\FEATURE_PLAN.md')
    output_path = Path(r'C:\WorkSpace\clawcodex\docs\FEATURE_PLAN.md')
    
    with open(input_path, 'r', encoding='utf-8') as f:
        content = f.read()
    lines = content.split('\n')

    # Parse main chapters (## sections)
    chapters = []
    for i, line in enumerate(lines):
        m = re.match(r'^(#{2})\s+(.+)', line)
        if m:
            chapters.append({'start': i, 'title': m.group(2).strip(), 'end': len(lines)})
    for i in range(len(chapters) - 1):
        chapters[i]['end'] = chapters[i + 1]['start']

    # Find all feature headers (### or #### with F-number)
    features = []
    skip_headers = {'选型建议', '实施建议', '详细设计', '依赖与协同', '验收标准', '风险与约束', '核心设计', '改造点清单'}
    
    for i, line in enumerate(lines):
        if not line.startswith('###') and not line.startswith('####'):
            continue
        level = line.count('#')
        if level not in (3, 4):
            continue
        
        # Skip non-feature headers
        skip = False
        for sk in skip_headers:
            if sk in line and 'F-' not in line.split(sk)[0]:
                skip = True
                break
        if skip:
            continue
        if '优势' in line and 'F-' in line:
            continue
            
        f_num = None
        title = None
        
        # Pattern 1: (F-XXX status) at end with Chinese or ASCII parens
        m = re.search(r'[（(](F-\d+(?:\.\d+)?(?:-[A-Z]\d?)?)\s*[:：]?\s*(✅|📋|🔄|🔭|⛔)?\s*[)）]', line)
        if m:
            f_num = m.group(1)
            title = re.sub(r'\s*[（(]F-[^）)]+[）)]\s*$', '', line).strip()
            title = re.sub(r'^#{3,4}\s*(?:\d+\.\d+(?:\.\d+)?\s+)?', '', title)
        
        # Pattern 2: F-XXX: title
        if not f_num:
            m = re.match(r'^#{3,4}\s+(?:\d+\.\d+(?:\.\d+)?\s+)?(F-\d+(?:\.\d+)?(?:-[A-Z]\d?)?)\s*[:：]\s*(.+)', line)
            if m:
                f_num = m.group(1)
                title = m.group(2).strip()
        
        # Pattern 3: F-XXX anywhere in header text
        if not f_num:
            text = re.sub(r'^#{3,4}\s*(?:\d+\.\d+(?:\.\d+)?\s+)?', '', line).strip()
            m = re.search(r'\b(F-\d+(?:\.\d+)?(?:-[A-Z]\d?)?)\b', text)
            if m:
                f_num = m.group(1)
                title = text.replace(f_num, '').strip().strip(':：').strip()
                # Remove trailing parens content if any
                title = re.sub(r'\s*[（(].*?[）)]\s*$', '', title).strip()
        
        if f_num and title and len(title) > 2:
            # Determine chapter
            chapter_title = "未分类"
            for ch in chapters:
                if ch['start'] <= i < ch['end']:
                    chapter_title = ch['title']
                    break
            
            features.append({
                'f_num': f_num,
                'title': title,
                'line': i,
                'level': level,
                'chapter': chapter_title,
            })

    # Extract content for each feature
    for idx, feat in enumerate(features):
        start = feat['line']
        end = features[idx + 1]['line'] if idx + 1 < len(features) else len(lines)
        
        feat_lines = lines[start:end]
        
        # Truncate at next section boundary of same or higher level
        for j, l in enumerate(feat_lines[1:], 1):
            if l.startswith('#') and l.count('#') <= feat['level']:
                feat_lines = feat_lines[:j]
                break
        
        feat['content'] = feat_lines
        feat['status'] = extract_status(feat_lines)
        feat['priority'] = extract_priority(feat_lines)
        feat['goal'] = extract_goal(feat_lines)
        feat['archive_link'] = extract_archive_link(feat_lines)
        feat['content_length'] = len(feat_lines)
        feat['key_files'] = extract_key_files(feat_lines)
        feat['sub_features'] = extract_sub_features(feat_lines)
    
    # Write analysis to verify parsing
    out_lines = []
    out_lines.append(f"Total features found: {len(features)}")
    for feat in features:
        out_lines.append(f"  {feat['f_num']}: {feat['title']} [{feat['status']['emoji']} {feat['status']['text']}] P={feat['priority']} len={feat['content_length']} ch={feat['chapter']}")
    
    out_path = Path(ctx['runDir']) / 'analysis3.txt'
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out_lines))
    
    # Now build the refactored document
    refactored = build_refactored_document(chapters, features)
    
    refactored_path = Path(ctx['runDir']) / 'FEATURE_PLAN_REFACTORED.md'
    with open(refactored_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(refactored))
    
    return str(refactored_path)


def extract_status(lines):
    status_map = {
        '✅': '已完成',
        '📋': '规划中',
        '🔄': '进行中',
        '🔭': '长期规划',
        '⛔': '已被取代',
    }
    for line in lines[:20]:
        for emoji, text in status_map.items():
            if emoji in line:
                return {'emoji': emoji, 'text': text}
    for line in lines[:20]:
        if '已完成' in line or '完成' in line:
            return {'emoji': '✅', 'text': '已完成'}
        if '进行中' in line or '部分完成' in line:
            return {'emoji': '🔄', 'text': '进行中'}
        if '规划中' in line or '待开始' in line or '待实现' in line:
            return {'emoji': '📋', 'text': '规划中'}
        if '长期规划' in line:
            return {'emoji': '🔭', 'text': '长期规划'}
    return {'emoji': '📋', 'text': '规划中'}


def extract_priority(lines):
    for line in lines[:20]:
        m = re.search(r'优先级\s*[:：]\s*(P[0-4])', line, re.I)
        if m:
            return m.group(1).upper()
        m = re.search(r'\b(P[0-4])\b', line)
        if m:
            return m.group(1).upper()
    return "P?"


def extract_goal(lines):
    for line in lines[:15]:
        m = re.search(r'(?:^|\s)目标\s*[:：]\s*(.+)', line)
        if m:
            return m.group(1).strip()
        m = re.search(r'\*\*目标\*\*[:：]?\s*(.+)', line)
        if m:
            return m.group(1).strip()
        m = re.search(r'目标[:：]\s*(.+)', line)
        if m:
            return m.group(1).strip()
    return ""


def extract_archive_link(lines):
    for line in lines:
        if 'ARCHIVED_FEATURES.md' in line or 'ARCHIVED_PROGRESS.md' in line:
            return line.strip()
    return ""


def extract_key_files(lines):
    files = []
    for line in lines:
        for match in re.finditer(r'`([^`]+\.(?:py|ts|json|yaml|yml|md))`', line):
            path = match.group(1)
            if path not in [f[0] for f in files] and len(path) < 100 and not path.endswith('.md'):
                files.append((path, "实现文件"))
        if len(files) >= 10:
            break
    return files


def extract_sub_features(lines):
    subs = []
    for line in lines:
        line = line.strip()
        # Match patterns like P108-A, P102-A, etc.
        m = re.match(r'^[-*]\s*(P\d+[-_][A-Z]\d?)\s*[—:]\s*(.+)', line)
        if m:
            subs.append((m.group(1), m.group(2)))
        # Match numbered items
        elif re.match(r'^\d+\.\s+', line) and len(line) < 120 and not line.startswith('```') and not line.startswith('|'):
            text = re.sub(r'^\d+\.\s*', '', line)
            if text and len(text) > 10:
                subs.append((f"", text))
        if len(subs) >= 10:
            break
    return subs


def build_refactored_document(chapters, features):
    out = []
    
    # Header
    out.append("# ClawCodex 特性规划与设计文档")
    out.append("")
    out.append("> 文档路径: `docs/FEATURE_PLAN.md`")
    out.append("> 版本: v4.0（格式重构版）")
    out.append("> 更新日期: 2026-06-23")
    out.append("")
    out.append("> **说明**: 本文档所有特性采用统一 F-Number 编号体系。每个特性以 `F-XXX` 标识，状态使用统一表情符号：")
    out.append("> - ✅ 已完成 — 已实现并归档")
    out.append("> - 🔄 进行中 — 部分实现，尚有剩余工作")
    out.append("> - 📋 规划中 — 设计完成，待开发")
    out.append("> - 🔭 长期规划 — 方向性定义，未进入详细设计")
    out.append("> - ⛔ 已被取代 — 被其他特性合并或取代")
    out.append("")
    out.append("---")
    out.append("")
    
    # Filter out non-chapter sections for TOC
    real_chapters = [ch for ch in chapters if ch['title'] not in {
        '目录', '摘要', '高评分候选特性', '破坏性变更预警', '分类分布'
    }]
    
    # TOC
    out.append("## 目录")
    out.append("")
    for ch in real_chapters:
        ch_anchor = ch['title'].replace(' ', '-').replace('（', '').replace('）', '').replace('/', '')
        out.append(f"- [{ch['title']}](#{ch_anchor})")
        ch_feats = [f for f in features if f['chapter'] == ch['title']]
        for feat in ch_feats:
            feat_anchor = f"f-{feat['f_num'].lower().replace('.', '-')}"
            out.append(f"  - [{feat['f_num']} {feat['title']}](#{feat_anchor})")
    out.append("")
    out.append("---")
    out.append("")
    
    # Project overview
    out.append("## 项目概述与边界约束")
    out.append("")
    out.append("### 1.1 项目定位")
    out.append("")
    out.append("ClawCodex 是 Anthropic Claude Code 的 Python 移植版，同时扩展多 Provider 支持，目标成为功能完整的 AI Agent CLI 工具。")
    out.append("")
    out.append("### 1.2 当前架构（三层解耦）")
    out.append("")
    out.append("```")
    out.append("src/")
    out.append("├── upstream/            # Layer 1: 上游快照")
    out.append("├── capabilities/        # Layer 2: 协议接口定义")
    out.append("├── orchestrator/        # Layer 3: 自主模式编排")
    out.append("├── api/                 # Layer 3: 公共 Python API")
    out.append("└── ...                  # 其余上游原有模块")
    out.append("```")
    out.append("")
    out.append("**核心约束**: 所有 downstream/custom 开发默认进入 `clawcodex_ext/*`，`src/*` 仅接受 thin forwarding seams 和最小适配层。")
    out.append("")
    out.append("---")
    out.append("")
    
    # Archived notice
    out.append("## 已归档功能模块")
    out.append("")
    out.append("> **已实现功能已归档至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md)**")
    out.append("> 标记为 ✅ 的详细设计与实现记录均已在归档文档中。")
    out.append("")
    out.append("---")
    out.append("")
    
    # Write each chapter with its features
    for ch in real_chapters:
        if ch['title'] in {'项目概述与边界约束', '已归档功能模块'}:
            continue
        
        out.append(f"## {ch['title']}")
        out.append("")
        
        ch_feats = [f for f in features if f['chapter'] == ch['title']]
        for feat in ch_feats:
            out.extend(rewrite_feature(feat))
        
        out.append("")
    
    # Appendix
    out.append("## 附录：F-Number 快速索引")
    out.append("")
    out.append("| F-编号 | 特性 | 状态 | 优先级 |")
    out.append("|--------|------|:----:|:------:|")
    for feat in features:
        out.append(f"| {feat['f_num']} | {feat['title']} | {feat['status']['emoji']} {feat['status']['text']} | {feat['priority']} |")
    out.append("")
    
    return out


def rewrite_feature(feat):
    out = []
    
    # Header with F-number and status emoji
    out.append(f"### {feat['f_num']} {feat['title']} {feat['status']['emoji']}")
    out.append("")
    
    # Attribute table
    out.append("| 属性 | 值 |")
    out.append("|------|-----|")
    out.append(f"| 状态 | {feat['status']['emoji']} {feat['status']['text']} |")
    if feat['priority'] != 'P?':
        out.append(f"| 优先级 | {feat['priority']} |")
    if feat['goal']:
        out.append(f"| 目标 | {feat['goal']} |")
    out.append("")
    
    # Content based on status
    if feat['status']['emoji'] == '✅':
        out.extend(rewrite_completed(feat))
    elif feat['status']['emoji'] == '⛔':
        out.extend(rewrite_superseded(feat))
    elif feat['status']['emoji'] == '🔭':
        out.extend(rewrite_longterm(feat))
    elif feat['status']['emoji'] == '🔄':
        out.extend(rewrite_in_progress(feat))
    elif feat['status']['emoji'] == '📋':
        out.extend(rewrite_planning(feat))
    
    out.append("---")
    out.append("")
    return out


def rewrite_completed(feat):
    out = []
    out.append("#### 概述")
    
    # Extract first meaningful sentence
    desc = extract_first_paragraph(feat['content'])
    if desc:
        out.append(desc)
    else:
        out.append(f"{feat['title']} 已实现并归档。")
    out.append("")
    
    if feat['archive_link']:
        link = feat['archive_link'].lstrip('>').strip()
        out.append(f"> {link}")
        out.append("")
    
    # Key files for completed features
    if feat['key_files']:
        out.append("#### 关键文件")
        out.append("| 文件 | 说明 |")
        out.append("|------|------|")
        for path, desc in feat['key_files'][:6]:
            out.append(f"| `{path}` | {desc} |")
        out.append("")
    
    return out


def rewrite_superseded(feat):
    out = []
    out.append("#### 概述")
    out.append(f"{feat['title']} 已被其他特性取代，不再作为独立特性实施。")
    out.append("")
    
    # Extract replacement info
    for line in feat['content']:
        text = line.strip().lstrip('>').strip()
        if text and ('已被' in text or '取代' in text or '吸收' in text or '并入' in text) and not text.startswith('#') and not text.startswith('|'):
            out.append(text)
            break
    out.append("")
    return out


def rewrite_longterm(feat):
    out = []
    out.append("#### 概述")
    desc = extract_first_paragraph(feat['content'])
    if desc:
        out.append(desc)
    else:
        out.append(f"{feat['title']} 为长期方向性规划，尚未进入详细设计阶段。")
    out.append("")
    return out


def rewrite_in_progress(feat):
    out = []
    out.append("#### 概述")
    desc = extract_first_paragraph(feat['content'])
    if desc:
        out.append(desc)
    else:
        out.append(f"{feat['title']} 正在实现中。")
    out.append("")
    
    out.append("#### 实现状态")
    
    # Extract done items
    done_items = []
    for line in feat['content']:
        text = line.strip()
        if '✅' in text and len(text) < 150 and not text.startswith('```') and not text.startswith('|'):
            t = re.sub(r'.*✅\s*', '', text).strip()
            if t and t not in done_items:
                done_items.append(f"- ✅ {t}")
        elif '已完成' in text and len(text) < 150 and not text.startswith('#') and not text.startswith('|') and not text.startswith('```'):
            if text not in done_items:
                done_items.append(f"- {text}")
        if len(done_items) >= 6:
            break
    if done_items:
        out.extend(done_items[:6])
        out.append("")
    
    # Extract remaining items
    remain_items = []
    for line in feat['content']:
        text = line.strip()
        if ('待' in text or '剩余' in text or 'TODO' in text or '待补' in text or '缺' in text or '未' in text) and len(text) < 150 and not text.startswith('#') and not text.startswith('|') and not text.startswith('```'):
            if text not in remain_items and not text.startswith('- ✅'):
                remain_items.append(f"- 📋 {text}")
        if len(remain_items) >= 6:
            break
    if remain_items:
        out.extend(remain_items[:6])
        out.append("")
    
    if feat['key_files']:
        out.append("#### 关键文件")
        out.append("| 文件 | 说明 |")
        out.append("|------|------|")
        for path, desc in feat['key_files'][:6]:
            out.append(f"| `{path}` | {desc} |")
        out.append("")
    
    return out


def rewrite_planning(feat):
    out = []
    out.append("#### 概述")
    desc = extract_first_paragraph(feat['content'])
    if desc:
        out.append(desc)
    else:
        out.append(f"{feat['title']} 处于设计阶段。")
    out.append("")
    
    # Sub-features
    if feat['sub_features']:
        out.append("#### 设计要点")
        for sf in feat['sub_features'][:8]:
            if sf[0]:
                out.append(f"- **{sf[0]}**: {sf[1]}")
            else:
                out.append(f"- {sf[1]}")
        out.append("")
    else:
        # Extract any bullet points
        bullets = []
        for line in feat['content']:
            text = line.strip()
            if text.startswith('- ') or text.startswith('* '):
                if len(text) < 120 and not text.startswith('```') and not text.startswith('|'):
                    bullets.append(text)
                if len(bullets) >= 5:
                    break
        if bullets:
            out.append("#### 设计要点")
            out.extend(bullets[:5])
            out.append("")
    
    if feat['key_files']:
        out.append("#### 关键文件")
        out.append("| 文件 | 说明 |")
        out.append("|------|------|")
        for path, desc in feat['key_files'][:6]:
            out.append(f"| `{path}` | {desc} |")
        out.append("")
    
    return out


def extract_first_paragraph(lines):
    """Extract first meaningful paragraph."""
    for line in lines:
        text = line.strip()
        if text and not text.startswith('#') and not text.startswith('>') and not text.startswith('|') and not text.startswith('```') and not text.startswith('`') and not text.startswith('**') and len(text) > 15:
            # Clean up
            text = text.lstrip('*').strip()
            if text:
                return text
    return ""


main
