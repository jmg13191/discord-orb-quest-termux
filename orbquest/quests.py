"""Parsing helpers for the raw quest objects returned by Discord."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

# Task keys that are driven by the /video-progress endpoint.
VIDEO_TASKS = ("WATCH_VIDEO", "WATCH_VIDEO_ON_MOBILE")

# Task keys that are driven by the /heartbeat endpoint. These are the ones that
# would normally need a desktop client + an installed/running game or an active
# stream; the heartbeat endpoint lets us report progress without any of that.
HEARTBEAT_TASKS = (
    "PLAY_ON_DESKTOP",
    "STREAM_ON_DESKTOP",
    "PLAY_ON_XBOX",
    "PLAY_ON_PLAYSTATION",
    "PLAY_ACTIVITY",
)

# Order matters for detection: the first matching key wins.
SUPPORTED_TASKS = VIDEO_TASKS + HEARTBEAT_TASKS

# Reward "type" -> human label. 4 is the orb/collectible currency reward.
REWARD_LABELS = {
    1: "in-game reward",
    2: "reward code",
    3: "avatar decoration",
    4: "orbs",
    5: "collectible",
}


@dataclass(frozen=True)
class TaskInfo:
    key: str          # e.g. "PLAY_ON_DESKTOP"
    target: int       # seconds (heartbeat/video) required to complete
    uses_heartbeat: bool


@dataclass
class Quest:
    id: str
    name: str
    raw: dict[str, Any]

    @property
    def config(self) -> dict[str, Any]:
        return self.raw.get("config", {}) or {}

    @property
    def user_status(self) -> dict[str, Any]:
        return self.raw.get("user_status") or self.raw.get("userStatus") or {}

    @property
    def application_id(self) -> str | None:
        app = self.config.get("application") or {}
        return app.get("id")

    @property
    def enrolled(self) -> bool:
        us = self.user_status
        return bool(us.get("enrolled_at") or us.get("enrolledAt"))

    @property
    def completed(self) -> bool:
        us = self.user_status
        return bool(us.get("completed_at") or us.get("completedAt"))

    @property
    def claimed(self) -> bool:
        us = self.user_status
        return bool(us.get("claimed_at") or us.get("claimedAt"))

    @property
    def expires_at(self) -> datetime | None:
        raw = self.config.get("expires_at") or self.config.get("expiresAt")
        return _parse_iso(raw)

    @property
    def expired(self) -> bool:
        exp = self.expires_at
        return exp is not None and exp <= datetime.now(timezone.utc)

    @property
    def reward_label(self) -> str:
        rewards_cfg = self.config.get("rewards_config") or self.config.get("rewardsConfig") or {}
        rewards = rewards_cfg.get("rewards") or []
        if not rewards:
            return "unknown reward"
        first = rewards[0]
        name = (first.get("messages") or {}).get("name")
        if name:
            return name
        return REWARD_LABELS.get(first.get("type"), "unknown reward")

    def task(self) -> TaskInfo | None:
        return detect_task(self.config, self.application_id)

    def current_progress(self, task: TaskInfo) -> float:
        progress = self.user_status.get("progress") or {}
        entry = progress.get(task.key) or {}
        if "value" in entry:
            return float(entry["value"])
        stream = self.user_status.get("stream_progress_seconds") \
            or self.user_status.get("streamProgressSeconds")
        return float(stream or 0)


def detect_task(config: dict[str, Any], application_id: str | None = None) -> TaskInfo | None:
    task_config = config.get("task_config") or config.get("taskConfig") \
        or config.get("task_config_v2") or config.get("taskConfigV2") or {}
    tasks = task_config.get("tasks") or {}
    for key in SUPPORTED_TASKS:
        entry = tasks.get(key)
        if entry:
            return TaskInfo(
                key=key,
                target=int(entry.get("target", 0)),
                uses_heartbeat=key in HEARTBEAT_TASKS,
            )
    # Fallback: an app-backed quest with an unrecognised key is treated as a
    # desktop play task (the most common shape).
    if application_id and tasks:
        first_key = next(iter(tasks))
        return TaskInfo(
            key=first_key,
            target=int((tasks[first_key] or {}).get("target", 0)),
            uses_heartbeat=True,
        )
    return None


def parse_quests(raw_quests: list[dict[str, Any]]) -> list[Quest]:
    out: list[Quest] = []
    for raw in raw_quests:
        config = raw.get("config", {}) or {}
        name = (config.get("messages") or {}).get("quest_name") \
            or (config.get("messages") or {}).get("questName") \
            or "Unknown Quest"
        out.append(Quest(id=str(raw.get("id")), name=name, raw=raw))
    return out


def _parse_iso(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
