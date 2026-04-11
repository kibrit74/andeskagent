"""POST /command dogal dil komutu alip parse edip calistiran endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from adapters.desktop_adapter import click_ui, focus_window, list_windows, read_screen, take_screenshot, wait_for_window
from adapters.file_adapter import (
    copy_file_to_location,
    create_folder_in_location,
    delete_file_in_place,
    move_file_to_location,
    rename_file_in_place,
    search_files,
)
from adapters.mail_adapter import send_email_with_attachment
from adapters.script_adapter import generate_and_run_script, run_script
from adapters.script_adapter import _open_application as open_application
from adapters.system_adapter import get_system_status
from adapters.system_adapter import get_system_status
from core.auth import bearer_token_dependency
from core.command_parser import parse_command
from core.config import add_mail_recipient_to_whitelist, load_settings
from core.errors import BrowserStateError, BrowserAuthError
from db import log_task


settings = load_settings()
router = APIRouter(
    tags=["command"],
    dependencies=[Depends(bearer_token_dependency(settings.bearer_token))],
)
ui_router = APIRouter(tags=["command-ui"])


class CommandRequest(BaseModel):
    text: str
    approved: bool = False


class ApprovalStatus(BaseModel):
    required: bool
    status: str


class CommandResponse(BaseModel):
    action: str
    confidence: float
    summary: str
    next_step: str
    approval: ApprovalStatus
    params: dict
    result: dict | None = None
    knowledge_hint: str | None = None
    error: str | None = None
    handoff_recommended: bool = False


def _humanize_error(message: str) -> str:
    normalized = (message or "").lower()
    if "gmail_login_required" in normalized:
        return "Mail gondermek icin once Gmail oturumu acmaniz gerekiyor. Acilan Edge penceresinde giris yapip tekrar deneyin."
    if "gmail_compose_not_ready" in normalized:
        return "Gmail yazma ekrani hazir degil. Gmail sekmesinde oturumun acik oldugunu ve sayfanin yuklendiginini kontrol edin."
    if "gmail_send_not_confirmed" in normalized:
        return "Mail gonderimi dogrulanamadi. Gmail penceresini kontrol edip tekrar deneyin."
    if "gemini api anahtari ayarlanmamis" in normalized:
        return "Yapay zeka entegrasyonu hazir degil. Gemini anahtarini ayarlamaniz gerekiyor."
    if "recipient not in whitelist" in normalized:
        return "Bu alici adresine gonderim izni yok. Izinli alici listesini kontrol edin."
    if "at least one recipient is required" in normalized or "alici e-posta adresi gerekli" in normalized:
        return "Gonderim icin alici e-posta adresi eksik."
    if "attachment not found" in normalized or "gonderilecek dosya bulunamadi" in normalized:
        return "Gonderilecek dosya bulunamadi. Dosya adini veya konumunu daha net yazin."
    if "eslesen dosya bulunamadi" in normalized:
        return "Istenen dosya bulunamadi. Dosya adini veya uzantisini daha net yazin."
    if "kopyalanacak dosya bulunamadi" in normalized:
        return "Kopyalanacak dosya bulunamadi. Kaynak dosya adini daha net yazin."
    if "desteklenmeyen uygulama" in normalized:
        return "Bu uygulama su an dogrudan acilamiyor. Daha bilinen bir uygulama adi yazin."
    if "uygulama acilamadi" in normalized:
        return "Uygulama acilamadi. Uygulamanin kurulu oldugunu ve adini dogru yazdigini kontrol edin."
    if "ekran resmi alinamadi" in normalized:
        return "Ekran resmi alinamadi. Masaustu oturumu acik olmayabilir."
    if "script whitelist disinda" in normalized:
        return "Bu scripti calistirma izni yok."
    if "script manifest icinde bulunamadi" in normalized or "script adi gerekli" in normalized:
        return "Istenen script bulunamadi veya script adi anlasilmadi."
    if "browser mail send failed" in normalized or "did not return a result" in normalized or "compose butonu bulunamadi" in normalized:
        return "Mail gonderilemedi. Tarayici oturumu veya mail hesabi hazir olmayabilir."
    if "generated script blocked by safety rule" in normalized:
        return "Istek guvenlik kurallarina takildi. Daha guvenli ve dar bir komut deneyin."
    if "generated script failed" in normalized:
        return "Uretilen otomasyon calismadi. Istegi daha acik ve daha dar kapsamli yazin."
    if "generated script timed out" in normalized:
        return "Uretilen otomasyon zaman asimina ugradi. Uygulama asili kalmis olabilir; daha dar bir komut deneyin."
    if "desteklenmeyen tool" in normalized:
        return "Bu istek su an desteklenmeyen bir arac gerektiriyor."
    return message or "Islem tamamlanamadi."


def _search_with_fallback(*, query: str, location: str, extension: str | None) -> tuple[list[dict], str]:
    preferred = (location or "desktop").strip() or "desktop"
    ordered_locations: list[str] = [preferred]
    for candidate in ("desktop", "documents", "downloads"):
        if candidate != preferred:
            ordered_locations.append(candidate)

    for candidate_location in ordered_locations:
        items = search_files(
            query=query,
            location=candidate_location,
            extension=extension,
            allowed_folders=settings.allowed_folders,
        )
        if items:
            return items, candidate_location
    return [], preferred


@router.post("/command")
def execute_command(request: CommandRequest) -> CommandResponse:
    """Dogal dil komutunu parse et ve ilgili aksiyonu calistir."""
    parsed = None
    result = None
    error = None
    summary = ""
    next_step = ""
    approval_required = False
    approval_status = "not_required"
    handoff_recommended = False

    try:
        parsed = parse_command(request.text, settings)

        if parsed.action == "search_file":
            items, resolved_location = _search_with_fallback(
                query=parsed.params.get("query", ""),
                location=parsed.params.get("location", "desktop"),
                extension=parsed.params.get("extension"),
            )
            summary = f"{len(items)} adet dosya bulundu."
            next_step = "Isterseniz bu dosyalari siralayabilir veya size gonderilmesini isteyebilirsiniz."
            result = {"items": items, "count": len(items), "resolved_location": resolved_location}

        elif parsed.action == "copy_file":
            items, resolved_location = _search_with_fallback(
                query=parsed.params.get("query", ""),
                location=parsed.params.get("location", "desktop"),
                extension=parsed.params.get("extension"),
            )
            if items:
                selected = max(items, key=lambda x: x.get("modified_at", 0))
                approval_required = True
                approval_status = "approved" if request.approved else "pending"
                if approval_status == "pending":
                    summary = f"'{selected['name']}' dosyasi bulundu. Kopyalama islemi onay bekliyor."
                    next_step = "Lutfen dosyayi kopyalamak amaciyla isleme onay verin."
                    result = {"source_file": selected, "status": "pending_approval"}
                else:
                    copied = copy_file_to_location(
                        selected["path"],
                        destination_location=parsed.params.get("destination_location", "desktop"),
                        allowed_folders=settings.allowed_folders,
                    )
                    summary = "Dosya kopyalama islemi onaylandi ve gerceklestirildi."
                    next_step = "Baska bir ihtiyaciniz var mi?"
                    result = {
                        "source_file": selected,
                        "copied_file": copied,
                        "status": "copied",
                        "message": "Dosyanin kopyasi olusturuldu.",
                        "resolved_location": resolved_location,
                    }
            else:
                summary = "Kopyalanacak dosya bulunamadi."
                next_step = "Dosyanin adini veya uzantisini kontrol ederek tekrar deneyin."
                result = {"message": "Eslesen dosya bulunamadi."}

        elif parsed.action == "move_file":
            items, resolved_location = _search_with_fallback(
                query=parsed.params.get("query", ""),
                location=parsed.params.get("location", "desktop"),
                extension=parsed.params.get("extension"),
            )
            if items:
                selected = max(items, key=lambda x: x.get("modified_at", 0))
                destination_location = parsed.params.get("destination_location", "desktop")
                approval_required = True
                approval_status = "approved" if request.approved else "pending"
                if approval_status == "pending":
                    summary = f"'{selected['name']}' dosyasi {destination_location} konumuna tasinacak. Onay gerekiyor."
                    next_step = "Tasima islemini onaylayin."
                    result = {
                        "source_file": selected,
                        "destination_location": destination_location,
                        "resolved_location": resolved_location,
                        "status": "pending_approval",
                    }
                else:
                    moved = move_file_to_location(
                        selected["path"],
                        destination_location=destination_location,
                        allowed_folders=settings.allowed_folders,
                    )
                    summary = "Dosya tasima islemi tamamlandi."
                    next_step = "Baska bir ihtiyaciniz var mi?"
                    result = {
                        "source_file": selected,
                        "moved_file": moved,
                        "status": "moved",
                        "resolved_location": resolved_location,
                    }
            else:
                summary = "Tasinacak dosya bulunamadi."
                next_step = "Dosya adini veya uzantisini kontrol ederek tekrar deneyin."
                result = {"message": "Eslesen dosya bulunamadi."}

        elif parsed.action == "rename_file":
            items, resolved_location = _search_with_fallback(
                query=parsed.params.get("query", ""),
                location=parsed.params.get("location", "desktop"),
                extension=parsed.params.get("extension"),
            )
            if items:
                selected = max(items, key=lambda x: x.get("modified_at", 0))
                new_name = parsed.params.get("new_name", "")
                approval_required = True
                approval_status = "approved" if request.approved else "pending"
                if approval_status == "pending":
                    summary = f"'{selected['name']}' dosyasi yeniden adlandirilacak. Onay gerekiyor."
                    next_step = "Yeniden adlandirma islemini onaylayin."
                    result = {
                        "source_file": selected,
                        "new_name": new_name,
                        "resolved_location": resolved_location,
                        "status": "pending_approval",
                    }
                else:
                    renamed = rename_file_in_place(
                        selected["path"],
                        new_name=str(new_name),
                        allowed_folders=settings.allowed_folders,
                    )
                    summary = "Dosya yeniden adlandirildi."
                    next_step = "Baska bir ihtiyaciniz var mi?"
                    result = {
                        "source_file": selected,
                        "renamed_file": renamed,
                        "status": "renamed",
                        "resolved_location": resolved_location,
                    }
            else:
                summary = "Yeniden adlandirilacak dosya bulunamadi."
                next_step = "Dosya adini veya uzantisini kontrol ederek tekrar deneyin."
                result = {"message": "Eslesen dosya bulunamadi."}

        elif parsed.action == "delete_file":
            items, resolved_location = _search_with_fallback(
                query=parsed.params.get("query", ""),
                location=parsed.params.get("location", "desktop"),
                extension=parsed.params.get("extension"),
            )
            if items:
                selected = max(items, key=lambda x: x.get("modified_at", 0))
                approval_required = True
                approval_status = "approved" if request.approved else "pending"
                if approval_status == "pending":
                    summary = f"'{selected['name']}' dosyasi silinecek. Onay gerekiyor."
                    next_step = "Silme islemini onaylayin."
                    result = {
                        "source_file": selected,
                        "resolved_location": resolved_location,
                        "status": "pending_approval",
                    }
                else:
                    deleted = delete_file_in_place(
                        selected["path"],
                        allowed_folders=settings.allowed_folders,
                    )
                    summary = "Dosya silindi."
                    next_step = "Baska bir ihtiyaciniz var mi?"
                    result = {
                        "deleted_file": deleted,
                        "status": "deleted",
                        "resolved_location": resolved_location,
                    }
            else:
                summary = "Silinecek dosya bulunamadi."
                next_step = "Dosya adini veya uzantisini kontrol ederek tekrar deneyin."
                result = {"message": "Eslesen dosya bulunamadi."}

        elif parsed.action == "send_latest":
            items, resolved_location = _search_with_fallback(
                query=parsed.params.get("query", ""),
                location=parsed.params.get("location", "desktop"),
                extension=parsed.params.get("extension"),
            )
            if items:
                latest = max(items, key=lambda x: x.get("modified_at", 0))
                recipient = parsed.params.get("recipient")
                if recipient:
                    approval_required = True
                    approval_status = "approved" if request.approved else "pending"
                    if approval_status == "pending":
                        summary = f"'{latest['name']}' dosyasi bulundu. Mail gonderimi onay bekliyor."
                        next_step = "Riski onlemek adina gonderimi onaylayin."
                        result = {"latest_file": latest, "recipient": recipient, "status": "pending_approval"}
                    else:
                        settings.mail_recipients_whitelist = add_mail_recipient_to_whitelist(str(recipient))
                        send_email_with_attachment(
                            recipient=recipient,
                            subject="AI Destekli Teknik Destek Ajani",
                            body="Istenen dosya ektedir.",
                            file_path=latest["path"],
                            host=settings.smtp_host,
                            port=settings.smtp_port,
                            username=settings.smtp_username,
                            password=settings.smtp_password,
                            use_tls=settings.smtp_use_tls,
                            sender=settings.default_mail_from,
                            allowed_recipients=settings.mail_recipients_whitelist,
                            mail_transport=settings.mail_transport,
                            browser_channel=settings.playwright_browser_channel,
                            user_data_dir=settings.playwright_user_data_dir,
                            mail_url=settings.playwright_mail_url,
                            headless=settings.playwright_headless,
                        )
                        summary = f"'{latest['name']}' dosyasi {recipient} adresine gonderildi."
                        next_step = "Baska bir ihtiyaciniz varsa iletebilirsiniz."
                        result = {
                            "latest_file": latest,
                            "recipient": recipient,
                            "status": "sent",
                            "message": "En son dosya bulundu ve gonderildi.",
                            "resolved_location": resolved_location,
                        }
                else:
                    summary = f"En son dosya ({latest['name']}) bulundu, ancak alici belirtilmedigi icin gonderilemiyor."
                    next_step = "Lutfen komutu alici adresi ile birlikte tekrar yazin."
                    result = {
                        "latest_file": latest,
                        "message": "Dosya bulundu. Gondermek icin alici e-posta adresi gerekli.",
                        "resolved_location": resolved_location,
                    }
            else:
                summary = "Uzanti veya konuma uygun dosya bulunamadi."
                next_step = "Farkli bir klasor belirtmeyi veya uzantiyi degistirmeyi deneyin."
                result = {"message": "Eslesen dosya bulunamadi."}

        elif parsed.action == "create_folder":
            approval_required = True
            approval_status = "approved" if request.approved else "pending"
            folder_name = parsed.params.get("folder_name", "Yeni Klasor")
            destination_location = parsed.params.get("destination_location", "desktop")
            if approval_status == "pending":
                summary = f"'{folder_name}' isimli klasor {destination_location} konumunda olusturulacak. Onay gerekiyor."
                next_step = "Klasor olusturma islemini onaylayin."
                result = {
                    "folder_name": folder_name,
                    "destination_location": destination_location,
                    "status": "pending_approval",
                }
            else:
                created = create_folder_in_location(
                    str(folder_name),
                    destination_location=str(destination_location),
                    allowed_folders=settings.allowed_folders,
                )
                summary = f"'{created['name']}' klasoru olusturuldu."
                next_step = "Baska bir ihtiyaciniz var mi?"
                result = {
                    "created_folder": created,
                    "status": "created",
                }

        elif parsed.action == "open_application":
            approval_required = True
            approval_status = "approved" if request.approved else "pending"
            app_name = parsed.params.get("app_name", "")
            target = parsed.params.get("target")
            if approval_status == "pending":
                summary = f"'{app_name}' uygulamasi acilacak. Onay gerekiyor."
                next_step = "Uygulamayi acmak icin islemi onaylayin."
                result = {"app_name": app_name, "target": target, "status": "pending_approval"}
            else:
                resolved_target = str(target).strip() if target is not None else ""
                result = open_application(app_name=str(app_name), target=resolved_target or None)
                summary = f"'{app_name}' uygulamasi acildi veya one getirildi."
                next_step = "Gerekirse sonraki adimi yazabilirsiniz."

        elif parsed.action == "list_windows":
            result = list_windows()
            summary = f"{result.get('count', 0)} adet gorunen pencere bulundu."
            next_step = "Odaklanmak istediginiz pencereyi belirtebilirsiniz."

        elif parsed.action == "focus_window":
            approval_required = True
            approval_status = "approved" if request.approved else "pending"
            if approval_status == "pending":
                summary = "Belirtilen pencereye gecilecek. Onay gerekiyor."
                next_step = "Pencere odagini degistirmek icin islemi onaylayin."
                result = {"status": "pending_approval", **parsed.params}
            else:
                result = focus_window(
                    title_contains=str(parsed.params.get("title_contains", "")).strip() or None,
                    process_name=str(parsed.params.get("process_name", "")).strip() or None,
                )
                summary = "Pencere one getirildi."
                next_step = "Gerekirse sonraki komutu yazabilirsiniz."

        elif parsed.action == "wait_for_window":
            result = wait_for_window(
                title_contains=str(parsed.params.get("title_contains", "")).strip() or None,
                process_name=str(parsed.params.get("process_name", "")).strip() or None,
                timeout_seconds=int(parsed.params.get("timeout_seconds", 20) or 20),
            )
            summary = "Beklenen pencere bulundu."
            next_step = "Gerekirse pencereye odaklanabilir veya bir sonraki adimi calistirabilirsiniz."

        elif parsed.action == "click_ui":
            approval_required = True
            approval_status = "approved" if request.approved else "pending"
            if approval_status == "pending":
                summary = "Arayuzde bir hedefe tiklanacak. Onay gerekiyor."
                next_step = "Tiklama islemini onaylayin."
                result = {"status": "pending_approval", **parsed.params}
            else:
                result = click_ui(
                    x=int(parsed.params["x"]) if "x" in parsed.params else None,
                    y=int(parsed.params["y"]) if "y" in parsed.params else None,
                    button=str(parsed.params.get("button", "left")).strip() or "left",
                    text=str(parsed.params.get("text", "")).strip() or None,
                    title_contains=str(parsed.params.get("title_contains", "")).strip() or None,
                    process_name=str(parsed.params.get("process_name", "")).strip() or None,
                )
                summary = "Hedef arayuz ogesi tiklandi."
                next_step = "Gerekirse ekrani tekrar okuyabilir veya bir sonraki adimi yazabilirsiniz."

        elif parsed.action == "read_screen":
            approval_required = True
            approval_status = "approved" if request.approved else "pending"
            if approval_status == "pending":
                summary = "Ekran durumu toplanacak. Onay gerekiyor."
                next_step = "Ekran goruntusu almak icin islemi onaylayin."
                result = {"status": "pending_approval"}
            else:
                result = read_screen()
                summary = "Ekran durumu toplandi."
                next_step = "Gerekirse devam komutunu yazabilirsiniz."

        elif parsed.action == "take_screenshot":
            approval_required = True
            approval_status = "approved" if request.approved else "pending"
            if approval_status == "pending":
                summary = "Ekran goruntusu alinacak. Onay gerekiyor."
                next_step = "Ekran goruntusu almak icin islemi onaylayin."
                result = {"status": "pending_approval"}
            else:
                result = take_screenshot()
                summary = "Ekran goruntusu alindi."
                next_step = "Dosya yolunu sonuc ekraninda gorebilirsiniz."

        elif parsed.action == "run_script":
            approval_required = True
            approval_status = "approved" if request.approved else "pending"
            script_names = parsed.params.get("script_names")
            if isinstance(script_names, list) and script_names:
                if approval_status == "pending":
                    summary = f"Sistemde {len(script_names)} adet guvenli script calistirilmak isteniyor."
                    next_step = "Sisteme yetkili erisim saglamak icin onayinizi isaretlemeniz gereklidir."
                    result = {"script_names": script_names, "status": "pending_approval"}
                else:
                    steps: list[dict] = []
                    for script_name in script_names:
                        steps.append(
                            {
                                "tool": "run_whitelisted_script",
                                **run_script(str(script_name), allowed_scripts=settings.allowed_scripts),
                            }
                        )
                    summary = f"Secili {len(script_names)} adet script onay sonrasi calistirildi."
                    next_step = "Ciktilari asagidaki ekranda kontrol edebilirsiniz."
                    result = {
                        "summary": "Hazir script zinciri calistirildi.",
                        "steps": steps,
                        "step_count": len(steps),
                    }
            else:
                script_name = parsed.params.get("script_name", "")
                if not script_name:
                    summary = "Calistirilacak spesifik bir script belirlenemedi."
                    next_step = "Hangi script'in calistirilacagini daha net ifade edin (or. 'dns onarim scriptini calistir')."
                    error = "Hangi scriptin calistirilacagi belirlenemedi."
                else:
                    if approval_status == "pending":
                        summary = f"'{script_name}' isimli scripti calistirmak uzeresiniz. Onay gerekiyor."
                        next_step = "Islemi onaylayip devam edin."
                        result = {"script_name": script_name, "status": "pending_approval"}
                    else:
                        result = run_script(script_name, allowed_scripts=settings.allowed_scripts)
                        summary = f"'{script_name}' isimli script basariyla calistirildi."
                        next_step = "Sistem veya ag uzerinde cikan degisiklikleri dogrulayin."

        elif parsed.action == "system_status":
            result = get_system_status()
            summary = "Sistem durumu ve zafiyet analizleri alindi."
            next_step = ""

        elif parsed.action == "list_scripts":
            from adapters.script_adapter import list_scripts

            items = list_scripts()
            summary = f"Toplam {len(items)} adet whitelist scripti bulundu."
            next_step = "Calistirmak istediginiz scriptin ismini yazabilirsiniz."
            result = {"items": items, "count": len(items)}

        elif parsed.action == "send_file":
            items, resolved_location = _search_with_fallback(
                query=parsed.params.get("query", ""),
                location=parsed.params.get("location", "desktop"),
                extension=parsed.params.get("extension"),
            )
            if items:
                recipient = parsed.params.get("recipient")
                if recipient:
                    approval_required = True
                    approval_status = "approved" if request.approved else "pending"
                    selected = max(items, key=lambda x: x.get("modified_at", 0))
                    if approval_status == "pending":
                        summary = f"'{selected['name']}' dosyasi bulundu. Mail gonderimi yonetici onayi bekliyor."
                        next_step = "Lutfen yapilandirmayi dogrulayarak gonderme onayi verin."
                        result = {"sent_file": selected, "recipient": recipient, "status": "pending_approval"}
                    else:
                        settings.mail_recipients_whitelist = add_mail_recipient_to_whitelist(str(recipient))
                        send_email_with_attachment(
                            recipient=recipient,
                            subject="AI Destekli Teknik Destek Ajani",
                            body="Istenen dosya ektedir.",
                            file_path=selected["path"],
                            host=settings.smtp_host,
                            port=settings.smtp_port,
                            username=settings.smtp_username,
                            password=settings.smtp_password,
                            use_tls=settings.smtp_use_tls,
                            sender=settings.default_mail_from,
                            allowed_recipients=settings.mail_recipients_whitelist,
                            mail_transport=settings.mail_transport,
                            browser_channel=settings.playwright_browser_channel,
                            user_data_dir=settings.playwright_user_data_dir,
                            mail_url=settings.playwright_mail_url,
                            headless=settings.playwright_headless,
                        )
                        summary = f"'{selected['name']}' isimli dosya e-posta olarak {recipient} adresine iletildi."
                        next_step = "Alici kisisinin urun maillerini teyit edin."
                        result = {
                            "sent_file": selected,
                            "recipient": recipient,
                            "count": len(items),
                            "status": "sent",
                            "message": "Dosya bulundu ve gonderildi.",
                            "resolved_location": resolved_location,
                        }
                else:
                    summary = "Birden fazla dosya bulundu ancak alici maili belirtilmemis."
                    next_step = "Alici adresi ile komutu tekrar gonderin."
                    result = {
                        "found_files": items[:5],
                        "count": len(items),
                        "message": "Dosyalar bulundu. Gonderim icin alici e-posta adresi gerekli.",
                        "resolved_location": resolved_location,
                    }
            else:
                summary = "Iletilmek istenen dosya mevcut degil."
                next_step = "Dosya adini gozden gecirin veya arama limitlerini genisletin."
                result = {"message": "Eslesen dosya bulunamadi."}

        else:
            approval_required = True
            approval_status = "approved" if request.approved else "pending"
            if approval_status == "pending":
                summary = "Sistemin standart cozum yollari veya yetenekleri disinda olan bir islem algilandi."
                next_step = "Guvenli cercevede isleme devam etmek icin onaylayiniz."
                result = {"status": "pending_approval"}
            else:
                try:
                    result = generate_and_run_script(
                        request.text,
                        api_key=settings.gemini_api_key,
                        model=settings.gemini_model,
                        allowed_folders=settings.allowed_folders,
                        forbidden_actions=settings.forbidden_actions,
                    )
                    summary = "Sistemdeki kural tabanli otomasyon islendi."
                    next_step = "Konsol ciktilarina bakabilirsiniz."
                except Exception as eval_exc:
                    summary = "Sistem bu istegi zekice analiz etti fakat gerceklestirebilecek guvenli bir yol bulamadi."
                    error = str(eval_exc)
                    handoff_recommended = True
                    next_step = "Lutfen 'ticket ac' komutunu kullanarak durumu uzman ekibe bildirin."

        log_task(
            settings.sqlite_path,
            task_type="command",
            status="success" if not error else "failed",
            input_text=request.text,
            output_text=str(result) if result else str(error),
            metadata={
                "action": parsed.action,
                "confidence": parsed.confidence,
                "params": parsed.params,
                "summary": summary,
                "next_step": next_step,
                "approval_status": approval_status,
            },
        )

    except BrowserAuthError as exc:
        error = f"Oturum izni gerekiyor: {exc.message} (Hata Kodu: {exc.code})"
        summary = "Tarayicida islem yapabilmek icin ilgili hesaba giris yapmaniz gerekmektedir."
        next_step = "Lutfen masaustunde acilan yeni tarayici penceresinden oturum acip komutu tekrar calistirin."
        log_task(
            settings.sqlite_path,
            task_type="command",
            status="error",
            input_text=request.text,
            output_text=str(exc),
            metadata={"action": parsed.action if parsed else "parse_failed", "error_code": exc.code},
        )
    except BrowserStateError as exc:
        error = f"Sayfa hazir degil veya dogrulanamadi: {exc.message} (Hata Kodu: {exc.code})"
        summary = "Tarayici islemini gerceklestirirken sayfa yuklenmesi veya durumunda hata olustu."
        next_step = "Sistem yogunlugu veya teknik bir sikinti olabilir. Birkac saniye bekleyip tekrar deneyin."
        log_task(
            settings.sqlite_path,
            task_type="command",
            status="error",
            input_text=request.text,
            output_text=str(exc),
            metadata={"action": parsed.action if parsed else "parse_failed", "error_code": exc.code},
        )
    except (ValueError, RuntimeError, PermissionError) as exc:
        error = _humanize_error(str(exc))
        handoff_recommended = True
        if not summary:
            summary = "Sistem bu islem sirasinda beklenmeyen bir bloklayici ile karsilasti."
        next_step = "Destek kaydi olusturarak BT ekibine durumu iletebilirsiniz."
        log_task(
            settings.sqlite_path,
            task_type="command",
            status="error",
            input_text=request.text,
            output_text=str(exc),
            metadata={"action": parsed.action if parsed else "parse_failed"},
        )
    except Exception as exc:
        error = f"Yapay Zeka Servis Hatasi: {str(exc)}"
        handoff_recommended = True
        if not summary:
            summary = "Gorev islenirken dis servislere baglanti kurulamadi veya model yogunlugu yasandi."
        next_step = "Isterseniz isleme birkac dakika sonra tekrar baslayabilir veya destek bileti olusturabilirsiniz."
        log_task(
            settings.sqlite_path,
            task_type="command",
            status="error",
            input_text=request.text,
            output_text=str(exc),
            metadata={"action": parsed.action if parsed else "parse_failed", "type": type(exc).__name__},
        )

    return CommandResponse(
        action=parsed.action if parsed else "unknown",
        confidence=parsed.confidence if parsed else 0.0,
        summary=summary,
        next_step=next_step,
        approval=ApprovalStatus(required=approval_required, status=approval_status),
        params=parsed.params if parsed else {},
        result=result,
        knowledge_hint=parsed.knowledge_hint if parsed else None,
        error=error,
        handoff_recommended=handoff_recommended,
    )


@ui_router.post("/command-ui", response_model=CommandResponse, include_in_schema=False)
def execute_command_ui(request: CommandRequest) -> CommandResponse:
    return execute_command(request)
