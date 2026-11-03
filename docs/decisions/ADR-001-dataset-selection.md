# ADR-001: Select FlyWire FAFB v783 for the first connectome explorer

- Status: accepted for M1 design; implementation pending review
- Date: 2026-11-02
- Decision owners: NeuroPilot project

## Context

M1 needs a real, cited fruit-fly connectome that supports neuron IDs, annotations, directed connections, and synapse-count weights through a documented bulk-download path. The project must remain local-first, avoid scraping interactive pages, and avoid downloading the full EM volume, all synapse coordinates, or morphology archives.

## Decision

Use FlyWire FAFB v783, the Female Adult Fly Brain public Codex snapshot, as the initial dataset. Import these four products:

1. `neurons.csv.gz` for root IDs and source neurotransmitter predictions;
2. `classification.csv.gz` for hierarchical annotations;
3. `consolidated_cell_types.csv.gz` for consolidated primary/additional cell types;
4. `connections_princeton.csv.gz` for directed neuron-to-neuron edges, neuropil partitions, predicted transmitter field, and synapse-count weights.

The Python importer will download through the documented Codex resource endpoint, normalize a bounded sample, and write a provenance manifest. Rust will serve only local normalized artifacts. The frontend will render a bounded graph with deterministic force-directed layout coordinates explicitly labelled as layout coordinates.

## Rationale

- Codex identifies FAFB v783 as the public FAFB snapshot and reports 139,255 neurons and 3,732,460 displayed connections.
- Codex explicitly recommends static files for bulk analysis and documents `consolidated_cell_types` plus `connections_princeton` for programmatic processing.
- The official open-source Codex schema gives stable column names and confirms that connection rows are directed `(pre_root_id, post_root_id, neuropil)` tuples with `syn_count` and `nt_type`.
- The release is publicly available under CC BY-NC 4.0, with explicit FlyWire citation guidance.
- The four compressed products are roughly 72 MB combined, suitable for the M0 Mac and a bounded local import.

## Alternatives considered

### Live CAVEclient queries

Rejected for the first bulk import. CAVE is appropriate for supported live queries and root-ID lineage operations, but it introduces credentials, rate limits, mutable state, and a moving source database. It remains a possible later validation tool, never a substitute for the pinned static snapshot.

### Full synapse table

Deferred. It is approximately gigabytes and is unnecessary for a neuron-resolution graph whose edges already carry synapse counts. It would materially expand disk, parsing, and UI scope.

### Skeletons, meshes, and EM volume

Deferred. They are morphology/volume products, not required for the first graph explorer. Their inclusion would also create an anatomical-coordinate obligation that the first UI does not need.

### A different FlyWire dataset

Deferred. BANC, MANC, MAOL, and MCNS are valid Codex datasets, but selecting one now would change the scope and annotation/product assumptions without improving the M1 acceptance criteria.

## Consequences

Positive:

- reproducible, source-backed graph data;
- small initial disk footprint;
- clear separation between acquisition, API, and visualization;
- no need for a database or cloud compute.

Costs and limitations:

- a Codex account/API token is needed for downloads;
- current exported annotation objects may have HTTP metadata newer than the October 2023 snapshot, so manifests must record both snapshot and object metadata;
- root IDs are snapshot-specific and must be serialized as strings at the browser boundary;
- synapse counts and connectivity are structural observations in the release, not proof of functional or causal influence;
- the first graph layout is abstract and must not be interpreted as anatomy.

## Sources

- [Codex FAQ](https://codex.flywire.ai/faq)
- [FAFB download portal](https://codex.flywire.ai/api/download?dataset=fafb)
- [FlyWire citation and licensing guidelines](https://flywire.ai/guidelines)
- [FlyConnectome access tutorials](https://github.com/seung-lab/FlyConnectome)
- [Codex canonical data schema](https://github.com/murthylab/codex/blob/main/codex/data/catalog.py)
- [Dorkenwald et al., Nature (2024)](https://doi.org/10.1038/s41586-024-07558-y)
- [Schlegel et al., Nature (2024)](https://doi.org/10.1038/s41586-024-07686-5)
