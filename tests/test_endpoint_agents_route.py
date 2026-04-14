from __future__ import annotations

from fastapi.testclient import TestClient

from server.main import app
from server.routes import endpoint_agents


def test_endpoint_agent_register_heartbeat_job_lifecycle(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(endpoint_agents.settings, "sqlite_path", tmp_path / "endpoint-agents.db")
    client = TestClient(app)
    operator_headers = {"Authorization": "Bearer 432323"}

    register_response = client.post(
        "/endpoint-agents/devices/register",
        headers=operator_headers,
        json={
            "hostname": "musteri-pc-01",
            "os": "windows",
            "rustdesk_id": "123456789",
            "version": "0.1.0",
            "capabilities": ["run_script", "read_screen"],
            "metadata": {"site": "istanbul"},
        },
    )

    assert register_response.status_code == 200
    register_payload = register_response.json()
    device_id = register_payload["device"]["id"]
    device_token = register_payload["device_token"]
    device_headers = {"X-Device-Token": device_token}

    heartbeat_response = client.post(
        f"/endpoint-agents/devices/{device_id}/heartbeat",
        headers=device_headers,
        json={"status": "online", "metadata": {"ip": "10.0.0.5"}},
    )

    assert heartbeat_response.status_code == 200
    assert heartbeat_response.json()["device"]["status"] == "online"

    profile_response = client.post(
        f"/endpoint-agents/devices/{device_id}/profile",
        headers=device_headers,
        json={"rustdesk_id": "987654321", "version": "0.1.1", "capabilities": ["get_system_status"]},
    )

    assert profile_response.status_code == 200
    profile_device = profile_response.json()["device"]
    assert profile_device["rustdesk_id"] == "987654321"
    assert profile_device["version"] == "0.1.1"
    assert profile_device["capabilities"] == ["get_system_status"]

    create_job_response = client.post(
        f"/endpoint-agents/devices/{device_id}/jobs",
        headers=operator_headers,
        json={"action": "run_script", "payload": {"script_name": "dns_flush"}},
    )

    assert create_job_response.status_code == 200
    job_id = create_job_response.json()["job"]["id"]

    next_job_response = client.get(
        f"/endpoint-agents/devices/{device_id}/jobs/next",
        headers=device_headers,
    )

    assert next_job_response.status_code == 200
    next_job = next_job_response.json()["job"]
    assert next_job["id"] == job_id
    assert next_job["status"] == "leased"
    assert next_job["payload"] == {"script_name": "dns_flush"}

    result_response = client.post(
        f"/endpoint-agents/devices/{device_id}/jobs/{job_id}/result",
        headers=device_headers,
        json={"status": "succeeded", "result": {"returncode": 0, "stdout": "ok"}},
    )

    assert result_response.status_code == 200
    completed_job = result_response.json()["job"]
    assert completed_job["status"] == "succeeded"
    assert completed_job["result"]["stdout"] == "ok"


def test_endpoint_agent_rejects_invalid_device_token(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(endpoint_agents.settings, "sqlite_path", tmp_path / "endpoint-agents.db")
    client = TestClient(app)

    register_response = client.post(
        "/endpoint-agents/devices/register",
        headers={"Authorization": "Bearer 432323"},
        json={"hostname": "musteri-pc-02"},
    )
    device_id = register_response.json()["device"]["id"]

    heartbeat_response = client.post(
        f"/endpoint-agents/devices/{device_id}/heartbeat",
        headers={"X-Device-Token": "wrong"},
        json={"status": "online"},
    )

    assert heartbeat_response.status_code == 401
