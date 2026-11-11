# Meerkat (meerkat-posture)

Offline posture reminder. Meerkat watches your webcam, tracks your head and shoulders with
MediaPipe, and nudges you when you hold a bad posture too long or sit too long.
Everything runs on your computer.

> Meerkat is a reminder tool, not a medical device. If you have ongoing pain, see a
> physiotherapist or doctor.

## Privacy

Meerkat looks at you all day, so these rules are fixed in the code:

1. **No images or video are ever saved.** Each camera frame is processed in memory and
   dropped right away.
2. **No network access while running.** No telemetry, no update checks, no model downloads.
   The models are fetched once, during setup, by a separate script
   (`scripts/download_models.py`). That script is the only code that touches the network.
3. **Models are local files** in `models/`.
4. **Only numbers are stored** (angles, states, times) in a SQLite file in your user folder.
   You can turn that off (`[storage] enabled = false`).
5. **Pause really turns the camera off.** The device is released and the camera light goes out.
6. **The camera image is shown only when you ask for it** (tray menu "debug window", or
   `--debug`).

## What it checks

| Check | Default alert |
|---|---|
| Head down / head up | more than 15° / 10° from your calibrated pose for 30 s |
| Looking away (outside all calibrated screens) | more than 15° for 20 s |
| Head tilted sideways | more than 10° for 30 s |
| Leaning in toward the screen | face 15% larger than calibrated for 45 s |
| Shoulders tilted / body twisted / slouching | for 60 s |
| Sitting too long | after 30 min, then every 15 min until you stand up |

A second screen can be calibrated as its own "zone", so looking at it doesn't count as
looking away. Alerts have cooldowns (5 min per rule, 60 s between any two) so it stays quiet
enough to leave on all day. All values are in `config.toml`.

## Setup

Needs Python 3.11+ and [uv](https://github.com/astral-sh/uv).

```sh
uv sync
uv run python scripts/download_models.py   # one-time, downloads the models into models/
uv run python -m meerkat                   # start the tray app
```

On first start Meerkat asks you to sit up straight and look at your main screen for a few
seconds (calibration). After that it lives in the system tray:

- green: good posture, yellow: drifting, red: held a bad posture too long,
  grey: paused (camera off)
- right-click for: today's stats, pause, snooze the stand-up reminder, calibrate,
  choose camera, record session, debug window, open config, quit

Ctrl+C in the terminal also quits. Only one copy runs at a time.

## Windows app (.exe)

Build a folder with `Meerkat.exe` (no Python needed to run it, no terminal window):

```sh
uv run python scripts/download_models.py   # if not done yet
uv run pyinstaller meerkat.spec --noconfirm
```

The result is `dist/Meerkat/` (about 300 MB, because MediaPipe and OpenCV are inside).
Move the whole folder wherever you like and run `Meerkat.exe`. Then tick
**"เปิดอัตโนมัติตอนเข้า Windows"** in the tray menu to start it at sign-in (per-user, no admin).
If you move the folder later, toggle that option off and on again.

The exe is not code-signed, so Windows SmartScreen may warn the first time:
"More info" → "Run anyway". Logs go to `meerkat.log` in the data folder (tray menu
"เปิดโฟลเดอร์ข้อมูล / log"). `Meerkat.exe --selftest` checks that models, icons and sounds
load, without using the camera.

## Settings

`config.toml` lives in your user config folder: `%APPDATA%\meerkat` on Windows,
`~/Library/Application Support/meerkat` on macOS, `~/.config/meerkat` on Linux.
Edits are picked up within a few seconds. Some useful ones:

```toml
[alerts]
sound_posture = true      # chirp on posture alerts
sound_break = true        # chirp on stand-up reminders
sound_style = "meerkat"   # or "system" for the OS notification sound

[sitting]
break_after_min = 30.0
repeat_min = 15.0

[buddy]                   # the meerkat that pops up to get you standing
enabled = true
escalate_after_min = 5.0  # starts hopping if you're still sitting
center_after_min = 10.0   # walks to the middle of the screen
center = true             # false = stay in the corner

[rules.head_down]
threshold = 15.0          # degrees below your calibrated pose
hold_s = 30.0
enabled = true
```

## Data (numbers only)

- `meerkat.sqlite`: a 10-second summary of the metrics plus events (alerts, stand-ups,
  reminders). It feeds "today's stats" in the tray menu.
- "Record session" in the tray menu writes per-frame metrics to `sessions/*.csv`.
  No images. Re-run the rules on a recording to try other thresholds:

  ```sh
  uv run python -m meerkat --replay path/to/session.csv [--config other.toml]
  ```

## Development

```sh
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run python -m meerkat --debug          # camera window only, shows the raw numbers
uv run python scripts/make_icons.py       # regenerate tray icons
uv run python scripts/make_sounds.py      # regenerate alert sounds
```

The posture logic (`metrics.py`, `rules.py`, `sitting.py`) is pure functions and is tested
with made-up numbers, no camera needed. See [PLAN.md](PLAN.md) for the roadmap.

## License

MIT. Third-party licenses: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
