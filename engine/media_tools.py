"""Locate and validate the FFmpeg binaries the analysis engine shells out to.

The Windows package ships FFmpeg under ``runtime/bin`` next to ``engine``. A
developer checkout has neither, so the same resolver also honours an explicit
environment override and finally the system ``PATH``. Resolution happens once at
import time and every consumer reads the same answer, so the health endpoint can
never disagree with what clip analysis actually runs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

TOOL_NAMES: Tuple[str, str] = ("ffmpeg", "ffprobe")
VERSION_TIMEOUT_SECONDS = 8
_ENGINE_DIR = Path(__file__).resolve().parent


def executable_name(tool: str) -> str:
    """Return the platform-specific filename for a tool."""
    return f"{tool}.exe" if sys.platform == "win32" else tool


def bundled_search_dirs() -> List[Path]:
    """Return the directories a packaged install keeps its binaries in."""
    roots = [_ENGINE_DIR.parent, _ENGINE_DIR]
    candidates: List[Path] = []
    for root in roots:
        candidates.append(root / "runtime" / "bin")
        candidates.append(root / "runtime" / "ffmpeg")
        candidates.append(root / "runtime" / "ffmpeg" / "bin")
        candidates.append(root / "ffmpeg")
    unique: List[Path] = []
    seen = set()
    for candidate in candidates:
        identity = os.path.normcase(str(candidate))
        if identity not in seen:
            seen.add(identity)
            unique.append(candidate)
    return unique


def probe_version(executable: str) -> Tuple[bool, str]:
    """Run ``<tool> -version`` and return (works, first line or failure reason)."""
    try:
        result = subprocess.run(
            [executable, "-version"],
            capture_output=True,
            text=True,
            timeout=VERSION_TIMEOUT_SECONDS,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"timed out after {VERSION_TIMEOUT_SECONDS}s"
    except OSError as error:
        return False, str(error)
    if result.returncode != 0:
        return False, (result.stderr or "non-zero exit status").strip()[-200:]
    banner = (result.stdout or "").strip().splitlines()
    return True, banner[0] if banner else "unknown version"


class MediaTool:
    """One resolved executable plus how it was found and whether it runs."""

    def __init__(self, tool: str, path: str, source: str, available: bool, detail: str) -> None:
        self.tool = tool
        self.path = path
        self.source = source
        self.available = available
        self.detail = detail

    def as_dict(self) -> Dict[str, object]:
        """Return the JSON-safe shape the health endpoint publishes."""
        return {
            "path": self.path,
            "source": self.source,
            "available": self.available,
            "detail": self.detail,
        }


def resolve_tool(tool: str) -> MediaTool:
    """Resolve one tool through override, bundled runtime, then system PATH."""
    override = os.environ.get(f"FLAGSHIPEDITOR_{tool.upper()}", "").strip()
    candidates: List[Tuple[str, str]] = []
    if override:
        candidates.append((override, "environment"))
    filename = executable_name(tool)
    for directory in bundled_search_dirs():
        candidate = directory / filename
        if candidate.is_file():
            candidates.append((str(candidate), "bundled"))
    system_path = shutil.which(tool)
    if system_path:
        candidates.append((system_path, "system"))

    first_failure: Optional[MediaTool] = None
    for path, source in candidates:
        works, detail = probe_version(path)
        if works:
            return MediaTool(tool, path, source, True, detail)
        if first_failure is None:
            first_failure = MediaTool(tool, path, source, False, detail)
    if first_failure is not None:
        return first_failure
    return MediaTool(tool, filename, "missing", False, f"{tool} was not found in the bundled runtime or on PATH")


def detect_media_tools() -> Dict[str, MediaTool]:
    """Resolve every required tool once."""
    return {tool: resolve_tool(tool) for tool in TOOL_NAMES}


MEDIA_TOOLS: Dict[str, MediaTool] = detect_media_tools()
FFMPEG = MEDIA_TOOLS["ffmpeg"]
FFPROBE = MEDIA_TOOLS["ffprobe"]

# Child processes (and any module that still reads the environment) must see the
# resolved paths, not the raw override the user may have typed.
for _tool, _resolved in MEDIA_TOOLS.items():
    os.environ.setdefault(f"FLAGSHIPEDITOR_{_tool.upper()}", _resolved.path)


def missing_tools() -> List[str]:
    """Return the names of the tools that could not be executed."""
    return [name for name, tool in MEDIA_TOOLS.items() if not tool.available]


def describe() -> Dict[str, Dict[str, object]]:
    """Return every resolved tool for diagnostics and the health endpoint."""
    return {name: tool.as_dict() for name, tool in MEDIA_TOOLS.items()}
