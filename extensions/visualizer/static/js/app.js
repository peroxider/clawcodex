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

// ---- Filter / layout state (persisted to localStorage) ----
// "default" → only the "live" set: running, completed, success.
// "all"     → no status filter.
// Otherwise → exact match against session.status.
const DEFAULT_STATUS_SET = new Set(['running', 'completed', 'success']);
let statusFilter = _loadPref('statusFilter', 'default');
// 'grid' | 'list'
let layoutMode = _loadPref('layoutMode', 'grid');
// Sort key for list view (see _SORT_COLUMNS). Default: newest first.
let sortBy = _loadPref('sortBy', 'start_time');
// 'asc' | 'desc'
let sortDir = _loadPref('sortDir', 'desc');
let searchQuery = '';

function _loadPref(key, fallback) {
    try {
        const v = localStorage.getItem('viz.' + key);
        return v === null ? fallback : v;
    } catch (_) { return fallback; }
}
function _savePref(key, value) {
    try { localStorage.setItem('viz.' + key, value); } catch (_) { /* private mode */ }
}

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
    _applyFiltersAndRender();
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
        _applyFiltersAndRender();
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

// Columns available for list-view sort. Each entry maps a sort key to a
// human label and an extractor that returns the comparable value from a
// session. Missing fields sort to the bottom regardless of direction.
const _SORT_COLUMNS = {
    start_time: { label: 'Start', get: s => s.start_time || 0 },
    session_id: { label: 'ID', get: s => (s.session_id || '').toLowerCase() },
    title:      { label: 'Title', get: s => (s.title || s.session_id || '').toLowerCase() },
    status:     { label: 'Status', get: s => s.status || '' },
    model:      { label: 'Model', get: s => s.model || '' },
    duration_ms:{ label: 'Duration', get: s => s.duration_ms || 0 },
    turn_count: { label: 'Turns', get: s => s.turn_count || 0 },
    tool_count: { label: 'Tools', get: s => s.tool_count || 0 },
};

function _sortedSessions(arr) {
    const col = _SORT_COLUMNS[sortBy] || _SORT_COLUMNS.start_time;
    const sign = sortDir === 'asc' ? 1 : -1;
    return arr.slice().sort((a, b) => {
        const av = col.get(a);
        const bv = col.get(b);
        if (av < bv) return -1 * sign;
        if (av > bv) return 1 * sign;
        return 0;
    });
}

function renderSessionRow(s) {
    const statusClass = VizUtils.statusClass(s.status);
    const duration = VizUtils.formatDuration(s.duration_ms);
    const startTime = VizUtils.formatTime(s.start_time);
    const titleEsc = (s.title || s.session_id || '').replace(/[<&>]/g, c =>
        ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]));
    const idShort = (s.session_id || '').slice(0, 8);
    return `
        <div class="session-row" onclick="window.location.href='/session/${s.session_id}'">
            <div class="cell cell-time">${startTime}</div>
            <div class="cell cell-id" title="${s.session_id || ''}">${idShort}</div>
            <div class="cell cell-title">${titleEsc}</div>
            <div class="cell cell-status"><span class="status-badge ${statusClass}">${s.status || 'unknown'}</span></div>
            <div class="cell cell-model">${s.model || '—'}</div>
            <div class="cell cell-duration">${duration}</div>
            <div class="cell cell-turns">${s.turn_count || 0}</div>
            <div class="cell cell-tools">${s.tool_count || 0}</div>
        </div>
    `;
}

function _renderListHeader() {
    const cols = [
        ['start_time', 'Start'],
        ['session_id', 'ID'],
        ['title', 'Title'],
        ['status', 'Status'],
        ['model', 'Model'],
        ['duration_ms', 'Duration'],
        ['turn_count', 'Turns'],
        ['tool_count', 'Tools'],
    ];
    return cols.map(([key, label]) => {
        const isActive = sortBy === key;
        const arrow = isActive ? (sortDir === 'asc' ? ' ▲' : ' ▼') : '';
        return `<div class="cell cell-sortable${isActive ? ' active' : ''}"
                     onclick="event.stopPropagation();onSortColumn('${key}')">${label}${arrow}</div>`;
    }).join('');
}

function onSortColumn(key) {
    if (sortBy === key) {
        sortDir = sortDir === 'asc' ? 'desc' : 'asc';
    } else {
        sortBy = key;
        sortDir = (key === 'start_time' || key === 'duration_ms'
                   || key === 'turn_count' || key === 'tool_count') ? 'desc' : 'asc';
    }
    _savePref('sortBy', sortBy);
    _savePref('sortDir', sortDir);
    _applyFiltersAndRender();
}

function setLayoutMode(mode) {
    if (mode !== 'grid' && mode !== 'list') return;
    layoutMode = mode;
    _savePref('layoutMode', mode);
    const gridBtn = document.getElementById('layout-toggle-grid');
    const listBtn = document.getElementById('layout-toggle-list');
    if (gridBtn) gridBtn.classList.toggle('active', mode === 'grid');
    if (listBtn) listBtn.classList.toggle('active', mode === 'list');
    const grid = document.getElementById('sessions-grid');
    if (grid) {
        grid.classList.toggle('sessions-grid', mode === 'grid');
        grid.classList.toggle('sessions-list', mode === 'list');
    }
    _applyFiltersAndRender();
}

function onStatusFilterChange() {
    const sel = document.getElementById('status-filter-select');
    if (!sel) return;
    statusFilter = sel.value;
    _savePref('statusFilter', statusFilter);
    _applyFiltersAndRender();
}

function _filteredSessions() {
    let arr = allSessions;
    // Status filter
    if (statusFilter === 'default') {
        arr = arr.filter(s => DEFAULT_STATUS_SET.has((s.status || '').toLowerCase()));
    } else if (statusFilter !== 'all') {
        const target = statusFilter.toLowerCase();
        arr = arr.filter(s => (s.status || '').toLowerCase() === target);
    }
    // Search filter (id / title / agent / model)
    if (searchQuery) {
        const q = searchQuery;
        arr = arr.filter(s =>
            (s.session_id || '').toLowerCase().includes(q) ||
            (s.title || '').toLowerCase().includes(q) ||
            (s.agent_name || '').toLowerCase().includes(q) ||
            (s.model || '').toLowerCase().includes(q)
        );
    }
    return arr;
}

function _applyFiltersAndRender() {
    const grid = document.getElementById('sessions-grid');
    if (!grid) return;
    const filtered = _filteredSessions();
    if (filtered.length === 0) {
        grid.innerHTML = '<div class="empty-state">No matching sessions</div>';
        return;
    }
    if (layoutMode === 'list') {
        const sorted = _sortedSessions(filtered);
        grid.innerHTML = `<div class="list-header">${_renderListHeader()}</div>`
            + sorted.map(renderSessionRow).join('');
    } else {
        grid.innerHTML = filtered.map(renderSessionCard).join('');
    }
}

// Restore persisted UI state into the controls on first paint.
function _restoreUiState() {
    const sel = document.getElementById('status-filter-select');
    if (sel) sel.value = statusFilter;
    const gridBtn = document.getElementById('layout-toggle-grid');
    const listBtn = document.getElementById('layout-toggle-list');
    const grid = document.getElementById('sessions-grid');
    if (grid) {
        grid.classList.toggle('sessions-grid', layoutMode === 'grid');
        grid.classList.toggle('sessions-list', layoutMode === 'list');
    }
    if (gridBtn) gridBtn.classList.toggle('active', layoutMode === 'grid');
    if (listBtn) listBtn.classList.toggle('active', layoutMode === 'list');
}

function filterSessions() {
    const input = document.getElementById('search-input');
    searchQuery = (input ? input.value : '').toLowerCase();
    _applyFiltersAndRender();
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
window.setLayoutMode = setLayoutMode;
window.onStatusFilterChange = onStatusFilterChange;
window.onSortColumn = onSortColumn;
window._restoreUiState = _restoreUiState;
