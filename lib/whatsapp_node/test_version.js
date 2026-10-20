const pino = require('pino');
const qrcode = require('qrcode');
const path = require('path');
const os = require('os');
const fs = require('fs');

const user = "GermanMazza";
const sessionDir = path.join(os.homedir(), `.whatsapp_bot_session_${user}`);
const qrPath = path.join(__dirname, '..', '..', 'static', 'uploads', `qr_${user}.png`);

if (fs.existsSync(sessionDir)) fs.rmSync(sessionDir, { recursive: true, force: true });

let currentSock = null;

async function start(attempt = 1) {
    console.log(`[Attempt ${attempt}] Starting Baileys connection...`);

    if (currentSock && currentSock.ws) {
        try { currentSock.ws.close(); } catch(e){}
    }

    const baileys = await import('@whiskeysockets/baileys');
    const makeWASocket = baileys.default;
    const { useMultiFileAuthState, fetchLatestBaileysVersion, Browsers } = baileys;

    const { version } = await fetchLatestBaileysVersion();
    const { state, saveCreds } = await useMultiFileAuthState(sessionDir);

    currentSock = makeWASocket({
        version,
        auth: state,
        logger: pino({ level: 'info' }),
        browser: Browsers.macOS('Desktop'),
    });

    currentSock.ev.on('creds.update', saveCreds);

    currentSock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update;
        console.log(`[Attempt ${attempt}] Connection state:`, connection, "| QR code present:", !!qr);

        if (qr) {
            console.log("🎉🎉🎉 SUCCESS! QR CODE RECEIVED FROM WHATSAPP WEB! 🎉🎉🎉");
            await qrcode.toFile(qrPath, qr);
            console.log("SUCCESS! PNG file created at:", qrPath);
            process.exit(0);
        }

        if (connection === 'close') {
            const statusCode = lastDisconnect?.error?.output?.statusCode;
            console.log(`[Attempt ${attempt}] Disconnected (statusCode:`, statusCode, "). Reconnecting attempt", attempt + 1, "in 1s...");
            if (attempt < 5) {
                setTimeout(() => start(attempt + 1), 1000);
            } else {
                console.error("Exhausted attempts");
                process.exit(1);
            }
        }
    });
}

start(1).catch(console.error);
