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


def join_queue(manager: AnalysisJobManager, timeout: float = 10.0) -> None:
    """Bounded work_queue.join(): a lost task_done must fail, not hang."""
    joiner = threading.Thread(target=manager.work_queue.join, daemon=True)
    joiner.start()
    joiner.join(timeout)
    assert not joiner.is_alive(), (
        "work_queue.join() blocked: unfinished-task ledger desynced "
        f"(unfinished_tasks={manager.work_queue.unfinished_tasks})"
    )


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
        join_queue(manager)

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
        join_queue(manager)

    # Cancelling a job whose scheduler tokens are still sitting in the queue
    # (workers busy elsewhere) must keep the queue's unfinished-task ledger
    # balanced, or every later work_queue.join() deadlocks.
    gate = threading.Event()

    def gated_analyzer(path: str, cancel_event=None):
        if "blocker" in path:
            gate.wait(timeout=30)
        if cancel_event and cancel_event.is_set():
            raise ClipAnalysisError("cancelled", "cancelled")
        return ({"path": path, "name": Path(path).name, "usable": True}, False)

    with tempfile.TemporaryDirectory() as directory:
        manager = AnalysisJobManager(
            Path(directory) / "jobs.sqlite3", worker_count=2, analyzer=gated_analyzer
        )
        blockers = manager.create_job(["/virtual/blocker-0.mov", "/virtual/blocker-1.mov"])
        deadline = time.time() + 5.0
        while time.time() < deadline and manager.work_queue.qsize() > 0:
            time.sleep(0.01)  # both workers now hold their tokens
        parked = manager.create_job(["/virtual/parked-0.mov", "/virtual/parked-1.mov"])
        assert manager.work_queue.qsize() >= 2, "parked job tokens must be queued"
        manager.cancel(parked["jobId"])
        gate.set()
        assert wait_for(manager, blockers["jobId"])["state"] == "completed"
        assert wait_for(manager, parked["jobId"])["state"] == "cancelled"
        join_queue(manager)

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
        join_queue(recovered_manager)

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
        "prompt follow-up, token-drain ledger balance, ordinary restart recovery, "
        "cancelling restart recovery)."
    )


if __name__ == "__main__":
    main()
