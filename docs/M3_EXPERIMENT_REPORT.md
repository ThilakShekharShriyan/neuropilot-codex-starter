# M3 parameter-sweep experiment report

Run date: 2026-11-03  
Artifact: `artifacts/m3_motor_perturbation.json` (ignored local output)  
Artifact SHA-256: `43c1a5ec43b58ae1a90473aaf185ae7f03747f513b385b8bc8ba486018c7cd08`

## Configuration

- FlyGym NeuroMechFly v2 CPU simulation
- Seed base: `0`
- Paired repetitions: `3`
- Physics steps per condition: `50`
- Alternating motor amplitude: `0.05`
- Comparison amplitudes: `0.025`, `0.05`, `0.1`
- Baseline: zero control vector
- Perturbation: alternating `+0.05/-0.05` over active-leg motor order

## Results

| Metric | Baseline mean | Perturbation mean | Paired delta mean | Sample SD of delta | 95% half-width |
|---|---:|---:|---:|---:|---:|
| Root-body displacement (mm) | 0.1201725000 | 0.1201724634 | -0.0000000366 | 0.0000000000 | 0.0000000000 |
| Maximum joint-speed L2 (rad/s) | 0.0000000000 | 0.6423854949 | 0.6423854949 | 0.0000000000 | 0.0000000000 |
| Mean absolute joint angle (rad) | 0.0000000000 | 0.0001585108 | 0.0001585108 | 0.0000000000 | 0.0000000000 |

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

All rows have `n=3` paired repetitions and zero sample standard deviation in
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
The small sample and five-millisecond horizon are an M3 reproducibility smoke
experiment, not a benchmark or generalization study.
