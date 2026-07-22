"""An in-process fake Discord quest API for end-to-end testing.

Implements just enough of the real endpoints for the CLI to run a complete
enroll -> progress -> claim flow against `http://127.0.0.1:<port>/api/v9`, with
no real token or network. It also:

  * records every request's headers (so tests can assert the anti-detection
    fingerprint headers are actually sent), and
  * can inject a one-off HTTP 429 to exercise rate-limit backoff.
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

_PATH_RE = re.compile(r"^/api/v9/quests/(?P<id>[^/]+)/(?P<action>[a-z-]+)$")


class MockDiscord:
    def __init__(
        self,
        quests: list[dict[str, Any]],
        *,
        progress_step: int = 60,
        fail_once_429: bool = False,
    ) -> None:
        self.quests = {q["id"]: q for q in quests}
        self.progress_step = progress_step
        self.fail_once_429 = fail_once_429
        self.requests: list[dict[str, Any]] = []
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # --- lifecycle -------------------------------------------------------
    def __enter__(self) -> MockDiscord:
        handler = _make_handler(self)
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._thread:
            self._thread.join(timeout=2)

    @property
    def api_base(self) -> str:
        assert self._server is not None
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/api/v9"

    def header_seen(self, name: str) -> bool:
        name = name.lower()
        return any(name in {k.lower() for k in r["headers"]} for r in self.requests)

    def actions(self) -> list[str]:
        return [r["action"] for r in self.requests if r.get("action")]

    # --- request handling (called from the server thread) ----------------
    def handle(self, method: str, path: str, headers: dict[str, str], body: dict[str, Any]):
        with self._lock:
            record = {"method": method, "path": path, "headers": dict(headers),
                      "body": body, "action": None}
            self.requests.append(record)

            if path == "/api/v9/quests/@me" and method == "GET":
                return 200, {"quests": list(self.quests.values())}

            match = _PATH_RE.match(path)
            if not match or method != "POST":
                return 404, {"message": "Not Found", "code": 0}

            qid, action = match.group("id"), match.group("action")
            record["action"] = action
            quest = self.quests.get(qid)
            if quest is None:
                return 404, {"message": "Unknown Quest", "code": 10001}

            us = quest.setdefault("user_status", {})
            us.setdefault("progress", {})
            task_key = _task_key(quest)
            target = _target(quest)

            if action == "enroll":
                us["enrolled_at"] = "2026-01-01T00:00:00+00:00"
                return 200, {"user_status": us}

            if action in ("heartbeat", "video-progress"):
                # Inject a single 429 to prove the client backs off and retries.
                if self.fail_once_429:
                    self.fail_once_429 = False
                    return 429, {"message": "You are being rate limited.",
                                 "retry_after": 0.05, "global": False}
                if action == "video-progress":
                    value = min(target, int(body.get("timestamp", 0)))
                else:
                    prev = us["progress"].get(task_key, {}).get("value", 0)
                    value = min(target, prev + self.progress_step)
                us["progress"][task_key] = {"value": value}
                completed = value >= target
                if completed:
                    us["completed_at"] = "2026-01-01T00:10:00+00:00"
                resp = {"progress": us["progress"]}
                if action == "video-progress":
                    resp["completed_at"] = us.get("completed_at")
                return 200, resp

            if action == "claim-reward":
                us["claimed_at"] = "2026-01-01T00:11:00+00:00"
                return 200, {"user_status": us}

            return 404, {"message": "Not Found", "code": 0}


def _task_key(quest: dict[str, Any]) -> str:
    tasks = quest["config"]["task_config"]["tasks"]
    return next(iter(tasks))


def _target(quest: dict[str, Any]) -> int:
    tasks = quest["config"]["task_config"]["tasks"]
    return int(tasks[_task_key(quest)]["target"])


def _make_handler(mock: MockDiscord):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):  # silence
            pass

        def _dispatch(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                body = json.loads(raw) if raw else {}
            except ValueError:
                body = {}
            status, payload = mock.handle(method, self.path, dict(self.headers), body)
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

    return Handler


def sample_quests() -> list[dict[str, Any]]:
    """A play-on-desktop quest and a watch-video quest."""
    def make(qid: str, key: str, target: int, name: str) -> dict[str, Any]:
        return {
            "id": qid,
            "config": {
                "expires_at": "2999-01-01T00:00:00+00:00",
                "messages": {"quest_name": name},
                "application": {"id": "999"},
                "rewards_config": {"rewards": [{"type": 4, "messages": {"name": "100 Orbs"}}]},
                "task_config": {"tasks": {key: {"target": target}}},
            },
            "user_status": {},
        }

    return [
        make("1000000000000000001", "PLAY_ON_DESKTOP", 180, "Play Fake Game"),
        make("1000000000000000002", "WATCH_VIDEO", 60, "Watch Fake Video"),
    ]
