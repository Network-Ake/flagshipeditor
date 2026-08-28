"""Time-aligned lyrics, and what they mean, without a mandatory model download.

The shipped engine contains no lyric handling of any kind — a grep for
``lyric``, ``transcri`` or ``align`` across the whole product returns nothing.
The video therefore cannot know what the song is about, which is exactly the
failure Steve reported.

Acquisition is tiered, strongest evidence first, and every tier reports what it
actually knows rather than promoting a guess:

1. ``timecoded``  — the user supplied ``.lrc`` / ``.srt`` / ``.vtt`` / JSON with
   timestamps. Nothing is inferred; confidence is the file's own.
2. ``asr``        — a local speech model is installed and produced word times.
   Optional. Never bundled, never required, never a network call.
3. ``aligned``    — the user supplied plain lyrics and we measured where the
   voice is. Lines are distributed across the measured vocal phrases by
   syllable weight. This is an *alignment*, not a transcription, and its
   confidence is bounded well below the tiers above.
4. ``vocal_only`` — no text at all. We still measure when the voice enters,
   holds and rests, which is real editorial information: cut on the entry, ride
   the sustained line, breathe in the gap. No semantic claim is made.

Tier 4 needs no user input and no new dependency, so *every* track gets vocal
phrasing. Tier 3 needs only the artist's own lyrics, which for a music video is
the one text that always exists. That ordering is what keeps the package
offline and self-contained: the baseline install grows by zero bytes.

The semantic layer is a lexicon, and says so. It is not a language model and
does not pretend to be one: it extracts imagery, actions, places, objects,
address, intensity and repetition, keeps competing senses of an ambiguous term
side by side, and refuses to emit an interpretation whose confidence falls
below :data:`MIN_INTERPRETATION_CONFIDENCE`. Nothing downstream is allowed to
illustrate a line it does not actually understand.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Confidence discipline
# ---------------------------------------------------------------------------

# Ceilings per acquisition tier. A tier can report *less* than its ceiling; it
# can never report more. These are the numbers that stop the editor from acting
# on a line it effectively guessed.
TIER_CONFIDENCE_CEILING: Dict[str, float] = {
    "timecoded": 1.00,
    "asr": 0.85,
    "aligned": 0.62,
    "vocal_only": 0.0,
}

# Below this, a lyric may still influence *pacing* (we know a voice is there)
# but may not influence *imagery* — no clip is chosen because of what we think
# the words mean.
MIN_INTERPRETATION_CONFIDENCE = 0.45

# Below this a line's timing is not trusted enough to place a cut on it.
MIN_TIMING_CONFIDENCE = 0.35

# Vocal-detection gates. All three must hold before the engine will claim a
# lead vocal exists. Measured on fixtures: a synthesised rap-style lead over
# drums separates at ~0.45 with ~0.53 mean confidence and ~3.3 s median phrase
# length; a drums-only instrumental reaches ~0.20 / ~0.11 / ~0.56 s. The gates
# sit between those populations, so an instrumental reports no vocal rather
# than reporting one every half second.
MIN_VOCAL_SEPARATION = 0.30
MIN_VOCAL_MEAN_CONFIDENCE = 0.30
MIN_VOCAL_MEDIAN_SECONDS = 0.80


# ---------------------------------------------------------------------------
# Semantic lexicon
# ---------------------------------------------------------------------------
#
# Fields are *visual affordances*, not topics: each one names something an
# editor could actually put on screen or a way they could pace a shot. A term
# that maps to no visual affordance is deliberately absent rather than being
# given a vague one.
#
# ``regions`` is descriptive provenance for vocabulary that is strongly
# associated with a scene's shared musical vocabulary. It records where a term
# is commonly used so an uncertain reading can be reported honestly. It is
# never used to infer anything about a performer, and never changes a score.

SEMANTIC_FIELDS: Dict[str, Dict[str, Any]] = {
    "money": {
        "imagery": ("cash", "jewellery", "exchange", "excess"),
        "valence": 0.6,
        "intensity": 0.6,
    },
    "place": {"imagery": ("environment", "establishing", "architecture"), "valence": 0.0, "intensity": 0.3},
    "movement": {"imagery": ("vehicle", "travel", "motion"), "valence": 0.2, "intensity": 0.7},
    "conflict": {"imagery": ("tension", "confrontation", "threat"), "valence": -0.6, "intensity": 0.9},
    "loyalty": {"imagery": ("group", "closeness", "gesture"), "valence": 0.5, "intensity": 0.5},
    "grief": {"imagery": ("absence", "memory", "stillness"), "valence": -0.8, "intensity": 0.5},
    "ambition": {"imagery": ("ascent", "work", "distance"), "valence": 0.7, "intensity": 0.6},
    "celebration": {"imagery": ("crowd", "light", "excess"), "valence": 0.8, "intensity": 0.8},
    "romance": {"imagery": ("closeness", "face", "touch"), "valence": 0.6, "intensity": 0.4},
    "betrayal": {"imagery": ("distance", "turning_away", "isolation"), "valence": -0.7, "intensity": 0.6},
    "faith": {"imagery": ("light", "elevation", "stillness"), "valence": 0.4, "intensity": 0.4},
    "night": {"imagery": ("low_light", "neon", "environment"), "valence": -0.1, "intensity": 0.4},
    "substance": {"imagery": ("haze", "close_detail", "slow"), "valence": -0.1, "intensity": 0.3},
    "self": {"imagery": ("face", "performance", "direct_address"), "valence": 0.3, "intensity": 0.5},
    "time": {"imagery": ("passage", "memory", "contrast"), "valence": -0.2, "intensity": 0.3},
    "struggle": {"imagery": ("effort", "weight", "endurance"), "valence": -0.4, "intensity": 0.7},
}

# term -> (field, weight, regions). Weight is how strongly the term implies the
# field; a term that is only a weak hint carries a low weight and therefore
# cannot on its own push a line over the interpretation threshold.
LEXICON: Dict[str, Tuple[str, float, Tuple[str, ...]]] = {}


# Words that carry grammar rather than imagery. A lexicon that registers these
# turns every line into a match: "I drove through the city" would score as
# *struggle* purely because "through" appeared in a phrase like "fight through".
# Registration refuses them outright, which is cheaper than filtering later and
# impossible to forget.
FUNCTION_WORDS = frozenset(
    """a an the and or but if then than so as at by for from in into of off on
    out over to up with about after before back down day one two used it its
    this that these those is are was were be been being do does did have has
    had will would can could should may might must not no nor too very just
    now here there when where who whom which what how why all any some each
    every other another such own same s t re ve ll d m"""
    .split()
)


def _register(field: str, weight: float, terms: str, regions: Tuple[str, ...] = ()) -> None:
    """Map single concrete terms onto a semantic field.

    Only single tokens are accepted. An entry like ``"day one"`` would be split
    on whitespace and silently register ``day`` and ``one`` as loyalty terms,
    which then fire on any line containing either word. Multi-word idioms
    belong in :data:`IDIOMS`, which is matched against the whole line.
    """
    for term in terms.split():
        term = term.strip().lower()
        if not term or term in FUNCTION_WORDS:
            continue
        LEXICON[term] = (field, weight, regions)


# Idioms whose meaning is not the sum of their words. Matched against the
# normalised line before single-token lookup, so "day one" reads as loyalty
# while "one" on its own reads as nothing.
IDIOMS: Dict[str, Tuple[str, float]] = {
    "day one": ("loyalty", 0.9),
    "turn up": ("celebration", 0.9),
    "night out": ("celebration", 0.8),
    "two faced": ("betrayal", 0.9),
    "used to": ("time", 0.7),
    "back then": ("time", 0.9),
    "fight through": ("struggle", 0.9),
    "come up": ("ambition", 0.8),
    "on top": ("ambition", 0.7),
    "drop top": ("celebration", 0.7),
    "run it up": ("money", 0.8),
    "pull up": ("movement", 0.8),
    "back road": ("place", 0.7),
    "no love": ("betrayal", 0.8),
    "long nights": ("struggle", 0.8),
    "real ones": ("loyalty", 0.8),
}


# Core English vocabulary. Deliberately concrete: words that name something
# visible or a physical action.
_register("money", 0.9, "money cash bands racks bag guap paper profit rich wealth broke bills dollar dollars currency")
_register("money", 0.8, "chain chains diamonds diamond jewelry jewellery watch iced ice bust drip")
_register("place", 0.9, "block street streets corner hood city town road highway bridge rooftop apartment house studio")
_register("place", 0.7, "atlanta brooklyn compton miami detroit toronto london montreal harlem oakland queens bronx")
_register("movement", 0.9, "drive driving ride riding run running walk walking fly flying slide sliding speed race chase")
_register("movement", 0.8, "car cars whip foreign engine wheels road trip motorcycle bike train plane")
_register("conflict", 0.9, "fight fighting war beef smoke enemy enemies problem problems opps threat danger")
_register("conflict", 0.7, "gun steel iron pressure heat static drama")
_register("loyalty", 0.9, "brother brothers family fam gang crew team squad loyal loyalty together homie homies bruddas")
_register("grief", 0.9, "gone dead died death lost losing miss missing funeral grave tears cry crying pain hurt")
_register("ambition", 0.9, "grind hustle work working climb rise rising win winning goal dream dreams future")
_register("celebration", 0.9, "party celebrate lit club dance dancing pour champagne toast")
_register("romance", 0.9, "love loving baby girl shorty kiss heart together lover romance")
_register("betrayal", 0.9, "fake snake switched leaving lied lying betrayed traitor")
_register("faith", 0.9, "god lord pray prayer bless blessed heaven angel faith church soul spirit")
_register("night", 0.9, "night nights midnight dark darkness moon stars neon late")
_register("substance", 0.8, "smoke smoking drink drinking bottle cup pour high faded")
_register("self", 0.9, "i me my myself mine")
_register("self", 0.6, "you your yours we us our")
_register("time", 0.8, "years year yesterday tomorrow remember memory past forever")
_register("struggle", 0.9, "struggle survive survival hungry starving trapped stuck")

# Vocabulary strongly associated with particular scenes. Recorded with the
# regions it circulates in so an uncertain reading can be reported rather than
# silently resolved. Several of these are shared across multiple scenes, which
# is why ``regions`` is a list and not a label.
_register("place", 0.7, "trap bando spot", ("atlanta", "florida", "detroit"))
_register("loyalty", 0.7, "bruddas mandem wagwan", ("uk", "toronto"))
_register("movement", 0.7, "swerve skrrt slidin", ("atlanta", "west_coast"))
_register("celebration", 0.7, "rari drop top vibin", ("west_coast", "florida"))
_register("conflict", 0.6, "wave ting", ("uk", "toronto"))
_register("money", 0.7, "ps bread cheddar", ("uk", "new_york", "montreal"))
_register("place", 0.6, "ends endz", ("uk", "toronto"))
_register("loyalty", 0.6, "gs", ("west_coast",))

# Terms whose sense genuinely depends on context. Both readings are kept and
# the confidence is split, so nothing downstream can act on one of them alone.
AMBIGUOUS_TERMS: Dict[str, Tuple[Tuple[str, float], ...]] = {
    "ice": (("money", 0.55), ("night", 0.2)),
    "cold": (("struggle", 0.45), ("conflict", 0.25)),
    "smoke": (("conflict", 0.45), ("substance", 0.4)),
    "heat": (("conflict", 0.45), ("struggle", 0.2)),
    "bag": (("money", 0.6), ("ambition", 0.25)),
    "wave": (("celebration", 0.35), ("conflict", 0.3)),
    "trap": (("place", 0.5), ("struggle", 0.3)),
    "drop": (("movement", 0.35), ("celebration", 0.3)),
    "hard": (("struggle", 0.4), ("conflict", 0.25)),
    "run": (("movement", 0.5), ("ambition", 0.25)),
    "ring": (("romance", 0.35), ("money", 0.3)),
    "shine": (("money", 0.4), ("celebration", 0.35)),
}

# Sounds that carry performance energy but no meaning. Treated as delivery
# evidence — they mark a peak in the vocal — and never as imagery.
AD_LIB_TOKENS = frozenset(
    """yeah yea ay aye ayy uh huh hey woo woah whoa ooh oh ah skrrt brr grr
    baow pew hah yuh yup nah mm mmm sheesh damn okay ok let's go gang
    facts word bet bruh man look listen"""
    .split()
)

# A handful of French and Haitian-Creole markers. Presence is *detected* and
# reported; the semantic layer does not attempt to interpret a language it
# cannot analyse, and lowers confidence instead of guessing.
FRENCH_MARKERS = frozenset(
    "je tu il elle nous vous ils sont est les des une dans pour avec mais tout "
    "plus jamais toujours cœur coeur amour vie mort nuit temps rien être".split()
)
CREOLE_MARKERS = frozenset(
    "mwen ou li nou yo se pa gen ak nan pou anpil tout kè lanmou lavi lamò "
    "nuit tan anyen zanmi fanmi".split()
)


# ---------------------------------------------------------------------------
# Text utilities
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-z0-9']+")
_TIMECODE_LRC = re.compile(r"\[(\d+):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_TIMECODE_SRT = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
)


def _fold(text: str) -> str:
    """Lowercase and strip accents for matching, keeping the original intact.

    French and Creole both carry accents that matter for display and not for
    lookup. Folding only the match key means ``cœur`` still prints correctly.
    """
    text = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(ch for ch in text if not unicodedata.combining(ch)).lower()


def tokenize(text: str) -> List[str]:
    """Split a line into comparable word tokens."""
    return _WORD_RE.findall(_fold(text))


def count_syllables(word: str) -> int:
    """Estimate English syllables. Used only to weight alignment, never shown.

    Alignment needs relative line *lengths*, so a heuristic that is wrong by one
    syllable on an occasional word costs nothing. Being wrong by a factor of two
    on a long line would matter, and vowel-group counting is not.
    """
    word = re.sub(r"[^a-z]", "", _fold(word))
    if not word:
        return 0
    if len(word) <= 3:
        return 1
    word = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", word)
    word = re.sub(r"^y", "", word)
    groups = re.findall(r"[aeiouy]{1,2}", word)
    return max(1, len(groups))


def line_syllables(text: str) -> int:
    """Total estimated syllables in a line, floored at one for any non-empty line."""
    tokens = tokenize(text)
    if not tokens:
        return 0
    return max(1, sum(count_syllables(token) for token in tokens))


def detect_languages(lines: Sequence[str]) -> Dict[str, float]:
    """Report which languages the lyric appears to contain, by token share.

    English is the expected primary language; French is uncommon and Creole may
    appear. Detection exists so the semantic layer can *decline* to interpret a
    passage it has no lexicon for, rather than scoring it as meaningless English.
    """
    counts = {"english": 0, "french": 0, "creole": 0}
    total = 0
    for line in lines or []:
        for token in tokenize(line):
            total += 1
            if token in CREOLE_MARKERS:
                counts["creole"] += 1
            elif token in FRENCH_MARKERS:
                counts["french"] += 1
            elif token in LEXICON or token in AD_LIB_TOKENS:
                counts["english"] += 1
    if total == 0:
        return {}
    return {name: round(value / total, 4) for name, value in counts.items() if value}


# ---------------------------------------------------------------------------
# Tier 1 — timecoded lyric files
# ---------------------------------------------------------------------------


def parse_lrc(text: str) -> List[Dict[str, Any]]:
    """Parse an ``.lrc`` file, honouring repeated timestamps on one line."""
    entries: List[Dict[str, Any]] = []
    for raw in str(text or "").splitlines():
        stamps = list(_TIMECODE_LRC.finditer(raw))
        if not stamps:
            continue
        content = _TIMECODE_LRC.sub("", raw).strip()
        if not content:
            continue
        for stamp in stamps:
            minutes = int(stamp.group(1))
            seconds = int(stamp.group(2))
            fraction = stamp.group(3) or "0"
            fractional = int(fraction) / (10 ** len(fraction))
            entries.append({"start": minutes * 60 + seconds + fractional, "text": content})
    entries.sort(key=lambda entry: entry["start"])
    return entries


def parse_srt(text: str) -> List[Dict[str, Any]]:
    """Parse ``.srt``/``.vtt`` cues into ``{start, end, text}`` records."""
    entries: List[Dict[str, Any]] = []
    blocks = re.split(r"\n\s*\n", str(text or "").strip())
    for block in blocks:
        match = _TIMECODE_SRT.search(block)
        if not match:
            continue
        numbers = [int(value) for value in match.groups()]
        start = numbers[0] * 3600 + numbers[1] * 60 + numbers[2] + numbers[3] / 1000.0
        end = numbers[4] * 3600 + numbers[5] * 60 + numbers[6] + numbers[7] / 1000.0
        content = block[match.end():].strip()
        content = re.sub(r"<[^>]+>", "", content)
        content = " ".join(part.strip() for part in content.splitlines() if part.strip())
        if content:
            entries.append({"start": start, "end": end, "text": content})
    entries.sort(key=lambda entry: entry["start"])
    return entries


def parse_timecoded_json(payload: Any) -> List[Dict[str, Any]]:
    """Accept a JSON lyric structure produced by a transcription tool.

    Two shapes are honoured: a bare list of ``{start, end, text}`` and a wrapper
    carrying ``segments`` or ``lines``, which is what every local ASR frontend
    the panel might shell out to already emits.
    """
    if isinstance(payload, dict):
        payload = payload.get("segments") or payload.get("lines") or payload.get("lyrics") or []
    entries: List[Dict[str, Any]] = []
    for item in payload or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or item.get("line") or "").strip()
        if not text:
            continue
        try:
            start = float(item.get("start", item.get("time", 0.0)))
        except (TypeError, ValueError):
            continue
        record: Dict[str, Any] = {"start": start, "text": text}
        try:
            end = float(item.get("end"))
            if np.isfinite(end) and end > start:
                record["end"] = end
        except (TypeError, ValueError):
            pass
        confidence = item.get("confidence", item.get("probability"))
        try:
            if confidence is not None:
                record["confidence"] = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            pass
        entries.append(record)
    entries.sort(key=lambda entry: entry["start"])
    return entries


def load_lyric_source(text: str, filename: str = "") -> Tuple[str, List[Dict[str, Any]], List[str]]:
    """Sniff the lyric format and return ``(kind, timed_entries, plain_lines)``.

    ``kind`` is ``"timecoded"`` or ``"plain"``. Sniffing is by content first and
    extension second, because a user who pastes LRC text into a plain box should
    still get exact timings.
    """
    raw = str(text or "")
    if not raw.strip():
        return "plain", [], []

    extension = os.path.splitext(str(filename or ""))[1].lower()

    stripped = raw.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            entries = parse_timecoded_json(json.loads(raw))
            if entries:
                return "timecoded", entries, [entry["text"] for entry in entries]
        except (ValueError, TypeError):
            pass

    if _TIMECODE_SRT.search(raw) or extension in (".srt", ".vtt"):
        entries = parse_srt(raw)
        if entries:
            return "timecoded", entries, [entry["text"] for entry in entries]

    if _TIMECODE_LRC.search(raw) or extension == ".lrc":
        entries = parse_lrc(raw)
        if entries:
            return "timecoded", entries, [entry["text"] for entry in entries]

    lines = [line.strip() for line in raw.splitlines()]
    # Drop section markers a lyric sheet carries — "[Verse 1]", "(Hook)" — they
    # are structure, not sung text, and aligning them would shift every line.
    lines = [
        line
        for line in lines
        if line and not re.fullmatch(r"[\[\(].{0,40}[\]\)]", line)
    ]
    return "plain", [], lines


# ---------------------------------------------------------------------------
# Tier 4 — vocal activity, measured from the audio
# ---------------------------------------------------------------------------


class VocalSegment(NamedTuple):
    """One measured stretch where a lead vocal is present."""

    start: float
    end: float
    confidence: float
    peak: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def detect_vocal_activity(
    y: Any,
    sr: int,
    harmonic: Any = None,
    hop_length: int = 512,
    min_segment: float = 0.35,
    merge_gap: float = 0.28,
    harmonic_spectrum: Any = None,
    n_fft: int = 2048,
) -> Tuple[List[VocalSegment], Dict[str, Any]]:
    """Measure where a lead vocal is present, offline, with no new dependency.

    A sung or rapped lead sits in a band the drums mostly leave alone and is
    strongly harmonic, so the detector combines three things already available
    from the analysis librosa performs anyway: energy inside the vocal band of
    the harmonic component, how *peaked* that band's spectrum is (a voice has
    partials; a hi-hat does not), and how far above the track's own floor the
    result sits. The threshold is a percentile of the track, never an absolute
    level — the shipped section classifier's absolute RMS gates are exactly the
    mistake this avoids on a limited master.

    Returns the segments and a diagnostics record naming the method and the
    threshold it chose, so a downstream claim about a vocal entry can be
    checked rather than believed.
    """
    diagnostics: Dict[str, Any] = {"method": "band_energy_harmonicity", "available": False}
    try:
        import librosa  # noqa: F401  (import cost is already paid by beat analysis)
    except Exception as error:  # pragma: no cover - environment dependent
        diagnostics["error"] = f"librosa unavailable: {error}"
        return [], diagnostics

    import librosa

    try:
        if harmonic_spectrum is not None:
            # Beat analysis has already paid for an HPSS decomposition. Reusing
            # its harmonic magnitude spectrum makes vocal detection nearly free
            # — no inverse transform to rebuild a signal, no second forward
            # transform to analyse it.
            spectrogram = np.asarray(harmonic_spectrum, dtype=np.float32)
            if spectrogram.ndim != 2 or spectrogram.shape[1] < 4:
                diagnostics["error"] = "harmonic spectrum unusable"
                return [], diagnostics
            diagnostics["method"] = "hpss_harmonic_band_energy"
            n_fft = max(4, (spectrogram.shape[0] - 1) * 2)
        else:
            signal = np.asarray(harmonic if harmonic is not None else y, dtype=np.float32)
            if signal.ndim > 1:
                signal = np.mean(signal, axis=0)
            if signal.size < sr // 4:
                diagnostics["error"] = "signal too short"
                return [], diagnostics
            spectrogram = np.abs(librosa.stft(signal, n_fft=n_fft, hop_length=hop_length))

        frequencies = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
        times = librosa.frames_to_time(
            np.arange(spectrogram.shape[1]), sr=sr, hop_length=hop_length
        )
        if frequencies.size != spectrogram.shape[0]:
            diagnostics["error"] = "spectrum/frequency length mismatch"
            return [], diagnostics

        # The lead sits roughly here. Below 180 Hz is bass and kick; above
        # 4 kHz is mostly cymbals and air.
        band = (frequencies >= 180.0) & (frequencies <= 4000.0)
        if not np.any(band):
            diagnostics["error"] = "vocal band empty"
            return [], diagnostics

        band_magnitude = spectrogram[band, :]
        band_energy = np.sqrt(np.mean(band_magnitude ** 2, axis=0) + 1e-12)

        # Spectral flatness inside the band: low for a voice with clear
        # partials, high for broadband percussion. Inverted so "more vocal"
        # is a larger number.
        geometric = np.exp(np.mean(np.log(band_magnitude + 1e-10), axis=0))
        arithmetic = np.mean(band_magnitude, axis=0) + 1e-10
        peakiness = 1.0 - np.clip(geometric / arithmetic, 0.0, 1.0)

        def _norm(values: np.ndarray) -> np.ndarray:
            low = float(np.percentile(values, 10.0))
            high = float(np.percentile(values, 95.0))
            if high - low < 1e-9:
                return np.zeros_like(values)
            return np.clip((values - low) / (high - low), 0.0, 1.0)

        score = _norm(band_energy) * 0.6 + _norm(peakiness) * 0.4

        # Smooth over ~150 ms so a consonant gap does not end a phrase.
        step = float(np.median(np.diff(times))) if times.size > 1 else hop_length / sr
        width = max(1, int(round(0.15 / step))) if step > 0 else 1
        if width > 1:
            score = np.convolve(score, np.ones(width) / width, mode="same")

        # A track that is entirely instrumental has no bimodal split, so a
        # fixed percentile would invent a vocal. Requiring the chosen threshold
        # to actually separate two populations is what makes the instrumental
        # case return nothing instead of returning half the track.
        threshold = float(np.percentile(score, 62.0))
        above = score > threshold
        share = float(np.mean(above))
        separation = (
            float(np.mean(score[above]) - np.mean(score[~above]))
            if 0.02 < share < 0.98
            else 0.0
        )
        diagnostics.update(
            {
                "available": True,
                "threshold": round(threshold, 5),
                "active_share": round(share, 4),
                "separation": round(separation, 4),
                "frames": int(score.size),
            }
        )
        if separation < MIN_VOCAL_SEPARATION:
            diagnostics["verdict"] = "no_distinct_vocal_layer"
            return [], diagnostics

        segments: List[VocalSegment] = []
        index = 0
        count = score.size
        while index < count:
            if not above[index]:
                index += 1
                continue
            start_index = index
            while index < count and above[index]:
                index += 1
            start = float(times[start_index])
            end = float(times[min(index, count - 1)])
            window = score[start_index:index]
            peak = float(np.max(window)) if window.size else 0.0
            mean = float(np.mean(window)) if window.size else 0.0
            confidence = max(0.0, min(1.0, (mean - threshold) / max(1e-6, 1.0 - threshold)))
            segments.append(VocalSegment(start, end, round(confidence, 4), round(peak, 4)))

        merged: List[VocalSegment] = []
        for segment in segments:
            if merged and segment.start - merged[-1].end <= merge_gap:
                previous = merged[-1]
                merged[-1] = VocalSegment(
                    previous.start,
                    segment.end,
                    round(max(previous.confidence, segment.confidence), 4),
                    round(max(previous.peak, segment.peak), 4),
                )
                continue
            merged.append(segment)

        kept = [segment for segment in merged if segment.duration >= min_segment]
        if not kept:
            diagnostics["verdict"] = "no_segments_above_minimum"
            return [], diagnostics

        # An instrumental has no vocal layer, but a percentile threshold will
        # always split *something* — on a purely instrumental fixture the naive
        # detector returned nineteen fragments. What separates a real lead from
        # that is not how loud the band is, it is that a sung or rapped line is
        # *sustained* and stands clearly above the floor. Requiring both, on top
        # of the population separation, is what makes the instrumental answer
        # "no vocal" instead of "a vocal every half second".
        mean_confidence = float(np.mean([segment.confidence for segment in kept]))
        median_duration = float(np.median([segment.duration for segment in kept]))
        diagnostics.update(
            {
                "meanConfidence": round(mean_confidence, 4),
                "medianSegmentSeconds": round(median_duration, 4),
            }
        )
        if mean_confidence < MIN_VOCAL_MEAN_CONFIDENCE or median_duration < MIN_VOCAL_MEDIAN_SECONDS:
            diagnostics["verdict"] = "fragmented_no_sustained_lead"
            return [], diagnostics

        diagnostics["segments"] = len(kept)
        diagnostics["verdict"] = "measured"
        return kept, diagnostics
    except Exception as error:  # pragma: no cover - defensive
        diagnostics["error"] = str(error)
        return [], diagnostics


# ---------------------------------------------------------------------------
# Tier 3 — aligning supplied text to measured vocal phrases
# ---------------------------------------------------------------------------


def align_lines_to_vocals(
    lines: Sequence[str],
    segments: Sequence[VocalSegment],
    duration: float,
) -> List[Dict[str, Any]]:
    """Distribute plain lyric lines across measured vocal phrases by syllable weight.

    This is the honest middle tier. We know precisely *when* the voice is
    active, because that was measured; we know the order of the lines, because
    the user gave them to us; we do not know which line is which phrase. So the
    lines are laid onto the phrases in order, proportionally to their syllable
    count, and every resulting timestamp is reported with a confidence that
    reflects how strong that assumption is in its neighbourhood.

    Two things move a line's confidence:

    * how well the syllable budget matched the phrase it landed in — a phrase
      with room for eight syllables holding a nineteen-syllable line means the
      mapping has slipped;
    * how confident the vocal detector was about the phrase itself.

    A line that lands in a low-confidence region keeps its timing but is barred
    from driving imagery, which is what stops a mis-aligned line from choosing a
    shot for the wrong moment.
    """
    cleaned = [line for line in (lines or []) if str(line).strip()]
    if not cleaned:
        return []

    usable = [segment for segment in segments if segment.duration > 0.05]
    if not usable:
        # No measured vocal at all: spreading lines evenly across the track
        # would be fabrication. Return them untimed so a caller can still read
        # the lyric for global themes without placing a single cut on it.
        return [
            {
                "index": index,
                "text": text,
                "start": None,
                "end": None,
                "confidence": 0.0,
                "timing_source": "unaligned",
            }
            for index, text in enumerate(cleaned)
        ]

    syllables = [max(1, line_syllables(text)) for text in cleaned]
    total_syllables = float(sum(syllables))
    total_vocal = float(sum(segment.duration for segment in usable))
    if total_vocal <= 0:
        return []

    # Walk the phrases and the lines together, spending each phrase's duration
    # on the lines in proportion to their syllables.
    out: List[Dict[str, Any]] = []
    line_index = 0
    carried = 0.0  # syllable budget already consumed from the current line
    syllables_per_second = total_syllables / total_vocal

    for segment in usable:
        capacity = segment.duration * syllables_per_second
        cursor = segment.start
        spent = 0.0
        while line_index < len(cleaned) and spent < capacity - 1e-6:
            remaining_line = syllables[line_index] - carried
            take = min(remaining_line, capacity - spent)
            if take <= 1e-6:
                break
            span = (take / max(1e-6, capacity)) * segment.duration
            start = cursor
            end = min(segment.end, cursor + span)

            if carried <= 1e-6:
                # Fit quality: how close this line's syllable count is to what
                # the phrase could actually hold.
                fit = min(remaining_line, capacity) / max(remaining_line, capacity, 1e-6)
                confidence = float(
                    max(0.0, min(1.0, 0.35 + 0.4 * fit + 0.25 * segment.confidence))
                )
                out.append(
                    {
                        "index": line_index,
                        "text": cleaned[line_index],
                        "start": round(float(start), 4),
                        "end": round(float(end), 4),
                        "confidence": round(min(confidence, TIER_CONFIDENCE_CEILING["aligned"]), 4),
                        "timing_source": "syllable_alignment",
                        "syllables": syllables[line_index],
                        "phrase_confidence": segment.confidence,
                    }
                )
            elif out:
                out[-1]["end"] = round(float(end), 4)

            cursor = end
            spent += take
            carried += take
            if carried >= syllables[line_index] - 1e-6:
                line_index += 1
                carried = 0.0

        if line_index >= len(cleaned):
            break

    # Lines that never found a phrase keep their text and lose their timing.
    for index in range(line_index, len(cleaned)):
        if any(entry["index"] == index for entry in out):
            continue
        out.append(
            {
                "index": index,
                "text": cleaned[index],
                "start": None,
                "end": None,
                "confidence": 0.0,
                "timing_source": "unaligned",
            }
        )

    out.sort(key=lambda entry: (entry["start"] is None, entry["start"] or 0.0, entry["index"]))
    return out


# ---------------------------------------------------------------------------
# Tier 2 — optional local ASR
# ---------------------------------------------------------------------------


def transcribe_local(audio_path: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Use a locally installed speech model if — and only if — one is present.

    Nothing here is bundled and nothing is downloaded. Two adapters are probed,
    both entirely offline:

    * ``faster_whisper`` importable in the runtime, with the model directory
      given by ``FLAGSHIPEDITOR_ASR_MODEL``;
    * a ``whisper.cpp`` binary named by ``FLAGSHIPEDITOR_WHISPER_BIN`` plus a
      ``.bin`` model in ``FLAGSHIPEDITOR_ASR_MODEL``.

    Neither is installed by default, so the shipped package size is unchanged.
    A user who wants transcription supplies the model themselves and the engine
    uses it; a user who does not gets tier 3 or tier 4 and is told so.
    """
    diagnostics: Dict[str, Any] = {"attempted": [], "available": False}

    model_path = os.environ.get("FLAGSHIPEDITOR_ASR_MODEL", "").strip()

    try:
        from faster_whisper import WhisperModel  # type: ignore

        diagnostics["attempted"].append("faster_whisper")
        if model_path and os.path.exists(model_path):
            model = WhisperModel(model_path, device="cpu", compute_type="int8")
            segments, info = model.transcribe(
                audio_path, word_timestamps=True, vad_filter=True
            )
            entries: List[Dict[str, Any]] = []
            for segment in segments:
                text = str(getattr(segment, "text", "")).strip()
                if not text:
                    continue
                probability = getattr(segment, "avg_logprob", None)
                confidence = (
                    float(np.exp(probability)) if probability is not None else 0.6
                )
                entries.append(
                    {
                        "start": float(segment.start),
                        "end": float(segment.end),
                        "text": text,
                        "confidence": round(
                            min(TIER_CONFIDENCE_CEILING["asr"], max(0.0, confidence)), 4
                        ),
                    }
                )
            diagnostics.update(
                {
                    "available": bool(entries),
                    "engine": "faster_whisper",
                    "model": os.path.basename(model_path),
                    "language": getattr(info, "language", None),
                }
            )
            return entries, diagnostics
    except ImportError:
        pass
    except Exception as error:  # pragma: no cover - environment dependent
        diagnostics["faster_whisper_error"] = str(error)

    binary = os.environ.get("FLAGSHIPEDITOR_WHISPER_BIN", "").strip()
    if binary and os.path.exists(binary) and model_path and os.path.exists(model_path):
        diagnostics["attempted"].append("whisper_cpp")
        import subprocess
        import tempfile

        try:
            with tempfile.TemporaryDirectory() as workdir:
                prefix = os.path.join(workdir, "out")
                subprocess.run(
                    [binary, "-m", model_path, "-f", audio_path, "-oj", "-of", prefix],
                    check=True,
                    capture_output=True,
                    timeout=1800,
                )
                with open(prefix + ".json", "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            entries = []
            for item in payload.get("transcription", []):
                text = str(item.get("text", "")).strip()
                offsets = item.get("offsets") or {}
                if not text or "from" not in offsets:
                    continue
                entries.append(
                    {
                        "start": float(offsets["from"]) / 1000.0,
                        "end": float(offsets.get("to", offsets["from"])) / 1000.0,
                        "text": text,
                        "confidence": TIER_CONFIDENCE_CEILING["asr"] * 0.8,
                    }
                )
            diagnostics.update(
                {
                    "available": bool(entries),
                    "engine": "whisper_cpp",
                    "model": os.path.basename(model_path),
                }
            )
            return entries, diagnostics
        except Exception as error:  # pragma: no cover - environment dependent
            diagnostics["whisper_cpp_error"] = str(error)

    diagnostics["verdict"] = "no_local_model_installed"
    return [], diagnostics


# ---------------------------------------------------------------------------
# Semantics
# ---------------------------------------------------------------------------


class LyricLine(NamedTuple):
    """One lyric line with its timing, its meaning and how far to trust both."""

    index: int
    text: str
    start: Optional[float]
    end: Optional[float]
    timing_confidence: float
    fields: Tuple[Tuple[str, float], ...]
    imagery: Tuple[str, ...]
    valence: float
    intensity: float
    address: str
    is_ad_lib: bool
    interpretation_confidence: float
    alternatives: Tuple[Tuple[str, float], ...]
    timing_source: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "timingConfidence": round(self.timing_confidence, 4),
            "fields": [{"field": name, "weight": round(weight, 4)} for name, weight in self.fields],
            "imagery": list(self.imagery),
            "valence": round(self.valence, 4),
            "intensity": round(self.intensity, 4),
            "address": self.address,
            "isAdLib": self.is_ad_lib,
            "interpretationConfidence": round(self.interpretation_confidence, 4),
            "alternatives": [
                {"field": name, "weight": round(weight, 4)} for name, weight in self.alternatives
            ],
            "timingSource": self.timing_source,
        }


def analyse_line(text: str, index: int = 0) -> Dict[str, Any]:
    """Extract what a single line can support, and how confidently.

    The output separates three things the shipped engine conflates by having
    none of them: what the line *names* (fields and imagery), how it *feels*
    (valence and intensity), and how far either can be trusted. A line made
    entirely of ad-libs is marked as such and contributes delivery energy
    without contributing meaning.
    """
    tokens = tokenize(text)
    if not tokens:
        return {
            "fields": (),
            "imagery": (),
            "valence": 0.0,
            "intensity": 0.0,
            "address": "none",
            "is_ad_lib": False,
            "confidence": 0.0,
            "alternatives": (),
        }

    ad_lib_hits = sum(1 for token in tokens if token in AD_LIB_TOKENS)
    is_ad_lib = ad_lib_hits >= max(1, int(len(tokens) * 0.6))

    scores: Dict[str, float] = {}
    alternatives: Dict[str, float] = {}
    matched = 0
    foreign = 0

    # Idioms first: "day one" is loyalty, while "day" and "one" on their own
    # mean nothing. Matched tokens are consumed so the single-token pass cannot
    # score them a second time.
    normalised = " ".join(tokens)
    consumed = 0
    for phrase, (field, weight) in IDIOMS.items():
        if phrase in normalised:
            occurrences = normalised.count(phrase)
            scores[field] = scores.get(field, 0.0) + weight * occurrences
            consumed += len(phrase.split()) * occurrences
    matched += consumed

    for token in tokens:
        if token in CREOLE_MARKERS or token in FRENCH_MARKERS:
            foreign += 1
            continue
        if token in AMBIGUOUS_TERMS:
            matched += 1
            senses = AMBIGUOUS_TERMS[token]
            best_field, best_weight = senses[0]
            scores[best_field] = scores.get(best_field, 0.0) + best_weight
            for field, weight in senses[1:]:
                alternatives[field] = alternatives.get(field, 0.0) + weight
            continue
        entry = LEXICON.get(token)
        if entry:
            matched += 1
            field, weight, _regions = entry
            scores[field] = scores.get(field, 0.0) + weight

    # "I"/"you"/"we" are grammar, not subject matter. They set who the line
    # addresses, which decides performance-versus-narrative footage, but they
    # must not be allowed to make every line "about the self".
    address = "none"
    lowered = set(tokens)
    if lowered & {"i", "me", "my", "myself", "mine"}:
        address = "first_person"
    if lowered & {"you", "your", "yours"}:
        address = "second_person" if address == "none" else "dialogue"
    if lowered & {"we", "us", "our"}:
        address = "collective" if address == "none" else address
    if address != "none":
        scores["self"] = scores.get("self", 0.0) * 0.5

    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    ranked = [(name, weight) for name, weight in ranked if weight > 0.0][:4]

    imagery: List[str] = []
    for name, _weight in ranked:
        for item in SEMANTIC_FIELDS.get(name, {}).get("imagery", ()):
            if item not in imagery:
                imagery.append(item)

    if ranked:
        total = sum(weight for _name, weight in ranked)
        valence = sum(
            SEMANTIC_FIELDS.get(name, {}).get("valence", 0.0) * weight for name, weight in ranked
        ) / max(1e-6, total)
        intensity = sum(
            SEMANTIC_FIELDS.get(name, {}).get("intensity", 0.3) * weight for name, weight in ranked
        ) / max(1e-6, total)
    else:
        valence, intensity = 0.0, 0.3

    # Confidence is a coverage measure: what share of the line did the lexicon
    # actually recognise? A line of twelve words with one hit is a line we do
    # not understand, and saying so is the whole point.
    coverage = matched / max(1, len(tokens))
    confidence = max(0.0, min(1.0, coverage * 1.6))
    if is_ad_lib:
        # Ad-libs are correctly "understood" as carrying no imagery. That is a
        # confident *negative*, not a confident interpretation.
        confidence = 0.0
        imagery = []
        ranked = []
    if foreign:
        # A passage in a language the lexicon does not cover gets its
        # confidence cut in proportion, rather than being scored as if the
        # unrecognised words were meaningless English.
        confidence *= max(0.0, 1.0 - foreign / max(1, len(tokens)))

    alternative_list = tuple(
        sorted(
            ((name, weight) for name, weight in alternatives.items() if name not in scores),
            key=lambda item: (-item[1], item[0]),
        )[:3]
    )

    return {
        "fields": tuple(ranked),
        "imagery": tuple(imagery[:6]),
        "valence": float(valence),
        "intensity": float(max(intensity, 0.75 if is_ad_lib else 0.0)),
        "address": address,
        "is_ad_lib": is_ad_lib,
        "confidence": float(confidence),
        "alternatives": alternative_list,
    }


def find_repeated_lines(lines: Sequence[str], min_repeats: int = 2) -> Dict[str, int]:
    """Return normalised lines that recur, with their counts.

    A hook is the line the song keeps returning to. Detecting it from the text
    is far more reliable than inferring it from energy alone, and it is what
    lets the editor treat the third chorus as a *callback* rather than as
    another stretch of footage to fill.
    """
    counts: Dict[str, int] = {}
    for line in lines or []:
        key = " ".join(tokenize(line))
        if len(key) < 4:
            continue
        counts[key] = counts.get(key, 0) + 1
    return {key: value for key, value in counts.items() if value >= min_repeats}


class LyricAnalysis(NamedTuple):
    """Everything the editor knows about the words, and how far to trust it."""

    tier: str
    lines: Tuple[LyricLine, ...]
    vocal_segments: Tuple[VocalSegment, ...]
    hook_lines: Tuple[str, ...]
    languages: Dict[str, float]
    overall_confidence: float
    diagnostics: Dict[str, Any]

    @property
    def has_text(self) -> bool:
        return bool(self.lines)

    @property
    def can_interpret(self) -> bool:
        """Whether meaning may steer imagery at all."""
        return self.overall_confidence >= MIN_INTERPRETATION_CONFIDENCE and self.has_text

    def vocal_entries(self) -> List[float]:
        return [segment.start for segment in self.vocal_segments]

    def vocal_exits(self) -> List[float]:
        return [segment.end for segment in self.vocal_segments]

    def line_at(self, time_value: float) -> Optional[LyricLine]:
        """The line sounding at a moment, or ``None``."""
        for line in self.lines:
            if line.start is None or line.end is None:
                continue
            if line.start <= time_value < line.end:
                return line
        return None

    def in_vocal_rest(self, start: float, end: float) -> bool:
        """True when no measured vocal overlaps the window — room to breathe."""
        for segment in self.vocal_segments:
            if segment.start < end and segment.end > start:
                return False
        return bool(self.vocal_segments)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier,
            "overallConfidence": round(self.overall_confidence, 4),
            "canInterpret": self.can_interpret,
            "lines": [line.as_dict() for line in self.lines],
            "vocalSegments": [
                {
                    "start": round(segment.start, 4),
                    "end": round(segment.end, 4),
                    "confidence": segment.confidence,
                }
                for segment in self.vocal_segments
            ],
            "hookLines": list(self.hook_lines),
            "languages": self.languages,
            "diagnostics": self.diagnostics,
        }


def empty_analysis(reason: str = "no_input") -> LyricAnalysis:
    """A well-formed 'we know nothing' result, so callers need no None checks."""
    return LyricAnalysis(
        tier="vocal_only",
        lines=(),
        vocal_segments=(),
        hook_lines=(),
        languages={},
        overall_confidence=0.0,
        diagnostics={"verdict": reason},
    )


def analyse_lyrics(
    lyric_text: str = "",
    lyric_filename: str = "",
    audio_path: str = "",
    duration: float = 0.0,
    vocal_segments: Optional[Sequence[VocalSegment]] = None,
    allow_asr: bool = True,
) -> LyricAnalysis:
    """Acquire the strongest available lyric evidence and analyse it.

    The tier order is fixed and each step is skipped rather than faked when its
    inputs are missing, so the result always reports what actually happened.
    """
    diagnostics: Dict[str, Any] = {"tiersTried": []}
    segments = list(vocal_segments or [])
    timed: List[Dict[str, Any]] = []
    tier = "vocal_only"

    kind, entries, plain_lines = load_lyric_source(lyric_text, lyric_filename)
    diagnostics["suppliedFormat"] = kind if (lyric_text or "").strip() else "none"

    if kind == "timecoded" and entries:
        diagnostics["tiersTried"].append("timecoded")
        timed = entries
        tier = "timecoded"
    elif allow_asr and audio_path:
        diagnostics["tiersTried"].append("asr")
        transcribed, asr_diagnostics = transcribe_local(audio_path)
        diagnostics["asr"] = asr_diagnostics
        if transcribed:
            timed = transcribed
            tier = "asr"
            if not plain_lines:
                plain_lines = [entry["text"] for entry in transcribed]

    if not timed and plain_lines:
        diagnostics["tiersTried"].append("aligned")
        aligned = align_lines_to_vocals(plain_lines, segments, duration)
        if aligned:
            timed = aligned
            tier = "aligned"

    if not timed:
        diagnostics["tiersTried"].append("vocal_only")

    ceiling = TIER_CONFIDENCE_CEILING.get(tier, 0.0)
    texts = [str(entry.get("text", "")) for entry in timed]
    repeated = find_repeated_lines(texts)
    hook_keys = set(repeated)

    lines: List[LyricLine] = []
    for position, entry in enumerate(timed):
        text = str(entry.get("text", "")).strip()
        if not text:
            continue
        semantics = analyse_line(text, position)
        start = entry.get("start")
        end = entry.get("end")
        try:
            start = float(start) if start is not None else None
        except (TypeError, ValueError):
            start = None
        try:
            end = float(end) if end is not None else None
        except (TypeError, ValueError):
            end = None
        if start is not None and end is None:
            following = timed[position + 1].get("start") if position + 1 < len(timed) else None
            try:
                end = float(following) if following is not None else min(duration, start + 3.0)
            except (TypeError, ValueError):
                end = start + 3.0
        if start is not None and end is not None and end <= start:
            end = start + 0.4

        timing_confidence = float(entry.get("confidence", ceiling))
        timing_confidence = max(0.0, min(ceiling, timing_confidence))
        if start is None:
            timing_confidence = 0.0

        interpretation = min(semantics["confidence"], ceiling)
        lines.append(
            LyricLine(
                index=position,
                text=text,
                start=start,
                end=end,
                timing_confidence=timing_confidence,
                fields=semantics["fields"],
                imagery=semantics["imagery"],
                valence=semantics["valence"],
                intensity=semantics["intensity"],
                address=semantics["address"],
                is_ad_lib=semantics["is_ad_lib"],
                interpretation_confidence=interpretation,
                alternatives=semantics["alternatives"],
                timing_source=str(entry.get("timing_source", tier)),
            )
        )

    languages = detect_languages(texts)
    if lines:
        timed_lines = [line for line in lines if line.start is not None]
        coverage = len(timed_lines) / max(1, len(lines))
        mean_interpretation = float(
            np.mean([line.interpretation_confidence for line in lines])
        )
        overall = min(ceiling, coverage * 0.5 + mean_interpretation * 0.5)
    else:
        overall = 0.0

    hook_texts = tuple(
        sorted(hook_keys, key=lambda key: (-repeated[key], key))[:4]
    )

    diagnostics["lineCount"] = len(lines)
    diagnostics["timedLineCount"] = sum(1 for line in lines if line.start is not None)
    diagnostics["vocalSegmentCount"] = len(segments)
    diagnostics["repeatedLineCount"] = len(repeated)

    return LyricAnalysis(
        tier=tier,
        lines=tuple(lines),
        vocal_segments=tuple(segments),
        hook_lines=hook_texts,
        languages=languages,
        overall_confidence=float(max(0.0, min(1.0, overall))),
        diagnostics=diagnostics,
    )
