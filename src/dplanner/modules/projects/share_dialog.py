"""Share Project…: the link that sets this project up on somebody else's machine.

One artefact, three ways to hand it over — copied as a line, saved as a ``.dlink`` file,
or scanned off the screen — because the way a person passes something on is whatever is
open in front of them. All three carry the same :class:`~dplanner.domain.project_link.
ProjectLink`; the dialog only shows it.

**The sentence under the link is part of the feature.** A link that looks like a share
link is easy to mistake for an invitation, and this one grants nothing: it says where the
repositories are, and the person opening it still needs access to both. Saying so here is
cheaper than the message that would otherwise arrive an hour later.
"""

from pathlib import Path

import segno
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPaintEvent
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLineEdit, QWidget

from dplanner.core.fsio import write_atomic
from dplanner.domain.project_link import ROOT, SUFFIX, ProjectLink, document_text, encode
from dplanner.framework.dialog import DialogFrame
from dplanner.framework.widgets import block, caption, note
from dplanner.modules.projects.repos import shown_path

MIN_WIDTH = 540  # The link is shown in full, and two repository URLs want the room.
# The QR square's preferred side; the module size is derived from it, so the code is always
# a whole number of pixels per module and never resampled.
QR_TARGET = 216
# Modules of margin around the code. Four is what the QR specification asks for, and a
# scanner that finds nothing is usually looking at one drawn without it.
QUIET = 4


class QrCode(QWidget):
    """A link as a square of modules, painted from segno's matrix.

    **Dark on light whatever the theme.** Every other surface here takes its colours from
    the theme; this one may not, because the picture is not chrome — it is data a camera
    has to read, and an inverted code is a code some scanners refuse. So the square carries
    its own white ground, and the dialog's ground stops at its edge.
    """

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("QrCode")
        self.matrix = [bytes(row) for row in segno.make(text, error="m").matrix]
        across = len(self.matrix) + 2 * QUIET
        self.module = max(1, round(QR_TARGET / across))
        self.setFixedSize(across * self.module, across * self.module)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt's name
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("white"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("black"))
        size = self.module
        for row, modules in enumerate(self.matrix):
            for column, on in enumerate(modules):
                if on:
                    painter.drawRect((column + QUIET) * size, (row + QUIET) * size, size, size)


class ShareProjectDialog(DialogFrame):
    """A fit dialog: what the link sets up, the link itself, and the same link as a code.

    *Copy Link* is the primary — it is what the person came for — and *Save File…* the
    quiet secondary beside Close. What each did is said in the footer's status slot rather
    than in a box the person then has to dismiss.
    """

    def __init__(self, link: ProjectLink, parent: QWidget | None = None) -> None:
        super().__init__(f"Share “{link.name}”", parent)
        self.setObjectName("ShareProjectDialog")
        self.setMinimumWidth(MIN_WIDTH)
        self.link = link
        self.text = encode(link)
        body, layout = self.body, self.body_layout

        self.about = note(_what_it_does(link), body)
        self.about.setWordWrap(True)
        layout.addWidget(self.about)

        self.link_edit = QLineEdit(self.text, body)
        self.link_edit.setObjectName("ShareLinkEdit")
        self.link_edit.setReadOnly(True)
        # Click to select it by hand if you want to; the first stop is *Copy Link*, which
        # is what the dialog was opened for (DESIGN.md's *Bringing a surface up*, 7).
        self.link_edit.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.link_edit.setCursorPosition(0)
        block(layout, caption("Link", body), self.link_edit)

        self.code = QrCode(self.text, body)
        row = QHBoxLayout()  # Joined before it is filled — CLAUDE.md's layout rules.
        layout.addLayout(row)
        row.addStretch(1)
        row.addWidget(self.code)
        row.addStretch(1)

        self.save_button = self.add_button("Save File…", self._save)
        self.add_dismiss("Close")
        self.copy_button = self.set_primary("Copy Link", self._copy)

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.text)
        self.status.say("Link copied — paste it wherever you would send a URL", "ok")

    def _save(self) -> None:
        start = Path.home() / self.link.filename
        chosen = QFileDialog.getSaveFileName(
            self, "Save Project Link", str(start), f"DPlanner project links (*{SUFFIX})"
        )[0]
        if not chosen:
            return
        path = Path(chosen)
        if path.suffix != SUFFIX:
            path = path.with_suffix(SUFFIX)
        try:
            write_atomic(path, document_text(self.link))
        except OSError as error:
            self.status.say(f"{path.name} was not written — {error}", "error")
            return
        self.status.say(f"Saved to {shown_path(path)}", "ok")


def _what_it_does(link: ProjectLink) -> str:
    """The sentence over the link: what opening it does, and what it does not give."""
    where = f"“{link.name}” from {link.plan_label}"
    if link.plan_path != ROOT:
        where += f" · {link.plan_path}"
    code = f", with {link.code_label} as its code" if link.code_remote else ""
    return (
        f"Whoever opens this sets up {where}{code}. It carries no access — they need it "
        "on those repositories already."
    )
