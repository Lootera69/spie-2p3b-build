"""Guarded entry point: ``python -m tools.policy_train [build|--check|report]``.

The guard mirrors ``tools.conceptnet_build``: corpus generation runs ``invent`` and the MAP-Elites
search, which the certify gate may fan out across processes on Windows (spawn re-imports the entry
module), so a bare top-level ``main()`` call would re-run the build in every worker.
"""

from __future__ import annotations

import sys

from .build import main

if __name__ == "__main__":
    sys.exit(main())
