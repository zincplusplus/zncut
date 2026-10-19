#!/usr/bin/env python3
import sys, json, subprocess, os, argparse, bisect, urllib.request, urllib.parse, time, tempfile, shutil
from pathlib import Path

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

def parseSegments(text):
  # "250.3-330.1,600-645.5" -> same shape as the SponsorBlock response
  segments = []
  for pair in text.split(','):
    start, end = pair.strip().split('-')
    start, end = float(start), float(end)
    if end <= start:
      raise ValueError(f"Segment end must be after its start: {pair}")
    segments.append({'segment': [start, end]})
  return sorted(segments, key=lambda seg: seg['segment'][0])

def run(cmd, tempDir):
  # an ffmpeg failure must stop the cut, not leave a short video behind
  result = subprocess.run(cmd, capture_output=True, text=True)
  if result.returncode != 0:
    shutil.rmtree(tempDir, ignore_errors=True)
    print(f"ffmpeg failed: {result.stderr.strip()}")
    exit(1)

def probeDuration(path, stream):
  raw = subprocess.run([
    'ffprobe', '-v', 'quiet',
    '-select_streams', stream,
    '-show_entries', 'stream=duration',
    '-of', 'csv=p=0',
    str(path)
  ], capture_output=True, text=True)
  return float(raw.stdout.strip())

def getPrevKeyframe(keyframes, frame):
  i = bisect.bisect_right(keyframes, frame);
  result = keyframes[i-1];
  return result

def getNextKeyframe(keyframes, frame):
  i = bisect.bisect_right(keyframes, frame);
  result = keyframes[i] if i < len(keyframes) else None;
  return result

def main():
  #
  # APP SETTINGS
  #
  # todo allow users to say which categories they want
  parser = argparse.ArgumentParser()
  parser.add_argument('--input')
  # parser.add_argument('--delta', type=float, default=0.3)
  parser.add_argument('--id')
  parser.add_argument('--segments', help='Cut these instead of SponsorBlock segments, in seconds: 250.3-330.1,600-645.5')
  parser.add_argument('--output', default=None)
  args = parser.parse_args()

  if not args.input:
    print("Missing path to video. You need to provide it like this --input path/to/video.mp4")
    exit(1)

  if not args.id and not args.segments:
    print("Missing YouTube video id. You need to provide it like this --id SqD_8FGk89o otherwise I can't figure out the sponsors (or pass --segments 250.3-330.1)")
    exit(1)

  if args.segments:
    try:
      segments = parseSegments(args.segments)
    except ValueError as e:
      print(f"Invalid --segments: {e}. Use seconds like this --segments 250.3-330.1,600-645.5")
      exit(1)

  if not Path(args.input).exists():
    print(f"Video file not found: {args.input}")
    exit(1)

  if not args.output:
    p = Path(args.input)
    args.output = str(p.parent / f"{p.stem}_zncut{p.suffix}")

  #
  # APP
  #
  start_time = time.time()
  video = args.input;
  if not args.segments:
    segments = fetchSegments(args.id)
  if not segments:
    print("No sponsor segments found, nothing to cut")
    exit(0)

  keyframesRaw = subprocess.run([
    "ffprobe", "-v", "quiet",
    "-select_streams", "v:0",
    "-show_entries", "packet=pts_time,dts_time,flags",
    "-of", "csv=print_section=0",
    video
  ], capture_output=True, text=True)
  packets = [l.split(',') for l in keyframesRaw.stdout.split('\n') if l.count(',') >= 2 and 'N/A' not in l]
  framePts = sorted(float(p[0]) for p in packets)
  # keyframe pts -> keyframe dts. A stream copy stops on DTS, and with B-frames
  # the keyframe's DTS is earlier than its PTS, so we must stop at the DTS.
  keyframeDts = {float(p[0]): float(p[1]) for p in packets if 'K' in p[2]}
  keyframes = sorted(keyframeDts)

  # the video stream's own end: the container's duration also covers audio
  # that runs past the last frame (common on YouTube), which isn't cut
  lastFrame = probeDuration(video, 'v:0')

  # snap cut points to frame boundaries so audio and video drop exactly the
  # same duration, then merge overlapping/adjacent segments
  def snap(t):
    i = bisect.bisect_left(framePts, t - 1e-6)
    return framePts[i] if i < len(framePts) else lastFrame
  cuts = []
  for seg in sorted(segments, key=lambda s: s['segment'][0]):
    start, end = snap(seg['segment'][0]), snap(min(seg['segment'][1], lastFrame))
    if end <= start:
      continue
    if cuts and start <= cuts[-1][1]:
      cuts[-1][1] = max(cuts[-1][1], end)
    else:
      cuts.append([start, end])

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
  for i, (start, end) in enumerate(cuts):
    if start > cursor:
      prevKeyframe = getPrevKeyframe(keyframes, start)
      if prevKeyframe > cursor:
        keepSegments.append({'start': cursor, 'end': prevKeyframe, 'reencode': False})
        cursor = prevKeyframe
      if start > cursor:
        keepSegments.append({'start': cursor, 'end': start, 'reencode': True})
    # re-encode from the cut end up to the next keyframe (or the next cut)
    i2 = bisect.bisect_left(keyframes, end - 1e-6)
    nextKeyframe = keyframes[i2] if i2 < len(keyframes) else lastFrame
    stop = min(nextKeyframe, cuts[i+1][0] if i + 1 < len(cuts) else lastFrame)
    if stop > end:
      keepSegments.append({'start': end, 'end': stop, 'reencode': True})
    cursor = stop

  if cursor < lastFrame:
    keepSegments.append({'start': cursor, 'end': lastFrame, 'reencode': False})

  #
  # SPLITTING VIDEO INTO SEGMENTS TO REMOVE ADS
  #
  # own temp folder per run, so several cuts can share an output folder
  outputDir = Path(tempfile.mkdtemp(prefix='zncut_', dir=Path(args.output).parent))
  for i, seg in enumerate(keepSegments):
    print(f"Processing segment {i+1}/{len(keepSegments)}({seg['start']:.2f}s → {seg['end']:.2f}s)...")

    output = str(outputDir / f"segment_{i+1}.mp4");

    if seg['reencode']:
      cmd = [
          'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
          '-i', str(video),
          # -1ms: probe times are rounded to 6 decimals, never miss/add a frame
          '-ss', f"{seg['start'] - 0.001:.6f}",
          '-to', f"{seg['end'] - 0.001:.6f}",
          '-map', '0:v:0', '-c:v', videoCodec,
          output
      ]
    else:
      cmd = [
          'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
          '-ss', str(seg['start']),
          *(['-to', f"{keyframeDts[seg['end']] - 0.001:.6f}"] if seg['end'] in keyframeDts else []),
          '-i', str(video),
          '-map', '0:v:0', '-c', 'copy',
          output
      ]

    run(cmd, outputDir)

  #
  # JOIN THE FINAL SEGMENTS BACK
  #
  concatFile = str(outputDir / 'concat.txt')

  with open(concatFile, 'w') as f:
    for i in range(len(keepSegments)):
      f.write(f"file 'segment_{i+1}.mp4'\n")

  # audio: one sample-accurate pass over the kept ranges (AAC packets are
  # 21ms, so stream-copied audio can't follow frame-accurate video cuts)
  keepRanges, t = [], 0.0
  for start, end in cuts:
    if start > t: keepRanges.append((t, start))
    t = end
  if t < lastFrame: keepRanges.append((t, lastFrame))
  graph = ''.join(f"[1:a:0]atrim=start={a:.6f}:end={b:.6f},asetpts=PTS-STARTPTS[a{k}];" for k, (a, b) in enumerate(keepRanges))
  graph += ''.join(f"[a{k}]" for k in range(len(keepRanges))) + f"concat=n={len(keepRanges)}:v=0:a=1[a]"

  run([
      'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
      '-f', 'concat',
      '-safe', '0',
      '-i', concatFile,
      '-i', str(video),
      '-filter_complex', graph,
      '-map', '0:v', '-map', '[a]',
      '-map_chapters', '-1',  # source chapters would be stale; write shifted ones instead
      '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
      args.output
  ], outputDir)

  shutil.rmtree(outputDir)

  # never hand back a video that's shorter or longer than it should be
  expected = lastFrame - sum(end - start for start, end in cuts)
  actual = probeDuration(args.output, 'v:0')
  frame = (framePts[-1] - framePts[0]) / max(len(framePts) - 1, 1)
  if abs(actual - expected) > frame * 1.5:
    os.remove(args.output)
    print(f"Cut failed: expected {expected:.3f}s of video but got {actual:.3f}s, output removed")
    exit(1)

  elapsed = time.time() - start_time
  minutes, seconds = divmod(int(elapsed), 60)
  if minutes:
    print(f"Done in {minutes}m {seconds}s")
  else:
    print(f"Done in {seconds}s")

if __name__ == '__main__':
  main()
