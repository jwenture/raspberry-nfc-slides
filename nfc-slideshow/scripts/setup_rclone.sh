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
