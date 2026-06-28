from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split()).strip()
    return cleaned or None


class TrainingResultCreate(BaseModel):
    employee_name: str = Field(min_length=2, max_length=255)
    telegram_user_id: int
    telegram_chat_id: int
    topic: str = Field(min_length=2, max_length=255)
    total_questions: int = Field(ge=1, le=20)
    correct_answers: int = Field(ge=0, le=20)
    score_percent: int = Field(ge=0, le=100)
    final_summary: str | None = Field(default=None, max_length=4000)

    @field_validator("employee_name", "topic", "final_summary")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        return _normalize_text(value)


class TrainingResultRead(TrainingResultCreate):
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class TrainingSessionDraft(BaseModel):
    employee_name: str | None = None
    employee_role: Literal["auditor", "operator"] | None = None
    phase: Literal["collecting_role", "collecting_name", "learning", "testing", "completed"] = "collecting_role"
    current_learning_section: int = Field(default=1, ge=1, le=50)
    learning_status: Literal["explaining", "waiting_confirmation", "waiting_check_answer"] = "explaining"
    last_learning_question: str | None = None
    total_questions: int = Field(default=5, ge=1, le=20)
    questions_answered: int = Field(default=0, ge=0, le=20)
    correct_answers: int = Field(default=0, ge=0, le=20)
    current_question: str | None = None
    last_answer_feedback: str | None = None
    final_summary: str | None = None

    @field_validator("employee_name", "last_learning_question", "current_question", "last_answer_feedback", "final_summary")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _normalize_text(value)

    def remaining_questions(self) -> int:
        return max(self.total_questions - self.questions_answered, 0)

    def score_percent(self) -> int:
        if self.total_questions == 0:
            return 0
        return round((self.correct_answers / self.total_questions) * 100)


class TrainingAssistantTurn(BaseModel):
    reply: str = Field(min_length=1)
    phase: Literal["learning", "testing", "completed"]
    current_learning_section: int | None = Field(default=None, ge=1, le=50)
    learning_status: Literal["explaining", "waiting_confirmation", "waiting_check_answer"] | None = None
    last_learning_question: str | None = None
    section_completed: bool = False
    user_intent: Literal[
        "start",
        "confirmation",
        "negative_confirmation",
        "employee_question",
        "off_topic",
        "answer",
        "unknown",
    ] | None = None
    latest_answer_evaluated: bool = False
    answer_is_correct: bool | None = None
    answer_feedback: str | None = None
    next_question: str | None = None
    final_summary: str | None = None

    @field_validator("last_learning_question", "answer_feedback", "next_question", "final_summary")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _normalize_text(value)
