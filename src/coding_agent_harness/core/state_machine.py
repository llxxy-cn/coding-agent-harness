from coding_agent_harness.domain.enums import TaskStatus


TERMINAL_TASK_STATUSES = frozenset({TaskStatus.SUCCEEDED, TaskStatus.STOPPED, TaskStatus.PAUSED_FOR_HUMAN, TaskStatus.CANCELLED})


def is_terminal(status: TaskStatus) -> bool:
    return status in TERMINAL_TASK_STATUSES
