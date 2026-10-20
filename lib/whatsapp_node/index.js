const { default: makeWASocket, useMultiFileAuthState, DisconnectReason, delay, fetchLatestBaileysVersion, Browsers } = require('@whiskeysockets/baileys');
const pino = require('pino');
const express = require('express');
const qrcode = require('qrcode');
const fs = require('fs');
const path = require('path');
const os = require('os');

// ── Parse CLI arguments ────────────────────────────────────────────────────
const args = {};
for (let i = 2; i < process.argv.length; i++) {
    const arg = process.argv[i];
    if (arg.startsWith('--')) {
        const key = arg.slice(2);
        const val = process.argv[i + 1];
        args[key] = val;
        i++;
    }
}

const usuario = args.usuario || args.user || 'default';
const port = parseInt(args.port || 9001);

console.log(`>>> BRIDGE NODE: Iniciando para usuario: ${usuario} en puerto: ${port}`);

// ── Paths ──────────────────────────────────────────────────────────────────
const sessionDir = path.join(os.homedir(), `.whatsapp_bot_session_${usuario}`);
const qrPath = path.join(__dirname, '..', '..', 'static', 'uploads', `qr_${usuario}.png`);


// Ensure static/uploads exists
try { fs.mkdirSync(path.dirname(qrPath), { recursive: true }); } catch (err) {}

// ── Log file ───────────────────────────────────────────────────────────────
const logDir = path.join('C:', 'FerrariDB', 'logs');
const logFile = path.join(logDir, 'wa_bridge.log');
try { fs.mkdirSync(logDir, { recursive: true }); } catch (e) {}

function bridgeLog(level, message, extra = null) {
    const ts = new Date().toISOString().replace('T', ' ').slice(0, 19);
    const extraStr = extra ? ` | ${JSON.stringify(extra)}` : '';
    const line = `${ts} [${level.toUpperCase()}] [${usuario}:${port}] ${message}${extraStr}`;
    console.log(line);
    try {
        fs.appendFileSync(logFile, line + '\n', 'utf8');
    } catch (e) {}
}

// ── State ──────────────────────────────────────────────────────────────────
let sock = null;
let connectionStatus = 'disconnected';
let storedContacts = []; // lista de JIDs @s.whatsapp.net para statusJidList

// ── Cargar contactos desde archivos lid-mapping de la sesión ───────────────
function loadContactsFromSession() {
    // Los archivos lid-mapping-XXXXXXX_reverse.json contienen el teléfono de cada contacto
    // Nombre: lid-mapping-{LID}_reverse.json  Contenido: "549XXXXXXXXXX"
    try {
        const files = fs.readdirSync(sessionDir);
        const lidFiles = files.filter(f => f.startsWith('lid-mapping-') && f.endsWith('_reverse.json'));

        const jids = [];
        // Para evitar EMFILE y cuelgues, y debido a que statusJidList soporta listas de hasta ~500-1000 de forma estable,
        // limitamos la carga a los primeros 500 contactos para no saturar.
        const limit = Math.min(lidFiles.length, 500);
        for (let i = 0; i < limit; i++) {
            const file = lidFiles[i];
            try {
                const fullPath = path.join(sessionDir, file);
                const raw = fs.readFileSync(fullPath, 'utf8').trim();
                if (!raw) continue;
                const phone = JSON.parse(raw); // es un string con el número
                if (phone && /^\d{7,15}$/.test(phone)) {
                    jids.push(`${phone}@s.whatsapp.net`);
                }
            } catch (e) {
                // ignorar corruptos
            }
        }

        storedContacts = jids;
        bridgeLog('info', `Contactos cargados desde sesión (limite 500): ${jids.length} (de ${lidFiles.length} archivos lid en total)`);
        return jids.length;
    } catch (e) {
        bridgeLog('warn', `Error cargando contactos desde sesión: ${e.message}`);
        return 0;
    }
}

// ── Definir rutas de datos persistentes comunes en C:\FerrariDB\usuarios ──
const persistentUserDir = path.join('C:', 'FerrariDB', 'usuarios', usuario);
fs.mkdirSync(persistentUserDir, { recursive: true });

const directChatsFile = path.join(persistentUserDir, 'direct_chats_cache.json');
const contactsCacheFile = path.join(persistentUserDir, 'contacts_cache.json');

// ── Guardar contactos reales (con nombre en la libreta) en un archivo persistente ──
function saveRealContacts(contactsList) {
    if (!contactsList || !Array.isArray(contactsList)) return;
    try {
        let existing = [];
        if (fs.existsSync(contactsCacheFile)) {
            try {
                existing = JSON.parse(fs.readFileSync(contactsCacheFile, 'utf8'));
            } catch(e){}
        }
        
        const contactsMap = {};
        existing.forEach(c => { if (c && c.id) contactsMap[c.id] = c; });
        
        let newCount = 0;
        contactsList.forEach(c => {
            if (c && c.id && c.id.endsWith('@s.whatsapp.net')) {
                const name = c.name || c.verifiedName;
                if (name && name.trim().length > 0) {
                    if (!contactsMap[c.id]) newCount++;
                    contactsMap[c.id] = { id: c.id, name: name.trim() };
                }
            }
        });
        
        if (newCount > 0) {
            const toSave = Object.values(contactsMap);
            fs.writeFileSync(contactsCacheFile, JSON.stringify(toSave, null, 2), 'utf8');
            bridgeLog('info', `Guardados ${toSave.length} contactos reales (+${newCount} nuevos) en contacts_cache.json`);
        }
    } catch(e) {
        bridgeLog('error', `Error guardando cache de contactos: ${e.message}`);
    }
}

// ── Guardar chats directos (1-a-1, no grupos) con timestamp ─────────────────
function saveDirectChat(jid, timestamp) {
    if (!jid || !jid.endsWith('@s.whatsapp.net')) return;
    try {
        let chats = {};
        if (fs.existsSync(directChatsFile)) {
            try { chats = JSON.parse(fs.readFileSync(directChatsFile, 'utf8')); } catch(e){}
        }
        const ts = Number(timestamp) || Date.now();
        if (!chats[jid] || ts > chats[jid]) {
            chats[jid] = ts;
            fs.writeFileSync(directChatsFile, JSON.stringify(chats), 'utf8');
        }
    } catch(e) {}
}

// ── Socket ──────────────────────────────────────────────────────────────────
async function startSock() {
    connectionStatus = 'connecting';
    bridgeLog('info', 'Iniciando conexión Baileys...');

    // Pre-cargar contactos desde archivos de sesión ANTES de conectar
    const preLoaded = loadContactsFromSession();
    if (preLoaded > 0) {
        bridgeLog('info', `Pre-cargados ${preLoaded} contactos desde sesión guardada`);
    }

    const { version } = await fetchLatestBaileysVersion();
    bridgeLog('info', `Baileys version: ${version.join('.')}`);

    const { state, saveCreds } = await useMultiFileAuthState(sessionDir);

    sock = makeWASocket({
        version,
        auth: state,
        logger: pino({ level: 'silent' }),
        printQRInTerminal: true,
        // Para que Baileys también cargue los contactos
        syncFullHistory: true,
        browser: Browsers ? Browsers.windows('Chrome') : ['Windows', 'Chrome', '124.0.6367.207'],
        // Optimizaciones de tolerancia de red (mitigación 440)
        connectTimeoutMs: 60000, // Eleva el tiempo de espera de conexión a 60s
    });

    sock.ev.on('creds.update', saveCreds);

    // Cargar contactos del store cuando se actualicen
    sock.ev.on('contacts.upsert', (contacts) => {
        bridgeLog('debug', `contacts.upsert recibido: ${contacts.length}`);
        contacts.forEach(c => {
            if (c.id && !storedContacts.includes(c.id)) {
                storedContacts.push(c.id);
            }
        });
        saveRealContacts(contacts);
    });

    sock.ev.on('contacts.update', (contacts) => {
        bridgeLog('debug', `contacts.update recibido: ${contacts.length}`);
        saveRealContacts(contacts);
    });

    sock.ev.on('messaging-history.set', ({ chats, contacts, messages }) => {
        // Guardar contactos reales
        if (contacts && contacts.length > 0) {
            saveRealContacts(contacts);
        }

        // En el historial inicial, registramos los mensajes que fueron enviados por mí (fromMe)
        if (messages && messages.length > 0) {
            let processedCount = 0;
            messages.forEach(msg => {
                const jid = msg.key?.remoteJid;
                if (jid && jid.endsWith('@s.whatsapp.net')) {
                    if (!msg.key.fromMe) return; // Solo anclas de mensajes enviados por mí
                    if (msg.messageStubType || msg.stubType) return;

                    const msgType = Object.keys(msg.message || {})[0];
                    if (!msgType || ['protocolMessage', 'senderKeyDistributionMessage', 'keyExpiration'].includes(msgType)) return;

                    const ts = msg.messageTimestamp
                        ? Number(msg.messageTimestamp) * 1000
                        : Date.now();
                    
                    saveDirectChat(jid, ts);
                    processedCount++;
                }
            });
            bridgeLog('info', `messaging-history.set: procesados ${processedCount} mensajes históricos salientes reales.`);
        }
    });

    // Escuchar mensajes en tiempo real para actualizar la lista basados exclusivamente en tus envíos (fromMe)
    sock.ev.on('messages.upsert', ({ messages, type }) => {
        if (type !== 'notify') return;
        messages.forEach(msg => {
            const jid = msg.key?.remoteJid;
            if (jid && jid.endsWith('@s.whatsapp.net')) {
                // Solo registramos si el mensaje lo enviamos nosotros
                if (!msg.key.fromMe) return;
                if (msg.messageStubType || msg.stubType) return;
                
                const msgType = Object.keys(msg.message || {})[0];
                if (!msgType || ['protocolMessage', 'senderKeyDistributionMessage', 'keyExpiration'].includes(msgType)) return;

                // Solo si el mensaje tiene contenido real
                const ts = msg.messageTimestamp
                    ? Number(msg.messageTimestamp) * 1000
                    : Date.now();
                saveDirectChat(jid, ts);
                bridgeLog('info', `Mensaje enviado detectado hacia +${jid.replace('@s.whatsapp.net', '')}. Registrada última charla.`);
            }
        });
    });

    sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (qr) {
            connectionStatus = 'qr_ready';
            bridgeLog('info', `Nuevo QR generado para ${usuario}`);
            try {
                await qrcode.toFile(qrPath, qr);
            } catch (err) {
                bridgeLog('error', 'Error generando QR', { error: err.message });
            }
        }

        if (connection === 'close') {
            const statusCode = lastDisconnect?.error?.output?.statusCode;
            const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
            bridgeLog('warn', `Conexión cerrada. Reintentando: ${shouldReconnect}, StatusCode: ${statusCode}`);

            if (fs.existsSync(qrPath)) { try { fs.unlinkSync(qrPath); } catch (e) {} }

            if (shouldReconnect) {
                connectionStatus = 'connecting';
                // Si el cierre fue por latencia, socket colgado (428, 440, 500, 503, 515), reconectamos más rápido (1s)
                const isNetworkDrop = [428, 440, 500, 503, 515].includes(statusCode);
                const delay = isNetworkDrop ? 1000 : 5000;
                bridgeLog('info', `Reconectando en ${delay / 1000}s...`);
                setTimeout(startSock, delay);
            } else {
                connectionStatus = 'disconnected';
                bridgeLog('info', 'Logout detectado. Borrando sesión.');
                try { fs.rmSync(sessionDir, { recursive: true, force: true }); } catch (e) {}
            }
        } else if (connection === 'open') {
            connectionStatus = 'connected';
            bridgeLog('info', `WhatsApp conectado exitosamente para ${usuario}`);
            if (fs.existsSync(qrPath)) { try { fs.unlinkSync(qrPath); } catch (e) {} }

            // Construir lista de contactos directos excluyendo miembros de grupos
            setTimeout(async () => {
                try {
                    bridgeLog('info', 'Construyendo mapa LID→teléfono desde archivos de sesión...');

                    // Paso 1: mapa lid_number → phoneJid desde los archivos lid-mapping
                    const lidToPhone = {};
                    const allLidFiles = fs.readdirSync(sessionDir)
                        .filter(f => f.startsWith('lid-mapping-') && f.endsWith('_reverse.json'));
                    for (const f of allLidFiles) {
                        try {
                            const lidNum = f.replace('lid-mapping-', '').replace('_reverse.json', '');
                            const phone = JSON.parse(fs.readFileSync(path.join(sessionDir, f), 'utf8').trim());
                            if (phone && /^\d{7,15}$/.test(phone)) {
                                lidToPhone[`${lidNum}@lid`] = `${phone}@s.whatsapp.net`;
                            }
                        } catch(e) {}
                    }
                    bridgeLog('info', `Mapa LID→teléfono construido: ${Object.keys(lidToPhone).length} entradas`);

                    // Paso 2: obtener todos los grupos y resolver participantes a phoneJid
                    bridgeLog('info', 'Obteniendo grupos para filtrar contactos directos...');
                    const groups = await sock.groupFetchAllParticipating();
                    const groupMemberJids = new Set();
                    Object.values(groups).forEach(group => {
                        (group.participants || []).forEach(p => {
                            const raw = p.id || p.lid || '';
                            if (raw.endsWith('@s.whatsapp.net')) {
                                groupMemberJids.add(raw);
                            } else if (raw.endsWith('@lid') && lidToPhone[raw]) {
                                groupMemberJids.add(lidToPhone[raw]);
                            }
                        });
                    });
                    bridgeLog('info', `Grupos: ${Object.keys(groups).length} | Miembros excluidos: ${groupMemberJids.size}`);

                    // Paso 3: filtrar lid-mapping excluyendo miembros de grupos
                    const lidFiles = allLidFiles
                        .map(f => ({ name: f, mtime: fs.statSync(path.join(sessionDir, f)).mtimeMs }))
                        .sort((a, b) => b.mtime - a.mtime);

                    const directChats = {};
                    let added = 0, skipped = 0;
                    for (const { name: f, mtime } of lidFiles) {
                        try {
                            const phone = JSON.parse(fs.readFileSync(path.join(sessionDir, f), 'utf8').trim());
                            if (!phone || !/^\d{7,15}$/.test(phone)) continue;
                            const jid = `${phone}@s.whatsapp.net`;
                            if (!groupMemberJids.has(jid)) {
                                directChats[jid] = mtime;
                                added++;
                            } else {
                                skipped++;
                            }
                        } catch(e) {}
                    }

                    fs.writeFileSync(directChatsFile, JSON.stringify(directChats), 'utf8');
                    bridgeLog('info', `Contactos directos: ${added} guardados, ${skipped} de grupos excluidos → direct_chats_cache.json`);
                } catch(e) {
                    bridgeLog('warn', `Error construyendo lista de contactos directos: ${e.message}`);
                }
            }, 5000);
        }
    });
}

// ── Express ────────────────────────────────────────────────────────────────
const app = express();
app.use(express.json());

// GET /status  → estado de la conexión
app.get('/status', (req, res) => {
    res.json({
        usuario,
        status: connectionStatus,
        contacts_loaded: storedContacts.length,
    });
});

// POST /send  → enviar mensaje directo
app.post('/send', async (req, res) => {
    const { phone, message } = req.body;
    if (!phone || !message) return res.status(400).json({ error: 'phone and message required' });
    if (connectionStatus !== 'connected' || !sock) return res.status(503).json({ error: 'WhatsApp not connected' });

    try {
        let jid = phone.includes('@') ? phone : `${phone}@s.whatsapp.net`;
        bridgeLog('info', `Enviando mensaje a ${jid}`);
        const sent = await sock.sendMessage(jid, { text: message });
        res.json({ success: true, messageId: sent.key.id });
    } catch (err) {
        bridgeLog('error', `Error enviando mensaje a ${req.body.phone}`, { error: err.message });
        res.status(500).json({ error: 'Failed to send', details: err.message });
    }
});

// POST /status  → publicar estado/historia de WhatsApp
app.post('/status', async (req, res) => {
    const { filePath, caption } = req.body;

    bridgeLog('info', `Solicitud de publicar estado`, { filePath, caption });

    if (!filePath) return res.status(400).json({ error: 'filePath is required' });
    if (connectionStatus !== 'connected' || !sock) {
        bridgeLog('warn', `WhatsApp no conectado (status: ${connectionStatus})`);
        return res.status(503).json({ error: `WhatsApp no conectado. Status: ${connectionStatus}` });
    }

    try {
        const absolutePath = path.resolve(filePath);
        bridgeLog('debug', `Path absoluto resuelto: ${absolutePath}`);

        if (!fs.existsSync(absolutePath)) {
            bridgeLog('error', `Archivo no encontrado: ${absolutePath}`);
            return res.status(404).json({ error: `Archivo no encontrado: ${absolutePath}` });
        }

        const fileStats = fs.statSync(absolutePath);
        bridgeLog('debug', `Archivo existe. Tamaño: ${fileStats.size} bytes`);

        const mediaBuffer = fs.readFileSync(absolutePath);
        const ext = path.extname(absolutePath).toLowerCase();
        let mediaObj = {};

        if (['.jpg', '.jpeg', '.png'].includes(ext)) {
            mediaObj = { image: mediaBuffer };
            bridgeLog('debug', `Tipo detectado: imagen (${ext})`);
        } else if (['.mp4', '.mov', '.3gp'].includes(ext)) {
            mediaObj = { video: mediaBuffer };
            bridgeLog('debug', `Tipo detectado: video (${ext})`);
        } else {
            bridgeLog('error', `Extensión no soportada: ${ext}`);
            return res.status(400).json({ error: `Extensión no soportada para estado: ${ext}` });
        }

        if (caption) mediaObj.caption = caption;

        // POST /status  → publicar estado/historia de WhatsApp
        const broadcastMasivo = req.body.broadcastMasivo === true || req.body.broadcastMasivo === 'true';

        if (broadcastMasivo) {
            bridgeLog('info', `⚡ MODO BROADCAST MASIVO ACTIVO: Publicando estado para toda la agenda sin filtrar...`);
            const sentStatus = await sock.sendMessage(
                'status@broadcast',
                mediaObj
            );
            const statusId = sentStatus?.key?.id || 'unknown';
            bridgeLog('info', `Estado masivo enviado exitosamente. ID: ${statusId}`);
            return res.json({
                success: true,
                statusId,
                contacts_notified: -1, // -1 representa broadcast a toda la agenda
                mode: 'masivo'
            });
        }

        // ── IMPLEMENTACIÓN: Cascada de Destinatarios de 3 Niveles ──
        let statusJidList = [];
        
        // Rutas persistentes comunes en C:\FerrariDB\usuarios\<usuario>\
        const persistentGoogleContacts = path.join('C:', 'FerrariDB', 'usuarios', usuario, 'google_contacts.json');
        const persistentCrmContacts = path.join('C:', 'FerrariDB', 'usuarios', usuario, 'crm_recent_contacts.json');
        
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
            bridgeLog('error', `No se encontró archivo de agenda o está vacío para ${usuario}`);
            return res.status(400).json({ error: 'Debés subir la agenda de Google Contacts (.vcf) para publicar en WhatsApp.' });
        }

        // --- PASO 1: Contactos del CRM a los que les enviamos comunicaciones ---
        let crmContacts = [];
        if (fs.existsSync(persistentCrmContacts)) {
            try {
                const rawCrm = JSON.parse(fs.readFileSync(persistentCrmContacts, 'utf8'));
                crmContacts = rawCrm.filter(jid => googleContactsSet.has(jid)); // Asegurar que estén en la agenda
                bridgeLog('info', `Paso 1: Encontrados ${crmContacts.length} contactos del CRM que están agendados.`);
            } catch(e) {
                bridgeLog('error', `Error leyendo crm_recent_contacts.json: ${e.message}`);
            }
        }

        // Agregar los del Paso 1 al JidList
        crmContacts.forEach(jid => {
            if (!statusJidList.includes(jid)) statusJidList.push(jid);
        });

        // --- PASO 2: Chats de WhatsApp directos y reales (enviados fromMe) ---
        if (statusJidList.length < 250) {
            let directChats = {};
            if (fs.existsSync(directChatsFile)) {
                try { directChats = JSON.parse(fs.readFileSync(directChatsFile, 'utf8')); } catch(e){}
            }

            // Ordenar por última charla real saliente
            const paso2Contacts = Object.entries(directChats)
                .filter(([jid]) => googleContactsSet.has(jid))
                .sort((a, b) => b[1] - a[1])
                .map(([jid]) => jid);

            bridgeLog('info', `Paso 2: Encontrados ${paso2Contacts.length} chats reales de WhatsApp con envíos.`);
            for (const jid of paso2Contacts) {
                if (statusJidList.length >= 250) break;
                if (!statusJidList.includes(jid)) {
                    statusJidList.push(jid);
                }
            }
        }

        // --- PASO 3: Completar con contactos del mapa LID local aleatorios ---
        if (statusJidList.length < 250) {
            const extraNeeded = 250 - statusJidList.length;
            bridgeLog('warn', `Cupo incompleto (${statusJidList.length}/250). Completando Paso 3 con ${extraNeeded} contactos aleatorios de la agenda cruzados con LIDs.`);

            // Cargar LIDs locales de la sesión
            let sessionLids = [];
            try {
                const files = fs.readdirSync(sessionDir);
                const lidFiles = files.filter(f => f.startsWith('lid-mapping-') && f.endsWith('_reverse.json'));
                lidFiles.forEach(file => {
                    try {
                        const raw = fs.readFileSync(path.join(sessionDir, file), 'utf8').trim();
                        if (raw) {
                            const phone = JSON.parse(raw);
                            if (phone) sessionLids.push(`${phone}@s.whatsapp.net`);
                        }
                    } catch(e){}
                });
            } catch(e){}

            // Cruzar con Google Contacts
            const paso3Pool = sessionLids.filter(jid => googleContactsSet.has(jid) && !statusJidList.includes(jid));
            
            // Mezclar de forma aleatoria (Fisher-Yates)
            for (let i = paso3Pool.length - 1; i > 0; i--) {
                const j = Math.floor(Math.random() * (i + 1));
                [paso3Pool[i], paso3Pool[j]] = [paso3Pool[j], paso3Pool[i]];
            }

            bridgeLog('info', `Paso 3: Pool de contactos aleatorios de sesión cruzados: ${paso3Pool.length}`);
            for (const jid of paso3Pool) {
                if (statusJidList.length >= 250) break;
                statusJidList.push(jid);
            }
        }

        // Si aún así no alcanzamos 250, completamos directamente con la agenda de Google de forma secuencial
        if (statusJidList.length < 250) {
            bridgeLog('warn', `Cupo incompleto (${statusJidList.length}/250) tras Paso 3. Completando directamente con Google Contacts secuencial.`);
            for (const jid of googleContactsSet) {
                if (statusJidList.length >= 250) break;
                if (!statusJidList.includes(jid)) {
                    statusJidList.push(jid);
                }
            }
        }

        bridgeLog('info', `Selección Finalizada. Total de destinatarios a enviar estado: ${statusJidList.length}`);

        bridgeLog('info', `Enviando a status@broadcast con ${statusJidList.length} JIDs en lista...`);

        const sentStatus = await sock.sendMessage(
            'status@broadcast',
            mediaObj,
            { statusJidList }
        );

        const statusId = sentStatus?.key?.id || 'unknown';
        bridgeLog('info', `Estado enviado exitosamente. ID: ${statusId}`);

        res.json({
            success: true,
            statusId,
            contacts_notified: statusJidList.length,
            mode: 'seguro'
        });

    } catch (err) {
        bridgeLog('error', `Error publicando estado: ${err.message}`, { stack: err.stack?.slice(0, 300) });
        res.status(500).json({
            error: 'Error al publicar estado',
            details: err.message
        });
    }
});

// GET /logs  → últimas líneas del log (solo acceso local)
app.get('/logs', (req, res) => {
    try {
        if (!fs.existsSync(logFile)) return res.json({ lines: [] });
        const content = fs.readFileSync(logFile, 'utf8');
        const lines = content.trim().split('\n').slice(-100);
        res.json({ lines, logFile });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// GET /contacts  → cuántos contactos tiene cargados
app.get('/contacts', (req, res) => {
    res.json({
        count: storedContacts.length,
        sample: storedContacts.slice(0, 5),
    });
});

// GET /logout
app.get('/logout', async (req, res) => {
    try {
        if (sock) await sock.logout();
        connectionStatus = 'disconnected';
        if (fs.existsSync(qrPath)) { try { fs.unlinkSync(qrPath); } catch (e) {} }
        bridgeLog('info', 'Logout ejecutado');
        res.json({ success: true });
    } catch (err) {
        bridgeLog('error', `Error en logout: ${err.message}`);
        res.status(500).json({ error: 'Logout failed', details: err.message });
    }
});

// ── Start ──────────────────────────────────────────────────────────────────
startSock();
app.listen(port, '127.0.0.1', () => {
    bridgeLog('info', `Servidor Express corriendo en http://127.0.0.1:${port}`);
});
