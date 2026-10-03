"""Optional, versioned AI factual extraction for Job Hunt Pack F."""

from .base import (
    AIExtractionProvider,
    AIExtractionRequest,
    AIExtractionResponse,
    AIProviderError,
    UnavailableAIProvider,
    enabled,
    float_setting,
    integer_setting,
)
from .fake import FakeAIExtractionProvider
from .gemini import (
    GEMINI_ADAPTER_VERSION,
    GEMINI_ALLOWED_MODELS,
    GEMINI_DEFAULT_MODEL,
    GEMINI_PROVIDER_KEY,
    GeminiAIExtractionProvider,
)
from .prompt import (
    AI_EXTRACTOR_VERSION,
    PROMPT_ID,
    PROMPT_VERSION,
    RESPONSE_SCHEMA_VERSION,
    SYSTEM_PROMPT,
    build_user_prompt,
    prepare_source_text,
    prompt_fingerprint,
)
from .schema import (
    AI_RESPONSE_JSON_SCHEMA,
    AISchemaError,
    MAX_RAW_AI_RESPONSE_BYTES,
    ValidatedAIOutput,
    validate_ai_output,
)

__all__ = [
    "AI_EXTRACTOR_VERSION", "AI_RESPONSE_JSON_SCHEMA", "AIExtractionProvider",
    "AIExtractionRequest", "AIExtractionResponse", "AIProviderError", "AISchemaError",
    "FakeAIExtractionProvider", "GEMINI_ADAPTER_VERSION", "GEMINI_ALLOWED_MODELS",
    "GEMINI_DEFAULT_MODEL", "GEMINI_PROVIDER_KEY", "GeminiAIExtractionProvider",
    "MAX_RAW_AI_RESPONSE_BYTES", "PROMPT_ID", "PROMPT_VERSION", "RESPONSE_SCHEMA_VERSION",
    "SYSTEM_PROMPT", "UnavailableAIProvider", "ValidatedAIOutput", "build_user_prompt",
    "enabled", "float_setting", "integer_setting", "prepare_source_text",
    "prompt_fingerprint", "validate_ai_output",
]
