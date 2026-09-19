# NFC Slideshow Kiosk for Raspberry Pi 3

A kiosk system that plays fullscreen looping slideshows triggered by NFC card taps. Each NFC card maps to a Google Drive folder. Tapping a card plays all images and videos from that folder on a 7" DSI touchscreen. Designed for non-technical end users: plug in power, wait for "Tap a card" screen, tap card.

## How It Works

1. **Background sync** (daily at 3 AM): `rclone` downloads media from Google Drive, `ffmpeg` transcodes everything to 800x480 H.264 baseline (optimal for Pi 3 hardware decode).
2. **Foreground app** (always running): Polls PN532 NFC reader over I2C. On tag tap, looks up the UID in `tags.json`, plays the cached slideshow via VLC with hardware-accelerated decode.
3. **Kiosk mode**: Boots straight into Xorg + matchbox window manager + slideshow app. No desktop, no login, no mouse. Survives crashes (`Restart=always`) and power cuts (hardware watchdog).

## Hardware Requirements

| Component | Specification |
|---|---|
| Board | Raspberry Pi 3 (1GB RAM) |
| OS | Raspberry Pi OS Bookworm (Debian 12) |
| Display | Official 7" DSI touchscreen (800x480) |
| NFC Reader | PN532 module (I2C, default address 0x24) |
| Power | Official Pi 3 power supply (5V 2.5A) |
| Storage | 16GB+ microSD card |
| Network | WiFi or Ethernet (for sync only; playback works offline) |

### PN532 Wiring

| PN532 Pin | Pi Pin | GPIO |
|---|---|---|
| VCC | Pin 1 | 3.3V |
| GND | Pin 6 | GND |
| SDA | Pin 3 | GPIO2 (I2C SDA) |
| SCL | Pin 5 | GPIO3 (I2C SCL) |

Set the PN532 jumper to I2C mode (not SPI or UART).

## Software Setup (on Raspberry Pi)

### Step 1: Deploy code

Copy the `nfc-slideshow/` directory to `/home/john/nfc-slideshow/` on the Pi:

```bash
# From your development machine:
scp -r nfc-slideshow/ john@<pi-ip>:/home/john/

# Or via git:
git clone <repo-url> /home/john/nfc-slideshow
```

### Step 2: Configure Google Drive (rclone)

```bash
cd /home/john/nfc-slideshow
bash scripts/setup_rclone.sh
```

This runs `rclone config` interactively. Follow the prompts:
- New remote name: `gdrive`
- Type: `drive` (Google Drive)
- Scope: `drive.readonly`
- Authenticate via browser

Creates `config/rclone.conf` with OAuth tokens.

### Step 3: Discover NFC tag UIDs

Wire up the PN532 and enable I2C:

```bash
sudo raspi-config nonint do_i2c 0
sudo apt install -y swig liblgpio-dev python3-venv i2c-tools
i2cdetect -y 1  # Should show 0x24 or 0x48
```

Run the NFC test script to read tag UIDs:

```bash
cd /home/john/nfc-slideshow
python3 -m venv venv
venv/bin/pip install adafruit-circuitpython-pn532 adafruit-blinka
venv/bin/python3 ../nfc-test/test_nfc.py
# Tap a card — UID will be printed (e.g., 04:A3:2B:1C:00:01)
```

### Step 4: Map tags to folders

Edit `config/tags.json`:

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

- `uid`: Uppercase hex with colons (must match what the NFC reader returns)
- `name`: Human-readable label (for logging)
- `remote_path`: rclone remote path (Google Drive folder)

### Step 5: Install and reboot

```bash
cd /home/john/nfc-slideshow
bash scripts/install.sh
sudo reboot
```

`install.sh` installs all dependencies, creates the venv, enables I2C, configures auto-login, installs systemd services, runs the first sync, and enables the hardware watchdog.

After reboot, the Pi shows the "Tap a card" screen. Tap a card to play its slideshow.

## Running the Code

### Production (kiosk mode)

Everything runs automatically via systemd after `install.sh` + reboot:

```bash
# Check status
systemctl status nfc-slideshow.service
systemctl status nfc-sync.timer

# View logs
journalctl -u nfc-slideshow.service -f
tail -f /home/john/nfc-slideshow/logs/app.log
tail -f /home/john/nfc-slideshow/logs/sync.log

# Trigger manual sync
systemctl start nfc-sync.service

# Restart the app
sudo systemctl restart nfc-slideshow.service
```

### Development (manual run on Pi)

```bash
cd /home/john/nfc-slideshow

# Run the foreground app (requires X display + NFC reader)
DISPLAY=:0 venv/bin/python3 src/main.py

# Run the background sync (requires rclone configured)
venv/bin/python3 sync/sync_all.py

# Generate idle/error screen images
venv/bin/python3 scripts/generate_assets.py
```

### Testing without hardware (development machine)

The code can be partially tested on a non-Pi machine (e.g., Windows/Mac/Linux):

```bash
# Install test dependencies
pip install pyyaml Pillow

# Test config loading
python -c "import sys; sys.path.insert(0, '.'); from src.config import Config; c = Config.load('config/settings.yaml'); print(f'Screen: {c.screen.width}x{c.screen.height}')"

# Test tag mapper
python -c "import sys; sys.path.insert(0, '.'); from src.tag_mapper import TagMapper; tm = TagMapper('config/tags.json'); print(f'Tags: {len(tm.all_tags())}')"

# Test transcode (requires ffmpeg)
python -c "import sys; sys.path.insert(0, '.'); from sync.transcode import transcode_video; print(transcode_video('test.mp4', 'out.mp4', 800, 480))"
```

Note: `src/nfc_reader.py` requires `adafruit_pn532` + `board` (Pi-only). `src/slideshow.py` requires `python-vlc` + VLC installed. These will not import on non-Pi machines.

## Configuration

### `config/settings.yaml`

All application settings. Key values:

| Setting | Default | Description |
|---|---|---|
| `nfc.i2c_bus` | 1 | I2C bus number |
| `nfc.i2c_address` | 0x24 | PN532 I2C address (0x48 alternative) |
| `nfc.poll_interval` | 0.2 | Seconds between NFC polls |
| `nfc.debounce_seconds` | 1.0 | Ignore re-reads of same tag within this window |
| `slideshow.image_duration` | 5.0 | Seconds per image in slideshow |
| `slideshow.idle_timeout` | 30 | Return to idle after tag removed for N seconds |
| `slideshow.tags_reload_interval` | 14400 | Check tags.json mtime every N seconds (4 hours) |
| `screen.width` | 800 | Screen width (single source of truth) |
| `screen.height` | 480 | Screen height |
| `sync.keep_raw` | true | Keep raw downloads (required for rclone incremental sync) |
| `sync.rclone_flags` | `--transfers 4 ...` | Flags passed to rclone sync |

### Adding a new NFC tag

1. Tap the new card on the reader (run `nfc-test/test_nfc.py` to see the UID)
2. Add an entry to `config/tags.json` with the UID, name, and Google Drive folder path
3. Wait up to 4 hours for the app to auto-reload `tags.json` (or restart the service)
4. Run `systemctl start nfc-sync.service` to sync the new folder immediately

## Media Pipeline

```
Google Drive folder
  │
  ▼  rclone sync (daily 3AM, background)
cache/<uid>/raw/           original files (various formats)
  │
  ▼  ffmpeg transcode (during sync)
cache/<uid>/processed/     800x480 H.264 baseline video, 800x480 JPG images
  │
  ▼  VLC playback (foreground, instant)
DSI touchscreen            fullscreen, looped, no audio
```

### Supported formats

- **Images**: `.jpg`, `.jpeg`, `.png`, `.heic`
- **Videos**: `.mp4`, `.mov`, `.avi`, `.mkv`

All media is transcoded to 800x480. Videos become H.264 baseline (MP4 container, no audio). Images become JPG. HEIC files (iPhone photos) use `heif-convert` fallback if ffmpeg lacks libheif support.

## Project Structure

```
nfc-slideshow/
├── requirements.txt           Python dependencies
├── config/
│   ├── settings.yaml          All app settings
│   ├── tags.json              NFC UID → Google Drive folder mapping
│   ├── rclone.conf            Google Drive OAuth (generated by setup_rclone.sh)
│   ├── idle.png               "Tap a card" screen
│   └── error.png              "Unknown card" screen
├── src/
│   ├── config.py              Config loader + logging setup
│   ├── main.py                Entry point — state machine (IDLE/PLAYING/ERROR)
│   ├── nfc_reader.py          PN532 I2C polling, debounce, edge-triggered
│   ├── tag_mapper.py          tags.json loader, lookup, mtime-based reload
│   └── slideshow.py           VLC controller (MediaListPlayer, hardware decode)
├── sync/
│   ├── sync_all.py            Background sync orchestrator (rclone + transcode)
│   └── transcode.py           ffmpeg wrapper (video transcode + image resize)
├── scripts/
│   ├── install.sh             One-shot setup script
│   ├── setup_rclone.sh        Interactive rclone config
│   ├── generate_assets.py     Generate idle.png and error.png
│   ├── xorg-kiosk.service     Systemd: minimal X server
│   ├── matchbox.service       Systemd: window manager + DPMS off
│   ├── nfc-slideshow.service  Systemd: foreground app
│   ├── nfc-sync.service       Systemd: background sync (oneshot)
│   └── nfc-sync.timer         Systemd: daily 3AM trigger
├── cache/                     Processed media (cache/<uid>/processed/)
└── logs/                      Rotating logs (5MB x 3 files)
```

## State Machine

```
IDLE (VLC loops idle.png)
  └─ tag tapped ──> lookup UID in tags.json
       ├─ found + has media ──> PLAYING
       └─ not found / no media ──> ERROR (3-5s) ──> IDLE

PLAYING
  └─ new tag ──> swap playlist
  └─ same tag re-tapped ──> restart playlist
  └─ tag removed + 30s timeout ──> IDLE
```

## Troubleshooting

### NFC reader not detected

```bash
i2cdetect -y 1
# Should show 24 (hex) at some address. If not:
sudo raspi-config nonint do_i2c 0  # Enable I2C
# Check wiring (SDA=GPIO2, SCL=GPIO3, 3.3V, GND)
# Try alternative address 0x48 (change in settings.yaml)
```

### VLC not playing / black screen

```bash
# Check if Xorg is running
systemctl status xorg-kiosk.service
# Check if matchbox is running
systemctl status matchbox.service
# Check app logs
tail -50 /home/john/nfc-slideshow/logs/app.log
# Test VLC manually
DISPLAY=:0 vlc --fullscreen --no-audio --avcodec-hw=mmal test.mp4
```

### Sync not working

```bash
# Check rclone config
rclone listremotes --config /home/john/nfc-slideshow/config/rclone.conf
# Test rclone manually
rclone ls gdrive:slideshows/vacation2024 --config /home/john/nfc-slideshow/config/rclone.conf
# Check sync logs
tail -50 /home/john/nfc-slideshow/logs/sync.log
# Trigger manual sync
systemctl start nfc-sync.service
journalctl -u nfc-sync.service -f
```

### Screen blanking

```bash
# DPMS should be disabled by matchbox.service
DISPLAY=:0 xset q  # Check DPMS status
# If still blanking:
DISPLAY=:0 xset -dpms s off
```

### App won't start after reboot

```bash
# Check if auto-login is configured
cat /etc/systemd/system/getty@tty1.service.d/autologin.conf
# Should show: ExecStart=-/sbin/agetty --autologin john --noclear %I $TERM

# Check systemd service status
systemctl status nfc-slideshow.service
journalctl -u nfc-slideshow.service -b
```

### Disk full

```bash
df -h /home/john/nfc-slideshow/cache/
# Clean cache (will re-sync on next run):
# rm -rf /home/john/nfc-slideshow/cache/*/raw/
# Keep processed/ to avoid re-transcoding
```

## Boot Sequence

```
Power on
  → Linux kernel boots (~25s)
  → systemd
  → autologin as "john" (no password)
  → xorg-kiosk.service        X server on DSI display
  → matchbox.service          fullscreen WM, no cursor, DPMS off
  → nfc-slideshow.service     main.py starts
    → PN532 init
    → VLC shows "Tap a card"
    → READY
  → nfc-sync.timer            fires daily at 3AM in background
```

No desktop environment. No login prompt. No mouse cursor. Just the slideshow app.

## Dependencies

### Python (`requirements.txt`)

- `adafruit-circuitpython-pn532` — PN532 NFC reader driver
- `adafruit-blinka` — CircuitPython hardware abstraction for Pi
- `python-vlc` — VLC Python bindings
- `pyyaml` — YAML config parsing
- `Pillow` — Image generation for idle/error screens

### System (apt)

`vlc`, `rclone`, `ffmpeg`, `python3-pip`, `python3-venv`, `i2c-tools`, `xserver-xorg-video-fbdev`, `matchbox-window-manager`, `libheif-examples`, `swig`, `liblgpio-dev`

`swig` and `liblgpio-dev` are required for `adafruit-blinka` to compile on Bookworm.

## Design Documents

- `plan.md` — Full design document with architecture, edge cases, and implementation order
- `AGENTS.md` — Maintenance guide for AI agents working on this codebase
- `installation_notes.txt` — Real-world Pi setup findings
