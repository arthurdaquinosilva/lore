"""Drive the real interface in a pseudo-terminal and read the screen back with pyte."""

from __future__ import annotations

import os
import sys
import time

import pexpect
import pyte


class Term:
    def __init__(self, args: list[str], home: str, cols: int = 120, rows: int = 40, env: dict | None = None):
        self.screen = pyte.Screen(cols, rows)
        self.stream = pyte.ByteStream(self.screen)
        e = {**os.environ, "LORE_HOME": home, "TERM": "xterm-256color", "COLUMNS": str(cols), "LINES": str(rows), **(env or {})}
        lore = os.path.join(os.path.dirname(sys.executable), "lore")
        self.child = pexpect.spawn(lore, args, env=e, dimensions=(rows, cols), timeout=5)

    def pump(self, wait: float = 0.4) -> None:
        end = time.time() + wait
        while time.time() < end:
            try:
                data = self.child.read_nonblocking(65536, timeout=0.05)
                self.stream.feed(data)
                end = max(end, time.time() + 0.08)
            except pexpect.TIMEOUT:
                pass
            except pexpect.EOF:
                break

    def send(self, keys: str, wait: float = 0.4) -> None:
        self.child.send(keys)
        self.pump(wait)

    def text(self) -> str:
        return "\n".join(line.rstrip() for line in self.screen.display).rstrip()

    def alive(self) -> bool:
        return self.child.isalive()

    def close(self) -> None:
        if self.child.isalive():
            self.child.terminate(force=True)


if __name__ == "__main__":
    home, *args = sys.argv[1:]
    t = Term(args, home)
    t.pump(1.5)
    print(t.text())
    t.close()
