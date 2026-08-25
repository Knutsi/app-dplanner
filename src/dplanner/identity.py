"""Who this application says it is. **Rewritten by ``scripts/new_app.py`` when you fork.**

One place, because these strings are load-bearing in more ways than they look. ``APP_ID``
picks the ``QSettings`` file, the keyring service name and the Wayland ``app_id`` that a
compositor matches to a ``.desktop`` file; changing it later silently orphans every stored
preference and secret. ``APP_NAME`` is what a person reads.

The framework imports this and nothing else from the package root, so window titles, the
splash, the About box and the secret store all agree without any of them importing the app.
"""

from typing import Final

APP_NAME: Final = "DPlanner"
APP_ID: Final = "dplanner"  # QSettings organisation/application, keyring service, app_id.
APP_DOMAIN: Final = "dplanner.local"
APP_VERSION: Final = "0.1.0"
