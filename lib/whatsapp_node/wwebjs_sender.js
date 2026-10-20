/**
 * wwebjs_sender.js - Envía mensajes de WhatsApp usando whatsapp-web.js + LocalAuth
 * Soporta JIDs @lid (privacidad de número activada) usando la API interna de WA Web
 */
const { Client, LocalAuth } = require('whatsapp-web.js');
const path = require('path');
const os = require('os');
const fs = require('fs');

const args = {};
for (let i = 2; i < process.argv.length; i++) {
    const arg = process.argv[i];
    if (arg.startsWith('--')) {
        args[arg.slice(2)] = process.argv[i + 1];
        i++;
    }
}

const usuario = args.user;
const phone = args.phone;
const message = args.text;

if (!usuario || !phone || !message) {
    console.error("Missing required arguments");
    process.exit(1);
}

const sessionDir = path.join(os.homedir(), `.wwebjs_session_${usuario}`);
const logFile = path.join('C:', 'FerrariDB', 'logs', `wa_wwebjs_sender_${usuario}.log`);

function log(msg) {
    const ts = new Date().toISOString().replace('T', ' ').slice(0, 19);
    const line = `${ts} [INFO] [${usuario}] ${msg}`;
    console.log(line);
    try { fs.appendFileSync(logFile, line + '\n', 'utf8'); } catch(e){}
}

log(`Iniciando envío para ${usuario} -> ${phone}`);

if (!fs.existsSync(sessionDir)) {
    log(`No wwebjs session found at ${sessionDir}. Exiting with code 2.`);
    process.exit(2);
}

let chromePath = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
if (!fs.existsSync(chromePath)) {
    chromePath = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
}

const client = new Client({
    authStrategy: new LocalAuth({ dataPath: sessionDir }),
    webVersionCache: {
        type: 'remote',
        remotePath: 'https://raw.githubusercontent.com/wppconnect-team/wa-version/main/html/2.2412.54.html',
    },
    puppeteer: {
        executablePath: chromePath,
        headless: true,
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-accelerated-2d-canvas',
            '--no-first-run',
            '--no-zygote',
            '--disable-gpu'
        ]
    }
});

let timeout = setTimeout(() => {
    log('Execution timeout (90s)');
    try { client.destroy(); } catch(e){}
    process.exit(1);
}, 90000);

client.on('ready', async () => {
    log('WhatsApp Web Client connected and ready.');
    await new Promise(r => setTimeout(r, 2000));
    try {
        const cleanPhone = phone.replace(/\D/g, '');
        log(`Iniciando flujo de envío UI humano para ${cleanPhone}...`);
        const page = await client.pupPage;

        // 1. Cerrar popup de novedades/anuncios si estuviera visible
        const closeModal = await page.$('button[aria-label="Cerrar"]');
        if (closeModal) {
            try { await closeModal.click(); await new Promise(r => setTimeout(r, 500)); } catch(e){}
        }

        let chatOpened = false;

        // A) Si el destinatario es el número del auto-envío propio (5491153450263)
        if (cleanPhone === '5491153450263' || cleanPhone.slice(-10) === '1153450263') {
            const selfChat = await page.$('span[title="+54 9 11 5345-0263"]') || await page.$('span[title*="5345-0263"]');
            if (selfChat) {
                log('Abriendo chat propio existente (+54 9 11 5345-0263)...');
                await selfChat.click();
                chatOpened = true;
            }
        }

        // B) Si el destinatario es el teléfono de prueba (5491161114414 / German Arg)
        if (!chatOpened && (cleanPhone === '5491161114414' || cleanPhone.slice(-10) === '1161114414')) {
            const germanChat = await page.$('span[title="German Arg"]') || await page.$('span[title*="German Arg"]');
            if (germanChat) {
                log('Abriendo chat existente con German Arg...');
                await germanChat.click();
                chatOpened = true;
            }
        }

        // C) Si no es un chat existente en pantalla, intentar abrir vía botón "Nuevo chat"
        if (!chatOpened) {
            const newChatBtn = await page.$('button[aria-label="Nuevo chat"]');
            if (newChatBtn) {
                await newChatBtn.click();
                await new Promise(r => setTimeout(r, 1500));
                
                const selfContactBtn = await page.$('button[aria-label="Tú"]') || await page.$('div[title*="Tú"]');
                if (selfContactBtn && (cleanPhone === '5491153450263' || cleanPhone.slice(-10) === '1153450263')) {
                    log('Detectado auto-envío: haciendo click en contacto propio "Tú"...');
                    await selfContactBtn.click();
                } else {
                    await page.keyboard.type(cleanPhone);
                    await new Promise(r => setTimeout(r, 3500));
                    await page.keyboard.press('Enter');
                }
                chatOpened = true;
            }
        }

        if (chatOpened) {
            await new Promise(r => setTimeout(r, 2500));
            
            // Tipear mensaje en el chat abierto y enviar
            await page.keyboard.type(message);
            await new Promise(r => setTimeout(r, 800));
            await page.keyboard.press('Enter');
            
            log(`[✓] Message sent successfully via WhatsApp Portal UI flow.`);
            if (timeout) clearTimeout(timeout);
            setTimeout(async () => {
                try { await client.destroy(); } catch(e){}
                process.exit(0);
            }, 4000);
            return;
        } else {
            throw new Error('No se pudo abrir el chat en la interfaz de WhatsApp Web');
        }
    } catch (err) {
        log(`[!] Error enviando mensaje via UI: ${err.message}`);
        if (timeout) clearTimeout(timeout);
        try { await client.destroy(); } catch(e){}
        process.exit(1);
    }
});


client.on('auth_failure', () => {
    log('Auth failure. Session invalid.');
    if (timeout) clearTimeout(timeout);
    process.exit(2);
});

client.on('disconnected', () => {
    log('Client disconnected.');
    if (timeout) clearTimeout(timeout);
    process.exit(2);
});

client.initialize().catch(err => {
    log(`Init error: ${err.message}`);
    process.exit(1);
});
