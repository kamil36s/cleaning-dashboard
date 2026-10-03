"""EPUB sentence splitting and normalization used only for alignment."""

from __future__ import annotations

import re
import unicodedata


ABBREVIATIONS = {
    "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.", "vs.",
    "etc.", "e.g.", "i.e.", "np.", "itd.", "itp.", "ul.", "al.", "r.",
}

CONTRACTIONS = {
    "can't": "cannot", "cannot": "cannot", "couldn't": "could not",
    "didn't": "did not", "doesn't": "does not", "don't": "do not",
    "hadn't": "had not", "hasn't": "has not", "haven't": "have not",
    "isn't": "is not", "shouldn't": "should not", "wasn't": "was not",
    "weren't": "were not", "won't": "will not", "wouldn't": "would not",
    "i'm": "i am", "it's": "it is", "that's": "that is", "there's": "there is",
    "they're": "they are", "we're": "we are", "you're": "you are",
    "i've": "i have", "they've": "they have", "we've": "we have",
    "i'll": "i will", "they'll": "they will", "we'll": "we will",
}


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = text.translate(str.maketrans({"’": "'", "‘": "'", "`": "'", "´": "'"}))
    for contraction, expansion in CONTRACTIONS.items():
        text = re.sub(rf"(?<!\w){re.escape(contraction)}(?!\w)", expansion, text)
    text = "".join(
        character if character.isalnum() or character.isspace() else " "
        for character in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(character)
    )
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(value: str) -> list[str]:
    """Split prose while avoiding common abbreviation and decimal boundaries."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return []
    boundaries: list[int] = []
    for match in re.finditer(r"[.!?…]+(?:[\"'”’»）)\]]+)?(?=\s+|$)", text):
        end = match.end()
        fragment = text[:end].rstrip("\"'”’»）)]").split()[-1].casefold()
        if fragment in ABBREVIATIONS:
            continue
        if re.search(r"\b[A-Z]\.$", text[:end].rstrip("\"'”’»）)]")):
            continue
        if match.group().startswith(".") and end < len(text):
            previous = text[match.start() - 1] if match.start() else ""
            following = text[end + 1] if end + 1 < len(text) else ""
            if previous.isdigit() and following.isdigit():
                continue
        boundaries.append(end)
    output: list[str] = []
    start = 0
    for end in boundaries:
        sentence = text[start:end].strip()
        if sentence and normalize_text(sentence):
            output.append(sentence)
        start = end
        while start < len(text) and text[start].isspace():
            start += 1
    tail = text[start:].strip()
    if tail and normalize_text(tail):
        output.append(tail)
    return output
