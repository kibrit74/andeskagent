from __future__ import annotations

import subprocess
import threading
import uuid


class PowerShellWorker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None

    def _ensure(self) -> subprocess.Popen[str]:
        if self._process and self._process.poll() is None:
            return self._process
        self._process = subprocess.Popen(
            ["powershell", "-NoLogo", "-NoExit", "-Command", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        return self._process

    def run(self, script: str, *, timeout_seconds: int = 60) -> str:
        with self._lock:
            process = self._ensure()
            if not process.stdin or not process.stdout:
                raise RuntimeError("PowerShell worker hazir degil.")
            marker = f"__PS_DONE_{uuid.uuid4().hex}__"
            payload = f"{script}\nWrite-Output \"{marker}\"\n"
            process.stdin.write(payload)
            process.stdin.flush()
            output_lines: list[str] = []
            while True:
                line = process.stdout.readline()
                if not line:
                    break
                if marker in line:
                    break
                output_lines.append(line)
            return "".join(output_lines).strip()


_WORKER = PowerShellWorker()


def run_powershell_command(script: str, *, timeout_seconds: int = 60) -> str:
    return _WORKER.run(script, timeout_seconds=timeout_seconds)

