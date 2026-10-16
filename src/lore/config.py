"""User settings: `~/.config/lore/config.toml`."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lore.paths import config_path, default_source
from lore.theme import PALETTES

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

EDITING_MODES = ("emacs", "vi")
PREVIEWS = ("auto", "on", "off")


@dataclass
class Settings:
    theme: str = "void"
    editing_mode: str = "emacs"
    source: Path | None = None
    preview: str = "auto"

    @property
    def source_dir(self) -> Path:
        return self.source or default_source()


def load() -> tuple[Settings, list[str]]:
    s, warnings = Settings(), []
    path = config_path()
    if not path.is_file():
        return s, warnings
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return s, [f"{path}: {e}"]
    if (t := data.get("theme")) is not None:
        if t in PALETTES:
            s.theme = t
        else:
            warnings.append(f"theme must be one of {', '.join(PALETTES)}")
    if (m := data.get("editing_mode")) is not None:
        if m in EDITING_MODES:
            s.editing_mode = m
        else:
            warnings.append("editing_mode must be 'emacs' or 'vi'")
    if (p := data.get("preview")) is not None:
        if p in PREVIEWS:
            s.preview = p
        else:
            warnings.append("preview must be 'auto', 'on' or 'off'")
    if (src := data.get("source")) is not None:
        s.source = Path(str(src)).expanduser()
    return s, warnings
