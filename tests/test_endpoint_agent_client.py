from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from endpoint_agent.client import EndpointAgentClient, EndpointAgentConfig, EndpointJobExecutor


@dataclass
class FakeResponse:
    payload: dict[str, Any]
    status_code: int = 200

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeHttp:
    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []
        self.gets: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs) -> FakeResponse:
        self.posts.append({"url": url, **kwargs})
        return FakeResponse({"ok": True})

    def get(self, url: str, **kwargs) -> FakeResponse:
        self.gets.append({"url": url, **kwargs})
        return FakeResponse(
            {
                "job": {
                    "id": 7,
                    "device_id": "device-1",
                    "action": "get_system_status",
                    "payload": {},
                    "status": "leased",
                }
            }
        )


class FakeExecutor(EndpointJobExecutor):
    def execute(self, job: dict[str, Any]) -> dict[str, Any]:
        assert job["id"] == 7
        return {"status": "succeeded", "result": {"cpu_percent": 1.0}, "error_text": ""}


def test_endpoint_agent_client_processes_one_job() -> None:
    config = EndpointAgentConfig(
        api_base_url="http://127.0.0.1:8000",
        device_id="device-1",
        device_token="token-1",
        allowed_actions=["get_system_status"],
    )
    http = FakeHttp()

    result = EndpointAgentClient(config, http=http, executor=FakeExecutor(config)).run_once()

    assert result["status"] == "processed"
    assert result["job_id"] == 7
    assert http.posts[0]["url"].endswith("/endpoint-agents/devices/device-1/heartbeat")
    assert http.gets[0]["url"].endswith("/endpoint-agents/devices/device-1/jobs/next")
    assert http.posts[1]["url"].endswith("/endpoint-agents/devices/device-1/jobs/7/result")
    assert http.posts[1]["json"]["status"] == "succeeded"
    assert http.posts[1]["headers"] == {"X-Device-Token": "token-1"}


def test_endpoint_agent_client_syncs_rustdesk_profile() -> None:
    config = EndpointAgentConfig(
        api_base_url="http://127.0.0.1:8000",
        device_id="device-1",
        device_token="token-1",
        rustdesk_id="old-id",
        capabilities=["get_system_status"],
    )
    http = FakeHttp()

    EndpointAgentClient(config, http=http).sync_profile(rustdesk_id="new-id")

    request = http.posts[0]
    assert request["url"].endswith("/endpoint-agents/devices/device-1/profile")
    assert request["headers"] == {"X-Device-Token": "token-1"}
    assert request["json"]["rustdesk_id"] == "new-id"
    assert config.rustdesk_id == "new-id"


def test_endpoint_job_executor_blocks_disallowed_action() -> None:
    config = EndpointAgentConfig(
        api_base_url="http://127.0.0.1:8000",
        allowed_actions=["get_system_status"],
    )

    result = EndpointJobExecutor(config).execute({"action": "run_script", "payload": {"script_name": "dns_flush"}})

    assert result["status"] == "blocked"
    assert "policy" in result["error_text"].lower()
