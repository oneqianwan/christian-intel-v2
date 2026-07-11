from __future__ import annotations

import json
import re
from typing import Any, Iterable, Optional
from urllib.parse import urlparse

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from models.database import OrganizationProfile


_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_PHONE_DATE_RE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}$")
_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)

_BLOCKED_EMAIL_EXACT = {
    "example@example.com",
    "test@test.com",
    "info@example.com",
    "admin@example.com",
    "contact@domain.com",
    "support@domain.com",
    "hello@example.com",
    "user@domain.com",
    "email@domain.com",
}
_BLOCKED_EMAIL_PREFIXES = ("noreply", "no-reply", "privacy", "abuse")
_GENERIC_EMAIL_PREFIXES = ("webmaster",)
_SOCIAL_HOST_RULES = {
    "facebook": {"facebook.com", "www.facebook.com", "fb.com", "www.fb.com"},
    "youtube": {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"},
    "telegram": {"t.me", "www.t.me", "telegram.me", "www.telegram.me"},
    "twitter": {"x.com", "www.x.com", "twitter.com", "www.twitter.com"},
    "linkedin": {"linkedin.com", "www.linkedin.com"},
    "whatsapp": {"wa.me", "www.wa.me", "whatsapp.com", "www.whatsapp.com"},
    "instagram": {"instagram.com", "www.instagram.com"},
    "tiktok": {"tiktok.com", "www.tiktok.com"},
}
_SOCIAL_BLOCKLIST_PATTERNS = {
    "facebook": ["/sharer", "share.php", "/login", "/dialog/", "/ads/", "business/help"],
    "youtube": ["/watch", "/playlist", "/results", "/redirect"],
    "telegram": ["/share", "/login"],
    "twitter": ["/share", "/intent/", "/login"],
    "linkedin": ["/share", "/login"],
    "whatsapp": ["/send?", "/share"],
}
_SOURCE_PRIORITY = {
    "contact_page": 4,
    "official_website": 3,
    "generic_page": 2,
    "social_page": 1,
    "unknown": 0,
}
_EXTRACTION_PRIORITY = {
    "regex": 3,
    "link_parser": 3,
    "crawler": 2,
    "rule_based": 2,
    "manual_seed": 2,
    "llm_suggested": 0,
    "unknown": 1,
}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_org_name(value: Any) -> str:
    raw = _normalize_text(value)
    raw = re.sub(r"[\s\-_.,，。:：;；!！?？/\\]+", " ", raw)
    return raw.lower().strip()


def _dedupe_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys([value for value in values if _normalize_text(value)]))


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


def _safe_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        numeric = float(value)
    except Exception:
        return None
    if numeric < 0:
        return 0.0
    if numeric > 1:
        return 1.0
    return numeric


def _normalize_host(host: str) -> str:
    lowered = _normalize_text(host).lower()
    return lowered[4:] if lowered.startswith("www.") else lowered


def _normalize_email(value: Any) -> Optional[str]:
    email = _normalize_text(value)
    if not email:
        return None
    if email.lower().startswith("mailto:"):
        email = email.split(":", 1)[-1]
    email = email.split("?", 1)[0].strip().lower()
    if not email:
        return None
    if not _EMAIL_RE.fullmatch(email):
        return None
    return email


def _is_placeholder_email(email: str) -> bool:
    lowered = _normalize_text(email).lower()
    if not lowered:
        return True
    if lowered in _BLOCKED_EMAIL_EXACT:
        return True
    local, _, domain = lowered.partition("@")
    if domain in {"example.com", "example.org", "example.net", "domain.com", "test.com"}:
        return True
    if any(local.startswith(prefix) for prefix in _BLOCKED_EMAIL_PREFIXES):
        return True
    return False


def _is_generic_email(email: str) -> bool:
    local = _normalize_text(email).lower().split("@", 1)[0]
    return any(local.startswith(prefix) for prefix in _GENERIC_EMAIL_PREFIXES)


def _normalize_phone(value: Any) -> Optional[str]:
    raw = _normalize_text(value)
    if not raw:
        return None
    collapsed = re.sub(r"\s+", " ", raw)
    collapsed = re.sub(r"\b(?:ext|extension)\.?\s*\d+\b", "", collapsed, flags=re.IGNORECASE).strip()
    if not collapsed or _PHONE_DATE_RE.fullmatch(collapsed):
        return None
    digits = re.sub(r"\D", "", collapsed)
    if len(digits) < 8 or len(digits) > 16:
        return None
    if len(set(digits)) == 1:
        return None
    if digits in {"12345678", "123456789", "1234567890"}:
        return None
    if re.fullmatch(r"\d{4,6}", digits):
        return None
    groups = re.findall(r"\d+", collapsed)
    if not groups:
        return None
    normalized = " ".join(groups)
    if collapsed.strip().startswith("+"):
        normalized = f"+{normalized}"
    if normalized.startswith("+00"):
        normalized = f"+{normalized[3:]}"
    if normalized.startswith("++"):
        normalized = f"+{normalized.lstrip('+')}"
    return normalized[:32]


def _extract_telegram_handle(raw: str) -> Optional[str]:
    cleaned = _normalize_text(raw).lstrip("@")
    if not cleaned:
        return None
    if cleaned.startswith(("http://", "https://")):
        parsed = urlparse(cleaned)
        path = (parsed.path or "").strip("/")
        if not path:
            return None
        cleaned = path.split("/", 1)[0]
    if not re.fullmatch(r"[A-Za-z0-9_]{3,32}", cleaned):
        return None
    return cleaned


def _normalize_url(value: Any, *, platform: Optional[str] = None) -> Optional[str]:
    raw = _normalize_text(value)
    if not raw:
        return None
    if re.search(r"\s", raw):
        return None

    normalized_platform = _normalize_text(platform).lower() or None
    if normalized_platform == "telegram":
        handle = _extract_telegram_handle(raw)
        if handle and not raw.startswith(("http://", "https://")):
            return f"https://t.me/{handle}"

    if not raw.startswith(("http://", "https://")):
        if "." in raw and " " not in raw:
            raw = f"https://{raw.lstrip('/')}"
        else:
            return None

    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    normalized_host = _normalize_host(parsed.netloc)
    normalized_url = raw.strip()

    if not normalized_platform:
        return normalized_url

    allowed_hosts = {_normalize_host(host) for host in _SOCIAL_HOST_RULES.get(normalized_platform, set())}
    if allowed_hosts and normalized_host not in allowed_hosts:
        return None

    blocked_patterns = [pattern.lower() for pattern in _SOCIAL_BLOCKLIST_PATTERNS.get(normalized_platform, [])]
    path_with_query = f"{parsed.path or ''}?{parsed.query or ''}".lower()
    if any(pattern in path_with_query for pattern in blocked_patterns):
        return None

    if normalized_platform == "youtube":
        path = (parsed.path or "").lower()
        if normalized_host == "youtu.be":
            return None
        if path and not path.startswith(("/@", "/channel/", "/c/", "/user/")):
            return None

    return normalized_url


def classify_contact_source(source_url: Any, organization_url: Any = None) -> str:
    normalized_source = _normalize_url(source_url)
    if not normalized_source:
        return "unknown"

    parsed = urlparse(normalized_source)
    host = _normalize_host(parsed.netloc)
    path = (parsed.path or "").lower()
    if any(host in {_normalize_host(item) for item in hosts} for hosts in _SOCIAL_HOST_RULES.values()):
        return "social_page"
    if any(token in path for token in ["/contact", "contact-us", "contactus", "get-in-touch", "reach-us", "locations", "find-us", "offices"]):
        return "contact_page"

    normalized_org = _normalize_url(organization_url)
    if normalized_org:
        org_parsed = urlparse(normalized_org)
        if _normalize_host(org_parsed.netloc) == host:
            org_path = (org_parsed.path or "").rstrip("/").lower()
            current_path = (parsed.path or "").rstrip("/").lower()
            if current_path in {"", "/"} or current_path == org_path:
                return "official_website"
            return "generic_page"
    return "generic_page"


def _base_candidate(
    *,
    candidate_type: str,
    value: Any,
    platform: Optional[str] = None,
    source_url: Any = None,
    source_name: Any = None,
    extraction_method: Any = "unknown",
    source_context: Any = None,
    confidence: Any = None,
    warnings: Optional[list[str]] = None,
) -> dict:
    base_source_url = _normalize_url(source_url)
    normalized_platform = _normalize_text(platform).lower() or None
    derived_context = _normalize_text(source_context).lower() or classify_contact_source(base_source_url, None)
    return {
        "type": "social_profile" if candidate_type == "social" else _normalize_text(candidate_type).lower(),
        "platform": normalized_platform,
        "value": _normalize_text(value),
        "normalized_value": None,
        "source_url": base_source_url,
        "source_name": _normalize_text(source_name) or None,
        "extraction_method": _normalize_text(extraction_method).lower() or "unknown",
        "source_context": derived_context if derived_context in _SOURCE_PRIORITY else "unknown",
        "confidence": _safe_float(confidence),
        "verification_status": "unverified",
        "is_verified": False,
        "warnings": _dedupe_strings(list(warnings or [])),
    }


def normalize_contact_candidate(candidate: dict, *, organization_url: Any = None) -> Optional[dict]:
    if not isinstance(candidate, dict):
        return None
    candidate_type = _normalize_text(candidate.get("type")).lower()
    if candidate_type == "social":
        candidate_type = "social_profile"
    if candidate_type not in {"website", "email", "phone", "social_profile"}:
        return None

    normalized = _base_candidate(
        candidate_type=candidate_type,
        value=candidate.get("value") or candidate.get("normalized_value"),
        platform=candidate.get("platform"),
        source_url=candidate.get("source_url"),
        source_name=candidate.get("source_name"),
        extraction_method=candidate.get("extraction_method") or "unknown",
        source_context=candidate.get("source_context") or classify_contact_source(candidate.get("source_url"), organization_url),
        confidence=candidate.get("confidence"),
        warnings=list(candidate.get("warnings") or []),
    )

    if candidate_type == "email":
        normalized_value = _normalize_email(normalized["value"])
    elif candidate_type == "phone":
        normalized_value = _normalize_phone(normalized["value"])
    elif candidate_type == "website":
        normalized_value = _normalize_url(normalized["value"])
    else:
        platform = normalized.get("platform")
        if not platform:
            return None
        normalized_value = _normalize_url(normalized["value"], platform=platform)
        if platform == "telegram" and normalized_value:
            normalized["value"] = _extract_telegram_handle(normalized["value"]) or normalized["value"]

    normalized["normalized_value"] = normalized_value
    if not normalized.get("source_url"):
        normalized["warnings"] = _dedupe_strings(normalized["warnings"] + ["source_url_missing"])
    normalized["verification_status"] = "unverified"
    normalized["is_verified"] = False
    return normalized


def validate_contact_candidate(candidate: dict, *, organization_url: Any = None) -> Optional[dict]:
    normalized = normalize_contact_candidate(candidate, organization_url=organization_url)
    if not normalized or not normalized.get("normalized_value"):
        return None

    warnings = list(normalized.get("warnings") or [])
    candidate_type = normalized["type"]
    extraction_method = normalized.get("extraction_method") or "unknown"
    source_context = normalized.get("source_context") or "unknown"

    if candidate_type == "email":
        email = normalized["normalized_value"]
        if _is_placeholder_email(email):
            return None
        if _is_generic_email(email):
            warnings.append("generic_email")

    if extraction_method == "llm_suggested":
        warnings.extend(["llm_suggested", "review_needed"])

    if source_context not in _SOURCE_PRIORITY:
        normalized["source_context"] = "unknown"

    base_confidence = {
        "contact_page": 0.8,
        "official_website": 0.72,
        "generic_page": 0.55,
        "social_page": 0.45,
        "unknown": 0.35,
    }.get(normalized["source_context"], 0.35)
    method_modifier = {
        "regex": 0.08,
        "link_parser": 0.08,
        "crawler": 0.03,
        "rule_based": 0.03,
        "manual_seed": 0.0,
        "llm_suggested": -0.2,
        "unknown": 0.0,
    }.get(extraction_method, 0.0)
    if "source_url_missing" in warnings:
        method_modifier -= 0.1
    normalized["confidence"] = max(0.0, min(1.0, base_confidence + method_modifier))
    normalized["warnings"] = _dedupe_strings(warnings)
    normalized["verification_status"] = "unverified"
    normalized["is_verified"] = False
    normalized["trusted_for_writeback"] = extraction_method != "llm_suggested" and "source_url_missing" not in normalized["warnings"]
    return normalized


def _candidate_rank(candidate: dict) -> tuple[int, int, int]:
    source_score = _SOURCE_PRIORITY.get(candidate.get("source_context") or "unknown", 0)
    extraction_score = _EXTRACTION_PRIORITY.get(candidate.get("extraction_method") or "unknown", 0)
    confidence_score = int((candidate.get("confidence") or 0.0) * 100)
    return source_score, extraction_score, confidence_score


def dedupe_contact_candidates(candidates: Iterable[dict], *, organization_url: Any = None) -> list[dict]:
    deduped: dict[tuple[str, str, str], dict] = {}
    for raw_candidate in candidates or []:
        validated = validate_contact_candidate(raw_candidate, organization_url=organization_url)
        if not validated:
            continue
        key = (
            validated["type"],
            validated.get("platform") or "",
            validated["normalized_value"].lower(),
        )
        existing = deduped.get(key)
        if existing is None or _candidate_rank(validated) > _candidate_rank(existing):
            merged = dict(validated)
            if existing:
                merged["warnings"] = _dedupe_strings(list(existing.get("warnings") or []) + list(validated.get("warnings") or []))
                if existing.get("source_url") and not merged.get("source_url"):
                    merged["source_url"] = existing.get("source_url")
                if existing.get("source_name") and not merged.get("source_name"):
                    merged["source_name"] = existing.get("source_name")
            deduped[key] = merged
        elif existing is not None:
            existing["warnings"] = _dedupe_strings(list(existing.get("warnings") or []) + list(validated.get("warnings") or []))
    return list(deduped.values())


def build_contact_candidates_from_crawl_result(
    crawl_result: dict,
    *,
    organization_url: Any = None,
    default_source_url: Any = None,
    default_source_name: Any = None,
    extraction_method: str = "regex",
    source_context: Optional[str] = None,
) -> list[dict]:
    if not isinstance(crawl_result, dict):
        return []

    base_source_url = crawl_result.get("source_url") or default_source_url
    base_source_name = crawl_result.get("source_name") or default_source_name
    derived_context = source_context or crawl_result.get("source_context") or classify_contact_source(base_source_url, organization_url)

    raw_candidates: list[dict] = []

    def append_values(candidate_type: str, values: Any, *, platform: Optional[str] = None, method: Optional[str] = None) -> None:
        if values is None:
            return
        items = values if isinstance(values, list) else [values]
        for item in items:
            if not _normalize_text(item):
                continue
            raw_candidates.append(
                {
                    "type": candidate_type,
                    "platform": platform,
                    "value": item,
                    "source_url": base_source_url,
                    "source_name": base_source_name,
                    "extraction_method": method or extraction_method,
                    "source_context": derived_context,
                    "warnings": [],
                }
            )

    append_values("website", crawl_result.get("official_website"))
    append_values("email", crawl_result.get("emails"))
    append_values("email", crawl_result.get("contact_email"))
    append_values("email", crawl_result.get("general_email"))
    append_values("phone", crawl_result.get("phones"))
    append_values("phone", crawl_result.get("contact_phone"))
    append_values("phone", crawl_result.get("phone_public"))
    append_values("phone", crawl_result.get("general_phone"))

    social_field_map = {
        "facebook_url": "facebook",
        "youtube_url": "youtube",
        "twitter_url": "twitter",
        "telegram_username": "telegram",
    }
    for field_name, platform in social_field_map.items():
        append_values("social_profile", crawl_result.get(field_name), platform=platform, method="link_parser" if platform != "telegram" else extraction_method)

    social_accounts = crawl_result.get("social_accounts")
    if isinstance(social_accounts, dict):
        for platform, value in social_accounts.items():
            append_values("social_profile", value, platform=_normalize_text(platform).lower() or None, method="link_parser")
    elif isinstance(social_accounts, list):
        for item in social_accounts:
            if not isinstance(item, dict):
                continue
            platform = _normalize_text(item.get("platform") or item.get("type") or item.get("name")).lower() or None
            value = item.get("url") or item.get("value") or item.get("username") or item.get("handle")
            append_values("social_profile", value, platform=platform, method="link_parser")

    return dedupe_contact_candidates(raw_candidates, organization_url=organization_url)


def extract_contact_candidates_from_text(
    text: str,
    *,
    source_url: Any,
    source_name: Any = None,
    organization_url: Any = None,
    source_context: Optional[str] = None,
) -> list[dict]:
    content = text or ""
    emails = re.findall(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", content)
    phones = re.findall(r"(\+?\d[\d\s\-\(\)]{7,}\d)", content)
    social_accounts: dict[str, str] = {}
    for url in _URL_RE.findall(content):
        lowered = url.lower()
        if "facebook.com" in lowered or "fb.com" in lowered:
            social_accounts.setdefault("facebook", url)
        elif "youtube.com" in lowered or "youtu.be" in lowered:
            social_accounts.setdefault("youtube", url)
        elif "t.me/" in lowered or "telegram.me/" in lowered:
            social_accounts.setdefault("telegram", url)
        elif "twitter.com" in lowered or "x.com" in lowered:
            social_accounts.setdefault("twitter", url)
        elif "linkedin.com" in lowered:
            social_accounts.setdefault("linkedin", url)
        elif "wa.me/" in lowered or "whatsapp.com" in lowered:
            social_accounts.setdefault("whatsapp", url)
    return build_contact_candidates_from_crawl_result(
        {
            "emails": emails,
            "phones": phones,
            "social_accounts": social_accounts,
            "source_url": source_url,
            "source_name": source_name,
            "source_context": source_context or classify_contact_source(source_url, organization_url),
        },
        organization_url=organization_url,
        extraction_method="regex",
    )


def _candidate_storage_value(candidate: dict) -> str:
    if candidate.get("platform") == "telegram":
        return _extract_telegram_handle(candidate.get("value") or candidate.get("normalized_value") or "") or candidate["normalized_value"]
    return candidate["normalized_value"]


def _existing_field_normalized(field_name: str, value: Any) -> Optional[str]:
    if field_name == "contact_email":
        return _normalize_email(value)
    if field_name == "phone_public":
        return _normalize_phone(value)
    if field_name == "official_website":
        return _normalize_url(value)
    if field_name == "facebook_url":
        return _normalize_url(value, platform="facebook")
    if field_name == "youtube_url":
        return _normalize_url(value, platform="youtube")
    if field_name == "twitter_url":
        return _normalize_url(value, platform="twitter")
    if field_name == "telegram_username":
        return _normalize_url(value, platform="telegram")
    return _normalize_text(value) or None


def _candidate_field_name(candidate: dict) -> Optional[str]:
    if candidate["type"] == "website":
        return "official_website"
    if candidate["type"] == "email":
        return "contact_email"
    if candidate["type"] == "phone":
        return "phone_public"
    if candidate["type"] == "social_profile":
        platform = candidate.get("platform")
        return {
            "facebook": "facebook_url",
            "youtube": "youtube_url",
            "twitter": "twitter_url",
            "telegram": "telegram_username",
        }.get(platform)
    return None


def apply_validated_contact_candidates_to_org(
    org: OrganizationProfile,
    candidates: Iterable[dict],
    *,
    change_source: str,
    changed_by: str = "system",
    db: Optional[Session] = None,
) -> dict[str, list[str]]:
    validated_candidates = dedupe_contact_candidates(candidates, organization_url=org.official_website)
    writeback_candidates = [candidate for candidate in validated_candidates if candidate.get("trusted_for_writeback")]
    selected: dict[str, dict] = {}
    for candidate in writeback_candidates:
        field_name = _candidate_field_name(candidate)
        if not field_name:
            continue
        existing_selected = selected.get(field_name)
        if existing_selected is None or _candidate_rank(candidate) > _candidate_rank(existing_selected):
            selected[field_name] = candidate

    results = {"updated_fields": [], "skipped_fields": []}
    if not selected:
        return results

    from services.history_recorder import build_change_source_tag, record_change

    existing_context = classify_contact_source(getattr(org, "source_url", None), getattr(org, "official_website", None))

    for field_name, candidate in selected.items():
        storage_value = _candidate_storage_value(candidate)
        current_value = getattr(org, field_name)
        current_normalized = _existing_field_normalized(field_name, current_value)
        candidate_normalized = _existing_field_normalized(field_name, storage_value)
        if not candidate_normalized:
            results["skipped_fields"].append(field_name)
            continue
        if current_normalized == candidate_normalized:
            results["skipped_fields"].append(field_name)
            continue

        should_update = False
        if not current_normalized:
            should_update = True
        else:
            current_is_invalid = _existing_field_normalized(field_name, current_value) is None
            candidate_priority = _SOURCE_PRIORITY.get(candidate.get("source_context") or "unknown", 0)
            existing_priority = _SOURCE_PRIORITY.get(existing_context, 0)
            if current_is_invalid:
                should_update = True
            elif candidate_priority > existing_priority:
                should_update = True

        if not should_update:
            results["skipped_fields"].append(field_name)
            continue

        setattr(org, field_name, storage_value)
        if not _normalize_text(getattr(org, "source_url", None)) and candidate.get("source_url"):
            org.source_url = candidate.get("source_url")
        if not _normalize_text(getattr(org, "source_name", None)) and candidate.get("source_name"):
            org.source_name = candidate.get("source_name")
        record_change(
            org.id,
            field_name,
            current_value,
            storage_value,
            source=build_change_source_tag(
                change_source,
                source_url=candidate.get("source_url"),
                extraction_method=candidate.get("extraction_method"),
                source_context=candidate.get("source_context"),
            ),
            changed_by=changed_by,
            db=db,
        )
        results["updated_fields"].append(field_name)
    return results


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
