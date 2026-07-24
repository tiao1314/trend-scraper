#!/usr/bin/env python3
"""
Local control panel — serves the website AND runs the commands for real.

  python server.py           then open  http://localhost:8000/

GitHub Pages can't run Python (it's static hosting), so the "Run" buttons on
the live site trigger a GitHub Action instead. This server is the local
equivalent: its buttons execute the scraper on your machine and rewrite
docs/data.json, which the page then reloads.
"""

from __future__ import annotations

import json
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent
DOCS = ROOT / "docs"
PY = sys.executable

# label -> argv passed to export_web.py
COMMANDS = {
    "mock": ["--mock"],
    "live": [],
    "auto-discover": ["--auto-discover"],
}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(DOCS), **k)

    def do_POST(self):
        if not self.path.startswith("/run/"):
            self.send_error(404)
            return
        cmd = self.path.split("/run/", 1)[1].split("?")[0]
        if cmd not in COMMANDS:
            self._json(400, {"ok": False, "error": f"unknown command: {cmd}"})
            return
        argv = [PY, str(ROOT / "export_web.py"), *COMMANDS[cmd]]
        try:
            proc = subprocess.run(argv, cwd=ROOT, capture_output=True,
                                  text=True, timeout=900)
            self._json(200, {
                "ok": proc.returncode == 0,
                "stdout": proc.stdout[-4000:],
                "stderr": proc.stderr[-4000:],
            })
        except subprocess.TimeoutExpired:
            self._json(504, {"ok": False, "error": "timed out"})

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # quieter console
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"Trend scraper control panel:  http://localhost:{port}/")
    print("Run buttons are on the page (bottom). Ctrl-C to stop.")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
