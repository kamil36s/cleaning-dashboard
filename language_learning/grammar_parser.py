"""Optional offline dependency analysis; never participates in canonical analysis."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import threading

from .errors import LanguageError
from .analysis.norwegian_bokmal import PROCESSOR_PACKAGES, DEPENDENCY_PACKAGES, _parse_morphology

PARSER_VERSION = "1.0.0"
GRAMMAR_PROCESSORS = {**PROCESSOR_PACKAGES, "depparse": "bokmaal_charlm"}


class GrammarParser:
    def __init__(self, *, model_dir=None, pipeline_factory=None):
        self.model_dir = model_dir
        self.pipeline_factory = pipeline_factory
        self.pipeline = None
        self.load_error = False
        self.lock = threading.RLock()

    def resources(self):
        """Read installed metadata, without importing Stanza/PyTorch or networking."""
        dist = importlib.metadata.distribution("stanza")
        version_file = Path(dist.locate_file("stanza/_version.py")).read_text(encoding="utf-8")
        version = re.search(r'__resources_version__\s*=\s*[\'"]([^\'"]+)', version_file).group(1)
        from platformdirs import user_cache_dir
        directory = Path(self.model_dir or os.environ.get("LANGUAGE_STANZA_MODEL_DIR")
                         or os.environ.get("STANZA_RESOURCES_DIR")
                         or Path(user_cache_dir("stanza", "StanfordNLP", version)) / "resources")
        manifest = json.loads((directory / "resources.json").read_text(encoding="utf-8"))
        selections = {**GRAMMAR_PROCESSORS, **DEPENDENCY_PACKAGES}
        rows = []
        for processor, package in selections.items():
            metadata = manifest.get("nb", {}).get(processor, {}).get(package)
            if not metadata or not (directory / "nb" / processor / (package + ".pt")).is_file():
                raise FileNotFoundError("Grammar model not provisioned")
            rows.append({"processor": processor, "package": package, "md5": metadata["md5"]})
        fingerprint = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
        return directory, {"parserId": "stanza-nb-dependencies", "parserVersion": PARSER_VERSION,
                           "packageVersion": dist.version, "resourceVersion": version,
                           "resources": rows, "fingerprint": fingerprint, "downloadMethod": "NONE"}

    def health(self):
        try:
            _, provenance = self.resources()
        except (FileNotFoundError, importlib.metadata.PackageNotFoundError):
            return {"state": "UNAVAILABLE", "reason": "MODEL_NOT_PROVISIONED", "downloadMethod": "NONE"}
        except Exception:
            return {"state": "UNAVAILABLE", "reason": "RESOURCE_MANIFEST_INVALID", "downloadMethod": "NONE"}
        return {"state": "UNAVAILABLE" if self.load_error else "AVAILABLE",
                "reason": "PARSER_INITIALIZATION_FAILED" if self.load_error else None,
                "loadVerified": self.pipeline is not None, "provenance": provenance}

    def parse(self, text):
        with self.lock:
            health = self.health()
            if health["state"] != "AVAILABLE" and health.get("reason") != "PARSER_INITIALIZATION_FAILED":
                raise LanguageError("Grammar parser unavailable: " + health["reason"], code=health["reason"], status=503)
            try:
                directory, provenance = self.resources()
                if self.pipeline is None:
                    import stanza
                    from stanza.pipeline.core import DownloadMethod
                    self.pipeline = (self.pipeline_factory or stanza.Pipeline)(
                        lang="nb", dir=str(directory), package=None, processors=dict(GRAMMAR_PROCESSORS),
                        download_method=DownloadMethod.NONE, use_gpu=False, verbose=False)
                self.load_error = False
            except Exception as exc:
                self.load_error = True
                raise LanguageError("Grammar parser could not initialize offline", code="PARSER_INITIALIZATION_FAILED", status=503) from exc
            try:
                document = self.pipeline(text)
                sentences = []
                for sentence in document.sentences:
                    tokens = []
                    for token in sentence.tokens:
                        if len(token.words) != 1:
                            raise LanguageError("Dependency token mapping diverged", code="TOKEN_MAPPING_DIVERGED")
                        word = token.words[0]
                        tokens.append({"start": token.start_char, "end": token.end_char, "surface": token.text,
                                       "index": word.id, "head": word.head, "relation": word.deprel,
                                       "pos": word.upos, "lemma": word.lemma, "morphology": _parse_morphology(word.feats)})
                    if tokens:
                        sentences.append({"start": tokens[0]["start"], "end": tokens[-1]["end"], "tokens": tokens})
                return {"sentences": sentences, "provenance": provenance}
            except LanguageError:
                raise
            except Exception as exc:
                raise LanguageError("Grammar dependency parsing failed", code="GRAMMAR_PARSE_FAILED") from exc


def map_canonical(parsed, snapshot):
    """Exact whole-document, sentence and one-to-one token mapping; no guessing."""
    raw = snapshot["document"]["raw_text"]
    sentences = snapshot["sentences"]
    tokens = snapshot["tokens"]
    grouped = {}
    for token in tokens:
        grouped.setdefault(token["sentence_id"], []).append(token)
    def diverged():
        raise LanguageError("Dependency token mapping diverged; no occurrences saved", code="TOKEN_MAPPING_DIVERGED")
    if len(sentences) != len(parsed["sentences"]):
        diverged()
    mapped = []
    seen = 0
    for sentence, dependency in zip(sentences, parsed["sentences"]):
        canonical = grouped.get(sentence["id"], [])
        if (sentence["source_start"], sentence["source_end"]) != (dependency["start"], dependency["end"]) or len(canonical) != len(dependency["tokens"]):
            diverged()
        if raw[dependency["start"]:dependency["end"]] != sentence["exact_text"]:
            diverged()
        result = []
        for index, (token, word) in enumerate(zip(canonical, dependency["tokens"]), 1):
            if (token["source_start"], token["source_end"], token["surface"]) != (word["start"], word["end"], word["surface"]):
                diverged()
            if raw[word["start"]:word["end"]] != word["surface"] or word["index"] != index or not isinstance(word["head"], int) or not 0 <= word["head"] <= len(canonical) or word["head"] == index:
                diverged()
            result.append({**word, "tokenId": token["id"], "tokenOrder": token["token_order"]})
            seen += 1
        mapped.append({"sentenceId": sentence["id"], "tokens": result})
    if seen != len(tokens):
        diverged()
    return mapped
