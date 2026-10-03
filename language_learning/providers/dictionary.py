"""Bounded read-only access to the official Ordbøkene Display API."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
import json
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PROVIDER_ID = "ORDBOKENE_BOKMALSORDBOKA"
PROVIDER_VERSION = "live-display-api/v1"
LICENSE_ID = "CC-BY-4.0"
ATTRIBUTION = "Bokmålsordboka/Nynorskordboka, Universitetet i Bergen og Språkrådet, ordbøkene.no, CC-BY 4.0."
SOURCE_URL = "https://ordbokene.no/"
PRIMARY_BASE = "https://oda.uib.no/opal/prod"
FALLBACK_BASE = "https://odd.uib.no/opal/prod"


class DictionaryProviderError(RuntimeError):
    """Safe provider failure surfaced as an unavailable lexical section."""


@dataclass(frozen=True)
class ProviderLimits:
    timeout_seconds: float = 3.0
    max_response_bytes: int = 768 * 1024
    max_articles: int = 6
    max_senses: int = 16
    max_examples_per_sense: int = 5
    max_relations: int = 16


def _bounded_text(value: Any, maximum: int = 4000) -> str:
    return " ".join(str(value or "").split())[:maximum]


def _item_label(item: dict[str, Any]) -> str:
    if item.get("type_") == "article_ref":
        lemmas = item.get("lemmas") or []
        return _bounded_text((lemmas[0] if lemmas else {}).get("lemma"), 300)
    return _bounded_text(item.get("text") or item.get("id") or item.get("content"), 300)


def _render_content(value: Any, items: Any) -> str:
    text = str(value or "")
    for item in items if isinstance(items, list) else []:
        text = text.replace("$", _item_label(item), 1)
    return _bounded_text(text)


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


class OrdbokeneDictionaryProvider:
    """A display-only provider. It never receives a store or mutates user state."""

    def __init__(
        self,
        *,
        limits: ProviderLimits | None = None,
        fetch_json: Callable[[str], Any] | None = None,
    ):
        self.limits = limits or ProviderLimits()
        self._fetch_json_override = fetch_json

    def health(self) -> dict[str, Any]:
        return {
            "id": PROVIDER_ID,
            "version": PROVIDER_VERSION,
            "configured": True,
            "availability": "ON_DEMAND",
            "runtimeOnly": True,
            "cache": {"enabled": False, "reason": "DISPLAY_ONLY_MINIMAL_DATA_POLICY"},
            "license": LICENSE_ID,
            "sourceUrl": SOURCE_URL,
            "attribution": ATTRIBUTION,
            "limits": {
                "timeoutSeconds": self.limits.timeout_seconds,
                "maxResponseBytes": self.limits.max_response_bytes,
                "maxArticles": self.limits.max_articles,
                "maxSenses": self.limits.max_senses,
            },
        }

    def _fetch_json(self, url: str) -> Any:
        if self._fetch_json_override is not None:
            return self._fetch_json_override(url)
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "cleaning-dashboard-language/7.7"})
        try:
            with urlopen(request, timeout=self.limits.timeout_seconds) as response:
                declared = response.headers.get("Content-Length")
                if declared and int(declared) > self.limits.max_response_bytes:
                    raise DictionaryProviderError("Dictionary response exceeded the configured size limit")
                payload = response.read(self.limits.max_response_bytes + 1)
        except DictionaryProviderError:
            raise
        except Exception as exc:
            raise DictionaryProviderError("Dictionary provider is unavailable") from exc
        if len(payload) > self.limits.max_response_bytes:
            raise DictionaryProviderError("Dictionary response exceeded the configured size limit")
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DictionaryProviderError("Dictionary provider returned invalid data") from exc

    def _search(self, base: str, lemma: str) -> list[int]:
        query = urlencode({"w": lemma, "dict": "bm", "scope": "e"})
        payload = self._fetch_json(f"{base}/api/articles?{query}")
        raw_ids = ((payload or {}).get("articles") or {}).get("bm") or []
        return [int(item) for item in raw_ids[: self.limits.max_articles] if str(item).isdigit()]

    def _article(self, base: str, article_id: int) -> dict[str, Any]:
        payload = self._fetch_json(f"{base}/bm/article/{article_id}.json")
        if not isinstance(payload, dict):
            raise DictionaryProviderError("Dictionary provider returned an invalid article")
        return payload

    @staticmethod
    def _pos(article: dict[str, Any]) -> list[str]:
        values: list[str] = []
        for lemma in article.get("lemmas") or []:
            for paradigm in lemma.get("paradigm_info") or []:
                for tag in paradigm.get("tags") or []:
                    tag = str(tag).upper()
                    if tag in {"NOUN", "VERB", "ADJ", "ADV", "PRON", "DET", "ADP", "CCONJ", "SCONJ", "INTJ", "NUM", "PROPN"} and tag not in values:
                        values.append(tag)
        return values

    def _parse_article(self, article: dict[str, Any]) -> dict[str, Any]:
        article_id = str(article.get("article_id") or "")
        lemmas = []
        forms: list[dict[str, Any]] = []
        for lemma in article.get("lemmas") or []:
            label = _bounded_text(lemma.get("lemma"), 300)
            if label and label not in lemmas:
                lemmas.append(label)
            for paradigm in lemma.get("paradigm_info") or []:
                for inflection in paradigm.get("inflection") or []:
                    word = _bounded_text(inflection.get("word_form"), 300)
                    if word and not any(item["form"] == word for item in forms):
                        forms.append({"form": word, "tags": [_bounded_text(tag, 80) for tag in (inflection.get("tags") or [])[:8]]})

        senses: list[dict[str, Any]] = []
        for item in _walk((article.get("body") or {}).get("definitions") or []):
            if item.get("type_") != "definition" or item.get("id") is None:
                continue
            elements = item.get("elements") or []
            explanations = [child for child in elements if isinstance(child, dict) and child.get("type_") == "explanation"]
            if not explanations:
                continue
            definition = _render_content(explanations[0].get("content"), explanations[0].get("items"))
            if not definition:
                continue
            examples = []
            labels = []
            relations = []
            for child in _walk(elements):
                kind = child.get("type_")
                if kind == "example":
                    quote = child.get("quote") or {}
                    rendered = _render_content(quote.get("content"), quote.get("items"))
                    if rendered and rendered not in examples:
                        examples.append(rendered)
                elif kind == "usage":
                    rendered = _bounded_text(child.get("text") or child.get("content"), 200)
                    if rendered and rendered not in labels:
                        labels.append(rendered)
                elif kind == "article_ref":
                    label = _item_label(child)
                    if label and not any(relation["term"] == label for relation in relations):
                        relations.append({"type": "ARTICLE_REFERENCE", "term": label, "articleId": str(child.get("article_id") or "")})
            senses.append({
                "senseId": f"{article_id}:{item.get('id')}",
                "sourceLocalId": str(item.get("id")),
                "order": len(senses) + 1,
                "definition": definition,
                "examples": examples[: self.limits.max_examples_per_sense],
                "usageLabels": labels[:8],
                "relations": relations[: self.limits.max_relations],
                "translations": [],
            })
            if len(senses) >= self.limits.max_senses:
                break

        pronunciations = []
        for item in _walk((article.get("body") or {}).get("pronunciation") or []):
            value = _bounded_text(item.get("content") or item.get("text") or item.get("pronunciation"), 300)
            if value and value not in pronunciations:
                pronunciations.append(value)
        return {
            "articleId": article_id,
            "sourceVersion": f"article-updated:{_bounded_text(article.get('updated'), 80) or 'unknown'}",
            "lemmas": lemmas[:8],
            "partsOfSpeech": self._pos(article),
            "forms": forms[:40],
            "senses": senses,
            "pronunciations": pronunciations[:8],
        }

    def lookup_lemma(self, lemma: str, part_of_speech: str | None = None) -> dict[str, Any]:
        requested = _bounded_text(lemma, 300)
        if not requested:
            raise DictionaryProviderError("Dictionary lookup requires a lemma")
        base = PRIMARY_BASE
        try:
            article_ids = self._search(base, requested)
        except DictionaryProviderError:
            base = FALLBACK_BASE
            article_ids = self._search(base, requested)
        articles: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=min(4, max(1, len(article_ids)))) as executor:
            futures = {executor.submit(self._article, base, article_id): article_id for article_id in article_ids}
            for future in as_completed(futures):
                try:
                    articles.append(self._parse_article(future.result()))
                except DictionaryProviderError:
                    continue
        articles.sort(key=lambda item: int(item["articleId"]) if item["articleId"].isdigit() else 0)
        exact = [item for item in articles if any(value.casefold() == requested.casefold() for value in item["lemmas"])]
        candidates = exact or articles
        requested_pos = str(part_of_speech or "").upper()
        matching = [item for item in candidates if not requested_pos or requested_pos in item["partsOfSpeech"]]
        mismatch = bool(requested_pos and candidates and not matching)
        selected = matching if matching else ([] if mismatch else candidates)
        public = {
            "available": True,
            "lookupStatus": "POS_MISMATCH" if mismatch else "MATCHED" if selected else "NO_MATCH",
            "requestedLemma": requested,
            "requestedPartOfSpeech": requested_pos or None,
            "ambiguous": len(selected) > 1,
            "articles": selected,
            "provider": self.health(),
            "retrieval": {"mode": "LIVE_NO_CACHE", "endpointRole": "OFFICIAL_DISPLAY_API"},
        }
        public["contentFingerprint"] = hashlib.sha256(
            json.dumps(public["articles"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return public


__all__ = [
    "ATTRIBUTION", "DictionaryProviderError", "LICENSE_ID", "OrdbokeneDictionaryProvider",
    "PROVIDER_ID", "PROVIDER_VERSION", "ProviderLimits", "SOURCE_URL",
]
