"""Narrow, deterministic lifecycle wrapper around FlyGym 2.1.1."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from flygym import Simulation
from flygym.anatomy import ActuatedDOFPreset, AxisOrder, JointPreset, Skeleton
from flygym.compose import ActuatorType, FlatGroundWorld, NeuroMechFly
from flygym.utils.math import Rotation3D


@dataclass(frozen=True)
class FlySimulationConfig:
    """Configuration captured with every M2 run."""

    seed: int = 0
    timestep: float = 1e-4
    spawn_position: tuple[float, float, float] = (0.0, 0.0, 5.0)
    steps_per_command: int = 1

    def __post_init__(self) -> None:
        if self.steps_per_command < 1:
            raise ValueError("steps_per_command must be positive")
        if self.timestep <= 0:
            raise ValueError("timestep must be positive")


@dataclass(frozen=True)
class FlyState:
    """Observed live simulator state, in FlyGym's millimetre/radian units."""

    time: float
    joint_angles: tuple[float, ...]
    joint_velocities: tuple[float, ...]
    body_positions: tuple[tuple[float, float, float], ...]


class FlySimulation:
    """Own a single CPU FlyGym simulation with explicit reset/step/close."""

    def __init__(self, config: FlySimulationConfig | None = None) -> None:
        self.config = config or FlySimulationConfig()
        self._simulation: Simulation | None = None
        self._fly_name = "nmf"
        self._control_size = 0
        self._closed = False
        self._build()

    @property
    def control_size(self) -> int:
        return self._control_size

    def _build(self) -> None:
        np.random.seed(self.config.seed)
        world = FlatGroundWorld()
        fly = NeuroMechFly(name=self._fly_name)
        skeleton = Skeleton(
            axis_order=AxisOrder.DONTCARE,
            joint_preset=JointPreset.ALL_BIOLOGICAL,
        )
        fly.add_joints(skeleton)
        actuated = skeleton.get_actuated_dofs_from_preset(
            ActuatedDOFPreset.LEGS_ACTIVE_ONLY
        )
        fly.add_actuators(actuated, ActuatorType.MOTOR)
        world.add_fly(
            fly,
            spawn_position=self.config.spawn_position,
            spawn_rotation=Rotation3D("quat", (1.0, 0.0, 0.0, 0.0)),
        )
        self._simulation = Simulation(world, timestep=self.config.timestep)
        self._control_size = self._simulation.mj_model.nu

    def _require_open(self) -> Simulation:
        if self._closed or self._simulation is None:
            raise RuntimeError("simulation is closed")
        return self._simulation

    def reset(self) -> FlyState:
        simulation = self._require_open()
        simulation.reset()
        simulation.forward()
        return self.state()

    def step(self, control: Sequence[float] | None = None) -> FlyState:
        simulation = self._require_open()
        if control is not None:
            if len(control) != self._control_size:
                raise ValueError(
                    f"control must contain {self._control_size} values, got {len(control)}"
                )
            simulation.mj_data.ctrl[:] = np.asarray(control, dtype=np.float64)
        for _ in range(self.config.steps_per_command):
            simulation.step()
        return self.state()

    def state(self) -> FlyState:
        simulation = self._require_open()
        return FlyState(
            time=float(simulation.mj_data.time),
            joint_angles=tuple(
                float(value) for value in simulation.get_joint_angles(self._fly_name)
            ),
            joint_velocities=tuple(
                float(value)
                for value in simulation.get_joint_velocities(self._fly_name)
            ),
            body_positions=tuple(
                tuple(float(value) for value in position)
                for position in simulation.get_body_positions(self._fly_name)
            ),
        )

    def close(self) -> None:
        self._simulation = None
        self._closed = True

    def __enter__(self) -> FlySimulation:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()
