from __future__ import annotations

import pytest
from neuropilot_sim import FlySimulation, FlySimulationConfig


def test_cpu_simulation_reset_step_and_close_are_observable() -> None:
    with FlySimulation(FlySimulationConfig(seed=7, steps_per_command=2)) as simulation:
        initial = simulation.reset()
        stepped = simulation.step([0.0] * simulation.control_size)
        assert initial.time == 0.0
        assert stepped.time == pytest.approx(2e-4)
        assert len(initial.joint_angles) == 126
        assert len(initial.body_positions) > 0

    with pytest.raises(RuntimeError, match="closed"):
        simulation.state()


def test_control_shape_is_bounded() -> None:
    simulation = FlySimulation()
    try:
        simulation.reset()
        with pytest.raises(ValueError, match="control must contain"):
            simulation.step([])
    finally:
        simulation.close()


def test_configuration_rejects_invalid_steps() -> None:
    with pytest.raises(ValueError, match="steps_per_command"):
        FlySimulationConfig(steps_per_command=0)
