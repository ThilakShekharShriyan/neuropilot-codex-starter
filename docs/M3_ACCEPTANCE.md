# M3 acceptance evidence

## Scope

M3 evaluates a bounded, deterministic alternating leg-motor input in the CPU
FlyGym NeuroMechFly v2 model against a zero-control baseline. The output is
`simulated` biomechanics data. It is not neural data, connectome dynamics,
anatomical coordinates, a connectome-to-motor controller, or a biological
causality claim.

## Reproduction

From the repository root:

```bash
PYTHONPATH=python uv run --project . python -m neuropilot_sim.experiment \
  --output artifacts/m3_motor_perturbation.json \
  --comparison-csv artifacts/m3_motor_perturbation_comparison.csv
```

The default run uses ten paired repetitions, seeds `0` through `9`, fifty
physics steps, primary amplitude `0.05`, and comparison amplitudes `0.025`,
`0.05`, and `0.1`. The command writes an ignored JSON artifact, a SHA-256
sidecar, and a compact CSV export. A custom seed list must be explicit and have
the same length as `--repetitions`.

## Evidence run

The evidence run recorded:

- Git commit: `97981693d6d932a8558007178cb9caf8aac3d9d3`
- FlyGym: `2.1.1`
- MuJoCo: `3.16.0`
- Python: `3.12.14`
- NumPy: `2.5.4`
- HTTPX: `0.28.1`
- Platform: `macOS-26.7.2-arm64-arm-64bit`
- `uv.lock` SHA-256: `b1d222c75e6935e6b4a32ff93a541446f4f0a67c027adea35a98fa2261253e84`
- Canonical artifact SHA-256 (before the self-hash field): `e826a90a081069d26a71c254e0086be399319dca87c373ac0331441b34cc6485`
- Final JSON artifact SHA-256: `243da58e0b9faaf1f8defe24e34ab5293a68e7c785a3604d27c2d68d645bd809`

The ten distinct seeds produced identical baseline and perturbation metrics in
this simulator configuration. The result is therefore reported as deterministic
behavior with `no_variation_observed: true`; zero sample variance is not treated
as biological uncertainty. The amplitude sweep changes joint-speed and
joint-angle response magnitudes while displacement remains effectively near
zero over the short horizon.

## Acceptance checklist

- [x] Predeclared multi-seed paired execution
- [x] Seed-sensitivity check reports observed variation or deterministic behavior
- [x] Ten paired repetitions and existing amplitude sweep
- [x] Per-seed baseline, perturbation, and paired-delta rows
- [x] Effect-size summaries and descriptive uncertainty
- [x] Explicit no-variation flags
- [x] Compact CSV comparison export
- [x] Git, lockfile, dependency, platform, simulator, and configuration provenance
- [x] Artifact SHA-256 and reproducibility command
- [x] `make check` passes
- [x] No connectome-control, neural-dynamics, anatomical-coordinate, GPU, cloud,
  RL, or biological-causality claims

## Limitations

This is a short-horizon CPU simulation with a finite deterministic seed set and
an engineering control pattern. The descriptive standard errors and 95%
normal-approximation half-widths do not establish biological confidence
intervals. M4 remains separately gated.
