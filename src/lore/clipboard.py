"""Copy text to the system clipboard; falls back to the OSC 52 escape most terminals honour."""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys

TOOLS = [
    ("pbcopy", ["pbcopy"]),
    ("wl-copy", ["wl-copy"]),
    ("xclip", ["xclip", "-selection", "clipboard"]),
    ("xsel", ["xsel", "--clipboard", "--input"]),
    ("clip.exe", ["clip.exe"]),
]


def copy(text: str) -> str | None:
    """Returns how it was copied ('pbcopy', 'osc52', …) or None when nothing worked."""
    for name, cmd in TOOLS:
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, input=text.encode("utf-8"), check=True, timeout=3,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return name
            except (OSError, subprocess.SubprocessError):
                continue
    if sys.__stdout__ and sys.__stdout__.isatty() and len(text) < 90_000:
        payload = base64.b64encode(text.encode("utf-8")).decode()
        seq = f"\x1b]52;c;{payload}\x07"
        if os.environ.get("TMUX"):
            seq = f"\x1bPtmux;\x1b{seq}\x1b\\"
        sys.__stdout__.write(seq)
        sys.__stdout__.flush()
        return "osc52"
    return None
