"""Versioned JSON Schema documents for manual Reading Guide imports."""

SCHEMA_VERSION = "1.0"

MEMORY_PROPERTIES = {
    key: {"oneOf": [{"type": "array"}, {"type": "object"}]}
    for key in (
        "concepts_explained", "concepts_developed", "arguments_explained",
        "historical_context_used", "important_connections", "open_threads",
        "resolved_threads", "terms_introduced",
    )
}

SECTION_COMMENTARY_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "synchrobook://reading-guide/section-commentary/1.0",
    "type": "object",
    "required": [
        "schema_version", "operation", "book_id", "commentary_set_id",
        "reading_profile_id", "section_id", "source_fingerprint",
        "section_guide", "commentary_chunks", "memory_update",
    ],
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "operation": {"const": "section_commentary"},
        "book_id": {"type": "string"},
        "commentary_set_id": {"type": "string"},
        "reading_profile_id": {"type": "string"},
        "section_id": {"type": "string"},
        "source_fingerprint": {"type": "string", "pattern": "^sha256:[a-f0-9]{64}$"},
        "source_normalization_version": {"type": "integer", "minimum": 1},
        "section_guide": {
            "type": "object",
            "required": ["before_reading", "section_summary", "section_terminology", "argument_map"],
            "properties": {
                "before_reading": {}, "section_summary": {},
                "section_terminology": {"type": "array"}, "argument_map": {},
            },
        },
        "commentary_chunks": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "start_source_id", "end_source_id", "title", "blocks"],
                "properties": {
                    "id": {"type": "string"}, "start_source_id": {"type": "string"},
                    "end_source_id": {"type": "string"}, "title": {"type": "string"},
                    "blocks": {
                        "type": "array",
                        "items": {
                            "type": "object", "required": ["type", "renderer"],
                            "properties": {"type": {"type": "string"}, "renderer": {"type": "string"}, "content": {"type": "string"}, "data": {}},
                            "oneOf": [{"required": ["content"], "not": {"required": ["data"]}}, {"required": ["data"], "not": {"required": ["content"]}}],
                        },
                    },
                },
            },
        },
        "memory_update": {"type": "object", "required": list(MEMORY_PROPERTIES), "properties": MEMORY_PROPERTIES},
    },
}

BOOK_ANALYSIS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "synchrobook://reading-guide/book-analysis/1.0",
    "type": "object",
    "required": ["schema_version", "operation", "book_id", "source_fingerprint", "book_intelligence"],
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION}, "operation": {"const": "book_analysis"},
        "book_id": {"type": "string"}, "source_fingerprint": {"type": "string", "pattern": "^sha256:[a-f0-9]{64}$"},
        "book_intelligence": {
            "type": "object",
            "required": ["overview", "structure", "major_arguments", "core_concepts", "important_cross_references", "reading_progression", "historical_context", "likely_difficulties", "global_glossary_seed"],
        },
    },
}

SCHEMAS = {"section_commentary": SECTION_COMMENTARY_SCHEMA, "book_analysis": BOOK_ANALYSIS_SCHEMA}
