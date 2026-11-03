# M3 experiment design: bounded motor perturbation

## Question

In the CPU NeuroMechFly v2 biomechanical model, does a small deterministic
alternating leg-motor input change short-horizon root-body displacement or joint
motion relative to a zero-control baseline?

This is a simulated biomechanics question. It is not a claim about neural
activity, connectome dynamics, biological causality, or a connectome-to-motor
controller.

## Conditions

- **Baseline:** a zero vector over the model's active-leg motor actuators.
- **Perturbation:** a bounded alternating `+amplitude/-amplitude` vector over
  the same actuator order. The pattern is an engineering control input, not an
  anatomical or neuron-specific mapping.
- **Design:** paired repetitions use the same seed in both conditions.
- **Default:** three repetitions, fifty physics steps per run, amplitude `0.05`.

## Metrics

- root-body displacement in millimetres from reset to the final state;
- maximum joint-speed L2 norm in radians/second;
- mean absolute joint angle in radians at the final state;
- paired perturbation-minus-baseline deltas, mean, and sample standard deviation.

The first body position is the FlyGym root-body segment in the model's documented
body-segment order. It is not a connectome coordinate.

## Provenance and limitations

Every result records FlyGym version, MuJoCo version, Python/platform versions,
configuration, seeds, actuator count, condition definition, and `data_kind:
simulated`. No FAFB graph values are used as motor inputs. A short horizon and
small sample count provide an engineering smoke experiment, not a biological
benchmark. The runner does not estimate uncertainty beyond paired sample
standard deviation and does not imply causal generalization beyond this model.

## Reproduction

```bash
PYTHONPATH=python uv run --project . python -m neuropilot_sim.experiment \
  --output artifacts/m3_motor_perturbation.json
```
