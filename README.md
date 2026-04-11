# agent-ops — AI Destekli Teknik Destek Ajanı

Windows odaklı uzaktan teknik destek ajanı. Doğal dil komutlarıyla dosya arama, mail gönderme, script çalıştırma ve sistem izleme yapabilir.

## Kurulum

1. Python 3.11+ kurun
2. `pip install -r requirements.txt`
3. `config/settings.json` içindeki token ve SMTP bilgilerini güncelleyin
4. `uvicorn server.main:app --reload`
5. `python -m cli.main ping`

## Gemini Parser

`/command` endpoint'i artik Gemini ile parse edilir.

1. `config/settings.json` icine `gemini_api_key` girin veya `GEMINI_API_KEY` ortam degiskenini ayarlayin
2. Gerekirse `gemini_model` degerini degistirin
3. Bagimliliklari tekrar kurun: `pip install -r requirements.txt`

## API Endpointleri

| Method | Endpoint         | Açıklama                          |
|--------|------------------|-----------------------------------|
| GET    | /health          | Sunucu sağlık kontrolü            |
| GET    | /status          | Sistem durumu (CPU, RAM, Disk)     |
| GET    | /files/search    | Dosya arama                       |
| POST   | /files/send      | Dosya mail gönderme               |
| POST   | /scripts/run     | Script çalıştırma                 |
| GET    | /scripts/list    | Kullanılabilir scriptler           |
| GET    | /tasks           | Görev geçmişi                     |
| GET    | /tasks/{id}      | Görev detayı                      |
| POST   | /command         | Doğal dil komut çalıştırma        |

## CLI Komutları

```bash
# Temel
agentctl ping
agentctl status

# Dosya
agentctl find "mart takipler"
agentctl send-file "C:\Users\...\dosya.xlsx" user@domain.com
agentctl send-latest user@domain.com --ext xlsx

# Script
agentctl scripts-list
agentctl scripts-run outlook_repair
agentctl scripts-run dns_flush

# Görev
agentctl tasks
agentctl task 12

# Doğal dil
agentctl do "masaüstündeki mart takipler dosyasını bana gönder"
agentctl do "outlook önbelleğini temizle"
```

## Güvenlik

- Bearer token ile korumalı tüm endpointler
- İzinli klasör listesi (whitelist): Desktop, Documents, Downloads
- İzinli komut listesi (whitelist): outlook_repair, dns_flush, clear_temp, office_repair, restart_service
- Yasaklı işlemler: delete_system_files, modify_registry, network_config_change

## Teknik Stack

| Bileşen         | Teknoloji        |
|-----------------|------------------|
| Backend         | Python 3.11+     |
| API             | FastAPI          |
| CLI             | Typer + Rich     |
| Veritabanı      | SQLite           |
| Sistem izleme   | psutil           |
| Mail            | smtplib          |
| Script çalıştır | subprocess       |
| Auth            | Bearer token     |

## Klasör Yapısı

```
agent-ops/
├── server/
│   ├── main.py              # FastAPI app
│   └── routes/
│       ├── files.py          # dosya işlemleri
│       ├── mail.py           # mail gönderme
│       ├── system.py         # sistem bilgisi
│       ├── scripts.py        # BAT/PS çalıştırma
│       └── command.py        # doğal dil komut
├── cli/
│   └── main.py              # Typer CLI
├── adapters/
│   ├── file_adapter.py      # dosya arama/seçme
│   ├── mail_adapter.py      # mail gönderme
│   ├── system_adapter.py    # sistem bilgisi
│   └── script_adapter.py    # script çalıştırma
├── core/
│   ├── auth.py              # token kontrolü
│   ├── config.py            # ayarlar
│   ├── logger.py            # loglama
│   └── command_parser.py    # doğal dil parser
├── scripts/
│   ├── windows/             # PS1 + BAT scriptleri
│   └── manifest.json        # script meta verileri
├── knowledge/
│   └── issues.csv           # sorun → çözüm veritabanı
├── config/
│   ├── settings.json        # sunucu ayarları
│   └── whitelist.json       # izinli klasörler ve komutlar
├── logs/
│   └── ops.log
└── data/
    └── app.db
```

## Notlar

- `config/settings.json` içindeki token ve SMTP bilgileri gerçek değerlerle güncellenmelidir
- Tüm işlemler SQLite veritabanına loglanır
- Doğal dil parser MVP aşamasında kural tabanlıdır (v2'de LLM entegrasyonu planlanmaktadır)
