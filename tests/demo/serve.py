"""
Tiny static + reverse-proxy server for the GEO-1 test page.

Serves tests/demo/index.html at "/" and proxies every other GET path to the
running geocode service. This keeps the browser on a single origin (no CORS)
and requires ZERO changes to the verified service.

    python3 tests/demo/serve.py            # http://localhost:8090
    PORT=9000 TARGET=http://localhost:8080 python3 tests/demo/serve.py
"""
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", "8090"))
TARGET = os.environ.get("TARGET", "http://localhost:8080").rstrip("/")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._serve_index()
        return self._proxy()

    def _serve_index(self):
        with open(os.path.join(HERE, "index.html"), "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _proxy(self):
        try:
            with urllib.request.urlopen(TARGET + self.path, timeout=30) as resp:
                body = resp.read()
                ctype = resp.headers.get("Content-Type", "application/json")
                status = resp.status
        except urllib.error.HTTPError as e:  # forward API error codes (e.g. 404)
            body = e.read()
            ctype = e.headers.get("Content-Type", "application/json")
            status = e.code
        except Exception as e:
            body = f'{{"error":"proxy failed: {e}"}}'.encode()
            ctype, status = "application/json", 502
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # quiet


if __name__ == "__main__":
    print(f"Test page: http://localhost:{PORT}  (proxying API → {TARGET})")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
