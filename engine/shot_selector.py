# engine/shot_selector.py
# AI Shot Selection Engine — scores clips and picks the best one for each beat cut
# Inspired by MVX AI "Taste Engine" — goes beyond classification to actual shot selection

import cv2
import numpy as np
from typing import List, Dict, Optional


def score_clip(clip_info: dict, prev_clip_info: Optional[dict] = None) -> dict:
    """Score a single clip on 6 criteria, return composite score."""
    scores = {}
    scores['composition'] = bounded_score(clip_info.get('composition_score'), 50)
    scores['energy'] = bounded_score(clip_info.get('energy_score'), 50)
    
    # 3. Variety — visual distance from previous clip
    if prev_clip_info and clip_info.get('histogram') and prev_clip_info.get('histogram'):
        scores['variety'] = histogram_distance(
            clip_info['histogram'], prev_clip_info['histogram']
        )
    else:
        scores['variety'] = 80
    
    scores['sharpness'] = bounded_score(clip_info.get('sharpness_score'), 50)
    
    # 5. Stability — penalize shaky clips
    scores['stability'] = 100 - min(100, clip_info.get('motion_intensity', 0) * 2)
    
    # 6. Face quality — detection confidence + size + centering
    if clip_info.get('has_face'):
        scores['face_quality'] = face_quality_score(clip_info)
    else:
        scores['face_quality'] = 50  # Neutral for B-roll
    
    # Composite weighted score
    composite = (
        scores['composition'] * 0.25 +
        scores['energy'] * 0.20 +
        scores['variety'] * 0.20 +
        scores['sharpness'] * 0.15 +
        scores['stability'] * 0.10 +
        scores['face_quality'] * 0.10
    )
    
    return {
        'scores': scores,
        'composite': composite,
        'clip_path': clip_info.get('path', ''),
        'clip_name': clip_info.get('name', ''),
        'thumbnail_id': clip_info.get('thumbnail_id', ''),
        'scene_type': clip_info.get('scene_type', 'unknown')
    }


def bounded_score(value, default=50.0):
    """Coerce a score to the public 0..100 contract."""
    try:
        numeric = float(value)
        if not np.isfinite(numeric):
            return float(default)
        return max(0.0, min(100.0, numeric))
    except (TypeError, ValueError):
        return float(default)


def histogram_distance(first, second):
    """Return normalized histogram distance: 0 identical, 100 maximally different."""
    try:
        left = np.asarray(first, dtype=np.float64).reshape(-1)
        right = np.asarray(second, dtype=np.float64).reshape(-1)
        if left.size == 0 or left.size != right.size:
            return 50.0
        left_total = float(left.sum())
        right_total = float(right.sum())
        if left_total <= 0 or right_total <= 0:
            return 50.0
        left /= left_total
        right /= right_total
        return max(0.0, min(100.0, float(np.abs(left - right).sum()) * 50.0))
    except (TypeError, ValueError):
        return 50.0


def select_best_clips(clips: List[dict], beat_times: list,
                      section_type: str, style_config: dict,
                      used_recently: Optional[list] = None) -> List[dict]:
    """
    For each beat cut point, select the best clip.
    Returns list of {beat_time, clip_path, score, scores, alternatives} sorted by beat_time.
    """
    used_recently = used_recently if used_recently is not None else []
    selections = []
    prev_clip = None
    
    compatible = filter_clips_for_section(clips, section_type, style_config)
    if not compatible:
        compatible = clips  # fallback: use all clips
    
    for beat_time in beat_times:
        scored = []
        for clip in compatible:
            result = score_clip(clip, prev_clip)
            
            # Penalize recently used clips
            if clip.get('path') in used_recently[-4:]:
                result['composite'] = max(0.0, result['composite'] - 15.0)
            
            scored.append(result)
        
        scored.sort(key=lambda x: x['composite'], reverse=True)
        best = scored[0] if scored else {
            'composite': 0, 'clip_path': '', 'clip_name': '',
            'thumbnail_id': '', 'scene_type': 'unknown'
        }
        best['beat_time'] = beat_time
        best['section_type'] = section_type
        best['alternatives'] = [
            {
                'clip_path': s['clip_path'],
                'clip_name': s['clip_name'],
                'score': s['composite'],
                'thumbnail_id': s.get('thumbnail_id', '')
            }
            for s in scored[1:4]  # Top 3 alternatives for Review Mode
        ]
        
        selections.append(best)
        prev_clip = next((c for c in compatible if c.get('path') == best['clip_path']), None)
        if best['clip_path']:
            used_recently.append(best['clip_path'])
    
    return selections


def analyze_composition(frames):
    """Rule of thirds + center of interest detection."""
    scores = []
    for frame in frames:
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        thirds = [
            gray[:h//3, :], gray[h//3:2*h//3, :], gray[2*h//3:, :],
            gray[:, :w//3], gray[:, w//3:2*w//3], gray[:, 2*w//3:]
        ]
        edge_density = [np.mean(cv2.Canny(t, 50, 150)) for t in thirds]
        balance = 100 - (np.std(edge_density) / max(np.mean(edge_density), 1)) * 50
        scores.append(max(0, min(100, balance)))
    return float(np.mean(scores)) if scores else 50


def analyze_energy(frames):
    """Motion intensity + brightness + saturation."""
    motion = []
    brightness = []
    saturation = []
    for i, frame in enumerate(frames):
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        brightness.append(np.mean(hsv[:,:,2]))
        saturation.append(np.mean(hsv[:,:,1]))
        if i > 0:
            prev_gray = cv2.cvtColor(frames[i-1], cv2.COLOR_BGR2GRAY)
            curr_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            flow = cv2.calcOpticalFlowFarneback(
                prev_gray, curr_gray, None, 0.5, 3, 15, 3, 5, 1.2, 0
            )
            motion.append(np.mean(np.sqrt(flow[:,:,0]**2 + flow[:,:,1]**2)))
    
    energy = (
        (np.mean(motion) * 3 if motion else 30) +
        (np.mean(brightness) / 2.55 if brightness else 50) +
        (np.mean(saturation) / 2.55 if saturation else 50)
    ) / 3
    return max(0, min(100, float(energy)))


def laplacian_variance(frames):
    """Sharpness via Laplacian variance."""
    variances = []
    for frame in frames:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        variances.append(cv2.Laplacian(gray, cv2.CV_64F).var())
    return float(np.mean(variances)) if variances else 0


def face_quality_score(clip_info):
    """Face detection confidence + size + centering."""
    face_ratio = clip_info.get('face_size_ratio', 0)
    size_score = 100 - abs(face_ratio - 0.15) * 500
    return max(0, min(100, size_score))


def filter_clips_for_section(clips, section_type, style_config):
    """Filter clips compatible with a section type."""
    usable_clips = [clip for clip in clips if clip.get('usable', True) and clip.get('scene_type') != 'unknown']
    section_map = {
        'intro': ['b_roll_static', 'b_roll_low_light', 'b_roll'],
        'verse': ['performance', 'close_up'],
        'chorus': ['close_up', 'performance', 'b_roll_dynamic'],
        'drop': ['b_roll_dynamic', 'close_up', 'performance'],
        'bridge': ['b_roll_static', 'b_roll_low_light', 'b_roll'],
        'outro': ['b_roll_static', 'b_roll', 'performance']
    }
    compatible_types = section_map.get(section_type, ['performance', 'b_roll_dynamic'])
    return [clip for clip in usable_clips if clip.get('scene_type') in compatible_types]
