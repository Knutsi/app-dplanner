"""Debug ▸ Windows: what this machine can do about Windows, and the commands that do it.

Qt-free, and **asked once per build**. CLAUDE.md's rule is that no subprocess and no PATH walk
happens inside an action state — a state callback runs on every context change — so
:func:`probe` is called at registration and the answer is a field the two states read.

**The probe records facts; each verb derives its own refusal.** Running the check needs both
the harness (a development script, so an installed DPlanner does not carry it) and the VM to
run it in; *watching* the desktop needs only the VM. One probe, two questions, and neither
verb is hidden when it cannot run — a greyed entry with the reason in its label is what tells
a machine the capability exists at all.
"""

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# src/dplanner/modules/debug/windows_check.py → the repository root.
HARNESS = Path(__file__).resolve().parents[4] / "scripts" / "windows_check.py"
VM_COMMAND = "omarchy-windows-vm"

# Watching the desktop is delegated to Omarchy's own launcher rather than done here: it knows
# the private credentials file, the HiDPI scale, the Kerberos workaround FreeRDP 3 needs, and
# which client to run (xfreerdp3). `--keep-alive` is not optional. Without it the launcher
# stops the VM when the RDP window closes -- the developer's own VM, from a Debug menu entry.
DESKTOP_COMMAND = (VM_COMMAND, "launch", "--keep-alive")


@dataclass(frozen=True)
class WindowsCheck:
    """Two facts about this machine. Every refusal below is derived from them."""

    script: Path | None  # None when this build carries no scripts/.
    has_vm: bool

    @property
    def run_refusal(self) -> str:
        """Why the check cannot run here — empty when it can."""
        if self.script is None:
            return "only from a source checkout — this build has no scripts/"
        return "" if self.has_vm else f"needs Omarchy's Windows VM ({VM_COMMAND} is not on PATH)"

    @property
    def watch_refusal(self) -> str:
        """Why the desktop cannot be watched here — empty when it can.

        Only the VM: a build with no ``scripts/`` can still open an RDP session to a VM that
        is running, and refusing that would be refusing something that works.
        """
        return "" if self.has_vm else f"needs Omarchy's Windows VM ({VM_COMMAND} is not on PATH)"


def probe(
    script: Path = HARNESS, which: Callable[[str], str | None] = shutil.which
) -> WindowsCheck:
    """Asked once, at registration. ``which`` is injectable so every machine's answer is
    checkable from any other — the convention ``cli/desktop.py`` set."""
    return WindowsCheck(script if script.is_file() else None, bool(which(VM_COMMAND)))


def command(check: WindowsCheck, python: str, verb: str = "all") -> list[str]:
    """The harness invocation. Raises rather than build a command for a refused check."""
    if check.run_refusal:
        raise ValueError(check.run_refusal)
    assert check.script is not None
    return [python, str(check.script), verb]
