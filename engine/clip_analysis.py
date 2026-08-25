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


ANALYSIS_SCHEMA_VERSION = "4"
ANALYSIS_MAX_DIMENSION = max(320, min(960, int(os.environ.get("FLAGSHIPEDITOR_ANALYSIS_MAX_DIM", "640"))))
ANALYSIS_SAMPLES = max(12, min(16, int(os.environ.get("FLAGSHIPEDITOR_ANALYSIS_SAMPLES", "14"))))  # Increased from 6 to 12-16 for better motion representation
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
    return _extract_frames_opencv_timed(video_path, num_frames, cancel_event)[0]


def _extract_frames_opencv_timed(
    video_path: str,
    num_frames: int = ANALYSIS_SAMPLES,
    cancel_event: Optional[threading.Event] = None,
) -> Tuple[list, list]:
    """Sample frames through OpenCV, returning each frame's source timestamp."""
    _check_cancel(cancel_event)
    cap = cv2.VideoCapture(video_path, cv2.CAP_FFMPEG)
    try:
        if not cap.isOpened():
            return [], []
        total_frames = safe_int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            return [], []
        fps = safe_float(cap.get(cv2.CAP_PROP_FPS))
        positions = np.linspace(0, max(0, total_frames - 1), num=max(1, num_frames), dtype=int)
        frames = []
        timestamps = []
        for frame_index in positions:
            _check_cancel(cancel_event)
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
            ok, frame = cap.read()
            if ok and frame is not None:
                frames.append(resize_for_analysis(frame))
                timestamps.append(float(frame_index) / fps if fps > 0 else 0.0)
        return frames, timestamps
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
    return _extract_frames_ffmpeg_timed(
        video_path, duration, num_frames, cancel_event, deadline
    )[0]


def _extract_frames_ffmpeg_timed(
    video_path: str,
    duration: float,
    num_frames: int = ANALYSIS_SAMPLES,
    cancel_event: Optional[threading.Event] = None,
    deadline: Optional[float] = None,
) -> Tuple[list, list]:
    """Seek frames with FFmpeg, returning each frame's source timestamp."""
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
    kept_timestamps = []
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
            kept_timestamps.append(float(timestamp))
    return frames, kept_timestamps


def extract_frames(
    video_path: str,
    num_frames: int = ANALYSIS_SAMPLES,
    metadata: Optional[Dict[str, Any]] = None,
    cancel_event: Optional[threading.Event] = None,
    deadline: Optional[float] = None,
) -> Tuple[list, str]:
    """Use bundled FFmpeg for ProRes and as a fallback for other codecs."""
    frames, decoder, _timestamps = extract_frames_timed(
        video_path, num_frames, metadata, cancel_event, deadline
    )
    return frames, decoder


def extract_frames_timed(
    video_path: str,
    num_frames: int = ANALYSIS_SAMPLES,
    metadata: Optional[Dict[str, Any]] = None,
    cancel_event: Optional[threading.Event] = None,
    deadline: Optional[float] = None,
) -> Tuple[list, str, list]:
    """Extract sample frames along with where each one sits in the source.

    The timestamps are what let ``find_best_moment`` report a real seek point in
    seconds instead of a frame index the caller cannot interpret — the two
    decoders sample at different offsets, so the mapping cannot be reconstructed
    after the fact.
    """
    meta = metadata or get_video_metadata(video_path, cancel_event)
    codec = str(meta.get("codec", "")).lower()
    duration = safe_float(meta.get("duration"))
    if codec == "prores":
        frames, timestamps = _extract_frames_ffmpeg_timed(
            video_path, duration, num_frames, cancel_event, deadline
        )
        return frames, "ffmpeg", timestamps
    frames, timestamps = _extract_frames_opencv_timed(video_path, num_frames, cancel_event)
    if frames:
        return frames, "opencv", timestamps
    _check_deadline(deadline)
    frames, timestamps = _extract_frames_ffmpeg_timed(
        video_path, duration, num_frames, cancel_event, deadline
    )
    return frames, "ffmpeg", timestamps


def optical_flow_series(
    frames: list,
    cancel_event: Optional[threading.Event] = None,
    deadline: Optional[float] = None,
) -> list:
    """Return the mean flow magnitude between each consecutive frame pair.

    Farneback flow is by far the most expensive step in clip analysis, so it is
    computed once here and every motion metric is derived from the result.
    """
    if len(frames) < 2:
        return []
    motion_values = []
    previous_gray = cv2.cvtColor(frames[0], cv2.COLOR_BGR2GRAY)
    for current in frames[1:]:
        _check_cancel(cancel_event)
        _check_deadline(deadline)
        current_gray = cv2.cvtColor(current, cv2.COLOR_BGR2GRAY)
        flow = cv2.calcOpticalFlowFarneback(
            previous_gray, current_gray, None, 0.5, 3, 15, 3, 5, 1.2, 0
        )
        motion_values.append(float(np.mean(np.linalg.norm(flow, axis=2))))
        previous_gray = current_gray
    return motion_values


def _frame_metrics(frame: np.ndarray) -> Tuple[float, float, float, float]:
    """Return ``(composition, brightness, saturation, sharpness)`` for one frame.

    Composition scores how evenly edge detail is spread across the rule-of-thirds
    bands: a frame with all of its detail crammed into one band reads as badly
    framed. Brightness and saturation are rescaled from OpenCV's 0-255 to 0-100.
    Both ``compute_visual_scores`` and ``find_best_moment`` need these numbers,
    so they are computed once here instead of twice per frame.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    height, width = gray.shape[:2]
    thirds = [
        gray[: height // 3, :], gray[height // 3 : 2 * height // 3, :], gray[2 * height // 3 :, :],
        gray[:, : width // 3], gray[:, width // 3 : 2 * width // 3], gray[:, 2 * width // 3 :],
    ]
    edge_density = [float(np.mean(cv2.Canny(third, 50, 150))) for third in thirds]
    balance = 100.0 - (float(np.std(edge_density)) / max(float(np.mean(edge_density)), 1.0)) * 50.0
    composition = max(0.0, min(100.0, balance))
    brightness = float(np.mean(hsv[:, :, 2])) / 2.55
    saturation = float(np.mean(hsv[:, :, 1])) / 2.55
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    return composition, brightness, saturation, sharpness


def compute_motion_intensity(frames: list) -> float:
    """Average motion across a clip, 0 when it is a still or a single frame."""
    motion_values = optical_flow_series(frames)
    return float(np.mean(motion_values)) if motion_values else 0.0


def compute_motion_variance(frames: list) -> float:
    """Spread of motion across a clip — a shot that builds beats a constant pan."""
    if len(frames) < 3:
        return 0.0
    motion_values = optical_flow_series(frames)
    return float(np.var(motion_values)) if len(motion_values) > 1 else 0.0


def compute_brightness_stability(frames: list) -> float:
    """Compute brightness stability - flickering clips are bad for cutting.
    
    Returns 0-100 where 100 = very stable, 0 = highly unstable/flickering.
    """
    if not frames:
        return 50.0
    
    brightness_values = [float(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).mean()) for frame in frames]
    
    if len(brightness_values) < 2:
        return 100.0
    
    # Low std dev = stable brightness
    std_dev = float(np.std(brightness_values))
    mean_brightness = float(np.mean(brightness_values))
    
    # Normalize: assume std_dev > 50 is very unstable
    stability = max(0.0, 100.0 - (std_dev / 50.0 * 100.0))
    return stability


def per_frame_motion(motion_values: Optional[list], frame_count: int) -> list:
    """Spread a between-frames flow series onto the frames themselves.

    ``optical_flow_series`` returns ``frame_count - 1`` values, where entry ``j``
    is the motion between frames ``j`` and ``j + 1``. Indexing that series with a
    frame number therefore shifts every score by half a sample and leaves the
    last frame with no motion at all. Each frame instead takes the mean of the
    transitions it takes part in.
    """
    if frame_count <= 0:
        return []
    if not motion_values:
        return [0.0] * frame_count
    values = [float(value) for value in motion_values]
    per_frame = []
    for index in range(frame_count):
        adjacent = []
        if index - 1 < len(values) and index - 1 >= 0:
            adjacent.append(values[index - 1])
        if index < len(values):
            adjacent.append(values[index])
        per_frame.append(sum(adjacent) / len(adjacent) if adjacent else 0.0)
    return per_frame


def find_best_moment(
    frames: list,
    motion_values: Optional[list] = None,
    timestamps: Optional[list] = None,
) -> Dict[str, Any]:
    """Locate the most interesting stretch of a clip and where it sits in time.

    Every frame is scored on motion, rule-of-thirds composition and exposure,
    and the window around the peak becomes the clip's "best moment". When the
    caller passes the source timestamp of each sampled frame the result carries
    ``best_time`` in seconds, which is what ``shot_selector.best_moment_window``
    seeks to; without timestamps only frame indices can be reported, and the
    window falls back to the head of the clip.
    """
    frame_count = len(frames) if frames else 0
    times = [float(value) for value in (timestamps or [])][:frame_count]

    def _timed(start_idx: int, end_idx: int, peak_idx: int, confidence: float, score: float) -> Dict[str, Any]:
        result = {
            "best_start_frame": start_idx,
            "best_end_frame": end_idx,
            "best_frame_idx": peak_idx,
            "confidence": float(confidence),
            "score": float(score),
        }
        if times:
            result["best_time"] = times[min(peak_idx, len(times) - 1)]
            result["best_start_time"] = times[min(start_idx, len(times) - 1)]
            result["best_end_time"] = times[min(end_idx, len(times) - 1)]
        return result

    if frame_count < 3:
        return _timed(0, max(0, frame_count - 1), 0, 0.5, 0.0)

    motion_per_frame = per_frame_motion(motion_values, frame_count)

    frame_scores = []
    for index, frame in enumerate(frames):
        composition, brightness, _saturation, _sharpness = _frame_metrics(frame)
        score = composition + min(100.0, brightness)
        score += min(100.0, motion_per_frame[index] * 3.0)
        frame_scores.append(score)

    peak_idx = int(np.argmax(frame_scores))

    # Hold a window of 3-5 samples around the peak so the moment has room to
    # breathe, without letting it swallow a short clip whole.
    window_size = max(1, min(5, frame_count // 3))
    half = window_size // 2
    start_idx = max(0, peak_idx - half)
    end_idx = min(frame_count - 1, peak_idx + half)

    average_score = float(np.mean(frame_scores))
    peak_score = float(frame_scores[peak_idx])
    confidence = min(1.0, max(0.0, (peak_score - average_score) / 50.0 + 0.5))

    return _timed(start_idx, end_idx, peak_idx, confidence, peak_score)


def detect_faces(frames: list) -> Dict[str, Any]:
    """Detect faces using DNN if available, fallback to Haar cascades.
    
    Returns face presence, size ratio, AND consistency (face in most frames = performance,
    face in few frames = b-roll).
    """
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
            face_count = 0
            
            for frame in frames:
                h, w = frame.shape[:2]
                blob = cv2.dnn.blobFromImage(frame, 1.0, (300, 300), (104.0, 177.0, 123.0))
                net.setInput(blob)
                detections = net.forward()
                frame_has_face = False
                
                for i in range(detections.shape[2]):
                    confidence = detections[i, 2]
                    if confidence > 0.5:
                        has_face = True
                        frame_has_face = True
                        box = detections[i, 3:7] * np.array([w, h, w, h])
                        fw = box[2] - box[0]
                        fh = box[3] - box[1]
                        max_face_ratio = max(max_face_ratio, (fw * fh) / float(w * h))
                
                if frame_has_face:
                    face_count += 1
            
            # Consistency: what fraction of frames have faces?
            face_consistency = face_count / float(len(frames)) if frames else 0.0
            
            return {
                "has_face": has_face,
                "face_size_ratio": float(max_face_ratio),
                "face_consistency": face_consistency,
                "face_frame_count": face_count
            }
        except Exception:
            pass  # Fall through to Haar

    # Fallback: Haar cascades (less accurate but always available)
    if not hasattr(cv2, "CascadeClassifier") or not hasattr(cv2, "data"):
        return {"has_face": False, "face_size_ratio": 0.0, "face_consistency": 0.0}
    
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    if cascade.empty():
        return {"has_face": False, "face_size_ratio": 0.0, "face_consistency": 0.0}
    
    has_face = False
    max_face_ratio = 0.0
    face_count = 0
    
    for frame in frames:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # Improved params: scaleFactor=1.2, minNeighbors=5, minSize=(30,30)
        faces = cascade.detectMultiScale(gray, 1.2, 5, 0, (30, 30))
        if len(faces):
            has_face = True
            face_count += 1
            height, width = frame.shape[:2]
            for _x, _y, face_width, face_height in faces:
                max_face_ratio = max(max_face_ratio, (face_width * face_height) / float(width * height))
    
    # Consistency: what fraction of frames have faces?
    face_consistency = face_count / float(len(frames)) if frames else 0.0
    
    return {
        "has_face": has_face,
        "face_size_ratio": float(max_face_ratio),
        "face_consistency": face_consistency,
        "face_frame_count": face_count
    }


def compute_visual_scores(frames: list, motion: float) -> Dict[str, Any]:
    """Compute visual scores with histogram from middle frame (most representative)."""
    if not frames:
        return {"composition_score": 0.0, "energy_score": 0.0, "sharpness_score": 0.0, "histogram": []}
    
    composition_scores, brightness, saturation, sharpness = [], [], [], []

    # The middle frame is the most representative sample of a clip's palette:
    # the head and tail often carry a fade, a slate or a camera settling.
    middle_frame = frames[len(frames) // 2]
    middle_hsv = cv2.cvtColor(middle_frame, cv2.COLOR_BGR2HSV)

    for frame in frames:
        frame_composition, frame_brightness, frame_saturation, frame_sharpness = _frame_metrics(frame)
        composition_scores.append(frame_composition)
        brightness.append(frame_brightness)
        saturation.append(frame_saturation)
        sharpness.append(frame_sharpness)
    
    # Normalised hue histogram — this is what drives the variety score, so it
    # has to be a real distribution rather than an empty vector.
    hue_histogram = cv2.calcHist([middle_hsv], [0], None, [32], [0, 180]).reshape(-1).astype(np.float64)
    histogram_mass = float(hue_histogram.sum())
    if histogram_mass > 0:
        hue_histogram /= histogram_mass
    else:
        hue_histogram = np.full(32, 1.0 / 32.0, dtype=np.float64)

    sharpness_score = 100.0 * (1.0 - float(np.exp(-float(np.mean(sharpness)) / 300.0)))
    energy_score = (min(100.0, max(0.0, motion * 3.0)) + float(np.mean(brightness)) + float(np.mean(saturation))) / 3.0
    
    return {
        "composition_score": float(np.mean(composition_scores)),
        "energy_score": max(0.0, min(100.0, energy_score)),
        "sharpness_score": max(0.0, min(100.0, sharpness_score)),
        "histogram": hue_histogram.tolist(),
    }


def classify_clip(video_path: str, cancel_event: Optional[threading.Event] = None) -> Dict[str, Any]:
    """Analyse one media file within a bounded time and memory budget.
    
    Now includes:
    - Motion variance (changing motion = more interesting)
    - Brightness stability (flickering = bad for cutting)
    - Face consistency (face in most frames = performance, few = b-roll)
    - Best moment detection (where the cut should start)
    """
    deadline = time.monotonic() + CLIP_TIMEOUT_SECONDS
    absolute, _stat, cache_key = _source_identity(video_path)
    _check_cancel(cancel_event)
    metadata = get_video_metadata(absolute, cancel_event)
    _check_deadline(deadline)
    frames, decoder, frame_times = extract_frames_timed(
        absolute, ANALYSIS_SAMPLES, metadata, cancel_event, deadline
    )
    if not frames:
        raise ClipAnalysisError(
            "no_decodable_frames",
            "No video frame could be decoded — the file is corrupt or uses an unsupported codec",
        )
    _check_cancel(cancel_event)
    _check_deadline(deadline)
    
    # Detect faces with consistency
    face_info = detect_faces(frames)
    
    # Compute brightness and stability
    brightness_values = [float(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).mean()) for frame in frames]
    brightness = float(np.mean(brightness_values))
    brightness_stability = compute_brightness_stability(frames)
    
    # Optical flow is the most expensive step in the whole analysis, so it runs
    # once and every motion figure below is derived from that single series.
    motion_values = optical_flow_series(frames, cancel_event, deadline)
    motion = float(np.mean(motion_values)) if motion_values else 0.0
    motion_variance = float(np.var(motion_values)) if len(motion_values) > 1 else 0.0

    # Where in the source this clip is at its most interesting, in seconds.
    best_moment = find_best_moment(frames, motion_values, frame_times)
    
    # Compute visual scores
    visual_scores = compute_visual_scores(frames, motion)
    
    # Improved scene classification using multiple factors
    face_consistency = face_info.get("face_consistency", 0.0)
    
    if face_info["has_face"] and face_info["face_size_ratio"] > 0.15:
        scene_type = "close_up"
    elif face_info["has_face"] and face_consistency > 0.6:  # Face in most frames = performance
        scene_type = "performance"
    elif face_info["has_face"] and face_consistency > 0.3:  # Face in some frames
        scene_type = "b_roll_with_face"
    elif brightness < 60:
        scene_type = "b_roll_low_light"
    elif motion < 5 and motion_variance < 2:
        scene_type = "b_roll_static"
    elif motion > 15 or motion_variance > 10:
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
        "face_consistency": face_consistency,
        "brightness": brightness,
        "brightness_stability": brightness_stability,
        "motion_intensity": motion,
        "motion_variance": motion_variance,
        "best_moment": best_moment,
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
