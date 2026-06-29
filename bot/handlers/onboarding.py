import logging
import re
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, ReplyKeyboardMarkup, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.keyboards import cancel_keyboard, quiz_keyboard, remove_keyboard, role_keyboard, training_mode_keyboard
from config import Settings
from database import TrainingResultRepository
from schemas import TrainingSessionDraft
from services import AITrainingService, TrainingContentService, TrainingService
from services.training_content_service import QuizQuestion, TrainingSection

logger = logging.getLogger(__name__)
router = Router()

MARKDOWN_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
MARKDOWN_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
QUIZ_ANSWER_RE = re.compile(r"^[ABCDE](?:\+[ABCDE]){0,4}$")
QUIZ_LETTER_MAP = str.maketrans(
    {
        "\u0430": "A",
        "\u0410": "A",
        "\u0444": "A",
        "\u0424": "A",
        "a": "A",
        "A": "A",
        "\u0432": "B",
        "\u0412": "B",
        "\u0431": "B",
        "\u0411": "B",
        "\u0438": "B",
        "\u0418": "B",
        "b": "B",
        "B": "B",
        "\u0441": "C",
        "\u0421": "C",
        "c": "C",
        "C": "C",
        "\u0434": "D",
        "\u0414": "D",
        "d": "D",
        "D": "D",
        "\u0435": "E",
        "\u0415": "E",
        "\u0451": "E",
        "\u0401": "E",
        "e": "E",
        "E": "E",
    }
)

POSITIVE_RE = re.compile(r"^(да|понятно|ясно|ок|окей|хорошо|дальше|идем дальше|можем|готово?)\.?!?$", re.IGNORECASE)
NEGATIVE_RE = re.compile(r"^(нет|не понятно|непонятно|не ясно|неясно|объясни|повтори)\.?!?$", re.IGNORECASE)
START_TEST_RE = re.compile(r"(готов|готова|начать|перейти).{0,20}(тест|тестирован)", re.IGNORECASE)
LEARNING_MODE_ALIASES = {"обучение + тест", "обучение", "learning", "learn", "study"}
TEST_ONLY_MODE_ALIASES = {"только тест", "тест", "test", "testing", "quiz"}


class TrainingStates(StatesGroup):
    active = State()


def telegram_html(text: str) -> str:
    escaped = escape(text)
    escaped = MARKDOWN_BOLD_RE.sub(r"<b>\1</b>", escaped)
    return MARKDOWN_ITALIC_RE.sub(r"<i>\1</i>", escaped)


def material_html(text: str) -> str:
    lines = text.splitlines()
    formatted_lines: list[str] = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            if formatted_lines and formatted_lines[-1] != "":
                formatted_lines.append("")
            continue

        if line.startswith("#### "):
            formatted_lines.append(f"<b>{escape(line[5:])}</b>")
            continue

        if line.startswith("### "):
            formatted_lines.append(f"<b>{escape(line[4:])}</b>")
            continue

        if line.startswith("## "):
            formatted_lines.append(f"<b>{escape(line[3:])}</b>")
            continue

        if line.startswith(">"):
            formatted_lines.append(f"<i>{escape(line.lstrip('> ').strip())}</i>")
            continue

        if line.startswith("- [ ] "):
            formatted_lines.append(f"• {escape(line[6:])}")
            continue

        if line.startswith("- "):
            formatted_lines.append(f"• {escape(line[2:])}")
            continue

        if line.endswith(":") and len(line) <= 80:
            formatted_lines.append(f"<b>{escape(line)}</b>")
            continue

        if line in {"Золотое правило проекта", "Формат пилота", "Что проверяется на пилоте"}:
            formatted_lines.append(f"<b>{escape(line)}</b>")
            continue

        formatted_lines.append(telegram_html(line))

    while formatted_lines and formatted_lines[-1] == "":
        formatted_lines.pop()
    return "\n".join(formatted_lines)


def normalize_quiz_answer(text: str) -> str:
    normalized_letters = []
    for char in text.strip():
        if char.isspace() or char in "+,;./\\|-":
            continue

        translated = char.translate(QUIZ_LETTER_MAP).upper()
        if translated not in {"A", "B", "C", "D", "E"}:
            return text.strip()

        normalized_letters.append(translated)

    if not normalized_letters:
        return text.strip()

    unique_letters = []
    for letter in normalized_letters:
        if letter not in unique_letters:
            unique_letters.append(letter)
    return "+".join(unique_letters)


def is_positive_confirmation(text: str) -> bool:
    return bool(POSITIVE_RE.fullmatch(" ".join(text.split()).strip()))


def is_negative_confirmation(text: str) -> bool:
    return bool(NEGATIVE_RE.fullmatch(" ".join(text.split()).strip()))


def normalize_training_mode(text: str) -> str | None:
    cleaned = " ".join(text.split()).strip().lower()
    if cleaned in LEARNING_MODE_ALIASES:
        return "learning"
    if cleaned in TEST_ONLY_MODE_ALIASES:
        return "testing"
    return None


def training_keyboard(draft: TrainingSessionDraft) -> ReplyKeyboardMarkup | ReplyKeyboardRemove:
    if draft.phase == "testing":
        return quiz_keyboard()
    if draft.phase == "completed":
        return remove_keyboard()
    return cancel_keyboard()


def format_section(section: TrainingSection, employee_name: str | None = None, is_first: bool = False) -> str:
    prefix = ""
    if is_first:
        name = f", {employee_name}" if employee_name else ""
        prefix = (
            f"Привет{name}! Сначала разберем материал по темам. "
            "После каждой темы можно задать вопрос, а когда все темы будут понятны, начнется тест.\n\n"
        )

    return (
        f"{prefix}"
        f"📘 <b>Тема {section.number}. {escape(section.title)}</b>\n\n"
        f"{material_html(section.content)}\n\n"
        "<b>Все понятно? Можем идти дальше?</b>"
    )


def format_quiz_question(question: QuizQuestion, number: int, total: int) -> str:
    answer_hint = "Можно выбрать несколько вариантов." if question.allows_multiple_answers else "Выберите один вариант."
    options = "\n".join(f"<b>{letter}.</b> {escape(text)}" for letter, text in question.options.items())
    return (
        f"📝 <b>Тест</b>\n\n"
        f"<b>Вопрос {number} из {total}</b>\n\n"
        f"❓ {escape(question.question)}\n\n"
        f"{options}\n\n"
        f"{answer_hint}"
    )


def current_section(
    settings: Settings,
    content_service: TrainingContentService,
    draft: TrainingSessionDraft,
) -> TrainingSection | None:
    material = settings.get_training_material(draft.employee_role)
    return content_service.get_section(material, draft.current_learning_section)


def next_section(
    settings: Settings,
    content_service: TrainingContentService,
    draft: TrainingSessionDraft,
) -> TrainingSection | None:
    material = settings.get_training_material(draft.employee_role)
    sections = content_service.get_sections(material)
    for index, section in enumerate(sections):
        if section.number == draft.current_learning_section:
            if index + 1 < len(sections):
                return sections[index + 1]
            return None
    return sections[0] if sections else None


def quiz_questions(
    settings: Settings,
    content_service: TrainingContentService,
    draft: TrainingSessionDraft,
) -> list[QuizQuestion]:
    return content_service.load_quiz(settings.get_quiz_file(draft.employee_role))


async def start_testing(
    message: Message,
    state: FSMContext,
    settings: Settings,
    content_service: TrainingContentService,
    draft: TrainingSessionDraft,
) -> None:
    questions = quiz_questions(settings, content_service, draft)
    if not questions:
        await message.answer(
            "Тест для этой роли пока не заполнен. Добавьте вопросы в файл теста и начните обучение заново через /start.",
            reply_markup=remove_keyboard(),
        )
        await state.clear()
        return

    updated = TrainingSessionDraft.model_validate(draft.model_dump())
    updated.phase = "testing"
    updated.total_questions = len(questions)
    updated.questions_answered = 0
    updated.correct_answers = 0
    updated.quiz_mistakes = []
    updated.current_question = questions[0].question
    await state.update_data(draft=updated.model_dump())

    await message.answer(
        "Обучение завершено, начинаем тестирование.\n\n"
        + format_quiz_question(questions[0], number=1, total=len(questions)),
        reply_markup=quiz_keyboard(),
    )


async def save_completed_result(
    message: Message,
    state: FSMContext,
    settings: Settings,
    training_service: TrainingService,
    session_factory: async_sessionmaker[AsyncSession],
    draft: TrainingSessionDraft,
    final_summary: str,
) -> None:
    updated = TrainingSessionDraft.model_validate(draft.model_dump())
    updated.phase = "completed"
    updated.current_question = None
    updated.final_summary = final_summary

    async with session_factory() as session:
        repository = TrainingResultRepository(session)
        await training_service.create_result(
            repository=repository,
            draft=updated,
            topic=settings.training_topic,
            telegram_user_id=message.from_user.id if message.from_user else 0,
            telegram_chat_id=message.chat.id,
        )

    score_percent = updated.score_percent()
    pass_status = "Тест сдан" if score_percent >= settings.passing_score_percent else "Тест не сдан"
    final_text = (
        f"{final_summary}\n\n"
        f"Результат сохранен в Postgres.\n"
        f"Итог: {updated.correct_answers}/{updated.total_questions} ({score_percent}%).\n"
        f"Статус: {pass_status}. Порог сдачи: {settings.passing_score_percent}%."
    )

    await state.clear()
    await message.answer(telegram_html(final_text), reply_markup=remove_keyboard())


@router.message(Command("start"))
async def handle_start(message: Message, state: FSMContext, settings: Settings, training_service: TrainingService) -> None:
    await state.clear()
    await state.set_state(TrainingStates.active)
    await state.update_data(
        draft=training_service.start_session().model_dump(),
        role_collected=False,
        name_collected=False,
        mode_collected=False,
    )
    await message.answer(
        "Здравствуйте! Я помогу изучить новый материал, а затем проведу тестирование.\n\n"
        "Выберите роль сотрудника:",
        reply_markup=role_keyboard(),
    )


@router.message(Command("cancel"))
async def handle_cancel(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Сейчас нет активной сессии обучения.", reply_markup=remove_keyboard())
        return

    await state.clear()
    await message.answer(
        "Сессия обучения отменена. Чтобы начать заново, отправьте /start.",
        reply_markup=remove_keyboard(),
    )


@router.message(TrainingStates.active, F.text)
async def process_training(
    message: Message,
    state: FSMContext,
    settings: Settings,
    training_service: TrainingService,
    training_content_service: TrainingContentService,
    ai_training_service: AITrainingService,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    state_data = await state.get_data()
    draft = TrainingSessionDraft.model_validate(state_data.get("draft", {}))
    role_collected = bool(state_data.get("role_collected"))
    name_collected = bool(state_data.get("name_collected"))
    mode_collected = bool(state_data.get("mode_collected"))
    user_text = message.text or ""

    try:
        if not role_collected:
            updated = training_service.register_employee_role(draft=draft, employee_role=user_text)
            await state.update_data(draft=updated.model_dump(), role_collected=True)
            await message.answer(
                "Роль выбрана. Напишите имя сотрудника, которого нужно обучить.",
                reply_markup=cancel_keyboard(),
            )
            return

        if not name_collected:
            updated = training_service.register_employee_name(draft=draft, employee_name=user_text)
            await state.update_data(draft=updated.model_dump(), name_collected=True)
            await message.answer(
                "Выберите режим:",
                reply_markup=training_mode_keyboard(),
            )
            return

        if not mode_collected:
            mode = normalize_training_mode(user_text)
            if mode is None:
                await message.answer(
                    "Выберите режим кнопкой: Обучение + тест или Только тест.",
                    reply_markup=training_mode_keyboard(),
                )
                return

            await state.update_data(mode_collected=True)

            if mode == "testing":
                await start_testing(message, state, settings, training_content_service, draft)
                return

            section = current_section(settings, training_content_service, draft)
            if section is None:
                await message.answer("Не удалось найти первый раздел материала для этой роли.", reply_markup=cancel_keyboard())
                return

            await message.answer(format_section(section, draft.employee_name, is_first=True), reply_markup=cancel_keyboard())
            return

        if draft.phase == "learning":
            if START_TEST_RE.search(user_text):
                await start_testing(message, state, settings, training_content_service, draft)
                return

            if is_positive_confirmation(user_text):
                updated = TrainingSessionDraft.model_validate(draft.model_dump())
                section = next_section(settings, training_content_service, updated)

                if section is None:
                    await start_testing(message, state, settings, training_content_service, updated)
                    return

                updated.current_learning_section = section.number
                await state.update_data(draft=updated.model_dump())
                await message.answer("✅ Отлично, идем дальше.\n\n" + format_section(section), reply_markup=cancel_keyboard())
                return

            section = current_section(settings, training_content_service, draft)
            material = settings.get_training_material(draft.employee_role)
            section_text = f"## {section.number}. {section.title}\n\n{section.content}" if section else material

            if is_negative_confirmation(user_text):
                user_text = "Сотруднику непонятна текущая тема. Объясни ее проще и короче."

            try:
                answer = await ai_training_service.answer_employee_question(
                    topic=settings.training_topic,
                    employee_role=draft.employee_role,
                    material=material,
                    current_section=section_text,
                    user_question=user_text,
                )
            except Exception:
                logger.exception("Failed to answer employee question")
                answer = "Не удалось получить пояснение от AI. Попробуйте задать вопрос еще раз или обратитесь к координатору."

            await message.answer(telegram_html(f"{answer}\n\n**Все понятно? Можем идти дальше?**"), reply_markup=cancel_keyboard())
            return

        if draft.phase == "testing":
            questions = quiz_questions(settings, training_content_service, draft)
            if not questions:
                await message.answer("Тест для этой роли пока не заполнен.", reply_markup=remove_keyboard())
                await state.clear()
                return

            question_index = draft.questions_answered
            if question_index >= len(questions):
                await finish_testing(
                    message,
                    state,
                    settings,
                    training_service,
                    ai_training_service,
                    session_factory,
                    draft,
                )
                return

            normalized_answer = normalize_quiz_answer(user_text)
            if not QUIZ_ANSWER_RE.fullmatch(normalized_answer):
                await message.answer(
                    "Пожалуйста, выберите вариант ответа кнопкой или напишите комбинацию вроде A+B.",
                    reply_markup=quiz_keyboard(),
                )
                return

            question = questions[question_index]
            selected_answers = tuple(normalized_answer.split("+"))
            if any(answer not in question.options for answer in selected_answers):
                available = ", ".join(question.options)
                await message.answer(
                    f"В этом вопросе доступны варианты: {available}. Выберите один из них или комбинацию доступных вариантов.",
                    reply_markup=quiz_keyboard(),
                )
                return

            is_correct = set(selected_answers) == set(question.correct_answers)

            updated = TrainingSessionDraft.model_validate(draft.model_dump())
            updated.questions_answered += 1
            if is_correct:
                updated.correct_answers += 1
                feedback = "✅ Верно."
            else:
                correct = "+".join(question.correct_answers)
                feedback = f"❌ Неверно. Правильный ответ: {correct}."
                updated.quiz_mistakes.append(f"{question.question} Правильный ответ: {correct}.")

            if question.explanation:
                feedback += f" {question.explanation}"

            if updated.questions_answered >= len(questions):
                updated.total_questions = len(questions)
                await state.update_data(draft=updated.model_dump())
                await finish_testing(
                    message,
                    state,
                    settings,
                    training_service,
                    ai_training_service,
                    session_factory,
                    updated,
                    prefix=feedback,
                )
                return

            next_question_item = questions[updated.questions_answered]
            updated.current_question = next_question_item.question
            updated.total_questions = len(questions)
            await state.update_data(draft=updated.model_dump())
            await message.answer(
                telegram_html(feedback) + "\n\n" + format_quiz_question(next_question_item, number=updated.questions_answered + 1, total=len(questions)),
                reply_markup=quiz_keyboard(),
            )
            return

        await message.answer("Сессия уже завершена. Чтобы начать заново, отправьте /start.", reply_markup=remove_keyboard())

    except ValueError as exc:
        if not role_collected:
            reply_markup = role_keyboard()
        elif name_collected and not mode_collected:
            reply_markup = training_mode_keyboard()
        else:
            reply_markup = cancel_keyboard()
        await message.answer(str(exc), reply_markup=reply_markup)
    except Exception:
        logger.exception("Failed to process training")
        await message.answer(
            "Не удалось обработать сообщение. Попробуйте еще раз или отправьте /cancel.",
            reply_markup=cancel_keyboard(),
        )


async def finish_testing(
    message: Message,
    state: FSMContext,
    settings: Settings,
    training_service: TrainingService,
    ai_training_service: AITrainingService,
    session_factory: async_sessionmaker[AsyncSession],
    draft: TrainingSessionDraft,
    prefix: str | None = None,
) -> None:
    try:
        final_summary = await ai_training_service.generate_final_summary(
            topic=settings.training_topic,
            employee_role=draft.employee_role,
            correct_answers=draft.correct_answers,
            total_questions=draft.total_questions,
            score_percent=draft.score_percent(),
            quiz_mistakes=draft.quiz_mistakes,
        )
    except Exception:
        logger.exception("Failed to generate final summary")
        if draft.quiz_mistakes:
            final_summary = "Тест завершен. Рекомендуется повторить вопросы, где были ошибки."
        else:
            final_summary = "Тест завершен. Ошибок в ответах нет."

    if prefix:
        final_summary = f"{prefix}\n\n{final_summary}"

    await save_completed_result(
        message=message,
        state=state,
        settings=settings,
        training_service=training_service,
        session_factory=session_factory,
        draft=draft,
        final_summary=final_summary,
    )


@router.message(TrainingStates.active)
async def handle_invalid_collecting_input(message: Message) -> None:
    await message.answer("Пожалуйста, отправьте ответ текстом.", reply_markup=cancel_keyboard())


@router.message(F.text)
async def handle_text_without_flow(message: Message) -> None:
    await message.answer("Чтобы начать обучение и тестирование, отправьте /start.")


@router.message()
async def handle_unsupported_input(message: Message) -> None:
    await message.answer("Пожалуйста, используйте текстовые сообщения или команду /start.")
