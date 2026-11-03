from __future__ import annotations

import json
import threading
import urllib.request

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
            assert json.loads(response.read())["data_kind"] == "simulated-live"
        request = urllib.request.Request(
            f"{base}/api/v1/simulation/reset", data=b"{}", method="POST"
        )
        with urllib.request.urlopen(request) as response:
            state = json.loads(response.read())
            assert state["data_kind"] == "simulated-live"
            assert state["time"] == 0.0
        request = urllib.request.Request(
            f"{base}/api/v1/simulation/step", data=b"{}", method="POST"
        )
        with urllib.request.urlopen(request) as response:
            assert json.loads(response.read())["time"] > 0.0
    finally:
        server.shutdown()
        server.server_close()
        service.close()
