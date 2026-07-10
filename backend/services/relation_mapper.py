"""
关系映射服务
将 relation_edges 的 source/target 映射到 organization_profiles。
"""

import json
from typing import Any, Dict, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from models.database import KnowledgeEntity, OrganizationProfile, RelationEdge


class RelationMapper:
    ENTITY_ORG_ALIASES = {
        "gloo": "Gloo",
        "world vision": "World Vision International",
        "compassion international": "Compassion International",
        "samaritans purse": "Samaritan's Purse",
        "samaritan's purse": "Samaritan's Purse",
        "youversion / life.church": "Life.Church",
        "youversion": "Life.Church",
        "bibleproject": "BibleProject",
        "subsplash": "Subsplash",
        "tithe.ly": "Tithe.ly",
        "pushpay": "Pushpay",
        "rightnow media": "RightNow Media",
    }

    def __init__(self, db: Session):
        self.db = db

    def build_organization_graph(
        self,
        *,
        org_id: Optional[str] = None,
        organization_name: Optional[str] = None,
        depth: int = 1,
        limit: int = 50,
        include_unverified: bool = False,
    ) -> Dict[str, Any]:
        warnings: List[Dict[str, Any]] = []
        normalized_depth = 1
        if depth != 1:
            warnings.append(
                {
                    "code": "unsupported_depth",
                    "message": f"depth={depth} is not supported in this phase; using depth=1",
                }
            )

        normalized_limit = max(1, min(int(limit or 50), 200))
        center_org = self._resolve_center_org(org_id=org_id, organization_name=organization_name)
        if not center_org:
            return self._empty_graph_payload(
                warnings=[
                    {
                        "code": "not_found",
                        "message": "Organization not found",
                        "org_id": org_id,
                        "organization_name": organization_name,
                    }
                ],
                found=False,
                depth=normalized_depth,
                limit=normalized_limit,
                include_unverified=include_unverified,
            )

        related_side_ids = {center_org.id}
        for entity in self._find_entities_for_org(center_org):
            related_side_ids.add(entity.id)

        edge_query = self.db.query(RelationEdge).filter(
            or_(RelationEdge.source_id.in_(related_side_ids), RelationEdge.target_id.in_(related_side_ids))
        )
        filtered_unverified_count = 0
        if not include_unverified:
            filtered_unverified_count = edge_query.filter(RelationEdge.is_verified.is_(False)).count()
            edge_query = edge_query.filter(RelationEdge.is_verified.is_(True))

        edges = edge_query.order_by(RelationEdge.created_at.desc(), RelationEdge.id.desc()).limit(normalized_limit).all()

        nodes: List[Dict[str, Any]] = []
        edges_payload: List[Dict[str, Any]] = []
        seen_node_ids: set[str] = set()
        seen_edge_ids: set[str] = set()
        missing_evidence_count = 0

        for edge in edges:
            enriched = self.enrich_relation(edge)
            if not enriched or edge.id in seen_edge_ids:
                continue

            source = enriched["source"]
            target = enriched["target"]
            source_matches = source.get("id") == center_org.id or source.get("mapped_org_id") == center_org.id
            target_matches = target.get("id") == center_org.id or target.get("mapped_org_id") == center_org.id
            if not source_matches and not target_matches:
                continue

            source_graph_id = self._graph_node_id_for_side(source)
            target_graph_id = self._graph_node_id_for_side(target)

            if not source_matches and source_graph_id not in seen_node_ids:
                nodes.append(self._build_related_node_payload(source))
                seen_node_ids.add(source_graph_id)
            if not target_matches and target_graph_id not in seen_node_ids:
                nodes.append(self._build_related_node_payload(target))
                seen_node_ids.add(target_graph_id)

            has_evidence = bool(edge.evidence_url or edge.evidence_source or edge.evidence_date)
            if not has_evidence:
                missing_evidence_count += 1
                warnings.append(
                    {
                        "code": "missing_evidence",
                        "message": f"Relation edge {edge.id} has no evidence metadata",
                        "edge_id": edge.id,
                    }
                )
            if include_unverified and not bool(edge.is_verified):
                warnings.append(
                    {
                        "code": "unverified_edge",
                        "message": f"Relation edge {edge.id} is not verified",
                        "edge_id": edge.id,
                    }
                )

            edges_payload.append(
                {
                    "id": f"edge:{edge.id}",
                    "source": source_graph_id,
                    "target": target_graph_id,
                    "relation_type": edge.relation_type or "unknown",
                    "direction": self._graph_direction(source_matches=source_matches, target_matches=target_matches),
                    "strength": self._edge_strength(edge),
                    "confidence": float(edge.confidence or 0.0),
                    "is_verified": bool(edge.is_verified),
                    "evidence_url": edge.evidence_url,
                    "evidence_source": edge.evidence_source,
                    "evidence_date": edge.evidence_date.isoformat() if edge.evidence_date else None,
                    "reason": self._edge_reason(edge=edge, source=source, target=target),
                    "missing_evidence": not has_evidence,
                }
            )
            seen_edge_ids.add(edge.id)

        if filtered_unverified_count:
            warnings.append(
                {
                    "code": "unverified_filtered",
                    "message": f"{filtered_unverified_count} unverified relation(s) were filtered out",
                }
            )
        if not edges_payload:
            warnings.append(
                {
                    "code": "no_relations",
                    "message": "No graph relations found for this organization",
                }
            )

        return {
            "center": self._build_center_payload(center_org),
            "nodes": nodes,
            "edges": edges_payload,
            "summary": {
                "node_count": 1 + len(nodes),
                "edge_count": len(edges_payload),
                "verified_edge_count": sum(1 for edge_item in edges_payload if edge_item["is_verified"]),
                "unverified_edge_count": sum(1 for edge_item in edges_payload if not edge_item["is_verified"]),
                "missing_evidence_count": missing_evidence_count,
            },
            "warnings": warnings,
            "found": True,
            "depth": normalized_depth,
            "limit": normalized_limit,
            "include_unverified": include_unverified,
        }

    def enrich_relation(self, edge: RelationEdge) -> Optional[Dict]:
        source = self._resolve_side(edge.source_id)
        target = self._resolve_side(edge.target_id)

        if not source and not target:
            return None

        legacy = self._parse_legacy_properties(edge)
        investment_amount = edge.investment_amount or legacy.get("amount")
        investment_currency = edge.investment_currency or legacy.get("currency") or "USD"
        investment_round = edge.investment_round or legacy.get("round")
        evidence_date = edge.evidence_date
        if not evidence_date and legacy.get("date"):
            evidence_date = str(legacy.get("date")).split("T")[0]
        evidence_source = edge.evidence_source or edge.source_type_detail or edge.source_item or legacy.get("source")
        evidence_url = edge.evidence_url or legacy.get("url")
        has_evidence = bool(evidence_url or evidence_date or evidence_source or edge.is_verified)

        return {
            "relation_id": edge.id,
            "relation_type": edge.relation_type,
            "source": source or self._unknown_stub(edge.source_id),
            "target": target or self._unknown_stub(edge.target_id),
            "investment": {
                "amount": str(investment_amount),
                "currency": investment_currency,
                "round": investment_round,
            }
            if investment_amount is not None
            else None,
            "evidence": {
                "url": evidence_url,
                "date": evidence_date.isoformat() if hasattr(evidence_date, "isoformat") else evidence_date,
                "source": evidence_source,
                "verified": bool(edge.is_verified),
            }
            if has_evidence
            else None,
            "confidence": edge.confidence,
            "created_at": edge.created_at.isoformat() if edge.created_at else None,
            "source_item": edge.source_item,
        }

    def get_relations_for_org(self, org_id: str) -> List[Dict]:
        org = self.db.query(OrganizationProfile).filter(OrganizationProfile.id == org_id).first()
        if not org:
            return []

        related_side_ids = {org_id}
        for entity in self._find_entities_for_org(org):
            related_side_ids.add(entity.id)

        edges = (
            self.db.query(RelationEdge)
            .filter(or_(RelationEdge.source_id.in_(related_side_ids), RelationEdge.target_id.in_(related_side_ids)))
            .order_by(RelationEdge.created_at.desc())
            .all()
        )

        results: List[Dict] = []
        seen_relation_ids = set()
        for edge in edges:
            enriched = self.enrich_relation(edge)
            if not enriched or edge.id in seen_relation_ids:
                continue

            source = enriched["source"]
            target = enriched["target"]
            source_matches = source.get("id") == org_id or source.get("mapped_org_id") == org_id
            target_matches = target.get("id") == org_id or target.get("mapped_org_id") == org_id

            if not source_matches and not target_matches:
                continue

            direction = "outgoing" if source_matches else "incoming"
            other_org = target if direction == "outgoing" else source

            enriched["direction"] = direction
            enriched["other_org"] = {
                "id": other_org.get("mapped_org_id") or other_org.get("id"),
                "name": other_org.get("name") or "Unknown Organization",
                "country": other_org.get("country"),
            }
            results.append(enriched)
            seen_relation_ids.add(edge.id)

        return results

    def _resolve_center_org(
        self,
        *,
        org_id: Optional[str] = None,
        organization_name: Optional[str] = None,
    ) -> Optional[OrganizationProfile]:
        if org_id:
            org = self.db.query(OrganizationProfile).filter(OrganizationProfile.id == str(org_id)).first()
            if org:
                return org
        if organization_name:
            return self._find_org_by_name(str(organization_name).strip())
        return None

    def _resolve_side(self, side_id: str) -> Optional[Dict]:
        org = self.db.query(OrganizationProfile).filter(OrganizationProfile.id == side_id).first()
        if org:
            return {
                "id": org.id,
                "name": org.name,
                "country": org.country,
                "type": "organization",
            }

        entity = self.db.query(KnowledgeEntity).filter(KnowledgeEntity.id == side_id).first()
        if entity:
            mapped_org = self._map_entity_to_org(entity)
            if mapped_org:
                return {
                    "id": mapped_org.id,
                    "name": mapped_org.name,
                    "country": mapped_org.country,
                    "type": "organization",
                    "original_entity": entity.name,
                    "mapped_org_id": mapped_org.id,
                }
            return {
                "id": entity.id,
                "name": entity.name,
                "country": entity.country,
                "type": "entity",
            }

        return None

    def _map_entity_to_org(self, entity: KnowledgeEntity) -> Optional[OrganizationProfile]:
        if not entity or not entity.name:
            return None

        entity_name = entity.name.strip()
        alias_match = self.ENTITY_ORG_ALIASES.get(entity_name.lower())
        if alias_match:
            org = self._find_org_by_name(alias_match)
            if org:
                return org

        return self._find_org_by_name(entity_name)

    def _find_org_by_name(self, name: str) -> Optional[OrganizationProfile]:
        return (
            self.db.query(OrganizationProfile)
            .filter(
                or_(
                    OrganizationProfile.name.ilike(f"%{name}%"),
                    OrganizationProfile.english_name.ilike(f"%{name}%"),
                    OrganizationProfile.short_name.ilike(f"%{name}%"),
                    OrganizationProfile.official_name.ilike(f"%{name}%"),
                )
            )
            .first()
        )

    def _find_entities_for_org(self, org: OrganizationProfile) -> List[KnowledgeEntity]:
        candidates = []
        for value in [org.name, org.english_name, org.short_name, org.official_name]:
            if value and value.strip():
                candidates.append(value.strip())

        if not candidates:
            return []

        filters = [KnowledgeEntity.name.ilike(f"%{candidate}%") for candidate in candidates]
        matched = self.db.query(KnowledgeEntity).filter(or_(*filters)).all()

        results: List[KnowledgeEntity] = []
        seen = set()
        for entity in matched:
            mapped = self._map_entity_to_org(entity)
            if mapped and mapped.id == org.id and entity.id not in seen:
                results.append(entity)
                seen.add(entity.id)
        return results

    def _unknown_stub(self, unknown_id: str) -> Dict:
        return {
            "id": unknown_id,
            "name": "Unknown Organization",
            "country": None,
            "type": "unknown",
        }

    def _parse_legacy_properties(self, edge: RelationEdge) -> Dict:
        if not edge.properties_json:
            return {}
        try:
            data = json.loads(edge.properties_json)
            return data if isinstance(data, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

    def _build_center_payload(self, org: OrganizationProfile) -> Dict[str, Any]:
        return {
            "id": org.id,
            "graph_id": self._graph_node_id(org.id, "organization"),
            "type": "organization",
            "name": org.name,
            "region": org.state_province or org.city or org.country,
            "denomination": org.denomination,
            "people_score": org.people_score,
            "digital_score": org.digital_score,
            "intel_score": org.intel_score,
        }

    def _build_related_node_payload(self, side: Dict[str, Any]) -> Dict[str, Any]:
        org = None
        raw_id = str(side.get("mapped_org_id") or side.get("id") or "")
        if side.get("type") == "organization" and raw_id:
            org = self.db.query(OrganizationProfile).filter(OrganizationProfile.id == raw_id).first()

        node_type = "organization" if side.get("type") == "organization" else str(side.get("type") or "unknown")
        confidence = float(getattr(org, "confidence", 0.0) or 0.0)
        source_count = self._source_count_for_org(org)
        return {
            "id": self._graph_node_id(raw_id, node_type),
            "entity_id": raw_id,
            "type": node_type,
            "label": side.get("name") or "Unknown",
            "name": side.get("name") or "Unknown",
            "region": getattr(org, "state_province", None) or getattr(org, "city", None) or side.get("country"),
            "denomination": getattr(org, "denomination", None),
            "people_score": getattr(org, "people_score", None),
            "digital_score": getattr(org, "digital_score", None),
            "intel_score": getattr(org, "intel_score", None),
            "confidence": confidence,
            "source_count": source_count,
        }

    def _source_count_for_org(self, org: Optional[OrganizationProfile]) -> int:
        if not org:
            return 0
        source_count = 0
        if getattr(org, "source_url", None):
            source_count += 1
        trail = getattr(org, "data_sources_json", None)
        if trail:
            try:
                parsed = json.loads(trail)
                if isinstance(parsed, list):
                    source_count += len(parsed)
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        return source_count

    def _graph_node_id(self, raw_id: str, node_type: str) -> str:
        prefix = "org" if node_type == "organization" else node_type or "node"
        return f"{prefix}:{raw_id}"

    def _graph_node_id_for_side(self, side: Dict[str, Any]) -> str:
        raw_id = str(side.get("mapped_org_id") or side.get("id") or "")
        node_type = "organization" if side.get("type") == "organization" else str(side.get("type") or "unknown")
        return self._graph_node_id(raw_id, node_type)

    def _graph_direction(self, *, source_matches: bool, target_matches: bool) -> str:
        if source_matches and not target_matches:
            return "outbound"
        if target_matches and not source_matches:
            return "inbound"
        return "undirected"

    def _edge_strength(self, edge: RelationEdge) -> Optional[float]:
        legacy = self._parse_legacy_properties(edge)
        strength = legacy.get("strength")
        if strength is None:
            return float(edge.confidence or 0.0)
        try:
            return float(strength)
        except (TypeError, ValueError):
            return float(edge.confidence or 0.0)

    def _edge_reason(self, *, edge: RelationEdge, source: Dict[str, Any], target: Dict[str, Any]) -> str:
        relation_type = edge.relation_type or "unknown"
        evidence_source = edge.evidence_source
        if evidence_source:
            return (
                f'Database relation "{relation_type}" links '
                f'{source.get("name") or edge.source_id} and {target.get("name") or edge.target_id}; '
                f"evidence source: {evidence_source}"
            )
        return (
            f'Database relation "{relation_type}" links '
            f'{source.get("name") or edge.source_id} and {target.get("name") or edge.target_id} '
            "without evidence metadata"
        )

    def _empty_graph_payload(
        self,
        *,
        warnings: List[Dict[str, Any]],
        found: bool,
        depth: int,
        limit: int,
        include_unverified: bool,
    ) -> Dict[str, Any]:
        return {
            "center": None,
            "nodes": [],
            "edges": [],
            "summary": {
                "node_count": 0,
                "edge_count": 0,
                "verified_edge_count": 0,
                "unverified_edge_count": 0,
                "missing_evidence_count": 0,
            },
            "warnings": warnings,
            "found": found,
            "depth": depth,
            "limit": limit,
            "include_unverified": include_unverified,
        }


def build_organization_graph(
    *,
    db: Session,
    org_id: Optional[str] = None,
    organization_name: Optional[str] = None,
    depth: int = 1,
    limit: int = 50,
    include_unverified: bool = False,
) -> Dict[str, Any]:
    mapper = RelationMapper(db)
    return mapper.build_organization_graph(
        org_id=org_id,
        organization_name=organization_name,
        depth=depth,
        limit=limit,
        include_unverified=include_unverified,
    )
