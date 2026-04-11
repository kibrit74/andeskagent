# Teknik Ajan Roadmap

Bu belge, mevcut Windows odakli teknik destek ajanini daha guvenli, daha kullanilabilir ve daha agentic bir urune donusturmek icin uygulanabilir yol haritasidir.

## Hedef Durum

Tek tek komut calistiran bir arac yerine:

- kullanici niyetini anlayan
- uygun tool veya akisi secen
- riskli aksiyonlarda onay isteyen
- sonuc ozeti cikaran
- basarisiz oldugunda handoff yapan
- web, CLI ve gelecekte diger kanallarda ayni davranisi koruyan

bir teknik destek ajani.

## Mevcut Durum Ozeti

Bugun sistem sunlari yapiyor:

- dogal dil komutlarini parse ediyor
- dosya ariyor
- dosya kopyaliyor
- mail gonderiyor
- whitelist script calistiriyor
- sistem durumu getiriyor
- web UI ve CLI uzerinden kullanim sunuyor
- task logluyor

Ancak su eksikler kritik:

- aksiyon onay mekanizmasi yok
- vaka ozeti ve cozum notu yok
- hata/handoff akisi sinirli
- browser auth/session sagligi zayif
- parser mantigi buyudukce bakimi zorlasacak
- knowledge grounding daginik

## Onceliklendirme

### P0

1. Case summary ve resolution note
Her komut icin su alanlar uretilmeli:
- kullanici ne istedi
- sistem ne yapti
- sonuc ne oldu
- bir sonraki adim ne

Basari olcutu:
- web ve CLI ciktilari bu ozetleri tutarli gosterir
- task kayitlari summary alanlariyla genisler

2. Approval gate
Asagidaki aksiyonlar onaysiz calismamali:
- mail gonderme
- dosya kopyalama
- script calistirma
- uygulama acma
- browser tabanli kritik aksiyonlar

Basari olcutu:
- her riskli aksiyon once pending approval olur
- onay verilmeden gercek operasyon tetiklenmez

3. Browser auth-state ve session health
Ozellikle Gmail/Playwright akislari icin:
- login gerekli mi
- compose acildi mi
- gonderim dogrulandi mi
- yeniden deneme gerekli mi

Basari olcutu:
- mail akislarinda teknik hata yerine durum bazli geri bildirim doner
- auth-state kontrolu ortak katmana tasinir

4. Knowledge grounding katmani
Tek bilgi kaynagi gorunumu altinda sunlar toplanmali:
- `knowledge/issues.csv`
- `scripts/manifest.json`
- task gecmisi
- temel yardim/urun aciklamalari

Basari olcutu:
- ajan cevaplarinda hangi bilgi kaynagina dayandigi izlenebilir olur
- gereksiz fallback script uretimi azalir

5. Handoff / ticket akisi
Sistem cozemiyorsa:
- handoff tavsiyesi
- destek kaydi olusturma
- acik problem ozeti
- önerilen sonraki adim

Basari olcutu:
- basarisiz komutlar dead-end yaratmaz

### P1

1. Intent flow builder
- training phrases
- flow tanimlari
- test/live modu
- explicit fallback kurallari

2. Omnichannel katmani
- Teams
- Slack
- Outlook tabanli tetikleme

3. Agent QA ve feedback loop
- basari orani
- hata tipi
- retry sayisi
- kullanici memnuniyeti veya cozuldu/cozulmedi sinyali

4. Remote support capability expansion
- unattended access entegrasyon tasarimi
- file transfer iyilestirmeleri
- browser access
- multi-monitor veya hedef ekran secimi

5. UI ve CLI parity
- ayni aksiyon ayni geri bildirim dilini korumali
- tum arac sonuclari insan okunur ozette toplanmali

### P2

1. Suggested reply ve auto resolution note
- kullaniciya gidecek hazir cevap
- destek ekibine ic not

2. Policy-aware personalization
- farkli kullanici rolleri
- farkli izin setleri
- farkli cihaz profilleri

3. Long-running workflows
- zamanlanmis takip
- tekrar kontrol gorevleri
- asenkron durum guncellemeleri

## Uygulanabilir Is Paketleri

### Paket A - Summary ve Approval Temeli

Kapsam:
- task modelini genislet
- approval state ekle
- command sonucuna summary ve next_step alanlari ekle

Dosya adaylari:
- `db.py`
- `server/routes/command.py`
- `server/routes/web.py`
- `cli/main.py`

### Paket B - Browser Session Health

Kapsam:
- Playwright mail akisini auth-state bazli hale getir
- ortak browser state kontrolu ekle
- yeniden kullanilabilir durum kodlari tanimla

Dosya adaylari:
- `adapters/mail_adapter.py`
- `scripts/send-mail-playwright.mjs`
- `server/routes/command.py`

### Paket C - Knowledge Layer

Kapsam:
- knowledge kaynaklarini tek servis altinda topla
- command parser ve tool planner bu katmani kullansin

Dosya adaylari:
- `core/command_parser.py`
- yeni `core/knowledge.py`
- `knowledge/issues.csv`
- `scripts/manifest.json`

### Paket D - Handoff ve Ticketing

Kapsam:
- basarisiz komut icin handoff objesi
- task icinde escalation nedeni
- UI ve CLI'da “destek kaydi ac” yolu

Dosya adaylari:
- `server/routes/command.py`
- `db.py`
- `server/routes/web.py`
- `cli/main.py`

## Teknik Tasarim Notlari

### Onerilen yeni response sekli

```json
{
  "action": "send_file",
  "confidence": 0.94,
  "summary": "Indirim Maili dosyasi bulundu ancak gonderim icin Gmail oturumu gerekiyor.",
  "next_step": "Acilan Edge penceresinde Gmail'e giris yapip komutu tekrar deneyin.",
  "approval": {
    "required": true,
    "status": "pending"
  },
  "result": {},
  "error": null
}
```

### Onerilen approval modeli

- `required`: bool
- `status`: `not_required | pending | approved | rejected | expired`
- `approval_token`: kisa omurlu id
- `approval_reason`: neden onay gerekli

### Onerilen handoff modeli

- `handoff_required`
- `handoff_reason`
- `suggested_ticket_type`
- `summary_for_human`

## Sprint Onerisi

### Sprint 1

- summary + next_step standardizasyonu
- approval veri modeli
- browser auth-state hata siniflari

### Sprint 2

- command approval akisi
- handoff/ticket taslagi
- knowledge service ilk surum

### Sprint 3

- intent flow builder taslagi
- kanal genisleme altyapisi
- kalite ve feedback metrikleri

## Basari Metrikleri

- ilk denemede basarili aksiyon orani
- kullanici tarafinda teknik hata gorme orani
- onaysiz riskli aksiyon sayisi
- handoff gerektiren komutlarda tamamlanan ticket oranı
- mail/browser tabanli aksiyonlarda auth-state kaynakli hata orani
