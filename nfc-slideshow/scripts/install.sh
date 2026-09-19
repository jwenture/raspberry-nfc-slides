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
    xserver-xorg-video-fbdev matchbox-window-manager libheif-examples swig liblgpio-dev

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
