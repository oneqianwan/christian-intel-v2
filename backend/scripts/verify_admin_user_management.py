from __future__ import annotations

from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (BACKEND_DIR / relative_path).read_text(encoding="utf-8")


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    main_text = _read("main.py")
    router_text = _read("routers/admin.py")
    schema_text = _read("models/schemas.py")
    auth_service_text = _read("services/auth_service.py")
    test_text = _read("tests/test_admin_user_management.py")

    _assert("from routers import (" in main_text and "admin," in main_text, "main.py must import admin router")
    _assert("app.include_router(admin.router, prefix=\"/api\", tags=[\"admin\"])" in main_text, "main.py must register admin router")
    _assert("Depends(require_admin)" in router_text, "admin router must reuse require_admin")
    _assert("Depends(require_super_admin)" in router_text, "admin router must reuse require_super_admin")
    _assert("@router.get(\"/users\"" in router_text, "list users endpoint must exist")
    _assert("@router.get(\"/users/{user_id}\"" in router_text, "get user endpoint must exist")
    _assert("@router.patch(\"/users/{user_id}/role\"" in router_text, "patch role endpoint must exist")
    _assert("@router.patch(\"/users/{user_id}/status\"" in router_text, "patch status endpoint must exist")
    _assert("@router.post(\"/users/{user_id}/sessions/revoke\"" in router_text, "revoke sessions endpoint must exist")
    _assert("public_id=str(user.public_id)" in router_text, "responses must use public_id instead of internal id")
    _assert("password_hash" not in router_text, "admin router must not return password_hash")
    _assert("token_hash" not in router_text, "admin router must not return token_hash")
    _assert("revoke_all_user_sessions" in router_text and "revoke_all_user_sessions" in auth_service_text, "session revoke must reuse existing auth service")
    _assert("SELF_DEMOTION_FORBIDDEN" in router_text, "self demotion protection must exist")
    _assert("SELF_DISABLE_FORBIDDEN" in router_text, "self disable protection must exist")
    _assert("LAST_SUPER_ADMIN_PROTECTED" in router_text, "last super admin protection must exist")
    _assert("AdminUserResponse" in schema_text, "admin response schema must exist")
    _assert("AdminUserRoleUpdateRequest" in schema_text, "admin role request schema must exist")
    _assert("AdminUserStatusUpdateRequest" in schema_text, "admin status request schema must exist")
    _assert("test_17_revoke_target_sessions_works" in test_text, "session revoke test must exist")
    _assert("test_20_header_and_body_role_spoofing_rejected" in test_text, "header/body spoofing test must exist")
    _assert("test_21_auth_disabled_admin_api_fails_closed" in test_text, "AUTH_V1 disabled test must exist")

    print("ADMIN_USER_MANAGEMENT_CHECK=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
