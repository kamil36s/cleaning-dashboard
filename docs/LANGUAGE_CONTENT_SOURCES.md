# Language Content Inbox source and rights decisions

Last reviewed: 2026-09-18  
Policy: `language.content-rights/v1`  
Ingestion: `language.content-ingestion/v1`

The Content Inbox is a provenance and routing layer. Public availability is not treated as permission to copy, download, cache, or rehost. When storage authority is absent or unclear, the implementation stores only a canonicalized public URL, bounded user notes, and descriptive metadata. It performs no server-side URL request.

| Source class | Acquisition | Metadata / URL | Text / transcript | Audio / video | Attribution and retention | Decision |
|---|---|---:|---:|---:|---|---|
| `PASTED_TEXT` | User pastes text they control or may use | Yes | Yes | N/A | `USER_PROVIDED_STORAGE_ALLOWED`; retained until user deletion | Supported; canonical `TextDocument` owns analyzed text |
| `LOCAL_AUDIO` | User uploads a local file they own or may store | Yes | N/A until separately supplied | Yes, managed private file | `USER_OWNED_STORAGE_ALLOWED`; retained until user deletion | Supported for MP3, M4A/MP4 audio, WAV and OGG |
| `LOCAL_TRANSCRIPT` | User pastes/uploads plain transcript | Yes | Yes | N/A | User-provided attribution may be recorded; retained until deletion | Supported and projected to canonical `TextDocument` |
| `LOCAL_AUDIO_PLUS_TRANSCRIPT` | User uploads audio and then supplies transcript | Yes | Yes | Yes | Both artifacts inherit explicit user-controlled storage status | Supported; timestamped transcripts can become Listening-ready |
| `SRT` / `VTT` | User supplies subtitle file/text | Yes | Yes, including cue provenance | No media implied | Source fingerprint, format and version retained | Supported; timestamps remain source evidence |
| `ARTICLE_REFERENCE` | User enters HTTPS/HTTP URL | Yes | No | No | Reference/notes only | `REFERENCE_ONLY`, `STORAGE_NOT_AUTHORIZED` |
| `PODCAST_REFERENCE` | User enters episode URL | Yes | No | No download/cache | Reference/notes only | `REFERENCE_ONLY`; no RSS enclosure or episode fetch |
| `VIDEO_REFERENCE` | User enters video URL | Yes | No | No download/cache | Reference/notes only | `REFERENCE_ONLY`; no YouTube/general downloader |
| `NRK_REFERENCE` | User enters official `nrk.no`, `radio.nrk.no`, or `tv.nrk.no` URL | Yes | No | No download/cache | Reference/notes only | `REFERENCE_ONLY`; non-NRK hosts are rejected |
| Unknown/unsupported source | None | No | No | No | None | Fail closed with `unsupported_content_source` |

## NRK decision

NRK's archive-access information says permission to use or show archive content may be purchased and that conditions depend on the intended use. That is evidence that public playback is not a blanket storage/reuse licence. NRK's published EPG terms likewise describe protected text/images/metadata and agreement-limited use. Phase 10.5 therefore has no NRK retrieval adapter: official NRK links are useful references only, and the server does not fetch their pages, transcripts, streams, feeds, or media. Sources: [NRK archive access](https://info.nrk.no/ekstern/access-nrk-archives/) and [NRK EPG-data terms](https://info.nrk.no/wp-content/uploads/2021/02/NRK_EPG-data_TVA_Nordig_format.pdf).

## Podcast, article, and video decision

A URL or an application's ability to play a work does not establish a right to retain its bytes. No generic scraper, RSS enclosure downloader, page extractor, YouTube downloader, or media proxy is implemented. A future adapter requires a source-specific licence/access audit and a new policy version.

## Security and retention contract

- References accept only HTTP(S), strip fragments, reject credentials, reject localhost, `.local`, and private/loopback/link-local literal IPs, and never make a network call. NRK references additionally use an official-host allowlist.
- Local media has a 64 MiB request/service limit. Transcript JSON is bounded at the HTTP layer and cue count/timestamps are bounded by the parser.
- Media type is detected from bytes and checked against declared MIME and extension. Original names are sanitized display metadata only.
- Stored filenames are generated artifact IDs beneath `data/language-learning/media/`; database paths must resolve as direct children of that root. Media is served only by artifact ID through the managed range endpoint.
- SQLite stores metadata, checksum, rights, retention, and provenance—not media BLOBs and never the original client path.
- Duplicate local media and references are bounded by fingerprints. Destructive media cleanup/restore is deliberately not automated until reference-aware lifecycle operations exist.
- JSON export advances with the schema and exports media metadata/provenance only. A complete disaster-recovery backup must copy both the SQLite snapshot and the managed media directory while preserving relative artifact names.

## Open questions

No externally licensed/store-allowed adapter is selected in v1. `LICENSED_STORAGE_ALLOWED` is therefore not inferred from URL metadata. Source-provided transcripts without a direct user grant also remain reference-only until an adapter can prove storage authority.
