# Configuration

## Installing and removing

The one-line installer keeps lore out of your projects' environments:

```sh
curl -fsSL https://raw.githubusercontent.com/arthurdaquinosilva/lore/main/install.sh | sh
```

| Environment variable | |
| --- | --- |
| `LORE_VERSION=0.1.0` | Install a specific release (the git tag `v0.1.0`) instead of `main` |
| `LORE_NO_PIPX=1` | Use the built-in virtual environment even if pipx is installed |
| `LORE_INSTALL_DIR` | Where to link the `lore` command (default `~/.local/bin`) |

It uses pipx when available, otherwise a virtual environment in `~/.local/share/lore-docs/venv`. Re-running it upgrades. `… | sh -s -- --uninstall` removes the command and that environment, and keeps your aliases, settings and index. It needs `git` and Python 3.10+.

After installing, the script builds the index if your course sources are in the default place. If not, point lore at them once:

```sh
lore index --source /path/to/programming-material/_build/sources
```

## Where things live

| Path | Contents |
| --- | --- |
| `~/.config/lore/config.toml` | Settings (this page) |
| `~/.local/share/lore/index.db` | The search index, rebuilt by `lore index` |
| `~/.local/share/lore/aliases.json` | Your aliases (plain JSON, safe to edit or commit) |
| `~/.local/share/lore/recent.json` | Recently opened topics and recent searches |

`XDG_CONFIG_HOME` and `XDG_DATA_HOME` are respected.

## Settings

`config.toml`, every key optional:

```toml
theme = "void"            # void | nebula | matrix
editing_mode = "emacs"    # "vi" gives the search box vi keys (Esc → normal mode; j/k move the list; i, a, A, I edit)
preview = "auto"          # auto | on | off — auto hides the preview below 100 columns
source = "~/programming-material/_build/sources"
```

Command-line options override the file for one run: `--theme nebula`, `--vi`. A bad value prints a warning and the default is used.

| Environment variable | |
| --- | --- |
| `LORE_HOME` | Keep lore's data **and** config under one directory (`data/`, `config/`) |
| `LORE_SOURCE` | Where `lore index` and the first run look for the course sources |

## Keeping the index current

Run `lore index` whenever the courses change. It replaces the index atomically, so a failed build never leaves you without one. The interface warns in its bottom line — *courses changed — run: lore index* — when a source file is newer than the index. `lore info` shows where the index came from and when it was built.
