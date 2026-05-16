from __future__ import annotations

import sys
from pathlib import Path

SUPPORTED_EXTENSIONS = {".mp3", ".mp4", ".wav", ".m4a", ".flac"}


def scan_paths(paths: list[Path]) -> list[Path]:
    """Scan input paths, expand directories, and filter to supported media files.

    Args:
        paths: List of file or directory paths.

    Returns:
        Sorted list of supported media file paths.
    """
    result: list[Path] = []
    seen: set[Path] = set()

    for p in paths:
        if not p.exists():
            print(f"Skipping: {p} (not found)", file=sys.stderr)
            continue

        if p.is_file():
            _collect_file(p, result, seen)
        elif p.is_dir():
            for file_path in sorted(p.rglob("*")):
                if file_path.is_file():
                    _collect_file(file_path, result, seen)

    return result


def _collect_file(file_path: Path, result: list[Path], seen: set[Path]) -> None:
    if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        print(f"Skipping: {file_path} (unsupported format)", file=sys.stderr)
        return
    if file_path in seen:
        return
    seen.add(file_path)
    result.append(file_path)
