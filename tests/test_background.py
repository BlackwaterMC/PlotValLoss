"""Tests for background.BackgroundTaskWorker / dispatch_worker_task: progress, cancel, restart."""

import threading
import time

from background import BackgroundTaskWorker, dispatch_worker_task


def _wait_until(pred, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(0.01)
    return False


def test_task_runs_reports_progress_and_completes():
    worker = BackgroundTaskWorker()

    def task(cancel_event, update):
        update(current=5, total=10, status="Processed 5")
        update(current=10, total=10, status="Processed 10")

    ok, _ = worker.start(task, total=10)
    assert ok
    assert _wait_until(lambda: not worker.is_running())
    st = worker.get_status()
    assert st["ready"] is True and st["status"] == "Completed" and st["percent"] == 100.0


def test_second_start_while_running_is_refused():
    worker = BackgroundTaskWorker()
    release = threading.Event()
    worker.start(lambda cancel, update: release.wait(5), total=1)
    ok, msg = worker.start(lambda cancel, update: None, total=1)
    assert ok is False and "already running" in msg
    release.set()
    assert _wait_until(lambda: not worker.is_running())


def test_cancel_marks_cancelled_and_old_task_cannot_clobber_a_restart():
    worker = BackgroundTaskWorker()
    first_started = threading.Event()
    release_first = threading.Event()

    def first(cancel_event, update):
        first_started.set()
        release_first.wait(5)
        update(current=99, total=100, status="Processed 99")   # late update from the cancelled job

    worker.start(first, total=100)
    assert first_started.wait(5)
    worker.cancel()
    st = worker.get_status()
    assert st["running"] is False and st["status"] == "Cancelled" and st["ready"] is True

    second_release = threading.Event()
    ok, _ = worker.start(lambda cancel, update: second_release.wait(5), total=7)
    assert ok
    release_first.set()                       # old job finishes now; must not touch the new job's state
    time.sleep(0.2)
    st = worker.get_status()
    assert st["running"] is True and st["total"] == 7 and st["current"] == 0 and st["status"] == "Initializing..."
    second_release.set()
    assert _wait_until(lambda: not worker.is_running())
    assert worker.get_status()["status"] == "Completed"


def test_exception_in_task_sets_error_status():
    worker = BackgroundTaskWorker()

    def task(cancel, update):
        raise ValueError("bad scan")

    worker.start(task, total=1)
    assert _wait_until(lambda: not worker.is_running())
    st = worker.get_status()
    assert st["status"] == "Error" and "bad scan" in st["message"]


def test_busy_context_is_held_while_a_task_runs():
    class FakeManager:
        def __init__(self):
            self.depth = 0
            self.max_depth = 0

        def busy(self):
            mgr = self

            class _Ctx:
                def __enter__(self_inner):
                    mgr.depth += 1
                    mgr.max_depth = max(mgr.max_depth, mgr.depth)

                def __exit__(self_inner, *a):
                    mgr.depth -= 1
            return _Ctx()

    mgr = FakeManager()
    worker = BackgroundTaskWorker(auto_shutdown_manager=mgr)
    worker.start(lambda cancel, update: None, total=1)
    assert _wait_until(lambda: not worker.is_running())
    assert mgr.max_depth == 1 and mgr.depth == 0


def test_dispatch_returns_409_envelope_when_busy():
    worker = BackgroundTaskWorker()
    release = threading.Event()
    body, code = dispatch_worker_task(worker, lambda cancel_event, progress_cb: release.wait(5), total=1)
    assert code == 200 and body["started"] is True
    body2, code2 = dispatch_worker_task(worker, lambda cancel_event, progress_cb: None, total=1)
    assert code2 == 409 and body2["status"] == "error"
    release.set()
    assert _wait_until(lambda: not worker.is_running())


def test_dispatch_progress_callback_accepts_positional_and_keyword_forms():
    worker = BackgroundTaskWorker()

    def runner(cancel_event, progress_cb):
        progress_cb(3, 4, "Reading x...")
        progress_cb(status="Completed", current=4, total=4, ready=True, extra={"runs_count": 4})

    dispatch_worker_task(worker, runner, total=4)
    assert _wait_until(lambda: not worker.is_running())
    st = worker.get_status()
    assert st["runs_count"] == 4 and st["current"] == 4 and st["ready"] is True
