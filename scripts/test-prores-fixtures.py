#!/usr/bin/env python3
"""Generate tiny Standard/HQ ProRes files and validate the real decoder path."""

from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from clip_analysis import classify_clip, classify_clip_cached, extract_frames_ffmpeg, get_video_metadata


def make_fixture(ffmpeg: str, destination: Path, profile: int) -> None:
    subprocess.run(
        [
            ffmpeg, "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24000/1001",
            "-t", "1.2", "-c:v", "prores_ks", "-profile:v", str(profile), "-pix_fmt", "yuv422p10le",
            "-y", str(destination),
        ],
        check=True,
        timeout=60,
    )


def main() -> None:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise SystemExit("FFmpeg and FFprobe are required for the ProRes release gate")
    os.environ["FLAGSHIPEDITOR_FFMPEG"] = ffmpeg
    os.environ["FLAGSHIPEDITOR_FFPROBE"] = ffprobe
    with tempfile.TemporaryDirectory() as directory:
        for label, profile in (("standard", 2), ("hq", 3)):
            fixture = Path(directory) / f"prores-422-{label}.mov"
            make_fixture(ffmpeg, fixture, profile)
            metadata = get_video_metadata(str(fixture))
            assert metadata["codec"] == "prores"
            assert metadata["width"] == 320 and metadata["height"] == 180
            frames = extract_frames_ffmpeg(str(fixture), metadata["duration"], 3)
            assert len(frames) == 3
            assert max(frames[0].shape[:2]) <= 640
            result = classify_clip(str(fixture))
            assert result["usable"] is True
            assert result["decoder"] == "ffmpeg"
            assert result["codec"] == "prores"
            assert result["histogram"] and abs(sum(result["histogram"]) - 1.0) < 1e-6
            assert result["thumbnail_id"]
            first_cached_result, first_hit = classify_clip_cached(str(fixture))
            second_cached_result, second_hit = classify_clip_cached(str(fixture))
            assert first_cached_result["analysis_schema"] == second_cached_result["analysis_schema"]
            assert first_hit is False and second_hit is True
    print("ProRes fixture tests passed (422 Standard + 422 HQ through explicit FFmpeg sampling).")


if __name__ == "__main__":
    main()
