# Language Phase 7.7 dictionary and translation source audit

Audit date: **2026-09-17**. This is the authorization record for the sources displayed by Phase 7.7. A source not accepted here must not be ingested, cached, or presented as dictionary truth.

## Decision matrix

| Candidate | Coverage and facts | Rights reviewed | Phase 7.7 decision | Implemented role |
| --- | --- | --- | --- | --- |
| [Bokmålsordboka through the official Ordbøkene API](https://ordbokene.no/about/open-data) — University of Bergen and Språkrådet | Bokmål articles, stable article/local definition IDs, definitions, examples, usage labels, cross-article references, morphology and any supplied pronunciation | **CC BY 4.0**. The official open-data page explicitly permits use, sharing and adaptation, including commercial use, with attribution; it states that the license also applies to the API. Local storage/cache/display is legally permitted under the license, subject to attribution. | **ACCEPT — live display API** | Read-only, explicit lemma lookup. No bulk import and intentionally no cache in v1. |
| Existing [Norwegian KELLY](https://www.hf.uio.no/iln/english/about/organisation/text-laboratory/services/kelly.html) data | Lemma-level learner rank, corrected POS and an English raw gloss | Existing audited manifest: **CC BY-SA 4.0** | **ACCEPT — existing reference evidence only** | English `SOURCE_GLOSS`, role `KELLY_TRANSLATION_NOT_DICTIONARY_SENSE`; never a sense or authoritative translation. |
| Existing Tatoeba Bokmål/English rows | Sentence text and direct sentence translations | Existing manifests: dedicated rows **CC0 1.0**; broader sentence/translation rows **CC BY 2.0 FR** with per-item attribution | **ACCEPT — existing context only** | Cloze source context; not dictionary definitions or lemma translations. |
| [Norsk ordvev](https://www.nb.no/sprakbanken/ressurskatalog/oai-nb-no-sbr-27/) | Norwegian wordnet graph, about 305,000 synsets and 250,000 names in release 1.1.2 | **CC BY** according to the official Språkbanken catalogue | **DEFER** | Useful future semantic graph, but unnecessary for this bounded slice and expensive to ingest/rebuild. |
| [SNORRE terminology](https://www.nb.no/sprakbanken/ressurskatalog/oai-nb-no-sbr-48/) | Bokmål/Nynorsk/English terminology; definitions are not generally supplied | **CC0** according to the official Språkbanken catalogue | **DEFER** | Potential narrow terminology/translation evidence, not a general learner dictionary. |
| NAOB, Ordnett and other restricted/commercial dictionary bodies | Potential definitions and examples | Subscription, commercial, access-control or redistribution constraints were not established as compatible with this app | **REJECT** | No scrape, import, display or cache. |
| Unselected public web dictionaries and unverified Polish word lists | Varying definitions/translations | Storage, display, redistribution or attribution rights were unclear or insufficiently documented | **REJECT** | No lexical body is used. |
| General machine translation provider | Possible English/Polish output | No provider, credential/data-retention contract and disclosure policy was selected for this local phase | **DEFER** | No request is made and no machine result is fabricated. |

## Accepted source contracts

### Ordbøkene / Bokmålsordboka

- Provider ID: `ORDBOKENE_BOKMALSORDBOKA`.
- Adapter version: `live-display-api/v1`.
- Primary fixed endpoint: `https://oda.uib.no/opal/prod`; fixed fallback: `https://odd.uib.no/opal/prod`.
- Search uses the official Bokmål exact-entry scope and retrieves at most six articles. Articles are fetched only when the learner explicitly opens a lemma.
- Display attribution: **“Bokmålsordboka/Nynorskordboka, Universitetet i Bergen og Språkrådet, ordbøkene.no, CC-BY 4.0.”**
- Provider facts retain provider ID/version, license, attribution, article ID, article `updated` value as source version, source-local sense ID, retrieval mode and a content fingerprint.
- The API license permits local caching, but Phase 7.7 deliberately uses `LIVE_NO_CACHE`: no provider body is persisted in either SQLite database, exports or logs. This minimizes stale copies and keeps refresh semantics simple.
- The adapter renders only fields actually present in the source. Missing definitions, usage labels, relations, examples or pronunciation remain missing.

The official API database and JSON-shape documentation used in the adapter review are [API database documentation](https://github.com/uib/ordbok-api/blob/master/api_db.md) and [API JSON documentation](https://github.com/uib/ordbok-api/blob/master/api_json.md). The product ownership/current-maintenance statement is on the [official Ordbøkene about page](https://ordbokene.no/nob/about).

### KELLY English gloss evidence

- Source ID: `uio-norwegian-kelly-shu-wang`.
- License: `CC-BY-SA-4.0`.
- Attribution: credit the KELLY project, University of Oslo Text Laboratory and Shu Wang; cite Kilgarriff et al. (2014).
- Only already-imported raw `SOURCE_LEARNER_RANK` observations are queried. At most eight unique English glosses are returned after canonical reference resolution.
- Each result is lemma-level `SOURCE_GLOSS`, carries its original source/local ID, version/license/attribution and the explicit role `KELLY_TRANSLATION_NOT_DICTIONARY_SENSE`.

### Polish and user translations

No open Polish provider met the required source, rights, provenance and bounded-runtime bar during this audit. Provider Polish status is therefore `NOT_CONFIGURED` with reason `NO_ACCEPTED_OPEN_POLISH_TRANSLATION_SOURCE`.

Learners can store their own English, Polish or other locale values in the main user database. They are labeled user-owned, do not overwrite source facts and survive provider refresh/outage. They are not assigned provider confidence or machine-translation status.

## Safety and refresh policy

- The dictionary adapter is read-only and has no store dependency.
- Fixed HTTPS origins prevent caller-controlled SSRF destinations. Lemma values are URL-encoded; callers cannot supply a URL.
- Timeout is 3 seconds; one response is capped at 768 KiB; articles at 6; senses at 16; examples at 5 per sense; relations at 16; displayed strings and morphology are bounded.
- The fallback is tried only when primary search fails. Invalid/oversized JSON becomes a contained provider-unavailable state.
- Parallel article reads use at most four workers. Partial article failure does not erase successfully parsed articles.
- Provider refresh is naturally a new live read. It cannot overwrite user translations because source results are not persisted and user data has a separate table/API.
- No reference schema migration, corpus import, source refresh job or Tier 3 ingestion was authorized. Reference schema remains v3 and its logical fingerprint/rebuild recipe are unchanged.

## Role separation

| Payload fact | Owner | Semantic role |
| --- | --- | --- |
| Ordbøkene definition/example/label/reference/pronunciation | REFERENCE, live provider | dictionary article/sense fact |
| KELLY English gloss | REFERENCE, existing local DB | lemma-level learner `SOURCE_GLOSS`, not a dictionary sense |
| Tatoeba sentence/translation | REFERENCE, existing local DB | source context for Cloze |
| Learner translation | USER, main DB | explicit personal annotation |
| Phrasebook note/translation | USER, main DB | annotation attached to an exact saved expression/context |
| Knowledge, exposure, Anki, XP | USER/canonical learning services | untouched by dictionary lookup and phrasebook save |

