"""
FlagshipEditor — Beat Analysis Engine
Uses librosa for advanced beat detection, section segmentation, and music analysis.
"""

import librosa
import numpy as np
from typing import Dict, List, Any


def analyze_track(audio_path: str) -> Dict[str, Any]:
    """
    Full audio analysis: BPM, beats, downbeats, sections, energy, 808, hi-hats, key.
    """
    y, sr = librosa.load(audio_path, sr=22050)

    # Beat tracking
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr)
    beat_times = librosa.frames_to_time(beats, sr=sr)

    # Downbeat detection (estimate: every 4th beat in 4/4)
    downbeats = [beat_times[i] for i in range(0, len(beat_times), 4)]

    # Section detection via structural segmentation
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
    try:
        # Agglomerative clustering for structural segmentation
        from sklearn.cluster import AgglomerativeClustering
        from sklearn.preprocessing import StandardScaler

        # Segment using MFCC similarity
        frame_times = librosa.frames_to_time(np.arange(mfcc.shape[1]), sr=sr)
        scaler = StandardScaler()
        mfcc_scaled = scaler.fit_transform(mfcc.T)

        # Cluster into sections
        n_sections = min(6, max(3, int(len(beat_times) / 16)))
        clusterer = AgglomerativeClustering(n_clusters=n_sections)
        labels = clusterer.fit_predict(mfcc_scaled)

        # Convert frame labels to section boundaries
        sections = labels_to_sections(labels, frame_times, y, sr)
    except ImportError:
        # Fallback: simple energy-based segmentation
        sections = simple_segmentation(y, sr, beat_times, tempo)

    # Energy curve (RMS)
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
    rms_times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=512)

    # 808 detection (sub-bass onsets < 80Hz)
    bass_filtered = librosa.effects.low_pass(y, sr, cutoff=80)
    bass_onsets = librosa.onset.onset_detect(
        y=bass_filtered, sr=sr, units="time", hop_length=512
    )

    # Hi-hat detection (high frequency onsets > 8kHz)
    hihat_filtered = librosa.effects.high_pass(y, sr, cutoff=8000)
    hihat_onsets = librosa.onset.onset_detect(
        y=hihat_filtered, sr=sr, units="time", hop_length=512
    )

    # Key detection
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    key, mode = estimate_key(chroma)

    return {
        "tempo": float(tempo),
        "beats": beat_times.tolist(),
        "downbeats": downbeats,
        "sections": sections,
        "energy": rms.tolist(),
        "bass_onsets": bass_onsets.tolist(),
        "hihat_onsets": hihat_onsets.tolist(),
        "key": key,
        "mode": mode,
        "duration": float(len(y) / sr),
    }


def labels_to_sections(labels, frame_times, y, sr):
    """Convert frame-level cluster labels to section objects."""
    sections = []
    current_label = labels[0]
    current_start = 0.0

    for i in range(1, len(labels)):
        if labels[i] != current_label:
            section_type = classify_section_type(y, sr, current_start, frame_times[i])
            sections.append({
                "type": section_type,
                "start": float(current_start),
                "end": float(frame_times[i]),
            })
            current_label = labels[i]
            current_start = float(frame_times[i])

    # Last section
    duration = len(y) / sr
    section_type = classify_section_type(y, sr, current_start, duration)
    sections.append({
        "type": section_type,
        "start": float(current_start),
        "end": float(duration),
    })

    # Post-process: assign intro/verse/chorus/drop/outro based on energy
    sections = assign_section_types(sections, y, sr)

    return sections


def classify_section_type(y, sr, start, end):
    """Classify a section based on its audio characteristics."""
    segment = y[int(start * sr):int(end * sr)]
    if len(segment) == 0:
        return "verse"

    rms = np.sqrt(np.mean(segment ** 2))
    spectral_centroid = np.mean(librosa.feature.spectral_centroid(y=segment, sr=sr))

    if rms < 0.01:
        return "intro"
    elif rms > 0.1 and spectral_centroid > 3000:
        return "drop"
    elif rms > 0.05:
        return "chorus"
    else:
        return "verse"


def assign_section_types(sections, y, sr):
    """Assign meaningful section types based on position and energy."""
    if not sections:
        return sections

    # First section = intro, last = outro
    sections[0]["type"] = "intro"
    sections[-1]["type"] = "outro"

    # Find the highest energy section = drop
    max_energy = 0
    drop_idx = -1
    for i, sec in enumerate(sections[1:-1], 1):
        segment = y[int(sec["start"] * sr):int(sec["end"] * sr)]
        if len(segment) > 0:
            rms = np.sqrt(np.mean(segment ** 2))
            if rms > max_energy:
                max_energy = rms
                drop_idx = i

    if drop_idx > 0:
        sections[drop_idx]["type"] = "drop"

    # Alternate verse/chorus for remaining sections
    is_chorus = False
    for i in range(1, len(sections) - 1):
        if i == drop_idx:
            continue
        sections[i]["type"] = "chorus" if is_chorus else "verse"
        is_chorus = not is_chorus

    return sections


def simple_segmentation(y, sr, beat_times, tempo):
    """Fallback segmentation when sklearn is not available."""
    duration = len(y) / sr
    n_sections = max(3, min(6, int(duration / 30)))

    section_length = duration / n_sections
    sections = []

    for i in range(n_sections):
        start = i * section_length
        end = (i + 1) * section_length if i < n_sections - 1 else duration
        section_type = classify_section_type(y, sr, start, end)
        sections.append({"type": section_type, "start": float(start), "end": float(end)})

    sections[0]["type"] = "intro"
    sections[-1]["type"] = "outro"
    return sections


def estimate_key(chroma):
    """Estimate musical key from chroma features."""
    # Major and minor key profiles (Krumhansl-Schmuckler)
    major_profile = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
    minor_profile = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

    # Average chroma
    chroma_mean = np.mean(chroma, axis=1)

    # Correlate with each key
    best_corr = -1
    best_key = "C"
    best_mode = "major"

    note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

    for i in range(12):
        # Rotate profiles
        major_rot = np.roll(major_profile, i)
        minor_rot = np.roll(minor_profile, i)

        corr_major = np.corrcoef(chroma_mean, major_rot)[0, 1]
        corr_minor = np.corrcoef(chroma_mean, minor_rot)[0, 1]

        if corr_major > best_corr:
            best_corr = corr_major
            best_key = note_names[i]
            best_mode = "major"

        if corr_minor > best_corr:
            best_corr = corr_minor
            best_key = note_names[i]
            best_mode = "minor"

    return best_key, best_mode