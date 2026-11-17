#!/usr/bin/env python3
"""Serve the ESP32 console through its dedicated Tailscale Funnel port."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import mimetypes
import urllib.error
import urllib.request

UPSTREAM = "https://console.example.com"
PUBLIC = "https://console.example.net:10000"

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

upstream = urllib.request.build_opener(NoRedirect())

class ConsoleProxy(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def forward(self):
        if not self.path.startswith("/") or self.path.startswith("//"):
            return self.send_error(400)
        headers = {"User-Agent": "Mozilla/5.0", "Accept-Encoding": "identity"}
        for name in ("Cookie", "Content-Type", "Accept"):
            if name in self.headers:
                headers[name] = self.headers[name]
        body = None
        if self.command == "POST":
            if self.headers.get("Origin") != PUBLIC:
                return self.send_error(403)
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return self.send_error(400)
            if not 0 <= size <= 20000:
                return self.send_error(413)
            body = self.rfile.read(size)
            headers["Origin"] = UPSTREAM
        req = urllib.request.Request(UPSTREAM + self.path, data=body, headers=headers, method=self.command)
        try:
            response = upstream.open(req, timeout=15)
        except urllib.error.HTTPError as exc:
            response = exc
        except OSError:
            return self.send_error(502)
        with response:
            content = response.read()
            self.send_response(response.status)
            for name in ("Content-Type", "Content-Encoding", "Cache-Control", "Set-Cookie"):
                for value in response.headers.get_all(name, []):
                    if name != "Set-Cookie" or value.startswith("esp_session="):
                        self.send_header(name, value)
            location = response.headers.get("Location")
            if location:
                self.send_header("Location", location.replace(UPSTREAM, PUBLIC, 1) if location.startswith(UPSTREAM + "/") else location)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    def do_GET(self):
        path = urlsplit(self.path).path
        prefix = "/_next/static/"
        if path.startswith(prefix):
            static = (Path(__file__).resolve().parents[1] / "cloud/esp32-control/dist/client/_next/static").resolve()
            asset = (static / path.removeprefix(prefix)).resolve()
            if asset.is_relative_to(static) and asset.is_file():
                content = asset.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", mimetypes.guess_type(asset.name)[0] or "application/octet-stream")
                self.send_header("Cache-Control", "public, max-age=31536000, immutable")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
        self.forward()

    do_POST = forward

ThreadingHTTPServer(("127.0.0.1", 18769), ConsoleProxy).serve_forever()
