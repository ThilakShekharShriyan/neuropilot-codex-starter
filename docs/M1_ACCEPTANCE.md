# M1 acceptance smoke

Date: 2026-11-03 UTC  
Dataset: FlyWire FAFB, reviewed snapshot label `783`  
Artifact: `cf6716996c7c1a3d6d0721e9182deecae6456d41b9e6295d6af0247f860bafb0`

## Reproduction

From the repository root, with the ignored local acquisition already present:

```bash
PYTHONPATH=python uv run --project . python -m neuropilot_core.normalize
cargo run -p neuro-api --example real_server -- data/normalized/fafb_v783 8787
pnpm --dir apps/dashboard dev --host 127.0.0.1
```

The Rust service binds to loopback and the Vite development server proxies
`/api` to `127.0.0.1:8787`. No credentials are used by either process.

## Observed smoke results

- Dashboard returned HTTP 200 from `http://127.0.0.1:5173/`.
- Neuron lookup returned source-backed root ID `720575940596125868` with
  consolidated type `T5c`.
- Type search returned three `T5c` records.
- Both-direction expansion returned six nodes and five directed edges with the
  artifact provenance reference.
- Invalid root syntax returned the stable `400 invalid_root_id` envelope.
- The UI labels graph coordinates as abstract layout coordinates and displays
  measured/observed dataset provenance; it does not claim anatomical positions.

## Acceptance boundary

M1 now has a real acquired, normalized, source-backed explorer path. The
connectome remains a wiring graph, not a neural-dynamics or embodied-fly
simulation. M2 is still gated for separate review.
