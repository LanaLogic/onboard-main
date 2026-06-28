# Onboard

Telegram-бот для обучения сотрудников по роли и последующего тестирования через LLM.

Бот обучает сотрудника по инструкции из файла, задает вопросы по одному, проверяет ответы по материалу и сохраняет результат теста в Postgres.

## Возможности

- выбор роли сотрудника: `аудитор` или `оператор`;
- обучение только по материалу выбранной роли;
- ответы на вопросы сотрудника только по инструкции;
- тест из `QUIZ_QUESTION_COUNT` вопросов;
- подсчет результата и процента правильных ответов;
- статус `Тест сдан` / `Тест не сдан` по порогу `PASSING_SCORE_PERCENT`;
- сохранение результата в таблицу `training_results`.

## Как Работает

1. Пользователь отправляет `/start`.
2. Бот предлагает выбрать роль: `аудитор` или `оператор`.
3. Бот просит имя сотрудника.
4. AI-наставник обучает по файлу выбранной роли:
   - `materials/auditor.txt` для аудитора;
   - `materials/operator.txt` для оператора.
5. Когда материал разобран или сотрудник готов, бот переходит к тесту.
6. После теста бот считает результат, определяет статус сдачи и сохраняет итог в Postgres.

## Материалы

Материалы лежат в папке `materials/`.

```text
materials/
  auditor.txt
  operator.txt
```

Каждый файл самодостаточный: содержит вводную часть, правила роли, примеры, ошибки и критерии проверки. Файлы оформлены в Markdown, но оставлены с расширением `.txt`, чтобы не менять логику загрузки.

## Переменные Окружения

Создайте `.env` на основе `.env.example` и заполните реальные значения.

```env
BOT_TOKEN=your_telegram_bot_token
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/onboarding
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-5.4-mini-2026-03-17
OPENAI_BASE_URL=https://api.openai.com/v1

TRAINING_TOPIC=Ценовой мониторинг
TRAINING_AUDITOR_MATERIAL_FILE=./materials/auditor.txt
TRAINING_OPERATOR_MATERIAL_FILE=./materials/operator.txt

QUIZ_QUESTION_COUNT=5
PASSING_SCORE_PERCENT=80
LOG_LEVEL=INFO
```

Для локального запуска через `python main.py` используйте хост `localhost`.

Для запуска бота внутри Docker Compose используйте хост `db`:

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/onboarding
```

## Локальный Запуск

Команды для PowerShell из корня проекта:

```powershell
cd C:\Users\Светлана\Downloads\ПРОМПТ_ИНЖЕНЕР\onboard-main

python -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -r requirements.txt

Copy-Item .env.example .env
```

После этого заполните `.env` реальными токенами и запустите:

```powershell
docker compose up -d db
```

Затем:

```powershell
python main.py
```

Если PowerShell запрещает активацию виртуального окружения, выполните:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## Запуск Через Docker

1. Заполните `.env`.
2. Запустите:

```powershell
docker compose up --build
```

## Структура Результата В БД

Таблица `training_results` содержит:

- `employee_name`
- `telegram_user_id`
- `telegram_chat_id`
- `topic`
- `total_questions`
- `correct_answers`
- `score_percent`
- `final_summary`
- `created_at`

## Пример Сценария

```text
Пользователь: /start
Бот: Выберите роль сотрудника: аудитор / оператор
Пользователь: аудитор
Бот: Роль выбрана. Напишите имя сотрудника, которого нужно обучить.
Пользователь: Иван Петров
Бот: Начинает обучение по инструкции аудитора.
Пользователь: Готов к тесту
Бот: Задает вопросы по одному.
...
Бот: Итог: 4/5 (80%).
Бот: Статус: Тест сдан. Порог сдачи: 80%.
```
