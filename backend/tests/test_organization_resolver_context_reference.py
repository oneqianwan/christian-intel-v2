from __future__ import annotations

import sys
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.organization_resolver import OrganizationResolver


@pytest.mark.parametrize(
    "query",
    [
        "这个机构怎么联系",
        "刚才那个机构的证据简报",
        "它",
        "Contact info for this organization",
        "How can I contact that church?",
        "it",
        "them",
    ],
)
def test_context_references_require_previous_organization(query: str):
    resolver = OrganizationResolver()

    result = resolver.resolve_organization(query)

    assert result["organization_name"] is None
    assert result["resolution_status"] == "context_required"
    assert result["context_reference"] is True
    assert result["requires_previous_organization"] is True
    assert result["candidates"] == []
    assert "context_reference_requires_previous_organization" in result["warnings"]
