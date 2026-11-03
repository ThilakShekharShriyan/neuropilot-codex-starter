"""Loopback-only HTTP service for one live CPU FlyGym simulation."""

from __future__ import annotations

import argparse
import json
import math
import secrets
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .adapter import FlySimulation, FlyState

MAX_REQUEST_BYTES = 1_048_576
CONTROL_SCHEMA_VERSION = 1
CONTROL_AUTHORITY = 0.25
CONTROL_QUEUE_CAPACITY = 32
WATCHDOG_TIMEOUT_MS = 250


def _state_payload(state: FlyState) -> dict[str, Any]:
    return {
        "data_kind": "simulated-live",
        "time": state.time,
        "joint_angles": state.joint_angles,
        "joint_velocities": state.joint_velocities,
        "body_positions": state.body_positions,
    }


class SimulationService:
    def __init__(self, simulation: FlySimulation) -> None:
        self.simulation = simulation
        self.config = simulation.config
        self.lock = threading.Lock()
        self.session_id = secrets.token_hex(8)
        self.status = "live"
        self.step_count = 0
        self.last_step_latency_ms: float | None = None
        self.reset_count = 0
        self.request_count = 0
        self.error_count = 0
        self.control_session_id = secrets.token_hex(16)
        self.control_status = "paused"

    def _payload(self, state: FlyState) -> dict[str, Any]:
        payload = _state_payload(state)
        payload.update(
            {
                "session_id": self.session_id,
                "status": self.status,
                "step_count": self.step_count,
                "step_latency_ms": self.last_step_latency_ms,
            }
        )
        return payload

    def state(self) -> dict[str, Any]:
        with self.lock:
            return self._payload(self.simulation.state())

    def reset(self) -> dict[str, Any]:
        with self.lock:
            state = self.simulation.reset()
            self.status = "live"
            self.step_count = 0
            self.last_step_latency_ms = None
            self.reset_count += 1
            return self._payload(state)

    def step(self, control: list[float] | None) -> dict[str, Any]:
        with self.lock:
            started = time.perf_counter_ns()
            state = self.simulation.step(control)
            self.last_step_latency_ms = (time.perf_counter_ns() - started) / 1e6
            self.step_count += 1
            return self._payload(state)

    def close(self) -> None:
        with self.lock:
            self.simulation.close()
            self.status = "closed"
            self.control_status = "disconnected"

    def restart(self) -> dict[str, Any]:
        with self.lock:
            self.simulation.close()
            self.simulation = FlySimulation(self.config)
            self.session_id = secrets.token_hex(8)
            self.status = "live"
            self.step_count = 0
            self.reset_count = 0
            self.request_count = 0
            self.error_count = 0
            self.last_step_latency_ms = None
            self.control_session_id = secrets.token_hex(16)
            self.control_status = "paused"
            return self._payload(self.simulation.reset())

    def control_session(self) -> dict[str, Any]:
        with self.lock:
            self.control_session_id = secrets.token_hex(16)
            self.control_status = "paused" if self.status == "live" else "disconnected"
            return self._control_payload()

    def control_reset(self) -> dict[str, Any]:
        with self.lock:
            state = self.simulation.reset()
            self.status = "live"
            self.step_count = 0
            self.last_step_latency_ms = None
            self.reset_count += 1
            self.control_session_id = secrets.token_hex(16)
            self.control_status = "paused"
            payload = self._control_payload()
            payload["state"] = self._payload(state)
            return payload

    def control_status_payload(self) -> dict[str, Any]:
        with self.lock:
            return self._control_payload()

    def _control_payload(self) -> dict[str, Any]:
        return {
            "schema_version": CONTROL_SCHEMA_VERSION,
            "data_kind": "simulated-live",
            "control_session_id": self.control_session_id,
            "simulator_session_id": self.session_id,
            "status": self.control_status,
            "simulator_status": self.status,
            "control_authority": CONTROL_AUTHORITY,
            "watchdog_timeout_ms": WATCHDOG_TIMEOUT_MS,
            "queue_capacity": CONTROL_QUEUE_CAPACITY,
            "channels": ["forward", "lateral", "turn"],
            "sequence": 0,
        }

    def metrics(self) -> dict[str, Any]:
        with self.lock:
            return {
                "data_kind": "simulated-live",
                "session_id": self.session_id,
                "status": self.status,
                "request_count": self.request_count,
                "error_count": self.error_count,
                "reset_count": self.reset_count,
                "step_count": self.step_count,
                "last_step_latency_ms": self.last_step_latency_ms,
            }

    def record_request(self) -> None:
        with self.lock:
            self.request_count += 1

    def record_error(self) -> None:
        with self.lock:
            self.error_count += 1


def make_server(service: SimulationService, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _json_body(self) -> dict[str, Any]:
            raw_length = self.headers.get("Content-Length", "0")
            try:
                length = int(raw_length)
            except ValueError as exc:
                raise ValueError("content length is invalid") from exc
            if length < 0 or length > MAX_REQUEST_BYTES:
                raise ValueError("request body exceeds limit")
            raw = self.rfile.read(length)
            if not raw:
                return {}
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("request body must be an object")
            return value

        def do_GET(self) -> None:  # noqa: N802
            service.record_request()
            if self.path == "/health":
                metrics = service.metrics()
                self._send(
                    200,
                    {
                        "status": "ok" if metrics["status"] == "live" else "closed",
                        "data_kind": "simulated-live",
                        "session_id": metrics["session_id"],
                        "simulation_status": metrics["status"],
                    },
                )
                return
            if self.path == "/api/v1/simulation/state":
                try:
                    self._send(200, service.state())
                except RuntimeError:
                    self._send(
                        409,
                        {"code": "simulation_closed", "message": "simulation is closed"},
                    )
                return
            if self.path == "/api/v1/simulation/metrics":
                self._send(200, service.metrics())
                return
            if self.path == "/api/v1/control/status":
                self._send(200, service.control_status_payload())
                return
            self._send(404, {"code": "not_found", "message": "endpoint not found"})

        def do_POST(self) -> None:  # noqa: N802
            service.record_request()
            try:
                body = self._json_body()
                if self.path == "/api/v1/simulation/reset":
                    self._send(200, service.reset())
                elif self.path == "/api/v1/simulation/step":
                    control = body.get("control")
                    if control is not None and (
                        not isinstance(control, list)
                        or len(control) > 256
                        or not all(
                            isinstance(value, (int, float))
                            and not isinstance(value, bool)
                            and math.isfinite(float(value))
                            for value in control
                        )
                    ):
                        raise ValueError("control must be a numeric array")
                    self._send(200, service.step(control))
                elif self.path == "/api/v1/simulation/close":
                    service.close()
                    self._send(
                        200,
                        {
                            "status": "closed",
                            "data_kind": "simulated-live",
                            "session_id": service.session_id,
                        },
                    )
                elif self.path == "/api/v1/simulation/restart":
                    self._send(200, service.restart())
                elif self.path == "/api/v1/control/session":
                    self._send(200, service.control_session())
                elif self.path == "/api/v1/control/reset":
                    self._send(200, service.control_reset())
                else:
                    self._send(404, {"code": "not_found", "message": "endpoint not found"})
            except (ValueError, json.JSONDecodeError) as exc:
                service.record_error()
                self._send(400, {"code": "invalid_request", "message": str(exc)})
            except RuntimeError:
                service.record_error()
                self._send(409, {"code": "simulation_closed", "message": "simulation is closed"})

        def log_message(self, format: str, *args: object) -> None:
            return

    if port < 0 or port > 65535:
        raise ValueError("port must be between 0 and 65535")
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the NeuroPilot CPU FlyGym service")
    parser.add_argument("--port", type=int, default=8790)
    args = parser.parse_args()
    with FlySimulation() as simulation:
        server = make_server(SimulationService(simulation), args.port)
        print(f"simulation service listening on http://127.0.0.1:{args.port}", flush=True)
        shutdown_requested = threading.Event()

        def request_shutdown(signum: int, frame: object) -> None:
            del signum, frame
            if not shutdown_requested.is_set():
                shutdown_requested.set()
                server.shutdown()

        signal.signal(signal.SIGINT, request_shutdown)
        signal.signal(signal.SIGTERM, request_shutdown)
        server_thread = threading.Thread(target=server.serve_forever, name="simulation-http")
        server_thread.start()
        try:
            while server_thread.is_alive():
                server_thread.join(timeout=0.2)
        finally:
            if not shutdown_requested.is_set():
                shutdown_requested.set()
                server.shutdown()
            server_thread.join(timeout=2.0)
            server.server_close()
            print("simulation service stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
