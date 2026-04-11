# Implementation Plan

Bu belge `ROADMAP.md` icindeki oncelikleri uygulanabilir teslim planina indirger.

## Hemen Baslanacak P0

### 1. Summary + Next Step Standardizasyonu

Amac:
- her komut sonucunda tutarli `summary`
- her komut sonucunda tutarli `next_step`
- web ve CLI'da ayni dil

Teslimler:
- ortak response helper
- command response alanlari
- task log summary alanlari

Durum:
- baslanabilir

Risk:
- mevcut response uyumlulugu

### 2. Approval Gate Temeli

Amac:
- riskli aksiyonlari hemen calistirmak yerine once bekletmek

Kapsam:
- `send_file`
- `send_latest`
- `copy_file`
- `run_script`
- `open_application`

Teslimler:
- approval modeli
- approval saklama
- `/approvals/{id}/approve` benzeri endpoint taslagi
- web ve CLI onay akisi

Durum:
- tasarim gerekli

Risk:
- mevcut UX akisinin kirilmasi

### 3. Browser Auth-State Katmani

Amac:
- Gmail/Playwright akislarinda login, compose, send confirmation durumlarini ortaklestirmek

Teslimler:
- durum kodlari
- adapter seviyesinde normalize hata modeli
- yeniden deneme veya yeniden giris yonlendirmesi

Durum:
- kismen mevcut, genisletilecek

Risk:
- Gmail arayuz degiskenligi

### 4. Knowledge Service Ilk Surum

Amac:
- parser ve tool planner'in ayni grounding kaynagini kullanmasi

Kaynaklar:
- `knowledge/issues.csv`
- `scripts/manifest.json`
- gorev gecmisi

Teslimler:
- `core/knowledge.py`
- normalize knowledge lookup
- command parser entegrasyonu

Durum:
- tasarim gerekli

Risk:
- bilgi kaynaklari icin siralama/agirliklandirma

## Sonraki P1

### 5. Handoff ve Ticket Taslagi

Teslimler:
- handoff modeli
- UI/CLI tarafinda “destek kaydi ac” yolu
- insan operatore yonelik ozet

### 6. Intent Flow Builder

Teslimler:
- flow config dosyasi
- training phrase yapisi
- test/live ayrimi

### 7. Feedback ve QA

Teslimler:
- kullanici geri bildirimi
- basari metriği
- hata kategorisi dashboard verisi

## Sprint Onerisi

### Sprint 1

- Summary + next_step
- browser auth-state
- approval veri modeli

### Sprint 2

- approval akisi
- knowledge service
- handoff taslagi

### Sprint 3

- intent flow builder
- feedback loop
- kanal genisleme taslagi

## Teknik Ayrim

### Backend

- response modeli standardizasyonu
- approval persistence
- browser state normalization
- knowledge lookup service

### UI

- onay bekleyen aksiyon karti
- summary/next_step karti
- handoff butonu

### CLI

- onay komutlari
- daha iyi hata yonlendirmesi
- task summary goruntuleme

## Bitirme Kriterleri

- riskli aksiyonlar onaysiz calismaz
- her sonuc icin summary + next_step vardir
- Gmail benzeri akislarda auth-state teknik hata yerine durum bazli anlatilir
- knowledge lookup tek servis uzerinden calisir
