from typing import Annotated, Literal

from pydantic import BeforeValidator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    gemini_api_key: str = ""
    openai_api_key: str = ""
    gemini_live_model: str = "gemini-3.1-flash-live-preview"
    gemini_text_model: str = "gemini-2.5-flash"
    openai_model: str = "gpt-5.6-luna"
    openai_model_complex: str = "gpt-5.6-luna"
    openai_reasoning_model: str = "gpt-5.4-mini"
    openai_transcribe_model: str = "gpt-4o-mini-transcribe"
    mock_mode: bool = True
    synthesis_mock: bool = True
    live_provider: Annotated[
        Literal["gemini", "openai", "mock"],
        BeforeValidator(lambda value: value or "mock"),
    ] = "mock"
    data_dir: str = "data"
    context_before_seconds: float = 20.0
    context_after_seconds: float = 30.0
    buffer_seconds: float = 60.0
    record_dir: str = "data/sessions"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def set_default_mock_mode(self) -> "Settings":
        if "mock_mode" not in self.model_fields_set:
            self.mock_mode = not bool(self.gemini_api_key or self.openai_api_key)
        if "synthesis_mock" not in self.model_fields_set:
            self.synthesis_mock = not bool(self.openai_api_key)
        if self.mock_mode:
            self.live_provider = "mock"
        elif "live_provider" not in self.model_fields_set:
            if self.gemini_api_key:
                self.live_provider = "gemini"
            elif self.openai_api_key:
                self.live_provider = "openai"
            else:
                self.live_provider = "mock"
        return self


settings = Settings()
