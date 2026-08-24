"""Start the FlagshipEditor backend from a read-only installation directory.

The MSI puts ``engine/`` and ``runtime/`` under Program Files, which a standard
user cannot write to, while ``server.py`` expects to drop a PID file and a
thumbnail cache next to itself. Every one of those paths is redirected into the
per-user data directory *before* ``server`` is imported, so the backend behaves
exactly as it does from a writable checkout.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
INSTALL_DIR = ENGINE_DIR.parent
CREATE_NO_WINDOW = 0x08000000


def _data_dir() -> Path:
    """Return the writable directory the launcher was pointed at."""
    explicit = os.environ.get("FLAGSHIPEDITOR_DATA", "").strip()
    if explicit:
        return Path(explicit)
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return Path(base) / "ake-studio" / "FlagshipEditor"


DATA_DIR = _data_dir()
CACHE_DIR = Path(os.environ.get("FLAGSHIPEDITOR_CACHE") or (DATA_DIR / "cache"))
LOG_DIR = DATA_DIR / "logs"
for _directory in (CACHE_DIR, LOG_DIR):
    _directory.mkdir(parents=True, exist_ok=True)

os.environ["FLAGSHIPEDITOR_DATA"] = str(DATA_DIR)
os.environ["FLAGSHIPEDITOR_CACHE"] = str(CACHE_DIR)
os.environ.setdefault("FLAGSHIPEDITOR_THUMBNAILS", str(CACHE_DIR / "thumbnails"))
os.environ.setdefault("FLAGSHIPEDITOR_FFMPEG", str(INSTALL_DIR / "runtime" / "bin" / "ffmpeg.exe"))
os.environ.setdefault("FLAGSHIPEDITOR_FFPROBE", str(INSTALL_DIR / "runtime" / "bin" / "ffprobe.exe"))

# pythonw.exe runs without a console, so the standard streams are None and the
# first uvicorn log record would raise. Both are rebound to the per-user log
# files before anything that logs is imported.
sys.stdout = open(LOG_DIR / "backend.log", "a", encoding="utf-8", errors="replace", buffering=1)
sys.stderr = open(LOG_DIR / "backend-error.log", "a", encoding="utf-8", errors="replace", buffering=1)

if sys.platform == "win32":
    # FFmpeg and FFprobe are console programs: launched from a windowless host
    # they would each pop a console. The engine always passes its subprocess
    # arguments by keyword, so adding the flag here covers every call site.
    _base_popen_init = subprocess.Popen.__init__

    def _windowless_popen_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | CREATE_NO_WINDOW
        _base_popen_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _windowless_popen_init  # type: ignore[method-assign]

# The engine modules import each other by bare name.
sys.path.insert(0, str(ENGINE_DIR))

import uvicorn  # noqa: E402
import server  # noqa: E402

PID_FILE = DATA_DIR / "backend.pid"


def main() -> int:
    """Run the backend, publishing a PID file the stop script can use."""
    PID_FILE.write_text(str(os.getpid()), encoding="ascii")
    try:
        uvicorn.run(
            server.app,
            host="127.0.0.1",
            port=int(os.environ.get("FLAGSHIPEDITOR_PORT", "18791")),
            log_level="info",
        )
    finally:
        PID_FILE.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
