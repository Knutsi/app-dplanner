"""``python -m dplanner`` — the same entry point as the console script."""

import sys

from dplanner.entry import main

if __name__ == "__main__":
    sys.exit(main())
