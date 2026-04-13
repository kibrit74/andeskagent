const terminalBody = document.getElementById('terminal-body');
const cliInput = document.getElementById('cli-input');

let lastCommandText = '';

let commandHistory = [];
let historyIndex = -1;
let currentInputCache = '';

const urlParams = new URLSearchParams(window.location.search);
const bearerTokenFromUrl = urlParams.get('token');
if (bearerTokenFromUrl) {
    localStorage.setItem('bearer_token', bearerTokenFromUrl.trim());
}

const inputWrapper = document.querySelector('.terminal-input-wrapper');
let slashMenu = document.createElement('div');
slashMenu.className = 'slash-menu';
inputWrapper.appendChild(slashMenu);

const slashCommands = [
    { cmd: '/temizle', icon: '🧹', desc: 'Ekranı temizler' },
    { cmd: '/iptal', icon: '✖', desc: 'Son işlemi iptal eder' },
    { cmd: '/durum', icon: '📊', desc: 'Sistem durumunu raporlar' },
    { cmd: '/yardim', icon: '❓', desc: 'Yardım ve komut listesi' },
    { cmd: '/init', icon: '🧭', desc: 'Proje bağlamı dosyası oluşturur' },
    { cmd: '/memory', icon: '🧠', desc: 'Hafıza yönetimi (list/ekle/sil)' },
    { cmd: '/model', icon: '🧩', desc: 'Model sağlayıcı/model seçimi' },
    { cmd: '/plan', icon: '🧪', desc: 'Plan modu aç/kapat' },
    { cmd: '/compact', icon: '🗜️', desc: 'Oturum özetini kaydeder' },
    { cmd: '/usage', icon: '💸', desc: 'Kullanım bilgisi' },
    { cmd: '/rewind', icon: '⏪', desc: 'Son kayıt geri al' },
    { cmd: '/audit', icon: '📄', desc: 'Oturum audit raporu' },
    { cmd: '/agent', icon: '🤖', desc: 'Agent profili seç/listele' }
];

let slashSelectedIndex = 0;
let slashActive = false;

function renderSlashMenu(filter = '') {
    const filtered = slashCommands.filter(c => c.cmd.toLowerCase().startsWith(filter.toLowerCase()));
    
    if (filtered.length === 0 || !slashActive || filter === '') {
        slashMenu.classList.remove('active');
        return;
    }

    const wrapperRect = inputWrapper.getBoundingClientRect();
    const left = Math.max(8, wrapperRect.left + 20);
    const top = wrapperRect.bottom + 12;
    const availableHeight = Math.max(160, window.innerHeight - top - 16);
    const width = Math.min(wrapperRect.width - 40, 360);
    slashMenu.style.position = 'fixed';
    slashMenu.style.left = `${left}px`;
    slashMenu.style.top = `${top}px`;
    slashMenu.style.width = `${width}px`;
    slashMenu.style.maxHeight = `${Math.min(420, availableHeight)}px`;

    slashMenu.classList.add('active');
    slashMenu.innerHTML = '';
    
    if (slashSelectedIndex >= filtered.length) slashSelectedIndex = 0;
    if (slashSelectedIndex < 0) slashSelectedIndex = filtered.length - 1;
    
    filtered.forEach((item, index) => {
        const div = document.createElement('div');
        div.className = `slash-item ${index === slashSelectedIndex ? 'selected' : ''}`;
        div.innerHTML = `
            <div class="slash-item-icon">${item.icon}</div>
            <div class="slash-item-text">
                <div class="slash-item-title">${item.cmd}</div>
                <div class="slash-item-desc">${item.desc}</div>
            </div>
        `;
        div.addEventListener('click', () => {
            const rawCmd = item.cmd.replace('/', '');
            cliInput.value = rawCmd;
            slashMenu.classList.remove('active');
            slashActive = false;
            cliInput.focus();
            
            // Opsiyonel: direkt enter atılabilir
        });
        slashMenu.appendChild(div);
    });
}

function renderHelpCommands() {
    return `
        <div class="result-section">
            <div class="result-title-container">
                <div class="result-title">Komut Listesi</div>
            </div>
            <div class="result-grid">
                ${slashCommands.map((item) => `
                    <div class="result-card">
                        <div class="result-key">${escapeHtml(item.cmd)}</div>
                        <div class="result-value">${escapeHtml(item.desc)}</div>
                    </div>
                `).join('')}
            </div>
        </div>
    `;
}

function scrollToBottom() {
    terminalBody.scrollTop = terminalBody.scrollHeight;
}

function forceScrollToBottom() {
    scrollToBottom();
    requestAnimationFrame(() => {
        scrollToBottom();
        requestAnimationFrame(scrollToBottom);
    });
}

function autoResizeInput() {
    cliInput.style.height = 'auto';
    cliInput.style.height = `${Math.min(cliInput.scrollHeight, 180)}px`;
}

function createMessageElement(contentHtml) {
    const div = document.createElement('div');
    div.className = 'message';
    div.style.flexDirection = 'column';
    div.style.alignItems = 'flex-start';
    div.style.width = '100%';
    div.innerHTML = contentHtml;
    terminalBody.appendChild(div);
    forceScrollToBottom();
    return div;
}

function escapeHtml(value) {
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function humanizeKey(key) {
    return String(key)
        .replace(/_/g, ' ')
        .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
        .replace(/\s+/g, ' ')
        .trim()
        .replace(/^./, (char) => char.toUpperCase());
}

function formatPrimitive(value) {
    if (value === null || value === undefined || value === '') {
        return '-';
    }
    if (typeof value === 'boolean') {
        return value ? 'Evet' : 'Hayir';
    }
    return String(value);
}

function renderObjectRows(obj) {
    return Object.entries(obj)
        .map(([key, value]) => {
            if (value && typeof value === 'object') {
                return `
                    <div class="result-card">
                        <div class="result-key">${escapeHtml(humanizeKey(key))}</div>
                        <div class="result-value">${renderStructuredValue(value)}</div>
                    </div>
                `;
            }

            return `
                <div class="result-row">
                    <div class="result-key">${escapeHtml(humanizeKey(key))}</div>
                    <div class="result-value">${escapeHtml(formatPrimitive(value))}</div>
                </div>
            `;
        })
        .join('');
}

function renderArray(items) {
    const primitiveOnly = items.every((item) => item === null || ['string', 'number', 'boolean'].includes(typeof item));

    if (primitiveOnly) {
        return `
            <ul class="result-bullets">
                ${items.map((item) => `<li>${escapeHtml(formatPrimitive(item))}</li>`).join('')}
            </ul>
        `;
    }

    return items
        .map((item, index) => `
            <div class="result-card">
                <div class="result-key">Kayit ${index + 1}</div>
                <div class="result-value">${renderStructuredValue(item)}</div>
            </div>
        `)
        .join('');
}

function renderStructuredValue(value) {
    if (Array.isArray(value)) {
        return renderArray(value);
    }

    if (value && typeof value === 'object') {
        return `<div class="result-grid">${renderObjectRows(value)}</div>`;
    }

    return escapeHtml(formatPrimitive(value));
}

function renderWorkflowSteps(steps) {
    return `
        <div class="workflow-list">
            ${steps.map((step, index) => {
                const status = step && step.status ? String(step.status) : 'unknown';
                const title = step && (step.title || step.tool) ? String(step.title || step.tool) : `Adim ${index + 1}`;
                const verificationHtml = step && step.verification
                    ? `<div class="workflow-step-verification">${escapeHtml(String(step.verification))}</div>`
                    : '';
                const verifiedBadgeHtml = step && step.verified === true
                    ? `<div class="workflow-step-verified">Dogrulandi</div>`
                    : '';
                const rawStepPayload = step && typeof step === 'object'
                    ? Object.fromEntries(Object.entries(step).filter(([key]) => !['title', 'status'].includes(key)))
                    : null;
                const body = step && step.result
                    ? renderStructuredValue(step.result)
                    : step && step.error
                        ? `<div class="error-text">${escapeHtml(step.error)}</div>`
                        : rawStepPayload
                            ? renderStructuredValue(rawStepPayload)
                        : '';

                return `
                    <div class="workflow-step ${escapeHtml(status)}">
                        <div class="workflow-step-head">
                            <div class="workflow-step-title">${escapeHtml(title)}</div>
                            <div class="workflow-step-status-wrap">
                                ${verifiedBadgeHtml}
                                <div class="workflow-step-status">${escapeHtml(status)}</div>
                            </div>
                        </div>
                        ${verificationHtml}
                        ${body}
                    </div>
                `;
            }).join('')}
        </div>
    `;
}

function renderSessionContext(sessionContext) {
    if (!sessionContext || typeof sessionContext !== 'object') {
        return '';
    }

    const processName = sessionContext.process_name ? escapeHtml(sessionContext.process_name) : '';
    const title = sessionContext.title ? escapeHtml(sessionContext.title) : '';
    const fileName = sessionContext.file_name ? escapeHtml(sessionContext.file_name) : '';
    const parts = [processName, title, fileName].filter(Boolean);

    if (!parts.length) {
        return '';
    }

    return `
        <div class="session-context-badge">
            <span class="session-context-label">Aktif Oturum</span>
            <span class="session-context-value">${parts.join(' / ')}</span>
        </div>
    `;
}

function renderBrowserContext(browserContext) {
    if (!browserContext || typeof browserContext !== 'object') {
        return '';
    }

    const mode = browserContext.mode ? escapeHtml(browserContext.mode) : '';
    const provider = browserContext.provider ? escapeHtml(browserContext.provider) : '';
    const title = browserContext.title ? escapeHtml(browserContext.title) : '';
    const origin = browserContext.origin ? escapeHtml(browserContext.origin) : '';
    const fileName = browserContext.file_name ? escapeHtml(browserContext.file_name) : '';
    const linkCount = Number.isFinite(Number(browserContext.interactive_links))
        ? Number(browserContext.interactive_links)
        : null;

    const metaParts = [provider, mode].filter(Boolean).join(' / ');
    const headlineParts = [title, origin, fileName].filter(Boolean).join(' / ');
    const linkBadge = linkCount !== null
        ? `<span class="browser-context-chip">Link: ${linkCount}</span>`
        : '';

    if (!metaParts && !headlineParts) {
        return '';
    }

    return `
        <div class="browser-context-badge">
            <div class="browser-context-row">
                <span class="browser-context-label">Agent Tarayici</span>
                <span class="browser-context-meta">${metaParts || '-'}</span>
            </div>
            ${headlineParts ? `<div class="browser-context-title">${headlineParts}</div>` : ''}
            <div class="browser-context-chips">
                ${linkBadge}
                ${browserContext.authenticated === true ? '<span class="browser-context-chip success">Oturum Acik</span>' : ''}
            </div>
        </div>
    `;
}

function renderTiming(timing) {
    if (!timing || typeof timing !== 'object') {
        return '';
    }
    const total = Number.isFinite(Number(timing.total_ms)) ? Number(timing.total_ms).toFixed(1) : null;
    const parse = Number.isFinite(Number(timing.parse_ms)) ? Number(timing.parse_ms).toFixed(1) : null;
    const execute = Number.isFinite(Number(timing.execute_ms)) ? Number(timing.execute_ms).toFixed(1) : null;
    if (!total && !parse && !execute) {
        return '';
    }
    const parts = [];
    if (total) parts.push(`toplam ${total}ms`);
    if (parse) parts.push(`parse ${parse}ms`);
    if (execute) parts.push(`islem ${execute}ms`);
    if (timing.resumed === true) parts.push('resume');
    return `<div class="timing-badge">${escapeHtml(parts.join(' / '))}</div>`;
}

function renderResult(result) {
    if (result && typeof result === 'object' && Array.isArray(result.steps)) {
        const rawJson = escapeHtml(JSON.stringify(result, null, 2));
        return `
            <div class="result-section">
                <div class="result-title-container">
                    <div class="result-title">Is Akisi</div>
                    <button class="copy-btn dom-copy-btn" data-clipboard="${rawJson}" title="JSON olarak Kopyala">📋</button>
                </div>
                ${renderWorkflowSteps(result.steps)}
            </div>
        `;
    }

    if (!result || typeof result !== 'object') {
        const rawPrimitive = escapeHtml(formatPrimitive(result));
        return `
            <div class="result-section">
                <div class="result-title-container">
                    <div class="result-title">Sonuc</div>
                    <button class="copy-btn dom-copy-btn" data-clipboard="${rawPrimitive}" title="Kopyala">📋</button>
                </div>
                <div class="result-value">${rawPrimitive}</div>
            </div>
        `;
    }

    const rawJsonObj = escapeHtml(JSON.stringify(result, null, 2));
    return `
        <div class="result-section">
            <div class="result-title-container">
                <div class="result-title">Sonuc</div>
                <button class="copy-btn dom-copy-btn" data-clipboard="${rawJsonObj}" title="JSON olarak Kopyala">📋</button>
            </div>
            ${renderStructuredValue(result)}
        </div>
    `;
}

// Global copy button handler
document.addEventListener('click', (e) => {
    if (e.target && e.target.classList.contains('dom-copy-btn')) {
        const textToCopy = e.target.getAttribute('data-clipboard');
        if (textToCopy) {
            // Unescape HTML for exact copy length
            const decoded = String(textToCopy)
                .replace(/&amp;/g, '&')
                .replace(/&lt;/g, '<')
                .replace(/&gt;/g, '>')
                .replace(/&quot;/g, '"')
                .replace(/&#39;/g, "'");
                
            navigator.clipboard.writeText(decoded).then(() => {
                const originalText = e.target.innerText;
                e.target.innerText = '✅';
                setTimeout(() => { e.target.innerText = originalText; }, 1500);
            }).catch(err => {
                console.error('Kopyalama basarisiz:', err);
            });
        }
    }
});

async function sendCommand(text, isApproved = false) {
    lastCommandText = text;

    if (!isApproved) {
        createMessageElement(`
            <div style="display: flex; gap: 8px; width: 100%;">
                <span style="color: var(--accent-blue); flex: 0 0 auto;">&gt;</span>
                <span class="user-command">${escapeHtml(text)}</span>
            </div>
        `);
    }

    const stepBlock = document.createElement('div');
    stepBlock.className = 'step-block';
    terminalBody.appendChild(stepBlock);

    const loader = document.createElement('div');
    loader.className = 'step thinking';
    loader.innerHTML = `<span class="spinner">...</span><span>Sistem analiz ediyor...</span>`;
    stepBlock.appendChild(loader);
    scrollToBottom();

    try {
        let sessionId = localStorage.getItem('session_id');
        if (!sessionId) {
            if (window.crypto && typeof window.crypto.randomUUID === 'function') {
                sessionId = window.crypto.randomUUID();
            } else {
                sessionId = `session-${Date.now()}-${Math.random().toString(16).slice(2)}`;
            }
            localStorage.setItem('session_id', sessionId);
        }
        const operatorId = localStorage.getItem('operator_id') || '';
        const tenantId = localStorage.getItem('tenant_id') || '';

        const bearerToken = localStorage.getItem('bearer_token');
        const response = await fetch('/command-ui', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(bearerToken ? { 'Authorization': `Bearer ${bearerToken}` } : {}),
                'X-Session-Id': sessionId,
                ...(operatorId ? { 'X-Operator-Id': operatorId } : {}),
                ...(tenantId ? { 'X-Tenant-Id': tenantId } : {}),
            },
            body: JSON.stringify({ text, approved: isApproved }),
        });

        if (response.status === 401) {
            stepBlock.removeChild(loader);
            const step = document.createElement('div');
            step.className = 'step error';
            step.innerHTML = `<span>x</span><span>Yetki hatasi: Bearer token gerekli. URL'ye ?token=... ekleyin veya localStorage 'bearer_token' ayarlayin.</span>`;
            stepBlock.appendChild(step);
            forceScrollToBottom();
            return;
        }

        const data = await response.json();
        stepBlock.removeChild(loader);

        let approvalButtonHtml = '';
        const needsApproval = data.approval && data.approval.required && data.approval.status === 'pending';

        if (needsApproval) {
            approvalButtonHtml = `
                <div class="result-actions">
                    <button class="approve-btn" onclick="approveCommand(this)">Onayla ve Calistir</button>
                </div>
            `;
        }

        const confidencePercent = Math.round((data.confidence || 0) * 100);
        const errorHtml = data.error ? `<div class="error-text">${escapeHtml(data.error)}</div>` : '';
        const resultHtml = data.result ? renderResult(data.result) : '';
        const workflowProfileHtml = data.workflow_profile
            ? `<div class="workflow-profile">Profil: ${escapeHtml(data.workflow_profile)}</div>`
            : '';
        const sessionContextHtml = renderSessionContext(data.session_context);
        const browserContextHtml = renderBrowserContext(data.browser_context);
        const timingHtml = renderTiming(data.timing);

        const outputBlock = `
            <div class="result-block">
                <div style="font-weight: bold; margin-bottom: 16px;">${escapeHtml(data.summary || 'Islem analizi tamamlandi.')}</div>
                <div class="subtle-text" style="font-size: 0.9em; margin-bottom: 16px;">Aksiyon: ${escapeHtml(data.action || 'unknown')} | Guven: %${confidencePercent}</div>
                ${workflowProfileHtml}
                ${sessionContextHtml}
                ${browserContextHtml}
                ${timingHtml}
                <div class="subtle-text" style="font-size: 0.9em;">Devam: ${escapeHtml(data.next_step || '-')}</div>
                ${resultHtml}
                ${errorHtml}
                <div style="margin-top: 16px;">
                    ${approvalButtonHtml}
                </div>
            </div>
        `;

        const step = document.createElement('div');
        step.className = 'step';
        step.style.width = '100%';
        step.innerHTML = outputBlock;
        stepBlock.appendChild(step);
    } catch (error) {
        stepBlock.removeChild(loader);
        const step = document.createElement('div');
        step.className = 'step error';
        step.innerHTML = `<span>x</span><span>Sunucuya baglanilamadi: ${escapeHtml(error.message)}</span>`;
        stepBlock.appendChild(step);
    }

    forceScrollToBottom();
}

window.approveCommand = function (button) {
    if (button) {
        button.style.opacity = '0.5';
        button.disabled = true;
        button.innerText = 'Onaylandi...';
    }
    sendCommand(lastCommandText, true);
};

cliInput.addEventListener('keydown', async (event) => {
    if (slashActive) {
        const filtered = slashCommands.filter(c => c.cmd.toLowerCase().startsWith(cliInput.value.toLowerCase()));
        if (event.key === 'ArrowDown') {
            event.preventDefault();
            slashSelectedIndex++;
            renderSlashMenu(cliInput.value);
            return;
        }
        if (event.key === 'ArrowUp' && !slashActive) {
            event.preventDefault();
            if (historyIndex === -1 && commandHistory.length > 0) {
                currentInputCache = cliInput.value;
                historyIndex = commandHistory.length - 1;
                cliInput.value = commandHistory[historyIndex];
            } else if (historyIndex > 0) {
                historyIndex--;
                cliInput.value = commandHistory[historyIndex];
            }
            return;
        }

        if (event.key === 'ArrowDown' && !slashActive) {
            event.preventDefault();
            if (historyIndex !== -1) {
                historyIndex++;
                if (historyIndex >= commandHistory.length) {
                    historyIndex = -1;
                    cliInput.value = currentInputCache;
                } else {
                    cliInput.value = commandHistory[historyIndex];
                }
            }
            return;
        }

        if (event.key === 'Enter' && filtered.length > 0) {
            event.preventDefault();
            const selectedStr = filtered[slashSelectedIndex].cmd.replace('/', '');
            cliInput.value = selectedStr;
            slashActive = false;
            slashMenu.classList.remove('active');
            return;
        }
    } else {
        if (event.key === 'ArrowUp') {
            event.preventDefault();
            if (historyIndex === -1 && commandHistory.length > 0) {
                currentInputCache = cliInput.value;
                historyIndex = commandHistory.length - 1;
                cliInput.value = commandHistory[historyIndex];
            } else if (historyIndex > 0) {
                historyIndex--;
                cliInput.value = commandHistory[historyIndex];
            }
            return;
        }

        if (event.key === 'ArrowDown') {
            event.preventDefault();
            if (historyIndex !== -1) {
                historyIndex++;
                if (historyIndex >= commandHistory.length) {
                    historyIndex = -1;
                    cliInput.value = currentInputCache;
                } else {
                    cliInput.value = commandHistory[historyIndex];
                }
            }
            return;
        }
    }

    if (event.key === 'Enter' && !event.shiftKey && cliInput.value.trim() !== '') {
        event.preventDefault();
        const text = cliInput.value;
        const lowerCmd = text.trim().toLowerCase();
        
        if (commandHistory.length === 0 || commandHistory[commandHistory.length - 1] !== text.trim()) {
            commandHistory.push(text.trim());
        }
        historyIndex = -1;
        currentInputCache = '';

        cliInput.value = '';
        cliInput.disabled = true;
        autoResizeInput();

        if (lowerCmd === 'cls' || lowerCmd === 'clear' || lowerCmd === 'temizle') {
            terminalBody.innerHTML = '';
            cliInput.disabled = false;
            cliInput.focus();
            return;
        }

        if (lowerCmd === 'iptal') {
            createMessageElement(`
                <div style="display: flex; gap: 8px; width: 100%;">
                    <span style="color: var(--accent-blue); flex: 0 0 auto;">&gt;</span>
                    <span class="user-command">${escapeHtml(text.trim())}</span>
                </div>
            `);
            const msg = document.createElement('div');
            msg.className = 'message system';
            msg.innerHTML = `<span style="color: #f85149;">✖ İşlem iptal edildi.</span>`;
            terminalBody.appendChild(msg);
            
            const btns = document.querySelectorAll('.approve-btn');
            btns.forEach(b => {
                b.style.opacity = '0.5';
                b.disabled = true;
                b.innerText = 'İptal Edildi';
            });
            
            lastCommandText = '';
            scrollToBottom();
            cliInput.disabled = false;
            cliInput.focus();
            return;
        }

        if (lowerCmd === 'yardim' || lowerCmd === 'help') {
            createMessageElement(`
                <div style="display: flex; gap: 8px; width: 100%;">
                    <span style="color: var(--accent-blue); flex: 0 0 auto;">&gt;</span>
                    <span class="user-command">${escapeHtml(text.trim())}</span>
                </div>
            `);
            const msg = document.createElement('div');
            msg.className = 'message system';
            msg.innerHTML = renderHelpCommands();
            terminalBody.appendChild(msg);
            forceScrollToBottom();
            cliInput.disabled = false;
            cliInput.focus();
            return;
        }

        // Yerel komut yakalamaları
        if (['time', 'saat'].includes(lowerCmd)) {
            const now = new Date().toLocaleTimeString('tr-TR');
            terminalBody.innerHTML += `<div class="message system" style="margin-top: 8px;"><span style="color: var(--accent-green);">✓</span> 🕒 Yerel Saat: ${now}</div>`;
            scrollToBottom();
            cliInput.disabled = false;
            cliInput.focus();
            return;
        }

        if (['date', 'tarih'].includes(lowerCmd)) {
            const today = new Date().toLocaleDateString('tr-TR');
            terminalBody.innerHTML += `<div class="message system" style="margin-top: 8px;"><span style="color: var(--accent-green);">✓</span> 📅 Bugünün Tarihi: ${today}</div>`;
            scrollToBottom();
            cliInput.disabled = false;
            cliInput.focus();
            return;
        }

        if (lowerCmd.startsWith('echo ')) {
            const p = escapeHtml(text.substring(5).trim());
            terminalBody.innerHTML += `<div class="message system" style="margin-top: 8px;"><span style="color: var(--accent-green);">✓</span> ${p}</div>`;
            scrollToBottom();
            cliInput.disabled = false;
            cliInput.focus();
            return;
        }

        await sendCommand(text, false);

        cliInput.disabled = false;
        cliInput.focus();
        autoResizeInput();
    }
});

cliInput.addEventListener('input', (e) => {
    autoResizeInput();
    const val = cliInput.value;
    if (val.startsWith('/')) {
        slashActive = true;
        renderSlashMenu(val);
    } else {
        slashActive = false;
        slashMenu.classList.remove('active');
    }
});
window.addEventListener('load', () => {
    autoResizeInput();
    cliInput.focus();
});

// Auto-focus logic
document.addEventListener('click', (e) => {
    // If user is not selecting text and the target is not a button/input, focus cli
    if (window.getSelection().toString() === '') {
        const tagName = e.target.tagName.toLowerCase();
        if (tagName !== 'button' && tagName !== 'input' && tagName !== 'textarea' && tagName !== 'a' && !e.target.closest('.slash-menu')) {
            cliInput.focus();
        }
    }

    if (!e.target.closest('.slash-menu') && e.target !== cliInput) {
        slashActive = false;
        slashMenu.classList.remove('active');
    }
});

/* ─── Canlı Ekran Paylaşımı (WebSocket) ─── */
let screenWs = null;
let screenStreaming = false;
let screenControlEnabled = false;
let screenMetrics = {
    width: 0,
    height: 0,
    scale: 1,
    cursorWidth: 0,
    cursorHeight: 0,
    virtualX: 0,
    virtualY: 0,
    virtualWidth: 0,
    virtualHeight: 0,
    lastImageWidth: 0,
    lastImageHeight: 0,
};
let screenClickMode = 'double';
let screenLongPressTimer = null;
let screenLongPressFired = false;
let screenFullscreenEnabled = false;
let screenDebugEnabled = false;
let screenControlGloballyDisabled = true;

function setScreenControlState(enabled) {
    if (screenControlGloballyDisabled) {
        screenControlEnabled = false;
    } else {
        screenControlEnabled = enabled;
    }
    const btn = document.getElementById('screen-control-toggle');
    if (btn) {
        btn.classList.toggle('active', screenControlEnabled);
        btn.textContent = screenControlEnabled ? 'Kontrol: Açık' : 'Kontrol: Kapalı';
    }
    document.body.classList.toggle('screen-control-active', screenControlEnabled);
}

function setClickMode(mode) {
    screenClickMode = mode === 'single' ? 'single' : 'double';
    const btn = document.getElementById('screen-click-mode');
    if (btn) {
        btn.textContent = screenClickMode === 'single' ? 'Tık: Tek' : 'Tık: Çift';
    }
}

function setScreenFullscreenState(enabled) {
    screenFullscreenEnabled = enabled;
    const preview = document.getElementById('screen-preview');
    const btn = document.getElementById('screen-fullscreen-toggle');
    if (preview) {
        preview.classList.toggle('fullscreen', enabled);
    }
    document.body.classList.toggle('screen-fullscreen-active', enabled);
    if (btn) {
        btn.textContent = enabled ? 'Pencere' : 'Tam Ekran';
    }
}

function setScreenDebugState(enabled) {
    if (screenControlGloballyDisabled) {
        screenDebugEnabled = false;
    } else {
        screenDebugEnabled = enabled;
    }
    const btn = document.getElementById('screen-debug-toggle');
    if (btn) {
        btn.classList.toggle('active', screenDebugEnabled);
        btn.textContent = screenDebugEnabled ? 'Debug: Açık' : 'Debug: Kapalı';
    }
}

async function sendScreenClick(x, y, { button = 'left', doubleClick = false } = {}) {
    let bearerToken = localStorage.getItem('bearer_token');
    if (!bearerToken) {
        const urlToken = new URLSearchParams(window.location.search).get('token');
        if (urlToken) {
            bearerToken = urlToken;
            localStorage.setItem('bearer_token', urlToken);
        }
    }
    const tokenQuery = bearerToken ? `?token=${encodeURIComponent(bearerToken)}` : '';
    await fetch(`/screen/click${tokenQuery}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            ...(bearerToken ? { 'Authorization': `Bearer ${bearerToken}` } : {}),
        },
        body: JSON.stringify({
            x,
            y,
            button,
            double_click: Boolean(doubleClick),
        }),
    });
}

function getScreenClickPoint(event, element, canvasElement) {
    if (!screenMetrics.width || !screenMetrics.height) {
        return null;
    }
    const targetRect = canvasElement || element;
    const rect = targetRect.getBoundingClientRect();
    if (!rect.width || !rect.height) {
        return null;
    }

    const naturalWidth = screenMetrics.lastImageWidth || element.naturalWidth || rect.width;
    const naturalHeight = screenMetrics.lastImageHeight || element.naturalHeight || rect.height;
    if (!naturalWidth || !naturalHeight) {
        return null;
    }

    const scale = Math.min(rect.width / naturalWidth, rect.height / naturalHeight);
    const displayWidth = naturalWidth * scale;
    const displayHeight = naturalHeight * scale;
    const offsetX = (rect.width - displayWidth) / 2;
    const offsetY = (rect.height - displayHeight) / 2;

    const clickX = event.clientX - rect.left - offsetX;
    const clickY = event.clientY - rect.top - offsetY;

    const clampedX = Math.max(0, Math.min(displayWidth, clickX));
    const clampedY = Math.max(0, Math.min(displayHeight, clickY));

    const imageX = clampedX / scale;
    const imageY = clampedY / scale;

    const targetWidth = screenMetrics.virtualWidth || screenMetrics.cursorWidth || screenMetrics.width;
    const targetHeight = screenMetrics.virtualHeight || screenMetrics.cursorHeight || screenMetrics.height;
    if (!targetWidth || !targetHeight) {
        return null;
    }
    const baseX = Number.isFinite(screenMetrics.virtualX) ? screenMetrics.virtualX : 0;
    const baseY = Number.isFinite(screenMetrics.virtualY) ? screenMetrics.virtualY : 0;
    const mappedX = Math.max(0, Math.min(targetWidth - 1, Math.round((imageX / naturalWidth) * targetWidth)));
    const mappedY = Math.max(0, Math.min(targetHeight - 1, Math.round((imageY / naturalHeight) * targetHeight)));
    return { x: baseX + mappedX, y: baseY + mappedY };
}

function closeScreenShare() {
    const preview = document.getElementById('screen-preview');
    const frame = document.getElementById('screen-frame');

    if (screenWs && (screenWs.readyState === WebSocket.OPEN || screenWs.readyState === WebSocket.CONNECTING)) {
        screenWs.close();
    }

    screenWs = null;
    screenStreaming = false;
    setScreenControlState(false);
    setScreenFullscreenState(false);
    preview.classList.add('hidden');
    frame.src = '';
}

function toggleScreenShare() {
    const preview = document.getElementById('screen-preview');

    // Zaten açıksa kapat
    if (screenWs && screenWs.readyState === WebSocket.OPEN) {
        closeScreenShare();
        return;
    }

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${location.host}/ws/screen`;

    screenWs = new WebSocket(wsUrl);
    screenStreaming = true;

    screenWs.onopen = () => {
        preview.classList.remove('hidden');
    };

    screenWs.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'frame' && msg.data) {
                const dataUrl = 'data:image/jpeg;base64,' + msg.data;
                document.getElementById('screen-frame').src = dataUrl;
                if (screenCanvas && screenCanvasCtx) {
                    const img = new Image();
                    img.onload = () => {
                        screenCanvas.width = img.width;
                        screenCanvas.height = img.height;
                        screenCanvasCtx.drawImage(img, 0, 0);
                        screenMetrics.lastImageWidth = img.width;
                        screenMetrics.lastImageHeight = img.height;
                        if (screenDebugCanvas && screenDebugCtx) {
                            screenDebugCanvas.width = img.width;
                            screenDebugCanvas.height = img.height;
                            screenDebugCtx.clearRect(0, 0, img.width, img.height);
                        }
                    };
                    img.src = dataUrl;
                }
                if (msg.screen_width && msg.screen_height) {
                    screenMetrics.width = Number(msg.screen_width) || 0;
                    screenMetrics.height = Number(msg.screen_height) || 0;
                }
                if (msg.cursor_width && msg.cursor_height) {
                    screenMetrics.cursorWidth = Number(msg.cursor_width) || 0;
                    screenMetrics.cursorHeight = Number(msg.cursor_height) || 0;
                }
                if (msg.virtual_width && msg.virtual_height) {
                    screenMetrics.virtualWidth = Number(msg.virtual_width) || 0;
                    screenMetrics.virtualHeight = Number(msg.virtual_height) || 0;
                }
                if (msg.virtual_x !== undefined && msg.virtual_y !== undefined) {
                    screenMetrics.virtualX = Number(msg.virtual_x) || 0;
                    screenMetrics.virtualY = Number(msg.virtual_y) || 0;
                }
                if (msg.scale) {
                    screenMetrics.scale = Number(msg.scale) || 1;
                }
            }
        } catch (e) {
            // JSON parse hatası — yoksay
        }
    };

    screenWs.onerror = () => {
        closeScreenShare();
    };

    screenWs.onclose = () => {
        closeScreenShare();
    };
}

// Toggle butonu
const screenToggleBtn = document.getElementById('screen-toggle');
if (screenToggleBtn) {
    screenToggleBtn.addEventListener('click', toggleScreenShare);
}

// Kapatma butonu
const screenCloseBtn = document.getElementById('screen-close');
if (screenCloseBtn) {
    screenCloseBtn.addEventListener('click', closeScreenShare);
}

const screenControlBtn = document.getElementById('screen-control-toggle');
if (screenControlBtn) {
    screenControlBtn.addEventListener('click', () => {
        if (screenControlGloballyDisabled) {
            return;
        }
        setScreenControlState(!screenControlEnabled);
    });
}

const screenClickModeBtn = document.getElementById('screen-click-mode');
if (screenClickModeBtn) {
    screenClickModeBtn.addEventListener('click', () => {
        if (screenControlGloballyDisabled) {
            return;
        }
        setClickMode(screenClickMode === 'double' ? 'single' : 'double');
    });
    setClickMode(screenClickMode);
}

const screenFullscreenBtn = document.getElementById('screen-fullscreen-toggle');
if (screenFullscreenBtn) {
    screenFullscreenBtn.addEventListener('click', () => {
        setScreenFullscreenState(!screenFullscreenEnabled);
    });
}

const screenDebugBtn = document.getElementById('screen-debug-toggle');
if (screenDebugBtn) {
    screenDebugBtn.addEventListener('click', () => {
        if (screenControlGloballyDisabled) {
            return;
        }
        setScreenDebugState(!screenDebugEnabled);
    });
    setScreenDebugState(false);
}

const screenFrame = document.getElementById('screen-frame');
const screenClickLayer = document.getElementById('screen-click-layer');
const screenGlobalBlocker = document.getElementById('screen-global-blocker');
const screenCanvas = document.getElementById('screen-canvas');
const screenCanvasCtx = screenCanvas ? screenCanvas.getContext('2d') : null;
const screenDebugCanvas = document.getElementById('screen-debug-canvas');
const screenDebugCtx = screenDebugCanvas ? screenDebugCanvas.getContext('2d') : null;
if (screenClickLayer && screenFrame) {
    screenClickLayer.addEventListener('contextmenu', (event) => {
        event.preventDefault();
        event.stopPropagation();
    });

    screenClickLayer.addEventListener('click', async (event) => {
        event.preventDefault();
        event.stopPropagation();
        if (!screenControlEnabled) {
            return;
        }
        if (!screenMetrics.width || !screenMetrics.height) {
            return;
        }
        if (screenLongPressFired) {
            screenLongPressFired = false;
            return;
        }
        const point = getScreenClickPoint(event, screenFrame, screenCanvas);
        if (!point) {
            return;
        }
        if (screenDebugEnabled && screenDebugCanvas && screenDebugCtx) {
            const baseX = screenMetrics.virtualX || 0;
            const baseY = screenMetrics.virtualY || 0;
            const targetWidth = screenMetrics.virtualWidth || screenMetrics.cursorWidth || screenMetrics.width || 1;
            const targetHeight = screenMetrics.virtualHeight || screenMetrics.cursorHeight || screenMetrics.height || 1;
            const canvasX = (point.x - baseX) / targetWidth * screenDebugCanvas.width;
            const canvasY = (point.y - baseY) / targetHeight * screenDebugCanvas.height;
            screenDebugCtx.clearRect(0, 0, screenDebugCanvas.width, screenDebugCanvas.height);
            screenDebugCtx.beginPath();
            screenDebugCtx.arc(canvasX, canvasY, 8, 0, Math.PI * 2);
            screenDebugCtx.strokeStyle = '#ff3b30';
            screenDebugCtx.lineWidth = 3;
            screenDebugCtx.stroke();
        }

        try {
            await sendScreenClick(point.x, point.y, {
                button: 'left',
                doubleClick: screenClickMode === 'double',
            });
        } catch (e) {
            // Sessizce yut
        }
    });

    screenClickLayer.addEventListener('pointerdown', (event) => {
        event.preventDefault();
        event.stopPropagation();
        if (event.currentTarget && event.pointerId !== undefined) {
            try {
                event.currentTarget.setPointerCapture(event.pointerId);
            } catch (e) {
                // ignore
            }
        }
        if (!screenControlEnabled) {
            return;
        }
        if (!screenMetrics.width || !screenMetrics.height) {
            return;
        }
        screenLongPressFired = false;
        if (screenLongPressTimer) {
            clearTimeout(screenLongPressTimer);
        }
        const point = getScreenClickPoint(event, screenFrame, screenCanvas);
        if (!point) {
            return;
        }
        screenLongPressTimer = setTimeout(async () => {
            try {
                await sendScreenClick(point.x, point.y, { button: 'right', doubleClick: false });
                screenLongPressFired = true;
            } catch (e) {
                // Sessizce yut
            }
        }, 550);
    });

    screenClickLayer.addEventListener('pointerup', () => {
        if (screenLongPressTimer) {
            clearTimeout(screenLongPressTimer);
            screenLongPressTimer = null;
        }
    });

    screenClickLayer.addEventListener('pointerleave', (event) => {
        if (screenLongPressTimer) {
            clearTimeout(screenLongPressTimer);
            screenLongPressTimer = null;
        }
        if (event.currentTarget && event.pointerId !== undefined) {
            try {
                event.currentTarget.releasePointerCapture(event.pointerId);
            } catch (e) {
                // ignore
            }
        }
    });
}

if (screenGlobalBlocker) {
    const blockEvents = (event) => {
        if (!screenControlEnabled) {
            return;
        }
        event.preventDefault();
        event.stopPropagation();
    };
    screenGlobalBlocker.addEventListener('touchstart', blockEvents, { passive: false });
    screenGlobalBlocker.addEventListener('touchmove', blockEvents, { passive: false });
    screenGlobalBlocker.addEventListener('touchend', blockEvents, { passive: false });
    screenGlobalBlocker.addEventListener('click', blockEvents);
    screenGlobalBlocker.addEventListener('pointerdown', blockEvents);
    screenGlobalBlocker.addEventListener('pointerup', blockEvents);
}

window.addEventListener('beforeunload', closeScreenShare);
document.addEventListener('visibilitychange', () => {
    if (document.hidden && screenStreaming) {
        closeScreenShare();
    }
});

document.addEventListener('touchmove', (event) => {
    if (screenControlEnabled && !screenControlGloballyDisabled) {
        event.preventDefault();
    }
}, { passive: false });

document.body.classList.add('screen-control-disabled');
setScreenControlState(false);

/* ─── Tema Seçimi (Theme Selection) ─── */
const themeDots = document.querySelectorAll('.theme-dot');
if (themeDots.length > 0) {
    themeDots.forEach(dot => {
        dot.addEventListener('click', (e) => {
            // Aktif sınıfı temizle
            themeDots.forEach(d => d.classList.remove('active'));
            
            // Tıklanana aktif sınıfı ekle
            const target = e.target;
            target.classList.add('active');
            
            // Tema niteliğini body'ye uygula
            const themeName = target.getAttribute('data-theme');
            if (themeName === 'default') {
                document.body.removeAttribute('data-theme');
            } else {
                document.body.setAttribute('data-theme', themeName);
            }
            
            // Tercihi kaydet
            localStorage.setItem('agentic-cli-theme', themeName);
        });
    });

    // Kayıtlı temayı yükle
    const savedTheme = localStorage.getItem('agentic-cli-theme');
    if (savedTheme) {
        const activeDot = document.querySelector(`.theme-dot[data-theme="${savedTheme}"]`);
        if (activeDot) {
            activeDot.click();
        }
    }
}
