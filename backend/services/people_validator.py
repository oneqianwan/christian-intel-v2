import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


HIGH_PRIORITY_TITLES = [
    "CEO",
    "Chief Executive Officer",
    "President",
    "Founder",
    "Co-Founder",
    "Executive Director",
    "Senior Pastor",
    "Lead Pastor",
    "Bishop",
    "Archbishop",
    "General Secretary",
    "Chairman",
    "Chair",
    "Director General",
]

REJECTED_TITLES = [
    "Columnist",
    "Contributor",
    "Writer",
    "Author",
    "Blogger",
    "Editor",
    "Guest",
    "Speaker",
    "Volunteer",
    "Member",
    "Student",
    "Intern",
    "Consultant",
]

NAME_BLACKLIST = [
    "about",
    "contact",
    "home",
    "menu",
    "search",
    "login",
    "subscribe",
    "copyright",
    "privacy",
    "follow",
    "share",
    "twitter",
    "facebook",
    "instagram",
    "linkedin",
    "youtube",
    "tiktok",
    "read more",
    "learn more",
    "click here",
]


@dataclass
class ValidationResult:
    is_valid: bool
    reason: str
    confidence: float
    action: str


class PeopleValidator:
    """People 提取结果严格校验。"""

    def validate(
        self,
        candidate_name: str,
        candidate_title: str,
        org_name: str,
        org_country: str,
        source_url: str,
        extraction_method: str,
    ) -> ValidationResult:
        if not candidate_name or not candidate_title:
            return ValidationResult(False, "Empty name or title", 0.0, "reject")

        if len(candidate_name) < 3 or len(candidate_name) > 50:
            return ValidationResult(False, f"Name length invalid: {len(candidate_name)}", 0.0, "reject")

        name_lower = candidate_name.lower().strip()
        for blacklisted in NAME_BLACKLIST:
            if blacklisted in name_lower:
                return ValidationResult(False, f"Name in blacklist: {blacklisted}", 0.0, "reject")

        if not any(char.isalpha() for char in candidate_name):
            return ValidationResult(False, "Name contains no letters", 0.0, "reject")

        title_lower = candidate_title.lower().strip()
        for rejected in REJECTED_TITLES:
            if rejected.lower() in title_lower:
                return ValidationResult(False, f"Title in reject list: {rejected}", 0.1, "reject")

        for priority in HIGH_PRIORITY_TITLES:
            if priority.lower() in title_lower:
                if self._is_likely_person_name(candidate_name):
                    return ValidationResult(
                        True,
                        f"High priority title: {priority}",
                        0.85 if extraction_method == "rule" else 0.75,
                        "approve",
                    )

        org_words = set((org_name or "").lower().split())
        name_words = set(candidate_name.lower().split())
        shared = org_words & name_words
        if len(shared) >= 2 and len(name_words) <= 3:
            return ValidationResult(False, f"Name overlaps with org name: {sorted(shared)}", 0.2, "reject")

        if candidate_name.lower().strip() == (org_name or "").lower().strip():
            return ValidationResult(False, "Name equals org name", 0.0, "reject")

        if (org_country or "").lower() in {"united states", "united kingdom", "australia", "canada"}:
            if self._is_chinese_name(candidate_name):
                return ValidationResult(False, "Chinese name in English-country org", 0.2, "reject")

        if self._is_likely_person_name(candidate_name):
            return ValidationResult(
                True,
                "Passed basic validation, needs review",
                0.5 if extraction_method == "llm" else 0.6,
                "review",
            )

        return ValidationResult(False, "Name doesn't look like a person name", 0.2, "reject")

    def _is_likely_person_name(self, name: str) -> bool:
        words = name.split()
        if len(words) < 1 or len(words) > 4:
            return False

        for word in words:
            if not word or not word[0].isalpha():
                return False

        if words[0] and words[0][0].islower():
            if len(words) <= 2:
                return False

        if name.isupper() and len(name) > 4:
            return False

        return True

    def _is_chinese_name(self, name: str) -> bool:
        for char in name:
            if "\u4e00" <= char <= "\u9fff":
                return True
        return False
