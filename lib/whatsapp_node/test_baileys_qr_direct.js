const { default: makeWASocket, useMultiFileAuthState, fetchLatestBaileysVersion, Browsers } = require('@whiskeysockets/baileys');
const pino = require('pino');
const qrcode = require('qrcode');
const path = require('path');
const os = require('os');
const fs = require('fs');

async function test() {
    console.log("Testing Baileys with Origin headers...");
    const user = "GermanMazza";
    const sessionDir = path.join(os.homedir(), `.whatsapp_bot_session_${user}`);
    const qrPath = path.join(__dirname, '..', '..', 'static', 'uploads', `qr_${user}.png`);

    if (fs.existsSync(sessionDir)) fs.rmSync(sessionDir, { recursive: true, force: true });

    const { version } = await fetchLatestBaileysVersion();
    console.log("Fetched Baileys version:", version);

    const { state, saveCreds } = await useMultiFileAuthState(sessionDir);

    const sock = makeWASocket({
        version,
        auth: state,
        logger: pino({ level: 'info' }),
        browser: ['Windows', 'Chrome', '125.0.0.0'],
        options: {
            headers: {
                'Origin': 'https://web.whatsapp.com',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
            }
        },
        connectTimeoutMs: 60000,
        defaultQueryTimeoutMs: 60000,
    });

    sock.ev.on('creds.update', saveCreds);
    sock.ev.on('connection.update', async (update) => {
        console.log("Update connection:", update.connection, "QR received?:", !!update.qr);
        if (update.qr) {
            console.log("SUCCESS! QR string received from WhatsApp Web!");
            await qrcode.toFile(qrPath, update.qr);
            console.log("SUCCESS! PNG file created at:", qrPath);
            process.exit(0);
        }
    });
}

test().catch(err => console.error("Test failed error:", err));
