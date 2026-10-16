"""The startup wordmark: pixels drawn with half-block characters (same technique as ember's)."""

from __future__ import annotations

# 5×7 bitmap glyphs. Rendered with ▀ ▄ █: every terminal cell holds two square-ish pixels.
GLYPHS: dict[str, tuple[str, ...]] = {
    "L": ("#....", "#....", "#....", "#....", "#....", "#....", "#####"),
    "O": (".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "R": ("####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"),
    "E": ("#####", "#....", "#....", "####.", "#....", "#....", "#####"),
    ":": ("...", ".##", ".##", "...", "...", ".##", ".##"),
}
_HALF = {(True, True): "█", (True, False): "▀", (False, True): "▄", (False, False): " "}


def pixel_rows(word: str, spacing: int = 1) -> list[str]:
    """`word` as lines of half-block characters (7 pixel rows → 4 lines)."""
    height = 7
    bitmap = ["" for _ in range(height)]
    for i, ch in enumerate(word.upper()):
        glyph = GLYPHS[ch]
        for row in range(height):
            bitmap[row] += ("." * spacing if i else "") + glyph[row]
    width = len(bitmap[0])
    lines = []
    for top in range(0, height, 2):
        line = ""
        for col in range(width):
            upper = bitmap[top][col] == "#"
            lower = top + 1 < height and bitmap[top + 1][col] == "#"
            line += _HALF[(upper, lower)]
        lines.append(line.rstrip())
    return lines
