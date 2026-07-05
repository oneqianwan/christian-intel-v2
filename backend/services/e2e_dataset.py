from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    question: str
    expected_answer: str
    expected_entities: List[str] = field(default_factory=list)
    expected_facts: List[str] = field(default_factory=list)
    expected_citations: int = 0
    expected_reasoning: List[str] = field(default_factory=list)
    category: str = ""
    difficulty: str = "medium"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "question": self.question,
            "expected_answer": self.expected_answer,
            "expected_entities": list(self.expected_entities or []),
            "expected_facts": list(self.expected_facts or []),
            "expected_citations": int(self.expected_citations or 0),
            "expected_reasoning": list(self.expected_reasoning or []),
            "category": self.category,
            "difficulty": self.difficulty,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvaluationCase":
        payload = data or {}
        return cls(
            case_id=str(payload.get("case_id") or ""),
            question=str(payload.get("question") or ""),
            expected_answer=str(payload.get("expected_answer") or ""),
            expected_entities=[str(item) for item in (payload.get("expected_entities") or []) if str(item or "").strip()],
            expected_facts=[str(item) for item in (payload.get("expected_facts") or []) if str(item or "").strip()],
            expected_citations=int(payload.get("expected_citations") or 0),
            expected_reasoning=[str(item) for item in (payload.get("expected_reasoning") or []) if str(item or "").strip()],
            category=str(payload.get("category") or ""),
            difficulty=str(payload.get("difficulty") or "medium"),
        )


_SEED_ORGANIZATIONS = [
    "OpenAI",
    "Microsoft",
    "Google",
    "Amazon",
    "Meta",
    "Apple",
    "NVIDIA",
    "Tesla",
    "xAI",
    "Anthropic",
    "ByteDance",
    "Tencent",
    "Alibaba",
    "Baidu",
    "Intel",
    "AMD",
    "Netflix",
    "Salesforce",
    "Oracle",
    "SAP",
]


def _difficulty_for(index: int, *, hard_every: int = 5) -> str:
    if index % hard_every == 0:
        return "hard"
    if index % 2 == 0:
        return "medium"
    return "easy"


def _org_case(name: str, index: int) -> EvaluationCase:
    return EvaluationCase(
        case_id=f"e2e-org-{index:03d}",
        question=f"请介绍 {name} 的核心能力、业务定位、主要产品以及近期发展方向。",
        expected_answer=f"{name} 的组织概况与核心能力总结",
        expected_entities=[name],
        expected_facts=["organization", "products", "leadership", "strategy"],
        expected_citations=2,
        expected_reasoning=["summarize", "organize", "evidence-backed"],
        category="Organization",
        difficulty=_difficulty_for(index),
    )


def _timeline_case(name: str, index: int) -> EvaluationCase:
    return EvaluationCase(
        case_id=f"e2e-timeline-{index:03d}",
        question=f"梳理 {name} 最近几年的关键发展时间线，并标出重要节点。",
        expected_answer=f"{name} 的关键发展时间线",
        expected_entities=[name],
        expected_facts=["date", "event", "milestone", "impact"],
        expected_citations=2,
        expected_reasoning=["timeline", "sequence", "causal ordering"],
        category="Timeline",
        difficulty=_difficulty_for(index),
    )


def _relationship_case(name: str, partner: str, index: int) -> EvaluationCase:
    return EvaluationCase(
        case_id=f"e2e-relationship-{index:03d}",
        question=f"分析 {name} 和 {partner} 的合作、竞争或依赖关系，并说明证据。",
        expected_answer=f"{name} 与 {partner} 的关系分析",
        expected_entities=[name, partner],
        expected_facts=["relationship", "cooperation", "competition", "dependency"],
        expected_citations=2,
        expected_reasoning=["compare", "link entities", "support claim"],
        category="Relationship",
        difficulty=_difficulty_for(index),
    )


def _investment_case(name: str, investor: str, index: int) -> EvaluationCase:
    return EvaluationCase(
        case_id=f"e2e-investment-{index:03d}",
        question=f"总结 {investor} 与 {name} 的投资、融资或资本合作信息，并判断其战略意义。",
        expected_answer=f"{investor} 对 {name} 的投资与资本关系总结",
        expected_entities=[name, investor],
        expected_facts=["investment", "amount", "round", "strategic impact"],
        expected_citations=2,
        expected_reasoning=["investment reasoning", "source-backed"],
        category="Investment",
        difficulty=_difficulty_for(index),
    )


def _comparison_case(left: str, right: str, index: int) -> EvaluationCase:
    return EvaluationCase(
        case_id=f"e2e-compare-{index:03d}",
        question=f"对比 {left} 和 {right} 在产品、技术路线、市场定位上的差异。",
        expected_answer=f"{left} 与 {right} 的对比分析",
        expected_entities=[left, right],
        expected_facts=["product", "technology", "market", "difference"],
        expected_citations=2,
        expected_reasoning=["comparison", "difference", "evidence-backed"],
        category="Comparison",
        difficulty=_difficulty_for(index),
    )


def _ranking_case(name: str, peers: List[str], index: int) -> EvaluationCase:
    peer_text = "、".join(peers[:3])
    return EvaluationCase(
        case_id=f"e2e-ranking-{index:03d}",
        question=f"基于公开信息，对 {name}、{peer_text} 做一个能力或影响力排序，并说明依据。",
        expected_answer=f"{name} 及其同类公司的排序说明",
        expected_entities=[name, *peers[:3]],
        expected_facts=["ranking", "criteria", "evidence", "conclusion"],
        expected_citations=3,
        expected_reasoning=["ranking", "criteria-based", "compare"],
        category="Ranking",
        difficulty=_difficulty_for(index),
    )


def _multi_hop_case(name: str, partner: str, investor: str, index: int) -> EvaluationCase:
    return EvaluationCase(
        case_id=f"e2e-multihop-{index:03d}",
        question=f"结合 {name}、{partner} 和 {investor} 的关系，分析它们在产品、资本和合作上的多跳联系。",
        expected_answer=f"{name}、{partner}、{investor} 的多跳关联分析",
        expected_entities=[name, partner, investor],
        expected_facts=["relationship", "investment", "partnership", "implication"],
        expected_citations=3,
        expected_reasoning=["multi-hop", "derive link", "cross-source"],
        category="Multi-hop",
        difficulty="hard",
    )


def _mixed_query_case(name: str, partner: str, index: int) -> EvaluationCase:
    return EvaluationCase(
        case_id=f"e2e-mixed-{index:03d}",
        question=f"请同时从组织、时间线、合作关系和风险角度综合分析 {name} 与 {partner}。",
        expected_answer=f"{name} 与 {partner} 的综合分析",
        expected_entities=[name, partner],
        expected_facts=["organization", "timeline", "relationship", "risk"],
        expected_citations=3,
        expected_reasoning=["mixed query", "synthesis", "structured summary"],
        category="Mixed Query",
        difficulty="hard",
    )


def get_default_e2e_dataset() -> List[EvaluationCase]:
    dataset: List[EvaluationCase] = []
    names = list(_SEED_ORGANIZATIONS)
    total = len(names)
    for index, name in enumerate(names, start=1):
        partner = names[index % total]
        investor = names[(index + 3) % total]
        peers = [names[(index + offset) % total] for offset in range(1, 4)]
        dataset.append(_org_case(name, index))
        dataset.append(_timeline_case(name, index))
        dataset.append(_relationship_case(name, partner, index))
        dataset.append(_investment_case(name, investor, index))
        dataset.append(_comparison_case(name, partner, index))
        dataset.append(_ranking_case(name, peers, index))
        dataset.append(_multi_hop_case(name, partner, investor, index))
        dataset.append(_mixed_query_case(name, partner, index))
    return dataset
