"""Flask plumbing for the loss viewer (trimmed from ImageTools' utility_concrete.web_server
and abstract_web): JSON response envelopes, the /api/config and progress routes, the
local-only request guard, a JSON error handler, and browser-close auto-shutdown.

Depends on: flask
"""

import logging
import os
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlsplit

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from config_store import PROJECT_ROOT, load_config, save_config

logger = logging.getLogger("web_support")

STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
TEMPLATE_DIR = os.path.join(PROJECT_ROOT, "templates")


# --- JSON envelopes -----------------------------------------------------------

def api_success(data: Any = None, message: Optional[str] = None, code: int = 200, **extra: Any) -> Any:
    """Standard JSON success envelope.

    A Flask response inside an app context, else a ``(payload_dict, code)`` tuple.
    """
    payload: Dict[str, Any] = {"status": "success"}
    if message is not None:
        payload["message"] = message
    if data is not None:
        payload["data"] = data
    if extra:
        payload.update(extra)

    from flask import has_app_context
    if has_app_context():
        return jsonify(payload), code
    return payload, code


def api_error(message: Any, code: int = 400, **extra: Any) -> Any:
    """Standard JSON error envelope (same return shapes as :func:`api_success`)."""
    payload: Dict[str, Any] = {"status": "error", "message": str(message)}
    if extra:
        payload.update(extra)

    from flask import has_app_context
    if has_app_context():
        return jsonify(payload), code
    return payload, code


# --- Routes -------------------------------------------------------------------

def make_config_routes(app, config_file: Callable[[], str], allowed_keys, coerce=None):
    """Registers ``GET/POST /api/config`` for a whitelisted set of keys.

    ``config_file`` is a callable returning the settings file path (looked up on every
    request, so tests can swap it). Keys outside ``allowed_keys`` already in the file
    are preserved on save.
    """
    @app.route("/api/config", methods=["GET", "POST"])
    def api_config():
        path = config_file()
        if request.method == "POST":
            cfg = load_config(path)
            data = request.get_json(silent=True) or {}
            for key in allowed_keys:
                if key in data:
                    cfg[key] = coerce(data[key]) if coerce else data[key]
            save_config(path, cfg)
            return api_success(data=cfg)
        return api_success(data=load_config(path))


def register_progress_routes(app, service, *, progress_rule: str, cancel_rule: str, cancel_message: str) -> None:
    """Registers a ``GET <progress_rule>`` + ``POST <cancel_rule>`` pair for a background worker."""
    endpoint_base = progress_rule.strip("/").replace("/", "_")

    @app.route(progress_rule, endpoint=f"progress_{endpoint_base}")
    def _progress():
        return jsonify(service.get_progress())

    @app.route(cancel_rule, methods=["POST"], endpoint=f"cancel_{endpoint_base}")
    def _cancel():
        service.cancel()
        return api_success(message=cancel_message)


# --- Auto-shutdown ------------------------------------------------------------

class AutoShutdownManager:
    """Tracks active browser tabs/windows and triggers server shutdown when all clients close."""

    def __init__(self, heartbeat_timeout=25.0, initial_grace_period=30.0, shutdown_grace_delay=5.0):
        self.active_clients = {}
        self.active_clients_lock = threading.Lock()
        self.has_connected_clients = False
        self.start_time = time.time()
        self.heartbeat_timeout = float(heartbeat_timeout)
        self.initial_grace_period = float(initial_grace_period)
        self.shutdown_grace_delay = float(shutdown_grace_delay)
        self._watchdog_started = False
        self._pending_shutdown_timer = None
        self.busy_count = 0

    @contextmanager
    def busy(self):
        """Context manager marking the server as busy (a scan is running). Prevents shutdown."""
        with self.active_clients_lock:
            self.busy_count += 1
            if self._pending_shutdown_timer and self._pending_shutdown_timer.is_alive():
                self._pending_shutdown_timer.cancel()
                self._pending_shutdown_timer = None
        try:
            yield
        finally:
            with self.active_clients_lock:
                self.busy_count = max(0, self.busy_count - 1)
                now = time.time()
                for cid in self.active_clients:
                    self.active_clients[cid] = now

    def _do_shutdown(self):
        with self.active_clients_lock:
            if self.busy_count > 0:
                return
            if len(self.active_clients) == 0:
                logger.info("All browser clients closed. Server shutting down.")
                os._exit(0)

    def trigger_shutdown(self, delay=None):
        """Triggers process exit after a brief grace delay (allows cancellation on page refresh)."""
        if delay is None:
            delay = self.shutdown_grace_delay

        with self.active_clients_lock:
            if self.busy_count > 0:
                return
            if self._pending_shutdown_timer and self._pending_shutdown_timer.is_alive():
                self._pending_shutdown_timer.cancel()
            self._pending_shutdown_timer = threading.Timer(delay, self._do_shutdown)
            self._pending_shutdown_timer.daemon = True
            self._pending_shutdown_timer.start()

    def record_heartbeat(self, client_id):
        with self.active_clients_lock:
            if self._pending_shutdown_timer:
                self._pending_shutdown_timer.cancel()
                self._pending_shutdown_timer = None

            self.active_clients[str(client_id)] = time.time()
            self.has_connected_clients = True
            return len(self.active_clients)

    def record_client_leave(self, client_id):
        with self.active_clients_lock:
            if client_id and str(client_id) in self.active_clients:
                del self.active_clients[str(client_id)]
            remaining = len(self.active_clients)

        if self.has_connected_clients and remaining == 0 and self.busy_count == 0:
            self.trigger_shutdown()

        return remaining

    def start_watchdog(self):
        if self._watchdog_started:
            return
        self._watchdog_started = True

        def _monitor():
            while True:
                time.sleep(2.0)
                now = time.time()
                with self.active_clients_lock:
                    if self.busy_count > 0:
                        for cid in self.active_clients:
                            self.active_clients[cid] = now
                        continue

                    stale = [cid for cid, last_seen in self.active_clients.items() if now - last_seen > self.heartbeat_timeout]
                    for cid in stale:
                        del self.active_clients[cid]
                    client_count = len(self.active_clients)

                if self.has_connected_clients and client_count == 0:
                    self.trigger_shutdown()
                    break

                if self.initial_grace_period and self.initial_grace_period > 0 and self.initial_grace_period != float("inf") and not self.has_connected_clients and (now - self.start_time > self.initial_grace_period):
                    logger.info("No client connected within initial grace period. Shutting down.")
                    self.trigger_shutdown()
                    break

        threading.Thread(target=_monitor, daemon=True).start()


def register_auto_shutdown(app, heartbeat_timeout=120.0, initial_grace_period=float("inf"), shutdown_grace_delay=5.0):
    """Registers the heartbeat and client-leave endpoints on a Flask app."""
    manager = AutoShutdownManager(heartbeat_timeout=heartbeat_timeout, initial_grace_period=initial_grace_period, shutdown_grace_delay=shutdown_grace_delay)

    @app.route("/api/heartbeat", methods=["POST"])
    def auto_shutdown_heartbeat():
        data = request.get_json(silent=True) or {}
        client_id = data.get("client_id", "default")
        count = manager.record_heartbeat(client_id)
        return jsonify({"status": "alive", "active_clients": count})

    @app.route("/api/client_leave", methods=["POST"])
    def auto_shutdown_client_leave():
        client_id = None
        if request.is_json:
            data = request.get_json(silent=True) or {}
            client_id = data.get("client_id")
        else:
            try:
                raw = request.get_data(as_text=True)
                if raw:
                    import json as json_lib
                    data = json_lib.loads(raw)
                    client_id = data.get("client_id")
            except Exception:
                pass

        if not client_id:
            client_id = request.form.get("client_id")

        remaining = manager.record_client_leave(client_id)
        return jsonify({"status": "ok", "remaining_clients": remaining})

    return manager


# --- Error handling and request guard -----------------------------------------

def register_error_handler(app):
    """Log any unexpected error in a route and answer in the JSON error shape.

    Normal HTTP errors (404, 405, ...) keep Flask's own responses, and under test mode
    (``app.testing``) the exception still propagates so tests see the real error.
    """
    @app.errorhandler(Exception)
    def _unexpected_error(exc):
        if isinstance(exc, HTTPException):
            return exc
        if app.testing or app.config.get("PROPAGATE_EXCEPTIONS"):
            raise exc
        logger.error("Unhandled error on %s %s", request.method, request.path, exc_info=exc)
        return api_error(f"Unexpected error: {exc}", code=500)


_LOCAL_HOSTNAMES = frozenset({"127.0.0.1", "localhost", "::1"})
_READ_ONLY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _hostname_of(host_header):
    """Lower-cased host name in a ``Host`` header value (port stripped), or ``None``."""
    try:
        return urlsplit("//" + (host_header or "")).hostname
    except ValueError:
        return None


def register_local_only_guard(app):
    """Answer only requests that really come from this machine's own app window.

    The server listens on 127.0.0.1 only, but a web page open in an ordinary browser can
    still be made to send requests to a local port. Two checks:

    * the ``Host`` header must name this machine (``127.0.0.1`` / ``localhost`` /
      ``::1``), which stops "DNS rebinding";
    * a browser request that changes something (anything but GET/HEAD/OPTIONS) and
      carries an ``Origin`` must come from this same local server, which stops a
      hostile page posting to a local port. Requests with no ``Origin`` (tests, curl)
      are unaffected.
    """
    @app.before_request
    def _local_only():
        host = request.headers.get("Host", "")
        if _hostname_of(host) not in _LOCAL_HOSTNAMES:
            logger.warning("Refused %s %s: Host %r is not this machine", request.method, request.path, host)
            return api_error("Forbidden: this app only answers requests addressed to localhost", code=403)
        origin = request.headers.get("Origin")
        if origin is not None and request.method not in _READ_ONLY_METHODS:
            try:
                origin_host = urlsplit(origin).netloc.lower()
            except ValueError:
                origin_host = ""
            if origin_host != host.lower():
                logger.warning("Refused %s %s: Origin %r is not this app", request.method, request.path, origin)
                return api_error("Forbidden: request did not come from this app", code=403)


def create_app(import_name, *, heartbeat_timeout=120.0):
    """Build the Flask app; returns ``(app, auto_shutdown_manager)``."""
    app = Flask(import_name, static_folder=STATIC_DIR, template_folder=TEMPLATE_DIR)
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
    register_local_only_guard(app)
    register_error_handler(app)
    manager = register_auto_shutdown(app, heartbeat_timeout=heartbeat_timeout)
    return app, manager
