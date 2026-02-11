"""
Pipeline Runner — Reuse/editor mode for video generation.

Called by timeline_editor.py when the user clicks "Generate" in the web UI.
Also usable standalone for reprocessing existing voice + timestamps.

Flow:
  1. Load voice.mp3 + word_timestamps.json from output/
  2. apply_speed_curve (uniform 1.2x)
  3. Pitch drops:
     a. Manual pitch drops from editor? → use those
     b. pitch_markers.json exists? → resolve_pitch_cues()
     c. else → get_auto_pitch_cues() [legacy fallback]
  4. apply_pitch_drops (Praat PSOLA)
  5. Audio mix (voice + SFX + background music)
  6. Captions, memes, video composite

Usage (from timeline_editor.py):
    py engines/pipeline_runner.py '<sfx_placements_json>' '<options_json>'

Usage (standalone):
    py engines/pipeline_runner.py --standalone
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
ASSETS_DIR = PROJECT_ROOT / "assets"


def _ffmpeg() -> str:
    """Return the correct ffmpeg command for the current environment."""
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    if shutil.which("ffmpeg.exe"):
        return "ffmpeg.exe"
    raise FileNotFoundError("ffmpeg not found — install it or add it to PATH")

sys.path.insert(0, str(PROJECT_ROOT))

from engines.pitch_engine import (
    apply_pitch_drops,
    get_auto_pitch_cues,
    resolve_pitch_cues,
)


# ---------------------------------------------------------------------------
# Speed curve
# ---------------------------------------------------------------------------

def apply_speed_curve(
    voice_path: str,
    speed: float = 1.2,
) -> tuple[str, list[dict]]:
    """Apply uniform speed+pitch increase and scale timestamps.

    Returns (sped_up_path, scaled_timestamps).
    """
    output_path = str(OUTPUT_DIR / "voice_fast.wav")
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

    ts_path = OUTPUT_DIR / "word_timestamps.json"
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
    scaled_ts_path = str(OUTPUT_DIR / "word_timestamps_fast.json")
    with open(scaled_ts_path, "w") as f:
        json.dump(scaled, f, indent=2)

    return output_path, scaled


# ---------------------------------------------------------------------------
# Pitch drop resolution (3-tier fallback)
# ---------------------------------------------------------------------------

def resolve_pitch_drops(
    scaled_timestamps: list[dict],
    manual_pitch_drops: list[dict] | None = None,
) -> list[dict]:
    """Resolve pitch drops using 3-tier fallback strategy.

    Priority:
        1. Manual pitch drops from the editor UI (if provided)
        2. pitch_markers.json from script generation → resolve_pitch_cues()
        3. get_auto_pitch_cues() legacy AI fallback

    Args:
        scaled_timestamps: Word timestamps (already speed-scaled).
        manual_pitch_drops: Pitch drops from the editor UI, already in
                           [{start, end, semitones}] format.

    Returns:
        List of {"start": float, "end": float, "semitones": int}.
    """
    # Tier 1: Manual drops from editor
    if manual_pitch_drops:
        print(f"  Using {len(manual_pitch_drops)} manual pitch drops from editor")
        return manual_pitch_drops

    # Tier 2: pitch_markers.json → resolve_pitch_cues
    markers_path = OUTPUT_DIR / "pitch_markers.json"
    if markers_path.exists():
        with open(markers_path) as f:
            pitch_drops = json.load(f)
        if pitch_drops:
            cues = resolve_pitch_cues(pitch_drops, scaled_timestamps)
            print(f"  Resolved {len(cues)} pitch cues from pitch_markers.json")
            return cues

    # Tier 3: Legacy AI fallback
    print("  No pitch markers found — falling back to AI detection (legacy)")
    full_text = " ".join(w["word"] for w in scaled_timestamps)
    cues = get_auto_pitch_cues(full_text, scaled_timestamps)
    print(f"  AI detected {len(cues)} pitch cues")
    return cues


# ---------------------------------------------------------------------------
# Audio mix (voice + SFX + background music)
# ---------------------------------------------------------------------------

def mix_audio(
    voice_path: str,
    sfx_placements: list[dict],
    bg_music_path: str | None = None,
    bg_music_volume: float = 0.15,
) -> str:
    """Mix voice audio with SFX and optional background music.

    Returns path to the mixed audio file.
    """
    output_path = str(OUTPUT_DIR / "audio_mixed.wav")

    if not sfx_placements and not bg_music_path:
        # Nothing to mix — just use the voice as-is
        import shutil
        shutil.copy2(voice_path, output_path)
        return output_path

    # Build FFmpeg filter complex for mixing
    inputs = ["-i", voice_path]
    filter_parts = []
    input_idx = 1  # 0 = voice

    # Add SFX inputs
    for i, placement in enumerate(sfx_placements):
        sfx_path = placement.get("sfx_path", "")
        if not os.path.exists(sfx_path):
            continue
        delay_ms = int(placement["time"] * 1000)
        volume = placement.get("volume", 0.7)

        inputs.extend(["-i", sfx_path])
        filter_parts.append(
            f"[{input_idx}]adelay={delay_ms}|{delay_ms},volume={volume}[sfx{i}]"
        )
        input_idx += 1

    # Add background music
    if bg_music_path and os.path.exists(bg_music_path):
        inputs.extend(["-i", bg_music_path])
        filter_parts.append(
            f"[{input_idx}]volume={bg_music_volume}[bgm]"
        )
        input_idx += 1

    if not filter_parts:
        import shutil
        shutil.copy2(voice_path, output_path)
        return output_path

    # Build amix filter
    mix_inputs = "[0]"  # voice is always first
    for i in range(len(sfx_placements)):
        mix_inputs += f"[sfx{i}]"
    if bg_music_path and os.path.exists(bg_music_path):
        mix_inputs += "[bgm]"

    n_inputs = 1 + len([p for p in sfx_placements if os.path.exists(p.get("sfx_path", ""))])
    if bg_music_path and os.path.exists(bg_music_path):
        n_inputs += 1

    filter_parts.append(f"{mix_inputs}amix=inputs={n_inputs}:duration=first[out]")
    filter_graph = ";".join(filter_parts)

    cmd = ["ffmpeg", "-y"] + inputs + [
        "-filter_complex", filter_graph,
        "-map", "[out]",
        output_path,
    ]

    subprocess.run(cmd, capture_output=True, check=True)
    return output_path


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run(
    sfx_placements: list[dict] | None = None,
    options: dict | None = None,
):
    """Run the reuse/editor pipeline.

    Args:
        sfx_placements: SFX placements from the timeline editor.
        options: Pipeline options (base_speed, manual_pitch_drops, etc.).
    """
    if sfx_placements is None:
        sfx_placements = []
    if options is None:
        options = {}

    base_speed = options.get("base_speed", 1.2)
    manual_pitch_drops = options.get("manual_pitch_drops", None)

    voice_path = str(OUTPUT_DIR / "voice.mp3")
    ts_path = str(OUTPUT_DIR / "word_timestamps.json")

    # Validate inputs
    if not os.path.exists(voice_path):
        print(f"ERROR: {voice_path} not found!")
        sys.exit(1)
    if not os.path.exists(ts_path):
        print(f"ERROR: {ts_path} not found!")
        sys.exit(1)

    print("=" * 50)
    print("Pipeline Runner (reuse/editor mode)")
    print("=" * 50)

    # ── Step 1: Load existing data ────────────────────────────────────
    print(f"\n[1/6] Loading voice + timestamps")
    with open(ts_path) as f:
        word_timestamps = json.load(f)
    print(f"  Words: {len(word_timestamps)}")

    # ── Step 2: Speed curve ───────────────────────────────────────────
    print(f"\n[2/6] Applying {base_speed}x speed + pitch")
    voice_fast_path, scaled_timestamps = apply_speed_curve(voice_path, speed=base_speed)
    duration = scaled_timestamps[-1]["end"] if scaled_timestamps else 0
    print(f"  Duration: {duration:.1f}s")

    # ── Step 3: Resolve pitch drops (3-tier fallback) ─────────────────
    print(f"\n[3/6] Resolving pitch drops")
    pitch_cues = resolve_pitch_drops(scaled_timestamps, manual_pitch_drops)

    for cue in pitch_cues:
        print(f"    [{cue['start']:.2f}-{cue['end']:.2f}] {cue['semitones']} st")

    # Save resolved cues
    with open(OUTPUT_DIR / "pitch_cues.json", "w") as f:
        json.dump(pitch_cues, f, indent=2)

    # ── Step 4: Apply pitch drops ─────────────────────────────────────
    print(f"\n[4/6] Applying pitch drops (Praat PSOLA)")
    if pitch_cues:
        pitched_path = apply_pitch_drops(voice_fast_path, pitch_cues)
        print(f"  Output: {pitched_path}")
    else:
        pitched_path = voice_fast_path
        print("  No pitch cues — skipping")

    # ── Step 5: Audio mix ─────────────────────────────────────────────
    print(f"\n[5/6] Audio mix ({len(sfx_placements)} SFX placements)")
    # TODO: mix_audio when SFX mixing is implemented
    final_audio = pitched_path

    # ── Step 6: Captions + video composite ────────────────────────────
    print(f"\n[6/6] Captions + video composite")
    print("  TODO: Caption rendering + FFmpeg composite")

    print("\n" + "=" * 50)
    print("Pipeline runner complete!")
    print(f"  Audio: {final_audio}")
    print(f"  Pitch cues: {len(pitch_cues)}")
    print("=" * 50)


# ---------------------------------------------------------------------------
# CLI entry point (called by timeline_editor.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        # Called from timeline_editor.py:
        #   py engines/pipeline_runner.py '<sfx_json>' '<options_json>'
        sfx = json.loads(sys.argv[1])
        opts = json.loads(sys.argv[2])
        run(sfx_placements=sfx, options=opts)
    elif len(sys.argv) == 2 and sys.argv[1] == "--standalone":
        # Standalone reprocessing mode
        run()
    else:
        print("Usage:")
        print("  py engines/pipeline_runner.py '<sfx_json>' '<options_json>'")
        print("  py engines/pipeline_runner.py --standalone")
        sys.exit(1)
