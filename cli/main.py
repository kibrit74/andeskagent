"""Teknik Destek Ajani CLI - agentctl."""
from __future__ import annotations

import json

import requests
import typer
from rich import print
from rich.console import Console
from rich.table import Table

from core.config import load_settings


app = typer.Typer(
    name="agentctl",
    help="AI Destekli Uzak Teknik Destek Ajani CLI",
    add_completion=False,
)
console = Console()


def _headers() -> dict[str, str]:
    settings = load_settings()
    return {"Authorization": f"Bearer {settings.bearer_token}"}


def _base_url() -> str:
    settings = load_settings()
    return settings.api_base_url.rstrip("/")


def _print_json_response(response: requests.Response) -> None:
    try:
        payload = response.json()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    except Exception:
        print(f"[red]HTTP {response.status_code}[/red]: {response.text}")


def _handle_error(response: requests.Response) -> bool:
    if response.status_code >= 400:
        print(f"[red]Hata ({response.status_code}):[/red]")
        _print_json_response(response)
        return True
    return False


def _feedback_for_response(data: dict) -> tuple[str, str | None]:
    action = data.get("action", "unknown")
    result = data.get("result") or {}
    error = data.get("error")
    if error:
        next_step = "Komutu daha acik yazarak tekrar deneyin."
        normalized = str(error).lower()
        if "anahtar" in normalized:
            next_step = "Ayarlar dosyasindaki Gemini anahtarini kontrol edin."
        elif "gmail oturumu" in normalized:
            next_step = "Acilan Edge penceresinde Gmail'e giris yapin, sonra ayni komutu tekrar deneyin."
        elif "alici" in normalized or "gonderim" in normalized:
            next_step = "Alici adresini ve mail ayarlarini kontrol edin."
        elif "dosya bulunamadi" in normalized:
            next_step = "Dosya adini, konumu veya uzantiyi daha net yazin."
        elif "uygulama" in normalized:
            next_step = "Daha bilinen bir uygulama adi deneyin."
        elif "guvenlik" in normalized:
            next_step = "Daha dar kapsamli ve guvenli bir komut deneyin."
        return (f"Islem tamamlanamadi: {error}", next_step)

    if action == "system_status":
        return ("Sistem durumu alindi.", "CPU, RAM ve disk degerlerini yukaridan kontrol edebilirsiniz.")
    if action == "search_file":
        count = result.get("count", 0)
        return (f"{count} dosya bulundu." if count else "Eslesen dosya bulunamadi.", "Gerekirse dosya adini veya uzantiyi daha net yazin.")
    if action == "send_file":
        if result.get("status") == "sent":
            return ("Dosya gonderildi.", "Alici tarafinda gelen kutusunu kontrol edin.")
        return ("Dosya bulundu ama gonderim tamamlanmadi.", "Alici e-posta adresi ve mail ayarlarini kontrol edin.")
    if action == "send_latest":
        if result.get("status") == "sent":
            return ("En yeni dosya gonderildi.", "Alici tarafinda gelen kutusunu kontrol edin.")
        return ("En yeni dosya bulundu.", "Gonderim icin alici bilgisinin tam oldugundan emin olun.")
    if action == "run_script":
        return ("Script calistirildi.", "Cikti veya uyarilari asagida inceleyin.")
    if action == "list_scripts":
        return ("Kullanilabilir scriptler listelendi.", "Calistirmak icin scripts-run komutunu kullanabilirsiniz.")
    if result.get("steps"):
        return ("Istek uygun araclarla isletildi.", "Asagidaki sonuc kartlari yapilan adimlari gosteriyor.")
    return ("Islem tamamlandi.", None)


def _render_tool_steps(steps: list[dict]) -> None:
    for index, step in enumerate(steps, 1):
        tool = step.get("tool", "islem")
        print(f"[bold cyan]{index}. adim:[/bold cyan] {tool}")
        if tool == "get_system_status" and step.get("result"):
            result = step["result"]
            table = Table(title="Sistem Durumu")
            table.add_column("Metrik", style="cyan")
            table.add_column("Deger", style="green")
            table.add_row("CPU", f"{result.get('cpu_percent', '?')}%")
            table.add_row("RAM", f"{result.get('memory_percent', '?')}%")
            table.add_row("Disk", f"{result.get('disk_percent', '?')}%")
            table.add_row("Surec Sayisi", str(result.get("process_count", "?")))
            console.print(table)
            continue
        if tool in {"search_files", "list_scripts"} and step.get("items"):
            items = step["items"]
            table = Table(title=f"{tool} ({step.get('count', len(items))})")
            if tool == "list_scripts":
                table.add_column("Ad", style="cyan")
                table.add_column("Aciklama", style="green")
                for item in items:
                    table.add_row(item.get("name", "?"), item.get("description", ""))
            else:
                table.add_column("Dosya", style="cyan")
                table.add_column("Yol", style="dim")
                for item in items[:10]:
                    table.add_row(item.get("name", "?"), item.get("path", "?"))
            console.print(table)
            continue
        if tool == "send_file":
            print(f"[green]Gonderilen dosya:[/green] {step.get('sent_file', {}).get('path', '?')}")
            print(f"[green]Alici:[/green] {step.get('recipient', '?')}")
            continue
        if tool == "copy_file":
            print(f"[green]Kaynak:[/green] {step.get('source_file', {}).get('path', '?')}")
            print(f"[green]Kopya:[/green] {step.get('copied_file', {}).get('path', '?')}")
            continue
        if tool == "open_application":
            print(f"[green]Uygulama:[/green] {step.get('app_name', '?')}")
            if step.get("target"):
                print(f"[green]Hedef:[/green] {step.get('target')}")
            continue
        if tool == "take_screenshot":
            print(f"[green]Ekran resmi:[/green] {step.get('path', '?')}")
            continue
        if tool == "run_whitelisted_script":
            print(f"[green]Script:[/green] {step.get('script', '?')}")
            if step.get("stdout"):
                print(f"[dim]Cikti:[/dim] {step['stdout']}")
            if step.get("stderr"):
                print(f"[yellow]Uyari:[/yellow] {step['stderr']}")
            continue
        if step.get("summary"):
            print(step["summary"])


def _render_command_result(data: dict) -> None:
    action = data.get("action", "unknown")
    confidence = data.get("confidence", 0)
    
    summary = data.get("summary")
    next_step = data.get("next_step")
    
    if summary:
        print(f"[bold green]{summary}[/bold green]")
        
    print(f"[cyan]Aksiyon:[/cyan] {action} [dim](guven: {confidence:.0%})[/dim]")
    
    if next_step:
        print(f"[dim]Devam:[/dim] {next_step}")

    if data.get("knowledge_hint"):
        print(f"[yellow]Bilgi tabani:[/yellow] {data['knowledge_hint']}")

    error = data.get("error")
    if error:
        print(f"[red][HATA] {error}[/red]")
        return

    result = data.get("result")
    if not result:
        return

    if result.get("steps") and isinstance(result["steps"], list):
        _render_tool_steps(result["steps"])
        return

    items = result.get("items")
    if items and isinstance(items, list) and isinstance(items[0], dict) and "name" in items[0]:
        table = Table(title=f"Sonuclar ({result.get('count', len(items))})")
        table.add_column("Dosya", style="cyan")
        table.add_column("Boyut", style="green")
        for item in items[:10]:
            size_kb = item.get("size_bytes", 0) / 1024
            table.add_row(item.get("name", "?"), f"{size_kb:.1f} KB")
        console.print(table)
        return

    if result.get("status") == "pending_approval" or "items" in result:
        return

    print(json.dumps(result, ensure_ascii=False, indent=2))


def _execute_natural_language_command(text: str, approved: bool = False) -> bool:
    response = requests.post(
        f"{_base_url()}/command",
        headers=_headers(),
        json={"text": text, "approved": approved},
        timeout=180,
    )
    if _handle_error(response):
        return False
    data = response.json()
    _render_command_result(data)

    approval = data.get("approval", {})
    if approval.get("status") == "pending":
        print()
        confirm = typer.confirm("Islemi onayliyor musunuz?", default=False)
        if confirm:
            print("[cyan]Islem onaylandi, gerceklestiriliyor...[/cyan]")
            return _execute_natural_language_command(text, approved=True)
        else:
            print("[yellow]Islem iptal edildi.[/yellow]")

    if data.get("handoff_recommended"):
        print()
        if typer.confirm("Islem basarisiz oldu. Uzman destegi icin kayit (ticket) acmak ister misiniz?", default=True):
            print(f"[cyan]=> YENI DESTEK KAYDI ACILDI: '{text}'[/cyan]")
            # Gercek projede bu kisimda IT Service Desk'e API istegi gonderilir

    return True


@app.command()
def ping() -> None:
    """Sunucu saglik kontrolu."""
    try:
        response = requests.get(f"{_base_url()}/health", timeout=10)
        if response.status_code == 200:
            print("[green][OK] Sunucu calisiyor[/green]")
        _print_json_response(response)
    except requests.ConnectionError:
        print("[red][HATA] Sunucuya baglanilamadi[/red]")
        raise typer.Exit(1)


@app.command()
def status() -> None:
    """Sistem durumunu goster (CPU, RAM, Disk)."""
    response = requests.get(f"{_base_url()}/status", headers=_headers(), timeout=15)
    if _handle_error(response):
        return
    data = response.json()
    table = Table(title="Sistem Durumu")
    table.add_column("Metrik", style="cyan")
    table.add_column("Deger", style="green")
    table.add_row("CPU", f"{data.get('cpu_percent', '?')}%")
    table.add_row("RAM", f"{data.get('memory_percent', '?')}%")
    table.add_row("Disk", f"{data.get('disk_percent', '?')}%")
    table.add_row("Surec Sayisi", str(data.get("process_count", "?")))
    console.print(table)


@app.command()
def find(
    query: str = typer.Argument(..., help="Aranacak dosya adi"),
    location: str = typer.Option("desktop", "--location", "-l", help="Konum: desktop/documents/downloads"),
    extension: str = typer.Option("", "--ext", "-e", help="Dosya uzantisi filtresi (xlsx, pdf, vb.)"),
) -> None:
    """Dosya ara (Desktop/Documents/Downloads icinde)."""
    params = {"query": query, "location": location}
    if extension:
        params["extension"] = extension
    response = requests.get(
        f"{_base_url()}/files/search",
        headers=_headers(),
        params=params,
        timeout=30,
    )
    if _handle_error(response):
        return
    data = response.json()
    items = data.get("items", [])
    if not items:
        print("[yellow]Sonuc bulunamadi.[/yellow]")
        return
    table = Table(title=f"Arama Sonuclari ({data.get('count', len(items))} dosya)")
    table.add_column("#", style="dim")
    table.add_column("Dosya Adi", style="cyan")
    table.add_column("Boyut", style="green")
    table.add_column("Yol", style="dim")
    for i, item in enumerate(items, 1):
        size_kb = item.get("size_bytes", 0) / 1024
        table.add_row(str(i), item.get("name", "?"), f"{size_kb:.1f} KB", item.get("path", "?"))
    console.print(table)


@app.command("send-file")
def send_file(
    file_path: str = typer.Argument(..., help="Gonderilecek dosyanin yolu"),
    to: str = typer.Argument(..., help="Alici e-posta adresi"),
    subject: str = typer.Option("AI Destekli Teknik Destek Ajani", "--subject", "-s"),
    body: str = typer.Option("Istenen dosya ektedir.", "--body", "-b"),
) -> None:
    """Dosyayi belirtilen adrese mail at."""
    response = requests.post(
        f"{_base_url()}/files/send",
        headers=_headers(),
        json={"file_path": file_path, "to": to, "subject": subject, "body": body},
        timeout=30,
    )
    if _handle_error(response):
        return
    print("[green][OK] Dosya gonderildi![/green]")
    _print_json_response(response)


@app.command("send-latest")
def send_latest(
    to: str = typer.Argument(..., help="Alici e-posta adresi"),
    location: str = typer.Option("desktop", "--from", "-f", help="Konum: desktop/documents/downloads"),
    extension: str = typer.Option("", "--ext", "-e", help="Dosya uzantisi filtresi"),
) -> None:
    """En son degistirilen dosyayi bul ve gonder."""
    params = {"query": "", "location": location}
    if extension:
        params["extension"] = extension
    search_response = requests.get(
        f"{_base_url()}/files/search",
        headers=_headers(),
        params=params,
        timeout=30,
    )
    if _handle_error(search_response):
        return
    items = search_response.json().get("items", [])
    if not items:
        print("[yellow]Dosya bulunamadi.[/yellow]")
        return
    latest = max(items, key=lambda x: x.get("modified_at", 0))
    print(f"[cyan]En son dosya:[/cyan] {latest.get('name')} ({latest.get('path')})")
    send_response = requests.post(
        f"{_base_url()}/files/send",
        headers=_headers(),
        json={"file_path": latest["path"], "to": to},
        timeout=30,
    )
    if _handle_error(send_response):
        return
    print("[green][OK] Dosya gonderildi![/green]")


@app.command("scripts-list")
def scripts_list() -> None:
    """Kullanilabilir scriptleri listele."""
    response = requests.get(
        f"{_base_url()}/scripts/list",
        headers=_headers(),
        timeout=15,
    )
    if _handle_error(response):
        return
    data = response.json()
    items = data.get("items", [])
    if not items:
        print("[yellow]Script bulunamadi.[/yellow]")
        return
    table = Table(title="Kullanilabilir Scriptler")
    table.add_column("Ad", style="cyan")
    table.add_column("Aciklama", style="green")
    for item in items:
        table.add_row(item.get("name", "?"), item.get("description", ""))
    console.print(table)


@app.command("scripts-run")
def scripts_run(
    script_name: str = typer.Argument(..., help="Calistirilacak script adi"),
) -> None:
    """Whitelist'teki bir scripti calistir."""
    response = requests.post(
        f"{_base_url()}/scripts/run",
        headers=_headers(),
        json={"script_name": script_name},
        timeout=60,
    )
    if _handle_error(response):
        return
    data = response.json()
    print(f"[green][OK] Script calistirildi:[/green] {script_name}")
    if data.get("stdout"):
        print(f"[dim]Cikti:[/dim] {data['stdout']}")
    if data.get("stderr"):
        print(f"[yellow]Uyari:[/yellow] {data['stderr']}")


@app.command("tasks")
def tasks() -> None:
    """Gorev gecmisini listele."""
    response = requests.get(
        f"{_base_url()}/tasks",
        headers=_headers(),
        timeout=15,
    )
    if _handle_error(response):
        return
    data = response.json()
    items = data.get("items", [])
    if not items:
        print("[yellow]Henuz gorev kaydi yok.[/yellow]")
        return
    table = Table(title=f"Gorev Gecmisi ({data.get('count', len(items))} kayit)")
    table.add_column("ID", style="dim")
    table.add_column("Tur", style="cyan")
    table.add_column("Durum", style="green")
    table.add_column("Girdi", style="white", max_width=30)
    table.add_column("Cikti", style="dim", max_width=30)
    table.add_column("Tarih", style="dim")
    for item in items[:20]:
        status_color = "green" if item.get("status") == "success" else "red"
        table.add_row(
            str(item.get("id", "?")),
            item.get("task_type", "?"),
            f"[{status_color}]{item.get('status', '?')}[/{status_color}]",
            item.get("input_text", "")[:30],
            item.get("output_text", "")[:30],
            item.get("created_at", "")[:19],
        )
    console.print(table)


@app.command("task")
def task_detail(
    task_id: int = typer.Argument(..., help="Gorev ID'si"),
) -> None:
    """Belirli bir gorevin detayini goster."""
    response = requests.get(
        f"{_base_url()}/tasks/{task_id}",
        headers=_headers(),
        timeout=15,
    )
    if _handle_error(response):
        return
    _print_json_response(response)


@app.command("do")
def do_command(
    text: str = typer.Argument(..., help="Dogal dil komut metni"),
) -> None:
    """Dogal dil komutu calistir."""
    _execute_natural_language_command(text)


@app.command("chat")
def chat() -> None:
    """Interaktif agent modu. Komutu yazarak devam et."""
    print("[cyan]Agent chat modu basladi.[/cyan] Cikmak icin `exit`, `quit` veya `q` yaz.")
    while True:
        try:
            text = typer.prompt("agent")
        except (KeyboardInterrupt, EOFError):
            print("\n[yellow]Chat kapatildi.[/yellow]")
            raise typer.Exit(0)

        normalized = text.strip()
        if not normalized:
            continue
        if normalized.lower() in {"exit", "quit", "q"}:
            print("[yellow]Chat kapatildi.[/yellow]")
            return

        try:
            _execute_natural_language_command(normalized)
        except requests.ConnectionError:
            print("[red][HATA] Sunucuya baglanilamadi[/red]")
        except requests.RequestException as exc:
            print(f"[red][HATA][/red] Istek basarisiz: {exc}")


if __name__ == "__main__":
    app()
