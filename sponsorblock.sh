#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCES_DIR="$SCRIPT_DIR/test/sources"

ALL_CATEGORIES="sponsor selfpromo interaction intro outro preview music_offtopic poi_highlight filler exclusive_access"

usage() {
  cat <<'EOF'
Usage: sponsorblock.sh [OPTIONS]

Fetch SponsorBlock segments for downloaded videos in ./test/sources/*/

Category flags (enable with --name, disable with --no-name):
  ON by default:   sponsor selfpromo interaction intro outro preview
  OFF by default:  music_offtopic poi_highlight filler exclusive_access

Presets:
  --all         Enable all categories
  --default     Reset to default categories

Other:
  --help        Show this help message
EOF
}

is_category() {
  for c in $ALL_CATEGORIES; do
    [ "$c" = "$1" ] && return 0
  done
  return 1
}

# Initialize enabled categories to defaults
ENABLED="sponsor selfpromo interaction"

set_enabled() {
  local cat="$1" enable="$2"
  # Remove if present
  ENABLED="$(echo " $ENABLED " | sed "s/ $cat / /g" | sed 's/^ *//;s/ *$//')"
  # Add back if enabling
  if [ "$enable" -eq 1 ]; then
    ENABLED="$ENABLED $cat"
    ENABLED="$(echo "$ENABLED" | sed 's/^ *//')"
  fi
}

is_enabled() {
  echo " $ENABLED " | grep -q " $1 "
}

# Parse arguments
while [ $# -gt 0 ]; do
  case "$1" in
    --help)
      usage
      exit 0
      ;;
    --all)
      ENABLED="$ALL_CATEGORIES"
      ;;
    --default)
      ENABLED="sponsor selfpromo interaction intro outro preview"
      ;;
    --no-*)
      cat="${1#--no-}"
      if is_category "$cat"; then
        set_enabled "$cat" 0
      else
        echo "Unknown category: $cat"
        exit 1
      fi
      ;;
    --*)
      cat="${1#--}"
      if is_category "$cat"; then
        set_enabled "$cat" 1
      else
        echo "Unknown option: $1"
        exit 1
      fi
      ;;
    *)
      echo "Unknown argument: $1"
      exit 1
      ;;
  esac
  shift
done

if [ -z "$ENABLED" ]; then
  echo "Error: no categories enabled"
  exit 1
fi

# Build category list in stable order
CATEGORIES=()
for cat in $ALL_CATEGORIES; do
  if is_enabled "$cat"; then
    CATEGORIES+=("$cat")
  fi
done

# URL-encode the category list as JSON array
CATEGORY_JSON="[$(printf '"%s",' "${CATEGORIES[@]}" | sed 's/,$//' )]"
CATEGORY_PARAM="$(python3 -c "import urllib.parse; print(urllib.parse.quote('$CATEGORY_JSON'))")"

echo "Categories: ${CATEGORIES[*]}"

# Iterate over video directories
for VIDEO_DIR in "$SOURCES_DIR"/*/; do
  [ -d "$VIDEO_DIR" ] || continue
  VIDEO_ID="$(basename "$VIDEO_DIR")"

  API_URL="https://sponsor.ajay.app/api/skipSegments?videoID=${VIDEO_ID}&categories=${CATEGORY_PARAM}"

  echo -n "Fetching segments for $VIDEO_ID... "

  HTTP_CODE="$(curl -s -o "$VIDEO_DIR/sponsorblock.json" -w "%{http_code}" "$API_URL")"

  if [ "$HTTP_CODE" = "200" ]; then
    COUNT="$(python3 -c "import json; print(len(json.load(open('${VIDEO_DIR}/sponsorblock.json'))))")"
    echo "$COUNT segments"
  elif [ "$HTTP_CODE" = "404" ]; then
    echo "[]" > "$VIDEO_DIR/sponsorblock.json"
    echo "no segments (404)"
  else
    echo "error (HTTP $HTTP_CODE)"
    rm -f "$VIDEO_DIR/sponsorblock.json"
    continue
  fi

  # Skip keyframe enrichment if no segments
  if [ "$COUNT" = "0" ] || [ -z "$COUNT" ]; then
    continue
  fi

  # Find the video file
  VIDEO_FILE=""
  for ext in mp4 mkv webm; do
    match="$(ls "$VIDEO_DIR"/*."$ext" 2>/dev/null | head -1)"
    if [ -n "$match" ]; then
      VIDEO_FILE="$match"
      break
    fi
  done

  if [ -z "$VIDEO_FILE" ]; then
    echo "  No video file found, skipping keyframe enrichment"
    continue
  fi

  # Extract keyframe timestamps and enrich sponsorblock.json
  echo -n "  Enriching with keyframes... "
  ffprobe -v quiet -select_streams v:0 \
    -show_entries packet=pts_time,flags \
    -of csv=print_section=0 "$VIDEO_FILE" 2>/dev/null | \
    awk -F',' '$2 ~ /K/ && $1 != "N/A" { print $1 }' | sort -n | \
    python3 -c "
import sys, json, bisect

keyframes = [float(line.strip()) for line in sys.stdin if line.strip()]
sb_path = '${VIDEO_DIR}/sponsorblock.json'
segments = json.load(open(sb_path))

for seg in segments:
    start = seg['segment'][0]
    end = seg['segment'][1]

    # Keyframes around segment start
    i = bisect.bisect_right(keyframes, start)
    kf_before_start = keyframes[i - 1] if i > 0 else None
    kf_after_start = keyframes[i] if i < len(keyframes) else None
    seg['keyframesAroundSegmentStart'] = [kf_before_start, kf_after_start]

    # Keyframes around segment end
    i = bisect.bisect_right(keyframes, end)
    kf_before_end = keyframes[i - 1] if i > 0 else None
    kf_after_end = keyframes[i] if i < len(keyframes) else None
    seg['keyframesAroundSegmentEnd'] = [kf_before_end, kf_after_end]

with open(sb_path, 'w') as f:
    json.dump(segments, f, indent=2)
print('done')
"
done
