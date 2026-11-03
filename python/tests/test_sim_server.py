from __future__ import annotations

import json
import math
import os
import socket
import subprocess
import sys
import threading
import time
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


def test_control_session_contract_rotates_on_session_and_reset() -> None:
    service = SimulationService(FlySimulation())
    first = service.control_status_payload()
    assert first["schema_version"] == 1
    assert first["status"] == "paused"
    assert first["simulator_status"] == "live"
    assert first["channels"] == ["forward", "lateral", "turn"]
    assert first["control_authority"] == 0.25
    created = service.control_session()
    assert created["control_session_id"] != first["control_session_id"]
    reset = service.control_reset()
    assert reset["control_session_id"] != created["control_session_id"]
    assert reset["simulator_session_id"] == created["simulator_session_id"]
    assert reset["status"] == "paused"
    assert reset["state"]["step_count"] == 0
    service.close()


def test_control_status_reports_disconnect_after_close() -> None:
    service = SimulationService(FlySimulation())
    service.close()
    status = service.control_status_payload()
    assert status["status"] == "disconnected"
    assert status["simulator_status"] == "closed"


def test_control_http_session_and_status_endpoints() -> None:
    service = SimulationService(FlySimulation())
    server = make_server(service, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urllib.request.urlopen(f"{base}/api/v1/control/status") as response:
            status = json.loads(response.read())
        assert status["schema_version"] == 1
        assert status["status"] == "paused"
        request = urllib.request.Request(
            f"{base}/api/v1/control/session", data=b"{}", method="POST"
        )
        with urllib.request.urlopen(request) as response:
            created = json.loads(response.read())
        assert created["control_session_id"] != status["control_session_id"]
        assert created["simulator_session_id"] == status["simulator_session_id"]
        reset_request = urllib.request.Request(
            f"{base}/api/v1/control/reset", data=b"{}", method="POST"
        )
        with urllib.request.urlopen(reset_request) as response:
            reset = json.loads(response.read())
        assert reset["control_session_id"] != created["control_session_id"]
        assert reset["state"]["step_count"] == 0
    finally:
        server.shutdown()
        server.server_close()
        service.close()


def test_control_lifecycle_input_and_watchdog() -> None:
    service = SimulationService(FlySimulation())
    session = service.control_session()
    control_id = session["control_session_id"]
    assert service.control_resume(control_id)["status"] == "active"
    forwarded = service.control_input(
        control_id, 1, [0.1] * session["actuator_count"], "keyboard", "active"
    )
    assert forwarded["forwarded"] is True
    assert forwarded["last_control_sequence"] == 1
    assert service.control_heartbeat(control_id)["status"] == "active"
    assert service.control_pause(control_id)["status"] == "paused"
    assert service.control_stop(control_id)["status"] == "stopped"
    reset = service.control_reset()
    assert reset["status"] == "paused"
    service.close()


def test_neutral_control_does_not_refresh_watchdog() -> None:
    service = SimulationService(FlySimulation())
    session = service.control_session()
    control_id = session["control_session_id"]
    service.control_resume(control_id)
    service.control_input(
        control_id, 1, [0.1] * session["actuator_count"], "keyboard", "active"
    )
    time.sleep(0.1)
    service.control_input(
        control_id, 2, [0.0] * session["actuator_count"], "keyboard", "neutral"
    )
    assert service.control_status_payload()["status"] == "active"
    deadline = time.monotonic() + 0.3
    while time.monotonic() < deadline and service.control_status_payload()["status"] == "active":
        time.sleep(0.02)
    assert service.control_status_payload()["status"] == "stopped"
    service.close()


def test_control_watchdog_neutralizes_and_stops() -> None:
    service = SimulationService(FlySimulation())
    control_id = service.control_session()["control_session_id"]
    service.control_resume(control_id)
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and service.control_status_payload()["status"] != "stopped":
        time.sleep(0.02)
    status = service.control_status_payload()
    assert status["status"] == "stopped"
    assert status["watchdog_trips"] == 1
    assert status["neutralization_count"] == 1
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


def test_subprocess_sigterm_exits_and_closes_server() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = "python"
    process = subprocess.Popen(
        [sys.executable, "-m", "neuropilot_sim.server", "--port", str(port)],
        cwd=os.getcwd(),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10.0
        output = ""
        while time.monotonic() < deadline and "listening" not in output:
            line = process.stdout.readline() if process.stdout else ""
            output += line
        assert "listening" in output
        process.terminate()
        remaining, _ = process.communicate(timeout=5)
        output += remaining
        assert process.returncode == 0
        assert "simulation service stopped" in output
        with socket.socket() as connection:
            connection.settimeout(0.5)
            assert connection.connect_ex(("127.0.0.1", port)) != 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
