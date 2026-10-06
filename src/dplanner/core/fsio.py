"""Filesystem primitives, free of policy.

Everything here is a helper that a storage provider or a store composes; none of it decides
anything. ``slugify`` transliterates rather than merely stripping, because a folder name is
the one part of a workspace a person reads in a file browser.
"""

import csv
import os
import re
import tempfile
import unicodedata
from collections.abc import Sequence
from pathlib import Path

# Norwegian (plus neighbours) transliterated explicitly: NFKD alone would drop ø entirely
# rather than fold it to "o", and æ→ae matters for readable folder names.
_NORDIC = {
    "ø": "o",
    "Ø": "O",
    "å": "a",
    "Å": "A",
    "æ": "ae",
    "Æ": "Ae",
    "ö": "o",
    "ä": "a",
    "ü": "u",
    "ß": "ss",
    "ð": "d",
    "þ": "th",
}


def slugify(title: str, *, fallback: str = "untitled") -> str:
    """Fold ``title`` to a lowercase ASCII slug suitable as a folder name."""
    s = "".join(_NORDIC.get(c, c) for c in title)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s or fallback


def write_atomic(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` so a crash never leaves a truncated file.

    The temporary lives in the same directory as the target because the rename is only
    atomic within one filesystem, and its name is unique to this call because two
    processes write one path — a window and the CLI — and a shared name let one writer
    rename the other's half-written file, or find its own gone. No fsync: git is the
    durability layer for this project, and the failure this guards against is a partial
    write, not a lost one.

    ``newline="\n"`` because every file that comes through here is part of the on-disk
    format, and that format is LF (FORMAT.md's *Bytes on disk*). Left to itself
    ``write_text`` translates to ``os.linesep``, so the same plan saved on Windows came
    back as a whole-file diff against the same plan saved anywhere else — one platform
    quietly rewriting every line of a format whose whole purpose is to be shared and
    merged.
    """
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        # mkstemp makes the file 0600; keep what the target had, or what write_text gave.
        tmp.chmod(path.stat().st_mode if path.exists() else 0o644)
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_csv(path: Path, rows: Sequence[Sequence[str]]) -> None:
    """Write ``rows`` as CSV the way a spreadsheet expects it.

    utf-8-sig: the BOM is what makes Excel read the file as Unicode rather than guessing
    the console code page.
    """
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        csv.writer(handle).writerows(rows)
