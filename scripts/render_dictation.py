"""Render the dictation surfaces in the dark and the light theme, to PNG.

    uv run python scripts/render_dictation.py --out docs/screenshots/f14-dictation

What F14 added: a microphone on every markdown strip, the editor's accent edge while it is
on, the Spinner in the glyph while the words are on their way, Settings ▸ Dictation with its
two preset fields and *Try it*, and the API key wizard a provider's refusal opens. The
providers and the recorder are stand-ins — a real one would need a microphone and a key —
driven through the same service every prose editor runs on.
"""

import argparse
import os
import shlex
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

# A shell that presets the platform would put every render on the desktop.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_PLATFORMTHEME"] = ""

from PySide6.QtCore import QCoreApplication, QEvent, QSettings
from PySide6.QtWidgets import QApplication, QWidget

from dplanner.domain.dictation import DictationProvider, Recorder
from dplanner.framework.dictation import DictationService
from dplanner.framework.key_dialog import ApiKeyDialog
from dplanner.framework.prose_section import ProseSection
from dplanner.framework.tasks import TaskService
from dplanner.modules.dictation.settings_page import build_page
from dplanner.modules.openai.provider import KEY_GUIDE, KEYS_URL
from dplanner.theme import apply_theme
from dplanner.theme.themes import DARK, LIGHT, Theme

PAGE_SIZE = (560, 640)
EDITOR_SIZE = (480, 240)
DIALOG_SIZE = (520, 420)

# A recorder that writes samples until told to stop — the test suite's stand-in.
RECORDER_SCRIPT = (
    "import signal, struct, sys, threading, time\n"
    "stop = threading.Event()\n"
    "signal.signal(signal.SIGTERM, lambda *_: stop.set())\n"
    "out = sys.stdout.buffer\n"
    "while not stop.is_set():\n"
    "    out.write(struct.pack('<h', 12000) * 160); out.flush(); time.sleep(0.01)\n"
)


def recorder_command() -> str:
    return " ".join(shlex.quote(t) for t in (sys.executable, "-u", "-c", RECORDER_SCRIPT))


class _Field:
    """A text field over nothing: enough for a bound editor to render."""

    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text

    def command(self, pos, removed, added, origin):
        self._text = self._text[:pos] + added + self._text[pos + len(removed) :]
        return _Noop()

    def connect(self, applied):
        return lambda: None


class _Noop:
    def text(self) -> str:
        return "Typing"

    def redo(self, document) -> None:
        pass

    def undo(self, document) -> None:
        pass

    def merge_with(self, other) -> bool:
        return False


def providers(*, slow: float = 0.0) -> tuple[DictationProvider, ...]:
    def transcribe(_wav: bytes, _text: str) -> str:
        time.sleep(slow)
        return "The modal asks for the e-mail address, which is also the account key."

    whisper = DictationProvider(
        "whisper_cpp",
        "whisper.cpp (whisper-cli)",
        "Command",
        "whisper-cli -m ggml-base.en.bin -f {audio} -nt -np",
        lambda _t: None,
        transcribe=transcribe,
        hint="Put the path of a downloaded ggml model after -m.",
        url="https://github.com/ggml-org/whisper.cpp",
    )
    live = DictationProvider(
        "openai_live",
        "OpenAI live transcription",
        "Model",
        "gpt-4o-transcribe",
        lambda _t: "OpenAI has no API key — add one",
        listen=lambda _m, _d: None,  # type: ignore[arg-type,return-value]
        rate=24000,
        hint="A Realtime transcription model; the words land while you speak.",
        url=KEYS_URL,
        setup_action="openai.key",
    )
    return (whisper, live)


def service(app_tasks: TaskService, *, slow: float = 0.0, which=None) -> DictationService:
    rows = (
        Recorder("pw-record", "PipeWire (pw-record)", "linux", recorder_command(), "pw-record"),
        Recorder("parecord", "PulseAudio (parecord)", "linux", "parecord --raw", "parecord"),
        Recorder("ffmpeg", "ffmpeg (PulseAudio)", "linux", "ffmpeg -f pulse", "ffmpeg"),
    )
    found = {"pw-record": "/usr/bin/pw-record", "ffmpeg": "/usr/bin/ffmpeg", "whisper-cli": "/x"}
    return DictationService(
        providers(slow=slow),
        app_tasks,
        recorders=rows,
        platform="linux",
        which=which or found.get,
    )


def settle(app: QApplication, seconds: float = 0.05) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)


def save(widget: QWidget, out: Path, name: str, theme: Theme, app: QApplication) -> None:
    settle(app)
    path = out / f"{name}-{theme.name}.png"
    widget.grab().save(str(path), "PNG")
    print(path)


def discard(widget: QWidget) -> None:
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def render(app: QApplication, theme: Theme, out: Path) -> None:
    # The choices are per-user settings: the refused page below picks a provider, and the
    # strip after it must not inherit that pick — nor the previous theme's.
    QSettings().clear()
    apply_theme(app, theme)
    tasks = TaskService()

    # Settings ▸ Dictation: whisper.cpp picked and ready, the recorder Automatic.
    ready = service(tasks)
    page = build_page(ready, None, run_action=lambda _id: None, platform="linux")
    page.resize(*PAGE_SIZE)
    page.show()
    save(page, out, "dictation-settings", theme, app)
    discard(page)

    # The same page with the live provider picked: refused, with the mend beside it.
    refused = service(tasks)
    refused.set_choice("openai_live", "")
    page = build_page(refused, None, run_action=lambda _id: None, platform="linux")
    page.resize(*PAGE_SIZE)
    page.show()
    save(page, out, "dictation-settings-refused", theme, app)
    discard(page)
    QSettings().clear()

    # A prose editor's strip: idle, recording, transcribing, and the words landed.
    slow = service(tasks, slow=1.5)
    field = _Field("Operators sign in with an e-mail address and a one-time code. ")
    section = ProseSection(lambda _id: field, _undo(), "What this step is.", dictation=slow)
    section.resize(*EDITOR_SIZE)
    section.show_target("step")
    section.show()
    cursor = section.edit.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    section.edit.setTextCursor(cursor)
    save(section, out, "dictation-strip-idle", theme, app)
    verb = section.tools.dictation
    assert verb is not None
    verb.toggle()
    settle(app, 0.2)
    save(section, out, "dictation-strip-recording", theme, app)
    verb.toggle()
    settle(app, 0.3)
    save(section, out, "dictation-strip-transcribing", theme, app)
    deadline = time.time() + 10
    while verb.dictation.state() != "idle" and time.time() < deadline:
        settle(app)
    save(section, out, "dictation-strip-landed", theme, app)
    section.dispose()
    discard(section)

    # The microphone greyed with its reason: a build with no provider.
    none = DictationService((), tasks, recorders=(), platform="linux")
    greyed = ProseSection(lambda _id: _Field(""), _undo(), "What this step is.", dictation=none)
    greyed.resize(*EDITOR_SIZE)
    greyed.show_target("step")
    greyed.show()
    save(greyed, out, "dictation-strip-greyed", theme, app)
    greyed.dispose()
    discard(greyed)

    # The API key wizard, after a key was tested.
    dialog = ApiKeyDialog(
        None,
        service="OpenAI",
        guide=KEY_GUIDE,
        keys_url=KEYS_URL,
        placeholder="sk-…",
        tasks=tasks,
        probe=lambda _key: "14 models on the account",
        open_url=lambda _url: None,
        backend_problem=None,
    )
    dialog.resize(*DIALOG_SIZE)
    dialog.show()
    dialog.key.setText("sk-proj-0000000000000000")
    dialog.test()
    deadline = time.time() + 10
    while not dialog.passed and time.time() < deadline:
        settle(app)
    save(dialog, out, "dictation-key-dialog", theme, app)
    discard(dialog)


def _undo():
    from dplanner.framework.undo import UndoService

    return UndoService(None)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--out", type=Path, default=Path("docs/screenshots/f14-dictation"))
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    assert isinstance(app, QApplication)
    # The suite's conftest redirects QSettings for the same reason: the developer's own
    # choices must not leak into a render, nor a render's into their settings.
    with TemporaryDirectory() as tmp:
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tmp)
        for theme in (DARK, LIGHT):
            render(app, theme, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
