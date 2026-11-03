# NeuroPilot — end-to-end plan

## Product thesis

An interactive research workbench that lets a user explore a fruit-fly connectome, inspect selected neurons and their connectivity, run an embodied fly simulation, observe sensorimotor behavior, and conduct reproducible perturbation/robustness experiments. A later, separate BCI module demonstrates neural-signal decoding and control without conflating EEG with fly neural data.

## Target user experience

A polished desktop-style dashboard:
- Left: dataset/snapshot explorer and neuron search.
- Center: 3D connectome/scene viewport with selectable neurons, paths, and fly body.
- Right: selected-cell details, connectivity, experiment controls.
- Bottom: timeline, event stream, simulation controls, metrics.
- Top: dataset version, session status, compute backend, FPS, simulation speed.

The first visual target is a responsive dashboard with a real data-backed neuron/network view. Do not start by building an elaborate fake 3D brain.

## Stack decisions

| Layer | Choice | Responsibility |
|---|---|---|
| Connectome data | FlyWire/Codex published snapshots; CAVEclient only where appropriate | Source and query data |
| Embodied simulation | NeuroMechFly v2 / FlyGym + MuJoCo | Fly body, sensors, environment |
| Scientific compute | Python, NumPy, SciPy, pandas/Polars, NetworkX as appropriate | Analysis and experiments |
| ML (later) | PyTorch/JAX only when an actual model is selected | Learned decoding/control |
| Systems | Rust stable, Tokio, Axum, Serde, tracing | Event gateway, orchestration, validation |
| UI | TypeScript, React, Vite, Three.js | Interactive visualization |
| Desktop | Tauri 2, later | Native packaging |
| Storage | JSONL for event logs; Parquet for tabular results; Zarr for chunked arrays if needed | Reproducible artifacts |
| Python env | `uv` | Locked, fast Python environment |
| JS package manager | `pnpm` | Reproducible frontend |
| Rust workspace | Cargo workspace | Shared types/services |

Do not add a GPU framework to the Rust service. Do not make Rust own the simulator.

## Five milestones (gated)

### M0 — Machine and repository baseline
**Goal:** clean, reproducible development environment on the MacBook.

Tasks:
- Inspect macOS/Apple Silicon, available RAM/disk, Xcode CLT, Homebrew, Git, Rust, Python, Node, pnpm, uv.
- Create Git repo, `.gitignore`, `pyproject.toml`, Cargo workspace, Vite React app only after environment checks.
- Add formatting/lint/test commands and a single `make check`.
- Capture machine profile without collecting personal identifiers.

Acceptance:
- `./scripts/check_environment.sh` produces a clear report.
- Rust hello-world test, Python import/test, frontend dev server all work.
- `make check` runs and returns success.
- No dataset/GPU required.

### M1 — Connectome data foundation and explorer
**Goal:** show real, cited fly connectome data and navigate a small selected subgraph.

Tasks:
- Choose the appropriate FlyWire/Codex dataset and snapshot. Record dataset/version and citation before download.
- Prefer official static downloadable files for bulk analysis. Do not scrape Codex pages.
- Build a small import pipeline for a bounded sample/subgraph.
- Normalize neuron IDs, annotations, synapses/edges, and provenance.
- Rust API serves typed graph data; frontend renders a small interactive network.
- Add search by neuron ID/name/type only where source supports it.

Acceptance:
- UI displays a real dataset-derived subgraph.
- Every displayed record can be traced to dataset + snapshot + source file.
- Search/select/inspect works.
- No invented neuron labels or synthetic values presented as biological facts.
- Data license/citation is documented.

### M2 — Embodied fly simulation
**Goal:** run NeuroMechFly/FlyGym locally and display actual simulation state.

Tasks:
- Pin a FlyGym v2 release; verify API against current docs.
- First run the upstream interactive viewer and a minimal scripted example before custom integration.
- Wrap simulator in a Python adapter with reset/step/state/close lifecycle.
- Expose state to Rust over localhost HTTP/WebSocket.
- Display fly, environment, joints/contacts/sensors supported by the simulator.
- Keep brain/connectome integration explicitly modular: do not claim a full connectome-to-motor controller unless implemented and validated.

Acceptance:
- One documented command starts the simulator adapter.
- Reset/step/stop works; failures and shutdown are handled.
- UI shows live or recorded simulation with correct label.
- Stable session IDs and timestamps; no UI-thread blocking.
- CPU mode works on the Mac.

### M3 — Neural activity and perturbation experiments
**Goal:** create repeatable experiments that change a documented input/parameter and quantify outcomes.

Tasks:
- Select one scientifically supportable neural/sensorimotor question.
- Identify a model whose implementation and parameters are available; do not invent a fly brain model.
- Build baseline and perturbation conditions, controlled seeds, repetitions, and configuration capture.
- Plot behavior/kinematics and relevant neural/model outputs where available.
- Add experiment comparison and export.

Acceptance:
- A clean rerun reproduces the experiment within stated tolerances.
- Baseline vs perturbation is compared with sample count, uncertainty, and limitations.
- Code distinguishes simulator outputs from connectome measurements and hypotheses.
- No claim of biological causality beyond the model's scope.

### M4 — Closed-loop interaction and robustness
**Goal:** connect user actions or supported sensory input to the simulation and evaluate behavior under disturbances.

Tasks:
- Add keyboard/gamepad controls first; later support a validated sensor/controller.
- Implement bounded event flow, watchdog, stop/reset, and explicit control authority.
- Test latency, dropped events, reconnect, pause/resume, and environment variation.
- Add experiment replay and session comparison.

Acceptance:
- Control loop is observable and can be stopped safely.
- Latency is measured end-to-end, not inferred from model inference time.
- Failure injection and recovery tests pass.

### M5 — Separate EEG/BCI extension (optional, distinct dataset)
**Goal:** demonstrate a conventional EEG decoding pipeline as a separate module.

Tasks:
- Select a dataset and decoder with a real, documented checkpoint if the project specification requires pretrained inference.
- If no verified checkpoint is available, stop and propose an explicit scope change; do not pretend a training artifact is pretrained.
- Evaluate held-out subjects/sessions, drift/noise robustness, calibration, false activations, and latency.
- Send decoded intent to a safe simulated UI/robot task, not directly into fly neural circuitry.

Acceptance:
- Dataset and model provenance documented.
- Real vs replayed vs synthetic input clearly identified.
- Subject/session split avoids leakage.
- End-to-end latency and failure behavior measured.

## Performance strategy

### Smoothness budget
- UI rendering: aim for 60 FPS on the local Mac in the normal scene.
- Send state updates at a bounded rate (start at 20–30 Hz); render independently at display refresh.
- Keep only a bounded rolling history in memory.
- Use typed compact payloads and avoid sending full connectome graphs every frame.
- Precompute graph layouts/geometry; update only changed buffers.
- Use instancing/LOD for repeated geometry.
- Measure FPS, frame time p50/p95, API latency, simulation step time, and queue depth.

### MacBook-first policy
Run locally:
- Rust services and tests.
- React/Three.js dashboard.
- FlyGym CPU simulation and small experiments.
- Connectome subgraph processing and preprocessing.
- Small model inference if compatible.

Use cloud GPU only if:
- The chosen FlyGym Warp/MJWarp backend is supported by the cloud OS/GPU and gives measured speedup.
- A selected ML model needs CUDA/VRAM beyond local capacity.
- A large batch of simulations is embarrassingly parallel.

Do not assume the Mac's Apple GPU can run CUDA. Do not provision cloud compute before a benchmark and explicit cost approval.

## GPU decision gates

| Workload | Local Mac | Cloud GPU |
|---|---|---|
| Rust/UI/API | Yes | No |
| Connectome metadata and small graph | Yes | No |
| FlyGym CPU baseline | Start here | Not initially |
| FlyGym Warp/MJWarp | Verify Apple Silicon support; do not assume | Likely Linux NVIDIA path; validate exact release |
| Large parallel experiments | Small batch locally | Consider |
| PyTorch/JAX large training | Small models only | Consider |
| 3D visualization | Yes | No; render locally |

## MCP policy

MCP is optional. It is not required to compile, run, test, or visualize NeuroPilot.

Recommended:
1. **OpenAI Developer Docs MCP** — read-only documentation lookup for Codex/OpenAI features. Add with:
   `codex mcp add openaiDeveloperDocs --url https://developers.openai.com/mcp`
2. **GitHub MCP** — optional if Codex should create issues, inspect PRs, or work with GitHub remotely. Keep write permissions limited.
3. **No FlyWire MCP required** — use official dataset downloads and documented Python APIs. Avoid giving an agent broad credentials when a local dataset file is enough.
4. **No GPU MCP required** — provision GPU machines manually or via a reviewed script after approval.

Do not install a generic “browser MCP”, filesystem MCP, or shell MCP just to make local development work. Codex already works in the local repository; unnecessary MCP servers increase attack surface.

## End-to-end developer pipeline

1. **Plan:** state milestone, hypothesis, data source, expected artifact, acceptance tests.
2. **Research:** verify official docs/API/version and dataset terms.
3. **Design:** update `docs/ARCHITECTURE.md` or an ADR for meaningful decisions.
4. **Implement:** small vertical slice, no speculative abstractions.
5. **Test:** unit → integration → smoke → benchmark.
6. **Run:** launch all local services with one documented command.
7. **Observe:** structured logs, session ID, FPS, latency, queue depth, errors.
8. **Review:** use `$experiment-review`; inspect diff and scientific claims.
9. **Record:** update milestone checklist, provenance, screenshots/results.
10. **Gate:** ask user to verify before next milestone.

## First Codex task

Paste this into Codex from the repository root:

> Read AGENTS.md, plan.md, skills.md, and README.md. We are at M0 only. Inspect the Mac environment and repository without changing files first. Report OS/architecture, available RAM/disk if accessible, installed versions of git, rustc/cargo, Python, uv, Node, pnpm, and Xcode Command Line Tools. Identify missing prerequisites. Do not install anything, create cloud resources, download datasets, or start later milestones. Then propose the smallest M0 setup diff and wait for approval.
