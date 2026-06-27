from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://intel:intel123@localhost:5432/christian_intel"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
