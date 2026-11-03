# NeuroPilot Skills — Codex workflow catalogue

Codex project skills live under `.agents/skills/<skill-name>/SKILL.md`. This index explains when to invoke them; the actual skill file contains the executable workflow instructions.

## Available skills

### `$neuro-research`
Use for connectome data, FlyWire/Codex datasets, neuron metadata, scientific literature, data provenance, and experiment design. Must cite source datasets and preserve dataset snapshot/version.

### `$flygym-integration`
Use when integrating NeuroMechFly/FlyGym or MuJoCo. Must first verify installed FlyGym version/API, create the smallest runnable example, and keep simulator code in Python.

### `$rust-service`
Use when implementing Rust domain types, event gateway, WebSocket/HTTP APIs, orchestration, telemetry, and robust async services. Must include cancellation, timeouts, bounded channels, validation, and tests.

### `$visualization-performance`
Use when implementing React/Three.js visualization or optimizing frame rate. Must profile before optimizing, cap history sizes, avoid per-frame allocations, and preserve scientific labels.

### `$experiment-review`
Use before accepting a milestone. Verify reproducibility, configuration capture, provenance, metrics, test results, and whether claims are supported by outputs.

## General workflow
- Select one skill per focused task; do not load every skill for every change.
- Skills do not replace `AGENTS.md` or milestone acceptance criteria.
- A skill may request additional tools, but never install an MCP server, dependency, or cloud resource without approval.
