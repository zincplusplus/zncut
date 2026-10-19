# Frame- and audio-accuracy tests for zncut --segments.
#
# The source video draws its own frame number as 10 bit blocks and flashes
# once per second together with an audio beep, so after a cut we can read
# back exactly which frames survived and whether sound still lines up.
# Needs ffmpeg/ffprobe and numpy. Run: python -m pytest tests
import math, subprocess, sys
from pathlib import Path

import numpy as np
import pytest

ZNCUT = Path(__file__).resolve().parent.parent / 'zncut.py'
W, H, FPS, SECONDS, RATE = 320, 240, 30, 20, 48000
FRAMES = FPS * SECONDS

def frameImage(n):
  im = np.zeros((H, W), np.uint8)
  for b in range(10):
    if n >> b & 1:
      im[40:80, b*32:b*32+32] = 255
  if n % FPS == 0:
    im[180:220, 140:180] = 255
  return im

def makeSource(path, audioSeconds):
  raw = b''.join(frameImage(n).tobytes() for n in range(FRAMES))
  beep = "if(lt(mod(t,1),0.05),0.8*sin(2*PI*1000*t),0)"
  subprocess.run([
    'ffmpeg', '-v', 'error', '-y',
    '-f', 'rawvideo', '-pix_fmt', 'gray', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
    '-f', 'lavfi', '-i', f"aevalsrc='{beep}':s={RATE}:d={audioSeconds}",
    '-c:v', 'libx264', '-g', '60', '-pix_fmt', 'yuv420p',
    '-c:a', 'aac', str(path)
  ], input=raw, check=True)
  return path

@pytest.fixture(scope='session')
def source(tmp_path_factory):
  return makeSource(tmp_path_factory.mktemp('src') / 'src.mp4', SECONDS)

def keptFrames(segments):
  cut = set()
  for pair in segments.split(','):
    a, b = map(float, pair.split('-'))
    cut |= set(range(math.ceil(a*FPS - 1e-6), min(FRAMES, math.ceil(b*FPS - 1e-6))))
  return [n for n in range(FRAMES) if n not in cut]

def readFrames(path):
  raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-map', '0:v:0', '-fps_mode', 'passthrough',
                        '-f', 'rawvideo', '-pix_fmt', 'gray', '-'], capture_output=True, check=True).stdout
  frames = np.frombuffer(raw, np.uint8).reshape(-1, H, W)
  numbers = [sum(1 << b for b in range(10) if im[60, b*32+16] > 125) for im in frames]
  flashes = [i for i, im in enumerate(frames) if im[200, 160] > 125]
  return numbers, flashes

def readAudio(path):
  raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-map', '0:a:0', '-ac', '1', '-ar', str(RATE),
                        '-f', 'f32le', '-'], capture_output=True, check=True).stdout
  return np.abs(np.frombuffer(raw, np.float32))

def beepOnsets(audio):
  loud = np.flatnonzero(audio > 0.2)
  onsets = [loud[0]] + [b for a, b in zip(loud[:-1], loud[1:]) if b - a > RATE // 100]
  return [s / RATE for s in onsets]

def beepsAt(audio, t):
  # the beep should be sounding just after the flash frame starts
  window = audio[int((t + 0.002) * RATE):int((t + 0.020) * RATE)]
  return len(window) > 0 and window.max() > 0.2

def cut(source, tmp_path, segments):
  out = tmp_path / 'out.mp4'
  result = subprocess.run([sys.executable, '-I', str(ZNCUT), '--input', str(source), '--segments', segments,
                           '--output', str(out)], capture_output=True, text=True)
  assert result.returncode == 0, result.stdout + result.stderr
  return out

@pytest.mark.parametrize('segments', [
  '7.5-8.5',                         # middle of a keyframe interval
  '4-5',                             # starts exactly on a keyframe
  '3.31-4.07,4.5-5.0,12.01-14.99',   # used to silently truncate the output
  '0-1.2',                           # at the start
  '18.5-20',                         # to the end
  '6.1-7.0,6.5-7.9',                 # overlapping
])
def test_cut_keeps_exactly_the_right_frames_with_audio_in_sync(source, tmp_path, segments):
  out = cut(source, tmp_path, segments)

  numbers, flashes = readFrames(out)
  assert numbers == keptFrames(segments)

  # every surviving flash still has its beep, and every beep that starts
  # still starts on a flash (a beep cut short by a cut can merge with the
  # next one, so check both directions instead of pairing them up)
  audio = readAudio(out)
  for i in flashes:
    assert beepsAt(audio, i / FPS), f'no beep at flash frame {i}'
  for t in beepOnsets(audio):
    assert min(abs(t - i / FPS) for i in flashes) < 0.010, f'beep at {t:.3f}s has no flash'

def test_audio_running_past_the_last_frame_does_not_fail_the_cut(tmp_path):
  # YouTube files often end with ~0.2s of audio after the last video frame
  source = makeSource(tmp_path / 'tail.mp4', SECONDS + 0.2)
  out = cut(source, tmp_path, '7.5-8.5,12-13')
  numbers, _ = readFrames(out)
  assert numbers == keptFrames('7.5-8.5,12-13')
