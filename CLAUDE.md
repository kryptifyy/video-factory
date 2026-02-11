# Video Factory

Short-form viral video automation: AI script → ElevenLabs voice → pitch drops → captions → video.

## Project Structure

```
video_factory/
├── pipeline.py                  # Full generation pipeline (fresh mode)
├── engines/
│   ├── script_engine.py         # AI script generation with pitch drop markers
│   ├── pitch_engine.py          # Pitch resolution, Praat PSOLA, inline markup parser
│   └── pipeline_runner.py       # Reuse/editor mode pipeline (called by timeline editor)
├── timeline_editor.py           # Web UI for SFX placement
├── timeline_editor.html         # Editor frontend
├── assets/sfx/                  # SFX library (organized by category)
└── output/                      # Generated artifacts
    ├── voice.mp3                # ElevenLabs TTS output
    ├── word_timestamps.json     # [{word, start, end}] from TTS
    ├── script.json              # Full GeneratedScript with pitch_drops
    ├── script.txt               # Plain text script for TTS
    ├── pitch_markers.json       # [{phrase, semitones}] from script generation
    ├── pitch_cues.json          # [{start, end, semitones}] resolved timestamps
    ├── voice_fast.wav           # After 1.2x speed+pitch
    ├── voice_pitched.wav        # After Praat PSOLA pitch drops
    └── sfx_placements.json      # [{sfx_path, time, volume}]
```

## Script Template Format

Pitch drops are decided at script-writing time and baked into the script output.
Two input paths, same output format:

### AI-Generated Scripts (JSON field)

The `GeneratedScript` Pydantic model includes a `pitch_drops` field:

```json
{
  "full_script": "...sound like a literal war crime...",
  "pitch_drops": [
    {"phrase": "war crime", "semitones": -4},
    {"phrase": "purge siren", "semitones": -5}
  ]
}
```

The AI picks 3-6 phrases: punchline words, shocking claims, spaced 2s+ apart, -3 to -6 semitones.

### Manually-Written Scripts (inline markup)

Use `*phrase*(-N)` syntax:

```
...sound like a literal *war crime*(-4)? ...sounds like the *purge siren*(-5).
```

`parse_marked_script(text)` strips markers → clean text for TTS + pitch_drops list.

## Pipeline Flow

### Fresh Generation (`pipeline.py`)

```
1. generate_script(topic) → GeneratedScript with pitch_drops
   → Save pitch_markers.json to output/
2. generate_voice(full_script) → voice.mp3 + word_timestamps.json
3. apply_speed_curve (uniform 1.2x via FFmpeg asetrate)
   → Scales word_timestamps to match new speed
4. resolve_pitch_cues(pitch_drops, word_timestamps) → [{start, end, semitones}]
   → Same cues drive vine boom SFX placement
4b. apply_pitch_drops(audio, pitch_cues) → Praat PSOLA
5-7. Captions, audio mix, video composite
```

### Reuse/Editor Mode (`engines/pipeline_runner.py`)

```
1. Load voice.mp3 + word_timestamps.json from output/
2. apply_speed_curve (1.2x)
3. Pitch drops (3-tier fallback):
   a. Manual pitch drops from editor UI? → use those
   b. pitch_markers.json exists? → resolve_pitch_cues()
   c. else → get_auto_pitch_cues() [legacy AI call]
4. apply_pitch_drops (Praat PSOLA)
5-6. Audio mix, captions, video composite
```

## Phrase Matching Algorithm (`resolve_pitch_cues`)

Converts `[{phrase, semitones}]` → `[{start, end, semitones}]` using word timestamps.

1. **Normalize** all words: strip punctuation + lowercase (`"crime?"` → `"crime"`, `"HELLO!!!"` → `"hello"`)
2. For each phrase in pitch_drops, split into target words
3. **Slide** through word_timestamps looking for consecutive normalized match
4. **Fallback**: if full phrase match fails, match just the last word of the phrase
5. **Track used indices** to prevent overlapping matches (first match wins)
6. Return sorted pitch cues with start/end times from word_timestamps

## Duration Constraint

Target: **≤40 seconds** final video duration after 1.2x speed+pitch increase.

- Script word count target: 100-170 words
- At natural speech (~3 words/sec): ~33-57 seconds raw
- After 1.2x speedup: ~28-47 seconds
- Sweet spot: 100-140 words → 28-39 seconds final

The prompt instructs the AI to aim for ≤40s final at 1.2x playback. The pipeline warns if duration exceeds 40s after speed adjustment.

## Praat PSOLA Pitch Shifting

`apply_pitch_drops()` uses **parselmouth** (Python Praat wrapper) with **TD-PSOLA**
(Time-Domain Pitch-Synchronous Overlap-Add):

1. Convert input to WAV (Praat requires WAV)
2. Create a Manipulation object (0.01s time step, 75-600 Hz pitch range)
3. Extract the pitch tier
4. For each pitch cue `{start, end, semitones}`:
   - Calculate frequency factor: `factor = 2^(semitones/12)`
   - Sample original pitch at 10ms intervals across the region
   - Apply factor with **20ms ramp zones** at boundaries for smooth transitions
   - Ramp blends between original pitch (1.0) and shifted pitch (factor)
5. Replace pitch tier in the Manipulation object
6. Resynthesize via overlap-add → output WAV

**Why PSOLA?** It preserves voice quality and naturalness better than simple resampling.
The algorithm works by repositioning pitch-synchronous windows: closer together = higher
pitch, further apart = lower pitch. Unmodified regions pass through unchanged.

**Key parameters:**
- Pitch range: 75-600 Hz (covers male and female voices)
- Time step: 0.01s (10ms resolution)
- Ramp zone: 20ms (prevents click artifacts at boundaries)
- Typical semitones: -3 to -6 (deeper voice for comedic emphasis)

## Testing

### No-cost test (reuse mode)
```bash
cd video_factory
py pipeline.py --reuse
```
Loads existing `output/voice.mp3` + `word_timestamps.json`, tests resolve/apply path. No API calls.

### Markup parser test
```python
from engines.pitch_engine import parse_marked_script

text = "This is a *war crime*(-4) and a *federal offense*(-5)."
clean, drops = parse_marked_script(text)
# clean = "This is a war crime and a federal offense."
# drops = [{"phrase": "war crime", "semitones": -4}, {"phrase": "federal offense", "semitones": -5}]
```

### Resolve test (with existing timestamps)
```python
from engines.pitch_engine import resolve_pitch_cues
import json

with open("output/word_timestamps.json") as f:
    timestamps = json.load(f)

drops = [{"phrase": "petabytes", "semitones": -4}, {"phrase": "room", "semitones": -5}]
cues = resolve_pitch_cues(drops, timestamps)
# cues = [{"start": 4.48, "end": 5.02, "semitones": -4}, {"start": 11.03, "end": 11.27, "semitones": -5}]
```

## Key Dependencies

- `pydantic` — data models for script + pitch drops
- `anthropic` — Claude API for script generation
- `elevenlabs` — TTS with word-level timestamps
- `parselmouth` — Python Praat wrapper for PSOLA pitch shifting
- `ffmpeg` — speed adjustment (asetrate), audio mixing, video compositing
