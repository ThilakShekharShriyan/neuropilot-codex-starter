# M3 initial experiment report

Run date: 2026-11-03  
Artifact: `artifacts/m3_motor_perturbation.json` (ignored local output)  
Artifact SHA-256: `f3f2cc7ed0ca3ac5ced90a163d345029f2e30bff58bdd7096cce469f21d3fd71`

## Configuration

- FlyGym NeuroMechFly v2 CPU simulation
- Seed base: `0`
- Paired repetitions: `3`
- Physics steps per condition: `50`
- Alternating motor amplitude: `0.05`
- Baseline: zero control vector
- Perturbation: alternating `+0.05/-0.05` over active-leg motor order

## Results

| Metric | Baseline mean | Perturbation mean | Paired delta mean | Sample SD of delta |
|---|---:|---:|---:|---:|
| Root-body displacement (mm) | 0.1201725000 | 0.1201724634 | -0.0000000366 | 0.0 |
| Maximum joint-speed L2 (rad/s) | 0.0000000000 | 0.6423854949 | 0.6423854949 | 0.0 |
| Mean absolute joint angle (rad) | 0.0000000000 | 0.0001585108 | 0.0001585108 | 0.0 |

The zero sample standard deviations reflect deterministic repeated runs under
the current short CPU setup; they are not evidence of biological certainty.
The displacement result is effectively unchanged over this short horizon while
joint motion responds to the control input.

## Interpretation boundary

This is a simulated biomechanics result from FlyGym, not measured neural data,
neural dynamics, connectome behavior, or a causal biological claim. The motor
pattern is an engineering perturbation with no neuron or anatomical mapping.
The small sample and five-millisecond horizon are an M3 reproducibility smoke
experiment, not a benchmark or generalization study.
