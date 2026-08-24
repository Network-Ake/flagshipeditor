#!/usr/bin/env python3
"""Deterministic engine contract checks that do not require media fixtures."""

from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from clip_analysis import compute_visual_scores, parse_frame_rate, resize_for_analysis
from shot_selector import filter_clips_for_section, histogram_distance, score_clip


def main() -> None:
    assert parse_frame_rate("30000/1001") == 30000 / 1001
    assert parse_frame_rate("0/0") == 30.0
    assert parse_frame_rate("not-a-rate") == 30.0
    assert parse_frame_rate(None) == 30.0
    resized = resize_for_analysis(np.zeros((2160, 3840, 3), dtype=np.uint8), 640)
    assert max(resized.shape[:2]) == 640
    visual = compute_visual_scores(
        [
            np.zeros((90, 160, 3), dtype=np.uint8),
            np.full((90, 160, 3), 180, dtype=np.uint8),
        ],
        motion=4.0,
    )
    assert len(visual["histogram"]) == 32
    assert abs(sum(visual["histogram"]) - 1.0) < 1e-9
    for key in ("composition_score", "energy_score", "sharpness_score"):
        assert 0.0 <= visual[key] <= 100.0
    assert histogram_distance([1, 0], [1, 0]) == 0.0
    assert histogram_distance([1, 0], [0, 1]) == 100.0
    strong = score_clip({
        "path": "strong.mov",
        "name": "strong.mov",
        "composition_score": 90,
        "energy_score": 85,
        "sharpness_score": 95,
        "motion_intensity": 2,
        "has_face": True,
        "face_size_ratio": 0.15,
        "histogram": [1, 0],
    })
    weak = score_clip({
        "path": "weak.mov",
        "name": "weak.mov",
        "composition_score": 15,
        "energy_score": 20,
        "sharpness_score": 10,
        "motion_intensity": 40,
        "has_face": False,
        "histogram": [0, 1],
    })
    assert strong["composite"] > weak["composite"]
    produced_types = [
        {"scene_type": scene_type}
        for scene_type in (
            "close_up", "performance", "b_roll_low_light",
            "b_roll_static", "b_roll_dynamic", "b_roll",
        )
    ]
    for section_type in ("intro", "verse", "chorus", "drop", "bridge", "outro"):
        assert filter_clips_for_section(produced_types, section_type, {})
    assert not filter_clips_for_section([{"scene_type": "unknown", "usable": False}], "verse", {})
    print("Engine contract tests passed (metadata, scoring, variety, scene alignment).")


if __name__ == "__main__":
    main()
