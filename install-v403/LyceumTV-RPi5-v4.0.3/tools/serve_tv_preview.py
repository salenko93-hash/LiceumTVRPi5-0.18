"""Read-only local preview host; never starts the application or its background jobs."""
import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen, ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8094)
    parser.add_argument("--api", help="Existing local API origin, e.g. http://127.0.0.1:8080")
    args = parser.parse_args()
    if args.api:
        parsed = urlparse(args.api)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.path not in {"", "/"} or parsed.query or parsed.fragment or parsed.username:
            parser.error("--api must be a local HTTP origin without credentials or a path")
    opener = build_opener(ProxyHandler({}))

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(ROOT / "public"), **kw)

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def do_GET(self):
            if self.path.split("?", 1)[0] == "/api/state":
                if not args.api:
                    self.send_error(503, "No local API configured; choose an explicit archive sample")
                    return
                try:
                    with opener.open(args.api.rstrip("/") + "/api/state", timeout=4) as response:
                        body = response.read(2_000_001)
                    if len(body) > 2_000_000:
                        raise ValueError("State too large")
                    json.loads(body)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(body)
                except (URLError, OSError, ValueError):
                    self.send_error(502, "Local API unavailable")
                return
            if self.path == "/":
                self.path = "/tv-display-preview.html"
            super().do_GET()

    print(f"Read-only preview: http://127.0.0.1:{args.port}/tv-display-preview.html?sample=groups", flush=True)
    print("Live mode: /tv-display-preview.html (requires --api). Stop: Ctrl+C.", flush=True)
    try:
        ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
