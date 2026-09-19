# NFC Slideshow System for Raspberry Pi 3

## 1. Project Overview

A kiosk system for a Raspberry Pi 3 with an NFC reader and 7" DSI touchscreen. When an NFC tag is tapped, the system identifies the associated Google Drive folder (via a local UID-to-folder mapping), and plays a fullscreen looping slideshow of all images and videos in that folder. The system is designed for a **non-technical end user** — they plug in power, wait for the "Tap a card" screen, and tap a card. No login, no menus, no mouse.

### Design Constraints

- **Hardware**: Raspberry Pi 3 (1GB RAM, ARM Cortex-A53 quad-core 1.2GHz)
- **OS**: Raspberry Pi OS **Bookworm** (Debian 12, Python 3.11, no `omxplayer`)
- **Screen**: Official Raspberry Pi 7" DSI touchscreen (800x480 resolution)
- **NFC Reader**: PN532 module connected via I2C
- **User**: `john` (with sudo access) — not `pi`
- **Smoothness is the top priority**: The program must be light and responsive. No stuttering, no long waits.
- **No audio**: Videos play silently. No audio hardware needed.
- **Non-technical user**: Must boot straight into the app. Must survive power cuts and crashes without manual intervention.
- **Background sync**: Google Drive content is synced once daily (3 AM) in the background. Tapping a card plays from local cache instantly.
- **Language**: Python (the controller). Heavy lifting is delegated to VLC (C/C++) and ffmpeg (C/C++).

### Why Python is sufficient

`slideshow.py` is a **controller**, not a renderer. The actual heavy lifting is done by native code:

| Work | Done by | Language |
|---|---|---|
| Video decode (H.264 to frames) | VLC / MMAL hardware decoder | C/C++ (libvlc) |
| Image rendering | VLC | C/C++ |
| Video transcode (sync job) | ffmpeg | C/C++ |
| NFC I2C read | Linux kernel I2C driver | C |

Python only does: state machine logic, VLC API calls (`media_player.play()`), and I2C reads every 0.2s. These happen at **human timescales** (tag taps, state transitions), not at frame rate (60fps). The GIL and interpreter overhead are irrelevant — they are not in the hot path.

A Go rewrite would save approximately 20MB RAM and 0.5s startup. On a 1GB Pi 3, that is noise. Go only makes sense if we later build a custom renderer replacing VLC entirely, which is not needed.

---

## 2. Architecture

### High-Level Flow

```
 ┌───────────────────────────────────────────────────────────┐
 │  BACKGROUND (daily, 3 AM via systemd timer)               │
 │  sync_all.py                                              │
 │    1. rclone sync gdrive:<folder> -> cache/<uid>/raw      │
 │    2. ffmpeg transcode videos -> 800x480 H.264 baseline   │
 │    3. ffmpeg resize images -> 800x480                     │
 │    4. Write to cache/<uid>/processed/                     │
 └───────────────────────────────────────────────────────────┘

 ┌───────────────────────────────────────────────────────────┐
 │  FOREGROUND (always running, systemd service)             │
 │  main.py                                                  │
 │    NFC poll ---tag---> lookup ---> VLC play from cache    │
 │    (idle = VLC looping a static "tap a card" PNG)         │
 └───────────────────────────────────────────────────────────┘
```

The foreground app **never** does network I/O or transcoding. It only reads local files and controls VLC. This is what keeps it smooth.

### State Machine

```
IDLE (VLC loops idle.png)
  └─ tag tapped ──> lookup UID in tags.json
       ├─ found ──> VLC stop -> VLC play cache/<uid>/processed/* (loop)
       └─ not found ──> flash "unknown card" image 3s -> back to IDLE
PLAYING
  └─ new tag ──> VLC stop -> back to lookup
  └─ same tag ──> restart playlist
  └─ tag removed + 30s timeout ──> back to IDLE
```

### Boot Sequence (zero interaction)

```
Plug in power
  → Linux kernel boots (~25s on Pi 3)
  → systemd
  → autologin as "john" (no password prompt)
  → xorg-kiosk.service        ← minimal X server on DSI display, -ac (no access control)
  → matchbox.service          ← tiny fullscreen window manager (no taskbar) + xset -dpms (no screen blank)
  → nfc-slideshow.service (After=xorg + matchbox, ExecStartPre waits for X display)
        → main.py starts
        → PN532 init
        → VLC shows idle.png ("Tap a card")
        → READY
    → nfc-sync.timer            ← fires daily at 3AM in background
```

Key properties:
- **No desktop environment** — just Xorg + matchbox-window-manager (~15MB RAM vs ~200MB for full LXDE). More RAM for VLC.
- **Auto-login** — no password, no prompt.
- **Crash recovery** — `Restart=always` + `RestartSec=3`. If VLC or Python crashes, systemd restarts within 3 seconds.
- **Network-independent at runtime** — foreground app only reads local `cache/`. If WiFi is down on boot, the slideshow still works. Sync retries when network returns.
- **Hardware watchdog** — Pi 3 built-in watchdog. If the system fully hangs (kernel panic, etc.), it auto-reboots after 15s.
- **No screen blanking** — DPMS disabled via `xset -dpms s off` in matchbox.service. Screen stays on indefinitely.
- **Xorg access control** — `-ac` flag on Xorg disables access control so `john` can connect to the display started by root. Safe on an isolated kiosk (modern Xorg doesn't listen on TCP).
- **Display readiness** — `nfc-slideshow.service` has an `ExecStartPre` that waits for the X display lock file before starting, preventing a race where VLC starts before Xorg is ready.

---

## 3. Project Structure

```
nfc-slideshow/
├── requirements.txt
├── venv/                       # Python virtual environment (PEP 668 on Bookworm)
├── config/
│   ├── tags.json              # UID -> Drive folder mapping
│   ├── settings.yaml          # timings, I2C, paths, screen res
│   ├── rclone.conf            # Google Drive remote (generated by rclone config)
│   ├── wpa_supplicant.conf    # WiFi credentials (copied to /etc/wpa_supplicant/ during install)
│   ├── idle.png               # Pre-rendered "Tap a card" screen (placeholder generated)
│   └── error.png              # Pre-rendered "Unknown card" screen (placeholder generated)
├── src/
│   ├── __init__.py
│   ├── config.py              # Shared config loader (settings.yaml + path resolution)
│   ├── main.py                # State machine: IDLE -> PLAYING -> IDLE
│   ├── nfc_reader.py          # PN532 I2C interface, poll + debounce
│   ├── tag_mapper.py          # Load tags.json, lookup by UID, list all tags
│   └── slideshow.py           # VLC controller (play playlist / play idle / stop)
├── sync/
│   ├── __init__.py
│   ├── sync_all.py            # Background: rclone + ffmpeg transcode for all tags
│   └── transcode.py           # ffmpeg wrapper: video transcode + image resize
├── scripts/
│   ├── install.sh             # apt deps, pip, enable I2C, systemd units, first sync
│   ├── setup_rclone.sh        # Interactive rclone config for Google Drive
│   ├── generate_assets.py     # Generate idle.png, error.png
│   ├── xorg-kiosk.service     # Minimal X server systemd unit
│   ├── matchbox.service       # Matchbox window manager systemd unit
│   ├── nfc-slideshow.service  # Foreground app systemd unit
│   ├── nfc-sync.service       # Background sync systemd unit
│   └── nfc-sync.timer         # Daily sync trigger
├── cache/                     # processed media, ready for instant playback
│   └── <uid>/
│       ├── raw/               # original downloads (cleaned after processing)
│       └── processed/         # transcoded media (slideshow reads from here)
└── logs/                      # runtime logs (rotating, max 5MB x 3 files)
```

---

## 4. Module Details

### `src/config.py` — Shared Configuration Loader

Responsibilities:
- Load `settings.yaml` and expose typed access to all settings.
- Resolve all paths relative to the project root (`Path(__file__).parent.parent`), not CWD — works regardless of working directory.
- Provide screen dimensions as the single source of truth (consumed by `slideshow.py`, `transcode.py`, and `generate_assets.py`).
- Configure Python `logging` with `RotatingFileHandler` (5MB max, 3 backups) + `StreamHandler`. Called once from each entry point (`main.py`, `sync_all.py`).

Interface:
```python
@dataclass
class Config:
    nfc: NfcConfig
    slideshow: SlideshowConfig
    paths: PathConfig
    screen: ScreenConfig        # width, height — single source of truth
    sync: SyncConfig
    vlc: VlcConfig

    @classmethod
    def load(cls, settings_path: str) -> "Config": ...
```

Both `src/main.py` and `sync/sync_all.py` call `Config.load()`. No config parsing duplication.

### `src/main.py` — State Machine / Orchestrator

Responsibilities:
- Load config via `Config.load()`, initialize `TagMapper`, `NfcReader`, `Slideshow`.
- Run the main event loop: poll NFC, transition states, control VLC.
- Discover media files in `cache/<uid>/processed/`, sorted alphabetically by filename, pass to `slideshow.play_playlist()`.
- Periodically check `tags.json` mtime (every ~4 hours) and reload if changed — allows adding tags without service restart.
- Handle graceful shutdown on SIGINT/SIGTERM (stop VLC, release I2C).
- Log state transitions for debugging.

State transitions (3 states — `ERROR` is transient, returns to `IDLE` after 3s):
- `IDLE` → `PLAYING` (tag detected, UID found, cache has media)
- `IDLE` → `ERROR` → `IDLE` (tag detected, UID not found or cache empty)
- `PLAYING` → `PLAYING` (new tag detected — swap playlist)
- `PLAYING` → `IDLE` (tag removed + `idle_timeout` seconds)

### `src/nfc_reader.py` — PN532 I2C Interface

Responsibilities:
- Initialize PN532 over I2C (configurable bus and address).
- Poll for tags at configurable interval (default 0.2s).
- Debounce: ignore re-reads of the same tag within a configurable window (default 1.0s).
- Return UID as uppercase hex string with colon separators (e.g., `04:A3:2B:1C:00:01`).
- Detect tag removal (no tag read for N polls).

Key library: `adafruit-circuitpython-pn532` + `adafruit-blinka` + `board`

Interface:
```python
class NfcReader:
    def __init__(self, i2c_bus: int, i2c_address: int, poll_interval: float, debounce_seconds: float): ...
    def poll(self) -> str | None:    # Returns UID hex string or None
    def is_tag_present(self) -> bool: ...
    def cleanup(self): ...
```

### `src/tag_mapper.py` — Tag UID Lookup

Responsibilities:
- Load `tags.json` at startup.
- Lookup UID → `{name, remote_path}`.
- List all tags (used by `sync_all.py` to iterate every folder for syncing).
- Support reload: re-read `tags.json` if file mtime changed since last load.
- Raise `UnknownTagError` if UID not found.

Interface:
```python
class TagMapper:
    def __init__(self, tags_file: str): ...
    def lookup(self, uid: str) -> TagInfo: ...  # raises UnknownTagError
    def all_tags(self) -> list[TagInfo]: ...     # for sync_all.py iteration
    def maybe_reload(self): ...                  # re-read if mtime changed
```

### `src/slideshow.py` — VLC Controller

Responsibilities:
- Initialize VLC instance with Pi 3 tuned flags. Screen dimensions come from `Config.screen`, not hardcoded.
- `play_idle(image_path)`: Play a single static image in an infinite loop (idle screen).
- `play_playlist(media_files, loop=True)`: Build a VLC playlist from a list of file paths, play fullscreen.
- `stop()`: Stop playback and release media.
- `is_playing()`: Check if currently playing.
- `play_image(image_path, duration=3)`: Show a single image for N seconds using the main VLC instance, then `stop()`. Works despite `--image-duration=5` being a global flag — Python `sleep(duration)` then `stop()` cuts it short. No second VLC instance needed. Used only for `error.png` (unknown card / cache missing).

VLC launch flags for Pi 3 smoothness:
```python
flags = [
    "--no-audio",                    # no audio hardware needed
    "--fullscreen",
    "--loop",                        # loop the playlist
    "--no-osd",                      # no on-screen display
    "--quiet",                       # minimal logging
    "--image-duration=5",            # 5 seconds per image
    "--no-video-title-show",
    "--avcodec-hw=mmal",             # hardware decode via MMAL (Pi 3 specific)
    "--no-stats",
    "--no-sub-autodetect-file",
]
```

Interface:
```python
class Slideshow:
    def __init__(self, config: dict): ...
    def play_idle(self, image_path: str): ...
    def play_playlist(self, media_files: list[str], loop: bool = True): ...
    def play_image(self, image_path: str, duration: float = 3.0): ...
    def stop(self): ...
    def is_playing(self) -> bool: ...
    def cleanup(self): ...
```

### `sync/sync_all.py` — Background Daily Sync

Responsibilities:
- Load config via `Config.load()` (shared with foreground app).
- Use `TagMapper.all_tags()` to iterate every mapped folder.
- For each tag:
  1. `rclone sync <remote_path> cache/<uid>/raw/ --config rclone.conf` (incremental — only downloads new/changed files).
  2. Filter files by supported extensions (images: `.jpg`, `.jpeg`, `.png`, `.heic`; videos: `.mp4`, `.mov`, `.avi`, `.mkv`). Skip non-media files.
  3. For each video in `raw/`: transcode to `{width}x{height}` H.264 baseline, no audio. Auto-rotate based on EXIF/metadata. Scale to fill screen (`force_original_aspect_ratio=increase`, crops overflow).
  4. For each image in `raw/`: resize to `{width}x{height}`. Auto-rotate based on EXIF. Same scale-to-fill behavior.
  5. Write processed files to `cache/<uid>/processed/`.
  6. Skip if output already exists and is newer than input (incremental transcode).
  7. `raw/` is kept (`keep_raw: true`) — required for rclone incremental sync. Deleting raw would cause full re-download every sync.
- Dimensions come from `Config.screen`, not hardcoded.
- Log results and errors to `logs/sync.log` (rotating).
- Exit cleanly (systemd timer handles scheduling).

### `sync/transcode.py` — ffmpeg Wrapper

Responsibilities:
- `transcode_video(input_path, output_path, width, height)`: Run ffmpeg with Pi 3 optimized flags. Width/height received from `Config.screen`. Auto-rotate based on metadata. Scale to fill screen (crop overflow).
- `resize_image(input_path, output_path, width, height)`: Run ffmpeg to resize image. Same dimensions source. Auto-rotate based on EXIF orientation (critical for phone photos).
- Handle various input formats gracefully (including HEIC via libheif).
- Skip if output already exists and is newer than input (incremental).

ffmpeg flags for video transcode (dimensions from config, shown as 800x480 example):
```
ffmpeg -i input.mp4 \
  -vf "auto_rotate=1,scale=800:480:force_original_aspect_ratio=increase,crop=800:480" \
  -c:v h264 \
  -profile:v baseline \
  -level 3.1 \
  -preset fast \
  -crf 28 \
  -an \
  -movflags +faststart \
  -y \
  output.mp4
```

- `auto_rotate=1` = rotate based on video metadata (handles portrait phone videos).
- `force_original_aspect_ratio=increase` + `crop` = scale to fill screen, crop overflow. Portrait videos fill the screen instead of showing small with black bars.
- H.264 **baseline profile** + **level 3.1** = maximum Pi 3 hardware decode compatibility.
- `--crf 28` = good quality at low bitrate (small files, less I/O).
- `-an` = strip audio.
- `+faststart` = moov atom at front, instant playback start.

ffmpeg flags for image resize:
```
ffmpeg -i input.jpg \
  -vf "auto_rotate=1,scale=800:480:force_original_aspect_ratio=increase,crop=800:480" \
  -y \
  output.jpg
```

- `auto_rotate=1` = respect EXIF orientation (phone photos appear right-side up).
- Same scale-to-fill + crop behavior as video.

---

## 5. Configuration

### `config/tags.json`

```json
{
  "tags": [
    {
      "uid": "04:A3:2B:1C:00:01",
      "name": "Vacation 2024",
      "remote_path": "gdrive:slideshows/vacation2024"
    },
    {
      "uid": "04:A3:2B:1C:00:02",
      "name": "Kids Photos",
      "remote_path": "gdrive:slideshows/kids"
    }
  ]
}
```

- `uid`: Uppercase hex with colons. Must match what `nfc_reader.py` returns.
- `name`: Human-readable label for logging and future admin UI.
- `remote_path`: rclone remote path (e.g., `gdrive:folder/subfolder`).

### `config/settings.yaml`

```yaml
nfc:
  i2c_bus: 1
  i2c_address: 0x24
  poll_interval: 0.2          # seconds between polls
  debounce_seconds: 1.0       # ignore re-reads of same tag within this window

slideshow:
  image_duration: 5.0         # seconds per image in slideshow
  loop: true                  # loop the playlist
  fullscreen: true
  idle_timeout: 30            # return to idle if tag removed for this many seconds
  tags_reload_interval: 14400 # check tags.json mtime every N seconds (4 hours)

paths:
  cache_dir: "./cache"
  rclone_config: "./config/rclone.conf"
  idle_image: "./config/idle.png"
  error_image: "./config/error.png"

screen:
  width: 800                   # single source of truth — consumed by slideshow.py, transcode.py, generate_assets.py
  height: 480

sync:
  log_file: "./logs/sync.log"
  keep_raw: true              # keep raw downloads (required for rclone incremental sync)
  rclone_flags: "--transfers 4 --checkers 8 --contimeout 30s --timeout 300s --retries 3"
  supported_image_extensions: [".jpg", ".jpeg", ".png", ".heic"]
  supported_video_extensions: [".mp4", ".mov", ".avi", ".mkv"]

vlc:
  extra_flags: []             # additional VLC flags for tuning
```

### `config/rclone.conf`

Generated by `rclone config` interactive setup. Contains the `gdrive` remote with OAuth token. Must be kept secure (contains access tokens).

---

## 6. Systemd Units

### `scripts/xorg-kiosk.service`

```ini
[Unit]
Description=Minimal X Server (Kiosk)
After=systemd-user-sessions.service

[Service]
ExecStart=/usr/bin/Xorg :0 -ac
Restart=always
RestartSec=2
User=root

[Install]
WantedBy=multi-user.target
```

`-ac` disables access control so `john` can connect to the display. Safe on an isolated kiosk (modern Xorg doesn't listen on TCP). Mouse cursor is hidden by matchbox-window-manager (`-use_cursor no`). No custom xorg.conf needed — Xorg auto-detects the DSI touchscreen via DRM/KMS.

### `scripts/matchbox.service`

```ini
[Unit]
Description=Matchbox Window Manager (Kiosk)
After=xorg-kiosk.service
Requires=xorg-kiosk.service

[Service]
ExecStartPre=/bin/bash -c 'until [ -S /tmp/.X11-unix/X0 ]; do sleep 0.5; done'
ExecStartPre=/usr/bin/xset -dpms s off
ExecStart=/usr/bin/matchbox-window-manager -use_titlebar no -use_cursor no
Restart=always
RestartSec=2
User=john
Environment=DISPLAY=:0

[Install]
WantedBy=multi-user.target
```

Tiny fullscreen window manager (~2MB RAM). No taskbar, no titlebar, no cursor. Ensures VLC's fullscreen window renders correctly. First `ExecStartPre` waits for the X display socket (prevents race with Xorg startup). Second `ExecStartPre` disables DPMS and screen saver so the display stays on indefinitely.

### `scripts/nfc-slideshow.service`

```ini
[Unit]
Description=NFC Slideshow Player
After=xorg-kiosk.service matchbox.service
Requires=xorg-kiosk.service matchbox.service

[Service]
ExecStartPre=/bin/bash -c 'until [ -S /tmp/.X11-unix/X0 ]; do sleep 0.5; done'
ExecStart=/home/john/nfc-slideshow/venv/bin/python3 /home/john/nfc-slideshow/src/main.py
WorkingDirectory=/home/john/nfc-slideshow
Restart=always
RestartSec=3
User=john
Environment=DISPLAY=:0
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

`ExecStartPre` waits for the X display socket to exist before starting, preventing a race where VLC starts before Xorg is ready. Python runs from the venv (PEP 668 on Bookworm prevents system-wide pip install).

### `scripts/nfc-sync.service`

```ini
[Unit]
Description=NFC Slideshow Media Sync (oneshot)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/home/john/nfc-slideshow/venv/bin/python3 /home/john/nfc-slideshow/sync/sync_all.py
WorkingDirectory=/home/john/nfc-slideshow
User=john
Environment=PYTHONUNBUFFERED=1
```

### `scripts/nfc-sync.timer`

```ini
[Unit]
Description=Daily NFC Slideshow Media Sync

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true
Unit=nfc-sync.service

[Install]
WantedBy=timers.target
```

`Persistent=true` means if the Pi was off at 3 AM, the sync runs on next boot.

---

## 7. Dependencies

### Python packages (`requirements.txt`)

```
adafruit-circuitpython-pn532>=2.0
adafruit-blinka>=8.0
python-vlc>=3.0
pyyaml>=6.0
```

### System packages (apt install)

```
vlc
rclone
ffmpeg
python3-pip
python3-venv
i2c-tools
xserver-xorg-video-fbdev
matchbox-window-manager
libheif-examples
```

`python3-venv` required for virtual environment (PEP 668 on Bookworm). `libheif-examples` provides HEIC decode support for iPhone photos.

---

## 8. Installation Steps

### `scripts/install.sh`

```bash
#!/bin/bash
set -e

APP_DIR="/home/john/nfc-slideshow"
VENV="$APP_DIR/venv"

# 0. Verify rclone is configured (setup_rclone.sh must run first)
if [ ! -f "$APP_DIR/config/rclone.conf" ]; then
    echo "ERROR: rclone not configured. Run setup_rclone.sh first."
    exit 1
fi

# 1. System packages
sudo apt update
sudo apt install -y vlc rclone ffmpeg python3-pip python3-venv i2c-tools \
    xserver-xorg-video-fbdev matchbox-window-manager libheif-examples

# 2. Python virtual environment (PEP 668 on Bookworm)
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install -r "$APP_DIR/requirements.txt"

# 3. Enable I2C for PN532
sudo raspi-config nonint do_i2c 0

# 4. Auto-login to console as john (no desktop, no password)
sudo raspi-config nonint do_boot_to_console 0
# Configure auto-login as john on tty1 (raspi-config only sets console boot, not auto-login)
sudo mkdir -p /etc/systemd/system/getty@tty1.service.d
sudo tee /etc/systemd/system/getty@tty1.service.d/autologin.conf > /dev/null <<EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin john --noclear %I \$TERM
EOF
sudo systemctl daemon-reload

# 5. Hardware watchdog
if ! grep -q "watchdog_timeout" /boot/config.txt; then
    echo "watchdog_timeout=15" | sudo tee -a /boot/config.txt
fi

# 6. Generate idle/error screen images
"$VENV/bin/python3" "$APP_DIR/scripts/generate_assets.py"

# 7. Install systemd units
sudo cp "$APP_DIR/scripts/xorg-kiosk.service" /etc/systemd/system/
sudo cp "$APP_DIR/scripts/matchbox.service" /etc/systemd/system/
sudo cp "$APP_DIR/scripts/nfc-slideshow.service" /etc/systemd/system/
sudo cp "$APP_DIR/scripts/nfc-sync.service" /etc/systemd/system/
sudo cp "$APP_DIR/scripts/nfc-sync.timer" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable xorg-kiosk matchbox nfc-slideshow nfc-sync.timer

# 8. Configure systemd hardware watchdog
sudo sed -i 's/^#RuntimeWatchdogSec.*/RuntimeWatchdogSec=15s/' /etc/systemd/system.conf

# 9. WiFi configuration (if using WiFi — skip if Ethernet)
#    Place wpa_supplicant.conf in /boot/ before first boot, or configure here:
# sudo cp "$APP_DIR/config/wpa_supplicant.conf" /etc/wpa_supplicant/wpa_supplicant.conf

# 10. First sync (so cache is populated before first boot into kiosk mode)
echo "Running initial sync... this may take a while."
"$VENV/bin/python3" "$APP_DIR/sync/sync_all.py"

echo "Installation complete. Reboot to start the kiosk."
```

### `scripts/setup_rclone.sh`

```bash
#!/bin/bash
# Interactive rclone configuration for Google Drive
# Must be run on a machine with a browser (or use rclone's headless auth)
mkdir -p config
rclone config --config config/rclone.conf
# Follow prompts:
#   1. New remote -> "gdrive"
#   2. Type -> "drive" (Google Drive)
#   3. client_id -> leave blank (use rclone's default)
#   4. client_secret -> leave blank
#   5. scope -> "drive.readonly"
#   6. root_folder_id -> leave blank (or set to a specific folder)
#   7. Use auto config -> yes (if on Pi with browser) or no (headless)
```

---

## 9. Media Pipeline

```
Google Drive
  │
  ▼  rclone sync (background, daily 3AM)
cache/<uid>/raw/          (original files, various formats/sizes)
  │
  ▼  ffmpeg transcode (background, during sync)
cache/<uid>/processed/    (800x480 H.264 baseline video, 800x480 images, auto-rotated, scale-to-fill)
  │
  ▼  VLC playback (foreground, instant)
DSI touchscreen           (fullscreen, looped, no audio)
```

### Why pre-transcode matters on Pi 3

- A 1080p H.264 high-profile video requires significant CPU to decode in software. The Pi 3's MMAL hardware decoder can handle it, but it is near the limit.
- A 800x480 H.264 baseline video is trivial for the MMAL decoder. Minimal CPU, minimal memory bandwidth, smooth playback.
- Pre-transcoding also normalizes formats (MOV, AVI, MKV all become MP4) so VLC never encounters a format it cannot play.
- This runs in the background daily, so transcode time is not a concern.

---

## 10. Smoothness Checklist for Pi 3

| Technique | Impact |
|---|---|
| Pre-transcode to 800x480 H.264 baseline | Pi 3 hardware decoder handles this effortlessly |
| Auto-rotate + scale-to-fill (crop) | Phone photos/videos appear correct orientation, screen fully filled |
| No audio stream | Saves decode bandwidth |
| No pygame / no X app framework | Just VLC, nothing else rendering |
| Foreground app does zero network I/O | No stalls, no waiting on rclone |
| `+faststart` on MP4s | Playback begins instantly (moov atom at front) |
| VLC `--quiet --no-osd --no-stats` | Minimal overhead |
| `--avcodec-hw=mmal` | Hardware video decode via MMAL (Pi 3 specific) |
| Small poll interval (0.2s) but debounced | Responsive without CPU thrashing |
| Minimal X (no desktop environment) | ~15MB RAM vs ~200MB for LXDE |
| No mouse cursor (matchbox `-use_cursor no`) | No rendering overhead for cursor |

---

## 11. Edge Cases and Potential Issues

### NFC Reader Issues

1. **Tag UID format mismatch**: The UID returned by the PN532 library may be in bytes, needing conversion to hex string. Must ensure the format in `tags.json` matches exactly what `nfc_reader.py` returns (uppercase hex with colons). **Mitigation**: Log the raw UID on every tap during development. Add a `--debug` flag that prints UIDs without requiring a match.

2. **PN532 not detected on I2C bus**: Wiring issue or I2C not enabled. **Mitigation**: `install.sh` enables I2C via `raspi-config`. Add a startup check in `nfc_reader.py` that logs a clear error and shows "Reader error" on screen if PN532 is not found at the expected address. Use `i2cdetect -y 1` to verify during setup.

3. **Tag read debounce**: Some tags may fire multiple read events in rapid succession. **Mitigation**: Debounce window (1.0s default) ignores re-reads of the same UID.

4. **Tag removed detection**: PN532 may not reliably report tag removal (depends on tag type and library). **Mitigation**: Track "last seen UID" and consider the tag removed if no read for N consecutive polls. Use the `idle_timeout` setting (30s) before returning to idle screen.

5. **Multiple tags on reader simultaneously**: PN532 can sometimes detect multiple tags. **Mitigation**: Use only the first detected tag. Log a warning if multiple are detected.

6. **I2C bus contention**: If another I2C device is on the same bus, address conflicts or bus locking can occur. **Mitigation**: Use a dedicated I2C bus or ensure no address conflict. Default PN532 I2C address is 0x24 (can be changed to 0x48 via solder jumper on some boards).

### Sync / Drive Issues

7. **Google Drive OAuth token expiry**: rclone OAuth tokens can expire. **Mitigation**: rclone auto-refreshes tokens if a refresh token is present. If the token is fully expired (rare), the sync fails and logs an error. The foreground app continues working from cache. Add a log check in `sync_all.py` that detects auth failure and logs a prominent warning.

8. **Network unavailable during sync**: If the Pi is offline at 3 AM, the sync fails. **Mitigation**: `Persistent=true` on the systemd timer means it runs on next boot if missed. Also, the sync service has `Wants=network-online.target` so it waits for network. Add retry logic in `sync_all.py` (rclone `--retries 3` is already in config).

9. **Large folder / slow network**: First sync of a large folder could take hours. **Mitigation**: This is a one-time cost. The install script runs the first sync interactively so the user sees progress. Subsequent daily syncs are incremental (rclone only transfers changed files).

10. **Disk space exhaustion**: Cache could fill up the SD card. **Mitigation**: Add a disk space check in `sync_all.py` before downloading. Log a warning if free space < 1GB. Consider adding `--drive-limit-download 0` to rclone (no limit) but monitor disk usage. Future: auto-cleanup of old/unused cache folders.

11. **rclone rate limiting**: Google Drive API has rate limits. **Mitigation**: rclone handles this with `--retries` and exponential backoff. Default `--tpslimit` may need tuning for large folders.

12. **New content added to Drive after initial sync**: If someone adds new photos to the Drive folder, they will not appear until the next daily sync. **Mitigation**: This is by design (background sync). Document this behavior. Future: add a manual "sync now" via a special admin NFC tag or button.

### Playback Issues

13. **Empty folder / no media files**: A tag maps to a folder that exists but has no images or videos. **Mitigation**: Check media list before calling `slideshow.play_playlist()`. If empty, show "No content found" image for 5 seconds, then return to idle.

14. **Cache folder missing (sync not yet run)**: Tag is tapped but `cache/<uid>/processed/` does not exist. **Mitigation**: Check cache existence before attempting playback. Show "Content not synced yet" image. This should not happen after install (first sync runs during setup), but could happen if a new tag is added to `tags.json` without running sync.

15. **VLC crash or hang**: VLC could crash on a corrupt file, or hang on an unsupported codec. **Mitigation**: `Restart=always` on the systemd service restarts the whole app. Additionally, `slideshow.py` should set a VLC callback for errors and skip to the next media item if one fails. Pre-transcoding normalizes formats so this is unlikely.

16. **Unsupported video codec after transcode**: If ffmpeg fails to transcode a video (e.g., proprietary codec, DRM-protected file), the processed file will not exist. **Mitigation**: `sync_all.py` logs transcode failures. The file is simply absent from the processed folder and skipped during playback. Log a warning.

17. **Corrupt image file**: An image that cannot be loaded by VLC. **Mitigation**: VLC will skip to the next item in the playlist. Log the error.

18. **Very short videos**: A video that is 0.5s long may cause a visible flicker. **Mitigation**: Acceptable for v1. Could add a minimum duration check in the future.

19. **Very large number of files**: A folder with 1000+ images. VLC playlist should handle this, but startup time may increase. **Mitigation**: Pre-transcoded images are small (800x480 JPG). VLC handles large playlists fine. If needed, add a file count limit in settings.

### System / Hardware Issues

20. **SD card corruption from sudden power loss**: The user will unplug power without shutting down. **Mitigation**: TODO — read-only root filesystem (overlayfs) with separate writable cache partition. For v1, use `sync` mount option and accept the risk. Document that a clean shutdown (if possible) is preferable.

21. **DSI touchscreen not detected**: The ribbon cable could be loose or the overlay not configured. **Mitigation**: The official 7" DSI touchscreen is detected automatically by Raspberry Pi OS. If not, `xorg-kiosk.service` will fail and systemd will restart it in a loop. Add a check in `install.sh` that verifies the display is detected (`/dev/fb0` exists).

22. **VLC cannot open display**: If Xorg is not running or DISPLAY is not set. **Mitigation**: `nfc-slideshow.service` has `After=xorg-kiosk.service` and `Requires=xorg-kiosk.service`. The `Environment=DISPLAY=:0` is set in the service file. VLC will fail fast if display is unavailable, and systemd will restart the chain.

23. **PN532 I2C address varies**: Some PN532 boards default to 0x24, others to 0x48. **Mitigation**: Configurable in `settings.yaml`. Document both addresses. `i2cdetect -y 1` during setup shows the actual address.

24. **Pi 3 thermal throttling**: Under sustained video playback, the Pi 3 may thermal throttle (reducing clock speed). **Mitigation**: Pre-transcoded 800x480 content is light on CPU. Add a heatsink to the Pi 3. Monitor `vcgencmd measure_temp` during testing. The low resolution is the primary mitigation — decode cost is minimal.

25. **Time/timezone not set**: If the Pi has no RTC and no NTP, the daily sync timer may fire at the wrong time. **Mitigation**: Ensure NTP is configured (`systemd-timesyncd` is default on Pi OS). The `Persistent=true` timer flag ensures sync runs even if the time was wrong when the timer elapsed.

26. **rclone.conf contains OAuth tokens**: Security risk if SD card is stolen. **Mitigation**: File permissions set to 600 (`chmod 600 config/rclone.conf`). For production with read-only root, the config is baked into the read-only layer.

### User Experience Issues

27. **No feedback during sync**: If the user taps a card whose folder is being re-synced, they see old content (which is fine) but new content appears only next day. **Mitigation**: This is by design. Document the daily sync behavior.

28. **Unknown tag tapped**: User taps a card that is not in `tags.json`. **Mitigation**: Show "Unknown card" image for 3 seconds, then return to idle. Log the UID for the admin to add to `tags.json`.

29. **Boot time perception**: ~25s boot time with no feedback on screen. **Mitigation**: The DSI touchscreen will show the boot console text (kernel messages) during boot, which is acceptable. For a cleaner look, configure the bootloader to show a splash image (`/boot/splash.png`).

30. **Accidental double-tap**: User taps a card and quickly taps it again. **Mitigation**: Debounce window (1.0s) handles this. Same tag re-tap after debounce window restarts the slideshow.

### Format / Compatibility Issues

31. **HEIC photos from iPhones**: `.heic` files may not decode if ffmpeg lacks libheif support. **Mitigation**: `libheif-examples` installed via apt. If ffmpeg still can't decode HEIC, use `heif-convert` as a pre-step in `transcode.py`. Test during Phase 1.

32. **Portrait videos and photos**: Phone media shot vertically. **Mitigation**: `auto_rotate=1` in ffmpeg respects EXIF/metadata rotation. `force_original_aspect_ratio=increase` + `crop` scales to fill the screen (crops overflow) instead of showing small with black bars.

33. **EXIF orientation on images**: Phone photos often have rotation in EXIF metadata, not baked into pixels. Without auto-rotate, images appear sideways. **Mitigation**: `auto_rotate=1` in ffmpeg resize filter.

34. **Non-media files in Drive folder**: Google Docs, Sheets, PDFs, or random files in a synced folder. **Mitigation**: `sync_all.py` filters by supported file extensions before transcoding. Non-media files are ignored.

35. **Google Drive proprietary formats**: Google Docs/Sheets/Slides are not real files. rclone skips them by default (or exports with `--drive-export-formats`). **Mitigation**: Default rclone behavior is fine — only real files (images, videos) are synced.

### System / Bookworm Issues

36. **PEP 668 externally-managed-environment**: Bookworm blocks system-wide `pip install`. **Mitigation**: Virtual environment created during install. All systemd services use `venv/bin/python3`.

37. **Screen blanking (DPMS)**: DSI touchscreen may blank after inactivity. **Mitigation**: `xset -dpms s off` in `matchbox.service` `ExecStartPre`. Screen stays on indefinitely.

38. **Xorg access control**: Xorg started as root, app runs as `john`. **Mitigation**: `-ac` flag on Xorg disables access control. Safe on isolated kiosk.

39. **Display readiness race**: `main.py` may start before Xorg is fully initialized. **Mitigation**: `ExecStartPre` in `nfc-slideshow.service` waits for `/tmp/.X11-unix/X0` socket before starting.

40. **tags.json changes while running**: New tags added without service restart. **Mitigation**: `main.py` checks `tags.json` mtime every 4 hours and reloads if changed. No restart needed.

41. **matchbox-window-manager not available**: Package may not be in Bookworm repos. **Mitigation**: Verify with `apt-cache policy matchbox-window-manager`. Fallback: `openbox` or no WM (VLC fullscreen without WM, though behavior can be flaky).

---

## 12. Fallback Strategy

If VLC stutters on Pi 3 despite pre-transcoding:

1. **Try `mpv`** (works on Bookworm):
   - `mpv --hwdec=mmal --no-audio --loop-file=inf --fullscreen video.mp4`
   - Lighter than VLC, good MMAL support.
   - Can handle both images and videos with `--image-display-duration=5`.

2. **Reduce resolution further**: Transcode to 640x480 or even 480x360 if 800x480 is still too heavy.

3. **Switch to Golang**: If Python proves to have unacceptable overhead (unlikely given the architecture, but possible if VLC Python bindings have memory issues). The architecture stays the same — only `slideshow.py` and `main.py` would be rewritten. `sync_all.py` could stay Python or become a Go binary.

Note: `omxplayer` is **not available on Bookworm** (Buster only). It is not a fallback option.

Only `slideshow.py` changes in fallback scenarios 1 and 2. The rest of the architecture stays identical. This is why `slideshow.py` is isolated as a single module with a clean interface.

---

## 13. Implementation Order

Recommended sequence for building:

### Phase 1: Core Playback (no NFC, no sync)
- [x] 1. Create project structure, config files, and Python venv (`python3 -m venv venv`).
- [x] 2. Implement `slideshow.py` — VLC controller with idle screen and playlist playback.
- [x] 3. Implement `main.py` with a simple test loop (play idle, wait for keypress, play test folder).
- [ ] 4. Test on Pi 3 with a few pre-loaded images and videos.
- [ ] 5. Tune VLC flags for smoothness.

### Phase 2: NFC Integration
- [ ] 6. Wire PN532 to Pi 3 I2C (SDA/SCL/GND/3.3V).
- [x] 6a. NFC test script created (`nfc-test/test_nfc.py`) — standalone I2C poll + UID print, tries addresses 0x24 and 0x48.
- [x] 7. Implement `nfc_reader.py` — poll for tags, return UID.
- [x] 8. Implement `tag_mapper.py` — load tags.json, lookup.
- [x] 9. Integrate into `main.py` — tap a card, play associated folder.
- [ ] 10. Test with real NFC tags.

### Phase 3: Background Sync
- [ ] 11. Run `setup_rclone.sh` to configure Google Drive remote.
- [ ] 12. Implement `transcode.py` — ffmpeg wrapper.
- [ ] 13. Implement `sync_all.py` — rclone + transcode for all tags.
- [ ] 14. Test sync with a small Drive folder.
- [ ] 15. Set up systemd timer for daily sync.

### Phase 4: Kiosk Mode
- [x] 16. Generate idle/error screen images (`generate_assets.py`).
- [ ] 17. Create systemd service files.
- [ ] 18. Write `install.sh` (including venv creation, WiFi setup, DPMS disable).
- [ ] 19. Test full boot sequence (power cycle, tap card, playback).
- [ ] 20. Test crash recovery (kill process, verify restart).

### Phase 5: Hardening
- [ ] 21. Add hardware watchdog configuration.
- [ ] 22. Test with network disconnected (verify playback from cache).
- [ ] 23. Test with corrupt/missing files.
- [ ] 24. Add logging and verify logs are useful for remote debugging.
- [ ] 25. [TODO] Read-only root filesystem with writable cache partition.
- [ ] 26. [TODO] Web admin page for tag management.
- [ ] 27. [TODO] Background pre-sync of all folders on boot (so first tap is instant even before daily sync).

---

## 14. Hardening TODO (Post-v1)

- [ ] **Read-only root filesystem** (overlayfs) + separate writable cache partition. Prevents SD card corruption from sudden power cuts. Root is read-only, `cache/` and `logs/` are on a small ext4 partition mounted rw.
- [ ] **Background pre-sync on boot**: Sync all mapped folders on boot (in background) so first tap is instant even before the daily sync timer fires.
- [ ] **Web admin page**: Small HTTP server to add/remove tag mappings, trigger manual sync, view logs. Accessible from another device on the same network.
- [ ] **Health monitoring**: Log CPU temp, memory usage, disk space periodically. Alert if disk space low or sync failing repeatedly.
- [ ] **Splash screen during boot**: Configure bootloader to show a branded splash image instead of kernel boot text.
- [ ] **OTA updates**: Mechanism to update the app code remotely (git pull on boot, or a dedicated update mechanism).

---

## 15. Key File References

| File | Purpose | Status |
|---|---|---|
| `src/config.py` | Shared config loader, path resolution, logging setup | ✅ Done |
| `src/main.py` | Entry point, state machine, signal handling | ✅ Full state machine (IDLE/PLAYING/ERROR) |
| `src/nfc_reader.py` | PN532 I2C polling, debounce, UID formatting | ✅ Done |
| `src/tag_mapper.py` | tags.json loader, lookup by UID, list all tags | ✅ Done |
| `src/slideshow.py` | VLC instance management, playlist, idle screen | ✅ Done |
| `sync/sync_all.py` | Daily background sync orchestrator | ❌ Not started |
| `sync/transcode.py` | ffmpeg video transcode + image resize | ❌ Not started |
| `config/tags.json` | Tag UID to Drive folder mapping | ✅ Sample data |
| `config/settings.yaml` | All application settings | ✅ Done |
| `config/rclone.conf` | Google Drive OAuth credentials | ❌ Generated by setup_rclone.sh |
| `config/idle.png` | "Tap a card" screen | ✅ Placeholder generated |
| `config/error.png` | "Unknown card" screen | ✅ Placeholder generated |
| `scripts/install.sh` | One-shot setup script | ❌ Not started |
| `scripts/setup_rclone.sh` | Interactive rclone configuration | ❌ Not started |
| `scripts/generate_assets.py` | Generate idle/error PNGs | ✅ Done (placeholder content) |
| `scripts/xorg-kiosk.service` | Systemd unit for minimal X server | ❌ Not started |
| `scripts/matchbox.service` | Systemd unit for matchbox window manager | ❌ Not started |
| `scripts/nfc-slideshow.service` | Systemd unit for foreground app | ❌ Not started |
| `scripts/nfc-sync.service` | Systemd unit for background sync | ❌ Not started |
| `scripts/nfc-sync.timer` | Systemd timer for daily sync | ❌ Not started |
| `nfc-test/test_nfc.py` | Standalone NFC reader test script | ✅ Done (not in original plan) |
