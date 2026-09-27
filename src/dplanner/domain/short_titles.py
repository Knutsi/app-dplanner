"""What a project is called where its whole title is too heavy: a tab's label.

*DPlanner changes 2* is **DC2** and *Dermatology module* is **DM** — a word's first letter,
a number whole. A one-word title is already as short as it can be said, so it stays whole.

**Unique against the siblings, so derived and never stored.** Two titles with the same
initials grow letters of their first word until they part (*DerM*, *DelM*), and a pair that
growing cannot part (*Dermatology module*, *Dermatology mapping*) keeps its whole titles.
Renaming one project can therefore change another's short title, which is why a tab reads
it afresh on every project rename rather than holding it.
"""

import re
from collections import Counter
from collections.abc import Sequence

from dplanner.domain.model import Project, ProjectId

UNTITLED = "Untitled project"


def short_titles(projects: Sequence[Project]) -> dict[ProjectId, str]:
    """Every project's short title, no two alike (ignoring case) unless their whole titles
    are."""
    words = {project.id: re.findall(r"[^\W_]+", project.title) for project in projects}
    whole = {project.id: project.title or UNTITLED for project in projects}
    letters = dict.fromkeys(whole, 1)  # How much of the first word each abbreviation takes.
    while True:
        labels = {pid: _abbreviated(words[pid], letters[pid]) or whole[pid] for pid in whole}
        clashes = Counter(label.casefold() for label in labels.values())
        growing = [
            pid
            for pid, label in labels.items()
            if clashes[label.casefold()] > 1 and label != whole[pid]
        ]
        if not growing:
            return labels
        for pid in growing:
            letters[pid] += 1


def _abbreviated(words: Sequence[str], letters: int) -> str:
    """The initials of two words or more, the first word ``letters`` long — or "" when there
    is nothing to abbreviate, or the first word has no more letters to give."""
    if len(words) < 2:
        return ""
    first = words[0]
    if letters > 1 and (first.isdigit() or letters > len(first)):
        return ""
    head = first if first.isdigit() else first[0].upper() + first[1:letters]
    return head + "".join(word if word.isdigit() else word[0].upper() for word in words[1:])
