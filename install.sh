#!/bin/sh
# lore installer: puts the `lore` command in its own virtual environment and builds the offline index.
#
#   ./install.sh                 from a clone of this repository
#   ./install.sh --uninstall     remove the command and the virtual environment (keeps your aliases)
#
# Options (environment variables):
#   LORE_INSTALL_DIR   where to put the `lore` command (default: ~/.local/bin)
#   LORE_SOURCE        where the course sources are (default: ~/programming-material/_build/sources)
set -eu

MIN_PY_MINOR=10
HERE="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/lore-app"
BIN_DIR="${LORE_INSTALL_DIR:-$HOME/.local/bin}"
VENV="$DATA_DIR/venv"

say() { printf '%s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

if [ "${1:-}" = "--uninstall" ]; then
    rm -f "$BIN_DIR/lore"
    rm -rf "$DATA_DIR"
    say "lore removed. Your aliases (~/.local/share/lore/aliases.json) and index were left alone."
    exit 0
fi

find_python() {
    for c in python3.13 python3.12 python3.11 python3.10 python3 python; do
        if command -v "$c" >/dev/null 2>&1 &&
           "$c" -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, $MIN_PY_MINOR) else 1)" 2>/dev/null; then
            command -v "$c"
            return 0
        fi
    done
    return 1
}

PY="$(find_python)" || die "Python 3.$MIN_PY_MINOR or newer is required"
say "using $PY"
mkdir -p "$DATA_DIR" "$BIN_DIR"
"$PY" -m venv "$VENV"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet "$HERE"
ln -sf "$VENV/bin/lore" "$BIN_DIR/lore"
say "installed: $BIN_DIR/lore"
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) say "note: $BIN_DIR is not on your PATH" ;; esac

if "$BIN_DIR/lore" index; then
    say ""
    say "Done. Run: lore"
else
    say ""
    say "lore is installed, but no index was built. Point it at the courses with:"
    say "  lore index --source /path/to/programming-material/_build/sources"
fi
