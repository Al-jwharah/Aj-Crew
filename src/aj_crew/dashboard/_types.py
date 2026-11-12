"""Shared TYPE_CHECKING imports for dashboard modules."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aj_crew.context import ContextBuilder
    from aj_crew.cron import CronService
    from aj_crew.history import ConversationLog, HistoryConsolidator
    from aj_crew.learn import LessonStore
    from aj_crew.session import SessionManager
    from aj_crew.subagent import SubagentManager
    from aj_crew.taskrunner import TaskRunner

__all__ = [
    "ContextBuilder",
    "CronService",
    "ConversationLog",
    "HistoryConsolidator",
    "LessonStore",
    "SessionManager",
    "SubagentManager",
    "TaskRunner",
]
