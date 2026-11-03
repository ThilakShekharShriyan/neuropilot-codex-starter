# NeuroPilot — Codex Starter Pack

A research-grade, local-first project for exploring fruit-fly connectomics, embodied sensorimotor simulation, neural activity, and (as a separate extension) EEG-based BCI control.

## Architecture decision

- **Python**: FlyGym / NeuroMechFly, MuJoCo, connectome/data analysis, scientific experiments, ML.
- **Rust**: typed event gateway, experiment orchestration, session management, telemetry, safety/validation boundaries.
- **TypeScript + React + Vite + Three.js**: interactive research dashboard and 3D visualization.
- **Tauri 2**: package as a native desktop application only after the browser-based UI is stable.
- **Parquet / Zarr / JSONL**: durable experiment outputs; JSON over localhost for the first process boundary.
- **No GPU required for initial development.** Add cloud GPU only for workloads that benchmark as too slow or need CUDA/Warp/large models.

Do not rewrite FlyGym or MuJoCo in Rust. Integrate the scientific simulator through a narrow Python service boundary. Rust is used where it adds real value, not as a language checkbox.

## Quick start

1. Read `AGENTS.md`, `plan.md`, and `skills.md`.
2. Install prerequisites from `docs/DEVELOPMENT.md`.
3. Run the environment checks:
   ```bash
   ./scripts/check_environment.sh
   ```
4. Run the M0 verification:
   ```bash
   make check
   cargo run -p neuropilot-hello
   pnpm --dir apps/dashboard dev
   ```
   For a transport-only smoke test, run the explicitly synthetic graph server:
   ```bash
   cargo run -p neuro-api --example synthetic_server
   ```
   This fixture is not FAFB and must not be used as biological evidence. The
   dashboard labels graph coordinates as abstract layout coordinates and never
   treats them as anatomy.
   After the approved FAFB acquisition, normalize and serve the observed
   artifact locally:
   ```bash
   PYTHONPATH=python uv run --project . python -m neuropilot_core.normalize
   cargo run -p neuro-api --example real_server -- data/normalized/fafb_v783 8787
   pnpm --dir apps/dashboard dev
   ```
   The real-data server is loopback-only; the browser receives only bounded
   JSON responses and never receives the Codex token.
5. Ask Codex to inspect the repository and propose a minimal Milestone 0 implementation:
   > Read AGENTS.md, plan.md, skills.md. Do not implement future milestones. Inspect my machine and repository, report missing prerequisites, and propose the smallest verified Milestone 0.
6. Work milestone by milestone. Do not advance until the acceptance checklist is met.

## Repository map (target)

```text
neuropilot/
├── AGENTS.md
├── plan.md
├── skills.md
├── .agents/skills/neuro-research/SKILL.md
├── docs/
│   ├── DEVELOPMENT.md
│   ├── ARCHITECTURE.md
│   ├── DATA_AND_CITATIONS.md
│   └── decisions/
├── apps/
│   └── dashboard/             # React + Vite + Three.js
├── crates/
│   ├── neuro-core/            # Rust domain types and validation
│   ├── neuro-gateway/         # Rust API/event gateway
│   └── experiment-runner/     # Rust orchestration
├── python/
│   ├── neuropilot_sim/        # FlyGym/MuJoCo adapter
│   ├── neuropilot_neuro/      # neural/connectome analysis
│   └── tests/
├── schemas/                   # versioned event/data contracts
├── experiments/               # configs, never raw data by default
├── data/
│   ├── raw/                   # gitignored
│   ├── interim/               # gitignored
│   └── processed/             # gitignored
├── artifacts/                 # gitignored
├── scripts/
└── infra/
    └── cloud/                 # optional GPU job templates, later
```

The first implementation should be smaller than this target tree. Create folders only when the corresponding milestone needs them.

## Important scientific boundary

A fruit-fly connectome/simulator is not a human implanted BCI. The project must label simulated neural activity, measured EEG, and inferred control intent distinctly. Never imply that a fly connectome reproduces Neuralink hardware, human cortical signals, or clinical performance.
