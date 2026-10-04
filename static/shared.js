// shared.js - the browser helpers plot_val_loss.html relies on.
// Trimmed from ImageTools' shared.js: the scan-progress overlay controller and the
// heartbeat that lets the server shut itself down when the browser tab is closed.

// ProgressOverlayController - Reusable progress modal controller with polling and cancellation
class ProgressOverlayController {
    constructor({ overlayId, titleId, percentId, fillId, statusId, countId, cancelBtnId }) {
        this.overlayId = overlayId;
        this.titleId = titleId;
        this.percentId = percentId;
        this.fillId = fillId;
        this.statusId = statusId;
        this.countId = countId;
        this.cancelBtnId = cancelBtnId;
        this.pollInterval = null;
        this.pollSeq = 0;
        this.activeSessionId = 0;
        this.maxPercentSeen = 0;
    }

    show({ title = 'Processing...', initialStatus = 'Initializing...', countText = 'Processing', onCancel = null } = {}) {
        this.activeSessionId++;
        this.maxPercentSeen = 0;
        this.pollSeq = 0;
        const overlay = document.getElementById(this.overlayId);
        const titleEl = document.getElementById(this.titleId);
        const fill = document.getElementById(this.fillId);
        const percentEl = document.getElementById(this.percentId);
        const statusEl = document.getElementById(this.statusId);
        const countEl = document.getElementById(this.countId);
        const cancelBtn = document.getElementById(this.cancelBtnId);

        if (titleEl && title) titleEl.innerText = title;
        if (fill) fill.style.width = '0%';
        if (percentEl) percentEl.innerText = '0%';
        if (statusEl) statusEl.innerText = initialStatus;
        if (countEl) countEl.innerText = countText;
        if (cancelBtn && onCancel) {
            cancelBtn.onclick = onCancel;
        }
        if (overlay) overlay.style.display = 'flex';
    }

    startPolling(endpoint, { intervalMs = 200, onProgress = null, onComplete = null, onError = null, autoDismiss = false, dismissDelayMs = 400 } = {}) {
        this.stopPolling();
        const sessionId = this.activeSessionId;
        let lastResolvedSeq = 0;
        let hasSeenRunning = false;

        const poll = async () => {
            const currentSeq = ++this.pollSeq;
            try {
                const res = await fetch(endpoint);
                if (!res.ok) return;
                const data = await res.json();
                // Discard stale responses from previous sessions or out-of-order poll arrivals
                if (sessionId !== this.activeSessionId || currentSeq < lastResolvedSeq) {
                    return;
                }
                lastResolvedSeq = currentSeq;

                if (data) {
                    this.update(data);
                    if (onProgress) onProgress(data);

                    const isRunning = data.is_running === true || data.running === true ||
                                      (data.phase && data.phase !== 'idle' && data.phase !== 'complete' && data.phase !== 'cancelled') ||
                                      (data.status && data.status !== 'Idle' && data.status !== 'Ready' && data.status !== 'Completed' && data.status !== 'Cancelled');
                    if (isRunning) {
                        hasSeenRunning = true;
                    }

                    const isExplicitComplete = data.phase === 'complete' || data.phase === 'completed' || data.phase === 'cancelled' ||
                                               data.status === 'Completed' || data.status === 'Cancelled';
                    const isTransitionedToStopped = hasSeenRunning && (data.is_running === false || data.running === false) &&
                                                    (data.ready === true || data.status === 'Ready' || data.phase === 'complete');

                    const isDone = isExplicitComplete || isTransitionedToStopped;
                    if (isDone) {
                        this.stopPolling();
                        if (autoDismiss) {
                            this.hide(dismissDelayMs);
                        }
                        if (onComplete) {
                            onComplete(data);
                        }
                    }
                }
            } catch (e) {
                if (onError) onError(e);
            }
        };
        poll(); // Immediate initial poll at t=0
        this.pollInterval = setInterval(poll, intervalMs);
    }

    update({ percent = 0, message = '', status = '', current = 0, total = 0, is_running = true } = {}) {
        const fill = document.getElementById(this.fillId);
        const percentEl = document.getElementById(this.percentId);
        const statusEl = document.getElementById(this.statusId);
        const countEl = document.getElementById(this.countId);

        let rawPct = Math.min(100, Math.max(0, percent || 0));
        // Enforce strictly monotonic non-decreasing percent values during an active run
        if (is_running && rawPct < this.maxPercentSeen) {
            rawPct = this.maxPercentSeen;
        } else {
            this.maxPercentSeen = rawPct;
        }

        if (fill) fill.style.width = `${rawPct}%`;
        if (percentEl) percentEl.innerText = `${rawPct}%`;
        const text = message || status;
        if (statusEl && text) statusEl.innerText = text;
        if (countEl) {
            if (total > 0) {
                countEl.innerText = `${current} / ${total}`;
            } else {
                countEl.innerText = 'Processing';
            }
        }
    }

    stopPolling() {
        if (this.pollInterval) {
            clearInterval(this.pollInterval);
            this.pollInterval = null;
        }
    }

    hide(delayMs = 400) {
        this.stopPolling();
        const overlay = document.getElementById(this.overlayId);
        const fill = document.getElementById(this.fillId);
        const percentEl = document.getElementById(this.percentId);

        if (fill) fill.style.width = '100%';
        if (percentEl) percentEl.innerText = '100%';

        setTimeout(() => {
            if (overlay) overlay.style.display = 'none';
        }, delayMs);
    }

    hideImmediate() {
        this.stopPolling();
        const overlay = document.getElementById(this.overlayId);
        if (overlay) overlay.style.display = 'none';
    }
}

window.ProgressOverlayController = ProgressOverlayController;


/**
 * Tells the server this tab is alive (every 3 s) and that it left (on close), so the
 * app can exit once the last tab closes.
 */
function initAutoShutdown() {
    if (window._autoShutdownInitialized) return;
    window._autoShutdownInitialized = true;

    const clientId = 'tab-' + Math.random().toString(36).substring(2, 9) + '-' + Date.now();

    function sendHeartbeat() {
        let controller = null;
        let signal = undefined;
        let timerId = null;

        if (typeof AbortController !== 'undefined') {
            controller = new AbortController();
            signal = controller.signal;
            timerId = setTimeout(() => {
                try {
                    controller.abort();
                } catch (_) {}
            }, 3000);
        }

        fetch('/api/heartbeat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ client_id: clientId }),
            signal: signal
        }).then(() => {
            if (timerId) clearTimeout(timerId);
        }).catch(() => {
            if (timerId) clearTimeout(timerId);
        });
    }

    function sendClientLeave(e) {
        if (e && e.persisted) return;

        if (navigator.sendBeacon) {
            const blob = new Blob([JSON.stringify({ client_id: clientId })], { type: 'application/json' });
            navigator.sendBeacon('/api/client_leave', blob);
        } else {
            fetch('/api/client_leave', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ client_id: clientId }),
                keepalive: true
            }).catch(() => {});
        }
    }

    window.addEventListener('beforeunload', sendClientLeave);
    window.addEventListener('pagehide', sendClientLeave);

    // Immediately refresh the heartbeat when the tab becomes visible, returns from bfcache, or gains focus
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') {
            sendHeartbeat();
        }
    });
    window.addEventListener('pageshow', sendHeartbeat);
    window.addEventListener('focus', sendHeartbeat);

    sendHeartbeat();
    setInterval(sendHeartbeat, 3000);
}
window.initAutoShutdown = initAutoShutdown;

if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAutoShutdown);
    } else {
        initAutoShutdown();
    }
}
