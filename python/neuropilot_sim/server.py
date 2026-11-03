"""Loopback-only HTTP service for one live CPU FlyGym simulation."""

from __future__ import annotations

import argparse
import json
import math
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .adapter import FlySimulation, FlyState

MAX_REQUEST_BYTES = 1_048_576


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
        self.lock = threading.Lock()
        self.session_id = secrets.token_hex(8)
        self.status = "live"
        self.step_count = 0
        self.last_step_latency_ms: float | None = None
        self.reset_count = 0
        self.request_count = 0
        self.error_count = 0

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
            service.request_count += 1
            if self.path == "/health":
                self._send(200, {"status": "ok", "data_kind": "simulated-live"})
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
            self._send(404, {"code": "not_found", "message": "endpoint not found"})

        def do_POST(self) -> None:  # noqa: N802
            service.request_count += 1
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
                else:
                    self._send(404, {"code": "not_found", "message": "endpoint not found"})
            except (ValueError, json.JSONDecodeError) as exc:
                service.error_count += 1
                self._send(400, {"code": "invalid_request", "message": str(exc)})
            except RuntimeError:
                service.error_count += 1
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
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
