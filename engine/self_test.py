#!/usr/bin/env python3
"""Offline packaged-runtime media gate used by the Windows installer."""

from pathlib import Path
import sys

# Ensure the engine directory is on sys.path so sibling modules import correctly
_engine_dir = str(Path(__file__).resolve().parent)
if _engine_dir not in sys.path:
    sys.path.insert(0, _engine_dir)

from clip_analysis import classify_clip


def main() -> None:
    fixtures = Path(__file__).resolve().parent / "fixtures"
    expected = {
        "prores-422-standard.mov": "standard",
        "prores-422-hq.mov": "hq",
    }
    for filename, profile in expected.items():
        source = fixtures / filename
        if not source.is_file():
            raise RuntimeError(f"Packaged media fixture is missing: {filename}")
        result = classify_clip(str(source))
        if result.get("codec") != "prores" or result.get("decoder") != "ffmpeg" or not result.get("usable"):
            raise RuntimeError(f"Packaged ProRes decode failed for {filename}: {result}")
        if profile not in str(result.get("profile", "")).lower():
            raise RuntimeError(f"Unexpected ProRes profile for {filename}: {result.get('profile')}")
    print("Packaged ProRes 422 Standard/HQ self-test passed.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"FlagshipEditor media self-test failed: {error}", file=sys.stderr)
        raise SystemExit(1)
