from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    gemini_api_key: str = ""
    openai_api_key: str = ""
    gemini_live_model: str = "gemini-3.1-flash-live-preview"
    gemini_text_model: str = "gemini-2.5-flash"
    openai_model: str = "gpt-5.6-luna"
    openai_model_complex: str = "gpt-5.6-terra"
    mock_mode: bool = True
    synthesis_mock: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def set_default_mock_mode(self) -> "Settings":
        if "mock_mode" not in self.model_fields_set:
            self.mock_mode = not bool(self.gemini_api_key)
        if "synthesis_mock" not in self.model_fields_set:
            self.synthesis_mock = not bool(self.openai_api_key)
        return self


settings = Settings()
