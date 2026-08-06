from pydantic import BaseModel, ConfigDict, Field, StrictInt


class Budget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    action_count: StrictInt = Field(default=0, ge=0)
    feedback_count: StrictInt = Field(default=0, ge=0)
    max_actions: StrictInt = Field(default=40, ge=1)
    max_feedback: StrictInt = Field(default=8, ge=1)

    @property
    def can_call_llm(self) -> bool:
        return self.action_count < self.max_actions and self.feedback_count < self.max_feedback

    def consume_action(self) -> "Budget":
        return self.model_copy(update={"action_count": self.action_count + 1})

    def consume_feedback(self) -> "Budget":
        return self.model_copy(update={"feedback_count": self.feedback_count + 1})
