const pino = require('pino');
const fs = require('fs');
const path = require('path');
const os = require('os');

// Parse CLI arguments
const args = {};
let broadcastMasivoCli = false;
for (let i = 2; i < process.argv.length; i++) {
    const arg = process.argv[i];
    if (arg === '--broadcast_masivo') {
        broadcastMasivoCli = true;
    } else if (arg.startsWith('--')) {
        const key = arg.slice(2);
        const val = process.argv[i + 1];
        args[key] = val;
        i++;
    }
}

const usuario = args.user || 'admin';
const scope = args.scope || 'historias'; // 'portal' or 'historias'
const action = args.action || 'message'; // 'status' or 'message'
const filePath = args.file;
const caption = args.caption || '';
const phone = args.phone;
const message = args.text;

let sessionDir;
if (scope === 'portal') {
    sessionDir = path.join(os.homedir(), '.whatsapp_portal_session_admin');
} else {
    sessionDir = path.join(os.homedir(), `.whatsapp_bot_session_${usuario}`);
}

const logDir = path.join('C:', 'FerrariDB', 'logs');
if (!fs.existsSync(logDir)) {
    try { fs.mkdirSync(logDir, { recursive: true }); } catch(e){}
}
const logFile = path.join(logDir, `wa_ephemeral_${scope}_${usuario}.log`);

function bridgeLog(level, msg) {
    const ts = new Date().toISOString().replace('T', ' ').slice(0, 19);
    const line = `${ts} [${level.toUpperCase()}] [${scope}:${usuario}] ${msg}`;
    console.log(line);
    try { fs.appendFileSync(logFile, line + '\n', 'utf8'); } catch(e){}
}

async function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function start() {
    bridgeLog('info', `Iniciando ephemeral sender (Scope: ${scope}, Action: ${action})`);

    const hasBaileysSession = fs.existsSync(sessionDir) && fs.existsSync(path.join(sessionDir, 'creds.json'));
    if (!hasBaileysSession) {
        bridgeLog('warn', `No session found in ${sessionDir}. Exiting with code 2.`);
        process.exit(2);
    }

    // Global process timeout of 120s
    const globalTimeoutTimer = setTimeout(() => {
        bridgeLog('error', 'Global execution timeout reached (120s)');
        process.exit(1);
    }, 120000);

    // ── TERMINAR CUALQUIER LINKER RESIDUAL QUE ESTÉ OCUPANDO EL SOCKET ──
    try {
        const uploadsDir = path.join(__dirname, '..', '..', 'static', 'uploads');
        const statusFile = scope === 'portal' 
            ? path.join(uploadsDir, 'status_portal_admin.json')
            : path.join(uploadsDir, `status_historias_${usuario}.json`);
        if (fs.existsSync(statusFile)) {
            const sdata = JSON.parse(fs.readFileSync(statusFile, 'utf8'));
            if (sdata.pid && sdata.pid !== process.pid) {
                try {
                    process.kill(sdata.pid);
                    bridgeLog('info', `Terminado proceso linker previo (PID ${sdata.pid}) para liberar el socket.`);
                } catch(e){}
            }
        }
    } catch(e){}

    let mediaObj = null;
    let targetStatusJids = [];
    let isMasivo = broadcastMasivoCli;

    // ── 1. PREPARACIÓN PREVIA DE ARCHIVOS Y DESTINATARIOS (ANTES DE ABRIR SOCKET) ──
    if (action === 'status') {
        if (!filePath || !fs.existsSync(filePath)) {
            bridgeLog('error', `File not found: ${filePath}`);
            process.exit(1);
        }
        
        const mediaBuffer = fs.readFileSync(filePath);
        const ext = path.extname(filePath).toLowerCase();
        if (['.jpg', '.jpeg', '.png'].includes(ext)) mediaObj = { image: mediaBuffer };
        else if (['.mp4', '.mov', '.3gp'].includes(ext)) mediaObj = { video: mediaBuffer };
        else {
            bridgeLog('error', `Unsupported extension: ${ext}`);
            process.exit(1);
        }
        if (caption) mediaObj.caption = caption;

        let ownPhoneJid = null;
        try {
            const creds = JSON.parse(fs.readFileSync(path.join(sessionDir, 'creds.json'), 'utf8'));
            if (creds && creds.me && creds.me.id) {
                ownPhoneJid = creds.me.id.split('@')[0].split(':')[0] + '@s.whatsapp.net';
            }
        } catch(e){}

        try {
            const persistentGoogleContacts = path.join('C:', 'FerrariDB', 'usuarios', usuario, 'google_contacts.json');
            const persistentCrmContacts = path.join('C:', 'FerrariDB', 'usuarios', usuario, 'crm_recent_contacts.json');
            const directChatsFile = path.join('C:', 'FerrariDB', 'usuarios', usuario, 'direct_chats_cache.json');
            
            let googleContactsSet = new Set();
            if (fs.existsSync(persistentGoogleContacts)) {
                try {
                    googleContactsSet = new Set(JSON.parse(fs.readFileSync(persistentGoogleContacts, 'utf8')));
                    bridgeLog('info', `Paso 0: Cargados ${googleContactsSet.size} contactos desde la agenda de Google.`);
                } catch(e) {
                    bridgeLog('error', `Error leyendo agenda de Google: ${e.message}`);
                }
            }

            if (googleContactsSet.size === 0) {
                bridgeLog('error', `No se encontro archivo de agenda para ${usuario}. Debes subir tu agenda primero.`);
                process.exit(1);
            }

            if (isMasivo) {
                bridgeLog('info', `⚡ CLI: MODO BROADCAST MASIVO ACTIVO: Preparando toda la agenda...`);
                for (const jid of googleContactsSet) {
                    if (jid && jid.endsWith('@s.whatsapp.net')) {
                        targetStatusJids.push(jid);
                    }
                }
            } else {
                let targets = [];

                // Paso 1: CRM recientes
                if (fs.existsSync(persistentCrmContacts)) {
                    try {
                        const rawCrm = JSON.parse(fs.readFileSync(persistentCrmContacts, 'utf8'));
                        const crmContacts = rawCrm.filter(jid => googleContactsSet.has(jid));
                        bridgeLog('info', `Paso 1 (CLI): Encontrados ${crmContacts.length} contactos del CRM.`);
                        crmContacts.forEach(jid => { if (!targets.includes(jid)) targets.push(jid); });
                    } catch(e){}
                }

                // Paso 2: Chats directos
                if (targets.length < 250 && fs.existsSync(directChatsFile)) {
                    try {
                        const directChats = JSON.parse(fs.readFileSync(directChatsFile, 'utf8'));
                        const paso2Contacts = Object.entries(directChats)
                            .filter(([jid]) => googleContactsSet.has(jid))
                            .sort((a, b) => b[1] - a[1])
                            .map(([jid]) => jid);
                        bridgeLog('info', `Paso 2 (CLI): Encontrados ${paso2Contacts.length} chats directos.`);
                        for (const jid of paso2Contacts) {
                            if (targets.length >= 250) break;
                            if (!targets.includes(jid)) targets.push(jid);
                        }
                    } catch(e){}
                }

                // Paso 3: LIDs locales
                if (targets.length < 250) {
                    try {
                        const files = fs.readdirSync(sessionDir);
                        const lidFiles = files.filter(f => f.startsWith('lid-mapping-') && f.endsWith('_reverse.json'));
                        let sessionLids = [];
                        lidFiles.forEach(file => {
                            try {
                                const raw = fs.readFileSync(path.join(sessionDir, file), 'utf8').trim();
                                if (raw) {
                                    const phone = JSON.parse(raw);
                                    if (phone) sessionLids.push(`${phone}@s.whatsapp.net`);
                                }
                            } catch(e){}
                        });
                        const paso3Pool = sessionLids.filter(jid => googleContactsSet.has(jid) && !targets.includes(jid));
                        for (let i = paso3Pool.length - 1; i > 0; i--) {
                            const j = Math.floor(Math.random() * (i + 1));
                            [paso3Pool[i], paso3Pool[j]] = [paso3Pool[j], paso3Pool[i]];
                        }
                        bridgeLog('info', `Paso 3 (CLI): Completando con ${paso3Pool.length} LIDs aleatorios.`);
                        for (const jid of paso3Pool) {
                            if (targets.length >= 250) break;
                            targets.push(jid);
                        }
                    } catch(e){}
                }

                // Paso 4: Fallback agenda Google
                if (targets.length < 250) {
                    for (const jid of googleContactsSet) {
                        if (targets.length >= 250) break;
                        if (!targets.includes(jid)) targets.push(jid);
                    }
                }

                const cleanJids = [];
                if (ownPhoneJid && ownPhoneJid.endsWith('@s.whatsapp.net') && !cleanJids.includes(ownPhoneJid)) {
                    cleanJids.push(ownPhoneJid);
                }
                for (const jid of targets) {
                    if (cleanJids.length >= 250) break;
                    if (jid && jid.endsWith('@s.whatsapp.net')) {
                        const digits = jid.replace('@s.whatsapp.net', '');
                        if (!digits.startsWith('0') && /^\d{10,15}$/.test(digits) && !cleanJids.includes(jid)) {
                            cleanJids.push(jid);
                        }
                    }
                }
                targetStatusJids = cleanJids;
            }
        } catch(e) {
            bridgeLog('error', `Error resolviendo destinatarios en CLI: ${e.message}`);
            process.exit(1);
        }

        // Anti-ban humano: Pausa previa de preparación antes de conectar el socket
        const statusPreDelay = Math.floor(Math.random() * 4000) + 4000;
        bridgeLog('info', `Simulando preparación previa humana (${statusPreDelay}ms)...`);
        await sleep(statusPreDelay);

    } else if (action === 'message') {
        if (!phone || !message) {
            bridgeLog('error', `Missing phone or message`);
            process.exit(1);
        }
        await sleep(1500);
    }

    // ── 2. CONEXIÓN A BAILEYS Y ENVÍO INMEDIATO AL ABRIR EL SOCKET ──
    const baileys = await import('@whiskeysockets/baileys');
    const makeWASocket = baileys.default || baileys.makeWASocket;
    const { useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion, Browsers } = baileys;

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
        logger: pino({ level: 'silent' }),
        browser: Browsers ? Browsers.windows('Chrome') : ['Windows', 'Chrome', '124.0.6367.207'],
        markOnlineOnConnect: false,
        syncFullHistory: false,
        connectTimeoutMs: 60000,
        keepAliveIntervalMs: 10000,
        defaultQueryTimeoutMs: 60000,
    });

    sock.ev.on('creds.update', saveCreds);

    let isConnected = false;
    let hasSent = false;
    
    // timeout si la conexión demora más de 30s
    const connectionTimeout = setTimeout(() => {
        if (!isConnected) {
            bridgeLog('error', 'Timeout waiting for first connection');
            process.exit(1);
        }
    }, 30000);

    sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (qr) {
            bridgeLog('error', `QR requested. Session invalid for ${usuario}.`);
            process.exit(2);
        }

        if (connection === 'close') {
            const statusCode = lastDisconnect?.error?.output?.statusCode;
            const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
            
            if (hasSent) {
                bridgeLog('info', 'Disconnected cleanly after sending.');
                process.exit(0);
            }

            if (shouldReconnect) {
                bridgeLog('warn', `Connection closed. Waiting for automatic reconnection...`);
            } else {
                bridgeLog('error', `Logged out. Session invalid.`);
                try { fs.rmSync(sessionDir, { recursive: true, force: true }); } catch (e) {}
                process.exit(2);
            }
        } else if (connection === 'open') {
            isConnected = true;
            clearTimeout(connectionTimeout);
            bridgeLog('info', `WhatsApp connected. Processing action: ${action}`);

            if (hasSent) return;

            try {
                if (action === 'status') {
                    if (targetStatusJids.length === 0) {
                        bridgeLog('error', `No se encontraron destinatarios válidos para publicar estado.`);
                        process.exit(1);
                    }

                    // Dar 2 segundos al socket para sincronizar stanzas iniciales con el servidor
                    try { await sock.sendPresenceUpdate('available'); } catch(e){}
                    await sleep(2000);

                    bridgeLog('info', `Sending status with ${targetStatusJids.length} contacts...`);
                    const sentStatus = await sock.sendMessage('status@broadcast', mediaObj, { 
                        statusJidList: targetStatusJids 
                    });
                    bridgeLog('info', `Status sent. ID: ${sentStatus?.key?.id}`);
                    hasSent = true;
                    try { clearTimeout(globalTimeoutTimer); } catch(e){}

                    // Esperar 3.5 segundos para que los ACKs del servidor se completen antes de cerrar
                    setTimeout(() => {
                        bridgeLog('info', 'Cerrando socket de forma segura tras envío de estado...');
                        try { if (sock.ws) sock.ws.close(); } catch(e){}
                        setTimeout(() => process.exit(0), 1000);
                    }, 3500);

                } else if (action === 'message') {
                    const cleanDigits = phone.replace(/\D/g, '');
                    let targetJid = `${cleanDigits}@s.whatsapp.net`;
                    bridgeLog('info', `Destinatario inicial: ${targetJid}`);

                    try {
                        const candidates = [cleanDigits];
                        if (cleanDigits.startsWith('549')) {
                            candidates.push('54' + cleanDigits.slice(3));
                        } else if (cleanDigits.startsWith('54') && !cleanDigits.startsWith('549')) {
                            candidates.push('549' + cleanDigits.slice(2));
                        }

                        for (const c of candidates) {
                            const res = await sock.onWhatsApp(c);
                            if (res && res.length > 0 && res[0].exists && res[0].jid) {
                                targetJid = res[0].jid;
                                bridgeLog('info', `Destinatario validado con onWhatsApp: ${targetJid}`);
                                break;
                            }
                        }
                    } catch(e) {
                        bridgeLog('warn', `onWhatsApp check: ${e.message}`);
                    }

                    bridgeLog('info', `Enviando mensaje a ${targetJid}...`);
                    const sentMsg = await sock.sendMessage(targetJid, { text: message });
                    bridgeLog('info', `Mensaje enviado exitosamente. ID: ${sentMsg?.key?.id}`);
                    hasSent = true;
                    try { clearTimeout(globalTimeoutTimer); } catch(e){}

                    setTimeout(() => {
                        bridgeLog('info', 'Cerrando socket de forma segura...');
                        try { if (sock.ws) sock.ws.close(); } catch(e){}
                        setTimeout(() => process.exit(0), 1000);
                    }, 2500);
                } else {
                    bridgeLog('error', `Unknown action: ${action}`);
                    process.exit(1);
                }

            } catch (err) {
                bridgeLog('error', `Action failed: ${err.message}`);
                process.exit(1);
            }
        }
    });
}

start().catch(err => {
    console.error("Unhandled start error:", err);
    process.exit(1);
});
