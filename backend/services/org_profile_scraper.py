import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from models.database import OrganizationProfile
from services.contact_intelligence import (
    apply_validated_contact_candidates_to_org,
    build_contact_candidates_from_crawl_result,
)


PH_ORGANIZATION_SEEDS = [
    {
        "name": "Philippine Council of Evangelical Churches",
        "name_local": "",
        "country": "菲律宾",
        "website": "https://pcec.org.ph",
        "leader_title_hint": ["President", "Bishop", "Chairman"],
        "denomination": "Evangelical Alliance",
    },
    {
        "name": "Christ's Commission Fellowship",
        "name_local": "",
        "country": "菲律宾",
        "website": "https://ccf.org.ph",
        "leader_title_hint": ["Senior Pastor", "Founding Pastor", "Lead Pastor"],
        "denomination": "Independent",
    },
    {
        "name": "Victory Philippines",
        "name_local": "",
        "country": "菲律宾",
        "website": "https://victory.org.ph",
        "leader_title_hint": ["Senior Pastor", "Lead Pastor"],
        "denomination": "Evangelical",
    },
    {
        "name": "Philippine Bible Society",
        "name_local": "",
        "country": "菲律宾",
        "website": "https://philbible.org.ph",
        "leader_title_hint": ["General Secretary", "Executive Director", "President", "CEO"],
        "denomination": "Interdenominational",
    },
    {
        "name": "Jesus is Lord Church Worldwide",
        "name_local": "",
        "country": "菲律宾",
        "website": "https://jilworldwide.org",
        "leader_title_hint": ["Founder", "President", "Bishop", "Pastor"],
        "denomination": "Pentecostal",
    },
]


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _is_probable_person_name(name: str) -> bool:
    n = _normalize_text(name)
    if not n or len(n) < 5 or len(n) > 60:
        return False
    if any(bad in n.lower() for bad in ["document", "documents", "executive", "governing", "our ", "from ", "about", "who we are"]):
        return False
    if re.search(r"\d", n):
        return False
    if n.isupper():
        return False
    if not re.fullmatch(r"[A-Za-z .,'’\\-]+", n):
        return False
    if re.search(r"\b(Team|Leadership|Leaders|Staff|Board|Office|Contact|Committee|Convention|Administration|Assembly|Department)\b", n, re.IGNORECASE):
        return False

    raw_tokens = [t.strip(" ,") for t in n.split() if t.strip(" ,")]
    if len(raw_tokens) < 2 or len(raw_tokens) > 4:
        return False

    stopwords = {"of", "the", "and", "for", "to", "in", "on", "at", "a", "an"}
    if any(t.lower().strip(".") in stopwords for t in raw_tokens):
        return False

    title_words = {
        "president",
        "director",
        "secretary",
        "bishop",
        "pastor",
        "rev",
        "reverend",
        "chief",
        "executive",
        "vice",
        "chairman",
        "administrator",
        "admin",
        "lead",
        "senior",
        "metropolitan",
    }
    if any(t.lower().strip(".") in title_words for t in raw_tokens):
        return False

    for t in raw_tokens:
        if re.fullmatch(r"[A-Z]\\.", t):
            continue
        if not re.fullmatch(r"[A-Z][a-zA-Z'’\\-]+", t):
            return False

    return True


def _extract_emails(text: str) -> List[str]:
    if not text:
        return []
    email_pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
    emails = re.findall(email_pattern, text)
    seen = set()
    out: List[str] = []
    blocked_tlds = {"jpg", "jpeg", "png", "gif", "webp", "svg", "pdf", "mp4", "mov"}
    for e in emails:
        el = e.lower().strip()
        tld = el.rsplit(".", 1)[-1] if "." in el else ""
        if tld in blocked_tlds:
            continue
        if "/" in el or "\\" in el:
            continue
        if el in seen:
            continue
        seen.add(el)
        out.append(e.strip())
    return out


def _pick_best_email(emails: List[str]) -> Optional[str]:
    if not emails:
        return None
    priority = ["info", "office", "contact", "admin", "communications", "media"]
    for kw in priority:
        for e in emails:
            if kw in e.lower():
                return e
    return emails[0]


def _extract_phones(text: str) -> List[str]:
    if not text:
        return []
    phone_pattern = r"(\+?\d[\d\s\-\(\)]{7,}\d)"
    candidates = re.findall(phone_pattern, text)
    cleaned: List[str] = []
    seen = set()
    for c in candidates:
        v = _normalize_text(c)[:80]
        if v in seen:
            continue
        seen.add(v)
        cleaned.append(v)
    return cleaned


def _pick_best_phone(phones: List[str]) -> Optional[str]:
    if not phones:
        return None
    candidates: List[str] = []
    for p in phones:
        s = _normalize_text(p)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            continue
        digits = re.sub(r"\D", "", s)
        if len(digits) < 9 or len(digits) > 16:
            continue
        candidates.append(s)
    if not candidates:
        return None
    for p in candidates:
        if p.strip().startswith("+"):
            return p[:50]
    for p in candidates:
        if any(ch in p for ch in ["(", ")", "-", " "]):
            return p[:50]
    return None


def _extract_social_links(soup: BeautifulSoup) -> Dict[str, Optional[str]]:
    facebook = None
    youtube = None
    telegram = None
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        low = href.lower()
        if not facebook and "facebook.com" in low:
            facebook = href
        if not youtube and ("youtube.com" in low or "youtu.be" in low):
            youtube = href
        if not telegram and ("t.me/" in low or "telegram.me/" in low):
            telegram = href
    return {"facebook_url": facebook, "youtube_url": youtube, "telegram_username": telegram}


def _find_candidate_links(soup: BeautifulSoup, base_url: str, keywords: List[str], limit: int = 10) -> List[Tuple[str, str]]:
    hits: List[Tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        raw_href = (a.get("href") or "").strip()
        if not raw_href:
            continue
        text = _normalize_text(a.get_text(" ", strip=True))
        href = urljoin(base_url, raw_href)
        low = (raw_href + " " + text).lower()
        if any(k in low for k in keywords):
            hits.append((text, href))
        if len(hits) >= limit:
            break
    return hits


def _extract_leader_from_page(soup: BeautifulSoup, title_hints: List[str]) -> Tuple[Optional[str], Optional[str]]:
    hints = [h.lower() for h in (title_hints or []) if h]
    if not hints:
        hints = ["pastor", "president", "bishop", "chairman", "director", "secretary"]

    for header in soup.find_all(["h1", "h2", "h3", "h4"]):
        text = _normalize_text(header.get_text(" ", strip=True))
        if not text or len(text) < 3 or len(text) > 80:
            continue
        low = text.lower()
        if any(h in low for h in hints):
            if "," in text:
                a, b = text.split(",", 1)
                return _normalize_text(a), _normalize_text(b)
            parts = text.split(" ")
            if len(parts) >= 2:
                return text, None

    text = _normalize_text(soup.get_text(" ", strip=True))
    if not text:
        return None, None
    for hint in hints:
        m = re.search(rf"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){{1,3}})\s+(?:-|–|—)?\s*({re.escape(hint)})", text, flags=re.IGNORECASE)
        if m:
            return _normalize_text(m.group(1)), _normalize_text(m.group(2))
    return None, None


def _extract_address_from_page(soup: BeautifulSoup) -> Optional[str]:
    text_nodes = []
    for tag in soup.find_all(["p", "div", "span", "li"]):
        t = _normalize_text(tag.get_text(" ", strip=True))
        if 20 <= len(t) <= 220:
            text_nodes.append(t)

    city_hints = ["manila", "quezon", "makati", "pasig", "cebu", "davao", "philippines"]
    for t in text_nodes:
        low = t.lower()
        if any(h in low for h in city_hints):
            cut = t
            for sep in [" Email ", " Call ", " Email Us ", " Call Us "]:
                idx = cut.lower().find(sep.strip().lower())
                if idx > 10:
                    cut = cut[:idx].strip()
            return cut
    return None


def scrape_leadership_page(base_url: str, org_name: str, title_hints: list) -> Dict[str, Any]:
    leadership_paths = [
        "/leadership",
        "/team",
        "/about/leadership",
        "/about/team",
        "/pastors",
        "/leaders",
        "/our-team",
        "/who-we-are",
        "/about-us",
        "/about",
        "/people",
        "/staff",
    ]

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    hints = [str(h).strip() for h in (title_hints or []) if str(h).strip()]
    if not hints:
        hints = ["President", "Senior Pastor", "Lead Pastor", "Bishop", "Director", "Secretary"]

    for path in leadership_paths:
        url = base_url.rstrip("/") + path
        try:
            resp = httpx.get(url, headers=headers, timeout=10, follow_redirects=True, verify=False)
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "lxml")
            page_text = _normalize_text(soup.get_text(" ", strip=True))
            page_text_low = page_text.lower()

            leader_name, leader_title = _extract_leader_from_page(soup, hints)
            if leader_name and _is_probable_person_name(leader_name):
                return {
                    "status": "success",
                    "leader_name": _normalize_text(leader_name),
                    "leader_title": _normalize_text(leader_title) if leader_title else None,
                    "source_url": str(resp.url),
                }

            for header in soup.find_all(["h2", "h3", "h4", "strong"]):
                text = _normalize_text(header.get_text(" ", strip=True))
                if not text or len(text) < 3 or len(text) > 80:
                    continue

                lower_text = text.lower()
                if any(hint.lower() in lower_text for hint in hints):
                    name = text.split(",", 1)[0].strip() if "," in text else text
                    for hint in hints:
                        name = name.replace(hint, "").replace(hint.lower(), "").strip()
                    if any(bad in name.lower() for bad in ["staff", "team", "our team", "leadership", "leaders"]):
                        continue

                    if "," in text:
                        title_part = text.split(",", 1)[1].strip()
                    else:
                        title_part = ", ".join([h for h in hints if h.lower() in lower_text][:2])

                    name = name.strip(" -|:")
                    if name and len(name) <= 80 and _is_probable_person_name(name):
                        return {
                            "status": "success",
                            "leader_name": name,
                            "leader_title": title_part,
                            "source_url": str(resp.url),
                        }

            for div in soup.find_all(["div", "article"]):
                text = _normalize_text(div.get_text(" ", strip=True))
                if not text:
                    continue
                low = text.lower()
                if any(hint.lower() in low for hint in hints):
                    name_tag = div.find(["h2", "h3", "h4", "strong"])
                    if name_tag:
                        name = _normalize_text(name_tag.get_text(" ", strip=True))
                        if name and len(name) <= 80 and _is_probable_person_name(name):
                            return {
                                "status": "success",
                                "leader_name": name,
                                "leader_title": ", ".join([h for h in hints if h.lower() in low][:2]),
                                "source_url": str(resp.url),
                            }
                    title_keywords = [h for h in hints if (" " not in h and "-" not in h) and re.search(r"[A-Za-z]", h)]
                    if any(t.lower() in low for t in title_keywords):
                        cand = div.find(["h1", "h2", "h3", "h4"])
                        if cand:
                            name = _normalize_text(cand.get_text(" ", strip=True))
                            if name and len(name) <= 80 and _is_probable_person_name(name):
                                return {
                                    "status": "success",
                                    "leader_name": name,
                                    "leader_title": ", ".join([h for h in title_keywords if h.lower() in low][:2]) or None,
                                    "source_url": str(resp.url),
                                }

        except Exception:
            continue

    return {"status": "not_found", "leader_name": None, "leader_title": None}


def enrich_org_with_leader(db: Session, org_id: str, base_url: str, title_hints: list):
    leader_data = scrape_leadership_page(base_url, "", title_hints)

    if leader_data.get("status") == "success":
        org = db.query(OrganizationProfile).filter(OrganizationProfile.id == org_id).first()
        if org:
            org.leader_name = leader_data.get("leader_name")
            org.leader_title = leader_data.get("leader_title")
            org.leader_bio_url = leader_data.get("source_url")
            db.commit()
            print(f"[OK] 补充负责人: {org.name} -> {org.leader_name} ({org.leader_title})")
            return True

    print(f"[WARN] 未找到负责人: {base_url}")
    return False


def scrape_org_website(org_seed: Dict[str, Any], db: Session) -> Dict[str, Any]:
    base_url = (org_seed.get("website") or "").strip()
    if not base_url:
        return {"status": "failed", "error": "missing_website"}

    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        candidates = [base_url]
        if "://" in base_url:
            scheme, rest = base_url.split("://", 1)
            if not rest.startswith("www."):
                candidates.append(f"{scheme}://www.{rest}")
        if base_url.startswith("https://"):
            candidates.append(base_url.replace("https://", "http://", 1))

        last_exc: Optional[Exception] = None
        resp = None
        for u in candidates:
            try:
                resp = httpx.get(u, headers=headers, timeout=15, follow_redirects=True, verify=False)
                resp.raise_for_status()
                break
            except Exception as e:
                last_exc = e
                resp = None
                continue
        if resp is None:
            raise last_exc or Exception("request_failed")
        effective_base = str(resp.url)

        soup = BeautifulSoup(resp.text, "lxml")

        result: Dict[str, Any] = {
            "official_website": effective_base,
            "leader_name": None,
            "leader_title": None,
            "contact_email": None,
            "phone_public": None,
            "address": None,
            "facebook_url": None,
            "youtube_url": None,
            "telegram_username": None,
            "member_estimate": None,
            "contact_candidates": [],
        }

        emails = _extract_emails(resp.text)
        mailtos = []
        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            if href.lower().startswith("mailto:"):
                mailtos.append(href.split(":", 1)[-1].split("?", 1)[0].strip())
        emails = list(dict.fromkeys(emails + [m for m in mailtos if m]))
        result["contact_email"] = _pick_best_email(emails)

        phones = _extract_phones(resp.text)
        result["phone_public"] = _pick_best_phone(phones)

        socials = _extract_social_links(soup)
        result.update(socials)
        result["contact_candidates"].extend(
            build_contact_candidates_from_crawl_result(
                {
                    "official_website": effective_base,
                    "emails": emails,
                    "phones": phones,
                    "facebook_url": socials.get("facebook_url"),
                    "youtube_url": socials.get("youtube_url"),
                    "telegram_username": socials.get("telegram_username"),
                    "source_url": effective_base,
                    "source_name": "org_profile_scraper",
                    "source_context": "official_website",
                },
                organization_url=effective_base,
                extraction_method="regex",
            )
        )

        contact_candidates = _find_candidate_links(
            soup,
            effective_base,
            keywords=["contact", "contacts", "get in touch", "location", "visit", "reach us"],
            limit=6,
        )
        leader_candidates = _find_candidate_links(
            soup,
            effective_base,
            keywords=["leadership", "leaders", "team", "staff", "pastor", "bish", "president", "about", "who we are"],
            limit=6,
        )

        title_hints = org_seed.get("leader_title_hint") or []
        for _, url in leader_candidates[:2]:
            try:
                r = httpx.get(url, headers=headers, timeout=12, follow_redirects=True, verify=False)
                if r.status_code >= 400:
                    continue
                s = BeautifulSoup(r.text, "lxml")
                leader_name, leader_title = _extract_leader_from_page(s, title_hints)
                if leader_name and not result["leader_name"]:
                    result["leader_name"] = leader_name
                if leader_title and not result["leader_title"]:
                    result["leader_title"] = leader_title
                if not result.get("facebook_url") or not result.get("youtube_url") or not result.get("telegram_username"):
                    result.update({k: v for k, v in _extract_social_links(s).items() if v and not result.get(k)})
            except Exception:
                pass

        for _, url in contact_candidates[:2]:
            try:
                r = httpx.get(url, headers=headers, timeout=12, follow_redirects=True, verify=False)
                if r.status_code >= 400:
                    continue
                s = BeautifulSoup(r.text, "lxml")
                emails2 = _extract_emails(r.text)
                if emails2 and not result["contact_email"]:
                    result["contact_email"] = _pick_best_email(emails2)
                phones2 = _extract_phones(r.text)
                if phones2 and not result["phone_public"]:
                    result["phone_public"] = _pick_best_phone(phones2)
                addr = _extract_address_from_page(s)
                if addr and not result["address"]:
                    result["address"] = addr
                if not result.get("facebook_url") or not result.get("youtube_url") or not result.get("telegram_username"):
                    result.update({k: v for k, v in _extract_social_links(s).items() if v and not result.get(k)})
                result["contact_candidates"].extend(
                    build_contact_candidates_from_crawl_result(
                        {
                            "emails": emails2,
                            "phones": phones2,
                            "facebook_url": result.get("facebook_url"),
                            "youtube_url": result.get("youtube_url"),
                            "telegram_username": result.get("telegram_username"),
                            "source_url": str(r.url),
                            "source_name": "org_profile_scraper",
                            "source_context": "contact_page",
                        },
                        organization_url=effective_base,
                        extraction_method="regex",
                    )
                )
            except Exception:
                pass

        if not result.get("leader_name"):
            leader_data = scrape_leadership_page(effective_base, org_seed.get("name") or "", title_hints)
            if leader_data.get("status") == "success":
                result["leader_name"] = leader_data.get("leader_name")
                result["leader_title"] = leader_data.get("leader_title")

        return {"status": "success", "data": result}
    except Exception as e:
        return {"status": "failed", "error": str(e)[:100]}


def store_organization_profile(db: Session, org_seed: Dict[str, Any], scraped_data: Dict[str, Any]) -> Dict[str, Any]:
    if scraped_data.get("status") != "success":
        return {"status": "failed", "error": "抓取失败"}

    data = scraped_data.get("data") or {}
    if not data.get("leader_name") and data.get("official_website"):
        leader_data = scrape_leadership_page(
            str(data.get("official_website")),
            org_seed.get("name") or "",
            org_seed.get("leader_title_hint") or [],
        )
        if leader_data.get("status") == "success":
            data["leader_name"] = leader_data.get("leader_name")
            data["leader_title"] = leader_data.get("leader_title")
            data["leader_bio_url"] = leader_data.get("source_url")
    name = org_seed["name"]
    country = org_seed["country"]

    existing = (
        db.query(OrganizationProfile)
        .filter(OrganizationProfile.name == name, OrganizationProfile.country == country)
        .first()
    )

    profile_data: Dict[str, Any] = {
        "name": name,
        "name_local": org_seed.get("name_local", "") or None,
        "country": country,
        "denomination": org_seed.get("denomination", "") or None,
        "official_website": data.get("official_website"),
        "contact_email": None,
        "phone_public": None,
        "address": data.get("address"),
        "leader_name": data.get("leader_name"),
        "leader_title": data.get("leader_title"),
        "leader_bio_url": data.get("leader_bio_url"),
        "facebook_url": None,
        "youtube_url": None,
        "telegram_username": None,
        "source_url": org_seed.get("website"),
        "source_name": "机构官网抓取",
        "confidence": 0.85,
        "ingested_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }

    if existing:
        if (profile_data.get("phone_public") is None) and existing.phone_public:
            if re.fullmatch(r"\d{7,}", (existing.phone_public or "").strip()):
                existing.phone_public = None
        if (profile_data.get("contact_email") is None) and existing.contact_email:
            el = (existing.contact_email or "").lower().strip()
            if el.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".pdf", ".mp4", ".mov")):
                existing.contact_email = None
        for key, value in profile_data.items():
            if value is None:
                continue
            if hasattr(existing, key):
                setattr(existing, key, value)
        apply_validated_contact_candidates_to_org(
            existing,
            data.get("contact_candidates") or [],
            change_source="org_profile_scraper",
            changed_by="system",
            db=db,
        )
        db.commit()
        return {"status": "updated", "id": existing.id}

    profile = OrganizationProfile(id=str(uuid.uuid4()), **profile_data)
    apply_validated_contact_candidates_to_org(
        profile,
        data.get("contact_candidates") or [],
        change_source="org_profile_scraper",
        changed_by="system",
        db=db,
    )
    db.add(profile)
    db.commit()
    return {"status": "created", "id": profile.id}
