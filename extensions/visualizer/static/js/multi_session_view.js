/**
 * ClawCodex Visualizer — Multi-Session Waterfall View (F-95)
 *
 * Design-spec aligned with session分析效果图.png:
 *   - top: 5-pill legend with counts (read/execute/write/orchestrate/other)
 *   - left: time axis (relative, e.g. 0/5/10/15/20/25/30 min)
 *   - rows: each session gets a swimlane, sub-agents cascade below in waterfall
 *   - activity ticks: dense color-coded vertical bars (28% lane height)
 *   - fork/join: pink/blue curved bezier lines between parent and sub-agents
 *   - model pills: rounded capsules with metadata (ops · agentType · context)
 *   - agent pills: role-colored capsules (评审/核对/写入/执行) + score
 */

const MultiSessionView = (function() {
    let chart = null;
    let currentData = null;
    // Track init() arguments so live updates can re-render and re-init
    // without forcing the caller to pass options on every event.
    let currentContainerId = 'ms-chart';
    let currentLegendId = 'ms-legend-bar';
    let currentSessionIds = null;
    // Stash gantt.js's onLiveEvent so we can co-exist on session_row.html
    // — when the user is on the waterfall view we own the dispatcher and
    // also nudge gantt.js so the gantt chart stays in sync if mounted.
    let ganttLiveEvent = null;

    // ---- View density tuning (waterfall fix) ----
    // Below HIT_MIN_PX the canvas rect becomes hard to hit; we wrap each
    // foreground bar in a transparent hit zone.
    const HIT_MIN_PX = 8;
    const VISIBLE_MIN_PX = 6;
    const MIN_TICK_SECONDS = 0.001;
    // F-95 follow-up: per-category opacity for the custom-series bars.
    // LLM_TEXT bars (assistant text/thinking spans) get a low opacity so
    // they read as a background layer and never visually obscure the
    // narrower tool-call chips that share the same pixel range, even at
    // maximum dataZoom zoom. All other categories default to 0.95.
    const OPACITY_BY_CAT = {
        llm_text: 0.25,
        read: 0.9,
        execute: 0.9,
        write: 0.9,
        orchestrate: 0.85,
        other: 0.75,
    };
    // Visible-window threshold (in data seconds) below which we render
    // ticks in their natural per-turn form, and above which we collapse
    // neighbours into aggregated "fat" bars. Re-evaluated on datazoom.
    const DETAIL_THRESHOLD_SEC = 60;
    // Debounce window for re-aggregating after a datazoom burst.
    let densifyTimer = null;
    // Cache the last mode so we can short-circuit re-renders.
    let lastViewMode = 'detail';
    // Cached dataZoom state — preserved across the re-render that
    // follows a density-mode switch so the user's zoom doesn't jump.
    let lastDzState = null;
    let selectedAgentId = null;
    let badgePayloads = [];

    async function _loadTurnIo(meta) {
        const llmSection = document.getElementById('turn-drawer-llm');
        const toolSection = document.getElementById('turn-drawer-tools');
        const sessionId = meta && meta.sessionId;
        const candidates = transcriptLookupIds(meta);
        if (!sessionId || candidates.length === 0) {
            renderLocalRecords(meta);
            return;
        }

        if (llmSection) {
            llmSection.innerHTML = '<div class="turn-drawer-loading">'
                + '<span class="turn-drawer-spinner"></span> Loading transcript I/O...</div>';
        }
        if (toolSection) {
            toolSection.innerHTML = '<div class="turn-drawer-loading">'
                + '<span class="turn-drawer-spinner"></span> Loading tool I/O...</div>';
        }

        let lastError = '';
        for (const turnId of candidates) {
            const url = `/api/viz/turn/${encodeURIComponent(sessionId)}__`
                      + `${encodeURIComponent(turnId)}/llm-io`;
            try {
                const resp = await fetch(url, { headers: { 'Accept': 'application/json' } });
                if (!resp.ok) {
                    let detail = `HTTP ${resp.status}`;
                    try {
                        const body = await resp.json();
                        if (body && body.detail) detail = body.detail;
                    } catch (_) { /* ignore body parse */ }
                    lastError = detail;
                    continue;
                }
                const payload = await resp.json();
                renderSessionRecords(payload, meta);
                if (llmSection) llmSection.innerHTML = _renderLlmIoHtml(payload);
                if (toolSection) toolSection.innerHTML = _renderToolIoHtml(payload, meta);
                return;
            } catch (e) {
                lastError = String(e && e.message || e);
            }
        }

        renderLocalIo(meta);
        renderLocalRecords(meta);
        if (!hasLocalLlmPreview(meta)) {
            appendIoHint(llmSection, `Transcript lookup failed: ${lastError || 'not found'}`);
        }
    }

    /**
     * Initialize the view for the given session IDs.
     * Public entry point used by multi_session.html inline script and
     * session_row.html (single-session waterfall).
     *
     * @param {string[]} sessionIds
     * @param {object} [options]
     * @param {string} [options.chartContainerId='ms-chart']  ECharts target div.
     * @param {string|null} [options.legendContainerId='ms-legend-bar']
     *        Legend pill bar div. Pass null to skip (e.g. when the page
     *        already renders legend counts in its own chrome).
     */
    async function init(sessionIds, options) {
        const opts = options || {};
        const chartId = opts.chartContainerId || 'ms-chart';
        const legendId = opts.legendContainerId === undefined
            ? 'ms-legend-bar' : opts.legendContainerId;
        currentContainerId = chartId;
        currentLegendId = legendId;
        currentSessionIds = sessionIds;

        // First init() on this page — capture gantt.js's onLiveEvent (if
        // any) before we replace the global. This is what lets the
        // waterfall and the gantt view co-exist on session_row.html.
        if (!ganttLiveEvent && typeof window.onLiveEvent === 'function'
                && window.onLiveEvent !== onLiveEvent) {
            ganttLiveEvent = window.onLiveEvent;
        }
        window.onLiveEvent = onLiveEvent;

        if (!Array.isArray(sessionIds) || sessionIds.length === 0) {
            const el = document.getElementById(chartId);
            if (el) el.innerHTML = '<div class="empty-state">未提供 session ID</div>';
            return;
        }
        try {
            const data = await VizUtils.apiFetch(
                `/api/viz/multi-session?sessions=${encodeURIComponent(sessionIds.join(','))}`
            );
            currentData = data;
            updateReferenceChrome(data);
            if (legendId) renderLegend(data.legend || [], legendId);
            renderChart(data, chartId);
        } catch (e) {
            console.error('Multi-session load failed:', e);
            const el = document.getElementById(chartId);
            if (el) el.innerHTML = `<div class="empty-state">加载失败: ${e.message}</div>`;
        }
    }

    // ------------------------------------------------------------------
    // Live event handler (window.onLiveEvent)
    // ------------------------------------------------------------------
    function onLiveEvent(event) {
        if (!event) return;
        // Waterfall not initialized yet — defer to gantt.js (full reload).
        if (!currentData || !chart) {
            if (typeof ganttLiveEvent === 'function') ganttLiveEvent(event);
            return;
        }
        let handled = false;
        if (event.type === 'bar_update') {
            handled = applyBarUpdate(event);
            if (handled) {
                renderChart(currentData, currentContainerId);
                if (currentLegendId) renderLegend(currentData.legend || [], currentLegendId);
            }
        } else if (event.type === 'transcript_event') {
            // Sub-agent activity, config updates, etc. — full server
            // round-trip is the simplest correct path.
            init(currentSessionIds, {
                chartContainerId: currentContainerId,
                legendContainerId: currentLegendId,
            });
            return;
        }
        // Always nudge the gantt view if it's still mounted, so the two
        // views stay in sync.  Cheap when the gantt chart isn't visible.
        if (typeof ganttLiveEvent === 'function' && window.ganttChart) {
            try { ganttLiveEvent(event); } catch (e) { /* swallow */ }
        }
    }

    /**
     * Mutate ``currentData`` in place with a structured ``bar_update``.
     * Returns true if the data was changed and a re-render is warranted.
     */
    function applyBarUpdate(event) {
        const sessionId = event.session_id;
        const bar = event && event.bar;
        if (!sessionId || !bar) return false;
        const session = (currentData.sessions || []).find(s => s.id === sessionId);
        if (!session) return false;  // event is for a session not in the view

        const baseTime = (currentData.timeRange && currentData.timeRange.min) || 0;
        const startRel = Math.max(0, (bar.start_time || 0) - baseTime);
        const endRel = Math.max(
            startRel + MIN_TICK_SECONDS,
            (bar.end_time || startRel) - baseTime
        );
        const tick = {
            x: startRel,
            w: endRel - startRel,
            category: bar.category || 'other',
            color: bar.color || '#a0a0b0',
            status: bar.status || 'running',
            label: bar.label || bar.tool_name || '',
            id: bar.id,
        };
        session.ticks = session.ticks || [];
        const existingIdx = session.ticks.findIndex(t => t.id === bar.id);
        const isNew = existingIdx < 0;
        if (isNew) session.ticks.push(tick);
        else session.ticks[existingIdx] = tick;

        // Keep legend count in sync for newly-emitted bars.
        if (isNew && Array.isArray(currentData.legend)) {
            const legendItem = currentData.legend.find(l => l.category === tick.category);
            if (legendItem) legendItem.count = (legendItem.count || 0) + 1;
        }
        // Extend the time axis if the new bar goes past the right edge.
        if (currentData.timeRange && endRel * 1.1 > (currentData.timeRange.max || 0)) {
            currentData.timeRange.max = endRel * 1.1;
        }
        // Track the session end so the endMarker / stats reflect activity.
        session.end_time = Math.max(session.end_time || 0, bar.end_time || 0);
        return true;
    }

    // ------------------------------------------------------------------
    // Legend bar (pure HTML — no ECharts needed)
    // ------------------------------------------------------------------
    function renderLegend(legend, containerId) {
        const bar = document.getElementById(containerId || 'ms-legend-bar');
        if (!bar) return;
        if (!legend.length) {
            bar.innerHTML = '';
            return;
        }
        bar.innerHTML = legend.map(l => `
            <span class="ms-legend-pill" data-category="${l.category}">
                <span class="ms-dot" style="background:${l.color}"></span>
                <span class="ms-label">${l.label}</span>
                <span class="ms-count">${l.count}</span>
            </span>
        `).join('');
    }

    function updateReferenceChrome(data) {
        const shell = document.querySelector('.ms-analysis-shell');
        if (!shell || !data) return;
        const sessions = data.sessions || [];
        const agents = data.agents || [];
        const first = sessions[0] || {};
        const modelEl = document.getElementById('ms-reference-model');
        const summaryEl = document.getElementById('ms-reference-summary');
        const statusEl = document.getElementById('ms-reference-status');

        if (modelEl) {
            const model = first.model || first.name || first.id || 'Opus4.8';
            modelEl.textContent = truncateVisual(model, 38);
        }

        if (summaryEl) {
            const mainOps = first.totalOps || (first.ticks || []).length || 0;
            const subCount = agents.filter(a => a.parentSessionId === first.id).length || agents.length;
            const subOps = agents.reduce((sum, a) => sum + (a.count || (a.ticks || []).length || 0), 0);
            const context = first.contextSize || first.context || '';
            const childrenCtx = agents.map(a => a.contextSize || a.context).filter(Boolean);
            const pieces = [];
            pieces.push(subCount
                ? `${mainOps} 主线 + ${subCount} 子agent (${subOps || mainOps} 调用)`
                : `${mainOps} 主线 · 单agent`);
            if (context) pieces.push(`主agent上下文 ${context}`);
            if (childrenCtx.length) pieces.push(`子agent ${childrenCtx[0]}${childrenCtx.length > 1 ? '-' + childrenCtx[childrenCtx.length - 1] : ''}`);
            summaryEl.innerHTML = pieces.map(p => `<span>${escapeHtml(p)}</span>`).join('');
        }

        if (statusEl) {
            const marker = first.endMarker || {};
            const timeLabel = marker.timeLabel || marker.durationLabel || '';
            const status = marker.statusLabel || marker.label || first.status || '汇合修复 ✓';
            statusEl.innerHTML = `
                ${timeLabel ? `<span>${escapeHtml(timeLabel)}</span>` : ''}
                <span>${escapeHtml(status)}</span>
                <span class="ms-reference-dot"></span>
            `;
        }
    }

    // ------------------------------------------------------------------
    // Main chart (ECharts custom series)
    // ------------------------------------------------------------------
    function renderChart(data, containerId) {
        const container = document.getElementById(containerId || 'ms-chart');
        if (!container) return;

        if (!chart) {
            chart = echarts.init(container, 'dark', { renderer: 'canvas' });
            window.addEventListener('resize', () => chart && chart.resize());

            // F-95 ResizeObserver fix: when the page (or its tab) lays
            // out after init(), the canvas can be created with width=0
            // and the chart never recovers. window.resize alone doesn't
            // catch container-only size changes (e.g. sidebar collapse),
            // so observe the container directly and re-fit on every
            // observed dimension change. Guarded by chart being non-null
            // since the observer may fire after teardown.
            if (typeof ResizeObserver !== 'undefined') {
                const ro = new ResizeObserver(() => {
                    if (chart) chart.resize();
                });
                ro.observe(container);
            }
            // First-frame re-fit: the parent flex/grid may not have
            // assigned a real width at the moment echarts.init runs.
            // requestAnimationFrame defers the resize until after the
            // current layout pass, which matches how ECharts' own
            // examples handle this case.
            requestAnimationFrame(() => {
                if (chart) chart.resize();
            });

            // ---- Click: open the side drawer with turn metadata ----
            chart.on('click', function(params) {
                if (!params || !params.data) return;
                // Skip edge series — they carry no turn payload.
                if (params.seriesName === 'edges') return;
                if (params.seriesName === 'lanes' && params.data.agentId) {
                    selectedAgentId = selectedAgentId === params.data.agentId ? null : params.data.agentId;
                    renderChart(currentData, currentContainerId);
                    return;
                }
                // F-95 follow-up: agent label pill click. The pill
                // lives in the 'badges' custom series; buildBadgeData
                // tags it with kind === 'agent' (index 2) and agentId
                // (index 3) in the value tuple. We read from
                // params.value rather than params.data because the
                // custom-series encode pipeline rebuilds params.data
                // from the internal DataStore and drops extra fields.
                if (params.seriesName === 'badges'
                        && Array.isArray(params.value)
                        && badgePayloads[params.value[2]]
                        && badgePayloads[params.value[2]].kind === 'agent') {
                    const agentId = badgePayloads[params.value[2]].agentId;
                    selectedAgentId = selectedAgentId === agentId ? null : agentId;
                    renderChart(currentData, currentContainerId);
                    return;
                }
                const meta = buildTurnMeta(params.data);
                selectedAgentId = meta.agentId || null;
                renderChart(currentData, currentContainerId);
                openTurnDrawer(meta);
            });

            // ---- Datazoom: debounced re-aggregation ----
            // When the user pans/zooms across the DETAIL_THRESHOLD_SEC
            // boundary we rebuild the series with the right density.
            // We capture the dataZoom state from the event payload
            // (params.batch[0].start/end) because the option isn't
            // guaranteed to be updated yet when the handler fires.
            // We also derive the next mode from lastDzState + the
            // session's timeRange rather than chart.getOption(), so a
            // dispatchAction (or any source of dataZoom updates) is
            // reflected even when the option hasn't been re-applied.
            chart.on('datazoom', function(params) {
                if (densifyTimer) clearTimeout(densifyTimer);
                // ECharts surfaces dataZoom state in two shapes:
                //   - user gestures:  params.batch = [{ start, end, ... }]
                //   - dispatchAction: params = { type, start, end }  (top-level)
                // Read both, prefer the explicit numbers on whichever
                // shape we got, and fall back to chart.getOption() only
                // as a last resort.
                let nextStart, nextEnd;
                const batch = params && params.batch && params.batch[0];
                if (batch && typeof batch.start === 'number'
                        && typeof batch.end === 'number') {
                    nextStart = batch.start; nextEnd = batch.end;
                } else if (params && typeof params.start === 'number'
                        && typeof params.end === 'number') {
                    nextStart = params.start; nextEnd = params.end;
                } else {
                    const dz = chart.getOption().dataZoom;
                    if (dz && dz[0]) {
                        nextStart = dz[0].start || 0;
                        nextEnd = dz[0].end || 100;
                    }
                }
                if (typeof nextStart === 'number' && typeof nextEnd === 'number') {
                    lastDzState = { start: nextStart, end: nextEnd };
                }
                densifyTimer = setTimeout(() => {
                    // Use the cached lastDzState + the session's timeRange
                    // to decide the mode. This matches what renderChart
                    // uses for its own aggregation decision, so the two
                    // stay in sync even if chart.getOption() lags.
                    const ts = (currentData && currentData.timeRange) || {};
                    const span = Math.max(1, (ts.max || 60) - (ts.min || 0));
                    const dz = lastDzState || { start: 0, end: 100 };
                    const visSpan = span * (dz.end - dz.start) / 100;
                    const nextMode = visSpan > DETAIL_THRESHOLD_SEC ? 'density' : 'detail';
                    if (nextMode === lastViewMode) return;
                    lastViewMode = nextMode;
                    if (currentData) renderChart(currentData, currentContainerId);
                }, 180);
            });
        }

        const sessions = data.sessions || [];
        const agents = data.agents || [];
        const edges = data.edges || [];
        const timeRange = data.timeRange || { min: 0, max: 60, tickSeconds: [], tickLabels: [] };
        const layout = getChartLayout(container);

        // Build implicit y categories: each row is one lane.
        // Row 0: first session
        // Row 1..N: sub-agents of first session, then second session, then sub-agents of second...
        // Order: sessions[i] at y=i, agents of sessions[i] follow at y=i+1..i+k.
        // The server already does this — we just take y as-is.
        const yCategories = buildYCategories(sessions, agents);
        const yIndex = new Map(yCategories.map((label, i) => [label, i]));
        const laneData = buildLaneData(sessions, agents, yIndex, yCategories, timeRange);
        const badgeData = buildBadgeData(sessions, agents, yIndex);

        // ---- Session swimlane series (activity ticks per session) ----
        const sessionTickDataRaw = sessions.flatMap(s => {
            const yi = yIndex.get(sessionLabel(s));
            return (s.ticks || []).map(t => ({
                value: [
                    yi,
                    t.x,
                    t.x + tickWidthSeconds(t),
                    t.color,
                    t.status,
                    t.label,
                    t.id,
                    t.category || 'other',
                ],
                itemId: t.id,
                sessionId: s.id,
                agentId: null,
                category: t.category || 'other',
                barType: t.type || null,
                detail: t.detail || null,
                toolUseId: t.toolUseId || (t.detail && t.detail.tool_use_id) || null,
            }));
        });

        // ---- Agent swimlane series (one per agent) ----
        const agentTickDataRaw = [];
        for (const a of agents) {
            const yi = yIndex.get(agentLabel(a));
            // Background span (spawn → join) — subtle gray bar
                agentTickDataRaw.push({
                    value: [
                        yi,
                        a.spawnX,
                        a.joinX,
                    'rgba(255,255,255,0.04)',
                    'span',
                    a.title,
                    `span-${a.id}`,
                    'span',
                ],
                isBackground: true,
                    sessionId: a.parentSessionId || null,
                    agentId: a.id,
                    laneRole: a.role || '执行',
                });
            // Activity ticks from agent metadata (or empty)
            for (const t of (a.ticks || [])) {
                agentTickDataRaw.push({
                    value: [
                        yi,
                        t.x,
                        t.x + tickWidthSeconds(t),
                        t.color,
                        t.status,
                        t.label,
                        t.id,
                        t.category || 'other',
                    ],
                    itemId: t.id,
                    sessionId: a.parentSessionId || null,
                    agentId: a.id,
                    laneRole: a.role || '执行',
                    category: t.category || 'other',
                    barType: t.type || null,
                    detail: t.detail || null,
                    toolUseId: t.toolUseId || (t.detail && t.detail.tool_use_id) || null,
                });
            }
        }

        const activityRange = getTickTimeRange(sessionTickDataRaw, agentTickDataRaw);
        if (activityRange) {
            timeRange.min = activityRange.min;
            timeRange.max = activityRange.max;
        }

        // ---- Density-aware aggregation ----
        // When the visible window is wide (zoomed out) we collapse
        // neighbouring turns into single "fat" bars so the user can
        // still hover/click. Crucially the aggregation operates on
        // the *visible* window only: ticks outside the current view
        // are filtered out first, and bucket size is computed from
        // visSpan (not the full timeline span) so the bucket grid
        // adapts to the user's zoom level.
        // ---- Density-aware aggregation ----
        // When the visible window is wide (zoomed out) we collapse
        // neighbouring turns into single "fat" bars so the user can
        // still hover/click. Crucially the aggregation operates on
        // the *visible* window only: ticks outside the current view
        // are filtered out first, and bucket size is computed from
        // visSpan (not the full timeline span) so the bucket grid
        // adapts to the user's zoom level.
        //
        // NB: we can't read xAxis min/max from chart.getOption() here
        // — on the very first render the chart hasn't been given an
        // option yet, so chart.getOption() returns the default empty
        // option and getEffectiveRange() short-circuits to null. We
        // derive the range from timeRange + lastDzState directly.
        const xMin = timeRange.min || 0;
        const xMax = timeRange.max || 60;
        const dzState = lastDzState || { start: 0, end: 100 };
        const xSpan = Math.max(1, xMax - xMin);
        const effRange = {
            visMin: xMin + xSpan * dzState.start / 100,
            visMax: xMin + xSpan * dzState.end / 100,
            visSpan: xSpan * (dzState.end - dzState.start) / 100,
        };
        const sessionTickData = sessionTickDataRaw;
        const agentTickData = agentTickDataRaw;
        const renderedMode = effRange.visSpan > DETAIL_THRESHOLD_SEC ? 'density' : 'detail';
        lastViewMode = renderedMode;
        if (renderedMode === 'density') {
            const sIn = filterToRange(sessionTickDataRaw, effRange.visMin, effRange.visMax);
            const aIn = filterToRange(agentTickDataRaw, effRange.visMin, effRange.visMax);
            const bucketCount = Math.max(50, Math.min(600, Math.round(effRange.visSpan / 0.2)));
            const sDens = densifyTicks(sIn, effRange.visSpan, bucketCount);
            const aDens = densifyTicks(aIn, effRange.visSpan, bucketCount);
            sessionTickData.splice(0, sessionTickData.length, ...sDens);
            agentTickData.splice(0, agentTickData.length, ...aDens);
        }

        // ---- Edges (fork/join) for graph series ----
        const graphNodes = [];
        const graphLinks = [];
        const branchData = [];
        // Session nodes
        for (const s of sessions) {
            graphNodes.push({
                id: `s-${s.id}`,
                name: s.name,
                x: 0,
                y: yIndex.get(sessionLabel(s)),
                fixedY: true,
                category: 0,
            });
        }
        // Agent nodes
        for (const a of agents) {
            graphNodes.push({
                id: `a-${a.id}`,
                name: a.title,
                x: 0,
                y: yIndex.get(agentLabel(a)),
                fixedY: true,
                category: 1,
            });
        }
        // Edge endpoints (left = fork from parent x; right = join back to parent x)
        for (const e of edges) {
            if (e.type === 'fork') {
                const parentY = e.from.y;
                const childY = e.to.y;
                // Find parent session at y=parentY
                const parent = sessions.find(s => s.y === parentY);
                if (!parent) continue;
                const child = agents.find(a => a.depthY === childY);
                if (!child) continue;
                graphNodes.push({
                    id: `fork-${parent.id}-${child.id}`,
                    name: '', x: e.from.x, y: parentY, fixedY: true, _role: 'fork-endpoint',
                });
                graphNodes.push({
                    id: `fork-end-${parent.id}-${child.id}`,
                    name: '', x: e.from.x, y: childY, fixedY: true, _role: 'fork-endpoint',
                });
                graphLinks.push({
                    source: `fork-${parent.id}-${child.id}`,
                    target: `fork-end-${parent.id}-${child.id}`,
                    lineStyle: edgeStyle(child.id, 'fork'),
                });
                branchData.push({
                    value: [parentY, e.from.x, e.to.x, childY, 'fork'],
                    agentId: child.id,
                    color: '#ea7ccc',
                });
            } else if (e.type === 'join') {
                const childY = e.from.y;
                const parentY = e.to.y;
                const parent = sessions.find(s => s.y === parentY);
                if (!parent) continue;
                const child = agents.find(a => a.depthY === childY);
                if (!child) continue;
                graphNodes.push({
                    id: `join-${parent.id}-${child.id}`,
                    name: '', x: e.from.x, y: childY, fixedY: true, _role: 'join-endpoint',
                });
                graphNodes.push({
                    id: `join-end-${parent.id}-${child.id}`,
                    name: '', x: e.to.x, y: parentY, fixedY: true, _role: 'join-endpoint',
                });
                graphLinks.push({
                    source: `join-${parent.id}-${child.id}`,
                    target: `join-end-${parent.id}-${child.id}`,
                    lineStyle: edgeStyle(child.id, 'join'),
                });
                branchData.push({
                    value: [childY, e.from.x, e.to.x, parentY, 'join'],
                    agentId: child.id,
                    color: '#7aa2ff',
                });
            }
        }

        const option = {
            backgroundColor: layout.reference ? 'transparent' : '#0d1117',
            animation: false,
            // F-95 legend fix: disable ECharts' auto-rendered legend so it
            // never collides with the HTML `.ms-legend-bar` (which session_row
            // places above the chart).  The HTML bar carries the same
            // 5-pill content via renderLegend(); the ECharts default legend
            // would otherwise wrap onto 2-3 lines inside grid.top:70 and
            // stack on top of the stats bar.
            legend: { show: false },
            tooltip: {
                trigger: 'item',
                backgroundColor: 'rgba(13, 17, 23, 0.95)',
                borderColor: '#30363d',
                textStyle: { color: '#c9d1d9', fontSize: 11 },
                formatter: function(params) {
                    if (!params.data || !params.data.value) return '';
                    const v = params.data.value;
                    if (v.length < 6) return '';
                    if (params.data.isBackground) {
                        return `<strong>${escapeHtml(v[4] || '')}</strong><br/>
                                <span style="color:#8b949e">background span</span>`;
                    }
                    if (params.data.aggregatedCount > 1) {
                        return `<strong>${params.data.aggregatedCount} aggregated turns</strong><br/>
                                <span style="color:#8b949e">click to expand</span>`;
                    }
                    const id = params.data.itemId || v[6] || '—';
                    const dur = ((v[2] || 0) - (v[1] || 0)).toFixed(2);
                    return `<strong>${escapeHtml(v[5] || v[4] || id)}</strong><br/>
                            <span style="color:#8b949e">id:</span> ${escapeHtml(id)}<br/>
                            <span style="color:#8b949e">start:</span> ${formatRelSec(v[1])}<br/>
                            <span style="color:#8b949e">dur:</span> ${dur}s<br/>
                            <span style="color:#8b949e">status:</span> ${escapeHtml(v[4] || '—')}`;
                },
            },
            grid: {
                left: layout.gridLeft,
                right: layout.gridRight,
                top: layout.gridTop,
                bottom: layout.gridBottom,
                containLabel: !layout.reference,
            },
            xAxis: {
                type: 'value',
                min: timeRange.min,
                max: timeRange.max,
                axisLabel: {
                    show: !layout.compact && !layout.reference,
                    color: '#8b949e',
                    fontSize: 10,
                    formatter: formatRelSec,
                },
                axisLine: { lineStyle: { color: layout.reference ? 'rgba(108,132,154,0.08)' : 'rgba(139,148,158,0.06)' } },
                axisTick: { show: !layout.reference, lineStyle: { color: 'rgba(139,148,158,0.04)' } },
                splitLine: {
                    lineStyle: {
                        type: layout.reference ? 'dashed' : 'solid',
                        color: layout.reference ? 'rgba(116,139,162,0.16)' : 'rgba(139,148,158,0.035)',
                        width: layout.reference ? 1.2 : 1,
                    },
                },
            },
            yAxis: {
                type: 'category',
                data: yCategories,
                inverse: true,
                axisLabel: {
                    show: false,
                    color: '#8b949e',
                    fontSize: 10,
                    margin: 4,
                    formatter: function(value) {
                        const TARGET_PX = layout.compact ? 42 : 110;
                        const charPx = 10;
                        const maxVisual = TARGET_PX / charPx;
                        let visual = 0;
                        let out = '';
                        for (const ch of value) {
                            const w = /[\u4e00-\u9fa5\uff00-\uffef]/.test(ch) ? 2 : 1;
                            if (visual + w > maxVisual) {
                                out += '…';
                                break;
                            }
                            out += ch;
                            visual += w;
                        }
                        return out;
                    },
                },
                axisLine: { show: false },
                axisTick: { show: false },
                splitLine: {
                    show: !layout.reference,
                    lineStyle: { color: 'rgba(139,148,158,0.03)' },
                },
            },
            dataZoom: [
                { type: 'slider', xAxisIndex: 0, height: layout.reference ? 0 : 14, bottom: layout.reference ? 0 : 14,
                  show: !layout.reference,
                  start: lastDzState ? lastDzState.start : 0,
                  end: lastDzState ? lastDzState.end : 100,
                  textStyle: { color: '#8b949e' },
                  borderColor: '#30363d',
                  fillerColor: 'rgba(88,166,255,0.08)',
                  handleStyle: { color: '#58a6ff' },
                  dataBackground: {
                      lineStyle: { color: '#30363d' },
                      areaStyle: { color: '#161b22' }
                  },
                  selectedDataBackground: {
                      lineStyle: { color: '#58a6ff' },
                      areaStyle: { color: 'rgba(88,166,255,0.1)' }
                  }
                },
                { type: 'inside', xAxisIndex: 0, zoomOnMouseWheel: true, moveOnMouseMove: true,
                  start: lastDzState ? lastDzState.start : 0,
                  end: lastDzState ? lastDzState.end : 100 },
            ],
            series: [
                // Session activity ticks
                {
                    name: 'lanes',
                    type: 'custom',
                    renderItem: renderLane,
                    encode: { x: [1, 2], y: 0 },
                    data: laneData,
                    progressive: 0,
                    z: 0,
                },
                {
                    name: 'sessions',
                    type: 'custom',
                    renderItem: renderTick,
                    encode: { x: [1, 2], y: 0 },
                    data: sessionTickData,
                    progressive: 0,
                    z: 3,
                },
                // Agent activity ticks (foreground + background spans)
                {
                    name: 'agents',
                    type: 'custom',
                    renderItem: renderTick,
                    encode: { x: [1, 2], y: 0 },
                    data: agentTickData,
                    progressive: 0,
                    z: 2,
                },
                // Fork / join curves
                {
                    name: 'branches',
                    type: 'custom',
                    renderItem: renderBranch,
                    encode: { x: [1, 2], y: [0, 3] },
                    data: branchData,
                    progressive: 0,
                    silent: true,
                    z: 5,
                },
                {
                    name: 'edges',
                    type: 'graph',
                    coordinateSystem: 'cartesian2d',
                    layout: 'none',
                    roam: false,
                    silent: true,
                    symbol: ['none', 'none'],
                    nodes: graphNodes,
                    links: graphLinks,
                    lineStyle: { width: 1.5, opacity: 0.7 },
                    z: 4,
                },
                // F-95 follow-up: model / agent / end-marker / spawn
                // callout pills. They live in their own custom series
                // so `notMerge: true` on the main setOption no longer
                // wipes them. `clip: false` lets the gutter pills
                // (model + agent) render outside the plot area; the
                // end-marker and spawn callout use real data-x
                // coordinates and are clamped to the plot edge.
                {
                    name: 'badges',
                    type: 'custom',
                    coordinateSystem: 'cartesian2d',
                    renderItem: renderBadge,
                    encode: { x: 1, y: 0 },
                    data: badgeData,
                    clip: false,
                    progressive: 0,
                    z: 10,
                },
            ],
        };

        option.xAxis.axisLabel.formatter = formatRelSec;
        chart.setOption(option, true);
    }

    function getChartLayout(container) {
        const width = container && container.clientWidth ? container.clientWidth : 1000;
        const compact = width < 640;
        const reference = !!(container && container.dataset && container.dataset.visualMode === 'reference');
        if (reference) {
            const mobile = width < 900;
            return {
                compact: mobile,
                reference: true,
                gridLeft: mobile ? 18 : 20,
                gridRight: mobile ? 16 : 64,
                gridTop: mobile ? 58 : 51,
                gridBottom: mobile ? 22 : 26,
                badgeX: mobile ? 16 : 17,
                modelWidth: mobile ? 250 : 390,
                agentRoleWidth: mobile ? 44 : 46,
                agentTitleX: mobile ? 52 : 56,
                agentCountX: mobile ? 156 : 188,
                agentTitleVisual: mobile ? 10 : 18,
                rowScale: mobile ? 0.9 : 0.82,
            };
        }
        return {
            compact,
            reference: false,
            gridLeft: compact ? 108 : 260,
            gridRight: compact ? 20 : 48,
            gridTop: 20,
            gridBottom: 56,
            badgeX: compact ? 8 : 16,
            modelWidth: compact ? 84 : 200,
            agentRoleWidth: compact ? 44 : 72,
            agentTitleX: compact ? 48 : 82,
            agentCountX: compact ? 96 : 186,
            agentTitleVisual: compact ? 6 : 20,
            rowScale: 1,
        };
    }

    function currentLayout() {
        const el = document.getElementById(currentContainerId);
        return getChartLayout(el);
    }

    // ------------------------------------------------------------------
    // Custom-series renderer for one tick
    //
    // Renders each foreground bar as a <group> containing:
    //   1. A clipped, visible rect with a pixel floor (preserves the
    //      dense "rainfall" look).
    //   2. A transparent rect with a minimum width that absorbs
    //      pointer events (hover/click). The hit area is clipped to
    //      the plot rectangle so it never spills out of the chart.
    //
    // Background spans and aggregated bars keep a slightly larger
    // visual floor because they represent longer-lived activity.
    // ------------------------------------------------------------------
    function tickWidthSeconds(t) {
        const w = t && typeof t.w === 'number' ? t.w : 0;
        return Math.max(w, MIN_TICK_SECONDS);
    }

    function getTickTimeRange(...groups) {
        const starts = [];
        const ends = [];

        for (const group of groups) {
            for (const tick of group || []) {
                if (tick && tick.isBackground) continue;
                const v = tick && tick.value;
                if (!Array.isArray(v)) continue;
                if (typeof v[1] === 'number') starts.push(v[1]);
                if (typeof v[2] === 'number') ends.push(v[2]);
            }
        }

        if (!starts.length || !ends.length) return null;
        const min = Math.min(...starts);
        let max = Math.max(...ends);
        if (max <= min) max = min + MIN_TICK_SECONDS;
        return { min, max };
    }

    function renderTick(params, api) {
        const layout = currentLayout();
        const yIdx = api.value(0);
        const xStart = api.coord([api.value(1), yIdx])[0];
        const xEnd = api.coord([api.value(2), yIdx])[0];
        let color = api.value(3) || '#5470c6';
        const isBg = params.data && params.data.isBackground;
        const isAggregated = params.data && params.data.aggregatedCount > 1;
        // F-95 follow-up: per-category opacity. LLM_TEXT bars (which
        // span long assistant text/thinking periods) get a low opacity
        // so they read as a background layer and never visually
        // obscure the narrower tool-call chips that share the same
        // pixel range, even when the user zooms in to the maximum.
        const cat = api.value(7) || (params.data && params.data.category) || 'other';
        if (layout.reference) color = referenceColor(cat, color);
        const isOrchestrate = cat === 'orchestrate';
        let baseOpacity = OPACITY_BY_CAT[cat] != null ? OPACITY_BY_CAT[cat] : 0.95;
        if (isOrchestrate) baseOpacity = 0.34;
        const agentId = params.data && params.data.agentId;
        const isDimmed = selectedAgentId && agentId && selectedAgentId !== agentId;
        const isFocused = selectedAgentId && agentId && selectedAgentId === agentId;
        if (isDimmed) baseOpacity *= 0.32;

        const rowHeight = api.size([0, 1])[1] * (layout.rowScale || 1);
        const height = layout.reference
            ? Math.max(5, Math.min(22, rowHeight * (isBg ? 0.62 : (isOrchestrate ? 0.16 : 0.34))))
            : rowHeight * (isBg ? 0.55 : (isOrchestrate ? 0.14 : 0.28));
        const y = api.coord([0, yIdx])[1];
        const yOffset = isOrchestrate ? -rowHeight * (layout.reference ? 0.2 : 0.14) : 0;

        // ---- Visual width (thin rect) ----
        const visFloor = isBg ? 2 : (layout.reference ? 5 : VISIBLE_MIN_PX);
        const visWidth = Math.max(xEnd - xStart, visFloor);

        if (isBg) {
            return {
                type: 'rect',
                shape: {
                    x: xStart, y: y + yOffset - height / 2,
                    width: visWidth, height: height, r: 3,
                },
                style: {
                    fill: color,
                    opacity: isDimmed ? 0.18 : (layout.reference ? 0.52 : 0.65),
                    stroke: isFocused ? color : 'none',
                    lineWidth: isFocused ? 1 : 0,
                },
            };
        }

        // ---- Hit area (transparent min width, centered on bar) ----
        const xCenter = (xStart + xEnd) / 2;
        const hitW = Math.max(visWidth, HIT_MIN_PX);
        const hitX = xCenter - hitW / 2;
        const plotBox = {
            x: params.coordSys.x, y: params.coordSys.y,
            width: params.coordSys.width, height: params.coordSys.height,
        };
        const visRect = echarts.graphic.clipRectByRect({
            x: xStart, y: y - height / 2,
            width: visWidth, height: height, r: 1,
        }, plotBox);
        const hitRect = echarts.graphic.clipRectByRect({
            x: hitX, y: y - rowHeight * 0.24,
            width: hitW, height: rowHeight * 0.48, r: 1,
        }, plotBox);

        if (isOrchestrate) {
            const railH = 3;
            const railRect = echarts.graphic.clipRectByRect({
                x: xStart,
                y: y - rowHeight * 0.30,
                width: Math.max(xEnd - xStart, 12),
                height: railH,
                r: 1.5,
            }, plotBox);
            const handleRect = echarts.graphic.clipRectByRect({
                x: xStart - 2,
                y: y - rowHeight * 0.30 - 3,
                width: 5,
                height: railH + 6,
                r: 1.5,
            }, plotBox);
            return {
                type: 'group',
                silent: false,
                children: [
                    {
                        type: 'rect',
                        shape: railRect,
                        style: {
                        fill: color,
                        opacity: isDimmed ? 0.18 : (layout.reference ? 0.72 : 0.65),
                        shadowBlur: isFocused ? 6 : (layout.reference ? 3 : 2),
                        shadowColor: color,
                        },
                        emphasis: { style: { opacity: 1, stroke: '#fff', lineWidth: 1.2 } },
                    },
                    {
                        type: 'rect',
                        shape: handleRect,
                        style: {
                            fill: color,
                            opacity: isDimmed ? 0.25 : (layout.reference ? 0.9 : 0.85),
                            stroke: layout.reference ? 'rgba(151,177,205,0.38)' : 'rgba(255,255,255,0.6)',
                            lineWidth: 0.6,
                        },
                        silent: true,
                    },
                    {
                        type: 'rect',
                        shape: hitRect,
                        style: { fill: 'transparent' },
                        silent: false,
                        z: -1,
                    },
                ],
            };
        }

        return {
            type: 'group',
            silent: false,
            children: [
                {
                    type: 'rect',
                    shape: visRect,
                    style: {
                        fill: color,
                        opacity: isAggregated ? baseOpacity * 0.9 : baseOpacity,
                        stroke: isOrchestrate ? color : undefined,
                        lineWidth: isOrchestrate ? 0.6 : 0,
                        shadowBlur: isFocused ? 4 : (layout.reference ? 2 : 0),
                        shadowColor: color,
                    },
                    emphasis: { style: { opacity: 1, stroke: '#fff', lineWidth: 1.5 } },
                },
                {
                    type: 'rect',
                    shape: hitRect,
                    style: { fill: 'transparent' },
                    silent: false,
                    z: -1,
                },
            ].concat(_aggregatedBadge(params, xStart, xEnd, y, height, color)),
        };
    }

    function referenceColor(category, fallback) {
        const colors = {
            read: '#5f83ef',
            write: '#8acb3e',
            execute: '#d5a43b',
            orchestrate: '#c83f86',
            llm_text: '#526579',
            other: '#748394',
            span: '#33465c',
        };
        return colors[category] || fallback || '#748394';
    }

    /**
     * Build the ``+N`` corner badge for an aggregated bar. Returns an
     * empty array for non-aggregated bars so the caller can simply
     * ``.concat()`` the result. The badge is only drawn when the bar
     * is wide enough to fit it (>16px) so dense buckets stay readable.
     */
    function _aggregatedBadge(params, xStart, xEnd, y, height, color) {
        const aggCount = params.data && params.data.aggregatedCount;
        if (!aggCount || aggCount <= 1) return [];
        const barWidth = xEnd - xStart;
        if (barWidth < 16) return [];
        const label = `+${aggCount}`;
        // Font size scales gently with bar height so very thin rows stay
        // legible without overflowing.
        const fs = Math.max(7, Math.min(10, Math.floor(height * 0.5)));
        // Approx text width: 0.6em per char + 4px padding each side.
        const padX = 4;
        const approxW = label.length * fs * 0.6 + padX * 2;
        // Anchor the badge to the bar's top-right corner, but clamp to
        // the right edge so it doesn't spill past the visible bar.
        const badgeW = Math.min(approxW, barWidth - 2);
        const badgeH = fs + 2;
        const bx = xEnd - badgeW;
        const by = y - height / 2 + 1;
        return [
            {
                type: 'rect',
                shape: { x: bx, y: by, width: badgeW, height: badgeH, r: 2 },
                style: {
                    fill: 'rgba(0, 0, 0, 0.55)',
                    stroke: 'rgba(255, 255, 255, 0.7)',
                    lineWidth: 0.5,
                },
                silent: true,
                z: 2,
            },
            {
                type: 'text',
                style: {
                    text: label,
                    fill: '#ffffff',
                    font: `${fs}px ui-monospace, monospace`,
                    fontWeight: 600,
                    align: 'center',
                    verticalAlign: 'middle',
                    x: bx + badgeW / 2,
                    y: by + badgeH / 2,
                },
                silent: true,
                z: 3,
            },
        ];
    }

    // ------------------------------------------------------------------
    // Aggregation: collapse neighbouring ticks into wider bars
    //
    // Sort by x, then bucket by floor(x / bucketSize) * bucketSize.
    // Single-element buckets pass through unchanged so isolated turns
    // stay individually clickable. Aggregated buckets carry their
    // constituent ticks in `data.aggregated` for the drawer to list.
    // ------------------------------------------------------------------
    function densifyTicks(ticks, totalSpan, targetCount) {
        if (!Array.isArray(ticks) || ticks.length === 0) return ticks;
        const cap = Math.max(50, Math.min(targetCount || 400, ticks.length));
        if (ticks.length <= cap) return ticks;
        const bucket = totalSpan / cap;

        const sorted = ticks.slice().sort((a, b) => (a.value[1] || 0) - (b.value[1] || 0));
        const out = [];
        let buf = [];
        let bucketStart = Math.floor((sorted[0].value[1] || 0) / bucket) * bucket;

        const flush = () => {
            if (buf.length === 0) return;
            if (buf.length === 1) {
                out.push(buf[0]);
            } else {
                const first = buf[0];
                // Pick the most-frequent colour in the bucket; fall back
                // to a distinct "aggregated" purple.
                const colorCounts = new Map();
                for (const t of buf) {
                    const c = (t.value && t.value[3]) || '#9c7cff';
                    colorCounts.set(c, (colorCounts.get(c) || 0) + 1);
                }
                let pickColor = '#9c7cff';
                let pickCount = 0;
                for (const [c, n] of colorCounts) {
                    if (n > pickCount) { pickColor = c; pickCount = n; }
                }
                out.push({
                    value: [first.value[0], bucketStart, bucketStart + bucket,
                            pickColor, 'aggregated',
                            `${buf.length} turns`, `agg-${bucketStart.toFixed(2)}`,
                            (first.value && first.value[7]) || first.category || 'other'],
                    itemId: `agg-${bucketStart.toFixed(2)}`,
                    sessionId: first.sessionId,
                    agentId: first.agentId,
                    aggregatedCount: buf.length,
                    aggregated: buf.slice(),
                });
            }
            buf = [];
        };

        for (const t of sorted) {
            const xs = t.value[1] || 0;
            const bStart = Math.floor(xs / bucket) * bucket;
            if (bStart !== bucketStart) {
                flush();
                bucketStart = bStart;
            }
            buf.push(t);
        }
        flush();
        return out;
    }

    // ------------------------------------------------------------------
    // Density mode decision
    // ------------------------------------------------------------------
    function shouldDensify() {
        return getVisibleSec() > DETAIL_THRESHOLD_SEC;
    }
    function currentBucketCount() {
        // Aim for ~one bucket per 0.2s of visible range, clamped 50..600.
        const vis = getVisibleSec();
        const target = Math.round(vis / 0.2);
        return Math.max(50, Math.min(600, target));
    }
    // Returns the current visible window in the same coordinate system
    // as the tick data (t.x): { visMin, visMax, visSpan }.  null if the
    // chart hasn't been laid out yet.
    function getEffectiveRange() {
        if (!chart) return null;
        const opt = chart.getOption();
        const xAxis = opt && opt.xAxis && opt.xAxis[0];
        const dz = opt && opt.dataZoom && opt.dataZoom[0];
        if (!xAxis || xAxis.min == null || xAxis.max == null) return null;
        const min = xAxis.min || 0;
        const max = xAxis.max || 0;
        const start = (dz && typeof dz.start === 'number') ? dz.start : 0;
        const end = (dz && typeof dz.end === 'number') ? dz.end : 100;
        const span = max - min;
        return {
            visMin: min + span * start / 100,
            visMax: min + span * end / 100,
            visSpan: span * (end - start) / 100,
        };
    }
    function getVisibleSec() {
        const r = getEffectiveRange();
        return r ? r.visSpan : 0;
    }
    // Keep only ticks whose [xStart, xEnd] overlaps [visMin, visMax].
    function filterToRange(ticks, visMin, visMax) {
        if (!Array.isArray(ticks) || ticks.length === 0) return ticks;
        return ticks.filter(t => {
            const xStart = (t.value && t.value[1]) || 0;
            const xEnd = (t.value && t.value[2]) || (xStart + MIN_TICK_SECONDS);
            return xEnd >= visMin && xStart <= visMax;
        });
    }

    // ------------------------------------------------------------------
    // Side drawer — shows the clicked (or aggregated) turn's metadata.
    // The LLM I/O / Tool I/O / Session Records panels are intentionally
    // empty placeholders; downstream code can populate them by
    // listening for the 'turn-drawer:opened' CustomEvent.
    // ------------------------------------------------------------------
    function openTurnDrawer(meta) {
        const drawer = document.getElementById('turn-drawer');
        if (!drawer) return;
        const overview = document.getElementById('turn-drawer-overview');
        const title = document.getElementById('turn-drawer-title');
        const aggSection = document.getElementById('turn-drawer-aggregated');
        const aggList = document.getElementById('turn-drawer-agg-list');
        const aggCount = document.getElementById('turn-drawer-agg-count');
        if (!overview || !title) return;

        const aggregated = meta.aggregated;
        if (Array.isArray(aggregated) && aggregated.length > 1) {
            title.textContent = `${aggregated.length} Aggregated Turns`;
            aggSection.style.display = '';
            aggCount.textContent = `(${aggregated.length})`;
            aggList.innerHTML = aggregated.map(t => {
                const v = t.value;
                const id = t.itemId || (v && v[6]);
                const start = formatRelSec(v[1]);
                const end = formatRelSec(v[2] || (v[1] + MIN_TICK_SECONDS));
                return `<li class="turn-drawer-agg-item" data-item-id="${id}">
                    <span class="ms-dot" style="background:${v[3] || '#9c7cff'}"></span>
                    <span class="turn-drawer-agg-label">${escapeHtml(v[5] || id || 'turn')}</span>
                    <span class="turn-drawer-agg-time">${start} → ${end}</span>
                </li>`;
            }).join('');
            // Make each aggregated row clickable to drill in.
            for (const li of aggList.querySelectorAll('li')) {
                li.addEventListener('click', () => {
                    const id = li.dataset.itemId;
                    const t = aggregated.find(t2 => t2.itemId === id);
                    if (t) openTurnDrawer(buildTurnMeta(t));
                });
            }
        } else {
            title.textContent = meta.label || meta.turnId || 'Turn Detail';
            aggSection.style.display = 'none';
        }

        overview.innerHTML = `
            <dt>Session</dt><dd>${escapeHtml(meta.sessionId || '—')}</dd>
            <dt>Agent</dt><dd>${escapeHtml(meta.agentId || '—')}</dd>
            <dt>Turn ID</dt><dd>${escapeHtml(meta.turnId || '—')}</dd>
            <dt>Status</dt><dd>${escapeHtml(meta.status || '—')}</dd>
            <dt>Start (rel)</dt><dd>${formatRelSec(meta.startRel)}</dd>
            <dt>End (rel)</dt><dd>${formatRelSec(meta.endRel)}</dd>
            <dt>Duration</dt><dd>${(meta.endRel - meta.startRel).toFixed(2)}s</dd>
        `;

        drawer.classList.add('open');
        drawer.setAttribute('aria-hidden', 'false');

        renderLocalRecords(meta);
        renderLocalIo(meta);

        // Fetch LLM I/O (assistant message + tool result) for this turn.
        // Aggregated clicks drill into the first turn in the bucket; the
        // drawer also exposes the aggregated list so the user can pick
        // a different one — selecting a row re-opens the drawer with that
        // turn's id (see the click handlers below) and re-fetches here.
        _loadTurnIo(meta);

        // Extension hook for future async detail loaders.
        try {
            window.dispatchEvent(new CustomEvent('turn-drawer:opened', { detail: meta }));
        } catch (e) { /* CustomEvent unavailable in very old browsers */ }
        if (typeof window.__loadTurnDetail === 'function') {
            try { window.__loadTurnDetail(meta); } catch (e) { /* swallow */ }
        }
    }

    /**
     * Fetch ``/api/viz/turn/{session_id}__{turn_id}/llm-io`` and render
     * the result into ``#turn-drawer-llm``. Three states:
     *   - loading: shows a spinner / "Loading…" line
     *   - success: input + output blocks rendered as labeled <details>
     *   - error  : a short error line with the status code
     * The function never throws — fetch/network failures are surfaced
     * inline so the rest of the drawer keeps working.
     */
    async function _loadTurnLlmIo(meta) {
        const section = document.getElementById('turn-drawer-llm');
        if (!section) return;
        const sessionId = meta && meta.sessionId;
        const turnId = meta && meta.turnId;
        if (!sessionId || !turnId) {
            section.innerHTML = '<div class="turn-drawer-empty">'
                + 'No turn id — pick a turn from the chart.</div>';
            return;
        }
        section.innerHTML = '<div class="turn-drawer-loading">'
            + '<span class="turn-drawer-spinner"></span> Loading LLM I/O…</div>';
        const url = `/api/viz/turn/${encodeURIComponent(sessionId)}__`
                  + `${encodeURIComponent(turnId)}/llm-io`;
        try {
            const resp = await fetch(url, { headers: { 'Accept': 'application/json' } });
            if (!resp.ok) {
                let detail = `HTTP ${resp.status}`;
                try {
                    const body = await resp.json();
                    if (body && body.detail) detail = body.detail;
                } catch (_) { /* ignore body parse */ }
                section.innerHTML = `<div class="turn-drawer-error">`
                    + `<strong>Failed to load LLM I/O</strong><br/>`
                    + `<span>${escapeHtml(detail)}</span></div>`;
                return;
            }
            const payload = await resp.json();
            section.innerHTML = _renderLlmIoHtml(payload);
        } catch (e) {
            section.innerHTML = `<div class="turn-drawer-error">`
                + `<strong>Network error</strong><br/>`
                + `<span>${escapeHtml(String(e && e.message || e))}</span></div>`;
        }
    }

    /**
     * Render the LLM I/O payload as collapsible sections: "Input"
     * (the assistant message that issued the tool call) and "Output"
     * (the tool message that returned the result). Long strings are
     * truncated server-side so the drawer stays light.
     */
    function _renderLlmIoHtml(payload) {
        if (!payload) return '<div class="turn-drawer-empty">Empty response</div>';
        const blocks = [];
        blocks.push(`<div class="turn-drawer-llm-meta">`
            + `<span class="turn-drawer-llm-session">${escapeHtml(payload.session_id || '—')}</span>`
            + ` · turn <code>${escapeHtml(payload.turn_id || '—')}</code></div>`);
        if (payload.input) {
            blocks.push('<details class="turn-drawer-llm-block" open>'
                + '<summary>Input <small>(assistant → tool call)</small></summary>'
                + _renderContentBlocks(payload.input.content_blocks || [])
                + '</details>');
        } else {
            blocks.push('<div class="turn-drawer-empty">'
                + 'No input message found for this turn.</div>');
        }
        if (payload.output) {
            blocks.push('<details class="turn-drawer-llm-block" open>'
                + '<summary>Output <small>(tool result)</small></summary>'
                + _renderContentBlocks(payload.output.content_blocks || [])
                + '</details>');
        } else {
            blocks.push('<div class="turn-drawer-empty">'
                + 'No output message found for this turn.</div>');
        }
        return blocks.join('');
    }

    function _renderContentBlocks(blocks) {
        if (!blocks.length) return '<div class="turn-drawer-empty">(empty)</div>';
        return blocks.map(b => {
            const t = b.type || 'block';
            if (t === 'text') {
                return `<div class="turn-drawer-llm-text">`
                    + `<pre>${escapeHtml(b.text || '')}</pre></div>`;
            }
            if (t === 'tool_use') {
                return `<div class="turn-drawer-llm-tool-use">`
                    + `<div class="turn-drawer-llm-tag">tool_use · ${escapeHtml(b.name || '?')}`
                    + ` · id=${escapeHtml(b.id || '')}</div>`
                    + `<pre>${escapeHtml(JSON.stringify(b.input || {}, null, 2))}</pre>`
                    + `</div>`;
            }
            if (t === 'tool_result') {
                return `<div class="turn-drawer-llm-tool-result">`
                    + `<div class="turn-drawer-llm-tag">tool_result`
                    + ` · tool_use_id=${escapeHtml(b.tool_use_id || '')}`
                    + (b.is_error ? ' · <em>error</em>' : '')
                    + `</div>`
                    + `<pre>${escapeHtml(typeof b.content === 'string' ? b.content : JSON.stringify(b.content, null, 2))}</pre>`
                    + `</div>`;
            }
            if (t === 'tool_call_legacy') {
                const fn = b.function || {};
                return `<div class="turn-drawer-llm-tool-use">`
                    + `<div class="turn-drawer-llm-tag">tool_call_legacy`
                    + ` · ${escapeHtml(fn.name || '?')}`
                    + ` · id=${escapeHtml(b.id || '')}</div>`
                    + `<pre>${escapeHtml(JSON.stringify(fn.arguments || {}, null, 2))}</pre>`
                    + `</div>`;
            }
            // Generic block — render as JSON so nothing is silently dropped.
            return `<div class="turn-drawer-llm-generic">`
                + `<div class="turn-drawer-llm-tag">${escapeHtml(t)}</div>`
                + `<pre>${escapeHtml(JSON.stringify(b, null, 2))}</pre>`
                + `</div>`;
        }).join('');
    }

    function _renderToolIoHtml(payload, meta) {
        const inputBlocks = ((payload && payload.input && payload.input.content_blocks) || [])
            .filter(b => b && (b.type === 'tool_use' || b.type === 'tool_call_legacy'));
        const outputBlocks = ((payload && payload.output && payload.output.content_blocks) || [])
            .filter(b => b && b.type === 'tool_result');
        const cards = [];

        if (inputBlocks.length) {
            cards.push(...inputBlocks.map(b => renderToolInputCard(b)));
        } else if (meta && meta.detail && Object.keys(meta.detail).length) {
            cards.push(renderLocalToolCard(meta));
        }

        if (outputBlocks.length) {
            cards.push(...outputBlocks.map(b => renderToolOutputCard(b)));
        }

        return cards.length
            ? cards.join('')
            : '<div class="turn-drawer-empty">No tool input/output found for this item.</div>';
    }

    function renderLocalIo(meta) {
        const llmSection = document.getElementById('turn-drawer-llm');
        const toolSection = document.getElementById('turn-drawer-tools');
        const detail = (meta && meta.detail) || {};
        const barType = meta && meta.barType;

        if (llmSection) {
            if (detail.text_preview) {
                llmSection.innerHTML = renderTextCard('Preview', detail.text_preview);
            } else if (barType === 'custom' && meta.label) {
                llmSection.innerHTML = renderTextCard('Message', meta.label);
            } else {
                llmSection.innerHTML = '<div class="turn-drawer-empty">No LLM text preview for this item.</div>';
            }
        }

        if (toolSection) {
            if (detail.params || detail.tool_use_id || barType === 'tool_call') {
                toolSection.innerHTML = renderLocalToolCard(meta);
            } else if (detail.excerpt) {
                toolSection.innerHTML = renderTextCard('Tool result preview', detail.excerpt);
            } else {
                toolSection.innerHTML = '<div class="turn-drawer-empty">No tool input/output for this item.</div>';
            }
        }
    }

    function hasLocalLlmPreview(meta) {
        const detail = (meta && meta.detail) || {};
        return Boolean(detail.text_preview || ((meta && meta.barType) === 'custom' && meta.label));
    }

    function renderLocalRecords(meta) {
        const recordsSection = document.getElementById('turn-drawer-records');
        if (!recordsSection) return;

        const detail = (meta && meta.detail) || {};
        const record = {
            source: 'chart',
            sessionId: meta && meta.sessionId,
            agentId: meta && meta.agentId,
            turnId: meta && meta.turnId,
            toolUseId: meta && meta.toolUseId,
            type: meta && meta.barType,
            label: meta && meta.label,
            status: meta && meta.status,
            startRel: meta && meta.startRel,
            endRel: meta && meta.endRel,
            detail,
        };

        recordsSection.innerHTML = renderRecordCard('Chart record', record);
    }

    function renderSessionRecords(payload, meta) {
        const recordsSection = document.getElementById('turn-drawer-records');
        if (!recordsSection) return;

        const cards = [renderRecordCard('Chart record', {
            source: 'chart',
            sessionId: meta && meta.sessionId,
            turnId: meta && meta.turnId,
            toolUseId: meta && meta.toolUseId,
            type: meta && meta.barType,
            label: meta && meta.label,
            status: meta && meta.status,
            startRel: meta && meta.startRel,
            endRel: meta && meta.endRel,
            detail: meta && meta.detail,
        })];

        if (payload && payload.input) {
            cards.push(renderRecordCard('Transcript input record', compactMessageRecord(payload.input)));
        }
        if (payload && payload.output) {
            cards.push(renderRecordCard('Transcript output record', compactMessageRecord(payload.output)));
        }

        recordsSection.innerHTML = cards.join('');
    }

    function compactMessageRecord(message) {
        const blocks = (message && message.content_blocks) || [];
        return {
            role: message && message.role,
            name: message && message.name,
            timestamp: (message && (message.timestamp || message._timestamp)) || '',
            toolCallId: message && message.tool_call_id,
            content: blocks.map(compactBlockRecord),
        };
    }

    function compactBlockRecord(block) {
        if (!block) return {};
        if (block.type === 'text') {
            return { type: 'text', text: block.text || '' };
        }
        if (block.type === 'tool_use') {
            return {
                type: 'tool_use',
                id: block.id || '',
                name: block.name || '',
                input: block.input || {},
            };
        }
        if (block.type === 'tool_result') {
            return {
                type: 'tool_result',
                tool_use_id: block.tool_use_id || '',
                is_error: !!block.is_error,
                content: block.content || '',
            };
        }
        if (block.type === 'tool_call_legacy') {
            return {
                type: 'tool_call_legacy',
                id: block.id || '',
                function: block.function || {},
            };
        }
        return block;
    }

    function renderRecordCard(title, record) {
        return renderIoCard(title, record && record.role ? `role=${record.role}` : '', '', record || {});
    }

    function _renderLlmIoHtml(payload) {
        if (!payload) return '<div class="turn-drawer-empty">Empty response</div>';
        const inputText = textLikeBlocks(payload.input && payload.input.content_blocks);
        const outputText = textLikeBlocks(payload.output && payload.output.content_blocks);
        const cards = [];
        if (inputText.length) cards.push(renderTextCard('LLM input/context', inputText.join('\n\n')));
        if (outputText.length) cards.push(renderTextCard('LLM output', outputText.join('\n\n')));
        return cards.length
            ? cards.join('')
            : '<div class="turn-drawer-empty">No text blocks found; see Tool I/O for call details.</div>';
    }

    function textLikeBlocks(blocks) {
        return (blocks || [])
            .filter(b => b && b.type === 'text' && b.text)
            .map(b => b.text);
    }

    function renderToolInputCard(block) {
        if (block.type === 'tool_call_legacy') {
            const fn = block.function || {};
            return renderIoCard('Tool input', fn.name || 'tool', block.id || '', fn.arguments || {});
        }
        return renderIoCard('Tool input', block.name || 'tool', block.id || '', block.input || {});
    }

    function renderToolOutputCard(block) {
        return renderIoCard(
            block.is_error ? 'Tool output (error)' : 'Tool output',
            'result',
            block.tool_use_id || '',
            block.content || ''
        );
    }

    function renderLocalToolCard(meta) {
        const detail = (meta && meta.detail) || {};
        return renderIoCard('Tool input', meta.label || meta.barType || 'tool', detail.tool_use_id || meta.toolUseId || '', detail.params || detail);
    }

    function renderTextCard(title, text) {
        return renderIoCard(title, '', '', text || '');
    }

    function renderIoCard(title, name, id, body) {
        const heading = [name, id ? `id=${id}` : ''].filter(Boolean).join(' · ');
        return `<div class="turn-drawer-io-card">
            <div class="turn-drawer-io-title">${escapeHtml(title)}</div>
            ${heading ? `<div class="turn-drawer-io-meta">${escapeHtml(heading)}</div>` : ''}
            <pre>${escapeHtml(formatIoBody(body))}</pre>
        </div>`;
    }

    function formatIoBody(body) {
        if (body == null || body === '') return '(empty)';
        if (typeof body === 'string') return body;
        try {
            return JSON.stringify(body, null, 2);
        } catch (_) {
            return String(body);
        }
    }

    function uniqueTruthy(values) {
        return [...new Set((values || []).filter(v => v != null && String(v).trim() !== '').map(String))];
    }

    function transcriptLookupIds(meta) {
        if (!meta) return [];
        const ids = [meta.toolUseId];
        const turnId = meta.turnId ? String(meta.turnId) : '';
        if (turnId.startsWith('call_') || meta.barType === 'tool_call' || meta.barType === 'tool_result') {
            ids.push(turnId);
        }
        return uniqueTruthy(ids);
    }

    function appendIoHint(section, message) {
        if (!section || !message) return;
        section.insertAdjacentHTML('beforeend',
            `<div class="turn-drawer-error"><span>${escapeHtml(message)}</span></div>`);
    }

    function closeTurnDrawer() {
        const drawer = document.getElementById('turn-drawer');
        if (!drawer) return;
        drawer.classList.remove('open');
        drawer.setAttribute('aria-hidden', 'true');
    }

    function buildTurnMeta(t) {
        const v = t.value || [];
        return {
            sessionId: t.sessionId || null,
            agentId: t.agentId || null,
            turnId: t.itemId || v[6] || null,
            startRel: v[1],
            endRel: v[2] || (v[1] + MIN_TICK_SECONDS),
            color: v[3],
            status: v[4],
            label: v[5],
            aggregated: t.aggregated,
            isBackground: t.isBackground,
            barType: t.barType || null,
            detail: t.detail || null,
            toolUseId: t.toolUseId || (t.detail && t.detail.tool_use_id) || null,
        };
    }

    function formatRelSec(sec) {
        if (typeof sec !== 'number' || !isFinite(sec)) return '—';
        const a = Math.abs(sec);
        if (a < 60) {
            return `${Math.round(a)}s`;
        }
        const minutes = Math.floor(a / 60);
        if (minutes < 60) {
            return `${minutes}分钟`;
        }
        const h = Math.floor(minutes / 60);
        const m = minutes % 60;
        return `${h}小时${m}分钟`;
    }

    function escapeHtml(s) {
        if (s == null) return '';
        return String(s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    // Expose the drawer API on window so inline onclick handlers
    // (and downstream feature code) can call it.
    window.openTurnDrawer = openTurnDrawer;
    window.closeTurnDrawer = closeTurnDrawer;

    // ------------------------------------------------------------------
    // Badge / label overlay
    //
    // Modeled as a custom series ('badges') so the pills are part of
    // the main option and survive `setOption(option, true)`. Earlier
    // the pills were added via `chart.setOption({graphic:{...}})`
    // inside a 'finished' handler; that approach suffered from three
    // problems:
    //   1. `notMerge: true` cleared the graphic elements before the
    //      'finished' handler had a chance to re-add them.
    //   2. The 'finished' event does not fire reliably on re-renders
    //      when `animation: false`, so the pills would stay cleared
    //      (this is the bug: clicking a sub-agent swimlane caused
    //      the title pills to disappear).
    //   3. The two setOption calls in attachBadges (clear + re-add)
    //      were batched by ECharts and could collapse to the empty
    //      state on some code paths.
    //
    // Putting pills in a custom series fixes all three: the series is
    // re-rendered as part of the main option, `renderItem` runs after
    // ECharts has finished layout so `api.coord()` is valid, and
    // `clip:false` lets the gutter pills render outside the plot area.
    // ------------------------------------------------------------------
    function buildBadgeData(sessions, agents, yIndex) {
        // Every field the renderer needs is stuffed into the `value`
        // array. ECharts 5.x custom series with `encode` rebuilds
        // `params.data` from the internal DataStore, dropping any
        // extra fields we put on the data object. Stuffing everything
        // into the value tuple is the only reliable way to round-trip
        // data through the encode pipeline.
        //
        // Index layout per kind:
        //   model     [yi, 0,    'model',     active,     sessionName, totalOps, agentType, contextSize]
        //   agent     [yi, 0,    'agent',     agentId,    role, title, count, roleColor, score, scoreLabel]
        //   endmarker [yi, xData,'endmarker', timeLabel,  statusLabel]
        //   spawn     [yi, xData,'spawn',      label]
        const data = [];
        badgePayloads = [];
        const pushBadge = (yi, x, payload) => {
            const idx = badgePayloads.push(payload) - 1;
            data.push({ value: [yi, x, idx] });
        };
        for (const s of sessions) {
            const yi = yIndex.get(sessionLabel(s));
            if (typeof yi !== 'number') continue;
            const active = s.y === 0 ? 1 : 0;
            const sessionName = s.name || s.id.slice(0, 8);
            pushBadge(yi, 0, {
                kind: 'model',
                active,
                sessionName,
                totalOps: s.totalOps || 0,
                agentType: s.agentType || '',
                contextSize: s.contextSize || '',
            });
            if (s.endMarker) {
                pushBadge(yi, s.endMarker.x, {
                    kind: 'endmarker',
                    timeLabel: s.endMarker.timeLabel || '',
                    statusLabel: s.endMarker.statusLabel || s.endMarker.label || '',
                });
            }
            if (s.spawnCallout) {
                pushBadge(yi, s.spawnCallout.x, {
                    kind: 'spawn',
                    label: s.spawnCallout.label || '',
                });
            }
        }
        for (const a of agents) {
            const yi = yIndex.get(agentLabel(a));
            if (typeof yi !== 'number') continue;
            pushBadge(yi, a.joinX || a.spawnX || 0, {
                kind: 'agent',
                agentId: a.id,
                role: a.role || '执行',
                title: a.title || '',
                count: a.count || 0,
                roleColor: a.roleColor || '#3b82f6',
                score: a.score != null ? a.score : '',
                scoreLabel: a.scoreLabel || a.title || '',
            });
        }
        return data;
    }

    function renderBadge(params, api) {
        const yIdx = api.value(0);
        const xData = api.value(1);
        const raw = badgePayloads[api.value(2)] || {};
        const kind = raw.kind;
        const layout = currentLayout();
        const yPx = api.coord([0, yIdx])[1];

        if (kind === 'model') {
            const active = raw.active != null ? raw.active : api.value(3) === 1;
            const sessionName = String(raw.sessionName || api.value(4) || '');
            const totalOps = raw.totalOps || api.value(5) || 0;
            const agentType = String(raw.agentType || api.value(6) || '');
            const contextSize = String(raw.contextSize || api.value(7) || '');
            const GUTTER_RIGHT = layout.badgeX;
            const pillW = layout.modelWidth;
            const metaParts = [];
            if (totalOps) metaParts.push(`${totalOps} 工具调用`);
            if (agentType) metaParts.push(agentType);
            if (contextSize) metaParts.push(`上下文 ${contextSize}`);
            const metaText = metaParts.join(' · ');
            return {
                type: 'group',
                position: [GUTTER_RIGHT, yPx - 10],
                silent: true,
                children: [
                    {
                        type: 'rect',
                        shape: { x: 0, y: 0, width: pillW, height: 20, r: 10 },
                        style: {
                            fill: layout.reference ? 'rgba(17, 29, 42, 0.06)' : (active ? 'rgba(88,166,255,0.12)' : 'rgba(22,27,34,0.6)'),
                            stroke: layout.reference ? 'rgba(255,255,255,0)' : (active ? 'rgba(88,166,255,0.4)' : 'rgba(48,54,61,0.5)'),
                            lineWidth: layout.reference ? 0 : (active ? 1 : 0.8),
                            shadowBlur: layout.reference ? 0 : (active ? 4 : 0),
                            shadowColor: 'rgba(88,166,255,0.25)',
                        },
                        silent: true,
                    },
                    {
                        type: 'text',
                        style: {
                            text: truncateVisual(sessionName, layout.compact ? 10 : 24),
                            fill: layout.reference ? 'rgba(201,211,224,0)' : '#c9d1d9',
                            fontSize: layout.reference ? 1 : 11,
                            fontWeight: 600,
                            x: 10, y: 10,
                        },
                        silent: true,
                    },
                    metaText ? {
                        type: 'text',
                        style: {
                            text: metaText,
                            fill: '#8b949e',
                            fontSize: 10,
                            x: pillW + 12, y: 10,
                        },
                        silent: true,
                    } : null,
                ].filter(Boolean),
            };
        }

        if (kind === 'agent') {
            const agentId = raw.agentId || api.value(3);
            const role = String(raw.role || api.value(4) || '执行');
            const title = String(raw.title || api.value(5) || '');
            const count = raw.count || api.value(6) || 0;
            const roleColor = String(raw.roleColor || api.value(7) || '#58a6ff');
            const score = raw.score != null ? raw.score : api.value(8);
            const scoreLabel = String(raw.scoreLabel || api.value(9) || title);
            const xPx = api.coord([xData, yIdx])[0];
            const GUTTER_RIGHT = layout.reference
                ? Math.max(layout.gridLeft + 4, Math.min(xPx + 12, params.coordSys.x + params.coordSys.width - 310))
                : layout.badgeX;
            const active = !selectedAgentId || selectedAgentId === agentId;
            const dimmed = selectedAgentId && selectedAgentId !== agentId;
            return {
                type: 'group',
                position: [GUTTER_RIGHT, yPx - (layout.reference ? 10 : 7)],
                silent: false,
                children: [
                    {
                        type: 'rect',
                        shape: { x: 0, y: 0, width: layout.agentRoleWidth, height: layout.reference ? 20 : 16, r: layout.reference ? 4 : 8 },
                        style: {
                            fill: layout.reference ? 'rgba(177, 40, 102, 0.52)' : roleColor,
                            opacity: active ? (layout.reference ? 0.95 : 0.15) : 0.06,
                            stroke: layout.reference ? 'rgba(202, 65, 132, 0.72)' : roleColor,
                            lineWidth: active ? (layout.reference ? 0.6 : 1) : 0.5,
                            shadowBlur: active ? (layout.reference ? 8 : 4) : 0,
                            shadowColor: roleColor,
                        },
                        silent: true,
                    },
                    {
                        type: 'text',
                        style: {
                            text: truncateVisual(role, layout.compact ? 4 : 8),
                            fill: layout.reference ? '#f1a6ce' : roleColor,
                            fontSize: layout.reference ? 12 : 9,
                            fontWeight: 700,
                            opacity: dimmed ? 0.4 : 1,
                            x: layout.reference ? 9 : 8,
                            y: layout.reference ? 10 : 8,
                        },
                        silent: true,
                    },
                    {
                        type: 'text',
                        style: {
                            text: truncateVisual(scoreLabel, layout.agentTitleVisual),
                            fill: layout.reference ? '#9ba9ba' : '#c9d1d9',
                            fontSize: layout.reference ? 15 : 10,
                            fontWeight: active ? (layout.reference ? 700 : 600) : 400,
                            opacity: dimmed ? 0.4 : 1,
                            x: layout.agentTitleX,
                            y: layout.reference ? 10 : 8,
                        },
                        silent: true,
                    },
                    score !== '' ? {
                        type: 'text',
                        style: {
                            text: String(score),
                            fill: layout.reference ? '#8290a0' : '#8b949e',
                            fontSize: layout.reference ? 13 : 10,
                            fontVariantNumeric: 'tabular-nums',
                            opacity: dimmed ? 0.4 : 1,
                            x: layout.agentCountX,
                            y: layout.reference ? 10 : 8,
                        },
                        silent: true,
                    } : null,
                ].filter(Boolean),
            };
        }

        if (kind === 'endmarker') {
            const xEnd = api.coord([xData, yIdx])[0];
            const modelPillRight = layout.gridLeft;
            const xPos = (xEnd < modelPillRight) ? modelPillRight : (xEnd + 8);
            const timeLabel = String(raw.timeLabel || api.value(3) || '');
            const statusLabel = String(raw.statusLabel || api.value(4) || '');
            return {
                type: 'group',
                position: [xPos, yPx - 7],
                silent: true,
                children: [
                    {
                        type: 'circle',
                        shape: { cx: 0, cy: 7, r: layout.reference ? 0 : 3.5 },
                        style: { fill: '#3fb950', opacity: layout.reference ? 0 : 1 },
                        silent: true,
                    },
                    timeLabel ? {
                        type: 'text',
                        style: {
                            text: timeLabel,
                            fill: layout.reference ? '#c2ccd7' : '#c9d1d9',
                            fontSize: layout.reference ? 14 : 10,
                            x: 9, y: 0,
                        },
                        silent: true,
                    } : null,
                    statusLabel ? {
                        type: 'text',
                        style: {
                            text: statusLabel,
                            fill: layout.reference ? '#8190a0' : '#8b949e',
                            fontSize: layout.reference ? 14 : 10,
                            x: 9 + (timeLabel ? timeLabel.length * 6 : 0), y: 0,
                        },
                        silent: true,
                    } : null,
                ].filter(Boolean),
            };
        }

        if (kind === 'spawn') {
            const xPx = api.coord([xData, yIdx])[0];
            const PILL_W = layout.reference ? 328 : (layout.compact ? 150 : 200);
            const xClamped = Math.max(layout.gridLeft + 8, xPx - PILL_W / 2);
            const topY = layout.reference ? Math.max(91, yPx + 28) : Math.max(8, yPx - 124);
            const label = String(raw.label || api.value(3) || '');
            return {
                type: 'group',
                position: [xClamped, topY],
                silent: true,
                children: [{
                    type: 'rect',
                    shape: { x: 0, y: 0, width: PILL_W, height: layout.reference ? 36 : 20, r: layout.reference ? 6 : 5 },
                    style: {
                        fill: layout.reference ? 'rgba(42, 50, 98, 0.56)' : 'rgba(22, 27, 34, 0.94)',
                        stroke: layout.reference ? 'rgba(91, 112, 222, 0.65)' : '#ea7ccc',
                        lineWidth: layout.reference ? 2 : 0.8,
                        shadowBlur: layout.reference ? 10 : 6,
                        shadowColor: layout.reference ? 'rgba(91,112,222,0.35)' : 'rgba(234,124,204,0.3)',
                    },
                    silent: true,
                }, {
                    type: 'text',
                    style: {
                        text: layout.reference ? label : label,
                        fill: layout.reference ? '#8fa0f4' : '#f2b7df',
                        fontSize: layout.reference ? 16 : 10,
                        fontWeight: 800,
                        x: layout.reference ? 18 : 10,
                        y: layout.reference ? 18 : 10,
                    },
                    silent: true,
                }],
            };
        }

        return { type: 'group', children: [], silent: true };
    }

    function buildLaneData(sessions, agents, yIndex, yCategories, timeRange) {
        const xMin = timeRange.min || 0;
        const xMax = timeRange.max || Math.max(60, xMin + 60);
        const perSession = new Map();
        for (const s of sessions) perSession.set(s.id, []);
        for (const a of agents) {
            if (perSession.has(a.parentSessionId)) perSession.get(a.parentSessionId).push(a);
        }
        const lanes = [];
        for (const s of sessions) {
            const yi = yIndex.get(sessionLabel(s));
            const children = perSession.get(s.id) || [];
            const maxChildY = children.length
                ? Math.max(...children.map(a => yIndex.get(agentLabel(a))).filter(v => typeof v === 'number'))
                : yi;
            lanes.push({
                value: [yi, xMin, xMax, '#5470c6', 1],
                sessionId: s.id,
                isSessionLane: true,
                childCount: children.length,
                groupTop: yi,
                groupBottom: maxChildY,
                active: !selectedAgentId,
            });
        }
        for (const a of agents) {
            const yi = yIndex.get(agentLabel(a));
            const color = a.roleColor || '#5470c6';
            lanes.push({
                value: [yi, xMin, xMax, color, 0],
                sessionId: a.parentSessionId || null,
                agentId: a.id,
                role: a.role || '执行',
                active: !selectedAgentId || selectedAgentId === a.id,
                dimmed: selectedAgentId && selectedAgentId !== a.id,
            });
        }
        return lanes.filter(l => typeof l.value[0] === 'number');
    }

    function renderLane(params, api) {
        const layout = currentLayout();
        const yIdx = api.value(0);
        const xStart = api.coord([api.value(1), yIdx])[0];
        const xEnd = api.coord([api.value(2), yIdx])[0];
        const y = api.coord([0, yIdx])[1];
        const rowH = api.size([0, 1])[1] * (layout.rowScale || 1);
        const color = api.value(3) || '#5470c6';
        const isSession = !!api.value(4);
        const data = params.data || {};
        const height = layout.reference
            ? Math.max(18, Math.min(31, rowH * (isSession ? 0.7 : 0.68)))
            : Math.max(16, rowH * (isSession ? 0.78 : 0.68));
        const opacity = data.dimmed ? 0.06 : (isSession ? (layout.reference ? 0.06 : 0.08) : (layout.reference ? 0.12 : 0.04));
        const borderOpacity = data.active ? 0.5 : 0.12;
        const children = [{
            type: 'rect',
            shape: { x: xStart, y: y - height / 2, width: xEnd - xStart, height, r: layout.reference ? 4 : (isSession ? 4 : 3) },
            style: {
                fill: isSession
                    ? (layout.reference ? 'rgba(38, 57, 76, 0.28)' : 'rgba(88,166,255,0.05)')
                    : (layout.reference ? 'rgba(51, 67, 86, 0.72)' : 'rgba(255,255,255,0.015)'),
                opacity,
                stroke: data.active
                    ? (isSession
                        ? (layout.reference ? 'rgba(81,103,128,0.38)' : 'rgba(88,166,255,0.18)')
                        : (layout.reference ? 'rgba(101,121,145,0.28)' : color))
                    : 'rgba(139,148,158,0.12)',
                lineWidth: data.active ? (isSession ? 0.6 : (layout.reference ? 0.5 : 0.8)) : 0.3,
                shadowBlur: data.active && !isSession ? (layout.reference ? 2 : 4) : 0,
                shadowColor: color,
            },
            silent: isSession,
        }];
        if (!isSession && !layout.reference) {
            children.push({
                type: 'rect',
                shape: { x: xStart + 1, y: y - height / 2 + 2, width: 2, height: height - 4, r: 1 },
                style: { fill: color, opacity: borderOpacity },
                silent: true,
            });
        }
        return { type: 'group', children, silent: isSession };
    }

    function renderBranch(params, api) {
        const layout = currentLayout();
        const fromY = api.value(0);
        const fromX = api.value(1);
        const toX = api.value(2);
        const toY = api.value(3);
        const kind = api.value(4);
        const p1 = api.coord([fromX, fromY]);
        const p2 = api.coord([toX, toY]);
        const data = params.data || {};
        const active = !selectedAgentId || selectedAgentId === data.agentId;
        const color = data.color || (kind === 'join' ? '#7aa2ff' : '#ea7ccc');
        const dx = layout.reference
            ? Math.max(42, Math.min(135, Math.abs(p2[1] - p1[1]) * 0.72))
            : Math.max(34, Math.min(92, Math.abs(p2[1] - p1[1]) * 0.5));
        const dir = kind === 'join' ? -1 : 1;
        const cpx = p1[0] + dir * dx;
        return {
            type: 'group',
            children: [
                {
                    type: 'bezierCurve',
                    shape: {
                        x1: p1[0],
                        y1: p1[1],
                        x2: p2[0],
                        y2: p2[1],
                        cpx1: cpx,
                        cpy1: p1[1],
                        cpx2: cpx,
                        cpy2: p2[1],
                    },
                    style: {
                        stroke: color,
                        fill: null,
                        lineWidth: active ? (layout.reference ? 1.8 : 1.5) : 0.7,
                        opacity: active ? (layout.reference ? 0.46 : 0.6) : 0.15,
                        shadowBlur: active ? (layout.reference ? 7 : 4) : 0,
                        shadowColor: color,
                    },
                },
                {
                    type: 'circle',
                    shape: { cx: p2[0], cy: p2[1], r: active ? (layout.reference ? 3.8 : 2.8) : 2 },
                    style: {
                        fill: color,
                        opacity: active ? 0.75 : 0.2,
                    },
                },
            ],
        };
    }

    function edgeStyle(agentId, edgeType) {
        const active = !selectedAgentId || selectedAgentId === agentId;
        return {
            color: edgeType === 'join' ? '#7aa2ff' : '#ea7ccc',
            width: active ? 2 : 0.8,
            curveness: edgeType === 'join' ? 0.26 : 0.34,
            opacity: active ? 0.8 : 0.15,
            shadowBlur: active ? 4 : 0,
            shadowColor: edgeType === 'join' ? 'rgba(122,162,255,0.45)' : 'rgba(234,124,204,0.45)',
        };
    }

    function truncateVisual(value, maxVisual) {
        let visual = 0;
        let out = '';
        for (const ch of String(value || '')) {
            const w = /[\u4e00-\u9fa5\uff00-\uffef]/.test(ch) ? 2 : 1;
            if (visual + w > maxVisual) return out + '…';
            out += ch;
            visual += w;
        }
        return out;
    }

    // ------------------------------------------------------------------
    // Row label helpers (must match server-side y layout)
    // ------------------------------------------------------------------
    function sessionLabel(s) {
        // Truncate to fit y axis
        return (s.name || s.id.slice(0, 8)).slice(0, 24);
    }
    function agentLabel(a) {
        return `${a.role || '执行'}/${a.title || ''}`.slice(0, 24);
    }
    function buildYCategories(sessions, agents) {
        // Replicate server's renumbering: session at y=i, its agents follow at y=i+1..i+k
        const out = [];
        // Stable order: sessions in input order, agents grouped & sorted by parent + spawnX
        const perSession = new Map();
        for (const s of sessions) perSession.set(s.id, []);
        for (const a of agents) {
            if (perSession.has(a.parentSessionId)) {
                perSession.get(a.parentSessionId).push(a);
            }
        }
        for (const s of sessions) {
            out.push(sessionLabel(s));
            const subs = perSession.get(s.id) || [];
            subs.sort((a, b) => (a.spawnX || 0) - (b.spawnX || 0));
            for (const a of subs) out.push(agentLabel(a));
        }
        return out;
    }

    return { init };
})();

// Public entry point used by multi_session.html inline script and
// session_row.html (single-session waterfall).
async function initMultiSessionView(sessionIds, options) {
    return MultiSessionView.init(sessionIds, options);
}
