from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import psutil


@dataclass(slots=True)
class SystemStatus:
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    process_count: int
    open_applications: list[str]


class SystemInfoAdapter:
    def collect(self) -> SystemStatus:
        open_applications: list[str] = []
        for proc in psutil.process_iter(attrs=["name"]):
            try:
                name = proc.info.get("name")
                if name:
                    open_applications.append(name)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        root_path = Path.cwd().anchor or "C:\\"
        return SystemStatus(
            cpu_percent=psutil.cpu_percent(interval=0.2),
            memory_percent=psutil.virtual_memory().percent,
            disk_percent=psutil.disk_usage(root_path).percent if psutil.disk_partitions() else 0.0,
            process_count=len(open_applications),
            open_applications=sorted(set(open_applications)),
        )


def get_system_status() -> dict[str, object]:
    status = SystemInfoAdapter().collect()
    return {
        "cpu_percent": status.cpu_percent,
        "memory_percent": status.memory_percent,
        "disk_percent": status.disk_percent,
        "process_count": status.process_count,
        "open_applications": status.open_applications,
    }

