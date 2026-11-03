---
name: rust-service
description: Use when building NeuroPilot Rust services, typed event contracts, async gateways, WebSocket telemetry, orchestration, validation, or performance-sensitive systems code.
---

# Rust service workflow

1. Define the contract and failure semantics before implementation.
2. Prefer stable Rust, Tokio, Axum, Serde, and tracing unless a dependency is justified.
3. Use bounded channels and explicit backpressure policies.
4. Include cancellation, deadlines/timeouts, graceful shutdown, and reconnect behavior.
5. Validate all inbound commands; never trust frontend payloads.
6. Avoid blocking async executor threads; isolate blocking work.
7. Avoid production unwrap/expect; return contextual errors.
8. Add unit and integration tests for malformed input and failure paths.
9. Add structured spans with session/request IDs.
10. Benchmark before optimizing.
