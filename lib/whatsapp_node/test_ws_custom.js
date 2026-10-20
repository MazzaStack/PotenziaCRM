const { default: makeWASocket, useMultiFileAuthState, fetchLatestBaileysVersion, Browsers } = require('@whiskeysockets/baileys');
const WebSocket = require('ws');
const pino = require('pino');
const qrcode = require('qrcode');
const path = require('path');
const os = require('os');
const fs = require('fs');

async function test() {
    console.log("Testing Baileys with custom WebSocket instance...");
    const user = "GermanMazza";
    const sessionDir = path.join(os.homedir(), `.whatsapp_bot_session_${user}`);
    const qrPath = path.join(__dirname, '..', '..', 'static', 'uploads', `qr_${user}.png`);

    if (fs.existsSync(sessionDir)) fs.rmSync(sessionDir, { recursive: true, force: true });

    const { version } = await fetchLatestBaileysVersion().catch(() => ({ version: [2, 3000, 1015901307] }));
    const { state, saveCreds } = await useMultiFileAuthState(sessionDir);

    const sock = makeWASocket({
        version,
        auth: state,
        logger: pino({ level: 'debug' }),
        browser: ['Ubuntu', 'Chrome', '20.0.04'],
        waWebSocketUrl: 'wss://web.whatsapp.com/ws/chat',
        connectTimeoutMs: 60000,
    });

    sock.ev.on('creds.update', saveCreds);
    sock.ev.on('connection.update', async (update) => {
        console.log("Update:", update.connection, "QR:", !!update.qr);
        if (update.qr) {
            console.log("SUCCESS! QR received!");
            await qrcode.toFile(qrPath, update.qr);
            console.log("PNG File created!");
            process.exit(0);
        }
    });
}

test().catch(err => console.error(err));
