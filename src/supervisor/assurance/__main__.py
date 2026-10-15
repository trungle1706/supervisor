"""``python -m supervisor.assurance``: see :mod:`supervisor.assurance.cli`."""

from __future__ import annotations

import sys

from supervisor.assurance.cli import main

if __name__ == "__main__":
    sys.exit(main())
