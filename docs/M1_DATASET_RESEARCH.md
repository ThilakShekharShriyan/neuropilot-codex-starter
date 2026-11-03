# M1 dataset research: FlyWire FAFB v783

Status: research and design only. No FAFB files are downloaded by this document.

## Scientific question and scope

M1 asks: can NeuroPilot show a small, selectable directed subgraph from the public FlyWire FAFB v783 static release, with every node, annotation, edge, weight, and dataset claim traceable to an official source file?

The first release is a neuron-resolution graph. It is not a volumetric viewer, a morphology viewer, or a model of neural dynamics. Force-directed display coordinates are layout coordinates and must never be presented as soma or anatomical coordinates.

## Dataset identity

| Field | Value | Evidence |
|---|---|---|
| Dataset | FlyWire FAFB (Female Adult Fly Brain) | [Codex FAQ](https://codex.flywire.ai/faq) |
| Snapshot | v783, October 2023 public snapshot | [Codex FAQ](https://codex.flywire.ai/faq), [FlyWire guidelines](https://flywire.ai/guidelines) |
| Codex scope | 139,255 neurons; 3,732,460 displayed connections | [Codex FAFB page](https://codex.flywire.ai/?dataset=fafb) |
| Public license | CC BY-NC 4.0 | [FlyWire guidelines](https://flywire.ai/guidelines) |
| Access model | Static download products; Codex recommends downloads for bulk analysis | [Codex FAQ](https://codex.flywire.ai/faq), [FlyConnectome](https://github.com/seung-lab/FlyConnectome) |

The snapshot date and the export date are different concepts. Codex says v783 is the October 2023 snapshot, while current exports can include newer classification/community-label material. The provenance manifest must therefore record both the requested snapshot and the HTTP object metadata observed at download time.

## Products required for the first importer

The four required products below are sufficient for neuron IDs, hierarchical annotations, consolidated cell types, and weighted directed connections.

| Requirement | Codex product / file | Canonical columns | Current official object metadata* |
|---|---|---|---|
| Neuron IDs and predicted transmitter fields | `neurons` / `neurons.csv.gz` | `root_id`, `group`, `nt_type`, `nt_type_score`, `da_avg`, `ser_avg`, `gaba_avg`, `glut_avg`, `ach_avg`, `oct_avg` | 1,679,884 bytes; ETag `f60333e9e4124160b9b203b1712a6f91`; generation `1733428446832038` |
| Hierarchical annotations | `classification` / `classification.csv.gz` | `root_id`, `flow`, `super_class`, `class`, `sub_class`, `hemilineage`, `side`, `nerve` | 934,402 bytes; ETag `701c0faf054ceddb460bea4e87d6a624`; generation `1771945205700934` |
| Consolidated cell types | `consolidated_cell_types` / `consolidated_cell_types.csv.gz` | `root_id`, `primary_type`, `additional_type(s)` | 901,707 bytes; ETag `18cc628156bede3129c0e19d14cf52d6`; generation `1771945190208855` |
| Directed connection weights | `connections_princeton` / `connections_princeton.csv.gz` | `pre_root_id`, `post_root_id`, `neuropil`, `syn_count`, `nt_type` | 68,456,801 bytes; ETag `5e5101c6ffc17d7e300541d8f71842c1`; generation `1751983868445475` |

\* These are read-only HTTP `HEAD` observations of the official FlyWire Codex GCS objects on 2026-11-02. They are not a substitute for a signed release checksum. The importer must record the response headers and compute SHA-256 locally. The GCS object path pattern used by the official Codex source is `https://storage.googleapis.com/flywire-data/codex/data/fafb/783/{filename}`.

The Codex FAQ names `connections_princeton` in its programmatic example. The open-source Codex loader also supports a `connections.csv.gz` object with the same canonical connection columns. M1 must select `connections_princeton` from the authenticated download portal and fail closed if the downloaded header does not match the expected schema; it must not silently substitute a different threshold or release. The importer records the actual header and row statistics so we can determine whether the product is already filtered.

### Connection threshold semantics

The Codex application describes its default connectivity threshold as at least five synapses for a neuron pair. Because the source table can contain multiple rows for one `(pre_root_id, post_root_id)` pair across neuropils, M1 treats `min_synapses` as a **pair-level** threshold:

- group rows by `(pre_root_id, post_root_id)` and sum `syn_count` across neuropils;
- retain every original `(pre, post, neuropil)` row belonging to a pair whose total meets the threshold when `aggregate=false`;
- return one edge per endpoint pair with the summed total and an explicit aggregation rule when `aggregate=true`;
- never apply the pair threshold independently to each neuropil row;
- record whether the downloaded product itself contains rows below five synapses and whether it is filtered upstream.

The normalized artifact stores both the source row and the pair total used for filtering. This makes the portal's default behavior reproducible rather than assumed.

## Optional products deliberately deferred

| Product | Size observed | Decision |
|---|---:|---|
| `coordinates.csv.gz` | 5,314,546 bytes | Defer for the first graph view. Add only when an anatomical coordinate view is explicitly scoped. |
| `cell_stats.csv.gz` | 2,526,548 bytes | Defer; not needed for node search or graph expansion. |
| `labels.csv.gz` | 4,771,292 bytes | Defer; community labels are not required for the first acceptance slice. |
| `fafb_v783_princeton_synapse_table.csv.gz` | approximately 2.7 GB according to the portal-linked ecosystem documentation | Do not download in M1. The neuron-resolution connection table already supplies synapse-count weights. |
| Neuron skeleton archive | approximately 13 GB compressed / 31 GB unpacked according to portal-linked ecosystem documentation | Do not download in M1. It is morphology, outside the first graph scope. |
| Synapse coordinates / attachment rates | Variable and per-synapse | Do not download in M1. It is unnecessary for a bounded neuron graph. |

The required compressed set is approximately 72.0 MB decimal (about 68.7 MiB). Adding the three small optional tables would be approximately 84.6 MB decimal. Reserve 2 GB for temporary decompression, validation output, and the normalized bounded sample; this is ample on the M0 machine without committing raw data to Git. The full synapse table and skeleton archive are intentionally excluded from this estimate.

## Authentication and secret handling

Codex requires Google sign-in for interactive apps and provides the download resource through an API token from the user account page. The documented resource pattern is:

```text
https://codex.flywire.ai/api/download_resource?data_product=<product>&dataset=fafb&api_token=<token>
```

The token is required by the download workflow, even though the public release is licensed for non-commercial use. M1 must use a Python-only downloader that reads `CODEX_API_TOKEN` from the process environment or an ignored local `.env` file. The token must never be:

- included in a URL sent to the browser;
- stored in JSON provenance manifests, logs, exception messages, lockfiles, or Git;
- embedded in the Rust service or frontend bundle;
- passed to third-party analytics or telemetry.

The downloader must never log the complete request URL or query parameters. It redacts `api_token` from request diagnostics, redirect errors, retry messages, and exception text. The manifest stores two distinct token-free fields: `portal_url` (`https://codex.flywire.ai/api/download?dataset=fafb`) and `resource_url_template` (`https://codex.flywire.ai/api/download_resource?data_product={product}&dataset=fafb&api_token=<redacted>`). The authenticated URL is constructed only at request time and is never persisted.

The Rust service reads only imported local artifacts. It does not need a Codex token. `.env.example` may contain the variable name only; `.env` remains ignored by the existing `.gitignore`.

## Reproducible import plan

1. Require an explicit dataset configuration: `dataset=flywire-fafb`, `snapshot=783`, source URL, selected product names, and an output directory under ignored `data/`.
2. Download each product through the documented Codex resource endpoint with a streaming request, bounded retries, and atomic temporary files. Never resume into an unknown partial file.
3. Record response status, `Content-Length`, `ETag`, `Last-Modified`, `x-goog-generation`, source URL template, access date, and local SHA-256 before decompression.
4. Decompress with Python’s standard library and validate gzip/CSV headers against the expected product schema.
5. Parse `root_id`, `pre_root_id`, and `post_root_id` as unsigned 64-bit integers represented losslessly in Python and serialized as JSON strings at the API boundary. Do not pass these IDs through JavaScript `number` values.
6. Validate referential integrity: both connection endpoints must be present in the `neurons` table. Annotation tables are left joins and cannot make a dangling endpoint valid. Report rejected rows for missing source neurons, duplicate neuron IDs, duplicate annotation IDs, and missing annotation values. `syn_count` must be a positive integer. Preserve source self-loops and flag them with `is_self_loop=true`; do not silently discard them.
7. Normalize only the bounded sample needed for M1 into deterministic Parquet or newline-delimited JSON artifacts. Keep raw gzipped files outside Git.
8. Write a provenance manifest beside the normalized artifact, then expose the manifest identifier and source metadata through the Rust API. The manifest stores a token-free portal URL and token-free resource URL template; it never stores the authenticated URL.

The importer should support a small checked-in schema fixture for tests, but fixture rows must be labelled synthetic and must never be presented in the UI as biological data.

## Provenance manifest

The manifest is machine-readable JSON, for example:

```json
{
  "manifest_version": 1,
  "dataset": "flywire-fafb",
  "snapshot": "783",
  "snapshot_date": "2023-10",
  "source": "https://codex.flywire.ai/api/download?dataset=fafb",
  "accessed_at_utc": "2026-11-02T00:00:00Z",
  "license": "CC BY-NC 4.0",
  "citation": [
    "Dorkenwald et al., Nature 634, 124–138 (2024)",
    "Schlegel et al., Nature 634, 139–152 (2024)"
  ],
  "products": [
    {
      "name": "connections_princeton",
      "filename": "connections_princeton.csv.gz",
      "sha256": "computed-after-download",
      "content_length_bytes": 68456801,
      "etag": "5e5101c6ffc17d7e300541d8f71842c1",
      "gcs_generation": "1751983868445475",
      "schema_columns": ["pre_root_id", "post_root_id", "neuropil", "syn_count", "nt_type"],
      "source_filter_status": "measured-during-import"
    }
  ],
  "import": {
    "git_commit": "recorded-at-import",
    "python_version": "recorded-at-import",
    "seed": null,
    "transform": "bounded-neuron-subgraph-v1"
  }
}
```

The example values identify fields, not a completed import. The real manifest must contain the actual access timestamp, hashes, row counts, validation counts, importer commit, pair-threshold policy, and source-filter measurement. `additional_type(s)` is the source header; the importer maps it explicitly to normalized `additional_types` after validating the downloaded header.

## Evidence and limitations

| Claim | Source | Limitation |
|---|---|---|
| v783 is the FAFB public snapshot and latest release | [Codex FAQ](https://codex.flywire.ai/faq) | Snapshot identity does not freeze later annotation exports. |
| Static files are preferred for bulk analysis | [Codex FAQ](https://codex.flywire.ai/faq) | The portal requires an authenticated user workflow. |
| Graph edges are directed and weighted by synapse count, with neuropil and predicted NT fields | [Codex source schema](https://github.com/murthylab/codex/blob/main/codex/data/catalog.py) | This is a data representation, not evidence of functional causality. |
| Public release is CC BY-NC 4.0 | [FlyWire guidelines](https://flywire.ai/guidelines) | Follow the current citation guide and terms at publication time. |
| Full volume and morphology are too large for conventional downloads | [FlyConnectome](https://github.com/seung-lab/FlyConnectome) | M1 deliberately uses metadata and neuron-level edges only. |

The approximately 2 GB temporary-space figure is an engineering estimate, not a measured decompressed size. The acquisition report must record measured compressed and decompressed byte totals before the real dataset is accepted.
