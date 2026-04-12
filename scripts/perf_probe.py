from __future__ import annotations

import argparse
import json
import statistics
import time
from typing import Any

import requests


DEFAULT_COMMANDS = [
    "gorunen pencereleri listele",
    "ekrani oku",
    "sayfanin ustundeki linke tikla",
]


def _send_command(base_url: str, text: str, approved: bool) -> dict[str, Any]:
    started_at = time.perf_counter()
    response = requests.post(
        f"{base_url.rstrip('/')}/command-ui",
        json={"text": text, "approved": approved},
        timeout=180,
    )
    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)
    response.raise_for_status()
    payload = response.json()
    payload["_client_ms"] = elapsed_ms
    return payload


def _summarize(values: list[float]) -> dict[str, float]:
    return {
        "min_ms": round(min(values), 1),
        "avg_ms": round(statistics.mean(values), 1),
        "max_ms": round(max(values), 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Local command performance probe")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Server base URL")
    parser.add_argument("--repeat", type=int, default=3, help="Runs per command")
    parser.add_argument("--approved", action="store_true", help="Send commands with approved=true")
    parser.add_argument("commands", nargs="*", help="Commands to probe")
    args = parser.parse_args()

    commands = args.commands or DEFAULT_COMMANDS
    report: list[dict[str, Any]] = []

    for command in commands:
        runs: list[dict[str, Any]] = []
        print(f"\n[probe] {command}")
        for index in range(args.repeat):
            payload = _send_command(args.base_url, command, args.approved)
            timing = payload.get("timing") or {}
            run_info = {
                "run": index + 1,
                "client_ms": float(payload.get("_client_ms", 0.0) or 0.0),
                "server_total_ms": float(timing.get("total_ms", 0.0) or 0.0),
                "server_parse_ms": float(timing.get("parse_ms", 0.0) or 0.0),
                "server_execute_ms": float(timing.get("execute_ms", 0.0) or 0.0),
                "action": payload.get("action"),
                "summary": payload.get("summary"),
                "error": payload.get("error"),
            }
            runs.append(run_info)
            print(
                json.dumps(
                    {
                        "run": run_info["run"],
                        "client_ms": run_info["client_ms"],
                        "server_total_ms": run_info["server_total_ms"],
                        "server_parse_ms": run_info["server_parse_ms"],
                        "server_execute_ms": run_info["server_execute_ms"],
                        "action": run_info["action"],
                        "error": run_info["error"],
                    },
                    ensure_ascii=False,
                )
            )

        report.append(
            {
                "command": command,
                "client": _summarize([item["client_ms"] for item in runs]),
                "server_total": _summarize([item["server_total_ms"] for item in runs]),
                "server_parse": _summarize([item["server_parse_ms"] for item in runs]),
                "server_execute": _summarize([item["server_execute_ms"] for item in runs]),
                "runs": runs,
            }
        )

    print("\n=== PERF SUMMARY ===")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
