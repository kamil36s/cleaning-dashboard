"""Versioned, deliberately conservative source POS mappings."""

from __future__ import annotations


ORDBANK_POS_MAPPING_VERSION = "ordbank-pos/v1"
ORDBANK_POS = {
    "adj": "ADJ",
    "adv": "ADV",
    "det": "DET",
    "fork": "ABBREVIATION",
    "henv": "REFERENCE",
    "inf": "PART",
    "interj": "INTJ",
    "konj": "CCONJ",
    "num": "NUM",
    "pref": "PREFIX",
    "prep": "ADP",
    "pron": "PRON",
    "sbu": "SCONJ",
    "subst": "NOUN",
    "symb": "SYM",
    "verb": "VERB",
}

KELLY_POS_MAPPING_VERSION = "kelly-pos/v1"
KELLY_POS = {
    "adj": "ADJ",
    "adv": "ADV",
    "conj": "CCONJ",
    "det": "DET",
    "interj": "INTJ",
    "n": "NOUN",
    "num": "NUM",
    "prep": "ADP",
    "pron": "PRON",
    "subj": "SCONJ",
    "v": "VERB",
}


def ordbank_tag_family(raw_tag: str) -> str:
    value = str(raw_tag or "").strip()
    return value.split(maxsplit=1)[0] if value else ""


def map_ordbank_family(family: str) -> str | None:
    return ORDBANK_POS.get(str(family or "").strip())


def map_kelly_pos(raw_pos: str) -> tuple[str, ...]:
    mapped = {
        KELLY_POS[item.strip()]
        for item in str(raw_pos or "").split(",")
        if item.strip() in KELLY_POS
    }
    return tuple(sorted(mapped))


__all__ = [
    "KELLY_POS_MAPPING_VERSION",
    "ORDBANK_POS_MAPPING_VERSION",
    "map_kelly_pos",
    "map_ordbank_family",
    "ordbank_tag_family",
]
