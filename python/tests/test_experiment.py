from __future__ import annotations

import pytest
from neuropilot_sim.experiment import ExperimentConfig, run_experiment


def test_paired_experiment_is_source_labeled_and_reproducible() -> None:
    config = ExperimentConfig(seed=3, repetitions=2, steps=2, amplitude=0.05)
    first = run_experiment(config)
    second = run_experiment(config)
    assert first["data_kind"] == "simulated"
    assert first["config"] == second["config"]
    assert first["paired_deltas"] == second["paired_deltas"]
    assert len(first["baseline"]["replicates"]) == 2
    assert first["model"]["flygym_version"] == "2.1.1"


def test_experiment_config_rejects_unsafe_inputs() -> None:
    with pytest.raises(ValueError, match="repetitions"):
        ExperimentConfig(repetitions=1)
    with pytest.raises(ValueError, match="amplitude"):
        ExperimentConfig(amplitude=float("nan"))
