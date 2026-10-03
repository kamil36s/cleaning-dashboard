# Language Phase 8 provider setup

Phase 8 keeps both Gemini and Google Cloud Text-to-Speech credentials on the Python server. Do not place either credential in Vite variables, browser storage, generation requests, or exported data.

## Gemini automatic generation

Copy these names into the server's private environment file and supply the key only there:

```dotenv
LANGUAGE_GEMINI_ENABLED=true
LANGUAGE_GEMINI_MODE=FREE_ONLY
LANGUAGE_GEMINI_MODEL=gemini-3.8-flash
GEMINI_API_KEY=
```

Restart the Python dashboard server after changing them. Language Settings and `GET /api/language/generation/provider-health` expose only redacted state, provider/adapter/model identifiers, and policy. The health check makes no generative network call.

`FREE_ONLY` is a software fail-closed policy: the adapter has one fixed model and endpoint, no model/provider fallback, no quota-bypass retry, and stops on rate or quota exhaustion. Google account/project billing configuration is external to this dashboard and Phase 8 does not modify it. Confirm the API key's project and billing/free-tier settings in Google AI Studio or Google Cloud before enabling automatic mode.

If Gemini is disabled, unconfigured, rate-limited, quota-exhausted, or unavailable, select Manual in Generate. The existing copy/paste workflow remains fully functional.

## Accepted generated-text audio

Reader audio reuses the existing Phase 9A Google Cloud TTS setup:

```dotenv
GOOGLE_CLOUD_PROJECT=
GOOGLE_APPLICATION_CREDENTIALS=
NORWEGIAN_TTS_VOICE=nb-NO-Chirp3-HD-Kore
```

The configured identity needs permission to call Google Cloud Text-to-Speech. The browser sends only an accepted generated document ID and authoritative sentence ID. The server resolves the exact stored sentence and fixed `nb-NO` voice/configuration; arbitrary browser text and synthesis overrides are rejected.

Audio is cached under `data/audio/language-learning/nb-NO/` with an identity derived from exact sentence text, language, provider, voice, encoding, and synthesis configuration version. Identical Cloze and generated Reader sentences reuse the same metadata and MP3. Listening creates no exposure, knowledge, Anki, XP, quest, or Listening-module evidence.

## Troubleshooting states

- `NOT_CONFIGURED`: opt-in disabled or key missing.
- `CONFIGURED`: local configuration is valid; no probe call was made.
- `AVAILABLE`: at least one call succeeded in this process.
- `FREE_QUOTA_EXHAUSTED` / `RATE_LIMITED`: stop; do not retry to evade the limit.
- `AUTH_ERROR`: verify the server-side key and project permissions.
- `MODEL_UNAVAILABLE`: configured model is not allowlisted or the endpoint returned not found.
- `NETWORK_ERROR`: bounded transport attempts failed.
- `PROVIDER_ERROR`: refusal, malformed response, or another terminal provider failure.

Automatic requests and attempts are durable. A process restart requeues an interrupted automatic request unless cancellation had already been requested. The total provider-attempt ceiling remains three.
