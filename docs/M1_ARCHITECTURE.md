# M1 architecture: real FAFB v783 explorer

Status: design only. This document does not add dependencies or implement the API/UI.

## Boundaries

```text
Codex download (token stays here)
        |
        v
Python importer + validator
  raw ignored files
  normalized bounded graph + provenance manifest
        |
        v
Rust local service
  typed contracts, validation, bounded query results
        |
        v
React + Three.js dashboard
  search, selected neuron, directed subgraph
```

Python owns acquisition, CSV/gzip parsing, schema checks, joins, and scientific data transformations. Rust owns the read-only local API, typed response validation, pagination/caps, and service lifecycle. The browser receives only normalized records and never receives credentials or raw bulk files.

## Normalized data model

The first normalized store may be Parquet for tables plus one JSON provenance manifest. A database is unnecessary for the bounded M1 sample.

### `neurons`

| Field | Type | Meaning |
|---|---|---|
| `dataset_id` | string | `flywire-fafb` |
| `snapshot` | string | `783` |
| `root_id` | uint64 / API string | Snapshot-local neuron identifier |
| `group` | nullable string | Codex neuron group, if present |
| `nt_type` | nullable string | Predicted neurotransmitter type from source |
| `nt_type_score` | nullable float64 | Source confidence/score |
| `source_product` | string | `neurons` |

### `neuron_annotations`

One row per `(root_id, annotation_namespace, key)` or a wide typed row for the fixed v783 fields. The initial implementation can use a wide table with:

`root_id`, `flow`, `super_class`, `class`, `sub_class`, `hemilineage`, `side`, `nerve`, `primary_type`, `additional_types`, `source_products`.

`primary_type` and normalized `additional_types` come from `consolidated_cell_types`; hierarchical fields come from `classification`. The source header must be validated as `additional_type(s)` and explicitly mapped to `additional_types`. Missing values remain null. The importer must not convert nulls into labels such as “unknown type”.

### `connections`

One row per source edge and neuropil tuple:

`pre_root_id`, `post_root_id`, `neuropil`, `synapse_count`, `nt_type`, `source_product`, `threshold_policy`.

`synapse_count` is the source `syn_count`; it is a count/edge weight, not a probability or firing rate. Multiple rows between the same endpoints are valid when they differ by neuropil. The default minimum threshold is pair-level: sum all neuropil rows for `(pre_root_id, post_root_id)` first, then compare the pair total to `min_synapses`. An unaggregated response preserves every row belonging to a qualifying pair; an aggregated response sums those rows and returns `aggregation_rule: "sum_synapse_count_by_endpoint_pair"`. The import report records whether the source file was already filtered and retains source rows below the UI threshold when present.

### `dataset_metadata`

The manifest is exposed as metadata with `dataset_id`, `snapshot`, snapshot date, source URL, access date, license, citations, product list, file hashes, row counts, schema version, importer commit, and validation report. Every graph response includes a compact `provenance_ref` pointing to this metadata.

## Rust API contract

All endpoints are loopback-only and JSON over HTTP for M1. The API version is `/api/v1`. The Rust listener binds to `127.0.0.1`; IPv6 is disabled unless explicitly configured and tested as `::1`. CORS allows only the exact local dashboard origin, never `*`. Host and Origin headers are validated for local requests. Errors and metadata never include absolute local paths.

The Rust crate now includes a dependency-light Axum JSON router for neuron lookup and directed connection expansion over an already validated `GraphService`. The router does not acquire data, read credentials, or load arbitrary paths. It returns stable, redacted error envelopes and preserves the typed query semantics. A runnable listener, normalized-artifact loader, narrow search route, loopback host/origin checks, and exact-origin CORS remain explicit follow-up work; the router is transport code only and must not be mistaken for a complete real-data service.

### Get one neuron

```http
GET /api/v1/datasets/flywire-fafb/783/neurons/{root_id}
```

Response `200`:

```json
{
  "schema_version": 1,
  "dataset": {"id": "flywire-fafb", "snapshot": "783"},
  "provenance_ref": "manifest-sha256:…",
  "neuron": {
    "root_id": "720575940632369439",
    "group": null,
    "nt_type": "acetylcholine",
    "nt_type_score": 0.98,
    "annotations": {
      "primary_type": "HSN",
      "additional_types": [],
      "flow": "central",
      "super_class": "central",
      "class": null,
      "sub_class": null,
      "hemilineage": null,
      "side": "left",
      "nerve": null
    }
  }
}
```

`404` means the root ID is absent from the selected snapshot. `400` means malformed or unsafe ID syntax. Root IDs are strings on the wire to avoid JavaScript precision loss.

### Expand directed connections

```http
GET /api/v1/datasets/flywire-fafb/783/neurons/{root_id}/connections?direction=outgoing&limit=50&cursor=…&min_synapses=5&aggregate=false
```

Query rules:

- `direction` is required and is `incoming`, `outgoing`, or `both`;
- `limit` is bounded by the service, with a documented default and maximum;
- `cursor` is an integrity-checked client-visible pagination token bound to the imported artifact, schema version, graph limits, and complete query tuple; malformed, modified, stale, or out-of-range cursors fail closed. Its checksum detects accidental or unsophisticated modification; it is not a cryptographic authorization mechanism, which is appropriate only for this local read-only contract.
- `min_synapses` is an explicit pair-level filter, defaulting to the measured source/portal policy used by the imported product;
- `aggregate=false` preserves one row per `(pre, post, neuropil)`; `aggregate=true` sums `synapse_count` by endpoint pair and returns the aggregation rule.

For `aggregate=false`, a pair qualifies once the sum across all its neuropil rows meets the threshold; no individual neuropil row is thresholded independently. The importer must report whether `connections_princeton` was pre-filtered and must not infer that from the filename.

Response `200`:

```json
{
  "schema_version": 1,
  "dataset": {"id": "flywire-fafb", "snapshot": "783"},
  "provenance_ref": "manifest-sha256:…",
  "query": {"root_id": "720575940632369439", "direction": "outgoing", "limit": 50, "aggregate": false},
  "nodes": [
    {"root_id": "720575940632369440", "annotations": {"primary_type": null}}
  ],
  "edges": [
    {"pre_root_id": "720575940632369439", "post_root_id": "720575940632369440", "neuropil": "MB", "synapse_count": 12, "nt_type": "acetylcholine"}
  ],
  "aggregation_rule": null,
  "next_cursor": null,
  "truncated": false
}
```

The selected neuron is always included in `nodes`, including when it has no qualifying edges. For `direction=both`, each edge retains its original presynaptic-to-postsynaptic orientation. The service rejects negative limits, unknown directions, overlong IDs, unsupported dataset/snapshot combinations, and requests that exceed the graph cap. It must report `truncated=true` rather than silently dropping edges. API errors use a stable `{code, message, request_id}` shape and never include tokens or local absolute paths.

Pagination is reproducible: edges are ordered by `(pre_root_id, post_root_id, neuropil)` with deterministic tie-breakers for duplicate sort keys, and a cursor is valid only for the normalized artifact hash, schema version, graph limits, and complete query tuple `(root_id, direction, min_synapses, aggregate)`. The service documents a maximum page size and maximum total graph size. A request beyond the graph cap returns a bounded response with `truncated=true` and an explicit cap detail rather than allocating an unbounded result.

The Rust query service precomputes pair totals and incoming/outgoing adjacency indexes when the normalized artifact is loaded. A query scans only the relevant adjacency list, then applies the pair threshold, optional aggregation, deterministic ordering, pagination, and graph cap.

### Search

The first search endpoint is deliberately narrow:

```http
GET /api/v1/datasets/flywire-fafb/783/neurons?root_id=…&primary_type=HSN&limit=25&cursor=…
```

Only fields present in the imported tables may be searched. Free-form search and invented aliases are deferred until their source semantics are specified.

## Three.js subgraph design

The viewport renders the API’s bounded graph response, not the entire connectome. The selected neuron is a distinct visual state; incoming edges use one direction/color and outgoing edges another. Edge width is a monotonic visual encoding of `synapse_count`, with a legend and exact count on hover. Node color encodes a source annotation such as `primary_type` only when that value exists; null values use an explicit “unannotated” style.

The layout is a deterministic force-directed layout seeded from a hash of `(dataset, snapshot, root_id, sorted node IDs)`. Layout coordinates are labelled “graph layout coordinates” in the UI and are never called anatomical, spatial, soma, or brain coordinates. No Three.js geometry is created from coordinates unless a later scope explicitly imports and labels the official `coordinates.csv.gz` product.

Performance rules:

- cap the returned graph and render history;
- use instanced nodes where repeated geometry is needed;
- update only changed node/edge buffers;
- keep graph layout work outside the render loop;
- show loading, empty, error, disconnected, and truncated states;
- provide keyboard focus, selection, and reduced-motion behavior;
- display dataset/snapshot, source product, threshold, and provenance link beside the graph.

## Integration tests and acceptance criteria

## Proposed implementation breakdown

1. **Importer contract and fixture:** add typed product schemas, a tiny schema-matched fixture, header/type validation, and manifest serialization. No network call in tests.
2. **Authenticated acquisition:** add a Python CLI that accepts `--dataset flywire-fafb --snapshot 783`, reads `CODEX_API_TOKEN` only in the Python process, streams the four selected products, and records HTTP metadata plus SHA-256.
3. **Normalization:** join annotations by `root_id`, preserve nulls and source-product fields, validate connection endpoints and counts, and write a deterministic bounded artifact.
4. **Rust read service:** add typed domain structs and read-only endpoints for neuron lookup, narrow search, and capped incoming/outgoing expansion. Add pagination, aggregation, validation, and provenance references.
5. **Frontend graph slice:** add the API client, selected-neuron inspector, deterministic force layout, directed edge styling, weight legend, provenance panel, and all required loading/error/truncated states.
6. **End-to-end verification:** run the importer against an approved local download, compare API rows with source rows, run browser/API integration tests, capture a short graph screenshot, and update the run instructions without changing the M0 lockfiles unnecessarily.

The first implementation must add:

1. Importer header validation for all four required products, including malformed gzip, missing columns, duplicate annotation IDs, invalid uint64 IDs, non-positive synapse counts, and dangling connection endpoints.
2. Provenance tests that require a manifest, SHA-256, source product names, snapshot, license, citation, and import commit.
3. Rust contract tests for valid neuron lookup, 404 unknown root ID, malformed ID rejection, direction validation, cap enforcement, cursor pagination, `truncated`, and both aggregation modes.
4. A local HTTP integration test that proves the token is not present in any response or log capture.
5. Frontend tests for selected-node state, incoming/outgoing direction styling, weight legend, null annotation styling, loading/error/empty/truncated states, and the explicit graph-layout label.
6. A fixture smoke test that starts from a small schema-matched fixture and proves that displayed edges originate in fixture rows; the fixture must be visibly labelled synthetic in tests and never mixed with FAFB provenance.

M1 acceptance is met only when:

- the importer produces a manifest-backed normalized artifact from FAFB v783;
- the UI displays a real bounded subgraph from that artifact;
- search, select, and inspect work for source-backed IDs/annotations;
- incoming and outgoing connections and synapse counts match the imported source rows;
- every displayed record can be traced to dataset, snapshot, product, and file hash;
- no raw dataset, token, or fabricated biological coordinate is shipped to the browser;
- the M0 `make check` remains green and the M1 integration checks pass;
- the user reviews this milestone before any M2 work begins.
