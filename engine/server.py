"""FlagshipEditor — local analysis backend.

A FastAPI server bound to 127.0.0.1:18791. The CEP panel is the only client, so
every endpoint answers with the exact camelCase field names the After Effects
bridge consumes and every failure carries a sentence the panel can display.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# The engine directory is the import root: the panel launches ``server.py``
# directly and the sibling modules import each other by bare name.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from media_tools import FFMPEG, FFPROBE, describe as describe_media_tools, missing_tools

APP_ID = "com.akestudio.flagshipeditor.backend"
VERSION_FILE = Path(__file__).resolve().parent / "VERSION"
APP_VERSION = VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.exists() else "3.0.0"
PID_FILE = Path(__file__).resolve().parent / ".flagshipeditor.pid"
SERVER_PORT = int(os.environ.get("FLAGSHIPEDITOR_PORT", "18791"))
BEAT_TIMEOUT_SECONDS = max(30, int(os.environ.get("FLAGSHIPEDITOR_BEAT_TIMEOUT", "180")))
SUPPORTED_MEDIA_EXTENSIONS = {".mov", ".mp4", ".m4v", ".avi", ".mxf"}
MAX_SCANNED_FILES = 50000

LIBROSA_AVAILABLE = False
OPENCV_AVAILABLE = False
SHOT_SELECTOR_AVAILABLE = False
IMPORT_ERRORS: Dict[str, str] = {}

try:
    from beat_analysis import analyze_track

    LIBROSA_AVAILABLE = True
except ImportError as error:  # librosa or scipy missing from the runtime
    IMPORT_ERRORS["librosa"] = str(error)

try:
    from analysis_jobs import AnalysisJobManager
    from clip_analysis import ANALYSIS_SCHEMA_VERSION, THUMBNAIL_DIR as ANALYSIS_THUMBNAIL_DIR
    from clip_analysis import classify_clip_cached

    OPENCV_AVAILABLE = True
except ImportError as error:  # opencv missing from the runtime
    IMPORT_ERRORS["opencv"] = str(error)

try:
    from shot_selector import (
        normalize_motion_evidence,
        resolve_media_profile,
        score_clip,
        select_best_clips,
    )

    SHOT_SELECTOR_AVAILABLE = True
except ImportError as error:  # numpy missing from the runtime
    IMPORT_ERRORS["shot_selector"] = str(error)

if OPENCV_AVAILABLE:
    THUMBNAIL_DIR = ANALYSIS_THUMBNAIL_DIR
else:
    THUMBNAIL_DIR = Path(
        os.environ.get(
            "FLAGSHIPEDITOR_THUMBNAILS",
            str(Path(__file__).resolve().parent / ".thumbnails"),
        )
    )
THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="FlagshipEditor Backend", version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/thumbnails", StaticFiles(directory=str(THUMBNAIL_DIR)), name="thumbnails")

ANALYSIS_WORKERS = max(1, min(4, int(os.environ.get("FLAGSHIPEDITOR_ANALYSIS_WORKERS", "3"))))
ANALYSIS_JOBS = AnalysisJobManager(worker_count=ANALYSIS_WORKERS) if OPENCV_AVAILABLE else None

# Beat analysis runs on one worker so a second request cannot start a second
# librosa pass over the same CPU, and so the panel can poll real progress.
BEAT_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="flagship-beat")
BEAT_LOCK = threading.Lock()
BEAT_STATE: Dict[str, Any] = {
    "state": "idle",
    "step": "",
    "progress": 0.0,
    "audioPath": "",
    "startedAt": 0.0,
    "message": "",
}


class BeatRequest(BaseModel):
    """Body of ``POST /analyze-beat``."""

    audioPath: str


class ClipRequest(BaseModel):
    """Body of ``POST /analyze-clip``."""

    videoPath: str


class AnalysisJobRequest(BaseModel):
    """Body of ``POST /analysis-jobs``."""

    videoPaths: List[str]


class FolderScanRequest(BaseModel):
    """Body of ``POST /media/scan``."""

    rootPath: str
    recursive: bool = True


class ShotSelectionRequest(BaseModel):
    """Body of ``POST /select-shots`` — one call plans the whole edit."""

    clips: List[Dict[str, Any]]
    beats: List[float] = Field(default_factory=list)
    sections: List[Dict[str, Any]] = Field(default_factory=list)
    styleConfig: Dict[str, Any] = Field(default_factory=dict)
    duration: float = 0.0
    tempo: float = 0.0
    bassOnsets: List[float] = Field(default_factory=list)
    downbeats: List[float] = Field(default_factory=list)
    seed: int = 1
    # The hook measured by beat analysis. Optional: a caller that has none — or
    # an older panel that does not send one — gets the selector's own estimate.
    hook: Optional[Dict[str, Any]] = None
    # Two more beat signals the selector consumes when they are available:
    # phrase boundaries become cut points, and the energy curve (with the time
    # base it was measured on) tunes each cut's energy target. Every one is
    # optional, so an older panel keeps the previous behaviour exactly.
    phraseBoundaries: List[float] = Field(default_factory=list)
    energy: List[float] = Field(default_factory=list)
    energyTimes: List[float] = Field(default_factory=list)
    energyHopLength: Optional[float] = None
    energySampleRate: Optional[float] = None


class ScoreRequest(BaseModel):
    """Body of ``POST /score-clip`` — used by the panel's swap picker."""

    clip: Dict[str, Any]
    sectionType: str = ""
    library: List[Dict[str, Any]] = Field(default_factory=list)


def _set_beat_state(**changes: Any) -> None:
    """Publish beat-analysis progress for ``GET /analyze-beat/progress``."""
    with BEAT_LOCK:
        BEAT_STATE.update(changes)


def _run_beat_analysis(audio_path: str) -> Dict[str, Any]:
    """Analyse a track on the beat worker, reporting progress as it goes."""

    def report(step: str, fraction: float) -> None:
        _set_beat_state(state="running", step=step, progress=round(float(fraction) * 100.0, 1))

    _set_beat_state(
        state="running",
        step="Queued",
        progress=0.0,
        audioPath=audio_path,
        startedAt=time.time(),
        message="",
    )
    try:
        result = analyze_track(audio_path, report)
    except Exception as error:
        _set_beat_state(state="failed", step="", progress=0.0, message=str(error))
        raise
    _set_beat_state(state="completed", step="Done", progress=100.0, message="")
    return result


@app.get("/health")
def health() -> Dict[str, Any]:
    """Report every dependency the panel needs before it can generate an edit."""
    return {
        "appId": APP_ID,
        "processId": os.getpid(),
        "status": "ok" if (LIBROSA_AVAILABLE and OPENCV_AVAILABLE and SHOT_SELECTOR_AVAILABLE) else "degraded",
        "version": APP_VERSION,
        "librosa": LIBROSA_AVAILABLE,
        "opencv": OPENCV_AVAILABLE,
        "shot_selector": SHOT_SELECTOR_AVAILABLE,
        "ffprobe": FFPROBE.available,
        "ffmpeg": FFMPEG.available,
        "tools": describe_media_tools(),
        "missingTools": missing_tools(),
        "importErrors": IMPORT_ERRORS,
        "analysis_schema": ANALYSIS_SCHEMA_VERSION if OPENCV_AVAILABLE else None,
        "jobs": ANALYSIS_JOBS.health() if ANALYSIS_JOBS else None,
        "beat": dict(BEAT_STATE),
    }


@app.post("/analyze-beat")
def analyze_beat(req: BeatRequest) -> Dict[str, Any]:
    """Detect tempo, beats, sections, onsets and key for one music file."""
    if not LIBROSA_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Beat analysis is unavailable: librosa did not load. Reinstall the FlagshipEditor runtime.",
        )
    audio_path = os.path.abspath(req.audioPath)
    if not os.path.isfile(audio_path):
        raise HTTPException(status_code=400, detail=f"Music file is missing: {req.audioPath}")
    future: Future = BEAT_EXECUTOR.submit(_run_beat_analysis, audio_path)
    try:
        return future.result(timeout=BEAT_TIMEOUT_SECONDS)
    except FutureTimeoutError as error:
        raise HTTPException(
            status_code=504,
            detail=(
                f"Beat analysis exceeded {BEAT_TIMEOUT_SECONDS}s. Use a shorter track or "
                "convert it to a 44.1 kHz WAV before retrying."
            ),
        ) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=400, detail=f"Music file is missing: {req.audioPath}") from error
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Beat analysis failed: {error}") from error


@app.get("/analyze-beat/progress")
def analyze_beat_progress() -> Dict[str, Any]:
    """Return the live progress of the running beat analysis."""
    with BEAT_LOCK:
        state = dict(BEAT_STATE)
    started = float(state.get("startedAt") or 0.0)
    state["elapsedSeconds"] = round(max(0.0, time.time() - started), 1) if started else 0.0
    state["timeoutSeconds"] = BEAT_TIMEOUT_SECONDS
    return state


@app.post("/analyze-clip")
def analyze_clip_endpoint(req: ClipRequest) -> Dict[str, Any]:
    """Analyse a single clip synchronously — the batch path is /analysis-jobs."""
    if not OPENCV_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Clip analysis is unavailable: OpenCV did not load. Reinstall the FlagshipEditor runtime.",
        )
    try:
        result, _cache_hit = classify_clip_cached(req.videoPath)
        return result
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@app.post("/analysis-jobs")
def create_analysis_job(req: AnalysisJobRequest) -> Dict[str, Any]:
    """Queue a batch of clips for background analysis."""
    if not ANALYSIS_JOBS:
        raise HTTPException(status_code=503, detail="Clip analysis is unavailable")
    try:
        return ANALYSIS_JOBS.create_job(req.videoPaths)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/analysis-jobs/{job_id}")
def analysis_job_status(job_id: str) -> Dict[str, Any]:
    """Return progress, ETA and per-file errors for one analysis job."""
    if not ANALYSIS_JOBS:
        raise HTTPException(status_code=503, detail="Clip analysis is unavailable")
    try:
        return ANALYSIS_JOBS.get_status(job_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Analysis job not found") from error


@app.get("/analysis-jobs/{job_id}/result")
def analysis_job_result(job_id: str) -> Dict[str, Any]:
    """Return every successfully analysed clip once a job has finished."""
    if not ANALYSIS_JOBS:
        raise HTTPException(status_code=503, detail="Clip analysis is unavailable")
    try:
        return ANALYSIS_JOBS.get_results(job_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Analysis job not found") from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/analysis-jobs/{job_id}/cancel")
def cancel_analysis_job(job_id: str) -> Dict[str, Any]:
    """Stop a running analysis job and mark its queued files cancelled."""
    if not ANALYSIS_JOBS:
        raise HTTPException(status_code=503, detail="Clip analysis is unavailable")
    try:
        return ANALYSIS_JOBS.cancel(job_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Analysis job not found") from error


@app.post("/media/scan")
def scan_media_folder(req: FolderScanRequest) -> Dict[str, Any]:
    """List every supported media file under a folder without following loops."""
    root = os.path.abspath(req.rootPath)
    if not os.path.isdir(root):
        raise HTTPException(status_code=400, detail="Selected media folder is unavailable")
    paths: List[str] = []
    skipped = 0
    total_bytes = 0
    pending = [root]
    seen_directories = set()
    try:
        while pending:
            directory = pending.pop()
            directory_identity = os.path.normcase(os.path.realpath(directory))
            if directory_identity in seen_directories:
                continue
            seen_directories.add(directory_identity)
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False) and req.recursive:
                        pending.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        if Path(entry.name).suffix.lower() not in SUPPORTED_MEDIA_EXTENSIONS:
                            skipped += 1
                            continue
                        paths.append(os.path.abspath(entry.path))
                        try:
                            total_bytes += entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            pass
                        if len(paths) >= MAX_SCANNED_FILES:
                            raise HTTPException(
                                status_code=413,
                                detail=f"Folder contains more than {MAX_SCANNED_FILES:,} supported media files",
                            )
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=f"Cannot read media folder: {error}") from error
    paths.sort(key=lambda value: os.path.normcase(value))
    return {
        "rootPath": root,
        "paths": paths,
        "totalFiles": len(paths),
        "totalBytes": total_bytes,
        "skipped": skipped,
    }


@app.post("/select-shots")
def select_shots(req: ShotSelectionRequest) -> Dict[str, Any]:
    """Plan the cut grid for the whole track and pick a clip for every cut."""
    if not SHOT_SELECTOR_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Shot selection is unavailable: numpy did not load. Reinstall the FlagshipEditor runtime.",
        )
    if not req.clips:
        raise HTTPException(status_code=400, detail="No analysed clips were supplied")
    try:
        selections = select_best_clips(
            clips=req.clips,
            beats=req.beats,
            sections=req.sections,
            style_config=req.styleConfig,
            duration=req.duration,
            tempo=req.tempo,
            bass_onsets=req.bassOnsets,
            seed=req.seed,
            hook=req.hook,
            phrase_boundaries=req.phraseBoundaries,
            energy=req.energy,
            energy_times=req.energyTimes,
            energy_hop_length=req.energyHopLength,
            energy_sample_rate=req.energySampleRate,
            downbeats=req.downbeats,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=f"Invalid shot-selection input: {error}") from error
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Shot selection failed: {error}") from error
    if not selections:
        raise HTTPException(
            status_code=422,
            detail="No cut could be planned. The track has no usable beat grid or every clip was rejected.",
        )
    return {
        "selections": selections,
        "mediaProfile": resolve_media_profile(req.clips),
        "cutCount": len(selections),
    }


@app.post("/score-clip")
def score_clip_endpoint(req: ScoreRequest) -> Dict[str, Any]:
    """Score one clip for a section so the panel can rank a manual swap."""
    if not SHOT_SELECTOR_AVAILABLE:
        raise HTTPException(status_code=503, detail="Shot scoring is unavailable")
    try:
        target_identity = str(req.clip.get("path", "")).replace("\\", "/").lower()
        peers = [
            clip
            for clip in req.library
            if str(clip.get("path", "")).replace("\\", "/").lower() != target_identity
        ]
        normalized = normalize_motion_evidence(peers + [req.clip])
        result = score_clip(normalized[-1], None, req.sectionType)
        result["motionNormalizationContext"] = (
            "library" if req.library else "legacy_single_clip"
        )
        return result
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Clip scoring failed: {error}") from error


@app.post("/shutdown")
def shutdown_server() -> Dict[str, Any]:
    """Stop the backend after the response has been flushed to the panel."""

    def stop_after_response() -> None:
        time.sleep(0.25)
        PID_FILE.unlink(missing_ok=True)
        os._exit(0)

    threading.Thread(target=stop_after_response, daemon=True).start()
    return {"status": "stopping", "appId": APP_ID, "version": APP_VERSION}


def main(port: Optional[int] = None) -> None:
    """Run the backend, publishing a PID file for the installer's stop path."""
    PID_FILE.write_text(str(os.getpid()), encoding="ascii")
    try:
        uvicorn.run(app, host="127.0.0.1", port=port or SERVER_PORT, log_level="info")
    finally:
        PID_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
