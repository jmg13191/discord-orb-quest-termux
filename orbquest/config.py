"""Config loading: token + optional overrides from file / env / CLI."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from .api import API_BASE

CONFIG_ENV = "ORBQUEST_CONFIG"
TOKEN_ENV = "DISCORD_TOKEN"
DEFAULT_CONFIG_PATHS = ("config.json", os.path.expanduser("~/.config/orbquest/config.json"))


@dataclass
class Config:
    token: str = ""
    channel_id: str | None = None
    user_agent: str | None = None
    locale: str = "en-US"
    timezone: str = "America/New_York"
    speed: float = 1.0
    auto_claim: bool = True
    super_properties: dict[str, Any] | None = None
    # --- anti-detection ---
    stealth: bool = False
    proxy: str | None = None
    api_base: str = API_BASE
    idle_min: float = 0.0          # min idle gap between quests (seconds)
    idle_max: float = 0.0          # max idle gap between quests (seconds)
    warmup_min: float = 0.0        # min delay before the first action
    warmup_max: float = 0.0        # max delay before the first action
    shuffle: bool = True           # randomise quest order
    _source: str = field(default="defaults", repr=False)


def _read_file(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_config(
    *,
    path: str | None = None,
    token: str | None = None,
    channel_id: str | None = None,
    speed: float | None = None,
    no_claim: bool = False,
    stealth: bool = False,
    proxy: str | None = None,
    api_base: str | None = None,
    idle: tuple[float, float] | None = None,
    warmup: tuple[float, float] | None = None,
    no_shuffle: bool = False,
) -> Config:
    """Merge config from (lowest -> highest priority): file, env, CLI args."""
    data: dict[str, Any] = {}
    source = "defaults"

    file_path = path or os.environ.get(CONFIG_ENV)
    if not file_path:
        for candidate in DEFAULT_CONFIG_PATHS:
            if os.path.isfile(candidate):
                file_path = candidate
                break
    if file_path and os.path.isfile(file_path):
        data = _read_file(file_path)
        source = file_path

    idle_cfg = data.get("idle_between_quests") or [0.0, 0.0]
    warmup_cfg = data.get("warmup_delay") or [0.0, 0.0]

    cfg = Config(
        token=str(data.get("token", "")),
        channel_id=data.get("channel_id"),
        user_agent=data.get("user_agent"),
        locale=data.get("locale", "en-US"),
        timezone=data.get("timezone", "America/New_York"),
        speed=float(data.get("speed", 1.0)),
        auto_claim=bool(data.get("auto_claim", True)),
        super_properties=data.get("super_properties"),
        stealth=bool(data.get("stealth", False)),
        proxy=data.get("proxy"),
        api_base=str(data.get("api_base", API_BASE)),
        idle_min=float(idle_cfg[0]),
        idle_max=float(idle_cfg[1]),
        warmup_min=float(warmup_cfg[0]),
        warmup_max=float(warmup_cfg[1]),
        shuffle=bool(data.get("shuffle", True)),
        _source=source,
    )

    env_token = os.environ.get(TOKEN_ENV)
    if env_token:
        cfg.token = env_token.strip()

    # CLI args win over everything.
    if token:
        cfg.token = token.strip()
    if channel_id:
        cfg.channel_id = channel_id
    if speed is not None:
        cfg.speed = speed
    if no_claim:
        cfg.auto_claim = False
    if stealth:
        cfg.stealth = True
    if proxy:
        cfg.proxy = proxy
    if api_base:
        cfg.api_base = api_base
    if idle is not None:
        cfg.idle_min, cfg.idle_max = idle
    if warmup is not None:
        cfg.warmup_min, cfg.warmup_max = warmup
    if no_shuffle:
        cfg.shuffle = False

    # Stealth implies a sensible default idle gap when the user didn't set one.
    if cfg.stealth and cfg.idle_max <= 0:
        cfg.idle_min, cfg.idle_max = 5.0, 20.0

    return cfg
