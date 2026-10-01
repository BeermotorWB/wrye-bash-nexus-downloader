"""Shared fixtures: a local HTTP server, so no test touches the network."""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep test output quiet
        pass

    def _dispatch(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.body = self.rfile.read(length) if length else b""
        self.server.requests.append(self)
        self.server.handler(self)

    do_GET = do_POST = do_HEAD = _dispatch


@pytest.fixture
def http_server():
    """Start a local server; call it with handler(req) -> None, get its URL.
    Each request is recorded in server.requests."""
    servers = []

    def start(handler):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        srv.daemon_threads = True
        srv.handler = handler
        srv.requests = []
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        return srv, f"http://127.0.0.1:{srv.server_address[1]}"

    yield start
    for srv in servers:
        srv.shutdown()
        srv.server_close()


def reply(req, status=200, body=b"", headers=None):
    """Send a response from a test handler."""
    req.send_response(status)
    for k, v in (headers or {}).items():
        req.send_header(k, v)
    req.send_header("Content-Length", str(len(body)))
    req.end_headers()
    if req.command != "HEAD":
        req.wfile.write(body)
