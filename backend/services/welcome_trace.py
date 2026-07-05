import json
import threading
import uuid
from typing import Any

WELCOME_REPLY_TEXT = (
    "Christian Intelligence Operating System（CIO）\n"
    "Enterprise Christian Intelligence Platform\n"
    "企业级基督教情报分析平台\n\n"
    "Christian Intelligence Operating System（CIO）是一套面向研究、分析与决策支持的企业级基督教情报分析平台。\n"
    "系统专注于整合全球公开数据、机构资料、人物信息、媒体动态及关系网络，帮助用户快速获取可追溯、可验证、可分析的情报。\n"
    "回答优先基于数据库与公开来源，不编造不存在的数据。\n\n"
    "推荐查询\n"
    "• 查询 Victory Philippines 的评分\n"
    "• 查询 Every Nation\n"
    "• 查询 Billy Graham\n"
    "• 查询菲律宾基督教媒体\n"
    "• 查询韩国基督教情况\n"
    "• 查询 OpenAI 和 Microsoft 的关系\n"
    "• 查询 Compassion International 的资金来源"
)
WELCOME_REPLY_NORMALIZED = "".join(WELCOME_REPLY_TEXT.split())

_lock = threading.Lock()
_conversation_uuid_map: dict[str, str] = {}


def register_welcome_reply(conversation_id: str | None, text: str) -> str | None:
    if text != WELCOME_REPLY_TEXT or not conversation_id:
        return None
    with _lock:
        welcome_uuid = _conversation_uuid_map.get(conversation_id)
        if not welcome_uuid:
            welcome_uuid = uuid.uuid4().hex
            _conversation_uuid_map[conversation_id] = welcome_uuid
    return welcome_uuid


def lookup_welcome_reply_uuid(conversation_id: str | None, text: str) -> str | None:
    if "".join(str(text or "").split()) != WELCOME_REPLY_NORMALIZED or not conversation_id:
        return None
    with _lock:
        return _conversation_uuid_map.get(conversation_id)


def emit_welcome_trace(stage: str, welcome_uuid: str | None, *, conversation_id: str | None = None, extra: dict[str, Any] | None = None) -> None:
    if not welcome_uuid:
        return
    payload = {
        "stage": stage,
        "welcome_reply_uuid": welcome_uuid,
        "conversation_id": conversation_id or "",
        **dict(extra or {}),
    }
    print("WELCOME_REPLY_TRACE " + json.dumps(payload, ensure_ascii=False))
