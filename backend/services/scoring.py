from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from models.database import IntelligenceItem, Source


# ===== 评分规则 =====

def score_timeliness(published_at: datetime) -> int:
    """时效性评分（25%权重）"""
    if not published_at:
        return 50  # 未知时间给中等分

    now = datetime.utcnow()
    delta = now - published_at

    if delta <= timedelta(days=7):
        return 100
    elif delta <= timedelta(days=30):
        return 80
    elif delta <= timedelta(days=90):
        return 50
    else:
        return 20


def score_source_influence(source: Source) -> int:
    """机构影响力评分（20%权重）"""
    if not source:
        return 50

    base_score = {
        "high": 100,
        "medium": 70,
        "low": 40,
    }.get(source.trust_level, 50)

    # 官方/RSS来源额外加分
    if source.type in ["rss", "youtube_channel", "official"]:
        base_score = min(100, base_score + 10)

    return base_score


def score_uniqueness(title: str) -> int:
    """内容独特性评分（20%权重）"""
    if not title:
        return 30

    title_lower = title.lower()

    # 高独特性（政策/人事/合作/战略）
    high_keywords = [
        "政策", "声明", "宣布", "任命", "合作", "签署", "通过",
        "冲突", "逼迫", "战略", "合并", "分裂", "调查", "预算", "新领导",
        "policy", "announce", "appoint", "cooperate", "sign",
        "conflict", "persecution", "strategy", "merge", "split", "leaders",
    ]

    # 低独特性（讲道/灵修/常规）
    low_content = [
        "讲道", "灵修", "敬拜", "祷告会", "主日", "崇拜", "赞美",
        "sermon", "devotional", "worship", "prayer meeting", "sunday",
        "liturgy", "homily",
    ]

    # 如果是 YouTube 讲道系列，直接低分
    if any(kw in title_lower for kw in low_content):
        return 30

    # 如果是 "Run Through" 或 "The Mission" 系列，也低分
    if "run through" in title_lower or "the mission" in title_lower:
        return 25

    # 原有逻辑保留
    mid_keywords = [
        "活动", "项目", "会议", "聚会", "培训", "宣教", "复兴", "庆典",
        "event", "project", "conference", "gathering", "training", "revival",
    ]

    if any(kw in title_lower for kw in high_keywords):
        return 100
    elif any(kw in title_lower for kw in mid_keywords):
        return 60
    else:
        return 50  # 默认中等


def score_completeness(item: IntelligenceItem) -> int:
    """数据完整性评分（15%权重）"""
    checks = [
        bool(item.title and len(item.title) > 5),
        bool(item.content and len(item.content) > 10),
        bool(item.source_url),
        bool(item.published_at),
        bool(item.source_name),
    ]

    passed = sum(checks)

    if passed == 5:
        return 100
    elif passed >= 4:
        return 75
    elif passed >= 3:
        return 50
    else:
        return 25


def score_action_orientation(title: str) -> int:
    """行动导向评分（20%权重）"""
    if not title:
        return 30

    title_lower = title.lower()

    # 明确低分内容
    low_content = ["the mission (", "devotional", "daily time with god", "run through", "homily", "liturgy songs"]
    if any(kw in title_lower for kw in low_content):
        return 20  # 直接最低分

    # 只有 "Pastor + 人名 + 变动/任命类词" 才给中等分
    pastor_change_words = ["announces", "appoints", "new pastor", "pastoral transition", "任命", "新任", "接任", "transition"]
    if "pastor" in title_lower and any(kw in title_lower for kw in pastor_change_words):
        return 60  # 人事变动中等分
    elif "pastor" in title_lower:
        return 25  # 单纯讲道直接低分，不抬升

    # 强行动词（可立即响应）
    strong_actions = [
        "发布", "启动", "任命", "合作", "宣布", "推出", "成立",
        "签署", "通过", "召开", "举办", "开始",
        "launch",
        "announce", "appoint", "cooperate", "sign", "establish",
        "hold", "start", "release", "introduce",
    ]

    # 弱行动词（计划性）
    weak_actions = [
        "讨论", "计划", "考虑", "展望", "准备", "筹备",
        "discuss", "plan", "consider", "prepare",
    ]

    if any(kw in title_lower for kw in strong_actions):
        return 100
    elif any(kw in title_lower for kw in weak_actions):
        return 60
    else:
        return 30


def score_christian_relevance(title: str) -> int:
    """基督教相关性评分——无关内容直接扣分"""
    if not title:
        return 50  # 无标题给中等，不极端

    title_lower = title.lower()

    strong_relevant = [
        "christian", "church", "jesus", "gospel", "evangelical",
        "pastor", "worship", "mission", "bible", "faith", "prayer",
        "教会", "基督", "福音", "牧师", "宣教", "敬拜", "圣经", "信仰",
    ]

    irrelevant = [
        "taylor swift", "wedding planner", "celebrity", "fashion",
        "makeup", "recipe", "cooking", "gaming", "sports betting",
        "体育博彩", "化妆", "食谱", "游戏", "婚礼策划",
    ]

    if any(kw in title_lower for kw in irrelevant):
        return 0  # 直接零分

    if any(kw in title_lower for kw in strong_relevant):
        return 100  # 强相关

    return 50  # 默认中等


def score_content_penalty(title: str) -> int:
    """常规灵修/直播/聚会内容惩罚——这类内容情报价值低"""
    if not title:
        return 0  # 无惩罚

    title_lower = title.lower()

    # 强惩罚：常规直播/敬拜/祷告会（几乎无情报价值）
    strong_penalty = [
        "worship and healing service", "prayer revival meeting",
        "prayer breakthrough", "worship service, live", "healing service, live",
        "sunday service", "worship night", "prayer night",
        "敬拜医治", "祷告复兴会", "主日崇拜", "敬拜之夜",
    ]

    # 中等惩罚：灵修问答/个人成长类
    mid_penalty = [
        "feeling empty inside", "here's why", "the father you can rely on",
        "daily time with god", "the habit of", "ano ang", "sumuko ka na ba",
        "ano ang tamang response", "ano ang dapat",
        "灵修", "为什么", "依靠神", "每日亲近神",
    ]

    if any(kw in title_lower for kw in strong_penalty):
        return -40

    if any(kw in title_lower for kw in mid_penalty):
        return -25

    return 0


def calculate_score(item: IntelligenceItem, source: Source = None) -> Dict[str, Any]:
    """计算情报综合质量分"""
    timeliness = score_timeliness(item.published_at or item.ingested_at)
    influence = score_source_influence(source)
    uniqueness = score_uniqueness(item.title)
    completeness = score_completeness(item)
    action = score_action_orientation(item.title)

    total = int(
        timeliness * 0.25 +
        influence * 0.20 +
        uniqueness * 0.20 +
        completeness * 0.15 +
        action * 0.20
    )

    # 叠加基督教相关性
    relevance = score_christian_relevance(item.title)
    if relevance == 0:
        total = int(total * 0.3)  # 无关内容最多30分
    elif relevance == 100:
        total = min(100, total + 5)

    # 新增：常规内容惩罚
    penalty = score_content_penalty(item.title)
    total = max(0, total + penalty)

    return {
        "total_score": total,
        "dimensions": {
            "timeliness": {"score": timeliness, "weight": 0.25, "weighted": int(timeliness * 0.25)},
            "influence": {"score": influence, "weight": 0.20, "weighted": int(influence * 0.20)},
            "uniqueness": {"score": uniqueness, "weight": 0.20, "weighted": int(uniqueness * 0.20)},
            "completeness": {"score": completeness, "weight": 0.15, "weighted": int(completeness * 0.15)},
            "action": {"score": action, "weight": 0.20, "weighted": int(action * 0.20)},
            "relevance": {"score": relevance, "weight": 0.0, "weighted": 0},
        },
        "penalty": penalty,
        "level": "high" if total >= 70 else "medium" if total >= 45 else "low",
    }


def get_scored_items(db: Session, country: str = "菲律宾", limit: int = 15) -> List[Dict[str, Any]]:
    """获取按质量分排序的情报列表"""
    items = db.query(IntelligenceItem).join(Source).filter(
        Source.country == country
    ).order_by(IntelligenceItem.ingested_at.desc()).limit(200).all()

    sources = {
        source.id: source
        for source in db.query(Source).all()
    }

    scored: List[Dict[str, Any]] = []
    for item in items:
        source = sources.get(item.source_id)
        score_data = calculate_score(item, source)
        scored.append({
            "id": item.id,
            "title": item.title,
            "content": item.content[:200] if item.content else "",
            "source_name": item.source_name,
            "source_url": item.source_url,
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "score": score_data["total_score"],
            "score_level": score_data["level"],
            "dimensions": score_data["dimensions"],
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]


def confidence_assessment(
    sources: List[Dict],
    data_timestamp: Optional[datetime],
    cross_validation_count: int = 0,
    contradictions: int = 0,
) -> Dict[str, Any]:
    """
    计算情报置信度
    返回: {"score": 0-100, "level": "HIGH|MEDIUM|LOW|INSUFFICIENT", "reason": "说明"}
    """
    score = 0
    reason_parts: List[str] = []

    distinct_sources: List[Dict[str, Any]] = []
    seen_source_keys = set()
    for source in sources or []:
        source_name = (source or {}).get("name", "")
        source_url = (source or {}).get("url", "")
        key = (source_name.strip().lower(), source_url.strip().lower())
        if key in seen_source_keys:
            continue
        seen_source_keys.add(key)
        distinct_sources.append(source or {})

    source_count = len(distinct_sources)
    if source_count >= 3:
        score += 45
        reason_parts.append("来源数量>=3，+45")
    elif source_count == 2:
        score += 35
        reason_parts.append("来源数量=2，+35")
    elif source_count == 1:
        score += 20
        reason_parts.append("来源数量=1，+20")
    else:
        reason_parts.append("无有效来源，+0")

    source_type_scores = {
        "official": 20,
        "database": 15,
        "media": 10,
        "social": 5,
    }
    authority_score = 0
    for source in distinct_sources:
        authority_score += source_type_scores.get((source.get("type") or "").lower(), 0)
    score += authority_score
    reason_parts.append(f"来源权威性，+{authority_score}")

    timeliness_score = 0
    if data_timestamp:
        data_age = datetime.utcnow() - data_timestamp
        if data_age <= timedelta(days=30):
            timeliness_score = 20
        elif data_age <= timedelta(days=90):
            timeliness_score = 10
        elif data_age <= timedelta(days=180):
            timeliness_score = 5
    score += timeliness_score
    reason_parts.append(f"时效性，+{timeliness_score}")

    cross_validation_score = min(max(cross_validation_count, 0) * 5, 15)
    score += cross_validation_score
    reason_parts.append(f"交叉验证，+{cross_validation_score}")

    contradiction_penalty = max(contradictions, 0) * 15
    score -= contradiction_penalty
    if contradiction_penalty:
        reason_parts.append(f"来源矛盾，-{contradiction_penalty}")

    score = max(0, min(100, score))

    if score >= 80:
        level = "HIGH"
    elif score >= 50:
        level = "MEDIUM"
    elif score >= 20:
        level = "LOW"
    else:
        level = "INSUFFICIENT"

    return {
        "score": score,
        "level": level,
        "reason": "；".join(reason_parts),
    }


def freshness_assessment(
    data_timestamp: Optional[datetime],
    current_time: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    评估数据时效性
    返回: {"status": "CURRENT|RECENT|STALE|EXPIRED", "days_old": int, "description": "人话说明"}
    """
    if not data_timestamp:
        return {"status": "UNKNOWN", "days_old": -1, "description": "更新时间未知，无法评估时效性"}

    if not current_time:
        current_time = datetime.utcnow()

    delta = current_time - data_timestamp
    days_old = delta.days

    if days_old <= 7:
        status = "CURRENT"
        description = f"数据非常新鲜，{days_old}天前更新"
    elif days_old <= 30:
        status = "RECENT"
        description = f"数据时效良好，{days_old}天前更新"
    elif days_old <= 180:
        status = "STALE"
        description = f"数据已过时，{days_old}天前更新，建议核实是否有新动态"
    else:
        status = "EXPIRED"
        description = f"数据严重过期，{days_old}天前更新，当前参考价值有限"

    return {"status": status, "days_old": days_old, "description": description}
