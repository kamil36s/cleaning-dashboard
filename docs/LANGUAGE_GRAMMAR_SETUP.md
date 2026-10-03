# Optional Grammar parser setup

Normal Reader analysis stays on Stanza `tokenize=bokmaal`, `pos=bokmaal_charlm`, and `lemma=bokmaal_nocharlm`. Grammar uses its own lazy CPU pipeline with those same packages plus `depparse=bokmaal_charlm`. The existing `conll17` pretrain and forward/backward character language models are required by the selected POS/dependency packages. No MWT processor is required.

The Phase 11 audit found Stanza/resource version 1.14.0 and all Reader resources locally installed, but no dependency model. The following explicit developer provisioning command was run separately from the application:

```powershell
python -c "import stanza; stanza.download('nb', package=None, processors={'depparse':'bokmaal_charlm'}, verbose=False)"
```

If using a nondefault resource directory, pass `model_dir=...` to the explicit downloader and set `LANGUAGE_STANZA_MODEL_DIR` for the application. `STANZA_RESOURCES_DIR` is also respected. The audited default is `C:\Users\kamil\AppData\Local\StanfordNLP\stanza\Cache\1.14.0\resources`.

Runtime code contains no download call. Every Grammar pipeline construction forces `DownloadMethod.NONE`. Health reads package/resource metadata and local file presence without importing Stanza/PyTorch, creating a pipeline or contacting a provider. `AVAILABLE` means provisioned; `loadVerified=false` explicitly distinguishes that from a successful initialization. Missing files report `UNAVAILABLE / MODEL_NOT_PROVISIONED`; malformed manifests and initialization failure have separate reasons. Restart after repairing a failed installation. Reader remains independent.

Run the offline developer benchmark with:

```powershell
python scripts/benchmark_language_grammar.py
```

It blocks socket connection attempts during analysis. `--capture-fixtures` additionally regenerates the committed parser snapshots and checks them against the independent expected positive/negative cases. Snapshot regeneration is explicit, never an application request.

Local files after provisioning:

- `nb/tokenize/bokmaal.pt`
- `nb/pos/bokmaal_charlm.pt`
- `nb/lemma/bokmaal_nocharlm.pt`
- `nb/depparse/bokmaal_charlm.pt`
- `nb/pretrain/conll17.pt`
- `nb/forward_charlm/conll17.pt`
- `nb/backward_charlm/conll17.pt`

Parser provenance includes package/resource versions, all selected processor/package manifest checksums, and manifest fingerprint `f37f657a84b4515f0986ae2be727e4afda30ade6043111359d66af51102e8588`. The resource manifest fingerprint is not a calibrated model-confidence value. Grammar occurrences use categorical `SUPPORTED_RULE_MATCH` or `EXPERIMENTAL_RULE_MATCH` evidence.
