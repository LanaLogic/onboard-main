import logging
import re
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.keyboards import cancel_keyboard, remove_keyboard, role_keyboard
from config import Settings
from database import TrainingResultRepository
from schemas import TrainingSessionDraft
from services import AITrainingService, TrainingService

logger = logging.getLogger(__name__)
router = Router()
MARKDOWN_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
SECTION_HEADING_RE = re.compile(r"^##\s+\d+[\.)]?\s+", re.MULTILINE)


class TrainingStates(StatesGroup):
    active = State()


def telegram_html(text: str) -> str:
    escaped = escape(text)
    return MARKDOWN_BOLD_RE.sub(r"<b>\1</b>", escaped)


def count_learning_sections(settings: Settings, draft: TrainingSessionDraft) -> int:
    material = settings.get_training_material(draft.employee_role)
    count = len(SECTION_HEADING_RE.findall(material))
    return count or 1


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
            ai_turn = await ai_training_service.generate_turn(
                draft=draft,
                user_message=user_text,
                is_new_dialogue=False,
            )
            updated_draft = training_service.apply_ai_turn(draft, ai_turn)

        replies = [ai_turn.reply]
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
            replies.append(next_ai_turn.reply)
            ai_turn = next_ai_turn

        if ai_turn.phase == "completed":
            async with session_factory() as session:
                repository = TrainingResultRepository(session)
                await training_service.create_result(
                    repository=repository,
                    draft=updated_draft,
                    topic=settings.training_topic,
                    telegram_user_id=message.from_user.id if message.from_user else 0,
                    telegram_chat_id=message.chat.id,
                )
            score_percent = updated_draft.score_percent()
            pass_status = "Тест сдан" if score_percent >= settings.passing_score_percent else "Тест не сдан"
            combined_reply = "\n\n".join(replies)
            final_text = (
                f"{combined_reply}\n\n"
                f"Результат сохранен в Postgres.\n"
                f"Итог: {updated_draft.correct_answers}/{updated_draft.total_questions} "
                f"({score_percent}%).\n"
                f"Статус: {pass_status}. Порог сдачи: {settings.passing_score_percent}%."
            )

            await state.clear()
            await message.answer(
                telegram_html(final_text),
                reply_markup=remove_keyboard(),
            )
            return

        await message.answer(telegram_html("\n\n".join(replies)), reply_markup=cancel_keyboard())
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
