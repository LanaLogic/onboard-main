from database.models import TrainingResult
from database.repository import TrainingResultRepository
from schemas import TrainingAssistantTurn, TrainingResultCreate, TrainingSessionDraft


class TrainingService:
    ROLE_ALIASES = {
        "аудитор": "auditor",
        "auditor": "auditor",
        "оператор": "operator",
        "operator": "operator",
    }

    @classmethod
    def validate_employee_role(cls, value: str) -> str:
        cleaned = " ".join(value.split()).strip().lower()
        role = cls.ROLE_ALIASES.get(cleaned)
        if role is None:
            raise ValueError("Выберите роль: аудитор или оператор.")
        return role

    @staticmethod
    def validate_employee_name(value: str) -> str:
        cleaned = " ".join(value.split()).strip()
        if len(cleaned) < 2:
            raise ValueError("Укажите имя сотрудника хотя бы из двух символов.")
        return cleaned

    def start_session(self) -> TrainingSessionDraft:
        return TrainingSessionDraft(total_questions=1)

    def register_employee_role(self, draft: TrainingSessionDraft, employee_role: str) -> TrainingSessionDraft:
        updated = TrainingSessionDraft.model_validate(draft.model_dump())
        updated.employee_role = self.validate_employee_role(employee_role)
        updated.phase = "collecting_name"
        return updated

    def register_employee_name(self, draft: TrainingSessionDraft, employee_name: str) -> TrainingSessionDraft:
        updated = TrainingSessionDraft.model_validate(draft.model_dump())
        updated.employee_name = self.validate_employee_name(employee_name)
        updated.phase = "learning"
        updated.current_learning_section = 1
        updated.learning_status = "explaining"
        updated.last_learning_question = None
        return updated

    def apply_ai_turn(
        self,
        current: TrainingSessionDraft,
        ai_turn: TrainingAssistantTurn,
    ) -> TrainingSessionDraft:
        updated = TrainingSessionDraft.model_validate(current.model_dump())
        updated.phase = ai_turn.phase

        if ai_turn.current_learning_section is not None:
            updated.current_learning_section = ai_turn.current_learning_section

        if ai_turn.learning_status is not None:
            updated.learning_status = ai_turn.learning_status

        if ai_turn.last_learning_question is not None:
            updated.last_learning_question = ai_turn.last_learning_question

        if ai_turn.section_completed:
            updated.current_learning_section = current.current_learning_section + 1
            updated.learning_status = "explaining"
            updated.last_learning_question = None

        if ai_turn.latest_answer_evaluated and current.phase == "testing" and current.current_question:
            updated.questions_answered += 1
            if ai_turn.answer_is_correct:
                updated.correct_answers += 1

        if ai_turn.answer_feedback is not None:
            updated.last_answer_feedback = ai_turn.answer_feedback

        updated.current_question = ai_turn.next_question

        if ai_turn.final_summary is not None:
            updated.final_summary = ai_turn.final_summary

        return updated

    async def create_result(
        self,
        repository: TrainingResultRepository,
        draft: TrainingSessionDraft,
        topic: str,
        telegram_user_id: int,
        telegram_chat_id: int,
    ) -> TrainingResult:
        result_in = TrainingResultCreate(
            employee_name=draft.employee_name or "Неизвестный сотрудник",
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            topic=topic,
            total_questions=draft.total_questions,
            correct_answers=draft.correct_answers,
            score_percent=draft.score_percent(),
            final_summary=draft.final_summary,
        )
        return await repository.create(result_in)
