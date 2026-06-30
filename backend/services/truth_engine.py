import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional


logger = logging.getLogger(__name__)


@dataclass
class ConfidenceFactors:
    source_score: float = 0.0
    cross_validation: float = 0.0
    temporal_score: float = 0.0
    completeness: float = 0.0

    def weighted_average(self) -> float:
        weights = {
            "source_score": 0.35,
            "cross_validation": 0.25,
            "temporal_score": 0.20,
            "completeness": 0.20,
        }
        total = (
            self.source_score * weights["source_score"]
            + self.cross_validation * weights["cross_validation"]
            + self.temporal_score * weights["temporal_score"]
            + self.completeness * weights["completeness"]
        )
        return min(1.0, max(0.0, total))


class TruthEngine:
    SOURCE_TRUST = {
        "arda": 0.95,
        "pew_research": 0.95,
        "joshua_project": 0.90,
        "wikipedia": 0.75,
        "wikidata": 0.85,
        "official_website": 0.90,
        "rss": 0.60,
        "newsapi": 0.55,
        "auto_extracted": 0.40,
        "auto_extracted_verified": 0.70,
        "manual_seed": 0.95,
        "unknown": 0.30,
    }

    def calculate_confidence(
        self,
        source_name: str,
        content: str,
        published_at: Optional[datetime] = None,
        has_cross_validation: bool = False,
    ) -> float:
        factors = ConfidenceFactors()
        source_key = self._normalize_source_name(source_name)
        factors.source_score = self.SOURCE_TRUST.get(source_key, 0.30)
        factors.cross_validation = 0.7 if has_cross_validation else 0.3
        factors.temporal_score = self._calculate_temporal_score(published_at)
        factors.completeness = self._calculate_completeness(content)
        return factors.weighted_average()

    def _normalize_source_name(self, source: str) -> str:
        if not source:
            return "unknown"
        source_lower = source.lower().strip()
        mappings = {
            "arda": ["arda", "arda_country", "arda_denomination"],
            "pew_research": ["pew", "pewresearch"],
            "joshua_project": ["joshua", "joshuaproject"],
            "wikipedia": ["wikipedia", "wiki_extracted", "wiki"],
            "wikidata": ["wikidata"],
            "official_website": ["website", "official"],
            "manual_seed": ["manual", "seed"],
            "auto_extracted": ["auto_extracted"],
            "auto_extracted_verified": ["auto_extracted_verified"],
            "rss": ["rss"],
            "newsapi": ["newsapi"],
        }
        for canonical, aliases in mappings.items():
            if any(alias in source_lower for alias in aliases):
                return canonical
        return "unknown"

    def _calculate_temporal_score(self, published_at: Optional[datetime]) -> float:
        if not published_at:
            return 0.5
        now = datetime.now()
        age = now - published_at
        if age < timedelta(days=30):
            return 1.0
        if age < timedelta(days=90):
            return 0.9
        if age < timedelta(days=365):
            return 0.8
        if age < timedelta(days=365 * 2):
            return 0.6
        if age < timedelta(days=365 * 3):
            return 0.4
        return 0.2

    def _calculate_completeness(self, content: str) -> float:
        if not content:
            return 0.0
        length = len(content)
        if length > 2000:
            base = 1.0
        elif length > 1000:
            base = 0.85
        elif length > 500:
            base = 0.70
        elif length > 200:
            base = 0.55
        elif length > 50:
            base = 0.40
        else:
            base = 0.20

        structure_bonus = 0.0
        content_lower = content.lower()
        if any(marker in content_lower for marker in ["http", "www", ".org", ".com"]):
            structure_bonus += 0.05
        if any(marker in content_lower for marker in ["founded", "established", "since"]):
            structure_bonus += 0.05
        if any(marker in content_lower for marker in ["leader", "ceo", "director", "pastor"]):
            structure_bonus += 0.05
        return min(1.0, base + structure_bonus)

    def generate_confidence_report(
        self,
        source_name: str,
        content: str,
        published_at: Optional[datetime] = None,
        has_cross_validation: bool = False,
    ) -> Dict:
        confidence = self.calculate_confidence(source_name, content, published_at, has_cross_validation)
        return {
            "confidence_score": round(confidence, 2),
            "confidence_level": self._level_label(confidence),
            "source_trust": self.SOURCE_TRUST.get(self._normalize_source_name(source_name), 0.30),
            "temporal_status": self._temporal_label(published_at),
            "recommendation": self._recommendation(confidence),
        }

    def _level_label(self, score: float) -> str:
        if score >= 0.85:
            return "Very High"
        if score >= 0.70:
            return "High"
        if score >= 0.55:
            return "Medium"
        if score >= 0.40:
            return "Low"
        return "Very Low"

    def _temporal_label(self, published_at: Optional[datetime]) -> str:
        if not published_at:
            return "Unknown date"
        age = datetime.now() - published_at
        if age < timedelta(days=30):
            return "Recent (< 30 days)"
        if age < timedelta(days=365):
            return "Within 1 year"
        if age < timedelta(days=365 * 2):
            return "1-2 years old"
        return "Older than 2 years"

    def _recommendation(self, confidence: float) -> str:
        if confidence >= 0.80:
            return "Highly reliable, can be used for decision-making"
        if confidence >= 0.60:
            return "Reliable with caveats, verify critical details"
        if confidence >= 0.40:
            return "Use with caution, seek additional verification"
        return "Insufficient confidence, recommend manual verification"
