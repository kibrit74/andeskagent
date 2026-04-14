# Teknikajan + RustDesk Endpoint Agent Plan

## Karar

Musteri bilgisayarina OpenClaude kurulmaz. OpenClaude, OpenRouter ve Gemini SDK sunucu/operasyon tarafinda kalir. Musteri bilgisayarinda yalnizca guvenli uygulayici katman calisir:

- RustDesk client: uzak ekran, mouse ve klavye icin.
- Teknikajan Endpoint Agent: backend'den is alir, policy kontrolu yapar, komutu uygular ve sonucu geri yollar.
- Device token: cihaz kimligini dogrulamak icin.
- Policy/approval kurallari: hangi aksiyonlarin calisabilecegini sinirlamak icin.

## Faz 1: Endpoint Agent API Temeli

Hedef: Backend ile musteri cihazi arasinda guvenli komut kuyrugu olusturmak.

Tamamlanan ilk isler:

- `endpoint_devices` tablosu: cihaz kimligi, RustDesk ID, durum, capability ve metadata.
- `endpoint_jobs` tablosu: cihaza gonderilecek komut kuyrugu ve sonuclari.
- Operator API:
  - `POST /endpoint-agents/devices/register`
  - `GET /endpoint-agents/devices`
  - `POST /endpoint-agents/devices/{device_id}/jobs`
  - `GET /endpoint-agents/devices/{device_id}/jobs`
- Client API:
  - `POST /endpoint-agents/devices/{device_id}/heartbeat`
  - `POST /endpoint-agents/devices/{device_id}/profile`
  - `GET /endpoint-agents/devices/{device_id}/jobs/next`
  - `POST /endpoint-agents/devices/{device_id}/jobs/{job_id}/result`
- Device token ham olarak saklanmaz; SHA-256 hash saklanir.

## Faz 2: Windows Endpoint Agent

Hedef: Musteri PC'de Windows servisi gibi calisan hafif agent.

Ilk kapsam:

- Device register/provision komutu.
- Periyodik heartbeat.
- Job polling.
- Izinli aksiyonlar:
  - `get_system_status`
  - `run_script` sadece whitelist ile
  - `read_screen` policy izinliyse
  - `collect_logs`
- Sonuc teslimi: stdout, stderr, returncode, hata mesaji, metadata.

Tamamlanan ilk runner:

- `python -m endpoint_agent provision <api_base_url> <operator_token> --config-path config/endpoint_agent.json`
- `python -m endpoint_agent sync-profile --config-path config/endpoint_agent.json --rustdesk-id RUSTDESK_ID`
- `python -m endpoint_agent run-once --config-path config/endpoint_agent.json`
- `python -m endpoint_agent run --config-path config/endpoint_agent.json`
- Windows task installer: `scripts/endpoint-agent/install-windows-task.ps1`
- Windows task uninstaller: `scripts/endpoint-agent/uninstall-windows-task.ps1`
- Manuel tek tur calistirma: `scripts/endpoint-agent/run-once-windows.ps1`
- Config ornegi: `config/endpoint_agent.example.json`
- Varsayilan izinli aksiyonlar: `get_system_status`, `collect_logs`.
- `run_script` ve `read_screen` client config policy'sine eklenmeden calismaz.

Windows MVP kurulum ornegi:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\endpoint-agent\install-windows-task.ps1 `
  -ApiBaseUrl http://127.0.0.1:8000 `
  -OperatorToken 432323 `
  -AllowedActions get_system_status,collect_logs `
  -AllowedScripts dns_flush
```

Bu asamada Windows Scheduled Task kullanilir. `-RustDeskId` verilmezse installer `rustdesk.exe --get-id` ile RustDesk ID'yi otomatik bulmaya calisir. RustDesk farkli bir dizindeyse `-RustDeskPath C:\...\RustDesk.exe` verilebilir.

Paketleme ve servis kurulumu:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
powershell -ExecutionPolicy Bypass -File scripts\endpoint-agent\build-windows-exe.ps1
```

NSSM ile Windows Service kurulumu:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\endpoint-agent\install-windows-service-nssm.ps1 `
  -NssmPath C:\Tools\nssm\nssm.exe `
  -ApiBaseUrl http://127.0.0.1:8000 `
  -OperatorToken 432323 `
  -AllowedActions get_system_status,collect_logs `
  -AllowedScripts dns_flush
```

NSSM servis kurulumu da ayni RustDesk ID otomasyonunu kullanir. Config daha once olustuysa script yeniden provision yapmaz; mevcut `device_id/device_token` ile `sync-profile` calistirir ve RustDesk ID'yi backend kaydina isler.

Servis kaldirma:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\endpoint-agent\uninstall-windows-service-nssm.ps1 `
  -NssmPath C:\Tools\nssm\nssm.exe
```

Not: `OperatorToken` sadece provision sirasinda kullanilir. Kalici servis argumanlarinda saklanmaz; servis yalnizca `device_id` ve `device_token` iceren client config ile calisir.

Guvenlik:

- API key client'a gomulmez.
- Client sadece device token bilir.
- Destructive islemler default kapali kalir.
- Her job backend tarafinda audit log'a yazilir.

## Faz 3: RustDesk Self-host

Hedef: Kendi uzak masaustu altyapisi.

- HBBS/HBBR kurulumu.
- RustDesk ID ve cihaz kaydinin endpoint device kaydina otomatik baglanmasi.
- Online/offline durumunun backend panelinde gorunmesi.
- Relay ve direct connection ayarlarinin config/provision surecine eklenmesi.

## Faz 4: White-label Client

Hedef: RustDesk tabanli Teknikajan markali client.

- Teknikajan adi, logo ve bordo-altin tema.
- RustDesk server config gomulu dagitim.
- WebView icinde Teknikajan CLI/panel.
- Endpoint Agent servisinin installer ile birlikte kurulmasi.

## Faz 5: Otonom Kontrol

Hedef: AI planlama + endpoint agent uygulama + RustDesk goruntu akisi.

- Backend AI modeli komutu planlar.
- Policy engine komutu izin/onay seviyesine ayirir.
- Endpoint agent komutu uygular.
- RustDesk ekrani insan operator icin canli goruntu saglar.
- Tum aksiyonlar audit log'a yazilir.

## Not

Google/OpenClaude/Gemini gibi AI ve model provider bilesenleri musteri PC'ye kurulmaz. Bunlar backend/operasyon katmaninda kalir. Musteri PC yalnizca guvenli is uygulayici olarak calisir.
