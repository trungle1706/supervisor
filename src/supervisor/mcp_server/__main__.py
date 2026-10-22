"""``python -m supervisor.mcp_server``: serve POST /mcp alone, or manage connected apps."""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import sys  # noqa: E402

from supervisor.mcp_server.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
