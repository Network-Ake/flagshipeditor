#!/usr/bin/env python3
"""Validate the committed ProRes fixtures and the real decoder path.

Two things are checked here, and they fail for different reasons:

* the *committed* fixtures under ``engine/fixtures`` — the media the Windows
  installer's ``self_test.py`` gate decodes before it commits an install — are
  intact, are the profiles they claim to be, and survive the engine's own
  FFmpeg resolution;
* freshly *generated* ProRes still decodes, so the recipe in
  ``scripts/generate-prores-fixtures.mjs`` keeps working on a new FFmpeg.

The negative cases matter as much as the positive ones: a missing or corrupt
fixture must stop the installer with a message that names the file, not sail
through because nothing looked at the bytes.
"""

from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "engine"
FIXTURE_DIR = ENGINE / "fixtures"
MANIFEST = FIXTURE_DIR / "manifest.json"

sys.path.insert(0, str(ENGINE))

from clip_analysis import classify_clip, classify_clip_cached, extract_frames_ffmpeg, get_video_metadata
from media_tools import FFMPEG, FFPROBE


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


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


def check_committed_fixtures() -> None:
    """The media that ships must be present, intact and correctly typed.

    ``self_test.py`` only substring-matches the profile name, so the exact
    ``Standard``/``HQ`` strings FFprobe returns are asserted here — if a future
    FFmpeg renames them the installer gate would start failing in the field
    rather than in CI.
    """
    assert MANIFEST.is_file(), f"fixture manifest is missing: {MANIFEST}"
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["fixtures"], "fixture manifest lists no fixtures"

    expected_tokens = {"prores-422-standard.mov": "standard", "prores-422-hq.mov": "hq"}
    seen = set()
    for entry in manifest["fixtures"]:
        fixture = FIXTURE_DIR / entry["file"]
        assert fixture.is_file(), f"committed fixture is missing: {entry['file']}"
        seen.add(entry["file"])

        # Integrity: catches truncation, a mangled checkout and a stale manifest.
        actual_bytes = fixture.stat().st_size
        assert actual_bytes == entry["bytes"], (
            f"{entry['file']}: {actual_bytes} bytes on disk, manifest says {entry['bytes']}"
        )
        actual_hash = sha256(fixture)
        assert actual_hash == entry["sha256"], (
            f"{entry['file']}: sha256 {actual_hash} does not match manifest {entry['sha256']}"
        )

        # Codec identity through the same FFprobe the engine resolved.
        metadata = get_video_metadata(str(fixture))
        assert metadata["codec"] == "prores", f"{entry['file']}: codec {metadata['codec']}"
        assert metadata["width"] == entry["width"] and metadata["height"] == entry["height"]
        assert metadata["profile"] == entry["profile"], (
            f"{entry['file']}: FFprobe says {metadata['profile']!r}, manifest says {entry['profile']!r}"
        )
        token = expected_tokens[entry["file"]]
        assert token in metadata["profile"].lower(), (
            f"{entry['file']}: self_test.py looks for {token!r} in profile {metadata['profile']!r}"
        )

        # Decode: real frames out of the real binary, not just a container read.
        frames = extract_frames_ffmpeg(str(fixture), metadata["duration"], 3)
        assert len(frames) == 3, f"{entry['file']}: extracted {len(frames)} frames, expected 3"

        result = classify_clip(str(fixture))
        assert result["usable"] is True, f"{entry['file']}: classified unusable — {result}"
        assert result["decoder"] == "ffmpeg", f"{entry['file']}: decoder {result['decoder']}"
        assert result["codec"] == "prores"
        assert result["histogram"] and abs(sum(result["histogram"]) - 1.0) < 1e-6

    assert seen == set(expected_tokens), f"manifest covers {sorted(seen)}, expected {sorted(expected_tokens)}"


def run_isolated_self_test(fixtures_dir: Path) -> subprocess.CompletedProcess:
    """Run ``self_test.py`` against a throwaway copy of the engine.

    ``self_test.py`` resolves its fixture directory from its own location, and
    ``Path.resolve()`` follows symlinks, so the engine modules have to be really
    copied. Only the top-level ``*.py`` files are — the virtualenv is supplied by
    the interpreter running this test. The committed fixtures are never touched.
    """
    isolated = fixtures_dir.parent
    for module in sorted(ENGINE.glob("*.py")):
        shutil.copy2(module, isolated / module.name)
    return subprocess.run(
        [sys.executable, str(isolated / "self_test.py")],
        capture_output=True, text=True, timeout=180,
    )


def check_missing_fixture_fails_clearly() -> None:
    with tempfile.TemporaryDirectory() as directory:
        fixtures = Path(directory) / "fixtures"
        fixtures.mkdir()
        shutil.copy2(FIXTURE_DIR / "prores-422-hq.mov", fixtures / "prores-422-hq.mov")
        result = run_isolated_self_test(fixtures)
        assert result.returncode != 0, "a missing fixture must fail the self-test"
        assert "prores-422-standard.mov" in result.stderr, (
            f"the failure must name the missing fixture, got: {result.stderr.strip()!r}"
        )
        assert "missing" in result.stderr.lower()


def check_corrupt_fixture_fails_clearly() -> None:
    with tempfile.TemporaryDirectory() as directory:
        fixtures = Path(directory) / "fixtures"
        fixtures.mkdir()
        shutil.copy2(FIXTURE_DIR / "prores-422-hq.mov", fixtures / "prores-422-hq.mov")
        # A file that exists, is the right size and is not decodable media.
        original = (FIXTURE_DIR / "prores-422-standard.mov").stat().st_size
        (fixtures / "prores-422-standard.mov").write_bytes(b"\x00" * original)
        result = run_isolated_self_test(fixtures)
        assert result.returncode != 0, "a corrupt fixture must fail the self-test"
        assert "prores-422-standard.mov" in result.stderr, (
            f"the failure must name the corrupt fixture, got: {result.stderr.strip()!r}"
        )


def check_generated_fixtures_still_decode() -> None:
    ffmpeg = FFMPEG.path
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


def main() -> None:
    if not FFMPEG.available or not FFPROBE.available:
        raise SystemExit(
            "FFmpeg and FFprobe are required for the ProRes release gate: "
            f"ffmpeg={FFMPEG.path} ({FFMPEG.detail}), ffprobe={FFPROBE.path} ({FFPROBE.detail})"
        )
    # Child processes must shell out to the same binaries this process resolved.
    os.environ["FLAGSHIPEDITOR_FFMPEG"] = FFMPEG.path
    os.environ["FLAGSHIPEDITOR_FFPROBE"] = FFPROBE.path

    check_committed_fixtures()
    check_missing_fixture_fails_clearly()
    check_corrupt_fixture_fails_clearly()
    check_generated_fixtures_still_decode()
    print(
        "ProRes fixture tests passed (committed 422 Standard + HQ verified against the manifest, "
        f"missing and corrupt fixtures rejected, fresh encodes decode through {Path(FFMPEG.path).name})."
    )


if __name__ == "__main__":
    main()
