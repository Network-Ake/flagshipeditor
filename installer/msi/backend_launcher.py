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

# Everything below runs before the standard streams exist (pythonw.exe leaves
# them None), so a raised exception here would die invisibly. Directory
# creation therefore falls back to a per-user temp location instead of
# raising, and the reasons are replayed into the log once it is open.
_DEFERRED_WARNINGS: list[str] = []


def _report_fatal(message: str) -> None:
    """Last-resort diagnostics for a windowless process with no log file."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, message, "FlagshipEditor Backend", 0x10)
        except Exception:
            pass


def _usable_dir(primary: Path, fallback_name: str) -> Path:
    """Create ``primary`` or fall back to a writable per-user temp directory."""
    try:
        primary.mkdir(parents=True, exist_ok=True)
        return primary
    except OSError as error:
        fallback = Path(tempfile.gettempdir()) / "FlagshipEditor" / fallback_name
        _DEFERRED_WARNINGS.append(
            f"Could not create {primary} ({error}); using {fallback} instead."
        )
    try:
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback
    except OSError as error:
        _report_fatal(f"FlagshipEditor could not create {primary} or {fallback}: {error}")
        raise


CACHE_DIR = _usable_dir(
    Path(os.environ.get("FLAGSHIPEDITOR_CACHE") or (DATA_DIR / "cache")), "cache"
)
LOG_DIR = _usable_dir(DATA_DIR / "logs", "logs")

os.environ["FLAGSHIPEDITOR_DATA"] = str(DATA_DIR)
os.environ["FLAGSHIPEDITOR_CACHE"] = str(CACHE_DIR)
os.environ.setdefault("FLAGSHIPEDITOR_THUMBNAILS", str(CACHE_DIR / "thumbnails"))
os.environ.setdefault("FLAGSHIPEDITOR_FFMPEG", str(INSTALL_DIR / "runtime" / "bin" / "ffmpeg.exe"))
os.environ.setdefault("FLAGSHIPEDITOR_FFPROBE", str(INSTALL_DIR / "runtime" / "bin" / "ffprobe.exe"))

# pythonw.exe runs without a console, so the standard streams are None and the
# first uvicorn log record would raise. Both are rebound to the per-user log
# files before anything that logs is imported; if even those cannot be opened
# the streams fall back to os.devnull so the backend still starts.
def _stream(path: Path):
    try:
        return open(path, "a", encoding="utf-8", errors="replace", buffering=1)
    except OSError as error:
        _report_fatal(f"FlagshipEditor could not open its log file {path}: {error}")
        return open(os.devnull, "a", encoding="utf-8")


sys.stdout = _stream(LOG_DIR / "backend.log")
sys.stderr = _stream(LOG_DIR / "backend-error.log")
for _warning in _DEFERRED_WARNINGS:
    print(f"[backend_launcher] {_warning}", file=sys.stderr)

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
    try:
        PID_FILE.write_text(str(os.getpid()), encoding="ascii")
    except OSError as error:
        # The stop script's clean path is the /shutdown endpoint; the PID file
        # only backs its force-kill fallback, so a failed write must not keep
        # the backend from starting.
        print(f"[backend_launcher] Could not write {PID_FILE}: {error}", file=sys.stderr)
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
