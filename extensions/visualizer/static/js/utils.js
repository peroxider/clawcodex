/**
 * ClawCodex Visualizer — Utility Functions
 */

const VizUtils = {
    /**
     * Format a Unix timestamp to a readable string.
     */
    formatTime(ts) {
        if (!ts || ts === 0) return '—';
        const d = new Date(ts * 1000);
        return d.toLocaleString();
    },

    /**
     * Format duration in ms to human-readable string.
     */
    formatDuration(ms) {
        if (!ms || ms === 0) return '0ms';
        if (ms < 1000) return `${ms}ms`;
        if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
        if (ms < 3600000) return `${(ms / 60000).toFixed(1)}min`;
        return `${(ms / 3600000).toFixed(1)}h`;
    },

    /**
     * Format token count.
     */
    formatTokens(n) {
        if (!n || n === 0) return '0';
        if (n < 1000) return String(n);
        if (n < 1000000) return `${(n / 1000).toFixed(1)}k`;
        return `${(n / 1000000).toFixed(1)}M`;
    },

    /**
     * Status badge CSS class.
     */
    statusClass(status) {
        const map = {
            completed: 'status-completed',
            success: 'status-success',
            failed: 'status-failed',
            error: 'status-error',
            running: 'status-running',
        };
        return map[status] || 'status-unknown';
    },

    /**
     * Anomaly severity CSS class.
     */
    anomalyClass(severity) {
        return `anomaly-${severity}`;
    },

    /**
     * Truncate string.
     */
    truncate(str, maxLen = 50) {
        if (!str) return '';
        return str.length > maxLen ? str.substring(0, maxLen) + '...' : str;
    },

    /**
     * Fetch JSON from API.
     */
    async apiFetch(url, options = {}) {
        const resp = await fetch(url, options);
        if (!resp.ok) {
            const text = await resp.text();
            throw new Error(`API error ${resp.status}: ${text}`);
        }
        return resp.json();
    },

    /**
     * Download a blob.
     */
    downloadBlob(blob, filename) {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }
};

// Make available globally
window.VizUtils = VizUtils;
