# Journal V2 Review

Date: 2026-09-23  
Status: **PASS**  
Architecture: **history-wiki-journal-v2@1**

The same 14 pilot dates were rewritten from the complete Warsaw-local bundle of raw **user messages**. Assistant messages are excluded from the deterministic day index and from reconstruction input. The old claim-ledger files remain only as an archived Phase 2 experiment and are not shipped to the presentation snapshot.

| Local date | Title | Words | Source conversations | User messages | Privacy | Ambiguity | Assistant excluded |
| --- | --- | ---: | ---: | ---: | --- | --- | --- |
| 2023-01-10 | Trzeba to wreszcie ułożyć | 514 | 2 | 33 | sensitive | no | yes |
| 2023-01-24 | Przeprowadzka, rutyna, smoothie | 105 | 3 | 9 | private | no | yes |
| 2023-02-20 | Nie wiem, co jest dalej | 203 | 1 | 16 | third_party_sensitive | no | yes |
| 2024-07-21 | Dwie–trzy godziny nad Primal Fear | 505 | 7 | 57 | private | no | yes |
| 2024-07-24 | Jedna kość RAM-u działa | 153 | 4 | 17 | third_party_sensitive | no | yes |
| 2024-07-29 | Canto II i tysiąc rumuńskich słów | 489 | 4 | 37 | private | yes — A large Romanian frequency list is pasted source material, not a same-day lived event. | yes |
| 2025-02-03 | Jedno fucking zadanie | 101 | 2 | 4 | sensitive | no | yes |
| 2025-03-16 | Checklista rano, przepaść później | 191 | 3 | 14 | third_party_sensitive | no | yes |
| 2025-08-11 | Tirana, Konya i gdzie tu się wysrać | 448 | 8 | 33 | sensitive | no | yes |
| 2025-10-21 | Dwie godziny piekła z GitHubem | 534 | 14 | 93 | sensitive | no | yes |
| 2026-05-09 | Cmentarz, Tatra i jebane Gemini | 445 | 13 | 40 | sensitive | no | yes |
| 2026-07-07 | Papier czy L4 | 432 | 2 | 2 | sensitive | no | yes |
| 2026-08-17 | Hyperfocus na przepisywanie | 466 | 11 | 112 | third_party_sensitive | yes — Many dated 2015–2016 diary entries are pasted archive material; the reconstruction keeps them as work performed on this day. | yes |
| 2026-09-17 | Kilka systemów naraz | 574 | 18 | 126 | sensitive | yes — Many Codex result reports and prompts are pasted into user messages; the reconstruction records the projects advanced, not assistant-authored report wording as fact. | yes |

## Architecture validation

- Candidate dates indexed from individual user-message timestamps: **767**.
- Pilot dates generated: **14**; no additional days were generated.
- Cache identity: `local_date + source_bundle_hash + output_hash`.
- Reusable pilot outputs detected at build start: **14**.
- Prose shape: **2–8 paragraphs**, naturally short or long according to source density; no padding to a uniform length.
- Provenance in the reading view is lightweight: date, timezone, source counts, and clickable conversation titles.
- Privacy remains section-gated, but sentence-level claim IDs, confidence labels and the visible Claim Ledger are removed.

## Editorial validation

The pilot preserves rough language, mundane errands, technical work, anger, relationship material and severe mental-health content where they occur in the user messages. Pasted archives and Codex reports are treated as material handled on the day, not silently converted into same-day lived events. No fake quotation marks were added around paraphrases.

This review approves only the revised 14-day pilot. It does **not** authorize generation of the remaining Journal days.
