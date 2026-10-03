# Language reference import operations

Status: **Phase 7.5B production procedure**  
Reference schema: **v1**  
Scope: authorized Bokmål Tier 1 plus Tier 2 unigram only

## Configuration

- `LANGUAGE_REFERENCE_DB` selects the independent published database. The default is `data/reference/language-reference-nb.sqlite`.
- `LANGUAGE_REFERENCE_SOURCE_DIR` selects the ignored raw-artifact directory. The default is `data/reference/sources/`.
- Neither path is exposed by the normal Language server. Normal server startup does not initialize or query the reference database.
- `data/language-learning.sqlite` is never opened for writing by this pipeline.

## Commands

Acquire and verify frozen artifacts without building:

```powershell
python scripts/build_language_reference.py --tier 2 --download-only
```

The one-time manifest-freezing audit may use `--download-only --allow-unfrozen`. A production build rejects `--allow-unfrozen` and rejects any size or SHA-256 mismatch.

Build twice, compare logical content, validate, and atomically publish:

```powershell
python scripts/build_language_reference.py --tier 2 --rebuild-check --force-rebuild
```

Verify the published database without rebuilding:

```powershell
python scripts/build_language_reference.py --tier 2 --verify-only
python scripts/diagnose_language_reference.py
```

`--no-publish` retains the first staging database for a local inspection run. Tier 3 is deliberately unsupported by the Phase 7.5B CLI; the accepted `n=2..6` archive cannot be selected accidentally.

## Safety and staging

1. Resolve paths and require 3 GiB free for Tier 1 or 5 GiB for Tier 1+2 before any download/import.
2. Download only manifest-approved URLs, through `.part` files, with bounded timeout/retries.
3. Validate exact observed byte size and SHA-256 before use.
4. Create a unique empty staging database; never modify the published file in place.
5. Import Ordbank, KELLY, CLARINO, official idioms, then the Bokmål unigram archive in bounded batches.
6. Keep a source/checksum/parser-version-specific import run. Interrupted builds restart from a new empty staging database; they are not resumed across source or parser changes.
7. Run derived jobs, `ANALYZE`, `PRAGMA optimize`, integrity/FK checks, query benchmarks, and canonical hashing.
8. When requested, build again from the same artifacts and require equal logical fingerprints.
9. Switch the validated database back to `journal_mode=DELETE` and `synchronous=FULL`.
10. Publish with one same-filesystem atomic replacement. A failure before that call leaves the previous published database untouched.

Failed staging databases are diagnostic artifacts and may be deleted after the failure is recorded. Raw artifacts, staging databases, the production DB, and generated reports remain ignored by Git.

## Reject and logging policy

- Import progress is logged by source and every 250,000 large-source rows, never per row.
- Reject detail is bounded to 20 samples per parser category and 100 import-run warning/error messages.
- A source-count deviation stops that source. The CLARINO frozen artifact demonstrated this rule: import stopped when the audit's 10,000-row expectation disagreed with the observed 9,999 data rows. The invariant and documentation were updated only after bounded inspection showed one header plus 9,999 valid rows.
- Ordbank form rows whose `LEMMA_ID` is absent from `lemma.txt` are counted and rejected; they do not create orphan reference forms.
- Ambiguous/unmatched corpus rows are accepted raw evidence, not rejects. Candidate mappings and frequency mass remain inspectable.

## Generated local reports

The default report directory is ignored `data/reference/reports/`:

- `language-reference-attribution.json` — source/provider/version/license/attribution/landing page, with no filesystem paths.
- `language-reference-quality.json` — machine-readable counts, mapping mass, validation, benchmarks, storage, fingerprints, and user-DB isolation.
- `language-reference-quality.md` — bounded human-readable source and benchmark summary.

## Recovery

- Checksum mismatch: do not rename/reuse the artifact. Reacquire it, compare upstream metadata, and update the tracked manifest only through an explicit source-freeze review.
- Parser-version change: bump the manifest parser version. The new value appears in the import run and changes the deterministic run provenance.
- Failed import/validation/rebuild: do not publish; inspect the failed staging run and bounded errors, correct code/manifest evidence, and restart from empty staging.
- Existing production DB: pass `--force-rebuild` only when replacement is intended. The existing file survives until the final atomic replacement succeeds.

