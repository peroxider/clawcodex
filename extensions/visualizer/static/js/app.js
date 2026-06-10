/**
 * ClawCodex Visualizer — Main App (Index Page)
 */

let currentWorkspace = null;
let allSessions = [];

// Polling state — refreshes the workspace tabs and session list every
// POLL_INTERVAL_MS so running sessions show up without a manual refresh.
// Only the DOM is touched when the data actually changes, so an idle page
// is silent (no flicker, no scroll jumps).
const POLL_INTERVAL_MS = 5000;
let pollTimer = null;
let pollInFlight = false;
let lastWorkspacesSig = '';
let lastSessionsSig = '';
let lastWorkspacesData = null;

function _workspaceSig(workspaces) {
    // Compact signature: id + name + session_count. Skips last_updated
    // (jittery on re-stat) and path (irrelevant to UI).
    return JSON.stringify(workspaces.map(w => [w.id, w.name, w.session_count]));
}

function _sessionSig(sessions) {
    // Status + counters drive the visible card; ignore heavy detail
    // fields (title / metadata) so a sub-second update to one card
    // doesn't cascade into a full re-render.
    return JSON.stringify(sessions.map(s => [
        s.session_id,
        s.status,
        s.tool_count,
        s.turn_count,
        s.model,
        s.end_time,
    ]));
}

function _setLiveState(state) {
    // state: 'live' | 'paused' | 'error'
    const el = document.getElementById('live-indicator');
    if (!el) return;
    el.classList.remove('live', 'paused', 'error');
    el.classList.add(state);
    const label = el.querySelector('.live-label');
    if (label) {
        label.textContent = state === 'live' ? 'Live'
            : state === 'paused' ? 'Paused (typing)'
            : 'Offline';
    }
}

// Helper: push the current data into the bottom status bar so its
// fields (Sessions / Last Updated / Auto-refresh) reflect real state.
// All three VizStatusBar methods are no-ops on pages where the bar
// isn't rendered, so it's safe to call unconditionally.
function _pushStatusBar() {
    if (typeof window.VizStatusBar !== 'object' || !window.VizStatusBar) return;
    window.VizStatusBar.updateSessionCount(allSessions.length);
    window.VizStatusBar.updateLastUpdated();
}

function startLivePolling() {
    if (pollTimer) return;
    _setLiveState('live');
    pollTimer = setInterval(_pollOnce, POLL_INTERVAL_MS);
    if (typeof window.VizStatusBar === 'object' && window.VizStatusBar) {
        window.VizStatusBar.setAutoRefresh(true);
    }
}

function stopLivePolling() {
    if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
    }
    if (typeof window.VizStatusBar === 'object' && window.VizStatusBar) {
        window.VizStatusBar.setAutoRefresh(false);
    }
}

async function _pollOnce() {
    if (pollInFlight) return;  // Skip tick if previous fetch is still in flight.
    pollInFlight = true;
    try {
        // Always refresh workspace tabs (cheap, low frequency).
        const workspaces = await VizUtils.apiFetch('/api/viz/workspaces');
        const wsSig = _workspaceSig(workspaces);
        if (wsSig !== lastWorkspacesSig) {
            lastWorkspacesSig = wsSig;
            lastWorkspacesData = workspaces;
            _renderWorkspaces(workspaces);
        }
        // Refresh session list only when not actively filtering.
        const searchEl = document.getElementById('search-input');
        if (!(searchEl && document.activeElement === searchEl
              && (searchEl.value || '').length > 0)) {
            await _refreshSessionsList();
        } else {
            _setLiveState('paused');
        }
    } catch (e) {
        console.warn('Live poll error:', e);
        _setLiveState('error');
    } finally {
        pollInFlight = false;
    }
}

function _renderWorkspaces(workspaces) {
    const tabsEl = document.getElementById('workspace-tabs');
    if (!tabsEl) return;
    if (workspaces.length === 0) {
        tabsEl.innerHTML = '<div class="workspace-tab active">Default</div>';
        currentWorkspace = 'default';
        return;
    }
    // Preserve the active tab across re-renders so the user doesn't get
    // bounced back to the first tab every 5 seconds.
    const activeId = currentWorkspace || workspaces[0].id;
    tabsEl.innerHTML = workspaces.map(ws =>
        `<div class="workspace-tab ${ws.id === activeId ? 'active' : ''}"
              data-ws-id="${ws.id}"
              onclick="selectWorkspace('${ws.id}', this)">${ws.name} (${ws.session_count})</div>`
    ).join('');
    if (!workspaces.some(w => w.id === activeId)) {
        currentWorkspace = workspaces[0].id;
    }
}

async function _refreshSessionsList() {
    const grid = document.getElementById('sessions-grid');
    if (!grid) return;
    let url = '/api/viz/workspaces/default/sessions';
    if (currentWorkspace && currentWorkspace !== 'default') {
        url = `/api/viz/workspaces/${currentWorkspace}/sessions`;
    }
    const sessions = await VizUtils.apiFetch(url);
    const sig = _sessionSig(sessions);
    if (sig === lastSessionsSig) return;  // No change — leave the DOM alone.
    lastSessionsSig = sig;
    allSessions = sessions;
    _pushStatusBar();
    if (sessions.length === 0) {
        grid.innerHTML = '<div class="empty-state">No sessions found</div>';
        return;
    }
    grid.innerHTML = sessions.map(s => renderSessionCard(s)).join('');
}

async function loadWorkspaces() {
    try {
        const workspaces = await VizUtils.apiFetch('/api/viz/workspaces');
        lastWorkspacesSig = _workspaceSig(workspaces);
        lastWorkspacesData = workspaces;
        _renderWorkspaces(workspaces);
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
        lastSessionsSig = _sessionSig(sessions);
        _pushStatusBar();
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

function openMultiSessionDialog() {
    document.getElementById('multi-session-dialog').style.display = 'flex';
    // Pre-fill with the first two session cards if any
    if (allSessions && allSessions.length >= 1) {
        const ids = allSessions.slice(0, 2).map(s => s.session_id).join(',');
        document.getElementById('multi-session-ids').value = ids;
    }
}

function closeMultiSessionDialog() {
    document.getElementById('multi-session-dialog').style.display = 'none';
}

function openMultiSessionPage() {
    const ids = document.getElementById('multi-session-ids').value.trim();
    if (!ids) {
        alert('请输入至少一个 session ID');
        return;
    }
    closeMultiSessionDialog();
    window.location.href = `/multi?session_ids=${encodeURIComponent(ids)}`;
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
window.openMultiSessionDialog = openMultiSessionDialog;
window.closeMultiSessionDialog = closeMultiSessionDialog;
window.openMultiSessionPage = openMultiSessionPage;
