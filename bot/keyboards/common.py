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
            [KeyboardButton(text="auditor"), KeyboardButton(text="operator")],
            [KeyboardButton(text="/cancel")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Choose role",
    )


def training_mode_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Обучение + тест")],
            [KeyboardButton(text="Только тест")],
            [KeyboardButton(text="/cancel")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите режим",
    )


def quiz_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="A"), KeyboardButton(text="B"), KeyboardButton(text="C")],
            [KeyboardButton(text="D"), KeyboardButton(text="E")],
            [KeyboardButton(text="/cancel")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите вариант или напишите A+B",
    )


def remove_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()
