"""Offline unit tests -- no network, no real token."""

from __future__ import annotations

import base64
import json

from orbquest.api import DEFAULT_SUPER_PROPERTIES, encode_super_properties
from orbquest.quests import Quest, detect_task, parse_quests


def _quest(task_key: str, target: int = 300, **user_status) -> dict:
    return {
        "id": "123",
        "config": {
            "expires_at": "2999-01-01T00:00:00+00:00",
            "messages": {"quest_name": "Play Something"},
            "application": {"id": "999"},
            "rewards_config": {"rewards": [{"type": 4, "messages": {"name": "50 Orbs"}}]},
            "task_config": {"tasks": {task_key: {"target": target}}},
        },
        "user_status": user_status,
    }


def test_detect_video_task():
    task = detect_task(_quest("WATCH_VIDEO")["config"], "999")
    assert task is not None
    assert task.key == "WATCH_VIDEO"
    assert task.uses_heartbeat is False
    assert task.target == 300


def test_detect_desktop_play_task_uses_heartbeat():
    task = detect_task(_quest("PLAY_ON_DESKTOP")["config"], "999")
    assert task is not None
    assert task.key == "PLAY_ON_DESKTOP"
    assert task.uses_heartbeat is True


def test_detect_task_v2_config_shape():
    cfg = {"task_config_v2": {"tasks": {"STREAM_ON_DESKTOP": {"target": 900}}}}
    task = detect_task(cfg, None)
    assert task is not None
    assert task.key == "STREAM_ON_DESKTOP"
    assert task.target == 900


def test_detect_unknown_app_task_falls_back_to_heartbeat():
    cfg = {"task_config": {"tasks": {"SOME_FUTURE_TASK": {"target": 120}}}}
    task = detect_task(cfg, application_id="42")
    assert task is not None
    assert task.uses_heartbeat is True
    assert task.target == 120


def test_detect_returns_none_without_supported_task_or_app():
    assert detect_task({"task_config": {"tasks": {}}}, None) is None


def test_super_properties_round_trip():
    encoded = encode_super_properties(DEFAULT_SUPER_PROPERTIES)
    decoded = json.loads(base64.b64decode(encoded))
    assert decoded["browser"] == "Discord Client"
    assert decoded["os"] == "Windows"


def test_quest_state_flags():
    q = parse_quests([_quest("PLAY_ON_DESKTOP", enrolled_at="2020-01-01T00:00:00Z")])[0]
    assert isinstance(q, Quest)
    assert q.name == "Play Something"
    assert q.enrolled is True
    assert q.completed is False
    assert q.expired is False
    assert q.reward_label == "50 Orbs"
    assert q.application_id == "999"


def test_expired_quest_detected():
    raw = _quest("PLAY_ON_DESKTOP")
    raw["config"]["expires_at"] = "2000-01-01T00:00:00+00:00"
    q = parse_quests([raw])[0]
    assert q.expired is True


def test_current_progress_reads_task_value():
    raw = _quest("PLAY_ON_DESKTOP", progress={"PLAY_ON_DESKTOP": {"value": 42}})
    q = parse_quests([raw])[0]
    task = q.task()
    assert task is not None
    assert q.current_progress(task) == 42.0
