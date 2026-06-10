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
        const endRel = Math.max(startRel + 0.05, (bar.end_time || startRel) - baseTime);
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
        const sessionTickData = sessions.flatMap(s => {
            const yi = yIndex.get(sessionLabel(s));
            return (s.ticks || []).map(t => ({
                value: [
                    yi,
                    t.x,
                    t.x + (t.w || 0.05),
                    t.color,
                    t.status,
                    t.label,
                    t.id,
                ],
                itemId: t.id,
            }));
        });

        // ---- Agent swimlane series (one per agent) ----
        const agentTickData = [];
        const agentEdgeData = [];
        for (const a of agents) {
            const yi = yIndex.get(agentLabel(a));
            // Background span (spawn → join) — subtle gray bar
            agentTickData.push({
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
            });
            // Activity ticks from agent metadata (or empty)
            for (const t of (a.ticks || [])) {
                agentTickData.push({
                    value: [yi, t.x, t.x + (t.w || 0.05), t.color, t.status, t.label, t.id],
                    itemId: t.id,
                });
            }
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
                        return `<strong>${v[4] || ''}</strong><br/>
                                <span style="color:#a0a0b0">background span</span>`;
                    }
                    return `<strong>${v[5] || v[4] || ''}</strong><br/>
                            x: ${v[1].toFixed(1)}s<br/>
                            status: ${v[4] || '—'}`;
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
                interval: (timeRange.tickSeconds[1] || 60) - (timeRange.tickSeconds[0] || 0),
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
                { type: 'slider', xAxisIndex: 0, height: 16, bottom: 16, start: 0, end: 100,
                  textStyle: { color: '#a0a0b0' } },
                { type: 'inside', xAxisIndex: 0, zoomOnMouseWheel: true, moveOnMouseMove: true },
            ],
            series: [
                // Session activity ticks
                {
                    name: 'sessions',
                    type: 'custom',
                    renderItem: renderTick,
                    encode: { x: [1, 2], y: 0 },
                    data: sessionTickData,
                    progressive: 5000,
                    z: 3,
                },
                // Agent activity ticks (foreground + background spans)
                {
                    name: 'agents',
                    type: 'custom',
                    renderItem: renderTick,
                    encode: { x: [1, 2], y: 0 },
                    data: agentTickData,
                    progressive: 5000,
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

        chart.setOption(option, true);
        attachBadges(data, yIndex, yCategories);
    }

    // ------------------------------------------------------------------
    // Custom-series renderer for one tick
    // ------------------------------------------------------------------
    function renderTick(params, api) {
        const yIdx = api.value(0);
        const xStart = api.coord([api.value(1), yIdx])[0];
        const xEnd = api.coord([api.value(2), yIdx])[0];
        const color = api.value(3) || '#5470c6';
        const isBg = params.data && params.data.isBackground;

        const height = api.size([0, 1])[1] * (isBg ? 0.85 : 0.5);
        const y = api.coord([0, yIdx])[1];

        const width = Math.max(xEnd - xStart, isBg ? 1 : 1.5);
        if (isBg) {
            return {
                type: 'rect',
                shape: {
                    x: xStart, y: y - height / 2,
                    width: width, height: height, r: 3,
                },
                style: { fill: color, stroke: 'none' },
            };
        }
        return {
            type: 'rect',
            shape: echarts.graphic.clipRectByRect({
                x: xStart, y: y - height / 2,
                width: width, height: height, r: 1,
            }, {
                x: params.coordSys.x, y: params.coordSys.y,
                width: params.coordSys.width, height: params.coordSys.height,
            }),
            style: { fill: color, opacity: 0.95 },
            emphasis: { style: { opacity: 1, stroke: '#fff', lineWidth: 0.5 } },
        };
    }

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
