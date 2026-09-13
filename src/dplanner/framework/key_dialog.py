"""Adding a service's API key: one guided modal, and nothing stored until it worked.

A provider module — OpenAI, Anthropic, whoever is next — owns a key and a page where it can
be pasted, but a bare password field is a lookup pushed onto the person: where does a key
come from, what does it look like, did I paste the right one. This dialog is the walk
through it, the shape the Confluence Connect dialog set: a sentence saying where the key
is made and a button that opens that page, the field, *Test* on a task runner with the
service's own probe turning the button's glyph, and *Save* refused with its reason until
the test passed. The key goes to the keychain only then, and a machine whose keychain
cannot keep it is told so up front rather than after typing.

The dialog knows no service: the words, the address, the probe and what saving means are
the module's, handed in. That is what lets every vendor module offer the same act.
"""

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtCore import Signal as QtSignal
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QWidget

from dplanner.framework.dialog import DialogFrame
from dplanner.framework.signalling import Spinner
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.framework.widgets import captioned, ink_of, note
from dplanner.theme.icons import ICON_SIZE, connect_icon, external_icon

KEY_HINT = "Kept in this computer's keychain, never in the plan and never in a file."
# The probe's answer: what the key could reach, in the service's words ("14 models").
Probe = Callable[[str], str]


class ApiKeyDialog(DialogFrame):
    """Ask for one service's API key, prove it, and hand it back once it worked."""

    _probed = QtSignal(str, str)  # (what the key could reach, error) — worker → GUI.

    def __init__(
        self,
        parent: QWidget | None,
        *,
        service: str,
        guide: str,
        keys_url: str,
        placeholder: str,
        tasks: TaskService,
        probe: Probe,
        open_url: Callable[[str], None],
        backend_problem: str | None,
        current: str = "",
    ) -> None:
        super().__init__(f"Add {service} API Key", parent)
        self.setObjectName("ApiKeyDialog")
        self.setModal(True)
        self._probe = probe
        self._runner = TaskRunner(tasks, parent=self)
        self._probed.connect(self._on_probed)
        self._passed = False
        self._problem = backend_problem

        body, layout = self.body, self.body_layout
        layout.addWidget(note(guide, body))

        self.open_keys = QPushButton(f"Open {service} API Keys in Browser", body)
        self.open_keys.setObjectName("openKeysPage")
        self.open_keys.setIcon(external_icon(ink_of(body).name()))
        self.open_keys.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.open_keys.setAutoDefault(False)
        self.open_keys.clicked.connect(lambda: open_url(keys_url))
        layout.addWidget(self.open_keys, 0, Qt.AlignmentFlag.AlignLeft)

        layout.addWidget(captioned("API key", body, KEY_HINT))
        self.key = QLineEdit(current, body)
        self.key.setObjectName("ApiKeyEdit")
        self.key.setPlaceholderText(placeholder)
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.key)

        row = QHBoxLayout()
        layout.addLayout(row)
        # The glyph is the slot the Spinner turns in while the probe runs.
        self.test_button = QPushButton("Test Key", body)
        self.test_button.setObjectName("testKey")
        self.test_button.setIcon(connect_icon(ink_of(body)))
        self.test_button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.test_button.setAutoDefault(False)
        self.test_button.clicked.connect(self.test)
        row.addWidget(self.test_button)
        row.addStretch(1)
        self._spinner = Spinner(self).attach(self.test_button)
        layout.addStretch(1)

        self.add_dismiss()
        self.save = self.set_primary("Save", self.accept)
        self.key.textChanged.connect(self._invalidate)
        self._invalidate()
        if backend_problem is not None:
            self.test_button.setEnabled(False)
            self.refuse(f"Cannot store a key on this machine: {backend_problem}")

    def value(self) -> str:
        return self.key.text().strip()

    @property
    def passed(self) -> bool:
        """Whether the last test reached the service with the key as it is now."""
        return self._passed

    # -- internals -------------------------------------------------------------------------------

    def _invalidate(self) -> None:
        """An edit undoes the test: the primary goes back to refused, with its reason."""
        self._passed = False
        if self._problem is not None:
            return  # The keychain refusal already standing says something truer.
        # A blank field is refused with no words — blank is plain to see; filled and
        # untested is the state that needs a sentence.
        self.refuse("Test the key first" if self.value() else "")

    def test(self) -> None:
        key = self.value()
        if not key:
            self.refuse("Paste the key first")
            return
        probe, probed = self._probe, self._probed

        def body() -> None:  # Worker thread: the key and nothing else.
            try:
                probed.emit(probe(key), "")
            except Exception as error:  # The service's own refusal, reported not raised.
                probed.emit("", str(error) or type(error).__name__)

        if self._runner.run("Testing the API key", body, key="api_key.test"):
            self.test_button.setEnabled(False)
            self._spinner.start()
            self.refuse("")
            self.status.say("Asking the service…", "busy")

    def _on_probed(self, reached: str, error: str) -> None:
        self._spinner.stop()
        self.test_button.setEnabled(True)
        self._passed = not error and self._problem is None
        if error:
            self.refuse(error)
            self.status.say(error, "error")
            return
        self.refuse(
            None if self._passed else f"Cannot store a key on this machine: {self._problem}"
        )
        if self._passed:
            self.status.say(f"The key works — {reached}.", "ok")
