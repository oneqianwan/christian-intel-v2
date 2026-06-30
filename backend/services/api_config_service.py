import base64
import hashlib
import json
import os
from datetime import datetime
from typing import Any

from cryptography.fernet import Fernet
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.orm import Session

from models.database import ApiConfig, SessionLocal, init_db

load_dotenv(override=True)


MASTER_KEY_ENV = "API_CONFIG_MASTER_KEY"
ENV_FALLBACKS = {
    "newsapi": ["NEWSAPI_KEY", "NEWS_API_KEY"],
    "youtube": ["YOUTUBE_API_KEY", "GOOGLE_CSE_API_KEY"],
    "google_cse": ["GOOGLE_CSE_API_KEY", "YOUTUBE_API_KEY"],
    "scrapingbee": ["SCRAPINGBEE_API_KEY"],
    "deepseek": ["DEEPSEEK_API_KEY"],
}


def _derive_fernet_key(raw_value: str) -> bytes:
    digest = hashlib.sha256(raw_value.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def get_cipher() -> Fernet:
    raw_value = os.getenv(MASTER_KEY_ENV, "").strip()
    if not raw_value:
        raise RuntimeError(f"缺少环境变量 {MASTER_KEY_ENV}")
    return Fernet(_derive_fernet_key(raw_value))


def mask_key(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}***{value[-4:]}"


def ensure_api_config_schema() -> None:
    init_db()
    db = SessionLocal()
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS api_configs (
                id SERIAL PRIMARY KEY,
                api_name VARCHAR(50) UNIQUE NOT NULL,
                encrypted_api_key TEXT,
                key_hint VARCHAR(16),
                extra_config JSON DEFAULT '{}',
                status VARCHAR(20) DEFAULT 'unknown',
                usage_info TEXT,
                last_checked TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """))
        db.commit()
    finally:
        db.close()


def save_api_config(
    db: Session,
    api_name: str,
    api_key: str,
    extra_config: dict[str, Any] | None = None,
    status: str = "configured",
) -> ApiConfig:
    cipher = get_cipher()
    encrypted = cipher.encrypt(api_key.encode("utf-8")).decode("utf-8")
    config = db.query(ApiConfig).filter(ApiConfig.api_name == api_name).first()
    if not config:
        config = ApiConfig(api_name=api_name)
        db.add(config)

    config.encrypted_api_key = encrypted
    config.key_hint = mask_key(api_key)
    config.extra_config = extra_config or {}
    config.status = status
    config.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(config)
    return config


def get_api_config(db: Session, api_name: str) -> dict[str, Any] | None:
    config = db.query(ApiConfig).filter(ApiConfig.api_name == api_name).first()
    if not config:
        return None

    decrypted_key = ""
    if config.encrypted_api_key:
        cipher = get_cipher()
        decrypted_key = cipher.decrypt(config.encrypted_api_key.encode("utf-8")).decode("utf-8")

    extra_config = config.extra_config or {}
    if isinstance(extra_config, str):
        try:
            extra_config = json.loads(extra_config)
        except Exception:
            extra_config = {}

    return {
        "api_name": config.api_name,
        "api_key": decrypted_key,
        "key_hint": config.key_hint or "",
        "extra_config": extra_config,
        "status": config.status or "unknown",
        "usage_info": config.usage_info,
        "last_checked": config.last_checked,
    }


def update_api_status(
    db: Session,
    api_name: str,
    status: str,
    usage_info: str | None = None,
) -> None:
    config = db.query(ApiConfig).filter(ApiConfig.api_name == api_name).first()
    if not config:
        return
    config.status = status
    config.last_checked = datetime.utcnow()
    if usage_info is not None:
        config.usage_info = usage_info
    config.updated_at = datetime.utcnow()
    db.commit()


def save_api_key(
    db: Session,
    api_name: str,
    api_key: str,
    extra_config: dict[str, Any] | None = None,
    status: str = "configured",
) -> ApiConfig:
    return save_api_config(db, api_name, api_key, extra_config, status=status)


def get_api_key(db: Session, api_name: str) -> str:
    config = get_api_config(db, api_name)
    stored_key = (config or {}).get("api_key", "")
    if stored_key:
        return stored_key

    for env_name in ENV_FALLBACKS.get(api_name, []):
        env_value = os.getenv(env_name, "").strip()
        if env_value:
            return env_value
    return ""


def test_api_key(db: Session, api_name: str) -> dict[str, Any] | None:
    return get_api_config(db, api_name)
