from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import or_

from models.database import OrganizationProfile


@dataclass
class OrganizationRecord:
    organization_id: Optional[str]
    name: str
    canonical_name: str
    variants: list[str]


class OrganizationResolver:
    CONTEXT_REFERENCE_PATTERNS = [
        r"这个机构",
        r"该机构",
        r"刚才那个机构",
        r"这个教会",
        r"刚才那个教会",
        r"^\s*它\s*$",
        r"\bthis\s+organization\b",
        r"\bthat\s+organization\b",
        r"\bthis\s+church\b",
        r"\bthat\s+church\b",
        r"^\s*it\s*$",
        r"^\s*them\s*$",
    ]

    BROAD_QUERY_PATTERNS = [
        r"帮我分析一下?$",
        r"帮我分析",
        r"分析一下$",
        r"analy[sz]e\s+this$",
        r"analy[sz]e$",
        r"analysis$",
    ]

    LEADING_PHRASE_PATTERNS = [
        r"^(?:give\s+me|show\s+me|tell\s+me|contact\s+info\s+for|what\s+is\s+the\s+contact\s+information\s+for|what\s+are\s+the\s+next\s+steps\s+for|how\s+can\s+i\s+contact|how\s+do\s+i\s+contact|create\s+(?:an?\s+)?action\s+plan\s+for|give\s+me\s+(?:an?\s+)?evidence\s+brief\s+for)\s+",
        r"^(?:给我|请给我|请生成|生成|帮我|告诉我|说明|查一下|查询|联系一下)\s+",
    ]

    TRAILING_INTENT_PATTERNS = [
        r"(?:的)?(?:联系方式|联系信息|邮箱|电话|官网|网站|社媒账号有哪些|社媒|公开联系方式)$",
        r"(?:contact\s+info(?:rmation)?|contact\s+channels?|email|phone|website|social\s+links?)$",
        r"(?:的)?(?:关系图谱|关系网络|合作网络|关联机构|合作方)$",
        r"(?:relationship\s+graph|relationship\s+network|connected\s+organizations?|relationship\s+path)$",
        r"(?:who\s+are\s+.+?\s+partners|what\s+organizations\s+is\s+.+?\s+connected\s+to)$",
        r"(?:的)?(?:推荐合作对象有哪些|推荐合作对象|推荐合作机构|优先联系谁|谁最值得联系|可以跟谁合作)$",
        r"(?:recommend(?:ed)?\s+partners?|partner(?:ship)?\s+recommendations?|outreach\s+targets?|best\s+organizations?\s+to\s+contact)$",
        r"(?:people\s+score|digital\s+score|intel\s+score|composite\s+score|overall\s+score|scores?)$",
        r"(?:的)?(?:合作行动计划|行动计划|外联计划|行动方案|下一步怎么做|下一步应该怎么做|怎么推进|如何推进|推进合作|合作怎么推进|接下来怎么推进|下一步怎么推进|后续怎么做|怎么落地)$",
        r"(?:action\s+plan|next\s+steps|outreach\s+plan|execution\s+plan|follow[\-\s]?up\s+plan|how\s+to\s+proceed|how\s+should\s+we\s+proceed|how\s+to\s+move\s+forward)$",
        r"(?:的)?(?:证据简报|合作证据简报|决策依据|推荐依据|为什么推荐|为什么值得联系|为什么这个机构值得联系|为什么应该联系|为什么不应该联系|合作证据)$",
        r"(?:evidence\s+brief|decision\s+rationale|recommendation\s+evidence|why\s+recommend|why\s+recommended|why\s+should\s+i\s+contact|why\s+should\s+we\s+contact|why\s+worth\s+contacting)$",
    ]

    ACTION_WORD_PATTERNS = [
        r"怎么联系",
        r"如何联系",
        r"联系方式",
        r"联系信息",
        r"联系",
        r"行动计划",
        r"下一步",
        r"怎么推进",
        r"如何推进",
        r"推进合作",
        r"后续怎么做",
        r"怎么落地",
        r"证据简报",
        r"推荐依据",
        r"决策依据",
        r"为什么推荐",
        r"为什么应该联系",
        r"为什么不应该联系",
        r"why\s+recommend",
        r"why\s+should",
        r"action\s+plan",
        r"next\s+steps",
        r"contact\s+info",
        r"relationship\s+graph",
    ]

    PRONOUN_ONLY_VALUES = {
        "i",
        "we",
        "they",
        "them",
        "it",
        "this organization",
        "that organization",
        "this church",
        "that church",
        "这个机构",
        "该机构",
        "这个教会",
        "它",
    }

    TARGET_PATTERNS = [
        r"给我\s+(.+?)\s+联系\s+(.+?)\s+的(?:合作)?行动计划(?:\?|？|$)",
        r"(.+?)\s+联系\s+(.+?)\s+的(?:合作)?行动计划(?:\?|？|$)",
        r"给我\s+(.+?)\s+联系\s+(.+?)\s+的(?:合作)?证据简报(?:\?|？|$)",
        r"(.+?)\s+联系\s+(.+?)\s+的(?:合作)?证据简报(?:\?|？|$)",
        r"create\s+(?:an?\s+)?(?:outreach\s+|partnership\s+)?action\s+plan\s+for\s+(.+?)\s+(?:to\s+contact|to\s+approach|approach)\s+(.+?)(?:\?|？|$)",
        r"give\s+me\s+(?:an?\s+)?(?:partnership\s+)?evidence\s+brief\s+for\s+(.+?)\s+(?:to\s+contact|contacting)\s+(.+?)(?:\?|？|$)",
        r"why\s+should\s+(.+?)\s+contact\s+(.+?)(?:\?|？|$)",
        r"how\s+should\s+(.+?)\s+approach\s+(.+?)(?:\?|？|$)",
    ]

    def resolve_organization(
        self,
        query: str,
        *,
        db: Any = None,
        alias_map: Optional[Dict[str, str]] = None,
        known_organizations: Optional[Iterable[Any]] = None,
    ) -> Dict[str, Any]:
        raw_query = str(query or "").strip()
        normalized_query = self._normalize_text(raw_query)
        alias_map = alias_map or {}
        context_reference = self._has_context_reference(raw_query)

        if context_reference:
            return self._base_result(
                raw_query=raw_query,
                normalized_query=normalized_query,
                resolution_status="context_required",
                confidence=0.0,
                missing_parameters=["organization_context"],
                context_reference=True,
                requires_previous_organization=True,
                reason_codes=["context_reference_detected"],
                warnings=["context_reference_requires_previous_organization"],
            )

        primary_segment, target_segment = self._extract_primary_and_target_segments(raw_query)
        reason_codes: list[str] = []
        warnings: list[str] = []
        missing_parameters: list[str] = []

        if primary_segment:
            reason_codes.append("organization_segment_extracted")

        candidates = self._resolve_segment(
            primary_segment,
            db=db,
            alias_map=alias_map,
            known_organizations=known_organizations,
        )
        target_candidates = self._resolve_segment(
            target_segment,
            db=db,
            alias_map=alias_map,
            known_organizations=known_organizations,
        )

        resolution_status = "resolved"
        organization_name: Optional[str] = None
        organization_id: Optional[str] = None
        canonical_name: Optional[str] = None
        confidence = 0.0

        if not primary_segment:
            resolution_status = "missing"
            missing_parameters.append("organization_name")
            reason_codes.append("organization_name_missing")
            if self._is_broad_query(raw_query):
                warnings.append("broad_query_without_organization")
                reason_codes.append("broad_query_without_organization")
        elif not candidates:
            resolution_status = "unresolved"
            warnings.append("organization_unresolved")
            reason_codes.append("organization_resolution_unresolved")
        elif len(candidates) > 1 and self._is_ambiguous_candidates(candidates):
            resolution_status = "ambiguous"
            missing_parameters.append("organization_name")
            warnings.append("multiple_organization_candidates")
            reason_codes.append("multiple_organization_candidates_detected")
        else:
            top = candidates[0]
            organization_name = top["name"]
            organization_id = top["organization_id"]
            canonical_name = top["canonical_name"]
            confidence = round(float(top["confidence"]), 3)
            reason_codes.extend(top["reason_codes"])

        target_organization_name: Optional[str] = None
        target_organization_id: Optional[str] = None
        target_canonical_name: Optional[str] = None

        if target_segment:
            reason_codes.append("target_organization_segment_extracted")
            if target_candidates and not self._is_ambiguous_candidates(target_candidates):
                target_top = target_candidates[0]
                target_organization_name = target_top["name"]
                target_organization_id = target_top["organization_id"]
                target_canonical_name = target_top["canonical_name"]
                reason_codes.extend(target_top["reason_codes"])
            elif target_candidates:
                warnings.append("target_organization_ambiguous")
                reason_codes.append("target_organization_ambiguous")
            else:
                warnings.append("target_organization_unresolved")
                reason_codes.append("target_organization_unresolved")

        return {
            "input_query": raw_query,
            "normalized_query": normalized_query,
            "organization_name": organization_name,
            "organization_id": organization_id,
            "canonical_name": canonical_name,
            "target_organization_name": target_organization_name,
            "target_organization_id": target_organization_id,
            "target_canonical_name": target_canonical_name,
            "resolution_status": resolution_status,
            "confidence": round(float(confidence), 3),
            "candidates": candidates[:5],
            "target_candidates": target_candidates[:5],
            "missing_parameters": list(dict.fromkeys(missing_parameters)),
            "context_reference": False,
            "requires_previous_organization": False,
            "reason_codes": list(dict.fromkeys(reason_codes)),
            "warnings": list(dict.fromkeys(warnings)),
        }

    def _base_result(
        self,
        *,
        raw_query: str,
        normalized_query: str,
        resolution_status: str,
        confidence: float,
        missing_parameters: list[str],
        context_reference: bool,
        requires_previous_organization: bool,
        reason_codes: list[str],
        warnings: list[str],
    ) -> Dict[str, Any]:
        return {
            "input_query": raw_query,
            "normalized_query": normalized_query,
            "organization_name": None,
            "organization_id": None,
            "canonical_name": None,
            "target_organization_name": None,
            "target_organization_id": None,
            "target_canonical_name": None,
            "resolution_status": resolution_status,
            "confidence": round(float(confidence), 3),
            "candidates": [],
            "target_candidates": [],
            "missing_parameters": missing_parameters,
            "context_reference": context_reference,
            "requires_previous_organization": requires_previous_organization,
            "reason_codes": reason_codes,
            "warnings": warnings,
        }

    def _extract_primary_and_target_segments(self, query: str) -> tuple[Optional[str], Optional[str]]:
        raw = str(query or "").strip()
        for pattern in self.TARGET_PATTERNS:
            match = re.search(pattern, raw, re.IGNORECASE)
            if not match:
                continue
            primary = self._clean_segment(match.group(1) or "")
            target = self._clean_segment(match.group(2) or "")
            return primary, target
        return self._extract_primary_segment(raw), None

    def _extract_primary_segment(self, query: str) -> Optional[str]:
        raw = str(query or "").strip()
        patterns = [
            r"contact\s+info\s+for\s+(.+?)(?:\?|？|$)",
            r"what\s+is\s+the\s+contact\s+information\s+for\s+(.+?)(?:\?|？|$)",
            r"how\s+can\s+i\s+contact\s+(.+?)(?:\?|？|$)",
            r"how\s+do\s+i\s+contact\s+(.+?)(?:\?|？|$)",
            r"what\s+are\s+the\s+next\s+steps\s+for\s+(.+?)(?:\?|？|$)",
            r"give\s+me\s+(?:an?\s+)?(?:partnership\s+)?evidence\s+brief\s+for\s+(.+?)(?:\?|？|$)",
            r"show\s+me\s+the\s+relationship\s+graph\s+of\s+(.+?)(?:\?|？|$)",
            r"recommend\s+partner\s+organizations?\s+for\s+(.+?)(?:\?|？|$)",
            r"who\s+should\s+(.+?)\s+partner\s+with(?:\?|？|$)",
            r"who\s+should\s+(.+?)\s+contact\s+first(?:\?|？|$)",
            r"推荐\s+(.+?)\s+适合合作的机构(?:\?|？|$)",
            r"推荐\s+(.+?)\s+可以合作的机构(?:\?|？|$)",
            r"(.+?)\s+怎么联系(?:\?|？|$)",
            r"给我\s+(.+?)\s+的联系方式(?:\?|？|$)",
            r"给我\s+(.+?)\s+的证据简报(?:\?|？|$)",
            r"(.+?)\s+的证据简报(?:\?|？|$)",
            r"show\s+me\s+(.+?)\s+scores?(?:\?|？|$)",
            r"(.+?)\s+people\s+score(?:\?|？|$)",
            r"(.+?)\s+digital\s+score(?:\?|？|$)",
            r"(.+?)\s+intel\s+score(?:\?|？|$)",
            r"(.+?)\s+overall\s+score(?:\?|？|$)",
            r"(.+?)\s+composite\s+score(?:\?|？|$)",
            r"who\s+are\s+(.+?)\s+partners(?:\?|？|$)",
            r"what\s+organizations\s+is\s+(.+?)\s+connected\s+to(?:\?|？|$)",
            r"(.+?)\s+怎么推进(?:\?|？|$)",
            r"(.+?)\s+如何推进(?:\?|？|$)",
            r"(.+?)\s+接下来怎么推进(?:\?|？|$)",
            r"(.+?)\s+下一步怎么推进(?:\?|？|$)",
            r"(.+?)\s+后续怎么做(?:\?|？|$)",
            r"(.+?)\s+怎么落地(?:\?|？|$)",
            r"(.+?)\s+下一步怎么做(?:\?|？|$)",
            r"(.+?)\s+下一步应该怎么做(?:\?|？|$)",
            r"(.+?)\s+的关系图谱(?:\?|？|$)",
            r"(.+?)\s+和哪些机构有关联(?:\?|？|$)",
            r"(.+?)\s+有哪些合作方(?:\?|？|$)",
            r"(.+?)\s+推荐合作对象有哪些(?:\?|？|$)",
            r"为什么推荐\s+(.+?)(?:\?|？|$)",
            r"为什么应该联系\s+(.+?)(?:\?|？|$)",
            r"为什么不应该联系\s+(.+?)(?:\?|？|$)",
            r"(.+?)\s+的评分是多少(?:\?|？|$)",
            r"(.+?)\s+的评分多少(?:\?|？|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, raw, re.IGNORECASE)
            if not match:
                continue
            candidate = self._clean_segment(match.group(1) or "")
            if candidate:
                return candidate
        return self._clean_segment(raw)

    def _clean_segment(self, value: str) -> Optional[str]:
        clean = str(value or "").strip()
        if not clean:
            return None

        for pattern in self.LEADING_PHRASE_PATTERNS:
            clean = re.sub(pattern, "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"(?:\?|？|。|！|!|,|，|\.)+$", "", clean).strip()
        for pattern in self.TRAILING_INTENT_PATTERNS:
            clean = re.sub(pattern, "", clean, flags=re.IGNORECASE)

        clean = re.sub(r"target[_\-\s]?org[_\-\s]?id\s*[:=]\s*[A-Za-z0-9._\-]+", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"(?:\?|？|。|！|!|,|，|\.)+$", "", clean).strip()
        clean = re.sub(r"\s+", " ", clean).strip(" \"'`")
        clean = clean.rstrip(" .?!,;:，；：。！？")

        if len(clean) <= 1:
            return None
        if clean.lower() in self.PRONOUN_ONLY_VALUES:
            return None
        if self._has_context_reference(clean):
            return None
        if self._looks_like_action_phrase(clean):
            return None
        return clean

    def _looks_like_action_phrase(self, value: str) -> bool:
        raw = str(value or "").strip()
        if not raw:
            return False
        for pattern in self.ACTION_WORD_PATTERNS:
            if re.search(pattern, raw, re.IGNORECASE):
                return True
        if re.match(r"^(?:what|how|why|give|show|tell|create|build|draft)\b", raw, re.IGNORECASE):
            return True
        if re.match(r"^(?:给我|请给我|请生成|生成|帮我|告诉我|说明|查一下|查询)\b", raw):
            return True
        return False

    def _resolve_segment(
        self,
        segment: Optional[str],
        *,
        db: Any = None,
        alias_map: Optional[Dict[str, str]] = None,
        known_organizations: Optional[Iterable[Any]] = None,
    ) -> list[dict[str, Any]]:
        if not segment:
            return []

        alias_map = alias_map or {}
        records = self._build_records(known_organizations or [])
        if db is not None:
            records.extend(self._records_from_db(db, segment))

        candidates: list[dict[str, Any]] = []
        seen: set[tuple[Optional[str], str]] = set()
        normalized_segment = self._normalize_text(segment)

        alias_candidate = self._candidate_from_alias(segment, normalized_segment, alias_map, records)
        if alias_candidate is not None:
            key = (alias_candidate["organization_id"], alias_candidate["canonical_name"])
            seen.add(key)
            candidates.append(alias_candidate)

        for record in records:
            candidate = self._match_record(segment, normalized_segment, record)
            if candidate is None:
                continue
            key = (candidate["organization_id"], candidate["canonical_name"])
            if key in seen:
                continue
            seen.add(key)
            candidates.append(candidate)

        if not candidates:
            candidates.append(
                {
                    "organization_id": None,
                    "name": segment,
                    "canonical_name": segment,
                    "match_type": "extracted_only",
                    "confidence": 0.72,
                    "reason_codes": ["organization_segment_extracted_only"],
                }
            )

        candidates.sort(key=lambda item: (float(item["confidence"]), item["match_type"] == "exact"), reverse=True)
        return candidates[:5]

    def _candidate_from_alias(
        self,
        segment: str,
        normalized_segment: str,
        alias_map: Dict[str, str],
        records: list[OrganizationRecord],
    ) -> Optional[dict[str, Any]]:
        for alias, canonical_name in alias_map.items():
            if self._normalize_text(alias) != normalized_segment:
                continue
            record = next(
                (item for item in records if self._normalize_text(item.canonical_name) == self._normalize_text(canonical_name)),
                None,
            )
            return {
                "organization_id": record.organization_id if record else None,
                "name": segment,
                "canonical_name": record.canonical_name if record else canonical_name,
                "match_type": "alias",
                "confidence": 0.93 if record else 0.9,
                "reason_codes": ["alias_match"],
            }
        return None

    def _match_record(
        self,
        segment: str,
        normalized_segment: str,
        record: OrganizationRecord,
    ) -> Optional[dict[str, Any]]:
        best_match_type: Optional[str] = None
        best_confidence = 0.0
        best_reason_codes: list[str] = []

        raw_segment = str(segment or "").strip()

        for variant in record.variants:
            normalized_variant = self._normalize_text(variant)
            if not normalized_variant:
                continue
            if raw_segment == variant:
                best_match_type = "exact"
                best_confidence = 0.97
                best_reason_codes = ["exact_name_match"]
                break
            if normalized_segment == normalized_variant:
                if best_confidence < 0.89:
                    best_match_type = "normalized"
                    best_confidence = 0.89
                    best_reason_codes = ["normalized_name_match"]
                continue

            if normalized_segment in normalized_variant or normalized_variant in normalized_segment:
                token_ratio = self._token_overlap_ratio(normalized_segment, normalized_variant)
                if token_ratio >= 0.5 and best_confidence < 0.78:
                    best_match_type = "fuzzy"
                    best_confidence = 0.78
                    best_reason_codes = ["light_partial_match"]
                continue

            similarity = SequenceMatcher(None, normalized_segment, normalized_variant).ratio()
            if similarity >= 0.84 and best_confidence < 0.76:
                best_match_type = "fuzzy"
                best_confidence = 0.76
                best_reason_codes = ["light_fuzzy_match"]

        if not best_match_type:
            return None

        return {
            "organization_id": record.organization_id,
            "name": record.name,
            "canonical_name": record.canonical_name,
            "match_type": best_match_type,
            "confidence": round(best_confidence, 3),
            "reason_codes": best_reason_codes,
        }

    def _records_from_db(self, db: Any, segment: str) -> list[OrganizationRecord]:
        if not segment:
            return []
        rows = (
            db.query(OrganizationProfile)
            .filter(
                or_(
                    OrganizationProfile.name.ilike(f"%{segment}%"),
                    OrganizationProfile.english_name.ilike(f"%{segment}%"),
                    OrganizationProfile.short_name.ilike(f"%{segment}%"),
                    OrganizationProfile.official_name.ilike(f"%{segment}%"),
                )
            )
            .limit(10)
            .all()
        )
        return self._build_records(rows)

    def _build_records(self, organizations: Iterable[Any]) -> list[OrganizationRecord]:
        records: list[OrganizationRecord] = []
        seen: set[tuple[Optional[str], str]] = set()
        for item in organizations:
            record = self._to_record(item)
            if record is None:
                continue
            key = (record.organization_id, record.canonical_name)
            if key in seen:
                continue
            seen.add(key)
            records.append(record)
        return records

    def _to_record(self, item: Any) -> Optional[OrganizationRecord]:
        if item is None:
            return None
        if isinstance(item, str):
            name = item.strip()
            if not name:
                return None
            return OrganizationRecord(None, name, name, [name])

        if isinstance(item, dict):
            organization_id = self._strip_or_none(item.get("organization_id") or item.get("id"))
            name = self._strip_or_none(item.get("name"))
            canonical_name = self._strip_or_none(item.get("canonical_name")) or name
            variants = [
                name,
                canonical_name,
                self._strip_or_none(item.get("official_name")),
                self._strip_or_none(item.get("english_name")),
                self._strip_or_none(item.get("short_name")),
            ]
            alias_list = item.get("aliases")
            if isinstance(alias_list, list):
                variants.extend(self._strip_or_none(alias) for alias in alias_list)
            variants = [variant for variant in variants if variant]
            if not name or not canonical_name:
                return None
            return OrganizationRecord(organization_id, name, canonical_name, list(dict.fromkeys(variants)))

        name = self._strip_or_none(getattr(item, "name", None))
        canonical_name = (
            self._strip_or_none(getattr(item, "canonical_name", None))
            or self._strip_or_none(getattr(item, "official_name", None))
            or name
        )
        if not name or not canonical_name:
            return None
        variants = [
            name,
            canonical_name,
            self._strip_or_none(getattr(item, "official_name", None)),
            self._strip_or_none(getattr(item, "english_name", None)),
            self._strip_or_none(getattr(item, "short_name", None)),
        ]
        return OrganizationRecord(
            self._strip_or_none(getattr(item, "id", None)),
            name,
            canonical_name,
            [variant for variant in dict.fromkeys(variants) if variant],
        )

    def _strip_or_none(self, value: Any) -> Optional[str]:
        clean = str(value or "").strip()
        return clean or None

    def _has_context_reference(self, query: str) -> bool:
        raw = str(query or "").strip()
        return any(re.search(pattern, raw, re.IGNORECASE) for pattern in self.CONTEXT_REFERENCE_PATTERNS)

    def _is_broad_query(self, query: str) -> bool:
        raw = str(query or "").strip()
        return any(re.search(pattern, raw, re.IGNORECASE) for pattern in self.BROAD_QUERY_PATTERNS)

    def _is_ambiguous_candidates(self, candidates: list[dict[str, Any]]) -> bool:
        if len(candidates) < 2:
            return False
        first = float(candidates[0]["confidence"])
        second = float(candidates[1]["confidence"])
        return abs(first - second) <= 0.08

    def _normalize_text(self, value: str) -> str:
        raw = str(value or "").strip().lower()
        raw = raw.replace("&", " and ")
        raw = re.sub(r"[-_/]+", " ", raw)
        raw = re.sub(r"[^\w\s\u4e00-\u9fff]", " ", raw)
        raw = re.sub(r"\s+", " ", raw).strip()
        return raw

    def _token_overlap_ratio(self, left: str, right: str) -> float:
        left_tokens = {token for token in left.split(" ") if token}
        right_tokens = {token for token in right.split(" ") if token}
        if not left_tokens or not right_tokens:
            return 0.0
        overlap = len(left_tokens & right_tokens)
        return overlap / max(min(len(left_tokens), len(right_tokens)), 1)
