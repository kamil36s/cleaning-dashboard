"""Small exact-match taxonomy used after source facts have been preserved."""

from __future__ import annotations

import re
import unicodedata


NORMALIZATION_VERSION = "normalization@1"

CONCEPTS = (
    ("concept_skill_sql", "skill", "SQL", "SQL", ("sql",)),
    ("concept_skill_api_testing", "skill", "API_TESTING", "API testing", ("api testing", "rest api testing", "restful api testing")),
    ("concept_tool_postman", "tool", "POSTMAN", "Postman", ("postman",)),
    ("concept_tool_jira", "tool", "JIRA", "Jira", ("jira",)),
    ("concept_tool_playwright", "tool", "PLAYWRIGHT", "Playwright", ("playwright",)),
    ("concept_tool_selenium", "tool", "SELENIUM", "Selenium", ("selenium",)),
    ("concept_language_python", "programming_language", "PYTHON", "Python", ("python",)),
    ("concept_language_javascript", "programming_language", "JAVASCRIPT", "JavaScript", ("javascript", "java script", "js")),
    ("concept_spoken_english", "spoken_language", "ENGLISH", "English", ("english",)),
    ("concept_spoken_polish", "spoken_language", "POLISH", "Polish", ("polish", "polski")),
    ("concept_spoken_norwegian", "spoken_language", "NORWEGIAN", "Norwegian", ("norwegian", "norsk")),
    ("concept_work_remote", "work_model", "REMOTE", "Remote", ("remote", "telecommute", "work from home")),
    ("concept_work_hybrid", "work_model", "HYBRID", "Hybrid", ("hybrid",)),
    ("concept_work_onsite", "work_model", "ON_SITE", "On-site", ("on site", "onsite", "on-site")),
    ("concept_contract_employment", "contract_type", "EMPLOYMENT", "Employment", ("employment", "employment contract", "uop", "umowa o prace", "umowa o pracę")),
    ("concept_contract_b2b", "contract_type", "B2B", "B2B", ("b2b",)),
    ("concept_contract_contract", "contract_type", "CONTRACT", "Contract", ("contract", "contractor")),
    ("concept_contract_temporary", "contract_type", "TEMPORARY", "Temporary", ("temporary", "fixed term", "fixed-term")),
)


def normalized_token(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    text = re.sub(r"[_/]+", " ", text)
    text = re.sub(r"[^\w+#.-]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip(" .-")


def concept_match(fact_type: str, value: str) -> tuple[str, float] | None:
    token = normalized_token(value)
    if not token:
        return None
    allowed = {
        "skill": {"skill", "tool", "programming_language"},
        "tool": {"tool", "programming_language"},
        "language": {"spoken_language"},
        "work_model": {"work_model"},
        "contract_type": {"contract_type"},
    }.get(fact_type, set())
    matches = []
    for concept_id, concept_type, _key, _label, aliases in CONCEPTS:
        if concept_type in allowed and token in {normalized_token(alias) for alias in aliases}:
            matches.append(concept_id)
    if len(matches) == 1:
        return matches[0], 0.99
    return None
