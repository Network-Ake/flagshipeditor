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
from typing import Any, Dict, Optional, Sequence, Tuple

import cv2
import numpy as np

from media_tools import FFMPEG, FFPROBE


ANALYSIS_SCHEMA_VERSION = "7"
ANALYSIS_MAX_DIMENSION = max(320, min(960, int(os.environ.get("FLAGSHIPEDITOR_ANALYSIS_MAX_DIM", "640"))))
ANALYSIS_SAMPLES = max(12, min(16, int(os.environ.get("FLAGSHIPEDITOR_ANALYSIS_SAMPLES", "14"))))  # Increased from 6 to 12-16 for better motion representation

# The fraction of a clip the spread samples span. Both decoders use it: OpenCV
# used to walk 0-100% while FFmpeg walked 5-95%, so the same footage produced
# different sample spacing — and therefore different motion evidence — purely
# from which decoder happened to open it. Motion is only comparable between two
# clips when both were sampled under the same policy, so the policy is fixed
# here and travels in the cache identity.
ANALYSIS_SAMPLE_WINDOW = (0.05, 0.95)

# Camera movement needs *consecutive* frames: the spread samples above are
# seconds apart, and optical flow across a two-second gap describes where the
# subject ended up, not how the camera got there. A short burst taken at the
# clip's midpoint is the smallest sample that makes the question answerable, and
# it stays bounded — one extra seek, a handful of frames, half resolution.
MOTION_BURST_FRAMES = max(2, min(12, int(os.environ.get("FLAGSHIPEDITOR_MOTION_BURST", "6"))))
MOTION_BURST_MAX_DIMENSION = max(160, min(480, int(os.environ.get("FLAGSHIPEDITOR_MOTION_BURST_DIM", "320"))))

# Professional shot scale, tightest first. ``unknown`` is not a level: it is the
# absence of evidence, and downstream scoring treats it as no opinion rather
# than as a wide shot.
SHOT_TYPES = (
    "extreme_close_up",
    "close_up",
    "medium_close_up",
    "medium_shot",
    "medium_long_shot",
    "long_shot",
    "extreme_long_shot",
)
# Face area as a fraction of frame area, at the tight end of each level. Derived
# from 16:9 film-grammar framing; a face filling 40% of frame is an ECU, a face
# under 1.5% means the body is a detail in a landscape.
SHOT_FACE_RATIO_THRESHOLDS = (0.40, 0.25, 0.15, 0.08, 0.04, 0.015)
# Framing "tightness" at the tight end of each level, for footage with no face
# to measure. Weaker evidence, and reported with a correspondingly low
# confidence.
SHOT_TIGHTNESS_THRESHOLDS = (0.85, 0.70, 0.55, 0.40, 0.28, 0.15)

CAMERA_MOVEMENTS = ("static", "pan", "tilt", "push_pull", "handheld", "unknown")
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


_CODE_HASH_CACHE: Dict[str, str] = {}


def _module_code_hash() -> str:
    """SHA-256 of this file, memoised.

    The schema version moves when a human remembers to move it; the source hash
    moves whenever the code that produced a cached number changes. The cache
    needs the second property, so it binds both.
    """
    cached = _CODE_HASH_CACHE.get("value")
    if cached is not None:
        return cached
    try:
        digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except (OSError, NameError):
        digest = f"unhashable:{ANALYSIS_SCHEMA_VERSION}"
    _CODE_HASH_CACHE["value"] = digest
    return digest


def _tool_identity(tool: Any) -> Dict[str, Any]:
    """Identify a bundled binary by path, size, mtime and reported version.

    Hashing a 70 MB FFmpeg build on every cache lookup is not affordable, and
    the version banner alone does not distinguish two builds of the same
    release. Stat identity plus the banner separates them at the cost of one
    ``stat`` call.
    """
    path = getattr(tool, "path", "") or ""
    detail = {
        "path": path,
        "available": bool(getattr(tool, "available", False)),
        "version": str(getattr(tool, "detail", ""))[:200],
    }
    try:
        stat = os.stat(path)
        detail["size"] = stat.st_size
        detail["mtime_ns"] = stat.st_mtime_ns
    except OSError:
        detail["size"] = -1
        detail["mtime_ns"] = -1
    return detail


def _file_identity(path: str) -> Dict[str, Any]:
    """Cheap, stable identity for an analysis model or configuration file."""
    value = os.path.abspath(path) if path else ""
    detail: Dict[str, Any] = {
        "path": value,
        "available": False,
        "size": -1,
        "mtime_ns": -1,
        "ctime_ns": -1,
        "inode": -1,
        "device": -1,
    }
    try:
        stat = os.stat(value)
        detail.update(
            available=os.path.isfile(value),
            size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            ctime_ns=getattr(stat, "st_ctime_ns", -1),
            inode=getattr(stat, "st_ino", -1),
            device=getattr(stat, "st_dev", -1),
        )
    except OSError:
        pass
    return detail


def _configured_face_model_identity() -> Dict[str, Any]:
    """Bind both Caffe model files, not merely their reusable base path."""
    configured = (os.environ.get("FLAGSHIPEDITOR_FACE_MODEL", "") or "").strip()
    root = configured[: -len(".prototxt")] if configured.endswith(".prototxt") else configured
    return {
        "configured": configured,
        "prototxt": _file_identity(f"{root}.prototxt" if root else ""),
        "caffemodel": _file_identity(f"{root}.caffemodel" if root else ""),
    }


def analysis_identity() -> Dict[str, Any]:
    """Return everything that can change a clip-analysis number.

    Path, size and mtime answer "is this the same file?". They say nothing
    about the code, the sampling policy, the decoder build or the detector that
    produced the cached result, so a cache hit after any of those changed
    replays evidence the current engine would never produce. Read at call time,
    so a changed setting is visible on the very next lookup.
    """
    return {
        "schema": ANALYSIS_SCHEMA_VERSION,
        "code": _module_code_hash(),
        "config": {
            "max_dimension": ANALYSIS_MAX_DIMENSION,
            "samples": ANALYSIS_SAMPLES,
            "sample_window": list(ANALYSIS_SAMPLE_WINDOW),
            "motion_burst_frames": MOTION_BURST_FRAMES,
            "motion_burst_max_dimension": MOTION_BURST_MAX_DIMENSION,
            "face_model": _configured_face_model_identity(),
        },
        "tools": {
            "ffmpeg": _tool_identity(FFMPEG),
            "ffprobe": _tool_identity(FFPROBE),
        },
        "dependencies": {
            "opencv": str(getattr(cv2, "__version__", "unknown")),
            "numpy": str(getattr(np, "__version__", "unknown")),
        },
    }


def identity_fingerprint(identity: Dict[str, Any]) -> str:
    """Hash an identity document deterministically (sorted keys, no whitespace)."""
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _source_identity(
    video_path: str,
    identity: Optional[Dict[str, Any]] = None,
) -> Tuple[str, os.stat_result, str]:
    absolute = os.path.abspath(video_path)
    try:
        stat = os.stat(absolute)
    except FileNotFoundError as error:
        raise ClipAnalysisError("missing", f"Media file is missing: {video_path}") from error
    except OSError as error:
        raise ClipAnalysisError("unreadable", f"Cannot access media file: {video_path} ({error})") from error
    if not os.path.isfile(absolute) or stat.st_size <= 0:
        raise ClipAnalysisError("invalid_file", f"Media file is empty or not a regular file: {video_path}")
    identity = "|".join(
        (
            os.path.normcase(absolute),
            str(stat.st_size),
            str(stat.st_mtime_ns),
            identity_fingerprint(identity or analysis_identity()),
        )
    )
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
        # Same 5-95% window FFmpeg uses, so the two decoders produce the same
        # sample spacing and their motion numbers stay comparable.
        last_frame = max(0, total_frames - 1)
        first_position = int(round(last_frame * ANALYSIS_SAMPLE_WINDOW[0]))
        last_position = int(round(last_frame * ANALYSIS_SAMPLE_WINDOW[1]))
        positions = np.linspace(
            first_position, last_position, num=max(1, num_frames), dtype=int
        )
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
        timestamps = np.linspace(
            duration * ANALYSIS_SAMPLE_WINDOW[0],
            duration * ANALYSIS_SAMPLE_WINDOW[1],
            num=max(1, num_frames),
        ).tolist()
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


def extract_motion_burst(
    video_path: str,
    metadata: Dict[str, Any],
    decoder: str,
    cancel_event: Optional[threading.Event] = None,
    deadline: Optional[float] = None,
) -> list:
    """Grab a short run of consecutive frames from the middle of the clip.

    The spread samples the rest of the analysis uses are seconds apart, which is
    fine for "how much does this clip move" and useless for "how does the camera
    move" — Farneback cannot track a displacement of half a frame width, and a
    two-second gap makes every move look like noise. Consecutive frames restore
    the question.

    The burst is deliberately small and taken at half the analysis resolution:
    direction statistics survive downsampling, and the cost has to stay inside
    the per-clip budget. Returns ``[]`` rather than raising when the burst
    cannot be read, because camera movement is an enrichment and must never fail
    a clip that otherwise analysed cleanly.
    """
    _check_cancel(cancel_event)
    duration = safe_float(metadata.get("duration"))
    fps = safe_float(metadata.get("fps"), 30.0)
    if fps <= 0:
        fps = 30.0
    burst_seconds = MOTION_BURST_FRAMES / fps
    midpoint = max(0.0, duration * 0.5 - burst_seconds * 0.5) if duration > 0 else 0.0

    def _shrink(frames: list) -> list:
        return [resize_for_analysis(frame, MOTION_BURST_MAX_DIMENSION) for frame in frames]

    if decoder != "ffmpeg":
        capture = cv2.VideoCapture(video_path, cv2.CAP_FFMPEG)
        try:
            if capture.isOpened():
                total = safe_int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
                if total >= 2:
                    start = max(0, min(total - MOTION_BURST_FRAMES, int(total // 2)))
                    capture.set(cv2.CAP_PROP_POS_FRAMES, start)
                    frames = []
                    for _ in range(MOTION_BURST_FRAMES):
                        _check_cancel(cancel_event)
                        ok, frame = capture.read()
                        if not ok or frame is None:
                            break
                        frames.append(frame)
                    if len(frames) >= 2:
                        return _shrink(frames)
        except cv2.error:
            pass
        finally:
            capture.release()

    if not FFMPEG.available:
        return []
    scale_filter = (
        f"scale=w='if(gte(iw,ih),min(iw,{MOTION_BURST_MAX_DIMENSION}),-2)':"
        f"h='if(lt(iw,ih),min(ih,{MOTION_BURST_MAX_DIMENSION}),-2)'"
    )
    command = [
        FFMPEG_PATH,
        "-v", "error",
        "-ss", f"{midpoint:.6f}",
        "-i", video_path,
        "-map", "0:v:0",
        "-frames:v", str(MOTION_BURST_FRAMES),
        "-vf", scale_filter,
        "-f", "image2pipe",
        "-vcodec", "bmp",
        "pipe:1",
    ]
    budget = FRAME_TIMEOUT_SECONDS
    if deadline is not None:
        budget = int(max(1, min(budget, deadline - time.monotonic())))
    try:
        payload = _run_cancellable(command, cancel_event, budget)
    except ClipAnalysisError as error:
        if error.code == "cancelled":
            raise
        return []
    return _shrink(_split_bmp_stream(payload))


def _split_bmp_stream(payload: bytes) -> list:
    """Decode a concatenated BMP stream into frames.

    BMP is used for the burst rather than MJPEG because every image carries its
    own byte length in the header, so consecutive frames can be split apart
    exactly instead of being scanned for markers.
    """
    frames = []
    offset = 0
    total = len(payload)
    while offset + 6 <= total and len(frames) < MOTION_BURST_FRAMES:
        if payload[offset:offset + 2] != b"BM":
            break
        size = int.from_bytes(payload[offset + 2:offset + 6], "little")
        if size <= 0 or offset + size > total:
            break
        frame = cv2.imdecode(
            np.frombuffer(payload[offset:offset + size], dtype=np.uint8), cv2.IMREAD_COLOR
        )
        if frame is None:
            break
        frames.append(frame)
        offset += size
    return frames


def optical_flow_series(
    frames: list,
    cancel_event: Optional[threading.Event] = None,
    deadline: Optional[float] = None,
    timestamps: Optional[list] = None,
) -> list:
    """Return the mean flow magnitude between each consecutive frame pair.

    Farneback flow is by far the most expensive step in clip analysis, so it is
    computed once here and every motion metric is derived from the result.

    The values are pixels of displacement *between two samples*, not per second.
    Pass ``timestamps`` and read ``magnitude_per_second`` off
    ``flow_descriptors`` when the numbers have to be compared between clips of
    different length — see ``motion_sample_policy``.
    """
    return [
        entry["magnitude"]
        for entry in flow_descriptors(frames, cancel_event, deadline, timestamps)
    ]


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


def flow_descriptors(
    frames: list,
    cancel_event: Optional[threading.Event] = None,
    deadline: Optional[float] = None,
    timestamps: Optional[list] = None,
) -> list:
    """Describe each consecutive frame pair with one dense-flow pass.

    ``mean(|flow|)`` — the only number the engine used to keep — cannot tell a
    smooth pan from a shaky handheld shot: both move the same number of pixels.
    The direction of the field is what separates them, so the same Farneback
    result also yields the mean translation vector, how much of the field agrees
    with that vector, and how much of it points away from frame centre.

    Farneback is the most expensive step in clip analysis, so it is still run
    exactly once per pair and every motion figure is derived from this result.

    ``magnitude`` is displacement between two *samples*, and the spread samples
    are seconds apart — a 60 s clip puts four seconds between them, a 4 s clip a
    quarter of one. Comparing those two numbers compares sample spacing as much
    as it compares movement. When ``timestamps`` is supplied each pair therefore
    also carries the source time it spans and ``magnitude_per_second``, which is
    the figure that is comparable across clips.
    """
    if len(frames) < 2:
        return []
    times = [float(value) for value in (timestamps or [])][:len(frames)]
    descriptors = []
    previous_gray = cv2.cvtColor(frames[0], cv2.COLOR_BGR2GRAY)
    height, width = previous_gray.shape[:2]
    # A fixed grid of probe points keeps the statistics bounded and identical
    # for a given frame size, whatever the resolution of the source.
    stride = max(1, int(round(max(height, width) / 96.0)))
    rows = np.arange(0, height, stride)
    columns = np.arange(0, width, stride)
    centre_y = (height - 1) / 2.0
    centre_x = (width - 1) / 2.0
    grid_y, grid_x = np.meshgrid(rows - centre_y, columns - centre_x, indexing="ij")
    radius = np.sqrt(grid_x ** 2 + grid_y ** 2)
    safe_radius = np.where(radius > 1e-6, radius, 1.0)
    radial_x = grid_x / safe_radius
    radial_y = grid_y / safe_radius

    for pair_index, current in enumerate(frames[1:]):
        _check_cancel(cancel_event)
        _check_deadline(deadline)
        current_gray = cv2.cvtColor(current, cv2.COLOR_BGR2GRAY)
        flow = cv2.calcOpticalFlowFarneback(
            previous_gray, current_gray, None, 0.5, 3, 15, 3, 5, 1.2, 0
        )
        magnitude = float(np.mean(np.linalg.norm(flow, axis=2)))

        sampled = flow[np.ix_(rows, columns)]
        delta_x = sampled[..., 0]
        delta_y = sampled[..., 1]
        lengths = np.sqrt(delta_x ** 2 + delta_y ** 2)
        total_length = float(np.sum(lengths))
        mean_x = float(np.mean(delta_x))
        mean_y = float(np.mean(delta_y))
        translation = math.hypot(mean_x, mean_y)
        # 1.0 when every vector points the same way (a tripod pan), towards 0
        # when they cancel out (handheld, parallax, subject motion).
        coherence = (
            translation * float(lengths.size) / total_length if total_length > 1e-9 else 0.0
        )
        # Positive when the field expands from centre (push in / zoom in),
        # negative when it collapses towards it (pull out).
        # Projecting each vector onto its own outward direction and dividing by
        # the total distance travelled gives a true alignment in [-1, 1]: the
        # projection of a vector on a unit direction can never exceed its own
        # length.
        radial = (
            float(np.sum(delta_x * radial_x + delta_y * radial_y)) / total_length
            if total_length > 1e-9
            else 0.0
        )
        descriptor = {
            "magnitude": magnitude,
            "mean_x": mean_x,
            "mean_y": mean_y,
            "coherence": max(0.0, min(1.0, coherence)),
            "radial": max(-1.0, min(1.0, radial)),
        }
        if len(times) > pair_index + 1:
            start_time = times[pair_index]
            end_time = times[pair_index + 1]
            elapsed = end_time - start_time
            descriptor["start_time"] = start_time
            descriptor["end_time"] = end_time
            descriptor["elapsed"] = elapsed
            # Two samples taken at the same instant cannot describe a rate, and
            # inventing one by dividing by an epsilon would report a number
            # nothing measured.
            descriptor["magnitude_per_second"] = (
                magnitude / elapsed if elapsed > 1e-9 else None
            )
        descriptors.append(descriptor)
        previous_gray = current_gray
    return descriptors


def motion_sample_policy(
    decoder: str,
    timestamps: Optional[list],
    descriptors: Optional[list] = None,
    duration: float = 0.0,
) -> Dict[str, Any]:
    """Describe how the motion evidence for one clip was sampled.

    Two motion numbers are only comparable when they were produced the same
    way. This records the decoder that produced the frames, the window of the
    source they span, how far apart they sit and whether a per-second figure
    could be derived — so a consumer can tell "this clip moves more" from "this
    clip was sampled further apart".
    """
    times = [float(value) for value in (timestamps or [])]
    spacings = [second - first for first, second in zip(times, times[1:])]
    normalized = bool(
        descriptors
        and all(entry.get("magnitude_per_second") is not None for entry in descriptors)
    )
    coverage = (times[-1] - times[0]) if len(times) >= 2 else 0.0
    duration = safe_float(duration)
    return {
        "decoder": str(decoder or "unknown"),
        "samples_requested": ANALYSIS_SAMPLES,
        "samples_used": len(times),
        "window": list(ANALYSIS_SAMPLE_WINDOW),
        "coverage_start": round(times[0], 6) if times else 0.0,
        "coverage_end": round(times[-1], 6) if times else 0.0,
        "coverage_seconds": round(coverage, 6),
        "coverage_fraction": round(coverage / duration, 6) if duration > 0 else 0.0,
        "mean_spacing_seconds": (
            round(sum(spacings) / len(spacings), 6) if spacings else 0.0
        ),
        "consecutive_frames": False,
        "elapsed_normalized": normalized,
        "claim": (
            "spread samples seconds apart, not adjacent video frames; "
            "compare motion_intensity_per_second across clips, never motion_intensity"
        ),
    }


def classify_camera_movement(descriptors: list, source: str = "burst") -> Dict[str, Any]:
    """Name the camera move behind a series of flow descriptors.

    The decision is a cascade, cheapest and most certain first: no movement at
    all, then a field that expands or collapses about centre, then a field that
    translates as one piece, and finally movement that is real but agrees with
    itself neither in space nor across time — which is what handheld operating
    looks like.

    ``unknown`` is returned rather than guessed whenever the evidence is missing,
    so a clip analysed without a usable burst is treated by the selector as
    having no opinion instead of being labelled static.
    """
    if not descriptors:
        return {
            "camera_movement": "unknown",
            "camera_movement_confidence": 0.0,
            "camera_movement_source": "unavailable",
        }

    magnitudes = np.asarray([entry["magnitude"] for entry in descriptors], dtype=np.float64)
    mean_magnitude = float(np.mean(magnitudes))
    vectors = np.asarray(
        [(entry["mean_x"], entry["mean_y"]) for entry in descriptors], dtype=np.float64
    )
    lengths = np.linalg.norm(vectors, axis=1)
    travelled = float(np.sum(lengths))
    # 1.0 when every pair moves the camera the same way (a sustained move),
    # towards 0 when the direction flips from pair to pair (shake).
    consistency = (
        float(np.linalg.norm(np.sum(vectors, axis=0))) / travelled if travelled > 1e-9 else 0.0
    )
    coherence = float(np.mean([entry["coherence"] for entry in descriptors]))
    radial = float(np.mean([entry["radial"] for entry in descriptors]))
    net_x, net_y = (float(value) for value in np.sum(vectors, axis=0))

    # Confidence is deliberately capped below 1.0: this is inferred from
    # apparent motion, with no scene depth and no camera metadata.
    penalty = 1.0 if source == "burst" else 0.55

    if mean_magnitude < 0.6:
        movement = "static"
        confidence = min(1.0, (0.6 - mean_magnitude) / 0.6 + 0.4)
    elif abs(radial) >= 0.45 and abs(radial) >= coherence:
        movement = "push_pull"
        confidence = min(1.0, (abs(radial) - 0.45) / 0.35 + 0.45)
    elif coherence >= 0.5 and consistency >= 0.6:
        movement = "pan" if abs(net_x) >= abs(net_y) else "tilt"
        confidence = min(1.0, (coherence - 0.5) / 0.4 * 0.5 + consistency * 0.5)
    else:
        movement = "handheld"
        confidence = min(1.0, (1.0 - coherence) * 0.5 + (1.0 - consistency) * 0.5)

    return {
        "camera_movement": movement,
        "camera_movement_confidence": round(max(0.0, min(1.0, confidence)) * penalty, 4),
        "camera_movement_source": source,
        "camera_translation_coherence": round(coherence, 4),
        "camera_direction_consistency": round(max(0.0, min(1.0, consistency)), 4),
        "camera_radial_flow": round(radial, 4),
    }


def framing_tightness(frame: np.ndarray) -> float:
    """Estimate how tightly a frame is framed, from 0 (widest) to 1 (tightest).

    This is the fallback for footage with no face to measure, and it reads three
    things a lens does rather than anything about the subject: a tight shot has
    little fine detail spread across the frame, it separates a sharp centre from
    a soft surround, and large parts of it are flat. A landscape is the opposite
    on all three counts.

    It is a framing proxy, not subject detection, which is why every shot type
    derived from it is reported with low confidence.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape[:2]
    if height < 8 or width < 8:
        return 0.5

    edges = cv2.Canny(gray, 50, 150)
    edge_density = float(np.count_nonzero(edges)) / float(edges.size)

    top, bottom = height // 3, 2 * height // 3
    left, right = width // 3, 2 * width // 3
    centre = gray[top:bottom, left:right]
    centre_detail = float(cv2.Laplacian(centre, cv2.CV_64F).var()) if centre.size else 0.0
    surround = gray.copy()
    surround[top:bottom, left:right] = 0
    border_detail = float(cv2.Laplacian(surround, cv2.CV_64F).var())
    separation = centre_detail / border_detail if border_detail > 1e-6 else 1.0

    blurred = cv2.blur(gray.astype(np.float32), (9, 9))
    local_variance = cv2.blur((gray.astype(np.float32) - blurred) ** 2, (9, 9))
    flat_fraction = float(np.mean(local_variance < 12.0))

    tightness = (
        0.45 * (1.0 - min(1.0, edge_density / 0.12))
        + 0.30 * max(0.0, min(1.0, (separation - 1.0) / 3.0))
        + 0.25 * flat_fraction
    )
    return max(0.0, min(1.0, tightness))


def _bucket(value: float, thresholds: Sequence[float]) -> str:
    for index, threshold in enumerate(thresholds):
        if value >= threshold:
            return SHOT_TYPES[index]
    return SHOT_TYPES[len(thresholds)]


def classify_shot_type(frames: list, face_info: Dict[str, Any]) -> Dict[str, Any]:
    """Place a clip on the seven-level shot scale, tightest to widest.

    Collapsing footage into "close_up or b-roll" throws away the distinction an
    editor actually cuts on: a verse wants the artist's face readable, a drop
    wants the body and the room in frame. Face area against frame area is the
    measurement that separates them, and it is the one this engine can make
    without a pose model.

    When no face is found the scale is estimated from framing instead, and the
    returned confidence says so. ``unknown`` is reserved for clips with no
    frames at all.
    """
    if not frames:
        return {"shot_type": "unknown", "shot_type_confidence": 0.0, "shot_scale": 0.0}

    face_ratio = safe_float(face_info.get("face_size_ratio"), 0.0)
    consistency = safe_float(face_info.get("face_consistency"), 0.0)
    if face_info.get("has_face") and face_ratio > 0.0:
        return {
            "shot_type": _bucket(face_ratio, SHOT_FACE_RATIO_THRESHOLDS),
            # A face seen in one frame of fourteen is a passer-by, not the
            # framing of the shot; consistency is what makes the measurement
            # representative of the clip rather than of one sample.
            "shot_type_confidence": round(max(0.0, min(1.0, 0.55 + 0.45 * consistency)), 4),
            "shot_scale": round(max(0.0, min(1.0, face_ratio)), 6),
            "shot_type_basis": "face",
        }

    tightness = framing_tightness(frames[len(frames) // 2])
    return {
        "shot_type": _bucket(tightness, SHOT_TIGHTNESS_THRESHOLDS),
        "shot_type_confidence": 0.35,
        "shot_scale": round(tightness, 6),
        "shot_type_basis": "framing",
    }


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


def find_moment_windows(
    frames: list,
    motion_values: Optional[list] = None,
    timestamps: Optional[list] = None,
    limit: int = 4,
    min_separation: float = 0.75,
) -> list:
    """Rank several distinct moments in a clip, not just the single best one.

    ``find_best_moment`` reports one peak. The selector used to seek to it every
    single time a clip appeared, so a clip used eight times showed the *same
    frames* eight times — measured at 94.3 % of cuts reusing a source window,
    with only 49 distinct windows across an entire 857-cut timeline.

    Publishing several ranked moments is what makes reuse survivable: the second
    appearance of a clip can go somewhere else in it. Peaks closer together than
    ``min_separation`` seconds are collapsed, so "a different moment" means
    genuinely different material rather than the same instant nudged by a frame.

    Returns ``[]`` rather than a fabricated spread when there are too few
    samples or no timestamps to place them in the clip's own timeline.
    """
    frame_count = len(frames) if frames else 0
    times = [float(value) for value in (timestamps or [])][:frame_count]
    if frame_count < 4 or len(times) < frame_count:
        return []

    motion_per_frame = per_frame_motion(motion_values, frame_count)
    scores = []
    for index, frame in enumerate(frames):
        composition, brightness, _saturation, sharpness = _frame_metrics(frame)
        score = composition + min(100.0, brightness) + min(100.0, motion_per_frame[index] * 3.0)
        score += min(100.0, sharpness) * 0.35
        scores.append(score)

    average = float(np.mean(scores))
    spread = float(np.std(scores)) or 1.0
    order = sorted(range(frame_count), key=lambda index: (-scores[index], index))

    chosen: list = []
    for index in order:
        moment = times[index]
        if any(abs(moment - entry["time"]) < min_separation for entry in chosen):
            continue
        chosen.append(
            {
                "time": round(float(moment), 4),
                "frameIndex": int(index),
                # Normalised against this clip's own spread: an absolute score
                # would rank a bright clip above a well-composed dark one for
                # reasons that have nothing to do with which moment is best
                # *within* the clip.
                "score": round(float(max(0.0, min(1.0, 0.5 + (scores[index] - average) / (spread * 4.0)))), 4),
            }
        )
        if len(chosen) >= limit:
            break
    return chosen


FACE_CONFIDENCE_THRESHOLD = 0.5


def _resolve_face_model(base: str) -> Tuple[str, str, str]:
    """Return ``(prototxt, caffemodel, identity)`` for a configured DNN model.

    ``FLAGSHIPEDITOR_FACE_MODEL`` is documented as a *base* path — the loader
    appends ``.prototxt`` and ``.caffemodel``. It was also tested with
    ``os.path.isfile`` on the base itself, so the documented configuration
    failed that test and dropped silently to Haar. Both spellings are accepted
    here: a base path, or the prototxt itself with the weights beside it.

    Returns empty strings when nothing usable is configured; the caller records
    that as the reason it fell back.
    """
    base = (base or "").strip()
    if not base:
        return "", "", ""
    root = base[: -len(".prototxt")] if base.endswith(".prototxt") else base
    prototxt = f"{root}.prototxt"
    caffemodel = f"{root}.caffemodel"
    if os.path.isfile(prototxt) and os.path.isfile(caffemodel):
        return prototxt, caffemodel, os.path.basename(root)
    return "", "", os.path.basename(root)


_FACE_DETECTOR_LOCAL = threading.local()


def _face_detector_cache() -> Dict[str, Any]:
    cache = getattr(_FACE_DETECTOR_LOCAL, "cache", None)
    if cache is None:
        cache = {}
        _FACE_DETECTOR_LOCAL.cache = cache
    return cache


def _cached_dnn_face_detector(prototxt: str, caffemodel: str) -> Any:
    """Load one Caffe detector per worker thread and model-file identity."""
    key = identity_fingerprint(
        {"prototxt": _file_identity(prototxt), "caffemodel": _file_identity(caffemodel)}
    )
    cache = _face_detector_cache()
    if cache.get("dnn_key") != key:
        cache["dnn"] = cv2.dnn.readNetFromCaffe(prototxt, caffemodel)
        cache["dnn_key"] = key
    return cache["dnn"]


def _cached_haar_face_detector(path: str) -> Any:
    """Load one Haar cascade per worker thread instead of once per clip."""
    key = identity_fingerprint(_file_identity(path))
    cache = _face_detector_cache()
    if cache.get("haar_key") != key:
        cache["haar"] = cv2.CascadeClassifier(path)
        cache["haar_key"] = key
    return cache["haar"]


def _dnn_face_boxes(
    detections: Any,
    width: int,
    height: int,
    threshold: float = FACE_CONFIDENCE_THRESHOLD,
) -> list:
    """Extract ``(ratio, confidence)`` pairs from one Caffe SSD forward pass.

    ``net.forward()`` returns a ``(1, 1, N, 7)`` volume. Indexing it as if it
    were ``(N, 7)`` yields a 2-D slice, so the confidence test raises "truth
    value of an array is ambiguous" and the whole DNN branch lands in its
    ``except`` — which is why the optional detector could never actually run.
    """
    array = np.asarray(detections, dtype=np.float64)
    rows = array.reshape(-1, array.shape[-1]) if array.size else np.empty((0, 7))
    frame_area = float(width * height)
    boxes = []
    for row in rows:
        if row.shape[0] < 7:
            continue
        confidence = float(row[2])
        if not math.isfinite(confidence) or confidence <= threshold:
            continue
        left, top, right, bottom = (float(value) for value in row[3:7])
        face_width = (right - left) * width
        face_height = (bottom - top) * height
        if face_width <= 0 or face_height <= 0 or frame_area <= 0:
            continue
        ratio = (face_width * face_height) / frame_area
        if math.isfinite(ratio) and ratio > 0:
            boxes.append((min(1.0, ratio), confidence))
    return boxes


def _face_result(
    detector: str,
    frames: int,
    face_frames: int,
    max_ratio: float,
    fallback: str = "",
    model: str = "",
    confidence: float = 0.0,
    confidence_kind: str = "unavailable",
) -> Dict[str, Any]:
    """Assemble one face verdict together with what produced it.

    ``has_face=False`` and ``face_size_ratio=0`` are the same two fields whether
    a detector looked and found nothing or no detector could run at all. The
    provenance fields are what separate those cases, so a consumer never reads
    "no face" as a measurement when it is an absence of measurement.
    """
    ratio = float(max_ratio) if math.isfinite(float(max_ratio)) else 0.0
    has_face = bool(face_frames > 0 and ratio > 0.0)
    return {
        "has_face": has_face,
        "face_size_ratio": ratio if has_face else 0.0,
        "face_consistency": (face_frames / float(frames)) if frames > 0 else 0.0,
        "face_frame_count": int(face_frames),
        "face_detector": detector,
        "face_detector_fallback": fallback,
        "face_detector_model": model,
        "face_detector_confidence": round(max(0.0, min(1.0, float(confidence))), 4),
        "face_detector_confidence_kind": str(confidence_kind),
        "face_frames_examined": int(frames),
    }


def detect_faces(frames: list) -> Dict[str, Any]:
    """Detect faces using DNN if available, fallback to Haar cascades.

    Returns face presence, size ratio, AND consistency (face in most frames =
    performance, face in few frames = b-roll), plus which detector produced the
    answer and why it was that one. A silent degradation from DNN to Haar
    changes both the accuracy and the failure modes of everything downstream —
    shot scale, scene type, the verse/chorus affinity — so it is recorded
    rather than hidden.
    """
    frame_count = len(frames)

    # Try DNN-based face detector first (more accurate, handles angles better)
    configured = os.environ.get("FLAGSHIPEDITOR_FACE_MODEL", "")
    prototxt, caffemodel, model_identity = _resolve_face_model(configured)
    fallback_reason = ""
    if configured and not prototxt:
        fallback_reason = "dnn_model_files_missing"
    elif prototxt:
        try:
            net = _cached_dnn_face_detector(prototxt, caffemodel)
            max_face_ratio = 0.0
            best_confidence = 0.0
            face_count = 0

            for frame in frames:
                h, w = frame.shape[:2]
                blob = cv2.dnn.blobFromImage(frame, 1.0, (300, 300), (104.0, 177.0, 123.0))
                net.setInput(blob)
                boxes = _dnn_face_boxes(net.forward(), w, h)
                if boxes:
                    face_count += 1
                    max_face_ratio = max(max_face_ratio, max(ratio for ratio, _ in boxes))
                    best_confidence = max(best_confidence, max(value for _, value in boxes))

            return _face_result(
                "dnn_caffe",
                frame_count,
                face_count,
                max_face_ratio,
                model=model_identity,
                confidence=best_confidence,
                confidence_kind="detector_score",
            )
        except (cv2.error, ValueError, AttributeError, IndexError) as error:
            fallback_reason = f"dnn_failed:{type(error).__name__}"

    # Fallback: Haar cascades (less accurate but always available)
    if not hasattr(cv2, "CascadeClassifier") or not hasattr(cv2, "data"):
        return _face_result(
            "unavailable",
            frame_count,
            0,
            0.0,
            fallback=fallback_reason or "opencv_cascade_support_missing",
            model=model_identity,
        )

    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    cascade = _cached_haar_face_detector(cascade_path)
    if cascade.empty():
        return _face_result(
            "unavailable",
            frame_count,
            0,
            0.0,
            fallback=fallback_reason or "haar_cascade_file_missing",
            model=model_identity,
        )

    max_face_ratio = 0.0
    face_count = 0

    for frame in frames:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # Improved params: scaleFactor=1.2, minNeighbors=5, minSize=(30,30)
        faces = cascade.detectMultiScale(gray, 1.2, 5, 0, (30, 30))
        if len(faces):
            face_count += 1
            height, width = frame.shape[:2]
            for _x, _y, face_width, face_height in faces:
                max_face_ratio = max(max_face_ratio, (face_width * face_height) / float(width * height))

    return _face_result(
        "haar_cascade",
        frame_count,
        face_count,
        max_face_ratio,
        fallback=fallback_reason or ("dnn_not_configured" if not configured else ""),
        model=model_identity,
        # Haar exposes no calibrated detector score. Report that absence rather
        # than manufacturing a number that looks comparable with the DNN.
        confidence=0.0,
        confidence_kind="unavailable",
    )


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


def classify_clip(
    video_path: str,
    cancel_event: Optional[threading.Event] = None,
    *,
    _identity: Optional[Dict[str, Any]] = None,
    _source: Optional[Tuple[str, os.stat_result, str]] = None,
) -> Dict[str, Any]:
    """Analyse one media file within a bounded time and memory budget.
    
    Now includes:
    - Motion variance (changing motion = more interesting)
    - Brightness stability (flickering = bad for cutting)
    - Face consistency (face in most frames = performance, few = b-roll)
    - Best moment detection (where the cut should start)
    - Shot scale on the seven-level professional taxonomy (``shot_type``)
    - Camera movement from a bounded burst of consecutive frames

    ``scene_type`` keeps its original vocabulary and its original rules. The
    shot scale is published alongside it rather than in place of it, so every
    existing consumer — the section affinity table, the panel, saved projects —
    keeps reading exactly what it read before.
    """
    deadline = time.monotonic() + CLIP_TIMEOUT_SECONDS
    identity = _identity or analysis_identity()
    absolute, _stat, cache_key = _source or _source_identity(video_path, identity)
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
    spread_descriptors = flow_descriptors(frames, cancel_event, deadline, frame_times)
    motion_values = [entry["magnitude"] for entry in spread_descriptors]
    motion = float(np.mean(motion_values)) if motion_values else 0.0
    motion_variance = float(np.var(motion_values)) if len(motion_values) > 1 else 0.0
    # The same movement, expressed as a rate. ``motion_intensity`` is
    # displacement between two samples and therefore scales with how far apart
    # this clip's samples happened to fall; the per-second figure is the one
    # that can be compared with another clip's.
    rates = [
        entry["magnitude_per_second"]
        for entry in spread_descriptors
        if entry.get("magnitude_per_second") is not None
    ]
    motion_per_second = float(np.mean(rates)) if rates else None
    motion_variance_per_second = float(np.var(rates)) if len(rates) > 1 else None
    sample_policy = motion_sample_policy(
        decoder, frame_times, spread_descriptors, metadata.get("duration", 0.0)
    )

    # How the camera moves, read from consecutive frames rather than from the
    # spread samples. Falling back to the spread samples keeps a usable answer
    # for clips whose burst cannot be decoded, at a reduced confidence.
    _check_deadline(deadline)
    burst = extract_motion_burst(absolute, metadata, decoder, cancel_event, deadline)
    if len(burst) >= 2:
        camera = classify_camera_movement(
            flow_descriptors(burst, cancel_event, deadline), "burst"
        )
    else:
        camera = classify_camera_movement(spread_descriptors, "sparse")

    # Where this clip sits on the seven-level shot scale.
    shot = classify_shot_type(frames, face_info)

    # Where in the source this clip is at its most interesting, in seconds.
    best_moment = find_best_moment(frames, motion_values, frame_times)
    # Several ranked moments, so a clip that appears more than once can show
    # different material each time instead of repeating its own best frame.
    moment_windows = find_moment_windows(frames, motion_values, frame_times)
    
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
        "face_detector": face_info["face_detector"],
        "face_detector_fallback": face_info["face_detector_fallback"],
        "face_detector_model": face_info["face_detector_model"],
        "face_detector_confidence": face_info["face_detector_confidence"],
        "face_detector_confidence_kind": face_info["face_detector_confidence_kind"],
        "face_frames_examined": face_info["face_frames_examined"],
        "brightness": brightness,
        "brightness_stability": brightness_stability,
        "motion_intensity": motion,
        "motion_variance": motion_variance,
        "motion_intensity_per_second": motion_per_second,
        "motion_variance_per_second": motion_variance_per_second,
        "motion_sample_times": [round(float(value), 6) for value in frame_times],
        "motion_sample_policy": sample_policy,
        "best_moment": best_moment,
        "moment_windows": moment_windows,
        **shot,
        **camera,
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
        "analysis_identity": dict(identity, fingerprint=identity_fingerprint(identity)),
    }


def classify_clip_cached(
    video_path: str,
    cancel_event: Optional[threading.Event] = None,
) -> Tuple[Dict[str, Any], bool]:
    identity = analysis_identity()
    source = _source_identity(video_path, identity)
    absolute, stat, cache_key = source
    fingerprint = identity_fingerprint(identity)
    _check_cancel(cancel_event)
    with _cache_connection() as connection:
        row = connection.execute(
            "SELECT result_json FROM analysis_cache WHERE cache_key = ? AND schema_version = ?",
            (cache_key, ANALYSIS_SCHEMA_VERSION),
        ).fetchone()
        if row:
            cached = json.loads(row[0])
            # The key already binds the identity, so a row whose stored
            # fingerprint disagrees was not written by this engine. Rebuilding
            # is cheaper than trusting it.
            if (
                isinstance(cached, dict)
                and (cached.get("analysis_identity") or {}).get("fingerprint") == fingerprint
            ):
                connection.execute("UPDATE analysis_cache SET last_access = ? WHERE cache_key = ?", (time.time(), cache_key))
                return cached, True
    result = classify_clip(absolute, cancel_event, _identity=identity, _source=source)
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
