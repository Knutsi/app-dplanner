"""The "Dictation" settings page: the provider that transcribes, the recorder that listens,
and a button to hear it work — all from presets.

**Sane defaults, options laid out.** Both choices are a dropdown of known rows over an
editable field, the Agent profiles page's shape: picking a provider pre-fills its command or
model, picking a recorder pre-fills its command, and *Automatic* is the first recorder this
machine has. Under each field a status line says what stands in the way — a program not on
PATH, a key not added — with the mend beside it: an *Add API key…* button that runs the
provider's own setup action, a link to where the program comes from. *Try it* is the same
:class:`~dplanner.framework.dictation.Dictation` the microphone on every strip runs, so what
is heard here is what a prose editor would get.
"""

import sys
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.dictation import DictationProvider, Recorder, provider_by_id
from dplanner.framework.dictation import Dictation, DictationService
from dplanner.framework.signalling import Spinner, StatusLine
from dplanner.framework.widgets import caption, captioned, ink_of, note
from dplanner.theme.icons import ICON_SIZE, microphone_icon
from dplanner.theme.tokens import CAPTION_GAP, DIALOG_MARGIN, SECTION_GAP

AUTOMATIC = "Automatic"
NOT_FOUND = "not found"
OS_DICTATION = {
    "darwin": "macOS has dictation of its own: press Fn twice in any field here and speak.",
    "win32": "Windows has dictation of its own: press Win+H in any field here and speak.",
}
RunAction = Callable[[str], None]


def provider_label(provider: DictationProvider) -> str:
    return f"{provider.label} — {', '.join(provider.capabilities())}"


def recorder_label(recorder: Recorder, installed: bool) -> str:
    return recorder.label if installed else f"{recorder.label} — {NOT_FOUND}"


@dataclass
class _Block:
    """A caption over a dropdown, the field it pre-fills, and the line under it."""

    combo: QComboBox
    field_caption: QWidget
    edit: QLineEdit
    status: StatusLine


def _block(page: QWidget, layout: QVBoxLayout, title: str, name: str) -> _Block:
    layout.addWidget(caption(title, page))
    combo = QComboBox(page)
    combo.setObjectName(f"{name}Combo")
    layout.addWidget(combo)
    holder = QWidget(page)
    holder.setObjectName(f"{name}Caption")
    holder_row = QHBoxLayout(holder)
    holder_row.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(holder)
    edit = QLineEdit(page)
    edit.setObjectName(f"{name}Edit")
    layout.addWidget(edit)
    status = StatusLine(page)
    status.setObjectName(f"{name}Status")
    layout.addWidget(status)
    return _Block(combo, holder, edit, status)


def _recaption(block: _Block, title: str, hint: str) -> None:
    layout = block.field_caption.layout()
    assert layout is not None
    while (item := layout.takeAt(0)) is not None:
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)  # Out of the tree now, not on the next turn of the loop.
            widget.deleteLater()
    layout.addWidget(captioned(title, block.field_caption, hint))


def build_page(
    dictation: DictationService,
    parent: QWidget | None,
    *,
    run_action: RunAction,
    platform: str = sys.platform,
) -> QWidget:
    page = QWidget(parent)
    page.setObjectName("DictationSettingsPage")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN)
    layout.setSpacing(CAPTION_GAP)

    # -- Transcription: which provider, and its one text ----------------------------------
    provider = _block(page, layout, "Transcription", "DictationProvider")
    for candidate in dictation.providers:
        provider.combo.addItem(provider_label(candidate), candidate.id)
    setup_row = QHBoxLayout()
    setup_button = QPushButton("Add API key…", page)
    setup_button.setObjectName("DictationSetupButton")
    setup_button.setAutoDefault(False)
    where = QLabel(page)
    where.setObjectName("DictationProviderLink")
    where.setOpenExternalLinks(True)
    setup_row.addWidget(setup_button)
    setup_row.addWidget(where)
    setup_row.addStretch(1)
    layout.addLayout(setup_row)
    layout.addSpacing(SECTION_GAP)

    def current_provider() -> DictationProvider | None:
        return provider_by_id(dictation.providers, str(provider.combo.currentData()))

    def show_provider() -> None:
        """Reflect the service: the picked provider, its text, and what stands in the way."""
        status = dictation.status()
        chosen = status.provider
        provider.combo.blockSignals(True)
        provider.combo.setCurrentIndex(provider.combo.findData(chosen.id) if chosen else -1)
        provider.combo.blockSignals(False)
        if chosen is None:
            provider.edit.setText("")
            provider.edit.setEnabled(False)
            _recaption(provider, "Command", "")
            provider.status.say(status.message, "error")
            setup_button.hide()
            where.hide()
            return
        provider.edit.setEnabled(True)
        if provider.edit.text() != status.text:
            provider.edit.setText(status.text)
        _recaption(provider, chosen.caption, chosen.hint)
        why = chosen.refusal(status.text)
        if why is None:
            provider.status.say(f"Ready — {', '.join(chosen.capabilities())}", "ok")
        else:
            provider.status.say(f"{chosen.label}: {why}", "error")
        setup_button.setVisible(chosen.needs_setup and why is not None)
        where.setVisible(bool(chosen.url))
        where.setText(f'<a href="{chosen.url}">About {chosen.label}</a>')

    def pick_provider(index: int) -> None:
        chosen = provider_by_id(dictation.providers, str(provider.combo.itemData(index)))
        if chosen is not None:
            dictation.set_choice(chosen.id, dictation.texts().get(chosen.id, ""))

    def commit_provider_text() -> None:
        chosen = current_provider()
        if chosen is not None:
            dictation.set_choice(chosen.id, provider.edit.text())

    provider.combo.activated.connect(pick_provider)
    provider.edit.editingFinished.connect(commit_provider_text)

    def mend() -> None:
        chosen = current_provider()
        if chosen is not None and chosen.setup_action:
            run_action(chosen.setup_action)

    setup_button.clicked.connect(mend)

    # -- Recording: which recorder, and its command ---------------------------------------
    recorder = _block(page, layout, "Recording", "DictationRecorder")
    rows = dictation.recorders()
    recorder.combo.addItem(AUTOMATIC, "")
    for row in rows:
        installed = dictation.recorder_refusal(row.command) is None
        recorder.combo.addItem(recorder_label(row, installed), row.command)
    layout.addSpacing(SECTION_GAP)

    def show_recorder() -> None:
        text = dictation.recorder_command()
        if recorder.edit.text() != text:
            recorder.edit.setText(text)
        index = recorder.combo.findData(text) if text else 0
        recorder.combo.blockSignals(True)
        recorder.combo.setCurrentIndex(index if index != -1 else recorder.combo.count() - 1)
        recorder.combo.blockSignals(False)
        automatic = dictation.automatic_recorder()
        row = next((r for r in rows if r.command == text), None)
        hint = row.hint if row is not None else ""
        _recaption(recorder, "Command" if text else "Command — Automatic", hint)
        why = dictation.recorder_refusal(text)
        if why is not None:
            recorder.status.say(f"Cannot record: {why}", "error")
        elif text:
            recorder.status.say(f"Recording with {row.label if row else text.split()[0]}", "ok")
        elif automatic is not None:
            recorder.status.say(f"Recording with {automatic.label}, the first installed", "ok")

    def pick_recorder(index: int) -> None:
        dictation.set_recorder_command(str(recorder.combo.itemData(index) or ""))

    recorder.combo.activated.connect(pick_recorder)
    recorder.edit.editingFinished.connect(
        lambda: dictation.set_recorder_command(recorder.edit.text())
    )
    recorder.combo.addItem("Custom", None)  # Reflects a typed command; picks nothing.

    # -- Try it: the same state machine every microphone runs ---------------------------------
    layout.addWidget(caption("Try it", page))
    trial = Dictation(dictation, page)
    try_row = QHBoxLayout()
    try_button = QPushButton("Dictate a sentence", page)
    try_button.setObjectName("DictationTryButton")
    try_button.setAutoDefault(False)
    try_button.setIcon(microphone_icon(ink_of(page)))
    try_button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
    try_button.clicked.connect(trial.toggle)
    spinner = Spinner(page).attach(try_button)
    heard = StatusLine(page)
    heard.setObjectName("DictationHeard")
    try_row.addWidget(try_button)
    try_row.addWidget(heard, 1)
    layout.addLayout(try_row)
    settled: list[str] = []  # Each utterance's completed transcript.
    interim: list[str] = []  # The deltas of the utterance still being said.

    def on_state(state: str) -> None:
        listening = state in ("recording", "listening")
        try_button.setText("Stop" if listening else "Dictate a sentence")
        if state in ("transcribing", "finishing"):
            spinner.start()
        else:
            spinner.stop()
        if listening:
            settled.clear()
            interim.clear()
            heard.say("Listening — say something, then press Stop.", "busy")
        elif state in ("transcribing", "finishing"):
            heard.say("Writing it down…", "busy")

    def on_heard(text: str, final: bool) -> None:
        if final:
            settled.append(text)
            interim.clear()
        else:
            interim.append(text)
        said = " ".join([*settled, "".join(interim)]).strip()
        heard.say(f"Heard: {said}", "ok" if said else "info")

    trial.state_changed.connect(on_state)
    trial.heard.connect(on_heard)
    trial.refused.connect(lambda why: heard.say(why, "error"))

    aside = OS_DICTATION.get(platform)
    if aside:
        layout.addSpacing(SECTION_GAP)
        layout.addWidget(note(aside, page))
    layout.addStretch(1)

    def show() -> None:
        show_provider()
        show_recorder()
        try_button.setEnabled(dictation.status().ready)

    show()
    unsubscribe = dictation.config_changed.connect(show)
    page.destroyed.connect(lambda: unsubscribe())
    return page
