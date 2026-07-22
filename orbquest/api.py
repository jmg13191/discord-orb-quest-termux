"""Thin HTTP client around the Discord quest endpoints.

The whole point of this project is that Discord validates quest progress
*server-side* from a handful of REST calls. The official desktop client is the
thing that normally emits those calls (after it detects a running game, an
active stream or a watched video), but nothing about the endpoints themselves
requires a desktop or an installed game -- they only require a valid user
session. That is what lets the same flow run from Termux on a phone.

Endpoints used (all under https://discord.com/api/v9):

  GET  /quests/@me                     list the quests offered to the account
  POST /quests/{id}/enroll             accept a quest
  POST /quests/{id}/video-progress     report watch-video timestamp
  POST /quests/{id}/heartbeat          report play/stream/activity heartbeat
  POST /quests/{id}/claim-reward       claim the reward once completed
"""

from __future__ import annotations

import base64
import json
import random
import time
from typing import Any

import requests

API_BASE = "https://discord.com/api/v9"

# Client build numbers the desktop app has actually shipped. Picking from a
# small set of *plausible* values (rather than one hard-coded number that never
# changes) makes the fingerprint look less like a static script.
KNOWN_BUILD_NUMBERS = (359820, 360180, 360590, 361140, 361703)

# How many times to retry a request that hit a 429 before giving up.
MAX_RATE_LIMIT_RETRIES = 5

# A desktop-flavoured super-properties blob. Quests that are gated to
# "PLAY_ON_DESKTOP"/"STREAM_ON_DESKTOP" are only *offered* to sessions that look
# like the desktop app, so the default footprint mimics the Windows client.
DEFAULT_SUPER_PROPERTIES: dict[str, Any] = {
    "os": "Windows",
    "browser": "Discord Client",
    "release_channel": "stable",
    "client_version": "1.0.9046",
    "os_version": "10.0.19045",
    "os_arch": "x64",
    "app_arch": "x64",
    "system_locale": "en-US",
    "client_build_number": 359820,
    "native_build_number": 65515,
    "client_event_source": None,
}

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) discord/1.0.9046 Chrome/128.0.6613.186 "
    "Electron/32.2.5 Safari/537.36"
)


class QuestAPIError(RuntimeError):
    """Raised when the Discord API returns a non-2xx status."""

    def __init__(self, status: int, body: Any, endpoint: str) -> None:
        self.status = status
        self.body = body
        self.endpoint = endpoint
        code = body.get("code") if isinstance(body, dict) else None
        message = body.get("message") if isinstance(body, dict) else body
        super().__init__(f"{endpoint} -> HTTP {status}"
                         + (f" (code {code})" if code else "")
                         + (f": {message}" if message else ""))

    @property
    def is_quest_unavailable(self) -> bool:
        """Statuses that mean 'this quest is gone / not for you' -> skip it."""
        return self.status in (400, 403, 404, 409, 410)


def encode_super_properties(props: dict[str, Any]) -> str:
    """Base64-encode the super-properties dict the way the Discord client does."""
    raw = json.dumps(props, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("utf-8")


def build_super_properties(
    base: dict[str, Any] | None = None,
    *,
    locale: str = "en-US",
    randomize_build: bool = True,
) -> dict[str, Any]:
    """Return a super-properties dict with a fresh, plausible fingerprint.

    Keeps the desktop footprint but varies the build number and syncs the
    locale, so two runs don't present a byte-identical fingerprint.
    """
    props = dict(base or DEFAULT_SUPER_PROPERTIES)
    props["system_locale"] = locale
    if randomize_build:
        props["client_build_number"] = random.choice(KNOWN_BUILD_NUMBERS)
    return props


class DiscordQuestAPI:
    def __init__(
        self,
        token: str,
        *,
        super_properties: dict[str, Any] | None = None,
        user_agent: str | None = None,
        locale: str = "en-US",
        timeout: float = 30.0,
        api_base: str = API_BASE,
        proxy: str | None = None,
        timezone: str = "America/New_York",
        session: requests.Session | None = None,
    ) -> None:
        if not token or not token.strip():
            raise ValueError("A Discord user token is required.")
        self.token = token.strip()
        self.super_properties = super_properties or build_super_properties(locale=locale)
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        self.locale = locale
        self.timezone = timezone
        self.timeout = timeout
        self.api_base = api_base.rstrip("/")
        self.session = session or requests.Session()
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        self.session.headers.update(self._base_headers())

    def _base_headers(self) -> dict[str, str]:
        # Headers mirror what the desktop client actually sends so the request
        # shape (not just the token) looks like a real session.
        if "," in self.locale:
            lang = self.locale
        else:
            lang = f"{self.locale},{self.locale.split('-')[0]};q=0.9"
        return {
            "Authorization": self.token,
            "User-Agent": self.user_agent,
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Accept-Language": lang,
            "X-Discord-Locale": self.locale,
            "X-Discord-Timezone": self.timezone,
            "X-Super-Properties": encode_super_properties(self.super_properties),
            "X-Debug-Options": "bugReporterEnabled",
            "Origin": "https://discord.com",
            "Referer": "https://discord.com/quests",
        }

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        url = f"{self.api_base}{path}"
        for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
            resp = self.session.request(
                method, url,
                data=json.dumps(body) if body is not None else None,
                timeout=self.timeout,
            )
            try:
                parsed: Any = resp.json()
            except ValueError:
                parsed = resp.text
            # Respect Discord's rate limiter: back off for the advertised
            # window (plus jitter) rather than hammering and looking like a bot.
            if resp.status_code == 429 and attempt < MAX_RATE_LIMIT_RETRIES:
                retry_after = _retry_after_seconds(resp, parsed)
                time.sleep(retry_after + random.uniform(0.1, 0.6))
                continue
            if not resp.ok:
                raise QuestAPIError(resp.status_code, parsed, f"{method} {path}")
            return parsed
        raise QuestAPIError(429, parsed, f"{method} {path}")

    # --- endpoints -------------------------------------------------------
    def get_quests(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/quests/@me")
        if isinstance(data, dict):
            return data.get("quests", []) or []
        if isinstance(data, list):
            return data
        return []

    def enroll(self, quest_id: str) -> Any:
        return self._request(
            "POST", f"/quests/{quest_id}/enroll",
            {"location": 11, "is_targeted": False},
        )

    def video_progress(self, quest_id: str, timestamp: float) -> Any:
        return self._request(
            "POST", f"/quests/{quest_id}/video-progress",
            {"timestamp": round(float(timestamp), 6)},
        )

    def heartbeat(self, quest_id: str, stream_key: str, terminal: bool = False) -> Any:
        return self._request(
            "POST", f"/quests/{quest_id}/heartbeat",
            {"stream_key": stream_key, "terminal": terminal},
        )

    def claim_reward(self, quest_id: str) -> Any:
        return self._request(
            "POST", f"/quests/{quest_id}/claim-reward",
            {
                "platform": 0,
                "location": 11,
                "is_targeted": False,
                "metadata_raw": None,
                "metadata_sealed": None,
                "traffic_metadata_raw": None,
                "traffic_metadata_sealed": None,
            },
        )


def _retry_after_seconds(resp: requests.Response, parsed: Any) -> float:
    """Extract the rate-limit wait window from a 429 response."""
    if isinstance(parsed, dict) and parsed.get("retry_after") is not None:
        try:
            return max(0.0, float(parsed["retry_after"]))
        except (TypeError, ValueError):
            pass
    header = resp.headers.get("Retry-After")
    if header:
        try:
            return max(0.0, float(header))
        except ValueError:
            pass
    return 1.0
