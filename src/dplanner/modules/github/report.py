"""What the GitHub refs say in a report: the pull request and the branch a step lands in.

The repository slug is the code repository the project records (its primary code location),
else — the older, colocated shape — the plan directory's own origin, derived from the
module's file area; the same answer ``dplanner github`` and the GitHub tab give.

Qt-free by rule — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

from datetime import date

from dplanner.cli.report.parts import Contribution, Facet, ReportSource
from dplanner.core.storage.locations import find_repo_root, origin_url
from dplanner.domain.locations import primary_code
from dplanner.domain.model import Library, Project
from dplanner.domain.store import FilesFor
from dplanner.modules.github.aspect import MODULE_ID, branch_url, pr_label, pr_url, read
from dplanner.modules.github.gh import parse_repo


def report_source() -> ReportSource:
    def source(_library: Library, project: Project, files: FilesFor, _day: date) -> Contribution:
        facets = {}
        repo: str | None = None
        for step in project.steps:
            refs = read(step)
            if refs is None:
                continue
            if repo is None:
                # The code repository the project records; else — the older shape — the
                # plan's own origin, as `dplanner github` and the GitHub tab read it.
                root = find_repo_root(files(project.id, MODULE_ID).absolute(""))
                primary = primary_code(project.locations)
                url = (
                    primary.repository
                    if primary is not None
                    else origin_url(root)
                    if root is not None
                    else ""
                )
                repo = parse_repo(url) or ""
            found = []
            if refs.pr_number is not None or refs.pr_url:
                words = pr_label(refs)
                if refs.pr_state:
                    words += f" · {refs.pr_state}"
                if refs.pr_title:
                    words += f" · {refs.pr_title}"
                url = pr_url(refs, repo or None)
                found.append(Facet("Pull request", words, kind="link" if url else "text", url=url))
            if refs.branch:
                url = branch_url(refs, repo or None)
                found.append(Facet("Branch", refs.branch, kind="link" if url else "text", url=url))
            if found:
                facets[step.id] = tuple(found)
        return Contribution(facets=facets)

    return source
