---
description: Capture hand-drawn diagrams from paper/post-its via the Desk View camera (window opens immediately; SPACE captures, R flips, Q cancels)
allowed-tools: Bash, Read
---

## Capture result

The capture window already ran — this is its output:

!`missing=""; for tool in uv ffmpeg; do command -v "$tool" >/dev/null 2>&1 || missing="$missing $tool"; done; if [ -n "$missing" ]; then echo "MISSING TOOLS:$missing"; command -v brew >/dev/null 2>&1 && echo "HOMEBREW: installed" || echo "HOMEBREW: not installed"; else pkill -f desk_snap.py 2>/dev/null; OUTDIR=$(mktemp -d /tmp/desk-snap.XXXXXX); uv run ~/.claude/scripts/desk_snap.py --live --once -o "$OUTDIR" 2>&1; fi`

## Your task

If the output starts with `MISSING TOOLS:`, no capture window opened. The
skill needs `uv` (runs the script and installs its Python packages) and
`ffmpeg` (reads the camera). Tell the user which are missing and ask them to
install them, then rerun `/look-at-desk`:
- With Homebrew (`HOMEBREW: installed`): `brew install <missing tools>`.
- Without Homebrew: install it from https://brew.sh first, then use the
  command above. (`uv` alone can also come from
  `curl -LsSf https://astral.sh/uv/install.sh | sh`.)
Offer to run the install command for them, but only run it if they agree.
Stop here; skip the steps below.

Otherwise the user has ALREADY used the capture window (it opened before you
saw this), so do NOT print any instructions, controls, or preamble about the
window.

1. From the output above, collect the `  [N] clean: <path>` lines — these are
   cleaned, white-background scans of each detected sheet (paper/post-its).
2. Read every `clean` PNG with the Read tool and look at the content. If one
   is illegible, fall back to its `crop` file, then the `raw` frame.
3. Then do what the user asked: $ARGUMENTS
   (If no arguments were given: describe what is drawn on each sheet.)
4. If there are no `clean:` lines (user pressed Q, or `no paper found`), say
   the capture was cancelled/empty and offer to relaunch — suggest moving the
   paper toward the middle of the desk area and leaning back. To relaunch:
   `OUTDIR=$(mktemp -d /tmp/desk-snap.XXXXXX); uv run ~/.claude/scripts/desk_snap.py --live --once -o "$OUTDIR"`
   (foreground, generous timeout).
5. If the output says `no camera matching 'Desk View' found`, explain that
   the skill needs a Desk View camera: an iPhone used as a Continuity Camera
   (near the Mac, same Apple ID, Wi-Fi and Bluetooth on) or a Mac whose
   built-in camera supports Desk View. If the camera fails to open at all,
   the terminal app may need camera access in System Settings → Privacy &
   Security → Camera.

Implementation notes (only if debugging is needed): script lives at
`~/.claude/scripts/desk_snap.py`; the capture device is the AVFoundation
camera whose name contains "Desk View" (resolved at runtime).
