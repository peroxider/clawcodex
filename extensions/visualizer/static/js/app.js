/**
 * ClawCodex Visualizer — Main App (Index Page)
 */

let currentWorkspace = null;
let allSessions = [];

async function loadWorkspaces() {
    try {
        const workspaces = await VizUtils.apiFetch('/api/viz/workspaces');
        const tabsEl = document.getElementById('workspace-tabs');
        if (!tabsEl) return;

        if (workspaces.length === 0) {
            tabsEl.innerHTML = '<div class="workspace-tab active">Default</div>';
            currentWorkspace = 'default';
            return;
        }

        tabsEl.innerHTML = workspaces.map((ws, i) =>
            `<div class="workspace-tab ${i === 0 ? 'active' : ''}"
                  onclick="selectWorkspace('${ws.id}', this)">${ws.name} (${ws.session_count})</div>`
        ).join('');
        currentWorkspace = workspaces[0].id;
    } catch (e) {
        console.error('Failed to load workspaces:', e);
    }
}

async function loadSessions() {
    const grid = document.getElementById('sessions-grid');
    if (!grid) return;

    try {
        let url = '/api/viz/workspaces/default/sessions';
        if (currentWorkspace && currentWorkspace !== 'default') {
            url = `/api/viz/workspaces/${currentWorkspace}/sessions`;
        }

        const sessions = await VizUtils.apiFetch(url);
        allSessions = sessions;

        if (sessions.length === 0) {
            grid.innerHTML = '<div class="empty-state">No sessions found</div>';
            return;
        }

        grid.innerHTML = sessions.map(s => renderSessionCard(s)).join('');
    } catch (e) {
        grid.innerHTML = `<div class="empty-state">Error loading sessions: ${e.message}</div>`;
        console.error('Failed to load sessions:', e);
    }
}

function renderSessionCard(s) {
    const statusClass = VizUtils.statusClass(s.status);
    const duration = VizUtils.formatDuration(s.duration_ms);
    const startTime = VizUtils.formatTime(s.start_time);

    return `
        <div class="session-card" onclick="window.location.href='/session/${s.session_id}'">
            <h4>${s.title || s.session_id}</h4>
            <div class="meta">
                <span class="status-badge ${statusClass}">${s.status}</span>
                <div>🕐 ${startTime}</div>
                <div>⏱ ${duration}</div>
                ${s.model ? `<div>🤖 ${s.model}</div>` : ''}
                ${s.agent_name ? `<div>👤 ${s.agent_name}</div>` : ''}
                ${s.turn_count ? `<div>🔄 ${s.turn_count} turns</div>` : ''}
                ${s.tool_count ? `<div>🔧 ${s.tool_count} tools</div>` : ''}
            </div>
        </div>
    `;
}

function selectWorkspace(wsId, el) {
    currentWorkspace = wsId;
    document.querySelectorAll('.workspace-tab').forEach(t => t.classList.remove('active'));
    if (el) el.classList.add('active');
    loadSessions();
}

function refreshSessions() {
    loadSessions();
}

function filterSessions() {
    const query = document.getElementById('search-input').value.toLowerCase();
    const grid = document.getElementById('sessions-grid');
    const filtered = allSessions.filter(s =>
        (s.session_id || '').toLowerCase().includes(query) ||
        (s.title || '').toLowerCase().includes(query) ||
        (s.agent_name || '').toLowerCase().includes(query) ||
        (s.model || '').toLowerCase().includes(query)
    );

    if (filtered.length === 0) {
        grid.innerHTML = '<div class="empty-state">No matching sessions</div>';
    } else {
        grid.innerHTML = filtered.map(s => renderSessionCard(s)).join('');
    }
}

function openCompareDialog() {
    document.getElementById('compare-dialog').style.display = 'flex';
}

function closeCompareDialog() {
    document.getElementById('compare-dialog').style.display = 'none';
}

async function doCompare() {
    const ids = document.getElementById('compare-ids').value.trim();
    if (!ids) return;
    closeCompareDialog();
    // Navigate to comparison view
    window.location.href = `/compare?sessions=${encodeURIComponent(ids)}`;
}

// Make functions globally available
window.loadWorkspaces = loadWorkspaces;
window.loadSessions = loadSessions;
window.refreshSessions = refreshSessions;
window.filterSessions = filterSessions;
window.selectWorkspace = selectWorkspace;
window.openCompareDialog = openCompareDialog;
window.closeCompareDialog = closeCompareDialog;
window.doCompare = doCompare;
