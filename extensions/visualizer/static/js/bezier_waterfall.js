/**
 * ClawCodex Visualizer — Bezier Waterfall View
 *
 * P3 zoom + pan. Renders the 8-category timeline with a sticky time
 * axis, ported from clawcodex_sessions_analysis (Next.js). The
 * bezier view is mounted in a separate container (#bezier-chart) so
 * the ECharts view stays untouched in the same page.
 *
 * Scope of this file (P3):
 *   - Fetch /api/viz/multi-session?sessions=... and render 8 category bars
 *   - Sticky time axis with buildTicks() / tickLabel() (zoom-aware)
 *   - Min 2.5 px bar width for `durationUnrecorded`
 *   - ts_unrecorded bars get a dashed / dimmed style
 *   - 1×-40× cursor-anchored wheel zoom (Z-axis pinned under cursor)
 *   - alt+wheel horizontal pan (deltaX + deltaY)
 *   - 4 px left-button drag-to-pan, document-level pointer tracking
 *   - userSelect=none while panning (prevents text selection side effect)
 *   - ResizeObserver on the scroll container; re-render on width change
 *   - ref-mirror pattern (zoomRef / containerWRef) so the wheel listener
 *     is mounted exactly once and doesn't churn on every render
 *   - destroy() tears down all listeners + observers + cancels rAF
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

    // Hex colors match the ECharts view's OperationCategory palette
    // (viz_models.py _CATEGORY_COLORS) so the legend doesn't shift
    // hues when the user toggles between views. The user/system
    // buckets reuse the python-side llm_text / background colors.
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

    // ----------------------------------------------------------------
    // Helpers (vanilla ports of the Next.js lib/format.ts + categories.ts)
    // ----------------------------------------------------------------

    function bezierCategoryOf(bar) {
        // user_role takes precedence — user prompt bars and system
        // injection bars don't have a meaningful tool-based category.
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

    // Generate tick marks (in ms) across a duration. `zoom` is the
    // linear zoom factor (1 = full range, 40 = 40x in). Denser ticks
    // appear at higher zoom. Ported from format.ts:15-35.
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
        // Floating-point accumulation guard matches format.ts.
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

    // Map an x in seconds (relative to baseTime) to a pixel offset
    // inside the canvas. Caller decides the canvas width.
    function xToPx(seconds, canvasWidth, durationSec) {
        if (durationSec <= 0) return 0;
        return (seconds / durationSec) * canvasWidth;
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
            // Computed bounds (filled by _computeBounds)
            this.baseTime = 0;        // seconds (matches ECharts timeRange.min)
            this.durationSec = 60;    // seconds
            this.canvasWidth = 0;     // pixels (depends on containerW * zoom)
            this.scaleX = 0;          // px per second
            this.container = null;
            this.scrollEl = null;     // alias for container; the scroll viewport
            // ---- P3 zoom / pan state ----
            this.zoom = 1;
            this.containerW = 0;      // measured by ResizeObserver
            this.panState = null;     // { startX, startScrollLeft, pointerId, moved }
            this.isPanning = false;
            this.rafId = null;        // pending rAF for scrollLeft restore
            // Ref-mirror pattern: the wheel listener reads from these
            // (not from `this.zoom` / `this.containerW` directly) so we
            // can mount the listener exactly once and avoid re-binding
            // on every render. See session-analyzer.tsx:70-73.
            this.zoomRef = { current: 1 };
            this.containerWRef = { current: 0 };
            // Cleanup bookkeeping. Every addEventListener / ResizeObserver
            // / requestAnimationFrame is registered here so destroy()
            // leaves zero residue — switchView('waterfall') → switchView
            // ('bezier') must not leak listeners (plan P3 verification).
            this._listeners = [];     // [{ target, type, fn, options }]
            this._observers = [];     // ResizeObserver[]
        }

        async init(sessionIds) {
            this.sessionIds = sessionIds;
            this.container = document.getElementById(this.containerId);
            if (!this.container) {
                console.error('[bezier] container not found:', this.containerId);
                return;
            }
            this.scrollEl = this.container;

            // Fetch
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
            // Defensive: ensure positive duration so xToPx() never divides
            // by zero. 60s is a reasonable single-minute fallback that
            // still yields sensible ticks via buildTicks().
            this.durationSec = Math.max(1, max - min);
            // canvas = max(100, containerW * zoom). containerW is 0
            // initially, so we get the 100 px floor until ResizeObserver
            // fires and re-renders with the real viewport width.
            this.canvasWidth = Math.max(MIN_CANVAS_PX, this.containerW * this.zoom);
            this.scaleX = this.canvasWidth / this.durationSec;
        }

        _render() {
            if (!this.container) return;
            this.container.innerHTML = '';

            // The scroll container is the outer #bezier-chart (overflow:auto
            // in the template, scrollWidth grows with the panel). The
            // panel inside is what we resize on zoom.
            const panel = document.createElement('div');
            panel.className = 'bezier-waterfall';
            panel.style.width = this.canvasWidth + 'px';

            panel.appendChild(this._renderTimeAxis());

            // Body — one row per session
            const body = document.createElement('div');
            body.className = 'bezier-body';
            const sessions = (this.data && this.data.sessions) || [];
            if (sessions.length === 0) {
                const empty = document.createElement('div');
                empty.className = 'bezier-empty';
                empty.textContent = '无 session 数据';
                body.appendChild(empty);
            } else {
                sessions.forEach((s) => body.appendChild(this._renderSessionRow(s)));
            }
            panel.appendChild(body);

            this.container.appendChild(panel);
        }

        _renderTimeAxis() {
            const axis = document.createElement('div');
            axis.className = 'bezier-time-axis';
            // Explicit width so absolutely-positioned ticks (left: x px)
            // have a defined range. Sticky positioning is set via CSS.
            axis.style.width = this.canvasWidth + 'px';
            // buildTicks takes ms + zoom. At higher zoom, ticks get
            // denser so the user still sees a few labels across the
            // visible window.
            const ticks = buildTicks(this.durationSec * 1000, this.zoom);
            for (const t of ticks) {
                const x = xToPx(t / 1000, this.canvasWidth, this.durationSec);
                const tick = document.createElement('div');
                tick.className = 'bezier-tick';
                tick.style.left = x + 'px';
                const label = document.createElement('span');
                label.className = 'bezier-tick-label';
                label.textContent = tickLabel(t);
                tick.appendChild(label);
                axis.appendChild(tick);
            }
            return axis;
        }

        _renderSessionRow(session) {
            const row = document.createElement('div');
            row.className = 'bezier-row';
            row.dataset.sessionId = session.id;

            // Row header (sticky-left label)
            const header = document.createElement('div');
            header.className = 'bezier-row-header';
            const name = document.createElement('span');
            name.className = 'bezier-row-name';
            name.textContent = session.name || session.id;
            header.appendChild(name);
            if (session.metadata) {
                const meta = document.createElement('span');
                meta.className = 'bezier-row-meta';
                meta.textContent = session.metadata;
                header.appendChild(meta);
            }
            row.appendChild(header);

            // Event track — full canvas width
            const track = document.createElement('div');
            track.className = 'bezier-row-track';
            track.style.width = this.canvasWidth + 'px';

            const ticks = session.ticks || [];
            for (const t of ticks) {
                track.appendChild(this._renderEventBar(t));
            }

            row.appendChild(track);
            return row;
        }

        _renderEventBar(tick) {
            const bar = document.createElement('div');
            const cat = bezierCategoryOf(tick);
            bar.className = 'bezier-event-bar bezier-cat-' + cat;
            if (tick.status === 'error') bar.classList.add('bezier-status-error');
            if (tick.status === 'warning') bar.classList.add('bezier-status-warning');
            if (tick.durationUnrecorded) bar.classList.add('bezier-duration-unrecorded');
            if (tick.tsUnrecorded) bar.classList.add('bezier-ts-unrecorded');
            if (tick.durationHeuristic) bar.classList.add('bezier-duration-heuristic');
            bar.dataset.barId = tick.id || '';
            bar.dataset.cat = cat;

            // x/w are already seconds relative to timeRange.min in the
            // builder output, so xToPx(0,...) lands at the canvas left.
            // Negative x clamps to 0 (a bar that pre-dates the visible
            // window — e.g. start_time backfill drift).
            const x = Math.max(0, xToPx(tick.x, this.canvasWidth, this.durationSec));
            let w = xToPx(tick.w || 0, this.canvasWidth, this.durationSec);
            if (tick.durationUnrecorded) w = Math.max(MIN_BAR_PX, w);

            bar.style.left = x + 'px';
            bar.style.width = w + 'px';
            bar.style.background = CATEGORY_COLORS[cat] || tick.color || '#6e7681';

            // Title — Chinese, matches ECharts tooltip feel
            const timeStr = tick.absoluteTime || (tick.tsUnrecorded ? '未记录' : '');
            const durStr = tick.durationUnrecorded
                ? (tick.durationHeuristic ? '估算' : '未记录')
                : ((tick.w * 1000).toFixed(0) + 'ms');
            bar.title =
                (tick.label || cat) +
                (timeStr ? ' · ' + timeStr : '') +
                ' · ' + durStr;

            return bar;
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

            // Initial measurement. clientWidth is 0 if the container
            // hasn't been laid out yet; ResizeObserver will pick up
            // the real value on the next animation frame.
            this._measureContainer();

            // ResizeObserver — preferred over window.resize because
            // it also fires on layout shifts (side-panel toggle,
            // header wrap) and not just window resizes.
            if (typeof ResizeObserver !== 'undefined') {
                const ro = new ResizeObserver(() => this._measureContainer());
                ro.observe(this.scrollEl);
                this._observers.push(ro);
            } else {
                // Legacy fallback (very old browsers).
                const onResize = () => this._measureContainer();
                window.addEventListener('resize', onResize);
                this._listeners.push({ target: window, type: 'resize', fn: onResize });
            }

            // Wheel handler — passive:false so preventDefault suppresses
            // the browser's native vertical page scroll. React 17+ binds
            // onWheel as passive, which is why session-analyzer.tsx:195
            // uses addEventListener with the explicit option. We do the
            // same in vanilla to keep the behaviour identical.
            this._addListener(this.scrollEl, 'wheel', (e) => this._onWheel(e), { passive: false });

            // Pointerdown starts a pan candidate. Document-level
            // pointermove / pointerup / pointercancel track it across
            // element boundaries (the user can drag off the container
            // and back without losing the pan).
            this._addListener(this.scrollEl, 'pointerdown', (e) => this._onPointerDown(e));
            this._addListener(document, 'pointermove',   (e) => this._onPointerMove(e));
            this._addListener(document, 'pointerup',     (e) => this._onPointerUp(e));
            this._addListener(document, 'pointercancel', (e) => this._onPointerUp(e));
        }

        _addListener(target, type, fn, options) {
            target.addEventListener(type, fn, options);
            this._listeners.push({ target: target, type: type, fn: fn, options: options || false });
        }

        _detachInteractions() {
            for (let i = 0; i < this._listeners.length; i++) {
                const l = this._listeners[i];
                try { l.target.removeEventListener(l.type, l.fn, l.options); }
                catch (_) { /* target may already be gone (e.g. destroyed child) */ }
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
            // Reset transient state so a re-init() doesn't carry it over.
            this.panState = null;
            this.isPanning = false;
            this.scrollEl = null;
            // Always clear the userSelect guard in case a pan was
            // interrupted mid-drag (page hide, etc.) and never got its
            // pointerup.
            document.body.style.userSelect = '';
        }

        _measureContainer() {
            if (!this.scrollEl) return;
            const w = this.scrollEl.clientWidth;
            if (w > 0 && w !== this.containerW) {
                this.containerW = w;
                this.containerWRef.current = w;
                // Recompute canvasWidth for the new viewport, then
                // re-render so ticks / bars re-project.
                this.canvasWidth = Math.max(MIN_CANVAS_PX, this.containerW * this.zoom);
                this.scaleX = this.canvasWidth / this.durationSec;
                this._render();
            }
        }

        _onWheel(e) {
            e.preventDefault();
            // alt + wheel = horizontal pan (deltaX covers trackpads,
            // deltaY covers mice that only emit vertical wheels).
            if (e.altKey) {
                this.scrollEl.scrollLeft = Math.max(
                    0, this.scrollEl.scrollLeft + e.deltaX + e.deltaY
                );
                return;
            }
            // Pin the pixel under the cursor across the zoom step.
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
            // Apply the new scroll position after _render() flushes
            // the new canvasWidth into the DOM. rAF is essential —
            // synchronous writes land on the old DOM and get clobbered.
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
            // Mouse: only primary button. Touch / pen always count.
            if (e.pointerType === 'mouse' && e.button !== 0) return;
            this.panState = {
                startX: e.clientX,
                startScrollLeft: this.scrollEl.scrollLeft,
                pointerId: e.pointerId,
                moved: false,
            };
            this.isPanning = true;
            this._setUserSelect(true);
        }

        _onPointerMove(e) {
            const state = this.panState;
            if (!state || state.pointerId !== e.pointerId) return;
            const deltaX = e.clientX - state.startX;
            // Wait until the user has moved at least PAN_THRESHOLD_PX
            // before treating it as a pan. Below the threshold we leave
            // state.moved=false so the pointerup still fires a click on
            // whatever was under the cursor (an event bar, a tick).
            if (!state.moved && Math.abs(deltaX) < PAN_THRESHOLD_PX) return;
            state.moved = true;
            e.preventDefault();
            this.scrollEl.scrollLeft = Math.max(0, state.startScrollLeft - deltaX);
        }

        _onPointerUp(e) {
            if (!this.panState || this.panState.pointerId !== e.pointerId) return;
            this.panState = null;
            this.isPanning = false;
            this._setUserSelect(false);
        }

        _setUserSelect(disabled) {
            // Toggle document.body.userSelect. Saved/restored pattern
            // (instead of hard-setting "none") so we never clobber a
            // user-defined stylesheet rule on body. session-analyzer.tsx
            // does the same with a prev-var / restore in useEffect.
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

        // Public — programmatic zoom. P4 / P5 will wire the +/- controls
        // and connector-click reset. For P3 this is mostly useful for
        // devtools poking.
        setZoom(next) {
            const clamped = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, next));
            if (clamped === this.zoom) return;
            this._setZoom(clamped);
        }

        destroy() {
            this._detachInteractions();
            if (this.container) {
                this.container.innerHTML = '';
                this.container.classList.remove('bezier-waterfall');
            }
            this.data = null;
            this.container = null;
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

    return {
        init: init,
        close: close,
        render: render,
        setZoom: function(z) { if (instance) instance.setZoom(z); },
        CATEGORIES: BEZIER_CATEGORIES,
        COLORS: CATEGORY_COLORS,
        LABELS: CATEGORY_LABELS,
        // Exposed for unit tests / future module reuse
        _bezierCategoryOf: bezierCategoryOf,
        _buildTicks: buildTicks,
        _tickLabel: tickLabel,
        _formatClock: formatClock,
        ZOOM_MIN: ZOOM_MIN,
        ZOOM_MAX: ZOOM_MAX,
        ZOOM_STEP: ZOOM_STEP,
    };
})();

// ---- Global API (consumed by template <script> blocks) ----
window.initBezierWaterfall  = function(sessionIds, options) { return BezierWaterfall.init(sessionIds, options); };
window.closeBezierPanel     = function() { BezierWaterfall.close(); };
window.renderBezierChart    = function() { BezierWaterfall.render(); };
window.setBezierZoom        = function(z) { BezierWaterfall.setZoom(z); };
// Devtools / smoke-test exposure — gives the same API the IIFE return
// value has, so devtools can poke at the helpers and unit tests can
// run in plain node without a DOM.
window.BezierWaterfall      = BezierWaterfall;
