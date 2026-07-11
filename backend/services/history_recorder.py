import logging

from models.database import FieldChangeHistory, SessionLocal

logger = logging.getLogger(__name__)

# 仅追踪高价值字段，避免把无关噪音写入 History Layer。
TRACKED_FIELDS = [
    "leader_name",
    "leader_title",
    "official_website",
    "description",
    "about_text",
    "mission_statement",
    "contact_email",
    "phone_public",
    "facebook_url",
    "youtube_url",
    "twitter_url",
    "telegram_username",
    "social_accounts_json",
    "social_accounts",
    "ai_maturity_score",
    "digital_score",
    "has_programs",
    "has_leadership_page",
    "has_annual_report",
]


def build_change_source_tag(
    source: str = "unknown",
    *,
    source_url: str | None = None,
    extraction_method: str | None = None,
    source_context: str | None = None,
) -> str:
    parts = [str(source or "unknown").strip() or "unknown"]
    if extraction_method:
        parts.append(f"method={str(extraction_method).strip()}")
    if source_context:
        parts.append(f"context={str(source_context).strip()}")
    if source_url:
        parts.append(f"url={str(source_url).strip()[:180]}")
    return "|".join(parts)[:255]


def record_change(
    org_id: str,
    field_name: str,
    old_value,
    new_value,
    source: str = "unknown",
    changed_by: str = "system",
    db=None,
) -> None:
    """记录单个字段变更。"""
    if field_name not in TRACKED_FIELDS:
        return

    old_str = str(old_value)[:500] if old_value is not None else None
    new_str = str(new_value)[:500] if new_value is not None else None

    if old_str == new_str:
        return
    if old_value is None and new_value is None:
        return

    owns_session = db is None
    db = db or SessionLocal()
    try:
        history = FieldChangeHistory(
            organization_id=org_id,
            field_name=field_name,
            old_value=old_str,
            new_value=new_str,
            change_source=source,
            changed_by=changed_by,
        )
        db.add(history)
        if owns_session:
            db.commit()
    except Exception as exc:
        if owns_session:
            db.rollback()
        logger.error("History record failed: %s", exc)
    finally:
        if owns_session:
            db.close()


def record_org_changes(org, source: str = "unknown", changed_by: str = "system") -> None:
    """预留给 ORM hook 或批量更新逻辑调用。"""
    return None
