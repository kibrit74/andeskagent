const terminalBody = document.getElementById('terminal-body');
const cliInput = document.getElementById('cli-input');

let lastCommandText = '';

const inputWrapper = document.querySelector('.terminal-input-wrapper');
let slashMenu = document.createElement('div');
slashMenu.className = 'slash-menu';
inputWrapper.appendChild(slashMenu);

const slashCommands = [
    { cmd: '/temizle', icon: '🧹', desc: 'Ekranı temizler' },
    { cmd: '/iptal', icon: '✖', desc: 'Son işlemi iptal eder' },
    { cmd: '/durum', icon: '📊', desc: 'Sistem durumunu raporlar' },
    { cmd: '/yardim', icon: '❓', desc: 'Yardım ve komut listesi' }
];

let slashSelectedIndex = 0;
let slashActive = false;

function renderSlashMenu(filter = '') {
    const filtered = slashCommands.filter(c => c.cmd.toLowerCase().startsWith(filter.toLowerCase()));
    
    if (filtered.length === 0 || !slashActive || filter === '') {
        slashMenu.classList.remove('active');
        return;
    }
    
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

function scrollToBottom() {
    terminalBody.scrollTop = terminalBody.scrollHeight;
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
    scrollToBottom();
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
                const title = step && step.title ? String(step.title) : `Adim ${index + 1}`;
                const body = step && step.result
                    ? renderStructuredValue(step.result)
                    : step && step.error
                        ? `<div class="error-text">${escapeHtml(step.error)}</div>`
                        : '';

                return `
                    <div class="workflow-step ${escapeHtml(status)}">
                        <div class="workflow-step-head">
                            <div class="workflow-step-title">${escapeHtml(title)}</div>
                            <div class="workflow-step-status">${escapeHtml(status)}</div>
                        </div>
                        ${body}
                    </div>
                `;
            }).join('')}
        </div>
    `;
}

function renderResult(result) {
    if (result && typeof result === 'object' && Array.isArray(result.steps)) {
        return `
            <div class="result-section">
                <div class="result-title">Is Akisi</div>
                ${renderWorkflowSteps(result.steps)}
            </div>
        `;
    }

    if (!result || typeof result !== 'object') {
        return `
            <div class="result-section">
                <div class="result-title">Sonuc</div>
                <div class="result-value">${escapeHtml(formatPrimitive(result))}</div>
            </div>
        `;
    }

    return `
        <div class="result-section">
            <div class="result-title">Sonuc</div>
            ${renderStructuredValue(result)}
        </div>
    `;
}

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
        const response = await fetch('/command-ui', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, approved: isApproved }),
        });

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

        const outputBlock = `
            <div class="result-block">
                <div style="font-weight: bold; margin-bottom: 16px;">${escapeHtml(data.summary || 'Islem analizi tamamlandi.')}</div>
                <div class="subtle-text" style="font-size: 0.9em; margin-bottom: 16px;">Aksiyon: ${escapeHtml(data.action || 'unknown')} | Guven: %${confidencePercent}</div>
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

    scrollToBottom();
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
        if (event.key === 'ArrowUp') {
            event.preventDefault();
            slashSelectedIndex--;
            renderSlashMenu(cliInput.value);
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
    }

    if (event.key === 'Enter' && !event.shiftKey && cliInput.value.trim() !== '') {
        event.preventDefault();
        const text = cliInput.value;
        const lowerCmd = text.trim().toLowerCase();
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
