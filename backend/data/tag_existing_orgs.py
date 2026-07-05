"""
给现有OrganizationProfile机构打Ontology标签
"""

import os
import sys
import uuid
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.database import (
    OrganizationOntologyTag,
    OrganizationProfile,
    get_db,
    init_db,
)


CORE_ORGANIZATIONS = [
    {
        "match": "%PCEC%",
        "label": "PCEC",
        "defaults": {
            "name": "Philippine Council of Evangelical Churches (PCEC)",
            "country": "菲律宾",
            "official_website": "https://pcec.org.ph",
            "denomination": "福音派跨宗派",
            "member_estimate": 30000,
            "source_name": "manual_seed",
            "source_url": "https://pcec.org.ph",
            "confidence": 0.9,
        },
        "tags": [
            {"tag_type": "organization_type", "tag_id": "association"},
            {"tag_type": "organization_type", "tag_id": "church_network"},
            {"tag_type": "theology", "tag_id": "evangelical"},
            {"tag_type": "theology", "tag_id": "interdenominational"},
            {"tag_type": "scale", "tag_id": "large"},
        ],
    },
    {
        "match": "%Victory%",
        "label": "Victory",
        "defaults": {
            "name": "Victory Philippines",
            "country": "菲律宾",
            "official_website": "https://victory.org.ph",
            "denomination": "Charismatic",
            "member_estimate": 120000,
            "source_name": "manual_seed",
            "source_url": "https://victory.org.ph",
            "confidence": 0.92,
        },
        "tags": [
            {"tag_type": "organization_type", "tag_id": "church_network"},
            {"tag_type": "theology", "tag_id": "charismatic"},
        ],
    },
    {
        "match": "%Christ's Commission Fellowship%",
        "label": "CCF",
        "defaults": {
            "name": "Christ's Commission Fellowship (CCF)",
            "country": "菲律宾",
            "official_website": "https://www.ccf.org.ph",
            "denomination": "福音派",
            "member_estimate": 100000,
            "source_name": "manual_seed",
            "source_url": "https://www.ccf.org.ph",
            "confidence": 0.85,
        },
        "tags": [
            {"tag_type": "organization_type", "tag_id": "church_network"},
            {"tag_type": "theology", "tag_id": "evangelical"},
            {"tag_type": "scale", "tag_id": "large"},
        ],
    },
    {
        "match": "%Jesus Is Lord Church%",
        "label": "JIL",
        "defaults": {
            "name": "Jesus Is Lord Church (JIL)",
            "country": "菲律宾",
            "official_website": "https://jilworldwide.org",
            "denomination": "灵恩派/五旬节派",
            "member_estimate": 500000,
            "source_name": "manual_seed",
            "source_url": "https://jilworldwide.org",
            "confidence": 0.9,
        },
        "tags": [
            {"tag_type": "organization_type", "tag_id": "church_network"},
            {"tag_type": "theology", "tag_id": "pentecostal"},
            {"tag_type": "scale", "tag_id": "mega"},
        ],
    },
    {
        "match": "%CBN Asia%",
        "label": "CBN Asia",
        "defaults": {
            "name": "CBN Asia",
            "country": "菲律宾",
            "official_website": "https://www.cbnasia.org",
            "denomination": "Evangelical",
            "source_name": "manual_seed",
            "source_url": "https://www.cbnasia.org",
            "confidence": 0.9,
        },
        "tags": [
            {"tag_type": "organization_type", "tag_id": "media_outlet"},
        ],
    },
    {
        "match": "%FEBC%",
        "label": "FEBC Philippines",
        "defaults": {
            "name": "FEBC Philippines",
            "country": "菲律宾",
            "official_website": "https://febc.ph/",
            "denomination": "福音派跨宗派",
            "source_name": "manual_seed",
            "source_url": "https://febc.ph/",
            "confidence": 0.9,
        },
        "tags": [
            {"tag_type": "organization_type", "tag_id": "media_outlet"},
            {"tag_type": "organization_type", "tag_id": "parachurch"},
        ],
    },
    {
        "match": "%Veritas%",
        "label": "Veritas PH",
        "defaults": {
            "name": "Veritas PH",
            "country": "菲律宾",
            "official_website": "https://www.veritasph.net/",
            "denomination": "天主教",
            "source_name": "manual_seed",
            "source_url": "https://www.veritasph.net/",
            "confidence": 0.88,
        },
        "tags": [
            {"tag_type": "organization_type", "tag_id": "media_outlet"},
            {"tag_type": "theology", "tag_id": "catholic"},
        ],
    },
    {
        "match": "%Philippine Bible Society%",
        "label": "Philippine Bible Society",
        "defaults": {
            "name": "Philippine Bible Society",
            "country": "菲律宾",
            "official_website": "https://bible.org.ph/",
            "denomination": "跨宗派",
            "source_name": "manual_seed",
            "source_url": "https://bible.org.ph/",
            "confidence": 0.9,
        },
        "tags": [
            {"tag_type": "organization_type", "tag_id": "faithtech_bible"},
            {"tag_type": "organization_type", "tag_id": "parachurch"},
            {"tag_type": "theology", "tag_id": "interdenominational"},
        ],
    },
]


def _add_tags_for_match(db, org, tags: list[dict], label: str):
    if not org:
        return False

    changed = False
    for tag in tags:
        existing = (
            db.query(OrganizationOntologyTag)
            .filter(
                OrganizationOntologyTag.organization_id == org.id,
                OrganizationOntologyTag.tag_type == tag["tag_type"],
                OrganizationOntologyTag.tag_id == tag["tag_id"],
            )
            .first()
        )
        if existing:
            continue

        db.add(
            OrganizationOntologyTag(
                id=str(uuid.uuid4()),
                organization_id=org.id,
                tag_type=tag["tag_type"],
                tag_id=tag["tag_id"],
                confidence="manual",
                source="name_pattern",
            )
        )
        changed = True

    print(f"✅ {label} 已打标签")
    return changed


def _find_or_create_org(db, item: dict):
    org = db.query(OrganizationProfile).filter(OrganizationProfile.name.ilike(item["match"])).first()
    if org:
        return org

    defaults = item["defaults"]
    org = OrganizationProfile(
        id=str(uuid.uuid4()),
        name=defaults["name"],
        country=defaults["country"],
        official_website=defaults.get("official_website"),
        denomination=defaults.get("denomination"),
        member_estimate=defaults.get("member_estimate"),
        source_name=defaults.get("source_name"),
        source_url=defaults.get("source_url"),
        confidence=defaults.get("confidence", 0.9),
        ingested_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(org)
    db.flush()
    print(f"➕ {item['label']} 缺失，已补充基础机构档案")
    return org


def tag_existing():
    """基于名称匹配，给已有机构自动打标签"""
    init_db()
    db = next(get_db())

    try:
        for item in CORE_ORGANIZATIONS:
            org = _find_or_create_org(db, item)
            _add_tags_for_match(db, org, item["tags"], item["label"])

        db.commit()
        print("✅ 现有机构标签完成")
    finally:
        db.close()


if __name__ == "__main__":
    tag_existing()
