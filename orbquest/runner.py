"""Drives a single quest to completion by replaying progress calls."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

from . import ui
from .api import DiscordQuestAPI, QuestAPIError
from .quests import Quest, TaskInfo

# Discord's own web player reports a video timestamp roughly every 7-10s. By
# default we go a bit faster but keep it jittered so it is not a fixed cadence.
VIDEO_STEP_RANGE = (3.5, 4.75)
# Heartbeats for play/stream/activity are accepted on a ~20-30s cadence.
HEARTBEAT_INTERVAL_RANGE = (20.0, 24.0)

# Stealth mode mirrors the real client's cadence exactly instead of rushing.
STEALTH_VIDEO_STEP_RANGE = (7.0, 10.0)
STEALTH_HEARTBEAT_INTERVAL_RANGE = (27.0, 32.0)

MAX_FAILURES = 5
# Safety cap so a stuck quest can never loop forever (25 min like the refs).
MAX_RUNTIME_SECONDS = 25 * 60


@dataclass
class RunResult:
    quest_id: str
    completed: bool
    reason: str = ""


class QuestRunner:
    def __init__(
        self,
        api: DiscordQuestAPI,
        *,
        channel_id: str | None = None,
        speed: float = 1.0,
        auto_claim: bool = True,
        dry_run: bool = False,
        stealth: bool = False,
    ) -> None:
        self.api = api
        self.channel_id = channel_id
        # In stealth mode we never speed up -- realistic timing is the point.
        self.speed = 1.0 if stealth else max(0.1, speed)
        self.auto_claim = auto_claim
        self.dry_run = dry_run
        self.stealth = stealth
        self.video_step = STEALTH_VIDEO_STEP_RANGE if stealth else VIDEO_STEP_RANGE
        self.heartbeat_interval = (
            STEALTH_HEARTBEAT_INTERVAL_RANGE if stealth else HEARTBEAT_INTERVAL_RANGE
        )

    def _sleep(self, low: float, high: float) -> None:
        if self.dry_run:
            return
        time.sleep(random.uniform(low, high) / self.speed)

    def _stream_key(self, quest: Quest) -> str:
        # A real voice/DM channel id is preferred; when we do not have one the
        # quest id works as a stand-in (matches the browser extension fallback).
        # The trailing session counter is randomised so it is not always ':1'.
        base = self.channel_id or quest.id
        return f"call:{base}:{random.randint(1, 9999)}"

    def run(self, quest: Quest) -> RunResult:
        task = quest.task()
        if task is None:
            return RunResult(quest.id, False, "unsupported task type")
        if task.target <= 0:
            return RunResult(quest.id, False, "invalid target")

        if not quest.enrolled:
            if self.dry_run:
                ui.log(f"[dry-run] would enroll in '{quest.name}'", "dim")
            else:
                try:
                    self.api.enroll(quest.id)
                    ui.log(f"Enrolled in '{quest.name}'", "ok")
                except QuestAPIError as exc:
                    if exc.is_quest_unavailable:
                        return RunResult(quest.id, False, f"enroll rejected ({exc.status})")
                    raise

        if self.dry_run:
            ui.log(f"[dry-run] would complete '{quest.name}' "
                   f"({task.key}, target {task.target}s)", "dim")
            return RunResult(quest.id, False, "dry-run")

        if task.uses_heartbeat:
            result = self._run_heartbeat(quest, task)
        else:
            result = self._run_video(quest, task)

        if result.completed and self.auto_claim:
            self._claim(quest)
        return result

    def _run_video(self, quest: Quest, task: TaskInfo) -> RunResult:
        cur = quest.current_progress(task)
        failures = 0
        started = time.monotonic()
        ui.log(f"Watching '{quest.name}' -> {ui.progress_bar(cur, task.target)}", "info")

        while cur < task.target:
            self._sleep(*self.video_step)
            cur = min(task.target, cur + random.uniform(*self.video_step) * self.speed)
            try:
                resp = self.api.video_progress(quest.id, cur)
                server = _server_progress(resp, task.key)
                if server is not None:
                    cur = min(task.target, max(cur, server))
                failures = 0
                if isinstance(resp, dict) and resp.get("completed_at"):
                    cur = task.target
            except QuestAPIError as exc:
                if exc.is_quest_unavailable:
                    return RunResult(quest.id, False, f"quest unavailable ({exc.status})")
                failures += 1
                if failures >= MAX_FAILURES:
                    return RunResult(quest.id, False, "too many network failures")
            ui.log(f"  {quest.name}: {ui.progress_bar(cur, task.target)}", "dim")
            if time.monotonic() - started > MAX_RUNTIME_SECONDS:
                return RunResult(quest.id, False, "timeout")

        ui.log(f"Completed '{quest.name}'", "ok")
        return RunResult(quest.id, True)

    def _run_heartbeat(self, quest: Quest, task: TaskInfo) -> RunResult:
        stream_key = self._stream_key(quest)
        cur = quest.current_progress(task)
        failures = 0
        started = time.monotonic()
        ui.log(f"Simulating '{quest.name}' [{task.key}] -> "
               f"{ui.progress_bar(cur, task.target)}", "info")

        while cur < task.target:
            try:
                resp = self.api.heartbeat(quest.id, stream_key, terminal=False)
                server = _server_progress(resp, task.key)
                cur = server if server is not None else cur + 20
                failures = 0
            except QuestAPIError as exc:
                if exc.is_quest_unavailable:
                    return RunResult(quest.id, False, f"quest unavailable ({exc.status})")
                failures += 1
                if failures >= MAX_FAILURES:
                    return RunResult(quest.id, False, "too many network failures")
            ui.log(f"  {quest.name}: {ui.progress_bar(cur, task.target)}", "dim")
            if cur >= task.target:
                break
            if time.monotonic() - started > MAX_RUNTIME_SECONDS:
                return RunResult(quest.id, False, "timeout")
            self._sleep(*self.heartbeat_interval)

        try:
            self.api.heartbeat(quest.id, stream_key, terminal=True)
        except QuestAPIError:
            pass  # terminal ping is best-effort
        ui.log(f"Completed '{quest.name}'", "ok")
        return RunResult(quest.id, True)

    def _claim(self, quest: Quest) -> None:
        try:
            self.api.claim_reward(quest.id)
            ui.log(f"Claimed reward for '{quest.name}' ({quest.reward_label})", "ok")
        except QuestAPIError as exc:
            ui.log(f"Could not claim '{quest.name}': {exc}", "warn")


def _server_progress(resp: object, key: str) -> float | None:
    if not isinstance(resp, dict):
        return None
    progress = resp.get("progress")
    if not isinstance(progress, dict):
        return None
    entry = progress.get(key)
    if isinstance(entry, dict) and "value" in entry:
        return float(entry["value"])
    return None
