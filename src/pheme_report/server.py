"""Small local HTTP service behind the dashboard's "Ask about the report" box.

    GET  /api/health   -> {"ok": true, "report": true|false}
    POST /api/ask      {"question": "...", "history": [{"question": "...", "answer": "..."}]}
                       -> {"answer": "...", "referenced_cases": [...], "model": "..."}

It listens on localhost only. The AWS credentials stay in this process; the browser never
sees them. The dashboard's dev server forwards /api to it.
"""

from __future__ import annotations

import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from .ai import Analyst, AnalystError
from .build import load_report
from .qa import answer_question

MAX_BODY_BYTES = 64_000


class AskService:
    """Loads the report when it changes on disk and creates the model client on first use."""

    def __init__(self, report_path: Path, analyst_factory: Callable[[], Analyst]) -> None:
        self.report_path = report_path
        self._factory = analyst_factory
        self._analyst: Analyst | None = None
        self._report: dict[str, Any] | None = None
        self._mtime: float | None = None
        self._lock = threading.Lock()

    def report(self) -> dict[str, Any] | None:
        with self._lock:
            try:
                mtime = self.report_path.stat().st_mtime
            except OSError:
                return None
            if mtime != self._mtime:
                loaded = load_report(self.report_path)
                if loaded is not None:  # keep the last good one if the file is mid-write
                    self._report, self._mtime = loaded, mtime
            return self._report

    def analyst(self) -> Analyst:
        with self._lock:
            if self._analyst is None:
                self._analyst = self._factory()
            return self._analyst

    def ask(self, body: Any) -> tuple[HTTPStatus, dict[str, Any]]:
        if not isinstance(body, dict) or not isinstance(body.get("question"), str):
            return HTTPStatus.BAD_REQUEST, {"error": 'Send JSON like {"question": "..."}.'}
        history = body.get("history")
        if not isinstance(history, list):
            history = []
        report = self.report()
        if report is None or not report.get("runs"):
            return HTTPStatus.CONFLICT, {
                "error": "There is no report with runs yet. Run `pheme-report build` first."
            }
        try:
            answer = answer_question(
                self.analyst(), report, body["question"], [h for h in history if isinstance(h, dict)]
            )
        except ValueError as exc:
            return HTTPStatus.BAD_REQUEST, {"error": str(exc)}
        except AnalystError as exc:
            return HTTPStatus.BAD_GATEWAY, {"error": str(exc)}
        except Exception as exc:  # no region or credentials, SDK missing
            return HTTPStatus.SERVICE_UNAVAILABLE, {
                "error": f"The model is not available: {type(exc).__name__}: {exc}"
            }
        return HTTPStatus.OK, answer


def make_handler(service: AskService) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            if self.path.split("?")[0] == "/api/health":
                self._send(HTTPStatus.OK, {"ok": True, "report": service.report() is not None})
            else:
                self._send(HTTPStatus.NOT_FOUND, {"error": "Not found."})

        def do_POST(self) -> None:  # noqa: N802
            if self.path.split("?")[0] != "/api/ask":
                self._send(HTTPStatus.NOT_FOUND, {"error": "Not found."})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length <= 0 or length > MAX_BODY_BYTES:
                self._send(HTTPStatus.BAD_REQUEST, {"error": "Missing or oversized request body."})
                return
            try:
                body = json.loads(self.rfile.read(length))
            except ValueError:
                self._send(HTTPStatus.BAD_REQUEST, {"error": "The request body is not valid JSON."})
                return
            self._send(*service.ask(body))

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            print(f"  {self.address_string()} {format % args}")

    return Handler


def serve(report_path: Path, analyst_factory: Callable[[], Analyst], port: int) -> ThreadingHTTPServer:
    """Create the server (bound to localhost). The caller runs ``serve_forever``."""
    service = AskService(report_path, analyst_factory)
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(service))
