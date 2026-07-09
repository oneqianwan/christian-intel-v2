from __future__ import annotations

from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (BACKEND_DIR / relative_path).read_text(encoding="utf-8")


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    agent_text = _read("routers/agent.py")
    configs_text = _read("routers/configs.py")
    dashboard_text = _read("routers/dashboard.py")
    feedback_text = _read("routers/feedback.py")
    bookmarks_text = _read("routers/bookmarks.py")
    dependency_text = _read("dependencies/auth.py")
    model_text = _read("models/database.py")
    test_high_risk_text = _read("tests/test_high_risk_admin_protection.py")
    test_legacy_text = _read("tests/test_legacy_identity_cleanup.py")

    _assert("APIRouter(prefix=\"/api/agent\", tags=[\"agent\"], dependencies=[Depends(require_admin)])" in agent_text, "agent router must be admin-only")
    _assert("Depends(require_super_admin)" in configs_text, "configs keys must reuse require_super_admin")
    _assert("@router.get(\"/configs/keys\")" in configs_text, "configs keys route must exist")
    _assert("Depends(require_admin)" in dashboard_text, "dashboard write endpoints must reuse require_admin")
    _assert("get_current_user_if_auth_enabled" in feedback_text, "feedback must reuse current_user auth helper")
    _assert("user_id=str(current_user.id)" in feedback_text, "feedback auth mode must bind current_user")
    _assert("x_session_id or \"session-1\"" in feedback_text, "feedback legacy mode must stay explicitly separated")
    _assert("Depends(require_admin)" in feedback_text, "feedback stats must be admin-only")
    _assert("get_current_user_if_auth_enabled" in bookmarks_text, "bookmarks must reuse current_user auth helper")
    _assert("return \"default\"" in bookmarks_text, "bookmarks legacy default path must stay explicit")
    _assert("Bookmark.user_id == bookmark_user_id" in bookmarks_text, "bookmarks must filter by effective user id")
    _assert("user_id = Column(String(100), nullable=True)" in model_text, "user_feedbacks must store auth user binding")
    _assert("ix_user_feedbacks_user_id" in model_text, "user_feedbacks user_id index must exist")
    _assert("def get_current_user_if_auth_enabled(" in dependency_text, "shared auth helper must exist")
    _assert("test_03_admin_and_super_admin_agent_run_can_enter_business_logic" in test_high_risk_text, "agent protection test must exist")
    _assert("test_06_configs_keys_super_admin_returns_200" in test_high_risk_text, "configs super_admin test must exist")
    _assert("test_09_dashboard_write_admin_and_super_admin_return_200" in test_high_risk_text, "dashboard write protection test must exist")
    _assert("test_01_feedback_auth_mode_ignores_x_session_id_and_binds_current_user" in test_legacy_text, "feedback auth cleanup test must exist")
    _assert("test_08_bookmarks_auth_disabled_preserves_legacy_default_behavior" in test_legacy_text, "bookmarks legacy preservation test must exist")

    print("HIGH_RISK_ADMIN_PROTECTION_CHECK=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
