const terminalBody = document.getElementById('terminal-body');
const cliInput = document.getElementById('cli-input');

function getApiBaseUrl() {
    return window.location.origin;
}

function scrollToBottom() {
    terminalBody.scrollTop = terminalBody.scrollHeight;
}

function escapeHtml(value) {
    return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
}

function createMessageElement(contentHtml) {
    const div = document.createElement('div');
    div.className = 'message';
    div.innerHTML = contentHtml;
    terminalBody.appendChild(div);
    scrollToBottom();
    return div;
}

function renderItems(items) {
    if (!Array.isArray(items) || !items.length) {
        return '<div class="result-block">Sonuc bulunamadi.</div>';
    }

    const rows = items.slice(0, 8).map((item) => {
        const name = escapeHtml(item.name || item.path || 'Kayit');
        const path = escapeHtml(item.path || '');
        return `<li><strong>${name}</strong>${path ? `<div class="subtle">${path}</div>` : ''}</li>`;
    }).join('');

    return `<div class="result-block"><ul class="result-list">${rows}</ul></div>`;
}

function renderResult(result) {
    if (!result) {
        return '';
    }

    if (result.items) {
        return renderItems(result.items);
    }

    if (Array.isArray(result.steps) && result.steps.length) {
        return result.steps.map((step) => `
            <div class="result-block">
                <div><strong>${escapeHtml(step.tool || 'islem')}</strong></div>
                <pre>${escapeHtml(JSON.stringify(step, null, 2))}</pre>
            </div>
        `).join('');
    }

    if (result.status === 'pending_approval') {
        return '';
    }

    return `
        <div class="result-block">
            <pre>${escapeHtml(JSON.stringify(result, null, 2))}</pre>
        </div>
    `;
}

function attachApprovalHandler(button, originalText) {
    if (!button) {
        return;
    }

    button.addEventListener('click', async () => {
        button.disabled = true;
        await sendPrompt(originalText, true);
    });
}

function renderResponse(data, originalText) {
    createMessageElement(`
        <span style="color: var(--accent-blue);">></span>
        <span class="user-command">${escapeHtml(originalText)}</span>
    `);

    const responseElement = createMessageElement(`
        <span style="color: ${data.error ? 'var(--accent-red)' : 'var(--accent-green)'};">●</span>
        <div class="response-stack">
            <div class="result-block">
                <div><strong>${escapeHtml(data.summary || (data.error ? 'Islem basarisiz.' : 'Islem tamamlandi.'))}</strong></div>
                <div class="subtle">Aksiyon: ${escapeHtml(data.action || 'unknown')} | Guven: ${Math.round((data.confidence || 0) * 100)}%</div>
                ${data.next_step ? `<div class="subtle">Devam: ${escapeHtml(data.next_step)}</div>` : ''}
                ${data.error ? `<div class="error-text">${escapeHtml(data.error)}</div>` : ''}
            </div>
            ${renderResult(data.result)}
            ${data.approval?.status === 'pending' ? '<button class="approve-btn">Onayla ve Calistir</button>' : ''}
        </div>
    `);

    attachApprovalHandler(responseElement.querySelector('.approve-btn'), originalText);
}

async function sendPrompt(promptText, approved = false) {
    const pending = createMessageElement(`
        <span class="spinner">o</span>
        <span class="step thinking">Sunucuya baglaniliyor...</span>
    `);

    try {
        const response = await fetch(`${getApiBaseUrl()}/command-ui`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: promptText, approved }),
        });

        pending.remove();

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        renderResponse(data, promptText);
    } catch (error) {
        pending.remove();
        createMessageElement(`
            <span style="color: var(--accent-red);">●</span>
            <div class="result-block">
                <div><strong>Sunucuya ulasilamadi.</strong></div>
                <div class="error-text">${escapeHtml(error.message || String(error))}</div>
                <div class="subtle">API adresi: ${escapeHtml(getApiBaseUrl())}/command-ui</div>
            </div>
        `);
    }
}

cliInput.addEventListener('keydown', async (event) => {
    if (event.key === 'Enter' && cliInput.value.trim() !== '') {
        const value = cliInput.value.trim();
        cliInput.value = '';
        cliInput.disabled = true;
        await sendPrompt(value, false);
        cliInput.disabled = false;
        cliInput.focus();
    }
});

window.addEventListener('load', () => {
    createMessageElement(`
        <span style="color: #6e7681;">API</span>
        <span class="text">Baglanti hedefi: ${escapeHtml(getApiBaseUrl())}/command-ui</span>
    `);
    cliInput.focus();
});
