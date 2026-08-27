"""Persistent bounded analysis jobs with progress, cancellation, and resume."""

from __future__ import annotations

import json
import os
import queue
import sqlite3
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, Tuple

from clip_analysis import ClipAnalysisError, classify_clip_cached


DEFAULT_DB = Path(
    os.environ.get(
        "FLAGSHIPEDITOR_JOBS_DB",
        str(
            Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()))
            / "ake-studio"
            / "FlagshipEditor"
            / "cache"
            / "jobs.sqlite3"
        ),
    )
)
TERMINAL_STATES = {"completed", "completed_with_errors", "cancelled", "failed"}


class AnalysisJobManager:
    def __init__(
        self,
        database_path: Path = DEFAULT_DB,
        worker_count: int = 2,
        analyzer: Callable[..., Tuple[Dict[str, Any], bool]] = classify_clip_cached,
    ) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.worker_count = max(1, min(2, int(worker_count)))
        self.analyzer = analyzer
        # The queue contains a bounded number of scheduler tokens per job, not
        # one entry per media file. Workers claim the next item from SQLite.
        # This keeps cancellation O(1) in memory even for 50,000-file jobs.
        self.work_queue: queue.Queue[str] = queue.Queue()
        self.cancel_events: Dict[str, threading.Event] = {}
        self.current_files: Dict[int, Tuple[str, str]] = {}
        self.lock = threading.RLock()
        self._initialize_database()
        self._recover_jobs()
        self.workers = []
        for worker_index in range(self.worker_count):
            worker = threading.Thread(
                target=self._worker_loop,
                args=(worker_index,),
                daemon=True,
                name=f"flagship-analysis-{worker_index + 1}",
            )
            worker.start()
            self.workers.append(worker)

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.database_path), timeout=20)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=20000")
        return connection

    def _initialize_database(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    total INTEGER NOT NULL,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    finished_at REAL
                );
                CREATE TABLE IF NOT EXISTS job_items (
                    job_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    path TEXT NOT NULL,
                    state TEXT NOT NULL,
                    result_json TEXT,
                    error_code TEXT,
                    error_message TEXT,
                    cached INTEGER NOT NULL DEFAULT 0,
                    started_at REAL,
                    finished_at REAL,
                    PRIMARY KEY (job_id, position),
                    FOREIGN KEY (job_id) REFERENCES jobs(id)
                );
                CREATE INDEX IF NOT EXISTS job_items_state ON job_items(job_id, state);
                """
            )

    def _recover_jobs(self) -> None:
        now = time.time()
        with self._connection() as connection:
            # A process restart means no analyzer can still own a running item.
            # Honour persisted cancellation before recovering ordinary work so
            # a job cannot remain in `cancelling` forever after a crash/restart.
            connection.execute(
                """
                UPDATE job_items
                SET state = 'cancelled', finished_at = COALESCE(finished_at, ?)
                WHERE state IN ('queued', 'running')
                  AND job_id IN (SELECT id FROM jobs WHERE cancel_requested = 1)
                """,
                (now,),
            )
            connection.execute(
                """
                UPDATE jobs
                SET state = 'cancelled', finished_at = COALESCE(finished_at, ?)
                WHERE cancel_requested = 1
                  AND state NOT IN ('completed', 'completed_with_errors', 'cancelled', 'failed')
                """,
                (now,),
            )
            connection.execute(
                """
                UPDATE job_items SET state = 'queued', started_at = NULL
                WHERE state = 'running'
                  AND job_id IN (SELECT id FROM jobs WHERE cancel_requested = 0)
                """
            )
            connection.execute(
                "UPDATE jobs SET state = 'queued', started_at = NULL WHERE state = 'running' AND cancel_requested = 0"
            )
            rows = connection.execute(
                """
                SELECT item.job_id, COUNT(*) AS queued_count
                FROM job_items item JOIN jobs job ON job.id = item.job_id
                WHERE item.state = 'queued' AND job.cancel_requested = 0
                GROUP BY item.job_id
                ORDER BY job.created_at
                """
            ).fetchall()
            for row in rows:
                self._schedule_job(row["job_id"], row["queued_count"])
            # Finalize any cancelling jobs that have no remaining queued work.
            # Without this, a job can remain in `cancelling` forever after a
            # restart if its workers were interrupted mid-item.
            stuck = connection.execute(
                """
                SELECT j.id FROM jobs j
                WHERE j.state = 'cancelling'
                  AND NOT EXISTS (
                    SELECT 1 FROM job_items i
                    WHERE i.job_id = j.id AND i.state = 'queued'
                  )
                """
            ).fetchall()
            for row in stuck:
                self._refresh_job_state_locked(connection, row["id"])

    def _schedule_job(self, job_id: str, queued_count: int) -> None:
        for _ in range(min(self.worker_count, max(0, int(queued_count)))):
            self.work_queue.put(job_id)

    def _claim_next_item(self, job_id: str) -> Optional[Tuple[int, str]]:
        """Atomically claim the next queued item unless cancellation won."""
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = connection.execute(
                "SELECT cancel_requested, state FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if not job or job["cancel_requested"]:
                return None
            # FIX: skip tokens for jobs already in a terminal state (e.g.
            # cancelled during restart recovery).  Prevents a finalised job
            # from being flipped back to ``cancelling`` by _refresh_job_state.
            if job["state"] in TERMINAL_STATES:
                return None
            item = connection.execute(
                """
                SELECT position, path FROM job_items
                WHERE job_id = ? AND state = 'queued'
                ORDER BY position LIMIT 1
                """,
                (job_id,),
            ).fetchone()
            if not item:
                return None
            started_at = time.time()
            updated = connection.execute(
                """
                UPDATE job_items SET state = 'running', started_at = ?
                WHERE job_id = ? AND position = ? AND state = 'queued'
                """,
                (started_at, job_id, item["position"]),
            ).rowcount
            if not updated:
                return None
            connection.execute(
                """
                UPDATE jobs SET state = 'running', started_at = COALESCE(started_at, ?)
                WHERE id = ? AND cancel_requested = 0
                """,
                (started_at, job_id),
            )
            return item["position"], item["path"]

    def _has_queued_work(self, job_id: str) -> bool:
        with self._connection() as connection:
            return bool(
                connection.execute(
                    """
                    SELECT 1 FROM job_items item JOIN jobs job ON job.id = item.job_id
                    WHERE item.job_id = ? AND item.state = 'queued' AND job.cancel_requested = 0
                    LIMIT 1
                    """,
                    (job_id,),
                ).fetchone()
            )

    @staticmethod
    def _deduplicate(paths: Iterable[str]) -> list[str]:
        output, seen = [], set()
        for path in paths:
            absolute = os.path.abspath(str(path))
            identity = os.path.normcase(absolute)
            if identity not in seen:
                seen.add(identity)
                output.append(absolute)
        return output

    def create_job(self, paths: Iterable[str]) -> Dict[str, Any]:
        unique_paths = self._deduplicate(paths)
        if not unique_paths:
            raise ValueError("No media paths were supplied")
        if len(unique_paths) > 50000:
            raise ValueError("A library job is limited to 50,000 unique media files")
        job_id = uuid.uuid4().hex
        now = time.time()
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO jobs (id, state, total, created_at) VALUES (?, 'queued', ?, ?)",
                (job_id, len(unique_paths), now),
            )
            connection.executemany(
                "INSERT INTO job_items (job_id, position, path, state) VALUES (?, ?, ?, 'queued')",
                [(job_id, position, path) for position, path in enumerate(unique_paths)],
            )
        self.cancel_events[job_id] = threading.Event()
        self._schedule_job(job_id, len(unique_paths))
        return self.get_status(job_id)

    def _is_cancelled(self, job_id: str) -> bool:
        event = self.cancel_events.get(job_id)
        if event and event.is_set():
            return True
        with self._connection() as connection:
            row = connection.execute("SELECT cancel_requested FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return not row or bool(row[0])

    def _worker_loop(self, worker_index: int) -> None:
        while True:
            job_id = self.work_queue.get()
            try:
                if self._is_cancelled(job_id):
                    self._refresh_job_state(job_id)
                    continue
                claimed = self._claim_next_item(job_id)
                if not claimed:
                    self._refresh_job_state(job_id)
                    continue
                position, path = claimed
                event = self.cancel_events.setdefault(job_id, threading.Event())
                with self.lock:
                    self.current_files[worker_index] = (job_id, path)
                try:
                    result, cache_hit = self.analyzer(path, cancel_event=event)
                    serialized = json.dumps(result, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
                    with self._connection() as connection:
                        connection.execute(
                            """
                            UPDATE job_items SET state = 'succeeded', result_json = ?, cached = ?, finished_at = ?
                            WHERE job_id = ? AND position = ?
                            """,
                            (serialized, int(cache_hit), time.time(), job_id, position),
                        )
                except ClipAnalysisError as error:
                    if error.code == "cancelled" or event.is_set():
                        self._mark_item_cancelled(job_id, position)
                    else:
                        self._mark_item_failed(job_id, position, error.code, str(error))
                except Exception as error:  # isolate every source-file failure
                    self._mark_item_failed(job_id, position, "analysis_failed", str(error))
                finally:
                    with self.lock:
                        self.current_files.pop(worker_index, None)
                if self._has_queued_work(job_id):
                    # Reuse this token at the tail. Other jobs can therefore
                    # start promptly instead of waiting behind a huge library.
                    self.work_queue.put(job_id)
            finally:
                self._refresh_job_state(job_id)
                self.work_queue.task_done()

    def _mark_item_cancelled(self, job_id: str, position: int) -> None:
        with self._connection() as connection:
            connection.execute(
                "UPDATE job_items SET state = 'cancelled', finished_at = ? WHERE job_id = ? AND position = ? AND state IN ('queued', 'running')",
                (time.time(), job_id, position),
            )

    def _mark_item_failed(self, job_id: str, position: int, code: str, message: str) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE job_items SET state = 'failed', error_code = ?, error_message = ?, finished_at = ?
                WHERE job_id = ? AND position = ?
                """,
                (code[:80], message[-1000:], time.time(), job_id, position),
            )

    def _drain_queue_tokens(self, job_id: str) -> None:
        """Remove scheduler tokens for a cancelled job without blocking workers."""
        drained: list[str] = []
        while True:
            try:
                token = self.work_queue.get_nowait()
            except queue.Empty:
                break
            if token != job_id:
                drained.append(token)
            else:
                # A retired token must settle the queue's unfinished-task
                # ledger, or work_queue.join() blocks forever on a token
                # nobody holds.
                self.work_queue.task_done()
        for token in drained:
            # put-then-task_done keeps unfinished_tasks from transiently
            # hitting zero, which would wake a concurrent join() early.
            self.work_queue.put(token)
            self.work_queue.task_done()

    def _refresh_job_state_locked(self, connection: sqlite3.Connection, job_id: str) -> None:
        """Refresh job state using an existing connection (for recovery paths)."""
        job = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not job:
            return
        # A finalised job is never reopened. Without this, a worker refresh that
        # was already in flight when cancel() finished would overwrite the
        # terminal state and strand the job in 'running' forever.
        if job["state"] in TERMINAL_STATES:
            return
        counts = {
            row["state"]: row["count"]
            for row in connection.execute(
                "SELECT state, COUNT(*) AS count FROM job_items WHERE job_id = ? GROUP BY state",
                (job_id,),
            ).fetchall()
        }
        done = counts.get("succeeded", 0) + counts.get("failed", 0) + counts.get("cancelled", 0)
        if done < job["total"]:
            state = "cancelling" if job["cancel_requested"] else "running"
            connection.execute("UPDATE jobs SET state = ? WHERE id = ?", (state, job_id))
            return
        if job["cancel_requested"] or counts.get("cancelled", 0):
            state = "cancelled"
        elif counts.get("succeeded", 0) == 0:
            state = "failed"
        elif counts.get("failed", 0):
            state = "completed_with_errors"
        else:
            state = "completed"
        connection.execute(
            "UPDATE jobs SET state = ?, finished_at = COALESCE(finished_at, ?) WHERE id = ?",
            (state, time.time(), job_id),
        )

    def _refresh_job_state(self, job_id: str) -> None:
        # BEGIN IMMEDIATE so the count/read and the state write are one
        # serialized transaction. A plain read-modify-write lets a worker act on
        # a pre-cancel snapshot and clobber the state cancel() just wrote.
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._refresh_job_state_locked(connection, job_id)

    def cancel(self, job_id: str) -> Dict[str, Any]:
        event = self.cancel_events.setdefault(job_id, threading.Event())
        event.set()
        with self._connection() as connection:
            if not connection.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,)).fetchone():
                raise KeyError(job_id)
            connection.execute("UPDATE jobs SET cancel_requested = 1, state = 'cancelling' WHERE id = ?", (job_id,))
            connection.execute(
                "UPDATE job_items SET state = 'cancelled', finished_at = ? WHERE job_id = ? AND state = 'queued'",
                (time.time(), job_id),
            )
        # Drain scheduler tokens for this job so cancelled tombstones do not
        # delay the next job. Workers skip any stale tokens via _is_cancelled.
        self._drain_queue_tokens(job_id)
        self._refresh_job_state(job_id)
        return self.get_status(job_id)

    def get_status(self, job_id: str) -> Dict[str, Any]:
        with self._connection() as connection:
            job = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not job:
                raise KeyError(job_id)
            counts = {
                row["state"]: row["count"]
                for row in connection.execute(
                    "SELECT state, COUNT(*) AS count FROM job_items WHERE job_id = ? GROUP BY state",
                    (job_id,),
                ).fetchall()
            }
            cached = connection.execute(
                "SELECT COUNT(*) FROM job_items WHERE job_id = ? AND cached = 1",
                (job_id,),
            ).fetchone()[0]
            errors = [
                {"path": row["path"], "code": row["error_code"], "message": row["error_message"]}
                for row in connection.execute(
                    "SELECT path, error_code, error_message FROM job_items WHERE job_id = ? AND state = 'failed' ORDER BY position LIMIT 200",
                    (job_id,),
                ).fetchall()
            ]
        succeeded = counts.get("succeeded", 0)
        failed = counts.get("failed", 0)
        cancelled = counts.get("cancelled", 0)
        completed = succeeded + failed + cancelled
        started = job["started_at"] or job["created_at"]
        end = job["finished_at"] or time.time()
        elapsed = max(0.0, end - started)
        rate = completed / elapsed if completed and elapsed > 0 else 0.0
        eta = (job["total"] - completed) / rate if rate > 0 and job["state"] not in TERMINAL_STATES else None
        with self.lock:
            current = [path for active_job, path in self.current_files.values() if active_job == job_id]
        return {
            "jobId": job_id,
            "state": job["state"],
            "total": job["total"],
            "completed": completed,
            "succeeded": succeeded,
            "failed": failed,
            "cancelled": cancelled,
            "cached": cached,
            "progress": round((completed / job["total"]) * 100.0, 2) if job["total"] else 100.0,
            "currentFiles": current,
            "elapsedSeconds": round(elapsed, 1),
            "etaSeconds": round(eta, 1) if eta is not None else None,
            "errorCount": failed,
            "errors": errors,
        }

    def get_results(self, job_id: str) -> Dict[str, Any]:
        status = self.get_status(job_id)
        if status["state"] not in TERMINAL_STATES:
            raise RuntimeError("Analysis job is not finished")
        with self._connection() as connection:
            results = [
                json.loads(row["result_json"])
                for row in connection.execute(
                    "SELECT result_json FROM job_items WHERE job_id = ? AND state = 'succeeded' ORDER BY position",
                    (job_id,),
                ).fetchall()
            ]
        return {"jobId": job_id, "state": status["state"], "results": results, "errors": status["errors"]}

    def health(self) -> Dict[str, Any]:
        with self._connection() as connection:
            running = connection.execute(
                "SELECT COUNT(*) FROM jobs WHERE state IN ('queued', 'running', 'cancelling')"
            ).fetchone()[0]
        return {
            "workers": self.worker_count,
            "queueDepth": self.work_queue.qsize(),
            "activeJobs": running,
            "persistent": True,
        }
