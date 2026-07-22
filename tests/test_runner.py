"""Runner tests using a fake in-memory API (no network, no sleeps)."""

from __future__ import annotations

import orbquest.runner as runner_mod
from orbquest.quests import parse_quests
from orbquest.runner import QuestRunner


class FakeAPI:
    """Simulates Discord's server-side progress accounting."""

    def __init__(self, target: int, key: str, step: int = 60):
        self.target = target
        self.key = key
        self.step = step
        self.value = 0
        self.enrolled = False
        self.claimed = False
        self.heartbeats = 0
        self.terminal_sent = False

    def enroll(self, quest_id):
        self.enrolled = True
        return {}

    def heartbeat(self, quest_id, stream_key, terminal=False):
        self.heartbeats += 1
        if terminal:
            self.terminal_sent = True
            return {"progress": {self.key: {"value": self.value}}}
        self.value = min(self.target, self.value + self.step)
        return {"progress": {self.key: {"value": self.value}}}

    def video_progress(self, quest_id, timestamp):
        self.value = min(self.target, int(timestamp))
        completed = self.value >= self.target
        return {
            "progress": {self.key: {"value": self.value}},
            "completed_at": "now" if completed else None,
        }

    def claim_reward(self, quest_id):
        self.claimed = True
        return {}


def _quest(task_key: str, target: int):
    raw = {
        "id": "q1",
        "config": {
            "expires_at": "2999-01-01T00:00:00+00:00",
            "messages": {"quest_name": "Test Quest"},
            "application": {"id": "999"},
            "rewards_config": {"rewards": [{"type": 4, "messages": {"name": "Orbs"}}]},
            "task_config": {"tasks": {task_key: {"target": target}}},
        },
        "user_status": {},
    }
    return parse_quests([raw])[0]


def test_heartbeat_quest_completes_and_claims(monkeypatch):
    monkeypatch.setattr(runner_mod.time, "sleep", lambda *_: None)
    quest = _quest("PLAY_ON_DESKTOP", 180)
    api = FakeAPI(target=180, key="PLAY_ON_DESKTOP", step=60)
    result = QuestRunner(api, auto_claim=True).run(quest)
    assert result.completed is True
    assert api.enrolled is True
    assert api.terminal_sent is True
    assert api.claimed is True
    assert api.heartbeats >= 3


def test_video_quest_completes(monkeypatch):
    monkeypatch.setattr(runner_mod.time, "sleep", lambda *_: None)
    quest = _quest("WATCH_VIDEO", 30)
    api = FakeAPI(target=30, key="WATCH_VIDEO")
    result = QuestRunner(api, auto_claim=False).run(quest)
    assert result.completed is True
    assert api.claimed is False


def test_dry_run_sends_nothing():
    quest = _quest("PLAY_ON_DESKTOP", 180)
    api = FakeAPI(target=180, key="PLAY_ON_DESKTOP")
    result = QuestRunner(api, dry_run=True).run(quest)
    assert result.completed is False
    assert api.heartbeats == 0
    assert api.enrolled is False


def test_invalid_target_is_skipped():
    quest = _quest("PLAY_ON_DESKTOP", 0)
    api = FakeAPI(target=0, key="PLAY_ON_DESKTOP")
    result = QuestRunner(api).run(quest)
    assert result.completed is False
    assert "invalid target" in result.reason
