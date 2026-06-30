"""
Execution log events for the Research Agent.

These mirror the `log_event_type` / `log_level` ENUMs from schema.sql
exactly, and are returned as plain data from ResearchAgent.execute() --
this agent never writes to Postgres itself (same boundary as everywhere
else: agents are infrastructure-adjacent but persistence is the
Orchestrator's job). The Orchestrator takes the list of LogEvent objects
returned alongside the findings and inserts them as `execution_logs` rows
with the real workflow_id/task_id/agent_id foreign keys filled in.

Returning logs as structured data (not just calling Python's `logging`
module and hoping something captures it) is what makes "log execution"
actually mean something for observability: every event here is a
candidate execution_logs row, not just a line in a log file nobody
correlates back to a specific workflow run.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class LogEventType(str, Enum):
    AGENT_INVOKED = "agent_invoked"
    AGENT_RESPONSE_RECEIVED = "agent_response_received"
    ERROR = "error"
    SYSTEM = "system"


class LogLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass(frozen=True)
class LogEvent:
    event_type: LogEventType
    log_level: LogLevel
    message: str
    details: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class ExecutionLogger:
    """Accumulates LogEvents during one task execution. Passed into
    ResearchAgent.execute() (dependency injection, not a module-level
    singleton) so that concurrent executions of different tasks don't
    share or interleave log state -- each call gets its own logger
    instance, mirroring how each call gets its own findings object."""

    def __init__(self) -> None:
        self._events: list[LogEvent] = []

    def log(self, event_type: LogEventType, log_level: LogLevel, message: str, **details) -> None:
        self._events.append(LogEvent(event_type=event_type, log_level=log_level, message=message, details=details))

    def info(self, event_type: LogEventType, message: str, **details) -> None:
        self.log(event_type, LogLevel.INFO, message, **details)

    def warning(self, event_type: LogEventType, message: str, **details) -> None:
        self.log(event_type, LogLevel.WARNING, message, **details)

    def error(self, event_type: LogEventType, message: str, **details) -> None:
        self.log(event_type, LogLevel.ERROR, message, **details)

    @property
    def events(self) -> list[LogEvent]:
        return list(self._events)
