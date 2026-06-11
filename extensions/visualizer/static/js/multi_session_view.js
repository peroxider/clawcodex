/**
 * ClawCodex Visualizer — Multi-Session Waterfall View (F-95)
 *
 * Renders the JSON payload from /api/viz/multi-session into an ECharts
 * custom-series chart that matches the reference layout:
 *   - top: 5-pill legend with counts
 *   - left: time axis (relative, e.g. 0/5/10/15/20/25/30 min)
 *   - rows: each session gets a swimlane, sub-agents cascade below
 *   - activity ticks: dense color-coded vertical bars
 *   - fork/join: pink curved lines between parent and sub-agents
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
    const HIT_MIN_PX = 10;
    const VISIBLE_MIN_PX = 8;
    const MIN_TICK_SECONDS = 0.001;
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

    // ------------------------------------------------------------------
    // Main chart (ECharts custom series)
    // ------------------------------------------------------------------
    function renderChart(data, containerId) {
        const container = document.getElementById(containerId || 'ms-chart');
        if (!container) return;

        if (!chart) {
            chart = echarts.init(container, 'dark', { renderer: 'canvas' });
            window.addEventListener('resize', () => chart && chart.resize());

            // ---- Click: open the side drawer with turn metadata ----
            chart.on('click', function(params) {
                if (!params || !params.data) return;
                // Skip edge series — they carry no turn payload.
                if (params.seriesName === 'edges') return;
                openTurnDrawer(buildTurnMeta(params.data));
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

        // Build implicit y categories: each row is one lane.
        // Row 0: first session
        // Row 1..N: sub-agents of first session, then second session, then sub-agents of second...
        // Order: sessions[i] at y=i, agents of sessions[i] follow at y=i+1..i+k.
        // The server already does this — we just take y as-is.
        const yCategories = buildYCategories(sessions, agents);
        const yIndex = new Map(yCategories.map((label, i) => [label, i]));

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
                ],
                itemId: t.id,
                sessionId: s.id,
                agentId: null,
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
                ],
                isBackground: true,
                sessionId: a.parentSessionId || null,
                agentId: a.id,
            });
            // Activity ticks from agent metadata (or empty)
            for (const t of (a.ticks || [])) {
                agentTickDataRaw.push({
                    value: [yi, t.x, t.x + tickWidthSeconds(t), t.color, t.status, t.label, t.id],
                    itemId: t.id,
                    sessionId: a.parentSessionId || null,
                    agentId: a.id,
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
                    lineStyle: { color: '#ea7ccc', width: 1.5, curveness: 0.3, opacity: 0.7 },
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
                    lineStyle: { color: '#ea7ccc', width: 1.5, curveness: 0.3, opacity: 0.7 },
                });
            }
        }

        const option = {
            backgroundColor: 'transparent',
            animation: false,
            tooltip: {
                trigger: 'item',
                backgroundColor: 'rgba(26, 26, 46, 0.95)',
                borderColor: '#2a2a4e',
                textStyle: { color: '#e0e0e0', fontSize: 12 },
                formatter: function(params) {
                    if (!params.data || !params.data.value) return '';
                    const v = params.data.value;
                    if (v.length < 6) return '';
                    if (params.data.isBackground) {
                        return `<strong>${escapeHtml(v[4] || '')}</strong><br/>
                                <span style="color:#a0a0b0">background span</span>`;
                    }
                    if (params.data.aggregatedCount > 1) {
                        return `<strong>${params.data.aggregatedCount} aggregated turns</strong><br/>
                                <span style="color:#a0a0b0">click to expand</span>`;
                    }
                    const id = params.data.itemId || v[6] || '—';
                    const dur = ((v[2] || 0) - (v[1] || 0)).toFixed(2);
                    return `<strong>${escapeHtml(v[5] || v[4] || id)}</strong><br/>
                            <span style="color:#a0a0b0">id:</span> ${escapeHtml(id)}<br/>
                            <span style="color:#a0a0b0">start:</span> ${formatRelSec(v[1])}<br/>
                            <span style="color:#a0a0b0">dur:</span> ${dur}s<br/>
                            <span style="color:#a0a0b0">status:</span> ${escapeHtml(v[4] || '—')}`;
                },
            },
            grid: {
                left: 220, right: 60, top: 70, bottom: 60,
                containLabel: false,
            },
            xAxis: {
                type: 'value',
                min: timeRange.min,
                max: timeRange.max,
                axisLabel: {
                    color: '#a0a0b0',
                    fontSize: 11,
                    formatter: function(v) {
                        const mins = v / 60;
                        if (mins < 1) return `${Math.round(v)}s`;
                        if (Math.abs(mins - Math.round(mins)) < 0.01) return `${Math.round(mins)}分钟`;
                        return `${mins.toFixed(1)}分钟`;
                    },
                },
                splitLine: { lineStyle: { color: 'rgba(160,160,176,0.08)' } },
            },
            yAxis: {
                type: 'category',
                data: yCategories,
                inverse: false,
                axisLabel: {
                    color: '#a0a0b0',
                    fontSize: 11,
                    formatter: function(value) {
                        // value is the label string; truncate for the y-axis
                        return value.length > 24 ? value.slice(0, 22) + '…' : value;
                    },
                },
                axisLine: { show: false },
                axisTick: { show: false },
                splitLine: { show: true, lineStyle: { color: 'rgba(160,160,176,0.05)' } },
            },
            dataZoom: [
                { type: 'slider', xAxisIndex: 0, height: 16, bottom: 16,
                  start: lastDzState ? lastDzState.start : 0,
                  end: lastDzState ? lastDzState.end : 100,
                  textStyle: { color: '#a0a0b0' } },
                { type: 'inside', xAxisIndex: 0, zoomOnMouseWheel: true, moveOnMouseMove: true,
                  start: lastDzState ? lastDzState.start : 0,
                  end: lastDzState ? lastDzState.end : 100 },
            ],
            series: [
                // Session activity ticks
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
            ],
        };

        option.xAxis.axisLabel.formatter = formatRelSec;
        chart.setOption(option, true);
        attachBadges(data, yIndex, yCategories);
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
        const yIdx = api.value(0);
        const xStart = api.coord([api.value(1), yIdx])[0];
        const xEnd = api.coord([api.value(2), yIdx])[0];
        const color = api.value(3) || '#5470c6';
        const isBg = params.data && params.data.isBackground;
        const isAggregated = params.data && params.data.aggregatedCount > 1;

        const height = api.size([0, 1])[1] * (isBg ? 0.85 : 0.5);
        const y = api.coord([0, yIdx])[1];

        // ---- Visual width (thin rect) ----
        const visFloor = isBg ? 2 : VISIBLE_MIN_PX;
        const visWidth = Math.max(xEnd - xStart, visFloor);

        if (isBg) {
            return {
                type: 'rect',
                shape: {
                    x: xStart, y: y - height / 2,
                    width: visWidth, height: height, r: 3,
                },
                style: { fill: color, stroke: 'none' },
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
            x: hitX, y: y - height / 2,
            width: hitW, height: height, r: 1,
        }, plotBox);

        return {
            type: 'group',
            silent: false,
            children: [
                {
                    type: 'rect',
                    shape: visRect,
                    style: {
                        fill: color,
                        opacity: isAggregated ? 0.85 : 0.95,
                    },
                    emphasis: { style: { opacity: 1, stroke: '#fff', lineWidth: 2 } },
                },
                {
                    // Eats hover/click; rendered behind the bar via z order.
                    type: 'rect',
                    shape: hitRect,
                    style: { fill: 'transparent' },
                    silent: false,
                    z: -1,
                },
            ].concat(_aggregatedBadge(params, xStart, xEnd, y, height, color)),
        };
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
        const fs = Math.max(8, Math.min(11, Math.floor(height * 0.55)));
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
                            `${buf.length} turns`, `agg-${bucketStart.toFixed(2)}`],
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
        const sign = sec < 0 ? '-' : '';
        const a = Math.abs(sec);
        const h = Math.floor(a / 3600);
        const m = Math.floor((a % 3600) / 60);
        const s = Math.floor(a % 60);
        const ms = Math.round((a - Math.floor(a)) * 1000);
        if (h > 0) {
            return `${sign}${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(ms).padStart(3, '0')}`;
        }
        return `${sign}${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(ms).padStart(3, '0')}`;
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
    // Badge / label overlay (ECharts graphic component)
    // ------------------------------------------------------------------
    function attachBadges(data, yIndex, yCategories) {
        const elements = [];
        const sessions = data.sessions || [];
        const agents = data.agents || [];

        // Model pill (left side, y row) for each session
        for (const s of sessions) {
            const yi = yIndex.get(sessionLabel(s));
            const yPx = chart.convertToPixel({ yAxisIndex: 0 }, [0, yi])[1];
            const active = s.y === 0 ? true : false; // first session is "active"
            elements.push(buildModelPill(s, yPx, active));
            // Metadata text
            elements.push(buildMetadata(s, yPx));
            // End marker
            if (s.endMarker) {
                elements.push(buildEndMarker(s, yPx));
            }
            // Spawn callout
            if (s.spawnCallout) {
                elements.push(buildSpawnCallout(s, yPx));
            }
        }
        // Agent row labels (role + title + count) on the right side
        for (const a of agents) {
            const yi = yIndex.get(agentLabel(a));
            const yPx = chart.convertToPixel({ yAxisIndex: 0 }, [0, yi])[1];
            elements.push(buildAgentLabel(a, yPx));
        }

        chart.setOption({ graphic: { elements } });
    }

    function buildModelPill(s, yPx, active) {
        return {
            type: 'group',
            position: [16, yPx - 12],
            children: [{
                type: 'rect',
                shape: { width: 200, height: 24, r: 12 },
                style: {
                    fill: active ? 'rgba(84,112,198,0.18)' : 'rgba(15,52,96,0.4)',
                    stroke: active ? '#5470c6' : '#2a2a4e',
                    lineWidth: active ? 1.5 : 1,
                },
            }, {
                type: 'text',
                position: [12, 12],
                style: {
                    text: s.name || s.id.slice(0, 8),
                    fill: '#e0e0e0',
                    fontSize: 12,
                    fontWeight: 600,
                },
            }],
        };
    }

    function buildMetadata(s, yPx) {
        return {
            type: 'text',
            position: [16, yPx + 18],
            style: {
                text: s.metadata || '',
                fill: '#a0a0b0',
                fontSize: 11,
            },
        };
    }

    function buildEndMarker(s, yPx) {
        if (!s.endMarker) return null;
        const xEnd = chart.convertToPixel({ xAxisIndex: 0 }, s.endMarker.x)[0];
        // The model pill lives at x=[16, 216]. If the endMarker is in that
        // zone (which happens whenever the end of the session is near the
        // start of the time axis, e.g. an in-progress session), push it
        // past the pill so it doesn't overlap with the model label.
        const modelPillRight = 220;
        const xPos = (xEnd < modelPillRight) ? modelPillRight : (xEnd + 8);
        return {
            type: 'group',
            position: [xPos, yPx - 8],
            children: [{
                type: 'circle',
                shape: { r: 4, cx: 0, cy: 8 },
                style: { fill: '#91cc75' },
            }, {
                type: 'text',
                position: [10, 0],
                style: {
                    text: s.endMarker.label,
                    fill: '#e0e0e0',
                    fontSize: 11,
                },
            }],
        };
    }

    function buildSpawnCallout(s, yPx) {
        if (!s.spawnCallout) return null;
        const xPx = chart.convertToPixel({ xAxisIndex: 0 }, s.spawnCallout.x)[0];
        return {
            type: 'group',
            position: [xPx - 100, yPx + 16],
            children: [{
                type: 'rect',
                shape: { width: 200, height: 22, r: 4 },
                style: {
                    fill: 'rgba(234,124,204,0.15)',
                    stroke: '#ea7ccc',
                    lineWidth: 1,
                },
            }, {
                type: 'text',
                position: [10, 11],
                style: {
                    text: `▼ ${s.spawnCallout.label}`,
                    fill: '#ea7ccc',
                    fontSize: 11,
                    fontWeight: 600,
                },
            }],
        };
    }

    function buildAgentLabel(a, yPx) {
        return {
            type: 'group',
            position: [16, yPx - 8],
            children: [{
                type: 'rect',
                shape: { width: 70, height: 16, r: 8 },
                style: {
                    fill: a.roleColor || '#5470c6',
                    opacity: 0.18,
                    stroke: a.roleColor || '#5470c6',
                    lineWidth: 0.8,
                },
            }, {
                type: 'text',
                position: [10, 8],
                style: {
                    text: a.role || '执行',
                    fill: a.roleColor || '#5470c6',
                    fontSize: 10,
                    fontWeight: 600,
                },
            }, {
                type: 'text',
                position: [78, 8],
                style: {
                    text: a.title || '',
                    fill: '#e0e0e0',
                    fontSize: 11,
                },
            }, {
                type: 'text',
                position: [180, 8],
                style: {
                    text: String(a.count || 0),
                    fill: '#a0a0b0',
                    fontSize: 11,
                    fontVariantNumeric: 'tabular-nums',
                },
            }],
        };
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
