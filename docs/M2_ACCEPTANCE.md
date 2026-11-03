# M2 CPU simulation acceptance checkpoint

Status: implementation checkpoint ready for review. GPU, cloud, RL, and
connectome-to-motor integration are not part of M2.

## Stack

1. Python FlyGym 2.1.1 CPU service on `127.0.0.1:8790`.
2. Rust loopback gateway on `127.0.0.1:8788`.
3. React dashboard talking only to the Rust origin.

```bash
PYTHONPATH=python uv run --project . python -m neuropilot_sim.server --port 8790
cargo run -p neuro-api --example m2_server -- data/normalized/fafb_v783 8788
pnpm --dir apps/dashboard dev --host 127.0.0.1
```

## Lifecycle contract

- `reset` returns a neutral, `simulated-live` state and resets session-scoped
  step telemetry.
- `step` advances a bounded number of CPU physics steps and returns state plus
  measured step latency.
- `state` and `metrics` are read-only and bounded.
- `restart` creates a fresh session ID and resets counters without restarting
  the Rust process.
- `close` transitions the simulation to `closed`; later state/step requests
  return a stable conflict response.
- SIGINT/SIGTERM run the server shutdown path without deadlocking, close the
  listening socket, and release the simulator through its context manager.

## Observability

Session responses include `session_id`, lifecycle status, simulation time,
step count, and last-step latency. Metrics include request/error/reset/step
counters. The dashboard polls state every five seconds and enters a degraded
state on failed polls, recovering on a later successful poll.

The measured local gateway baseline was 30 sequential reset/step requests:
p50 `1.16 ms`, p95 `3.25 ms`. This is an engineering baseline, not a
scientific or performance claim.

## Scientific boundary

All simulator responses are labeled `simulated-live`. Body positions are
FlyGym simulation state in millimetres, not connectome coordinates. The M1
FAFB graph remains observed source-backed data and is not used as a claimed
brain controller.

## Verification

- Python: 78 tests passed.
- Rust: 21 tests passed.
- Ruff, formatting, Clippy, frontend typecheck/build passed.
- Subprocess signal regression passed for clean exit, shutdown marker, and
  closed port.
- Restart, reconnect, timeout, malformed response, closed-session, and
  concurrent telemetry paths are covered.
