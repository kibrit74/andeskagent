from __future__ import annotations

import json
import platform
import socket
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import requests

from adapters.script_adapter import run_script
from adapters.system_adapter import get_system_status


DEFAULT_CONFIG_PATH = Path("config") / "endpoint_agent.json"
DEFAULT_LOG_PATH = Path("logs") / "ops.log"
DEFAULT_TIMEOUT_SECONDS = 20
SUPPORTED_ACTIONS = ("get_system_status", "run_script", "read_screen", "collect_logs")


@dataclass(slots=True)
class EndpointAgentConfig:
    api_base_url: str
    device_id: str = ""
    device_token: str = ""
    hostname: str = field(default_factory=socket.gethostname)
    os: str = field(default_factory=lambda: platform.platform())
    rustdesk_id: str = ""
    version: str = "0.1.0"
    capabilities: list[str] = field(default_factory=lambda: list(SUPPORTED_ACTIONS))
    allowed_actions: list[str] = field(default_factory=lambda: ["get_system_status", "collect_logs"])
    allowed_scripts: list[str] = field(default_factory=list)
    poll_interval_seconds: int = 10
    log_path: str = str(DEFAULT_LOG_PATH)


def load_agent_config(path: str | Path = DEFAULT_CONFIG_PATH) -> EndpointAgentConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return EndpointAgentConfig(**payload)


def save_agent_config(config: EndpointAgentConfig, path: str | Path = DEFAULT_CONFIG_PATH) -> None:
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as handle:
        json.dump(asdict(config), handle, ensure_ascii=True, indent=2)


def _result(status: str, result: dict[str, Any] | None = None, error_text: str = "") -> dict[str, Any]:
    return {"status": status, "result": result or {}, "error_text": error_text}


class EndpointJobExecutor:
    def __init__(self, config: EndpointAgentConfig) -> None:
        self.config = config

    def execute(self, job: dict[str, Any]) -> dict[str, Any]:
        action = str(job.get("action", "")).strip()
        payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
        if action not in self.config.allowed_actions:
            return _result("blocked", error_text=f"Action policy disinda: {action}")

        try:
            if action == "get_system_status":
                return _result("succeeded", get_system_status())
            if action == "run_script":
                script_name = str(payload.get("script_name", "")).strip()
                if not script_name:
                    return _result("blocked", error_text="script_name gerekli.")
                return _result("succeeded", run_script(script_name, allowed_scripts=self.config.allowed_scripts))
            if action == "read_screen":
                from adapters.desktop_adapter import read_screen

                mode = str(payload.get("mode", "medium")).strip() or "medium"
                return _result("succeeded", read_screen(mode=mode))
            if action == "collect_logs":
                return _result("succeeded", self._collect_logs(payload))
        except Exception as exc:
            return _result("failed", error_text=str(exc))

        return _result("blocked", error_text=f"Desteklenmeyen action: {action}")

    def _collect_logs(self, payload: dict[str, Any]) -> dict[str, Any]:
        tail_lines = int(payload.get("tail_lines", 200) or 200)
        tail_lines = max(1, min(tail_lines, 500))
        log_path = Path(self.config.log_path)
        if not log_path.exists():
            return {"path": str(log_path), "lines": [], "missing": True}
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return {"path": str(log_path), "lines": lines[-tail_lines:], "line_count": min(len(lines), tail_lines)}


class EndpointAgentClient:
    def __init__(
        self,
        config: EndpointAgentConfig,
        *,
        http: requests.Session | None = None,
        executor: EndpointJobExecutor | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.config = config
        self.http = http or requests.Session()
        self.executor = executor or EndpointJobExecutor(config)
        self.timeout_seconds = timeout_seconds

    @classmethod
    def provision(
        cls,
        *,
        api_base_url: str,
        operator_token: str,
        config_path: str | Path = DEFAULT_CONFIG_PATH,
        hostname: str | None = None,
        os_name: str | None = None,
        rustdesk_id: str = "",
        version: str = "0.1.0",
        capabilities: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> EndpointAgentConfig:
        config = EndpointAgentConfig(
            api_base_url=api_base_url.rstrip("/"),
            hostname=hostname or socket.gethostname(),
            os=os_name or platform.platform(),
            rustdesk_id=rustdesk_id,
            version=version,
            capabilities=capabilities or list(SUPPORTED_ACTIONS),
        )
        response = requests.post(
            f"{config.api_base_url}/endpoint-agents/devices/register",
            headers={"Authorization": f"Bearer {operator_token}"},
            json={
                "hostname": config.hostname,
                "os": config.os,
                "rustdesk_id": config.rustdesk_id,
                "version": config.version,
                "capabilities": config.capabilities,
                "metadata": metadata or {},
            },
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        config.device_id = str(payload["device"]["id"])
        config.device_token = str(payload["device_token"])
        save_agent_config(config, config_path)
        return config

    def _device_headers(self) -> dict[str, str]:
        if not self.config.device_id or not self.config.device_token:
            raise RuntimeError("Endpoint agent provision edilmemis: device_id/device_token eksik.")
        return {"X-Device-Token": self.config.device_token}

    def heartbeat(self, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.http.post(
            f"{self.config.api_base_url.rstrip('/')}/endpoint-agents/devices/{self.config.device_id}/heartbeat",
            headers=self._device_headers(),
            json={"status": "online", "metadata": metadata or {}},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def sync_profile(
        self,
        *,
        rustdesk_id: str | None = None,
        config_path: str | Path | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if rustdesk_id is not None:
            self.config.rustdesk_id = rustdesk_id.strip()

        response = self.http.post(
            f"{self.config.api_base_url.rstrip('/')}/endpoint-agents/devices/{self.config.device_id}/profile",
            headers=self._device_headers(),
            json={
                "hostname": self.config.hostname,
                "os": self.config.os,
                "rustdesk_id": self.config.rustdesk_id,
                "version": self.config.version,
                "capabilities": self.config.capabilities,
                "metadata": metadata or {},
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        if config_path:
            save_agent_config(self.config, config_path)
        return response.json()

    def fetch_next_job(self) -> dict[str, Any] | None:
        response = self.http.get(
            f"{self.config.api_base_url.rstrip('/')}/endpoint-agents/devices/{self.config.device_id}/jobs/next",
            headers=self._device_headers(),
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        job = payload.get("job")
        return job if isinstance(job, dict) else None

    def complete_job(self, job_id: int, execution: dict[str, Any]) -> dict[str, Any]:
        response = self.http.post(
            f"{self.config.api_base_url.rstrip('/')}/endpoint-agents/devices/{self.config.device_id}/jobs/{job_id}/result",
            headers=self._device_headers(),
            json={
                "status": execution.get("status", "failed"),
                "result": execution.get("result", {}),
                "error_text": execution.get("error_text", ""),
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def run_once(self) -> dict[str, Any]:
        self.heartbeat({"capabilities": self.config.capabilities, "version": self.config.version})
        job = self.fetch_next_job()
        if not job:
            return {"status": "idle"}

        job_id = int(job["id"])
        execution = self.executor.execute(job)
        completion = self.complete_job(job_id, execution)
        return {"status": "processed", "job_id": job_id, "execution": execution, "completion": completion}

    def run_forever(self) -> None:
        while True:
            self.run_once()
            time.sleep(max(1, int(self.config.poll_interval_seconds or 10)))
