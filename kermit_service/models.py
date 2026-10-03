"""Narrow public wire contracts; no retrieval controls are accepted."""

from pathlib import PurePosixPath


MAX_BODY_BYTES = 2048
MAX_QUESTION_CHARS = 500
REQUEST_KEYS = {"contractVersion", "question", "profile", "allowMemoryPressure"}
CHAT_BODY_BYTES = 16384
CHAT_KEYS = {"contractVersion", "message", "profile", "history", "conversationState", "allowMemoryPressure"}
MAX_HISTORY_ITEMS = 12
MAX_HISTORY_CHARS = 3000
RESOURCE_KEYS = ("availableMb", "minimumMb", "recommendedMb",
                 "deficitToMinimumMb", "deficitToRecommendedMb", "modelResident")


def parse_ask(payload, profiles):
    if not isinstance(payload, dict) or set(payload) - REQUEST_KEYS:
        raise ValueError("unsupported request field")
    if payload.get("contractVersion") != 1 or type(payload.get("contractVersion")) is not int:
        raise ValueError("unsupported contract version")
    question = payload.get("question")
    if not isinstance(question, str) or not question.strip() or len(question) > MAX_QUESTION_CHARS or "\x00" in question:
        raise ValueError("question must contain 1-500 characters")
    try:
        question.encode("utf-8", "strict")
    except UnicodeError as exc:
        raise ValueError("invalid question text") from exc
    if payload.get("profile") not in profiles:
        raise ValueError("unsupported profile")
    override = payload.get("allowMemoryPressure", False)
    if type(override) is not bool:
        raise ValueError("invalid memory confirmation")
    return question.strip(), payload["profile"], override


def parse_chat(payload, profiles):
    if not isinstance(payload, dict) or set(payload) - CHAT_KEYS:
        raise ValueError("unsupported request field")
    question, profile, override = parse_ask({"contractVersion": payload.get("contractVersion"),
                                              "question": payload.get("message"),
                                              "profile": payload.get("profile"),
                                              "allowMemoryPressure": payload.get("allowMemoryPressure", False)}, profiles)
    history = payload.get("history", [])
    if not isinstance(history, list) or len(history) > MAX_HISTORY_ITEMS:
        raise ValueError("invalid conversation history")
    total = 0
    for item in history:
        if not isinstance(item, dict) or set(item) != {"role", "content"} or item["role"] not in ("user", "assistant"):
            raise ValueError("invalid conversation role")
        content = item["content"]
        if not isinstance(content, str) or not content.strip() or len(content) > 1200 or "\x00" in content:
            raise ValueError("invalid conversation text")
        content.encode("utf-8", "strict")
        total += len(content)
    if total > MAX_HISTORY_CHARS:
        raise ValueError("conversation history too large")
    state = payload.get("conversationState")
    if state is not None and (not isinstance(state, dict) or set(state) != {"route", "topic"}
                              or state["route"] not in ("GENERAL_CONVERSATION", "PROJECT_GROUNDED", "CLARIFICATION_REQUIRED")
                              or state["topic"] not in (None, "cleaning", "reading", "finance", "quote", "weather", "todo", "language-learning")):
        raise ValueError("invalid conversation state")
    return question, profile, override, history, state


def public_resource(resource):
    return {key: resource.get(key) for key in RESOURCE_KEYS} if isinstance(resource, dict) else None


def public_answer(result, profile, model, elapsed_ms):
    """Copy only Phase 6 display fields; never pass provider diagnostics through."""
    def validate_paths(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "path":
                    if (not isinstance(item, str) or not item or len(item) > 300
                            or item.startswith("/") or "\\" in item or ":" in item
                            or any(part in ("", ".", "..") for part in item.split("/"))
                            or any(ord(char) < 32 for char in item)
                            or str(PurePosixPath(item)) != item):
                        raise ValueError("unsafe citation path")
                else:
                    validate_paths(item)
        elif isinstance(value, list):
            for item in value:
                validate_paths(item)
    validate_paths(result.get("citations", []))
    validate_paths(result.get("conflicts", []))
    status = result.get("draftStatus", "ok")
    if status in ("draft", "insufficient_evidence"):
        status = "ok"
    verified = status == "ok" and result.get("groundingStatus") in (
        "grounded", "conflicted", "insufficient_evidence")
    answer = {"contractVersion": 1, "status": status,
              "answer": result.get("answer", "") if verified else "The answer could not be verified. Please try again.",
              "claims": result.get("claims", []) if verified else [],
              "citations": result.get("citations", []) if verified else [],
              "uncertainty": result.get("uncertainty", []),
              "conflicts": result.get("conflicts", []) if verified else [],
              "groundingStatus": result.get("groundingStatus", "unavailable"),
              "evidenceAsOf": result.get("evidenceAsOf"), "model": model, "profile": profile,
              "timing": {"totalMs": elapsed_ms, "draftMs": result.get("draftLatencyMs", 0),
                         "groundingMs": result.get("groundingLatencyMs", 0)},
              "resource": public_resource(result.get("resource"))}
    return answer
