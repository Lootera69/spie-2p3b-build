"""Loopback preview, and the opt-in public deployment of the same preview.

No model calls, file-upload endpoint, or publishing API. The server is loopback-only
by default: a public origin must be named explicitly (``--public-origin``, or the
``BRAINBLOOM_PUBLIC_ORIGIN``/``RENDER_EXTERNAL_URL`` environment), which is what
widens the Host allowlist and turns on the per-client request cap.
"""

from __future__ import annotations

import json
import subprocess
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .brief import Brief, prepare
from .brief import configuration as brief_configuration
from .catalog import Request, configuration
from .service import Generator

STATIC = Path(__file__).with_name("static")
MAX_BODY = 8192
# A deployed instance is unauthenticated and answers serially, so one caller must
# not be able to monopolise it. Loopback runs stay uncapped (limit 0 disables).
PUBLIC_RATE_LIMIT = 60
RATE_WINDOW = 60.0


def parse_public_origin(value: str) -> tuple[str, str]:
    """Split a deployment origin into (Host value, canonical Origin value)."""
    parsed = urlsplit(value.strip().rstrip("/"))
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.path:
        raise ValueError(f"Public origin must look like https://host[:port], not {value!r}")
    host = parsed.netloc.casefold()
    return host, f"{parsed.scheme}://{host}"


class RateLimiter:
    """Fixed-window per-client cap, bounded in memory and free of dependencies."""

    def __init__(self, limit: int, window: float = RATE_WINDOW) -> None:
        self.limit = limit
        self.window = window
        self.windows: dict[str, tuple[float, int]] = {}

    def allow(self, client: str, now: float | None = None) -> bool:
        if self.limit <= 0:
            return True
        now = time.monotonic() if now is None else now
        if len(self.windows) > 4096:
            # Expired windows are the only growth source; drop them, never live ones.
            self.windows = {k: v for k, v in self.windows.items() if now - v[0] < self.window}
        start, count = self.windows.get(client, (now, 0))
        if now - start >= self.window:
            start, count = now, 0
        if count >= self.limit:
            return False
        self.windows[client] = (start, count + 1)
        return True


class LocalHTTPServer(HTTPServer):
    # Browsers may open an idle connection before sending a request. Bound header
    # reads too, otherwise that connection can block this serial server forever.
    connection_timeout = 5

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(self.connection_timeout)
        return connection, address


def handler_for(
    engine: Generator,
    *,
    public_origin: str | None = None,
    rate_limit: int = 0,
) -> type[BaseHTTPRequestHandler]:
    public = parse_public_origin(public_origin) if public_origin else None
    limiter = RateLimiter(rate_limit)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            pass  # Do not print question content or browser-supplied log strings.

        def send(self, status: int, payload: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", (
                "default-src 'none'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
            ))
            self.end_headers()
            self.wfile.write(payload)

        def send_json(self, status: int, value: object) -> None:
            self.send(status, json.dumps(value).encode("utf-8"), "application/json; charset=utf-8")

        def origins(self) -> dict[str, str]:
            # Rebuilt per request: the port is only known after binding, and tests
            # bind port 0. Maps an accepted Host to the one Origin that matches it.
            port = self.server.server_address[1]
            allowed = {
                f"127.0.0.1:{port}": f"http://127.0.0.1:{port}",
                f"localhost:{port}": f"http://localhost:{port}",
            }
            if public is not None:
                allowed[public[0]] = public[1]
            return allowed

        def client_key(self) -> str:
            # Behind the platform's proxy the peer address is the proxy, so the
            # leftmost forwarded entry is the only per-caller key available. It is
            # client-settable, hence trusted solely on a deliberately public origin.
            if public is not None:
                forwarded = self.headers.get("X-Forwarded-For")
                if forwarded:
                    return forwarded.split(",")[0].strip()[:64]
            return self.client_address[0]

        def local_request(self) -> bool:
            allowed = self.origins()
            host = (self.headers.get("Host") or "").casefold()
            origin = self.headers.get("Origin")
            if host not in allowed or (origin is not None and origin != allowed[host]):
                self.send_json(403, {"error": "Only same-origin requests are allowed"})
                return False
            if not limiter.allow(self.client_key()):
                self.send_json(429, {"error": "Too many requests; try again shortly"})
                return False
            return True

        def do_GET(self) -> None:
            if self.path == "/healthz":
                # Platform health checks arrive before any origin is known, and with
                # the probe's own Host header. Static, bodiless, ahead of the check.
                self.send_json(200, {"status": "ok"})
                return
            if not self.local_request():
                return
            if self.path == "/api/config":
                self.send_json(200, {
                    **configuration(),
                    "bank": engine.bank_manifest,
                    "platform_verifier": engine.verifier is not None,
                    "dictionary": engine.dictionary.configuration(),
                    "history": {"enabled": engine.history is not None,
                                "designs": len(engine.history.keys()) if engine.history else 0},
                    "workshop": brief_configuration(),
                })
                return
            assets = {
                "/": ("index.html", "text/html; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                "/style.css": ("style.css", "text/css; charset=utf-8"),
            }
            if self.path not in assets:
                self.send_json(404, {"error": "Not found"})
                return
            name, mime = assets[self.path]
            self.send(200, (STATIC / name).read_bytes(), mime)

        def read_body(self) -> bytes:
            # Read the whole bounded body once, before the content-type or JSON
            # rejection below, so every reply still consumes the request. An unread
            # body makes Windows reset the socket, surfacing to the client as an
            # aborted connection. Chunked or oversized framing cannot be bounded, so
            # it is refused here without reading.
            if self.headers.get("Transfer-Encoding"):
                raise ValueError(f"A 1-{MAX_BODY} byte JSON request is required")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                raise ValueError(f"A 1-{MAX_BODY} byte JSON request is required")
            self.connection.settimeout(10)
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("Incomplete JSON request body")
            return body

        def drain(self) -> None:
            # Best-effort consume the body on an already-decided path (403/404) so the
            # socket closes cleanly. Never raises: strict framing is read_body's job on
            # the generate path, not a settled rejection's.
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if self.headers.get("Transfer-Encoding") or not 0 < length <= MAX_BODY:
                    return
                self.connection.settimeout(10)
                self.rfile.read(length)
            except (ValueError, OSError):
                pass

        def do_POST(self) -> None:
            if not self.local_request():
                self.drain()
                return
            if self.path not in ("/api/generate", "/api/topics", "/api/prepare"):
                self.drain()
                self.send_json(404, {"error": "Not found"})
                return
            try:
                body = self.read_body()
                if self.headers.get_content_type() != "application/json":
                    raise ValueError("Content-Type must be application/json")
                data = json.loads(body)
                if not isinstance(data, dict):
                    raise ValueError("Request must be an object")
                if self.path == "/api/prepare":
                    self.send_json(200, prepare(Brief(**data), engine.dictionary))
                    return
                if self.path == "/api/topics":
                    if set(data) - {"subject", "sense", "category"}:
                        raise ValueError("Topic lookup accepts subject, sense and category only")
                    category = data.get("category", "puzzles")
                    if (not isinstance(category, str)
                            or category not in configuration()["categories"]):
                        raise ValueError("Choose a supported category")
                    self.send_json(200, engine.dictionary.lookup(
                        data.get("subject", ""), data.get("sense", ""), category
                    ))
                    return
                request = Request(**data)
            except (ValueError, TypeError, OSError) as exc:
                self.send_json(400, {"error": str(exc)})
                return
            except RuntimeError:
                self.send_json(500, {"error": "Independent checks disagreed; no puzzle released"})
                return
            try:
                self.send_json(200, engine.build(request))
            except ValueError as exc:
                self.send_json(422, {"error": str(exc)})
            except (RuntimeError, OSError, subprocess.TimeoutExpired):
                self.send_json(500, {"error": "Verification failed; no drafts released"})

    return Handler


def serve(
    engine: Generator,
    port: int = 8766,
    *,
    open_browser: bool = False,
    host: str = "127.0.0.1",
    public_origin: str | None = None,
) -> None:
    if not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    if not host:
        raise ValueError("Host must be an address to bind, such as 127.0.0.1 or 0.0.0.0")
    if public_origin:
        parse_public_origin(public_origin)  # Fail at startup, not on the first request.
    handler = handler_for(
        engine,
        public_origin=public_origin,
        rate_limit=PUBLIC_RATE_LIMIT if public_origin else 0,
    )
    # Serial requests deliberately avoid sharing Z3's global context across threads.
    with LocalHTTPServer((host, port), handler) as server:
        url = public_origin.rstrip("/") if public_origin else f"http://{host}:{port}"
        print(f"BrainBloom generator: {url}", flush=True)
        if public_origin:
            print(f"Serving {host}:{port} publicly. No publishing endpoint.", flush=True)
        else:
            print("Local preview only. Press Ctrl+C to stop. No publishing endpoint.", flush=True)
        if open_browser:
            try:
                if not webbrowser.open(url):
                    print(f"Open {url} in your browser.", flush=True)
            except webbrowser.Error:
                print(f"Open {url} in your browser.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
