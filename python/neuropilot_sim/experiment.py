"""Reproducible paired M3 motor-perturbation experiment."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import platform
import statistics
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from .adapter import FlySimulation, FlySimulationConfig


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    seed: int = 0
    repetitions: int = 3
    steps: int = 50
    amplitude: float = 0.05
    comparison_amplitudes: tuple[float, ...] = (0.025, 0.05, 0.1)

    def __post_init__(self) -> None:
        if self.repetitions < 2:
            raise ValueError("repetitions must be at least 2")
        if self.steps < 1:
            raise ValueError("steps must be positive")
        if not math.isfinite(self.amplitude) or self.amplitude <= 0.0:
            raise ValueError("amplitude must be finite and positive")
        if not self.comparison_amplitudes or any(
            not math.isfinite(value) or value <= 0.0 for value in self.comparison_amplitudes
        ):
            raise ValueError("comparison amplitudes must be finite and positive")


def _metric(
    initial: tuple[float, ...],
    final: tuple[float, ...],
    velocities: tuple[float, ...],
    angles: tuple[float, ...],
) -> dict[str, float]:
    return {
        "root_body_displacement_mm": math.dist(initial, final),
        "max_joint_speed_l2": math.sqrt(sum(value * value for value in velocities)),
        "mean_abs_joint_angle_rad": statistics.fmean(abs(value) for value in angles),
    }


def _run_condition(config: ExperimentConfig, seed: int, perturb: bool) -> dict[str, float]:
    with FlySimulation(FlySimulationConfig(seed=seed)) as simulation:
        initial = simulation.reset()
        control = None
        if perturb:
            control = [
                config.amplitude if index % 2 == 0 else -config.amplitude
                for index in range(simulation.control_size)
            ]
        final = initial
        max_speed = 0.0
        for _ in range(config.steps):
            final = simulation.step(control)
            max_speed = max(
                max_speed,
                math.sqrt(sum(value * value for value in final.joint_velocities)),
            )
        metrics = _metric(
            initial.body_positions[0],
            final.body_positions[0],
            final.joint_velocities,
            final.joint_angles,
        )
        metrics["max_joint_speed_l2"] = max_speed
        return metrics


def _summary(rows: list[dict[str, float]]) -> dict[str, dict[str, float | int]]:
    metric_names = tuple(rows[0])
    return {
        name: _uncertainty([row[name] for row in rows])
        for name in metric_names
    }


def _uncertainty(values: list[float]) -> dict[str, float | int]:
    mean = statistics.fmean(values)
    sample_stddev = statistics.stdev(values) if len(values) > 1 else 0.0
    standard_error = sample_stddev / math.sqrt(len(values))
    return {
        "n": len(values),
        "mean": mean,
        "sample_stddev": sample_stddev,
        "standard_error": standard_error,
        "ci95_half_width": 1.96 * standard_error,
    }


def _paired_runs(config: ExperimentConfig) -> tuple[list[dict[str, float]], list[dict[str, float]]]:
    baseline = [
        _run_condition(config, config.seed + index, False)
        for index in range(config.repetitions)
    ]
    perturbation = [
        _run_condition(config, config.seed + index, True)
        for index in range(config.repetitions)
    ]
    return baseline, perturbation


def run_experiment(config: ExperimentConfig) -> dict[str, object]:
    baseline, perturbation = _paired_runs(config)
    deltas = [
        {name: perturb[name] - base[name] for name in base}
        for base, perturb in zip(baseline, perturbation, strict=True)
    ]
    comparison = []
    for amplitude in config.comparison_amplitudes:
        comparison_config = replace(config, amplitude=amplitude)
        comparison_baseline, comparison_perturbation = _paired_runs(comparison_config)
        comparison_deltas = [
            {name: perturb[name] - base[name] for name in base}
            for base, perturb in zip(
                comparison_baseline, comparison_perturbation, strict=True
            )
        ]
        comparison.append(
            {
                "amplitude": amplitude,
                "paired_deltas": {
                    "replicates": comparison_deltas,
                    "summary": _summary(comparison_deltas),
                },
            }
        )
    return {
        "schema_version": 1,
        "data_kind": "simulated",
        "question": "bounded alternating leg-motor perturbation versus zero-control baseline",
        "model": {
            "name": "FlyGym NeuroMechFly v2 CPU Simulation",
            "flygym_version": importlib.metadata.version("flygym"),
            "mujoco_version": importlib.metadata.version("mujoco"),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
        "config": asdict(config),
        "actuator_definition": "active-leg motor actuator order from FlyGym",
        "conditions": {
            "baseline": "zero control vector",
            "perturbation": "alternating +amplitude/-amplitude control vector",
        },
        "baseline": {"replicates": baseline, "summary": _summary(baseline)},
        "perturbation": {
            "replicates": perturbation,
            "summary": _summary(perturbation),
        },
        "paired_deltas": {"replicates": deltas, "summary": _summary(deltas)},
        "comparison": comparison,
        "limitations": [
            "simulated biomechanics only; no neural dynamics or connectome controller",
            "short horizon and small sample count",
            "engineering control pattern is not an anatomical mapping",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the M3 paired motor perturbation experiment"
    )
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/m3_motor_perturbation.json")
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--steps", type=int, default=50)
    parser.add_argument("--amplitude", type=float, default=0.05)
    parser.add_argument(
        "--comparison-amplitudes",
        default="0.025,0.05,0.1",
        help="comma-separated positive amplitudes for the comparison sweep",
    )
    args = parser.parse_args()
    result = run_experiment(
        ExperimentConfig(
            seed=args.seed,
            repetitions=args.repetitions,
            steps=args.steps,
            amplitude=args.amplitude,
            comparison_amplitudes=tuple(
                float(value) for value in args.comparison_amplitudes.split(",") if value
            ),
        )
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result["paired_deltas"]["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
