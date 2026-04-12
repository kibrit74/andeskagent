## Kurumsal Teknik Destek Platformu — Multi‑Tenant Agent Dokumani

### 1. Amac
Bu platform, tek bir masaustu uygulamasi uzerinden farkli sirketlerin (or. Vestel, Sony) kendi teknik destek ajanini guvenli, izole ve ozellestirilebilir sekilde calistirmasini saglar. Her musteri kendi tenant’ina ait policy, tool seti ve entegrasyonlarini kullanir.

### 2. Temel Kavramlar
- Agent Client: Kullanicinin PC’sine kurulan masaustu uygulamasi.
- Tenant: Kurum/musteri izolasyonu (Vestel, Sony).
- Agent Profile: Tenant’a ait tool, policy ve prompt seti.
- Policy Engine: Izinli tool/aksiyon kurallarini uygular.
- Session Context: Kullanicinin aktif isi ve uygulama baglami.

### 3. Dagitim Modeli
#### 3.1 Tek Uygulama, Cok Tenant (Onerilen)
- Kullanici tek bir binary indirir.
- Giris yapinca tenant belirlenir.
- Tenant’a ait agent profili indirilir.
- Arac/entegrasyon/izinler tenant’a gore aktif olur.

#### 3.2 White‑Label (Opsiyonel)
- Buyuk musteriler icin ayri marka paketi.
- Ayni core, farkli gorunum ve ayarlar.
- Bakim maliyeti yuksektir; sadece buyuk sozlesmelerde onerilir.

### 4. Kullanici Yolculugu
1. Kullanici uygulamayi indirir ve kurar.
2. Login (SSO / mail dogrulama / activation key).
3. Backend tenant’i belirler ve agent profile indirir.
4. Kullanici komut verir; policy engine tenant kurallarina gore tool zincirini calistirir.
5. Istenirse kullanici destek bileti olusturur (tenant’a gore ticket provider farkli olabilir).

### 5. Mimari Bilesenler
#### 5.1 Agent Client
- Komut UI
- OCR / UI automation
- File ops
- Local session state
- Offline cache (kisa sureli)

#### 5.2 Tenant Service (Backend)
- Tenant + user management
- Agent profile config
- Policy engine
- Audit log

#### 5.3 Tool Runtime
- File / system / UI tools
- Mail / calendar / ticket integrations
- Optional agent browser session manager

### 6. Coklu Tenant Izolasyonu
#### 6.1 Veri Izolasyonu
- Tenant ID her request’te zorunlu.
- Data storage: tenant bazli partition veya ayri DB.

#### 6.2 Policy Izolasyonu
Her tenant icin ayri:
- allowed_tools
- blocked_actions
- allowed_folders
- mail_whitelist
- browser_domains_whitelist

#### 6.3 Prompt ve Skill Izolasyonu
Tenant basina:
- ozel prompt prefix
- ozel skill set
- ozel tool routing

### 7. Agent Profile Yapisi (Ornek)
```json
{
  "tenant_id": "vestel",
  "display_name": "Vestel Destek Asistani",
  "allowed_tools": ["search_file", "copy_file", "send_file", "open_application"],
  "blocked_actions": ["delete_file"],
  "allowed_folders": ["C:/Users/*/Desktop", "C:/Users/*/Documents"],
  "mail_whitelist": ["@vestel.com.tr"],
  "browser_domains_whitelist": ["mail.google.com", "calendar.google.com"],
  "prompts": {
    "system_prefix": "Vestel internal support policy..."
  }
}
```

### 8. Entegrasyon Modeli
#### 8.1 Mail / Calendar
- Tenant policy’ye gore aktif/pasif
- OAuth veya service account
- Gmail, Outlook, Microsoft 365 desteklenebilir

#### 8.2 Ticketing
- Tenant bazli entegrasyon (Jira / ServiceNow / Zendesk)
- Minimum MVP: JSON ticket store (local/central)

### 9. Guvenlik
- Tenant ID ve user ID tum loglarda zorunlu.
- Tool izinleri policy‑driven.
- Sensitive actions approval required.
- Audit log immutable (append‑only).

### 10. Update / Rollout
- Client update: auto‑update veya per‑tenant rollout.
- Agent profile: dynamic download, kod deploy beklemez.
- Feature flag: tenant bazinda toggle.

### 11. Operasyonel Yonetim
- Admin console:
  - tenant olustur
  - policy guncelle
  - tool whitelist/blacklist
  - audit log incele
- Monitoring:
  - error rate
  - tool latency
  - user flow completion

### 12. Onerilen Yol Haritasi
#### Phase 1 — Core Multi‑Tenant
- Tenant yonetimi
- Policy engine
- Agent profile fetch
- Audit log

#### Phase 2 — Entegrasyonlar
- Mail/Calendar
- Ticketing
- Web/Agent browser

#### Phase 3 — White‑Label
- UI theme
- tenant‑specific packaging

### 13. Kritik Kararlar
- Tek uygulama + tenant profile onerilir.
- White‑label sadece buyuk musteri icin.
- Tool seti tenant policy ile yonetilmeli.
