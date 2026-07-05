import json
import logging
import os
import sys
from typing import Optional

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
os.chdir(backend_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy import or_

from models.database import (
    FundingRound,
    Investment,
    Investor,
    KnowledgeEntity,
    OrganizationProfile,
    SessionLocal,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _safe_country(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return str(value).strip()


def _match_org(db, entity: Optional[KnowledgeEntity]) -> Optional[OrganizationProfile]:
    """尽量把融资实体映射到机构主表。"""
    if not entity or not entity.name:
        return None

    candidates = [entity.name]
    raw_name = entity.name.strip()
    if "/" in raw_name:
        candidates.extend(part.strip() for part in raw_name.split("/") if part.strip())

    country = _safe_country(entity.country)
    for candidate in candidates:
        query = db.query(OrganizationProfile).filter(
            or_(
                OrganizationProfile.name == candidate,
                OrganizationProfile.english_name == candidate,
                OrganizationProfile.official_name == candidate,
                OrganizationProfile.short_name == candidate,
            )
        )
        if country:
            matched = query.filter(OrganizationProfile.country == country).first()
            if matched:
                return matched
        matched = query.first()
        if matched:
            return matched
    return None


def build_investment_graph():
    """从 Investor / Investment / FundingRound 构建关系图谱。"""
    db = SessionLocal()

    try:
        print("=" * 50)
        print("投资关系图谱构建")
        print("=" * 50)

        investments = db.query(Investment).all()
        print(f"总投资记录: {len(investments)}")

        org_investors = {}
        investor_orgs = {}
        funding_investors = {}

        for inv in investments:
            investor = db.query(Investor).filter(Investor.id == inv.investor_id).first()
            funding = db.query(FundingRound).filter(FundingRound.id == inv.funding_round_id).first()
            if not funding:
                continue

            entity = db.query(KnowledgeEntity).filter(KnowledgeEntity.id == funding.entity_id).first()
            org = _match_org(db, entity)

            target_id = org.id if org else f"entity:{funding.entity_id}"
            target_name = org.name if org else (entity.name if entity else funding.entity_id)
            target_country = org.country if org else (entity.country if entity else None)

            investor_name = investor.name if investor else f"Investor-{inv.investor_id}"
            investor_country = investor.country if investor else None

            org_investors.setdefault(target_id, []).append(
                {
                    "investor_name": investor_name,
                    "investor_id": inv.investor_id,
                    "amount": inv.amount,
                    "lead_investor": bool(inv.lead_investor),
                    "round_id": funding.id,
                    "round_type": funding.round_type,
                    "target_name": target_name,
                    "target_country": target_country,
                    "target_source": "organization_profile" if org else "knowledge_entity",
                }
            )

            investor_orgs.setdefault(inv.investor_id, []).append(
                {
                    "org_name": target_name,
                    "org_id": target_id,
                    "country": target_country,
                    "round_id": funding.id,
                    "round_type": funding.round_type,
                }
            )

            funding_investors.setdefault(funding.id, []).append(
                {
                    "investor_id": inv.investor_id,
                    "investor_name": investor_name,
                    "investor_country": investor_country,
                }
            )

        print(f"\n有投资的机构/实体: {len(org_investors)}家")
        sorted_orgs = sorted(org_investors.items(), key=lambda item: -len(item[1]))[:10]
        for target_id, investors_for_org in sorted_orgs:
            target_name = investors_for_org[0]["target_name"] if investors_for_org else target_id
            inv_names = [item["investor_name"] for item in investors_for_org]
            print(f"  {target_name}: {', '.join(inv_names)}")

        print("\n共同投资关系分析...")
        co_investor_pairs = {}
        for round_id, investors_in_round in funding_investors.items():
            if len(investors_in_round) <= 1:
                continue
            unique_ids = []
            seen = set()
            for item in investors_in_round:
                if item["investor_id"] in seen:
                    continue
                seen.add(item["investor_id"])
                unique_ids.append(item)
            for idx, inv_a in enumerate(unique_ids):
                for inv_b in unique_ids[idx + 1 :]:
                    pair = tuple(sorted([inv_a["investor_id"], inv_b["investor_id"]]))
                    if pair not in co_investor_pairs:
                        co_investor_pairs[pair] = {
                            "count": 0,
                            "investor_a_name": inv_a["investor_name"] if pair[0] == inv_a["investor_id"] else inv_b["investor_name"],
                            "investor_b_name": inv_b["investor_name"] if pair[1] == inv_b["investor_id"] else inv_a["investor_name"],
                            "shared_round_ids": [],
                        }
                    co_investor_pairs[pair]["count"] += 1
                    co_investor_pairs[pair]["shared_round_ids"].append(round_id)

        print(f"共同投资关系对: {len(co_investor_pairs)}")
        top_pairs = sorted(co_investor_pairs.items(), key=lambda item: -item[1]["count"])[:5]
        for (_, _), pair_data in top_pairs:
            print(
                f"  {pair_data['investor_a_name']} + {pair_data['investor_b_name']}: "
                f"{pair_data['count']}次共同投资"
            )

        total_orgs_with_investors = len(org_investors)
        total_investor_connections = sum(len(items) for items in org_investors.values())

        print("\n" + "=" * 50)
        print("图谱统计")
        print("=" * 50)
        print(f"机构-投资方关系: {total_investor_connections}")
        print(f"有投资的机构/实体: {total_orgs_with_investors}")
        print(f"共同投资关系对: {len(co_investor_pairs)}")
        print(f"投资方节点: {len(investor_orgs)}")

        graph_data = {
            "org_investors": {
                target_id: [
                    {
                        "name": item["investor_name"],
                        "id": item["investor_id"],
                        "amount": item["amount"],
                        "lead_investor": item["lead_investor"],
                        "round_id": item["round_id"],
                        "round_type": item["round_type"],
                    }
                    for item in investors_for_org
                ]
                for target_id, investors_for_org in org_investors.items()
            },
            "investor_orgs": {
                str(investor_id): [
                    {
                        "name": item["org_name"],
                        "id": item["org_id"],
                        "country": item["country"],
                        "round_id": item["round_id"],
                        "round_type": item["round_type"],
                    }
                    for item in targets
                ]
                for investor_id, targets in investor_orgs.items()
            },
            "co_investors": [
                {
                    "investor_a": pair[0],
                    "investor_b": pair[1],
                    "investor_a_name": pair_data["investor_a_name"],
                    "investor_b_name": pair_data["investor_b_name"],
                    "shared_rounds": pair_data["count"],
                    "shared_round_ids": pair_data["shared_round_ids"],
                }
                for pair, pair_data in co_investor_pairs.items()
            ],
            "stats": {
                "total_relations": total_investor_connections,
                "orgs_with_investors": total_orgs_with_investors,
                "co_investor_pairs": len(co_investor_pairs),
                "investor_nodes": len(investor_orgs),
            },
        }

        output_path = os.path.join(backend_dir, "data", "relation_graph.json")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as file_obj:
            json.dump(graph_data, file_obj, ensure_ascii=False, indent=2)

        print(f"\n图谱数据已写入: {output_path}")
        return graph_data
    finally:
        db.close()


if __name__ == "__main__":
    build_investment_graph()
