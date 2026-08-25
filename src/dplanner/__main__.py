"""``python -m dplanner`` — the same entry point as the console script."""

import sys

from dplanner.app import main

if __name__ == "__main__":
    sys.exit(main())
