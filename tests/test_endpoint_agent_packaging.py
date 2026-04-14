from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_endpoint_agent_powershell_packaging_scripts_parse() -> None:
    scripts = [
        ROOT / "scripts" / "endpoint-agent" / "build-windows-exe.ps1",
        ROOT / "scripts" / "endpoint-agent" / "install-windows-task.ps1",
        ROOT / "scripts" / "endpoint-agent" / "uninstall-windows-task.ps1",
        ROOT / "scripts" / "endpoint-agent" / "run-once-windows.ps1",
        ROOT / "scripts" / "endpoint-agent" / "install-windows-service-nssm.ps1",
        ROOT / "scripts" / "endpoint-agent" / "uninstall-windows-service-nssm.ps1",
        ROOT / "scripts" / "endpoint-agent" / "rustdesk-id.ps1",
    ]
    script_items = ",\n".join(f"  '{script}'" for script in scripts)
    powershell = "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            "foreach ($file in @(",
            script_items,
            ")) {",
            "  $tokens = $null",
            "  $errors = $null",
            "  [System.Management.Automation.Language.Parser]::ParseFile($file, [ref]$tokens, [ref]$errors) | Out-Null",
            "  if ($errors.Count -gt 0) {",
            "    $errors | ForEach-Object { Write-Error \"$file $($_.Message)\" }",
            "    exit 1",
            "  }",
            "}",
        ]
    )

    completed = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", powershell],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_endpoint_agent_build_requirements_include_pyinstaller() -> None:
    requirements = (ROOT / "requirements-build.txt").read_text(encoding="utf-8").lower()

    assert "pyinstaller" in requirements
