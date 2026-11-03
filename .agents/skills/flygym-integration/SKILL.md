---
name: flygym-integration
description: Use when installing, testing, integrating, or extending NeuroMechFly/FlyGym or MuJoCo simulation in NeuroPilot.
---

# FlyGym integration workflow

1. Inspect installed FlyGym version and current official docs before coding.
2. Confirm whether the task targets FlyGym 2.x; do not mix 1.x and 2.x APIs.
3. First run the upstream interactive viewer or minimal official example unchanged.
4. Record Python, FlyGym, MuJoCo, OS, and backend versions.
5. Build a narrow Python adapter with reset, step, state, and close lifecycle.
6. Keep simulation and numerical work out of Rust unless there is a measured reason.
7. Add deterministic seeds and a smoke test.
8. Handle exceptions, shutdown, timeouts, and invalid commands.
9. Label replayed frames versus live simulation.
10. Start CPU-first; only investigate GPU after profiling and compatibility checks.
