from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class FilePicker(Protocol):
    def choose_audio(self) -> Path | None: ...
    def choose_directory(self) -> Path | None: ...


@dataclass
class FakeFilePicker:
    audio: Path | None = None
    directory: Path | None = None

    def choose_audio(self) -> Path | None:
        return self.audio

    def choose_directory(self) -> Path | None:
        return self.directory


class WindowsFilePicker:
    """Use the standard Windows dialog without introducing a GUI runtime."""

    def choose_audio(self) -> Path | None:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            selected = filedialog.askopenfilename(
                title="选择音频",
                filetypes=[
                    ("Audio", "*.mp3 *.wav *.m4a *.flac"),
                    ("All files", "*.*"),
                ],
            )
        finally:
            root.destroy()
        return Path(selected) if selected else None

    def choose_directory(self) -> Path | None:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            selected = filedialog.askdirectory(title="选择 SubForge Library 目录")
        finally:
            root.destroy()
        return Path(selected) if selected else None
