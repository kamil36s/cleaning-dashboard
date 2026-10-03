"""Versioned questionnaire metadata and deterministic scoring for Mental Health.

Validated item wording intentionally does not live in this module. Instruments
remain ``external-score`` until a complete authorised language pack is installed.
Numeric scoring is kept separately so packs can be versioned without changing
historical results.
"""

from __future__ import annotations

import json
import logging
import re
from copy import deepcopy
from pathlib import Path
from statistics import mean


class MentalHealthScoringError(ValueError):
    pass


QUESTIONNAIRE_PACKS_ROOT = Path(__file__).resolve().parent / "mental_health_questionnaires"
PACK_TEXT_STATUSES = {"official", "official_translation", "user_supplied"}
PACK_SCHEMA_VERSION = "1.0"
LOGGER = logging.getLogger(__name__)


def _bands(*rows):
    return [dict(zip(("min", "max", "label"), row)) for row in rows]


def _instrument(
    instrument_id,
    name,
    short_name,
    category,
    construct_type,
    cadence,
    minimum,
    recall,
    minutes,
    item_count,
    score_min,
    score_max,
    higher_is_better,
    source,
    license_status,
    *,
    enabled=False,
    subscales=None,
    bands=None,
    scoring=None,
    description="",
    special_flags=None,
    license_notice="",
    custom=False,
    questions=None,
    response_options=None,
    language="en",
):
    native = custom and bool(questions)
    return {
        "id": instrument_id,
        "name": name,
        "shortName": short_name,
        "category": category,
        "description": description,
        "constructType": construct_type,
        "questionnaireMode": "native" if native else "external-score",
        "questionTextStatus": "user_supplied" if native else "missing",
        "defaultCadenceDays": cadence,
        "minimumRetestDays": minimum,
        "recallPeriod": recall,
        "estimatedMinutes": minutes,
        "itemCount": item_count,
        "language": language,
        "version": "1.0",
        "scoringVersion": "1.0",
        "source": source,
        "licenseStatus": license_status,
        "licenseNotice": license_notice,
        "scoreMin": score_min,
        "scoreMax": score_max,
        "higherIsBetter": higher_is_better,
        "requiresTotalScore": True,
        "subscales": subscales or [],
        "responseOptions": response_options or [],
        "questions": questions or [],
        "scoring": scoring or {"type": "external"},
        "interpretationBands": bands or [],
        "specialFlags": special_flags or [],
        "enabledByDefault": enabled,
        "custom": custom,
        "disclaimer": (
            "Narzędzie do samomonitoringu i screeningu; wynik nie jest diagnozą "
            "i nie zastępuje profesjonalnej oceny."
            if not custom
            else "CUSTOM — niestandaryzowany tracker osobisty, nie test psychologiczny."
        ),
    }


DEFAULT_RESPONSE_03 = [
    {"value": 0, "label": "0"}, {"value": 1, "label": "1"},
    {"value": 2, "label": "2"}, {"value": 3, "label": "3"},
]


REGISTRY = {
    item["id"]: item
    for item in [
        _instrument("phq9", "Patient Health Questionnaire-9", "PHQ-9", "depression", "state", 14, 7, "past 2 weeks", 3, 9, 0, 27, False, "PHQ Screeners", "unrestricted", enabled=True, description="Depressive symptom severity screening.", scoring={"type": "sum", "items": 9}, bands=_bands((0, 4, "minimal"), (5, 9, "mild"), (10, 14, "moderate"), (15, 19, "moderately severe"), (20, 27, "severe")), special_flags=[{"item": 9, "flag": "self_harm_related"}]),
        _instrument("gad7", "Generalized Anxiety Disorder-7", "GAD-7", "anxiety", "state", 14, 7, "past 2 weeks", 3, 7, 0, 21, False, "PHQ Screeners", "unrestricted", enabled=True, description="Generalized anxiety symptom severity screening.", scoring={"type": "sum", "items": 7}, bands=_bands((0, 4, "minimal"), (5, 9, "mild"), (10, 14, "moderate"), (15, 21, "severe"))),
        _instrument("who5", "WHO-5 Well-Being Index", "WHO-5", "wellbeing", "state", 14, 7, "past 2 weeks", 2, 5, 0, 25, True, "World Health Organization", "CC BY-NC-SA 3.0", enabled=True, description="Subjective mental well-being; also reports raw score ×4.", scoring={"type": "who5", "items": 5}, bands=_bands((0, 12, "low well-being"), (13, 25, "above common further-assessment threshold")), license_notice="Attribution required; non-commercial share-alike use."),
        _instrument("k6", "Kessler Psychological Distress Scale", "K6", "distress", "state", 28, 14, "past 30 days", 2, 6, 0, 24, False, "Kessler et al.", "metadata/scoring only", enabled=True, description="Nonspecific psychological distress.", scoring={"type": "sum", "items": 6}, bands=_bands((0, 12, "below high-distress reference"), (13, 24, "high-distress screening reference"))),
        _instrument("dass21", "Depression Anxiety Stress Scales-21", "DASS-21", "distress", "state", 28, 14, "past week", 7, 21, 0, 42, False, "DASS / UNSW", "public-domain questionnaire; public-app conditions apply", subscales=[{"id": "depression", "name": "Depression"}, {"id": "anxiety", "name": "Anxiety"}, {"id": "stress", "name": "Stress"}], scoring={"type": "dass21"}, description="Trend-first depression, anxiety and stress dimensions; no automatic diagnosis."),
        _instrument("cbi", "Copenhagen Burnout Inventory", "CBI", "burnout", "mixed", 28, 14, "current", 7, 19, 0, 100, False, "National Research Centre for the Working Environment", "metadata/scoring only", enabled=True, subscales=[{"id": "personal", "name": "Personal burnout"}, {"id": "work", "name": "Work burnout"}, {"id": "client", "name": "Client burnout", "optional": True}], scoring={"type": "cbi", "reverseItems": [13]}, description="Separate personal, work-related and client-related burnout means."),
        _instrument("pcl5", "PTSD Checklist for DSM-5", "PCL-5", "ptsd", "state", 28, 14, "past month (past-week version supported separately)", 8, 20, 0, 80, False, "VA National Center for PTSD", "public domain", subscales=[{"id": "B", "name": "Intrusion"}, {"id": "C", "name": "Avoidance"}, {"id": "D", "name": "Negative alterations"}, {"id": "E", "name": "Arousal/reactivity"}], scoring={"type": "pcl5"}, bands=_bands((0, 30, "below common research cut-point range"), (31, 80, "within/above common 31–33 research cut-point range"))),
        _instrument("pcptsd5", "Primary Care PTSD Screen for DSM-5", "PC-PTSD-5", "ptsd", "state", None, 90, "current/past month", 2, 5, 0, 5, False, "VA National Center for PTSD", "public domain", scoring={"type": "sum", "items": 5}, description="Baseline screening after a trauma-exposure gate."),
        _instrument("dssb", "Brief Dissociative Symptoms Scale", "DSS-B", "dissociation", "state", 28, 7, "past week", 3, 8, 0, 32, False, "DSS-B authors", "metadata/scoring only", scoring={"type": "sum", "items": 8}, description="Trend only; no universal diagnostic cutoff."),
        _instrument("asrs6", "Adult ADHD Self-Report Scale v1.1 Screener", "ASRS-6", "neurodevelopmental", "trait", 365, 180, "long-term pattern", 3, 6, 0, 6, False, "WHO / ASRS Workgroup", "reproduction permitted with required notices", scoring={"type": "asrs6"}, description="Six-question ADHD screener; official threshold algorithm required."),
        _instrument("aq10", "Autism Spectrum Quotient – 10 Adult", "AQ-10", "neurodevelopmental", "trait", 365, 365, "trait", 3, 10, 0, 10, False, "Autism Research Centre", "non-commercial with acknowledgement", scoring={"type": "aq10"}, bands=_bands((0, 5, "below NICE assessment-consideration threshold"), (6, 10, "threshold suggesting comprehensive assessment may be appropriate"))),
        _instrument("aq50", "Autism Spectrum Quotient – 50", "AQ-50", "neurodevelopmental", "trait", None, 365, "trait", 12, 50, 0, 50, False, "Autism Research Centre", "non-commercial with acknowledgement", scoring={"type": "aq50"}, description="Broad autistic-trait profile; use once or very rarely."),
        _instrument("rses", "Rosenberg Self-Esteem Scale", "RSES", "self_concept", "mixed", 90, 28, "current", 3, 10, 0, 30, True, "Morris Rosenberg / University of Maryland", "public domain", enabled=True, scoring={"type": "rses", "reverseItems": [3, 5, 8, 9, 10]}, description="Self-esteem trend; no universal clinical high/low cutoff."),
        _instrument("swls", "Satisfaction With Life Scale", "SWLS", "wellbeing", "mixed", 90, 28, "current", 2, 5, 5, 35, True, "Diener et al.", "non-commercial with attribution", enabled=True, scoring={"type": "sum", "items": 5}, bands=_bands((5, 9, "very low"), (10, 14, "low"), (15, 19, "slightly below average"), (20, 24, "approximately average"), (25, 29, "high"), (30, 35, "very high"))),
        _instrument("flourishing", "Flourishing Scale", "FS", "wellbeing", "mixed", 90, 28, "current", 3, 8, 8, 56, True, "Diener et al.", "non-commercial with attribution", scoring={"type": "sum", "items": 8}, description="Trend and baseline comparison without pathology thresholds."),
        _instrument("spane", "Scale of Positive and Negative Experience", "SPANE", "wellbeing", "state", 28, 14, "past 4 weeks", 4, 12, -24, 30, True, "Diener et al.", "non-commercial with attribution", enabled=True, subscales=[{"id": "positive", "name": "SPANE-P", "higherIsBetter": True}, {"id": "negative", "name": "SPANE-N", "higherIsBetter": False}, {"id": "balance", "name": "SPANE-B", "higherIsBetter": True}], scoring={"type": "spane"}),
        _instrument("mini_ipip20", "Mini-IPIP (20 items)", "Mini-IPIP-20", "personality", "trait", 365, 365, "trait", 6, 20, 4, 20, True, "International Personality Item Pool / Donnellan et al.", "public domain", subscales=[{"id": key, "name": name} for key, name in (("extraversion", "Extraversion"), ("agreeableness", "Agreeableness"), ("conscientiousness", "Conscientiousness"), ("neuroticism", "Neuroticism"), ("intellect_imagination", "Intellect / Imagination"))], scoring={"type": "ipip_domains", "itemsPerDomain": 4}, description="The Donnellan et al. Mini-IPIP as a separate instrument; raw domain totals only."),
        _instrument("ipip_bfm20", "IPIP Big Five Factor Markers – 20", "IPIP-BFM-20", "personality", "trait", 365, 365, "trait", 6, 20, 4, 20, True, "International Personality Item Pool", "public domain", subscales=[{"id": key, "name": name} for key, name in (("extraversion", "Extraversion"), ("agreeableness", "Agreeableness"), ("conscientiousness", "Conscientiousness"), ("emotional_stability", "Emotional Stability"), ("intellect", "Intellect / Openness"))], scoring={"type": "ipip_domains", "itemsPerDomain": 4}, description="Raw domain totals/averages only; no percentile without installed norms."),
        _instrument("ipip_bfm50", "IPIP Big Five Factor Markers – 50", "IPIP-BFM-50", "personality", "trait", 365, 365, "trait", 12, 50, 10, 50, True, "International Personality Item Pool", "public domain", subscales=[{"id": key, "name": name} for key, name in (("extraversion", "Extraversion"), ("agreeableness", "Agreeableness"), ("conscientiousness", "Conscientiousness"), ("emotional_stability", "Emotional Stability"), ("intellect", "Intellect / Openness"))], scoring={"type": "ipip_domains", "itemsPerDomain": 10}, description="Deeper personality baseline; raw domains only."),
        _instrument("auditc", "Alcohol Use Disorders Identification Test – Consumption", "AUDIT-C", "substance_use", "state", 180, 90, "typical/recent alcohol use", 2, 3, 0, 12, False, "World Health Organization", "metadata/scoring only", scoring={"type": "auditc"}, description="Alcohol screening, not diagnosis."),
        _instrument("audit", "Alcohol Use Disorders Identification Test", "AUDIT", "substance_use", "state", 365, 180, "recent alcohol use", 4, 10, 0, 40, False, "World Health Organization", "metadata/scoring only", scoring={"type": "sum", "items": 10}, bands=_bands((0, 7, "WHO Zone I"), (8, 15, "WHO Zone II"), (16, 19, "WHO Zone III"), (20, 40, "WHO Zone IV"))),
        _instrument("asrm", "Altman Self-Rating Mania Scale", "ASRM", "mania", "state", 7, 7, "past week", 3, 5, 0, 20, False, "Altman et al.", "metadata/scoring only", scoring={"type": "sum", "items": 5}, description="Optional deliberate symptom monitoring; no bipolar inference."),
    ]
}

# These instruments are profiles of separate dimensions.  Requiring a total
# would create a score that the source instrument does not define.
for _profile_id in ("dass21", "cbi", "spane", "ipip_bfm20", "mini_ipip20", "ipip_bfm50"):
    REGISTRY[_profile_id]["requiresTotalScore"] = False


def _external(instrument_id, name, short_name, category, construct, cadence, minimum, recall, count, low, high, higher, source, license_status, description=""):
    REGISTRY[instrument_id] = _instrument(instrument_id, name, short_name, category, construct, cadence, minimum, recall, 3, count, low, high, higher, source, license_status, description=description)


_external("pss10", "Perceived Stress Scale-10", "PSS-10", "stress", "state", 28, 14, "past month", 10, 0, 40, False, "Cohen et al.", "permission required", "No universal diagnostic cutoff.")
_external("isi", "Insomnia Severity Index", "ISI", "sleep", "state", 28, 14, "past 2 weeks", 7, 0, 28, False, "ISI / Mapi Research Trust", "licensed")
REGISTRY["isi"]["interpretationBands"] = _bands((0, 7, "no clinically significant insomnia"), (8, 14, "subthreshold"), (15, 21, "moderate clinical insomnia"), (22, 28, "severe clinical insomnia"))
_external("ess", "Epworth Sleepiness Scale", "ESS", "sleep", "state", 28, 14, "recent", 8, 0, 24, False, "Epworth Sleepiness Scale", "licensed")
_external("dast10", "Drug Abuse Screening Test-10", "DAST-10", "substance_use", "state", 365, 180, "past year", 10, 0, 10, False, "DAST", "copyrighted")
_external("whodas12", "WHO Disability Assessment Schedule 2.0 – 12", "WHODAS-12", "functioning", "state", 90, 28, "past 30 days", 12, 0, 48, False, "World Health Organization", "electronic-use licence may be required")
_external("spin", "Social Phobia Inventory", "SPIN", "social_anxiety", "state", 90, 28, "past week", 17, 0, 68, False, "SPIN authors", "external-score only")
_external("ocir", "Obsessive-Compulsive Inventory-Revised", "OCI-R", "ocd", "state", 90, 28, "past month", 18, 0, 72, False, "OCI-R authors", "external-score only")
_external("catq", "Camouflaging Autistic Traits Questionnaire", "CAT-Q", "neurodevelopmental", "trait", 365, 180, "trait", 25, 25, 175, False, "CAT-Q authors", "external-score only")
_external("raadsr", "Ritvo Autism Asperger Diagnostic Scale-Revised", "RAADS-R", "neurodevelopmental", "trait", None, 365, "trait", 80, 0, 240, False, "RAADS-R authors", "external-score only")
_external("ders", "Difficulties in Emotion Regulation Scale", "DERS / DERS-SF", "emotion_regulation", "mixed", 90, 28, "current", None, None, None, False, "DERS authors", "external-score only")
_external("ucla_loneliness", "UCLA Loneliness Scale", "UCLA-LS", "social", "mixed", 90, 28, "current", None, None, None, False, "UCLA Loneliness Scale authors", "external-score only")
_external("ecrr", "Experiences in Close Relationships-Revised", "ECR-R", "relationships", "trait", 365, 180, "close relationships", 36, 36, 252, False, "ECR-R authors", "external-score only")
_external("tas20", "Toronto Alexithymia Scale-20", "TAS-20", "self_knowledge", "trait", 365, 180, "trait", 20, 20, 100, False, "TAS-20 authors", "external-score only")


CUSTOM_OPTIONS = [{"value": value, "label": str(value)} for value in range(5)]
SENSORY_QUESTIONS = [
    "Wrażliwość na hałas", "Wrażliwość na światło", "Dyskomfort dotyku lub ubrań",
    "Przeciążenie w tłumie", "Przeciążenie wieloma rozmowami",
    "Trudność filtrowania bodźców", "Potrzeba wycofania się",
    "Długi powrót do równowagi po przeciążeniu",
]
EXECUTIVE_QUESTIONS = [
    "Trudność rozpoczęcia zadania", "Trudność przełączania zadań", "Prokrastynacja",
    "Gubienie toku zadań", "Trudność ustalania priorytetów", "Ślepota czasowa",
    "Zawodna pamięć robocza", "Trudność zakończenia aktywności",
    "Przytłoczenie, gdy konkuruje kilka zadań",
]
for instrument_id, name, short_name, category, questions in (
    ("sensory_overload", "Sensory Overload Check", "Sensory Check", "custom", SENSORY_QUESTIONS),
    ("executive_function", "Executive Function Check-in", "Executive Check", "custom", EXECUTIVE_QUESTIONS),
):
    REGISTRY[instrument_id] = _instrument(
        instrument_id, name, short_name, category, "state", 7, 7, "past 7 days",
        3, len(questions), 0, len(questions) * 4, False, "User-defined template",
        "custom / not validated", custom=True, language="pl",
        questions=[{"id": str(index), "text": text, "required": True} for index, text in enumerate(questions, 1)],
        response_options=CUSTOM_OPTIONS, scoring={"type": "sum", "items": len(questions)},
        description="Osobisty trend; bez interpretacji diagnostycznej.",
    )


# Instrument versions identify the authoritative form, not the application
# release. Existing assessment rows keep the version stored at completion.
for _instrument_id, _instrument_version in {
    "phq9": "PHQ-9 Polish for Poland (official PHQ Screeners form)",
    "gad7": "GAD-7 Polish for Poland (official PHQ Screeners form)",
    "who5": "WHO/UCN/MSD/MHE/2024.1 Polish translation",
    "rses": "RSES 10-item English (UMD public-domain copy)",
    "ipip_bfm50": "IPIP Goldberg Big-Five 50-item official sample",
    "pcl5": "PCL-5 Standard 2023-08-29",
    "pcptsd5": "PC-PTSD-5 2022",
    "swls": "SWLS Polish translation (Jankowski; official Diener distribution)",
    "flourishing": "Flourishing Scale Polish translation (Kaczmarek/Baran; official Diener distribution)",
    "spane": "SPANE/SPIND Polish translation (Kaczmarek/Baran; official Diener distribution)",
    "mini_ipip20": "Mini-IPIP Donnellan 20-item English",
}.items():
    REGISTRY[_instrument_id]["version"] = _instrument_version


def _pack_failure(path, message):
    raise MentalHealthScoringError(f"{path}: {message}")


def _validate_options(path, options, label):
    if not isinstance(options, list) or len(options) < 2:
        _pack_failure(path, f"{label} must contain at least two response options")
    values = []
    for option in options:
        if not isinstance(option, dict) or "value" not in option or not str(option.get("label") or "").strip():
            _pack_failure(path, f"{label} requires a value and an exact non-empty label")
        value = option["value"]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _pack_failure(path, f"{label} values must be numeric")
        values.append(value)
    if len(values) != len(set(values)):
        _pack_failure(path, f"{label} response values must be unique")
    return set(values)


def _validate_language_pack(instrument, path, pack):
    if not isinstance(pack, dict):
        _pack_failure(path, "definition root must be an object")
    if pack.get("schemaVersion") != PACK_SCHEMA_VERSION:
        _pack_failure(path, f"schemaVersion must be {PACK_SCHEMA_VERSION}")
    if pack.get("instrumentId") != instrument["id"]:
        _pack_failure(path, f"instrumentId must be {instrument['id']}")
    if pack.get("instrumentVersion") != instrument["version"]:
        _pack_failure(path, f"instrumentVersion must be {instrument['version']}")
    if not str(pack.get("scoringVersion") or "").strip():
        _pack_failure(path, "scoringVersion is required")
    language = str(pack.get("language") or "")
    if not re.fullmatch(r"[a-z]{2}(?:-[A-Z]{2})?", language):
        _pack_failure(path, "language must be an ISO language tag such as pl or en")
    if pack.get("questionTextStatus") not in PACK_TEXT_STATUSES:
        _pack_failure(path, "questionTextStatus is invalid")

    source = pack.get("source")
    if not isinstance(source, dict) or not all(str(source.get(key) or "").strip() for key in ("title", "url")):
        _pack_failure(path, "source metadata requires title and url")
    if not re.fullmatch(r"https://[^\s]+", str(source["url"])):
        _pack_failure(path, "source.url must be an absolute HTTPS URL")
    digest = str(source.get("documentSha256") or "")
    if digest and not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
        _pack_failure(path, "source.documentSha256 must be a SHA-256 hex digest")
    licence = pack.get("license")
    if not isinstance(licence, dict) or not all(str(licence.get(key) or "").strip() for key in ("status", "notice")):
        _pack_failure(path, "license metadata requires status and notice")

    questions = pack.get("questions")
    if not isinstance(questions, list) or not questions:
        _pack_failure(path, "questions must be a non-empty array")
    if pack.get("questionCount") != len(questions):
        _pack_failure(path, f"questionCount must equal {len(questions)}")
    ids = []
    global_values = _validate_options(path, pack.get("responseOptions"), "responseOptions") if pack.get("responseOptions") else None
    option_values = {}
    for question in questions:
        if not isinstance(question, dict):
            _pack_failure(path, "every question must be an object")
        item_id = str(question.get("id") or "")
        if not item_id or not str(question.get("text") or "").strip():
            _pack_failure(path, "every question requires a unique id and exact non-empty text")
        ids.append(item_id)
        options = question.get("responseOptions")
        if options is not None:
            option_values[item_id] = _validate_options(path, options, f"question {item_id} responseOptions")
        elif global_values is not None:
            option_values[item_id] = global_values
        else:
            _pack_failure(path, f"question {item_id} has no response options")
        if "required" in question and not isinstance(question["required"], bool):
            _pack_failure(path, f"question {item_id} required must be boolean")
    if len(ids) != len(set(ids)):
        _pack_failure(path, "question ids must be unique")
    known_ids = set(ids)
    for question in questions:
        condition = question.get("visibleWhen") or question.get("visibleWhenAny")
        if not condition:
            continue
        if not isinstance(condition, dict):
            _pack_failure(path, f"question {question['id']} visibility condition must be an object")
        references = {str(condition["itemId"])} if "itemId" in condition else {str(item_id) for item_id in condition.get("itemIds", [])}
        if not references or not references <= known_ids or str(question["id"]) in references:
            _pack_failure(path, f"question {question['id']} visibility condition references invalid items")

    scoring = pack.get("scoring")
    if not isinstance(scoring, dict) or scoring.get("type") not in {"sum", "subscale_sum"}:
        _pack_failure(path, "scoring.type must be sum or subscale_sum")
    item_ids = [str(item_id) for item_id in (scoring.get("itemIds") or [])]
    if not item_ids or len(item_ids) != len(set(item_ids)) or not set(item_ids) <= known_ids:
        _pack_failure(path, "scoring.itemIds must be unique known question ids")
    if pack.get("scoredItemCount") != len(item_ids):
        _pack_failure(path, f"scoredItemCount must equal {len(item_ids)}")
    allowed_values = scoring.get("allowedValues")
    if not isinstance(allowed_values, list) or not allowed_values:
        _pack_failure(path, "scoring.allowedValues is required")
    if any(set(allowed_values) != option_values[item_id] for item_id in item_ids):
        _pack_failure(path, "scoring.allowedValues must exactly match each scored item's response values")
    reverse_ids = {str(item_id) for item_id in (scoring.get("reverseItemIds") or [])}
    declared_reverse = {str(question["id"]) for question in questions if question.get("reverseScored") is True}
    if not reverse_ids <= set(item_ids) or reverse_ids != declared_reverse:
        _pack_failure(path, "reverseItemIds must exactly match questions marked reverseScored")

    subscales = scoring.get("subscales") or {}
    if not isinstance(subscales, dict):
        _pack_failure(path, "scoring.subscales must be an object")
    derived_subscales = scoring.get("derivedSubscales") or {}
    if not isinstance(derived_subscales, dict):
        _pack_failure(path, "scoring.derivedSubscales must be an object")
    registered_subscales = {row["id"] for row in instrument.get("subscales", [])}
    if set(subscales) & set(derived_subscales) or set(subscales) | set(derived_subscales) != registered_subscales:
        _pack_failure(path, "scoring subscale ids must exactly match the instrument registry")
    for subscale_id, members in subscales.items():
        member_ids = [str(item_id) for item_id in members]
        if not member_ids or len(member_ids) != len(set(member_ids)) or not set(member_ids) <= set(item_ids):
            _pack_failure(path, f"subscale {subscale_id} must contain unique scored item ids")
    memberships = [str(item_id) for members in subscales.values() for item_id in members]
    if memberships and (len(memberships) != len(set(memberships)) or set(memberships) != set(item_ids)):
        _pack_failure(path, "subscale membership must cover every scored item exactly once")
    for subscale_id, definition in derived_subscales.items():
        if not isinstance(definition, dict) or definition.get("type") != "difference":
            _pack_failure(path, f"derived subscale {subscale_id} must use the supported difference type")
        minuend = str(definition.get("minuend") or "")
        subtrahend = str(definition.get("subtrahend") or "")
        if not minuend or not subtrahend or minuend == subtrahend or not {minuend, subtrahend} <= set(subscales):
            _pack_failure(path, f"derived subscale {subscale_id} must reference two different base subscales")

    gate = scoring.get("gate")
    if gate is not None:
        gate_id = str(gate.get("itemId") or "") if isinstance(gate, dict) else ""
        if gate_id not in known_ids or gate_id in item_ids or not isinstance(gate.get("proceedValues"), list):
            _pack_failure(path, "scoring gate must reference a non-scored question and declare proceedValues")
        if not set(gate["proceedValues"]) <= option_values[gate_id]:
            _pack_failure(path, "scoring gate proceedValues are not valid responses")

    bands = pack.get("interpretationBands")
    if not isinstance(bands, list):
        _pack_failure(path, "interpretationBands must be an array")
    previous_max = None
    for band in sorted(bands, key=lambda row: row.get("min", float("inf")) if isinstance(row, dict) else float("inf")):
        if not isinstance(band, dict) or not all(key in band for key in ("min", "max", "label")) or band["min"] > band["max"]:
            _pack_failure(path, "every interpretation band requires min, max and label")
        if previous_max is not None and band["min"] <= previous_max:
            _pack_failure(path, "interpretation bands must not overlap")
        if instrument.get("scoreMin") is not None and band["min"] < instrument["scoreMin"] or instrument.get("scoreMax") is not None and band["max"] > instrument["scoreMax"]:
            _pack_failure(path, "interpretation band is outside the registered score range")
        previous_max = band["max"]
    rules = pack.get("interpretationRules") or []
    if not isinstance(rules, list):
        _pack_failure(path, "interpretationRules must be an array")
    for rule in rules:
        rule_ids = {str(item_id) for item_id in rule.get("itemIds", [])} if isinstance(rule, dict) else set()
        if rule.get("type") != "any_item_lte" or not rule_ids or not rule_ids <= set(item_ids) or "value" not in rule or not str(rule.get("label") or "").strip():
            _pack_failure(path, "interpretationRules contains an unsupported or invalid rule")
    return pack


def _load_language_packs(instrument, pack_root=None):
    instrument = deepcopy(instrument)
    instrument["languagePacks"] = []
    instrument["questionnaireValidationErrors"] = []
    directory = Path(pack_root or QUESTIONNAIRE_PACKS_ROOT) / instrument["id"]
    if not directory.is_dir():
        return instrument
    packs = []
    for path in sorted(directory.glob("*.json")):
        try:
            pack = json.loads(path.read_text(encoding="utf-8"))
            packs.append((path, _validate_language_pack(instrument, path, pack)))
        except (OSError, json.JSONDecodeError, MentalHealthScoringError) as exc:
            message = str(exc)
            instrument["questionnaireValidationErrors"].append(message)
            LOGGER.error("Mental Health questionnaire definition rejected; %s remains external-score: %s", instrument["id"], message)
    if instrument["questionnaireValidationErrors"]:
        return instrument
    if not packs:
        return instrument
    _, selected = next((row for row in packs if row[1].get("language") in {"pl", "pl-PL"}), packs[0])
    instrument["languagePacks"] = [
        {
            "language": pack["language"], "questionTextStatus": pack["questionTextStatus"],
            "source": pack["source"], "file": path.name, "scoringVersion": pack["scoringVersion"],
        }
        for path, pack in packs
    ]
    instrument["questions"] = selected["questions"]
    instrument["responseOptions"] = selected.get("responseOptions") or []
    instrument["language"] = selected["language"]
    instrument["questionTextStatus"] = selected["questionTextStatus"]
    instrument["questionnaireMode"] = "native"
    instrument["questionCount"] = selected["questionCount"]
    instrument["scoredItemCount"] = selected["scoredItemCount"]
    instrument["name"] = selected.get("title") or instrument["name"]
    instrument["description"] = selected.get("shortDescription") or instrument["description"]
    instrument["recallPeriod"] = selected.get("recallPeriod") or instrument["recallPeriod"]
    instrument["estimatedMinutes"] = selected.get("estimatedMinutes") or instrument["estimatedMinutes"]
    instrument["instructions"] = selected.get("instructions") or ""
    instrument["sourceMetadata"] = selected["source"]
    instrument["licenseMetadata"] = selected["license"]
    instrument["source"] = selected["source"]["title"]
    instrument["licenseStatus"] = selected["license"]["status"]
    instrument["licenseNotice"] = selected["license"]["notice"]
    instrument["attribution"] = selected.get("attribution") or ""
    instrument["scoring"] = selected["scoring"]
    instrument["scoringVersion"] = selected["scoringVersion"]
    instrument["interpretationBands"] = selected["interpretationBands"]
    instrument["interpretationRules"] = selected.get("interpretationRules") or []
    return instrument


def get_registry(pack_root=None):
    return [_load_language_packs(REGISTRY[key], pack_root) for key in REGISTRY]


def get_instrument(instrument_id, pack_root=None):
    instrument_id = str(instrument_id)
    for instrument in get_registry(pack_root):
        if instrument["id"] == instrument_id:
            return instrument
    raise MentalHealthScoringError("Unknown instrument")


def _ordered_values(responses, count):
    if isinstance(responses, dict):
        values = [responses.get(str(index), responses.get(index)) for index in range(1, count + 1)]
    elif isinstance(responses, list):
        values = responses[:]
    else:
        raise MentalHealthScoringError("Responses must be a list or object")
    if len(values) != count or any(value is None for value in values):
        raise MentalHealthScoringError(f"Exactly {count} answered items are required")
    try:
        return [float(value) for value in values]
    except (TypeError, ValueError) as exc:
        raise MentalHealthScoringError("Responses must be numeric") from exc


def _sum_score(responses, count):
    values = _ordered_values(responses, count)
    return {"rawScore": sum(values), "subscaleScores": {}}


def score_phq9(responses):
    return _sum_score(responses, 9)


def score_gad7(responses):
    return _sum_score(responses, 7)


def score_who5(responses):
    raw = sum(_ordered_values(responses, 5))
    return {"rawScore": raw, "normalizedScore": raw * 4, "subscaleScores": {"percentage": raw * 4}}


def score_cbi(responses):
    values = _ordered_values(responses, 19)
    values[12] = 100 - values[12]
    return {
        "rawScore": None,
        "subscaleScores": {
            "personal": mean(values[0:6]),
            "work": mean(values[6:13]),
            "client": mean(values[13:19]),
        },
    }


def score_rses(responses):
    values = _ordered_values(responses, 10)
    reverse = {3, 5, 8, 9, 10}
    raw = sum(3 - value if index in reverse else value for index, value in enumerate(values, 1))
    return {"rawScore": raw, "subscaleScores": {}}


def score_pcl5(responses):
    values = _ordered_values(responses, 20)
    clusters = {"B": sum(values[0:5]), "C": sum(values[5:7]), "D": sum(values[7:14]), "E": sum(values[14:20])}
    return {"rawScore": sum(values), "subscaleScores": clusters}


def score_ipip_domains(responses, domains):
    """Score caller-supplied versioned domain keys without assuming item wording."""
    if not isinstance(responses, dict) or not isinstance(domains, dict):
        raise MentalHealthScoringError("IPIP responses and domains must be objects")
    scores = {}
    for domain, keys in domains.items():
        total = 0.0
        for key in keys:
            item_id = str(key[0] if isinstance(key, (tuple, list)) else key)
            reverse = bool(key[1]) if isinstance(key, (tuple, list)) and len(key) > 1 else False
            if item_id not in responses:
                raise MentalHealthScoringError(f"Missing IPIP response: {item_id}")
            value = float(responses[item_id])
            total += 6 - value if reverse else value
        scores[domain] = total
    return {"rawScore": None, "subscaleScores": scores}


def _registered_response_map(instrument, responses):
    questions = instrument.get("questions") or []
    if isinstance(responses, dict):
        values = {str(key): value for key, value in responses.items()}
    elif isinstance(responses, list):
        if len(responses) != len(questions):
            raise MentalHealthScoringError(f"Exactly {len(questions)} questionnaire responses are required")
        values = {str(question["id"]): value for question, value in zip(questions, responses)}
    else:
        raise MentalHealthScoringError("Responses must be a list or object")
    known_ids = {str(question["id"]) for question in questions}
    if not set(values) <= known_ids:
        raise MentalHealthScoringError("Responses contain an unknown questionnaire item")
    global_options = instrument.get("responseOptions") or []
    by_id = {str(question["id"]): question for question in questions}
    numeric = {}
    for item_id, value in values.items():
        if value in (None, ""):
            continue
        if isinstance(value, bool):
            raise MentalHealthScoringError(f"Response for item {item_id} must be numeric")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise MentalHealthScoringError(f"Response for item {item_id} must be numeric") from exc
        options = by_id[item_id].get("responseOptions") or global_options
        allowed = {float(option["value"]) for option in options}
        if number not in allowed:
            raise MentalHealthScoringError(f"Response for item {item_id} is outside its registered options")
        numeric[item_id] = number
    return numeric


def _condition_is_active(condition, values):
    if not isinstance(condition, dict):
        return True
    if "itemId" in condition:
        return values.get(str(condition["itemId"])) in {float(value) for value in condition.get("values", [])}
    item_ids = [str(item_id) for item_id in condition.get("itemIds", [])]
    minimum = float(condition.get("minValue", 0))
    return bool(item_ids) and any(values.get(item_id, float("-inf")) >= minimum for item_id in item_ids)


def _score_registered_definition(instrument, responses):
    scoring = instrument["scoring"]
    values = _registered_response_map(instrument, responses)
    for question in instrument.get("questions", []):
        condition = question.get("visibleWhen") or question.get("visibleWhenAny")
        if question.get("required", True) and _condition_is_active(condition, values) and str(question["id"]) not in values:
            raise MentalHealthScoringError(f"Missing required response: {question['id']}")
    gate = scoring.get("gate")
    if gate:
        gate_id = str(gate["itemId"])
        if gate_id not in values:
            raise MentalHealthScoringError(f"Missing required response: {gate_id}")
        proceed = {float(value) for value in gate["proceedValues"]}
        if values[gate_id] not in proceed:
            return {"rawScore": float(gate.get("stopScore", 0)), "subscaleScores": {}}

    item_ids = [str(item_id) for item_id in scoring["itemIds"]]
    missing = [item_id for item_id in item_ids if item_id not in values]
    if missing:
        raise MentalHealthScoringError(f"Missing required responses: {', '.join(missing)}")
    reverse_ids = {str(item_id) for item_id in scoring.get("reverseItemIds", [])}
    allowed = [float(value) for value in scoring["allowedValues"]]
    reverse_min, reverse_max = min(allowed), max(allowed)

    def keyed(item_id):
        value = values[item_id]
        return reverse_min + reverse_max - value if item_id in reverse_ids else value

    subscales = {
        subscale_id: sum(keyed(str(item_id)) for item_id in members)
        for subscale_id, members in (scoring.get("subscales") or {}).items()
    }
    for subscale_id, definition in (scoring.get("derivedSubscales") or {}).items():
        subscales[subscale_id] = subscales[definition["minuend"]] - subscales[definition["subtrahend"]]
    raw = sum(keyed(item_id) for item_id in item_ids) if scoring["type"] == "sum" else None
    result = {"rawScore": raw, "subscaleScores": subscales}
    multiplier = scoring.get("normalizedMultiplier")
    if raw is not None and multiplier is not None:
        normalized = raw * float(multiplier)
        result["normalizedScore"] = normalized
        if scoring.get("normalizedSubscaleId"):
            result["subscaleScores"][str(scoring["normalizedSubscaleId"])] = normalized
    return result


def score_instrument(instrument_id, responses, *, scoring_override=None):
    instrument = get_instrument(instrument_id)
    if scoring_override is not None and instrument.get("questionnaireMode") == "native" and not instrument.get("custom"):
        raise MentalHealthScoringError("Validated native questionnaires must use their registered scoring definition")
    scoring = scoring_override or instrument["scoring"]
    kind = scoring.get("type")
    if instrument.get("questionnaireMode") == "native" and instrument.get("questionTextStatus") in {"official", "official_translation"}:
        result = _score_registered_definition(instrument, responses)
    elif instrument_id == "cbi":
        result = score_cbi(responses)
    elif kind == "sum":
        result = _sum_score(responses, int(scoring["items"]))
    else:
        raise MentalHealthScoringError("This scoring definition requires an authorised versioned item/key pack")
    score = result.get("rawScore")
    if score is not None and instrument.get("scoreMin") is not None and instrument.get("scoreMax") is not None:
        if score < instrument["scoreMin"] or score > instrument["scoreMax"]:
            raise MentalHealthScoringError("Calculated score is outside the instrument range")
        span = instrument["scoreMax"] - instrument["scoreMin"]
        result.setdefault("normalizedScore", round((score - instrument["scoreMin"]) / span * 100, 2) if span else None)
    return result


def interpretation_for(instrument, score, responses=None):
    if score is None:
        return None
    interpretation = None
    for band in instrument.get("interpretationBands", []):
        if band["min"] <= score <= band["max"]:
            interpretation = {"label": band["label"], "diagnostic": False, "notices": []}
            break
    if responses and instrument.get("interpretationRules"):
        values = _registered_response_map(instrument, responses)
        notices = []
        for rule in instrument["interpretationRules"]:
            if rule["type"] == "any_item_lte" and any(values.get(str(item_id), float("inf")) <= float(rule["value"]) for item_id in rule["itemIds"]):
                notices.append(rule["label"])
        if notices:
            interpretation = interpretation or {"label": notices[0], "diagnostic": False, "notices": []}
            interpretation["notices"] = notices
    return interpretation
