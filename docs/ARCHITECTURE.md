# Architecture

## Runtime topology (initial)

```text
React + Three.js UI
        |
        | HTTP commands / WebSocket telemetry
        v
Rust gateway (Axum + Tokio)
  - typed API contracts
  - session lifecycle
  - validation / backpressure
  - tracing and metrics
        |
        | localhost HTTP/JSON initially
        v
Python adapter
  - FlyGym / MuJoCo
  - connectome import and analysis
  - experiment execution
        |
        v
Dataset snapshots / experiment artifacts
```

## Contract rules
- Version every event schema (`schema_version`).
- Every message includes `session_id`, `sequence`, and monotonic or UTC timestamp with clearly documented semantics.
- Commands are validated and idempotent where possible.
- State snapshots are separate from high-frequency telemetry.
- Queues are bounded. Define whether overload drops oldest telemetry, drops newest telemetry, or pauses the producer.
- UI reconnect must resubscribe and request a fresh state snapshot.
- Never send raw credentials to browser code.

## Example event envelope

```json
{
  "schema_version": 1,
  "session_id": "local-session",
  "sequence": 42,
  "timestamp_unix_ms": 0,
  "kind": "simulation.state",
  "payload": {
    "simulation_time_s": 1.25,
    "is_running": true
  }
}
```

The timestamp value above is a schema example, not measured data.

## Performance
- Separate simulation step rate from UI render rate.
- Start with modest telemetry frequency and profile.
- Keep graph geometry and simulation state updates separate.
- Use binary transport only if profiling proves JSON is a bottleneck.
- Record p50/p95 latency and frame-time distributions.
