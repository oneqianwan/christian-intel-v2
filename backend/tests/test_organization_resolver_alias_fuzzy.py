from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.organization_resolver import OrganizationResolver


KNOWN_ORGANIZATIONS = [
    {"id": "org-victory-ph", "name": "Victory Philippines", "canonical_name": "Victory Philippines"},
    {"id": "org-victory-church", "name": "Victory Church", "canonical_name": "Victory Church"},
    {"id": "org-victory-outreach", "name": "Victory Outreach", "canonical_name": "Victory Outreach"},
    {"id": "org-alpha", "name": "Alpha Church", "canonical_name": "Alpha Church"},
]

ALIAS_MAP = {
    "Victory PH": "Victory Philippines",
    "Victory Church Philippines": "Victory Philippines",
    "Alpha": "Alpha Church",
}


def test_exact_match_returns_known_organization():
    resolver = OrganizationResolver()

    result = resolver.resolve_organization(
        "Victory Philippines 怎么联系",
        known_organizations=KNOWN_ORGANIZATIONS,
        alias_map=ALIAS_MAP,
    )

    assert result["resolution_status"] == "resolved"
    assert result["organization_name"] == "Victory Philippines"
    assert result["organization_id"] == "org-victory-ph"
    assert result["candidates"][0]["match_type"] == "exact"


def test_alias_match_maps_to_canonical_name():
    resolver = OrganizationResolver()

    result = resolver.resolve_organization(
        "Victory PH 怎么联系",
        known_organizations=KNOWN_ORGANIZATIONS,
        alias_map=ALIAS_MAP,
    )

    assert result["resolution_status"] == "resolved"
    assert result["canonical_name"] == "Victory Philippines"
    assert result["organization_id"] == "org-victory-ph"
    assert result["candidates"][0]["match_type"] == "alias"


def test_normalized_match_supports_hyphen_and_case_differences():
    resolver = OrganizationResolver()

    result = resolver.resolve_organization(
        "victory-philippines contact info",
        known_organizations=KNOWN_ORGANIZATIONS,
        alias_map=ALIAS_MAP,
    )

    assert result["resolution_status"] == "resolved"
    assert result["canonical_name"] == "Victory Philippines"
    assert result["candidates"][0]["match_type"] == "normalized"


def test_light_fuzzy_match_supports_minor_typo():
    resolver = OrganizationResolver()

    result = resolver.resolve_organization(
        "Victory Philippiens 怎么联系",
        known_organizations=KNOWN_ORGANIZATIONS,
        alias_map=ALIAS_MAP,
    )

    assert result["resolution_status"] == "resolved"
    assert result["canonical_name"] == "Victory Philippines"
    assert result["candidates"][0]["match_type"] == "fuzzy"


def test_multiple_candidates_return_ambiguous_without_fabricated_id():
    resolver = OrganizationResolver()

    result = resolver.resolve_organization(
        "Victory 怎么联系",
        known_organizations=KNOWN_ORGANIZATIONS,
        alias_map=ALIAS_MAP,
    )

    assert result["resolution_status"] == "ambiguous"
    assert result["organization_name"] is None
    assert len(result["candidates"]) >= 2
    assert {candidate["canonical_name"] for candidate in result["candidates"][:3]} >= {
        "Victory Philippines",
        "Victory Church",
    }
