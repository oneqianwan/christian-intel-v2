from __future__ import annotations

import json
import re
from typing import Any, Iterable, Optional
from urllib.parse import urlparse

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from models.database import OrganizationProfile


_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_org_name(value: Any) -> str:
    raw = _normalize_text(value)
    raw = re.sub(r"[\s\-_.,，。:：;；!！?？/\\]+", " ", raw)
    return raw.lower().strip()


def _organization_payload(org: OrganizationProfile) -> dict:
    return {
        "id": org.id,
        "name": org.name,
        "source_url": _normalize_text(org.source_url) or None,
        "source_name": _normalize_text(org.source_name) or None,
        "organization_confidence": float(org.confidence) if org.confidence is not None else None,
        "updated_at": org.updated_at,
    }


def _empty_summary() -> dict:
    return {
        "contact_count": 0,
        "email_count": 0,
        "phone_count": 0,
        "social_count": 0,
        "website_count": 0,
        "verified_count": 0,
        "missing_source_count": 0,
        "outreach_candidate_count": 0,
    }


def _empty_payload(*, warnings: list[str], found: bool, organization: Optional[dict] = None) -> dict:
    return {
        "organization": organization,
        "contacts": [],
        "summary": _empty_summary(),
        "warnings": list(dict.fromkeys(warnings)),
        "found": found,
    }


def _safe_json_loads(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    text = _normalize_text(raw)
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _normalize_email(value: Any) -> Optional[str]:
    email = _normalize_text(value).lower()
    if not email:
        return None
    if not _EMAIL_RE.fullmatch(email):
        return None
    return email


def _normalize_phone(value: Any) -> Optional[str]:
    raw = _normalize_text(value)
    if not raw:
        return None
    collapsed = re.sub(r"\s+", " ", raw)
    digits = re.sub(r"\D", "", collapsed)
    if len(digits) < 7:
        return None
    normalized = re.sub(r"[^0-9+()\-\s]", "", collapsed).strip()
    if normalized.startswith("++"):
        normalized = normalized.lstrip("+")
    if not re.search(r"\d", normalized):
        return None
    return normalized[:50]


def _normalize_url(value: Any, *, platform: Optional[str] = None) -> Optional[str]:
    raw = _normalize_text(value)
    if not raw:
        return None
    if re.search(r"\s", raw):
        return None

    if platform == "telegram":
        cleaned = raw.lstrip("@")
        if cleaned.startswith(("http://", "https://")):
            raw = cleaned
        elif re.fullmatch(r"[A-Za-z0-9_]{3,}", cleaned):
            raw = f"https://t.me/{cleaned}"
        else:
            return None

    if not raw.startswith(("http://", "https://")):
        if platform and platform in {"facebook", "youtube", "twitter", "linkedin", "whatsapp", "instagram", "tiktok"}:
            raw = f"https://{raw.lstrip('/')}"
        elif "." in raw and " " not in raw:
            raw = f"https://{raw}"
        else:
            return None

    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        return None
    if not parsed.netloc:
        return None
    return raw.strip()


def _iter_social_candidates(org: OrganizationProfile) -> Iterable[tuple[str, Any]]:
    direct_fields = [
        ("facebook", org.facebook_url),
        ("youtube", org.youtube_url),
        ("twitter", org.twitter_url),
        ("telegram", org.telegram_username),
    ]
    for platform, value in direct_fields:
        if _normalize_text(value):
            yield platform, value

    for payload in (_safe_json_loads(org.social_accounts_json), _safe_json_loads(org.social_accounts)):
        if isinstance(payload, dict):
            for platform, value in payload.items():
                if _normalize_text(value):
                    yield _normalize_text(platform).lower(), value
        elif isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    continue
                platform = _normalize_text(item.get("platform") or item.get("type") or item.get("name")).lower()
                value = item.get("url") or item.get("value") or item.get("username") or item.get("handle")
                if platform and _normalize_text(value):
                    yield platform, value


def _build_contact_item(
    *,
    contact_id: str,
    contact_type: str,
    label: str,
    value: str,
    normalized_value: str,
    usage: str,
    platform: Optional[str],
    org: OrganizationProfile,
    extra_warnings: Optional[list[str]] = None,
) -> dict:
    warnings = ["field_level_source_missing", "field_level_confidence_missing", "field_level_verification_missing"]
    if extra_warnings:
        warnings.extend(extra_warnings)
    return {
        "id": contact_id,
        "type": contact_type,
        "label": label,
        "value": value,
        "normalized_value": normalized_value,
        "platform": platform,
        "source_url": _normalize_text(org.source_url) or None,
        "source_name": _normalize_text(org.source_name) or None,
        "confidence": None,
        "verification_status": "unverified",
        "is_verified": False,
        "usage": usage,
        "warnings": list(dict.fromkeys(warnings)),
    }


def _resolve_organization(
    db: Session,
    *,
    org_id: Optional[str] = None,
    organization_name: Optional[str] = None,
) -> Optional[OrganizationProfile]:
    if _normalize_text(org_id):
        return db.query(OrganizationProfile).filter(OrganizationProfile.id == _normalize_text(org_id)).first()

    name = _normalize_text(organization_name)
    if not name:
        return None

    lowered = name.lower()
    exact = (
        db.query(OrganizationProfile)
        .filter(
            or_(
                func.lower(OrganizationProfile.name) == lowered,
                func.lower(OrganizationProfile.english_name) == lowered,
                func.lower(OrganizationProfile.short_name) == lowered,
            )
        )
        .first()
    )
    if exact:
        return exact

    normalized_name = _normalize_org_name(name)
    for org in db.query(OrganizationProfile).all():
        candidates = [org.name, org.english_name, org.short_name]
        if any(_normalize_org_name(candidate) == normalized_name for candidate in candidates if _normalize_text(candidate)):
            return org
    return None


def build_organization_contact_payload(
    *,
    db: Session,
    org_id: Optional[str] = None,
    organization_name: Optional[str] = None,
    include_unverified: bool = True,
) -> dict:
    org = _resolve_organization(db, org_id=org_id, organization_name=organization_name)
    if not org:
        return _empty_payload(warnings=["not_found"], found=False, organization=None)

    payload_warnings: list[str] = []
    organization = _organization_payload(org)
    contacts: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    counters: dict[str, int] = {}

    def register(
        *,
        contact_type: str,
        label: str,
        value: str,
        normalized_value: str,
        usage: str,
        platform: Optional[str] = None,
        extra_warnings: Optional[list[str]] = None,
    ) -> None:
        dedup_key = (contact_type, platform or "", normalized_value.lower())
        if dedup_key in seen:
            return
        seen.add(dedup_key)
        counter_key = f"{contact_type}:{platform or ''}"
        counters[counter_key] = counters.get(counter_key, 0) + 1
        if contact_type == "social_profile":
            contact_id = f"social:{platform}:{counters[counter_key]}"
        else:
            contact_id = f"{contact_type}:{counters[counter_key]}"
        contacts.append(
            _build_contact_item(
                contact_id=contact_id,
                contact_type=contact_type,
                label=label,
                value=value,
                normalized_value=normalized_value,
                usage=usage,
                platform=platform,
                org=org,
                extra_warnings=extra_warnings,
            )
        )

    website_value = _normalize_text(org.official_website)
    if website_value:
        normalized_website = _normalize_url(website_value)
        if normalized_website:
            register(
                contact_type="website",
                label="Official website",
                value=website_value,
                normalized_value=normalized_website,
                usage="research",
            )
        else:
            payload_warnings.append("invalid_url_format")

    email_value = _normalize_text(org.contact_email)
    if email_value:
        normalized_email = _normalize_email(email_value)
        if normalized_email:
            register(
                contact_type="email",
                label="Public email",
                value=email_value,
                normalized_value=normalized_email,
                usage="outreach_candidate",
            )
        else:
            payload_warnings.append("invalid_email_format")

    phone_value = _normalize_text(org.phone_public)
    if phone_value:
        normalized_phone = _normalize_phone(phone_value)
        if normalized_phone:
            register(
                contact_type="phone",
                label="Public phone",
                value=phone_value,
                normalized_value=normalized_phone,
                usage="outreach_candidate",
            )
        else:
            payload_warnings.append("invalid_phone_format")

    platform_labels = {
        "facebook": "Facebook",
        "youtube": "YouTube",
        "twitter": "Twitter",
        "telegram": "Telegram",
        "linkedin": "LinkedIn",
        "whatsapp": "WhatsApp",
        "instagram": "Instagram",
        "tiktok": "TikTok",
    }
    for platform, raw_value in _iter_social_candidates(org):
        normalized_social = _normalize_url(raw_value, platform=platform)
        if not normalized_social:
            payload_warnings.append("invalid_url_format")
            continue
        register(
            contact_type="social_profile",
            label=platform_labels.get(platform, platform.title() or "Social profile"),
            value=_normalize_text(raw_value),
            normalized_value=normalized_social,
            usage="research",
            platform=platform,
            extra_warnings=["officiality_not_verified"],
        )

    if not include_unverified:
        contacts = [contact for contact in contacts if contact.get("is_verified") is True]
        payload_warnings.append("unverified_contacts_filtered")

    if any("field_level_source_missing" in contact["warnings"] for contact in contacts):
        payload_warnings.append("field_level_source_not_available")
    if any("field_level_confidence_missing" in contact["warnings"] for contact in contacts):
        payload_warnings.append("field_level_confidence_not_available")
    if any("field_level_verification_missing" in contact["warnings"] for contact in contacts):
        payload_warnings.append("field_level_verification_not_available")

    if not contacts:
        payload_warnings.append("contact_missing")

    summary = {
        "contact_count": len(contacts),
        "email_count": sum(1 for contact in contacts if contact["type"] == "email"),
        "phone_count": sum(1 for contact in contacts if contact["type"] == "phone"),
        "social_count": sum(1 for contact in contacts if contact["type"] == "social_profile"),
        "website_count": sum(1 for contact in contacts if contact["type"] == "website"),
        "verified_count": sum(1 for contact in contacts if contact["is_verified"] is True),
        "missing_source_count": sum(1 for contact in contacts if "field_level_source_missing" in contact["warnings"]),
        "outreach_candidate_count": sum(1 for contact in contacts if contact["usage"] == "outreach_candidate"),
    }

    return {
        "organization": organization,
        "contacts": contacts,
        "summary": summary,
        "warnings": list(dict.fromkeys(payload_warnings)),
        "found": True,
    }
