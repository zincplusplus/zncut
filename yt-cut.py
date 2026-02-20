#!/usr/bin/env python3
import sys, json, subprocess, os, argparse, bisect, urllib.request, urllib.parse
from pathlib import Path

#
# APP SETTINGS
#
# todo allow users to say which categories they want
parser = argparse.ArgumentParser()
parser.add_argument('--input')
# parser.add_argument('--delta', type=float, default=0.3)
parser.add_argument('--id')
parser.add_argument('--output_dir', default='.')
args = parser.parse_args()

if not args.input:
  print("Missing path to video. You need to provide it like this --input=path/to/video.mp4")
  exit(1)

if not args.id:
  print("Missing YouTube video id. You need to provide it like this --id=SqD_8FGk89o otherwise I can't figure out the sponsors")
  exit(1)

if not args.output_dir:
  print("Missing output path. You need to provide it like this --output_dir=path/to/output/")
  exit(1)

if not Path(args.input).exists():
  print(f"Video file not found: {args.input}")
  exit(1)


#
# METHODS
#
def fetchSegments(videoId, categories=['sponsor', 'selfpromo', 'interaction']):
  categoryJson = json.dumps(categories)
  encoded = urllib.parse.quote(categoryJson)
  url = f"https://sponsor.ajay.app/api/skipSegments?videoID={videoId}&categories={encoded}"

  try:
      with urllib.request.urlopen(url) as response:
          return json.loads(response.read())
  except urllib.error.HTTPError as e:
      if e.code == 404:
          return []
      raise

def getPrevKeyframe(keyframes, frame):
  i = bisect.bisect_right(keyframes, frame);
  result = keyframes[i-1];
  return result

def getNextKeyframe(keyframes, frame):
  i = bisect.bisect_right(keyframes, frame);
  result = keyframes[i] if i < len(keyframes) else None;
  return result

#
# APP
#
video = args.input;
videoId = args.id
segments = fetchSegments(videoId)
if not segments:
  print("No sponsor segments found, nothing to cut")
  exit(0)

keyframesRaw = subprocess.run([
  "ffprobe", "-v", "quiet",
  "-select_streams", "v:0",
  "-show_entries", "packet=pts_time,flags",
  "-of", "csv=print_section=0",
  video
], capture_output=True, text=True)
keyframes = [float(line.split(',')[0]) for line in keyframesRaw.stdout.split('\n') if line and len(line.split(',')) > 1 and 'K' in line.split(',')[1]]

lastFrameRaw = subprocess.run([
  'ffprobe', '-v', 'quiet',
  '-show_entries', 'format=duration',
  '-of', 'csv=p=0',
  str(video)
], capture_output=True, text=True)
lastFrame = float(lastFrameRaw.stdout.strip())

codecRaw = subprocess.run([
  'ffprobe', '-v', 'quiet',
  '-select_streams', 'v:0',
  '-show_entries', 'stream=codec_name',
  '-of', 'csv=p=0',
  str(video)
], capture_output=True, text=True)
inputCodec = codecRaw.stdout.strip()

CODEC_MAP = {
    'h264': 'libx264',
    'hevc': 'libx265',
    'vp9':  'libvpx-vp9',
    'av1':  'libsvtav1',
}
videoCodec = CODEC_MAP.get(inputCodec, 'libx264')

# make segments to keep
cursor = 0;
keepSegments = [];

#
# DETERMINE SEGMENTS TO KEEP
#
# todo: if we're close enought to a keyframe let's just use it instead of reencoding for nothing
# todo: eliminate segments smaller than 1s
for seg in segments:
  startFrame = seg['segment'][0]
  prevKeyframe = getPrevKeyframe(keyframes, startFrame)

  endFrame = seg['segment'][1]
  nextKeyframe = getNextKeyframe(keyframes, endFrame)

  # print(startFrame, '-', endFrame)

  if cursor != startFrame:
    keepSegments.append({
      'start': cursor,
      'end': prevKeyframe,
      'reencode': False
    })


  if startFrame != 0:
    keepSegments.append({
      'start': prevKeyframe,
      'end': startFrame,
      'reencode': True
    })

  if endFrame != lastFrame:
    keepSegments.append({
      'start': endFrame,
      'end': nextKeyframe,
      'reencode': True
    })

  cursor = nextKeyframe if nextKeyframe else lastFrame

if cursor < lastFrame:
  keepSegments.append({
    'start': cursor,
    'end': lastFrame,
    'reencode': False
  })



#
# SPLITTING VIDEO INTO SEGMENTS TO REMOVE ADS
#
outputDir = Path(args.output_dir)
for i, seg in enumerate(keepSegments):
  print(f"Processing segment {i+1}/{len(keepSegments)}({seg['start']:.2f}s → {seg['end']:.2f}s)...")

  output = str(outputDir / f"segment_{i+1}.mp4")

  if seg['reencode']:
    cmd = [
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
        '-i', str(video),
        '-ss', str(seg['start']),
        '-to', str(seg['end']),
        '-c:v', videoCodec, '-c:a', 'copy',
        output
    ]
  else:
    cmd = [
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
        '-ss', str(seg['start']),
        '-to', str(seg['end']),
        '-i', str(video),
        '-c', 'copy',
        output
    ]

  subprocess.run(cmd)

#
# JOIN THE FINAL SEGMENTS BACK
#
concatFile = str(outputDir / 'concat.txt')

with open(concatFile, 'w') as f:
  for i in range(len(keepSegments)):
    f.write(f"file 'segment_{i+1}.mp4'\n")

subprocess.run([
    'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
    '-f', 'concat',
    '-safe', '0',
    '-i', concatFile,
    '-c', 'copy',
    str(outputDir / 'output.mp4')
])

for i in range(len(keepSegments)):
  os.remove(str(outputDir / f'segment_{i+1}.mp4'))

os.remove(concatFile)
