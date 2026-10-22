# Changelog

## Unreleased

- **pitch**, one palette shared by ember, shtick, cinder, flare and lore: cool blue/violet hues on the terminal's own black. Backgrounds stay transparent, completion menus included (the current item is bold instead of shaded). lore's accent is green, and the wordmark follows it; selected rows, chips and overlays are transparent too. The `void`, `nebula` and `matrix` themes are gone; a config that still names one falls back to pitch with a warning.

## 0.1.0

- First release: offline full-text search over the course library (topics, code snippets with their output, definitions), a full-screen interface in ember's style with live suggestions, a preview and a reader, copy, aliases (`lore @name`), `--pick` for pipes, and a scripting CLI (`search`, `get`, `alias`, `index`, `courses`, `info`).
- One-line installer: `curl -fsSL .../install.sh | sh`, with `--uninstall`, `LORE_VERSION`, `LORE_NO_PIPX` and `LORE_INSTALL_DIR`.
