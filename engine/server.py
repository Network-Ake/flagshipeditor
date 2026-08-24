"""
FlagshipEditor — Python Backend Server
Local FastAPI server that handles beat analysis and clip classification.
Runs on localhost:18791
"""

import os
import sys
import json
import subprocess
import threading
import time
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

APP_ID = "com.akestudio.flagshipeditor.backend"
APP_VERSION = (Path(__file__).parent / "VERSION").read_text(encoding="utf-8").strip() if (Path(__file__).parent / "VERSION").exists() else "0.1.7"
PID_FILE = Path(__file__).parent / ".flagshipeditor.pid"
FFPROBE_PATH = os.environ.get("FLAGSHIPEDITOR_FFPROBE", "ffprobe")
FFMPEG_PATH = os.environ.get(
    "FLAGSHIPEDITOR_FFMPEG",
    str(Path(FFPROBE_PATH).with_name("ffmpeg")) if Path(FFPROBE_PATH).is_absolute() else "ffmpeg",
)
# Fix: on Windows, ensure .exe extension is present
if sys.platform == "win32" and not FFMPEG_PATH.lower().endswith(".exe"):
    FFMPEG_PATH = FFMPEG_PATH + ".exe"
THUMBNAIL_DIR = Path(
    os.environ.get(
        "FLAGSHIPEDITOR_THUMBNAILS",
        str(Path(os.environ.get(
            "LOCALAPPDATA" if sys.platform == "win32" else "HOME",
            os.environ.get("TEMP", os.environ.get("TMP", "/tmp")) if sys.platform != "win32" else "",
        )) / "FlagshipEditor" / "thumbnails") if sys.platform == "win32" else
        str(Path(os.environ.get("HOME", "/tmp")) / "Library" / "Caches" / "FlagshipEditor" / "thumbnails")
    )
)
THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)


def executable_works(executable: str) -> bool:
    try:
        result = subprocess.run(
            [executable, "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


FFPROBE_AVAILABLE = executable_works(FFPROBE_PATH)
FFMPEG_AVAILABLE = executable_works(FFMPEG_PATH)

# Import analysis modules (graceful degradation if deps not installed)
sys.path.insert(0, str(Path(__file__).parent))

LIBROSA_AVAILABLE = False
OPENCV_AVAILABLE = False

try:
    from beat_analysis import analyze_track
    LIBROSA_AVAILABLE = True
except ImportError:
    pass

try:
    from clip_analysis import ANALYSIS_SCHEMA_VERSION, THUMBNAIL_DIR as ANALYSIS_THUMBNAIL_DIR, classify_clip_cached
    from analysis_jobs import AnalysisJobManager
    OPENCV_AVAILABLE = True
except ImportError:
    pass

SHOT_SELECTOR_AVAILABLE = False
try:
    from shot_selector import select_best_clips, score_clip
    SHOT_SELECTOR_AVAILABLE = True
except ImportError:
    pass

app = FastAPI(title="FlagshipEditor Backend", version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
if OPENCV_AVAILABLE:
    THUMBNAIL_DIR = ANALYSIS_THUMBNAIL_DIR
    THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/thumbnails", StaticFiles(directory=str(THUMBNAIL_DIR)), name="thumbnails")

ANALYSIS_JOBS = AnalysisJobManager(worker_count=int(os.environ.get("FLAGSHIPEDITOR_ANALYSIS_WORKERS", "2"))) if OPENCV_AVAILABLE else None
SUPPORTED_MEDIA_EXTENSIONS = {".mov", ".mp4", ".m4v", ".avi", ".mxf"}


class BeatRequest(BaseModel):
    audioPath: str


class ClipRequest(BaseModel):
    videoPath: str


class AnalysisJobRequest(BaseModel):
    videoPaths: list[str]


class FolderScanRequest(BaseModel):
    rootPath: str
    recursive: bool = True


class ShotSelectionRequest(BaseModel):
    clips: list  # List of clip_info dicts
    beatTimes: list  # List of beat times in seconds
    sectionType: str
    styleConfig: dict = Field(default_factory=dict)
    usedRecently: list = Field(default_factory=list)


@app.get("/health")
def health():
    return {
        "appId": APP_ID,
        "processId": os.getpid(),
        "status": "ok",
        "version": APP_VERSION,
        "librosa": LIBROSA_AVAILABLE,
        "opencv": OPENCV_AVAILABLE,
        "shot_selector": SHOT_SELECTOR_AVAILABLE,
        "ffprobe": FFPROBE_AVAILABLE,
        "ffmpeg": FFMPEG_AVAILABLE,
        "analysis_schema": ANALYSIS_SCHEMA_VERSION if OPENCV_AVAILABLE else None,
        "jobs": ANALYSIS_JOBS.health() if ANALYSIS_JOBS else None,
    }


@app.post("/analyze-beat")
def analyze_beat(req: BeatRequest):
    if not LIBROSA_AVAILABLE:
        raise HTTPException(status_code=503, detail="librosa not installed. Run: pip install librosa scikit-learn")
    try:
        result = analyze_track(req.audioPath)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/analyze-clip")
def analyze_clip_endpoint(req: ClipRequest):
    if not OPENCV_AVAILABLE:
        raise HTTPException(status_code=503, detail="opencv not installed. Run: pip install opencv-python")
    try:
        result, _cache_hit = classify_clip_cached(req.videoPath)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/analysis-jobs")
def create_analysis_job(req: AnalysisJobRequest):
    if not ANALYSIS_JOBS:
        raise HTTPException(status_code=503, detail="Clip analysis is unavailable")
    try:
        return ANALYSIS_JOBS.create_job(req.videoPaths)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/analysis-jobs/{job_id}")
def analysis_job_status(job_id: str):
    if not ANALYSIS_JOBS:
        raise HTTPException(status_code=503, detail="Clip analysis is unavailable")
    try:
        return ANALYSIS_JOBS.get_status(job_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Analysis job not found") from error


@app.get("/analysis-jobs/{job_id}/result")
def analysis_job_result(job_id: str):
    if not ANALYSIS_JOBS:
        raise HTTPException(status_code=503, detail="Clip analysis is unavailable")
    try:
        return ANALYSIS_JOBS.get_results(job_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Analysis job not found") from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/analysis-jobs/{job_id}/cancel")
def cancel_analysis_job(job_id: str):
    if not ANALYSIS_JOBS:
        raise HTTPException(status_code=503, detail="Clip analysis is unavailable")
    try:
        return ANALYSIS_JOBS.cancel(job_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Analysis job not found") from error


@app.post("/media/scan")
def scan_media_folder(req: FolderScanRequest):
    root = os.path.abspath(req.rootPath)
    if not os.path.isdir(root):
        raise HTTPException(status_code=400, detail="Selected media folder is unavailable")
    paths: list[str] = []
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
                    elif entry.is_file(follow_symlinks=False) and Path(entry.name).suffix.lower() in SUPPORTED_MEDIA_EXTENSIONS:
                        paths.append(os.path.abspath(entry.path))
                        try:
                            total_bytes += entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            pass
                        if len(paths) >= 50000:
                            raise HTTPException(status_code=413, detail="Folder contains more than 50,000 supported media files")
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=f"Cannot read media folder: {error}") from error
    paths.sort(key=lambda value: os.path.normcase(value))
    return {"rootPath": root, "paths": paths, "totalFiles": len(paths), "totalBytes": total_bytes}


@app.post("/start")
def start_server():
    return {"status": "already running"}


@app.post("/shutdown")
async def shutdown_server():
    def stop_after_response():
        time.sleep(0.25)
        PID_FILE.unlink(missing_ok=True)
        os._exit(0)

    threading.Thread(target=stop_after_response, daemon=True).start()
    return {"status": "stopping", "appId": APP_ID, "version": APP_VERSION}


@app.post("/select-shots")
def select_shots(req: ShotSelectionRequest):
    if not SHOT_SELECTOR_AVAILABLE:
        raise HTTPException(status_code=503, detail="shot_selector not available. Run: pip install opencv-python numpy scipy")
    try:
        result = select_best_clips(
            req.clips,
            req.beatTimes,
            req.sectionType,
            req.styleConfig,
            req.usedRecently
        )
        return {"selections": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    PID_FILE.write_text(str(os.getpid()), encoding="ascii")
    try:
        uvicorn.run(app, host="127.0.0.1", port=18791, log_level="info")
    finally:
        PID_FILE.unlink(missing_ok=True)
