# M1.1 — FAFB v783 acquisition contract research

Status: research-only. No authenticated request or product download was performed.

Access date: 2026-11-02 America/Los_Angeles (2026-11-03 UTC as shown by the Codex response headers).

## Scientific and engineering question

Can NeuroPilot acquire the four selected FAFB v783 static products reproducibly, without putting a Codex credential in the browser or repository, and without assuming that a product's filtering or release metadata is stronger than the official sources document?

## Official sources

| Source | Evidence used | Limitation |
|---|---|---|
| [Codex FAQ](https://codex.flywire.ai/faq) | FAFB default snapshot is v783 (October 2023); bulk analysis should use static downloads; resource URL shape is `/api/download_resource?data_product=...&dataset=...&api_token=...`; the token is copied from the Codex account page; FAFB's default connectivity threshold is 5+ synapses and rows may be split by neuropil. | The FAQ does not enumerate the authenticated portal's current product table or assert that `connections_princeton` is already threshold-filtered. |
| [Codex download portal](https://codex.flywire.ai/api/download?dataset=fafb) | Official FAFB v783 context and current dataset page. | Unauthenticated access renders the sign-in page rather than the product inventory. |
| [FlyWire citation guidelines](https://flywire.ai/guidelines) | Public release data is CC BY-NC 4.0; v783 is the October 2023 snapshot; newer classification/community annotations can accompany the public release. | The linked citation-credit document must be checked before publication for the exact bibliography. |
| [FlyConnectome access tutorials](https://github.com/seung-lab/FlyConnectome) | Officially points bulk-download users to Codex and distinguishes static bulk data from CAVE/live queries. | It is a tutorial repository, not the release manifest for the selected files. |

The official FAQ also states that a CAVE/FlyWire token is for live source-project permissions (for example, root-ID mapping or protected data), not normally required for the static-download workflow. The Codex download token is a separate credential and must still be supplied to each resource request.

## Endpoint and authentication contract

### Portal/discovery

```text
GET https://codex.flywire.ai/api/download?dataset=fafb
```

This is the official human-facing download page. It is suitable for discovery and citation review, but the unauthenticated response currently redirects to/signals a Google sign-in page. The acquisition implementation must not scrape that HTML to infer a release manifest.

### Product resource

The FAQ documents this request shape:

```text
GET https://codex.flywire.ai/api/download_resource?data_product=<product>&dataset=fafb&api_token=<TOKEN>
```

The token is in the query string. This is a credential-bearing URL. It must exist only in the Python acquisition process and in memory for the request; it must never be logged, placed in a manifest, passed to the browser, or committed.

### Unauthenticated response probe

On 2026-11-03 UTC, a request to each of the four candidate product identifiers without `api_token` returned HTTP `401`, `Content-Type: application/json`, and the same error class (`Missing or invalid api_token`). No product bytes were downloaded. This confirms the endpoint rejects unauthenticated resource access, but does not prove that each identifier is accepted after authentication.

The response did not provide a product `ETag`, `Last-Modified`, or generation header in this unauthenticated case. Authenticated metadata must be recorded during the approved acquisition.

## Product inventory

These are the four products selected by the approved M1 contract. The identifiers and normalized headers below are the importer contract; the authenticated portal inventory must be checked before writing any bytes.

| Product identifier | Intended role | Expected format | Expected header contract | Verification status |
|---|---|---|---|---|
| `neurons` | neuron IDs and neurotransmitter predictions | gzipped UTF-8 CSV | `root_id,group,nt_type,nt_type_score,da_avg,ser_avg,gaba_avg,glut_avg,ach_avg,oct_avg` | Identifier is part of the approved contract; portal enumeration pending authentication. |
| `classification` | hierarchical neuron annotations | gzipped UTF-8 CSV | `root_id,flow,super_class,class,sub_class,hemilineage,side,nerve` | Identifier is part of the approved contract; portal enumeration pending authentication. |
| `consolidated_cell_types` | consolidated cell-type annotations | gzipped UTF-8 CSV | `root_id,primary_type,additional_type(s)` | The FAQ's worked example names this product; exact current header still must be checked. |
| `connections_princeton` | directed neuron-pair/neuropil connectivity | gzipped UTF-8 CSV | `pre_root_id,post_root_id,neuropil,syn_count,nt_type` | The FAQ's worked example names this product; filtering state is unresolved. |

“Gzipped CSV” is documented by the FAQ's programmatic-access example. Column headers above are the fail-closed local importer contract, not a claim that an unauthenticated portal page has already verified them.

## Filtering status and semantics

Verified from the FAQ:

- Connectivity is directed: presynaptic to postsynaptic.
- FAFB's default minimum is 5 synapses per directed pair.
- A pair can have multiple rows when synapses occur in different neuropils.
- The default threshold is therefore interpreted at pair level, after summing the rows for the directed endpoint pair.

Unresolved and deliberately not assumed:

- The official materials reviewed here do not say whether `connections_princeton` is already filtered to pairs whose cross-neuropil total is at least 5, whether it is an unfiltered export, or whether it uses another release-time transformation.
- The name “Princeton” is not treated as proof of filtering behavior.

The acquisition acceptance test must calculate pair totals from the downloaded file and report both source rows below 5 and pairs whose total is below 5. If any below-threshold pair is present, the manifest must record that the source was not fully pre-filtered. If none is present, that is evidence about this artifact only—not a permanent Codex guarantee.

## HTTP metadata and provenance

For each product, the manifest must record:

- token-free portal URL and token-free resource URL template;
- exact request timestamp (UTC), response status, `Content-Type`, `Content-Length` if supplied, `ETag`, `Last-Modified`, and any documented generation/version fields;
- local compressed-byte count and SHA-256 computed after the complete response is written;
- gzip integrity result, normalized row count, exact observed header, and importer commit;
- dataset/snapshot (`flywire-fafb`, `783`), license, citation references, and preprocessing/threshold policy.

An `ETag`, when supplied, is an HTTP cache validator observed at a time. It is not an immutable release hash and must not replace the locally computed SHA-256. Missing headers are valid observations and must be represented as null rather than fabricated.

Exact current download sizes, generations, ETags, and Last-Modified values remain unresolved until an authenticated metadata/download response is authorized. The earlier approximate storage estimate is not promoted to a verified release fact here.

## License, attribution, and citation

FlyWire's public release is CC BY-NC 4.0. Attribution is required and the non-commercial restriction must remain visible in repository/UI metadata; commercial hosting or use requires a separate license review. FAFB v783 is described by FlyWire as the October 2023 snapshot, while newer classification/community-label material may be attached to the public release.

Before publication, copy the exact current citation credits from FlyWire's citation guide into the dataset manifest and project documentation. The FlyWire terms also direct scientific users to cite the FlyWire website and the relevant FlyWire publication/preprint. This project must not claim that a local import is publication-ready until those exact credits are recorded.

## Safe acquisition recommendations

1. Read the token from an environment variable or local secret store. Do not include it in command-line logging, exception text, retry messages, tracing spans, or persisted configuration.
2. Build the authenticated URL from structured parameters, but redact `api_token` before every log/error path. Disable automatic debug dumps of request URLs and do not persist redirect locations containing query credentials.
3. Stream the response to a product-specific temporary file. Enforce a compressed-byte limit and a decompressed-size limit before parsing. Verify the gzip stream and SHA-256, then atomically rename into the ignored raw-data directory.
4. On interruption, delete or quarantine the partial file. Resume only if a future acquisition test proves that the server supports byte ranges with a stable validator; otherwise restart safely. Never treat a partial file as an artifact.
5. Retry only transient network failures and 429/5xx responses with bounded exponential backoff and jitter. Do not retry 401/403 or schema/authentication errors. Cap attempts and preserve the final redacted diagnostic.
6. Keep acquisition single-purpose and sequential for the first run so request/response metadata and disk usage are auditable. Do not request the synapse-coordinate table, brain volume, skeleton archive, or other out-of-scope products.

## Proposed acquisition tests

These tests are for M1.2 and are not run in this research-only task:

1. **Portal inventory:** with an approved token, enumerate the portal and assert the four exact product identifiers, advertised formats, sizes, and citation text; save the token-free response metadata.
2. **Authentication boundary:** assert missing/invalid tokens fail without creating a product file; assert logs and exceptions contain neither the token nor an authenticated URL.
3. **Streaming and cancellation:** interrupt each transfer, verify no partial artifact is accepted, and verify bounded retries for timeout, reset, 429, and 5xx cases.
4. **HTTP provenance:** capture status, content type, length, ETag, Last-Modified, generation/version fields, final URL after redaction, local SHA-256, and byte counts.
5. **Format contract:** verify gzip integrity, UTF-8 CSV decoding, exact headers, row widths, and the existing importer validation rules before normalization.
6. **Cross-product integrity:** require connection endpoints to exist in `neurons`; left-join optional annotations; count duplicate IDs, missing annotation values, dangling endpoints, and self-loops.
7. **Filtering evidence:** calculate directed pair totals across neuropils, report below-threshold rows/pairs, and record whether the source artifact was already filtered. Do not silently apply a second threshold.
8. **Reproducibility:** rerunning against the same downloaded bytes produces the same normalized artifact hash and deterministic manifest; a changed source hash invalidates cursors and prior normalized artifacts.

## Decision and gate

The static-download route and token-bearing resource endpoint are sufficiently identified for a controlled acquisition review. Product inventory metadata, authenticated response headers, exact sizes, and `connections_princeton` pre-filter status are not yet verified. No real FAFB bytes or credentials were accessed in M1.1.

Stop here and wait for review. M1.2 may begin only after explicit authorization for an authenticated, controlled acquisition.

### M1.2 implementation gate

The acquisition CLI intentionally does not scrape `/api/download`: Codex's
unauthenticated response is a sign-in page, and no supported authenticated
product-inventory endpoint was identified. `discover_inventory()` therefore
fails closed before any product request. A future acquisition may proceed only
after an official inventory mechanism is documented and implemented.

Retry delays use bounded exponential backoff plus capped random jitter. The
four products are downloaded into a unique staging directory, validated as a
complete bundle, and published by directory swap with rollback; a failed stage
or manifest write cannot replace a previous complete output.
