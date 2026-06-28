from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove


def cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="/cancel")]],
        resize_keyboard=True,
        input_field_placeholder="Введите ответ или /cancel",
    )


def role_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="аудитор"), KeyboardButton(text="оператор")],
            [KeyboardButton(text="/cancel")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите роль",
    )


def remove_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()
