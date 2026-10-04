"""Cancellable background worker for long scans, plus the task-dispatch helper.

Trimmed from ImageTools' abstract_concurrency/background.py: only BackgroundTaskWorker
(progress tracking, cancel, error handling, auto-shutdown "busy" locking) and
dispatch_worker_task. Zero external dependencies (standard library only).
"""

import math
import threading
from contextlib import nullcontext
from typing import Any, Callable, Dict, Optional


class BackgroundTaskWorker:
    """
    Standardized background worker thread supporting progress tracking,
    graceful cancellation, exception handling, and auto-shutdown busy locking.
    """

    def __init__(self, auto_shutdown_manager=None):
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._cancel_event = threading.Event()
        self._auto_shutdown_manager = auto_shutdown_manager
        self._progress: Dict[str, Any] = {
            "running": False,
            "ready": False,
            "current": 0,
            "total": 0,
            "remaining": 0,
            "percent": 0.0,
            "status": "Idle",
            "message": "",
        }

    def is_running(self) -> bool:
        """Returns True if a task thread is actively running."""
        with self._lock:
            return bool(self._progress.get("running", False))

    def cancel(self):
        """Signals cancellation to the running task thread."""
        with self._lock:
            self._cancel_event.set()
            if self._progress["running"]:
                self._progress["running"] = False
                if self._progress.get("status") != "Error":
                    self._progress["status"] = "Cancelled"
                self._progress["ready"] = True

    def get_status(self) -> dict:
        """Returns a snapshot copy of the current worker progress."""
        with self._lock:
            return dict(self._progress)

    # Alias: register_progress_routes calls ``service.get_progress()``.
    get_progress = get_status

    def update_progress(
        self,
        current: Optional[int] = None,
        total: Optional[int] = None,
        status: Optional[str] = None,
        message: Optional[str] = None,
        ready: Optional[bool] = None,
        extra: Optional[dict] = None,
        **kwargs,
    ):
        """Thread-safely updates progress metrics and calculates percentage."""
        with self._lock:
            self._apply_progress(current, total, status, message, ready, extra, **kwargs)

    @staticmethod
    def _sanitize_metric(val: Any) -> Any:
        if val is None:
            return None
        if isinstance(val, (int, float)):
            if math.isnan(val) or math.isinf(val):
                return 0
            return int(val) if isinstance(val, float) and val.is_integer() else max(0, val)
        if isinstance(val, str):
            try:
                f = float(val.strip())
                if math.isnan(f) or math.isinf(f):
                    return 0
                return int(f) if f.is_integer() else max(0.0, f)
            except (ValueError, TypeError):
                return val
        return val

    def _apply_progress(self, current=None, total=None, status=None, message=None,
                        ready=None, extra=None, **kwargs):
        """Body of :meth:`update_progress`; the caller must hold ``self._lock``."""
        if total is not None:
            sanitized_total = self._sanitize_metric(total)
            self._progress["total"] = sanitized_total
        if current is not None:
            sanitized_current = self._sanitize_metric(current)
            self._progress["current"] = sanitized_current
        if ready is not None:
            self._progress["ready"] = ready

        tot = self._progress.get("total", 0)
        cur = self._progress.get("current", 0)
        try:
            tot_num = float(tot) if isinstance(tot, (int, float, str)) else 0.0
            cur_num = float(cur) if isinstance(cur, (int, float, str)) else 0.0
            if math.isnan(tot_num) or math.isinf(tot_num):
                tot_num = 0.0
            if math.isnan(cur_num) or math.isinf(cur_num):
                cur_num = 0.0
            tot_num = max(0.0, tot_num)
            cur_num = max(0.0, cur_num)
            self._progress["remaining"] = max(0, int(tot_num - cur_num)) if tot_num > 0 else 0
            self._progress["percent"] = max(0.0, min(100.0, round((cur_num / tot_num) * 100, 1))) if tot_num > 0 else 0.0
        except (ValueError, TypeError, OverflowError):
            self._progress["remaining"] = 0
            self._progress["percent"] = 0.0

        if status is not None:
            self._progress["status"] = status
        if message is not None:
            self._progress["message"] = message
        if extra:
            self._progress.update(extra)
        if kwargs:
            self._progress.update(kwargs)

    def _initialize_task_state(
        self,
        total: int,
        status_msg: str,
        extra_initial_state: Optional[dict] = None,
    ) -> threading.Event:
        """Re-arms the cancel event and initializes worker progress state (under _lock)."""
        self._cancel_event.set()
        self._cancel_event = threading.Event()
        self._progress = {
            "running": True,
            "ready": False,
            "current": 0,
            "total": total,
            "remaining": total,
            "percent": 0.0,
            "status": status_msg,
            "message": "",
        }
        if extra_initial_state:
            self._progress.update(extra_initial_state)
        return self._cancel_event

    def start(
        self,
        task_fn: Callable[[threading.Event, Callable], None],
        total: int = 0,
        status_msg: str = "Initializing...",
        on_complete: Optional[Callable] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        extra_initial_state: Optional[dict] = None,
    ) -> tuple[bool, str]:
        """
        Starts executing task_fn in a daemon background thread.
        task_fn signature: (cancel_event, progress_updater) -> None
        """
        if not callable(task_fn):
            return False, "task_fn must be callable"

        with self._lock:
            if self._progress["running"]:
                return False, "Task is already running"

            cancel_ev = self._initialize_task_state(total, status_msg, extra_initial_state)

        execution = _TaskExecution(
            worker=self,
            cancel_event=cancel_ev,
            task_fn=task_fn,
            on_complete=on_complete,
            on_error=on_error,
        )
        self._thread = threading.Thread(target=execution.run, daemon=True)
        self._thread.start()
        return True, "Task started successfully"

    def dispatch(
        self,
        runner: Callable,
        *args: Any,
        total: int = 10,
        status_msg: str = "Running...",
        api_success: Optional[Callable[..., Any]] = None,
        api_error: Optional[Callable[..., Any]] = None,
        extra_initial_state: Optional[dict] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[], None]] = None,
        **kwargs: Any,
    ) -> Any:
        """Dispatches runner to this worker using dispatch_worker_task."""
        return dispatch_worker_task(
            self,
            runner,
            *args,
            total=total,
            status_msg=status_msg,
            api_success=api_success,
            api_error=api_error,
            extra_initial_state=extra_initial_state,
            on_error=on_error,
            on_complete=on_complete,
            **kwargs,
        )


_ALLOWED_CANCEL_STATUSES = frozenset({"Cancelled", "Cancelling", "Error"})
_COMPLETION_STATUS_PREFIXES = (
    "Processed ",
    "Analyzing ",
    "Initializing",
    "Captioning",
    "Tagging",
)


class _TaskExecution:
    """Encapsulates execution context, cancel tracking, and progress filtering for a worker task."""

    def __init__(
        self,
        worker: BackgroundTaskWorker,
        cancel_event: threading.Event,
        task_fn: Callable[[threading.Event, Callable], None],
        on_complete: Optional[Callable] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
    ):
        self.worker = worker
        self.cancel_event = cancel_event
        self.task_fn = task_fn
        self.on_complete = on_complete
        self.on_error = on_error

    def is_current(self) -> bool:
        """A job is current only while its own event remains the worker's active event."""
        return self.worker._cancel_event is self.cancel_event

    def update_progress(self, *args: Any, **kwargs: Any) -> None:
        """Applies sanitized progress updates while holding worker lock."""
        with self.worker._lock:
            if not self.is_current():
                return
            if self.cancel_event.is_set():
                args, kwargs = self._filter_cancelled_progress(args, kwargs)
            self.worker._apply_progress(*args, **kwargs)

    def _filter_cancelled_progress(
        self, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> tuple[tuple[Any, ...], dict[str, Any]]:
        curr_status = self.worker._progress.get("status")
        current_ready = self.worker._progress.get("ready") is True
        args_list = list(args)
        kw = dict(kwargs)

        self._filter_status_arg_and_kw(args_list, kw, curr_status)
        kw.pop("running", None)
        self._filter_ready_flag(args_list, kw, current_ready)

        if isinstance(kw.get("extra"), dict):
            kw["extra"] = self._filter_extra(kw["extra"], curr_status, current_ready)

        return tuple(args_list), kw

    @staticmethod
    def _is_status_allowed_on_cancel(status_val: Any, curr_status: Optional[str]) -> bool:
        if curr_status == "Error":
            return False
        return status_val in _ALLOWED_CANCEL_STATUSES

    def _filter_status_arg_and_kw(
        self, args_list: list[Any], kw: dict[str, Any], curr_status: Optional[str]
    ) -> None:
        if "status" in kw and not self._is_status_allowed_on_cancel(kw["status"], curr_status):
            del kw["status"]
        elif len(args_list) >= 3 and args_list[2] is not None:
            if not self._is_status_allowed_on_cancel(args_list[2], curr_status):
                args_list[2] = None

    @staticmethod
    def _filter_ready_flag(args_list: list[Any], kw: dict[str, Any], current_ready: bool) -> None:
        if not current_ready:
            return
        if kw.get("ready") is False:
            del kw["ready"]
        if len(args_list) >= 5 and args_list[4] is False:
            args_list[4] = True

    def _filter_extra(
        self, extra: dict[str, Any], curr_status: Optional[str], current_ready: bool
    ) -> dict[str, Any]:
        extra_copy = dict(extra)
        if not self._is_status_allowed_on_cancel(extra_copy.get("status"), curr_status):
            extra_copy.pop("status", None)
        extra_copy.pop("running", None)
        if current_ready and extra_copy.get("ready") is False:
            extra_copy.pop("ready", None)
        return extra_copy

    def run(self) -> None:
        """Runs the task within auto-shutdown context and coordinates lifecycle transitions."""
        mgr = self.worker._auto_shutdown_manager
        busy_ctx = mgr.busy() if mgr else nullcontext()
        try:
            with busy_ctx:
                self.task_fn(self.cancel_event, self.update_progress)
        except Exception as e:
            self._handle_error(e)
            return

        self._handle_completion()

    def _handle_error(self, exc: Exception) -> None:
        import traceback
        traceback.print_exc()
        with self.worker._lock:
            if self.is_current():
                self.worker._progress["running"] = False
                self.worker._progress["status"] = "Error"
                self.worker._progress["message"] = str(exc)
        if self.on_error:
            try:
                self.on_error(exc)
            except Exception:
                pass

    def _handle_completion(self) -> None:
        with self.worker._lock:
            if not self.is_current():
                return  # replaced by a newer job; its progress is not ours to touch

            self.worker._progress["running"] = False
            self.worker._progress["ready"] = True

            if self.cancel_event.is_set():
                if self.worker._progress.get("status") != "Error":
                    self.worker._progress["status"] = "Cancelled"
                return

            curr_status = self.worker._progress.get("status", "")
            if not curr_status or curr_status.startswith(_COMPLETION_STATUS_PREFIXES):
                self.worker._progress["status"] = "Completed"

        if self.on_complete:
            try:
                self.on_complete()
            except Exception:
                pass


def _normalize_progress_callback_args(
    cb_args: tuple[Any, ...], cb_kwargs: dict[str, Any]
) -> dict[str, Any]:
    current = cb_kwargs.get("current")
    total_val = cb_kwargs.get("total")
    status = cb_kwargs.get("status")
    message = cb_kwargs.get("message")
    extra = cb_kwargs.get("extra")

    if len(cb_args) == 1:
        message = cb_args[0]
    elif len(cb_args) == 2:
        current, total_val = cb_args
    elif len(cb_args) == 3:
        current, total_val, message = cb_args
    elif len(cb_args) >= 4:
        current, total_val, status, message = cb_args[:4]

    update_dict: dict[str, Any] = {}
    if current is not None:
        update_dict["current"] = current
    if total_val is not None:
        update_dict["total"] = total_val
    if status is not None:
        update_dict["status"] = status
    if message is not None:
        update_dict["message"] = message
    if extra is not None:
        update_dict["extra"] = extra

    for k, v in cb_kwargs.items():
        if k not in ("current", "total", "status", "message", "extra"):
            update_dict[k] = v

    return update_dict


class _DispatchedTaskAdapter:
    """Adapts a runner callable with flexible progress_cb signatures to a worker task callable."""

    def __init__(self, runner: Callable, args: tuple[Any, ...], kwargs: dict[str, Any]):
        self.runner = runner
        self.args = args
        self.kwargs = kwargs

    def __call__(self, cancel_event: threading.Event, updater: Callable) -> None:
        def _cb(*cb_args: Any, **cb_kwargs: Any) -> None:
            updater(**_normalize_progress_callback_args(cb_args, cb_kwargs))

        self.runner(*self.args, cancel_event=cancel_event, progress_cb=_cb, **self.kwargs)


def dispatch_worker_task(
    worker: BackgroundTaskWorker,
    runner: Callable,
    *args: Any,
    total: int = 10,
    status_msg: str = "Running...",
    api_success: Optional[Callable[..., Any]] = None,
    api_error: Optional[Callable[..., Any]] = None,
    extra_initial_state: Optional[dict] = None,
    on_error: Optional[Callable[[Exception], None]] = None,
    on_complete: Optional[Callable[[], None]] = None,
    **kwargs: Any,
) -> Any:
    """Dispatches a long-running callable `runner` to `worker` with standard progress callback adapter.

    `runner` is called as `runner(*args, cancel_event=cancel_event, progress_cb=cb, **kwargs)`.
    `cb` accepts flexible positional or keyword arguments for progress updates.
    Returns standard success or 409 error envelope.
    """
    if not callable(runner):
        msg = "runner must be callable"
        if api_error:
            return api_error(msg, code=400)
        return {"status": "error", "message": msg}, 400

    if worker.is_running():
        msg = f"Task is already running: {worker.get_status().get('status', 'busy')}"
        if api_error:
            return api_error(msg, code=409)
        return {"status": "error", "message": msg}, 409

    task_fn = _DispatchedTaskAdapter(runner, args, kwargs)

    started, msg = worker.start(
        task_fn=task_fn,
        total=total,
        status_msg=status_msg,
        extra_initial_state=extra_initial_state,
        on_error=on_error,
        on_complete=on_complete,
    )
    if not started:
        if api_error:
            return api_error(msg, code=409)
        return {"status": "error", "message": msg}, 409

    if api_success:
        return api_success(started=True)
    return {"status": "success", "started": True}, 200
