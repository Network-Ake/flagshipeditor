"""Bounded, cacheable video analysis for FlagshipEditor."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import cv2
import numpy as np

from media_tools import FFMPEG, FFPROBE


ANALYSIS_SCHEMA_VERSION = "3"
ANALYSIS_MAX_DIMENSION = max(320, min(960, int(os.environ.get("FLAGSHIPEDITOR_ANALYSIS_MAX_DIM", "640"))))
ANALYSIS_SAMPLES = max(3, min(10, int(os.environ.get("FLAGSHIPEDITOR_ANALYSIS_SAMPLES", "6"))))
PROBE_TIMEOUT_SECONDS = max(5, int(os.environ.get("FLAGSHIPEDITOR_PROBE_TIMEOUT", "25")))
FRAME_TIMEOUT_SECONDS = max(5, int(os.environ.get("FLAGSHIPEDITOR_FRAME_TIMEOUT", "30")))
CLIP_TIMEOUT_SECONDS = max(30, int(os.environ.get("FLAGSHIPEDITOR_CLIP_TIMEOUT", "120")))
FFPROBE_PATH = FFPROBE.path
FFMPEG_PATH = FFMPEG.path

BASE_CACHE_DIR = Path(
    os.environ.get(
        "FLAGSHIPEDITOR_CACHE",
        str(
            Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()))
            / "ake-studio"
            / "FlagshipEditor"
            / "cache"
        )
        if sys.platform == "win32"
        else str(
            Path(os.environ.get("HOME", tempfile.gettempdir()))
            / "Library"
            / "Caches"
            / "FlagshipEditor"
            / "cache"
        ),
    )
)
THUMBNAIL_DIR = Path(os.environ.get("FLAGSHIPEDITOR_THUMBNAILS", str(BASE_CACHE_DIR / "thumbnails")))
CACHE_DB = BASE_CACHE_DIR / "analysis.sqlite3"


class ClipAnalysisError(RuntimeError):
    """A classified media failure that can be isolated to one clip."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _cancelled(cancel_event: Optional[threading.Event]) -> bool:
    return bool(cancel_event and cancel_event.is_set())


def _check_cancel(cancel_event: Optional[threading.Event]) -> None:
    if _cancelled(cancel_event):
        raise ClipAnalysisError("cancelled", "Analysis cancelled")


def _check_deadline(deadline: Optional[float]) -> None:
    """Abort a clip that has outrun its whole-file budget."""
    if deadline is not None and time.monotonic() >= deadline:
        raise ClipAnalysisError(
            "clip_timeout",
            f"Analysis exceeded the {CLIP_TIMEOUT_SECONDS}s budget for a single clip",
        )


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError, OverflowError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default


def parse_frame_rate(value: Any, default: float = 30.0) -> float:
    """Parse an ffprobe rate without eval or division-by-zero failures."""
    try:
        numerator, denominator = str(value).split("/", 1)
        denominator_value = float(denominator)
        if denominator_value == 0:
            return default
        rate = float(numerator) / denominator_value
        return rate if math.isfinite(rate) and rate > 0 else default
    except (TypeError, ValueError, OverflowError):
        return default


def resize_for_analysis(frame: np.ndarray, max_dimension: int = ANALYSIS_MAX_DIMENSION) -> np.ndarray:
    """Bound memory before retaining frames or running optical flow."""
    height, width = frame.shape[:2]
    largest = max(height, width)
    if largest <= max_dimension:
        return frame
    scale = max_dimension / float(largest)
    return cv2.resize(
        frame,
        (max(2, int(round(width * scale))), max(2, int(round(height * scale)))),
        interpolation=cv2.INTER_AREA,
    )


def _cache_connection() -> sqlite3.Connection:
    BASE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(CACHE_DB), timeout=20)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=20000")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS analysis_cache (
            cache_key TEXT PRIMARY KEY,
            schema_version TEXT NOT NULL,
            source_path TEXT NOT NULL,
            source_size INTEGER NOT NULL,
            source_mtime_ns INTEGER NOT NULL,
            result_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            last_access REAL NOT NULL
        )
        """
    )
    return connection


def _source_identity(video_path: str) -> Tuple[str, os.stat_result, str]:
    absolute = os.path.abspath(video_path)
    try:
        stat = os.stat(absolute)
    except FileNotFoundError as error:
        raise ClipAnalysisError("missing", f"Media file is missing: {video_path}") from error
    except OSError as error:
        raise ClipAnalysisError("unreadable", f"Cannot access media file: {video_path} ({error})") from error
    if not os.path.isfile(absolute) or stat.st_size <= 0:
        raise ClipAnalysisError("invalid_file", f"Media file is empty or not a regular file: {video_path}")
    identity = f"{os.path.normcase(absolute)}|{stat.st_size}|{stat.st_mtime_ns}|{ANALYSIS_SCHEMA_VERSION}"
    return absolute, stat, hashlib.sha256(identity.encode("utf-8")).hexdigest()


def save_thumbnail(cache_key: str, frames: list) -> str:
    """Persist a capped JPEG under an opaque filename."""
    if not frames:
        return ""
    try:
        THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
        thumbnail_id = cache_key + ".jpg"
        destination = THUMBNAIL_DIR / thumbnail_id
        if not destination.exists():
            thumbnail = resize_for_analysis(frames[0], 480)
            ok, encoded = cv2.imencode(".jpg", thumbnail, [cv2.IMWRITE_JPEG_QUALITY, 78])
            if not ok:
                return ""
            temporary = destination.with_suffix(".tmp")
            temporary.write_bytes(encoded.tobytes())
            os.replace(temporary, destination)
        return thumbnail_id
    except (OSError, ValueError, cv2.error):
        return ""


def classify_probe_failure(diagnostic: str) -> Tuple[str, str]:
    """Turn raw FFprobe stderr into a code and a sentence a user can act on."""
    text = diagnostic.lower()
    if "invalid data found" in text or "moov atom not found" in text or "truncat" in text:
        return "corrupt_media", "The file is corrupt or incompletely written"
    if "decoder" in text and "not found" in text:
        return "unsupported_codec", "This build of FFmpeg has no decoder for that codec"
    if "permission denied" in text:
        return "unreadable", "Windows denied read access to the file"
    if "no such file" in text:
        return "missing", "The file no longer exists at that path"
    if "protocol not found" in text:
        return "unsupported_path", "The media path uses a protocol FFmpeg cannot read"
    return "probe_failed", diagnostic


def get_video_metadata(video_path: str, cancel_event: Optional[threading.Event] = None) -> Dict[str, Any]:
    """Extract bounded metadata through the bundled FFprobe."""
    _check_cancel(cancel_event)
    if not FFPROBE.available:
        raise ClipAnalysisError(
            "probe_unavailable",
            f"FFprobe is unavailable ({FFPROBE.path}): {FFPROBE.detail}",
        )
    command = [
        FFPROBE_PATH,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        video_path,
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as error:
        raise ClipAnalysisError("probe_timeout", f"FFprobe timed out after {PROBE_TIMEOUT_SECONDS}s") from error
    except OSError as error:
        raise ClipAnalysisError("probe_unavailable", f"FFprobe could not start: {error}") from error
    _check_cancel(cancel_event)
    if result.returncode != 0:
        diagnostic = (result.stderr or "unknown FFprobe error").strip()[-500:]
        code, message = classify_probe_failure(diagnostic)
        raise ClipAnalysisError(code, message)
    try:
        metadata = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as error:
        raise ClipAnalysisError("invalid_metadata", "FFprobe returned invalid JSON") from error
    streams = metadata.get("streams") or []
    stream = next((item for item in streams if item.get("codec_type") == "video"), None)
    if not stream:
        raise ClipAnalysisError("no_video_stream", "The file has no video stream")
    fmt = metadata.get("format") or {}
    duration = safe_float(stream.get("duration"), safe_float(fmt.get("duration")))
    return {
        "codec": str(stream.get("codec_name") or "unknown"),
        "profile": str(stream.get("profile") or "unknown"),
        "pixel_format": str(stream.get("pix_fmt") or "unknown"),
        "width": safe_int(stream.get("width")),
        "height": safe_int(stream.get("height")),
        "fps": parse_frame_rate(stream.get("avg_frame_rate") or stream.get("r_frame_rate")),
        "duration": max(0.0, duration),
        "bit_rate": safe_int(stream.get("bit_rate"), safe_int(fmt.get("bit_rate"))),
    }


def extract_frames_opencv(
    video_path: str,
    num_frames: int = ANALYSIS_SAMPLES,
    cancel_event: Optional[threading.Event] = None,
) -> list:
    """Sample and immediately downscale frames through OpenCV."""
    _check_cancel(cancel_event)
    cap = cv2.VideoCapture(video_path, cv2.CAP_FFMPEG)
    try:
        if not cap.isOpened():
            return []
        total_frames = safe_int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            return []
        positions = np.linspace(0, max(0, total_frames - 1), num=max(1, num_frames), dtype=int)
        frames = []
        for frame_index in positions:
            _check_cancel(cancel_event)
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
            ok, frame = cap.read()
            if ok and frame is not None:
                frames.append(resize_for_analysis(frame))
        return frames
    finally:
        cap.release()


def _run_cancellable(
    command: list[str],
    cancel_event: Optional[threading.Event],
    timeout: int,
) -> bytes:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    )
    deadline = time.monotonic() + timeout
    while True:
        if _cancelled(cancel_event):
            process.kill()
            process.communicate()
            raise ClipAnalysisError("cancelled", "Analysis cancelled")
        if time.monotonic() >= deadline:
            process.kill()
            _, stderr = process.communicate()
            raise ClipAnalysisError("decode_timeout", (stderr or b"FFmpeg frame timeout")[-500:].decode("utf-8", "replace"))
        try:
            stdout, stderr = process.communicate(timeout=0.1)
            break
        except subprocess.TimeoutExpired:
            continue
    if process.returncode != 0:
        raise ClipAnalysisError("decode_failed", (stderr or b"FFmpeg decode failed")[-500:].decode("utf-8", "replace"))
    return stdout


def extract_frames_ffmpeg(
    video_path: str,
    duration: float,
    num_frames: int = ANALYSIS_SAMPLES,
    cancel_event: Optional[threading.Event] = None,
    deadline: Optional[float] = None,
) -> list:
    """Seek through ProRes with bundled FFmpeg without decoding the full clip."""
    if not FFMPEG.available:
        raise ClipAnalysisError(
            "decode_unavailable",
            f"FFmpeg is unavailable ({FFMPEG.path}): {FFMPEG.detail}",
        )
    if duration <= 0:
        timestamps = [0.0]
    else:
        timestamps = np.linspace(duration * 0.05, duration * 0.95, num=max(1, num_frames)).tolist()
    frames = []
    scale_filter = (
        f"scale=w='if(gte(iw,ih),min(iw,{ANALYSIS_MAX_DIMENSION}),-2)':"
        f"h='if(lt(iw,ih),min(ih,{ANALYSIS_MAX_DIMENSION}),-2)'"
    )
    for timestamp in timestamps:
        _check_cancel(cancel_event)
        _check_deadline(deadline)
        command = [
            FFMPEG_PATH,
            "-v", "error",
            "-ss", f"{timestamp:.6f}",
            "-i", video_path,
            "-map", "0:v:0",
            "-frames:v", "1",
            "-vf", scale_filter,
            "-f", "image2pipe",
            "-vcodec", "mjpeg",
            "-q:v", "4",
            "pipe:1",
        ]
        budget = FRAME_TIMEOUT_SECONDS
        if deadline is not None:
            budget = int(max(1, min(budget, deadline - time.monotonic())))
        try:
            encoded = _run_cancellable(command, cancel_event, budget)
        except ClipAnalysisError as error:
            if frames and error.code == "decode_failed":
                continue
            raise
        frame = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is not None:
            frames.append(resize_for_analysis(frame))
    return frames


def extract_frames(
    video_path: str,
    num_frames: int = ANALYSIS_SAMPLES,
    metadata: Optional[Dict[str, Any]] = None,
    cancel_event: Optional[threading.Event] = None,
    deadline: Optional[float] = None,
) -> Tuple[list, str]:
    """Use bundled FFmpeg for ProRes and as a fallback for other codecs."""
    meta = metadata or get_video_metadata(video_path, cancel_event)
    codec = str(meta.get("codec", "")).lower()
    duration = safe_float(meta.get("duration"))
    if codec == "prores":
        return extract_frames_ffmpeg(video_path, duration, num_frames, cancel_event, deadline), "ffmpeg"
    frames = extract_frames_opencv(video_path, num_frames, cancel_event)
    if frames:
        return frames, "opencv"
    _check_deadline(deadline)
    return extract_frames_ffmpeg(video_path, duration, num_frames, cancel_event, deadline), "ffmpeg"


def compute_motion_intensity(frames: list) -> float:
    if len(frames) < 2:
        return 0.0
    total_motion = 0.0
    for previous, current in zip(frames, frames[1:]):
        prev_gray = cv2.cvtColor(previous, cv2.COLOR_BGR2GRAY)
        curr_gray = cv2.cvtColor(current, cv2.COLOR_BGR2GRAY)
        flow = cv2.calcOpticalFlowFarneback(prev_gray, curr_gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        total_motion += float(np.mean(np.linalg.norm(flow, axis=2)))
    return total_motion / (len(frames) - 1)


def detect_faces(frames: list) -> Dict[str, Any]:
    """Detect faces using DNN if available, fallback to Haar cascades."""
    # Try DNN-based face detector first (more accurate, handles angles better)
    dnn_model = os.environ.get("FLAGSHIPEDITOR_FACE_MODEL", "")
    if dnn_model and os.path.isfile(dnn_model):
        try:
            net = cv2.dnn.readNetFromCaffe(
                dnn_model + ".prototxt",
                dnn_model + ".caffemodel",
            )
            has_face = False
            max_face_ratio = 0.0
            for frame in frames:
                h, w = frame.shape[:2]
                blob = cv2.dnn.blobFromImage(frame, 1.0, (300, 300), (104.0, 177.0, 123.0))
                net.setInput(blob)
                detections = net.forward()
                for i in range(detections.shape[2]):
                    confidence = detections[i, 2]
                    if confidence > 0.5:
                        has_face = True
                        box = detections[i, 3:7] * np.array([w, h, w, h])
                        fw = box[2] - box[0]
                        fh = box[3] - box[1]
                        max_face_ratio = max(max_face_ratio, (fw * fh) / float(w * h))
            return {"has_face": has_face, "face_size_ratio": float(max_face_ratio)}
        except Exception:
            pass  # Fall through to Haar

    # Fallback: Haar cascades (less accurate but always available)
    if not hasattr(cv2, "CascadeClassifier") or not hasattr(cv2, "data"):
        return {"has_face": False, "face_size_ratio": 0.0}
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    if cascade.empty():
        return {"has_face": False, "face_size_ratio": 0.0}
    has_face = False
    max_face_ratio = 0.0
    for frame in frames:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # Improved params: scaleFactor=1.2, minNeighbors=5, minSize=(30,30)
        faces = cascade.detectMultiScale(gray, 1.2, 5, 0, (30, 30))
        if len(faces):
            has_face = True
            height, width = frame.shape[:2]
            for _x, _y, face_width, face_height in faces:
                max_face_ratio = max(max_face_ratio, (face_width * face_height) / float(width * height))
    return {"has_face": has_face, "face_size_ratio": float(max_face_ratio)}


def compute_visual_scores(frames: list, motion: float) -> Dict[str, Any]:
    if not frames:
        return {"composition_score": 0.0, "energy_score": 0.0, "sharpness_score": 0.0, "histogram": []}
    composition_scores, brightness, saturation, sharpness = [], [], [], []
    hue_histogram = np.zeros(32, dtype=np.float64)
    for frame in frames:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        height, width = gray.shape[:2]
        thirds = [
            gray[: height // 3, :], gray[height // 3 : 2 * height // 3, :], gray[2 * height // 3 :, :],
            gray[:, : width // 3], gray[:, width // 3 : 2 * width // 3], gray[:, 2 * width // 3 :],
        ]
        edge_density = [float(np.mean(cv2.Canny(third, 50, 150))) for third in thirds]
        balance = 100.0 - (float(np.std(edge_density)) / max(float(np.mean(edge_density)), 1.0)) * 50.0
        composition_scores.append(max(0.0, min(100.0, balance)))
        brightness.append(float(np.mean(hsv[:, :, 2])) / 2.55)
        saturation.append(float(np.mean(hsv[:, :, 1])) / 2.55)
        sharpness.append(float(cv2.Laplacian(gray, cv2.CV_64F).var()))
        hue_histogram += cv2.calcHist([hsv], [0], None, [32], [0, 180]).reshape(-1)
    if float(hue_histogram.sum()) > 0:
        hue_histogram /= float(hue_histogram.sum())
    sharpness_score = 100.0 * (1.0 - float(np.exp(-float(np.mean(sharpness)) / 300.0)))
    energy_score = (min(100.0, max(0.0, motion * 3.0)) + float(np.mean(brightness)) + float(np.mean(saturation))) / 3.0
    return {
        "composition_score": float(np.mean(composition_scores)),
        "energy_score": max(0.0, min(100.0, energy_score)),
        "sharpness_score": max(0.0, min(100.0, sharpness_score)),
        "histogram": hue_histogram.tolist(),
    }


def classify_clip(video_path: str, cancel_event: Optional[threading.Event] = None) -> Dict[str, Any]:
    """Analyse one media file within a bounded time and memory budget."""
    deadline = time.monotonic() + CLIP_TIMEOUT_SECONDS
    absolute, _stat, cache_key = _source_identity(video_path)
    _check_cancel(cancel_event)
    metadata = get_video_metadata(absolute, cancel_event)
    _check_deadline(deadline)
    frames, decoder = extract_frames(absolute, ANALYSIS_SAMPLES, metadata, cancel_event, deadline)
    if not frames:
        raise ClipAnalysisError(
            "no_decodable_frames",
            "No video frame could be decoded — the file is corrupt or uses an unsupported codec",
        )
    _check_cancel(cancel_event)
    _check_deadline(deadline)
    face_info = detect_faces(frames)
    brightness = float(np.mean([cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).mean() for frame in frames]))
    motion = compute_motion_intensity(frames)
    visual_scores = compute_visual_scores(frames, motion)
    if face_info["has_face"] and face_info["face_size_ratio"] > 0.15:
        scene_type = "close_up"
    elif face_info["has_face"] and face_info["face_size_ratio"] > 0.03:
        scene_type = "performance"
    elif brightness < 60:
        scene_type = "b_roll_low_light"
    elif motion < 5:
        scene_type = "b_roll_static"
    elif motion > 15:
        scene_type = "b_roll_dynamic"
    else:
        scene_type = "b_roll"
    return {
        "path": absolute,
        "name": os.path.basename(absolute),
        "duration": metadata["duration"],
        "scene_type": scene_type,
        "has_face": face_info["has_face"],
        "face_size_ratio": face_info["face_size_ratio"],
        "brightness": brightness,
        "motion_intensity": motion,
        **visual_scores,
        "thumbnail_id": save_thumbnail(cache_key, frames),
        "codec": metadata["codec"],
        "profile": metadata["profile"],
        "pixel_format": metadata["pixel_format"],
        "width": metadata["width"],
        "height": metadata["height"],
        "fps": metadata["fps"],
        "decoder": decoder,
        "usable": True,
        "analysis_schema": ANALYSIS_SCHEMA_VERSION,
    }


def classify_clip_cached(
    video_path: str,
    cancel_event: Optional[threading.Event] = None,
) -> Tuple[Dict[str, Any], bool]:
    absolute, stat, cache_key = _source_identity(video_path)
    _check_cancel(cancel_event)
    with _cache_connection() as connection:
        row = connection.execute(
            "SELECT result_json FROM analysis_cache WHERE cache_key = ? AND schema_version = ?",
            (cache_key, ANALYSIS_SCHEMA_VERSION),
        ).fetchone()
        if row:
            connection.execute("UPDATE analysis_cache SET last_access = ? WHERE cache_key = ?", (time.time(), cache_key))
            return json.loads(row[0]), True
    result = classify_clip(absolute, cancel_event)
    serialized = json.dumps(result, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    now = time.time()
    with _cache_connection() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO analysis_cache
            (cache_key, schema_version, source_path, source_size, source_mtime_ns, result_json, created_at, last_access)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (cache_key, ANALYSIS_SCHEMA_VERSION, absolute, stat.st_size, stat.st_mtime_ns, serialized, now, now),
        )
        # Keep the cache bounded without ever touching source media.
        connection.execute(
            "DELETE FROM analysis_cache WHERE cache_key IN (SELECT cache_key FROM analysis_cache ORDER BY last_access DESC LIMIT -1 OFFSET 50000)"
        )
    return result, False
