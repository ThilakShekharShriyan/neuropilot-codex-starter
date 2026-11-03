# M4 closed-loop interaction architecture

Status: first typed contract slice implemented; full M4 remains under review.

## Scope and scientific boundary

M4 adds a safe human-input loop for the existing CPU NeuroMechFly simulation.
The first control sources are keyboard and gamepad events. The input is an
engineering command to a simulator, not a neuron, connectome, biological,
EEG/BCI, or anatomical control signal. The UI must label the session
`simulated-live` and retain the M2 boundary: FlyGym and numerical state remain
owned by Python; Rust validates and transports commands; React owns input and
presentation.

The first slice does not add connectome-to-motor mapping, neural dynamics,
reinforcement learning, GPU/cloud execution, autonomous control, or a physical
device. M4 must not imply that a user command is a biological motor command.

## Runtime topology

```text
Keyboard/gamepad/browser event
        │ bounded command + control_session_id
        ▼
React dashboard ──localhost HTTP──> Rust gateway
                                      │ validated command queue
                                      ▼
                              Python FlyGym service
                                      │ state/metrics
                                      ▼
                              Rust gateway ──> dashboard
```

The browser talks only to the Rust loopback origin. The Rust gateway talks only
to the Python loopback service. No credentials or external network calls are
introduced. The Python service remains the sole owner of MuJoCo/FlyGym state.

## Control contract

All control messages are versioned JSON objects. The gateway rejects unknown
versions, missing fields, non-finite numbers, booleans masquerading as numbers,
oversized arrays, and stale session IDs before forwarding anything to Python.

```json
{
  "schema_version": 1,
  "control_session_id": "opaque-current-session",
  "sequence": 42,
  "issued_at_ms": 1730000000000,
  "control": [0.0, 0.25, -0.25],
  "source": "keyboard",
  "mode": "active"
}
```

Contract rules:

- `control_session_id` is required and identifies the Rust control session; commands
  from a prior or unknown session are rejected without forwarding.
- `sequence` is a client-provided monotonically increasing value. Duplicate or
  older values are rejected and counted as stale events.
- `issued_at_ms` is diagnostic metadata only. The gateway uses its own monotonic
  receive clock for freshness and does not trust a browser wall clock.
- `source` is an enum (`keyboard` or `gamepad` in this slice), retained for
  telemetry and audit; it is not a biological label.
- `mode` is `active` or `neutral`. Neutral is an explicit zero-control command.
- Each actuator value is finite and bounded to `[-1.0, 1.0]` at the gateway.
  The configured control authority is a second bound, initially `0.25`, applied
  before forwarding: `forwarded = clamp(input, -0.25, 0.25)`.
- The maximum vector length is the existing bounded simulator limit of 256;
  the expected active-leg actuator length is validated against the current
  Python session before the first active command.
- The Python session advertises the observed `actuator_count`; Rust must use
  that value for mapping and reject zero or mismatched counts.
- Control messages never contain neuron IDs, connectome edges, anatomical
  coordinates, or claims about neural activity.

The browser-facing surface is intentionally smaller than the raw active-leg
actuator vector. It exposes three named engineering channels: `forward`,
`lateral`, and `turn`, each bounded to `[-1.0, 1.0]` before the `0.25`
control-authority bound is applied. Rust owns a versioned, explicit table that
expands these channels to the simulator actuator vector. This is an engineering
mapping, not a biological or anatomical mapping, and it must never be inferred
from neuron labels or connectome edges. The exact active-leg actuator length is
discovered from the validated simulator session, not guessed in the frontend. A
mismatch is an `invalid_control` failure, not an opportunity to pad or truncate
silently. Keyboard keys and gamepad axes produce the same three-channel
contract.

### Session identity and reset semantics

M4 uses two distinct opaque identifiers:

- `control_session_id` identifies a Rust gateway control session and appears in
  every control request, response, error, and telemetry record;
- `simulator_session_id` is the Python service's M2 session ID for the underlying
  FlyGym process/session.

Creating a control session, reconnecting, or resetting rotates the
`control_session_id` and clears its sequence window. M4 reset calls the existing
Python reset lifecycle, which preserves the M2 `simulator_session_id` while
returning a fresh baseline state. A Python restart/reconnect creates a new
`simulator_session_id` as well as a new control session. Both IDs are returned
so this distinction is explicit; no request from an old control session is
accepted even when the Python reset ID is unchanged.

### Sequence semantics

Sequences are unsigned integers beginning at `1` for each new control session.
Gaps are allowed, but only strictly increasing values are accepted. Duplicates,
older values, and out-of-order values are rejected with `stale_sequence` and
never forwarded. The highest accepted sequence remains in force across pause
and resume. Reset, reconnect, Python restart, and gateway restart create a new
control session and reset the sequence watermark to zero. Stop clears queued
active commands but does not make old sequence numbers valid; explicit reset is
required before a new sequence window exists. Gaps and rejections are counted.

### Watchdog refresh semantics

The watchdog is refreshed only by an accepted, strictly increasing `active`
control command or an explicit heartbeat for the current control session.
Neutral commands, rejected/duplicate/queue-dropped commands, browser polling,
pause, and telemetry reads do not refresh it. Heartbeats carry no actuator
values and cannot create motion. The watchdog is armed only in `ACTIVE` and is
disarmed in `PAUSED`, `STOPPED`, and `DISCONNECTED`.

## Lifecycle and safety state machine

The Rust gateway maintains a session-scoped control state:

```text
DISCONNECTED ──connect──> PAUSED
PAUSED ──resume + live session──> ACTIVE
ACTIVE ──pause──> PAUSED
ACTIVE/PAUSED ──stop or watchdog──> STOPPED
STOPPED ──reset──> PAUSED
Any state ──session close/crash──> DISCONNECTED
DISCONNECTED ──reconnect──> PAUSED
```

Safety semantics:

- **Pause:** immediately stops forwarding active input and sends one neutral
  command when the Python service is reachable. State remains inspectable.
- **Emergency stop:** is idempotent, transitions to `STOPPED`, clears pending
  commands, sends neutral once when possible, and requires an explicit reset
  before resume. A failed neutral send still leaves the gateway fail-safe and
  increments a stop-delivery error counter.
- **Reset:** rotates the gateway `control_session_id`, clears the sequence
  window and bounded queue, and calls Python reset. The Python
  `simulator_session_id` is preserved by this operation; reconnect after a
  Python restart creates a new simulator ID.
- **Watchdog:** uses a monotonic deadline. If no accepted active command or
  explicit heartbeat arrives within the configured interval (initial proposal: 250 ms),
  the gateway drops pending active commands, sends neutral once, increments
  `watchdog_trips`, and transitions to `STOPPED`.
- **Disconnect:** on timeout, refusal, malformed response, or remote close, the
  gateway stops forwarding immediately and enters `DISCONNECTED`; it never
  replays an old active command after reconnect.
- **Reconnect:** obtains a fresh validated simulator session, starts `PAUSED`,
  clears stale sequence state, and requires an explicit user resume. Reconnect
  must not cause uncontrolled motion.
- **Shutdown:** stops event intake, trips the same neutral/stop path, drains or
  discards the bounded queue according to its policy, closes the gateway, and
  requests Python shutdown. The shutdown path is idempotent.

The 250 ms watchdog value is a proposed initial configuration, not a measured
human-safety guarantee. It must be surfaced in telemetry and captured in the
session configuration.

## Queue and backpressure policy

The gateway uses a bounded single-writer control queue. Proposed initial limits:

- capacity: 32 commands;
- active control: latest-value-wins coalescing per session/source;
- lifecycle commands (`stop`, `reset`, `pause`, `resume`) are never coalesced
  away and take priority over active control;
- overflow drops the oldest active command, increments `dropped_events`, and
  records the highest accepted sequence;
- no unbounded queue, blocking browser request, or retry of stale active input.

The queue policy is observable and must be tested under rapid bursts. It is a
latency/safety tradeoff, not a scientific measurement.

## Proposed gateway endpoints

These are design contracts only; the existing M2 endpoints remain unchanged
until an implementation is approved.

| Method/path | Purpose | Key response/error semantics |
|---|---|---|
| `POST /api/v1/control/session` | Start or attach to a control session | Returns gateway `control_session_id`, simulator ID, state `paused`, limits, and watchdog config |
| `POST /api/v1/control/input` | Submit one bounded keyboard/gamepad command | `202` accepted/coalesced; `400` invalid; `409` stale session/state; `429` bounded queue policy if lifecycle priority cannot be preserved |
| `POST /api/v1/control/heartbeat` | Refresh watchdog without actuator values | `202` accepted for active matching session; `409` if paused/stopped/stale |
| `POST /api/v1/control/pause` | Pause and neutralize | Idempotent; state `paused` |
| `POST /api/v1/control/resume` | Resume after explicit safety checks | Requires live matching simulator session; state `active` |
| `POST /api/v1/control/stop` | Emergency stop | Idempotent; state `stopped`; clears active queue |
| `POST /api/v1/control/reset` | Reset simulator and control state | Fresh simulator session or validated reset response; state `paused` |
| `GET /api/v1/control/status` | Read lifecycle, limits, and last accepted sequence | Bounded, session-scoped telemetry |
| `GET /api/v1/control/metrics` | Read counters and latency | Telemetry only; no biological interpretation |

The input endpoint must not wait for a full physics step if doing so makes the
browser unresponsive. It acknowledges acceptance/coalescing and reports the
event's gateway receive/forward timestamps through bounded telemetry. State
polling remains independent from input submission.

### Versioned control error envelope

Every non-success control response uses one JSON envelope and never returns a
Python traceback or raw transport exception:

```json
{
  "schema_version": 1,
  "error": {
    "code": "stale_sequence",
    "message": "control sequence is not newer than the accepted sequence",
    "control_session_id": "opaque-current-session",
    "sequence": 41,
    "retryable": false
  }
}
```

Stable first-slice codes are `invalid_control`, `stale_session`,
`stale_sequence`, `control_paused`, `watchdog_stop`, `queue_dropped`,
`simulator_unavailable`, `simulator_closed`, `invalid_simulator_response`, and
`shutdown`. `watchdog_stop` is emitted when the gateway transitions to
`STOPPED`; `queue_dropped` is emitted only as a per-event result when bounded
backpressure discards an active event. HTTP classes are stable (`400` malformed
input, `409` lifecycle/session conflict, `503` simulator unavailable, `410`
closed session, `429` queue policy rejection); clients use `error.code` for
behavior. Messages are concise and non-sensitive.

## Telemetry contract

Every control session exposes bounded counters and timing fields:

- `control_session_id`, lifecycle state, and `simulator_session_id`;
- end-to-end input latency: browser-issued timestamp is diagnostic, while the
  gateway records receive-to-forward and forward-to-ack durations using a
  monotonic clock;
- `accepted_events`, `coalesced_events`, `dropped_events`, `rejected_events`;
- queue depth and maximum observed queue depth;
- `watchdog_trips`, `stop_count`, `pause_count`, `resume_count`, `reset_count`;
- invalid-control, stale-session, timeout, disconnect, and reconnect counts;
- last accepted sequence and last forwarded sequence;
- configured bounds, watchdog interval, queue capacity, and `data_kind`.

Telemetry is operational evidence, not a neural or behavioral measurement. All
counters reset with a new control session and are bounded to prevent overflow;
the API must expose whether a counter saturated.

## Failure handling and tests

Before implementation, the following failure-injection matrix is required:

| Case | Required result |
|---|---|
| Gateway timeout | Enter disconnected/stopped-safe state; no active replay |
| Python simulator crash | Detect refusal/EOF; clear queue; reconnect starts paused |
| Reconnect after restart | Fresh simulator/session IDs; explicit resume required |
| Rapid input burst | Bounded queue; documented coalescing/drops; lifecycle commands preserved |
| NaN, infinity, boolean, oversized, out-of-range controls | Reject before Python; no state change |
| Wrong/stale session ID or sequence | Reject/count; no forwarding |
| Watchdog expiry | Exactly one neutral attempt, one trip counter, stopped state |
| Stop during active control | Stop wins over queued input; no post-stop active command |
| Reset during active control | Queue cleared; fresh baseline; paused until resume |
| Malformed Python response | Safe disconnect; no unsafe state presented |
| Gateway shutdown during control | Stop/neutral path and clean process termination |

The first integration smoke test must run keyboard-like commands through the
full `Dashboard → Rust → Python` path on loopback, verify bounded state changes,
trip the watchdog, stop, restart Python, reconnect, and confirm that no motion
resumes until an explicit resume/input sequence.

## Acceptance gates for implementation

M4 implementation may be reviewed only after:

1. The typed control contract and versioned error responses are implemented in
   Rust and Python with no frontend-only validation assumptions.
2. Loopback-only host/origin checks remain enforced.
3. Emergency stop, pause/resume, reset, watchdog, disconnect, reconnect, and
   shutdown semantics pass integration tests.
4. Queue depth, coalescing/drops, watchdog trips, stop/reset counts, and
   end-to-end latency are observable and bounded.
5. Failure-injection tests cover every case in the matrix.
6. The dashboard labels the control as simulated and provides accessible
   keyboard controls plus a visible stop state; gamepad support may be staged
   behind the same contract.
7. A measured CPU smoke run records p50/p95 input latency and does not claim a
   performance target before a baseline exists.
8. `docs/M4_ACCEPTANCE.md` records exact commands, versions, test results,
   configuration, limitations, and the distinction between simulator control
   and biological/connectome data.

## Remaining planning questions

- Choose the exact watchdog interval and queue capacity after a local latency
  baseline; do not present the proposed values as safety certification.
- Decide whether browser-issued timestamps are retained only in memory or in a
  bounded JSONL session log. If persisted, record privacy scope and retention.

The first implementation slice adds the Python control-session/status/reset
payloads and Rust validation/proxy methods, with loopback failure-path tests.
The second slice adds Rust-side three-channel validation, explicit mapping, and
a bounded latest-value-wins queue. The lifecycle slice adds explicit resume-gated
forwarding, pause/stop neutralization, heartbeat handling, watchdog stopping, and
session/sequence enforcement. Frontend keyboard/gamepad controls, broader
reconnect/failure-injection coverage, and the measured end-to-end latency
acceptance artifact remain outstanding.
