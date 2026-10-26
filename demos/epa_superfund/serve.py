"""Serve the epa_superfund demo on loopback and answer live tool calls.

Run capture.py once first so data.js exists, then open http://127.0.0.1:8788.
Only the demo page, its script, and data.js are served, and only the nine
epa_superfund tools can be called.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = 8788
PUBLIC = {
    "/": ("index.html", "text/html"),
    "/index.html": ("index.html", "text/html"),
    "/app.js": ("app.js", "application/javascript"),
    "/data.js": ("data.js", "application/javascript"),
}
TOOLS = {"search_epa_superfund_sites"} | {
    f"get_epa_superfund_{suffix}"
    for suffix in (
        "sites_in_roi",
        "site",
        "operable_units",
        "institutional_controls",
        "documents",
        "cleanup_actions",
        "contaminants",
        "public_notices",
    )
}
BUSY = threading.Lock()


class DemoHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/api/call":
            self.send_error(404)
            return
        if self.headers.get("Origin") not in {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}:
            self.send_error(403)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 8192 or self.headers.get_content_type() != "application/json":
                raise ValueError("Expected a small JSON request")
            spec = json.loads(self.rfile.read(length))
            if not isinstance(spec, dict) or spec.get("tool") not in TOOLS or not isinstance(spec.get("args"), dict):
                raise ValueError("Unknown tool or invalid arguments")
        except (ValueError, TypeError) as exc:
            self.send_error(400, str(exc))
            return
        if not BUSY.acquire(blocking=False):
            self.send_error(429, "A query is already running")
            return
        try:
            result = subprocess.run(
                [sys.executable, str(HERE / "capture.py"), json.dumps(spec)],
                text=True,
                capture_output=True,
                timeout=100,
                check=False,
            )
            if result.returncode:
                print(result.stderr[-2000:], flush=True)
                self.send_error(502, "Tool call failed; see the server log")
                return
            self._send(result.stdout.encode(), "application/json")
        except subprocess.TimeoutExpired:
            self.send_error(504, "Tool call exceeded the demo time limit")
        finally:
            BUSY.release()

    def do_GET(self):
        target = PUBLIC.get(self.path.split("?")[0])
        if not target or not (HERE / target[0]).is_file():
            self.send_error(404, "Run capture.py first" if self.path.startswith("/data.js") else None)
            return
        self._send((HERE / target[0]).read_bytes(), target[1] + "; charset=utf-8")

    def _send(self, payload: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)


if __name__ == "__main__":
    print(f"epa_superfund demo: http://127.0.0.1:{PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), DemoHandler).serve_forever()
