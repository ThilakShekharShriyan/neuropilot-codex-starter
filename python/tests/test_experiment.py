from __future__ import annotations

import pytest
from neuropilot_sim.experiment import (
    ExperimentConfig,
    run_experiment,
    write_artifact,
    write_comparison_csv,
)


def test_paired_experiment_is_source_labeled_and_reproducible() -> None:
    config = ExperimentConfig(
        seed=3,
        repetitions=2,
        steps=2,
        amplitude=0.05,
        comparison_amplitudes=(0.025, 0.05),
    )
    first = run_experiment(config)
    second = run_experiment(config)
    assert first["data_kind"] == "simulated"
    assert first["config"] == second["config"]
    assert first["paired_deltas"] == second["paired_deltas"]
    assert first["comparison"] == second["comparison"]
    assert [row["amplitude"] for row in first["comparison"]] == [0.025, 0.05]
    assert [row["seed"] for row in first["per_seed"]] == [3, 4]
    uncertainty = first["paired_deltas"]["summary"]["max_joint_speed_l2"]
    assert uncertainty["n"] == 2
    assert "standard_error" in uncertainty
    assert "ci95_half_width" in uncertainty
    assert uncertainty["no_variation_observed"] is True
    assert first["paired_deltas"]["effect_sizes"]["max_joint_speed_l2"][
        "standardized_mean_delta"
    ] is None
    assert len(first["baseline"]["replicates"]) == 2
    assert first["model"]["flygym_version"] == "2.1.1"


def test_experiment_config_rejects_unsafe_inputs() -> None:
    with pytest.raises(ValueError, match="repetitions"):
        ExperimentConfig(repetitions=1)
    with pytest.raises(ValueError, match="amplitude"):
        ExperimentConfig(amplitude=float("nan"))
    with pytest.raises(ValueError, match="comparison amplitudes"):
        ExperimentConfig(comparison_amplitudes=(0.05, float("inf")))
    with pytest.raises(ValueError, match="seed_list length"):
        ExperimentConfig(repetitions=2, seed_list=(1,))


def test_seed_list_and_exports_are_explicit(tmp_path) -> None:
    config = ExperimentConfig(
        repetitions=2,
        steps=2,
        seed_list=(11, 29),
        comparison_amplitudes=(0.05,),
    )
    result = run_experiment(config)
    assert result["config"]["seed_list"] == [11, 29]
    assert result["provenance"]["git_commit"]
    assert result["provenance"]["lockfile_sha256"]
    assert all(row["seed"] in (11, 29) for row in result["comparison"][0]["per_seed"])
    artifact = tmp_path / "experiment.json"
    csv_path = tmp_path / "comparison.csv"
    canonical_hash, artifact_hash = write_artifact(result, artifact)
    write_comparison_csv(result, csv_path)
    assert len(canonical_hash) == 64
    assert len(artifact_hash) == 64
    assert artifact.with_suffix(".json.sha256").exists()
    assert "amplitude,metric,n,mean" in csv_path.read_text(encoding="utf-8")
