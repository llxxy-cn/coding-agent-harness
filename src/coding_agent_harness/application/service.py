from coding_agent_harness.domain.enums import TaskStatus


class ApplicationService:
    def __init__(self, core=None, *, session_store=None) -> None:
        self.core = core
        self.session_store = session_store or (core.session_store if core is not None else None)

    def run_task(self, task_id):
        if self.core is None:
            raise ValueError("task execution is unavailable")
        return self.core.run(task_id)

    def run_session(self, session):
        if self.session_store is None:
            raise ValueError("task storage is unavailable")
        self.session_store.save(session)
        return self.run_task(session.task_id)

    def status_task(self, task_id):
        if self.session_store is None:
            raise ValueError("task storage is unavailable")
        return self.session_store.load(task_id)

    def resume_task(self, task_id):
        if self.core is None or self.session_store is None:
            raise ValueError("task execution is unavailable")
        session = self.session_store.load(task_id)
        if session.status is not TaskStatus.PAUSED_FOR_HUMAN:
            raise ValueError("task is not resumable")
        self.session_store.save(session.model_copy(update={"status": TaskStatus.DECIDING}))
        return self.core.run(task_id)
