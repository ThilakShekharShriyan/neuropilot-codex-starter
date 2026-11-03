# M2 CPU simulation architecture

Status: M2 foundation implemented; embodied simulation integration remains under
review.

## Scope

M2 starts with one live CPU NeuroMechFly v2 simulation. It is a biomechanical
simulation and is not claimed to be a full connectome-driven brain model. The
FAFB connectome remains a separate observed-data artifact from M1.

FlyGym is pinned to `2.1.1`, the current v2 release used here. FlyGym 2.x is
not API-compatible with FlyGym 1.x. The official installation documentation
supports Python 3.12 and recommends omitting the Warp extra on machines without
an NVIDIA GPU:

- https://neuromechfly.org/2.1.1/installation/
- https://github.com/NeLy-EPFL/flygym/releases/tag/v2.1.1

## Python adapter

`python/neuropilot_sim/adapter.py` owns the simulator lifecycle:

- `reset()` restores the neutral keyframe and returns observed state;
- `step(control)` validates a bounded motor-control vector and advances a fixed
  number of physics steps;
- `state()` returns time, joint angles/velocities, and body-segment positions;
- `close()` is idempotent and makes later use fail explicitly.

The adapter uses the CPU `Simulation`, `NeuroMechFly`, `FlatGroundWorld`,
biological joints, and active-leg motor actuators. It uses deterministic seed
capture and a fixed timestep. State units follow FlyGym: millimetres, radians,
and seconds.

## Boundaries

Python remains the owner of MuJoCo/FlyGym and scientific state. Rust should
later expose a bounded localhost session service; it must not reimplement the
simulator. The frontend must label frames as live simulation state and must not
present body positions as connectome/anatomical coordinates.

GPU Warp, reinforcement learning, connectome-to-motor claims, and cloud
provisioning are explicitly out of scope for this first M2 slice.

## Reproduction

```bash
uv sync
PYTHONPATH=python uv run --project . pytest -q python/tests/test_sim_adapter.py
```
