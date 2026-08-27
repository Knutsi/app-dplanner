"""The GitHub aspect: the branch and pull request a step's work lands in.

A step carries one branch ref and one PR ref, recorded by whoever does the work — a
window's GitHub tab or ``dplanner github``. Recording is plain strings and never needs
GitHub; the ``gh`` CLI, when it is installed, powers the extras: pickers listing the
repository's branches and PRs, and a background refresh keeping each stored PR's
last-seen state current.

This file stays a docstring on purpose: re-exporting the Qt half here would make the
package's Qt-free files unreachable without loading Qt.
"""
