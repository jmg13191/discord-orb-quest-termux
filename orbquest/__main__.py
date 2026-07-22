"""Command-line entry point: `python -m orbquest ...`."""

from __future__ import annotations

import argparse
import random
import sys
import time

from . import __version__, ui
from .api import DiscordQuestAPI, QuestAPIError
from .config import Config, load_config
from .quests import Quest, parse_quests
from .runner import QuestRunner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orbquest",
        description="Complete Discord orb quests from Termux over the REST API.",
    )
    parser.add_argument("--version", action="version", version=f"orbquest {__version__}")
    parser.add_argument("-c", "--config", help="Path to a config.json file.")
    parser.add_argument("-t", "--token", help="Discord user token (overrides config/env).")
    parser.add_argument("--channel-id", help="Voice/DM channel id used for heartbeats.")
    parser.add_argument("--speed", type=float, help="Speed multiplier for progress pacing.")
    parser.add_argument("--no-claim", action="store_true", help="Do not auto-claim rewards.")
    parser.add_argument("--api-base", help="Override the API base URL (for testing).")
    parser.add_argument("--proxy", help="HTTP/HTTPS/SOCKS proxy URL for all requests.")

    stealth = parser.add_argument_group("anti-detection")
    stealth.add_argument("--stealth", action="store_true",
                         help="Client-matched pacing + idle gaps (recommended, forces speed 1).")
    stealth.add_argument("--idle", nargs=2, type=float, metavar=("MIN", "MAX"),
                         help="Random idle seconds between quests.")
    stealth.add_argument("--warmup", nargs=2, type=float, metavar=("MIN", "MAX"),
                         help="Random delay (seconds) before the first action.")
    stealth.add_argument("--no-shuffle", action="store_true",
                         help="Do not randomise quest order.")

    sub = parser.add_subparsers(dest="command")
    sub.add_parser("list", help="List quests offered to the account.")

    run_p = sub.add_parser("run", help="Complete quests.")
    run_p.add_argument("quest_ids", nargs="*", help="Quest ids to run (default: all runnable).")
    run_p.add_argument("--dry-run", action="store_true",
                       help="Show what would happen without sending progress.")
    return parser


def _make_api(cfg: Config) -> DiscordQuestAPI:
    return DiscordQuestAPI(
        cfg.token,
        super_properties=cfg.super_properties,
        user_agent=cfg.user_agent,
        locale=cfg.locale,
        timezone=cfg.timezone,
        api_base=cfg.api_base,
        proxy=cfg.proxy,
    )


def _runnable(quest: Quest) -> bool:
    return (
        not quest.completed
        and not quest.expired
        and quest.task() is not None
    )


def cmd_list(api: DiscordQuestAPI) -> int:
    quests = parse_quests(api.get_quests())
    if not quests:
        ui.log("No quests are currently offered to this account.", "warn")
        return 0
    ui.log(f"{len(quests)} quest(s):", "info")
    for q in quests:
        task = q.task()
        if q.completed:
            state, kind = "completed", "ok"
        elif q.expired:
            state, kind = "expired", "dim"
        elif task is None:
            state, kind = "unsupported", "warn"
        else:
            state, kind = ("enrolled" if q.enrolled else "not enrolled"), "info"
        task_desc = f"{task.key} {task.target}s" if task else "n/a"
        ui.log(f"  {q.id}  {q.name}  [{task_desc}]  reward: {q.reward_label}  "
               f"({state})", kind)
    return 0


def cmd_run(api: DiscordQuestAPI, cfg: Config, quest_ids: list[str], dry_run: bool) -> int:
    quests = parse_quests(api.get_quests())
    by_id = {q.id: q for q in quests}

    if quest_ids:
        targets = []
        for qid in quest_ids:
            if qid not in by_id:
                ui.log(f"Quest {qid} not found; skipping.", "warn")
                continue
            targets.append(by_id[qid])
    else:
        targets = [q for q in quests if _runnable(q)]

    if not targets:
        ui.log("Nothing to run (no runnable quests).", "warn")
        return 0

    if cfg.shuffle and not quest_ids:
        random.shuffle(targets)

    if cfg.stealth:
        ui.log("Stealth mode: client-matched pacing, idle gaps, shuffled order.", "info")

    runner = QuestRunner(
        api,
        channel_id=cfg.channel_id,
        speed=cfg.speed,
        auto_claim=cfg.auto_claim,
        dry_run=dry_run,
        stealth=cfg.stealth,
    )

    if not dry_run and cfg.warmup_max > 0:
        delay = random.uniform(cfg.warmup_min, cfg.warmup_max)
        ui.log(f"Warming up for {delay:.0f}s before starting...", "dim")
        time.sleep(delay)

    completed = 0
    for index, quest in enumerate(targets):
        if quest.completed:
            ui.log(f"'{quest.name}' already completed; skipping.", "dim")
            continue
        if not dry_run and index > 0 and cfg.idle_max > 0:
            gap = random.uniform(cfg.idle_min, cfg.idle_max)
            ui.log(f"Idling {gap:.0f}s before next quest...", "dim")
            time.sleep(gap)
        try:
            result = runner.run(quest)
        except QuestAPIError as exc:
            ui.log(f"'{quest.name}' failed: {exc}", "err")
            continue
        except KeyboardInterrupt:
            ui.log("Interrupted by user.", "warn")
            break
        if result.completed:
            completed += 1
        elif result.reason and result.reason != "dry-run":
            ui.log(f"'{quest.name}' not completed: {result.reason}", "warn")

    ui.log(f"Done. {completed}/{len(targets)} quest(s) completed.", "ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    cfg = load_config(
        path=args.config,
        token=args.token,
        channel_id=args.channel_id,
        speed=args.speed,
        no_claim=args.no_claim,
        stealth=args.stealth,
        proxy=args.proxy,
        api_base=args.api_base,
        idle=tuple(args.idle) if args.idle else None,
        warmup=tuple(args.warmup) if args.warmup else None,
        no_shuffle=args.no_shuffle,
    )

    if not cfg.token:
        ui.log("No Discord token found. Provide --token, set DISCORD_TOKEN, "
               "or add it to config.json.", "err")
        return 2

    try:
        api = _make_api(cfg)
    except ValueError as exc:
        ui.log(str(exc), "err")
        return 2

    command = args.command or "list"
    try:
        if command == "list":
            return cmd_list(api)
        if command == "run":
            return cmd_run(api, cfg, args.quest_ids, args.dry_run)
    except QuestAPIError as exc:
        if exc.status in (401, 403):
            ui.log("Discord rejected the token (401/403). Is it valid?", "err")
        else:
            ui.log(f"API error: {exc}", "err")
        return 1
    except KeyboardInterrupt:
        ui.log("Interrupted.", "warn")
        return 130

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
