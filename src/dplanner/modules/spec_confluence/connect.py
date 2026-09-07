"""The guided Connect dialog: where the token comes from, a test that proves it reads
the page, and nothing stored until the test passed.

The token field never logs, never echoes, and never leaves this dialog except into the
secret store the module hands over. *Test connection* runs the probe on a
:class:`~dplanner.framework.task_runner.TaskRunner` — the one threading shell — so the
dialog stays live while Confluence answers, and OK is enabled by the answer alone. A
machine whose keychain cannot keep a secret is told so up front and the dialog refuses
to store; a plaintext file is never the fallback.
"""

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtCore import Signal as QtSignal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.document_source import SourceUnavailableError
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.modules.spec_confluence.client import Credentials

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


class ConnectDialog(QDialog):
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
        super().__init__(parent)
        self.setObjectName("SourceConnectDialog")
        self.setWindowTitle("Connect to Confluence")
        self.setModal(True)
        self._probe = probe
        self._runner = TaskRunner(tasks, parent=self)
        self._probed.connect(self._on_probed)
        self._passed = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        guide = QLabel(GUIDE, self)
        guide.setObjectName("InspectorNote")
        guide.setWordWrap(True)
        guide.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(guide)

        self.open_tokens = QPushButton("Open Atlassian API Tokens in Browser", self)
        self.open_tokens.setObjectName("openTokensPage")
        self.open_tokens.clicked.connect(lambda: open_url(TOKENS_URL))
        layout.addWidget(self.open_tokens, 0, Qt.AlignmentFlag.AlignLeft)

        form = QFormLayout()
        self.site = QLineEdit(site, self)
        self.site.setReadOnly(True)
        form.addRow("Site", self.site)
        self.email = QLineEdit(email, self)
        self.email.setObjectName("ConfluenceEmailEdit")
        self.email.setPlaceholderText("you@example.com")
        form.addRow("Email", self.email)
        self.token = QLineEdit(self)
        self.token.setObjectName("ConfluenceTokenEdit")
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setPlaceholderText("the API token, pasted")
        form.addRow("API token", self.token)
        layout.addLayout(form)

        row = QHBoxLayout()
        self.test_button = QPushButton("Test Connection", self)
        self.test_button.setObjectName("testConnection")
        self.test_button.clicked.connect(self._test)
        row.addWidget(self.test_button)
        self.status = QLabel(self)
        self.status.setObjectName("InspectorNote")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)  # Every word may be the site's.
        row.addWidget(self.status, 1)
        layout.addLayout(row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        self.ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setObjectName("PrimaryButton")
        self.ok.setText("Connect")
        self.ok.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._problem = backend_problem
        if backend_problem is not None:
            self.status.setText(f"Cannot store a token on this machine: {backend_problem}")
            self.test_button.setEnabled(False)
        for edit in (self.email, self.token):
            edit.textChanged.connect(self._invalidate)

    def credentials(self) -> Credentials:
        return Credentials(email=self.email.text().strip(), token=self.token.text().strip())

    @property
    def passed(self) -> bool:
        """Whether the last test read the page with the credentials as they are now."""
        return self._passed

    def _invalidate(self) -> None:
        self._passed = False
        self.ok.setEnabled(False)

    def _test(self) -> None:
        credentials = self.credentials()
        if not credentials.email or not credentials.token:
            self.status.setText("Both the email and the token are needed.")
            return
        probe, probed = self._probe, self._probed

        def body() -> None:  # Worker thread: the credentials and nothing else.
            try:
                probed.emit(probe(credentials), "")
            except SourceUnavailableError as error:
                probed.emit("", str(error))

        if self._runner.run("Testing the Confluence connection", body, key="confluence.test"):
            self.test_button.setEnabled(False)
            self.status.setText("Testing…")

    def _on_probed(self, title: str, error: str) -> None:
        self.test_button.setEnabled(True)
        if error:
            self.status.setText(error)
            self._invalidate()
            return
        self.status.setText(f"Connected — this account can read “{title}”.")
        self._passed = self._problem is None
        self.ok.setEnabled(self._passed)
