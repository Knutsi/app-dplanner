"""Whether this machine can take dictation, as two checklist rows.

A Qt-free ``checks.py`` cannot read which provider a person chose — that is a QSettings
value, and the CLI never loads Qt — so the rows say what the machine *could* use, which is
also what *Automatic* would pick: a provider that does not refuse with its default text,
and a recorder whose program is on PATH. Both advise; a plan is typed as well as spoken.
The remedy is the dictation module's own action, so the checklist opens Settings ▸ Dictation
without importing anything.
"""

import shutil
import sys
from collections.abc import Sequence

from dplanner.cli.checklist import MachineCheck, Reading, Remedy
from dplanner.domain.dictation import (
    RECORDERS,
    DictationProvider,
    Recorder,
    Which,
    first_installed,
    recorders_for,
)

SETUP_ACTION = "dictation.settings"
# ffmpeg records on every platform this application runs on, and every family packages it.
FFMPEG_PACKAGES = {"": "ffmpeg", "windows": "Gyan.FFmpeg"}
OS_DICTATION = {
    "darwin": "macOS has its own dictation too: press Fn twice in any field.",
    "win32": "Windows has its own dictation too: press Win+H in any field.",
}


def _provider(providers: Sequence[DictationProvider]) -> Reading:
    refusals = []
    for provider in providers:
        why = provider.refusal(provider.default)
        if why is None:
            return Reading(ok=True, detail=f"{provider.label} is ready")
        refusals.append(f"{provider.label}: {why}")
    return Reading(ok=False, detail="; ".join(refusals) if refusals else "no providers")


def _recorder(recorders: Sequence[Recorder], which: Which) -> Reading:
    found = first_installed(recorders, which)
    if found is not None:
        return Reading(ok=True, detail=f"{found.label} on PATH")
    names = ", ".join(recorder.probe for recorder in recorders)
    return Reading(ok=False, detail=f"none of {names} on PATH" if names else "none known here")


def checks(
    *,
    providers: Sequence[DictationProvider],
    recorders: Sequence[Recorder] = RECORDERS,
    which: Which = shutil.which,
    platform: str = sys.platform,
) -> list[MachineCheck]:
    """``providers`` is the root's tuple, in the order Automatic tries them."""
    here = recorders_for(platform, recorders)
    aside = OS_DICTATION.get(platform, "")
    return [
        MachineCheck(
            id="dictation.provider",
            group="Services",
            label="A dictation provider",
            probe=lambda: _provider(providers),
            remedy=Remedy(
                words="Install a whisper command or add an OpenAI API key, then pick it "
                f"under Settings ▸ Dictation. {aside}".strip(),
                action=SETUP_ACTION,
                verb="Set Up…",
            ),
        ),
        MachineCheck(
            id="dictation.recorder",
            group="Services",
            label="A microphone recorder",
            probe=lambda: _recorder(here, which),
            remedy=Remedy(
                words="A command that streams the microphone — PipeWire, PulseAudio, ALSA, "
                "ffmpeg or sox; Settings ▸ Dictation picks the first one installed.",
                action=SETUP_ACTION,
                verb="Set Up…",
                packages=FFMPEG_PACKAGES,
            ),
        ),
    ]
