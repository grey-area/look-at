# look-at

Claude Code slash commands that let Claude look at things on your Mac:

| Command | What Claude sees |
|---|---|
| `/look-at-downloads [N]` | The newest N files or folders in `~/Downloads` (default 1). |
| `/look-at-screenshots [N]` | The newest N PNG screenshots on the Desktop (default 1). |
| `/look-at-desk [task]` | Paper sheets or post-its on your desk, captured through the Desk View camera. A preview window opens: SPACE captures, R flips 180°, Q cancels. Each sheet is cropped, straightened and cleaned to a white background. Anything after the command is the task, e.g. `/look-at-desk turn this into a mermaid diagram`. |

## Install

```sh
mkdir -p ~/.claude/commands ~/.claude/scripts
cp commands/*.md ~/.claude/commands/
cp scripts/*.py ~/.claude/scripts/
```

The commands call the scripts at `~/.claude/scripts/`, so keep that location.

## Requirements

- macOS and `python3`. `/look-at-downloads` and `/look-at-screenshots` use only the Python standard library. `/look-at-screenshots` assumes screenshots are saved to the Desktop as PNGs, which is the macOS default.
- `/look-at-desk` also needs:
  - [`uv`](https://docs.astral.sh/uv/) and `ffmpeg`: `brew install uv ffmpeg`. `uv` installs the script's Python dependencies (`opencv-python`, `numpy`) on first run. If either tool is missing, the command says so instead of capturing.
  - A Desk View camera: an iPhone used as a Continuity Camera, or a Mac whose built-in camera supports Desk View.
  - Camera access for your terminal app (System Settings → Privacy & Security → Camera).

## License

MIT
