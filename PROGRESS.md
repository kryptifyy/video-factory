# Timeline Editor — Progress Log

## What This Is
A web-based timeline editor for short-form viral videos. Edit pitch drops, place SFX, and preview audio — all from a browser. Deployed as a PWA so it works like an app on your phone.

## Live URL
https://video-factory-lz93.onrender.com

## GitHub Repo
https://github.com/kryptifyy/video-factory

## What's Been Built

### Core Editor (existed before)
- Timeline canvas with waveform, word blocks, pitch drops, SFX track
- Transcript sidebar with clickable word chips
- Pitch drop popup (right-click a word)
- SFX drag-and-drop placement
- Audio playback with speed control
- Undo/redo, auto-save, keyboard shortcuts
- Generate Video button (calls pipeline_runner.py)

### Mobile + Deployment (added today — Feb 11, 2026)
- **Render.com deployment** — accessible from any device with internet
- **PWA support** — Add to Home Screen for app-like experience
- **Mobile responsive layout** — everything stacks vertically on phones
- **Touch events** — tap-to-seek, pinch-to-zoom, long-press for pitch popup, tap-to-place SFX
- **Download Config button** — export editor state as JSON when on Render (since video generation needs a local PC)
- **Mobile audio fix** — AudioContext deferred to first user tap (required by mobile browsers)
- **Network access** — server binds 0.0.0.0 so you can access from phone on same WiFi

## Files
| File | Purpose |
|------|---------|
| `timeline_editor.py` | Python server (stdlib only, no deps) |
| `timeline_editor.html` | Full editor UI (HTML + CSS + JS, single file) |
| `manifest.json` | PWA manifest |
| `requirements.txt` | Empty (Render needs it to detect Python) |
| `render.yaml` | Render deployment config |
| `output/voice.mp3` | TTS audio |
| `output/word_timestamps.json` | Word-level timing data |
| `output/pitch_markers.json` | Pitch drop markers |
| `output/editor_state.json` | Saved editor state |

## Still TODO
- Verify mobile layout renders correctly on phone
- Test all touch interactions on actual device
- Test audio playback on mobile
- Add SFX files to assets/sfx/<category>/ for full experience
- Full video generation pipeline (needs ffmpeg, parselmouth, etc on local PC)
