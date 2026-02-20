#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCES_DIR="$SCRIPT_DIR/test/sources"
DELTA="${1:-0.3}"

for VIDEO_DIR in "$SOURCES_DIR"/*/; do
  [ -d "$VIDEO_DIR" ] || continue
  VIDEO_ID="$(basename "$VIDEO_DIR")"
  VIDEO_FILE="$VIDEO_DIR/source.mp4"

  if [ ! -f "$VIDEO_FILE" ]; then
    echo "[$VIDEO_ID] no source.mp4, skipping"
    continue
  fi

  echo "[$VIDEO_ID] processing..."
  python3 "$SCRIPT_DIR/yt-cut.py" \
    --delta="$DELTA" \
    --input="$VIDEO_FILE" \
    --id="$VIDEO_ID" \
    --output_dir="$VIDEO_DIR"
done
