import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SECTION_RE = re.compile(r"^##\s+(\d+)[\.)]?\s*(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class TrainingSection:
    number: int
    title: str
    content: str


@dataclass(frozen=True)
class QuizQuestion:
    question: str
    question_type: str
    options: dict[str, str]
    correct_answers: tuple[str, ...]
    explanation: str = ""

    @property
    def allows_multiple_answers(self) -> bool:
        return len(self.correct_answers) > 1


class TrainingContentService:
    @staticmethod
    def parse_sections(material: str) -> list[TrainingSection]:
        matches = list(SECTION_RE.finditer(material))
        if not matches:
            cleaned = material.strip()
            return [TrainingSection(number=1, title="Материал", content=cleaned)] if cleaned else []

        sections: list[TrainingSection] = []
        for index, match in enumerate(matches):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(material)
            sections.append(
                TrainingSection(
                    number=int(match.group(1)),
                    title=match.group(2).strip(),
                    content=material[start:end].strip(),
                )
            )
        return sections

    def get_sections(self, material: str) -> list[TrainingSection]:
        return self.parse_sections(material)

    def get_section(self, material: str, section_number: int) -> TrainingSection | None:
        for section in self.get_sections(material):
            if section.number == section_number:
                return section
        return None

    def load_quiz(self, path: str) -> list[QuizQuestion]:
        quiz_path = Path(path)
        if not quiz_path.exists():
            return []

        raw_text = quiz_path.read_text(encoding="utf-8").strip()
        if not raw_text:
            return []

        raw_items = json.loads(raw_text)
        if not isinstance(raw_items, list):
            raise ValueError("Файл теста должен содержать JSON-массив вопросов.")

        if len(raw_items) == 1 and isinstance(raw_items[0], dict) and isinstance(raw_items[0].get("questions"), list):
            raw_items = raw_items[0]["questions"]

        questions = [self._parse_quiz_question(item) for item in raw_items]
        return questions

    @staticmethod
    def _parse_quiz_question(item: Any) -> QuizQuestion:
        if not isinstance(item, dict):
            raise ValueError("Каждый вопрос теста должен быть JSON-объектом.")

        question = str(item.get("question", "")).strip()
        if not question:
            raise ValueError("В вопросе теста не заполнено поле question.")

        question_type = str(item.get("type", "single_choice")).strip() or "single_choice"
        options = TrainingContentService._parse_options(item.get("options"))
        correct_answers = TrainingContentService._parse_correct_answers(item)
        if any(answer not in options for answer in correct_answers):
            raise ValueError("Правильные ответы должны ссылаться на существующие варианты ответа.")

        explanation = str(item.get("explanation", "")).strip()

        return QuizQuestion(
            question=question,
            question_type=question_type,
            options=options,
            correct_answers=correct_answers,
            explanation=explanation,
        )

    @staticmethod
    def _parse_options(raw_options: Any) -> dict[str, str]:
        if isinstance(raw_options, dict):
            options = {str(key).upper(): str(value).strip() for key, value in raw_options.items()}
        elif isinstance(raw_options, list):
            letters = ["A", "B", "C", "D", "E"]
            options = {letter: str(value).strip() for letter, value in zip(letters, raw_options)}
        else:
            raise ValueError("Поле options должно быть объектом A/B/C... или списком вариантов.")

        allowed_letters = {"A", "B", "C", "D", "E"}
        if not 2 <= len(options) <= 5:
            raise ValueError("В каждом вопросе должно быть от 2 до 5 вариантов ответа.")
        if any(letter not in allowed_letters for letter in options):
            raise ValueError("Варианты ответа должны быть обозначены буквами A, B, C, D, E.")
        if any(not value for value in options.values()):
            raise ValueError("Все варианты ответа должны быть заполнены.")
        return options

    @staticmethod
    def _parse_correct_answers(item: dict[str, Any]) -> tuple[str, ...]:
        raw_answers = item.get("correct_answers", item.get("correct_answer"))
        if isinstance(raw_answers, str):
            answers = [part.strip().upper() for part in re.split(r"[+,; ]+", raw_answers) if part.strip()]
        elif isinstance(raw_answers, list):
            answers = [str(part).strip().upper() for part in raw_answers if str(part).strip()]
        else:
            raise ValueError("В вопросе теста должно быть поле correct_answer или correct_answers.")

        unique_answers = tuple(dict.fromkeys(answers))
        if not unique_answers or any(answer not in {"A", "B", "C", "D", "E"} for answer in unique_answers):
            raise ValueError("Правильные ответы должны быть A, B, C, D, E или их комбинацией.")
        return unique_answers
