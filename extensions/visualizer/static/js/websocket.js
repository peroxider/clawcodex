/**
 * ClawCodex Visualizer — WebSocket Live Tail
 */

class VizWebSocket {
    constructor() {
        this.ws = null;
        this.sessionId = null;
        this.reconnectTimer = null;
        this.handlers = {};
    }

    connect(sessionId) {
        this.sessionId = sessionId;
        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const url = `${protocol}//${location.host}/api/viz/ws/sessions/${sessionId}`;

        this.ws = new WebSocket(url);

        this.ws.onopen = () => {
            console.log('WS connected for session:', sessionId);
            this._updateStatus('connected');
        };

        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === 'heartbeat') return;
                if (data.type === 'transcript_event') {
                    this._emit('transcript', data);
                }
            } catch (e) {
                console.warn('WS message parse error:', e);
            }
        };

        this.ws.onclose = () => {
            console.log('WS disconnected for session:', sessionId);
            this._updateStatus('disconnected');
            // Auto-reconnect after 3 seconds
            this.reconnectTimer = setTimeout(() => {
                if (this.sessionId) this.connect(this.sessionId);
            }, 3000);
        };

        this.ws.onerror = (err) => {
            console.warn('WS error:', err);
            this._updateStatus('disconnected');
        };
    }

    disconnect() {
        this.sessionId = null;
        if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
    }

    on(event, handler) {
        if (!this.handlers[event]) this.handlers[event] = [];
        this.handlers[event].push(handler);
    }

    _emit(event, data) {
        (this.handlers[event] || []).forEach(h => h(data));
    }

    _updateStatus(status) {
        const el = document.getElementById('ws-status');
        if (el) {
            el.textContent = status === 'connected' ? '● Connected' : '● Disconnected';
            el.className = status;
        }
    }
}

// Global instance
const vizWs = new VizWebSocket();

/**
 * Connect live tail for a session.
 */
function connectLiveTail(sessionId) {
    vizWs.connect(sessionId);

    // Handle new transcript events — add bars to gantt chart
    vizWs.on('transcript', (event) => {
        if (typeof onLiveEvent === 'function') {
            onLiveEvent(event);
        }
    });
}

window.connectLiveTail = connectLiveTail;
window.vizWs = vizWs;
