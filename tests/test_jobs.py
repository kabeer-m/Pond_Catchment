"""
Unit tests for jobs.py (background job runner on a thread pool).

CSD: Testing Strategy + Concurrency/Asynchronous Processing. The last
test below pins down a real race condition that showed up during
development: a worker thread could start executing a job and look
itself up by job_id before the submitting thread had finished writing
that job's dict entry, raising a KeyError inside the pool. That's
exactly the kind of bug concurrent code needs a regression test for.
"""

import time

import jobs


def test_successful_job_reaches_done_with_its_result():
    job_id = jobs.submit(lambda x: x * 2, 21)
    for _ in range(50):
        status = jobs.get_status(job_id)
        if status["status"] == "done":
            break
        time.sleep(0.01)
    assert status == {"status": "done", "result": 42}


def test_failing_job_reaches_error_status():
    def boom():
        raise ValueError("synthetic failure")

    job_id = jobs.submit(boom)
    for _ in range(50):
        status = jobs.get_status(job_id)
        if status["status"] == "error":
            break
        time.sleep(0.01)
    assert status == {"status": "error", "error": "synthetic failure"}


def test_unknown_job_id_reports_not_found():
    assert jobs.get_status("does-not-exist") == {"status": "not_found"}


def test_many_concurrent_submissions_never_raise_a_keyerror():
    # Regression test: hammer submit() with fast jobs so a worker thread
    # is very likely to try to record "running" before this loop moves
    # on, reproducing the race described in the module docstring above
    # if the job record isn't registered before the executor starts it.
    job_ids = [jobs.submit(lambda: "ok") for _ in range(200)]
    deadline = time.time() + 5
    while time.time() < deadline:
        statuses = [jobs.get_status(j)["status"] for j in job_ids]
        if all(s == "done" for s in statuses):
            break
        time.sleep(0.01)
    assert all(jobs.get_status(j) == {"status": "done", "result": "ok"} for j in job_ids)
