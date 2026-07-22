"""Config loading: token + optional overrides from file / env / CLI."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

CONFIG_ENV = "ORBQUEST_CONFIG"
TOKEN_ENV = "DISCORD_TOKEN"
DEFAULT_CONFIG_PATHS = ("config.json", os.path.expanduser("~/.config/orbquest/config.json"))


@dataclass
class Config:
    token: str = ""
    channel_id: str | None = None
    user_agent: str | None = None
    locale: str = "en-US"
    speed: float = 1.0
    auto_claim: bool = True
    super_properties: dict[str, Any] | None = None
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

    cfg = Config(
        token=str(data.get("token", "")),
        channel_id=data.get("channel_id"),
        user_agent=data.get("user_agent"),
        locale=data.get("locale", "en-US"),
        speed=float(data.get("speed", 1.0)),
        auto_claim=bool(data.get("auto_claim", True)),
        super_properties=data.get("super_properties"),
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

    return cfg
