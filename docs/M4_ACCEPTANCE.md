# M4 acceptance evidence

Status: implementation evidence collected; final milestone acceptance remains
pending review.

## Scope and boundary

M4 provides bounded keyboard and optional gamepad commands for the CPU
NeuroMechFly simulator. It is explicitly `simulated-live` engineering control.
It is not a connectome controller, neural-dynamics system, anatomical control
signal, biological motor claim, GPU workload, or physical-device interface.

## Reproduction

Run the Python simulator first:

```bash
PYTHONPATH=python uv run --project . python -m neuropilot_sim.server --port 8790
```

For a bounded Rust control smoke test, use the tiny synthetic graph fixture so
the test does not load the large normalized connectome artifact:

```bash
NEUROPILOT_SIM_URL=http://127.0.0.1:8790 \
  cargo run -p neuro-api --example m4_server -- 8788
```

The browser or a local client then uses the Rust origin at
`http://127.0.0.1:8788`. The normal M2 `m2_server` command remains available
for the real normalized artifact, but is not needed to measure control latency.

## Evidence run

The loopback smoke run used 20 sequential active keyboard-source inputs after
an explicit control-session creation and resume. It measured:

- client request round-trip p50: **1.015 ms**;
- client request minimum/maximum: **0.915 / 1.152 ms**;
- Rust-to-Python control latency reported by the service: **0.769 ms** for the
  last input;
- accepted events: `20`;
- rejected events: `0`;
- dropped events: `0`;
- coalesced events: `0`;
- maximum observed queue depth: `1`;
- queue depth after forwarding: `0`;
- watchdog trips during the active run: `0`.

These are one local CPU smoke sample, not a performance target, safety
certification, or scientific measurement. The queue is intentionally drained
immediately in this slice, so the observed maximum depth of one does not
represent burst saturation behavior.

## Failure and safety evidence

- Python tests cover active resume, pause, stop, reset, watchdog neutralization,
  stale control sessions after restart, malformed controls, neutral commands,
  and idle gamepad zero-input watchdog behavior.
- Rust tests cover bounded channel mapping, stale sequence/session rejection,
  malformed simulator responses, timeout, refusal, remote close, and gateway
  reconnect behavior.
- Keyboard focus loss and gamepad disconnect send neutral input.
- Reconnect/reset creates a fresh control session and requires explicit resume.
- Neutral input does not refresh the watchdog; all-zero gamepad input is treated
  as neutral defensively in Python.

## Validation command and result

```bash
make check
```

Latest verified result:

- Python: 89 tests passed
- Rust: 26 tests passed
- Ruff, formatting, Clippy: passed
- Frontend typecheck/build: passed
- Git worktree clean

The frontend build continues to emit the existing non-fatal bundle-size warning.

## Acceptance checklist

- [x] Versioned bounded control contract
- [x] Separate control and simulator session IDs
- [x] Explicit three-channel engineering mapping
- [x] Resume-gated active forwarding
- [x] Pause, emergency stop, reset, heartbeat, and watchdog behavior
- [x] Keyboard controls with simultaneous-key and focus-loss safety
- [x] Optional gamepad polling, deadzone, clamping, and disconnect neutralization
- [x] Stable stale-session, stale-sequence, invalid-control, and simulator errors
- [x] Control latency, queue depth, accepted/rejected/drop counters exposed
- [x] Local loopback smoke measurement recorded
- [x] No connectome-control or biological-causality claims
- [ ] Broader burst/drop saturation test with a deliberately slow consumer
- [ ] Final user review of M4 acceptance

M4 remains incomplete until the remaining burst/drop evidence is collected and
the user approves this acceptance document. M5 remains gated.
