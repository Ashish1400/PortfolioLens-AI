"""Loopback-only development server; no external frameworks or secrets in the browser."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from urllib.parse import urlparse
from .copilot import ask


def serve(root, port=8765):
    report_path = root / "artifacts/dashboard.json"
    if not report_path.exists():
        raise ValueError("Build the pipeline first: python -m portfoliolens build")
    report = json.loads(report_path.read_text())
    class Handler(BaseHTTPRequestHandler):
        def send_bytes(self, body, content_type="application/json", status=200):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlparse(self.path).path
            static = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}
            if path == "/api/dashboard":
                self.send_bytes(json.dumps(report).encode())
            elif path == "/api/config":
                self.send_bytes(json.dumps({"openai_available": bool(os.getenv("OPENAI_API_KEY") and os.getenv("OPENAI_MODEL"))}).encode())
            elif path in static:
                mime = {"/": "text/html; charset=utf-8", "/app.js": "text/javascript; charset=utf-8", "/style.css": "text/css; charset=utf-8"}
                self.send_bytes((root / "web" / static[path]).read_bytes(), mime[path])
            else:
                self.send_bytes(b'{"error":"Not found"}', status=404)

        def do_POST(self):
            if self.path != "/api/ask":
                return self.send_bytes(b'{"error":"Not found"}', status=404)
            # Reject cross-site requests to the local server. No browser-provided API key.
            origin = self.headers.get("Origin")
            if origin and origin not in [f"http://127.0.0.1:{port}", f"http://localhost:{port}"]:
                return self.send_bytes(b'{"error":"Origin rejected"}', status=403)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 8192:
                    raise ValueError("Invalid request size.")
                request = json.loads(self.rfile.read(length))
                if not isinstance(request, dict):
                    raise ValueError("Request must be a JSON object.")
                result = ask(report, request.get("question", ""), request.get("mode", "offline"),
                             root / "artifacts/copilot_audit.jsonl")
                self.send_bytes(json.dumps(result).encode())
            except (ValueError, TypeError, KeyError) as exc:
                self.send_bytes(json.dumps({"error": str(exc)}).encode(), status=400)

        def log_message(self, format, *args):
            pass
    print(f"PortfolioLens AI: http://127.0.0.1:{port} (synthetic local demo)", flush=True)
    with ThreadingHTTPServer(("127.0.0.1", port), Handler) as server:
        server.serve_forever()
