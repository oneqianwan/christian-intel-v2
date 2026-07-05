"""
Agent执行层：执行具体的行动计划
"""

import os
import sys
import uuid
from datetime import datetime

from sqlalchemy import text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.planner import ActionPlan
from models.database import Mission, get_db
from services.mission_service import create_collection_mission


class ActionExecutor:
    def __init__(self):
        self._db_gen = get_db()
        self.db = next(self._db_gen)

    def __del__(self):
        try:
            self._db_gen.close()
        except Exception:
            pass

    def execute(self, plan: ActionPlan) -> dict:
        if plan.action == "auto_collect_and_notify":
            return self._auto_collect_and_notify(plan)
        if plan.action == "auto_collect":
            return self._auto_collect(plan)
        if plan.action == "mark_api_error":
            return self._mark_api_error(plan)
        if plan.action == "notify_user":
            return self._notify_user(plan)
        return {"status": "unknown_action", "created": 0}

    def _auto_collect(self, plan: ActionPlan) -> dict:
        from agent.memory import Memory

        country = plan.params.get("country", "全球")
        reason = plan.params.get("reason", "Agent自动补采")
        count = max(1, min(int(plan.params.get("count", 5) or 5), 10))

        if country == "全球":
            sources = self.db.execute(
                text(
                    """
                    SELECT name, url, type
                    FROM sources
                    WHERE scope = 'global' AND is_active = true
                    ORDER BY created_at DESC NULLS LAST, name ASC
                    LIMIT :limit
                    """
                ),
                {"limit": count},
            ).fetchall()
        else:
            sources = self.db.execute(
                text(
                    """
                    SELECT name, url, type
                    FROM sources
                    WHERE country = :country AND is_active = true
                    ORDER BY created_at DESC NULLS LAST, name ASC
                    LIMIT :limit
                    """
                ),
                {"country": country, "limit": count},
            ).fetchall()

        # 无 active 来源时，退化为基于已有情报来源重采。
        if not sources:
            if country == "全球":
                sources = self.db.execute(
                    text(
                        """
                        SELECT DISTINCT source_name, source_url, 'rss' AS source_type
                        FROM intelligence_items
                        WHERE scope = 'global' AND source_name IS NOT NULL AND source_name != ''
                        ORDER BY source_name ASC
                        LIMIT :limit
                        """
                    ),
                    {"limit": min(count, 5)},
                ).fetchall()
            else:
                sources = self.db.execute(
                    text(
                        """
                        SELECT DISTINCT source_name, source_url, 'rss' AS source_type
                        FROM intelligence_items
                        WHERE country = :country AND source_name IS NOT NULL AND source_name != ''
                        ORDER BY source_name ASC
                        LIMIT :limit
                        """
                    ),
                    {"country": country, "limit": min(count, 5)},
                ).fetchall()

        composite_id = str(uuid.uuid4())
        created = 0
        mission_ids = []

        for src in sources:
            try:
                name, url, src_type = src
                mission = create_collection_mission(
                    query=f"{reason} | source={name} | type={src_type or 'rss'} | url={url or ''}",
                    country=country,
                    priority=plan.priority,
                    target_entity=name,
                    composite_task_id=composite_id,
                    composite_status="pending",
                    db=self.db,
                )
                mission_id = mission.id if mission else None
                if not mission_id:
                    print(f"  Mission未创建，跳过该来源: source={name}")
                    continue
                mission_ids.append(mission_id)
                created += 1
            except Exception as exc:
                print(f"  Mission创建失败: {exc}")
        should_create_default_notification = (
            created > 0
            and plan.action != "auto_collect_and_notify"
            and plan.params.get("notification_type") != "gap_filled"
        )
        if should_create_default_notification:
            memory = Memory()
            memory.create_task(
                "pending_notification",
                country,
                f"等待Worker完成后通知用户: {country} +{created}",
                {
                    "notify_plan": {
                        "notification_type": "task_complete",
                        "country": country,
                        "count": created,
                        "composite_id": composite_id,
                    }
                },
            )
        print(f"  [OK] auto_collect: {country} +{created}")
        return {
            "created": created,
            "status": "success",
            "composite_id": composite_id,
            "mission_ids": mission_ids,
        }

    def _auto_collect_and_notify(self, plan: ActionPlan) -> dict:
        """
        采集+通知组合动作：
        1. 先执行auto_collect创建采集任务
        2. 记录查询缺口与待通知任务
        3. Worker完成后自动发送通知给用户
        """
        from agent.memory import Memory

        collect_result = self._auto_collect(plan)
        if collect_result.get("created", 0) == 0:
            return collect_result

        try:
            memory = Memory()
            user_query = plan.params.get("user_query", "")
            composite_id = collect_result.get("composite_id", "")

            memory.create_task(
                task_type="query_gap",
                target=user_query[:100],
                reason=f"已处理查询缺口: {user_query[:50]}",
                plan={
                    "country": plan.params.get("country", "全球"),
                    "entity": plan.params.get("entity", ""),
                    "conversation_id": plan.params.get("conversation_id", ""),
                    "composite_task_id": composite_id,
                },
            )

            memory.create_task(
                task_type="query_gap_notification",
                target=plan.params.get("country", "全球"),
                reason=f"用户查询缺口补齐通知: {user_query[:50]}",
                plan={
                    "notify_plan": {
                        "notification_type": "gap_filled",
                        "original_query": user_query,
                        "conversation_id": plan.params.get("conversation_id", ""),
                        "country": plan.params.get("country", ""),
                        "composite_id": composite_id,
                    },
                    "composite_task_id": composite_id,
                    "mission_count": collect_result.get("created", 0),
                },
            )

            print(f"  [OK] 已记录待通知任务: {user_query[:50]}...")
        except Exception as exc:
            print(f"  [WARN] 通知任务记录失败（不影响采集）: {exc}")

        return collect_result

    def _mark_api_error(self, plan: ActionPlan) -> dict:
        api_name = plan.params.get("api_name")
        if not api_name:
            return {"created": 0, "status": "failed"}

        try:
            self.db.execute(
                text(
                    """
                    UPDATE api_configs
                    SET status = 'error',
                        usage_info = :reason,
                        last_checked = :last_checked,
                        updated_at = :updated_at
                    WHERE api_name = :name
                    """
                ),
                {
                    "name": api_name,
                    "reason": plan.params.get("reason", "Agent检测异常"),
                    "last_checked": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                },
            )
            self.db.commit()
            print(f"  [OK] mark_error: {api_name}")
            return {"created": 0, "status": "success", "detail": f"{api_name} marked error"}
        except Exception as exc:
            return {"created": 0, "status": "failed", "detail": str(exc)}

    def _notify_user(self, plan: ActionPlan) -> dict:
        from agent.memory import Memory
        from models.database import Message, get_db

        db_gen = get_db()
        db = next(db_gen)

        try:
            conv_id = plan.params.get("conversation_id", "")
            conversation = None
            if conv_id:
                conversation = db.execute(
                    text("SELECT id FROM conversations WHERE id = :conversation_id"),
                    {"conversation_id": conv_id},
                ).fetchone()
            if not conversation:
                conversation = db.execute(
                    text(
                        """
                        SELECT id
                        FROM conversations
                        ORDER BY updated_at DESC NULLS LAST, created_at DESC
                        LIMIT 1
                        """
                    )
                ).fetchone()

            if not conversation:
                return {"status": "no_conversation", "created": 0}

            conv_id = conversation[0]
            notification_type = plan.params.get("notification_type", "task_complete")

            if notification_type == "task_complete":
                country = plan.params.get("country", plan.target or "")
                count = plan.params.get("count", 0)
                content = (
                    "🤖 **Agent自动通知**\n\n"
                    f"我刚完成了对 **{country}** 的情报补采，新增 **{count}** 条情报入库。\n\n"
                    f'您可以问：“{country}基督教最新动态” 查看结果。'
                )
            elif notification_type == "gap_filled":
                original_query = plan.params.get("original_query", "")
                content = (
                    "🤖 **Agent自动通知**\n\n"
                    f'您之前问的 **“{original_query}”** 我已经补充完数据了。\n\n'
                    "现在可以为您提供完整分析，请重新提问。"
                )
            else:
                content = f"🤖 **Agent通知**\n\n{plan.params.get('message', '任务已完成')}"

            message = Message(
                id=str(uuid.uuid4()),
                conversation_id=conv_id,
                role="assistant",
                content=content,
                delivery_type="agent_notification",
                created_at=datetime.utcnow(),
            )
            db.add(message)
            db.execute(
                text(
                    """
                    UPDATE conversations
                    SET updated_at = :updated_at
                    WHERE id = :conversation_id
                    """
                ),
                {"updated_at": datetime.utcnow(), "conversation_id": conv_id},
            )
            db.commit()

            if notification_type == "keyword_surge":
                try:
                    memory = Memory()
                    memory.create_task(
                        task_type="keyword_surge_notification",
                        target=plan.params.get("category", "unknown"),
                        reason=f"突发关键词预警通知: {plan.params.get('category', '')}",
                        plan={"notified_at": datetime.utcnow().isoformat()},
                    )
                except Exception as exc:
                    print(f"  [notify] keyword_surge记录失败: {exc}")

            print(f"  [OK] notify_user: 消息已推送到对话 {conv_id[:8]}")
            return {"status": "success", "created": 1, "conversation_id": conv_id}
        except Exception as exc:
            db.rollback()
            print(f"  [ERR] notify_user失败: {exc}")
            return {"status": "failed", "created": 0, "detail": str(exc)}
        finally:
            try:
                db_gen.close()
            except Exception:
                pass
