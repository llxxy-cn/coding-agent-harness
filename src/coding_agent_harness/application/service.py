from coding_agent_harness.domain.enums import TaskStatus


class ApplicationService:
    def __init__(self, core) -> None:
        self.core = core

    def run_task(self, task_id):
        return self.core.run(task_id)

    def resume_task(self, task_id):
        session = self.core.session_store.load(task_id)
        if session.status is not TaskStatus.PAUSED_FOR_HUMAN:
            raise ValueError("task is not paused")
        self.core.session_store.save(session.model_copy(update={"status": TaskStatus.DECIDING}))
        return self.core.run(task_id)
