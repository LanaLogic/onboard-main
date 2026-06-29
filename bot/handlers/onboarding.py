import logging
import re
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, ReplyKeyboardMarkup, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.keyboards import cancel_keyboard, quiz_keyboard, remove_keyboard, role_keyboard
from config import Settings
from database import TrainingResultRepository
from schemas import TrainingSessionDraft
from services import AITrainingService, TrainingService

logger = logging.getLogger(__name__)
router = Router()
MARKDOWN_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
SECTION_HEADING_RE = re.compile(r"^##\s+\d+[\.)]?\s+", re.MULTILINE)
QUIZ_ANSWER_RE = re.compile(r"^[ABC](?:\+[ABC]){0,2}$")
QUIZ_LETTER_MAP = str.maketrans(
    {
        "а": "A",
        "А": "A",
        "a": "A",
        "A": "A",
        "б": "B",
        "Б": "B",
        "b": "B",
        "B": "B",
        "в": "C",
        "В": "C",
        "c": "C",
        "C": "C",
    }
)
QUIZ_LETTER_MAP.update(
    str.maketrans(
        {
            "\u0430": "A",
            "\u0410": "A",
            "\u0444": "A",
            "\u0424": "A",
            "\u0432": "B",
            "\u0412": "B",
            "\u0431": "B",
            "\u0411": "B",
            "\u0438": "B",
            "\u0418": "B",
            "\u0441": "C",
            "\u0421": "C",
        }
    )
)


class TrainingStates(StatesGroup):
    active = State()


def telegram_html(text: str) -> str:
    escaped = escape(text)
    return MARKDOWN_BOLD_RE.sub(r"<b>\1</b>", escaped)


def count_learning_sections(settings: Settings, draft: TrainingSessionDraft) -> int:
    material = settings.get_training_material(draft.employee_role)
    count = len(SECTION_HEADING_RE.findall(material))
    return count or 1


def normalize_quiz_answer(text: str) -> str:
    normalized_letters = []
    for char in text.strip():
        if char.isspace() or char in "+,;./\\|-":
            continue

        translated = char.translate(QUIZ_LETTER_MAP).upper()
        if translated not in {"A", "B", "C"}:
            return text.strip()

        normalized_letters.append(translated)

    if not normalized_letters:
        return text.strip()

    unique_letters = []
    for letter in normalized_letters:
        if letter not in unique_letters:
            unique_letters.append(letter)
    return "+".join(unique_letters)


def normalize_for_contains(text: str) -> str:
    return " ".join(text.split()).casefold()


def build_visible_reply(ai_turn, draft: TrainingSessionDraft) -> str:
    reply = ai_turn.reply
    if (
        ai_turn.phase == "testing"
        and ai_turn.next_question
        and draft.remaining_questions() > 0
        and normalize_for_contains(ai_turn.next_question) not in normalize_for_contains(reply)
    ):
        return f"{reply}\n\n{ai_turn.next_question}"
    return reply


def training_keyboard(draft: TrainingSessionDraft) -> ReplyKeyboardMarkup | ReplyKeyboardRemove:
    if draft.phase == "testing":
        return quiz_keyboard()
    if draft.phase == "completed":
        return remove_keyboard()
    return cancel_keyboard()


async def save_completed_result(
    message: Message,
    state: FSMContext,
    settings: Settings,
    training_service: TrainingService,
    session_factory: async_sessionmaker[AsyncSession],
    draft: TrainingSessionDraft,
    replies: list[str],
) -> None:
    async with session_factory() as session:
        repository = TrainingResultRepository(session)
        await training_service.create_result(
            repository=repository,
            draft=draft,
            topic=settings.training_topic,
            telegram_user_id=message.from_user.id if message.from_user else 0,
            telegram_chat_id=message.chat.id,
        )

    score_percent = draft.score_percent()
    pass_status = "Тест сдан" if score_percent >= settings.passing_score_percent else "Тест не сдан"
    combined_reply = "\n\n".join(replies)
    final_text = (
        f"{combined_reply}\n\n"
        f"Результат сохранен в Postgres.\n"
        f"Итог: {draft.correct_answers}/{draft.total_questions} ({score_percent}%).\n"
        f"Статус: {pass_status}. Порог сдачи: {settings.passing_score_percent}%."
    )

    await state.clear()
    await message.answer(telegram_html(final_text), reply_markup=remove_keyboard())


@router.message(Command("start"))
async def handle_start(message: Message, state: FSMContext, settings: Settings, training_service: TrainingService) -> None:
    await state.clear()
    await state.set_state(TrainingStates.active)
    await state.update_data(
        draft=training_service.start_session(settings.quiz_question_count).model_dump(),
        result_id=None,
        role_collected=False,
        name_collected=False,
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
async def process_ai_training(
    message: Message,
    state: FSMContext,
    settings: Settings,
    training_service: TrainingService,
    ai_training_service: AITrainingService,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    state_data = await state.get_data()
    draft = TrainingSessionDraft.model_validate(state_data.get("draft", {}))
    role_collected = bool(state_data.get("role_collected"))
    name_collected = bool(state_data.get("name_collected"))
    user_text = message.text or ""

    try:
        if not role_collected:
            updated_draft = training_service.register_employee_role(draft=draft, employee_role=user_text)
            await state.update_data(draft=updated_draft.model_dump(), role_collected=True)
            await message.answer(
                "Роль выбрана. Напишите имя сотрудника, которого нужно обучить.",
                reply_markup=cancel_keyboard(),
            )
            return

        if not name_collected:
            updated_draft = training_service.register_employee_name(draft=draft, employee_name=user_text)
            await state.update_data(draft=updated_draft.model_dump(), name_collected=True)
            ai_turn = await ai_training_service.generate_turn(
                draft=updated_draft,
                user_message="Сотрудник готов начать обучение.",
                is_new_dialogue=True,
            )
            updated_draft = training_service.apply_ai_turn(updated_draft, ai_turn)
        else:
            ai_user_message = user_text
            if draft.phase == "testing" and draft.current_question:
                normalized_answer = normalize_quiz_answer(user_text)
                if not QUIZ_ANSWER_RE.fullmatch(normalized_answer):
                    await message.answer(
                        "Пожалуйста, выберите вариант ответа кнопкой: A, B, C или комбинацию вроде A+B.",
                        reply_markup=quiz_keyboard(),
                    )
                    return

                ai_user_message = (
                    f"Ответ сотрудника на текущий тестовый вопрос: {normalized_answer}. "
                    "Оцени этот ответ. Если тест еще не завершен, сразу задай следующий вопрос с 3 вариантами ответа."
                )

            ai_turn = await ai_training_service.generate_turn(
                draft=draft,
                user_message=ai_user_message,
                is_new_dialogue=False,
            )
            updated_draft = training_service.apply_ai_turn(draft, ai_turn)

        replies = [build_visible_reply(ai_turn, updated_draft)]
        await state.update_data(draft=updated_draft.model_dump())

        if ai_turn.section_completed and updated_draft.phase == "learning":
            max_sections = count_learning_sections(settings, updated_draft)
            is_learning_finished = updated_draft.current_learning_section > max_sections

            if is_learning_finished:
                updated_draft.phase = "testing"
                updated_draft.current_question = None
                updated_draft.learning_status = "explaining"
                await state.update_data(draft=updated_draft.model_dump())
                replies = []
                next_message = (
                    "Системный шаг: все темы обучения пройдены. "
                    "Не отвечай 'Отлично, идем дальше'. Начни тестирование и задай первый вопрос с 3 вариантами ответа."
                )
            else:
                next_message = (
                    "Системный шаг автоперехода: текущая тема уже отмечена как пройденная, "
                    "current_learning_section уже увеличен кодом. Не подтверждай понимание повторно. "
                    "Не здоровайся повторно. Не объясняй формат обучения повторно. "
                    "Не ставь section_completed=true. Объясни текущую тему согласно learning_status=explaining."
                )

            next_ai_turn = await ai_training_service.generate_turn(
                draft=updated_draft,
                user_message=next_message,
                is_new_dialogue=False,
            )
            updated_draft = training_service.apply_ai_turn(updated_draft, next_ai_turn)
            await state.update_data(draft=updated_draft.model_dump())
            replies.append(build_visible_reply(next_ai_turn, updated_draft))
            ai_turn = next_ai_turn

        if (
            ai_turn.latest_answer_evaluated
            and updated_draft.phase == "testing"
            and updated_draft.remaining_questions() == 0
        ):
            updated_draft.phase = "completed"
            updated_draft.current_question = None
            if updated_draft.final_summary is None:
                updated_draft.final_summary = ai_turn.final_summary or ai_turn.answer_feedback or "Тест завершен."
            await state.update_data(draft=updated_draft.model_dump())
            await save_completed_result(
                message=message,
                state=state,
                settings=settings,
                training_service=training_service,
                session_factory=session_factory,
                draft=updated_draft,
                replies=replies,
            )
            return

        if (
            ai_turn.latest_answer_evaluated
            and updated_draft.phase == "testing"
            and updated_draft.remaining_questions() > 0
            and not updated_draft.current_question
        ):
            next_ai_turn = await ai_training_service.generate_turn(
                draft=updated_draft,
                user_message="Системный шаг: ответ на тестовый вопрос уже оценен. Сразу задай следующий вопрос с 3 вариантами ответа.",
                is_new_dialogue=False,
            )
            updated_draft = training_service.apply_ai_turn(updated_draft, next_ai_turn)
            await state.update_data(draft=updated_draft.model_dump())
            replies.append(build_visible_reply(next_ai_turn, updated_draft))
            ai_turn = next_ai_turn

        if ai_turn.phase == "completed":
            await save_completed_result(
                message=message,
                state=state,
                settings=settings,
                training_service=training_service,
                session_factory=session_factory,
                draft=updated_draft,
                replies=replies,
            )
            return

        await message.answer(
            telegram_html("\n\n".join(replies)),
            reply_markup=training_keyboard(updated_draft),
        )
    except ValueError as exc:
        await message.answer(str(exc), reply_markup=role_keyboard() if not role_collected else cancel_keyboard())
    except Exception:
        logger.exception("Failed to process AI training")
        await message.answer(
            "Не удалось обработать сообщение. Попробуйте еще раз или отправьте /cancel.",
            reply_markup=cancel_keyboard(),
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
