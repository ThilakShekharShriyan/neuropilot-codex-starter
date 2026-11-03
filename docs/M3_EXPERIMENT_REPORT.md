# M3 final evidence experiment report

Run date: 2026-11-03  
Artifact: `artifacts/m3_motor_perturbation.json` (ignored local output)  
Artifact SHA-256: `243da58e0b9faaf1f8defe24e34ab5293a68e7c785a3604d27c2d68d645bd809`

Canonical artifact SHA-256 (before the self-hash field):
`e826a90a081069d26a71c254e0086be399319dca87c373ac0331441b34cc6485`
Evidence Git commit: `97981693d6d932a8558007178cb9caf8aac3d9d3`
`uv.lock` SHA-256:
`b1d222c75e6935e6b4a32ff93a541446f4f0a67c027adea35a98fa2261253e84`

## Configuration

- FlyGym NeuroMechFly v2 CPU simulation
- Seed base: `0`
- Paired repetitions: `10`
- Predeclared seeds: `0,1,2,3,4,5,6,7,8,9`
- Physics steps per condition: `50`
- Alternating motor amplitude: `0.05`
- Comparison amplitudes: `0.025`, `0.05`, `0.1`
- Baseline: zero control vector
- Perturbation: alternating `+0.05/-0.05` over active-leg motor order

## Results

| Metric | Baseline mean | Perturbation mean | Paired delta mean | Sample SD of delta | 95% half-width | No variation |
|---|---:|---:|---:|---:|---:|---:|
| Root-body displacement (mm) | 0.1201725000 | 0.1201724634 | -0.0000000366 | 0.0000000000 | 0.0000000000 | yes |
| Maximum joint-speed L2 (rad/s) | 0.0000000000 | 0.6423854949 | 0.6423854949 | 0.0000000000 | 0.0000000000 | yes |
| Mean absolute joint angle (rad) | 0.0000000000 | 0.0001585108 | 0.0001585108 | 0.0000000000 | 0.0000000000 | yes |

The JSON artifact also includes a comparison export with one row per amplitude,
paired replicates, and the same uncertainty fields. The report is updated with
the exact values and SHA-256 after the local run; no generated artifact is
committed.

### Comparison sweep

| Amplitude | Displacement delta mean (mm) | Joint-speed delta mean (rad/s) | Joint-angle delta mean (rad) |
|---:|---:|---:|---:|
| 0.025 | -0.0000000352 | 0.3211927475 | 0.0000792554 |
| 0.050 | -0.0000000366 | 0.6423854949 | 0.0001585108 |
| 0.100 | 0.0000000625 | 1.2847709894 | 0.0003170219 |

All rows have `n=10` paired repetitions and zero sample standard deviation in
this deterministic CPU setup. That is repeatability, not evidence of zero
uncertainty in the underlying biological system.

Zero or near-zero sample standard deviations reflect deterministic repeated runs
under the current CPU setup; they are not evidence of biological certainty. The
sweep is intended to show whether the measured response changes across the
bounded engineering inputs, not to establish a biological dose-response law.

## Interpretation boundary

This is a simulated biomechanics result from FlyGym, not measured neural data,
neural dynamics, connectome behavior, or a causal biological claim. The motor
pattern is an engineering perturbation with no neuron or anatomical mapping.
The finite seed set and five-millisecond horizon are an M3 reproducibility and
sensitivity experiment, not a benchmark or generalization study. The per-seed
rows and effect-size summaries are in the JSON artifact; compact amplitude
summaries are in `artifacts/m3_motor_perturbation_comparison.csv`.
