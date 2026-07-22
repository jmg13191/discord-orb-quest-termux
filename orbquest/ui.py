"""Small terminal logger. ANSI colours degrade gracefully on Termux."""

from __future__ import annotations

import os
import sys
from datetime import datetime

_USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

_COLORS = {
    "info": "\033[36m",
    "ok": "\033[32m",
    "warn": "\033[33m",
    "err": "\033[31m",
    "dim": "\033[90m",
}
_RESET = "\033[0m"


def _color(text: str, kind: str) -> str:
    if not _USE_COLOR:
        return text
    return f"{_COLORS.get(kind, '')}{text}{_RESET}"


def log(message: str, kind: str = "info") -> None:
    stamp = _color(datetime.now().strftime("%H:%M:%S"), "dim")
    print(f"{stamp} {_color(message, kind)}")


def progress_bar(cur: float, target: float, width: int = 24) -> str:
    ratio = 0.0 if target <= 0 else min(1.0, cur / target)
    filled = int(ratio * width)
    bar = "#" * filled + "-" * (width - filled)
    return f"[{bar}] {int(cur)}/{int(target)}s ({ratio * 100:4.1f}%)"
