"""
FlagshipEditor — Beat Analysis Engine
Uses librosa for advanced beat detection, section segmentation, and music analysis.
"""

import os
import sys
import json
import time
import hashlib
import sqlite3
from pathlib import Path
from typing import Dict, List, Any, Optional

import librosa
import numpy as np
from scipy.signal import butter, sosfilt, sosfiltfilt
from scipy.sparse import diags

# Beat analysis cache (same dir as clip analysis cache)
_BEAT_CACHE_DIR = Path(
    os.environ.get(
        "FLAGSHIPEDITOR_CACHE",
        str(Path(os.environ.get("LOCALAPPDATA", "/tmp")) / "ake-studio" / "FlagshipEditor" / "cache")
        if sys.platform == "win32"
        else str(Path(os.environ.get("HOME", "/tmp")) / "Library" / "Caches" / "FlagshipEditor" / "cache"),
    )
)
_BEAT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_BEAT_CACHE_DB = _BEAT_CACHE_DIR / "beat_analysis.sqlite3"


def _beat_cache_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_BEAT_CACHE_DB))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS beat_cache (
            cache_key TEXT PRIMARY KEY,
            source_path TEXT NOT NULL,
            source_size INTEGER NOT NULL,
            source_mtime_ns INTEGER NOT NULL,
            result_json TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    return conn


def _beat_cache_key(audio_path: str) -> tuple:
    """Return (absolute_path, size, mtime_ns, cache_key)."""
    st = os.stat(audio_path)
    key_str = f"{st.st_size}:{st.st_mtime_ns}:{audio_path}"
    return (
        os.path.abspath(audio_path),
        st.st_size,
        st.st_mtime_ns,
        hashlib.sha256(key_str.encode()).hexdigest(),
    )


def _correct_tempo(tempo: float) -> float:
    """Correct tempo doubling/halving to stay in typical music range (60-200 BPM)."""
    if tempo < 60:
        tempo *= 2
    elif tempo > 200:
        tempo /= 2
    return round(tempo, 2)


def frequency_filter(y: np.ndarray, sr: int, cutoff: float, filter_type: str) -> np.ndarray:
    """Apply a stable Butterworth low-pass or high-pass filter."""
    sos = butter(5, cutoff, btype=filter_type, fs=sr, output="sos")
    try:
        return sosfiltfilt(sos, y)
    except ValueError:
        # Very short audio can be shorter than scipy's zero-phase padding.
        return sosfilt(sos, y)


def analyze_track(audio_path: str, progress_callback: Optional[Any] = None) -> Dict[str, Any]:
    """
    Full audio analysis: BPM, beats, downbeats, sections, energy, 808, hi-hats, key.
    Results are cached in SQLite for instant re-analysis.
    Optional progress_callback(step: str, pct: float) for UI progress reporting.
    """
    # Check cache first
    abs_path, size, mtime_ns, cache_key = _beat_cache_key(audio_path)
    try:
        with _beat_cache_connection() as conn:
            row = conn.execute(
                "SELECT result_json FROM beat_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
            if row:
                return json.loads(row[0])
    except Exception:
        pass

    def _progress(step: str, pct: float):
        if progress_callback:
            try:
                progress_callback(step, pct)
            except Exception:
                pass

    _progress("Loading audio", 0.05)
    y, sr = librosa.load(audio_path, sr=22050)

    _progress("Detecting beats", 0.15)
    # Beat tracking
    tempo_result, beats = librosa.beat.beat_track(y=y, sr=sr)
    tempo = float(np.asarray(tempo_result).reshape(-1)[0])
    tempo = _correct_tempo(tempo)
    beat_times = librosa.frames_to_time(beats, sr=sr)

    # Downbeat detection (estimate: every 4th beat in 4/4)
    downbeats = [beat_times[i] for i in range(0, len(beat_times), 4)]

    _progress("Detecting sections", 0.30)
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
        n_sections = min(6, max(1, int(len(beat_times) / 16)), mfcc_scaled.shape[0])
        if n_sections < 2:
            raise ValueError("Audio is too short for clustered segmentation")
        frame_count = mfcc_scaled.shape[0]
        connectivity = diags(
            [np.ones(frame_count - 1), np.ones(frame_count - 1)],
            offsets=[-1, 1],
            shape=(frame_count, frame_count),
            format="csr",
        )
        clusterer = AgglomerativeClustering(
            n_clusters=n_sections,
            connectivity=connectivity,
        )
        labels = clusterer.fit_predict(mfcc_scaled)

        # Convert frame labels to section boundaries
        sections = labels_to_sections(labels, frame_times, y, sr)
    except (ImportError, ValueError):
        # Fallback: simple energy-based segmentation
        sections = simple_segmentation(y, sr, beat_times, tempo)

    _progress("Computing energy", 0.60)
    # Energy curve (RMS)
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
    rms_times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=512)

    _progress("Detecting 808s", 0.70)
    # 808 detection (sub-bass onsets < 80Hz)
    bass_filtered = frequency_filter(y, sr, 80, "lowpass")
    bass_onsets = librosa.onset.onset_detect(
        y=bass_filtered, sr=sr, units="time", hop_length=512
    )

    _progress("Detecting hi-hats", 0.80)
    # Hi-hat detection (high frequency onsets > 8kHz)
    hihat_filtered = frequency_filter(y, sr, 8000, "highpass")
    hihat_onsets = librosa.onset.onset_detect(
        y=hihat_filtered, sr=sr, units="time", hop_length=512
    )

    _progress("Detecting key", 0.90)
    # Key detection
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    key, mode = estimate_key(chroma)

    _progress("Finalizing", 0.95)
    result = {
        "tempo": tempo,
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

    # Save to cache
    try:
        with _beat_cache_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO beat_cache (cache_key, source_path, source_size, source_mtime_ns, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (cache_key, abs_path, size, mtime_ns, json.dumps(result), time.time()),
            )
            conn.commit()
    except Exception:
        pass

    _progress("Done", 1.0)
    return result


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

    return assign_section_types(sections, y, sr)


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
