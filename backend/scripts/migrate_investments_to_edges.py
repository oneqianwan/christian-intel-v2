import json
import os
import sys
import uuid

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
os.chdir(backend_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy import func, or_

from models.database import (
    FundingRound,
    Investment,
    Investor,
    KnowledgeEntity,
    OrganizationProfile,
    RelationEdge,
    SessionLocal,
)


def resolve_target(db, funding_round: FundingRound):
    """把 funding_round 解析成统一 target。"""
    if not funding_round or not funding_round.entity_id:
        return None, None

    knowledge_entity = db.query(KnowledgeEntity).filter(KnowledgeEntity.id == funding_round.entity_id).first()
    if not knowledge_entity:
        return funding_round.entity_id, "knowledge_entity"

    candidates = [knowledge_entity.name] if knowledge_entity.name else []
    if knowledge_entity.name and "/" in knowledge_entity.name:
        candidates.extend(part.strip() for part in knowledge_entity.name.split("/") if part.strip())

    for candidate in candidates:
        org = (
            db.query(OrganizationProfile)
            .filter(
                or_(
                    OrganizationProfile.name == candidate,
                    OrganizationProfile.english_name == candidate,
                    OrganizationProfile.official_name == candidate,
                    OrganizationProfile.short_name == candidate,
                )
            )
            .first()
        )
        if org:
            return org.id, "organization"

    return knowledge_entity.id, "knowledge_entity"


def main():
    db = SessionLocal()

    try:
        print("迁移Investment到RelationEdge...")

        investments = db.query(Investment).all()
        migrated = 0
        skipped = 0

        for investment in investments:
            investor = db.query(Investor).filter(Investor.id == investment.investor_id).first()
            if not investor:
                skipped += 1
                continue

            funding_round = db.query(FundingRound).filter(FundingRound.id == investment.funding_round_id).first()
            if not funding_round:
                skipped += 1
                continue

            target_id, target_type = resolve_target(db, funding_round)
            if not target_id:
                skipped += 1
                continue

            props = {}
            if investment.amount is not None:
                props["amount"] = float(investment.amount)
            if funding_round.round_type:
                props["round"] = funding_round.round_type
            if funding_round.announced_date:
                props["date"] = funding_round.announced_date.isoformat()
            if funding_round.amount is not None:
                props["round_amount"] = float(funding_round.amount)
            if investment.lead_investor is not None:
                props["lead_investor"] = bool(investment.lead_investor)

            source_item = f"investment:{investment.id}"
            existing = (
                db.query(RelationEdge)
                .filter(
                    RelationEdge.source_id == str(investment.investor_id),
                    RelationEdge.target_id == str(target_id),
                    RelationEdge.relation_type == "invested_in",
                    RelationEdge.source_item == source_item,
                )
                .first()
            )
            if existing:
                skipped += 1
                continue

            edge = RelationEdge(
                id=str(uuid.uuid4()),
                source_id=str(investment.investor_id),
                source_type="investor",
                target_id=str(target_id),
                target_type=target_type,
                relation_type="invested_in",
                confidence=0.95,
                source_item=source_item,
                source_type_detail="investment",
                properties_json=json.dumps(props, ensure_ascii=False) if props else None,
            )
            db.add(edge)
            migrated += 1

        db.commit()
        print(f"迁移完成: {migrated}条投资关系 -> RelationEdge")
        if skipped:
            print(f"跳过重复/无效记录: {skipped}条")

        print("\n构建共同投资关系...")
        funding_investors = {}
        for investment in investments:
            funding_investors.setdefault(investment.funding_round_id, [])
            if investment.investor_id not in funding_investors[investment.funding_round_id]:
                funding_investors[investment.funding_round_id].append(investment.investor_id)

        co_count = 0
        for funding_round_id, investor_ids in funding_investors.items():
            if len(investor_ids) <= 1:
                continue

            for index, inv1 in enumerate(investor_ids):
                for inv2 in investor_ids[index + 1 :]:
                    source_id, target_id = sorted([str(inv1), str(inv2)])
                    source_item = f"funding_round:{funding_round_id}"
                    existing = (
                        db.query(RelationEdge)
                        .filter(
                            RelationEdge.source_id == source_id,
                            RelationEdge.target_id == target_id,
                            RelationEdge.relation_type == "co_invested",
                            RelationEdge.source_item == source_item,
                        )
                        .first()
                    )
                    if existing:
                        continue

                    edge = RelationEdge(
                        id=str(uuid.uuid4()),
                        source_id=source_id,
                        source_type="investor",
                        target_id=target_id,
                        target_type="investor",
                        relation_type="co_invested",
                        confidence=0.9,
                        source_item=source_item,
                        source_type_detail="inferred",
                    )
                    db.add(edge)
                    co_count += 1

        db.commit()
        print(f"共同投资关系: {co_count}条")

        total_edges = db.query(RelationEdge).count()
        by_type = db.query(RelationEdge.relation_type, func.count()).group_by(RelationEdge.relation_type).all()
        print(f"\nRelationEdge总数: {total_edges}")
        for relation_type, count in by_type:
            print(f"  {relation_type}: {count}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
