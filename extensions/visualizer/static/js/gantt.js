/**
 * ClawCodex Visualizer — ECharts Gantt Chart
 */

let ganttChart = null;
let currentTimeMode = 'relative';
let currentSessionData = null;

async function loadSessionDetail(sessionId) {
    try {
        const data = await VizUtils.apiFetch(`/api/viz/sessions/${sessionId}`);
        currentSessionData = data;
        renderSessionHeader(data);
        renderGanttChart(sessionId);
        renderStats(data.stats);
        renderAnomalies(data.anomalies);
        renderAgentTree(data.agent_tree);
    } catch (e) {
        console.error('Failed to load session:', e);
        document.getElementById('session-meta').textContent = `Error: ${e.message}`;
    }
}

function renderSessionHeader(data) {
    const metaEl = document.getElementById('session-meta');
    if (!metaEl) return;

    metaEl.innerHTML = `
        <span>🆔 ${data.session_id}</span>
        <span>🕐 ${VizUtils.formatTime(data.start_time)}</span>
        <span>⏱ ${VizUtils.formatDuration(data.duration_ms)}</span>
        <span class="status-badge ${VizUtils.statusClass(data.status)}">${data.status}</span>
        ${data.model ? `<span>🤖 ${data.model}</span>` : ''}
        ${data.provider ? `<span>📡 ${data.provider}</span>` : ''}
        <span>🔄 ${data.turn_count} turns</span>
        <span>🔧 ${data.tool_count} tools</span>
    `;

    const titleEl = document.getElementById('session-title');
    if (titleEl && data.title) {
        titleEl.textContent = data.title;
    }

    // F-96-E: Orchestrator issue association
    const orchEl = document.getElementById('session-orch-info');
    if (orchEl) {
        const issueId = data.issue_id;
        const verifyStatus = data.verification_status;
        if (issueId) {
            orchEl.style.display = '';
            const issueLink = document.createElement('a');
            issueLink.href = '/viz/orchestrator';
            issueLink.title = 'View in Orchestrator Dashboard';
            issueLink.textContent = 'Issue ' + issueId;
            const linkSpan = document.createElement('span');
            linkSpan.className = 'orch-info-badge';
            linkSpan.textContent = '🎛 ';
            linkSpan.appendChild(issueLink);
            orchEl.innerHTML = '';
            orchEl.appendChild(linkSpan);
            if (verifyStatus) {
                const vs = document.createElement('span');
                vs.className = 'verify-badge verify-' + verifyStatus.replace(/[^a-zA-Z0-9_-]/g, '');
                vs.textContent = verifyStatus;
                orchEl.appendChild(vs);
            }
        } else {
            orchEl.style.display = 'none';
        }
    }
}

async function renderGanttChart(sessionId) {
    try {
        const ganttData = await VizUtils.apiFetch(
            `/api/viz/sessions/${sessionId}/gantt?time_mode=${currentTimeMode}`
        );

        const container = document.getElementById('gantt-chart');
        if (!container) return;

        if (!ganttChart) {
            ganttChart = echarts.init(container, 'dark');
            // Responsive
            window.addEventListener('resize', () => ganttChart?.resize());
        }

        const categories = ganttData.categories || [];
        const series = ganttData.series || [];

        if (categories.length === 0 || series.length === 0) {
            ganttChart.setOption({
                title: { text: 'No timeline data', left: 'center', top: 'center',
                         textStyle: { color: '#a0a0b0', fontSize: 16 } }
            });
            return;
        }

        const option = {
            backgroundColor: 'transparent',
            tooltip: {
                formatter: function(params) {
                    const d = params.data;
                    if (!d || d.length < 9) return '';
                    const label = d[4];
                    const duration = VizUtils.formatDuration(d[3]);
                    const status = d[6];
                    return `<strong>${label}</strong><br/>Duration: ${duration}<br/>Status: ${status}`;
                }
            },
            grid: { left: 150, right: 40, top: 30, bottom: 60 },
            xAxis: {
                type: 'value',
                axisLabel: {
                    formatter: v => VizUtils.formatDuration(v)
                }
            },
            yAxis: {
                type: 'category',
                data: categories,
                inverse: true,
                axisLabel: { fontSize: 11, color: '#a0a0b0' }
            },
            dataZoom: [
                { type: 'slider', xAxisIndex: 0, start: 0, end: 100 },
                { type: 'inside', xAxisIndex: 0 }
            ],
            series: [{
                type: 'custom',
                renderItem: renderGanttBar,
                encode: { x: [1, 2], y: 0 },
                data: series,
                progressive: 5000,
                animation: false
            }]
        };

        ganttChart.setOption(option, true);
    } catch (e) {
        console.error('Failed to render gantt:', e);
    }
}

function renderGanttBar(params, api) {
    const categoryIdx = api.value(0);
    const start = api.coord([api.value(1), categoryIdx]);
    const end = api.coord([api.value(2), categoryIdx]);
    const height = api.size([0, 1])[1] * 0.6;

    const label = api.value(4) || '';
    const status = api.value(6) || 'success';
    const color = api.value(7) || '#5470c6';

    const rectShape = echarts.graphic.clipRectByRect({
        x: start[0], y: start[1] - height / 2,
        width: Math.max(end[0] - start[0], 2), height: height
    }, {
        x: params.coordSys.x, y: params.coordSys.y,
        width: params.coordSys.width, height: params.coordSys.height
    });

    if (!rectShape) return;

    return {
        type: 'rect',
        shape: rectShape,
        style: {
            fill: color,
            opacity: status === 'running' ? 0.7 : 0.9
        },
        emphasis: { style: { opacity: 1 } }
    };
}

function renderStats(stats) {
    if (!stats) {
        console.warn('renderStats called with no stats');
        return;
    }

    // The visible stats bar (rendered by stats_bar.html container mode)
    // uses one #stat-* element per field. Populate each in place so the
    // "—" placeholders get replaced with real numbers.
    const fields = {
        'stat-total-ops':     stats.total_ops ?? 0,
        'stat-avg-duration':  VizUtils.formatDuration(stats.avg_duration_ms ?? 0),
        'stat-max-concurrent': stats.max_concurrent ?? 0,
        'stat-total-duration': VizUtils.formatDuration(stats.total_duration_ms ?? 0),
        'stat-tokens':        VizUtils.formatTokens(stats.context_tokens ?? 0),
        'stat-cost':          `$${(stats.cost_usd ?? 0).toFixed(4)}`,
    };
    for (const [id, value] of Object.entries(fields)) {
        const el = document.getElementById(id);
        if (el) el.textContent = String(value);
    }

    // Optional type breakdown — append to a dedicated element if present,
    // otherwise show in the hidden #stats-content target for backward compat.
    const byTypeEntries = Object.entries(stats.by_type || {});
    if (byTypeEntries.length > 0) {
        const typeBreakdown = byTypeEntries.map(([k, v]) =>
            `<span>${k}: <strong>${v}</strong></span>`
        ).join(' · ');
        const breakdownEl = document.getElementById('stats-type-breakdown')
            || document.getElementById('stats-content');
        if (breakdownEl) {
            breakdownEl.innerHTML =
                `<div style="margin-top:8px;font-size:12px;color:#a0a0b0">${typeBreakdown}</div>`;
        }
    }
}

function renderAnomalies(anomalies) {
    const el = document.getElementById('anomaly-content');
    if (!el) return;

    if (!anomalies || anomalies.length === 0) {
        el.innerHTML = '<div style="color:#a0a0b0;font-size:13px">No anomalies detected ✅</div>';
        return;
    }

    el.innerHTML = anomalies.map(a => `
        <div class="anomaly-item ${VizUtils.anomalyClass(a.severity)}">
            <div class="anomaly-desc">
                <div>${a.description}</div>
                <div class="anomaly-type">${a.type} · ${a.severity}</div>
                ${a.suggestion ? `<div style="margin-top:4px;color:#73c0de">💡 ${a.suggestion}</div>` : ''}
            </div>
        </div>
    `).join('');
}

function renderAgentTree(tree) {
    const panel = document.getElementById('tree-panel');
    const el = document.getElementById('tree-content');
    if (!panel || !el) return;

    if (!tree || tree.length === 0) {
        panel.style.display = 'none';
        return;
    }

    panel.style.display = 'block';
    el.innerHTML = tree.map(node => `
        <div style="padding:6px 0;padding-left:${node.depth * 20}px;font-size:13px;">
            ${node.depth > 0 ? '└─ ' : '🔵 '}${node.name}
            <span style="color:#a0a0b0">(${node.session_ref})</span>
        </div>
    `).join('');
}

function changeTimeMode(mode) {
    currentTimeMode = mode;
    if (currentSessionData) {
        renderGanttChart(currentSessionData.session_id);
    }
}

async function exportSession(format) {
    if (!currentSessionData) return;
    try {
        const resp = await fetch(`/api/viz/sessions/${currentSessionData.session_id}/export?format=${format}`);
        if (!resp.ok) throw new Error(`Export failed: ${resp.status}`);
        const blob = await resp.blob();
        const filename = `${currentSessionData.session_id}.${format}`;
        VizUtils.downloadBlob(blob, filename);
    } catch (e) {
        alert(`Export failed: ${e.message}`);
    }
}

/**
 * Handle live events from WebSocket.
 */
function onLiveEvent(event) {
    if (!currentSessionData || !ganttChart) return;
    // Refresh gantt chart data
    renderGanttChart(currentSessionData.session_id);
}

// Make functions globally available
window.loadSessionDetail = loadSessionDetail;
window.changeTimeMode = changeTimeMode;
window.exportSession = exportSession;
window.onLiveEvent = onLiveEvent;
