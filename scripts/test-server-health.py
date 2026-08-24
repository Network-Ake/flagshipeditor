#!/usr/bin/env python3
"""Verify the backend health identity used for safe process recovery."""

import os
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        os.environ["FLAGSHIPEDITOR_JOBS_DB"] = str(Path(directory) / "jobs.sqlite3")
        import server

        payload = server.health()
        assert payload["appId"] == server.APP_ID
        assert payload["version"] == server.APP_VERSION
        assert payload["processId"] == os.getpid()
        assert isinstance(payload["jobs"], dict) or payload["jobs"] is None

    print("Server health contract passed (application, version, and exact process identity).")


if __name__ == "__main__":
    main()
