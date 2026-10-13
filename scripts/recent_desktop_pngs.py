#!/usr/bin/env python3
"""Print the paths of the newest N top-level PNG files on the Desktop."""

from pathlib import Path
import sys


def main() -> int:
    raw_count = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else "1"
    try:
        count = int(raw_count)
    except ValueError:
        print(f"Expected a positive integer count, got: {raw_count!r}")
        return 2
    if count < 1:
        print("Expected a positive integer count.")
        return 2

    desktop = Path.home() / "Desktop"
    files = [
        path
        for path in desktop.iterdir()
        if path.is_file() and path.suffix.lower() == ".png"
    ] if desktop.is_dir() else []
    files.sort(key=lambda path: (path.stat().st_mtime, path.name), reverse=True)

    if not files:
        print(f"No PNG files found on {desktop}.")
        return 0

    for path in files[:count]:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
