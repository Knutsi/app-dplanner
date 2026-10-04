"""A fake model API that fails on purpose, so the agent CLIs can be probed for free.

Point a CLI's base URL at it and every request gets the failure the mode names. It speaks
both the Anthropic error shape (/v1/messages) and the OpenAI one (anything else), so one
server serves `claude`, `codex` and `opencode` alike.

    python fake_api.py <port> <mode>

Modes: 401 403 404model credit 429 529 500 garbage hang
"""

from __future__ import annotations

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ANTHROPIC = {
    "401": (401, "authentication_error", "invalid x-api-key"),
    "403": (403, "permission_error", "Your account does not have access (subscription expired)."),
    "404model": (404, "not_found_error", "model: claude-retired-1"),
    "credit": (400, "invalid_request_error", "Your credit balance is too low to access the Anthropic API."),
    "429": (429, "rate_limit_error", "Number of request tokens has exceeded your rate limit."),
    "529": (529, "overloaded_error", "Overloaded"),
    "500": (500, "api_error", "Internal server error"),
}

OPENAI = {
    "401": (401, "invalid_api_key", "Incorrect API key provided: bogus."),
    "403": (403, "unsupported_country_region_territory", "Your plan does not include access (subscription expired)."),
    "404model": (404, "model_not_found", "The model `gpt-retired-1` does not exist."),
    "credit": (
        429,
        "insufficient_quota",
        "You exceeded your current quota, please check your plan and billing details.",
    ),
    "429": (429, "rate_limit_exceeded", "Rate limit reached. Please try again in 20s."),
    "529": (503, "server_overloaded", "The server is overloaded."),
    "500": (500, "server_error", "The server had an error while processing your request."),
}


def handler_for(mode: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            sys.stderr.write(f"{time.strftime('%H:%M:%S')} {self.command} {self.path}\n")

        def _reply(self, status: int, body: bytes, content_type: str = "application/json") -> None:
            self.send_response(status)
            self.send_header("content-type", content_type)
            self.send_header("content-length", str(len(body)))
            if status == 429:
                self.send_header("retry-after", "20")
            self.end_headers()
            self.wfile.write(body)

        def _serve(self) -> None:
            length = int(self.headers.get("content-length") or 0)
            if length:
                self.rfile.read(length)
            if mode == "hang":
                time.sleep(3600)
                return
            if mode == "garbage":
                self._reply(200, b"<html>502 Bad Gateway from a captive portal</html>", "text/html")
                return
            if "/messages" in self.path:
                status, kind, message = ANTHROPIC[mode]
                body = {"type": "error", "error": {"type": kind, "message": message}}
            else:
                status, code, message = OPENAI[mode]
                body = {"error": {"message": message, "type": code, "code": code, "param": None}}
            self._reply(status, json.dumps(body).encode())

        do_POST = _serve
        do_GET = _serve

    return Handler


def main() -> None:
    port, mode = int(sys.argv[1]), sys.argv[2]
    server = ThreadingHTTPServer(("127.0.0.1", port), handler_for(mode))
    server.daemon_threads = True
    server.serve_forever()


if __name__ == "__main__":
    main()
