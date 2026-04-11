from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse


router = APIRouter(tags=["web"])


HTML_PAGE = """<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Teknik Ajan</title>
  <style>
    :root {
      --bg: #f4efe7;
      --panel: #fffaf3;
      --ink: #1f2937;
      --muted: #6b7280;
      --line: #d6c7b4;
      --accent: #b45309;
      --accent-2: #0f766e;
      --danger: #b91c1c;
      --soft: #f6eadb;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top right, #fcd9b6 0, transparent 30%),
        linear-gradient(180deg, #f7f1e8 0%, var(--bg) 100%);
      min-height: 100vh;
    }
    .wrap {
      max-width: 980px;
      margin: 0 auto;
      padding: 32px 20px 48px;
    }
    h1 { margin: 0 0 8px; font-size: clamp(32px, 5vw, 52px); }
    .lead { color: var(--muted); margin: 0 0 24px; }
    .panel {
      background: color-mix(in srgb, var(--panel) 90%, white);
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 20px;
      box-shadow: 0 14px 40px rgba(31, 41, 55, 0.08);
    }
    textarea {
      width: 100%;
      min-height: 140px;
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 16px;
      font: inherit;
      resize: vertical;
      background: white;
    }
    .toolbar {
      display: flex;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
      margin-top: 14px;
    }
    button {
      border: 0;
      border-radius: 999px;
      padding: 12px 18px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      background: var(--accent);
      color: white;
    }
    .hint {
      color: var(--muted);
      font-size: 14px;
    }
    .btn-approve {
      background: var(--accent-2);
    }
    .btn-ticket {
      background: var(--danger);
    }
    .action-row {
      margin-top: 14px;
      display: flex;
      gap: 12px;
    }
    .examples {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin: 18px 0 0;
    }
    .chip {
      border: 1px solid var(--line);
      background: white;
      border-radius: 999px;
      padding: 10px 14px;
      cursor: pointer;
      color: var(--ink);
    }
    .result-shell {
      margin-top: 18px;
      display: grid;
      gap: 14px;
    }
    .status {
      border-radius: 16px;
      padding: 14px 16px;
      font-weight: 600;
      background: #fff;
      border: 1px solid var(--line);
    }
    .status.ok {
      color: var(--accent-2);
      border-color: color-mix(in srgb, var(--accent-2) 35%, white);
      background: color-mix(in srgb, var(--accent-2) 8%, white);
    }
    .status.err {
      color: var(--danger);
      border-color: color-mix(in srgb, var(--danger) 35%, white);
      background: color-mix(in srgb, var(--danger) 6%, white);
    }
    .summary {
      background: var(--soft);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 16px;
      line-height: 1.5;
    }
    .cards {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
    }
    .card {
      background: white;
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 14px;
    }
    .card h3 {
      margin: 0 0 8px;
      font-size: 15px;
    }
    .kv {
      margin: 4px 0;
      color: var(--muted);
      font-size: 14px;
      word-break: break-word;
    }
    .list {
      margin: 0;
      padding-left: 18px;
    }
  </style>
</head>
<body>
  <main class="wrap">
    <h1>Teknik destek icin ne yapmak istiyorsunuz?</h1>
    <p class="lead">Buraya duz metin yazin. Sistem uygun araci secip islemi yapmaya calisir.</p>
    <section class="panel">
      <textarea id="prompt" placeholder="Ornek: masaustumdeki excel dosyasini bul ve yavuzob@gmail.com adresine gonder"></textarea>
      <div class="toolbar">
        <button id="send">Gonder</button>
        <div class="hint">Ctrl+Enter ile de calistirabilirsiniz.</div>
      </div>
      <div class="examples">
        <button class="chip" type="button">sistem durumunu goster</button>
        <button class="chip" type="button">scriptleri listele</button>
        <button class="chip" type="button">masaustumdeki excel dosyalarini bul</button>
        <button class="chip" type="button">indirim maili excelini yavuzob@gmail.com adresine gonder</button>
        <button class="chip" type="button">chrome'u ac ve ekran resmi al</button>
      </div>
      <div class="result-shell" id="result">
        <div class="status">Hazir.</div>
      </div>
    </section>
  </main>
  <script>
    const promptEl = document.getElementById('prompt');
    const resultEl = document.getElementById('result');
    const sendBtn = document.getElementById('send');

    function escapeHtml(value) {
      return String(value)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
    }

    function renderItems(items) {
      if (!Array.isArray(items) || !items.length) return '<div class="kv">Sonuc bulunamadi.</div>';
      const rows = items.slice(0, 8).map((item) => {
        const name = escapeHtml(item.name || item.path || 'Kayit');
        const path = escapeHtml(item.path || '');
        return `<li>${name}${path ? ` <span class="kv">${path}</span>` : ''}</li>`;
      }).join('');
      return `<ul class="list">${rows}</ul>`;
    }

    function renderStep(step) {
      const tool = step.tool || 'islem';
      if (tool === 'get_system_status' && step.result) {
        const r = step.result;
        return `
          <div class="card">
            <h3>Sistem Durumu</h3>
            <div class="kv">CPU: ${escapeHtml(r.cpu_percent ?? '-')}%</div>
            <div class="kv">RAM: ${escapeHtml(r.memory_percent ?? '-')}%</div>
            <div class="kv">Disk: ${escapeHtml(r.disk_percent ?? '-')}%</div>
            <div class="kv">Surec: ${escapeHtml(r.process_count ?? '-')}</div>
          </div>
        `;
      }
      if (tool === 'search_files') {
        return `
          <div class="card">
            <h3>Dosya Arama</h3>
            <div class="kv">${escapeHtml(step.count ?? 0)} sonuc bulundu</div>
            ${renderItems(step.items)}
          </div>
        `;
      }
      if (tool === 'copy_file') {
        return `
          <div class="card">
            <h3>Dosya Kopyalandi</h3>
            <div class="kv">Kaynak: ${escapeHtml(step.source_file?.path || '')}</div>
            <div class="kv">Kopya: ${escapeHtml(step.copied_file?.path || '')}</div>
          </div>
        `;
      }
      if (tool === 'send_file') {
        return `
          <div class="card">
            <h3>Dosya Gonderildi</h3>
            <div class="kv">Alici: ${escapeHtml(step.recipient || '')}</div>
            <div class="kv">Dosya: ${escapeHtml(step.sent_file?.path || '')}</div>
          </div>
        `;
      }
      if (tool === 'list_scripts') {
        const items = Array.isArray(step.items) ? step.items : [];
        const html = items.map((item) => `<li>${escapeHtml(item.name || '')} <span class="kv">${escapeHtml(item.description || '')}</span></li>`).join('');
        return `
          <div class="card">
            <h3>Scriptler</h3>
            <ul class="list">${html}</ul>
          </div>
        `;
      }
      if (tool === 'run_whitelisted_script') {
        return `
          <div class="card">
            <h3>Script Calisti</h3>
            <div class="kv">Script: ${escapeHtml(step.script || '')}</div>
            <div class="kv">Kod: ${escapeHtml(step.returncode ?? '')}</div>
          </div>
        `;
      }
      if (tool === 'open_application') {
        return `
          <div class="card">
            <h3>Uygulama Acildi</h3>
            <div class="kv">Uygulama: ${escapeHtml(step.app_name || '')}</div>
            ${step.target ? `<div class="kv">Hedef: ${escapeHtml(step.target)}</div>` : ''}
          </div>
        `;
      }
      if (tool === 'take_screenshot') {
        return `
          <div class="card">
            <h3>Ekran Resmi Alindi</h3>
            <div class="kv">Dosya: ${escapeHtml(step.path || '')}</div>
          </div>
        `;
      }
      return `
        <div class="card">
          <h3>${escapeHtml(tool)}</h3>
          <div class="kv">Islem tamamlandi.</div>
        </div>
      `;
    }

    function renderLegacyResult(result) {
      if (!result) return '';
      if (result.items) {
        return `
          <div class="card">
            <h3>Sonuclar</h3>
            <div class="kv">${escapeHtml(result.count ?? result.items.length)} kayit</div>
            ${renderItems(result.items)}
          </div>
        `;
      }
      if (result.sent_file || result.latest_file) {
        const file = result.sent_file || result.latest_file;
        return `
          <div class="card">
            <h3>Islem Sonucu</h3>
            ${result.recipient ? `<div class="kv">Alici: ${escapeHtml(result.recipient)}</div>` : ''}
            <div class="kv">Dosya: ${escapeHtml(file.path || '')}</div>
            ${result.message ? `<div class="kv">${escapeHtml(result.message)}</div>` : ''}
          </div>
        `;
      }
      return `<div class="card"><h3>Sonuc</h3><div class="kv">${escapeHtml(result.message || 'Islem tamamlandi.')}</div></div>`;
    }

    function renderResponse(data, originalText) {
      const sections = [];
      const hasError = Boolean(data.error);

      let summary = escapeHtml(data.summary || "");
      if (hasError && !summary) summary = escapeHtml(data.error);

      let nextStep = escapeHtml(data.next_step || "");

      sections.push(`<div class="status ${hasError ? 'err' : 'ok'}">${summary || (hasError ? "Hata olustu." : "Islem tamamlandi.")}</div>`);
      
      sections.push(`
        <div class="summary">
          <strong>Aksiyon:</strong> ${escapeHtml(data.action || 'unknown')}<br>
          <strong>Guven:</strong> ${escapeHtml(Math.round((data.confidence || 0) * 100))}%<br>
          ${nextStep ? `<strong>Devam:</strong> ${nextStep}<br>` : ''}
          ${data.knowledge_hint ? `<strong>Ipuclari:</strong> ${escapeHtml(data.knowledge_hint)}` : ''}
          ${hasError && data.error ? `<br><strong style="color:var(--danger)">Detay:</strong> ${escapeHtml(data.error)}` : ''}
        </div>
      `);

      if (data.approval?.status === "pending") {
        sections.push(`
          <div class="action-row">
            <button class="btn-approve" data-text="${escapeHtml(originalText)}">Bu Işlemi Onayla ve Gerçekleştir</button>
          </div>
        `);
      }

      if (data.handoff_recommended) {
        sections.push(`
          <div class="action-row">
            <button class="btn-ticket" data-text="${escapeHtml(originalText)}">Uzman Desteği İçin Kayıt (Ticket) Aç</button>
          </div>
        `);
      }

      const cards = [];
      if (data.result?.steps) {
        data.result.steps.forEach((step) => cards.push(renderStep(step)));
      } else if (data.result && data.result.status !== "pending_approval") {
        cards.push(renderLegacyResult(data.result));
      }
      if (cards.length) {
        sections.push(`<div class="cards">${cards.join('')}</div>`);
      }
      resultEl.innerHTML = sections.join('');

      const approveBtn = resultEl.querySelector('.btn-approve');
      if (approveBtn) {
        approveBtn.addEventListener('click', () => {
          sendPrompt(true, approveBtn.getAttribute('data-text'));
        });
      }

      const ticketBtn = resultEl.querySelector('.btn-ticket');
      if (ticketBtn) {
        ticketBtn.addEventListener('click', () => {
          alert('BT Destek birimine ticket olusturuldu! Konu: ' + ticketBtn.getAttribute('data-text'));
        });
      }
    }

    async function sendPrompt(isApproval = false, overrideText = null) {
      const text = overrideText || promptEl.value.trim();
      if (!text) {
        resultEl.innerHTML = '<div class="status err">Once ne yapmak istediginizi yazin.</div>';
        return;
      }
      if (!isApproval) {
        sendBtn.disabled = true;
      }
      resultEl.innerHTML = '<div class="status">Calisiyor...</div>';
      try {
        const res = await fetch('/command-ui', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text, approved: isApproval })
        });
        const data = await res.json();
        renderResponse(data, text);
      } catch (err) {
        resultEl.innerHTML = `<div class="status err">Istek basarisiz: ${escapeHtml(err)}</div>`;
      } finally {
        sendBtn.disabled = false;
      }
    }

    sendBtn.addEventListener('click', () => sendPrompt(false));
    promptEl.addEventListener('keydown', (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
        sendPrompt(false);
      }
    });
    document.querySelectorAll('.chip').forEach((button) => {
      button.addEventListener('click', () => {
        promptEl.value = button.textContent;
        sendPrompt(false);
      });
    });
  </script>
</body>
</html>
"""


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def home() -> str:
    return HTML_PAGE
