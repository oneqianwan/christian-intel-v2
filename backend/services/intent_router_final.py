from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


class IntentRouterFinal:
    SUPPORTED_LOOKUP_INTENTS = {
        "organization_score_lookup",
        "organization_relationship_graph_lookup",
        "organization_contact_lookup",
        "organization_partnership_recommendation_lookup",
        "organization_partnership_action_plan_lookup",
        "organization_partnership_evidence_brief_lookup",
    }

    INTENT_TO_GROUP = {
        "organization_score_lookup": "score",
        "organization_relationship_graph_lookup": "graph",
        "organization_contact_lookup": "contact",
        "organization_partnership_recommendation_lookup": "recommendation",
        "organization_partnership_action_plan_lookup": "action_plan",
        "organization_partnership_evidence_brief_lookup": "evidence_brief",
        "general_chat": "general_chat",
        "unsupported_or_ambiguous": "unsupported_or_ambiguous",
    }

    INTENT_TO_RESPONSE_CONTRACT = {
        "organization_score_lookup": "score_lookup",
        "organization_relationship_graph_lookup": "relationship_graph",
        "organization_contact_lookup": "contact_lookup",
        "organization_partnership_recommendation_lookup": "partnership_recommendations",
        "organization_partnership_action_plan_lookup": "partnership_action_plan",
        "organization_partnership_evidence_brief_lookup": "partnership_evidence_brief",
    }

    PRIORITY_MATRIX = {
        "organization_score_lookup": 600,
        "organization_contact_lookup": 500,
        "organization_relationship_graph_lookup": 450,
        "organization_partnership_action_plan_lookup": 400,
        "organization_partnership_evidence_brief_lookup": 350,
        "organization_partnership_recommendation_lookup": 300,
        "general_chat": 100,
        "unsupported_or_ambiguous": 0,
    }

    CONTEXT_REFERENCE_PATTERNS = [
        r"这个机构",
        r"该机构",
        r"刚才那个机构",
        r"这个教会",
        r"刚才那个教会",
        r"它\b",
        r"this\s+organization",
        r"that\s+organization",
        r"this\s+church",
        r"that\s+church",
        r"\bit\b",
        r"\bthem\b",
    ]

    PROGRESS_QUERY_PATTERNS = [
        r"怎么推进",
        r"如何推进",
        r"推进合作",
        r"合作怎么推进",
        r"接下来怎么推进",
        r"下一步怎么推进",
        r"后续怎么做",
        r"怎么落地",
        r"how\s+to\s+proceed",
        r"how\s+should\s+we\s+proceed",
        r"how\s+to\s+move\s+forward",
        r"next\s+move",
        r"execution\s+plan",
        r"follow[\-\s]?up\s+plan",
    ]

    EVIDENCE_REASON_PATTERNS = [
        r"为什么推荐",
        r"推荐依据",
        r"为什么值得联系",
        r"为什么这个机构值得联系",
        r"为什么应该联系",
        r"为什么不应该联系",
        r"决策依据",
        r"合作证据",
        r"证据简报",
        r"why\s+recommend",
        r"why\s+recommended",
        r"why\s+should\s+i\s+contact",
        r"why\s+should\s+we\s+contact",
        r"why\s+worth\s+contacting",
        r"evidence\s+behind\s+the\s+recommendation",
        r"recommendation\s+evidence",
        r"decision\s+rationale",
        r"evidence\s+brief",
    ]

    BROAD_ANALYSIS_PATTERNS = [
        r"帮我分析",
        r"分析一下",
        r"分析\s+.+",
        r"analy[sz]e",
        r"analysis",
        r"tell\s+me\s+about",
        r"介绍一下",
    ]

    GENERAL_CHAT_PATTERNS = [
        r"^hello\b",
        r"^hi\b",
        r"^你好$",
        r"^您好$",
        r"^thanks?\b",
        r"^谢谢",
    ]

    def __init__(self, parser: Any):
        self.parser = parser

    def route(self, query: str) -> Dict[str, Any]:
        raw_query = (query or "").strip()
        normalized_query = self._normalize_query(raw_query)
        language = self._detect_language(raw_query)
        context_reference = self._has_context_reference(raw_query)
        organization_resolution = self.parser.resolve_organization_entities(raw_query, use_db=False)

        if not raw_query:
            return self._finalize_result(
                intent="unsupported_or_ambiguous",
                normalized_query=normalized_query,
                language=language,
                candidate_intents=[],
                ambiguous=False,
                organization_name=None,
                target_organization_name=None,
                target_org_id=None,
                missing_parameters=[],
                reason_codes=["empty_query"],
                matched_keywords=[],
                safe_default_intent="unsupported_or_ambiguous",
                routing_decision="unsupported",
                warnings=["empty_query"],
                organization_resolution=organization_resolution,
            )

        candidates: list[dict[str, Any]] = []
        for builder in (
            self._build_score_candidate,
            self._build_contact_candidate,
            self._build_graph_candidate,
            self._build_action_plan_candidate,
            self._build_evidence_brief_candidate,
            self._build_recommendation_candidate,
        ):
            candidate = builder(raw_query, organization_resolution)
            if candidate:
                candidates.append(candidate)

        candidates = self._apply_combo_rules(raw_query, candidates)
        candidates.sort(key=lambda item: (item["confidence"], item["priority"]), reverse=True)

        if not candidates:
            if self._is_broad_analysis_query(raw_query):
                missing_parameters = ["organization_context"] if context_reference else []
                warnings = ["broad_analysis_query"]
                if context_reference:
                    warnings.append("context_reference_requires_previous_organization")
                return self._finalize_result(
                    intent="unsupported_or_ambiguous",
                    normalized_query=normalized_query,
                    language=language,
                    candidate_intents=[],
                    ambiguous=True,
                    organization_name=None,
                    target_organization_name=None,
                    target_org_id=None,
                    missing_parameters=missing_parameters,
                    reason_codes=["broad_analysis_query_requires_clarification"],
                    matched_keywords=[],
                    safe_default_intent="unsupported_or_ambiguous",
                    routing_decision="ask_clarification",
                    warnings=warnings,
                    organization_resolution=organization_resolution,
                )

            if self._is_general_chat(raw_query):
                return self._finalize_result(
                    intent="general_chat",
                    normalized_query=normalized_query,
                    language=language,
                    candidate_intents=[
                        {
                            "intent": "general_chat",
                            "confidence": 0.92,
                            "matched_signals": ["general_chat_signal"],
                            "priority": self.PRIORITY_MATRIX["general_chat"],
                        }
                    ],
                    ambiguous=False,
                    organization_name=None,
                    target_organization_name=None,
                    target_org_id=None,
                    missing_parameters=[],
                    reason_codes=["general_chat_signal_detected"],
                    matched_keywords=[],
                    safe_default_intent="general_chat",
                    routing_decision="direct",
                    warnings=[],
                    organization_resolution=organization_resolution,
                )

            warnings = []
            missing_parameters = []
            if context_reference:
                warnings.append("context_reference_requires_previous_organization")
                missing_parameters.append("organization_context")
            return self._finalize_result(
                intent="unsupported_or_ambiguous",
                normalized_query=normalized_query,
                language=language,
                candidate_intents=[],
                ambiguous=bool(context_reference),
                organization_name=None,
                target_organization_name=None,
                target_org_id=None,
                missing_parameters=missing_parameters,
                reason_codes=["unsupported_query"],
                matched_keywords=[],
                safe_default_intent="unsupported_or_ambiguous",
                routing_decision="ask_clarification" if context_reference else "unsupported",
                warnings=warnings,
                organization_resolution=organization_resolution,
            )

        primary = candidates[0]
        candidate_intents = [
            {
                "intent": candidate["intent"],
                "confidence": round(float(candidate["confidence"]), 3),
                "matched_signals": list(candidate["matched_signals"]),
                "priority": int(candidate["priority"]),
            }
            for candidate in candidates[:2]
        ]

        ambiguous = self._is_ambiguous(candidates)
        if (
            not ambiguous
            and self._is_progress_query(raw_query)
            and any(item["intent"] == "organization_partnership_action_plan_lookup" for item in candidates)
            and any(item["intent"] == "organization_partnership_recommendation_lookup" for item in candidates)
        ):
            ambiguous = True
        missing_parameters: list[str] = []
        warnings: list[str] = []

        organization_name = primary.get("organization_name")
        target_organization_name = primary.get("target_organization_name")
        target_org_id = primary.get("target_org_id")

        if organization_resolution.get("resolution_status") == "ambiguous":
            organization_name = None
            warnings.append("multiple_organization_candidates")
            if "organization_name" not in missing_parameters:
                missing_parameters.append("organization_name")
        elif organization_resolution.get("resolution_status") == "context_required":
            organization_name = None
        elif organization_resolution.get("organization_name"):
            organization_name = organization_resolution.get("organization_name")

        if organization_resolution.get("target_organization_name"):
            target_organization_name = organization_resolution.get("target_organization_name")
        if organization_resolution.get("target_organization_id"):
            target_org_id = organization_resolution.get("target_organization_id")

        if context_reference and not organization_name:
            missing_parameters.append("organization_context")
            warnings.append("context_reference_requires_previous_organization")
        elif not organization_name:
            missing_parameters.append("organization_name")
            warnings.append("organization_name_missing")

        routing_decision = "direct"
        safe_default_intent = primary["intent"]
        if ambiguous:
            routing_decision = "safe_default"
        if missing_parameters:
            routing_decision = "ask_clarification"

        if self._is_broad_analysis_query(raw_query) and primary["intent"] not in self.SUPPORTED_LOOKUP_INTENTS:
            warnings.append("broad_analysis_query")
            routing_decision = "ask_clarification"
            safe_default_intent = "unsupported_or_ambiguous"

        return self._finalize_result(
            intent=primary["intent"],
            normalized_query=normalized_query,
            language=language,
            candidate_intents=candidate_intents,
            ambiguous=ambiguous,
            organization_name=organization_name,
            target_organization_name=target_organization_name,
            target_org_id=target_org_id,
            missing_parameters=missing_parameters,
            reason_codes=list(primary["reason_codes"]),
            matched_keywords=list(primary["matched_keywords"]),
            safe_default_intent=safe_default_intent,
            routing_decision=routing_decision,
            warnings=warnings,
            organization_resolution=organization_resolution,
        )

    def _normalize_query(self, query: str) -> str:
        return re.sub(r"\s+", " ", (query or "").strip())

    def _detect_language(self, query: str) -> str:
        raw = str(query or "")
        has_zh = bool(re.search(r"[\u4e00-\u9fff]", raw))
        has_en = bool(re.search(r"[A-Za-z]", raw))
        if has_zh and has_en:
            return "mixed"
        if has_zh:
            return "zh"
        if has_en:
            return "en"
        return "unknown"

    def _has_context_reference(self, query: str) -> bool:
        return any(re.search(pattern, query, re.IGNORECASE) for pattern in self.CONTEXT_REFERENCE_PATTERNS)

    def _matches_any(self, query: str, patterns: list[str]) -> bool:
        raw = str(query or "").strip()
        return any(re.search(pattern, raw, re.IGNORECASE) for pattern in patterns)

    def _is_progress_query(self, query: str) -> bool:
        return self._matches_any(query, self.PROGRESS_QUERY_PATTERNS)

    def _is_evidence_reason_query(self, query: str) -> bool:
        return self._matches_any(query, self.EVIDENCE_REASON_PATTERNS)

    def _extract_with_context_guard(self, query: str, extractor: Any) -> Optional[str]:
        if self._has_context_reference(query):
            return None
        try:
            candidate = extractor(query)
        except Exception:
            return None
        clean = str(candidate or "").strip()
        if not clean:
            return None
        normalized_query = self._normalize_query(query).lower()
        if clean.lower() == normalized_query:
            return None
        if self._has_context_reference(clean):
            return None
        return clean

    def _is_broad_analysis_query(self, query: str) -> bool:
        raw = str(query or "").strip()
        if any(re.search(pattern, raw, re.IGNORECASE) for pattern in self.BROAD_ANALYSIS_PATTERNS):
            if not any(
                builder(raw, None)
                for builder in (
                    self._build_score_candidate,
                    self._build_contact_candidate,
                    self._build_graph_candidate,
                    self._build_recommendation_candidate,
                    self._build_action_plan_candidate,
                    self._build_evidence_brief_candidate,
                )
            ):
                return True
        return False

    def _is_general_chat(self, query: str) -> bool:
        raw = str(query or "").strip()
        return any(re.search(pattern, raw, re.IGNORECASE) for pattern in self.GENERAL_CHAT_PATTERNS)

    def _match_keywords(self, query: str, patterns: list[str]) -> list[str]:
        matches: list[str] = []
        for pattern in patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if not match:
                continue
            token = (match.group(0) or "").strip()
            if token and token not in matches:
                matches.append(token)
        return matches

    def _build_candidate(
        self,
        *,
        intent: str,
        query: str,
        keyword_patterns: list[str],
        organization_name: Optional[str],
        target_organization_name: Optional[str] = None,
        target_org_id: Optional[str] = None,
        base_confidence: float = 0.72,
        extra_reason_codes: Optional[list[str]] = None,
    ) -> Optional[dict[str, Any]]:
        matched_keywords = self._match_keywords(query, keyword_patterns)
        if not matched_keywords:
            return None

        matched_signals = [f"matched_keyword:{item}" for item in matched_keywords]
        reason_codes = [f"matched_{self.INTENT_TO_GROUP[intent]}_signal"]
        if organization_name:
            matched_signals.append("organization_name_extracted")
            reason_codes.append("organization_name_extracted")
        if target_organization_name:
            matched_signals.append("target_organization_name_extracted")
            reason_codes.append("target_organization_name_extracted")
        if target_org_id:
            matched_signals.append("target_org_id_extracted")
            reason_codes.append("target_org_id_extracted")
        if extra_reason_codes:
            reason_codes.extend(extra_reason_codes)

        confidence = base_confidence + min(len(matched_keywords), 3) * 0.05
        if organization_name:
            confidence += 0.06
        if target_organization_name or target_org_id:
            confidence += 0.03

        return {
            "intent": intent,
            "confidence": min(round(confidence, 3), 0.99),
            "matched_signals": matched_signals,
            "priority": self.PRIORITY_MATRIX[intent],
            "organization_name": organization_name or None,
            "target_organization_name": target_organization_name or None,
            "target_org_id": target_org_id or None,
            "matched_keywords": matched_keywords,
            "reason_codes": reason_codes,
        }

    def _resolved_organization_name(self, resolution: Optional[dict[str, Any]]) -> Optional[str]:
        if not isinstance(resolution, dict):
            return None
        status = str(resolution.get("resolution_status") or "").strip()
        if status in {"context_required", "missing", "unresolved", "ambiguous"}:
            return None
        clean = str(resolution.get("organization_name") or "").strip()
        return clean or None

    def _resolved_target_organization_name(self, resolution: Optional[dict[str, Any]]) -> Optional[str]:
        if not isinstance(resolution, dict):
            return None
        clean = str(resolution.get("target_organization_name") or "").strip()
        return clean or None

    def _resolved_target_organization_id(self, resolution: Optional[dict[str, Any]]) -> Optional[str]:
        if not isinstance(resolution, dict):
            return None
        clean = str(resolution.get("target_organization_id") or "").strip()
        return clean or None

    def _build_score_candidate(self, query: str, organization_resolution: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
        if not self.parser._is_score_query(query):
            return None
        return self._build_candidate(
            intent="organization_score_lookup",
            query=query,
            keyword_patterns=list(self.parser.SCORE_KEYWORDS),
            organization_name=self._resolved_organization_name(organization_resolution)
            or self._extract_with_context_guard(query, self.parser._extract_score_org_name),
            base_confidence=0.82,
        )

    def _build_contact_candidate(self, query: str, organization_resolution: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
        if not self.parser._is_contact_query(query):
            return None
        return self._build_candidate(
            intent="organization_contact_lookup",
            query=query,
            keyword_patterns=list(self.parser.CONTACT_KEYWORDS),
            organization_name=self._resolved_organization_name(organization_resolution)
            or self._extract_with_context_guard(query, self.parser._extract_contact_org_name),
            base_confidence=0.8,
        )

    def _build_graph_candidate(self, query: str, organization_resolution: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
        if not self.parser._is_relationship_graph_query(query):
            return None
        return self._build_candidate(
            intent="organization_relationship_graph_lookup",
            query=query,
            keyword_patterns=list(self.parser.RELATIONSHIP_GRAPH_KEYWORDS),
            organization_name=self._resolved_organization_name(organization_resolution)
            or self._extract_with_context_guard(query, self.parser._extract_relationship_graph_org_name),
            base_confidence=0.78,
        )

    def _build_recommendation_candidate(self, query: str, organization_resolution: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
        if not self.parser._is_recommendation_query(query):
            return None
        return self._build_candidate(
            intent="organization_partnership_recommendation_lookup",
            query=query,
            keyword_patterns=list(self.parser.RECOMMENDATION_KEYWORDS),
            organization_name=self._resolved_organization_name(organization_resolution)
            or self._extract_with_context_guard(query, self.parser._extract_recommendation_org_name),
            base_confidence=0.74,
        )

    def _build_action_plan_candidate(self, query: str, organization_resolution: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
        if not self.parser._is_action_plan_query(query):
            return None
        return self._build_candidate(
            intent="organization_partnership_action_plan_lookup",
            query=query,
            keyword_patterns=list(self.parser.ACTION_PLAN_KEYWORDS),
            organization_name=self._resolved_organization_name(organization_resolution)
            or self._extract_with_context_guard(query, self.parser._extract_action_plan_org_name),
            target_organization_name=self._resolved_target_organization_name(organization_resolution)
            or self.parser._extract_action_plan_target_org_name(query),
            target_org_id=self._resolved_target_organization_id(organization_resolution)
            or self.parser._extract_action_plan_target_org_id(query),
            base_confidence=0.76,
            extra_reason_codes=["progress_query_action_plan_default"] if self._is_progress_query(query) else None,
        )

    def _build_evidence_brief_candidate(self, query: str, organization_resolution: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
        if not self.parser._is_evidence_brief_query(query):
            return None
        return self._build_candidate(
            intent="organization_partnership_evidence_brief_lookup",
            query=query,
            keyword_patterns=list(self.parser.EVIDENCE_BRIEF_KEYWORDS),
            organization_name=self._resolved_organization_name(organization_resolution)
            or self._extract_with_context_guard(query, self.parser._extract_evidence_brief_org_name),
            target_organization_name=self._resolved_target_organization_name(organization_resolution)
            or self.parser._extract_evidence_brief_target_org_name(query),
            target_org_id=self._resolved_target_organization_id(organization_resolution)
            or self.parser._extract_evidence_brief_target_org_id(query),
            base_confidence=0.77,
        )

    def _apply_combo_rules(self, query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_intent = {candidate["intent"]: candidate for candidate in candidates}

        action_candidate = by_intent.get("organization_partnership_action_plan_lookup")
        recommendation_candidate = by_intent.get("organization_partnership_recommendation_lookup")
        contact_candidate = by_intent.get("organization_contact_lookup")
        evidence_candidate = by_intent.get("organization_partnership_evidence_brief_lookup")
        progress_query = self._is_progress_query(query)
        evidence_reason_query = self._is_evidence_reason_query(query)

        if action_candidate and progress_query and not recommendation_candidate:
            recommendation_candidate = {
                "intent": "organization_partnership_recommendation_lookup",
                "confidence": max(round(float(action_candidate["confidence"]) - 0.08, 3), 0.7),
                "matched_signals": ["progress_query_secondary_recommendation_candidate"],
                "priority": 340,
                "organization_name": action_candidate.get("organization_name"),
                "target_organization_name": None,
                "target_org_id": None,
                "matched_keywords": list(action_candidate.get("matched_keywords") or [])[:1] or ["怎么推进"],
                "reason_codes": ["progress_query_secondary_recommendation_candidate"],
            }
            candidates.append(recommendation_candidate)
            by_intent[recommendation_candidate["intent"]] = recommendation_candidate

        if evidence_candidate and evidence_reason_query and not recommendation_candidate:
            recommendation_candidate = {
                "intent": "organization_partnership_recommendation_lookup",
                "confidence": max(round(float(evidence_candidate["confidence"]) - 0.09, 3), 0.69),
                "matched_signals": ["evidence_reason_query_secondary_recommendation_candidate"],
                "priority": 320,
                "organization_name": evidence_candidate.get("organization_name"),
                "target_organization_name": evidence_candidate.get("target_organization_name"),
                "target_org_id": evidence_candidate.get("target_org_id"),
                "matched_keywords": ["recommendation rationale overlap"],
                "reason_codes": ["evidence_reason_query_secondary_recommendation_candidate"],
            }
            candidates.append(recommendation_candidate)
            by_intent[recommendation_candidate["intent"]] = recommendation_candidate

        if action_candidate and recommendation_candidate:
            action_candidate["confidence"] = min(action_candidate["confidence"] + 0.08, 0.99)
            action_candidate["priority"] = max(action_candidate["priority"], 560)
            action_candidate["reason_codes"].append("combined_recommendation_and_action_plan_action_plan_wins")
            recommendation_candidate["reason_codes"].append("combined_recommendation_and_action_plan_secondary")

        if action_candidate and contact_candidate:
            action_candidate["confidence"] = min(action_candidate["confidence"] + 0.1, 0.99)
            action_candidate["priority"] = max(action_candidate["priority"], 550)
            action_candidate["reason_codes"].append("combined_contact_and_action_plan_action_plan_wins")
            contact_candidate["reason_codes"].append("combined_contact_and_action_plan_secondary")

        if evidence_candidate and recommendation_candidate:
            evidence_candidate["confidence"] = min(evidence_candidate["confidence"] + 0.08, 0.99)
            evidence_candidate["reason_codes"].append("combined_recommendation_and_evidence_brief_evidence_brief_wins")
            recommendation_candidate["reason_codes"].append("combined_recommendation_and_evidence_brief_secondary")
            if evidence_reason_query:
                evidence_candidate["confidence"] = min(evidence_candidate["confidence"] + 0.03, 0.99)
                evidence_candidate["priority"] = max(evidence_candidate["priority"], 545)
                evidence_candidate["reason_codes"].append("evidence_brief_wins_over_recommendation_reason_query")

        if evidence_candidate and re.search(r"为什么.+值得联系|why.+worth.+contact", query, re.IGNORECASE):
            evidence_candidate["confidence"] = min(evidence_candidate["confidence"] + 0.04, 0.99)
            evidence_candidate["reason_codes"].append("contact_decision_rationale_prefers_evidence_brief")

        return candidates

    def _is_ambiguous(self, candidates: list[dict[str, Any]]) -> bool:
        if len(candidates) < 2:
            return False
        return abs(float(candidates[0]["confidence"]) - float(candidates[1]["confidence"])) <= 0.12

    def _finalize_result(
        self,
        *,
        intent: str,
        normalized_query: str,
        language: str,
        candidate_intents: list[dict[str, Any]],
        ambiguous: bool,
        organization_name: Optional[str],
        target_organization_name: Optional[str],
        target_org_id: Optional[str],
        missing_parameters: list[str],
        reason_codes: list[str],
        matched_keywords: list[str],
        safe_default_intent: str,
        routing_decision: str,
        warnings: list[str],
        organization_resolution: Optional[dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        confidence = 0.0
        if candidate_intents:
            confidence = round(float(candidate_intents[0]["confidence"]), 3)
        result: Dict[str, Any] = {
            "intent": intent,
            "intent_group": self.INTENT_TO_GROUP[intent],
            "confidence": confidence,
            "ambiguous": bool(ambiguous),
            "candidate_intents": candidate_intents,
            "organization_name": organization_name,
            "target_organization_name": target_organization_name,
            "target_org_id": target_org_id,
            "missing_parameters": missing_parameters,
            "reason_codes": list(dict.fromkeys(reason_codes)),
            "matched_keywords": list(dict.fromkeys(matched_keywords)),
            "normalized_query": normalized_query,
            "language": language,
            "safe_default_intent": safe_default_intent,
            "routing_decision": routing_decision,
            "warnings": list(dict.fromkeys(warnings)),
        }
        if isinstance(organization_resolution, dict):
            result["organization_resolution"] = organization_resolution
            target_resolution = {
                "target_organization_name": organization_resolution.get("target_organization_name"),
                "target_organization_id": organization_resolution.get("target_organization_id"),
                "target_canonical_name": organization_resolution.get("target_canonical_name"),
                "target_candidates": organization_resolution.get("target_candidates") or [],
            }
            result["target_organization_resolution"] = target_resolution
        response_contract = self.INTENT_TO_RESPONSE_CONTRACT.get(intent)
        if response_contract:
            result["response_contract"] = response_contract
        return result
