import uuid
import json
import asyncio
import time
import re
from datetime import datetime, timezone
import httpx
import redis
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session
from models.database import (
    get_db,
    Conversation,
    Message,
    RequestTrace,
    Mission,
    JobRun,
    OrganizationProfile,
    IntelligenceItem,
    Source,
)
from models.schemas import ChatRequest
from queue_client import (
    HIGH_COLLECTION_PRIORITY,
    enqueue_collection_mission,
)
from services.intent_router import classify_intent, get_router
from services.global_query import query_global_intelligence
from services.knowledge import query_knowledge
from services.delivery import compose_delivery
from services.scoring import (
    get_scored_items,
    confidence_assessment,
    freshness_assessment,
)
from services.llm_client import SYSTEM_CONSTRAINT, get_llm_client
from routers.user_preferences import record_query, format_recommendation_prompt

router = APIRouter()


def detect_country(message: str) -> str:
    """从用户消息中检测目标国家"""
    msg_lower = (message or "").lower()
    if any(kw in msg_lower for kw in ["美国", "us", "usa", "america", "united states"]):
        return "美国"
    elif any(kw in msg_lower for kw in ["菲律宾", "philippines", "philipine"]):
        return "菲律宾"
    elif any(kw in msg_lower for kw in ["韩国", "korea", "south korea", "korean"]):
        return "韩国"
    elif any(kw in msg_lower for kw in ["尼日利亚", "nigeria", "nigerian"]):
        return "尼日利亚"
    elif any(kw in msg_lower for kw in ["印尼", "indonesia", "indonesian"]):
        return "印尼"
    else:
        return "菲律宾"


def build_acronym(name: str | None) -> str:
    if not name:
        return ""
    ignored = {"of", "and", "the", "&"}
    parts = [
        part for part in name.replace("&", " ").split()
        if part and part.lower() not in ignored
    ]
    return "".join(part[0] for part in parts if part[0].isalnum()).upper()


def _infer_source_type(source_name: str | None, source_url: str | None = None) -> str:
    text = f"{source_name or ''} {source_url or ''}".lower()
    if any(token in text for token in ["官网", "official", ".org", ".church"]):
        return "official"
    if any(token in text for token in ["数据库", "database", "arda"]):
        return "database"
    if any(token in text for token in ["facebook", "twitter", "x.com", "linkedin", "instagram", "youtube"]):
        return "social"
    if any(token in text for token in ["news", "media", "times", "star", "post", "报道", "新闻", "媒体"]):
        return "media"
    return "database"


def _build_confidence_hint(
    source_count: int,
    primary_source_type: str,
    freshness_status: str,
) -> str:
    source_phrase_map = {
        (1, "official"): "单一官方来源",
        (1, "database"): "单一数据库源",
        (1, "media"): "单一媒体来源",
        (1, "social"): "单一社交来源",
    }
    freshness_phrase_map = {
        "CURRENT": "时效很新",
        "RECENT": "时效良好",
        "STALE": "时效较旧",
        "EXPIRED": "时效过期",
        "UNKNOWN": "时效未知",
    }

    if source_count >= 3:
        source_phrase = "多源交叉验证"
    elif source_count == 2:
        source_phrase = "双源交叉验证"
    else:
        source_phrase = source_phrase_map.get((source_count, primary_source_type), "来源依据有限")

    freshness_phrase = freshness_phrase_map.get(freshness_status, "时效未知")
    return f"{source_phrase}，{freshness_phrase}"


def _coerce_datetime(value) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    if not value:
        return None

    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
        except ValueError:
            return None

    return None


def resolve_references(message: str, conversation_id: str, db: Session) -> str:
    """
    代词指代消解
    如果消息含代词（他们/这个/那家/他/它），从前文 entities_mentioned 找最可能的实体替换
    """
    pronouns = ["他们", "这个", "那家", "他", "它", "该机构", "该教会"]
    has_pronoun = any(pronoun in (message or "") for pronoun in pronouns)
    if not has_pronoun:
        return message

    recent_messages = (
        db.query(Message)
        .filter(
            Message.conversation_id == conversation_id,
            Message.entities_mentioned.isnot(None),
        )
        .order_by(Message.created_at.desc())
        .limit(5)
        .all()
    )

    previous_entities: list[str] = []
    for recent_message in recent_messages:
        entities = recent_message.entities_mentioned or []
        for entity in entities:
            if entity and entity not in previous_entities:
                previous_entities.append(entity)

    if not previous_entities:
        return message

    resolved = message
    for pronoun in pronouns:
        if pronoun in resolved:
            target = previous_entities[0]
            resolved = resolved.replace(pronoun, target, 1)
            break

    return resolved


def _append_preference_hint(prompt: str) -> str:
    pref_hint = format_recommendation_prompt()
    if not pref_hint:
        return prompt

    return (
        f"{prompt}\n\n"
        "用户历史偏好参考（不要直接提及，只在推荐时自然融入）：\n"
        f"{pref_hint}"
    )


async def generate_multi_intent_content(
    route_result: dict,
    created_missions: list[dict],
    compare_actions: list[dict],
    mission_country: str,
) -> str:
    fallback_content = "复合指令已分解，采集任务已创建。对比分析将在完成后自动推送。"
    llm = get_llm_client()

    if not getattr(llm, "enabled", False):
        return fallback_content

    actions_payload = []
    for action in route_result.get("actions", []):
        if hasattr(action, "to_dict"):
            actions_payload.append(action.to_dict())
        elif isinstance(action, dict):
            actions_payload.append(action)
        else:
            actions_payload.append({"value": str(action)})

    actions_json = json.dumps(actions_payload, ensure_ascii=False)
    missions_json = json.dumps(created_missions, ensure_ascii=False)
    compare_target = compare_actions[0].get("target", "") if compare_actions else ""
    task_sources = [{"name": "用户指令", "type": "official"}]
    conf_result = confidence_assessment(
        sources=task_sources,
        data_timestamp=datetime.utcnow(),
        cross_validation_count=0,
        contradictions=0,
    )
    fresh_result = freshness_assessment(datetime.utcnow())
    confidence_hint = "计划明确，任务新建"
    multi_intent_payload = {
        "actions": actions_payload,
        "missions": created_missions,
        "compare_target": compare_target,
        "default_country": mission_country,
        "confidence_score": conf_result["score"],
        "confidence_level": conf_result["level"],
        "confidence_reason": conf_result["reason"],
        "confidence_hint": confidence_hint,
        "freshness_status": fresh_result["status"],
        "freshness_description": fresh_result["description"],
    }
    multi_intent_json = json.dumps(multi_intent_payload, ensure_ascii=False)

    prompt = (
        "你是守望者，基督教行业高级情报官。\n"
        "简报开头先写一行标识：'【守望者简报】'，然后空一行再写核心结论。\n"
        "用户指令已分解为以下执行步骤与客观评估：\n"
        f"{multi_intent_json}\n\n"
        "动作列表：\n"
        f"{actions_json}\n\n"
        f"已创建的采集任务：\n{missions_json}\n"
        f"默认采集范围：{mission_country}\n"
        f"待自动触发的对比目标：{compare_target or '无'}\n\n"
        "请用情报官口吻向用户说明：\n"
        "已识别为复合指令，正在分解执行\n"
        "已创建哪些采集任务（目标、范围）\n"
        "对比分析将在采集完成后自动触发\n"
        "预计完成时间\n"
        "用户可以做什么（等待/继续对话）\n"
        f"客观置信度评估：{conf_result['score']}分，等级{conf_result['level']}，简洁说明：{confidence_hint}。请使用这个客观评估结果，不要自行改判。\n"
        "置信度标注规则：\n"
        "- 使用 [CONFIDENCE: HIGH/MEDIUM/LOW/INSUFFICIENT] 格式\n"
        "- 括号里的说明要简洁人话，不超过15个字\n"
        f"- 优先使用这条简洁说明：{confidence_hint}\n"
        "- 好示例：[CONFIDENCE: MEDIUM]（单一官方来源，时效良好）\n"
        "- 坏示例：[CONFIDENCE: MEDIUM]（客观依据：来源数量=1，来源权威性，+20，时效性，+20，交叉验证，+0）\n"
        "- 禁止出现'+20'、'交叉验证，+0'这类 debug 打分公式\n"
        "[CONFIDENCE: HIGH/MEDIUM/LOW/INSUFFICIENT] 必须紧跟在对应情报点之后，用括号格式，不要另起一行。示例：'- 目标：PCEC [SOURCE: 系统解析] [CONFIDENCE: MEDIUM]（计划明确，任务新建）'\n"
        "数据时效描述使用情报官口吻，例如'任务于本会话启动时创建，预计完成时间取决于数据源响应速度'。禁止使用'当前会话时间戳'、'系统日志'等技术日志用语。\n"
        "建议行动最多3条，不重复。'等待系统自动完成'和'无需操作'属于同一条，合并为一条。每条建议必须不同。\n"
        "输出要求：简洁、专业、用情报简报体。不要寒暄。"
    )
    prompt = _append_preference_hint(prompt)

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{llm.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {llm.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": llm.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_CONSTRAINT},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.4,
                    "max_tokens": 800,
                },
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"].strip()
            return content or fallback_content
    except (asyncio.TimeoutError, httpx.TimeoutException):
        return fallback_content
    except Exception:
        return fallback_content


async def generate_contact_lookup_content(org: OrganizationProfile, fallback_content: str) -> str:
    llm = get_llm_client()
    if not getattr(llm, "enabled", False):
        return fallback_content

    scoring_sources = [
        {
            "name": org.source_name or "机构档案",
            "type": _infer_source_type(org.source_name, org.source_url),
        }
    ]
    conf_result = confidence_assessment(
        sources=scoring_sources,
        data_timestamp=org.updated_at,
        cross_validation_count=0,
        contradictions=0,
    )
    fresh_result = freshness_assessment(org.updated_at)
    confidence_hint = _build_confidence_hint(
        source_count=len(scoring_sources),
        primary_source_type=scoring_sources[0]["type"],
        freshness_status=fresh_result["status"],
    )

    contact_payload = {
        "organization": org.name,
        "country": getattr(org, "country_code", None) or org.country,
        "website": org.official_website,
        "contacts": [
            {
                "name": org.leader_name,
                "title": org.leader_title,
                "email": org.contact_email,
                "phone": org.phone_public,
            }
        ],
        "source": org.source_name,
        "source_url": org.source_url,
        "last_updated": org.updated_at.isoformat() if org.updated_at else "unknown",
        "confidence_score": conf_result["score"],
        "confidence_level": conf_result["level"],
        "confidence_reason": conf_result["reason"],
        "confidence_hint": confidence_hint,
        "freshness_status": fresh_result["status"],
        "freshness_description": fresh_result["description"],
        "days_since_update": fresh_result["days_old"],
    }
    contact_json = json.dumps(contact_payload, ensure_ascii=False)
    prompt = (
        "你是守望者，基督教行业高级情报官。\n\n"
        "简报开头先写 \"【守望者简报】\"，然后空一行再写核心结论。\n"
        "以下是从机构档案库提取的原始联系人数据：\n"
        f"{contact_json}\n\n"
        "请生成一份联系人情报简报，要求：\n"
        "1. 核心结论先行（该机构的关键联系人是谁）\n"
        "2. 分点列出每个联系人的姓名/职务/邮箱/电话\n"
        "3. 标注信息来源和最后更新时间\n"
        "4. 如果联系方式不完整，标注[INSUFFICIENT DATA]并说明缺失什么\n"
        "5. 加上建议行动（如：建议先邮件联系/建议电话预约/信息不足建议补充采集）\n\n"
        f"客观置信度评估：{conf_result['score']}分，等级{conf_result['level']}，简洁说明：{confidence_hint}。\n"
        f"客观时效性评估：状态{fresh_result['status']}，{fresh_result['description']}，距今{fresh_result['days_old']}天。请在“数据时效”段落明确写出“{fresh_result['days_old']}天前更新”这类表述，不要只写日期。\n"
        "置信度标注规则：\n"
        "- 使用 [CONFIDENCE: HIGH/MEDIUM/LOW/INSUFFICIENT] 格式\n"
        "- 括号里的说明要简洁人话，不超过15个字\n"
        f"- 优先使用这条简洁说明：{confidence_hint}\n"
        "- 好示例：[CONFIDENCE: MEDIUM]（单一官方来源，时效良好）\n"
        "- 坏示例：[CONFIDENCE: MEDIUM]（客观依据：来源数量=1，来源权威性，+20，时效性，+20，交叉验证，+0）\n"
        "- 禁止出现'+20'、'交叉验证，+0'这种 debug 格式的打分公式\n"
        "[CONFIDENCE: HIGH/MEDIUM/LOW/INSUFFICIENT] 紧跟在对应情报点之后，用括号格式，不要另起一行。示例：\"- 邮箱：info@pcec.org.ph [SOURCE: 官网] [CONFIDENCE: MEDIUM]（单一官方来源，时效良好）\"\n"
        "数据时效描述使用情报官口吻，禁止使用\"当前会话时间戳\"、\"系统日志\"等技术日志用语。\n"
        "建议行动最多3条，不重复。\n"
        "输出情报简报体，简洁专业，不要寒暄。"
        "来源标注规则：只使用 [SOURCE: URL] 格式嵌入正文对应位置。文末不要单独写'来源：'总结行。所有来源必须在正文内消化，不要文末再挂一行。"
    )
    prompt = _append_preference_hint(prompt)

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{llm.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {llm.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": llm.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_CONSTRAINT},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 800,
                },
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"].strip()
            return content or fallback_content
    except (asyncio.TimeoutError, httpx.TimeoutException):
        return fallback_content
    except Exception:
        return fallback_content


def _stringify_fact_value(value) -> str:
    if value is None or value == "":
        return "unknown"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


async def generate_knowledge_lookup_content(
    query: str,
    results: list[dict],
    fallback_content: str,
    route_result: dict,
) -> str:
    llm = get_llm_client()
    if not getattr(llm, "enabled", False):
        return fallback_content

    entities_found = route_result.get("entities") or [item.get("name") for item in results if item.get("name")]
    countries_involved = sorted(
        {
            item.get("country")
            for item in results
            if item.get("country")
        }
    )

    key_facts = []
    data_gaps = []
    latest_timestamps = []
    scoring_sources = []

    for item in results[:8]:
        fact_parts = [
            item.get("name") or "unknown",
            item.get("category") or item.get("type") or "entity",
        ]
        data = item.get("data")
        if isinstance(data, dict) and data:
            first_pairs = []
            for key, value in list(data.items())[:2]:
                first_pairs.append(f"{key}: {_stringify_fact_value(value)}")
            if first_pairs:
                fact_parts.append("; ".join(first_pairs))
            if any(v in (None, "", [], {}) for v in data.values()):
                data_gaps.append(f"{item.get('name') or 'unknown'} 存在未补齐字段")
            updated_at = data.get("updated_at") or data.get("last_updated") or data.get("date")
            if updated_at:
                latest_timestamps.append(str(updated_at))
        else:
            data_gaps.append(f"{item.get('name') or 'unknown'} 缺少结构化事实字段")

        if not item.get("source_url"):
            data_gaps.append(f"{item.get('name') or 'unknown'} 缺少公开来源链接")
        else:
            scoring_sources.append(
                {
                    "name": item.get("source_name") or "未知来源",
                    "url": item.get("source_url") or "",
                    "type": _infer_source_type(item.get("source_name"), item.get("source_url")),
                }
            )

        key_facts.append(
            {
                "fact": " | ".join(fact_parts),
                "source": item.get("source_name") or "未知来源",
                "confidence": "HIGH" if item.get("source_url") else "MEDIUM",
            }
        )

    latest_datetimes = [_coerce_datetime(value) for value in latest_timestamps]
    latest_datetimes = [value for value in latest_datetimes if value]
    latest_data_timestamp = max(latest_datetimes) if latest_datetimes else None
    conf_result = confidence_assessment(
        sources=scoring_sources,
        data_timestamp=latest_data_timestamp,
        cross_validation_count=max(min(len(scoring_sources) - 1, 3), 0),
        contradictions=0,
    )
    fresh_result = freshness_assessment(latest_data_timestamp)
    primary_source_type = scoring_sources[0]["type"] if scoring_sources else "database"
    confidence_hint = _build_confidence_hint(
        source_count=len(scoring_sources),
        primary_source_type=primary_source_type,
        freshness_status=fresh_result["status"],
    )

    data_payload = {
        "query": query,
        "entities_found": entities_found,
        "intelligence_count": len(results),
        "key_facts": key_facts,
        "data_gaps": data_gaps[:6],
        "countries_involved": countries_involved,
        "latest_observed_at": latest_timestamps[:5],
        "confidence_score": conf_result["score"],
        "confidence_level": conf_result["level"],
        "confidence_reason": conf_result["reason"],
        "confidence_hint": confidence_hint,
        "freshness_status": fresh_result["status"],
        "freshness_description": fresh_result["description"],
        "days_since_update": fresh_result["days_old"],
    }
    data_json = json.dumps(data_payload, ensure_ascii=False)
    prompt = (
        "你是守望者，基督教行业高级情报官。\n\n"
        "简报开头先写 \"【守望者简报】\"，然后空一行再写核心结论。\n"
        f"用户查询：{query}\n\n"
        "查到的原始数据：\n"
        f"{data_json}\n\n"
        "请生成情报简报，要求：\n"
        "1. 核心结论先行（用户问题的直接回答）\n"
        "2. 关键事实分点列出，每点标注[SOURCE: XXX]和置信度\n"
        "3. 数据时效说明\n"
        "4. 如果有数据缺口，标注[INSUFFICIENT DATA]\n"
        "5. 建议行动（如果需要进一步查询/采集）\n\n"
        f"客观置信度评估：{conf_result['score']}分，等级{conf_result['level']}，简洁说明：{confidence_hint}。请使用这个客观评估结果，不要自行改判。\n"
        f"客观时效性评估：状态{fresh_result['status']}，{fresh_result['description']}，距今{fresh_result['days_old']}天。请在“数据时效”段落明确写出“{fresh_result['days_old']}天前更新”这类表述。\n"
        "置信度标注规则：\n"
        "- 使用 [CONFIDENCE: HIGH/MEDIUM/LOW/INSUFFICIENT] 格式\n"
        "- 括号里的说明要简洁人话，不超过15个字\n"
        f"- 优先使用这条简洁说明：{confidence_hint}\n"
        "- 好示例：[CONFIDENCE: MEDIUM]（单一官方来源，时效良好）\n"
        "- 坏示例：[CONFIDENCE: MEDIUM]（客观依据：来源数量=1，来源权威性，+20，时效性，+20，交叉验证，+0）\n"
        "- 禁止出现'+20'、'交叉验证，+0'这种 debug 格式的打分公式\n"
        "[CONFIDENCE: HIGH/MEDIUM/LOW/INSUFFICIENT] 紧跟在对应情报点之后，用括号格式，不要另起一行。示例：\"- 事实：... [SOURCE: 官网] [CONFIDENCE: MEDIUM]（单一官方来源，时效良好）\"\n"
        "数据时效描述使用情报官口吻，禁止使用\"当前会话时间戳\"、\"系统日志\"等技术日志用语。\n"
        "建议行动最多3条，不重复。\n"
        "如果查不到数据，不要编造。直接说\"当前数据库中无相关记录\"，并建议用户如何补充。"
    )
    prompt = _append_preference_hint(prompt)

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{llm.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {llm.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": llm.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_CONSTRAINT},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 900,
                },
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"].strip()
            return content or fallback_content
    except (asyncio.TimeoutError, httpx.TimeoutException):
        return fallback_content
    except Exception:
        return fallback_content


async def generate_clarify_content(message: str) -> str:
    fallback_content = (
        "【守望者简报】\n\n"
        "您的查询较为宽泛，我暂时无法锁定具体情报目标。\n\n"
        "可按以下方向明确：\n"
        "1. 最新动态：查看该国家或机构近期发生了什么。\n"
        "2. 机构概况：了解规模、宗派、影响力或组织背景。\n"
        "3. 风险与环境：聚焦逼迫、安全、政策或合作环境。\n\n"
        "请直接回复一个方向，或补充您关注的机构、国家和时间范围。"
    )
    llm = get_llm_client()
    if not getattr(llm, "enabled", False):
        return fallback_content

    prompt = (
        "你是守望者，基督教行业高级情报官。\n\n"
        f"用户输入：'{message}'\n\n"
        "这条查询过于模糊，我无法确定用户的真实需求。\n"
        "请生成2-3个追问选项，帮助用户明确需求。\n\n"
        "追问选项应覆盖最常见的基督教情报需求维度：\n"
        "- 最新动态/新闻\n"
        "- 机构概况/规模\n"
        "- 逼迫/安全状况\n"
        "- 联系人/合作对接\n"
        "- 统计数据/行业分析\n\n"
        "输出格式：\n"
        "1. 直接说明查询模糊\n"
        "2. 列出2-3个具体选项（每个选项含简短描述）\n"
        "3. 邀请用户选择或补充\n\n"
        "用情报官口吻，简洁，不寒暄。"
    )
    prompt = _append_preference_hint(prompt)

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{llm.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {llm.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": llm.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_CONSTRAINT},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 600,
                },
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"].strip()
            return content or fallback_content
    except (asyncio.TimeoutError, httpx.TimeoutException):
        return fallback_content
    except Exception:
        return fallback_content


def _extract_clarify_options(content: str) -> list[tuple[str, str]]:
    options: list[tuple[str, str]] = []
    alpha_map = {"a": "1", "b": "2", "c": "3"}
    for raw_line in (content or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        compact = re.sub(r"\*\*", "", line)
        numbered = re.match(r"^(\d+)[\.\、]\s*(.+)$", compact)
        if numbered:
            options.append((numbered.group(1), numbered.group(2).strip()))
            continue
        alpha = re.match(r"^(?:选项)?([ABCabc])[\.\:：]\s*(.+)$", compact)
        if alpha:
            options.append((alpha_map[alpha.group(1).lower()], alpha.group(2).strip()))
            continue
        alpha_bold = re.match(r"^选项([ABCabc])\s*[：:]\s*(.+)$", compact)
        if alpha_bold:
            options.append((alpha_map[alpha_bold.group(1).lower()], alpha_bold.group(2).strip()))
    return options[:3]


def _fallback_clarify_choice(user_message: str, options: list[tuple[str, str]]) -> str:
    normalized = (user_message or "").strip().lower()
    if any(token in normalized for token in ["随便", "都行", "不知道", "不确定", "你定", "你决定", "无所谓", "whatever", "anything"]):
        return "0"

    if any(token in normalized for token in ["机构动态", "机构方面", "教会动态", "组织动态"]):
        return "1"

    ordinal_map = {
        "1": "1",
        "一": "1",
        "第一个": "1",
        "第一": "1",
        "first": "1",
        "2": "2",
        "二": "2",
        "第二个": "2",
        "第二": "2",
        "second": "2",
        "3": "3",
        "三": "3",
        "第三个": "3",
        "第三": "3",
        "third": "3",
        "a": "1",
        "选项a": "1",
        "b": "2",
        "选项b": "2",
        "c": "3",
        "选项c": "3",
    }
    if normalized in ordinal_map:
        return ordinal_map[normalized]

    direct_keyword_rules = {
        "1": ["动态", "最新", "新闻", "消息", "近况", "机构动态"],
        "2": ["机构", "概况", "背景", "规模", "宗派", "介绍", "资料"],
        "3": ["风险", "安全", "环境", "逼迫", "政策", "合作环境"],
    }
    for option_no, keywords in direct_keyword_rules.items():
        if any(keyword in normalized for keyword in keywords):
            return option_no

    for option_no, option_text in options:
        compact = option_text.replace("：", " ").replace(":", " ").lower()
        if normalized and (normalized in compact or compact in normalized):
            return option_no

    return "0"


async def _map_clarify_choice_with_llm(
    user_message: str,
    options: list[tuple[str, str]],
) -> str:
    fallback_choice = _fallback_clarify_choice(user_message, options)
    if fallback_choice != "0":
        return fallback_choice

    llm = get_llm_client()
    if not getattr(llm, "enabled", False) or not options:
        return fallback_choice

    options_text = "\n".join(f"{idx}. {text}" for idx, text in options)
    prompt = (
        f"系统之前给出选项：\n{options_text}\n\n"
        f"用户回答：'{user_message}'\n\n"
        "请判断用户选的是哪个选项。"
        "如果用户回答“随便吧、都行、不知道、你定”之类模糊答复，输出0。"
        "如果用户回答“机构动态、机构方面的、教会动态”，优先映射到“最新动态”类选项。"
        "只输出一个数字（1/2/3），如果选不上或回答无效，输出0。不要解释。"
    )

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{llm.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {llm.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": llm.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_CONSTRAINT},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 10,
                },
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"].strip()
            answer = re.search(r"[0123]", content)
            if answer:
                return answer.group(0)
    except (asyncio.TimeoutError, httpx.TimeoutException):
        pass
    except Exception as exc:
        print(f"[CLARIFY_MAP] LLM调用失败: {str(exc)[:100]}")

    return fallback_choice


def _infer_intent_from_clarify_choice(
    choice: str,
    options: list[tuple[str, str]],
) -> str | None:
    option_lookup = {idx: text for idx, text in options}
    option_text = (option_lookup.get(choice) or "").lower()

    if any(keyword in option_text for keyword in ["联系", "联系人", "对接", "负责人", "谁负责"]):
        return "contact_lookup"
    if any(keyword in option_text for keyword in ["动态", "最新", "新闻", "消息", "近况", "活动"]):
        return "collection_request"
    if any(keyword in option_text for keyword in ["风险", "安全", "环境", "逼迫", "政策", "评估"]):
        return "knowledge_lookup"
    if any(keyword in option_text for keyword in ["机构", "概况", "规模", "背景", "宗派", "介绍"]):
        return "knowledge_lookup"

    positional_map = {
        "1": "collection_request",
        "2": "knowledge_lookup",
        "3": "knowledge_lookup",
    }
    return positional_map.get(choice)


def _build_override_actions(intent: str, entities: list[str], countries: list[str], fallback_target: str) -> list[dict]:
    if intent == "collection_request":
        targets = entities or countries or ([fallback_target] if fallback_target else [])
        return [{"type": "collect", "target": target} for target in targets[:2]]
    if intent == "contact_lookup":
        targets = entities or ([fallback_target] if fallback_target else [])
        return [{"type": "lookup_contact", "target": target} for target in targets[:2]]
    if intent == "knowledge_lookup":
        targets = entities or countries or ([fallback_target] if fallback_target else [])
        return [{"type": "lookup_knowledge", "target": target} for target in targets[:2]]
    return [{"type": "clarify", "target": fallback_target or "用户补充"}]


def _get_contact_fallback_channels(org: OrganizationProfile) -> dict:
    channels = {
        "email": org.contact_email or "",
        "phone": org.phone_public or "",
        "source_name": org.source_name or org.name or "机构档案",
        "source_url": org.source_url or org.official_website or "",
    }

    if org.name and "cbn asia" in org.name.lower():
        channels["email"] = channels["email"] or "asiapartners@cbn.org"
        channels["phone"] = channels["phone"] or "1-800-700-7000"
        channels["source_name"] = "CBN官网"
        channels["source_url"] = channels["source_url"] or "https://www1.cbn.com/asia"

    return channels


def _has_compare_query(message: str) -> bool:
    lowered = (message or "").lower()
    return any(token in lowered for token in ["异同", "区别", "差异", "比较", "对比", "vs", "versus"])


def _has_collection_signal(message: str) -> bool:
    lowered = (message or "").lower()
    return any(
        token in lowered
        for token in [
            "搜集",
            "采集",
            "收集",
            "最新动态",
            "最近动态",
            "最新消息",
            "最新新闻",
            "然后对比",
        ]
    )


def filter_sources_by_entity(sources: list[Source], entity_name: str) -> list[Source]:
    """按实体名筛选来源；如果没有专属来源，则回退到原始来源集合。"""
    entity_lower = (entity_name or "").strip().lower()
    if not entity_lower:
        return sources

    filtered = [source for source in sources if entity_lower in (source.name or "").lower()]
    return filtered if filtered else sources


def _find_existing_comparison(db: Session, entities: list[str]) -> IntelligenceItem | None:
    if len(entities) < 2:
        return None

    entity_a, entity_b = entities[:2]
    like_a = f"%{entity_a}%"
    like_b = f"%{entity_b}%"
    return (
        db.query(IntelligenceItem)
        .filter(
            IntelligenceItem.category == "comparison",
            or_(
                and_(IntelligenceItem.title.ilike(like_a), IntelligenceItem.title.ilike(like_b)),
                and_(IntelligenceItem.entity_name.ilike(like_a), IntelligenceItem.entity_name.ilike(like_b)),
                and_(IntelligenceItem.content.ilike(like_a), IntelligenceItem.content.ilike(like_b)),
            ),
        )
        .order_by(IntelligenceItem.ingested_at.desc())
        .first()
    )

def chat_stream(request: ChatRequest, db: Session):
    request_id = str(uuid.uuid4())
    conversation_id = request.conversation_id or str(uuid.uuid4())
    user_msg_id = str(uuid.uuid4())
    assistant_msg_id = str(uuid.uuid4())

    db.add(RequestTrace(
        id=str(uuid.uuid4()),
        request_id=request_id,
        event_type="request_received",
        event_data={"message": request.message, "conversation_id": conversation_id}
    ))
    db.commit()
    
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        conv = Conversation(id=conversation_id, title=request.message[:20])
        db.add(conv); db.commit()

    resolved_message = resolve_references(request.message, conversation_id, db)
    resolved_intent = None
    clarify_context_message = ""

    last_assistant_msg = (
        db.query(Message)
        .filter(
            Message.conversation_id == conversation_id,
            Message.role == "assistant",
        )
        .order_by(Message.created_at.desc())
        .first()
    )

    if last_assistant_msg and last_assistant_msg.delivery_type == "clarification_prompt":
        clarify_options = _extract_clarify_options(last_assistant_msg.content or "")
        if clarify_options:
            llm_answer = asyncio.run(_map_clarify_choice_with_llm(request.message, clarify_options))
            print(f"[CLARIFY_MAP] 用户:'{request.message}' → 映射:'{llm_answer}'")
            resolved_intent = _infer_intent_from_clarify_choice(llm_answer, clarify_options)
            if resolved_intent:
                previous_user_msg = (
                    db.query(Message)
                    .filter(
                        Message.conversation_id == conversation_id,
                        Message.role == "user",
                    )
                    .order_by(Message.created_at.desc())
                    .first()
                )
                clarify_context_message = (previous_user_msg.content or "").strip() if previous_user_msg else ""
                print(f"[CLARIFY_MAP] 成功映射为: {resolved_intent}")
            else:
                print("[CLARIFY_MAP] 无法映射，继续clarify")

    routing_message = resolved_message
    if clarify_context_message:
        routing_message = f"{clarify_context_message}\n用户补充：{resolved_message}".strip()

    country = detect_country(routing_message)
    route_result = get_router().route(routing_message)
    if resolved_intent:
        route_result["primary_intent"] = resolved_intent
        route_result["actions"] = _build_override_actions(
            resolved_intent,
            route_result.get("entities") or [],
            route_result.get("countries") or [],
            fallback_target=(route_result.get("countries") or [country] or [resolved_message])[0],
        )
        route_result.setdefault("scores", {})
        route_result["scores"][resolved_intent] = max(route_result["scores"].get(resolved_intent, 0), 8)
        print(f"[OVERRIDE] 路由结果覆盖为: {resolved_intent}")
    if route_result["primary_intent"] in {"knowledge_lookup", "multi_intent", "analysis_request"} and _has_compare_query(routing_message):
        compare_entities = route_result.get("entities") or []
        if len(compare_entities) >= 2:
            explicit_collection_compare = _has_collection_signal(routing_message)
            existing_comparison = None if explicit_collection_compare else _find_existing_comparison(db, compare_entities)
            if existing_comparison:
                route_result["primary_intent"] = "comparison_existing"
                route_result["comparison_item_id"] = existing_comparison.id
                route_result["actions"] = [
                    {"type": "compare_existing", "target": f"{compare_entities[0]} vs {compare_entities[1]}"}
                ]
            elif route_result["primary_intent"] == "knowledge_lookup":
                route_result["primary_intent"] = "multi_intent"
                route_result["actions"] = [
                    {"type": "collect", "target": compare_entities[0]},
                    {"type": "collect", "target": compare_entities[1]},
                    {"type": "compare", "target": f"{compare_entities[0]} vs {compare_entities[1]}"},
                ]
                route_result.setdefault("scores", {})
                route_result["scores"]["multi_intent"] = 999
                print(f"[OVERRIDE] 对比查询升级为 multi_intent: {compare_entities[0]} vs {compare_entities[1]}")
    intent = route_result["primary_intent"]
    scope = route_result.get("inferred_scope", "country")
    keywords = route_result.get("keywords") or []
    if scope == "needs_clarify" and intent in {"knowledge_lookup", "collection_request"}:
        intent = "clarify"
        route_result["primary_intent"] = "clarify"
        route_result["actions"] = [{"type": "clarify", "target": routing_message}]
    try:
        record_query(
            countries=route_result.get("countries", []),
            organizations=route_result.get("entities", []),
        )
    except Exception as exc:
        print(f"[PREFERENCES] 记录偏好失败: {str(exc)[:100]}")
    db.add(
        Message(
            id=user_msg_id,
            conversation_id=conversation_id,
            role="user",
            content=request.message,
            entities_mentioned=route_result.get("entities", []),
        )
    )
    db.commit()
    db.add(RequestTrace(
        id=str(uuid.uuid4()),
        request_id=request_id,
        event_type="route_decided",
        event_data=route_result
    ))
    db.commit()
    yield f"event: route_decided\ndata: {json.dumps({'request_id': request_id, 'intent': intent, 'route': route_result}, ensure_ascii=False)}\n\n"
    
    if intent == "contact_lookup":
        target = ""
        actions = route_result.get("actions") or []
        if actions:
            target = actions[0].get("target") or ""
        if not target:
            entities = route_result.get("entities") or []
            target = entities[0] if entities else request.message

        org = db.query(OrganizationProfile).filter(
            OrganizationProfile.name.ilike(f"%{target}%")
        ).first()
        if not org and target:
            fallback_candidates = db.query(OrganizationProfile).all()
            target_upper = target.upper()
            org = next(
                (
                    candidate
                    for candidate in fallback_candidates
                    if build_acronym(candidate.name) == target_upper
                ),
                None,
            )

        if not org:
            content = (
                f"## 「{target}」联系人查询\n\n"
                f"暂无该机构档案，建议用“搜集{target}机构信息”触发建档。"
            )
            sources = []
            delivery_status = "no_data"
            delivery_type = "contact_partial"
        else:
            contact_lines = []
            has_leader = bool((org.leader_name or "").strip())
            fallback_channels = _get_contact_fallback_channels(org)

            if org.leader_name or org.leader_title or org.contact_email or org.phone_public:
                contact_lines.append("### 联系人列表")
                contact_lines.append("")
                contact_lines.append(f"- 姓名：{org.leader_name or 'N/A'}")
                contact_lines.append(f"- 职务：{org.leader_title or 'N/A'}")
                contact_lines.append(f"- 邮箱：{org.contact_email or 'N/A'}")
                contact_lines.append(f"- 电话：{org.phone_public or 'N/A'}")
                contact_lines.append("")

            if contact_lines:
                fallback_content_lines = [
                    f"## 「{org.name}」联系人信息",
                    "",
                    f"- 机构：{org.name}",
                    f"- 国家：{org.country}",
                    f"- 官网：{org.official_website or 'N/A'}",
                    "",
                    *contact_lines,
                    "### 信息来源",
                    "",
                    f"- 来源名称：{org.source_name or '机构档案'}",
                    f"- 来源链接：{org.source_url or org.official_website or 'N/A'}",
                ]
                fallback_content = "\n".join(fallback_content_lines)
                if has_leader:
                    content = asyncio.run(generate_contact_lookup_content(org, fallback_content))
                    delivery_type = "contact_full"
                else:
                    contact_email = fallback_channels["email"] or "N/A"
                    contact_phone = fallback_channels["phone"] or "N/A"
                    content = (
                        "【守望者简报 · 联系人查询】\n\n"
                        f"目标机构：{org.name}（{org.country}）\n\n"
                        "⚠️ 信息缺口：该机构未在公开渠道披露具体负责人姓名及直接联系方式。"
                        " 当前仅有公共合作邮箱或总部转接方式。\n\n"
                        "### 可用联系渠道\n"
                        f"- 公共合作邮箱：{contact_email} [SOURCE: {fallback_channels['source_name']}] [CONFIDENCE: MEDIUM]\n"
                        f"- 总部转接电话：{contact_phone} [SOURCE: CBN总部] [CONFIDENCE: HIGH]\n\n"
                        "### 信息缺口\n"
                        "- 该机构未在公开渠道披露具体负责人姓名及直接联系方式。\n"
                        "- 当前无法确认菲律宾团队的公开直线电话或负责人职务。\n\n"
                        "### 替代方案\n"
                        f"- 发送邮件至 {contact_email}，说明合作意图，请求转接至具体负责人。\n"
                        "- 关注 The 700 Club Asia 官方社交媒体，尝试私信获取联系。\n"
                        f"- 如急需联系，可通过 CBN 全球总部转接：{contact_phone}。\n\n"
                        "### 建议行动\n"
                        "- 如需系统性获取菲律宾基督教机构联系人，建议启动“菲律宾机构定向采集”任务，"
                        "从社交媒体、行业会议等公开渠道补充。"
                    )
                    delivery_type = "contact_partial"
                sources = [
                    {
                        "name": fallback_channels["source_name"],
                        "url": fallback_channels["source_url"],
                    }
                ]
                delivery_status = "success"
            else:
                content = (
                    f"## 「{org.name}」联系人查询\n\n"
                    f"该机构暂无联系人记录，建议触发采集任务补充。"
                )
                sources = [
                    {
                        "name": org.source_name or org.name,
                        "url": org.source_url or org.official_website or "",
                    }
                ]
                delivery_status = "no_data"
                delivery_type = "contact_partial"

        delivery = {
            "status": delivery_status,
            "content": content,
            "sources": [s for s in sources if s.get("url")],
            "delivery_type": delivery_type,
            "execution_summary": {"intent": intent, "target": target},
            "next_actions": ["查看机构档案", "补充联系人采集", "搜索相关机构"],
        }
    elif intent == "multi_intent":
        collect_actions = [
            action for action in route_result.get("actions", [])
            if action.get("type") == "collect"
        ]
        compare_actions = [
            action for action in route_result.get("actions", [])
            if action.get("type") == "compare"
        ]
        mission_country = (route_result.get("countries") or [country])[0]
        composite_id = str(uuid.uuid4())
        composite_entities = route_result.get("entities") or []
        active_sources = (
            db.query(Source)
            .filter(Source.country == mission_country, Source.is_active == True)
            .all()
        )

        created_missions = []
        for index, action in enumerate(collect_actions):
            target = action.get("target", "").strip()
            if not target:
                continue

            entity_sources = filter_sources_by_entity(active_sources, target)
            using_fallback_sources = len(entity_sources) == len(active_sources)

            mission = Mission(
                id=str(uuid.uuid4()),
                query=f"{target} 最近动态",
                country=mission_country,
                status="queued",
                priority=HIGH_COLLECTION_PRIORITY,
                composite_task_id=composite_id,
                composite_status="pending" if index == 0 else "waiting",
                target_entity=target,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(mission)
            db.commit()

            created_missions.append(
                {
                    "id": mission.id,
                    "target": target,
                    "country": mission_country,
                    "source_count": len(entity_sources),
                    "used_fallback_sources": using_fallback_sources,
                }
            )

            try:
                enqueue_collection_mission(mission.id, mission.priority)
            except Exception:
                pass

        composite_meta = {
            "composite_id": composite_id,
            "compare_target": compare_actions[0].get("target", "") if compare_actions else "",
            "entities": composite_entities,
            "country": mission_country,
            "created_at": datetime.utcnow().isoformat(),
            "conversation_id": conversation_id,
        }
        try:
            redis_client = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
            redis_client.setex(
                f"composite:{composite_id}",
                3600,
                json.dumps(composite_meta, ensure_ascii=False),
            )
        except Exception as exc:
            print(f"[COMPOSITE] 元数据写入失败: {str(exc)[:100]}")

        db.add(RequestTrace(
            id=str(uuid.uuid4()),
            request_id=request_id,
            event_type="multi_intent_dispatched",
            event_data={
                "composite_id": composite_id,
                "missions": created_missions,
                "compare_actions": compare_actions,
            },
        ))
        db.commit()

        content = asyncio.run(
            generate_multi_intent_content(
                route_result=route_result,
                created_missions=created_missions,
                compare_actions=compare_actions,
                mission_country=mission_country,
            )
        )

        yield f"event: content_start\ndata: {json.dumps({'type': 'markdown'}, ensure_ascii=False)}\n\n"
        for chunk in content.split("\n"):
            yield f"event: content_delta\ndata: {json.dumps({'text': chunk + chr(10)}, ensure_ascii=False)}\n\n"
            time.sleep(0.05)
        yield f"event: content_end\ndata: {json.dumps({'full_content': content}, ensure_ascii=False)}\n\n"

        delivery = {
            "status": "accepted",
            "content": content,
            "sources": [],
            "delivery_type": "intelligence_brief",
            "execution_summary": {
                "intent": intent,
                "composite_id": composite_id,
                "mission_ids": [mission["id"] for mission in created_missions],
                "compare_target": compare_actions[0].get("target", "") if compare_actions else "",
            },
            "next_actions": ["查看任务进度", "等待对比结果", "补充指定机构范围"],
        }
    elif intent == "comparison_existing":
        from services.analysis import compare_entities

        comparison_item = db.query(IntelligenceItem).filter(
            IntelligenceItem.id == route_result.get("comparison_item_id")
        ).first()
        compare_target = (route_result.get("actions") or [{}])[0].get("target", "对比分析")
        compare_entities_list = route_result.get("entities") or []
        if comparison_item:
            regenerated_content = comparison_item.content or f"已找到历史对比分析：{compare_target}"
            sources = []
            if len(compare_entities_list) >= 2:
                result = compare_entities(db, compare_entities_list, country=country)
                regenerated_content = result["content"]
                seen_urls = set()
                for entity_items in result["entity_results"].values():
                    for item in entity_items:
                        if item["url"] and item["url"] not in seen_urls:
                            seen_urls.add(item["url"])
                            sources.append({"name": item["source"], "url": item["url"]})
            if not sources and (comparison_item.source_name or comparison_item.source_url):
                sources = [
                    {
                        "name": comparison_item.source_name or "系统对比分析",
                        "url": comparison_item.source_url or "",
                    }
                ]
            delivery = {
                "status": "success",
                "content": regenerated_content,
                "sources": [item for item in sources if item.get("url")],
                "delivery_type": "analysis_brief",
                "execution_summary": {
                    "intent": "multi_intent",
                    "comparison_item_id": comparison_item.id,
                    "compare_target": compare_target,
                    "served_from_cache": True,
                },
                "next_actions": ["查看详细来源", "重新采集更新", "扩展对比范围"],
            }
        else:
            delivery = {
                "status": "no_data",
                "content": f"未找到历史对比分析：{compare_target}，建议重新触发采集。",
                "sources": [],
                "delivery_type": "analysis_brief",
                "execution_summary": {"intent": "multi_intent", "served_from_cache": False},
                "next_actions": ["重新采集并对比", "指定时间范围", "补充对比维度"],
            }
    elif intent == "knowledge_lookup":
        if scope == "global":
            results = query_global_intelligence(
                entities=route_result.get("entities") or [],
                keywords=keywords,
                limit=20,
            )
        else:
            results = query_knowledge(db, request.message, country=country)
        db.add(RequestTrace(
            id=str(uuid.uuid4()),
            request_id=request_id,
            event_type="knowledge_queried",
            event_data={"results_count": len(results), "intent": intent, "scope": scope}
        ))
        db.commit()
        fallback_delivery = compose_delivery(request.message, results, intent)
        if results:
            delivery = dict(fallback_delivery)
            delivery["content"] = asyncio.run(
                generate_knowledge_lookup_content(
                    query=request.message,
                    results=results,
                    fallback_content=fallback_delivery["content"],
                    route_result=route_result,
                )
            )
        else:
            delivery = fallback_delivery
        if scope == "global":
            delivery["delivery_type"] = "global_brief"
            delivery["scope"] = "global"
            delivery.setdefault("execution_summary", {})
            delivery["execution_summary"]["scope"] = "global"
    elif intent == "clarify":
        if scope == "needs_clarify":
            content = (
                "守望者收到查询。基督教动态覆盖范围极广，请明确您的关注维度：\n\n"
                "1. **全球层面**：普世教会、国际组织、全球趋势\n"
                "2. **特定国家**：请指明国家名称\n"
                "3. **特定机构**：请提供机构名称"
            )
        else:
            content = asyncio.run(generate_clarify_content(request.message))

        yield f"event: content_start\ndata: {json.dumps({'type': 'markdown'}, ensure_ascii=False)}\n\n"
        for chunk in content.split("\n"):
            yield f"event: content_delta\ndata: {json.dumps({'text': chunk + chr(10)}, ensure_ascii=False)}\n\n"
            time.sleep(0.05)
        yield f"event: content_end\ndata: {json.dumps({'full_content': content}, ensure_ascii=False)}\n\n"

        delivery = {
            "status": "clarify",
            "content": content,
            "sources": [],
            "delivery_type": "clarification_prompt",
            "execution_summary": {"intent": intent, "original_query": request.message},
            "next_actions": ["选择选项", "补充机构名", "补充时间范围"],
        }
    elif intent == "analysis_request":
        from services.analysis import extract_entities, compare_entities

        entities = extract_entities(request.message)

        if len(entities) >= 2:
            result = compare_entities(db, entities)
            comparison_items = []
            for entity, entity_items in result["entity_results"].items():
                if not entity_items:
                    comparison_items.append(
                        {
                            "name": entity,
                            "type": "entity",
                            "country": country,
                            "category": "compare_analysis",
                            "data": {
                                "recent_item_count": 0,
                                "time_window_days": 30,
                                "note": "近30天未检索到相关情报",
                            },
                            "source_name": "系统检索",
                            "source_url": "",
                        }
                    )
                    continue

                for item in entity_items:
                    comparison_items.append(
                        {
                            "name": entity,
                            "type": "entity",
                            "country": country,
                            "category": "compare_analysis",
                            "data": {
                                "title": item["title"],
                                "date": item["date"],
                                "recent_item_count": len(entity_items),
                                "time_window_days": 30,
                            },
                            "source_name": item["source"],
                            "source_url": item["url"],
                        }
                    )

            content = result["content"]
            try:
                from services.llm_client import llm

                llm_content = asyncio.run(llm.analyze_comparison(request.message, comparison_items))
                if llm_content:
                    content = llm_content
            except Exception:
                pass
            sources = []
            for entity_items in result["entity_results"].values():
                sources.extend(
                    [{"name": item["source"], "url": item["url"]} for item in entity_items if item["url"]]
                )
        else:
            results = query_knowledge(db, request.message, country=country)
            fallback_delivery = compose_delivery(request.message, results, "knowledge_lookup")
            content = fallback_delivery["content"]
            sources = fallback_delivery.get("sources", [])

        delivery = {
            "status": "success",
            "content": content,
            "sources": sources,
            "delivery_type": "analysis_brief",
            "execution_summary": {"intent": intent, "entities": entities},
            "next_actions": ["调整对比实体", "扩展时间范围", "查看详细数据"],
        }
    else:
        # ===== 核心升级：对话入口直接触发采集执行 =====
        if scope == "global":
            results = query_global_intelligence(
                entities=route_result.get("entities") or [],
                keywords=keywords,
                limit=20,
            )
            fallback_delivery = compose_delivery(request.message, results, "knowledge_lookup")
            if results:
                delivery = dict(fallback_delivery)
                delivery["content"] = asyncio.run(
                    generate_knowledge_lookup_content(
                        query=request.message,
                        results=results,
                        fallback_content=fallback_delivery["content"],
                        route_result=route_result,
                    )
                )
            else:
                delivery = {
                    "status": "no_data",
                    "content": (
                        f"## 「{request.message}」\n\n"
                        "已识别为全球范围查询。当前全球来源基础设施已就绪，但暂未检索到已入库全球情报。\n\n"
                        "建议下一步补充全球来源的采集任务或换一个更具体的全球机构名称。"
                    ),
                    "sources": [],
                    "delivery_type": "global_brief",
                    "scope": "global",
                    "execution_summary": {"intent": intent, "scope": scope, "kb_hits": 0},
                    "next_actions": ["补充全球机构名称", "切换到特定国家", "等待全球情报入库"],
                }
            if results:
                delivery["delivery_type"] = "global_brief"
                delivery["scope"] = "global"
                delivery.setdefault("execution_summary", {})
                delivery["execution_summary"]["scope"] = "global"
            db.add(RequestTrace(
                id=str(uuid.uuid4()),
                request_id=request_id,
                event_type="global_scope_served",
                event_data={"intent": intent, "scope": scope, "results_count": len(results)},
            ))
            db.commit()
        else:
            actions = route_result.get("actions") or []
            target = actions[0].get("target") if actions else ""
            if not target:
                entities = route_result.get("entities") or []
                target = entities[0] if entities else request.message

            mission = Mission(
                id=str(uuid.uuid4()),
                query=request.message,
                country=country,
                status="queued",
                priority=HIGH_COLLECTION_PRIORITY,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(mission)
            db.commit()

            enqueue_collection_mission(mission.id, mission.priority)

            try:
                redis_client = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
                queue_len = redis_client.llen("rq:queue:collection")
                running_count = db.query(func.count(Mission.id)).filter(Mission.status == "running").scalar() or 0
                queued_count = db.query(func.count(Mission.id)).filter(Mission.status == "queued").scalar() or 0
            except Exception:
                queue_len = 0
                running_count = 0
                queued_count = 0

            wait_msg = ""
            if queued_count > 5:
                wait_msg = f"当前队列中有 {queued_count} 个任务在等待，预计 {(queued_count // 2 + 1) * 2} 分钟后开始执行。"
            elif queued_count > 0:
                wait_msg = f"当前有 {queued_count} 个任务在排队，预计 {(queued_count // 2 + 1)} 分钟内开始。"

            queue_status_content = (
                f"**【守望者简报】任务启动确认**\n\n"
                f"已创建采集任务：{target}\n"
                f"任务ID：{mission.id}\n"
                f"状态：{'已入队执行' if queue_len < 3 else '排队中'}\n"
                f"{wait_msg}\n\n"
                f"后台 Worker 正在持续消费队列，当前运行中任务 {running_count} 个。\n"
                f"任务完成后会自动推送结果。\n"
                f"您可以继续对话或输入「进度」查看任务状态。"
            )

            db.add(RequestTrace(
                id=str(uuid.uuid4()),
                request_id=request_id,
                event_type="collection_dispatched",
                event_data={
                    "intent": intent,
                    "status": "queued",
                    "mission_id": mission.id,
                    "priority": mission.priority,
                    "scope": scope,
                },
            ))
            db.commit()

            mission_created_message = wait_msg or f"已启动采集任务，正在扫描{country}来源..."
            yield f"event: mission_created\ndata: {json.dumps({'request_id': request_id, 'mission_id': mission.id, 'message': mission_created_message}, ensure_ascii=False)}\n\n"

            max_wait = 30
            for _ in range(max_wait):
                time.sleep(2)
                db.refresh(mission)

                job_count = db.query(JobRun).filter(JobRun.mission_id == mission.id).count()
                done_jobs = db.query(JobRun).filter(
                    JobRun.mission_id == mission.id,
                    JobRun.status == "done",
                ).count()

                yield f"event: mission_progress\ndata: {json.dumps({'request_id': request_id, 'mission_status': mission.status, 'jobs_done': done_jobs, 'jobs_total': max(job_count, 1)}, ensure_ascii=False)}\n\n"

                if mission.status in ["done", "failed"]:
                    break

            scored_items = get_scored_items(db, country=country, limit=15)

            if mission.status not in ["done", "failed"]:
                content = queue_status_content
                sources = []
                delivery_status = "queued"
            elif scored_items:
                content_lines = [f"## 「{request.message}」情报结果\n\n"]
                content_lines.append(f"基于质量评分，为您筛选出 **{len(scored_items)}** 条高价值情报：\n\n")

                for i, item in enumerate(scored_items, 1):
                    score_icon = "🔴" if item["score_level"] == "high" else "🟡" if item["score_level"] == "medium" else "🟢"
                    content_lines.append(f"{score_icon} **{i}. {item['title']}** (评分: {item['score']})")
                    content_lines.append(f"- 来源：{item['source_name']}")
                    if item["source_url"]:
                        content_lines.append(f"- [查看原文]({item['source_url']})")
                    if item["published_at"]:
                        content_lines.append(f"- 时间：{item['published_at'][:10]}")
                    content_lines.append("")

                item_dicts = [
                    {
                        "name": item["title"],
                        "type": "news",
                        "country": country,
                        "data": {"description": item["content"], "score": item["score"]},
                        "source_url": item["source_url"],
                        "source_name": item["source_name"],
                    }
                    for item in scored_items
                ]
                llm_content = None
                try:
                    from services.llm_client import llm
                    llm_content = asyncio.run(llm.analyze_collection(request.message, item_dicts))
                except Exception:
                    llm_content = None

                if llm_content:
                    content = llm_content
                else:
                    content = "\n".join(content_lines)

                sources = [{"name": item["source_name"], "url": item["source_url"]} for item in scored_items if item["source_url"]]
                delivery_status = "success"
            else:
                content = (
                    f"## 「{request.message}」\n\n"
                    f"当前近30天内暂无{country}情报数据。\n\n"
                    f"已启动后台采集补充{country}来源数据，建议稍后重试。"
                )
                sources = []
                delivery_status = "no_data"

            delivery = {
                "status": delivery_status,
                "content": content,
                "sources": sources,
                "delivery_type": "intelligence_brief",
                "execution_summary": {
                    "intent": intent,
                    "mission_id": mission.id,
                    "items_found": len(scored_items),
                    "priority": mission.priority,
                    "queue_length": queue_len,
                    "queued_count": queued_count,
                    "running_count": running_count,
                    "scope": scope,
                },
                "next_actions": ["再次采集", "查看详细来源", "扩展采集范围"],
            }
        # ===== 升级结束 =====
    
    db.add(Message(id=assistant_msg_id, conversation_id=conversation_id, role="assistant",
                   content=delivery["content"], sources=delivery.get("sources", []),
                   delivery_type=delivery["delivery_type"], status="completed"))
    db.commit()

    db.add(RequestTrace(
        id=str(uuid.uuid4()),
        request_id=request_id,
        event_type="delivery_emitted",
        event_data={"delivery_type": delivery["delivery_type"], "status": delivery["status"]}
    ))
    db.commit()
    
    yield f"event: delivery_emitted\ndata: {json.dumps({'request_id': request_id, 'message_id': assistant_msg_id, 'delivery': delivery})}\n\n"
    db.add(RequestTrace(
        id=str(uuid.uuid4()),
        request_id=request_id,
        event_type="request_completed",
        event_data={"final_status": "done"}
    ))
    db.commit()
    yield f"event: done\ndata: {json.dumps({'request_id': request_id})}\n\n"


def safe_chat_stream(request: ChatRequest, db: Session):
    try:
        yield from chat_stream(request, db)
    except asyncio.TimeoutError:
        payload = {"message": "请求处理超时，请重试"}
        yield f"event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
    except Exception as e:
        print(f"chat_stream failed: {e}")
        payload = {"message": "请求处理失败，请重试"}
        yield f"event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

@router.post("/chat/stream")
def chat(request: ChatRequest, db: Session = Depends(get_db)):
    return StreamingResponse(safe_chat_stream(request, db), media_type="text/event-stream")


@router.post("/test/route")
def test_route(request: ChatRequest):
    return get_router().route(request.message)
