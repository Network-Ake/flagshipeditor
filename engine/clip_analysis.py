"""
FlagshipEditor — Clip Analysis Engine
Uses OpenCV + MediaPipe to classify video clips.
Supports ProRes 422 via FFmpeg.
"""

import cv2
import numpy as np
import subprocess
import json
import os
from typing import Dict, Any
import tempfile


def get_video_metadata(video_path: str) -> Dict[str, Any]:
    """Extract metadata from video file using FFprobe."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # Fallback to OpenCV
        cap = cv2.VideoCapture(video_path)
        return {
            "codec": "unknown",
            "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "fps": cap.get(cv2.CAP_PROP_FPS),
            "duration": cap.get(cv2.CAP_PROP_FRAME_COUNT) / max(cap.get(cv2.CAP_PROP_FPS), 1),
        }

    metadata = json.loads(result.stdout)
    stream = metadata["streams"][0]
    fmt = metadata.get("format", {})

    return {
        "codec": stream.get("codec_name", "unknown"),
        "profile": stream.get("profile", "unknown"),
        "width": int(stream.get("width", 0)),
        "height": int(stream.get("height", 0)),
        "fps": eval(stream.get("r_frame_rate", "30/1")),
        "duration": float(stream.get("duration", 0) or fmt.get("duration", 0)),
        "bit_rate": int(stream.get("bit_rate", 0)),
    }


def extract_frames(video_path: str, num_frames: int = 10) -> list:
    """Extract sample frames from video using OpenCV."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0:
        cap.release()
        return []

    frames = []
    step = max(1, total_frames // num_frames)

    for i in range(num_frames):
        frame_idx = i * step
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if ret:
            frames.append(frame)

    cap.release()
    return frames


def compute_motion_intensity(frames: list) -> float:
    """Compute motion intensity via optical flow between consecutive frames."""
    if len(frames) < 2:
        return 0.0

    total_motion = 0.0
    count = 0

    for i in range(1, len(frames)):
        prev_gray = cv2.cvtColor(frames[i - 1], cv2.COLOR_BGR2GRAY)
        curr_gray = cv2.cvtColor(frames[i], cv2.COLOR_BGR2GRAY)

        flow = cv2.calcOpticalFlowFarneback(
            prev_gray, curr_gray, None, 0.5, 3, 15, 3, 5, 1.2, 0
        )
        magnitude = np.sqrt(flow[:, :, 0] ** 2 + flow[:, :, 1] ** 2)
        total_motion += np.mean(magnitude)
        count += 1

    return float(total_motion / max(count, 1))


def detect_faces(frames: list) -> Dict[str, Any]:
    """Detect faces using OpenCV Haar Cascade (no MediaPipe dependency required)."""
    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )

    has_face = False
    max_face_ratio = 0.0

    for frame in frames:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.1, 4)

        if len(faces) > 0:
            has_face = True
            h, w = frame.shape[:2]
            for (fx, fy, fw, fh) in faces:
                ratio = (fw * fh) / (w * h)
                max_face_ratio = max(max_face_ratio, ratio)

    return {
        "has_face": has_face,
        "face_size_ratio": float(max_face_ratio),
    }


def classify_clip(video_path: str) -> Dict[str, Any]:
    """
    Full clip classification: face detection, motion, brightness, scene type.
    Supports ProRes 422 via FFmpeg/OpenCV.
    """
    # Get metadata
    meta = get_video_metadata(video_path)

    # Extract sample frames
    frames = extract_frames(video_path, num_frames=10)

    if not frames:
        return {
            "path": video_path,
            "name": os.path.basename(video_path),
            "duration": meta.get("duration", 0),
            "scene_type": "unknown",
            "has_face": False,
            "brightness": 0,
            "motion_intensity": 0,
            "codec": meta.get("codec", "unknown"),
            "width": meta.get("width", 0),
            "height": meta.get("height", 0),
        }

    # Face detection
    face_info = detect_faces(frames)

    # Brightness
    brightness = float(np.mean([
        cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).mean() for f in frames
    ]))

    # Motion intensity
    motion = compute_motion_intensity(frames)

    # Classification
    scene_type = "unknown"
    if face_info["has_face"] and face_info["face_size_ratio"] > 0.15:
        scene_type = "close_up"
    elif face_info["has_face"] and face_info["face_size_ratio"] > 0.03:
        scene_type = "performance"
    elif not face_info["has_face"] and brightness < 60:
        scene_type = "b_roll_low_light"
    elif not face_info["has_face"] and motion < 5:
        scene_type = "b_roll_static"
    elif not face_info["has_face"] and motion > 15:
        scene_type = "b_roll_dynamic"
    else:
        scene_type = "b_roll"

    return {
        "path": video_path,
        "name": os.path.basename(video_path),
        "duration": meta.get("duration", 0),
        "scene_type": scene_type,
        "has_face": face_info["has_face"],
        "face_size_ratio": face_info["face_size_ratio"],
        "brightness": brightness,
        "motion_intensity": motion,
        "codec": meta.get("codec", "unknown"),
        "profile": meta.get("profile", "unknown"),
        "width": meta.get("width", 0),
        "height": meta.get("height", 0),
        "fps": meta.get("fps", 30),
    }