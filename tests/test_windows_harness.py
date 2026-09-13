"""The Windows harness's guest-side scripts stay readable by Windows PowerShell.

One rule, and it is here rather than in a comment because breaking it costs a 25-minute
reinstall to discover: **the guest scripts are ASCII**. `install.bat` calls `powershell`,
which is Windows PowerShell 5.1, and 5.1 reads a `.ps1` with no byte-order mark as ANSI
rather than UTF-8. An em dash inside a double-quoted string then terminates the string early
and the file fails to parse — with an error pointing thirty lines from the character that
caused it. The first provisioning run of the throwaway box died exactly that way.

Nothing else in this repository has the constraint, which is why it needs a test: the house
prose is full of em dashes, and a reviewer reading these files on Linux sees nothing wrong.
"""

from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parent.parent / "scripts" / "windows"
GUEST_SCRIPTS = ("provision.ps1", "runner.ps1", "install.bat")


@pytest.mark.parametrize("name", GUEST_SCRIPTS)
def test_a_guest_script_is_ascii(name):
    text = (HARNESS / name).read_text(encoding="utf-8")
    offenders = sorted({character for character in text if ord(character) > 127})
    assert offenders == [], (
        f"{name} carries {offenders}, which Windows PowerShell 5.1 reads as ANSI. "
        "Write it plain, or give the file a UTF-8 byte-order mark."
    )


def test_the_batch_file_keeps_crlf():
    """cmd.exe parses a batch file line by line as it runs, and an LF-only one can misread a
    label or a block. `.gitattributes` marks it `eol=crlf`; this is that rule, asserted."""
    raw = (HARNESS / "install.bat").read_bytes()
    assert b"\n" in raw
    assert raw.count(b"\n") == raw.count(b"\r\n")


def test_install_bat_hands_over_and_decides_nothing():
    """It runs once per disk with no console to watch and no way to retry without
    reinstalling Windows, so every decision belongs in provision.ps1, which is re-runnable."""
    text = (HARNESS / "install.bat").read_text(encoding="utf-8")
    assert "provision.ps1" in text
    assert "exit /b 0" in text  # A non-zero exit can wedge dockur's setup with no Windows.
