#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

# 1. Install Python if missing
if ! command -v python3 >/dev/null; then
    if command -v apt-get >/dev/null; then
        sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip
    elif command -v dnf >/dev/null; then
        sudo dnf install -y python3 python3-venv python3-pip
    elif command -v yum >/dev/null; then
        sudo yum install -y python3 python3-venv python3-pip
    else
        echo "No supported package manager found. Install Python manually."
        exit 1
    fi
fi

# 2. Create venv
python3 -m venv exif/.venv

# 3. Install dependencies
exif/.venv/bin/pip install --upgrade pip
exif/.venv/bin/pip install flask Pillow pillow-heif piexif

# 4. Launch
exif/.venv/bin/python exif/EXIF_STRIP.py
