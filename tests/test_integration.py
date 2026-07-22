"""End-to-end tests: run the real CLI against an in-process mock Discord."""

from __future__ import annotations

import time

from orbquest.__main__ import main

from .mock_discord import MockDiscord, sample_quests


def test_full_run_completes_and_claims(monkeypatch):
    # No real waiting -- patch the stdlib sleep used by every module.
    monkeypatch.setattr(time, "sleep", lambda *_: None)

    with MockDiscord(sample_quests()) as mock:
        rc = main([
            "--token", "faketoken",
            "--api-base", mock.api_base,
            "--no-shuffle",
            "run",
        ])

    assert rc == 0
    actions = mock.actions()
    assert "enroll" in actions
    assert "heartbeat" in actions        # PLAY_ON_DESKTOP quest
    assert "video-progress" in actions   # WATCH_VIDEO quest
    assert actions.count("claim-reward") == 2

    for quest in mock.quests.values():
        us = quest["user_status"]
        assert us.get("completed_at")
        assert us.get("claimed_at")


def test_anti_detection_headers_are_sent(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_: None)

    with MockDiscord(sample_quests()) as mock:
        main(["--token", "faketoken", "--api-base", mock.api_base, "list"])

        for header in ("X-Super-Properties", "User-Agent", "Accept-Language",
                       "X-Discord-Timezone", "X-Discord-Locale", "Authorization"):
            assert mock.header_seen(header), f"missing {header}"


def test_rate_limit_429_is_retried(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_: None)

    with MockDiscord(sample_quests(), fail_once_429=True) as mock:
        rc = main([
            "--token", "faketoken",
            "--api-base", mock.api_base,
            "--no-shuffle",
            "run", "1000000000000000001",
        ])

    assert rc == 0
    # The injected 429 was retried, so the quest still completes.
    assert mock.quests["1000000000000000001"]["user_status"].get("claimed_at")


def test_stealth_mode_shuffles_and_still_completes(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_: None)

    with MockDiscord(sample_quests()) as mock:
        rc = main([
            "--token", "faketoken",
            "--api-base", mock.api_base,
            "--stealth",
            "run",
        ])

    assert rc == 0
    assert mock.actions().count("claim-reward") == 2


def test_dry_run_sends_only_get(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_: None)

    with MockDiscord(sample_quests()) as mock:
        rc = main([
            "--token", "faketoken",
            "--api-base", mock.api_base,
            "run", "--dry-run",
        ])

    assert rc == 0
    # dry-run must never enroll/progress/claim.
    assert mock.actions() == []
