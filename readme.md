# yt-cut

the fastest command line tool for removing segments from pre-downloaded youtube videos with frame-accurate cuts

## Dependencies

- Python 3.7+
- ffmpeg + ffprobe (`brew install ffmpeg` on macOS)

## Usage

```bash
python3 yt-cut.py --input=path/to/video.mp4 --id=VIDEO_ID --output_dir=path/to/output/
```

## Arguments

| Argument | Description | Required |
|---|---|---|
| `--input` | Path to the video file | Yes |
| `--id` | YouTube video ID | Yes |
| `--output_dir` | Folder to write output.mp4 to | No (defaults to `.`) |

## Example

```bash
python3 yt-cut.py --input=path/to/video.mp4 --id=SqD_8FGk89o --output_dir=./out/
```
