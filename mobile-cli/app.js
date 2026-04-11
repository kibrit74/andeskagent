const terminalBody = document.getElementById('terminal-body');
const cliInput = document.getElementById('cli-input');
const accessLink = document.getElementById('access-link');
const accessHint = document.getElementById('access-hint');
const qrImage = document.getElementById('qr-image');

function buildShareUrl() {
    const url = new URL(window.location.href);
    url.hash = '';
    return url.toString();
}

function hydrateAccessPanel() {
    const shareUrl = buildShareUrl();
    accessLink.href = shareUrl;
    accessLink.textContent = shareUrl;

    const encodedUrl = encodeURIComponent(shareUrl);
    qrImage.src = `https://api.qrserver.com/v1/create-qr-code/?size=220x220&margin=12&data=${encodedUrl}`;

    const isLocalhost = ['localhost', '127.0.0.1'].includes(window.location.hostname);
    accessHint.textContent = isLocalhost
        ? 'Not: QR kod localhost adresini gösterir. Telefonda kullanmak için sayfayi yerel ag IP adresiyle acin.'
        : 'QR kod bu sayfanin aktif adresine baglidir.';
}

// Otomatik scroll
function scrollToBottom() {
    terminalBody.scrollTop = terminalBody.scrollHeight;
}

// Yeni terminal elementi ekleme
function createMessageElement(contentHtml) {
    const div = document.createElement('div');
    div.className = 'message';
    div.innerHTML = contentHtml;
    terminalBody.appendChild(div);
    scrollToBottom();
    return div;
}

// Rastgele işlem senaryosu oluşturur (Agentic Step-by-Step UI Mock)
async function simulateAgenticExecution(promptText) {
    // 1. Kullanıcı komutunu göster
    createMessageElement(`
        <span style="color: var(--accent-blue);">❯</span>
        <span class="user-command">${promptText}</span>
    `);
    
    // Adım bloğu konteynerı
    const stepBlock = document.createElement('div');
    stepBlock.className = 'step-block';
    terminalBody.appendChild(stepBlock);
    
    function addStep(htmlHtml) {
        const step = document.createElement('div');
        step.className = 'step';
        step.innerHTML = htmlHtml;
        stepBlock.appendChild(step);
        scrollToBottom();
        return step;
    }

    // 2. Thinking phase
    const thinkingStep = addStep(`
        <span class="spinner">⠋</span>
        <span class="step thinking">Görev bağlamı analiz ediliyor...</span>
    `);
    await sleep(1500);
    thinkingStep.innerHTML = `<span>✓</span><span class="step success">Bağlam analiz edildi.</span>`;

    // 3. Tool execution (Dosya arama)
    const toolUse1 = addStep(`
        <span class="spinner">⠋</span>
        <span class="step tool-run">Çalıştırılıyor: grep_search "auth" ./src/</span>
    `);
    await sleep(2000);
    toolUse1.innerHTML = `<span>⚡</span><span class="step tool-run">Araç yürütüldü: grep_search</span>`;

    // 4. İkinci işlem planlama
    const toolUse2 = addStep(`
        <span class="spinner">⠋</span>
        <span class="step tool-run">Çalıştırılıyor: write_to_file ./src/config.js</span>
    `);
    await sleep(1800);
    toolUse2.innerHTML = `<span>⚡</span><span class="step tool-run">Araç yürütüldü: Dosya başarıyla oluşturuldu/düzenlendi.</span>`;

    // 5. Final cevabı
    await sleep(1000);
    createMessageElement(`
        <span style="color: var(--accent-green);">🤖</span>
        <div class="result-block">
            İstediğiniz yönergeler doğrultusunda ilgili işlemleri gerçekleştirdim. \n\nLogları ve projeyi kontrol edebilirsiniz. Herhangi bir hata bulunamadı.
        </div>
    `);
}

// Yardımcı fonksiyon
function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

// Input enter event
cliInput.addEventListener('keydown', async (e) => {
    if (e.key === 'Enter' && cliInput.value.trim() !== '') {
        const value = cliInput.value;
        cliInput.value = '';
        cliInput.disabled = true;
        
        await simulateAgenticExecution(value);
        
        cliInput.disabled = false;
        cliInput.focus();
    }
});

// Sayfa yüklendiğinde inputa odaklan
window.addEventListener('load', () => {
    hydrateAccessPanel();
    cliInput.focus();
});
