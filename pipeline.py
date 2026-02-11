"""
Pipeline — Full video generation pipeline (fresh generation mode).

Flow:
  1. generate_script(topic) → GeneratedScript with pitch_drops
     -> Save pitch_markers.json
  2. generate_voice(full_script) → voice.mp3 + word_timestamps
     -> 1.2x speed+pitch via asetrate
  3. apply_speed_curve (uniform 1.2x)
  4. resolve_pitch_cues(pitch_drops, word_timestamps) → [{start, end, semitones}]
     -> Same cues used for vine boom SFX
  4b. apply_pitch_drops(audio, pitch_cues) → Praat PSOLA
  5-7. captions, audio mix, video composite

Usage:
    py pipeline.py "topic here"
    py pipeline.py --reuse                # skip script+voice, reuse existing output/
    py pipeline.py --script "manual script with *drops*(-4)"
"""

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
OUTPUT_DIR = PROJECT_ROOT / "output"
ASSETS_DIR = PROJECT_ROOT / "assets"


def _ffmpeg() -> str:
    """Return the correct ffmpeg command for the current environment."""
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    if shutil.which("ffmpeg.exe"):
        return "ffmpeg.exe"
    raise FileNotFoundError("ffmpeg not found — install it or add it to PATH")

# Ensure engines/ is importable
sys.path.insert(0, str(PROJECT_ROOT))

from engines.script_engine import GeneratedScript, generate_script_claude
from engines.pitch_engine import (
    apply_pitch_drops,
    get_auto_pitch_cues,
    parse_marked_script,
    resolve_pitch_cues,
)


# ---------------------------------------------------------------------------
# Voice generation (ElevenLabs)
# ---------------------------------------------------------------------------

ADAM_VOICE_ID = "pNInz6obpgDQGcFmaJgB"


def generate_voice(
    script_text: str,
    output_dir: Path = OUTPUT_DIR,
    voice_id: str = ADAM_VOICE_ID,
) -> tuple[str, list[dict]]:
    """Generate voice audio via ElevenLabs with word-level timestamps.

    Returns:
        (voice_path, word_timestamps) where voice_path is the .mp3 file
        and word_timestamps is [{word, start, end}].
    """
    from elevenlabs.client import ElevenLabs
    from elevenlabs import VoiceSettings

    client = ElevenLabs()  # Uses ELEVEN_API_KEY env var

    response = client.text_to_speech.convert_with_timestamps(
        voice_id=voice_id,
        text=script_text,
        model_id="eleven_v3",
        output_format="mp3_44100_128",
        voice_settings=VoiceSettings(
            stability=0.5,
            similarity_boost=0.75,
            style=0.0,
            speed=1.0,
            use_speaker_boost=True,
        ),
    )

    # Save audio
    output_dir.mkdir(parents=True, exist_ok=True)
    voice_path = str(output_dir / "voice.mp3")
    audio_bytes = base64.b64decode(response.audio_base64)
    with open(voice_path, "wb") as f:
        f.write(audio_bytes)

    # Extract word timestamps from character-level alignment
    chars = response.alignment.characters
    starts = response.alignment.character_start_times_seconds
    ends = response.alignment.character_end_times_seconds

    word_timestamps = []
    current_word = ""
    word_start = None
    for i, char in enumerate(chars):
        if char == " ":
            if current_word:
                word_timestamps.append({
                    "word": current_word,
                    "start": word_start,
                    "end": ends[i - 1],
                })
                current_word = ""
                word_start = None
        else:
            if word_start is None:
                word_start = starts[i]
            current_word += char
    if current_word:
        word_timestamps.append({
            "word": current_word,
            "start": word_start,
            "end": ends[-1],
        })

    # Save timestamps
    ts_path = str(output_dir / "word_timestamps.json")
    with open(ts_path, "w") as f:
        json.dump(word_timestamps, f, indent=2)

    print(f"  Voice: {voice_path} ({len(audio_bytes)} bytes)")
    print(f"  Timestamps: {len(word_timestamps)} words, "
          f"{word_timestamps[-1]['end']:.1f}s duration")

    return voice_path, word_timestamps


# ---------------------------------------------------------------------------
# Speed/pitch adjustment (FFmpeg asetrate for uniform 1.2x)
# ---------------------------------------------------------------------------

def apply_speed_curve(
    voice_path: str,
    speed: float = 1.2,
    output_dir: Path = OUTPUT_DIR,
) -> tuple[str, list[dict]]:
    """Apply uniform speed+pitch increase via FFmpeg asetrate.

    asetrate changes sample rate (speeds up + raises pitch together),
    then aresample converts back to 44100Hz for downstream compatibility.

    Also scales word_timestamps to match the new speed.

    Returns:
        (sped_up_path, scaled_timestamps)
    """
    output_path = str(output_dir / "voice_fast.wav")
    target_rate = int(44100 * speed)

    subprocess.run(
        [
            _ffmpeg(), "-y", "-i", voice_path,
            "-af", f"asetrate={target_rate},aresample=44100",
            output_path,
        ],
        capture_output=True,
        check=True,
    )

    # Scale timestamps
    ts_path = str(output_dir / "word_timestamps.json")
    with open(ts_path) as f:
        word_timestamps = json.load(f)

    scaled = []
    for w in word_timestamps:
        scaled.append({
            "word": w["word"],
            "start": round(w["start"] / speed, 3),
            "end": round(w["end"] / speed, 3),
        })

    # Save scaled timestamps to separate file (keep originals for timeline editor)
    scaled_ts_path = str(output_dir / "word_timestamps_fast.json")
    with open(scaled_ts_path, "w") as f:
        json.dump(scaled, f, indent=2)

    duration = scaled[-1]["end"] if scaled else 0
    print(f"  Speed: {speed}x applied → {duration:.1f}s final duration")

    if duration > 40:
        print(f"  WARNING: Final duration {duration:.1f}s exceeds 40s target!")

    return output_path, scaled


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    topic: str = "",
    manual_script: str = "",
    reuse: bool = False,
    speed: float = 1.2,
    provider: str = "claude",
):
    """Run the full video generation pipeline.

    Args:
        topic: Topic for AI script generation.
        manual_script: Manually-written script (with optional *phrase*(-N) markup).
        reuse: If True, skip script+voice generation and reuse existing output/.
        speed: Playback speed multiplier (default 1.2x).
        provider: AI provider for script generation ("claude" or "openai").
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    pitch_drops = []
    script_text = ""

    # ── Step 1: Script ────────────────────────────────────────────────
    if reuse:
        print("\n[1/7] Reusing existing output (--reuse)")
        # Try to load pitch markers from previous run
        markers_path = OUTPUT_DIR / "pitch_markers.json"
        if markers_path.exists():
            with open(markers_path) as f:
                pitch_drops = json.load(f)
            print(f"  Loaded {len(pitch_drops)} pitch drops from pitch_markers.json")
        else:
            print("  No pitch_markers.json found — will fall back to AI pitch cues")

    elif manual_script:
        print("\n[1/7] Using manual script")
        script_text, pitch_drops = parse_marked_script(manual_script)
        print(f"  Script: {len(script_text.split())} words")
        print(f"  Pitch drops parsed: {len(pitch_drops)}")

        # Save pitch markers
        with open(OUTPUT_DIR / "pitch_markers.json", "w") as f:
            json.dump(pitch_drops, f, indent=2)

    else:
        print(f"\n[1/7] Generating script for: {topic}")
        script = generate_script_claude(topic=topic) if provider == "claude" else None
        if script is None:
            from engines.script_engine import generate_script_openai
            script = generate_script_openai(topic=topic)

        script_text = script.full_script
        pitch_drops = [d.model_dump() for d in script.pitch_drops]

        print(f"  Title: {script.title}")
        print(f"  Words: {script.word_count}")
        print(f"  Pitch drops: {len(pitch_drops)}")
        for d in pitch_drops:
            print(f"    \"{d['phrase']}\" → {d['semitones']} semitones")

        # Save script + pitch markers
        with open(OUTPUT_DIR / "script.json", "w") as f:
            json.dump(script.model_dump(), f, indent=2)
        with open(OUTPUT_DIR / "pitch_markers.json", "w") as f:
            json.dump(pitch_drops, f, indent=2)
        with open(OUTPUT_DIR / "script.txt", "w") as f:
            f.write(script_text)

    # ── Step 2: Voice (skip if reuse) ─────────────────────────────────
    voice_path = str(OUTPUT_DIR / "voice.mp3")
    ts_path = str(OUTPUT_DIR / "word_timestamps.json")

    if reuse:
        print("\n[2/7] Reusing existing voice + timestamps")
        if not os.path.exists(voice_path):
            print(f"  ERROR: {voice_path} not found!")
            sys.exit(1)
        if not os.path.exists(ts_path):
            print(f"  ERROR: {ts_path} not found!")
            sys.exit(1)
        with open(ts_path) as f:
            word_timestamps = json.load(f)
        print(f"  Loaded {len(word_timestamps)} word timestamps")
    else:
        print(f"\n[2/7] Generating voice (ElevenLabs)")
        voice_path, word_timestamps = generate_voice(script_text)

    # ── Step 3: Speed curve (1.2x) ───────────────────────────────────
    print(f"\n[3/7] Applying {speed}x speed + pitch")
    voice_fast_path, scaled_timestamps = apply_speed_curve(voice_path, speed=speed)

    # ── Step 4: Resolve pitch cues ────────────────────────────────────
    print("\n[4/7] Resolving pitch cues")
    if pitch_drops:
        pitch_cues = resolve_pitch_cues(pitch_drops, scaled_timestamps)
        print(f"  Resolved {len(pitch_cues)} pitch cues from script markers")
    else:
        # Fallback: legacy AI-based pitch cue detection
        print("  No script pitch drops — falling back to AI detection (legacy)")
        full_text = " ".join(w["word"] for w in scaled_timestamps)
        pitch_cues = get_auto_pitch_cues(full_text, scaled_timestamps)
        print(f"  AI detected {len(pitch_cues)} pitch cues")

    for cue in pitch_cues:
        print(f"    [{cue['start']:.2f}-{cue['end']:.2f}] {cue['semitones']} semitones")

    # Save resolved cues
    with open(OUTPUT_DIR / "pitch_cues.json", "w") as f:
        json.dump(pitch_cues, f, indent=2)

    # ── Step 4b: Apply pitch drops (Praat PSOLA) ─────────────────────
    print("\n[4b/7] Applying pitch drops (Praat PSOLA)")
    if pitch_cues:
        pitched_path = apply_pitch_drops(voice_fast_path, pitch_cues)
        print(f"  Output: {pitched_path}")
    else:
        pitched_path = voice_fast_path
        print("  No pitch cues — skipping")

    # ── Step 5: Vine boom SFX placement ──────────────────────────────
    print("\n[5/7] Placing vine boom SFX at pitch drop points")
    sfx_placements = []
    vine_boom_path = ASSETS_DIR / "sfx" / "emphasis" / "vine-boom.mp3"

    if vine_boom_path.exists():
        for cue in pitch_cues:
            sfx_placements.append({
                "sfx_path": str(vine_boom_path),
                "time": cue["end"],  # Place boom right after the pitched word
                "volume": 0.7,
            })
        print(f"  {len(sfx_placements)} vine booms placed")
    else:
        print(f"  Vine boom not found at {vine_boom_path} — skipping SFX")

    # Save SFX placements for downstream steps
    with open(OUTPUT_DIR / "sfx_placements.json", "w") as f:
        json.dump(sfx_placements, f, indent=2)

    # ── Steps 6-7: Captions, audio mix, video composite ──────────────
    print("\n[6/7] Captions + audio mix")
    print("  TODO: Caption rendering (Pillow + pilmoji)")
    print("  TODO: Audio mix (voice + SFX + background music)")

    print("\n[7/7] Video composite")
    print("  TODO: FFmpeg composite (gameplay + captions + memes)")

    # ── Summary ───────────────────────────────────────────────────────
    print("\n" + "=" * 50)
    print("Pipeline complete!")
    print(f"  Pitched audio: {pitched_path}")
    print(f"  Pitch cues: {len(pitch_cues)}")
    print(f"  SFX placements: {len(sfx_placements)}")
    print("=" * 50)

    return {
        "pitched_audio": pitched_path,
        "pitch_cues": pitch_cues,
        "sfx_placements": sfx_placements,
        "word_timestamps": scaled_timestamps,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Video Factory Pipeline")
    parser.add_argument("topic", nargs="?", default="", help="Topic for script generation")
    parser.add_argument("--reuse", action="store_true",
                        help="Reuse existing voice + timestamps (no API calls)")
    parser.add_argument("--script", type=str, default="",
                        help="Manual script text (supports *phrase*(-N) markup)")
    parser.add_argument("--speed", type=float, default=1.2,
                        help="Playback speed multiplier (default: 1.2)")
    parser.add_argument("--provider", choices=["claude", "openai"], default="claude",
                        help="AI provider for script generation")

    args = parser.parse_args()

    if not args.topic and not args.reuse and not args.script:
        parser.error("Provide a topic, --reuse, or --script")

    run_pipeline(
        topic=args.topic,
        manual_script=args.script,
        reuse=args.reuse,
        speed=args.speed,
        provider=args.provider,
    )


if __name__ == "__main__":
    main()
