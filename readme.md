# zncut

the fastest command line tool for removing ads from pre-downloaded youtube videos with frame-accurate cuts

## Install

```bash
pip install zncut
```

Requires ffmpeg + ffprobe (`brew install ffmpeg` on macOS).

## Usage

```bash
zncut --input path/to/video.mp4 --id VIDEO_ID --output path/to/output.mp4
```

## Arguments

| Argument   | Description            | Required                               |
| ---------- | ---------------------- | -------------------------------------- |
| `--input`  | Path to the video file | Yes                                    |
| `--id`     | YouTube video ID       | Yes                                    |
| `--output` | Output file path       | No (defaults to `<input>_zncut.<ext>`) |

## Example

```bash
zncut --input path/to/video.mp4 --id dQw4w9WgXcQ --output out.mp4
```

## Publishing to PyPI

First time only: `pipx install build twine`

```bash
pyproject-build && twine upload dist/*
```

The package is available at https://pypi.org/project/zncut/
