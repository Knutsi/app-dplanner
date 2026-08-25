"""The Qt-free bottom layer: storage, persistence contracts and the signal primitive.

Nothing in here knows what your application is about. ``core/`` is given to you by the
template and is the same in every application built from it; your model lives one layer up
in :mod:`dplanner.domain`, and everything Qt lives in :mod:`dplanner.framework`.

The split is enforced: ``tests/test_architecture.py`` fails the build if anything in here
imports Qt, your domain, the framework or a module. That is what keeps the storage
providers swappable — a provider that cannot see your model cannot grow a dependency on it.
"""

from dplanner.core.signals import Signal

__all__ = ["Signal"]
