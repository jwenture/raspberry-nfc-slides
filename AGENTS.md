# AGENTS.md — NFC Slideshow System

## Project Overview

NFC-triggered slideshow kiosk on Raspberry Pi 3. User taps an NFC card, system looks up the card's UID in a local mapping file, and plays a fullscreen looping slideshow of cached images/videos from the associated Google Drive folder. Designed for a non-technical end user: plug in power, wait for "Tap a card" screen, tap card.

Full design document: `plan.md` (856 lines, 15 sections, 41 edge cases).

## Hardware & OS

- **Board**: Raspberry Pi 3 (1GB RAM, ARM Cortex-A53 quad-core 1.2GHz)
- **OS**: Raspberry Pi OS Bookworm (Debian 12, Python 3.11)
- **Screen**: Official 7" DSI touchscreen (800x480, auto-detected via DRM/KMS)
- **NFC Reader**: PN532 module over I2C (default address 0x24, fallback 0x48)
- **Linux user**: `john` (with sudo) — not `pi`
- **No audio** — videos play silently
- **No desktop environment** — minimal Xorg + matchbox-window-manager

## Repository Structure

```
raspberry-nfc-slides/
├── plan.md                    # Full design document (read this first)
├── AGENTS.md                  # This file
├── README.md
├── installation_notes.txt     # Real-world Pi setup notes (swig, liblgpio-dev, I2C enable)
├── nfc-slideshow/             # Main application
│   ├── requirements.txt       # Python deps (adafruit-pn532, python-vlc, pyyaml, Pillow)
│   ├── config/
│   │   ├── settings.yaml      # All app settings (NFC, VLC, sync, screen, paths)
│   │   ├── tags.json          # UID → Google Drive folder mapping
│   │   ├── idle.png           # "Tap a card" screen (placeholder)
│   │   └── error.png          # "Unknown card" screen (placeholder)
│   ├── src/
│   │   ├── __init__.py
│   │   ├── config.py          # Config dataclasses + loader + logging setup
│   │   ├── main.py            # Entry point — full state machine (IDLE/PLAYING/ERROR)
│   │   ├── nfc_reader.py      # PN532 I2C polling, edge-triggered, debounce
│   │   ├── tag_mapper.py      # tags.json loader, lookup, mtime-based reload
│   │   └── slideshow.py       # VLC controller (MediaListPlayer, idle, playlist)
│   ├── sync/
│   │   └── __init__.py        # (sync_all.py and transcode.py not yet created)
│   ├── scripts/
│   │   └── generate_assets.py # Generates idle.png and error.png
│   ├── cache/                 # Processed media (cache/<uid>/processed/)
│   └── logs/                  # Rotating logs (5MB x 3 files)
└── nfc-test/
    └── test_nfc.py            # Standalone NFC reader test script
```

## Implementation Status

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Core playback (VLC, no NFC, no sync) | Code written, untested on Pi |
| 2 | NFC integration | Code written (nfc_reader, tag_mapper, main state machine), untested on Pi |
| 3 | Background sync (rclone + ffmpeg) | Not started |
| 4 | Kiosk mode (systemd, install.sh) | Not started |
| 5 | Hardening (watchdog, read-only root) | Not started |

See `plan.md` Section 13 for detailed checklist and Section 15 for file-by-file status.

## Key Design Decisions

### Python is the controller, not the renderer
VLC (C/C++) does all video decode and image rendering via MMAL hardware acceleration. ffmpeg (C/C++) does transcoding during background sync. Python only handles state machine logic, VLC API calls, and I2C polling at human timescales (not frame rate). The GIL is irrelevant.

### Virtual environment required (PEP 668)
Bookworm blocks system-wide `pip install`. All code runs from `venv/bin/python3`. Systemd ExecStart lines use the venv path. Never use `pip3 install` system-wide.

### Foreground app does zero network I/O
Google Drive sync runs as a background systemd timer at 3 AM. The foreground app only reads local `cache/<uid>/processed/`. This is what keeps playback smooth. Never add network calls to `main.py` or `slideshow.py`.

### Pre-transcode to 800x480 H.264 baseline
Background sync transcodes all media to 800x480 H.264 baseline profile (level 3.1) with ffmpeg. This is trivial for the Pi 3's MMAL hardware decoder. Raw files are kept (`keep_raw: true`) for rclone incremental sync.

### VLC MediaListPlayer for playlist looping
The `--loop` instance flag controls single-media looping, not playlist looping. `slideshow.py` uses `MediaListPlayer.set_playback_mode(vlc.PlaybackMode.loop)` instead.

### Per-media image-duration for idle screen
The global `--image-duration=5` flag would cause the idle screen to flicker every 5 seconds. `play_idle()` sets `:image-duration=86400` (24 hours) on the idle media item specifically, overriding the instance default. No flicker.

### Non-blocking play_image()
`play_image()` starts a timed image display (e.g., error.png for 3s) without blocking the main loop. VLC handles the timing via `:image-duration=N` on the media. `update()` returns True when VLC stops naturally (detected via `is_playing()` after a 0.5s grace period to avoid race condition).

### Path resolution from project root, not CWD
`config.py` resolves all paths relative to `settings.yaml`'s parent.parent (project root). Works regardless of working directory. Entry points (`main.py`, `sync_all.py`) add project root to `sys.path` for imports.

### Screen dimensions: single source of truth
`settings.yaml` `screen.width` and `screen.height` are consumed by `slideshow.py`, `transcode.py`, and `generate_assets.py`. Never hardcode 800x480.

### File ordering: alphabetical by filename
Media files in `cache/<uid>/processed/` are sorted alphabetically by `main.py` before passing to `slideshow.play_playlist()`.

## State Machine (`main.py`)

Three states: `IDLE`, `PLAYING`, `ERROR`.

```
IDLE (VLC loops idle.png)
  └─ tag detected ──> lookup UID in tags.json
       ├─ found + has media ──> PLAYING (VLC plays cache/<uid>/processed/*)
       ├─ found + no media ──> ERROR (error.png 5s) ──> IDLE
       └─ not found ──> ERROR (error.png 3s) ──> IDLE

PLAYING
  └─ new tag ──> lookup (same as IDLE tag handling)
  └─ same tag re-tapped ──> restart playlist
  └─ tag removed + 30s idle_timeout ──> IDLE

ERROR
  └─ slideshow.update() returns True ──> IDLE
  └─ new tag during error ──> lookup (interrupts error display)
```

Key behaviors:
- NFC polling is edge-triggered: `poll()` only returns a UID on first detection, not while the same tag stays on the reader
- After ERROR → IDLE, the same tag must be removed and re-tapped to trigger again (prevents repeated error flashes)
- `tags.json` is reloaded if mtime changes (checked every 4 hours)
- NFC init failure shows error.png indefinitely (not a timed display)
- SIGINT/SIGTERM set a shutdown flag; cleanup runs in `finally` block

## Configuration

### settings.yaml
All application settings. Key values:
- `nfc.i2c_address`: PN532 I2C address (0x24 default, 0x48 alternative)
- `nfc.poll_interval`: 0.2s between NFC polls
- `slideshow.image_duration`: 5.0s per image in slideshow
- `slideshow.idle_timeout`: 30s before returning to idle after tag removal
- `slideshow.tags_reload_interval`: 14400s (4h) between tags.json mtime checks
- `paths.log_file`: app log file (./logs/app.log, rotating 5MB x 3)
- `screen.width/height`: 800x480 (single source of truth)
- `sync.keep_raw`: true (required for rclone incremental sync)
- `sync.log_file`: sync log file (./logs/sync.log, separate from app log)
- `sync.supported_image_extensions`: [".jpg", ".jpeg", ".png", ".heic"]
- `sync.supported_video_extensions`: [".mp4", ".mov", ".avi", ".mkv"]

### tags.json
Maps NFC tag UIDs to Google Drive folders. UID format: uppercase hex with colons (e.g., `04:A3:2B:1C:00:01`). Must match exactly what `nfc_reader.py` returns. `main.py` checks mtime every 4 hours and reloads if changed — no service restart needed to add tags.

## Dependencies

### Python (requirements.txt)
- `adafruit-circuitpython-pn532>=2.0` — PN532 NFC reader driver
- `adafruit-blinka>=8.0` — CircuitPython hardware abstraction for Pi
- `python-vlc>=3.0` — VLC Python bindings (requires `vlc` apt package)
- `pyyaml>=6.0` — YAML config parsing
- `Pillow>=10.0` — Image generation for idle/error screens

### System (apt install)
`vlc rclone ffmpeg python3-pip python3-venv i2c-tools xserver-xorg-video-fbdev matchbox-window-manager libheif-examples swig liblgpio-dev`

`swig` and `liblgpio-dev` are required for `adafruit-blinka` to compile on Bookworm. Without them, `pip install adafruit-blinka` fails.

### Not on Bookworm
- `omxplayer` — Buster only, not a fallback option
- System-wide `pip install` — blocked by PEP 668, use venv

## How to Run

### NFC reader test (standalone)
```bash
sudo apt install swig liblgpio-dev          # required for adafruit-blinka on Bookworm
sudo raspi-config nonint do_i2c 0           # enable I2C (or use raspi-config menu: 3 → I5 → Yes)
i2cdetect -y 1                               # verify PN532 visible (should show 24 or 48)
python3 -m venv venv
venv/bin/pip install adafruit-circuitpython-pn532 adafruit-blinka
venv/bin/python3 test_nfc.py
```

### Full app (on Pi with display + NFC reader)
```bash
sudo apt install swig liblgpio-dev          # required for adafruit-blinka on Bookworm
sudo raspi-config nonint do_i2c 0           # enable I2C
cd /home/john/nfc-slideshow
python3 -m venv venv
venv/bin/pip install -r requirements.txt
# Place media in cache/<uid>/processed/ (matching tags.json UIDs)
venv/bin/python3 src/main.py
# Tap an NFC card to play its slideshow
# Remove card + 30s timeout returns to idle
# Ctrl+C to quit
```

### Generate placeholder assets
```bash
venv/bin/python3 scripts/generate_assets.py
```

## Real-World Installation Findings

Documented in `installation_notes.txt`; these were discovered during actual Pi setup:

1. **`swig` and `liblgpio-dev` required**: `adafruit-blinka` needs these to compile on Bookworm. Without them, `pip install adafruit-blinka` fails. Not documented in plan.md's dependency list — must be installed before pip install.

2. **I2C must be enabled before running**: If I2C is not enabled, `board.I2C()` raises `ValueError: No Hardware I2C on (scl,sda)=(3, 2)`. Fix: `sudo raspi-config` → Interface Options → I2C → Yes, or `sudo raspi-config nonint do_i2c 0`.

3. **Pi 3 I2C ports**: The error message reveals `Valid I2C ports: ((1, 3, 2), (0, 1, 0))` — bus 1 (SCL=GPIO3, SDA=GPIO2) is the default and correct for PN532. Bus 0 (SCL=GPIO1, SDA=GPIO0) is the alternative.

## Code Conventions

- No comments in Python code unless explicitly requested
- `from __future__ import annotations` not used (Python 3.11 supports `str | None` natively)
- Dataclasses for all config objects
- `logging` module (stdlib) with `RotatingFileHandler` (5MB, 3 backups) + `StreamHandler`
- Entry points add project root to `sys.path` for cross-package imports (`src/` and `sync/` are siblings)
- `Path(__file__).resolve().parent.parent` for project root resolution

## Known Issues & Gotchas

1. **`--avcodec-hw=mmal` is Pi-specific**: VLC on Windows/other platforms doesn't have MMAL. This flag is in `slideshow.py` and will cause VLC to fail or warn on non-Pi platforms. Do not remove it — it's required for hardware decode on Pi 3.

2. **`matchbox-window-manager` availability on Bookworm**: Unverified. If not available, fallback to `openbox` or no WM. Check with `apt-cache policy matchbox-window-manager`.

3. **HEIC decode in ffmpeg**: Unverified. `libheif-examples` installed via apt provides `heif-convert`. If ffmpeg lacks HEIC support, `transcode.py` (when implemented) should use `heif-convert` as a pre-step.

4. **VLC stop→play transition**: May cause a brief black flash. Not yet tested. Potential fix: use `set_media` without stopping first, or accept the flash.

5. **`i2c_address: 0x24` in YAML**: PyYAML parses `0x24` as integer 36 (YAML 1.1 hex syntax). This is correct — I2C addresses are integers.

6. **`-nocursor` removed from Xorg**: Was in original plan but is not a valid Xorg flag. Cursor hiding is done by matchbox's `-use_cursor no`.

7. **Auto-login as `john`**: `raspi-config nonint do_boot_to_console 0` only sets console boot, not auto-login. install.sh (when written) must add a systemd override on `getty@tty1.service` with `--autologin john`.

8. **`idle.png` and `error.png` are placeholders**: Black background, white text, generated by `scripts/generate_assets.py`. Content (font, colors, branding) to be defined later.

9. **NFC edge-triggered polling**: `nfc_reader.poll()` only reports a UID when it differs from the last reported one. After an error display (unknown tag), the same tag must be removed and re-tapped to trigger again. This is by design — prevents repeated error flashes for a tag left on the reader.

10. **`board.I2C()` ignores `i2c_bus` config**: The `i2c_bus` setting in settings.yaml is logged but not used — `board.I2C()` always uses the Pi's default bus (bus 1 on Pi 3). If a non-default bus is needed, the code must be modified to use `busio.I2C()` with specific pins.

11. **I2C must be enabled before first run**: `board.I2C()` raises `ValueError: No Hardware I2C on (scl,sda)=(3, 2)` if I2C is not enabled. Run `sudo raspi-config nonint do_i2c 0` first. See `installation_notes.txt`.

12. **`swig` and `liblgpio-dev` not in plan.md deps**: These system packages are required for `adafruit-blinka` to compile on Bookworm. They must be `apt install`ed before `pip install adafruit-blinka`. See `installation_notes.txt`.

## Plan Corrections Applied

Three issues found and fixed in `plan.md` during Phase 1 review:
- **(F)** Removed invalid `-nocursor` from Xorg ExecStart — cursor hiding is matchbox's job
- **(G)** Added `getty@tty1.service` override with `--autologin john` to install.sh — `raspi-config` alone doesn't configure auto-login
- **(H)** Added X socket wait (`/tmp/.X11-unix/X0`) to matchbox.service `ExecStartPre` — prevents race with Xorg startup

## What Not to Do

- Do not add network I/O to `main.py` or `slideshow.py` — foreground must stay smooth
- Do not use `pip3 install` system-wide — PEP 668 on Bookworm, use venv
- Do not hardcode screen dimensions — use `config.screen.width/height`
- Do not use `omxplayer` — not available on Bookworm
- Do not delete `cache/<uid>/raw/` — `keep_raw: true` is required for rclone incremental sync
- Do not add `--loop` as a VLC instance flag for playlist looping — use `MediaListPlayer.set_playback_mode(vlc.PlaybackMode.loop)`
- Do not use `--image-duration=5` for the idle screen — use per-media `:image-duration=86400` to avoid flicker
