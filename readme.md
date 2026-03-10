# zncut

the fastest command line tool for removing ads from pre-downloaded youtube videos with frame-accurate cuts

## Dependencies

- Python 3.7+
- ffmpeg + ffprobe (`brew install ffmpeg` on macOS)

## Usage

```bash
python3 zncut.py --input path/to/video.mp4 --id VIDEO_ID --output path/to/output.mp4
```

## Arguments

| Argument    | Description                   | Required                               |
| ----------- | ----------------------------- | -------------------------------------- |
| `--input`   | Path to the video file        | Yes                                    |
| `--id`      | YouTube video ID              | Yes                                    |
| `--output`  | Output file path              | No (defaults to `<input>_zncut.<ext>`) |

## Example

```bash
python3 zncut.py --input path/to/video.mp4 --id dQw4w9WgXcQ --output out.mp4
```
