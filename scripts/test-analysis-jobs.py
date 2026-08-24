#!/usr/bin/env python3
"""Stress the bounded analysis queue without decoding real media."""

from pathlib import Path
import tempfile
import threading
import time
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from analysis_jobs import AnalysisJobManager, TERMINAL_STATES
from clip_analysis import ClipAnalysisError


def wait_for(manager: AnalysisJobManager, job_id: str, timeout: float = 15.0):
    deadline = time.time() + timeout
    progress = []
    while time.time() < deadline:
        status = manager.get_status(job_id)
        progress.append(status["progress"])
        if status["state"] in TERMINAL_STATES:
            assert progress == sorted(progress), "progress must be monotonic"
            return status
        time.sleep(0.01)
    raise AssertionError("analysis job did not finish within its bounded test timeout")


def main() -> None:
    active = 0
    peak = 0
    lock = threading.Lock()

    def analyzer(path: str, cancel_event=None):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            for _ in range(2):
                if cancel_event and cancel_event.is_set():
                    raise ClipAnalysisError("cancelled", "cancelled")
                time.sleep(0.0005)
            if "corrupt" in path:
                raise ClipAnalysisError("decode_failed", "isolated corrupt fixture")
            return ({"path": path, "name": Path(path).name, "usable": True}, path.endswith("0.mov"))
        finally:
            with lock:
                active -= 1

    with tempfile.TemporaryDirectory() as directory:
        manager = AnalysisJobManager(Path(directory) / "jobs.sqlite3", worker_count=2, analyzer=analyzer)
        paths = [f"/virtual/clip-{index}.mov" for index in range(1000)] + ["/virtual/corrupt.mov"]
        created = manager.create_job(paths + [paths[0]])
        assert created["total"] == 1001, "duplicate paths must be coalesced"
        completed = wait_for(manager, created["jobId"])
        assert completed["state"] == "completed_with_errors"
        assert completed["succeeded"] == 1000
        assert completed["failed"] == 1
        assert completed["cached"] > 0
        assert peak <= 2, f"bounded queue exceeded two workers: {peak}"
        result = manager.get_results(created["jobId"])
        assert len(result["results"]) == 1000
        assert len(result["errors"]) == 1
        manager.work_queue.join()

    with tempfile.TemporaryDirectory() as directory:
        manager = AnalysisJobManager(Path(directory) / "jobs.sqlite3", worker_count=2, analyzer=analyzer)
        created = manager.create_job([f"/virtual/cancel-{index}.mov" for index in range(50000)])
        assert manager.health()["queueDepth"] <= 2, "media count must not become in-memory queue depth"
        manager.cancel(created["jobId"])
        cancelled = wait_for(manager, created["jobId"])
        assert cancelled["state"] == "cancelled"
        assert cancelled["completed"] == cancelled["total"]
        followup_started = time.monotonic()
        followup = manager.create_job(["/virtual/followup.mov"])
        followup_result = wait_for(manager, followup["jobId"], timeout=2.0)
        assert followup_result["state"] == "completed"
        assert time.monotonic() - followup_started < 2.0, "cancelled queue delayed the next job"
        manager.work_queue.join()

    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "jobs.sqlite3"
        idle_manager = AnalysisJobManager(database, worker_count=1, analyzer=analyzer)
        with idle_manager._connection() as connection:
            connection.execute(
                "INSERT INTO jobs (id, state, total, created_at, started_at) VALUES ('recovered-job', 'running', 2, ?, ?)",
                (time.time(), time.time()),
            )
            connection.executemany(
                "INSERT INTO job_items (job_id, position, path, state) VALUES ('recovered-job', ?, ?, 'running')",
                [(0, "/virtual/recovered-0.mov"), (1, "/virtual/recovered-1.mov")],
            )
        recovered_manager = AnalysisJobManager(database, worker_count=1, analyzer=analyzer)
        recovered = wait_for(recovered_manager, "recovered-job")
        assert recovered["state"] == "completed"
        assert recovered["succeeded"] == 2
        recovered_manager.work_queue.join()

    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "jobs.sqlite3"
        seed_manager = AnalysisJobManager(database, worker_count=1, analyzer=analyzer)
        now = time.time()
        with seed_manager._connection() as connection:
            connection.execute(
                """
                INSERT INTO jobs
                    (id, state, total, cancel_requested, created_at, started_at)
                VALUES ('restart-cancelling', 'cancelling', 3, 1, ?, ?)
                """,
                (now, now),
            )
            connection.executemany(
                """
                INSERT INTO job_items
                    (job_id, position, path, state, result_json, finished_at)
                VALUES ('restart-cancelling', ?, ?, ?, ?, ?)
                """,
                [
                    (0, "/virtual/already-done.mov", "succeeded", '{"path":"/virtual/already-done.mov"}', now),
                    (1, "/virtual/interrupted.mov", "running", None, None),
                    (2, "/virtual/not-started.mov", "queued", None, None),
                ],
            )
        recovered_manager = AnalysisJobManager(database, worker_count=1, analyzer=analyzer)
        recovered = recovered_manager.get_status("restart-cancelling")
        assert recovered["state"] == "cancelled"
        assert recovered["completed"] == recovered["total"] == 3
        assert recovered["succeeded"] == 1
        assert recovered["cancelled"] == 2
        assert recovered_manager.health()["queueDepth"] == 0

    print(
        "Analysis job tests passed "
        "(1,001-file bounded run, isolation, dedupe, progress, 50,000-file cancellation, "
        "prompt follow-up, ordinary restart recovery, cancelling restart recovery)."
    )


if __name__ == "__main__":
    main()
