"""Lifecycle task list (WP30, ADR D30; docs/controls.md).

A right-sized set of tasks per agent, by lifecycle stage, sized by the Decision 33 class and the
risk level. The lifecycle move is itself a task and the launch gate refuses GO while a required
task of the current stage is open. Off by default (CONTROLS_ENABLED).
"""

from supervisor.tasks.model import (
    CLASSES,
    LEVELS,
    STAGES,
    STATUSES,
    TaskError,
)

__all__ = ["CLASSES", "LEVELS", "STAGES", "STATUSES", "TaskError"]
