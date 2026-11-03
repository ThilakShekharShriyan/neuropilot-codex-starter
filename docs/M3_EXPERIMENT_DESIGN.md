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
- **Design:** paired repetitions use the same predeclared seed in both
  conditions. The default seed list is `0,1,2,3,4,5,6,7,8,9`.
- **Default:** ten paired repetitions, fifty physics steps per run, primary
  amplitude `0.05`.
- **Comparison sweep:** amplitudes `0.025`, `0.05`, and `0.1`, using the same
  paired seeds and horizon. The sweep is a sensitivity comparison, not a
  parameter-fitting or dose-response claim.

## Metrics

- root-body displacement in millimetres from reset to the final state;
- maximum joint-speed L2 norm in radians/second;
- mean absolute joint angle in radians at the final state;
- paired perturbation-minus-baseline deltas, mean, sample standard deviation,
  standard error, and a descriptive 95% normal-approximation half-width;
- a machine-readable comparison export containing the per-amplitude paired
  replicates and uncertainty summaries.
- a CSV export with one row per amplitude and metric for compact downstream
  plotting.

The first body position is the FlyGym root-body segment in the model's documented
body-segment order. It is not a connectome coordinate.

## Provenance and limitations

Every result records FlyGym version, MuJoCo version, Python/platform versions,
configuration, seeds, actuator count, condition definition, comparison
amplitudes, exact Git commit, lockfile hash, dependency versions, and
`data_kind: simulated`. No FAFB graph values are used as motor inputs. The
runner explicitly reports whether no variation was observed across the tested
seeds. The standard error and 95% half-width are descriptive summaries of the
finite paired runs; they are not confidence guarantees for biology or for this
model outside the tested conditions. A short horizon and finite seed sample
provide an engineering sensitivity experiment, not a biological benchmark.
The runner does not imply causal generalization beyond this model.

## Reproduction

```bash
PYTHONPATH=python uv run --project . python -m neuropilot_sim.experiment \
  --output artifacts/m3_motor_perturbation.json \
  --comparison-csv artifacts/m3_motor_perturbation_comparison.csv
```

The output is a deterministic JSON export. Use `--comparison-amplitudes` with
a comma-separated positive list to reproduce a different bounded sensitivity
sweep without changing the simulator or introducing random parameter search.
