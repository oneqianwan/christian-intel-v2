from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.organization_resolver import OrganizationResolver


KNOWN_ORGANIZATIONS = [
    {"id": "org-victory-ph", "name": "Victory Philippines", "canonical_name": "Victory Philippines"},
    {"id": "org-alpha", "name": "Alpha Church", "canonical_name": "Alpha Church"},
]

ALIAS_MAP = {
    "Alpha": "Alpha Church",
}


def test_chinese_primary_and_target_are_extracted():
    resolver = OrganizationResolver()

    result = resolver.resolve_organization(
        "给我 Victory Philippines 联系 Alpha Church 的行动计划",
        known_organizations=KNOWN_ORGANIZATIONS,
        alias_map=ALIAS_MAP,
    )

    assert result["organization_name"] == "Victory Philippines"
    assert result["target_organization_name"] == "Alpha Church"
    assert result["target_organization_id"] == "org-alpha"


def test_english_primary_and_target_are_extracted():
    resolver = OrganizationResolver()

    result = resolver.resolve_organization(
        "Create an action plan for Victory Philippines to contact Alpha Church",
        known_organizations=KNOWN_ORGANIZATIONS,
        alias_map=ALIAS_MAP,
    )

    assert result["organization_name"] == "Victory Philippines"
    assert result["target_organization_name"] == "Alpha Church"
    assert result["target_organization_id"] == "org-alpha"


def test_target_alias_is_resolved_to_canonical_name():
    resolver = OrganizationResolver()

    result = resolver.resolve_organization(
        "Create an action plan for Victory Philippines to contact Alpha",
        known_organizations=KNOWN_ORGANIZATIONS,
        alias_map=ALIAS_MAP,
    )

    assert result["organization_name"] == "Victory Philippines"
    assert result["target_canonical_name"] == "Alpha Church"
    assert result["target_candidates"][0]["match_type"] == "alias"


def test_missing_target_is_safe_for_non_targeted_query():
    resolver = OrganizationResolver()

    result = resolver.resolve_organization(
        "Create an action plan for Victory Philippines",
        known_organizations=KNOWN_ORGANIZATIONS,
        alias_map=ALIAS_MAP,
    )

    assert result["organization_name"] == "Victory Philippines"
    assert result["target_organization_name"] is None
    assert result["resolution_status"] == "resolved"


def test_action_words_are_not_treated_as_organization_name():
    resolver = OrganizationResolver()

    result = resolver.resolve_organization(
        "Create an action plan",
        known_organizations=KNOWN_ORGANIZATIONS,
        alias_map=ALIAS_MAP,
    )

    assert result["organization_name"] is None
    assert result["resolution_status"] == "missing"
