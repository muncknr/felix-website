import http.server
import ssl
import urllib.request
import urllib.error
import subprocess
import tempfile
import json
import os
from pathlib import Path

PORT = 8000
BIONIC_URL = "http://127.0.0.1:1234"

BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"
TRANSCRIBE_EXE = BASE_DIR / "voice" / "transcribe.cpp" / "build" / "bin" / "Release" / "transcribe-cli.exe"
VOXTRAL_MODEL = BASE_DIR / "voice" / "transcribe.cpp" / "models" / "voxtral" / "Voxtral-Mini-4B-Realtime-2602-Q4_K_M.gguf"
MAX_AUDIO_BYTES = 25 * 1024 * 1024


class FelixHandler(http.server.SimpleHTTPRequestHandler):
    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path == "/transcribe":
            self.handle_transcribe()
            return

        if self.path.startswith("/v1/"):
            self.proxy_bionic()
            return

        self.send_error(404, "Message not found")

    def proxy_bionic(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            request = urllib.request.Request(
                BIONIC_URL + self.path,
                data=body,
                method="POST",
                headers={
                    "Content-Type": self.headers.get("Content-Type", "application/json")
                },
            )

            with urllib.request.urlopen(request) as response:
                self.send_response(response.status)
                content_type = response.headers.get("Content-Type")
                if content_type:
                    self.send_header("Content-Type", content_type)
                self.end_headers()

                while True:
                    chunk = response.read(1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()

        except urllib.error.HTTPError as error:
            self.send_response(error.code)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(error.read())

        except Exception as error:
            self.send_response(502)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"Bionic proxy error: {error}".encode("utf-8"))

    def handle_transcribe(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self.send_json(400, {"error": "Invalid Content-Length"})
            return

        if content_length <= 0:
            self.send_json(400, {"error": "No audio was received"})
            return

        if content_length > MAX_AUDIO_BYTES:
            self.send_json(413, {"error": "Audio recording is too large"})
            return

        if not TRANSCRIBE_EXE.exists():
            self.send_json(500, {
                "error": f"transcribe-cli.exe not found: {TRANSCRIBE_EXE}"
            })
            return