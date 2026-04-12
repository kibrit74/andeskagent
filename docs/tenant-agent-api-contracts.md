## API Kontratlari (Mevcut ve Planlanan)

Bu dokuman iki bolumden olusur:
1. Mevcut uygulamadaki API yuzeyi (uygulanmis).
2. Kurumsal multi-tenant mimari icin planlanan API yuzeyi (taslak).

Tum response’larda `tenant_id` ve `request_id` loglanacak sekilde tasarlanir.

---

## A) Mevcut API (Uygulanmis)

### 1. Komut Calistirma
#### POST /command
Request:
```json
{
  "text": "Gmail'e git ve takvime etkinlik ekle",
  "approved": false
}
```
Response (ornek):
```json
{
  "action": "unknown",
  "workflow_profile": "agent_browser",
  "summary": "Browser oturumu hazirlaniyor.",
  "next_step": "Gerekirse onaylayin.",
  "approval": { "required": true, "status": "pending" }
}
```

#### POST /command-ui
`/command` ile ayni request/response, UI icin kullanilir.

---

### 2. Sistem
#### GET /status
Response:
```json
{
  "cpu_percent": 22.5,
  "memory_percent": 61.1,
  "disk_percent": 48.0,
  "process_count": 110,
  "open_applications": ["chrome", "outlook"]
}
```

#### GET /tasks
Response:
```json
{ "items": [], "count": 0 }
```

#### GET /tasks/{task_id}
Response:
```json
{ "item": { "id": 1, "task_type": "command", "status": "success" } }
```

---

### 3. Dosya
#### GET /files/search
Query:
```
?query=rapor&location=desktop&extension=pdf
```
Response:
```json
{ "items": [], "count": 0 }
```

#### POST /files/send
Request:
```json
{
  "file_path": "C:/Users/.../rapor.pdf",
  "to": "user@company.com",
  "subject": "AI Destekli Teknik Destek Ajani",
  "body": "Istenen dosya ektedir."
}
```
Response:
```json
{ "status": "sent" }
```

---

### 4. Script
#### GET /scripts/list
Response:
```json
{ "items": ["dns_flush"], "count": 1 }
```

#### POST /scripts/run
Request:
```json
{ "script_name": "dns_flush" }
```
Response:
```json
{ "returncode": 0 }
```

---

### 5. Web UI
#### GET /
Ana UI sayfasi.

#### GET /mobile-cli
Mobil CLI.

#### GET /qr.svg
Mobil CLI icin QR cikti.

---

### 6. Live Screen
#### WS /ws/screen
WebSocket uzerinden ekran kareleri.

---

## B) Planlanan API (Multi‑Tenant Platform)

### 1. Auth
#### POST /auth/login
Request:
```json
{
  "email": "user@company.com",
  "password": "secret"
}
```
Response:
```json
{
  "access_token": "jwt",
  "tenant_id": "vestel",
  "user_id": "u-123"
}
```

### 2. Agent Profile
#### GET /tenants/{tenant_id}/agent-profile
Response:
```json
{
  "tenant_id": "vestel",
  "display_name": "Vestel Destek Asistani",
  "allowed_tools": ["search_file", "copy_file", "send_file", "open_application"],
  "blocked_actions": ["delete_file"],
  "allowed_folders": ["C:/Users/*/Desktop", "C:/Users/*/Documents"],
  "mail_whitelist": ["@vestel.com.tr"],
  "browser_domains_whitelist": ["mail.google.com", "calendar.google.com"],
  "prompts": { "system_prefix": "Vestel internal support policy..." }
}
```

### 3. Browser Session
#### POST /browser/session/open
Request:
```json
{
  "purpose": "mail",
  "startup_url": "https://mail.google.com/",
  "reuse": true
}
```
Response:
```json
{
  "session_id": "browser-mail",
  "status": "ready",
  "url": "https://mail.google.com/"
}
```

#### POST /browser/session/navigate
Request:
```json
{
  "session_id": "browser-mail",
  "url": "https://calendar.google.com/"
}
```
Response:
```json
{
  "session_id": "browser-mail",
  "status": "loaded",
  "title": "Google Calendar"
}
```

### 4. PDF Isleme
#### POST /pdf/open
Request:
```json
{ "file_path": "C:/Users/.../Enerjisa.pdf" }
```
Response:
```json
{ "session_id": "browser-pdf", "document_type": "pdf", "page_count": 12 }
```

#### POST /pdf/links
Request:
```json
{ "session_id": "browser-pdf" }
```
Response:
```json
{ "links": [ { "index": 0, "url": "https://vdi.enerjisa.com.tr", "label": "Yeni Citrix Adresi" } ] }
```

#### POST /pdf/click-link
Request:
```json
{ "session_id": "browser-pdf", "match": "citrix" }
```
Response:
```json
{ "opened": true, "target_url": "https://vdi.enerjisa.com.tr" }
```

### 5. Ticket
#### POST /tickets
Request:
```json
{
  "title": "Outlook mail gondermiyor",
  "description": "ticket ac outlook mail gondermiyor"
}
```
Response:
```json
{ "ticket_id": 42, "status": "created" }
```
