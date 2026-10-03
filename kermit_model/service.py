"""Only this CLI orchestration calls Phase 4 retrieval; providers see messages only."""

from threading import BoundedSemaphore
import time

from kermit_retrieval import retrieve

from .answer import DraftValidationError, validate
from .config import configured
from .fake_provider import FakeProvider
from .ollama_provider import OllamaProvider
from .prompt import build_prompt
from .provider import ProviderFailure
from .resources import preflight, read_physical_memory


GENERATION_SLOT = BoundedSemaphore(1)


def generate_draft(pack, *, config=None, provider=None, presentation="neutral", explain=False,
                   allow_memory_pressure=False, memory_reader=None, trace_sink=None):
    config = config or configured()
    provider = provider or (FakeProvider() if config.provider == "fake" else OllamaProvider())
    messages, prompt_info = build_prompt(pack, presentation, config.reasoning, config.evidence_limit)
    diagnostic = {"retrieval": {"claimType": pack["claimType"], "candidateSubsystems": [s["id"] for s in pack["candidateSubsystems"]],
                                "evidenceIds": prompt_info["evidenceIds"], "conflictIds": [c["id"] for c in pack["conflicts"]],
                                "staleSourceCount": len(pack["staleSources"])},
                  "prompt": prompt_info, "profile": config.profile, "reasoning": config.reasoning,
                  "provider": config.provider, "model": config.model,
                  "generationOptions": {"think": config.think, "temperature": config.temperature,
                                        "num_predict": config.max_output_tokens, "evidenceLimit": config.evidence_limit,
                                        "keep_alive": config.keep_alive}}
    if not pack["selectedEvidence"] or pack.get("diagnostics", {}).get("supportStatus") == "none":
        return {"status": "insufficient_evidence", "answer": "The supplied evidence is insufficient to verify an answer.",
                "citedEvidenceIds": [], "uncertainty": pack["uncertainty"] + ["No directly relevant admitted evidence supports this request."],
                "conflictsMentioned": [],
                "provider": config.provider, "model": config.model, "profile": config.profile, "latencyMs": 0,
                "finishReason": "not_called", "diagnostics": diagnostic if explain else None}
    if not GENERATION_SLOT.acquire(blocking=False):
        raise ProviderFailure("prototype generation concurrency limit reached")
    resource = None
    try:
        if config.provider == "ollama":
            resource = preflight(config, provider, memory_reader=memory_reader)
            if resource["state"] != "green" and not (resource["state"] == "yellow" and allow_memory_pressure):
                status = "confirmation_required" if resource["state"] == "yellow" else (
                    "unavailable" if resource["reason"] == "model_unavailable" else "waiting_for_memory")
                return {"status": status, "answer": resource["message"], "citedEvidenceIds": [],
                        "uncertainty": [], "conflictsMentioned": [], "provider": config.provider,
                        "model": config.model, "profile": config.profile, "latencyMs": 0,
                        "finishReason": "resource_gate", "resource": resource,
                        "diagnostics": diagnostic if explain else None}
        generation_started = time.monotonic()
        result = provider.generate(messages, config)
    except ProviderFailure as exc:
        return {"status": "unavailable", "answer": "The local model is unavailable; no draft answer was produced.",
                "citedEvidenceIds": [], "uncertainty": [str(exc)[:120]], "conflictsMentioned": [],
                "provider": config.provider, "model": config.model, "profile": config.profile,
                "latencyMs": int((time.monotonic() - generation_started) * 1000) if "generation_started" in locals() else 0,
                "finishReason": "provider_error", "failureCategory": exc.category, "resource": resource,
                "diagnostics": diagnostic if explain else None}
    finally:
        GENERATION_SLOT.release()
    if resource is not None:
        try:
            after = (memory_reader or read_physical_memory)()
            resource["availableAfterMb"] = after.available_mb
        except (OSError, AttributeError, TypeError, ValueError):
            resource["availableAfterMb"] = None
        resource["loadDurationNs"] = result.usage.get("load_duration")
        resource["generationDurationMs"] = result.latency_ms
    try:
        model_pack = {**pack, "selectedEvidence": [e for e in pack["selectedEvidence"]
                                                    if e["evidenceId"] in prompt_info["evidenceIds"]]}
        if trace_sink is not None:
            trace_sink({"rawStructuredDraft": result.text, "finishReason": result.finish_reason,
                        "modelFacingEvidenceIds": prompt_info["evidenceIds"]})
        if result.finish_reason == "length":
            raise DraftValidationError("truncated_result", "provider stopped at output limit")
        draft = validate(result.text, model_pack)
        status = "draft"
        failure_category = None
    except DraftValidationError as exc:
        draft = {"answer": "The local model returned an invalid draft.", "citedEvidenceIds": [],
                 "uncertainty": [str(exc)[:120]], "conflictsMentioned": []}
        status = "invalid"
        failure_category = exc.category
    return {"status": status, **draft, "provider": result.provider, "model": result.model,
            "profile": config.profile, "latencyMs": result.latency_ms, "finishReason": result.finish_reason,
            "failureCategory": failure_category, "usage": result.usage, "resource": resource,
            "diagnostics": diagnostic if explain else None}


def ask(question, *, profile="normal", provider=None, presentation="neutral", explain=False,
        allow_memory_pressure=False):
    config = configured(profile, provider)
    pack = retrieve({"contractVersion": 1, "question": question})
    return generate_draft(pack, config=config, presentation=presentation, explain=explain,
                          allow_memory_pressure=allow_memory_pressure)
