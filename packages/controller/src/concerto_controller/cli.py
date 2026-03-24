"""CLI helpers for Concerto controller management."""
from __future__ import annotations

import sys

from alembic import command
from concerto_controller.db.session import _alembic_cfg


def migrate() -> None:
    """Run ``alembic upgrade head`` using the app's configuration."""
    command.upgrade(_alembic_cfg(), "head")


def revision() -> None:
    """Generate a new auto-detected migration revision.

    Usage:  concerto-revision -m "add foo column"
    """
    msg = "new migration"
    if "-m" in sys.argv:
        idx = sys.argv.index("-m")
        if idx + 1 < len(sys.argv):
            msg = sys.argv[idx + 1]

    command.revision(_alembic_cfg(), message=msg, autogenerate=True)


def downgrade() -> None:
    """Downgrade one revision.

    Usage:  concerto-downgrade          (goes back 1)
            concerto-downgrade base     (goes back to empty)
    """
    target = sys.argv[1] if len(sys.argv) > 1 else "-1"
    command.downgrade(_alembic_cfg(), target)
