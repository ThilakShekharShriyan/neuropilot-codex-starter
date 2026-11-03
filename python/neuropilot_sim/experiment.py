"""Reproducible paired M3 motor-perturbation experiment."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import platform
import statistics
import subprocess
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from .adapter import FlySimulation, FlySimulationConfig


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    seed: int = 0
    repetitions: int = 10
    steps: int = 50
    amplitude: float = 0.05
    comparison_amplitudes: tuple[float, ...] = (0.025, 0.05, 0.1)
    seed_list: tuple[int, ...] | None = None

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
        if self.seed_list is not None:
            if len(self.seed_list) != self.repetitions:
                raise ValueError("seed_list length must equal repetitions")
            if len(set(self.seed_list)) != len(self.seed_list):
                raise ValueError("seed_list must contain distinct seeds")

    def seeds(self) -> tuple[int, ...]:
        if self.seed_list is not None:
            return self.seed_list
        return tuple(self.seed + index for index in range(self.repetitions))


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


def _summary(rows: list[dict[str, float]]) -> dict[str, dict[str, float | int | bool]]:
    metric_names = tuple(rows[0])
    return {
        name: _uncertainty([row[name] for row in rows])
        for name in metric_names
    }


def _uncertainty(values: list[float]) -> dict[str, float | int | bool]:
    mean = statistics.fmean(values)
    sample_stddev = statistics.stdev(values) if len(values) > 1 else 0.0
    standard_error = sample_stddev / math.sqrt(len(values))
    return {
        "n": len(values),
        "mean": mean,
        "sample_stddev": sample_stddev,
        "standard_error": standard_error,
        "ci95_half_width": 1.96 * standard_error,
        "no_variation_observed": sample_stddev == 0.0,
    }


def _effect_sizes(rows: list[dict[str, float]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for name in rows[0]:
        values = [row[name] for row in rows]
        mean = statistics.fmean(values)
        sample_stddev = statistics.stdev(values) if len(values) > 1 else 0.0
        result[name] = {
            "standardized_mean_delta": (
                mean / sample_stddev if sample_stddev > 0.0 else None
            ),
            "method": "paired mean delta divided by sample standard deviation",
            "no_variation_observed": sample_stddev == 0.0,
        }
    return result


def _paired_runs(config: ExperimentConfig) -> tuple[list[dict[str, float]], list[dict[str, float]]]:
    seeds = config.seeds()
    baseline = [
        _run_condition(config, seed, False) for seed in seeds
    ]
    perturbation = [
        _run_condition(config, seed, True) for seed in seeds
    ]
    return baseline, perturbation


def _per_seed(
    seeds: tuple[int, ...],
    baseline: list[dict[str, float]],
    perturbation: list[dict[str, float]],
) -> list[dict[str, object]]:
    rows = []
    for seed, base, perturb in zip(seeds, baseline, perturbation, strict=True):
        rows.append(
            {
                "seed": seed,
                "baseline": base,
                "perturbation": perturb,
                "paired_delta": {name: perturb[name] - base[name] for name in base},
            }
        )
    return rows


def _provenance() -> dict[str, object]:
    project_root = Path(__file__).resolve().parents[2]
    try:
        git_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=project_root, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        git_commit = "unknown"
    lockfile = project_root / "uv.lock"
    lockfile_hash = hashlib.sha256(lockfile.read_bytes()).hexdigest() if lockfile.exists() else None
    packages = {}
    for package in ("flygym", "mujoco", "httpx", "numpy"):
        try:
            packages[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            packages[package] = None
    return {
        "git_commit": git_commit,
        "lockfile_sha256": lockfile_hash,
        "dependency_versions": packages,
        "artifact_sha256_scope": "canonical JSON before the artifact_sha256 field is added",
    }


def run_experiment(config: ExperimentConfig) -> dict[str, object]:
    seeds = config.seeds()
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
                "seed_list": list(seeds),
                "per_seed": _per_seed(seeds, comparison_baseline, comparison_perturbation),
                "paired_deltas": {
                    "replicates": comparison_deltas,
                    "summary": _summary(comparison_deltas),
                    "effect_sizes": _effect_sizes(comparison_deltas),
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
        "config": {**asdict(config), "seed_list": list(seeds)},
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
        "per_seed": _per_seed(seeds, baseline, perturbation),
        "paired_deltas": {
            "replicates": deltas,
            "summary": _summary(deltas),
            "effect_sizes": _effect_sizes(deltas),
        },
        "comparison": comparison,
        "provenance": _provenance(),
        "limitations": [
            "simulated biomechanics only; no neural dynamics or connectome controller",
            "short horizon and finite CPU seed sample",
            "engineering control pattern is not an anatomical mapping",
        ],
    }


def write_comparison_csv(result: dict[str, object], path: Path) -> None:
    rows = []
    for comparison in result["comparison"]:
        summary = comparison["paired_deltas"]["summary"]
        effects = comparison["paired_deltas"]["effect_sizes"]
        for metric, values in summary.items():
            rows.append(
                {
                    "amplitude": comparison["amplitude"],
                    "metric": metric,
                    "n": values["n"],
                    "mean": values["mean"],
                    "sample_stddev": values["sample_stddev"],
                    "standard_error": values["standard_error"],
                    "ci95_half_width": values["ci95_half_width"],
                    "standardized_mean_delta": effects[metric]["standardized_mean_delta"],
                    "no_variation_observed": values["no_variation_observed"],
                }
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_artifact(result: dict[str, object], path: Path) -> tuple[str, str]:
    canonical = json.loads(json.dumps(result, sort_keys=True))
    canonical["provenance"].pop("artifact_sha256", None)
    canonical_bytes = (json.dumps(canonical, indent=2, sort_keys=True) + "\n").encode()
    canonical_hash = hashlib.sha256(canonical_bytes).hexdigest()
    result["provenance"]["artifact_sha256"] = canonical_hash
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(result, indent=2, sort_keys=True) + "\n").encode()
    path.write_bytes(payload)
    final_hash = hashlib.sha256(payload).hexdigest()
    path.with_suffix(path.suffix + ".sha256").write_text(
        f"{final_hash}  {path.name}\n", encoding="utf-8"
    )
    return canonical_hash, final_hash


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the M3 paired motor perturbation experiment"
    )
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/m3_motor_perturbation.json")
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--repetitions", type=int, default=10)
    parser.add_argument("--steps", type=int, default=50)
    parser.add_argument("--amplitude", type=float, default=0.05)
    parser.add_argument(
        "--comparison-amplitudes",
        default="0.025,0.05,0.1",
        help="comma-separated positive amplitudes for the comparison sweep",
    )
    parser.add_argument(
        "--seeds",
        help="comma-separated predeclared seeds; length must match --repetitions",
    )
    parser.add_argument(
        "--comparison-csv",
        type=Path,
        default=Path("artifacts/m3_motor_perturbation_comparison.csv"),
    )
    args = parser.parse_args()
    seed_list = (
        tuple(int(value) for value in args.seeds.split(",") if value)
        if args.seeds
        else None
    )
    result = run_experiment(
        ExperimentConfig(
            seed=args.seed,
            repetitions=args.repetitions,
            steps=args.steps,
            amplitude=args.amplitude,
            comparison_amplitudes=tuple(
                float(value) for value in args.comparison_amplitudes.split(",") if value
            ),
            seed_list=seed_list,
        )
    )
    canonical_hash, final_hash = write_artifact(result, args.output)
    write_comparison_csv(result, args.comparison_csv)
    print(json.dumps({"canonical_sha256": canonical_hash, "artifact_sha256": final_hash}))
    print(json.dumps(result["paired_deltas"]["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
