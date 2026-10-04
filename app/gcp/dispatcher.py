"""Run slow, best-effort cloud calls off the request thread.

A Pub/Sub publish or Cloud Tasks enqueue can take a second or more (and up
to ~20s with the REST helper's timeout + retry during an outage). Doing that
inside the request that creates a task would make the whole app as slow as
Google's worst moment, so integrations hand their work to daemon threads.

Two lanes, each its own bounded queue and thread per worker process:
  * "critical" — the Cloud Tasks start-now scheduling. It is time-sensitive
    and must not wait behind telemetry stuck on a slow BigQuery/Pub/Sub.
  * "bulk" — events, PDF archiving, calendar sync, metrics.
A full queue drops new work (logged) instead of growing memory on a 1 GB VM.
Every job is wrapped so one failure never kills its thread. Queued jobs are
lost if the worker restarts — they are best-effort by design (the cron sweep
is the safety net for reminders) — except on a normal restart: the first job
submitted in a process installs an atexit hook that waits up to EXIT_DRAIN_SECONDS
for the queues to empty, so `systemctl restart` does not drop queued calendar
and event jobs."""

import atexit
import logging
import queue
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)

MAX_QUEUED = 500
# Well inside gunicorn's --graceful-timeout (20 s) and systemd's TimeoutStopSec (30 s).
EXIT_DRAIN_SECONDS = 8.0
LANES = ("critical", "bulk")

_queues: dict[str, queue.Queue] = {lane: queue.Queue(maxsize=MAX_QUEUED) for lane in LANES}
_threads: dict[str, threading.Thread | None] = {lane: None for lane in LANES}
_thread_lock = threading.Lock()
_exit_hook_installed = False
# Tests flip this so assertions can run right after the request returns.
synchronous = False


def _run(job: Callable[[], None]) -> None:
    try:
        job()
    except Exception:  # noqa: BLE001 — a failed integration must never escape
        logger.exception("integration_job_failed")


def _worker(lane: str) -> None:
    q = _queues[lane]
    while True:
        job = q.get()
        try:
            _run(job)
        finally:
            q.task_done()


def _drain_at_exit() -> None:
    if not drain(EXIT_DRAIN_SECONDS):
        left = sum(q.qsize() for q in _queues.values())
        logger.warning("dispatcher_drain_timeout seconds=%s jobs_left=%s", EXIT_DRAIN_SECONDS, left)


def _install_exit_hook() -> None:
    """Once per process, and only once real background work exists: tests (which
    run jobs synchronously) and one-off scripts never reach this. Registered in
    the worker after the fork, where the queues actually live."""
    global _exit_hook_installed
    if not _exit_hook_installed:
        atexit.register(_drain_at_exit)
        _exit_hook_installed = True


def pending(lane: str = "bulk") -> int:
    return _queues[lane].qsize()


def submit(job: Callable[[], None], *, lane: str = "bulk") -> None:
    if synchronous:
        _run(job)
        return
    # Started lazily, after gunicorn has forked: a thread created at import
    # time in the master process would not exist in the workers.
    with _thread_lock:
        thread = _threads[lane]
        if thread is None or not thread.is_alive():
            thread = threading.Thread(target=_worker, args=(lane,), name=f"gcp-{lane}", daemon=True)
            thread.start()
            _threads[lane] = thread
            _install_exit_hook()
    try:
        _queues[lane].put_nowait(job)
    except queue.Full:
        logger.error("integration_queue_full lane=%s dropped_job=true", lane)


def drain(timeout: float = 5.0) -> bool:
    """Block until queued jobs finish (graceful shutdown / scripts); False if
    `timeout` seconds passed first."""
    done = threading.Event()

    def waiter() -> None:
        for q in _queues.values():
            q.join()
        done.set()

    threading.Thread(target=waiter, daemon=True).start()
    return done.wait(timeout)
