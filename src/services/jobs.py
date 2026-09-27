"""
jobs.py
-------
Minimal background-job runner so a slow /analyzeContour call doesn't
block the Flask request thread (or a mobile client's HTTP timeout) for
the whole duration of DEM interpolation + flow accumulation on a large
contour map.

Design notes (CSD: Concurrency / Asynchronous Processing):
- A small ThreadPoolExecutor runs analysis jobs off the request thread.
  Threads (not processes) are enough here because the heavy work is
  numpy/scipy, which releases the GIL for most of its runtime -- no
  need for the complexity of multiprocessing + pickling DEM arrays
  across a process boundary.
- Job state lives in an in-memory dict guarded by a lock. That's the
  right amount of machinery for a single-process app like this one; if
  the app were ever scaled to multiple worker processes/machines, this
  dict would need to move to something shared (Redis, the SQLite cache
  in cache.py, etc.) -- noted here rather than over-built now.
- This module knows nothing about ponds, contours or Flask: it exposes
  submit(fn, *args, **kwargs) -> job_id and get_status(job_id), so it
  can run *any* callable in the background. app.py is the only place
  that knows it's being used to run the pond analysis pipeline.
"""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="pond-analysis")
_lock = threading.Lock()
_jobs: dict[str, "Job"] = {}


@dataclass
class Job:
    job_id: str
    status: str = "pending"  # pending -> running -> done | error
    result: Any = None
    error: str | None = None


def _run_and_record(job_id: str, fn: Callable, args: tuple, kwargs: dict) -> None:
    with _lock:
        _jobs[job_id].status = "running"
    try:
        result = fn(*args, **kwargs)
        with _lock:
            _jobs[job_id].status = "done"
            _jobs[job_id].result = result
    except Exception as exc:  # noqa: BLE001 - deliberately broad: surfaced via /jobs/<id>
        with _lock:
            _jobs[job_id].status = "error"
            _jobs[job_id].error = str(exc)


def submit(fn: Callable, *args, **kwargs) -> str:
    """Schedule fn(*args, **kwargs) to run in the background; returns a job id."""
    job_id = uuid.uuid4().hex
    # Register the job record BEFORE handing work to the executor: a
    # worker thread can call _run_and_record the instant executor.submit()
    # is invoked, and it looks itself up by job_id immediately -- if that
    # lookup can happen before this dict entry exists, it's a KeyError.
    with _lock:
        _jobs[job_id] = Job(job_id=job_id)
    _executor.submit(_run_and_record, job_id, fn, args, kwargs)
    return job_id


def get_status(job_id: str) -> dict:
    """
    Poll a job. Returns one of:
      {"status": "pending" | "running"}
      {"status": "done", "result": <return value of fn>}
      {"status": "error", "error": "<message>"}
      {"status": "not_found"}
    """
    with _lock:
        job = _jobs.get(job_id)
    if job is None:
        return {"status": "not_found"}
    if job.status == "done":
        return {"status": "done", "result": job.result}
    if job.status == "error":
        return {"status": "error", "error": job.error}
    return {"status": job.status}
