"""
Pitch Engine — Resolves script-level pitch drop markers into timestamped cues,
applies Praat PSOLA pitch shifts, and parses inline markup for manual scripts.

Pitch drops are now decided at script-writing time (in script_engine.py).
This module converts those markers into the [{start, end, semitones}] format
that apply_pitch_drops() needs.
"""

import json
import os
import re
import shutil
import string
import subprocess
from pathlib import Path


def _ffmpeg() -> str:
    """Return the correct ffmpeg command for the current environment."""
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    if shutil.which("ffmpeg.exe"):
        return "ffmpeg.exe"
    raise FileNotFoundError("ffmpeg not found — install it or add it to PATH")
from typing import Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_word(w: str) -> str:
    """Strip punctuation and lowercase for fuzzy matching.

    >>> _normalize_word("crime?")
    'crime'
    >>> _normalize_word("HELLO!!!")
    'hello'
    >>> _normalize_word("it's")
    "it's"
    """
    # Strip leading/trailing punctuation but keep internal apostrophes
    w = w.strip()
    w = w.lower()
    # Strip punctuation from both ends
    while w and w[0] in string.punctuation and w[0] != "'":
        w = w[1:]
    while w and w[-1] in string.punctuation and w[-1] != "'":
        w = w[:-1]
    return w


# ---------------------------------------------------------------------------
# resolve_pitch_cues — match phrases to word timestamps
# ---------------------------------------------------------------------------

def resolve_pitch_cues(
    pitch_drops: list[dict],
    word_timestamps: list[dict],
) -> list[dict]:
    """Match pitch drop phrases to word timestamps and return timed cues.

    Args:
        pitch_drops: List of {"phrase": str, "semitones": int} from the script.
        word_timestamps: List of {"word": str, "start": float, "end": float}
                         from ElevenLabs or other TTS.

    Returns:
        List of {"start": float, "end": float, "semitones": int} sorted by start time.
        Same format that apply_pitch_drops() expects.

    Matching algorithm:
        1. Normalize all words (strip punctuation, lowercase)
        2. For each phrase, split into target words
        3. Slide through word_timestamps looking for consecutive normalized match
        4. If full phrase match fails, fall back to matching just the last word
        5. Track used indices to prevent overlapping matches
    """
    if not pitch_drops or not word_timestamps:
        return []

    # Pre-normalize all timestamp words
    normalized_ts = [_normalize_word(w["word"]) for w in word_timestamps]
    used_indices: set[int] = set()
    cues = []

    for drop in pitch_drops:
        phrase = drop.get("phrase", "")
        semitones = drop.get("semitones", -4)
        if not phrase:
            continue

        target_words = [_normalize_word(w) for w in phrase.split()]
        if not target_words:
            continue

        match_indices = _find_consecutive_match(target_words, normalized_ts, used_indices)

        # Fallback: try matching just the last word of the phrase
        if match_indices is None and len(target_words) > 1:
            match_indices = _find_consecutive_match(
                [target_words[-1]], normalized_ts, used_indices
            )

        if match_indices is not None:
            used_indices.update(match_indices)
            start_ts = word_timestamps[match_indices[0]]
            end_ts = word_timestamps[match_indices[-1]]
            cues.append({
                "start": start_ts["start"],
                "end": end_ts["end"],
                "semitones": semitones,
            })

    # Sort by start time
    cues.sort(key=lambda c: c["start"])
    return cues


def _find_consecutive_match(
    target_words: list[str],
    normalized_ts: list[str],
    used_indices: set[int],
) -> Optional[list[int]]:
    """Slide through normalized_ts looking for a consecutive match of target_words.

    Returns the list of matched indices, or None if no match found.
    Skips positions that overlap with used_indices.
    """
    n = len(target_words)
    for i in range(len(normalized_ts) - n + 1):
        indices = list(range(i, i + n))

        # Skip if any index already used
        if any(idx in used_indices for idx in indices):
            continue

        # Check all words match
        if all(normalized_ts[i + j] == target_words[j] for j in range(n)):
            return indices

    return None


# ---------------------------------------------------------------------------
# parse_marked_script — inline markup for manual scripts
# ---------------------------------------------------------------------------

def parse_marked_script(text: str) -> tuple[str, list[dict]]:
    """Parse inline pitch drop markup from manually-written scripts.

    Markup format: *phrase*(-N) where N is semitones (positive integer after minus).

    Example:
        "...sound like a literal *war crime*(-4)? ...the *purge siren*(-5)."

    Returns:
        (clean_text, pitch_drops) where:
        - clean_text: text with markers stripped, ready for TTS
        - pitch_drops: [{"phrase": str, "semitones": int}]
    """
    pattern = r'\*([^*]+)\*\((-?\d+)\)'
    pitch_drops = []

    for match in re.finditer(pattern, text):
        phrase = match.group(1)
        semitones = int(match.group(2))
        pitch_drops.append({
            "phrase": phrase,
            "semitones": semitones,
        })

    # Strip markers to get clean text for TTS
    clean_text = re.sub(pattern, r'\1', text)

    return clean_text, pitch_drops


# ---------------------------------------------------------------------------
# apply_pitch_drops — Praat PSOLA pitch shifting
# ---------------------------------------------------------------------------

def apply_pitch_drops(
    voice_path: str,
    pitch_cues: list[dict],
    output_filename: str = "voice_pitched.wav",
) -> str:
    """Apply pitch drops to audio using Praat's TD-PSOLA algorithm.

    Args:
        voice_path: Path to the input audio file (mp3 or wav).
        pitch_cues: List of {"start": float, "end": float, "semitones": int}.
        output_filename: Name for the output file (saved in same dir as voice_path).

    Returns:
        Path to the pitch-shifted output file.

    Uses parselmouth (Python Praat wrapper) for high-quality pitch manipulation
    via TD-PSOLA (Time-Domain Pitch-Synchronous Overlap-Add):
    - Detects glottal pulses in the waveform
    - Extracts pitch-synchronous windows
    - Repositions windows to change pitch
    - Reconstructs with minimal artifacts on unmodified regions
    """
    import parselmouth
    from parselmouth.praat import call

    output_dir = Path(voice_path).parent
    output_path = str(output_dir / output_filename)

    if not pitch_cues:
        # No pitch drops — just copy the file
        import shutil
        shutil.copy2(voice_path, output_path)
        return output_path

    # Convert to WAV if needed (Praat works best with WAV)
    wav_path = voice_path
    if not voice_path.lower().endswith(".wav"):
        wav_path = str(output_dir / "_temp_for_praat.wav")
        subprocess.run(
            [_ffmpeg(), "-y", "-i", voice_path, "-ar", "44100", "-ac", "1", wav_path],
            capture_output=True,
            check=True,
        )

    # Load into Praat
    sound = parselmouth.Sound(wav_path)

    # Create manipulation object for PSOLA
    manipulation = call(sound, "To Manipulation", 0.01, 75, 600)
    pitch_tier = call(manipulation, "Extract pitch tier")

    # Clear existing pitch points and rebuild with modifications
    original_pitch = call(sound, "To Pitch", 0.0, 75, 600)

    # Get the pitch tier from the manipulation
    # We'll add points that scale the pitch in the cue regions
    for cue in pitch_cues:
        start = cue["start"]
        end = cue["end"]
        semitones = cue["semitones"]
        target_factor = 2 ** (semitones / 12.0)
        phrase_duration = end - start

        # Wide zones so the shift never sounds abrupt
        lead_in = 0.3   # 300ms ramp into the drop
        hold = phrase_duration  # full phrase at deepest pitch
        tail_out = 0.4  # 400ms smooth recovery after

        region_start = max(0, start - lead_in)
        region_end = min(sound.duration, end + tail_out)

        step = 0.005  # 5ms steps for smooth curve
        t = region_start
        while t <= region_end:
            try:
                orig_f0 = call(original_pitch, "Get value at time", t, "Hertz", "Linear")
                if orig_f0 and orig_f0 > 0:
                    if t < start:
                        # Lead-in: smooth ease from normal → ~30% depth
                        # Uses sine curve for natural-sounding onset
                        import math
                        progress = (t - region_start) / lead_in if lead_in > 0 else 1.0
                        progress = max(0.0, min(1.0, progress))
                        # sine ease-in: slow start, accelerates
                        depth = 0.3 * (1.0 - math.cos(progress * math.pi / 2))
                    elif t <= end:
                        # Main phrase: slide from 30% → 100% depth
                        # Linear slide through the phrase — deepest at last syllable
                        progress = (t - start) / phrase_duration if phrase_duration > 0 else 1.0
                        progress = max(0.0, min(1.0, progress))
                        depth = 0.3 + progress * 0.7
                    else:
                        # Tail-out: ease from 100% back to normal
                        # Sine ease-out: starts fast, slows to a gentle landing
                        import math
                        progress = (t - end) / tail_out if tail_out > 0 else 1.0
                        progress = max(0.0, min(1.0, progress))
                        depth = math.cos(progress * math.pi / 2)  # 1.0 → 0.0

                    effective_factor = 1.0 + (target_factor - 1.0) * depth
                    new_f0 = orig_f0 * effective_factor
                    call(pitch_tier, "Add point", t, new_f0)
            except Exception:
                pass  # Skip if pitch undefined at this point (silence/unvoiced)
            t += step

    # Replace pitch tier and resynthesize
    call([pitch_tier, manipulation], "Replace pitch tier")
    result_sound = call(manipulation, "Get resynthesis (overlap-add)")

    # Save output
    result_sound.save(output_path, parselmouth.SoundFileFormat.WAV)

    # Clean up temp WAV
    if wav_path != voice_path and os.path.exists(wav_path):
        os.remove(wav_path)

    return output_path


# ---------------------------------------------------------------------------
# get_auto_pitch_cues — LEGACY (kept as fallback for old scripts)
# ---------------------------------------------------------------------------

def get_auto_pitch_cues(
    script_text: str,
    word_timestamps: list[dict],
) -> list[dict]:
    """[LEGACY] Use a Claude API call to decide pitch drop placement.

    This is the OLD approach — a separate API call after voice generation.
    Kept as a fallback for --reuse with old scripts that lack pitch_drops.

    Prefer resolve_pitch_cues() with script-embedded pitch_drops instead.

    Args:
        script_text: The full script text.
        word_timestamps: Word-level timestamps from TTS.

    Returns:
        List of {"start": float, "end": float, "semitones": int}.
    """
    import anthropic

    client = anthropic.Anthropic()

    # Build word list with timestamps for the prompt
    words_with_times = [
        f"{w['word']} [{w['start']:.2f}-{w['end']:.2f}]"
        for w in word_timestamps
    ]

    prompt = f"""Given this script and its word-level timestamps, pick 3-5 words/phrases \
that should be pitch-dropped for comedic emphasis (deeper voice for punchlines).

Script: {script_text}

Words with timestamps:
{chr(10).join(words_with_times)}

Return a JSON array of objects with "start", "end", and "semitones" fields.
Use semitones between -3 and -6. Pick punchline words, shocking claims, or absurd phrases.
Space them at least 2 seconds apart.

Return ONLY the JSON array, no other text."""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        temperature=0.3,
        messages=[{"role": "user", "content": prompt}],
    )

    try:
        result = json.loads(response.content[0].text)
        if isinstance(result, list):
            return result
    except (json.JSONDecodeError, IndexError):
        pass

    return []
