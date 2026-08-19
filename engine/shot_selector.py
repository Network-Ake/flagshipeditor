# engine/shot_selector.py
# AI Shot Selection Engine — scores clips and picks the best one for each beat cut
# Inspired by MVX AI "Taste Engine" — goes beyond classification to actual shot selection

import cv2
import numpy as np
from typing import List, Dict, Optional


def score_clip(clip_info: dict, prev_clip_info: Optional[dict] = None) -> dict:
    """Score a single clip on 6 criteria, return composite score."""
    scores = {}
    frames = clip_info.get('frames', [])
    
    # 1. Composition — rule of thirds, center of interest
    scores['composition'] = analyze_composition(frames) if frames else 50
    
    # 2. Energy — motion + brightness + saturation
    scores['energy'] = analyze_energy(frames) if frames else 50
    
    # 3. Variety — visual distance from previous clip
    if prev_clip_info and 'histogram' in clip_info and 'histogram' in prev_clip_info:
        scores['variety'] = 100 - histogram_correlation(
            clip_info['histogram'], prev_clip_info['histogram']
        )
    else:
        scores['variety'] = 80
    
    # 4. Sharpness — Laplacian variance
    scores['sharpness'] = min(100, laplacian_variance(frames) / 100) if frames else 50
    
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
        'scene_type': clip_info.get('scene_type', 'unknown')
    }


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
                result['composite'] -= 15
            
            scored.append(result)
        
        scored.sort(key=lambda x: x['composite'], reverse=True)
        best = scored[0] if scored else {
            'composite': 0, 'clip_path': '', 'clip_name': '', 'scene_type': 'unknown'
        }
        best['beat_time'] = beat_time
        best['section_type'] = section_type
        best['alternatives'] = [
            {'clip_path': s['clip_path'], 'clip_name': s['clip_name'], 'score': s['composite']}
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


def histogram_correlation(h1, h2):
    """Visual similarity between two clips (0=identical, 100=totally different)."""
    try:
        corr = cv2.compareHist(h1, h2, cv2.HISTCMP_CORREL)
        return max(0, min(100, (1 - corr) * 100))
    except Exception:
        return 50


def face_quality_score(clip_info):
    """Face detection confidence + size + centering."""
    face_ratio = clip_info.get('face_size_ratio', 0)
    size_score = 100 - abs(face_ratio - 0.15) * 500
    return max(0, min(100, size_score))


def filter_clips_for_section(clips, section_type, style_config):
    """Filter clips compatible with a section type."""
    section_map = {
        'intro': ['b_roll_exterior', 'b_roll_studio', 'wide_shot', 'b_roll_low_light', 'b_roll_static'],
        'verse': ['performance_lip_sync', 'close_up', 'performance'],
        'chorus': ['performance_lip_sync', 'close_up', 'crowd', 'b_roll_dynamic', 'high_energy'],
        'drop': ['b_roll_dynamic', 'close_up', 'performance_lip_sync', 'high_energy'],
        'bridge': ['b_roll_exterior', 'wide_shot', 'b_roll_low_light', 'b_roll_static'],
        'outro': ['b_roll_exterior', 'wide_shot', 'performance', 'b_roll_static']
    }
    compatible_types = section_map.get(section_type, ['performance', 'b_roll_dynamic'])
    return [c for c in clips if c.get('scene_type', 'unknown') in compatible_types or c.get('scene_type') == 'unknown']