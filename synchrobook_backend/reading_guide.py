"""Provider-agnostic Reading Guide metadata for Synchrobook.

Generation targets are persisted separately from commentary chunks.  A target only
contains existing source sentence IDs; chunk boundaries enter the database solely
through a validated JSON import produced by an external LLM.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .reading_guide_schemas import SCHEMAS


ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = Path(os.environ.get("SYNCHROBOOK_DATA_DIR", ROOT / "data" / "synchrobook")).resolve()
BOOKS_ROOT = DATA_ROOT / "books"
DB_PATH = DATA_ROOT / "library.db"
SCHEMA_VERSION = "1.0"
SOURCE_NORMALIZATION_VERSION = 1
VALID_RENDERERS = {"prose", "short_note", "argument", "terminology", "references", "structured"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@contextmanager
def closing(connection):
    """Commit or roll back a SQLite transaction, then release its Windows handle."""
    try:
        with connection:
            yield connection
    finally:
        connection.close()


class ReadingGuideError(RuntimeError):
    def __init__(self, message: str, *, status: int = 400, code: str = "reading_guide_error", details=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.details = details

    def as_payload(self) -> dict:
        payload = {"ok": False, "error": str(self), "code": self.code}
        if self.details is not None:
            payload["details"] = self.details
        return payload


def _commentary_type(identifier, name, renderer, instruction, *, description="", scope="chunk", enabled=True, output_schema=None):
    return {
        "id": identifier, "name": name, "description": description or name,
        "generation_instruction": instruction, "default_renderer": renderer,
        "default_scope": scope, "enabled_by_default": enabled,
        "output_schema": output_schema,
    }


BUILTIN_COMMENTARY_TYPES = [
    _commentary_type("explanation", "Explanation", "prose", "Explain what the author is actually saying in this specific passage, preserving the author's conceptual distinctions and technical vocabulary. Focus on what is necessary to understand the passage at this point in the work. Do not merely paraphrase sentence by sentence. Explain relationships between claims, concepts and argumentative moves. Do not introduce later conclusions as though they had already been established."),
    _commentary_type("plain_language", "Plain Language", "prose", "Restate the central meaning of this passage in clear contemporary language for a reader who has understood the surrounding text but finds the present passage difficult. Prefer conceptual clarity over technical vocabulary, while explicitly preserving any distinction that would be lost by simplification. This is an explanatory simplification, not a replacement translation."),
    _commentary_type("argument_analysis", "Argument Analysis", "argument", "Reconstruct the argument made in this passage. Identify the relevant premises, inferential steps and conclusion. Include implicit premises only when they are genuinely required, and mark them as implicit. Distinguish between what follows formally from previously accepted premises and what depends on a controversial assumption. Do not invent a formal argument where the passage is not argumentative.", output_schema={"premises": [], "implicit_premises": [], "steps": [], "conclusion": "", "assessment_note": ""}),
    _commentary_type("watch_for", "Watch For", "short_note", "Identify the single most important non-obvious feature the reader should notice in this passage. This may be a conceptual shift, hidden assumption, unusual definition, change of meaning, argumentative dependency, ambiguity or move that becomes important later. Do not manufacture difficulty where none exists."),
    _commentary_type("terminology", "Terminology", "terminology", "Extract only technical, archaic, work-specific or conceptually important terms whose meaning materially helps understand this passage. Define each term in the sense relevant to the author and current work, not merely according to ordinary dictionary meaning. Do not repeat previously introduced terms unless this passage substantially changes, narrows or expands their meaning.", output_schema=[{"term": "", "definition": "", "development": "", "source_anchor_id": ""}]),
    _commentary_type("cross_reference", "Cross Reference", "references", "Identify earlier passages, definitions, arguments or concepts within the same work that are genuinely necessary or especially useful for understanding the current passage. Explain the relationship briefly. Prefer precise internal references. Do not create references merely because the topics are generally related.", output_schema=[{"reference": "", "relationship": ""}]),
    _commentary_type("historical_context", "Historical Context", "prose", "Provide historical, intellectual or philosophical context only where it materially improves understanding of this passage. Explain relevant debates, terminology, traditions, institutions or thinkers that the author is responding to. Keep context proportional to the passage and distinguish well-established historical context from interpretive reconstruction."),
    _commentary_type("importance", "Importance", "short_note", "Explain what functional role this passage plays in the larger work. State what it establishes, prepares, changes or makes possible. Use later parts of the work only to explain structural importance and avoid unnecessary spoilers."),
    _commentary_type("objection", "Possible Objection", "prose", "Present a strong and relevant objection to the reasoning or claim in the passage where such an objection genuinely exists. State the objection fairly and precisely. Do not automatically object to every passage. If no useful objection exists, omit this block."),
    _commentary_type("criticism", "Critical Commentary", "prose", "Provide concise critical analysis of the passage. Distinguish textual interpretation from evaluation. Identify weaknesses, ambiguities, contested assumptions or significant scholarly disputes where relevant. Do not treat disagreement as refutation and do not force a critical issue into every passage."),
    _commentary_type("example", "Example", "prose", "Give a concrete example that clarifies the concept or argument in this passage. The example should preserve the logical structure of the author's point rather than merely sharing the same topic. Clearly indicate if the example is modern and not the author's own."),
    _commentary_type("concept_map", "Concept Map", "structured", "Represent the conceptual relationships active in this passage. Include only concepts materially involved here and specify the relation between them.", output_schema={"nodes": [], "relations": [{"from": "", "relation": "", "to": ""}]}),
    _commentary_type("modern_english", "Modern English", "prose", "Rewrite the passage into clear contemporary English while preserving its meaning, logical structure and important distinctions. Do not summarize or add interpretation. Do not modernize technical terms when doing so would change the author's meaning; instead retain them and make the surrounding sentence clearer."),
    _commentary_type("literary_commentary", "Literary Commentary", "prose", "Explain literary features that materially shape the passage: narrative technique, structure, imagery, rhetoric, tone, voice, intertextuality or formal choices. Prioritize textual evidence. Do not reduce literary ambiguity to a single definitive interpretation."),
    _commentary_type("mythological_reference", "Mythological Reference", "references", "Identify mythological figures, stories or motifs that a contemporary reader may not recognize and that materially affect the meaning of the passage. Briefly explain the relevant tradition and why the reference matters here."),
    _commentary_type("biblical_reference", "Biblical Reference", "references", "Identify biblical references or allusions relevant to this passage. Explain the source and interpretive relevance concisely. Distinguish direct reference from probable or speculative allusion."),
    _commentary_type("symbolism", "Symbolism", "prose", "Identify significant symbolic structures or recurring symbols in the passage. Explain plausible meanings using the text and larger work as evidence. Where several interpretations remain viable, preserve that ambiguity instead of selecting one without justification."),
    _commentary_type("language_note", "Language Note", "short_note", "Explain a linguistic feature that materially affects understanding: archaic usage, unusual syntax, semantic shift, pun, ambiguity, original-language nuance, technical wording or rhetorical construction. Omit this block when there is no meaningful language issue."),
    _commentary_type("translation_note", "Translation Note", "prose", "Explain translation issues that materially affect interpretation of the passage. Where the original-language wording is known from supplied context, identify meaningful alternatives or losses in translation. Do not invent original-language claims when the necessary evidence is unavailable."),
    _commentary_type("paraphrase", "Paraphrase", "prose", "Give a faithful prose paraphrase of the passage while preserving its sequence and distinctions. Unlike Explanation, do not add substantial background interpretation. The purpose is to make the immediate textual meaning easier to follow."),
    _commentary_type("imagery", "Imagery", "prose", "Identify and explain important sensory, figurative or recurring imagery in the passage. Explain how the imagery functions rather than merely listing metaphors or images."),
    _commentary_type("theme", "Theme", "structured", "Identify themes materially developed by this passage and explain how the current passage develops, complicates or contrasts them. Avoid generic themes that could describe the entire work without specific relevance here.", output_schema=[{"theme": "", "development": ""}]),
    _commentary_type("character_reference", "Character Reference", "structured", "Provide only character information necessary to understand this passage at the current point in the work. Identify relationships, prior relevant actions and contextual significance. Do not reveal later developments unless explicitly allowed by the Reading Profile."),
]

SECTION_TYPES = {
    "before_reading": "Prepare the reader for the TARGET section without replacing the experience of reading it. Explain what the section is trying to accomplish, which previously introduced ideas are especially relevant, and what conceptual or argumentative features deserve attention. Give orientation rather than a full summary. Avoid unnecessary spoilers of conclusions that the section itself is meant to establish.",
    "section_summary": "Summarize what the section has actually established or developed. Distinguish central results from supporting steps. Explain how the section changes the reader's understanding of the work and how it connects to what came before. Do not simply list every subsection.",
    "section_terminology": "List technical or important terms introduced, substantially developed or used in a new way in this section. Do not duplicate terms merely because they occur again. For each term distinguish previous meaning from any new development where relevant.\n\nSuggested output:\n" + json.dumps([{"term": "", "definition": "", "development_in_section": ""}], indent=2),
    "argument_map": "Create a structural map of the section's reasoning. Show which major claims depend on which earlier claims and how the main conclusions are reached. This is a map of argumentative dependency, not a sentence-by-sentence summary.\n\nSuggested output:\n" + json.dumps({"nodes": [], "edges": [{"from": "", "relation": "supports|depends_on|contrasts|defines|develops", "to": ""}]}, indent=2),
}

BOOK_TYPES = {
    "book_map": "Create a compact structural and conceptual map of the entire work. Identify major divisions, central problems, argumentative progression, recurring concepts, important internal dependencies and places where the reader is likely to need special context. The result is intended to provide future section-level generation with global orientation, not to replace detailed commentary.\n\nDo not produce commentary for individual passages.",
    "global_glossary": "Maintain a work-specific glossary of important technical concepts. Definitions must reflect the author's usage in this work. Where a concept develops over the course of the work, preserve that development instead of collapsing it into one generic definition.",
    "concept_index": "Create an index of major concepts and their important occurrences or developments across the work. Focus on conceptual function and development rather than simple keyword frequency.",
    "argument_map": "Create a high-level dependency map of the major arguments in the work. Identify which major results depend on which definitions, assumptions or earlier conclusions. Keep this considerably more compact than section-level argument analysis.",
}

SPINOZA_INSTRUCTIONS = """You are guiding a careful first reading of Baruch Spinoza's Ethics.

Treat Spinoza's technical vocabulary according to his explicit definitions rather than ordinary-language meanings.

Track dependencies among Definitions, Axioms, Propositions, Demonstrations/Proofs, Corollaries, Scholia/Notes and other structural elements.

Explain what each important argument is doing within the architecture of the work.

When reconstructing an argument, distinguish:
- explicit premise,
- cited earlier proposition/definition/axiom,
- inferential step,
- conclusion.

Flag genuinely non-obvious or controversial transitions, especially when Spinoza moves between conceptual necessity, causal necessity and claims about existence.

Do not assume a proposition has been established before the reader reaches its proof.

Use later parts of the work for global orientation, but do not unnecessarily reveal later conclusions.

Use Cartesian, scholastic, theological or other historical context only when it materially improves understanding.

Avoid repeating the complete explanation of a technical term once Commentary Memory shows that it has already been introduced. Explain only new developments in its role or meaning.

The commentary should function as an intelligent philosophy tutor accompanying a first reading, not as a replacement for reading the primary text."""


def _default_memory() -> dict:
    return {key: [] for key in (
        "concepts_explained", "concepts_developed", "arguments_explained",
        "historical_context_used", "important_connections", "open_threads",
        "resolved_threads", "terms_introduced",
    )}


class ReadingGuideEngine:
    def _connect(self):
        connection = sqlite3.connect(DB_PATH, timeout=20)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 20000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS reading_guide_custom_types (
                    book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
                    id TEXT NOT NULL, data_json TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY (book_id, id)
                );
                CREATE TABLE IF NOT EXISTS reading_guide_profiles (
                    book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
                    id TEXT NOT NULL, data_json TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY (book_id, id)
                );
                CREATE TABLE IF NOT EXISTS reading_guide_sets (
                    id TEXT PRIMARY KEY, book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, profile_id TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}', source_fingerprint TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_reading_guide_active_set
                    ON reading_guide_sets(book_id) WHERE active=1;
                CREATE TABLE IF NOT EXISTS reading_guide_targets (
                    book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
                    set_id TEXT NOT NULL REFERENCES reading_guide_sets(id) ON DELETE CASCADE,
                    section_id TEXT NOT NULL, operation TEXT NOT NULL,
                    start_source_id TEXT, end_source_id TEXT,
                    source_fingerprint TEXT NOT NULL, normalization_version INTEGER NOT NULL,
                    source_ids_json TEXT NOT NULL, context_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (set_id, section_id, operation)
                );
                CREATE TABLE IF NOT EXISTS reading_guide_chunks (
                    set_id TEXT NOT NULL REFERENCES reading_guide_sets(id) ON DELETE CASCADE,
                    section_id TEXT NOT NULL, id TEXT NOT NULL,
                    start_source_id TEXT NOT NULL, end_source_id TEXT NOT NULL,
                    title TEXT NOT NULL, blocks_json TEXT NOT NULL, position INTEGER NOT NULL,
                    PRIMARY KEY (set_id, section_id, id)
                );
                CREATE INDEX IF NOT EXISTS idx_reading_guide_chunk_ranges
                    ON reading_guide_chunks(set_id, section_id, position);
                CREATE TABLE IF NOT EXISTS reading_guide_section_guides (
                    set_id TEXT NOT NULL REFERENCES reading_guide_sets(id) ON DELETE CASCADE,
                    section_id TEXT NOT NULL, data_json TEXT NOT NULL,
                    memory_update_json TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY (set_id, section_id)
                );
                CREATE TABLE IF NOT EXISTS reading_guide_memory (
                    set_id TEXT PRIMARY KEY REFERENCES reading_guide_sets(id) ON DELETE CASCADE,
                    data_json TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reading_guide_book_intelligence (
                    set_id TEXT PRIMARY KEY REFERENCES reading_guide_sets(id) ON DELETE CASCADE,
                    source_fingerprint TEXT NOT NULL, data_json TEXT NOT NULL, updated_at TEXT NOT NULL
                );
            """)

    @staticmethod
    def _validate_book_id(book_id: str) -> str:
        if not re.fullmatch(r"[a-f0-9]{32}", str(book_id or "")):
            raise ReadingGuideError("Invalid book identifier", status=404, code="not_found")
        return book_id

    @staticmethod
    def _identifier(value, label="identifier") -> str:
        value = str(value or "").strip()
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}", value):
            raise ReadingGuideError(f"Invalid {label}", code="invalid_identifier")
        return value

    def _book(self, book_id: str) -> dict:
        self._validate_book_id(book_id)
        path = BOOKS_ROOT / book_id / "text" / "book.json"
        if not path.is_file():
            raise ReadingGuideError("Book source is not available", status=404, code="book_source_missing")
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _source_units(book: dict) -> list[dict]:
        return [
            {
                "id": sentence["id"],
                "text": sentence.get("originalText") or sentence.get("text") or "",
                "chapterId": chapter["id"], "chapterTitle": chapter.get("title") or chapter["id"],
                "paragraphId": paragraph.get("id"), "heading": bool(paragraph.get("heading") or sentence.get("heading")),
            }
            for chapter in book.get("chapters", [])
            for paragraph in chapter.get("paragraphs", [])
            for sentence in paragraph.get("sentences", [])
            if sentence.get("id")
        ]

    @staticmethod
    def _normalized_source(units: list[dict]) -> str:
        rows = []
        for unit in units:
            text = unicodedata.normalize("NFC", str(unit.get("text") or "")).replace("\r\n", "\n").replace("\r", "\n")
            text = "\n".join(" ".join(line.split()) for line in text.split("\n")).strip()
            rows.append(f"[{unit['id']}]\n{text}")
        return "\n\n".join(rows)

    @classmethod
    def _fingerprint(cls, units: list[dict]) -> str:
        digest = hashlib.sha256(cls._normalized_source(units).encode("utf-8")).hexdigest()
        return f"sha256:{digest}"

    def _ensure_preset(self, book_id: str) -> None:
        profiles = [{
            "id": "guided-reading", "name": "Guided Reading", "description": "A general-purpose, spoiler-conscious reading guide.",
            "commentary_language": "Polish", "source_language": "unchanged",
            "enabled_chunk_types": ["explanation", "terminology", "watch_for", "importance"],
            "enabled_section_types": ["before_reading", "section_summary", "section_terminology"],
            "enabled_book_types": ["book_map", "global_glossary", "concept_index"],
            "type_order": ["explanation", "terminology", "watch_for", "importance"],
            "custom_global_instructions": "Guide a careful first reading. Keep the primary source central, distinguish explanation from interpretation, and avoid unnecessary spoilers.",
            "spoiler_policy": "first_reading", "context": "", "preset": True,
        }, {
            "id": "spinoza-guided-first-reading", "name": "Spinoza — Guided First Reading",
            "description": "Careful, spoiler-conscious first reading of Spinoza's Ethics.",
            "commentary_language": "Polish", "source_language": "unchanged",
            "enabled_chunk_types": ["explanation", "argument_analysis", "terminology", "watch_for", "cross_reference", "historical_context", "importance"],
            "enabled_section_types": ["before_reading", "section_summary", "section_terminology", "argument_map"],
            "enabled_book_types": ["book_map", "global_glossary", "concept_index", "argument_map"],
            "type_order": ["explanation", "argument_analysis", "terminology", "watch_for", "cross_reference", "historical_context", "importance"],
            "custom_global_instructions": SPINOZA_INSTRUCTIONS, "spoiler_policy": "first_reading", "context": "",
            "preset": True,
        }]
        with closing(self._connect()) as connection:
            for profile in profiles:
                exists = connection.execute("SELECT 1 FROM reading_guide_profiles WHERE book_id=? AND id=?", (book_id, profile["id"])).fetchone()
                if not exists:
                    connection.execute("INSERT INTO reading_guide_profiles VALUES (?, ?, ?, ?)", (book_id, profile["id"], json.dumps(profile, ensure_ascii=False), _now()))

    def _book_exists(self, connection, book_id):
        if not connection.execute("SELECT 1 FROM books WHERE id=?", (book_id,)).fetchone():
            raise ReadingGuideError("Book not found", status=404, code="not_found")

    @staticmethod
    def _json(row, key="data_json", fallback=None):
        return json.loads(row[key]) if row and row[key] else fallback

    def _types(self, book_id: str) -> list[dict]:
        with closing(self._connect()) as connection:
            custom = connection.execute("SELECT data_json FROM reading_guide_custom_types WHERE book_id=? ORDER BY id", (book_id,)).fetchall()
        return [{**row, "builtin": True} for row in BUILTIN_COMMENTARY_TYPES] + [{**self._json(row), "builtin": False} for row in custom]

    def _profile(self, book_id, profile_id) -> dict:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT data_json FROM reading_guide_profiles WHERE book_id=? AND id=?", (book_id, profile_id)).fetchone()
        if not row:
            raise ReadingGuideError("Reading profile not found", status=404, code="profile_not_found")
        return self._json(row)

    def _set(self, book_id, set_id) -> dict:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM reading_guide_sets WHERE book_id=? AND id=?", (book_id, set_id)).fetchone()
        if not row:
            raise ReadingGuideError("Commentary set not found", status=404, code="set_not_found")
        return dict(row)

    def state(self, book_id: str) -> dict:
        self.initialize(); self._validate_book_id(book_id)
        with closing(self._connect()) as connection:
            self._book_exists(connection, book_id)
        self._ensure_preset(book_id)
        with closing(self._connect()) as connection:
            profiles = [self._json(row) for row in connection.execute("SELECT data_json FROM reading_guide_profiles WHERE book_id=? ORDER BY updated_at, id", (book_id,))]
            sets = [dict(row) for row in connection.execute("SELECT * FROM reading_guide_sets WHERE book_id=? ORDER BY created_at", (book_id,))]
            active = next((row for row in sets if row["active"]), None)
            chunks = []
            guides = {}
            memory = _default_memory()
            intelligence = None
            targets = []
            if active:
                chunks = [{**dict(row), "blocks": json.loads(row["blocks_json"])} for row in connection.execute("SELECT * FROM reading_guide_chunks WHERE set_id=? ORDER BY section_id, position", (active["id"],))]
                for chunk in chunks:
                    chunk.pop("blocks_json", None)
                guides = {row["section_id"]: self._json(row) for row in connection.execute("SELECT section_id, data_json FROM reading_guide_section_guides WHERE set_id=?", (active["id"],))}
                memory = self._json(connection.execute("SELECT data_json FROM reading_guide_memory WHERE set_id=?", (active["id"],)).fetchone(), fallback=_default_memory())
                intelligence = self._json(connection.execute("SELECT data_json FROM reading_guide_book_intelligence WHERE set_id=?", (active["id"],)).fetchone())
                targets = [dict(row) for row in connection.execute("SELECT section_id, operation, start_source_id, end_source_id, source_fingerprint, normalization_version, created_at FROM reading_guide_targets WHERE set_id=?", (active["id"],))]
        for row in sets:
            row["active"] = bool(row["active"]); row["metadata"] = json.loads(row.pop("metadata_json") or "{}")
        return {
            "schemaVersion": SCHEMA_VERSION, "sourceNormalizationVersion": SOURCE_NORMALIZATION_VERSION,
            "sourceAnchorUnit": "sentence", "types": self._types(book_id), "sectionTypes": SECTION_TYPES,
            "bookTypes": BOOK_TYPES, "profiles": profiles, "sets": sets, "activeSetId": active["id"] if active else None,
            "schemas": SCHEMAS,
            "chunks": chunks, "sectionGuides": guides, "memory": memory,
            "bookIntelligence": intelligence, "glossary": self._glossary(chunks, guides, intelligence), "targets": targets,
        }

    def _save_type(self, book_id, data):
        identifier = self._identifier(data.get("id"), "commentary type ID")
        if identifier in {row["id"] for row in BUILTIN_COMMENTARY_TYPES}:
            raise ReadingGuideError("Built-in commentary types cannot be overwritten", code="builtin_type")
        renderer = data.get("default_renderer") or data.get("renderer") or "prose"
        scope = data.get("default_scope") or data.get("scope") or "chunk"
        if renderer not in VALID_RENDERERS or scope not in {"chunk", "section", "book"}:
            raise ReadingGuideError("Invalid commentary type renderer or scope", code="invalid_type")
        payload = {
            "id": identifier, "name": str(data.get("name") or identifier).strip(),
            "description": str(data.get("description") or "").strip(),
            "generation_instruction": str(data.get("generation_instruction") or data.get("instructions") or "").strip(),
            "custom_context": str(data.get("custom_context") or data.get("context") or ""),
            "default_scope": scope, "default_renderer": renderer,
            "enabled_by_default": data.get("enabled_by_default", data.get("enabled", True)) is not False,
            "output_schema": data.get("output_schema"),
        }
        if not payload["name"] or not payload["generation_instruction"]:
            raise ReadingGuideError("Type name and generation instructions are required", code="invalid_type")
        with closing(self._connect()) as connection:
            connection.execute("INSERT INTO reading_guide_custom_types VALUES (?, ?, ?, ?) ON CONFLICT(book_id,id) DO UPDATE SET data_json=excluded.data_json, updated_at=excluded.updated_at", (book_id, identifier, json.dumps(payload, ensure_ascii=False), _now()))
        return self.state(book_id)

    def _delete_type(self, book_id, identifier):
        identifier = self._identifier(identifier, "commentary type ID")
        with closing(self._connect()) as connection:
            referenced = connection.execute("SELECT blocks_json FROM reading_guide_chunks c JOIN reading_guide_sets s ON s.id=c.set_id WHERE s.book_id=?", (book_id,)).fetchall()
            count = sum(1 for row in referenced for block in json.loads(row["blocks_json"]) if block.get("type") == identifier)
            connection.execute("DELETE FROM reading_guide_custom_types WHERE book_id=? AND id=?", (book_id, identifier))
        result = self.state(book_id); result["preservedReferences"] = count
        return result

    def _save_profile(self, book_id, data):
        identifier = self._identifier(data.get("id") or uuid.uuid4().hex, "profile ID")
        definitions = self._types(book_id)
        chunk_types = {row["id"] for row in definitions if row["default_scope"] == "chunk"}
        section_types = set(SECTION_TYPES) | {row["id"] for row in definitions if not row.get("builtin") and row["default_scope"] == "section"}
        book_types = set(BOOK_TYPES) | {row["id"] for row in definitions if not row.get("builtin") and row["default_scope"] == "book"}
        chunks = [row for row in data.get("enabled_chunk_types", []) if row in chunk_types]
        order = [row for row in data.get("type_order", chunks) if row in chunks]
        order += [row for row in chunks if row not in order]
        payload = {
            "id": identifier, "name": str(data.get("name") or "Reading Profile").strip(),
            "description": str(data.get("description") or ""), "commentary_language": str(data.get("commentary_language") or "Polish"),
            "source_language": str(data.get("source_language") or "unchanged"),
            "enabled_chunk_types": chunks,
            "enabled_section_types": [row for row in data.get("enabled_section_types", []) if row in section_types],
            "enabled_book_types": [row for row in data.get("enabled_book_types", []) if row in book_types],
            "type_order": order, "custom_global_instructions": str(data.get("custom_global_instructions") or ""),
            "spoiler_policy": str(data.get("spoiler_policy") or "avoid_unnecessary"), "context": str(data.get("context") or ""),
            "preset": bool(data.get("preset", False)),
        }
        with closing(self._connect()) as connection:
            connection.execute("INSERT INTO reading_guide_profiles VALUES (?, ?, ?, ?) ON CONFLICT(book_id,id) DO UPDATE SET data_json=excluded.data_json, updated_at=excluded.updated_at", (book_id, identifier, json.dumps(payload, ensure_ascii=False), _now()))
        return self.state(book_id)

    def _delete_profile(self, book_id, identifier):
        identifier = self._identifier(identifier, "profile ID")
        with closing(self._connect()) as connection:
            if connection.execute("SELECT 1 FROM reading_guide_sets WHERE book_id=? AND profile_id=?", (book_id, identifier)).fetchone():
                raise ReadingGuideError("Profile is used by a commentary set", status=409, code="profile_in_use")
            connection.execute("DELETE FROM reading_guide_profiles WHERE book_id=? AND id=?", (book_id, identifier))
        return self.state(book_id)

    def _save_set(self, book_id, data, *, duplicate=False):
        source_id = data.get("id")
        if duplicate:
            source = self._set(book_id, source_id)
            identifier = uuid.uuid4().hex
            name = str(data.get("name") or f"{source['name']} — Copy")
            profile_id = source["profile_id"]
        else:
            identifier = self._identifier(source_id or uuid.uuid4().hex, "commentary set ID")
            name = str(data.get("name") or "Reading Guide").strip()
            profile_id = self._identifier(data.get("profile_id"), "profile ID")
            self._profile(book_id, profile_id)
        now = _now()
        with closing(self._connect()) as connection:
            conflicting = connection.execute("SELECT book_id FROM reading_guide_sets WHERE id=?", (identifier,)).fetchone()
            if conflicting and conflicting["book_id"] != book_id:
                raise ReadingGuideError("Commentary set ID is already used by another book", status=409, code="set_id_conflict")
            existing = connection.execute("SELECT 1 FROM reading_guide_sets WHERE book_id=?", (book_id,)).fetchone()
            connection.execute("INSERT INTO reading_guide_sets(id,book_id,name,profile_id,active,metadata_json,source_fingerprint,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,profile_id=excluded.profile_id,metadata_json=excluded.metadata_json,updated_at=excluded.updated_at", (identifier, book_id, name, profile_id, 0 if existing else 1, json.dumps(data.get("metadata") or {}, ensure_ascii=False), None, now, now))
            connection.execute("INSERT OR IGNORE INTO reading_guide_memory VALUES (?, ?, ?)", (identifier, json.dumps(_default_memory()), now))
            if duplicate:
                connection.execute(
                    "INSERT INTO reading_guide_chunks(set_id,section_id,id,start_source_id,end_source_id,title,blocks_json,position) SELECT ?,section_id,id,start_source_id,end_source_id,title,blocks_json,position FROM reading_guide_chunks WHERE set_id=?",
                    (identifier, source_id),
                )
                connection.execute(
                    "INSERT INTO reading_guide_section_guides(set_id,section_id,data_json,memory_update_json,updated_at) SELECT ?,section_id,data_json,memory_update_json,updated_at FROM reading_guide_section_guides WHERE set_id=?",
                    (identifier, source_id),
                )
                connection.execute(
                    "INSERT INTO reading_guide_targets(book_id,set_id,section_id,operation,start_source_id,end_source_id,source_fingerprint,normalization_version,source_ids_json,context_json,created_at) SELECT book_id,?,section_id,operation,start_source_id,end_source_id,source_fingerprint,normalization_version,source_ids_json,context_json,created_at FROM reading_guide_targets WHERE set_id=?",
                    (identifier, source_id),
                )
                for table, columns in (("reading_guide_memory", "data_json,updated_at"), ("reading_guide_book_intelligence", "source_fingerprint,data_json,updated_at")):
                    connection.execute(f"INSERT OR REPLACE INTO {table}(set_id,{columns}) SELECT ?,{columns} FROM {table} WHERE set_id=?", (identifier, source_id))
        return self.state(book_id)

    def _set_action(self, book_id, action, data):
        identifier = self._identifier(data.get("id"), "commentary set ID")
        self._set(book_id, identifier)
        with closing(self._connect()) as connection:
            if action == "activate_set":
                connection.execute("UPDATE reading_guide_sets SET active=0 WHERE book_id=?", (book_id,))
                connection.execute("UPDATE reading_guide_sets SET active=1,updated_at=? WHERE id=?", (_now(), identifier))
            elif action == "delete_set":
                was_active = connection.execute("SELECT active FROM reading_guide_sets WHERE id=?", (identifier,)).fetchone()["active"]
                connection.execute("DELETE FROM reading_guide_sets WHERE id=?", (identifier,))
                if was_active:
                    replacement = connection.execute("SELECT id FROM reading_guide_sets WHERE book_id=? ORDER BY created_at LIMIT 1", (book_id,)).fetchone()
                    if replacement: connection.execute("UPDATE reading_guide_sets SET active=1 WHERE id=?", (replacement["id"],))
        return self.state(book_id)

    @staticmethod
    def _target_stats(units):
        text = " ".join(row["text"] for row in units)
        characters = len(text); words = len(text.split()); tokens = round(characters / 4)
        size = "Small" if tokens < 2000 else "Good" if tokens < 6000 else "Large" if tokens < 12000 else "Very large"
        return {"characters": characters, "words": words, "estimatedTokens": tokens, "size": size, "warning": tokens >= 6000}

    def _select_target(self, book, data):
        units = self._source_units(book)
        if not units: raise ReadingGuideError("Book has no source sentences", code="empty_source")
        mode = data.get("mode") or "current_section"
        if mode in {"current_section", "selected_section"}:
            chapter_id = self._identifier(data.get("chapter_id"), "section ID")
            selected = [row for row in units if row["chapterId"] == chapter_id]
            section_id = chapter_id
        elif mode == "custom_range":
            lookup = {row["id"]: index for index, row in enumerate(units)}
            start, end = data.get("start_source_id"), data.get("end_source_id")
            if start not in lookup or end not in lookup or lookup[start] > lookup[end]:
                raise ReadingGuideError("Invalid custom source range", code="invalid_source_range")
            selected = units[lookup[start]:lookup[end] + 1]
            section_id = str(data.get("section_id") or f"range:{start}:{end}")
        else:
            raise ReadingGuideError("Unsupported generation mode", code="invalid_generation_mode")
        if not selected: raise ReadingGuideError("Selected section contains no source sentences", code="empty_target")
        return units, selected, section_id

    @staticmethod
    def _excerpt(units, maximum=1200):
        text = ReadingGuideEngine._normalized_source(units)
        return text if len(text) <= maximum else text[:maximum].rstrip() + "…"

    def _build_prompt(self, book_id, data):
        set_row = self._set(book_id, data.get("commentary_set_id"))
        profile_id = data.get("reading_profile_id") or set_row["profile_id"]
        profile = self._profile(book_id, profile_id)
        book = self._book(book_id); all_units = self._source_units(book)
        operation = "book_analysis" if data.get("mode") == "book_analysis" else "section_commentary"
        if operation == "book_analysis":
            selected = all_units; section_id = "book-analysis"
        else:
            all_units, selected, section_id = self._select_target(book, data)
        fingerprint = self._fingerprint(selected)
        start_index = all_units.index(selected[0]); end_index = all_units.index(selected[-1])
        previous_units = all_units[max(0, start_index - 8):start_index]
        next_units = all_units[end_index + 1:end_index + 9]
        with closing(self._connect()) as connection:
            memory = self._json(connection.execute("SELECT data_json FROM reading_guide_memory WHERE set_id=?", (set_row["id"],)).fetchone(), fallback=_default_memory())
            intelligence = self._json(connection.execute("SELECT data_json FROM reading_guide_book_intelligence WHERE set_id=?", (set_row["id"],)).fetchone(), fallback={})
            previous_section_id = all_units[start_index - 1]["chapterId"] if start_index else None
            source_order = {row["id"]: index for index, row in enumerate(all_units)}
            earlier_guides = []
            for row in connection.execute(
                """SELECT t.end_source_id, g.data_json
                   FROM reading_guide_targets t
                   JOIN reading_guide_section_guides g ON g.set_id=t.set_id AND g.section_id=t.section_id
                   WHERE t.set_id=? AND t.operation='section_commentary'""",
                (set_row["id"],),
            ):
                end = source_order.get(row["end_source_id"])
                if end is not None and end < start_index: earlier_guides.append((end, row))
            previous_guide = max(earlier_guides, key=lambda item: item[0])[1] if earlier_guides else (
                connection.execute("SELECT data_json FROM reading_guide_section_guides WHERE set_id=? AND section_id=?", (set_row["id"], previous_section_id)).fetchone()
                if previous_section_id else None
            )
        previous_summary = (self._json(previous_guide) or {}).get("section_summary") if previous_guide else None
        context = {
            "previous": {"sectionSummary": previous_summary, "endingExcerpt": self._excerpt(previous_units) if previous_units else None},
            "next": {"heading": next_units[0]["chapterTitle"] if next_units else None, "openingExcerpt": self._excerpt(next_units) if next_units else None},
            "bookIntelligenceIncluded": bool(intelligence), "memoryIncluded": True,
        }
        with closing(self._connect()) as connection:
            connection.execute("INSERT INTO reading_guide_targets VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(set_id,section_id,operation) DO UPDATE SET start_source_id=excluded.start_source_id,end_source_id=excluded.end_source_id,source_fingerprint=excluded.source_fingerprint,normalization_version=excluded.normalization_version,source_ids_json=excluded.source_ids_json,context_json=excluded.context_json,created_at=excluded.created_at", (book_id, set_row["id"], section_id, operation, selected[0]["id"], selected[-1]["id"], fingerprint, SOURCE_NORMALIZATION_VERSION, json.dumps([row["id"] for row in selected]), json.dumps(context, ensure_ascii=False), _now()))
        if operation == "book_analysis":
            prompt = self._book_prompt(book_id, book, profile, fingerprint, selected)
        else:
            prompt = self._section_prompt(book_id, book, set_row, profile, section_id, fingerprint, selected, memory, intelligence, context)
        return {"ok": True, "operation": operation, "sectionId": section_id, "sourceFingerprint": fingerprint, "sourceNormalizationVersion": SOURCE_NORMALIZATION_VERSION, "target": {"startSourceId": selected[0]["id"], "endSourceId": selected[-1]["id"], "sourceIds": [row["id"] for row in selected], **self._target_stats(selected)}, "context": context, "prompt": prompt}

    def _book_prompt(self, book_id, book, profile, fingerprint, units):
        metadata = json.dumps({"format": book.get("sourceFormat"), "language": book.get("language"), "extractionVersion": book.get("extractionVersion")}, ensure_ascii=False)
        registry = {row["id"]: row for row in self._types(book_id)}
        book_requests = []
        for identifier in profile.get("enabled_book_types", []):
            definition = registry.get(identifier, {})
            instruction = BOOK_TYPES.get(identifier) or definition.get("generation_instruction")
            if instruction:
                custom_context = definition.get("custom_context") or ""
                book_requests.append(f"TYPE: {identifier}\nINSTRUCTIONS:\n{instruction}\n\nOPTIONAL CUSTOM CONTEXT:\n{custom_context}")
        profile_instructions = profile.get("custom_global_instructions", "")
        if profile.get("context"): profile_instructions += "\n\nOPTIONAL PROFILE CONTEXT:\n" + profile["context"]
        if book_requests: profile_instructions += "\n\nENABLED BOOK-LEVEL CONTENT:\n\n" + "\n\n".join(book_requests)
        return f"""You are creating BOOK INTELLIGENCE for a synchronized reading application.

WORK:
{book.get('title', '')}
by {book.get('author', '')}

SOURCE VERSION:
{metadata}

READING PROFILE:
{profile['name']}

PROFILE-SPECIFIC INSTRUCTIONS:
{profile_instructions}

PURPOSE

Analyze the supplied work or supplied structural representation of the work in order to create compact global context for later section-by-section commentary generation.

Do NOT generate passage commentary.

The resulting BOOK INTELLIGENCE will be repeatedly supplied to another LLM while it comments on smaller TARGET sections.

Therefore prioritize:
- global structure,
- major arguments,
- conceptual progression,
- terminology,
- important internal dependencies,
- recurring problems,
- major historical/intellectual context,
- information necessary to avoid repetitive section commentary.

SOURCE:

{self._normalized_source(units)}

OUTPUT REQUIREMENTS

Return valid JSON only.

Use this structure:

{{
  "schema_version": "{SCHEMA_VERSION}",
  "operation": "book_analysis",
  "book_id": "{book_id}",
  "source_fingerprint": "{fingerprint}",
  "book_intelligence": {{
    "overview": "",
    "structure": [],
    "major_arguments": [],
    "core_concepts": [],
    "important_cross_references": [],
    "reading_progression": [],
    "historical_context": [],
    "likely_difficulties": [],
    "global_glossary_seed": []
  }}
}}

Keep BOOK INTELLIGENCE compact enough to be reused in later prompts.

Do not return markdown fences.
Do not return commentary outside JSON."""

    def _section_prompt(self, book_id, book, set_row, profile, section_id, fingerprint, units, memory, intelligence, context):
        types = {row["id"]: row for row in self._types(book_id)}
        ordered = profile.get("type_order") or profile.get("enabled_chunk_types") or []
        active_blocks = []
        for identifier in ordered:
            if identifier not in profile.get("enabled_chunk_types", []) or identifier not in types: continue
            row = types[identifier]
            active_blocks.append(f"TYPE:\n{row['id']}\n\nNAME:\n{row['name']}\n\nINSTRUCTIONS:\n{row['generation_instruction']}\n\nOUTPUT / RENDERER:\n{row['default_renderer']}\n\nOPTIONAL CUSTOM CONTEXT:\n{row.get('custom_context') or ''}\n\nOPTIONAL OUTPUT SCHEMA:\n{json.dumps(row.get('output_schema'), ensure_ascii=False, indent=2) if row.get('output_schema') is not None else ''}")
        section_rows = []
        for identifier in profile.get("enabled_section_types", []):
            definition = types.get(identifier, {})
            instruction = SECTION_TYPES.get(identifier) or definition.get("generation_instruction")
            if instruction:
                custom_context = definition.get("custom_context") or ""
                section_rows.append(f"TYPE: {identifier}\nINSTRUCTIONS:\n{instruction}\n\nOPTIONAL CUSTOM CONTEXT:\n{custom_context}")
        section_instructions = "\n\n".join(section_rows)
        metadata = json.dumps({"format": book.get("sourceFormat"), "language": book.get("language"), "extractionVersion": book.get("extractionVersion")}, ensure_ascii=False)
        previous = json.dumps(context["previous"], ensure_ascii=False, indent=2)
        following = json.dumps(context["next"], ensure_ascii=False, indent=2)
        return f"""You are generating a synchronized READING GUIDE for a specific passage of a book.

Your output will be imported directly into Synchrobook.

You must return VALID JSON ONLY.

==================================================
WORK
==================================================

Title:
{book.get('title', '')}

Author:
{book.get('author', '')}

Source/version:
{metadata}

Book ID:
{book_id}

Section ID:
{section_id}

Source fingerprint:
{fingerprint}

==================================================
READING PROFILE
==================================================

Profile:
{profile['name']}

Commentary language:
{profile.get('commentary_language', 'Polish')}

Profile instructions:

{profile.get('custom_global_instructions', '')}

Optional profile context:

{profile.get('context', '')}

==================================================
ACTIVE COMMENTARY TYPES
==================================================

For each enabled type, use the instructions below.

{chr(10).join(active_blocks)}

Only create a block of a given type where it adds useful information.

Do not generate empty filler blocks merely because a type is enabled.

==================================================
BOOK INTELLIGENCE — GLOBAL CONTEXT ONLY
==================================================

{json.dumps(intelligence, ensure_ascii=False, indent=2)}

This information exists only to orient you within the whole work.

Do not create commentary anchored to this context.

==================================================
COMMENTARY MEMORY — WHAT THE READER HAS ALREADY BEEN TAUGHT
==================================================

{json.dumps(memory, ensure_ascii=False, indent=2)}

Rules:

- Avoid repeating complete explanations already represented here.
- If the current passage develops a previously introduced concept, explain the NEW development.
- Refer back briefly when needed.
- Maintain conceptual continuity.
- Use open_threads to recognize issues that may now be resolved.
- Do not assume the reader remembers every detail, but avoid restarting the course from zero.

==================================================
PREVIOUS CONTEXT — CONTEXT ONLY
==================================================

{previous}

Use this only to understand continuity.

DO NOT create commentary chunks anchored to PREVIOUS CONTEXT.

==================================================
TARGET TEXT — GENERATE COMMENTARY ONLY FOR THIS
==================================================

{self._normalized_source(units)}

The TARGET is composed of ordered source units identified by IDs.

You MUST use these supplied source IDs when creating commentary boundaries.

YOU MUST NOT invent source IDs.

YOU MUST NOT use source IDs from PREVIOUS CONTEXT or NEXT CONTEXT as commentary anchors.

==================================================
NEXT CONTEXT — CONTEXT ONLY
==================================================

{following}

Use this to understand where the work is going and to avoid explanations that will immediately become misleading.

Do not generate commentary for NEXT CONTEXT.

Avoid unnecessary spoilers.

==================================================
TASK 1 — DETERMINE COMMENTARY CHUNKS
==================================================

Read the entire TARGET before deciding chunk boundaries.

Divide the TARGET into the smallest USEFUL LOGICAL UNITS for commentary.

Chunk boundaries must be semantic.

Good reasons to start a new commentary chunk include:

- a new argument begins,
- a new conceptual problem begins,
- the author shifts from proposition to substantial proof,
- a long proof contains several genuinely separate argumentative stages,
- a scholium/note changes subject,
- a new literary movement or image requires separate commentary,
- the commentary needed for the new passage would substantially differ from the previous one.

Bad reasons include:

- arbitrary token count,
- every paragraph,
- every sentence,
- mechanically every proposition,
- trying to create a fixed number of chunks.

A short proposition and proof may form one commentary chunk.

A long proposition, proof or note may require several.

Commentary chunks should normally cover the TARGET continuously without overlap.

Do not create tiny chunks when one coherent commentary unit is sufficient.

==================================================
TASK 2 — GENERATE COMMENTARY BLOCKS
==================================================

For each commentary chunk:

1. assign start_source_id,
2. assign end_source_id,
3. give it a concise title,
4. create useful blocks from ACTIVE COMMENTARY TYPES.

Do not mechanically generate every available commentary type for every chunk.

Generate only what materially helps.

==================================================
TASK 3 — SECTION GUIDE
==================================================

Generate enabled section-level content:

{section_instructions}

==================================================
TASK 4 — MEMORY UPDATE
==================================================

Create a compact memory_update describing what this section has now taught the reader.

Include:

concepts_explained
concepts_developed
arguments_explained
historical_context_used
important_connections
open_threads
resolved_threads
terms_introduced

Keep this concise.

This state will be supplied to the next generation request.

==================================================
GENERAL QUALITY RULES
==================================================

Do not merely summarize the source.

Preserve the distinction between:
- what the author says,
- explanation,
- historical context,
- interpretation,
- criticism.

Do not present interpretation as direct textual fact.

Do not manufacture controversy.

Do not manufacture historical context.

Do not repeat previously explained material unless required for the current argument.

Do not assume conclusions that have not yet been established at the reader's current position.

Use NEXT CONTEXT for orientation, not for unnecessary spoilers.

Commentary should help the reader continue reading the primary source rather than replace it.

==================================================
OUTPUT JSON
==================================================

Return:

{{
  "schema_version": "{SCHEMA_VERSION}",
  "operation": "section_commentary",
  "book_id": "{book_id}",
  "commentary_set_id": "{set_row['id']}",
  "reading_profile_id": "{profile['id']}",
  "section_id": "{section_id}",
  "source_fingerprint": "{fingerprint}",
  "source_normalization_version": {SOURCE_NORMALIZATION_VERSION},
  "section_guide": {{
    "before_reading": null,
    "section_summary": null,
    "section_terminology": [],
    "argument_map": null
  }},
  "commentary_chunks": [
    {{
      "id": "generated_unique_id",
      "start_source_id": "SOURCE_ID_FROM_TARGET",
      "end_source_id": "SOURCE_ID_FROM_TARGET",
      "title": "",
      "blocks": [{{"type": "explanation", "renderer": "prose", "content": ""}}]
    }}
  ],
  "memory_update": {{
    "concepts_explained": [], "concepts_developed": [], "arguments_explained": [],
    "historical_context_used": [], "important_connections": [], "open_threads": [],
    "resolved_threads": [], "terms_introduced": []
  }}
}}

Blocks may instead use "data" when required by their renderer/schema.

Every source ID used in start_source_id/end_source_id MUST exist in TARGET TEXT.

Return JSON only.

Do not wrap it in markdown.

Do not include explanatory text before or after the JSON."""

    @staticmethod
    def _merge_memory(current, update):
        merged = {**_default_memory(), **(current or {})}
        for key in _default_memory():
            old = merged.get(key, [])
            incoming = update.get(key, []) if isinstance(update, dict) else []
            if isinstance(old, dict) or isinstance(incoming, dict):
                base = old.copy() if isinstance(old, dict) else {}
                base.update(incoming if isinstance(incoming, dict) else {})
                merged[key] = base
                continue
            values, seen = [], set()
            for item in [*(old if isinstance(old, list) else []), *(incoming if isinstance(incoming, list) else [])]:
                marker = json.dumps(item, ensure_ascii=False, sort_keys=True)
                if marker not in seen: seen.add(marker); values.append(item)
            merged[key] = values
        resolved = {json.dumps(row, ensure_ascii=False, sort_keys=True) for row in merged.get("resolved_threads", [])}
        merged["open_threads"] = [row for row in merged.get("open_threads", []) if json.dumps(row, ensure_ascii=False, sort_keys=True) not in resolved]
        return merged

    def _validate_import(self, book_id, data, *, commit=False):
        raw = data.get("json")
        try: payload = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError as exc: return {"valid": False, "warnings": [], "errors": [f"Invalid JSON: {exc.msg}"]}
        errors, warnings = [], []
        if not isinstance(payload, dict): return {"valid": False, "warnings": [], "errors": ["Import root must be an object"]}
        operation = payload.get("operation")
        schema = SCHEMAS.get(operation)
        if schema:
            missing = [key for key in schema["required"] if key not in payload]
            if missing: errors.append(f"Import is missing required fields: {', '.join(missing)}")
        if payload.get("schema_version") != SCHEMA_VERSION: errors.append("Unsupported schema_version")
        if operation not in {"section_commentary", "book_analysis"}: errors.append("Unsupported operation")
        if payload.get("book_id") != book_id: errors.append("Import belongs to a different book")
        set_id = data.get("destination_set_id") or payload.get("commentary_set_id")
        try: set_row = self._set(book_id, set_id)
        except ReadingGuideError as exc: errors.append(str(exc)); set_row = None
        section_id = payload.get("section_id") if operation == "section_commentary" else "book-analysis"
        target = None
        if set_row and operation in {"section_commentary", "book_analysis"}:
            with closing(self._connect()) as connection:
                target = connection.execute("SELECT * FROM reading_guide_targets WHERE set_id=? AND section_id=? AND operation=?", (set_id, section_id, operation)).fetchone()
            if not target: errors.append("No matching generated target exists; generate the prompt first")
        if target and payload.get("source_fingerprint") != target["source_fingerprint"]:
            errors.append("Commentary was generated for a different version of this source text.")
        if target and payload.get("source_normalization_version") is not None and payload.get("source_normalization_version") != target["normalization_version"]:
            errors.append("Unsupported source normalization version")
        current_by_id = {}
        current_by_id = {}
        if target:
            current_by_id = {row["id"]: row for row in self._source_units(self._book(book_id))}
            target_ids = json.loads(target["source_ids_json"])
            if any(identifier not in current_by_id for identifier in target_ids):
                errors.append("One or more TARGET source IDs no longer exist")
            else:
                current_target = [current_by_id[identifier] for identifier in target_ids]
                if self._fingerprint(current_target) != target["source_fingerprint"]:
                    errors.append("Commentary was generated for a different version of this source text.")
        if operation == "book_analysis":
            intelligence = payload.get("book_intelligence")
            if not isinstance(intelligence, dict): errors.append("book_intelligence must be an object")
            elif schema:
                required = schema["properties"]["book_intelligence"].get("required", [])
                missing = [key for key in required if key not in intelligence]
                if missing: errors.append(f"book_intelligence is missing: {', '.join(missing)}")
        elif operation == "section_commentary":
            if set_row and payload.get("reading_profile_id") != set_row["profile_id"]: errors.append("Import uses a different reading profile")
            source_ids = json.loads(target["source_ids_json"]) if target else []
            positions = {identifier: index for index, identifier in enumerate(source_ids)}
            chunks = payload.get("commentary_chunks")
            if not isinstance(chunks, list): errors.append("commentary_chunks must be an array"); chunks = []
            type_map = {row["id"]: row for row in self._types(book_id)}
            seen_ids, previous_end, imported_ranges = set(), -1, []
            for index, chunk in enumerate(chunks):
                label = f"commentary_chunks[{index}]"
                if not isinstance(chunk, dict): errors.append(f"{label} must be an object"); continue
                chunk_id, start, end = chunk.get("id"), chunk.get("start_source_id"), chunk.get("end_source_id")
                missing = [key for key in ("id", "start_source_id", "end_source_id", "title", "blocks") if key not in chunk]
                if missing: errors.append(f"{label} is missing: {', '.join(missing)}")
                if not chunk_id or chunk_id in seen_ids: errors.append(f"{label}.id must be present and unique")
                seen_ids.add(chunk_id)
                if start not in positions or end not in positions:
                    supplied = [identifier for identifier in (start, end) if identifier not in positions]
                    invalid = [identifier for identifier in supplied if identifier not in current_by_id]
                    if invalid: errors.append(f"{label} uses a source ID that does not exist: {', '.join(map(str, invalid))}")
                    else: errors.append(f"{label} uses a source ID outside TARGET")
                    continue
                if positions[start] > positions[end]: errors.append(f"{label} has a reversed range")
                if positions[start] <= previous_end: errors.append(f"{label} overlaps or is out of order")
                previous_end = max(previous_end, positions[end])
                imported_ranges.append((str(chunk_id), start, end))
                if not isinstance(chunk.get("title"), str): errors.append(f"{label}.title must be a string")
                blocks = chunk.get("blocks")
                if not isinstance(blocks, list): errors.append(f"{label}.blocks must be an array"); continue
                for block_index, block in enumerate(blocks):
                    block_label = f"{label}.blocks[{block_index}]"
                    if not isinstance(block, dict): errors.append(f"{block_label} must be an object"); continue
                    definition = type_map.get(block.get("type"))
                    if not definition: errors.append(f"{block_label} has an unknown commentary type")
                    if block.get("renderer") not in VALID_RENDERERS: errors.append(f"{block_label} has an invalid renderer")
                    has_content, has_data = "content" in block, "data" in block
                    if has_content == has_data: errors.append(f"{block_label} must contain exactly one of content or data")
                    if has_content and not isinstance(block.get("content"), str): errors.append(f"{block_label}.content must be a string")
            if set_row and target:
                current_units = self._source_units(self._book(book_id))
                global_positions = {row["id"]: index for index, row in enumerate(current_units)}
                with closing(self._connect()) as connection:
                    existing_chunks = connection.execute("SELECT id,start_source_id,end_source_id FROM reading_guide_chunks WHERE set_id=? AND section_id<>?", (set_id, section_id)).fetchall()
                existing_ids = {row["id"] for row in existing_chunks}
                for chunk_id, start, end in imported_ranges:
                    if chunk_id in existing_ids: errors.append(f"Commentary chunk ID {chunk_id} already exists in this set")
                    if start not in global_positions or end not in global_positions: continue
                    left, right = global_positions[start], global_positions[end]
                    for existing in existing_chunks:
                        if existing["start_source_id"] not in global_positions or existing["end_source_id"] not in global_positions: continue
                        other_left, other_right = global_positions[existing["start_source_id"]], global_positions[existing["end_source_id"]]
                        if left <= other_right and other_left <= right:
                            errors.append(f"Commentary chunk {chunk_id} overlaps imported chunk {existing['id']} from another target")
                            break
            guide = payload.get("section_guide")
            if not isinstance(guide, dict): errors.append("section_guide must be an object")
            else:
                required_guide = {"before_reading", "section_summary", "section_terminology", "argument_map"}
                missing_guide = required_guide.difference(guide)
                if missing_guide: errors.append(f"section_guide is missing: {', '.join(sorted(missing_guide))}")
                if not isinstance(guide.get("section_terminology"), list): errors.append("section_guide.section_terminology must be an array")
            memory_update = payload.get("memory_update")
            if not isinstance(memory_update, dict): errors.append("memory_update must be an object")
            else:
                for key in _default_memory():
                    if key not in memory_update or not isinstance(memory_update[key], (list, dict)): errors.append(f"memory_update.{key} must be an array or object")
            if chunks and target and positions.get(chunks[0].get("start_source_id"), 0) > 0: warnings.append("Commentary does not cover the beginning of TARGET")
            if chunks and target and positions.get(chunks[-1].get("end_source_id"), -1) < len(source_ids) - 1: warnings.append("Commentary does not cover the end of TARGET")
        result = {"valid": not errors, "warnings": warnings, "errors": errors, "operation": operation, "sectionId": section_id}
        if errors or not commit: return result
        now = _now()
        with closing(self._connect()) as connection:
            if operation == "book_analysis":
                connection.execute("INSERT INTO reading_guide_book_intelligence VALUES (?,?,?,?) ON CONFLICT(set_id) DO UPDATE SET source_fingerprint=excluded.source_fingerprint,data_json=excluded.data_json,updated_at=excluded.updated_at", (set_id, payload["source_fingerprint"], json.dumps(payload["book_intelligence"], ensure_ascii=False), now))
            else:
                connection.execute("DELETE FROM reading_guide_chunks WHERE set_id=? AND section_id=?", (set_id, section_id))
                for position, chunk in enumerate(payload["commentary_chunks"]):
                    connection.execute("INSERT INTO reading_guide_chunks VALUES (?,?,?,?,?,?,?,?)", (set_id, section_id, str(chunk["id"]), chunk["start_source_id"], chunk["end_source_id"], chunk["title"], json.dumps(chunk["blocks"], ensure_ascii=False), position))
                connection.execute("INSERT INTO reading_guide_section_guides VALUES (?,?,?,?,?) ON CONFLICT(set_id,section_id) DO UPDATE SET data_json=excluded.data_json,memory_update_json=excluded.memory_update_json,updated_at=excluded.updated_at", (set_id, section_id, json.dumps(payload["section_guide"], ensure_ascii=False), json.dumps(payload["memory_update"], ensure_ascii=False), now))
                current = self._json(connection.execute("SELECT data_json FROM reading_guide_memory WHERE set_id=?", (set_id,)).fetchone(), fallback=_default_memory())
                merged = self._merge_memory(current, payload["memory_update"])
                connection.execute("INSERT INTO reading_guide_memory VALUES (?,?,?) ON CONFLICT(set_id) DO UPDATE SET data_json=excluded.data_json,updated_at=excluded.updated_at", (set_id, json.dumps(merged, ensure_ascii=False), now))
            connection.execute("UPDATE reading_guide_sets SET source_fingerprint=?,updated_at=? WHERE id=?", (payload["source_fingerprint"], now, set_id))
        result["imported"] = True
        return {**result, "state": self.state(book_id)}

    @staticmethod
    def _glossary(chunks, guides, intelligence=None):
        terms = {}
        def add(item, occurrence, set_id=None):
            if not isinstance(item, dict) or not str(item.get("term") or "").strip(): return
            key = str(item["term"]).strip().casefold(); current = terms.get(key)
            definition = item.get("definition") or ""; development = item.get("development") or item.get("development_in_section") or ""
            if not current:
                current = {"term": item["term"], "definition": definition, "firstOccurrence": occurrence, "latestDevelopment": development, "importantOccurrences": [], "commentarySetId": set_id}
                terms[key] = current
            if definition: current["definition"] = definition
            if development: current["latestDevelopment"] = development
            if occurrence not in current["importantOccurrences"]: current["importantOccurrences"].append(occurrence)
        for chunk in chunks:
            for block in chunk.get("blocks", []):
                if block.get("type") == "terminology" and isinstance(block.get("data"), list):
                    for item in block["data"]: add(item, item.get("source_anchor_id") or chunk["start_source_id"], chunk.get("set_id"))
        for section_id, guide in guides.items():
            for item in guide.get("section_terminology") or []: add(item, section_id)
        for item in (intelligence or {}).get("global_glossary_seed") or []: add(item, "book")
        return sorted(terms.values(), key=lambda row: row["term"].casefold())

    def _memory_action(self, book_id, action, data):
        set_row = self._set(book_id, data.get("commentary_set_id")); set_id = set_row["id"]
        with closing(self._connect()) as connection:
            if action == "save_memory": memory = data.get("memory")
            elif action == "reset_memory": memory = _default_memory()
            else:
                memory = _default_memory()
                for row in connection.execute("SELECT memory_update_json FROM reading_guide_section_guides WHERE set_id=? ORDER BY updated_at, section_id", (set_id,)):
                    memory = self._merge_memory(memory, json.loads(row["memory_update_json"]))
            if not isinstance(memory, dict): raise ReadingGuideError("Memory must be an object", code="invalid_memory")
            connection.execute("INSERT INTO reading_guide_memory VALUES (?,?,?) ON CONFLICT(set_id) DO UPDATE SET data_json=excluded.data_json,updated_at=excluded.updated_at", (set_id, json.dumps(memory, ensure_ascii=False), _now()))
        return self.state(book_id)

    def execute(self, book_id: str, payload: dict) -> dict:
        self.initialize(); self._validate_book_id(book_id)
        if not isinstance(payload, dict): raise ReadingGuideError("Request must be a JSON object", code="invalid_request")
        with closing(self._connect()) as connection: self._book_exists(connection, book_id)
        self._ensure_preset(book_id)
        action = payload.get("action"); data = payload.get("data") or {}
        if action == "save_type": return self._save_type(book_id, data)
        if action == "delete_type": return self._delete_type(book_id, data.get("id"))
        if action == "save_profile": return self._save_profile(book_id, data)
        if action == "duplicate_profile":
            profile = self._profile(book_id, data.get("id")); profile.update({"id": uuid.uuid4().hex, "name": data.get("name") or f"{profile['name']} — Copy", "preset": False}); return self._save_profile(book_id, profile)
        if action == "delete_profile": return self._delete_profile(book_id, data.get("id"))
        if action == "save_set": return self._save_set(book_id, data)
        if action == "duplicate_set": return self._save_set(book_id, data, duplicate=True)
        if action in {"activate_set", "delete_set"}: return self._set_action(book_id, action, data)
        if action == "build_prompt": return self._build_prompt(book_id, data)
        if action == "validate_import": return self._validate_import(book_id, data, commit=False)
        if action == "import_json": return self._validate_import(book_id, data, commit=True)
        if action in {"save_memory", "reset_memory", "rebuild_memory"}: return self._memory_action(book_id, action, data)
        raise ReadingGuideError("Unsupported Reading Guide action", code="unsupported_action")


READING_GUIDE = ReadingGuideEngine()
