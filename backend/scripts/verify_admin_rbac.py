from __future__ import annotations

from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (BACKEND_DIR / relative_path).read_text(encoding="utf-8")


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    dependency_text = _read("dependencies/auth.py")
    rbac_test_text = _read("tests/test_admin_rbac.py")

    _assert('ROLE_HIERARCHY: tuple[str, ...] = ("viewer", "analyst", "admin", "super_admin")' in dependency_text, "Role hierarchy must be defined")
    _assert("def normalize_role_value(" in dependency_text, "normalize_role_value helper must exist")
    _assert("def role_at_least(" in dependency_text, "role_at_least helper must exist")
    _assert("def require_role(*allowed_roles: str)" in dependency_text, "require_role helper must exist")
    _assert("def require_admin(" in dependency_text, "require_admin helper must exist")
    _assert("def require_super_admin(" in dependency_text, "require_super_admin helper must exist")
    _assert("Depends(get_current_user)" in dependency_text, "RBAC helpers must depend on authenticated current user")
    _assert('"ROLE_FORBIDDEN"' in dependency_text, "RBAC helpers must deny insufficient or invalid roles")
    _assert("x-session-id" not in dependency_text, "RBAC helpers must not trust x-session-id")
    _assert("x-user-id" not in dependency_text, "RBAC helpers must not trust x-user-id")
    _assert("test_11_header_role_spoofing_is_ignored" in rbac_test_text, "Header spoofing test must exist")
    _assert("test_12_body_role_spoofing_is_ignored" in rbac_test_text, "Body spoofing test must exist")
    _assert("test_15_auth_disabled_rejects_rbac_dependency" in rbac_test_text, "AUTH_V1 disabled test must exist")
    _assert("test_10_unknown_role_denied" in rbac_test_text, "Unknown role deny test must exist")

    print("ADMIN_RBAC_CHECK=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
