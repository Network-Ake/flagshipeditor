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
from typing import Dict, List, Any, Optional, Sequence

import librosa
import numpy as np
import scipy
from scipy.signal import butter, sosfilt, sosfiltfilt
from scipy.sparse import diags

# Bumping this invalidates every cached beat analysis. It must change whenever
# the extracted signals themselves change, otherwise a project re-opened after
# an engine upgrade silently replays evidence produced by the previous
# algorithm. Old rows keep their old key and are simply never read again.
BEAT_ANALYSIS_SCHEMA_VERSION = "5"

# Everything the analysis is measured at. These are part of the cache identity,
# so changing one of them retires the rows produced by the previous setting
# instead of replaying them under the new name.
ANALYSIS_SAMPLE_RATE = 22050
ENERGY_FRAME_LENGTH = 2048
ENERGY_HOP_LENGTH = 512

# Percussive isolation settings. HPSS is run on the STFT once and both the
# percussive waveform (beat tracking) and the percussive magnitude spectrogram
# (band-limited onset detection) are taken from that single decomposition.
HPSS_N_FFT = 2048
HPSS_HOP_LENGTH = 512
# Separation cost and peak memory both grow linearly with track length, so a
# pathological input falls back to the full mix rather than exhausting a 8 GB
# Windows machine.
HPSS_MAX_SECONDS = max(30.0, float(os.environ.get("FLAGSHIPEDITOR_HPSS_MAX_SECONDS", "600")))

# Sub-bass band used for 808/kick attacks, and the air band used for hi-hats.
BASS_BAND_HZ = (30.0, 120.0)
HIHAT_BAND_HZ = 8000.0

# Two bass attacks closer together than this cannot become two separate cuts
# (``shot_selector.MIN_CUT_SECONDS`` is 0.15s), so merging them here removes
# duplicate evidence without ever discarding a usable edit.
BASS_MIN_SPACING_SECONDS = 0.116

# Beats per bar assumed when naming downbeats. The engine measures *which* beat
# of the bar carries the accent; it does not measure the meter itself, and every
# downbeat label says so.
DOWNBEAT_METER = 4
# How far a bass attack may sit from a beat and still count as landing on it.
# Bounded by a quarter of the beat period so a slow track cannot swallow a
# genuinely syncopated hit.
ACCENT_TOLERANCE_SECONDS = 0.12
# Confidence attached to a section label that comes from its position in the
# track rather than from what was measured inside it.
POSITIONAL_LABEL_CONFIDENCE = 0.3

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


_CODE_HASH_CACHE: Dict[str, str] = {}


def _module_code_hash() -> str:
    """SHA-256 of this file, so an algorithm change cannot reuse old cache rows.

    The schema version only moves when someone remembers to move it. The source
    hash moves whenever the code that produced a cached number changes, which is
    the property the cache actually needs. Read once and memoised; an
    unreadable source falls back to the schema version rather than failing an
    analysis over a cache detail.
    """
    cached = _CODE_HASH_CACHE.get("value")
    if cached is not None:
        return cached
    try:
        digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except (OSError, NameError):
        digest = f"unhashable:{BEAT_ANALYSIS_SCHEMA_VERSION}"
    _CODE_HASH_CACHE["value"] = digest
    return digest


def _dependency_versions() -> Dict[str, str]:
    """Versions of the libraries whose output is stored in the cache."""
    return {
        "librosa": str(getattr(librosa, "__version__", "unknown")),
        "numpy": str(getattr(np, "__version__", "unknown")),
        "scipy": str(getattr(scipy, "__version__", "unknown")),
    }


def analysis_identity() -> Dict[str, Any]:
    """Return everything that can change an extracted signal.

    A cache key built from path, size and mtime answers "is this the same
    file?", which is only half the question. The other half is "was it analysed
    by this code, at these settings, on these libraries?" — and a post-upgrade
    hit that answers only the first half replays evidence the current engine
    would never produce. Every field below is read at call time so a changed
    setting is visible immediately.
    """
    return {
        "schema": BEAT_ANALYSIS_SCHEMA_VERSION,
        "code": _module_code_hash(),
        "config": {
            "sample_rate": ANALYSIS_SAMPLE_RATE,
            "energy_frame_length": ENERGY_FRAME_LENGTH,
            "energy_hop_length": ENERGY_HOP_LENGTH,
            "hpss_n_fft": HPSS_N_FFT,
            "hpss_hop_length": HPSS_HOP_LENGTH,
            "hpss_max_seconds": HPSS_MAX_SECONDS,
            "bass_band_hz": list(BASS_BAND_HZ),
            "hihat_band_hz": HIHAT_BAND_HZ,
            "bass_min_spacing_seconds": BASS_MIN_SPACING_SECONDS,
            "downbeat_meter": DOWNBEAT_METER,
            "accent_tolerance_seconds": ACCENT_TOLERANCE_SECONDS,
        },
        "dependencies": _dependency_versions(),
    }


def identity_fingerprint(identity: Dict[str, Any]) -> str:
    """Hash an identity document deterministically (sorted keys, no whitespace)."""
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _beat_cache_key(audio_path: str) -> tuple:
    """Return (absolute_path, size, mtime_ns, cache_key).

    The identity binds the source file *and* the analysis that produced the
    row: schema, source-code hash, measurement configuration and library
    versions. Rows written by any other combination keep their old key and are
    simply never read again.
    """
    absolute = os.path.abspath(audio_path)
    st = os.stat(absolute)
    key_str = ":".join(
        (
            identity_fingerprint(analysis_identity()),
            str(st.st_size),
            str(st.st_mtime_ns),
            os.path.normcase(absolute),
        )
    )
    return (
        absolute,
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


def separate_percussion(y: np.ndarray, sr: int) -> Dict[str, Any]:
    """Split the mix into percussive and harmonic evidence for rhythm analysis.

    A sustained or sidechained 808 is a *harmonic* event: it holds one pitch and
    its level breathes with the kick. Spectral-flux onset detection run on the
    full mix reads every one of those level recoveries as a new attack, which is
    why an 808-heavy drop currently produces several times more "bass onsets"
    than notes were played. Median-filter HPSS keeps the vertical (transient)
    structures and discards the horizontal (sustained) ones, so what survives in
    the sub-bass band is the attack rather than the note.

    One decomposition serves both consumers: ``signal`` is the percussive
    waveform used for beat tracking, and the band-limited magnitude slices feed
    onset detection without a second STFT. The harmonic sub-bass slice is kept
    because the note the separation deliberately removed is still real musical
    information — ``bass_sustain_intervals`` turns it back into evidence.

    Falls back to the full mix, reporting ``source="full_mix"``, when the track
    is longer than the separation budget or the decomposition fails.
    """
    duration = float(len(y)) / float(sr) if sr else 0.0
    freqs = librosa.fft_frequencies(sr=sr, n_fft=HPSS_N_FFT)
    low_band = (freqs >= BASS_BAND_HZ[0]) & (freqs <= BASS_BAND_HZ[1])
    high_band = freqs >= HIHAT_BAND_HZ

    def _bundle(magnitude: np.ndarray, signal: np.ndarray, harmonic: np.ndarray, source: str):
        return {
            "signal": signal,
            "source": source,
            "bass_band": magnitude[low_band],
            "hihat_band": magnitude[high_band],
            "harmonic_bass_band": harmonic[low_band],
            # The full harmonic magnitude, kept so vocal detection can reuse
            # this decomposition instead of paying for its own transform.
            "harmonic_full_band": harmonic,
            "hop_length": HPSS_HOP_LENGTH,
        }

    def _fallback_bundle():
        # Deliberately do not materialise a full-track STFT here. The fallback
        # path uses the legacy bounded-memory waveform filters downstream.
        return {
            "signal": y,
            "source": "full_mix",
            "bass_band": None,
            "hihat_band": None,
            "harmonic_bass_band": None,
            "harmonic_full_band": None,
            "hop_length": HPSS_HOP_LENGTH,
        }

    if duration > HPSS_MAX_SECONDS:
        return _fallback_bundle()
    try:
        spectrum = librosa.stft(y, n_fft=HPSS_N_FFT, hop_length=HPSS_HOP_LENGTH)
        harmonic_spectrum, percussive_spectrum = librosa.decompose.hpss(spectrum)
        percussive_signal = librosa.istft(
            percussive_spectrum, hop_length=HPSS_HOP_LENGTH, length=len(y)
        )
        return _bundle(
            np.abs(percussive_spectrum),
            percussive_signal,
            np.abs(harmonic_spectrum),
            "percussive",
        )
    except (ValueError, MemoryError, RuntimeError, librosa.util.exceptions.ParameterError):
        return _fallback_bundle()


def band_onsets(
    band_magnitude: np.ndarray,
    sr: int,
    hop_length: int,
    minimum_spacing: float,
    delta: float,
    smoothing: int,
) -> np.ndarray:
    """Detect attacks inside one frequency band of an already-computed magnitude.

    Slicing the spectrogram is what makes the detector band-limited; filtering
    the *waveform* and then running a full-spectrum onset detector — the previous
    approach — leaves almost every mel band empty and lets the normalisation step
    amplify the residual ripple of a sustained note into dozens of phantom
    attacks.

    ``minimum_spacing`` is a musical floor, not a smoothing constant: two attacks
    closer than that can never become two separate cuts downstream, so merging
    them removes duplicate evidence without losing an edit.
    """
    if band_magnitude.size == 0 or band_magnitude.shape[-1] < 3:
        return np.asarray([], dtype=np.float64)
    envelope = librosa.onset.onset_strength(
        S=librosa.amplitude_to_db(band_magnitude, ref=np.max),
        sr=sr,
        hop_length=hop_length,
    )
    if envelope.size < 3 or not np.any(np.isfinite(envelope)):
        return np.asarray([], dtype=np.float64)
    wait = max(1, int(round(minimum_spacing * sr / float(hop_length))))
    return librosa.onset.onset_detect(
        onset_envelope=envelope,
        sr=sr,
        units="time",
        hop_length=hop_length,
        wait=wait,
        delta=delta,
        pre_max=smoothing,
        post_max=smoothing,
        pre_avg=smoothing * 2,
        post_avg=smoothing * 2,
    )


def bass_sustain_intervals(
    harmonic_bass_band: np.ndarray,
    sr: int,
    hop_length: int,
    tempo: float,
    max_intervals: int = 512,
) -> List[Dict[str, float]]:
    """Return the spans where sub-bass is *held*, not re-struck.

    Percussive isolation is what stops a held 808 from faking attacks, and this
    is the other half of that trade: the note is still there, still the loudest
    thing in the drop, and a section full of held 808 is exactly the moment an
    editor treats as peak intensity. Without this, removing the phantom onsets
    would leave those bars looking like silence to the rest of the engine.
    """
    if harmonic_bass_band.size == 0 or harmonic_bass_band.shape[-1] < 2:
        return []
    envelope = np.asarray(harmonic_bass_band, dtype=np.float64).mean(axis=0)
    if not np.any(np.isfinite(envelope)):
        return []
    envelope = np.nan_to_num(envelope, nan=0.0, posinf=0.0, neginf=0.0)
    # A robust ceiling: a single clipped frame must not scale the whole track
    # into silence.
    ceiling = float(np.percentile(envelope, 95.0))
    if ceiling <= 0.0:
        return []
    normalized = np.clip(envelope / ceiling, 0.0, 1.0)

    period = 60.0 / float(tempo) if tempo and tempo > 0 else 0.5
    frame_seconds = float(hop_length) / float(sr)
    minimum_frames = max(2, int(round(1.5 * period / frame_seconds)))
    bridgeable_frames = max(1, int(round(0.5 * period / frame_seconds)))

    loud = normalized >= 0.35
    intervals: List[Dict[str, float]] = []
    start_index = None
    gap = 0
    for index, active in enumerate(loud):
        if active:
            if start_index is None:
                start_index = index
            gap = 0
            continue
        if start_index is None:
            continue
        gap += 1
        if gap <= bridgeable_frames:
            continue
        end_index = index - gap
        if end_index - start_index + 1 >= minimum_frames:
            intervals.append(
                {
                    "start": round(start_index * frame_seconds, 6),
                    "end": round((end_index + 1) * frame_seconds, 6),
                }
            )
        start_index = None
        gap = 0
    if start_index is not None and len(loud) - start_index >= minimum_frames:
        intervals.append(
            {
                "start": round(start_index * frame_seconds, 6),
                "end": round(len(loud) * frame_seconds, 6),
            }
        )
    return intervals[:max_intervals]


def energy_envelope(
    rms: Any,
    sample_rate: float = ANALYSIS_SAMPLE_RATE,
    hop_length: int = ENERGY_HOP_LENGTH,
    frame_length: int = ENERGY_FRAME_LENGTH,
) -> Dict[str, Any]:
    """Return the RMS curve together with the time base it was measured on.

    ``energy`` on its own is a list of numbers with no declared spacing: a
    consumer has to guess a hop length to place sample *n* in the track, and a
    guess that is wrong by one frame is wrong by 23 ms for every sample after
    it. The curve is therefore published with its own timestamps *and* the two
    parameters they were derived from, so a consumer can either read the times
    or rebuild them and check.

    ``energy_times[n]`` is exactly ``n * hop_length / sample_rate``, which is
    what ``librosa.frames_to_time`` computes for these frames.
    """
    values = np.asarray(rms, dtype=np.float64).reshape(-1)
    finite = np.isfinite(values)
    non_finite = int(values.size - int(np.count_nonzero(finite)))
    # A NaN would serialise to invalid JSON and poison every downstream mean.
    # Replacing it is only safe because the count travels with the curve.
    values = np.where(finite, values, 0.0)
    sample_rate = float(sample_rate) if sample_rate and sample_rate > 0 else float(ANALYSIS_SAMPLE_RATE)
    hop_length = int(hop_length) if hop_length and hop_length > 0 else ENERGY_HOP_LENGTH
    step = hop_length / sample_rate
    times = np.arange(values.size, dtype=np.float64) * step
    return {
        "energy": values.tolist(),
        "energy_times": [round(float(value), 6) for value in times],
        "energy_sample_rate": sample_rate,
        "energy_hop_length": hop_length,
        "energy_frame_length": int(frame_length),
        "energy_nonfinite_samples": non_finite,
    }


def label_provenance(method: str, confidence: Any, claim: str, **extra: Any) -> Dict[str, Any]:
    """Wrap one musical label in how it was derived and how sure that is.

    Every label this engine publishes is an inference. Naming the method and
    attaching a bounded confidence is what lets a consumer — or a report — tell
    a measurement from a convention instead of treating both as fact.
    """
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        value = 0.0
    if not np.isfinite(value):
        value = 0.0
    envelope = {
        "method": str(method),
        "confidence": round(max(0.0, min(1.0, value)), 4),
        "claim": str(claim),
    }
    envelope.update(extra)
    return envelope


def drop_label_provenance(sections: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Describe exactly how the published drop label was inferred."""
    candidates = [section for section in sections if section.get("type") == "drop"]
    confidence = max(
        [float(section.get("label_confidence", 0.0)) for section in candidates] or [0.0]
    )
    methods = sorted({str(section.get("label_source", "unknown")) for section in candidates})
    return label_provenance(
        "+".join(methods) if methods else "not_detected",
        confidence,
        "section labelled as the track energy peak; this is structural evidence, not genre identification",
        candidates=len(candidates),
    )


def beat_grid_regularity(beat_times: Any) -> float:
    """How steady the detected beat grid is, from 0 (erratic) to 1 (metronomic).

    Phrase boundaries are a metrical grid laid over the beats, so the grid's own
    steadiness is the ceiling on how much a phrase label can be trusted. Median
    absolute deviation is used rather than variance because a single dropped
    beat should not dominate the answer.
    """
    times = np.asarray(beat_times, dtype=np.float64).reshape(-1)
    if times.size < 3:
        return 0.0
    intervals = np.diff(times)
    intervals = intervals[np.isfinite(intervals) & (intervals > 0)]
    if intervals.size < 2:
        return 0.0
    median = float(np.median(intervals))
    if median <= 0:
        return 0.0
    deviation = float(np.median(np.abs(intervals - median))) / median
    # A 25% median deviation is already an unusable grid.
    return float(max(0.0, min(1.0, 1.0 - deviation * 4.0)))


def onset_grid_alignment(onsets: Any, beat_times: Any, tolerance: float = ACCENT_TOLERANCE_SECONDS) -> float:
    """Fraction of detected attacks that land on a beat, within ``tolerance``.

    A detector firing on the grid (or on its subdivisions) is describing the
    performance; one firing at unrelated times is describing noise or sustain.
    This is the only evidence available locally for how much the sub-bass attack
    list can be trusted, and it is reported as such rather than as certainty.
    """
    attacks = np.asarray(onsets, dtype=np.float64).reshape(-1)
    grid = np.asarray(beat_times, dtype=np.float64).reshape(-1)
    attacks = attacks[np.isfinite(attacks)]
    grid = grid[np.isfinite(grid)]
    if attacks.size == 0 or grid.size == 0:
        return 0.0
    grid = np.sort(grid)
    indices = np.clip(np.searchsorted(grid, attacks), 1, grid.size - 1)
    left = grid[indices - 1]
    right = grid[indices]
    distance = np.minimum(np.abs(attacks - left), np.abs(attacks - right))
    return float(np.count_nonzero(distance <= tolerance) / attacks.size)


def estimate_downbeat_phase(
    beat_times: Any,
    accent_times: Any = None,
    meter: int = DOWNBEAT_METER,
    tolerance: float = ACCENT_TOLERANCE_SECONDS,
) -> Dict[str, Any]:
    """Decide which beat of the bar carries the accent, instead of assuming it.

    Calling every fourth beat from index zero a downbeat is a guess about where
    the bar starts, and it is wrong whenever beat tracking latches onto the
    off-beat or the track opens with a pickup. The bar line is measurable in
    this genre: it is the phase whose beats coincide with the most sub-bass
    attacks, which is where the kick lands.

    Returns the chosen ``phase``, a ``confidence`` that is the margin over the
    runner-up phase, and the ``method`` that produced it. With no accent
    evidence the result is phase 0 at zero confidence — the old assumption,
    now labelled as one.

    The meter itself is *not* measured; ``meter`` is an assumption and travels
    with the answer.
    """
    times = np.asarray(beat_times, dtype=np.float64).reshape(-1)
    times = times[np.isfinite(times)]
    meter = max(1, int(meter))
    if times.size < meter:
        return {
            "phase": 0,
            "confidence": 0.0,
            "method": "insufficient_beats",
            "meter": meter,
        }

    accents = np.asarray(accent_times if accent_times is not None else [], dtype=np.float64).reshape(-1)
    accents = np.sort(accents[np.isfinite(accents)])
    if accents.size == 0:
        return {
            "phase": 0,
            "confidence": 0.0,
            "method": "assumed_first_beat",
            "meter": meter,
        }

    indices = np.clip(np.searchsorted(accents, times), 1, accents.size - 1)
    nearest = np.minimum(
        np.abs(times - accents[indices - 1]),
        np.abs(times - accents[indices]),
    )
    on_accent = nearest <= float(tolerance)
    positions = np.arange(times.size) % meter
    scores = []
    for phase in range(meter):
        mask = positions == phase
        count = int(np.count_nonzero(mask))
        scores.append(float(np.count_nonzero(on_accent & mask)) / count if count else 0.0)

    best_phase = int(np.argmax(np.asarray(scores)))
    best = scores[best_phase]
    if best <= 0.0:
        return {
            "phase": 0,
            "confidence": 0.0,
            "method": "assumed_first_beat",
            "meter": meter,
        }
    runner_up = max([value for phase, value in enumerate(scores) if phase != best_phase] or [0.0])
    return {
        "phase": best_phase,
        "confidence": round(max(0.0, min(1.0, best - runner_up)), 4),
        "method": "bass_accent_phase",
        "meter": meter,
        "phase_scores": [round(value, 4) for value in scores],
    }


def analyze_track(audio_path: str, progress_callback: Optional[Any] = None) -> Dict[str, Any]:
    """
    Full audio analysis: BPM, beats, downbeats, sections, energy, 808, hi-hats, key.
    Results are cached in SQLite for instant re-analysis.
    Optional progress_callback(step: str, pct: float) for UI progress reporting.
    """
    # Check cache first
    identity = analysis_identity()
    fingerprint = identity_fingerprint(identity)
    abs_path, size, mtime_ns, cache_key = _beat_cache_key(audio_path)
    cache_state = "miss"
    cache_error = ""
    try:
        with _beat_cache_connection() as conn:
            row = conn.execute(
                "SELECT result_json FROM beat_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
            if row:
                cached = json.loads(row[0])
                # The key already binds the identity, so a row whose stored
                # fingerprint disagrees was written by something other than this
                # engine. Rebuilding is cheaper than trusting it.
                if (
                    isinstance(cached, dict)
                    and cached.get("analysis_identity", {}).get("fingerprint") == fingerprint
                ):
                    cached["cache_state"] = "hit"
                    return cached
                cache_state = "stale_identity"
    except Exception as error:  # cache failure is never analysis failure
        cache_state = "error"
        cache_error = f"{type(error).__name__}: {error}"

    def _progress(step: str, pct: float):
        if progress_callback:
            try:
                progress_callback(step, pct)
            except Exception:
                pass

    _progress("Loading audio", 0.05)
    y, sr = librosa.load(audio_path, sr=ANALYSIS_SAMPLE_RATE)

    _progress("Isolating percussion", 0.10)
    # Rhythm is read off the percussive component so a held or sidechained 808
    # cannot masquerade as a stream of attacks. Timbre, key and the energy
    # curve stay on the full mix, where they describe what the listener hears.
    rhythm = separate_percussion(y, sr)

    _progress("Measuring vocal activity", 0.13)
    # Where the lead vocal actually is. This costs one extra STFT on a signal
    # HPSS has already produced, adds no dependency and no package weight, and
    # is the evidence that lets the editor cut on a vocal entry, ride a
    # sustained line and breathe in a rest — for every track, with no lyrics
    # supplied and no model installed.
    try:
        from lyric_analysis import detect_vocal_activity

        vocal_segments, vocal_diagnostics = detect_vocal_activity(
            y,
            sr,
            hop_length=rhythm.get("hop_length", 512),
            harmonic_spectrum=rhythm.get("harmonic_full_band"),
        )
    except Exception as error:  # pragma: no cover - never fail analysis over this
        vocal_segments, vocal_diagnostics = [], {"error": str(error), "available": False}

    _progress("Detecting beats", 0.15)
    # Beat tracking
    tempo_result, beats = librosa.beat.beat_track(y=rhythm["signal"], sr=sr)
    tempo = float(np.asarray(tempo_result).reshape(-1)[0])
    tempo = _correct_tempo(tempo)
    beat_times = librosa.frames_to_time(beats, sr=sr)

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
        segmentation_method = "mfcc_agglomerative"
    except (ImportError, ValueError):
        # Fallback: simple energy-based segmentation
        sections = simple_segmentation(y, sr, beat_times, tempo)
        segmentation_method = "fixed_length_energy"

    _progress("Computing energy", 0.60)
    # Energy curve (RMS)
    rms = librosa.feature.rms(
        y=y, frame_length=ENERGY_FRAME_LENGTH, hop_length=ENERGY_HOP_LENGTH
    )[0]
    rms_times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=ENERGY_HOP_LENGTH)
    energy = energy_envelope(rms, sr, ENERGY_HOP_LENGTH, ENERGY_FRAME_LENGTH)

    _progress("Detecting 808s", 0.70)
    # 808 attacks: sub-bass band of the percussive component. A high delta is
    # what rejects the slow level ramp of a sidechain recovery, which has no
    # attack even though its amplitude rises.
    if rhythm["bass_band"] is not None:
        bass_onsets = band_onsets(
            rhythm["bass_band"],
            sr,
            rhythm["hop_length"],
            BASS_MIN_SPACING_SECONDS,
            delta=0.30,
            smoothing=6,
        )
        # The held part of the note, kept as its own signal rather than
        # smuggled back in as fake attacks.
        bass_sustain = bass_sustain_intervals(
            rhythm["harmonic_bass_band"], sr, rhythm["hop_length"], tempo
        )
    else:
        # Long or memory-constrained tracks take the pre-HPSS waveform route.
        # It is less selective, but it avoids the unbounded complex STFT and
        # still produces schema-compatible attack and sustain evidence.
        bass_signal = frequency_filter(y, sr, BASS_BAND_HZ[1], "lowpass")
        bass_onsets = librosa.onset.onset_detect(
            y=bass_signal,
            sr=sr,
            units="time",
            hop_length=rhythm["hop_length"],
            wait=max(1, int(round(BASS_MIN_SPACING_SECONDS * sr / rhythm["hop_length"]))),
            delta=0.30,
        )
        bass_envelope = librosa.feature.rms(
            y=bass_signal,
            frame_length=HPSS_N_FFT,
            hop_length=rhythm["hop_length"],
        )
        bass_sustain = bass_sustain_intervals(
            bass_envelope, sr, rhythm["hop_length"], tempo
        )

    _progress("Detecting hi-hats", 0.80)
    # Hi-hats: air band of the same decomposition. Rolls are dense and even, so
    # this detector keeps librosa's sensitive threshold and a one-frame floor —
    # merging a 1/32 roll into one event would erase the pattern.
    if rhythm["hihat_band"] is not None:
        hihat_onsets = band_onsets(
            rhythm["hihat_band"],
            sr,
            rhythm["hop_length"],
            0.0,
            delta=0.07,
            smoothing=3,
        )
    else:
        hihat_signal = frequency_filter(y, sr, HIHAT_BAND_HZ, "highpass")
        hihat_onsets = librosa.onset.onset_detect(
            y=hihat_signal,
            sr=sr,
            units="time",
            hop_length=rhythm["hop_length"],
            delta=0.07,
        )

    _progress("Detecting key", 0.90)
    # Key detection
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    key, mode = estimate_key(chroma)

    _progress("Finalizing", 0.95)

    # Which beat of the bar is the downbeat is measured against the sub-bass
    # attacks, so this runs once those exist rather than assuming index zero.
    downbeat = estimate_downbeat_phase(beat_times, bass_onsets, DOWNBEAT_METER)
    downbeats = [
        float(beat_times[index])
        for index in range(int(downbeat["phase"]), len(beat_times), DOWNBEAT_METER)
    ]

    # Detect phrase boundaries
    phrase_boundaries = detect_phrase_boundaries(beat_times, tempo, sections, downbeats)

    duration = float(len(y) / sr)
    hook = detect_hook_section(sections, rms, rms_times, bass_onsets, bass_sustain, duration)

    grid_regularity = beat_grid_regularity(beat_times)
    bass_alignment = onset_grid_alignment(bass_onsets, beat_times)
    section_confidences = [
        float(section.get("label_confidence", POSITIONAL_LABEL_CONFIDENCE))
        for section in sections
    ]
    # A percussive decomposition rejects the sustain an 808 holds between hits;
    # the full-mix fallback cannot, so its attack list is capped no matter how
    # neatly it lands on the grid.
    bass_ceiling = 1.0 if rhythm["source"] == "percussive" else 0.6

    result = {
        "tempo": tempo,
        "beats": beat_times.tolist(),
        "downbeats": downbeats,
        "sections": sections,
        "phrase_boundaries": [pb['time'] for pb in phrase_boundaries],
        "energy": energy["energy"],
        "energy_times": energy["energy_times"],
        "energy_sample_rate": energy["energy_sample_rate"],
        "energy_hop_length": energy["energy_hop_length"],
        "energy_frame_length": energy["energy_frame_length"],
        "energy_nonfinite_samples": energy["energy_nonfinite_samples"],
        "bass_onsets": bass_onsets.tolist(),
        "bass_sustain": bass_sustain,
        "hihat_onsets": hihat_onsets.tolist(),
        "hook": hook,
        "rhythm_source": rhythm["source"],
        "analysis_schema": BEAT_ANALYSIS_SCHEMA_VERSION,
        "analysis_identity": dict(identity, fingerprint=fingerprint),
        "cache_state": cache_state,
        "cache_error": cache_error,
        "labels": {
            "downbeat": label_provenance(
                downbeat["method"],
                downbeat["confidence"],
                "the beat of the bar carrying the sub-bass accent; the meter itself is assumed",
                meter=int(downbeat["meter"]),
                phase=int(downbeat["phase"]),
            ),
            "section": label_provenance(
                f"{segmentation_method}+positional_override",
                float(np.mean(section_confidences)) if section_confidences else 0.0,
                "structural hypothesis; intro/outro come from position, not from measurement",
                sections=len(sections),
            ),
            "drop": drop_label_provenance(sections),
            "phrase": label_provenance(
                "metrical_grid_16_32_beats",
                grid_regularity,
                "a 4/4 metrical grid laid over the detected beats, not phrasing heard in the audio",
                boundaries=len(phrase_boundaries),
            ),
            "808": label_provenance(
                f"{rhythm['source']}_subbass_onset_flux",
                bass_alignment * bass_ceiling,
                "sub-bass attack evidence below 120 Hz; not 808 instrument identification",
                grid_alignment=round(bass_alignment, 4),
                onsets=int(len(bass_onsets)),
            ),
        },
        "key": key,
        "mode": mode,
        "duration": duration,
        # Measured vocal phrasing. Entries and exits become cut opportunities
        # in the event lattice; rests become permission to hold a shot.
        "vocal_segments": [
            {
                "start": round(float(segment.start), 4),
                "end": round(float(segment.end), 4),
                "confidence": float(segment.confidence),
            }
            for segment in vocal_segments
        ],
        "vocal_diagnostics": vocal_diagnostics,
    }
    result["labels"]["vocal"] = label_provenance(
        "harmonic_band_energy_and_peakiness",
        float(np.mean([segment.confidence for segment in vocal_segments])) if vocal_segments else 0.0,
        "presence of a harmonic lead in the 180-4000 Hz band; not speaker or lyric identification",
        segments=len(vocal_segments),
        verdict=str(vocal_diagnostics.get("verdict", "unknown")),
    )

    # Save to cache. A cache failure is not an analysis failure, but it is not
    # nothing either: it is recorded on the result instead of being swallowed.
    try:
        with _beat_cache_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO beat_cache (cache_key, source_path, source_size, source_mtime_ns, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (cache_key, abs_path, size, mtime_ns, json.dumps(result), time.time()),
            )
            conn.commit()
    except Exception as error:
        result["cache_state"] = "write_failed"
        result["cache_error"] = f"{type(error).__name__}: {error}"

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
    """Classify a section based on multiple audio characteristics.
    
    Uses spectral contrast + RMS envelope + onset density to classify:
    - Intro = low energy + low onset density at start
    - Verse = moderate energy, steady rhythm
    - Chorus = high energy + high onset density, repetitive
    - Drop = max energy + sub-bass heavy
    - Bridge = energy dip after chorus/drop
    - Outro = energy decay at end
    """
    start_sample = int(max(0, start * sr))
    end_sample = int(min(len(y), end * sr))
    
    if end_sample <= start_sample:
        return "verse"
    
    segment = y[start_sample:end_sample]
    if len(segment) == 0:
        return "verse"
    
    # Compute multiple features
    rms = np.sqrt(np.mean(segment ** 2))
    
    # Spectral contrast (difference between peaks and valleys in spectrum)
    spectral_contrast = librosa.feature.spectral_contrast(y=segment, sr=sr)
    contrast_mean = np.mean(spectral_contrast)
    
    # Onset density (onsets per second)
    onset_env = librosa.onset.onset_strength(y=segment, sr=sr)
    onset_density = np.sum(onset_env > np.mean(onset_env) * 0.5) / (len(segment) / sr)
    
    # Sub-bass energy (< 80Hz)
    bass_filtered = frequency_filter(segment, sr, 80, "lowpass")
    bass_energy = np.sqrt(np.mean(bass_filtered ** 2))
    bass_ratio = bass_energy / (rms + 1e-10)
    
    # Spectral centroid (brightness)
    spectral_centroid = np.mean(librosa.feature.spectral_centroid(y=segment, sr=sr))
    
    # Classify based on combined features
    # Drop: high energy + high bass ratio
    if rms > 0.08 and bass_ratio > 0.3:
        return "drop"
    
    # Chorus: high energy + high onset density
    elif rms > 0.05 and onset_density > 15:
        return "chorus"
    
    # Intro: low energy + low onset density
    elif rms < 0.02 and onset_density < 10:
        return "intro"
    
    # Bridge: moderate energy but lower than surroundings (energy dip)
    elif 0.02 < rms < 0.05 and onset_density < 12:
        return "bridge"
    
    # Verse: moderate energy, steady rhythm
    elif 0.02 < rms < 0.06:
        return "verse"
    
    # Default to chorus for high energy sections
    elif rms > 0.04:
        return "chorus"
    
    else:
        return "verse"


def assign_section_types(sections, y, sr):
    """Assign meaningful section types based on position and energy.

    The names this produces are a mixture of two very different kinds of
    evidence. "Drop" is measured — it is the loudest interior section, and the
    margin over the runner-up says how clearly. "Intro", "outro" and the
    alternating verse/chorus run are conventions about where things usually sit
    in a song, and they overwrite whatever ``classify_section_type`` measured.

    Both kinds are kept, so a consumer can tell them apart: ``measured_type``
    holds what the audio said, ``label_source`` says whether the published name
    came from that measurement or from position, and ``label_confidence``
    bounds how much the name is worth.
    """
    if not sections:
        return sections

    for section in sections:
        section["measured_type"] = section.get("type", "verse")

    # First section = intro, last = outro
    sections[0]["type"] = "intro"
    sections[-1]["type"] = "outro"

    # Find the highest energy section = drop
    energies = []
    max_energy = 0
    drop_idx = -1
    for i, sec in enumerate(sections[1:-1], 1):
        segment = y[int(sec["start"] * sr):int(sec["end"] * sr)]
        rms = float(np.sqrt(np.mean(segment ** 2))) if len(segment) > 0 else 0.0
        energies.append(rms)
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

    # How far the loudest interior section stands above the next loudest. A
    # drop that only just wins is a coin toss dressed as a label.
    runner_up = max([value for value in energies if value < max_energy] or [0.0])
    drop_margin = (max_energy - runner_up) / max_energy if max_energy > 0 else 0.0

    for index, section in enumerate(sections):
        measured = section.get("measured_type", section["type"])
        if index == drop_idx:
            section["label_source"] = "measured_energy"
            section["label_confidence"] = round(max(0.0, min(1.0, drop_margin)), 4)
        elif section["type"] == measured:
            section["label_source"] = "measured"
            section["label_confidence"] = 1.0
        else:
            section["label_source"] = "positional"
            section["label_confidence"] = POSITIONAL_LABEL_CONFIDENCE

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


# How much each section label contributes to being the hook. Chorus and drop
# are where a hook lives; an intro or outro almost never is, whatever its
# measured energy.
HOOK_SECTION_WEIGHT: Dict[str, float] = {
    "chorus": 1.0,
    "drop": 1.0,
    "bridge": 0.55,
    "verse": 0.45,
    "intro": 0.2,
    "outro": 0.2,
}
DEFAULT_HOOK_SECTION_WEIGHT = 0.45


def _section_mean_energy(energy, energy_times, start: float, end: float) -> float:
    """Mean RMS inside a section, using the energy curve's own time base."""
    if energy is None or energy_times is None:
        return 0.0
    values = np.asarray(energy, dtype=np.float64).reshape(-1)
    times = np.asarray(energy_times, dtype=np.float64).reshape(-1)
    if values.size == 0 or times.size == 0:
        return 0.0
    span = min(values.size, times.size)
    values = values[:span]
    times = times[:span]
    first = int(np.searchsorted(times, start, side="left"))
    last = int(np.searchsorted(times, end, side="left"))
    if last <= first:
        # A section shorter than one analysis frame still has a nearest sample.
        index = min(max(first, 0), span - 1)
        return float(values[index])
    window = values[first:last]
    return float(np.mean(window)) if window.size else 0.0


def _coverage(intervals, start: float, end: float) -> float:
    """Fraction of ``[start, end)`` covered by a list of {start, end} spans."""
    length = end - start
    if length <= 0:
        return 0.0
    covered = 0.0
    for interval in intervals or []:
        try:
            left = max(start, float(interval.get("start", 0.0)))
            right = min(end, float(interval.get("end", 0.0)))
        except (AttributeError, TypeError, ValueError):
            continue
        if right > left:
            covered += right - left
    return max(0.0, min(1.0, covered / length))


def detect_hook_section(
    sections,
    energy,
    energy_times,
    bass_onsets,
    bass_sustain,
    duration: float,
) -> Optional[Dict[str, Any]]:
    """Identify the section that carries the track's peak — the hook.

    Three measurable things distinguish a hook from the bars around it: it is
    loud, it is rhythmically dense, and in 808 music it sits on a held sub-bass
    note. Each is normalised against the rest of *this* track rather than an
    absolute threshold, because modern masters are limited flat and an absolute
    loudness gate would either fire everywhere or nowhere.

    The section label and a mild late-track preference break the remaining ties:
    the final chorus, not the first, is where an editor spends the best footage.

    Returns ``None`` when there is no section map to reason about, which is the
    signal for the shot selector to fall back to its own onset-only estimate.
    """
    parsed = []
    for index, section in enumerate(sections or []):
        try:
            start = float(section.get("start", 0.0))
            end = float(section.get("end", 0.0))
        except (AttributeError, TypeError, ValueError):
            continue
        if not (np.isfinite(start) and np.isfinite(end)) or end <= start:
            continue
        parsed.append((index, str(section.get("type", "verse")), start, end))
    if not parsed:
        return None

    onsets = np.asarray(
        [float(value) for value in (bass_onsets if bass_onsets is not None else [])],
        dtype=np.float64,
    )
    measured = []
    for index, section_type, start, end in parsed:
        span = end - start
        onset_count = int(np.sum((onsets >= start) & (onsets < end))) if onsets.size else 0
        measured.append(
            {
                "index": index,
                "type": section_type,
                "start": start,
                "end": end,
                "energy": _section_mean_energy(energy, energy_times, start, end),
                "density": onset_count / span if span > 0 else 0.0,
                "sustain": _coverage(bass_sustain, start, end),
            }
        )

    def _normalize(key: str) -> List[float]:
        peak = max(entry[key] for entry in measured)
        if peak <= 0:
            return [0.0] * len(measured)
        return [entry[key] / peak for entry in measured]

    energies = _normalize("energy")
    densities = _normalize("density")
    sustains = [entry["sustain"] for entry in measured]

    track_length = float(duration) if duration and duration > 0 else parsed[-1][3]
    scored = []
    for position, entry in enumerate(measured):
        evidence = (
            0.45 * energies[position]
            + 0.30 * densities[position]
            + 0.25 * sustains[position]
        )
        label_weight = HOOK_SECTION_WEIGHT.get(entry["type"], DEFAULT_HOOK_SECTION_WEIGHT)
        midpoint = (entry["start"] + entry["end"]) * 0.5
        lateness = midpoint / track_length if track_length > 0 else 0.0
        scored.append(evidence * label_weight * (1.0 + 0.25 * max(0.0, min(1.0, lateness))))

    best_position = int(np.argmax(np.asarray(scored, dtype=np.float64)))
    best_score = scored[best_position]
    if best_score <= 0:
        return None
    others = [value for position, value in enumerate(scored) if position != best_position]
    runner_up = max(others) if others else 0.0
    confidence = max(0.0, min(1.0, (best_score - runner_up) / best_score))

    chosen = measured[best_position]
    return {
        "index": chosen["index"],
        "type": chosen["type"],
        "start": round(chosen["start"], 6),
        "end": round(chosen["end"], 6),
        "score": round(float(best_score), 6),
        "confidence": round(float(confidence), 4),
    }


def detect_phrase_boundaries(beat_times, tempo, sections, downbeats=None):
    """Detect phrase boundaries (4-bar, 8-bar phrases) for musical cut placement.
    
    Returns a list of timestamps where phrase boundaries occur.
    These are preferred locations for transitions and section changes.
    """
    # ``analyze_track`` passes the librosa beat array straight through, and a
    # numpy array has no truth value — test the length, never the object.
    if beat_times is None or len(beat_times) < 4:
        return []
    
    # Calculate beat period
    beat_period = 60.0 / tempo if tempo > 0 else np.median(np.diff(beat_times))
    
    # In 4/4 time, a bar is typically 4 beats
    # Common phrase lengths: 4 bars (16 beats), 8 bars (32 beats)
    phrase_beats = [16, 32]  # 4-bar and 8-bar phrases
    
    phrase_boundaries = []
    
    # Start from the first downbeat
    for section in sections:
        section_start = section.get('start', 0.0)
        section_end = section.get('end', 0.0)
        section_type = section.get('type', 'verse')
        
        # Find the first measured downbeat in this section. Falling back to the
        # first beat preserves legacy results when no downbeat evidence exists.
        start_beat_idx = np.searchsorted(beat_times, section_start)
        end_beat_idx = np.searchsorted(beat_times, section_end)

        if downbeats is not None and len(downbeats) > 0:
            section_downbeats = [
                float(value)
                for value in downbeats
                if section_start <= float(value) < section_end
            ]
            if section_downbeats:
                start_beat_idx = int(np.searchsorted(beat_times, section_downbeats[0]))
        
        if start_beat_idx >= end_beat_idx:
            continue
        
        # Add phrase boundaries within the section
        for phrase_len in phrase_beats:
            for i in range(start_beat_idx + phrase_len, end_beat_idx, phrase_len):
                if i < len(beat_times):
                    phrase_boundaries.append({
                        'time': float(beat_times[i]),
                        'phrase_length': phrase_len,
                        'section_type': section_type
                    })
    
    # Remove duplicates (same time from different phrase lengths)
    seen_times = set()
    unique_boundaries = []
    for boundary in sorted(phrase_boundaries, key=lambda x: x['time']):
        # Round to nearest 10ms for comparison
        rounded_time = round(boundary['time'], 2)
        if rounded_time not in seen_times:
            seen_times.add(rounded_time)
            unique_boundaries.append(boundary)
    
    return unique_boundaries
