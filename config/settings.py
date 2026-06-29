from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str = Field(..., alias="BOT_TOKEN")
    database_url: str = Field(..., alias="DATABASE_URL")
    openai_api_key: str = Field(..., alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4.1-mini", alias="OPENAI_MODEL")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    training_topic: str = Field(default="Корпоративный онбординг", alias="TRAINING_TOPIC")
    training_material: str = Field(
        default=(
            "Компания использует асинхронную коммуникацию по умолчанию. "
            "Все задачи ведутся через трекер, важные решения фиксируются письменно, "
            "а эскалации блокеров ожидаются в течение 30 минут. "
            "Перед релизом нужны code review, зеленые тесты и короткая запись в changelog."
        ),
        alias="TRAINING_MATERIAL",
    )
    training_material_file: str | None = Field(default=None, alias="TRAINING_MATERIAL_FILE")
    training_auditor_material_file: str = Field(default="./materials/auditor.txt", alias="TRAINING_AUDITOR_MATERIAL_FILE")
    training_operator_material_file: str = Field(default="./materials/operator.txt", alias="TRAINING_OPERATOR_MATERIAL_FILE")
    training_auditor_quiz_file: str = Field(default="./materials/tests/auditor.json", alias="TRAINING_AUDITOR_QUIZ_FILE")
    training_operator_quiz_file: str = Field(default="./materials/tests/operator.json", alias="TRAINING_OPERATOR_QUIZ_FILE")
    passing_score_percent: int = Field(default=80, alias="PASSING_SCORE_PERCENT", ge=0, le=100)
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @staticmethod
    def _read_material_file(path: str) -> str:
        return Path(path).read_text(encoding="utf-8").strip()

    def get_training_material(self, employee_role: str | None = None) -> str:
        role_material_files = {
            "auditor": self.training_auditor_material_file,
            "operator": self.training_operator_material_file,
        }

        if employee_role in role_material_files:
            return self._read_material_file(role_material_files[employee_role])

        if self.training_material_file:
            return self._read_material_file(self.training_material_file)
        return self.training_material.strip()

    def get_quiz_file(self, employee_role: str | None = None) -> str:
        role_quiz_files = {
            "auditor": self.training_auditor_quiz_file,
            "operator": self.training_operator_quiz_file,
        }
        return role_quiz_files.get(employee_role, self.training_operator_quiz_file)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
