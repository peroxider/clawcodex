import re
from pathlib import Path
from collections import OrderedDict

def main(ctx):
    input_path = Path(r'C:\WorkSpace\clawcodex\docs\FEATURE_PLAN.md')
    output_path = Path(r'C:\WorkSpace\clawcodex\docs\FEATURE_PLAN.md')
    archive_path = Path(r'C:\WorkSpace\clawcodex\docs\ARCHIVED_FEATURES.md')
    
    with open(input_path, 'r', encoding='utf-8') as f:
        content = f.read()
    lines = content.split('\n')

    # Parse main sections (chapters)
    chapters = []
    current_chapter = None
    for i, line in enumerate(lines):
        m = re.match(r'^(#{2})\s+(.+)', line)
        if m:
            title = m.group(2).strip()
            if current_chapter:
                current_chapter['end'] = i
            current_chapter = {'start': i, 'title': title, 'end': len(lines), 'features': []}
            chapters.append(current_chapter)
    if current_chapter:
        current_chapter['end'] = len(lines)

    # Find all feature headers within chapters
    # A feature is a section with an F-number in its header, at level 3 or 4
    features = OrderedDict()
    
    for i, line in enumerate(lines):
        if not line.startswith('###') and not line.startswith('####'):
            continue
        
        level = line.count('#')
        if level not in (3, 4):
            continue
        
        # Skip non-feature headers (like 优势 sections, TOC items, etc.)
        if '优势' in line and 'F-' in line:
            continue
        if '选型建议' in line or '实施建议' in line:
            continue
            
        # Extract F-number
        f_num = None
        title = None
        
        # Pattern 1: (F-XXX) at end
        m = re.search(r'\((F-\d+(?:\.\d+)?(?:-[A-Z]\d?)?)\s*[:：]?\s*(✅|📋|🔄|🔭|⛔)?\s*\)', line)
        if m:
            f_num = m.group(1)
            title = re.sub(r'\s*\(F-[^)]+\)\s*$', '', line).strip()
            title = re.sub(r'^#{3,4}\s*(?:\d+\.\d+(?:\.\d+)?\s+)?', '', title)
        
        # Pattern 2: F-XXX at start of title
        if not f_num:
            m = re.match(r'^#{3,4}\s+(?:\d+\.\d+(?:\.\d+)?\s+)?(F-\d+(?:\.\d+)?(?:-[A-Z]\d?)?)\s*[:：]\s*(.+)', line)
            if m:
                f_num = m.group(1)
                title = m.group(2).strip()
        
        # Pattern 3: F-XXX anywhere in title, preceded by section number
        if not f_num:
            m = re.match(r'^#{3,4}\s+(?:\d+\.\d+(?:\.\d+)?\s+)?(.+?)\s*\((F-\d+(?:\.\d+)?(?:-[A-Z]\d?)?)\)\s*$', line)
            if m:
                f_num = m.group(2)
                title = m.group(1).strip()
        
        if f_num and title:
            # Clean up title
            title = re.sub(r'\s*[（(].*?[）)]\s*$', '', title).strip()
            title = re.sub(r'^(?:\d+\.\d+(?:\.\d+)?\s+)', '', title).strip()
            
            # Determine chapter
            chapter_title = "未分类"
            for ch in chapters:
                if ch['start'] <= i < ch['end']:
                    chapter_title = ch['title']
                    break
            
            features[f_num] = {
                'f_num': f_num,
                'title': title,
                'line': i,
                'level': level,
                'chapter': chapter_title,
                'header_line': line,
            }

    # Now extract content and status for each feature
    feature_list = list(features.values())
    for idx, feat in enumerate(feature_list):
        start = feat['line']
        end = feature_list[idx+1]['line'] if idx+1 < len(feature_list) else len(lines)
        
        # But also stop at next chapter boundary or same/higher level section
        feat_lines = lines[start:end]
        
        # Truncate at next section boundary
        for j, l in enumerate(feat_lines[1:], 1):
            if l.startswith('#') and l.count('#') <= feat['level']:
                feat_lines = feat_lines[:j]
                break
        
        feat['content'] = feat_lines
        feat['status'] = extract_status(feat_lines)
        feat['priority'] = extract_priority(feat_lines)
        feat['goal'] = extract_goal(feat_lines)
        feat['archive_link'] = extract_archive_link(feat_lines)
    
    # Write analysis
    out_lines = []
    out_lines.append(f"Total chapters: {len(chapters)}")
    for ch in chapters:
        out_lines.append(f"  {ch['title']}: lines {ch['start']}-{ch['end']}")
    out_lines.append(f"\nTotal features: {len(feature_list)}")
    for feat in feature_list:
        out_lines.append(f"  {feat['f_num']}: {feat['title']} [{feat['status']['emoji']} {feat['status']['text']}] P={feat['priority']} (ch: {feat['chapter']})")
    
    out_path = Path(ctx['runDir']) / 'analysis2.txt'
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out_lines))
    
    return str(out_path)


def extract_status(lines):
    """Extract status from feature lines."""
    status_map = {
        '✅': '已完成',
        '📋': '规划中',
        '🔄': '进行中',
        '🔭': '长期规划',
        '⛔': '已被取代',
    }
    
    for line in lines[:10]:
        for emoji, text in status_map.items():
            if emoji in line:
                return {'emoji': emoji, 'text': text}
    
    # Look for text-only status
    for line in lines[:10]:
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
    for line in lines[:10]:
        m = re.search(r'优先级\s*[:：]\s*(P[0-4])', line, re.I)
        if m:
            return m.group(1).upper()
        m = re.search(r'\b(P[0-4])\b', line)
        if m:
            return m.group(1).upper()
    return "P?"


def extract_goal(lines):
    for line in lines[:10]:
        m = re.search(r'(?:^|\s)目标\s*[:：]\s*(.+)', line)
        if m:
            return m.group(1).strip()
        m = re.search(r'\*\*目标\*\*[:：]?\s*(.+)', line)
        if m:
            return m.group(1).strip()
    return ""


def extract_archive_link(lines):
    for line in lines:
        if 'ARCHIVED_FEATURES.md' in line or 'ARCHIVED_PROGRESS.md' in line:
            return line.strip()
    return ""


main
