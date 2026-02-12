"""
Timeline Editor Server — Interactive web UI for timeline-based video editing.

Serves the HTML editor + API endpoints for loading data, saving state,
and launching the video generation pipeline.

Usage: py timeline_editor.py
Then open http://localhost:8080 (or the URL shown on startup)
"""
import json
import os
import socket
import subprocess
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).parent
OUTPUT_DIR = PROJECT_ROOT / "output"
EDITOR_STATE_PATH = OUTPUT_DIR / "editor_state.json"
WORD_TIMESTAMPS_PATH = OUTPUT_DIR / "word_timestamps.json"
PITCH_MARKERS_PATH = OUTPUT_DIR / "pitch_markers.json"
SFX_PLACEMENTS_PATH = OUTPUT_DIR / "sfx_placements.json"
VOICE_PATH = OUTPUT_DIR / "voice.mp3"
SFX_DIR = PROJECT_ROOT / "assets" / "sfx"
HTML_PATH = PROJECT_ROOT / "timeline_editor.html"
MANIFEST_PATH = PROJECT_ROOT / "manifest.json"

IS_RENDER = "PORT" in os.environ

SFX_CATEGORIES = {
    "emphasis":   {"color": "#ff4757", "label": "Emphasis"},
    "humor":      {"color": "#ffa502", "label": "Humor"},
    "shock":      {"color": "#a55eea", "label": "Shock"},
    "transition": {"color": "#2ed573", "label": "Transition"},
    "context":    {"color": "#1e90ff", "label": "Context"},
}


def scan_sfx_library():
    """Scan assets/sfx/ and return all available SFX with metadata."""
    sfx_list = []
    if not SFX_DIR.exists():
        return sfx_list

    for category_dir in sorted(SFX_DIR.iterdir()):
        if not category_dir.is_dir():
            continue
        category = category_dir.name
        cat_info = SFX_CATEGORIES.get(category, {"color": "#888", "label": category.title()})

        for f in sorted(category_dir.iterdir()):
            if f.suffix.lower() in (".mp3", ".wav", ".ogg"):
                name = f.stem.lower()
                for strip in ["-sound-effect", "-meme", "sound", "-effect"]:
                    name = name.replace(strip, "")
                name = name.replace("-", " ").replace("_", " ").strip()

                sfx_list.append({
                    "id": f"{category}/{f.stem}",
                    "name": name,
                    "category": category,
                    "color": cat_info["color"],
                    "category_label": cat_info["label"],
                    "filename": f.name,
                    "path": str(f),
                })

    return sfx_list


SFX_LIBRARY = []


class TimelineHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the timeline editor."""

    def log_message(self, format, *args):
        print(f"  {args[0]}")

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status, message):
        self._send_json({"error": message}, status)

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/":
            self._serve_html()
        elif path == "/manifest.json":
            self._serve_manifest()
        elif path == "/api/timeline-data":
            self._serve_timeline_data()
        elif path == "/api/audio":
            self._serve_audio()
        elif path == "/api/download-config":
            self._serve_download_config()
        elif path.startswith("/api/sfx/"):
            self._serve_sfx(path)
        else:
            self._send_error(404, "Not found")

    def do_POST(self):
        path = urlparse(self.path).path
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b""

        if path == "/api/save-state":
            self._save_state(body)
        elif path == "/api/save-pitch-markers":
            self._save_pitch_markers(body)
        elif path == "/api/generate":
            self._generate_video(body)
        else:
            self._send_error(404, "Not found")

    # --- Route handlers ---

    def _serve_html(self):
        if not HTML_PATH.exists():
            self._send_error(500, "timeline_editor.html not found")
            return
        content = HTML_PATH.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(content)

    def _serve_manifest(self):
        if not MANIFEST_PATH.exists():
            self._send_error(404, "manifest.json not found")
            return
        content = MANIFEST_PATH.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/manifest+json")
        self.send_header("Content-Length", str(len(content)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(content)

    def _serve_download_config(self):
        """Bundle editor_state.json + pitch_markers.json into a single JSON download."""
        config = {}
        if EDITOR_STATE_PATH.exists():
            with open(EDITOR_STATE_PATH) as f:
                config["editor_state"] = json.load(f)
        if PITCH_MARKERS_PATH.exists():
            with open(PITCH_MARKERS_PATH) as f:
                config["pitch_markers"] = json.load(f)

        body = json.dumps(config, indent=2).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Disposition", "attachment; filename=timeline_config.json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_timeline_data(self):
        if not WORD_TIMESTAMPS_PATH.exists():
            self._send_error(500, "word_timestamps.json not found in output/")
            return

        with open(WORD_TIMESTAMPS_PATH) as f:
            words = json.load(f)

        state = None
        if EDITOR_STATE_PATH.exists():
            with open(EDITOR_STATE_PATH) as f:
                state = json.load(f)

        pitch_markers = []
        if PITCH_MARKERS_PATH.exists():
            with open(PITCH_MARKERS_PATH) as f:
                pitch_markers = json.load(f)

        sfx_placements = []
        if SFX_PLACEMENTS_PATH.exists():
            with open(SFX_PLACEMENTS_PATH) as f:
                sfx_placements = json.load(f)

        self._send_json({
            "words": words,
            "state": state,
            "sfx_library": SFX_LIBRARY,
            "pitch_markers": pitch_markers,
            "sfx_placements": sfx_placements,
            "is_render": IS_RENDER,
        })

    def _serve_audio(self):
        """Stream voice.mp3 with HTTP Range support for seeking."""
        if not VOICE_PATH.exists():
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", "0")
            self._cors_headers()
            self.end_headers()
            return

        file_size = VOICE_PATH.stat().st_size
        range_header = self.headers.get("Range")

        if range_header:
            range_spec = range_header.replace("bytes=", "")
            parts = range_spec.split("-")
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if parts[1] else file_size - 1
            end = min(end, file_size - 1)
            length = end - start + 1

            self.send_response(206)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(length))
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            self.send_header("Accept-Ranges", "bytes")
            self._cors_headers()
            self.end_headers()

            with open(VOICE_PATH, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(8192, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        else:
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(file_size))
            self.send_header("Accept-Ranges", "bytes")
            self._cors_headers()
            self.end_headers()

            with open(VOICE_PATH, "rb") as f:
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    self.wfile.write(chunk)

    def _serve_sfx(self, url_path):
        """Serve any SFX file: /api/sfx/category/filename"""
        sfx_id = url_path[len("/api/sfx/"):]

        sfx_path = None
        for sfx in SFX_LIBRARY:
            if sfx["id"] == sfx_id:
                sfx_path = Path(sfx["path"])
                break

        if not sfx_path or not sfx_path.exists():
            self._send_error(404, f"SFX not found: {sfx_id}")
            return

        content_types = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg"}
        ctype = content_types.get(sfx_path.suffix, "audio/mpeg")

        data = sfx_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "max-age=3600")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(data)

    def _save_state(self, body):
        try:
            state = json.loads(body)
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            with open(EDITOR_STATE_PATH, "w") as f:
                json.dump(state, f, indent=2)

            # Also write sfx_placements.json for the pipeline
            if "sfx_placements" in state:
                with open(SFX_PLACEMENTS_PATH, "w") as f:
                    json.dump(state["sfx_placements"], f, indent=2)

            self._send_json({"success": True})
        except Exception as e:
            self._send_error(500, str(e))

    def _save_pitch_markers(self, body):
        """Save pitch markers to pitch_markers.json."""
        try:
            markers = json.loads(body)
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            with open(PITCH_MARKERS_PATH, "w") as f:
                json.dump(markers, f, indent=2)
            self._send_json({"success": True})
        except Exception as e:
            self._send_error(500, str(e))

    def _generate_video(self, body):
        """Launch pipeline_runner.py as subprocess to generate the video."""
        try:
            params = json.loads(body)
            sfx_placements = params.get("sfx_placements", [])
            base_speed = params.get("base_speed", 1.2)
            manual_pitch_drops = params.get("manual_pitch_drops", None)

            runner_path = PROJECT_ROOT / "engines" / "pipeline_runner.py"
            if not runner_path.exists():
                self._send_json({
                    "success": False,
                    "error": "engines/pipeline_runner.py not found. Pipeline not set up yet."
                }, 200)
                return

            python_exe = _find_python()

            opts = {"base_speed": base_speed}
            if manual_pitch_drops:
                opts["manual_pitch_drops"] = manual_pitch_drops

            cmd = [
                python_exe, str(runner_path),
                json.dumps(sfx_placements),
                json.dumps(opts),
            ]

            print(f"\n  [Server] Launching pipeline...")
            print(f"  [Server] SFX: {len(sfx_placements)}, Speed: {base_speed}x")
            if manual_pitch_drops:
                print(f"  [Server] Manual pitch drops: {len(manual_pitch_drops)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(PROJECT_ROOT),
                timeout=300
            )

            if result.stdout:
                for line in result.stdout.strip().split("\n"):
                    print(f"  [Pipeline] {line}")
            if result.stderr:
                for line in result.stderr.strip().split("\n")[-10:]:
                    print(f"  [Pipeline ERROR] {line}")

            if result.returncode == 0:
                self._send_json({"success": True, "output": str(OUTPUT_DIR / "final_video.mp4")})
            else:
                error_msg = result.stderr[-500:] if result.stderr else "Unknown error"
                self._send_json({"success": False, "error": error_msg}, 200)

        except subprocess.TimeoutExpired:
            self._send_json({"success": False, "error": "Pipeline timed out (5 min)"}, 200)
        except Exception as e:
            self._send_error(500, str(e))


def _find_python():
    cwd = str(PROJECT_ROOT)
    if cwd.startswith("/mnt/"):
        try:
            result = subprocess.run(["py.exe", "--version"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                return "py.exe"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    return sys.executable


def _get_local_ip():
    """Get the machine's local network IP for same-WiFi access."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def main():
    global SFX_LIBRARY
    SFX_LIBRARY = scan_sfx_library()

    port = int(os.environ.get("PORT", 8080))
    host = "0.0.0.0"
    server = HTTPServer((host, port), TimelineHandler)

    print("=" * 50)
    print("  Timeline Editor")
    print("=" * 50)
    print(f"  Local:   http://localhost:{port}")

    local_ip = _get_local_ip()
    if local_ip:
        print(f"  Network: http://{local_ip}:{port}")

    if IS_RENDER:
        print("  Mode:    Render (cloud)")
    else:
        print("  Mode:    Local")

    print(f"  Project: {PROJECT_ROOT}")

    if WORD_TIMESTAMPS_PATH.exists():
        with open(WORD_TIMESTAMPS_PATH) as f:
            wt = json.load(f)
        print(f"  Words: {len(wt)} ({wt[-1]['end']:.1f}s)" if wt else "  Words: 0")
    else:
        print("  Words: word_timestamps.json not found")

    if VOICE_PATH.exists():
        size_kb = VOICE_PATH.stat().st_size / 1024
        print(f"  Audio: voice.mp3 ({size_kb:.0f} KB)")
    else:
        print("  Audio: voice.mp3 not found (no playback)")

    if SFX_LIBRARY:
        print(f"  SFX: {len(SFX_LIBRARY)} sounds")
        for sfx in SFX_LIBRARY:
            print(f"    {sfx['category']}/{sfx['name']}")
    else:
        print("  SFX: None (add .mp3 files to assets/sfx/<category>/)")

    if PITCH_MARKERS_PATH.exists():
        with open(PITCH_MARKERS_PATH) as f:
            pm = json.load(f)
        print(f"  Pitch markers: {len(pm)}")
        for m in pm:
            print(f"    \"{m['phrase']}\" → {m['semitones']} st")

    print("=" * 50)
    print("  Press Ctrl+C to stop\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
