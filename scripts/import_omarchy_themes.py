"""Generate the built-in Omarchy themes from an Omarchy installation.

    uv run python scripts/import_omarchy_themes.py                       # $OMARCHY_PATH/themes
    uv run python scripts/import_omarchy_themes.py THEMES_DIR --out PATH

Reads every ``<theme>/colors.toml`` under the themes directory and writes
``src/dplanner/theme/omarchy_themes.py``: one record per theme holding the file's colours —
the ``#rrggbb`` values and the mode — which ``theme/omarchy.py`` maps onto a ``Theme`` at
import. The mapping lives in code so it can change without regenerating; regenerate when
Omarchy ships a theme or changes one, and commit the result. Nothing it builds touches the
user's config, journal or library.
"""

import argparse
import os
import sys
from pathlib import Path

from dplanner.theme.omarchy import HEX, read_colors

OUT = Path(__file__).resolve().parent.parent / "src" / "dplanner" / "theme" / "omarchy_themes.py"


def collect(themes_dir: Path) -> dict[str, dict[str, str]]:
    """Every theme under ``themes_dir`` with a readable ``colors.toml``: its ``#rrggbb``
    values and its mode, both sorted, so the output is stable across runs."""
    themes: dict[str, dict[str, str]] = {}
    for directory in sorted(path for path in themes_dir.iterdir() if path.is_dir()):
        colors = read_colors(directory / "colors.toml")
        if colors is None:
            continue
        themes[directory.name] = {
            key: value for key, value in sorted(colors.items()) if key == "mode" or HEX.match(value)
        }
    return themes


def render(themes: dict[str, dict[str, str]], version: str) -> str:
    """The generated module's text — ruff-formatted by construction."""
    lines = [
        '"""Omarchy\'s default themes, as the colours their ``colors.toml`` files hold.',
        "",
        f"Generated from Omarchy {version} by ``scripts/import_omarchy_themes.py`` — regenerate,",
        "never edit. :mod:`dplanner.theme.omarchy` maps each record onto a ``Theme``.",
        '"""',
        "",
        "OMARCHY_COLORS: dict[str, dict[str, str]] = {",
    ]
    for name, colors in themes.items():
        lines.append(f'    "{name}": {{')
        lines.extend(f'        "{key}": "{value}",' for key, value in colors.items())
        lines.append("    },")
    lines.append("}")
    return "\n".join(lines) + "\n"


def omarchy_version(themes_dir: Path) -> str:
    try:
        return (themes_dir.parent / "version").read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    default_dir = Path(os.environ.get("OMARCHY_PATH", "/usr/share/omarchy")) / "themes"
    parser.add_argument("themes_dir", nargs="?", type=Path, default=default_dir)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    if not args.themes_dir.is_dir():
        print(f"no themes directory at {args.themes_dir}", file=sys.stderr)
        return 2
    themes = collect(args.themes_dir)
    args.out.write_text(render(themes, omarchy_version(args.themes_dir)), encoding="utf-8")
    print(f"{len(themes)} themes → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
