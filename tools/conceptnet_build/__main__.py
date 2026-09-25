"""Guarded entry point: ``python -m tools.conceptnet_build [options]``.

The ``if __name__ == "__main__"`` guard is load-bearing, not ceremonial: the certify gate fans out
over a :class:`~concurrent.futures.ProcessPoolExecutor`, and on Windows (this project's platform)
new workers start via *spawn*, re-importing the entry module. Without the guard each worker would
re-run the build, forking endlessly.
"""

from __future__ import annotations

import sys

from .build import main

if __name__ == "__main__":
    sys.exit(main())
