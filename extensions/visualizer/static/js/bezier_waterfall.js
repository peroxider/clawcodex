/**
 * ClawCodex Visualizer — Bezier Waterfall View
 *
 * P4 — EventDetailDrawer (right-side slide-in, mirrors the waterfall
 *   chart's .turn-drawer pattern) on top of P3 zoom/pan.
 *   Renders the 8-category timeline with a sticky time axis, ported
 *   from clawcodex_sessions_analysis (Next.js). Clicking an event
 *   bar opens a side drawer with one of 5 body types.
 *
 * Scope of this file (P4):
 *   - Fetch /api/viz/multi-session?sessions=... and render 8 category bars
 *   - Sticky time axis with buildTicks() / tickLabel() (zoom-aware)
 *   - Min 2.5 px bar width for `durationUnrecorded`
 *   - ts_unrecorded bars get a dashed / dimmed style
 *   - 1×-40× cursor-anchored wheel zoom
 *   - alt+wheel horizontal pan (deltaX + deltaY)
 *   - 4 px left-button drag-to-pan, document-level pointer tracking
 *   - userSelect=none while panning
 *   - ResizeObserver on the scroll container; re-render on width change
 *   - ref-mirror pattern (zoomRef / containerWRef)
 *   - destroy() tears down all listeners + observers + cancels rAF
 *   - EventDetailDrawer: pre-built #bezier-drawer markup, .open toggle
 *       · 5 body types: tool / tool-result / llm / user / system
 *       · click vs pan differentiated by panState.moved (no separate
 *         click handler / suppress flag needed)
 *       · Esc key closes; X button closes
 *       · Sticky header (category color dot + label + category pill +
 *         error pill)
 *       · Time section: relative / duration / absolute
 *         (duration: 未记录 / 估算 / real ms — fixes Next.js
 *          event-detail-panel.tsx:84-108 missing "估算" label)
 *       · CodeBlock: 12-16 line preview + expand/collapse + copy
 *         (navigator.clipboard.writeText + execCommand fallback)
 *
 * Mapping (frontend-only — backend keeps OperationCategory enum):
 *   backend              -> bezier
 *   read                 -> read
 *   execute              -> execute
 *   write                -> write
 *   orchestrate          -> orchestrate
 *   llm_text             -> llm
 *   turn / background    -> other
 *   other                -> other
 *
 *   user_role=user       -> user    (overrides backend category)
 *   user_role=system     -> system  (overrides backend category)
 *   user_role=assistant  -> llm     (assistant text spans)
 */

const BezierWaterfall = (function() {
    'use strict';

    // ---- 8 bezier categories ----
    const BEZIER_CATEGORIES = ['read', 'execute', 'write', 'orchestrate', 'llm', 'user', 'system', 'other'];

    // Default category colours. The live values are read from
    // :root --bezier-cat-* CSS variables at module init (P7) so
    // theme changes propagate without restarting the view. The
    // hardcoded map below is the fallback used when the document
    // has no stylesheet (e.g. in Node smoke tests) or when a CSS
    // var resolves to an empty string.
    const CATEGORY_COLORS = {
        read:         '#3fb950',
        execute:      '#58a6ff',
        write:        '#d29922',
        orchestrate:  '#f778ba',
        llm:          '#79c0ff',
        user:         '#bc8cff',
        system:       '#8b949e',
        other:        '#6e7681',
    };

    // CSS variable name → fallback colour. Kept in one place so the
    // smoke test can verify that every category has a token + a
    // fallback (no silent drift).
    const CSS_VAR_FOR_CATEGORY = {
        read:        '--bezier-cat-read',
        execute:     '--bezier-cat-execute',
        write:       '--bezier-cat-write',
        orchestrate: '--bezier-cat-orchestrate',
        llm:         '--bezier-cat-llm',
        user:        '--bezier-cat-user',
        system:      '--bezier-cat-system',
        other:       '--bezier-cat-other',
    };

    // Read the live category colours from the document's :root
    // variables. Falls back to the hardcoded map when the document
    // isn't ready (Node smoke tests, pre-init calls). Returns a new
    // object so callers don't accidentally mutate the fallback.
    function readCategoryColors(doc) {
        const out = {};
        const probe = (doc && doc.documentElement)
            ? doc.documentElement
            : null;
        for (const cat of BEZIER_CATEGORIES) {
            let v = '';
            if (probe && typeof doc.defaultView !== 'undefined'
                && doc.defaultView
                && typeof doc.defaultView.getComputedStyle === 'function') {
                try {
                    v = doc.defaultView.getComputedStyle(probe)
                        .getPropertyValue(CSS_VAR_FOR_CATEGORY[cat] || '')
                        .trim();
                } catch (_) { v = ''; }
            }
            out[cat] = v || CATEGORY_COLORS[cat] || '#6e7681';
        }
        return out;
    }

    const CATEGORY_LABELS = {
        read:         '读取',
        execute:      '执行',
        write:        '写入',
        orchestrate:  '编排',
        llm:          '推理',
        user:         '用户',
        system:       '系统',
        other:        '其他',
    };

    // Visual: minimum visible bar width when no real duration was
    // recorded. Mirrors the Next.js `min-w-[2.5px]` constant.
    const MIN_BAR_PX = 2.5;
    // Minimum canvas width when the container hasn't been measured yet
    // (initial render before ResizeObserver fires). 100 px matches
    // Next.js's `Math.max(100, ...)` floor.
    const MIN_CANVAS_PX = 100;
    // ---- P3 zoom constants (ported from session-analyzer.tsx:22-24) ----
    const ZOOM_MIN  = 1;
    const ZOOM_MAX  = 40;
    const ZOOM_STEP = 0.12;  // per wheel tick (multiplicative)
    // Pan threshold in CSS pixels — drags below this are treated as
    // clicks and don't engage the pan. Matches session-analyzer.tsx:105.
    const PAN_THRESHOLD_PX = 4;
    // ---- P5b narrowed sub-agent track layout ----
    // Minimum fraction of the canvas width that a sub-agent track
    // occupies. Ported from workflow-panel.tsx:46 (MIN_LANE_FRAC = 0.12).
    // Narrow agent windows (e.g. a 3-second review in a 5-minute session)
    // are widened to this fraction so the track stays visible.
    const MIN_LANE_FRAC = 0.12;
    // CodeBlock default preview limits. LLM 12, others 16 — match
    // the Next.js <CodeBlock maxLines={...}> choices.
    const CODEBLOCK_MAX_LINES_LLM  = 12;
    const CODEBLOCK_MAX_LINES_OTHER = 16;
    // ---- P5 connector / row-layout constants ----
    // Row dimensions (must match the .bezier-row CSS). One unit
    // represents the height of a parent session row or a sub-agent
    // row. The bezier curve endpoints anchor to the centre of each
    // row's track (y = HEADER_H + TRACK_H/2 inside a row unit).
    const ROW_H        = 48;
    const HEADER_H     = 22;
    const TRACK_H      = 22;
    const SUBAGENT_INDENT_PX = 18;
    // Connector stroke widths — selected / hovered / default.
    // Mirrors the Next.js session-analyzer.tsx:238 values.
    const CONNECTOR_STROKE_DEFAULT  = 1.2;
    const CONNECTOR_STROKE_HOVER    = 2.0;
    const CONNECTOR_STROKE_SELECTED = 2.4;
    // Connector opacities — base (per role) / hover / selected.
    // Spawn curves are subtler than merge curves so the parent's
    // main lane stays the dominant signal; matches workflow-panel.tsx:705,725.
    const CONNECTOR_OPACITY_SPAWN    = 0.30;
    const CONNECTOR_OPACITY_MERGE    = 0.48;
    const CONNECTOR_OPACITY_HOVER    = 0.85;
    const CONNECTOR_OPACITY_SELECTED = 1.0;
    // Invisible hit-area stroke (px). 12px makes thin curves
    // clickable on mouse hover; matches workflow-panel.tsx:253.
    const CONNECTOR_HITAREA_STROKE = 12;
    // Glow path — only painted when the curve is selected. Wider
    // stroke + low opacity gives a halo effect.
    const CONNECTOR_GLOW_STROKE  = 8;
    const CONNECTOR_GLOW_OPACITY = 0.25;

    // ----------------------------------------------------------------
    // Helpers (vanilla ports of the Next.js lib/format.ts + categories.ts)
    // ----------------------------------------------------------------

    function bezierCategoryOf(bar) {
        if (bar.userRole === 'user') return 'user';
        if (bar.userRole === 'system') return 'system';
        if (bar.userRole === 'assistant') return 'llm';
        const map = {
            read:        'read',
            execute:     'execute',
            write:       'write',
            orchestrate: 'orchestrate',
            llm_text:    'llm',
            turn:        'other',
            background:  'other',
            other:       'other',
        };
        return map[bar.category] || 'other';
    }

    function formatClock(ms) {
        const totalSec = Math.round((ms || 0) / 1000);
        const m = Math.floor(totalSec / 60);
        const s = totalSec % 60;
        return m + ':' + String(s).padStart(2, '0');
    }

    // Mirror of clawcodex_sessions_analysis/lib/format.ts:formatTokens.
    // Used by the sub-agent label to render the muted token size badge
    // (workflow-panel.tsx:639-643). Returns "—" for falsy values so the
    // label stays readable when stats are missing.
    function formatTokens(n) {
        if (!n) return '—';
        if (n >= 1000) return Math.round(n / 1000) + 'K';
        return String(n);
    }

    function buildTicks(durationMs, zoom) {
        zoom = zoom || 1;
        const visibleMs = durationMs / zoom;
        const visibleMin = visibleMs / 60000;

        let stepMin;
        if (visibleMin > 80)       stepMin = 20;
        else if (visibleMin > 40)  stepMin = 10;
        else if (visibleMin > 12)  stepMin = 5;
        else if (visibleMin > 6)   stepMin = 2;
        else if (visibleMin > 2)   stepMin = 1;
        else if (visibleMin > 0.8) stepMin = 0.5;
        else if (visibleMin > 0.3) stepMin = 0.25;
        else                       stepMin = 0.1;

        const totalMin = durationMs / 60000;
        const ticks = [];
        for (let m = 0; m <= totalMin + stepMin * 0.01; m += stepMin) {
            ticks.push(Math.round(m * 60000));
        }
        return ticks;
    }

    function tickLabel(ms) {
        const totalSec = Math.round((ms || 0) / 1000);
        const m = Math.floor(totalSec / 60);
        const s = totalSec % 60;
        if (s === 0) return m + '分钟';
        return m + ':' + String(s).padStart(2, '0');
    }

    function xToPx(seconds, canvasWidth, durationSec) {
        if (durationSec <= 0) return 0;
        return (seconds / durationSec) * canvasWidth;
    }

    // Format a relative time (seconds) for the panel's "相对时间" row.
    // Mirrors formatClock but accepts seconds.
    function formatRelSec(sec) {
        if (sec == null || isNaN(sec)) return '—';
        return formatClock(sec * 1000);
    }

    // Format an ISO timestamp as the locale short form (used for the
    // "绝对时间" row). Falls back to "未记录" when null / unparseable.
    function formatAbsTime(iso) {
        if (!iso) return '';
        const d = new Date(iso);
        if (isNaN(d.getTime())) return '';
        const pad = (n) => String(n).padStart(2, '0');
        return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
            + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
    }

    // ----------------------------------------------------------------
    // DOM helpers for the detail panel (Section / Row / CodeBlock).
    // Vanilla port of event-detail-panel.tsx:307-433.
    // ----------------------------------------------------------------

    function el(tag, className, text) {
        const e = document.createElement(tag);
        if (className) e.className = className;
        if (text != null) e.textContent = text;
        return e;
    }

    function buildSection(title) {
        // Use the waterfall's .turn-drawer-section so the bezier drawer
        // inherits the same spacing, borders, and section titles. The
        // section content is a generic div (CodeBlock appends into it
        // directly; appendRow nests a <dl>).
        const section = el('section', 'turn-drawer-section');
        if (title) section.appendChild(el('h4', null, title));
        const content = el('div', 'turn-drawer-section-content');
        section.appendChild(content);
        return { section, content };
    }

    function appendRow(content, label, value, opts) {
        // Match the waterfall's <dl><dt><dd> shape so rows pick up the
        // shared .turn-drawer-section dl/dt/dd styles. Optional flag
        // classes are scoped to the bezier drawer (no waterfall collision).
        opts = opts || {};
        const dl = el('dl');
        const dt = el('dt', null, label);
        const dd = el('dd', null, (value == null || value === '') ? '—' : String(value));
        if (opts.mono)  dd.classList.add('bezier-drawer-mono');
        if (opts.muted) dd.classList.add('bezier-drawer-muted');
        if (opts.error) dd.classList.add('bezier-drawer-error-text');
        dl.appendChild(dt);
        dl.appendChild(dd);
        content.appendChild(dl);
    }

    function appendCodeBlock(content, text, maxLines) {
        const fullText = (text == null) ? '' : String(text);
        if (!fullText) {
            const empty = el('div', 'bezier-event-empty', '（无内容）');
            content.appendChild(empty);
            return;
        }
        const lines = fullText.split('\n');
        const hasMore = (maxLines !== undefined) && lines.length > maxLines;
        const shown = hasMore ? lines.slice(0, maxLines).join('\n') : fullText;
        const wrap = el('div', 'bezier-event-code-wrap');
        const pre = el('pre', 'bezier-event-code', shown);
        wrap.appendChild(pre);
        // Copy button (matches event-detail-panel.tsx:356-408)
        const copyBtn = el('button', 'bezier-event-copy');
        copyBtn.type = 'button';
        copyBtn.setAttribute('aria-label', '复制内容');
        copyBtn.appendChild(el('span', 'bezier-event-copy-label', 'COPY'));
        copyBtn.addEventListener('click', async () => {
            const ok = await copyToClipboard(fullText);
            const label = copyBtn.querySelector('.bezier-event-copy-label');
            if (label) label.textContent = ok ? '已复制' : '失败';
            setTimeout(() => {
                if (label) label.textContent = 'COPY';
            }, 1500);
        });
        wrap.appendChild(copyBtn);
        content.appendChild(wrap);
        if (hasMore) {
            const btn = el('button', 'bezier-event-expand');
            btn.type = 'button';
            let expanded = false;
            const total = lines.length;
            const updateLabel = () => {
                btn.textContent = expanded
                    ? '收起（共 ' + total + ' 行）'
                    : '展开剩余 ' + (total - maxLines) + ' 行（共 ' + total + ' 行）';
            };
            updateLabel();
            btn.addEventListener('click', () => {
                expanded = !expanded;
                pre.textContent = expanded ? fullText : lines.slice(0, maxLines).join('\n');
                updateLabel();
            });
            content.appendChild(btn);
        }
    }

    async function copyToClipboard(text) {
        try {
            if (navigator && navigator.clipboard && navigator.clipboard.writeText) {
                await navigator.clipboard.writeText(text);
                return true;
            }
        } catch (_) { /* fall through to legacy */ }
        // Legacy fallback for non-secure contexts (matches the
        // event-detail-panel.tsx:362-369 path).
        try {
            const ta = document.createElement('textarea');
            ta.value = text;
            ta.style.position = 'fixed';
            ta.style.opacity = '0';
            document.body.appendChild(ta);
            ta.select();
            const ok = document.execCommand('copy');
            document.body.removeChild(ta);
            return !!ok;
        } catch (e) {
            return false;
        }
    }

    // ----------------------------------------------------------------
    // BezierWaterfall class
    // ----------------------------------------------------------------

    class BezierWaterfallImpl {
        constructor(containerId, options) {
            this.containerId = containerId;
            this.options = options || {};
            this.sessionIds = [];
            this.data = null;
            // P7 — read the live category colours from the document's
            // :root --bezier-cat-* variables. Falls back to the
            // hardcoded CATEGORY_COLORS map when document is missing
            // (e.g. pre-init smoke tests).
            this._categoryColors = (typeof document !== 'undefined')
                ? readCategoryColors(document)
                : Object.assign({}, CATEGORY_COLORS);
            // Computed bounds (filled by _computeBounds)
            this.baseTime = 0;
            this.durationSec = 60;
            this.canvasWidth = 0;
            this.scaleX = 0;
            this.container = null;
            this.scrollEl = null;
            // ---- P3 zoom / pan state ----
            this.zoom = 1;
            this.containerW = 0;
            this.panState = null;
            this.isPanning = false;
            this.rafId = null;
            this.zoomRef = { current: 1 };
            this.containerWRef = { current: 0 };
            // ---- P4 detail drawer state ----
            this.selectedEvent = null;       // currently-open tick (or null)
            this._drawerRefs = null;         // {drawer, body, title, catDot, pills, closeBtn}
            this._drawerCloseWired = false;  // bound exactly once per instance
            this._tickByBarId = new Map();   // barId → tick, for click resolution
            // ---- P5 connector state ----
            // activeMap is rebuilt on every _render() and tracks the
            // current selectedConnector + hoveredConnector refs. The
            // SVG path elements carry the same key strings so
            // _buildActiveMap() and the path data stay in sync.
            this.selectedConnector = null;   // {sessionId, agentId, role} | null
            this.hoveredConnector  = null;   // {sessionId, agentId, role} | null
            this._activeMap        = new Map();   // key -> "selected" | "hovered"
            this._connectorSvgEl   = null;        // SVG root, for tooltip positioning
            this._connectorTipEl   = null;        // HTML tooltip sibling
            this._rowIndexById     = new Map();   // id (session or agent) -> flat row index
            this._agentById        = new Map();   // agentId -> agent row from data.agents
            this._agentLayoutCache = null;            // Map<sessionId, layout[]> | null
            // Cleanup bookkeeping.
            this._listeners = [];
            this._observers = [];
        }

        async init(sessionIds) {
            this.sessionIds = sessionIds;
            this.container = document.getElementById(this.containerId);
            if (!this.container) {
                console.error('[bezier] container not found:', this.containerId);
                return;
            }
            this.scrollEl = this.container;

            const url = '/api/viz/multi-session?sessions='
                + encodeURIComponent((sessionIds || []).join(','));
            this.container.innerHTML = '<div class="bezier-loading">'
                + '<span class="bezier-spinner"></span> 加载贝塞尔视图…</div>';
            try {
                const resp = await fetch(url, { headers: { 'Accept': 'application/json' } });
                if (!resp.ok) {
                    const detail = await resp.text().catch(() => '');
                    this._renderError('HTTP ' + resp.status + (detail ? ' · ' + detail : ''));
                    return;
                }
                this.data = await resp.json();
            } catch (e) {
                this._renderError(String((e && e.message) || e));
                return;
            }

            this._computeBounds();
            this._render();
            this._attachInteractions();
        }

        // ---- internal: bounds + render ----

        _computeBounds() {
            const tr = (this.data && this.data.timeRange) || {};
            const min = (typeof tr.min === 'number') ? tr.min : 0;
            const max = (typeof tr.max === 'number') ? tr.max : 0;
            this.baseTime = min;
            this.durationSec = Math.max(1, max - min);
            this.canvasWidth = Math.max(MIN_CANVAS_PX, this.containerW * this.zoom);
            this.scaleX = this.canvasWidth / this.durationSec;
        }

        _render() {
            if (!this.container) return;
            this.container.innerHTML = '';
            // Reset tick lookup; the click path uses this Map.
            this._tickByBarId = new Map();
            // Reset sub-agent layout cache; rebuilt by _getAgentLayout.
            this._agentLayoutCache = null;
            // Build the flat row index for the P5 connector layer.
            // Done up front so the sub-agent row renderer and the SVG
            // path endpoints see the same row numbers.
            this._buildRowIndex();

            const panel = el('div', 'bezier-waterfall');
            panel.style.width = this.canvasWidth + 'px';
            panel.style.position = 'relative'; // anchor the absolute-positioned SVG

            panel.appendChild(this._renderTimeAxis());

            const body = el('div', 'bezier-body');
            const sessions = (this.data && this.data.sessions) || [];
            const agentByParent = new Map();
            const agents = (this.data && this.data.agents) || [];
            for (const a of agents) {
                if (!agentByParent.has(a.parentSessionId)) {
                    agentByParent.set(a.parentSessionId, []);
                }
                agentByParent.get(a.parentSessionId).push(a);
            }
            if (sessions.length === 0) {
                body.appendChild(el('div', 'bezier-empty', '无 session 数据'));
            } else {
                sessions.forEach((s) => {
                    body.appendChild(this._renderSessionRow(s));
                    const subList = agentByParent.get(s.id) || [];
                    for (const a of subList) {
                        body.appendChild(this._renderSubAgentRow(a));
                    }
                });
            }
            panel.appendChild(body);

            // P5 — bezier connector layer (absolute-positioned SVG
            // over the body). Rendered AFTER rows so it paints on
            // top; pointer-events: none on the root preserves bar
            // clickability, while the hit-area / focusable paths
            // re-enable stroke pointer-events.
            const connectorSvg = this._renderConnectors();
            if (connectorSvg) panel.appendChild(connectorSvg);

            // P5 — connector tooltip (sibling of SVG, HTML <div>).
            const tip = this._renderConnectorTooltip();
            if (tip) panel.appendChild(tip);

            this.container.appendChild(panel);
        }

        _renderTimeAxis() {
            const axis = el('div', 'bezier-time-axis');
            axis.style.width = this.canvasWidth + 'px';
            const ticks = buildTicks(this.durationSec * 1000, this.zoom);
            for (const t of ticks) {
                const x = xToPx(t / 1000, this.canvasWidth, this.durationSec);
                const tick = el('div', 'bezier-tick');
                tick.style.left = x + 'px';
                tick.appendChild(el('span', 'bezier-tick-label', tickLabel(t)));
                axis.appendChild(tick);
            }
            return axis;
        }

        _renderSessionRow(session) {
            const row = el('div', 'bezier-row');
            row.dataset.sessionId = session.id;

            const header = el('div', 'bezier-row-header');
            header.appendChild(el('span', 'bezier-row-name', session.name || session.id));
            if (session.metadata) {
                header.appendChild(el('span', 'bezier-row-meta', session.metadata));
            }
            row.appendChild(header);

            const track = el('div', 'bezier-row-track');
            track.style.width = this.canvasWidth + 'px';

            const ticks = session.ticks || [];
            for (const t of ticks) {
                track.appendChild(this._renderEventBar(t));
            }
            row.appendChild(track);

            // Spawn annotation — mirrors workflow-panel.tsx:518-526. The
            // builder attaches a `spawnCallout` (x + label + subagentCount)
            // when the session summary contains a spawn_time. Position is
            // absolute so the pill drops below+right of the spawn dot and
            // sits on top of the row band without disturbing the flow of
            // the header / track below it.
            const spawnCallout = session.spawnCallout;
            if (spawnCallout && typeof spawnCallout.x === 'number') {
                const pill = el('div', 'bezier-annotation bezier-spawn-annotation');
                pill.style.left = Math.max(0, xToPx(spawnCallout.x, this.canvasWidth, this.durationSec) + 8) + 'px';
                // dotY in the TS reference is HEADER_H + LANE_H/2 = 22 + 11 = 33;
                // the +10 offsets the pill below the dot. Mirrored as-is
                // so the visual cadence matches clawcodex_sessions_analysis.
                pill.style.top = (HEADER_H + Math.floor(TRACK_H / 2) + 10) + 'px';
                const arrow = el('span', 'bezier-annotation-arrow', '▼');
                const timeText = el('span', 'bezier-annotation-time',
                    formatClock((spawnCallout.x || 0) * 1000));
                const sub = (typeof spawnCallout.subagentCount === 'number')
                    ? spawnCallout.subagentCount : 0;
                const label = el('span', 'bezier-annotation-label',
                    'Workflow 派生 ' + sub + ' 子agent');
                pill.appendChild(arrow);
                pill.appendChild(timeText);
                pill.appendChild(label);
                track.appendChild(pill);
            }

            // Merge annotation — mirrors workflow-panel.tsx:528-540. The
            // TS reference positions one merge pill per session panel,
            // anchored to the panel-level mergeX (max joinX across the
            // session's sub-agents). We compute the same value from
            // this.data.agents since the bezier view flattens sessions
            // and sub-agents into one vertical list. The pill anchors to
            // the LEFT of the merge dot (translateX(-100%)) so it never
            // overflows the canvas right edge.
            const subAgents = ((this.data && this.data.agents) || [])
                .filter((a) => a.parentSessionId === session.id);
            if (subAgents.length > 0) {
                let maxJoinX = 0;
                let hasJoin = false;
                for (const a of subAgents) {
                    const jx = (typeof a.joinX === 'number') ? a.joinX : (a.spawnX || 0);
                    if (jx > maxJoinX) maxJoinX = jx;
                    hasJoin = true;
                }
                if (hasJoin) {
                    const mergePx = xToPx(maxJoinX, this.canvasWidth, this.durationSec);
                    const pill = el('div', 'bezier-annotation bezier-merge-annotation');
                    pill.style.left = (mergePx - 8) + 'px';
                    pill.style.top = (HEADER_H + Math.floor(TRACK_H / 2) + 36) + 'px';
                    pill.style.transform = 'translateX(-100%)';
                    const arrow = el('span', 'bezier-annotation-arrow', '▲');
                    const timeText = el('span', 'bezier-annotation-time',
                        formatClock(maxJoinX * 1000));
                    const label = el('span', 'bezier-annotation-label', '汇合收工');
                    pill.appendChild(arrow);
                    pill.appendChild(timeText);
                    pill.appendChild(label);
                    track.appendChild(pill);
                }
            }

            return row;
        }

        _renderEventBar(tick) {
            const bar = el('div', 'bezier-event-bar bezier-cat-' + bezierCategoryOf(tick));
            if (tick.status === 'error') bar.classList.add('bezier-status-error');
            if (tick.status === 'warning') bar.classList.add('bezier-status-warning');
            if (tick.durationUnrecorded) bar.classList.add('bezier-duration-unrecorded');
            if (tick.tsUnrecorded) bar.classList.add('bezier-ts-unrecorded');
            if (tick.durationHeuristic) bar.classList.add('bezier-duration-heuristic');
            bar.dataset.barId = tick.id || '';
            // Index for click resolution. We don't attach a click
            // handler here — the click vs pan decision is made in
            // _onPointerUp using the startTick captured in
            // _onPointerDown, which avoids the suppress-flag dance.
            if (tick.id) this._tickByBarId.set(String(tick.id), tick);

            const x = Math.max(0, xToPx(tick.x, this.canvasWidth, this.durationSec));
            let w = xToPx(tick.w || 0, this.canvasWidth, this.durationSec);
            if (tick.durationUnrecorded) w = Math.max(MIN_BAR_PX, w);

            bar.style.left = x + 'px';
            bar.style.width = w + 'px';
            // Use the live theme colours (read at construction time
            // from --bezier-cat-* CSS vars, with a hardcoded fallback).
            // Per-bar `tick.color` override is preserved as the second
            // option for callers that supply a custom colour.
            const cat = bezierCategoryOf(tick);
            bar.style.background = (this._categoryColors && this._categoryColors[cat])
                || CATEGORY_COLORS[cat]
                || tick.color
                || '#6e7681';

            const timeStr = tick.absoluteTime || (tick.tsUnrecorded ? '未记录' : '');
            const durStr = tick.durationUnrecorded
                ? (tick.durationHeuristic ? '估算' : '未记录')
                : ((tick.w * 1000).toFixed(0) + 'ms');
            bar.title =
                (tick.label || bezierCategoryOf(tick)) +
                (timeStr ? ' · ' + timeStr : '') +
                ' · ' + durStr;

            return bar;
        }

        // ----------------------------------------------------------------
        // P5 — bezier connectors (spawn / merge) over the waterfall
        // ----------------------------------------------------------------
        //
        // The builder pre-computes the edge endpoints
        // (data.edges = [{type, from: {x,y}, to: {x,y}, color}, ...])
        // using its own internal row numbering. We translate those
        // builder-row indices to our own row index (sessions in order,
        // each followed by its sub-agents), then draw four SVG paths
        // per edge: hit-area (12 px, transparent, captures clicks +
        // pointer events), visible (variable stroke + opacity), glow
        // (only when selected) and focusable (transparent, tabIndex=0
        // for keyboard nav). 4 paths mirror workflow-panel.tsx:205-307.
        //
        // activeMap is rebuilt on every _render() and stores
        // {selected | hovered} for each connector key
        // (`${sessionId}:${agentId}:${role}`). Selected takes
        // precedence over hovered so a hover on a selected connector
        // doesn't downgrade its visual state — matches
        // workflow-panel.tsx:436-448.

        _connectorKeyOf(sessionId, agentId, role) {
            return sessionId + ':' + agentId + ':' + role;
        }

        _buildActiveMap() {
            this._activeMap = new Map();
            const sel = this.selectedConnector;
            if (sel) {
                const k = this._connectorKeyOf(sel.sessionId, sel.agentId, sel.role);
                this._activeMap.set(k, 'selected');
            }
            const hov = this.hoveredConnector;
            if (hov) {
                const k = this._connectorKeyOf(hov.sessionId, hov.agentId, hov.role);
                if (!this._activeMap.has(k)) this._activeMap.set(k, 'hovered');
            }
        }

        // Build the flat row index (sessions in order, each followed
        // by its sub-agents) AND the reverse lookup table
        // (builder-y → my row index). Called once per _render().
        _buildRowIndex() {
            const sessions = (this.data && this.data.sessions) || [];
            const agents   = (this.data && this.data.agents)   || [];
            const agentByParent = new Map();
            for (const a of agents) {
                if (!agentByParent.has(a.parentSessionId)) {
                    agentByParent.set(a.parentSessionId, []);
                }
                agentByParent.get(a.parentSessionId).push(a);
            }
            this._rowIndexById = new Map();
            this._agentById    = new Map();
            this._agentByBuilderY = new Map();
            this._builderYToMyY = new Map();
            let rowIdx = 0;
            for (const s of sessions) {
                this._rowIndexById.set('s:' + s.id, rowIdx);
                this._builderYToMyY.set(s.y, rowIdx);
                rowIdx++;
                const subList = agentByParent.get(s.id) || [];
                for (let i = 0; i < subList.length; i++) {
                    const a = subList[i];
                    this._rowIndexById.set('a:' + a.id, rowIdx);
                    this._agentById.set(a.id, a);
                    // Builder's depthY for the i-th sub-agent of session s.
                    const builderDepthY = s.y + 1 + i;
                    this._builderYToMyY.set(builderDepthY, rowIdx);
                    this._agentByBuilderY.set(builderDepthY, a);
                    rowIdx++;
                }
            }
            this._totalRows = rowIdx;
        }

        // ----------------------------------------------------------------
        // P5b — narrowed sub-agent track layout
        // ----------------------------------------------------------------
        //
        // Port of workflow-panel.tsx:48-160 buildLayout(). Each sub-agent
        // occupies a fraction of the canvas width corresponding to its
        // active time window (spawnX → joinX). Windows narrower than
        // MIN_LANE_FRAC are widened symmetrically so the track remains
        // visible, clamped to the session's merge point (rightBound).
        //
        // Returns an array of {agent, startFrac, endFrac} objects.

        _computeSubAgentLayout(agents) {
            if (!agents || agents.length === 0) return [];
            const dur = this.durationSec || 1;

            // mergeFrac = rightmost boundary (max joinX across all agents,
            // capped at 1.0). Lanes must not extend past this point.
            let maxJoin = 0;
            for (const a of agents) {
                const jx = a.joinX != null ? a.joinX : (a.spawnX || 0);
                if (jx > maxJoin) maxJoin = jx;
            }
            const mergeFrac = Math.min(1, maxJoin / dur) || 1;
            const rightBound = Math.max(MIN_LANE_FRAC, mergeFrac);

            const out = [];
            for (const a of agents) {
                const spawnX = a.spawnX || 0;
                const joinX  = a.joinX != null ? a.joinX : spawnX;
                let startFrac, endFrac;

                if (!(a.ticks && a.ticks.length > 0)) {
                    // No events: centre the min-width window on spawnX.
                    const centre = dur > 0 ? Math.max(0, Math.min(1, spawnX / dur)) : rightBound / 2;
                    startFrac = Math.max(0, centre - MIN_LANE_FRAC / 2);
                    endFrac   = Math.min(rightBound, startFrac + MIN_LANE_FRAC);
                } else {
                    // Derive window from the actual tick data.
                    let minT = Infinity, maxEnd = 0;
                    for (const t of a.ticks) {
                        if (t.x < minT) minT = t.x;
                        const end = t.x + Math.max(t.w || 0, 0.001);
                        if (end > maxEnd) maxEnd = end;
                    }
                    startFrac = dur > 0 ? Math.max(0, Math.min(1, (minT - 0.3) / dur)) : 0;
                    endFrac   = dur > 0 ? Math.min(Math.max(0, Math.min(1, maxEnd / dur)), rightBound) : rightBound;

                    if (endFrac - startFrac < MIN_LANE_FRAC) {
                        const centre = (startFrac + endFrac) / 2;
                        startFrac = Math.max(0, centre - MIN_LANE_FRAC / 2);
                        endFrac   = startFrac + MIN_LANE_FRAC;
                        if (endFrac > rightBound) {
                            endFrac   = rightBound;
                            startFrac = Math.max(0, endFrac - MIN_LANE_FRAC);
                        }
                    }
                }

                // Defensive swap if inverted.
                if (startFrac > endFrac) {
                    const tmp = startFrac; startFrac = endFrac; endFrac = tmp;
                }

                out.push({ agent: a, startFrac, endFrac });
            }
            return out;
        }

        // Cached lookup — returns the layout entry for a specific
        // agent, computing (and caching) the full sibling layout if
        // needed. Used by _renderConnectorPath and _renderConnectorTooltip
        // so they can snap curve endpoints to the narrowed track edge
        // without recomputing the entire layout on every edge.
        _getAgentLayout(agent) {
            if (!this._agentLayoutCache) this._agentLayoutCache = new Map();
            const sid = agent.parentSessionId;
            if (!this._agentLayoutCache.has(sid)) {
                const siblings = ((this.data && this.data.agents) || [])
                    .filter((a) => a.parentSessionId === sid);
                this._agentLayoutCache.set(sid, this._computeSubAgentLayout(siblings));
            }
            const layout = this._agentLayoutCache.get(sid);
            return layout.find((l) => l.agent.id === agent.id) || null;
        }

        _renderSubAgentRow(agent) {
            const row = el('div', 'bezier-row bezier-subagent-row');
            row.dataset.agentId = agent.id;
            row.dataset.parentSessionId = agent.parentSessionId;

            const header = el('div', 'bezier-row-header');
            header.style.paddingLeft = SUBAGENT_INDENT_PX + 'px';
            const pill = el('span', 'bezier-role-pill');
            pill.textContent = agent.role || '执行';
            if (agent.roleColor) pill.style.background = agent.roleColor;
            header.appendChild(pill);
            header.appendChild(el('span', 'bezier-row-name', agent.name || agent.id));
            // TS reference (workflow-panel.tsx:617-644) renders the
            // sub-agent label as a single inline group of badge +
            // name + events.length + formatTokens(contextTokens). We
            // keep the existing role pill + name + "次调用" meta, then
            // append the badge + count + tokens cluster to mirror
            // clawcodex_sessions_analysis without duplicating text.
            const meta = el('span', 'bezier-subagent-meta');
            if (agent.badge && agent.badge !== (agent.role || '执行')) {
                const badge = el('span', 'bezier-subagent-badge '
                    + (agent.isReview ? 'is-review' : 'is-default'));
                badge.textContent = agent.badge;
                meta.appendChild(badge);
            }
            if (agent.contextTokens) {
                meta.appendChild(el('span', 'bezier-subagent-tokens',
                    formatTokens(agent.contextTokens)));
            }
            if (meta.childNodes.length) {
                header.appendChild(meta);
            }
            if (agent.count) {
                header.appendChild(el('span', 'bezier-row-meta', agent.count + ' 次调用'));
            }
            row.appendChild(header);

            // Compute this agent's narrowed track layout. The track
            // occupies [startFrac, endFrac] of the canvas width rather
            // than the full width, matching workflow-panel.tsx's
            // buildLayout() with MIN_LANE_FRAC = 0.12.
            const layout = this._getAgentLayout(agent);
            const startFrac = layout ? layout.startFrac : 0;
            const endFrac   = layout ? layout.endFrac   : 1;
            const trackOffsetPx = startFrac * this.canvasWidth;
            const trackWidth    = Math.max(1, (endFrac - startFrac) * this.canvasWidth);
            const trackDurSec   = Math.max(0.001, (endFrac - startFrac) * this.durationSec);

            const track = el('div', 'bezier-row-track bezier-narrowed-track');
            track.style.width      = trackWidth + 'px';
            track.style.marginLeft = trackOffsetPx + 'px';

            const ticks = agent.ticks || [];
            for (const t of ticks) {
                const bar = el('div', 'bezier-event-bar bezier-cat-' + bezierCategoryOf(t));
                if (t.status === 'error') bar.classList.add('bezier-status-error');
                if (t.status === 'warning') bar.classList.add('bezier-status-warning');
                if (t.durationUnrecorded) bar.classList.add('bezier-duration-unrecorded');
                if (t.tsUnrecorded) bar.classList.add('bezier-ts-unrecorded');
                if (t.durationHeuristic) bar.classList.add('bezier-duration-heuristic');
                bar.classList.add('bezier-subagent-bar');
                bar.dataset.barId = t.id || '';
                if (t.id) this._tickByBarId.set(String(t.id), t);

                // Position RELATIVE to the track's own time window
                // (not global canvas), so events distribute correctly
                // within the narrowed track.
                const relX = t.x - (startFrac * this.durationSec);
                const leftPx = Math.max(0, (relX / trackDurSec) * trackWidth);
                let wPx = ((t.w || 0) / trackDurSec) * trackWidth;
                if (t.durationUnrecorded) wPx = Math.max(MIN_BAR_PX, wPx);

                bar.style.left  = leftPx + 'px';
                bar.style.width = wPx + 'px';

                const cat = bezierCategoryOf(t);
                bar.style.background = (this._categoryColors && this._categoryColors[cat])
                    || CATEGORY_COLORS[cat] || t.color || '#6e7681';

                const timeStr = t.absoluteTime || (t.tsUnrecorded ? '未记录' : '');
                const durStr = t.durationUnrecorded
                    ? (t.durationHeuristic ? '估算' : '未记录')
                    : ((t.w * 1000).toFixed(0) + 'ms');
                bar.title = (t.label || bezierCategoryOf(t))
                    + (timeStr ? ' · ' + timeStr : '') + ' · ' + durStr;

                track.appendChild(bar);
            }
            row.appendChild(track);
            return row;
        }

        _renderConnectors() {
            const edges = (this.data && this.data.edges) || [];
            if (!edges.length || !this._builderYToMyY) return null;

            this._buildActiveMap();
            const bodyOffsetTop = 6; // matches .bezier-body padding-top
            const totalHeight = (this._totalRows * ROW_H) + bodyOffsetTop;
            const svgNS = 'http://www.w3.org/2000/svg';
            const svg = document.createElementNS(svgNS, 'svg');
            svg.setAttribute('class', 'bezier-connector-svg');
            svg.setAttribute('width', this.canvasWidth);
            svg.setAttribute('height', totalHeight);
            svg.setAttribute('viewBox', '0 0 ' + this.canvasWidth + ' ' + totalHeight);
            // pointer-events: none on the root; the hit-area / focusable
            // paths re-enable stroke pointer-events so the curve
            // itself remains clickable without blocking bar clicks.
            svg.style.position = 'absolute';
            svg.style.top = '0';
            svg.style.left = '0';
            svg.style.pointerEvents = 'none';
            svg.style.zIndex = '5';
            svg.setAttribute('aria-hidden', 'true');

            for (const edge of edges) {
                const paths = this._renderConnectorPath(edge);
                if (paths) {
                    for (const p of paths) svg.appendChild(p);
                }
            }

            this._bindConnectorHandlers(svg);
            this._connectorSvgEl = svg;
            return svg;
        }

        _renderConnectorPath(edge) {
            const fromMyY = this._builderYToMyY.get(edge.from.y);
            const toMyY   = this._builderYToMyY.get(edge.to.y);
            if (fromMyY == null || toMyY == null) return null;
            const agent = this._agentByBuilderY.get(
                edge.type === 'fork' ? edge.to.y : edge.from.y
            );
            if (!agent) return null;

            const fromY = (fromMyY * ROW_H) + HEADER_H + (TRACK_H / 2);
            const toY   = (toMyY   * ROW_H) + HEADER_H + (TRACK_H / 2);
            let fromX = xToPx(edge.from.x, this.canvasWidth, this.durationSec);
            let toX   = xToPx(edge.to.x,   this.canvasWidth, this.durationSec);

            // Snap the sub-agent side X to the narrowed track edge.
            // Spawn (fork): curve goes parent → sub-agent, so toX = LEFT edge.
            // Merge (join): curve goes sub-agent → parent, so fromX = RIGHT edge.
            const myLayout = this._getAgentLayout(agent);
            if (myLayout) {
                if (edge.type === 'fork') {
                    toX = myLayout.startFrac * this.canvasWidth;
                } else {
                    fromX = myLayout.endFrac * this.canvasWidth;
                }
            }

            if (!isFinite(fromX) || !isFinite(toX)) return null;

            const role = edge.type === 'fork' ? 'spawn' : 'merge';
            const isSpawn = role === 'spawn';
            const key = this._connectorKeyOf(agent.parentSessionId, agent.id, role);
            const activeState = this._activeMap.get(key);
            const isSelected = activeState === 'selected';
            const isHovered  = activeState === 'hovered';

            const midY = fromY + ((toY - fromY) * 0.55);
            const d = 'M ' + fromX + ' ' + fromY
                + ' C ' + fromX + ' ' + midY
                + ', ' + toX   + ' ' + midY
                + ', ' + toX   + ' ' + toY;

            const baseOpacity = isSpawn ? CONNECTOR_OPACITY_SPAWN : CONNECTOR_OPACITY_MERGE;
            const sw = isSelected ? CONNECTOR_STROKE_SELECTED
                     : isHovered  ? CONNECTOR_STROKE_HOVER
                     :              CONNECTOR_STROKE_DEFAULT;
            const visibleOpacity = isSelected ? CONNECTOR_OPACITY_SELECTED
                                 : isHovered  ? CONNECTOR_OPACITY_HOVER
                                 :              baseOpacity;
            const baseColor   = isSpawn ? 'var(--bezier-connector-active)'
                                       : 'var(--bezier-connector-merge-active)';
            const hoverColor  = 'var(--bezier-connector-hover)';
            const visibleColor = (isSelected || isHovered)
                ? (isSelected ? baseColor : hoverColor)
                : 'var(--bezier-connector)';

            const svgNS = 'http://www.w3.org/2000/svg';
            const paths = [];

            // 1. Hit-area — transparent 12 px stroke catches clicks on thin curves.
            const hitArea = document.createElementNS(svgNS, 'path');
            hitArea.setAttribute('d', d);
            hitArea.setAttribute('fill', 'none');
            hitArea.setAttribute('stroke', 'transparent');
            hitArea.setAttribute('stroke-width', CONNECTOR_HITAREA_STROKE);
            hitArea.setAttribute('class', 'bezier-connector-hitarea');
            hitArea.setAttribute('data-connector-key', key);
            hitArea.setAttribute('data-session-id', agent.parentSessionId);
            hitArea.setAttribute('data-agent-id', agent.id);
            hitArea.setAttribute('data-role', role);
            hitArea.setAttribute('style', 'pointer-events: stroke; cursor: pointer; outline: none;');
            paths.push(hitArea);

            // 2. Visible path — the user-facing curve.
            const visible = document.createElementNS(svgNS, 'path');
            visible.setAttribute('d', d);
            visible.setAttribute('fill', 'none');
            visible.setAttribute('stroke', visibleColor);
            visible.setAttribute('stroke-width', sw);
            visible.setAttribute('opacity', visibleOpacity);
            visible.setAttribute('class', 'bezier-connector-visible');
            visible.setAttribute('style', 'pointer-events: none; transition: stroke-width 150ms ease-out, opacity 150ms ease-out, stroke 150ms ease-out;');
            paths.push(visible);

            // 3. Glow — only painted when selected. Wider stroke + low opacity
            // gives a halo that signals the active selection.
            if (isSelected) {
                const glow = document.createElementNS(svgNS, 'path');
                glow.setAttribute('d', d);
                glow.setAttribute('fill', 'none');
                glow.setAttribute('stroke', baseColor);
                glow.setAttribute('stroke-width', CONNECTOR_GLOW_STROKE);
                glow.setAttribute('opacity', CONNECTOR_GLOW_OPACITY);
                glow.setAttribute('class', 'bezier-connector-glow');
                glow.setAttribute('style', 'pointer-events: none; transition: opacity 200ms ease-out;');
                paths.push(glow);
            }

            // 4. Focusable — transparent, tabIndex=0, role=button. Sits on
            // top of the visible path so keyboard users can reach every
            // connector. role=button + aria-pressed gives AT users the
            // selected/hovered state.
            const focusable = document.createElementNS(svgNS, 'path');
            focusable.setAttribute('d', d);
            focusable.setAttribute('fill', 'none');
            focusable.setAttribute('stroke', 'transparent');
            focusable.setAttribute('stroke-width', Math.max(sw + 4, 10));
            focusable.setAttribute('tabindex', '0');
            focusable.setAttribute('role', 'button');
            focusable.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
            const startTime = formatClock((edge.from.x || 0) * 1000);
            const endTime   = formatClock((edge.to.x   || 0) * 1000);
            const ariaLabel = isSpawn
                ? '派生到子 agent "' + (agent.name || agent.id) + '",起始 ' + startTime
                  + ',事件 ' + (agent.count || 0)
                : '从子 agent "' + (agent.name || agent.id) + '" 汇合,结束 ' + endTime
                  + ',事件 ' + (agent.count || 0);
            focusable.setAttribute('aria-label', ariaLabel);
            focusable.setAttribute('data-connector-key', key);
            focusable.setAttribute('data-session-id', agent.parentSessionId);
            focusable.setAttribute('data-agent-id', agent.id);
            focusable.setAttribute('data-role', role);
            focusable.setAttribute('style', 'pointer-events: stroke; cursor: pointer; outline: none;');
            paths.push(focusable);

            return paths;
        }

        // HTML tooltip rendered as a sibling of the SVG so it's a
        // proper <div> with full CSS / animation support (SVG <g>
        // can't host <div> children reliably). Positioned at the
        // curve's midpoint; flips to the left side when the curve
        // sits past 85% of the canvas width so the box stays inside
        // the scroll container.
        _renderConnectorTooltip() {
            const ref = this.hoveredConnector || this.selectedConnector;
            if (!ref || !this._builderYToMyY) return null;
            const agent = this._agentById.get(ref.agentId);
            if (!agent) return null;
            const isSpawn = ref.role === 'spawn';
            const x0Raw = isSpawn ? agent.spawnX : agent.joinX;
            const x1Raw = isSpawn ? agent.joinX  : agent.spawnX;
            let x0 = xToPx(x0Raw || 0, this.canvasWidth, this.durationSec);
            let x1 = xToPx(x1Raw || 0, this.canvasWidth, this.durationSec);
            // Snap sub-agent side to the narrowed track edge (matches
            // _renderConnectorPath so the tooltip sits on the curve).
            const tipLayout = this._getAgentLayout(agent);
            if (tipLayout) {
                if (isSpawn) {
                    x1 = tipLayout.startFrac * this.canvasWidth;
                } else {
                    x0 = tipLayout.endFrac * this.canvasWidth;
                }
            }
            const y0 = (this._rowIndexById.get('s:' + agent.parentSessionId) * ROW_H)
                + HEADER_H + (TRACK_H / 2);
            const y1 = (this._rowIndexById.get('a:' + agent.id) * ROW_H)
                + HEADER_H + (TRACK_H / 2);
            if (!isFinite(x0) || !isFinite(y0) || !isFinite(x1) || !isFinite(y1)) return null;
            const midY = y0 + ((y1 - y0) * 0.55);
            const midX = (x0 + x1) / 2;
            const flip = (midX / Math.max(1, this.canvasWidth)) > 0.85;
            const arrow = isSpawn ? '▼' : '▲';
            const verb  = isSpawn ? '派生' : '汇合';
            const timeRange = isSpawn
                ? (formatClock((x0Raw || 0) * 1000) + ' 起')
                : (formatClock((x1Raw || 0) * 1000) + ' 收');

            const tip = el('div', 'bezier-connector-tooltip');
            tip.style.position = 'absolute';
            tip.style.left = midX + 'px';
            tip.style.top  = midY + 'px';
            tip.style.transform = flip
                ? 'translate(-100%, -100%) translate(0, -8px)'
                : 'translate(0, -100%) translate(0, -8px)';
            tip.setAttribute('role', 'tooltip');

            const head = el('div', 'bezier-connector-tooltip-head');
            const arrowSpan = el('span', 'bezier-connector-tooltip-arrow', arrow);
            arrowSpan.style.color = isSpawn
                ? 'var(--bezier-connector-active)'
                : 'var(--bezier-connector-merge-active)';
            head.appendChild(arrowSpan);
            head.appendChild(document.createTextNode(verb + ' → ' + (agent.name || agent.id)));
            tip.appendChild(head);

            tip.appendChild(el('div', 'bezier-connector-tooltip-meta',
                timeRange + ' · ' + (agent.count || 0) + ' 次调用'));
            tip.appendChild(el('div', 'bezier-connector-tooltip-hint', '点击查看泳道详情'));

            this._connectorTipEl = tip;
            return tip;
        }

        // Event delegation on the SVG root. One set of listeners
        // covers every connector — adding new edges does not require
        // re-binding. Listeners are tracked in this._listeners so
        // destroy() tears them down cleanly.
        _bindConnectorHandlers(svg) {
            const onEnter = (e) => {
                const target = e.target.closest('[data-connector-key]');
                if (!target) return;
                const sid = target.getAttribute('data-session-id');
                const aid = target.getAttribute('data-agent-id');
                const role = target.getAttribute('data-role');
                if (!sid || !aid || !role) return;
                if (this.hoveredConnector
                    && this.hoveredConnector.sessionId === sid
                    && this.hoveredConnector.agentId === aid
                    && this.hoveredConnector.role === role) return;
                this.hoveredConnector = { sessionId: sid, agentId: aid, role: role };
                this._render();
            };
            const onLeave = (e) => {
                // Only clear if we're truly leaving the SVG (not just
                // moving between two paths inside it).
                if (e.relatedTarget && svg.contains(e.relatedTarget)) return;
                if (this.hoveredConnector) {
                    this.hoveredConnector = null;
                    this._render();
                }
            };
            const onClick = (e) => {
                const target = e.target.closest('[data-connector-key]');
                if (!target) return;
                const sid = target.getAttribute('data-session-id');
                const aid = target.getAttribute('data-agent-id');
                const role = target.getAttribute('data-role');
                if (!sid || !aid || !role) return;
                e.stopPropagation();
                const cur = this.selectedConnector;
                if (cur && cur.sessionId === sid && cur.agentId === aid && cur.role === role) {
                    this.selectedConnector = null; // toggle off
                } else {
                    this.selectedConnector = { sessionId: sid, agentId: aid, role: role };
                }
                this._render();
            };
            const onKey = (e) => {
                const target = e.target.closest('[data-connector-key]');
                if (!target) return;
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    const sid = target.getAttribute('data-session-id');
                    const aid = target.getAttribute('data-agent-id');
                    const role = target.getAttribute('data-role');
                    if (!sid || !aid || !role) return;
                    const cur = this.selectedConnector;
                    if (cur && cur.sessionId === sid && cur.agentId === aid && cur.role === role) {
                        this.selectedConnector = null;
                    } else {
                        this.selectedConnector = { sessionId: sid, agentId: aid, role: role };
                    }
                    this._render();
                }
            };
            this._addListener(svg, 'mouseover', onEnter);
            this._addListener(svg, 'mouseout',  onLeave);
            this._addListener(svg, 'click',     onClick);
            this._addListener(svg, 'keydown',   onKey);
        }

        _renderError(msg) {
            if (!this.container) return;
            this.container.innerHTML = '<div class="bezier-error">'
                + '加载失败: ' + escapeHtml(msg) + '</div>';
        }

        // ----------------------------------------------------------------
        // P3 — zoom / pan interactions
        // ----------------------------------------------------------------

        _attachInteractions() {
            if (!this.scrollEl) return;

            this._measureContainer();

            if (typeof ResizeObserver !== 'undefined') {
                const ro = new ResizeObserver(() => this._measureContainer());
                ro.observe(this.scrollEl);
                this._observers.push(ro);
            } else {
                const onResize = () => this._measureContainer();
                window.addEventListener('resize', onResize);
                this._listeners.push({ target: window, type: 'resize', fn: onResize });
            }

            this._addListener(this.scrollEl, 'wheel', (e) => this._onWheel(e), { passive: false });
            this._addListener(this.scrollEl, 'pointerdown', (e) => this._onPointerDown(e));
            this._addListener(document, 'pointermove',   (e) => this._onPointerMove(e));
            this._addListener(document, 'pointerup',     (e) => this._onPointerUp(e));
            this._addListener(document, 'pointercancel', (e) => this._onPointerUp(e));

            // Esc closes the detail panel and clears any selected
            // connector. Always attached (cheap); only acts when a
            // panel / selection is actually open.
            this._addListener(document, 'keydown', (e) => {
                if (e.key !== 'Escape') return;
                if (this.selectedEvent) {
                    this._closeDetailPanel();
                }
                if (this.selectedConnector) {
                    this.selectedConnector = null;
                    this._render();
                }
            });
        }

        _addListener(target, type, fn, options) {
            target.addEventListener(type, fn, options);
            this._listeners.push({ target: target, type: type, fn: fn, options: options || false });
        }

        _detachInteractions() {
            for (let i = 0; i < this._listeners.length; i++) {
                const l = this._listeners[i];
                try { l.target.removeEventListener(l.type, l.fn, l.options); }
                catch (_) { /* target may already be gone */ }
            }
            this._listeners = [];
            for (let i = 0; i < this._observers.length; i++) {
                try { this._observers[i].disconnect(); } catch (_) { /* ignore */ }
            }
            this._observers = [];
            if (this.rafId != null) {
                cancelAnimationFrame(this.rafId);
                this.rafId = null;
            }
            this.panState = null;
            this.isPanning = false;
            this.scrollEl = null;
            document.body.style.userSelect = '';
        }

        _measureContainer() {
            if (!this.scrollEl) return;
            const w = this.scrollEl.clientWidth;
            if (w > 0 && w !== this.containerW) {
                this.containerW = w;
                this.containerWRef.current = w;
                this.canvasWidth = Math.max(MIN_CANVAS_PX, this.containerW * this.zoom);
                this.scaleX = this.canvasWidth / this.durationSec;
                this._render();
            }
        }

        _onWheel(e) {
            e.preventDefault();
            if (e.altKey) {
                this.scrollEl.scrollLeft = Math.max(
                    0, this.scrollEl.scrollLeft + e.deltaX + e.deltaY
                );
                return;
            }
            const delta  = e.deltaY < 0 ? 1 : -1;
            const factor = 1 + delta * ZOOM_STEP;
            const current = this.zoomRef.current;
            const next    = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, current * factor));
            if (next === current) return;

            const containerW = this.containerWRef.current;
            const cw         = Math.max(MIN_CANVAS_PX, containerW * current);
            const rect       = this.scrollEl.getBoundingClientRect();
            const cursorX    = e.clientX - rect.left + this.scrollEl.scrollLeft;
            const fracUnder  = cursorX / Math.max(1, cw);
            const newCanvas  = Math.max(MIN_CANVAS_PX, containerW * next);
            const newScroll  = fracUnder * newCanvas - (e.clientX - rect.left);

            this._setZoom(next);
            if (this.rafId != null) cancelAnimationFrame(this.rafId);
            this.rafId = requestAnimationFrame(() => {
                this.rafId = null;
                if (this.scrollEl) {
                    this.scrollEl.scrollLeft = Math.max(0, newScroll);
                }
            });
        }

        _setZoom(next) {
            this.zoom = next;
            this.zoomRef.current = next;
            this.canvasWidth = Math.max(MIN_CANVAS_PX, this.containerW * this.zoom);
            this.scaleX = this.canvasWidth / this.durationSec;
            this._render();
        }

        _onPointerDown(e) {
            if (e.pointerType === 'mouse' && e.button !== 0) return;
            // Capture the tick under the pointer (if any) so the
            // pointerup can decide click vs pan without needing a
            // separate click handler + suppress flag.
            const barEl = this._findBarElement(e.target);
            const tick  = barEl ? this._tickByBarId.get(barEl.dataset.barId) : null;
            this.panState = {
                startX: e.clientX,
                startY: e.clientY,
                startScrollLeft: this.scrollEl.scrollLeft,
                pointerId: e.pointerId,
                moved: false,
                startTick: tick,
            };
            this.isPanning = true;
            this._setUserSelect(true);
        }

        _onPointerMove(e) {
            const state = this.panState;
            if (!state || state.pointerId !== e.pointerId) return;
            const deltaX = e.clientX - state.startX;
            if (!state.moved && Math.abs(deltaX) < PAN_THRESHOLD_PX) return;
            state.moved = true;
            e.preventDefault();
            this.scrollEl.scrollLeft = Math.max(0, state.startScrollLeft - deltaX);
        }

        _onPointerUp(e) {
            if (!this.panState || this.panState.pointerId !== e.pointerId) return;
            const wasMoved  = this.panState.moved;
            const startTick = this.panState.startTick;
            this.panState = null;
            this.isPanning = false;
            this._setUserSelect(false);
            // Click (no significant drag) on a bar → open the panel.
            // The 4 px threshold in _onPointerMove guarantees the
            // panState.moved flag is false unless the user actually
            // dragged; below that we treat it as a click.
            if (!wasMoved && startTick) {
                this._openDetailPanel(startTick);
            }
        }

        _setUserSelect(disabled) {
            if (disabled) {
                if (this._prevUserSelect === undefined) {
                    this._prevUserSelect = document.body.style.userSelect;
                }
                document.body.style.userSelect = 'none';
            } else {
                document.body.style.userSelect = (this._prevUserSelect != null) ? this._prevUserSelect : '';
                this._prevUserSelect = undefined;
            }
        }

        _findBarElement(target) {
            let el = target;
            while (el && el !== this.scrollEl) {
                if (el.classList && el.classList.contains('bezier-event-bar')) return el;
                el = el.parentElement;
            }
            return null;
        }

        setZoom(next) {
            const clamped = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, next));
            if (clamped === this.zoom) return;
            this._setZoom(clamped);
        }

        // ----------------------------------------------------------------
        // P4 — EventDetailDrawer (right-side slide-in, mirrors the
        // waterfall chart's .turn-drawer pattern). 5 body types share
        // the same drawer; selection toggles the .open class.
        // ----------------------------------------------------------------

        // The 5 body types are keyed by `_eventKindOf(tick)`. Mapping
        // matches the Next.js panel's event.kind dispatch at
        // event-detail-panel.tsx:111-121.
        _eventKindOf(tick) {
            if (!tick) return 'other';
            if (tick.userRole === 'user')    return 'user';
            if (tick.userRole === 'system')  return 'system';
            if (tick.type === 'tool_result') return 'tool-result';
            if (tick.type === 'tool_call')   return 'tool';
            if (tick.type === 'llm_call')    return 'llm';
            if (tick.userRole === 'assistant') return 'llm';
            return 'other';
        }

        _headerLabelOf(tick) {
            const kind = this._eventKindOf(tick);
            if (kind === 'llm')          return (tick.model || 'LLM 思考');
            if (kind === 'user')         return '用户输入';
            if (kind === 'system')       return '系统 · ' + (tick.detail && tick.detail.subtype || 'system');
            if (kind === 'tool-result')  return (tick.detail && tick.detail.toolName || '工具返回') + ' 返回';
            return tick.label || '事件';
        }

        _isErrorOf(tick) {
            if (tick.status === 'error') return true;
            // tool_result also carries an `is_error` flag in detail
            if (tick.detail && tick.detail.is_error === true) return true;
            return false;
        }

        _openDetailPanel(tick) {
            this.selectedEvent = tick;
            this._renderDetailPanel();
        }

        _closeDetailPanel() {
            this.selectedEvent = null;
            this._renderDetailPanel();
        }

        // Lazily cache the static #bezier-drawer markup declared in
        // session_row.html. Wire the close button + Escape key once
        // per instance; subsequent calls just return the cached refs.
        // Mirrors the waterfall's drawer pattern (close button + Esc
        // + click-outside are all handled outside the chart code).
        _ensureDrawer() {
            if (this._drawerRefs) return this._drawerRefs;
            const drawer = document.getElementById('bezier-drawer');
            if (!drawer) {
                console.warn('[bezier] #bezier-drawer not found in DOM');
                return null;
            }
            const refs = {
                drawer,
                body: drawer.querySelector('#bezier-drawer-body'),
                title: drawer.querySelector('#bezier-drawer-title'),
                catDot: drawer.querySelector('#bezier-drawer-cat-dot'),
                pills: drawer.querySelector('#bezier-drawer-pills'),
                closeBtn: drawer.querySelector('.turn-drawer-close'),
            };
            if (refs.closeBtn) {
                refs.closeBtn.addEventListener('click', () => this._closeDetailPanel());
            }
            // Esc key — bound at the instance level (not the document
            // level) so multiple bezier instances don't double-fire.
            // Use capture phase so we close before the waterfall's own
            // Esc handler on a different drawer.
            this._onDrawerKeydown = (e) => {
                if (e.key === 'Escape' && this.selectedEvent) {
                    e.stopPropagation();
                    this._closeDetailPanel();
                }
            };
            document.addEventListener('keydown', this._onDrawerKeydown, true);
            this._drawerRefs = refs;
            this._drawerCloseWired = true;
            return refs;
        }

        // Build a single header pill (category or error). Pills are
        // scoped to the bezier drawer (no collision with the waterfall
        // legend bar) and inherit `--bezier-cat-*` theme colours.
        _buildPill(text, color, opts) {
            opts = opts || {};
            const pill = el('span', 'bezier-drawer-pill', text);
            if (color) {
                pill.style.borderColor = color;
                pill.style.color = color;
            }
            if (opts.error) pill.classList.add('bezier-drawer-pill-error');
            return pill;
        }

        // Populate the pre-built drawer markup and toggle the .open
        // class. When `selectedEvent` is null the drawer is hidden and
        // its body is cleared; no DOM nodes are created or destroyed.
        _renderDetailPanel() {
            if (!this.selectedEvent) {
                if (this._drawerRefs && this._drawerRefs.drawer) {
                    this._drawerRefs.drawer.classList.remove('open');
                    if (this._drawerRefs.body) this._drawerRefs.body.innerHTML = '';
                }
                return;
            }
            const refs = this._ensureDrawer();
            if (!refs) return;
            const tick = this.selectedEvent;
            // Update the static header (cat dot + title + pills).
            const kind = this._eventKindOf(tick);
            const cat  = (kind === 'llm') ? 'llm' : bezierCategoryOf(tick);
            const colorMap = this._categoryColors || CATEGORY_COLORS;
            const catColor = colorMap[cat] || CATEGORY_COLORS[cat] || '#6e7681';
            const catLabel = CATEGORY_LABELS[cat] || '其他';
            if (refs.catDot) refs.catDot.style.background = catColor;
            if (refs.title)  refs.title.textContent = this._headerLabelOf(tick);
            if (refs.pills) {
                refs.pills.innerHTML = '';
                refs.pills.appendChild(this._buildPill(catLabel, catColor));
                if (this._isErrorOf(tick)) {
                    refs.pills.appendChild(this._buildPill('错误', null, { error: true }));
                }
            }
            // Rebuild the body. Cheap; the body is short.
            if (refs.body) {
                refs.body.innerHTML = '';
                refs.body.appendChild(this._buildPanelBody(tick));
            }
            refs.drawer.classList.add('open');
            refs.drawer.setAttribute('aria-hidden', 'false');
        }

        _buildPanelBody(tick) {
            const body = el('div', 'bezier-event-panel-body');

            // Time section — same shape for all 5 kinds.
            const time = buildSection('时间');
            // Relative time (seconds, formatClock style). ts_unrecorded → "未记录".
            const relSec = (typeof tick.x === 'number') ? tick.x : null;
            appendRow(time.content, '相对时间',
                tick.tsUnrecorded ? '未记录' : formatRelSec(relSec),
                { mono: true, muted: !!tick.tsUnrecorded });
            // Duration — note: plan called out the Next.js bug
            // (event-detail-panel.tsx:91-100 missing "估算" label) and
            // we fix it here with a 3-way branch: 估算 / 未记录 / real.
            const durStr = tick.durationUnrecorded
                ? (tick.durationHeuristic ? '估算' : '未记录')
                : (typeof tick.w === 'number'
                    ? (tick.w).toFixed(2) + ' 秒 (' + Math.round(tick.w * 1000).toLocaleString() + ' ms)'
                    : '—');
            appendRow(time.content, '持续时间', durStr,
                { mono: true, muted: !!tick.durationUnrecorded && !tick.durationHeuristic });
            // Absolute time — ISO from the builder.
            const absStr = tick.tsUnrecorded ? '未记录' : (tick.absoluteTime ? formatAbsTime(tick.absoluteTime) : '—');
            appendRow(time.content, '绝对时间', absStr,
                { mono: true, muted: !!tick.tsUnrecorded });
            body.appendChild(time.section);

            // Kind-specific body — same dispatch as
            // event-detail-panel.tsx:111-121.
            const kind = this._eventKindOf(tick);
            if (kind === 'llm')          this._buildLlmBody(body, tick);
            else if (kind === 'user')    this._buildUserBody(body, tick);
            else if (kind === 'system')  this._buildSystemBody(body, tick);
            else if (kind === 'tool-result') this._buildToolResultBody(body, tick);
            else                          this._buildToolBody(body, tick);

            return body;
        }

        _buildLlmBody(root, tick) {
            // Model
            if (tick.model) {
                const s = buildSection('模型');
                appendRow(s.content, 'model', tick.model, { mono: true });
                root.appendChild(s.section);
            }
            // Token 消耗 — v1 永远 None(plan: "v1 逐事件 token 计数
            // 不实现(留 None)"). Surface the placeholder so users
            // understand the gap isn't a parsing failure.
            const t = buildSection('Token 消耗');
            t.content.appendChild(el('div', 'bezier-event-empty', 'v1 未记录 usage（仅 LLM 级别统计可见）'));
            root.appendChild(t.section);

            // LLM 输入 — current v1 leaves inputText None (plan:
            // "v1 input_text 不实现"); render the same placeholder.
            const inS = buildSection('LLM 输入');
            inS.content.appendChild(el('div', 'bezier-event-empty', 'v1 未记录（需要 parentUuid 链解析）'));
            root.appendChild(inS.section);

            // LLM 输出 — text_preview from the parser, max 12 lines.
            if (tick.detail && tick.detail.text_preview) {
                const out = buildSection('LLM 输出');
                appendCodeBlock(out.content, tick.detail.text_preview, CODEBLOCK_MAX_LINES_LLM);
                root.appendChild(out.section);
            } else {
                const empty = el('div', 'bezier-event-empty');
                empty.appendChild(el('p', null, '此 LLM 事件没有可显示的文本内容。'));
                empty.appendChild(el('p', null, 'v1 仅记录元数据。'));
                const s = buildSection('LLM 输出');
                s.content.appendChild(empty);
                root.appendChild(s.section);
            }
        }

        _buildUserBody(root, tick) {
            const s = buildSection('用户提示');
            const text = (tick.userText != null) ? tick.userText
                       : (tick.detail && tick.detail.text_preview) || '';
            appendCodeBlock(s.content, text, CODEBLOCK_MAX_LINES_OTHER);
            root.appendChild(s.section);
            root.appendChild(el('p', 'bezier-event-hint',
                '用户提示即为模型输入，触发紧随其后的 LLM 回合。'));
        }

        _buildSystemBody(root, tick) {
            const s = buildSection('事件类型');
            const subtype = (tick.detail && tick.detail.subtype) || 'system';
            appendRow(s.content, 'subtype', subtype, { mono: true });
            root.appendChild(s.section);
            const text = (tick.systemText != null) ? tick.systemText
                       : (tick.detail && tick.detail.text_preview) || '';
            if (text) {
                const t = buildSection('事件正文');
                appendCodeBlock(t.content, text, CODEBLOCK_MAX_LINES_OTHER);
                root.appendChild(t.section);
            } else {
                const empty = el('div', 'bezier-event-empty');
                empty.appendChild(el('p', null, '此系统事件没有可显示的正文内容。'));
                empty.appendChild(el('p', null, '仅记录了 subtype 标识与时间戳。'));
                const t = buildSection('事件正文');
                t.content.appendChild(empty);
                root.appendChild(t.section);
            }
            root.appendChild(el('p', 'bezier-event-hint',
                '系统事件由 harness 自动注入（如离开摘要、压缩标记、本地命令），非用户或模型行为。'));
        }

        _buildToolResultBody(root, tick) {
            const s = buildSection('配对信息');
            const toolName = (tick.detail && (tick.detail.toolName || tick.detail.tool_name)) || 'result';
            appendRow(s.content, 'tool', toolName, { mono: true });
            if (tick.detail && tick.detail.tool_use_id) {
                appendRow(s.content, 'tool_use_id', tick.detail.tool_use_id, { mono: true });
            }
            root.appendChild(s.section);
            const text = (tick.detail && tick.detail.excerpt) || '';
            if (text) {
                const t = buildSection('返回内容');
                appendCodeBlock(t.content, text, CODEBLOCK_MAX_LINES_OTHER);
                root.appendChild(t.section);
            } else {
                const empty = el('div', 'bezier-event-empty');
                empty.appendChild(el('p', null, '此工具返回没有可显示的正文内容。'));
                const t = buildSection('返回内容');
                t.content.appendChild(empty);
                root.appendChild(t.section);
            }
        }

        _buildToolBody(root, tick) {
            // 工具输入 — params object → JSON.
            if (tick.detail && tick.detail.params) {
                const s = buildSection('工具输入');
                const paramsText = (typeof tick.detail.params === 'string')
                    ? tick.detail.params
                    : JSON.stringify(tick.detail.params, null, 2);
                appendCodeBlock(s.content, paramsText, CODEBLOCK_MAX_LINES_OTHER);
                root.appendChild(s.section);
            }
            // 工具参数 — short summary (matches event-detail-panel.tsx:294-300)
            if (tick.detail && tick.detail.summary) {
                const s = buildSection('工具参数');
                s.content.appendChild(el('p', 'bezier-event-summary', tick.detail.summary));
                root.appendChild(s.section);
            }
            // No rich detail → fallback empty state
            if (!tick.detail || Object.keys(tick.detail).length === 0) {
                const empty = el('div', 'bezier-event-empty');
                empty.appendChild(el('p', null, '此事件暂无详细记录。'));
                empty.appendChild(el('p', null, '可在 transcript.jsonl 中查阅原始条目。'));
                const s = buildSection('详情');
                s.content.appendChild(empty);
                root.appendChild(s.section);
            }
        }

        // Resize handle removed: the side drawer uses the fixed width
        // defined on .turn-drawer (420px / 92vw) from the waterfall
        // chart. Resizing would shift the chart behind it; the existing
        // width is tuned for both surfaces.

        destroy() {
            this._detachInteractions();
            this._destroyDetailPanel();
            if (this._onDrawerKeydown) {
                document.removeEventListener('keydown', this._onDrawerKeydown, true);
                this._onDrawerKeydown = null;
            }
            this._drawerRefs = null;
            this._drawerCloseWired = false;
            if (this.container) {
                this.container.innerHTML = '';
                this.container.classList.remove('bezier-waterfall');
            }
            this.data = null;
            this.container = null;
        }

        _destroyDetailPanel() {
            if (this._drawerRefs && this._drawerRefs.drawer) {
                this._drawerRefs.drawer.classList.remove('open');
                this._drawerRefs.drawer.setAttribute('aria-hidden', 'true');
                if (this._drawerRefs.body) this._drawerRefs.body.innerHTML = '';
            }
            this.selectedEvent = null;
            this._tickByBarId = new Map();
        }
    }

    // ----------------------------------------------------------------
    // Local utility (avoid pulling in the full utils.js for one call)
    // ----------------------------------------------------------------

    function escapeHtml(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    // ----------------------------------------------------------------
    // Singleton lifecycle
    // ----------------------------------------------------------------

    let instance = null;

    function init(sessionIds, options) {
        if (instance) instance.destroy();
        const containerId = (options && options.chartContainerId) || 'bezier-chart';
        instance = new BezierWaterfallImpl(containerId, options);
        return instance.init(sessionIds || []);
    }

    function close() {
        if (instance) {
            instance.destroy();
            instance = null;
        }
    }

    function render() {
        if (instance) instance._render();
    }

    function setZoom(z) { if (instance) instance.setZoom(z); }
    function openDetail(tick) { if (instance) instance._openDetailPanel(tick); }
    function closeDetail() { if (instance) instance._closeDetailPanel(); }

    return {
        init: init,
        close: close,
        render: render,
        setZoom: setZoom,
        openDetail: openDetail,
        closeDetail: closeDetail,
        // P5 — connector state control (consumed by tests / devtools).
        clearConnectorSelection: function() {
            if (instance && instance.selectedConnector) {
                instance.selectedConnector = null;
                instance._render();
            }
        },
        CATEGORIES: BEZIER_CATEGORIES,
        COLORS: CATEGORY_COLORS,
        LABELS: CATEGORY_LABELS,
        _bezierCategoryOf: bezierCategoryOf,
        _buildTicks: buildTicks,
        _tickLabel: tickLabel,
        _formatClock: formatClock,
        _formatRelSec: formatRelSec,
        _formatAbsTime: formatAbsTime,
        _connectorKeyOf: function(sid, aid, role) { return sid + ':' + aid + ':' + role; },
        ZOOM_MIN: ZOOM_MIN,
        ZOOM_MAX: ZOOM_MAX,
        ZOOM_STEP: ZOOM_STEP,
        // P5 — row layout constants
        ROW_H: ROW_H,
        HEADER_H: HEADER_H,
        TRACK_H: TRACK_H,
        SUBAGENT_INDENT_PX: SUBAGENT_INDENT_PX,
        MIN_LANE_FRAC: MIN_LANE_FRAC,
        // P5 — connector constants
        CONNECTOR_STROKE_DEFAULT:  CONNECTOR_STROKE_DEFAULT,
        CONNECTOR_STROKE_HOVER:    CONNECTOR_STROKE_HOVER,
        CONNECTOR_STROKE_SELECTED: CONNECTOR_STROKE_SELECTED,
        CONNECTOR_OPACITY_SPAWN:    CONNECTOR_OPACITY_SPAWN,
        CONNECTOR_OPACITY_MERGE:    CONNECTOR_OPACITY_MERGE,
        CONNECTOR_OPACITY_HOVER:    CONNECTOR_OPACITY_HOVER,
        CONNECTOR_OPACITY_SELECTED: CONNECTOR_OPACITY_SELECTED,
        // P7 — CSS variable / theme surface
        // `_readCategoryColors(doc?)` returns a fresh object of
        // {category → colour} resolved from --bezier-cat-* on the
        // given document (default: window.document). Falls back
        // to the hardcoded CATEGORY_COLORS map when a token
        // resolves to '' or the document is unavailable.
        _readCategoryColors: readCategoryColors,
        _categoryColorVar: CSS_VAR_FOR_CATEGORY,
    };
})();

// ---- Global API (consumed by template <script> blocks) ----
window.initBezierWaterfall       = function(sessionIds, options) { return BezierWaterfall.init(sessionIds, options); };
window.closeBezierPanel          = function() { BezierWaterfall.close(); };
window.renderBezierChart         = function() { BezierWaterfall.render(); };
window.setBezierZoom             = function(z) { BezierWaterfall.setZoom(z); };
window.openBezierDetail          = function(tick) { BezierWaterfall.openDetail(tick); };
window.closeBezierDetail         = function() { BezierWaterfall.closeDetail(); };
window.clearBezierConnectorSelection = function() { BezierWaterfall.clearConnectorSelection(); };
// Devtools / smoke-test exposure
window.BezierWaterfall           = BezierWaterfall;
