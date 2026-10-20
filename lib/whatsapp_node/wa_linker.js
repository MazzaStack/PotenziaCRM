const qrcode = require('qrcode');
const path = require('path');
const os = require('os');
const fs = require('fs');

let makeWASocket, useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion;

const args = {};
for (let i = 2; i < process.argv.length; i++) {
    const arg = process.argv[i];
    if (arg.startsWith('--')) {
        args[arg.slice(2)] = process.argv[i + 1];
        i++;
    }
}

const usuario = args.user;
if (!usuario) {
    console.error("Missing --user argument");
    process.exit(1);
}

const uploadsDir = path.join(__dirname, '..', '..', 'static', 'uploads');
if (!fs.existsSync(uploadsDir)) {
    try { fs.mkdirSync(uploadsDir, { recursive: true }); } catch(e){}
}

const scope = args.scope || 'historias'; // 'portal' o 'historias'

let sessionDir, qrPath, statusPath, legacyQrPath, legacyStatusPath;

if (scope === 'portal') {
    sessionDir = path.join(os.homedir(), `.whatsapp_portal_session_admin`);
    qrPath = path.join(uploadsDir, `qr_portal_admin.png`);
    statusPath = path.join(uploadsDir, `status_portal_admin.json`);
} else {
    sessionDir = path.join(os.homedir(), `.whatsapp_bot_session_${usuario}`);
    qrPath = path.join(uploadsDir, `qr_historias_${usuario}.png`);
    statusPath = path.join(uploadsDir, `status_historias_${usuario}.json`);
    legacyQrPath = path.join(uploadsDir, `qr_${usuario}.png`);
    legacyStatusPath = path.join(uploadsDir, `status_${usuario}.json`);
}

const logDir = path.join('C:', 'FerrariDB', 'logs');
if (!fs.existsSync(logDir)) {
    try { fs.mkdirSync(logDir, { recursive: true }); } catch(e){}
}
const logFile = path.join(logDir, `wa_linker_${scope}_${usuario}.log`);

function writeLog(msg) {
    const ts = new Date().toISOString();
    try { fs.appendFileSync(logFile, `${ts} ${msg}\n`, 'utf8'); } catch(e){}
}

if (args.clean && fs.existsSync(sessionDir)) {
    try { fs.rmSync(sessionDir, { recursive: true, force: true }); } catch(e){}
}

function writeStatus(status, qrData = null) {
    writeLog(`Estado cambiado a: ${status}`);
    try {
        const payload = { status, usuario, scope, pid: process.pid, ts: Date.now() };
        if (qrData) {
            payload.qr = qrData;
        }
        const payloadStr = JSON.stringify(payload);
        fs.writeFileSync(statusPath, payloadStr);
        if (legacyStatusPath) {
            fs.writeFileSync(legacyStatusPath, payloadStr);
        }
    } catch(e){
        writeLog(`Error escribiendo status file: ${e.message}`);
    }
}

writeStatus('connecting');

// ── WATCHDOG: Timeout máximo de 180s (3 min) para escanear QR ──
// Si no se vincula en 3 minutos, se auto-destruye para no quedar zombi en memoria
setTimeout(() => {
    writeLog('Tiempo límite de espera de QR alcanzado (180s). Auto-cerrando proceso...');
    if (fs.existsSync(qrPath)) {
        try { fs.unlinkSync(qrPath); } catch(e){}
    }
    process.exit(0);
}, 180000);

async function startLinker() {
    if (!makeWASocket) {
        const baileys = await import('@whiskeysockets/baileys');
        makeWASocket = baileys.default || baileys.makeWASocket;
        useMultiFileAuthState = baileys.useMultiFileAuthState;
        DisconnectReason = baileys.DisconnectReason;
        fetchLatestBaileysVersion = baileys.fetchLatestBaileysVersion;
        Browsers = baileys.Browsers;
    }

    const { state, saveCreds } = await useMultiFileAuthState(sessionDir);
    
    let version = [2, 3000, 1043857760];
    try {
        const waVer = await fetchLatestBaileysVersion();
        if (waVer && waVer.version) {
            version = waVer.version;
        }
    } catch(e){}

    const sock = makeWASocket({
        auth: state,
        version,
        browser: Browsers ? Browsers.windows('Chrome') : ['Windows', 'Chrome', '124.0.6367.207'],
        printQRInTerminal: false,
        markOnlineOnConnect: false,
        syncFullHistory: false,
        connectTimeoutMs: 60000
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update;
        if (qr) {
            writeStatus('qr_ready', qr);
            try {
                await qrcode.toFile(qrPath, qr, { width: 300 });
                if (legacyQrPath) {
                    await qrcode.toFile(legacyQrPath, qr, { width: 300 });
                }
            } catch(e){}
        }

        if (connection === 'open') {
            writeStatus('connected');
            if (fs.existsSync(qrPath)) {
                try { fs.unlinkSync(qrPath); } catch(e){}
            }
            if (legacyQrPath && fs.existsSync(legacyQrPath)) {
                try { fs.unlinkSync(legacyQrPath); } catch(e){}
            }
            writeLog('Vinculación completada exitosamente. Guardando credenciales y liberando socket...');
            setTimeout(() => {
                try { if (sock.ws) sock.ws.close(); } catch(e){}
                setTimeout(() => process.exit(0), 1000);
            }, 3000);
        }

        if (connection === 'close') {
            const statusCode = lastDisconnect?.error?.output?.statusCode;
            if (statusCode === DisconnectReason.loggedOut) {
                writeStatus('disconnected');
                try { fs.rmSync(sessionDir, { recursive: true, force: true }); } catch(e){}
            } else {
                writeStatus('connecting');
                setTimeout(startLinker, 3000);
            }
        }
    });
}

startLinker().catch(e => {
    console.error("Linker error:", e);
    writeStatus('disconnected');
});
