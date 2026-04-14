from __future__ import annotations

from pathlib import Path

import typer

from endpoint_agent.client import DEFAULT_CONFIG_PATH, EndpointAgentClient, load_agent_config


app = typer.Typer(help="Teknikajan endpoint agent runtime")


@app.command()
def provision(
    api_base_url: str,
    operator_token: str,
    config_path: Path = DEFAULT_CONFIG_PATH,
    rustdesk_id: str = "",
) -> None:
    config = EndpointAgentClient.provision(
        api_base_url=api_base_url,
        operator_token=operator_token,
        config_path=config_path,
        rustdesk_id=rustdesk_id,
    )
    typer.echo(f"Provision tamamlandi. device_id={config.device_id}")


@app.command("run-once")
def run_once(config_path: Path = DEFAULT_CONFIG_PATH) -> None:
    config = load_agent_config(config_path)
    result = EndpointAgentClient(config).run_once()
    typer.echo(result)


@app.command("sync-profile")
def sync_profile(
    config_path: Path = DEFAULT_CONFIG_PATH,
    rustdesk_id: str = "",
) -> None:
    config = load_agent_config(config_path)
    result = EndpointAgentClient(config).sync_profile(
        rustdesk_id=rustdesk_id or None,
        config_path=config_path,
    )
    typer.echo(result)


@app.command()
def run(config_path: Path = DEFAULT_CONFIG_PATH) -> None:
    config = load_agent_config(config_path)
    EndpointAgentClient(config).run_forever()


if __name__ == "__main__":
    app()
