"""Open Project…: the two ways a project gets into a library, as one wizard.

There are exactly two, and they suit different people. Somebody who has just been handed a
**project link** knows nothing about this library yet and should not have to: the link says
which plan repository, which folder in it and which code, and the wizard clones what is
missing. Somebody who already works out of a plan repository wants to **browse** it and
pick — often several projects at once, which is what a shared plan repository is for.

So the first page asks which, and remembers the answer: the link leads on a machine that
has never chosen, and from then on the way that person actually uses opens first. Nothing
else about the pages is shared — each one owns its content, its refusal and the words on
the primary, and this file is the frame that shows one of them at a time.

The wizard **answers, it does not connect**. Both pages end at a
:class:`~dplanner.modules.projects.repos.Joined` on disk, and ``ProjectsModule`` adds them
to the library with the membership origin, off the undo stack — the same rule every other
membership change follows.
"""

from collections.abc import Collection
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.locations import Location, read_locations
from dplanner.domain.plan_repo import read_meta
from dplanner.framework.dialog import DialogFrame
from dplanner.framework.list_rows import DETAIL_ROLE, TwoLineDelegate
from dplanner.framework.tasks import TaskService
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.user_config import get_global, set_global
from dplanner.framework.widgets import caption
from dplanner.modules.projects.browse_page import BrowsePage
from dplanner.modules.projects.link_page import LinkPage
from dplanner.modules.projects.repos import MODULE_ID, Joined, RepositoryServices
from dplanner.modules.projects.repositories_folder import KEPT, clone_policy
from dplanner.modules.projects.repositories_page import RepositoriesPage, missing_repositories
from dplanner.theme.tokens import CAPTION_GAP

# One size for every page: a dialog on screen never resizes itself (shell-ui.md), so the
# chooser's two rows sit at the top of the room the other pages need.
DIALOG_SIZE = (680, 560)
WAY_KEY = "open_project_way"
LINK, BROWSE = "link", "browse"
WAY_ROLE = int(Qt.ItemDataRole.UserRole) + 10

# The two ways in, in the order they are offered. A link is first because it is the only
# one somebody joining a project for the first time can act on.
WAYS: tuple[tuple[str, str, str], ...] = (
    (LINK, "Open a project link", "Paste a link somebody sent you, or open a .dlink file"),
    (
        BROWSE,
        "Browse a plan repository",
        "Pick the projects you work on out of a repository you can reach",
    ),
)

CHOOSE, LINK_PAGE, BROWSE_PAGE, REPOSITORIES_PAGE = 0, 1, 2, 3


class OpenProjectDialog(DialogFrame):
    """A framed wizard: the way in, then the page for it, then — when the projects joined
    work in repositories this machine lacks — the Repositories page asking about each.

    One primary throughout, re-worded per page — *Continue*, then the page's own verb —
    because a wizard has one next step at a time and a second accent button would be a
    second answer to the same question. *Back* joins the footer when there is somewhere to
    go back to and leaves it on the first page, where it would name nothing. The
    Repositories page is reached only from a page's answer, never from Back: what it
    asks about is read off the plan the earlier page put on disk.
    """

    def __init__(
        self,
        services: RepositoryServices,
        tasks: TaskService,
        theme: ThemeService,
        *,
        listed_dirs: Collection[Path],
        listed_ids: Collection[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Open Project", parent, size=DIALOG_SIZE)
        self.setObjectName("OpenProjectDialog")
        self._services = services
        self._joined: list[Joined] = []

        self.choose = QWidget(self.body)
        chooser = QVBoxLayout(self.choose)
        chooser.setContentsMargins(0, 0, 0, 0)
        chooser.setSpacing(CAPTION_GAP)
        chooser.addWidget(caption("How would you like to open a project?", self.choose))
        self.ways = QListWidget(self.choose)
        self.ways.setObjectName("OpenProjectWays")
        self.ways.setItemDelegate(TwoLineDelegate(self.ways))
        for way, label, detail in WAYS:
            item = QListWidgetItem(label)
            item.setData(DETAIL_ROLE, detail)
            item.setData(WAY_ROLE, way)
            self.ways.addItem(item)
        self.ways.itemActivated.connect(lambda _item: self._advance())
        self.ways.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        self.ways.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        chooser.addWidget(self.ways)
        chooser.addStretch(1)
        remembered = str(get_global(MODULE_ID, WAY_KEY, LINK))
        self.ways.setCurrentRow(
            next((row for row, (way, _l, _d) in enumerate(WAYS) if way == remembered), 0)
        )

        self.link = LinkPage(
            services,
            tasks,
            theme,
            listed_dirs=listed_dirs,
            listed_ids=listed_ids,
            parent=self.body,
        )
        self.link.changed.connect(self._revalidate)
        self.link.finished.connect(self._on_finished)
        self.browse = BrowsePage(
            services,
            tasks,
            theme,
            listed_dirs=listed_dirs,
            listed_ids=listed_ids,
            parent=self.body,
        )
        self.browse.changed.connect(self._revalidate)
        self.browse.committed.connect(self._advance)
        self.repositories = RepositoriesPage(services, tasks, parent=self.body)
        self.repositories.changed.connect(self._revalidate)
        self.repositories.finished.connect(self._on_repositories)

        self.pages = QStackedWidget(self.body)
        for page in (self.choose, self.link, self.browse, self.repositories):
            self.pages.addWidget(page)
        self.body_layout.addWidget(self.pages, 1)

        self.back_button = self.add_button("Back", self._back)
        self.back_button.setVisible(False)
        self.add_dismiss()
        self.primary_button = self.set_primary("Continue", self._advance)
        self.show_page(CHOOSE)

    # -- moving between the pages ----------------------------------------------------------

    def way(self) -> str:
        item = self.ways.currentItem()
        return str(item.data(WAY_ROLE)) if item is not None else LINK

    def current_page(self) -> int:
        """Which page is showing. Not ``page`` — the frame's own body widget has that name."""
        return self.pages.currentIndex()

    def _advance(self) -> None:
        """The primary, whatever it says right now: choose a way, or run the page's verb.

        Also what a double-click on a row runs, which is why it re-reads the refusal: an
        activation must not do what a greyed button would refuse to.
        """
        if not self.primary_button.isEnabled():
            return
        page = self.current_page()
        if page == CHOOSE:
            set_global(MODULE_ID, WAY_KEY, self.way())
            self.show_page(LINK_PAGE if self.way() == LINK else BROWSE_PAGE)
            return
        if page == LINK_PAGE:
            self.link.begin()  # Answers through `finished`; the clone takes as long as it takes.
            self._revalidate()
            return
        if page == REPOSITORIES_PAGE:
            self.repositories.begin()
            self._revalidate()
            return
        self.browse.remember()
        self._joined_on_disk([Joined(directory) for directory in self.browse.chosen()])

    def _back(self) -> None:
        self.show_page(CHOOSE)

    def show_page(self, page: int) -> None:
        """Show one of the pages, and re-read the footer from it."""
        self.pages.setCurrentIndex(page)
        self.back_button.setVisible(page not in (CHOOSE, REPOSITORIES_PAGE))
        if page == LINK_PAGE:
            self.link.link_edit.setFocus()  # The one page that opens on something to type.
        self._revalidate()

    def _on_finished(self, ok: bool) -> None:
        joined = self.link.answer()
        if ok and joined is not None:
            self._joined_on_disk([joined])
            return
        self._revalidate()

    def _joined_on_disk(self, joined: list[Joined]) -> None:
        """The projects are on disk: ask about the repositories they work in that this
        machine lacks, or finish when there are none."""
        self._joined = joined
        locations: list[Location] = []
        for join in joined:
            locations += read_locations(read_meta(join.directory).get("locations"))
        missing = missing_repositories(locations, self._services.roles, self._services.checkout_for)
        # Under the kept policy nothing is asked: a verb that needs one of these clones it
        # where DPlanner keeps clones. The page is for the developer who wants to say
        # *use a checkout I have* before anything lands in their folder.
        if not missing or clone_policy() == KEPT:
            self.accept()
            return
        self.repositories.show_missing(missing, self._services.roles)
        self.show_page(REPOSITORIES_PAGE)

    def _on_repositories(self, ok: bool) -> None:
        if ok:
            recorded = self.repositories.recorded()
            self._joined = [
                Joined(join.directory, recorded) if index == 0 else join
                for index, join in enumerate(self._joined)
            ]
            self.accept()
            return
        self._revalidate()

    # -- what the footer says ---------------------------------------------------------------

    def _revalidate(self) -> None:
        """The footer is the current page's: its verb on the primary, its refusal beside it.
        Both pages answer the same two questions, so there is no branch past which one."""
        page = self.current_page()
        if page == CHOOSE:
            self.primary_button.setText("Continue")
            self.refuse(None)
            return
        current: LinkPage | BrowsePage | RepositoriesPage = (
            self.link
            if page == LINK_PAGE
            else self.repositories
            if page == REPOSITORIES_PAGE
            else self.browse
        )
        self.primary_button.setText(current.primary_text())
        self.refuse(current.refusal())

    # -- the answer -------------------------------------------------------------------------

    def joined(self) -> list[Joined]:
        return self._joined
