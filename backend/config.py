from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parent

class Settings(BaseSettings):
    DATABASE_URL: str = f"sqlite:///{(BACKEND_DIR / 'cio_intelligence.db').as_posix()}"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def normalize_database_url(self):
        if self.DATABASE_URL.startswith("sqlite:///"):
            raw_path = self.DATABASE_URL[len("sqlite:///") :]
            db_path = Path(raw_path)
            if not db_path.is_absolute():
                self.DATABASE_URL = f"sqlite:///{(BACKEND_DIR / db_path).resolve().as_posix()}"
        return self

settings = Settings()
