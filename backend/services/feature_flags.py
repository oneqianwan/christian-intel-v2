from __future__ import annotations

from config import FEATURE_FLAG_DEFAULTS, settings, sync_feature_flags_to_env


sync_feature_flags_to_env()


def feature_flag_enabled(name: str, default: bool = True) -> bool:
    normalized_name = str(name or "").strip().upper()
    fallback = FEATURE_FLAG_DEFAULTS.get(normalized_name, bool(default))
    return settings.feature_flag(normalized_name, default=fallback)


def feature_flag_default(name: str, default: bool = True) -> bool:
    return bool(FEATURE_FLAG_DEFAULTS.get(str(name or "").strip().upper(), default))


def registered_feature_flags() -> dict[str, bool]:
    return settings.FEATURE_FLAGS.to_dict()
