"""Debug ▸ Design Examples ▸ Modal: a DialogFrame carrying a form, the sample table and every
signalling state.
"""

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLineEdit,
    QProgressBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.framework.debounce import Debounced, DebounceService
from dplanner.framework.dialog import DialogFrame
from dplanner.framework.notices import Notice, NoticeBar
from dplanner.framework.signalling import Spinner, StatusLine, UpdatingIndicator
from dplanner.framework.table import Table
from dplanner.framework.widgets import captioned, ink_of, note
from dplanner.modules.debug.design_sample import COLUMNS, DEMO_DELAY_MS, fill_sample
from dplanner.theme.icons import (
    ICON_SIZE,
    spark_icon,
)
from dplanner.theme.tokens import CAPTION_GAP, FIELD_GAP


class DesignExampleDialog(DialogFrame):
    """The modal: a form, a table and every signalling state on one frame."""

    def __init__(self, debounce: DebounceService, parent: QWidget | None = None) -> None:
        super().__init__("Design Example", parent, size=(760, 760))
        body = self.body_layout

        form = QVBoxLayout()
        form.setSpacing(CAPTION_GAP)
        body.addLayout(form)  # Added before it is filled: a parentless layout leaks items.
        form.addWidget(
            captioned("Name", self.body, "A step's name is what its card shows; the key is dealt.")
        )
        self.name = QLineEdit("Build the modal", self.body)
        form.addWidget(self.name)
        form.addSpacing(FIELD_GAP)
        form.addWidget(captioned("Branch", self.body))
        self.branch = QLineEdit("agent/f7-build-the-modal", self.body)
        form.addWidget(self.branch)
        self.problem = StatusLine(self.body)
        self.problem.say("A branch of that name already exists on the remote", "error")
        form.addWidget(self.problem)
        form.addSpacing(FIELD_GAP)
        form.addWidget(captioned("Summary", self.body))
        self.summary = QLineEdit(self.body)
        self.summary.setPlaceholderText("What this step delivers (optional)")
        form.addWidget(self.summary)

        body.addWidget(captioned("Steps", self.body))
        self.table = Table(COLUMNS, parent=self.body)
        fill_sample(self.table, ink_of(self.body))
        body.addWidget(self.table, 1)

        signals = QVBoxLayout()
        signals.setSpacing(CAPTION_GAP)
        body.addLayout(signals)
        signals.addWidget(captioned("Signalling", self.body))
        strip = QHBoxLayout()
        strip.setSpacing(FIELD_GAP)
        signals.addLayout(strip)
        # A button that starts work carries a glyph, and the glyph turns while the work
        # runs: the slot is always there, so nothing moves.
        self.change_button = QToolButton(self.body)
        self.change_button.setObjectName("ToolbarButton")
        self.change_button.setText("Change something")
        self.change_button.setIcon(spark_icon(ink_of(self.body)))
        self.change_button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.change_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        strip.addWidget(self.change_button)
        strip.addStretch(1)
        self.updating = UpdatingIndicator(self.body)
        strip.addWidget(self.updating)
        self._recompute_soon = Debounced(
            self._recompute, DEMO_DELAY_MS, parent=self, service=debounce
        )
        self.updating.follow(self._recompute_soon)
        self.spinner = Spinner(self.body).attach(self.change_button)
        self.spinner.follow(self._recompute_soon)
        self.change_button.clicked.connect(self._recompute_soon.trigger)
        self.lines = [StatusLine(self.body) for _ in range(5)]
        for line, (words, tone) in zip(
            self.lines,
            (
                ("12 pages, fetched today", "info"),
                ("Reading the repository…", "busy"),
                ("Connected — this account can read the space", "ok"),
                ("An agent is rewriting this step — leave it be", "warn"),
                ("gh is not installed — branches and PRs are typed, not picked", "error"),
            ),
            strict=True,
        ):
            line.say(words, tone)  # type: ignore[arg-type]
            signals.addWidget(line)
        signals.addWidget(note("Publishing 2 of 5 repositories", self.body))
        self.progress = QProgressBar(self.body)
        self.progress.setRange(0, 5)
        self.progress.setValue(2)
        self.progress.setTextVisible(False)
        signals.addWidget(self.progress)
        # Standing notices: a fact that holds until it stops holding. In the application
        # this bar sits over the whole window's content (framework/main_window.py) — it is
        # here so the two shapes can be compared with the lines above them. Two: the one
        # band every agent at work shares, filled by everything they counted and opening
        # the list of them on a click, and a fact that is owed.
        self.notices = NoticeBar(self.body)
        self.notices.show_notice(
            Notice(
                id="demo.agents",
                words="2 agents are at work on Payments · S3, S7",
                tone="warn",
                busy=True,
                fraction=0.4,
                action="Clear",
                open=lambda: None,
                open_tip="Show every agent at work",
            )
        )
        self.notices.show_notice(
            Notice(
                id="demo.conflict",
                words="2 entries changed here and outside — this window is not saving"
                " until settled",
                tone="error",
                action="Settle…",
            )
        )
        signals.addWidget(self.notices)
        self.refuse_switch = QCheckBox(
            "Refuse the primary, with the reason in the footer", self.body
        )
        self.refuse_switch.toggled.connect(
            lambda on: self.refuse("Pick a repository first" if on else None)
        )
        signals.addWidget(self.refuse_switch)

        self.add_button("Delete Sample", self._delete, destructive=True)
        self.add_dismiss()
        self.set_primary("Apply", self.accept)

    def _recompute(self) -> None:
        fill_sample(self.table, ink_of(self.body))

    def _delete(self) -> None:
        self.status.say("Nothing was deleted — this is sample data", "info")
