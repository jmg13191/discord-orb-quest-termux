# orbquest — Discord orb quests from Termux

Complete Discord **orb / reward quests** from your Android phone using
[Termux](https://termux.dev/), with **no PC and no game installs**.

Discord quests (the "play this game for 15 minutes", "watch this video", "stream
this game" tasks that reward orbs, avatar decorations, and other collectibles)
are normally designed to be completed by the **desktop app**, which detects a
running game / active stream / watched video and reports progress to Discord.

The key insight — the same one used by the browser-based quest completers this
project is modelled on — is that Discord verifies quest progress **server-side
from a few ordinary REST calls**. Those calls don't actually need a PC or the
game; they only need a valid account session. This tool makes exactly those
calls from Python, so it runs anywhere Python runs — including Termux.

> ⚠️ **Read this first — Terms of Service & account risk.**
> Automating quests with a **user token** is a form of self-botting and
> **violates Discord's Terms of Service**. Discord can (and does) flag,
> disable, or ban accounts for API automation. There is no such thing as a
> "safe" token automation tool — you use this **entirely at your own risk**.
> Do not use it on an account you care about. This project is provided for
> educational purposes, to document how the quest endpoints work.

---

## How it works

| Quest task | Normally needs | What orbquest sends |
|---|---|---|
| `WATCH_VIDEO` / `WATCH_VIDEO_ON_MOBILE` | Watching the video in-client | `POST /quests/{id}/video-progress` with an increasing `timestamp` |
| `PLAY_ON_DESKTOP` | Desktop app + installed game running | `POST /quests/{id}/heartbeat` with a `stream_key` every ~20s |
| `STREAM_ON_DESKTOP` | Desktop app + active stream | same heartbeat flow |
| `PLAY_ACTIVITY` | Being in a voice/activity | same heartbeat flow |

The flow per quest is:

1. `GET /quests/@me` — discover the quests offered to the account.
2. `POST /quests/{id}/enroll` — accept the quest (if not already enrolled).
3. Loop the appropriate progress call until Discord's server-side counter
   reaches the task target.
4. `POST /quests/{id}/claim-reward` — claim the orbs (unless `--no-claim`).

Because `PLAY_ON_DESKTOP`/`STREAM_ON_DESKTOP` quests are only *offered* to
sessions that look like the desktop client, the API client sends a
desktop-flavoured `X-Super-Properties` header and user-agent by default (both
overridable in config).

---

## Install on Termux

```bash
# In Termux on your Android device:
pkg install -y git
git clone https://github.com/jmg13191/discord-orb-quest-termux.git
cd discord-orb-quest-termux
bash setup-termux.sh
```

`setup-termux.sh` installs Python and the one dependency (`requests`). To do it
manually:

```bash
pkg install -y python
pip install -r requirements.txt
```

---

## Configure your token

The tool needs your Discord **user token**. Provide it any of three ways
(highest priority last): `config.json` → `DISCORD_TOKEN` env var → `--token`.

```bash
cp config.example.json config.json
# edit config.json and paste your token
```

or:

```bash
export DISCORD_TOKEN="your_token_here"
```

`config.json` is git-ignored so you don't commit it by accident.

### Getting your token

Open Discord in a **desktop browser**, open DevTools (F12) → Console, and run:

```js
(webpackChunkdiscord_app.push([[''],{},e=>{m=[];for(let c in e.c)m.push(e.c[c])}]),m)
  .find(m=>m?.exports?.default?.getToken!==undefined).exports.default.getToken()
```

Copy the printed string (without quotes). Treat it like a password — anyone with
your token has full access to your account.

---

## Usage

```bash
# list the quests offered to your account (and their state)
python -m orbquest list

# see what would happen, without sending any progress
python -m orbquest run --dry-run

# complete every runnable quest and claim rewards
python -m orbquest run

# complete only specific quests by id
python -m orbquest run 1234567890 9876543210

# don't auto-claim; go a bit faster
python -m orbquest run --no-claim --speed 2
```

If you installed as a package (`pip install .`) the `orbquest` command is also
available directly, e.g. `orbquest list`.

### Options

| Flag | Meaning |
|---|---|
| `-c, --config PATH` | Path to a config file (default: `config.json` or `~/.config/orbquest/config.json`). |
| `-t, --token TOKEN` | Discord user token. |
| `--channel-id ID` | Real voice/DM channel id to use in heartbeat `stream_key` (optional). |
| `--speed N` | Pacing multiplier (2 = twice as fast). Higher = more suspicious. Ignored in `--stealth`. |
| `--no-claim` | Complete quests but leave rewards unclaimed. |
| `--api-base URL` | Override the API base URL (used by the test suite's mock server). |
| `--dry-run` | (`run`) Print the plan without sending progress. |

---

## Anti-detection

The point of these features is to make traffic look like a **real desktop
client** instead of a burst of identical scripted calls. None of them make bans
impossible — see the ToS warning — they only reduce the most obvious tells.

| Feature | Flag / config | What it does |
|---|---|---|
| **Stealth mode** | `--stealth` / `"stealth": true` | Matches Discord's real cadence (video ~7–10s, heartbeat ~27–32s), forces `speed=1`, and turns on idle gaps. Recommended. |
| **Randomized pacing** | always on | Every delay and progress increment is jittered, never a fixed interval. |
| **Idle between quests** | `--idle MIN MAX` / `"idle_between_quests"` | Random pause between finishing one quest and starting the next. |
| **Warmup delay** | `--warmup MIN MAX` / `"warmup_delay"` | Random pause before the first request, so runs don't start instantly. |
| **Quest-order shuffle** | on by default (`--no-shuffle` to disable) | Completes quests in a random order each run. |
| **Realistic client fingerprint** | automatic | Sends desktop `X-Super-Properties` (with a rotated, plausible build number), matching `User-Agent`, `Accept-Language`, `X-Discord-Locale`, `X-Discord-Timezone`, and `X-Debug-Options` headers. Override via `user_agent` / `super_properties` / `timezone` / `locale` in config. |
| **Randomized stream keys** | automatic | The heartbeat `stream_key` session id is randomized rather than always `:1`. |
| **Rate-limit backoff** | automatic | Honours Discord's `429` `retry_after` / `Retry-After` (with jitter) instead of hammering. |
| **Proxy support** | `--proxy URL` / `"proxy"` | Route all traffic through an HTTP/HTTPS/SOCKS proxy to rotate IPs. |

Recommended everyday invocation:

```bash
python -m orbquest --stealth run
```

---

## Config file

```json
{
  "token": "your_token",
  "channel_id": null,
  "locale": "en-US",
  "timezone": "America/New_York",
  "speed": 1.0,
  "auto_claim": true,
  "user_agent": null,
  "super_properties": null,

  "stealth": true,
  "proxy": null,
  "shuffle": true,
  "idle_between_quests": [5, 20],
  "warmup_delay": [3, 10]
}
```

Leave `user_agent`/`super_properties` as `null` to use the built-in desktop
defaults, or override them with your own values. CLI flags always win over the
config file, which wins over the `DISCORD_TOKEN` env var.

---

## Development

```bash
pip install -r requirements.txt pytest ruff
ruff check .
pytest
```

The tests are fully offline and need no token. They include:

- **unit tests** — task detection, super-properties encoding, quest state,
  runner loops (against a fake in-memory API); and
- **end-to-end tests** — the real CLI run against an in-process **mock Discord
  server** (`tests/mock_discord.py`) that implements the quest endpoints. These
  verify the full enroll → progress → claim flow, that the anti-detection
  fingerprint headers are actually sent, that a `429` is retried, and that
  `--dry-run` sends no state-changing calls.

CI (`.github/workflows/ci.yml`) runs lint + tests on Python 3.9 / 3.11 / 3.12.

---

## Credits & references

The endpoint flow is based on these open-source quest completers:

- [deadmorosebeaver5/auto-discord-quest-completer](https://github.com/deadmorosebeaver5/auto-discord-quest-completer)
- [nvckai/Discord-Web-Auto-Quest-Extension](https://github.com/nvckai/Discord-Web-Auto-Quest-Extension)
- [markterence/discord-quest-completer](https://github.com/markterence/discord-quest-completer)
- [nyxxbit/discord-quest-completer](https://github.com/nyxxbit/discord-quest-completer)

## License

MIT — see [LICENSE](LICENSE).
