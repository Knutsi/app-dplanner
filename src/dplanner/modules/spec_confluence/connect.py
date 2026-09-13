"""The guided Connect dialog: where the token comes from, a test that proves it reads
the page, and nothing stored until the test passed.

The token field never logs, never echoes, and never leaves this dialog except into the
secret store the module hands over. *Test connection* runs the probe on a
:class:`~dplanner.framework.task_runner.TaskRunner` — the one threading shell — so the
dialog stays live while Confluence answers, and the primary is enabled by the answer
alone. A machine whose keychain cannot keep a secret is told so up front and the dialog
refuses to store; a plaintext file is never the fallback.

It is a :class:`~dplanner.framework.dialog.DialogFrame`: the guide and the fields are the
body, the answer stands in the footer's status slot, and the primary is *refused with its
reason* rather than silently dead — DESIGN.md's *Dialogs*. The button that starts the
probe turns its own glyph while it runs, so nothing beside the words moves.
"""

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtCore import Signal as QtSignal
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QWidget

from dplanner.domain.document_source import SourceUnavailableError
from dplanner.framework.dialog import DialogFrame
from dplanner.framework.signalling import Spinner
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.framework.widgets import captioned, ink_of, note
from dplanner.modules.spec_confluence.client import Credentials
from dplanner.theme.icons import ICON_SIZE, connect_icon, external_icon

TOKENS_URL = "https://id.atlassian.com/manage-profile/security/api-tokens"

GUIDE = (
    "1. Open Atlassian's API tokens page (the button below) and create an API token — a "
    "classic one; tokens with scopes are not yet supported here. Tokens expire within a "
    "year, so you will be back on this page one day; DPlanner reads only, and this token "
    "is the only thing it needs.\n"
    "2. Paste the token here with the email of the Atlassian account it belongs to.\n"
    "3. Test the connection. The token is kept in this computer's keychain — never in the "
    "plan, never in a file — once the test passes."
)

TOKEN_HINT = "Kept in this computer's keychain, never in the plan and never in a file."


class ConnectDialog(DialogFrame):
    """Ask for an Atlassian account's email and API token for one site, and prove them."""

    _probed = QtSignal(str, str)  # (what the credentials could read, error) — worker → GUI.

    def __init__(
        self,
        parent: QWidget | None,
        site: str,
        *,
        tasks: TaskService,
        probe: Callable[[Credentials], str],
        open_url: Callable[[str], None],
        backend_problem: str | None,
        email: str = "",
    ) -> None:
        super().__init__("Connect to Confluence", parent)
        self.setObjectName("SourceConnectDialog")
        self.setModal(True)
        self._probe = probe
        self._runner = TaskRunner(tasks, parent=self)
        self._probed.connect(self._on_probed)
        self._passed = False

        body, layout = self.body, self.body_layout
        layout.addWidget(note(GUIDE, body))

        self.open_tokens = QPushButton("Open Atlassian API Tokens in Browser", body)
        self.open_tokens.setObjectName("openTokensPage")
        self.open_tokens.setIcon(external_icon(ink_of(body).name()))
        self.open_tokens.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.open_tokens.setAutoDefault(False)
        self.open_tokens.clicked.connect(lambda: open_url(TOKENS_URL))
        layout.addWidget(self.open_tokens, 0, Qt.AlignmentFlag.AlignLeft)

        self.site = self._field(body, "Site", site)
        self.site.setReadOnly(True)
        self.email = self._field(body, "Email", email, placeholder="you@example.com")
        self.email.setObjectName("ConfluenceEmailEdit")
        self.token = self._field(
            body, "API token", "", placeholder="the API token, pasted", hint=TOKEN_HINT
        )
        self.token.setObjectName("ConfluenceTokenEdit")
        self.token.setEchoMode(QLineEdit.EchoMode.Password)

        row = QHBoxLayout()
        layout.addLayout(row)
        # The glyph is not decoration: it is the slot the Spinner turns in while the
        # probe runs, so nothing beside the words moves.
        self.test_button = QPushButton("Test Connection", body)
        self.test_button.setObjectName("testConnection")
        self.test_button.setIcon(connect_icon(ink_of(body)))
        self.test_button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.test_button.setAutoDefault(False)
        self.test_button.clicked.connect(self._test)
        row.addWidget(self.test_button)
        row.addStretch(1)
        self._spinner = Spinner(self).attach(self.test_button)
        layout.addStretch(1)

        self.add_dismiss()
        self.ok = self.set_primary("Connect", self.accept)

        self._problem = backend_problem
        for edit in (self.email, self.token):
            edit.textChanged.connect(self._invalidate)
        self._invalidate()
        if backend_problem is not None:
            self.test_button.setEnabled(False)
            self.refuse(f"Cannot store a token on this machine: {backend_problem}")

    def credentials(self) -> Credentials:
        return Credentials(email=self.email.text().strip(), token=self.token.text().strip())

    @property
    def passed(self) -> bool:
        """Whether the last test read the page with the credentials as they are now."""
        return self._passed

    # -- internals -------------------------------------------------------------------------------

    def _field(
        self, body: QWidget, title: str, text: str, *, placeholder: str = "", hint: str = ""
    ) -> QLineEdit:
        self.body_layout.addWidget(captioned(title, body, hint))
        edit = QLineEdit(text, body)
        edit.setPlaceholderText(placeholder)
        self.body_layout.addWidget(edit)
        return edit

    def _invalidate(self) -> None:
        """An edit undoes the test: the primary goes back to refused, with its reason."""
        self._passed = False
        if self._problem is not None:
            return  # The keychain refusal already standing says something truer.
        # Blank fields are refused with no words — blank is plain to see; filled and
        # untested is the state that needs a sentence.
        self.refuse("Test the connection first" if self._ready() else "")

    def _ready(self) -> bool:
        return bool(self.email.text().strip() and self.token.text().strip())

    def _test(self) -> None:
        if not self._ready():
            self.refuse("Both the email and the token are needed.")
            return
        probe, probed = self._probe, self._probed

        def body() -> None:  # Worker thread: the credentials and nothing else.
            try:
                probed.emit(probe(credentials), "")
            except SourceUnavailableError as error:
                probed.emit("", str(error))

        credentials = self.credentials()
        if self._runner.run("Testing the Confluence connection", body, key="confluence.test"):
            self.test_button.setEnabled(False)
            self._spinner.start()
            self.refuse("")
            self.status.say("Reading the page…", "busy")

    def _on_probed(self, title: str, error: str) -> None:
        self._spinner.stop()
        self.test_button.setEnabled(True)
        self._passed = not error and self._problem is None
        if error:
            # Every word of it may be the site's; StatusLine escapes what it shows.
            self.refuse(error)
            self.status.say(error, "error")
            return
        self.refuse(
            None if self._passed else f"Cannot store a token on this machine: {self._problem}"
        )
        if self._passed:
            self.status.say(f"Connected — this account can read “{title}”.", "ok")
