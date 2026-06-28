from services.prompts import BASE_PROMPT


AI_TRAINING_RESPONSE_SCHEMA = {
    "name": "training_turn",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "reply": {"type": "string"},
            "phase": {"type": "string", "enum": ["learning", "testing", "completed"]},
            "current_learning_section": {"type": ["integer", "null"], "minimum": 1, "maximum": 50},
            "learning_status": {
                "type": ["string", "null"],
                "enum": ["explaining", "waiting_confirmation", "waiting_check_answer", None],
            },
            "last_learning_question": {"type": ["string", "null"]},
            "section_completed": {"type": "boolean"},
            "user_intent": {
                "type": ["string", "null"],
                "enum": [
                    "start",
                    "confirmation",
                    "negative_confirmation",
                    "employee_question",
                    "off_topic",
                    "answer",
                    "unknown",
                    None,
                ],
            },
            "latest_answer_evaluated": {"type": "boolean"},
            "answer_is_correct": {"type": ["boolean", "null"]},
            "answer_feedback": {"type": ["string", "null"]},
            "next_question": {"type": ["string", "null"]},
            "final_summary": {"type": ["string", "null"]},
        },
        "required": [
            "reply",
            "phase",
            "current_learning_section",
            "learning_status",
            "last_learning_question",
            "section_completed",
            "user_intent",
            "latest_answer_evaluated",
            "answer_is_correct",
            "answer_feedback",
            "next_question",
            "final_summary",
        ],
        "additionalProperties": False,
    },
}


def build_training_system_prompt(
    topic: str,
    material: str,
    total_questions: int,
    employee_role: str | None = None,
    phase: str | None = None,
) -> str:
    return BASE_PROMPT.format(
        topic=topic,
        employee_role=employee_role or "не указана",
        material=material,
        phase=phase or "не указан",
        total_questions=total_questions,
    ).strip()
