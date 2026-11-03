from __future__ import annotations

import json
import math
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from neuropilot_sim import FlySimulation
from neuropilot_sim.server import SimulationService, make_server


def test_loopback_service_lifecycle() -> None:
    service = SimulationService(FlySimulation())
    server = make_server(service, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urllib.request.urlopen(f"{base}/health") as response:
            assert response.status == 200
            health = json.loads(response.read())
            assert health["data_kind"] == "simulated-live"
            assert health["simulation_status"] == "live"
        request = urllib.request.Request(
            f"{base}/api/v1/simulation/reset", data=b"{}", method="POST"
        )
        with urllib.request.urlopen(request) as response:
            state = json.loads(response.read())
            assert state["data_kind"] == "simulated-live"
            assert state["time"] == 0.0
            assert state["status"] == "live"
            assert state["step_count"] == 0
        request = urllib.request.Request(
            f"{base}/api/v1/simulation/step", data=b"{}", method="POST"
        )
        with urllib.request.urlopen(request) as response:
            state = json.loads(response.read())
            assert state["time"] > 0.0
            assert state["step_count"] == 1
            assert state["step_latency_ms"] >= 0.0
        with urllib.request.urlopen(f"{base}/api/v1/simulation/metrics") as response:
            metrics = json.loads(response.read())
            assert metrics["data_kind"] == "simulated-live"
            assert metrics["step_count"] == 1
            assert metrics["request_count"] >= 3
    finally:
        server.shutdown()
        server.server_close()
        service.close()


def test_non_finite_control_is_rejected() -> None:
    service = SimulationService(FlySimulation())
    server = make_server(service, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/v1/simulation/step",
            data=json.dumps({"control": [math.nan]}).encode(),
            method="POST",
            headers={"content-type": "application/json"},
        )
        try:
            urllib.request.urlopen(request)
        except urllib.error.HTTPError as error:
            assert error.code == 400
            assert json.loads(error.read())["code"] == "invalid_request"
        else:
            raise AssertionError("non-finite control was accepted")
    finally:
        server.shutdown()
        server.server_close()
        service.close()


def test_restart_creates_new_session_and_resets_metrics() -> None:
    service = SimulationService(FlySimulation())
    first_session = service.session_id
    service.reset()
    service.step(None)
    restarted = service.restart()
    assert restarted["session_id"] != first_session
    assert restarted["status"] == "live"
    assert restarted["step_count"] == 0
    assert service.metrics()["reset_count"] == 0
    service.close()


def test_concurrent_requests_count_without_lost_increments() -> None:
    service = SimulationService(FlySimulation())
    server = make_server(service, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(lambda _: urllib.request.urlopen(f"{base}/health").read(), range(32)))
        with urllib.request.urlopen(f"{base}/api/v1/simulation/metrics") as response:
            metrics = json.loads(response.read())
        assert metrics["request_count"] == 33
        assert metrics["error_count"] == 0
    finally:
        server.shutdown()
        server.server_close()
        service.close()
