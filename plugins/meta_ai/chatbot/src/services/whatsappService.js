const { default: makeWASocket, useMultiFileAuthState, DisconnectReason, Browsers, fetchLatestBaileysVersion, fetchLatestWaWebVersion } = require('@whiskeysockets/baileys');
const pino = require('pino');
const geminiService = require('./geminiService');
const configService = require('./configService');
const licenseService = require('./licenseService');
const crmService = require('./crmService');
const loggerService = require('./loggerService');
const { loadState, saveState } = require('./persistenceService');
const fs = require('fs');
const path = require('path');
const qrcode = require('qrcode-terminal');

// Maps containing state per agent/username
const activeSockets = new Map();       // username -> socket
const connectionStates = new Map();    // username -> string ('disconnected', 'qr_ready', 'connecting', 'connected')
const qrCodes = new Map();             // username -> base64 or string QR
const allowedLeadsMaps = new Map();    // username -> Set
const leadNamesMaps = new Map();       // username -> Map
const autoModes = new Map();           // username -> boolean
const pendingActivations = new Map();  // username -> Set
const botSendingToMaps = new Map();    // username -> Map
const messageQueuesMaps = new Map();   // username -> Map (phone -> Promise)
const messageBuffersMaps = new Map();  // username -> Map (phone -> buffer)
const contactMaps = new Map();         // username -> Map (jid -> contact)
const licenseStatuses = new Map();     // username -> boolean
const lastMessageTimestampsMaps = new Map(); // username -> Map (jid -> timestamp in seconds)

// Multi-user state extensions for advanced features
const activationBuffersMaps = new Map();         // username -> Map (phone -> array of messages)
const activeChatsLastMessageTimeMaps = new Map(); // username -> Map (phone -> timestamp in ms)
const lidToJidMaps = new Map();                  // username -> Map (LID -> JID)
const vcfContactsMaps = new Map();               // username -> Set (normalized JIDs from VCF/CSV)
const licenseCheckIntervals = new Map();         // username -> Interval ID
const lastLicenseCheckTimes = new Map();         // username -> timestamp in ms

// Helper: Normalización y comparación de números
const cleanPhone = (phone) => {
    if (!phone) return '';
    return phone.toString().replace(/@s\.whatsapp\.net|@lid|@c\.us/g, '').replace(/\D/g, '');
};

const isSamePhone = (p1, p2) => {
    const c1 = cleanPhone(p1);
    const c2 = cleanPhone(p2);
    if (!c1 || !c2) return false;
    if (c1 === c2) return true;
    if (c1.length >= 10 && c2.length >= 10) {
        return c1.slice(-10) === c2.slice(-10);
    }
    return false;
};

// Helper: Normalización de números robusta
const normalizePhone = (phone) => {
    if (!phone) return null;
    let phoneStr = phone.toString().trim();
    if (phoneStr.endsWith('@lid')) {
        return phoneStr;
    }
    
    // Quitar sufijo de whatsapp y cualquier identificador de dispositivo (:0, :1, etc.) antes de limpiar
    phoneStr = phoneStr.split('@')[0].split(':')[0];
    let clean = phoneStr.replace(/\D/g, '');
    
    // Normalización Argentina Avanzada
    if (clean.length === 10) {
        if (clean.startsWith('15')) {
            clean = '54911' + clean.substring(2);
        } else if (clean.startsWith('11') || clean.startsWith('2') || clean.startsWith('3')) {
            clean = '549' + clean;
        }
    } else if (clean.length === 8) {
        clean = '54911' + clean;
    }
    
    // Caso Argentina clásico
    if (clean.startsWith('54') && !clean.startsWith('549') && clean.length === 12) {
        clean = '549' + clean.substring(2);
    }
    
    return `${clean}@s.whatsapp.net`;
};

const resolveToJid = async (username, phone) => {
    if (!phone) return null;
    let target = phone.toString().trim();
    
    if (!lidToJidMaps.has(username)) {
        lidToJidMaps.set(username, new Map());
    }
    const lidToJidMap = lidToJidMaps.get(username);
    const contacts = contactMaps.get(username) || new Map();
    const sock = activeSockets.get(username);
    
    if (target.endsWith('@lid')) {
        // 1. Intentar con caché local
        if (lidToJidMap.has(target)) {
            return normalizePhone(lidToJidMap.get(target));
        }
        
        // 2. Intentar con Baileys nativo usando base de datos de claves (signalRepository)
        if (sock && sock.signalRepository && sock.signalRepository.lidMapping) {
            try {
                const resolved = await sock.signalRepository.lidMapping.getPNForLID(target);
                if (resolved && resolved !== target) {
                    const normalized = normalizePhone(resolved);
                    console.log(`[LID Mapping] [${username}] Resuelto nativamente vía SignalRepository: ${target} -> ${normalized}`);
                    lidToJidMap.set(target, normalized);
                    persistCurrentState(username);
                    return normalized;
                }
            } catch (err) {
                console.error(`[LID Mapping] [${username}] Error al consultar signalRepository:`, err.message);
            }
        }
        
        // 3. Intentar con normalizeLid de Baileys
        if (sock && typeof sock.normalizeLid === 'function') {
            try {
                const resolved = await sock.normalizeLid(target);
                if (resolved && resolved !== target) {
                    const normalized = normalizePhone(resolved);
                    lidToJidMap.set(target, normalized);
                    persistCurrentState(username);
                    return normalized;
                }
            } catch {}
        }
        
        // 4. Fallback: Buscar en contactos guardados
        for (const [jid, contact] of contacts.entries()) {
            if (contact.lid === target || jid === target) {
                const normalized = normalizePhone(jid);
                lidToJidMap.set(target, normalized);
                persistCurrentState(username);
                return normalized;
            }
        }
    }
    
    return normalizePhone(target);
};

const resolveChatId = async (username, to) => {
    return resolveToJid(username, to);
};

const persistCurrentState = (username) => {
    const allowedLeads = allowedLeadsMaps.get(username) || new Set();
    const leadNames = leadNamesMaps.get(username) || new Map();
    const autoMode = autoModes.get(username) || false;
    const activeChatsLastMessageTime = activeChatsLastMessageTimeMaps.get(username) || new Map();
    const lidToJidMap = lidToJidMaps.get(username) || new Map();
    
    // Build human intervention map from geminiService status map for this agent
    const humanIntervention = {};
    allowedLeads.forEach(phone => {
        humanIntervention[phone] = geminiService.getHumanInterventionStatus(username, phone);
    });

    saveState(username, {
        allowedLeads,
        leadNames,
        humanIntervention,
        autoMode,
        activeChatsLastMessageTime,
        lidToJidMap
    });
};

const getContactsFilePath = (username) => {
    const configsDir = path.join(__dirname, '../../configs');
    if (!fs.existsSync(configsDir)) {
        fs.mkdirSync(configsDir, { recursive: true });
    }
    return path.join(configsDir, `contacts_store_${username}.json`);
};

const loadContacts = (username) => {
    const contacts = contactMaps.get(username);
    const lidToJidMap = lidToJidMaps.get(username);
    const contactsFile = getContactsFilePath(username);
    if (!contacts) return;
    try {
        if (fs.existsSync(contactsFile)) {
            const raw = fs.readFileSync(contactsFile, 'utf-8');
            const data = JSON.parse(raw);
            if (Array.isArray(data)) {
                for (const c of data) {
                    if (c && c.id) {
                        contacts.set(c.id, c);
                        if (c.lid && lidToJidMap) {
                            lidToJidMap.set(c.lid, c.id);
                        }
                    }
                }
                console.log(`[Persistencia] [${username}] ${contacts.size} contactos cargados desde ${contactsFile}`);
            }
        }
    } catch (error) {
        console.error(`[Persistencia] [${username}] Error al cargar contactos:`, error.message);
    }
};

const saveContacts = (username) => {
    const contacts = contactMaps.get(username);
    const contactsFile = getContactsFilePath(username);
    if (!contacts) return;
    try {
        const serializable = Array.from(contacts.values());
        fs.writeFileSync(contactsFile, JSON.stringify(serializable, null, 2), 'utf-8');
    } catch (error) {
        console.error(`[Persistencia] [${username}] Error al guardar contactos:`, error.message);
    }
};

const loadVcfContacts = (username) => {
    if (!vcfContactsMaps.has(username)) {
        vcfContactsMaps.set(username, new Set());
    }
    const vcfContacts = vcfContactsMaps.get(username);
    const vcfPath = path.join(__dirname, '../../configs/', `contacts_${username}.vcf`);
    try {
        if (fs.existsSync(vcfPath)) {
            vcfContacts.clear();
            const content = fs.readFileSync(vcfPath, 'utf-8');
            const lines = content.split(/\r?\n/);
            for (let line of lines) {
                line = line.trim();
                if (line.toUpperCase().startsWith('TEL')) {
                    const colonIdx = line.indexOf(':');
                    if (colonIdx !== -1) {
                        const rawNum = line.substring(colonIdx + 1).trim();
                        const cleanNum = rawNum.replace(/\D/g, '');
                        if (cleanNum.length >= 8) {
                            const normalized = normalizePhone(cleanNum);
                            if (normalized) {
                                vcfContacts.add(normalized);
                            }
                        }
                    }
                }
            }
            console.log(`[VCF Store] [${username}] ${vcfContacts.size} contactos cargados y normalizados desde ${vcfPath}`);
        }
    } catch (error) {
        console.error(`[VCF Store] [${username}] Error al cargar contactos VCF:`, error.message);
    }
};

const parseCSVRow = (text) => {
    const result = [];
    let insideQuote = false;
    let entry = '';
    for (let i = 0; i < text.length; i++) {
        const char = text[i];
        if (char === '"') {
            insideQuote = !insideQuote;
        } else if (char === ',' && !insideQuote) {
            result.push(entry);
            entry = '';
        } else {
            entry += char;
        }
    }
    result.push(entry);
    return result;
};

const loadCsvContacts = (username) => {
    if (!vcfContactsMaps.has(username)) {
        vcfContactsMaps.set(username, new Set());
    }
    const vcfContacts = vcfContactsMaps.get(username);
    const csvPaths = [
        path.join(__dirname, '../../configs/', `contacts_${username}.csv`),
        path.join(__dirname, '../../configs/', `contacts_${username}(1).csv`)
    ];
    
    let pathFound = null;
    for (const p of csvPaths) {
        if (fs.existsSync(p)) {
            pathFound = p;
            break;
        }
    }
    
    if (!pathFound) return;
    
    try {
        const content = fs.readFileSync(pathFound, 'utf-8');
        const lines = content.split(/\r?\n/);
        if (lines.length < 2) return;
        
        const headers = parseCSVRow(lines[0]);
        const phoneValueIndexes = [];
        for (let i = 0; i < headers.length; i++) {
            const h = headers[i].trim().toLowerCase();
            if (h.startsWith('phone ') && h.endsWith('value')) {
                phoneValueIndexes.push(i);
            }
        }
        
        let loadedCount = 0;
        for (let i = 1; i < lines.length; i++) {
            const line = lines[i].trim();
            if (!line) continue;
            const row = parseCSVRow(line);
            for (const idx of phoneValueIndexes) {
                if (row[idx]) {
                    const rawPhone = row[idx].trim();
                    const cleanNum = rawPhone.replace(/\D/g, '');
                    if (cleanNum.length >= 8) {
                        const normalized = normalizePhone(cleanNum);
                        if (normalized) {
                            vcfContacts.add(normalized);
                            loadedCount++;
                        }
                    }
                }
            }
        }
        console.log(`[CSV Store] [${username}] ${loadedCount} teléfonos leídos. Total contactos en set estático: ${vcfContacts.size} (desde ${path.basename(pathFound)})`);
    } catch (error) {
        console.error(`[CSV Store] [${username}] Error al cargar contactos CSV:`, error.message);
    }
};

const reloadStaticContacts = (username) => {
    loadVcfContacts(username);
    loadCsvContacts(username);
    const vcfContacts = vcfContactsMaps.get(username);
    return vcfContacts ? vcfContacts.size : 0;
};

const getAdminPhone = (username) => {
    const config = configService.loadConfig(username);
    let phone = config.credentials?.adminPhone || process.env.ADMIN_PHONE;
    if (phone && !phone.endsWith('@s.whatsapp.net')) {
        phone = normalizePhone(phone);
    }
    return phone;
};

// humanDelay per agent
const humanDelay = async (username, to, text = '') => {
    const config = configService.loadConfig(username);
    const minMs = (config.system?.humanDelay?.min ?? 4) * 1000;
    const maxMs = (config.system?.humanDelay?.max ?? 7) * 1000;
    
    // Si hay texto, calcular tiempo proporcional de tipeo (35ms por carácter) con jitter aleatorio (±500ms)
    let delayTime;
    if (text) {
        const proportionalMs = text.length * 35;
        const jitter = Math.floor(Math.random() * 1000) - 500;
        delayTime = Math.min(Math.max(proportionalMs + jitter, minMs), maxMs);
    } else {
        delayTime = Math.floor(Math.random() * (maxMs - minMs + 1)) + minMs;
    }

    const sock = activeSockets.get(username);
    let resolvedId = to;
    if (to.endsWith('@lid') && sock && sock.signalRepository && sock.signalRepository.lidMapping) {
        try {
            const resolved = await sock.signalRepository.lidMapping.getPNForLID(to);
            if (resolved) resolvedId = resolved;
        } catch {}
    } else {
        resolvedId = await resolveChatId(username, to);
    }

    if (sock && resolvedId) {
        try {
            await sock.sendPresenceUpdate('composing', resolvedId);
        } catch (e) {
            console.warn(`[WhatsApp] [${username}] No se pudo enviar composing a ${resolvedId}:`, e.message);
        }
    }

    // Espera del delay garantizada siempre
    await new Promise(resolve => setTimeout(resolve, delayTime));

    if (sock && resolvedId) {
        try {
            await sock.sendPresenceUpdate('paused', resolvedId);
        } catch (e) {
            // Ignorar silenciosamente
        }
    }
};

const botSend = async (username, to, text) => {
    const resolvedJid = await resolveToJid(username, to);
    if (!resolvedJid) return;
    const cleanNum = cleanPhone(resolvedJid);
    if (!botSendingToMaps.has(username)) {
        botSendingToMaps.set(username, new Map());
    }
    const botSendingTo = botSendingToMaps.get(username);
    botSendingTo.set(cleanNum, Date.now());

    try {
        await humanDelay(username, resolvedJid, text);
        const sock = activeSockets.get(username);
        if (sock && resolvedJid) {
            const result = await sock.sendMessage(resolvedJid, { text });
            if (result && result.key && result.key.remoteJid) {
                const sentJid = result.key.remoteJid;
                if (sentJid.endsWith('@lid') && resolvedJid.endsWith('@s.whatsapp.net')) {
                    if (!lidToJidMaps.has(username)) {
                        lidToJidMaps.set(username, new Map());
                    }
                    const lidToJidMap = lidToJidMaps.get(username);
                    console.log(`[LID Mapping] [${username}] Mapeando ${sentJid} -> ${resolvedJid} al enviar mensaje`);
                    lidToJidMap.set(sentJid, resolvedJid);
                    persistCurrentState(username);
                }
            }
        }
    } finally {
        botSendingTo.set(cleanNum, Date.now());
        setTimeout(() => {
            if (botSendingTo.get(cleanNum) && Date.now() - botSendingTo.get(cleanNum) >= 15000) {
                botSendingTo.delete(cleanNum);
            }
        }, 15000);
    }
};

const queueMessage = (username, phone, task) => {
    const cleanPhone = phone.replace(/\D/g, '');
    if (!messageQueuesMaps.has(username)) {
        messageQueuesMaps.set(username, new Map());
    }
    const messageQueues = messageQueuesMaps.get(username);
    const previous = messageQueues.get(cleanPhone) || Promise.resolve();
    const next = previous.then(() => task());
    messageQueues.set(cleanPhone, next);
    
    next.finally(() => {
        if (messageQueues.get(cleanPhone) === next) {
            messageQueues.delete(cleanPhone);
        }
    });
    return next;
};

const activateLeadQueue = [];
let isProcessingActivateQueue = false;

const processActivateQueue = async () => {
    if (isProcessingActivateQueue || activateLeadQueue.length === 0) return;
    isProcessingActivateQueue = true;
    while (activateLeadQueue.length > 0) {
        const item = activateLeadQueue.shift();
        try {
            await executeActivateLead(item.username, item.targetPhoneRaw, item.targetName, item.forcePathId);
        } catch (e) {
            console.error(`[Bot] [${item.username}] Error en cola de activación de lead:`, e);
        }
        if (activateLeadQueue.length > 0) {
            const cooldown = Math.floor(Math.random() * (120000 - 60000 + 1)) + 60000;
            console.log(`[Bot] [${item.username}] Enfriamiento anti-detección: esperando ${(cooldown / 1000).toFixed(0)}s antes de activar el siguiente lead...`);
            await new Promise(res => setTimeout(res, cooldown));
        }
    }
    isProcessingActivateQueue = false;
};

const activateLead = async (username, targetPhoneRaw, targetName, forcePathId = null) => {
    activateLeadQueue.push({ username, targetPhoneRaw, targetName, forcePathId });
    processActivateQueue();
};

const executeActivateLead = async (username, targetPhoneRaw, targetName, forcePathId = null) => {
    const targetPhone = await resolveToJid(username, targetPhoneRaw);
    const config = configService.loadConfig(username);

    if (!pendingActivations.has(username)) pendingActivations.set(username, new Set());
    if (!leadNamesMaps.has(username)) leadNamesMaps.set(username, new Map());
    if (!allowedLeadsMaps.has(username)) allowedLeadsMaps.set(username, new Set());
    if (!activationBuffersMaps.has(username)) activationBuffersMaps.set(username, new Map());

    const pendingActivation = pendingActivations.get(username);
    const leadNames = leadNamesMaps.get(username);
    const allowedLeads = allowedLeadsMaps.get(username);
    const activationBuffers = activationBuffersMaps.get(username);

    pendingActivation.add(targetPhone);
    leadNames.set(targetPhone, targetName);
    if (!activationBuffers.has(targetPhone)) {
        activationBuffers.set(targetPhone, []);
    }

    loggerService.writeLog(username, 'SYSTEM', targetPhone, `Iniciando activación de Lead (Cola). Nombre: "${targetName}", Path: ${forcePathId || 'ninguno'}`);

    let mensajeA = "";
    let mensajeB = "";
    let skipWelcome = false;

    if (forcePathId) {
        const matchedPath = (config.paths || []).find(p => p.id === forcePathId);
        if (matchedPath) {
            mensajeA = matchedPath.welcomeMessageA || "";
            mensajeB = matchedPath.welcomeMessageB || "";
            skipWelcome = matchedPath.skipWelcome || false;
        }
    }

    if (!mensajeA) mensajeA = config.personality?.globalGreeting || "¡Hola! 👋";
    if (!mensajeB && !forcePathId) {
        mensajeB = config.personality?.initialQuestion || "¿En qué puedo ayudarte?";
    }

    mensajeA = mensajeA.replace('{name}', targetName);
    if (mensajeB) {
        mensajeB = mensajeB.replace('{name}', targetName);
    }

    geminiService.preInitializeChat(username, targetPhone, targetName, mensajeA, mensajeB || "", skipWelcome, forcePathId);

    const finalizeActivation = async (defaultMsg) => {
        allowedLeads.add(targetPhone);
        pendingActivation.delete(targetPhone);

        const matchedPath = forcePathId ? (config.paths || []).find(p => p.id === forcePathId) : null;
        const isPathOnlyGreet = matchedPath?.onlyGreet || false;

        if (isPathOnlyGreet) {
            geminiService.markHumanIntervention(username, targetPhone);
        }

        persistCurrentState(username);

        const buffered = activationBuffers.get(targetPhone) || [];
        activationBuffers.delete(targetPhone);
        const combined = buffered.join('\n\n');

        loggerService.writeLog(username, 'SYSTEM', targetPhone, `Lead activado con éxito. Procesando buffer de mensajes (${buffered.length} acumulados).`);

        crmService.sendLeadToCRM(username, {
            nombre: targetName,
            telefono: targetPhone,
            mensajeOriginal: combined || defaultMsg
        }).catch(e => console.error('[CRM] Error en llamada crmService:', e));

        if (combined) {
            loggerService.writeLog(username, 'SYSTEM', targetPhone, `Procesando consulta capturada durante activación: "${combined}"`);
            setTimeout(async () => {
                try {
                    if (isPathOnlyGreet) {
                        console.log(`[Bot] [${username}] Ignorando consulta de buffer en activación por Only Greet en el path ${forcePathId}`);
                        return;
                    }
                    const aiResponse = await geminiService.processIncomingMessage(username, targetPhone, combined, targetName);
                    if (aiResponse) {
                        await botSend(username, targetPhone, aiResponse);
                        
                        // Actualizar timestamp
                        const activeChatsLastMessageTime = activeChatsLastMessageTimeMaps.get(username);
                        if (activeChatsLastMessageTime) {
                            activeChatsLastMessageTime.set(targetPhone, Date.now());
                            persistCurrentState(username);
                        }
                    }
                } catch (err) {
                    console.error("[Bot] Error procesando mensaje de buffer:", err.message);
                }
            }, 1000);
        }
    };

    if (skipWelcome) {
        loggerService.writeLog(username, 'SYSTEM', targetPhone, `Lead ${targetPhone} (${targetName}) pre-inicializado con skipWelcome activo.`);
        await finalizeActivation("[Lead ingresó por campaña con auto-saludo desactivado]");
    } else {
        await botSend(username, targetPhone, mensajeA);

        if (mensajeB) {
            setTimeout(async () => {
                try {
                    const buffered = activationBuffers.get(targetPhone) || [];
                    if (buffered.length > 0) {
                        console.log(`[Bot] [${username}] Omitiendo Mensaje B para ${targetPhone} porque el cliente ya envió un mensaje.`);
                        loggerService.writeLog(username, 'SYSTEM', targetPhone, `Omitiendo Mensaje B de bienvenida porque el cliente ya respondió.`);
                    } else {
                        await botSend(username, targetPhone, mensajeB);
                        console.log(`[Bot] [${username}] Mensaje B enviado a ${targetPhone}.`);
                    }
                } catch (e) {
                    console.error(`[Bot] [${username}] Error enviando mensaje B:`, e);
                } finally {
                    await finalizeActivation("");
                }
            }, 3500);
        } else {
            await finalizeActivation("");
        }
    }
};

const getMessageText = (msg) => {
    if (!msg.message) return "";
    const messageContent = msg.message.ephemeralMessage?.message || 
                           msg.message.viewOnceMessage?.message || 
                           msg.message.viewOnceMessageV2?.message || 
                           msg.message;
    
    const type = Object.keys(messageContent)[0];
    if (type === 'conversation') return messageContent.conversation;
    if (type === 'extendedTextMessage') return messageContent.extendedTextMessage.text;
    if (type === 'imageMessage') return messageContent.imageMessage.caption || "";
    if (type === 'videoMessage') return messageContent.videoMessage.caption || "";
    return "";
};

const getMessageType = (msg) => {
    if (!msg.message) return "chat";
    const messageContent = msg.message.ephemeralMessage?.message || 
                           msg.message.viewOnceMessage?.message || 
                           msg.message.viewOnceMessageV2?.message || 
                           msg.message;
    const type = Object.keys(messageContent)[0];
    if (type === 'imageMessage') return 'image';
    if (type === 'videoMessage') return 'video';
    if (type === 'audioMessage') return 'audio';
    if (type === 'documentMessage') return 'document';
    if (type === 'locationMessage') return 'location';
    if (type === 'contactMessage') return 'vcard';
    return 'chat';
};

const initialize = async (username) => {
    const user = username || 'default';
    
    // Close existing socket for the user if it exists
    if (activeSockets.has(user)) {
        try {
            activeSockets.get(user).end();
        } catch {}
    }

    const sessionDir = path.join(__dirname, `../../.baileys_auth_${user}`);
    const { state, saveCreds } = await useMultiFileAuthState(sessionDir);

    // Initialize map entries for this user
    if (!leadNamesMaps.has(user)) leadNamesMaps.set(user, new Map());
    if (!allowedLeadsMaps.has(user)) allowedLeadsMaps.set(user, new Set());
    if (!botSendingToMaps.has(user)) botSendingToMaps.set(user, new Map());
    if (!messageBuffersMaps.has(user)) messageBuffersMaps.set(user, new Map());
    if (!contactMaps.has(user)) contactMaps.set(user, new Map());
    if (!lastMessageTimestampsMaps.has(user)) lastMessageTimestampsMaps.set(user, new Map());
    if (!activationBuffersMaps.has(user)) activationBuffersMaps.set(user, new Map());
    if (!activeChatsLastMessageTimeMaps.has(user)) activeChatsLastMessageTimeMaps.set(user, new Map());
    if (!lidToJidMaps.has(user)) lidToJidMaps.set(user, new Map());

    const allowedLeads = allowedLeadsMaps.get(user);
    const leadNames = leadNamesMaps.get(user);
    const contacts = contactMaps.get(user);
    const activeChatsLastMessageTime = activeChatsLastMessageTimeMaps.get(user);
    const lidToJidMap = lidToJidMaps.get(user);

    // Load saved state
    const savedState = loadState(user);
    (savedState.allowedLeads || []).forEach(phone => allowedLeads.add(normalizePhone(phone)));
    Object.entries(savedState.leadNames || {}).forEach(([phone, name]) => leadNames.set(normalizePhone(phone), name));
    autoModes.set(user, savedState.autoMode || false);

    // Restore activeChatsLastMessageTime
    Object.entries(savedState.activeChatsLastMessageTime || {}).forEach(([phone, time]) => {
        activeChatsLastMessageTime.set(normalizePhone(phone), Number(time));
    });

    // Restore lidToJidMap
    if (savedState.lidToJidMap) {
        Object.entries(savedState.lidToJidMap).forEach(([lid, jid]) => {
            lidToJidMap.set(lid, jid);
        });
    }

    // Restore human interventions
    Object.entries(savedState.humanIntervention || {}).forEach(([phone, val]) => {
        if (val) geminiService.markHumanIntervention(user, normalizePhone(phone));
    });

    // Load contacts cache and static contacts
    loadContacts(user);
    reloadStaticContacts(user);

    console.log(`[WhatsApp] Inicializando sesión para el agente: ${user}`);
    loggerService.writeLog(user, 'SYSTEM', null, `Inicializando sesión para el agente: ${user}`);
    connectionStates.set(user, 'connecting');

    // Obtener la versión de WhatsApp Web compatible actualmente
    let version = [2, 3000, 1034074495]; // fallback estable conocido
    try {
        const waVersion = await fetchLatestWaWebVersion();
        if (waVersion && Array.isArray(waVersion.version)) {
            version = waVersion.version;
            console.log(`[WhatsApp] [${user}] Versión de WA Web obtenida: ${version.join('.')}`);
        }
    } catch (e) {
        console.warn(`[WhatsApp] [${user}] No se pudo obtener la versión de WA Web, usando fallback ${version.join('.')}: ${e.message}`);
    }

    const sock = makeWASocket({
        auth: state,
        version,
        browser: ['Ubuntu', 'Chrome', '20.0.04'],
        logger: pino({ level: 'silent' }),
        printQRInTerminal: false,
        markOnlineOnConnect: false,
        syncFullHistory: false
    });

    activeSockets.set(user, sock);

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('contacts.upsert', (newContacts) => {
        for (const contact of newContacts) {
            contacts.set(contact.id, contact);
            if (contact.id && contact.lid) {
                lidToJidMap.set(contact.lid, contact.id);
            }
        }
        saveContacts(user);
    });

    sock.ev.on('contacts.update', (updates) => {
        let changed = false;
        for (const update of updates) {
            if (contacts.has(update.id)) {
                contacts.set(update.id, { ...contacts.get(update.id), ...update });
                const updatedContact = contacts.get(update.id);
                if (updatedContact.id && updatedContact.lid) {
                    lidToJidMap.set(updatedContact.lid, updatedContact.id);
                }
                changed = true;
            }
        }
        if (changed) saveContacts(user);
    });

    sock.ev.on('messaging-history.set', ({ contacts: newContacts, messages: newMessages }) => {
        if (newContacts) {
            for (const contact of newContacts) {
                contacts.set(contact.id, contact);
                if (contact.id && contact.lid) {
                    lidToJidMap.set(contact.lid, contact.id);
                }
            }
            saveContacts(user);
        }
        if (newMessages) {
            const lastMessageTimestamps = lastMessageTimestampsMaps.get(user);
            if (lastMessageTimestamps) {
                for (const msg of newMessages) {
                    const jid = msg.key?.remoteJid;
                    const timestamp = msg.messageTimestamp ? Number(msg.messageTimestamp) : null;
                    if (jid && timestamp) {
                        const current = lastMessageTimestamps.get(jid) || 0;
                        if (timestamp > current) {
                            lastMessageTimestamps.set(jid, timestamp);
                        }
                    }
                }
            }
        }
    });

    sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (qr) {
            connectionStates.set(user, 'qr_ready');
            qrCodes.set(user, qr);
            console.log(`[WhatsApp] [${user}] QR de vinculación generado.`);
            loggerService.writeLog(user, 'SYSTEM', null, 'Código QR de WhatsApp generado y listo para escanear.');
        }

        if (connection === 'close') {
            const error = lastDisconnect?.error;
            const statusCode = error?.output?.statusCode;
            const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
            console.log(`[WhatsApp] [${user}] Conexión cerrada. Reconectando: ${shouldReconnect} (${statusCode || 'no-error'})`);
            loggerService.writeLog(user, 'SYSTEM', null, `Conexión cerrada. Reconectando: ${shouldReconnect} (código error: ${statusCode || 'no-error'})`);
            connectionStates.set(user, 'disconnected');
            qrCodes.delete(user);

            // Si el error es 428 (Connection Replaced / Rate Limit), pausamos para liberar el socket antes de reintentar
            if (statusCode === 428 || statusCode === 408) {
                console.warn(`[WhatsApp] [${user}] Detectado error ${statusCode} (Reemplazo/Timeout). Limpiando credenciales y aplicando enfriamiento de 15s...`);
                try {
                    fs.rmSync(sessionDir, { recursive: true, force: true });
                } catch (e) {}
                setTimeout(() => initialize(user), 15000);
                return;
            }

            // Si el error indica sesión corrupta/inválida, removemos la carpeta de sesión para forzar un QR limpio
            const isSessionBad = statusCode === DisconnectReason.badSession || statusCode === 401 || statusCode === 500;
            if (isSessionBad) {
                console.warn(`[WhatsApp] [${user}] Sesión corrupta o inválida (código: ${statusCode}). Eliminando credenciales para forzar QR limpio...`);
                loggerService.writeLog(user, 'SYSTEM', null, `Sesión corrupta o inválida (código: ${statusCode}). Eliminando credenciales.`);
                try {
                    fs.rmSync(sessionDir, { recursive: true, force: true });
                } catch (e) {
                    console.error("Error al borrar directorio de sesión de Baileys:", e);
                }
            }

            const hasCreds = fs.existsSync(path.join(sessionDir, 'creds.json'));
            if (shouldReconnect && hasCreds) {
                // Aplicamos un retraso de 10s para evitar saturación y spam en el log de reconexiones solo si la sesión existe
                setTimeout(() => initialize(user), 10000);
            } else {
                console.log(`[WhatsApp] [${user}] Sin credenciales activas o sesión desvinculada. Deteniendo bucle automático de ClaudIA.`);
            }
        } else if (connection === 'open') {
            connectionStates.set(user, 'connected');
            qrCodes.delete(user);
            console.log(`[WhatsApp] [${user}] ✅ Conectado y operativo.`);
            loggerService.writeLog(user, 'SYSTEM', null, `✅ WhatsApp conectado. Modo automático: ${autoModes.get(user) ? 'ON' : 'OFF'}`);

            await checkLicenseAndAlert(user);
            
            const existingInterval = licenseCheckIntervals.get(user);
            if (existingInterval) {
                clearInterval(existingInterval);
            }
            const newInterval = setInterval(() => checkLicenseAndAlert(user), 28800000); // 8 horas
            licenseCheckIntervals.set(user, newInterval);
        }
    });

    const checkLicenseAndAlert = async (username, force = false) => {
        const now = Date.now();
        const EIGHT_HOURS = 8 * 60 * 60 * 1000;
        const lastCheck = lastLicenseCheckTimes.get(username) || 0;
        
        if (!force && (now - lastCheck < EIGHT_HOURS)) {
            return;
        }

        const config = configService.loadConfig(username);
        const licenseKey = config.credentials?.licenseKey;
        
        console.log(`[Bot] [${username}] Ejecutando validación de licencia de rutina...`);
        const result = await licenseService.verifyLicense(licenseKey);
        
        if (result.status === 'error') {
            console.warn(`[Bot] [${username}] ⚠️ Error de conexión al validar la licencia. Se mantendrá el estado actual y se reintentará en 10 minutos.`);
            setTimeout(() => checkLicenseAndAlert(username, true), 10 * 60 * 1000);
            return;
        }

        lastLicenseCheckTimes.set(username, now);
        licenseStatuses.set(username, !!result.valid);
        
        if (!result.valid) {
            console.warn(`[Bot] [${username}] ⚠️ LICENCIA INVÁLIDA O EXPIRADA. Pausando respuestas.`);
            loggerService.writeLog(username, 'ERROR', null, `Validación de licencia falló: ${result.message}`);
            try {
                const adminPhone = getAdminPhone(username);
                if (adminPhone) {
                    await sock.sendMessage(adminPhone, { text: `⚠️ *Alerta de Sistema*\nLa licencia de ClaudIA Pro ha expirado o es inválida (Detalle: ${result.message}).\nEl bot se ha pausado por seguridad. Por favor, renová tu licencia desde el Dashboard.` });
                }
            } catch(e) {
                console.error(`[${username}] No se pudo avisar al admin sobre la licencia vencida:`, e.message);
            }
        }
    };

    const processAdminCommands = async (msgObj) => {
        try {
            const text = getMessageText(msgObj).trim();
            if (!text || !text.startsWith('/')) return false;

            const lowerText = text.toLowerCase();
            const adminPhone = getAdminPhone(user);
            const isAuto = autoModes.get(user) || false;

            if (lowerText.startsWith('/bot open ')) {
                const mode = lowerText.substring('/bot open '.length).trim();
                const config = configService.loadConfig(user);
                if(!config.system) config.system = {};
                config.system.openMode = (mode === 'on');
                configService.saveConfig(user, config);
                await sock.sendMessage(adminPhone, { text: `🌐 Modo Abierto: *${config.system.openMode ? 'ON' : 'OFF'}*\n${config.system.openMode ? 'ClaudIA ahora responderá a cualquier persona (que no esté en blacklist).' : 'ClaudIA solo responderá a leads autorizados.'}` });
                return true;
            }

            if (lowerText.startsWith('/bot strangers ')) {
                const mode = lowerText.substring('/bot strangers '.length).trim();
                const config = configService.loadConfig(user);
                if(!config.system) config.system = {};
                config.system.strangersOnly = (mode === 'on');
                configService.saveConfig(user, config);
                await sock.sendMessage(adminPhone, { text: `👤 Modo Solo Desconocidos: *${config.system.strangersOnly ? 'ON' : 'OFF'}*\n${config.system.strangersOnly ? 'ClaudIA solo responderá a números que NO tengas agendados.' : 'ClaudIA responderá a contactos y desconocidos por igual (según el Modo Abierto).'}` });
                return true;
            }

            if (lowerText.startsWith('/bot blacklist ')) {
                const parts = text.substring('/bot blacklist '.length).trim().split(' ');
                const action = parts[0].toLowerCase();
                const phone = await resolveToJid(user, parts[1]);
                
                if (!phone) return true;

                const config = configService.loadConfig(user);
                if (!config.system) config.system = {};
                if (!config.system.blacklist) config.system.blacklist = [];

                if (action === 'add') {
                    if (!config.system.blacklist.includes(phone)) config.system.blacklist.push(phone);
                    await sock.sendMessage(adminPhone, { text: `🚫 *${phone}* agregado a la Blacklist.` });
                } else if (action === 'remove') {
                    config.system.blacklist = config.system.blacklist.filter(p => p !== phone);
                    await sock.sendMessage(adminPhone, { text: `✅ *${phone}* removido de la Blacklist.` });
                }
                
                configService.saveConfig(user, config);
                return true;
            }

            if (lowerText === '/bot status') {
                const config = configService.loadConfig(user);
                const licenseResult = await licenseService.verifyLicense(config.credentials?.licenseKey);
                
                const statusMsg = `📊 *Estado de ClaudIA Pro (${user})*
━━━━━━━━━━━━━━━━━━━━━━━
🤖 *Nombre:* ${config.system?.botName || 'ClaudIA Pro'}
🌐 *Modo:* ${config.system?.mode === 'catalog' ? '📦 Catálogo Inteligente' : '✨ Boutique / Inmobiliaria'}
🔑 *Licencia:* ${licenseResult.valid ? '✅ Activa' : '❌ Inválida/Vencida'}
📦 *Base de Datos:* ${config.catalog?.items?.length || 0} ítems cargados
━━━━━━━━━━━━━━━━━━━━━━━
${isAuto ? '🤖 Modo automático: ✅ ON' : '🤖 Modo automático: ❌ OFF'}`;

                await sock.sendMessage(adminPhone, { text: statusMsg });
                return true;
            }

            if (lowerText === '/bot on') {
                autoModes.set(user, true);
                persistCurrentState(user);
                await sock.sendMessage(adminPhone, { text: `✅ *Modo automático ACTIVADO.*\nCada nuevo lead de Meta Ads será contactado automáticamente por ClaudIA.` });
                return true;
            }

            if (lowerText === '/bot off') {
                autoModes.set(user, false);
                persistCurrentState(user);
                await sock.sendMessage(adminPhone, { text: `❌ *Modo automático DESACTIVADO.*\nSolo recibirás la notificación del lead. Usá \`/bot <telefono> [nombre]\` para activar manualmente.` });
                return true;
            }

            if (lowerText === '/bot help') {
                const statusLine = isAuto ? `Modo automático: ✅ ON` : `Modo automático: ❌ OFF`;
                const MULTI_USER_HELP_MESSAGE = `🤖 *Comandos de ClaudIA (${user})*
━━━━━━━━━━━━━━━━━━━━━━━

*🔁 Modo automático (Meta Ads):*
*/bot ON*  → ClaudIA contacta cada lead nuevo de Ads automáticamente.
*/bot OFF* → Modo manual: solo recibís la notificación.

*👤 Modos de respuesta:*
*/bot open on/off*
  → Activa/desactiva el Modo Abierto (responde a cualquier desconocido).
  Ej: \`/bot open on\`

*/bot strangers on/off*
  → Activa/desactiva el filtro Solo Desconocidos (ignora agendados).
  Ej: \`/bot strangers on\`

*🚫 Blacklist (Lista Negra):*
*/bot blacklist add <telefono>*    → Agrega un número a la blacklist.
*/bot blacklist remove <telefono>* → Quita un número de la blacklist.
  Ej: \`/bot blacklist add 5491155556666\`

*🚀 Activación manual de un lead:*
*/bot <telefono> [nombre]*
  → Activa ClaudIA y envía el saludo inicial.
  Ej: \`/bot 5491112345678 Juan Pérez\`

*▶️ Reanudar conversación existente:*
*/bot continue <telefono> [nombre]*
  → Retoma la charla sin re-enviar el saludo.
  Ej: \`/bot continue 5491112345678 Juan Pérez\`

*🔄 Reinicio completo de un lead:*
*/reset bot <telefono>*
  → Borra el historial y la pausa humana. ClaudIA arranca de cero.

*❓ Información y Ayuda:*
*/bot status* → Muestra el estado actual (Nombre, Modo, Licencia, Catálogo).
*/bot HELP*   → Muestra este mensaje.`;

                await sock.sendMessage(adminPhone, { text: `${MULTI_USER_HELP_MESSAGE}\n\n📊 *Estado actual:* ${statusLine}` });
                return true;
            }

            // Enrutamiento / Activación / Reanudación manual (insensible a mayúsculas para el comando, preservando el caso de los argumentos)
            const isManualAct = lowerText.startsWith('/bot ') && 
                                !lowerText.startsWith('/bot on') && 
                                !lowerText.startsWith('/bot off') && 
                                !lowerText.startsWith('/bot help') &&
                                !lowerText.startsWith('/bot open') &&
                                !lowerText.startsWith('/bot strangers') &&
                                !lowerText.startsWith('/bot blacklist');

            if (isManualAct) {
                const isContinue = lowerText.startsWith('/bot continue ');
                const commandLabelLength = isContinue ? '/bot continue '.length : '/bot '.length;
                const argsStr = text.substring(commandLabelLength).trim();
                const parts = argsStr.split(/\s+/);
                
                const targetPhone = await resolveToJid(user, parts[0]);
                if (!targetPhone) {
                    await sock.sendMessage(adminPhone, { text: '⚠️ Número de teléfono no válido.' });
                    return true;
                }

                let targetName = parts.slice(1).join(' ').trim();
                let inlineMessage = null;
                const pipeIndex = targetName.indexOf(' | ');
                if (pipeIndex !== -1) {
                    inlineMessage = targetName.substring(pipeIndex + 3).trim();
                    targetName = targetName.substring(0, pipeIndex).trim();
                }

                if (!targetName) targetName = leadNames.get(targetPhone) || 'Cliente';

                allowedLeads.add(targetPhone);
                leadNames.set(targetPhone, targetName);

                if (isContinue) {
                    geminiService.resumeChat(user, targetPhone, targetName);
                    await sock.sendMessage(adminPhone, { text: `▶️ Reanudando a *${targetName}* (${targetPhone}).` });
                } else {
                    const config = configService.loadConfig(user);
                    const mensajeA = (config.personality?.globalGreeting || "¡Hola! 👋").replace('{name}', targetName);
                    const mensajeB = config.personality?.initialQuestion || "¿En qué puedo ayudarte?";
                    geminiService.preInitializeChat(user, targetPhone, targetName, mensajeA, mensajeB, true);
                    await sock.sendMessage(adminPhone, { text: `🚀 Activando a *${targetName}* (${targetPhone}).` });
                }
                
                persistCurrentState(user);

                try {
                    let messageToProcess = inlineMessage || null;
                    
                    if (!isContinue) {
                        crmService.sendLeadToCRM(user, {
                            nombre: targetName,
                            telefono: targetPhone,
                            mensajeOriginal: messageToProcess || ""
                        }).catch(e => console.error('[CRM] Error en llamada crmService:', e));
                    }

                    if (messageToProcess && messageToProcess.trim()) {
                        console.log(`[Bot] [${user}] Actuando proactivamente sobre: "${messageToProcess}"`);
                        const aiResponse = await geminiService.processIncomingMessage(user, targetPhone, messageToProcess, targetName);
                        if (aiResponse) {
                            await botSend(user, targetPhone, aiResponse);
                        }
                    } else if (!isContinue) {
                        await sock.sendMessage(adminPhone, { text: `✅ ClaudIA lista para *${targetName}*. Responderá al próximo mensaje.` });
                    }
                } catch (err) {
                    console.error(`[Bot] [${user}] Error en proactividad manual:`, err.message);
                }
                return true;
            }

            if (lowerText.startsWith('/reset bot')) {
                const phoneArg = text.substring('/reset bot'.length).trim();
                let target = phoneArg ? await resolveToJid(user, phoneArg) : null;

                if (target) {
                    geminiService.resetHumanIntervention(user, target);
                    persistCurrentState(user);
                    await sock.sendMessage(adminPhone, { text: `🔄 Bot reiniciado para *${target}*.` });
                }
                return true;
            }

            return false;
        } catch (error) {
            console.error(`[Bot] [${user}] Error procesando comando de admin:`, error);
            return false;
        }
    };

    const handleOutgoingMessage = async (msg) => {
        try {
            const rawReceiver = msg.key.remoteJid;
            if (!rawReceiver) return;

            const receiverJid = await resolveToJid(user, rawReceiver);
            const text = getMessageText(msg).trim();

            let realJid = receiverJid;
            const cleanReceiver = cleanPhone(receiverJid);
            const botSendingTo = botSendingToMaps.get(user);
            if (botSendingTo && (botSendingTo.has(cleanReceiver) || botSendingTo.has(cleanPhone(rawReceiver)))) {
                loggerService.writeLog(user, 'OUTGOING', receiverJid, `ClaudIA: "${text}"`);
                return;
            }

            const adminPhone = getAdminPhone(user);

            if (receiverJid === adminPhone) {
                await processAdminCommands(msg);
                return;
            }

            const wasCommand = await processAdminCommands(msg);
            if (wasCommand) return;

            // EXCEPCIÓN: Saludos automáticos de WhatsApp Business (no pausar IA)
            const textLower = text.toLowerCase();
            const config = configService.loadConfig(user);
            const ignoredTexts = config.system?.ignoredOutgoingTexts || [
                "cómo podemos ayudarte",
                "en qué puedo ayudarte",
                "en qué te puedo ayudar",
                "bienvenido"
            ];
            const isAutoGreeting = ignoredTexts.some(ignored => textLower.includes(ignored.toLowerCase()));

            if (isAutoGreeting) {
                console.log(`[Bot] [${user}] Saludo automático saliente detectado para ${realJid}. Omitiendo pausa de IA.`);
                loggerService.writeLog(user, 'OUTGOING', realJid, `Auto-Respuesta Nativa (Ignorada): "${text}"`);
                return;
            }

            // Registrar hora del último mensaje para conversación previa
            const normalizedReceiver = normalizePhone(receiverJid);
            if (normalizedReceiver) {
                const activeChatsLastMessageTime = activeChatsLastMessageTimeMaps.get(user);
                if (activeChatsLastMessageTime) {
                    activeChatsLastMessageTime.set(normalizedReceiver, Date.now());
                    persistCurrentState(user);
                }
            }

            let isLead = false;
            let matchedLeadPhone = null;

            for (const phone of allowedLeads) {
                if (isSamePhone(phone, realJid) || isSamePhone(phone, receiverJid)) {
                    isLead = true;
                    matchedLeadPhone = phone;
                    break;
                }
            }

            if (isLead && matchedLeadPhone) {
                const alreadyPaused = geminiService.getHumanInterventionStatus(user, matchedLeadPhone) || 
                                      geminiService.getHumanInterventionStatus(user, realJid) ||
                                      geminiService.getHumanInterventionStatus(user, receiverJid);
                if (alreadyPaused) {
                    return;
                }
                
                geminiService.markHumanIntervention(user, matchedLeadPhone);
                geminiService.markHumanIntervention(user, realJid);
                geminiService.markHumanIntervention(user, receiverJid);
                persistCurrentState(user);
                console.log(`[Bot] [${user}] Intervención humana detectada para ${matchedLeadPhone}. IA pausada.`);
                loggerService.writeLog(user, 'OUTGOING', realJid, `Humano (Admin): "${text}"`);
            } else {
                loggerService.writeLog(user, 'OUTGOING', realJid, `Mensaje saliente de la cuenta: "${text}"`);
            }
        } catch (error) {
            console.error("[Bot] Error en handleOutgoingMessage:", error);
        }
    };

    const handleIncomingMessage = async (msg) => {
        const rawSender = msg.key.remoteJid;
        const senderPhone = await resolveToJid(user, rawSender);
        const pushName = msg.pushName || "Cliente";

        const msgType = getMessageType(msg);
        let incomingText = getMessageText(msg);

        if (!senderPhone) return;
        if (geminiService.getHumanInterventionStatus(user, senderPhone)) {
            console.log(`[Bot] [${user}] Ignorado (Intervención humana activa para ${senderPhone})`);
            return;
        }

        const config = configService.loadConfig(user);

        // --- EVITAR AUDIO SI ignoreAudio ESTÁ ACTIVO (Salvo si es campaña de Meta) ---
        if (msgType === 'audio' && config.system?.ignoreAudio) {
            const hasPath = geminiService.hasActivePath(user, senderPhone);
            if (!hasPath) {
                console.log(`[Bot] [${user}] Ignorado (Mensaje de audio y ignoreAudio activo): ${senderPhone}`);
                loggerService.writeLog(user, 'SYSTEM', senderPhone, `Ignorado (Mensaje de audio y ignoreAudio activo)`);
                return;
            }
        }

        // --- INTERCEPTAR SI ONLY GREET ESTÁ ACTIVO ---
        if (config.system?.onlyGreet && !geminiService.hasActivePath(user, senderPhone)) {
            const allowedLeads = allowedLeadsMaps.get(user);
            const isLead = allowedLeads && allowedLeads.has(senderPhone);
            const active = geminiService.isChatActive(user, senderPhone);
            const intervention = geminiService.getHumanInterventionStatus(user, senderPhone);
            if (isLead || active || intervention) {
                console.log(`[Bot] [${user}] Ignorando mensaje de ${senderPhone} (Only Greet activo y ya saludado/procesado).`);
                return;
            }
        }

        // --- TRADUCTOR DE MULTIMEDIA A TEXTO ---
        if (msgType !== 'chat') {
            const mediaTypes = {
                'image': 'una imagen',
                'video': 'un video',
                'audio': 'un audio',
                'document': 'un documento/archivo',
                'location': 'una ubicación',
                'vcard': 'un contacto'
            };
            const typeDesc = mediaTypes[msgType] || 'un archivo';
            
            if (incomingText.trim() === "") {
                incomingText = `[SISTEMA: El usuario envió ${typeDesc} que no podés ver/escuchar directamente. Pedile amablemente que te lo explique en texto o decile que por ahora solo procesás mensajes escritos.]`;
            } else {
                incomingText = `${incomingText} [NOTA: Este mensaje acompaña a ${typeDesc}]`;
            }
        }

        if (incomingText.trim() === senderPhone || incomingText.trim() === senderPhone.split('@')[0]) {
            return;
        }

        const blacklist = (config.system?.blacklist || []).map(n => normalizePhone(n));
        const senderNormalized = normalizePhone(senderPhone);
        
        if (blacklist.includes(senderNormalized)) {
            console.log(`[Bot] [${user}] Ignorado (Blacklist): ${senderPhone}`);
            loggerService.writeLog(user, 'SYSTEM', senderNormalized, `Ignorado (Lista Negra): "${incomingText}"`);
            return;
        }

        // CAPTURA DURANTE ACTIVACIÓN (Evitar condición de carrera)
        const pendingActivation = pendingActivations.get(user);
        if (pendingActivation && pendingActivation.has(senderNormalized)) {
            console.log(`[Bot] [${user}] Capturando mensaje recibido durante activación para ${senderNormalized}: "${incomingText}"`);
            loggerService.writeLog(user, 'INCOMING', senderNormalized, `[ACTIVACIÓN] Capturando mensaje en buffer: "${incomingText}"`);
            const activationBuffers = activationBuffersMaps.get(user);
            if (activationBuffers) {
                if (!activationBuffers.has(senderNormalized)) {
                    activationBuffers.set(senderNormalized, []);
                }
                activationBuffers.get(senderNormalized).push(incomingText);
            }
            return;
        }

        // Registrar mensaje entrante normal
        loggerService.writeLog(user, 'INCOMING', senderNormalized, `${pushName}: "${incomingText}"`);

        let shouldProcess = false;
        let matchedLead = null;
        for (const phone of allowedLeads) {
            if (isSamePhone(phone, senderPhone)) {
                shouldProcess = true;
                matchedLead = phone;
                break;
            }
        }

        let realJid = senderPhone;
        if (!shouldProcess) {
            const sock = activeSockets.get(user);
            if (senderPhone.endsWith('@lid') && sock && typeof sock.normalizeLid === 'function') {
                try {
                    const resolved = await sock.normalizeLid(senderPhone);
                    if (resolved) {
                        realJid = resolved;
                    }
                } catch (err) {
                    console.error(`[WhatsApp] [${user}] Error al normalizar LID ${senderPhone}:`, err);
                }
            }
            for (const phone of allowedLeads) {
                if (isSamePhone(phone, realJid)) {
                    shouldProcess = true;
                    matchedLead = phone;
                    break;
                }
            }
        }

        if (!shouldProcess && config.system?.openMode) {
            const contact = contacts.get(realJid) || contacts.get(senderPhone);
            let isContact = contact && (!!contact.name || !!contact.verifiedName);

            // Double check with uploaded VCF / Google Contacts CSV
            const vcfContacts = vcfContactsMaps.get(user);
            if (!isContact && vcfContacts) {
                if (vcfContacts.has(senderNormalized) || vcfContacts.has(senderPhone) || vcfContacts.has(realJid)) {
                    isContact = true;
                }
            }

            if (config.system?.strangersOnly && isContact) {
                console.log(`[Bot] [${user}] Ignorado (Es contacto agendado/conocido): ${pushName} (${senderPhone})`);
                loggerService.writeLog(user, 'SYSTEM', senderNormalized, `Ignorado (Es contacto agendado y strangersOnly activo)`);
                return;
            }

            // Lógica de revisión de conversación previa si es desconocido
            if (config.system?.checkPreviousChat && sock) {
                try {
                    const lastMessageTimestamp = activeChatsLastMessageTime.get(senderPhone);
                    
                    if (lastMessageTimestamp) {
                        const now = Date.now();
                        const diffHours = (now - lastMessageTimestamp) / (1000 * 60 * 60);
                        const limitHours = config.system?.previousChatHours ?? 24;

                        if (diffHours <= limitHours) {
                            console.log(`[Bot] [${user}] Ignorado (Conversación previa hace ${diffHours.toFixed(1)} hs, menor al límite de ${limitHours} hs): ${pushName} (${senderPhone})`);
                            loggerService.writeLog(user, 'SYSTEM', senderNormalized, `Ignorado (Conversación previa hace ${diffHours.toFixed(1)} hs, menor al límite de ${limitHours} hs)`);
                            return; // Omitir respuesta (Bypass silencioso)
                        } else {
                            console.log(`[Bot] [${user}] Re-activando chat (Silencio expirado tras ${diffHours.toFixed(1)} hs): ${pushName} (${senderPhone})`);
                            loggerService.writeLog(user, 'SYSTEM', senderNormalized, `Re-activando chat (Silencio expirado tras ${diffHours.toFixed(1)} hs)`);
                            geminiService.resetHumanIntervention(user, senderPhone);
                        }
                    }
                } catch (e) {
                    console.warn(`[Bot] [${user}] Error al evaluar conversación previa:`, e.message);
                }
            }

            shouldProcess = true;

            if (shouldProcess) {
                if (config.system?.onlyGreet) {
                    console.log(`[Bot] [${user}] Solo Saludar activo. Iniciando secuencia de saludos genéricos para ${pushName} (${senderPhone}).`);
                    loggerService.writeLog(user, 'SYSTEM', senderNormalized, `Solo Saludar activo. Enviando saludos.`);
                    const mensajeA = (config.personality?.globalGreeting || "¡Hola! 👋").replace('{name}', pushName);
                    const mensajeB = (config.personality?.initialQuestion || "¿En qué puedo ayudarte?").replace('{name}', pushName);
                    geminiService.preInitializeChat(user, senderPhone, pushName, mensajeA, mensajeB, false);
                    await botSend(user, senderPhone, mensajeA);
                    setTimeout(async () => {
                        try {
                            await botSend(user, senderPhone, mensajeB);
                        } catch (e) {
                            console.error(`[Bot] [${user}] Error enviando mensaje B en Solo Saludar:`, e);
                        } finally {
                            allowedLeads.add(senderPhone);
                            allowedLeads.add(realJid);
                            leadNames.set(senderPhone, pushName);
                            leadNames.set(realJid, pushName);
                            activeChatsLastMessageTime.set(senderPhone, Date.now());
                            geminiService.markHumanIntervention(user, senderPhone);
                            geminiService.markHumanIntervention(user, realJid);
                            persistCurrentState(user);
                            crmService.sendLeadToCRM(user, {
                                nombre: pushName,
                                telefono: senderPhone,
                                mensajeOriginal: incomingText
                            }).catch(e => console.error('[CRM] Error en llamada crmService:', e));
                        }
                    }, 2000);
                    return;
                }

                console.log(`[Bot] [${user}] Activando respuesta por MODO ABIERTO para ${pushName} (${senderPhone})`);
                loggerService.writeLog(user, 'SYSTEM', senderNormalized, `Activando respuesta por MODO ABIERTO.`);
                if (!geminiService.isChatActive(user, senderPhone)) {
                    const mensajeA = (config.personality?.globalGreeting || "¡Hola! 👋").replace('{name}', pushName);
                    geminiService.preInitializeChat(user, senderPhone, pushName, mensajeA, "", false);
                    await botSend(user, senderPhone, mensajeA);
                }
                allowedLeads.add(senderPhone);
                allowedLeads.add(realJid);
                leadNames.set(senderPhone, pushName);
                leadNames.set(realJid, pushName);
                
                activeChatsLastMessageTime.set(senderPhone, Date.now());
                persistCurrentState(user);
            }
        }

        if (!shouldProcess) return;

        const messageBuffers = messageBuffersMaps.get(user);
        if (!messageBuffers.has(senderPhone)) {
            messageBuffers.set(senderPhone, { messages: [], timer: null });
        }

        const buffer = messageBuffers.get(senderPhone);
        buffer.messages.push(incomingText);

        if (buffer.timer) clearTimeout(buffer.timer);

        console.log(`[WhatsApp] [${user}] Mensaje agregado al buffer de debouncing para ${senderPhone}.`);

        buffer.timer = setTimeout(() => {
            const finalMessages = buffer.messages;
            messageBuffers.delete(senderPhone);
            const mergedText = finalMessages.join('\n\n');

            console.log(`[WhatsApp] [${user}] Procesando ráfaga acumulada de ${finalMessages.length} mensajes para ${senderPhone}.`);

            queueMessage(user, senderPhone, async () => {
                const leadName = leadNames.get(senderPhone) || "Cliente";
                
                if (geminiService.isFirstIncomingMessage(user, senderPhone)) {
                    crmService.sendLeadToCRM(user, {
                        nombre: leadName,
                        telefono: senderPhone,
                        mensajeOriginal: mergedText
                    }).catch(e => console.error('[CRM] Error en llamada crmService:', e));
                }

                try {
                    const aiResponse = await geminiService.processIncomingMessage(user, senderPhone, mergedText, leadName);
                    if (aiResponse) {
                        await botSend(user, senderPhone, aiResponse);
                        activeChatsLastMessageTime.set(senderPhone, Date.now());
                        persistCurrentState(user);
                    }
                } catch (error) {
                    console.error("[Bot] Error en flujo de IA:", error);
                }
            });
        }, 2000);
    };

    sock.ev.on('messages.upsert', async (upsert) => {
        if (!licenseStatuses.get(user)) return;
        if (upsert.type !== 'notify') return;

        const lastMessageTimestamps = lastMessageTimestampsMaps.get(user);

        for (const msg of upsert.messages) {
            if (!msg.key || !msg.message) continue;
            
            const senderJid = msg.key.remoteJid;
            if (senderJid.endsWith('@g.us') || senderJid === 'status@broadcast') continue;

            if (msg.key.fromMe) {
                if (lastMessageTimestamps) {
                    const timestamp = msg.messageTimestamp ? Number(msg.messageTimestamp) : Math.floor(Date.now() / 1000);
                    lastMessageTimestamps.set(senderJid, timestamp);
                }
                await handleOutgoingMessage(msg);
                continue;
            }

            // Simulación de lectura humana (marcar tilde azul tras 1.5s - 2.5s)
            if (sock && msg.key) {
                const readDelay = Math.floor(Math.random() * 1000) + 1500;
                setTimeout(async () => {
                    try {
                        const currentSock = activeSockets.get(user);
                        if (currentSock) await currentSock.readMessages([msg.key]);
                    } catch {}
                }, readDelay);
            }

            if (lastMessageTimestamps) {
                const previousTimestamp = lastMessageTimestamps.get(senderJid);
                msg.previousTimestamp = previousTimestamp;

                const timestamp = msg.messageTimestamp ? Number(msg.messageTimestamp) : Math.floor(Date.now() / 1000);
                lastMessageTimestamps.set(senderJid, timestamp);
            }

            await handleIncomingMessage(msg);
        }
    });
};

const sendTextMessage = async (username, to, text) => {
    try {
        const sock = activeSockets.get(username);
        if (!sock) throw new Error(`Socket de Baileys para ${username} no está activo`);
        const resolvedId = await resolveChatId(username, to);
        const result = await sock.sendMessage(resolvedId, { text });
        if (result && result.key && result.key.remoteJid) {
            const sentJid = result.key.remoteJid;
            if (sentJid.endsWith('@lid') && resolvedId.endsWith('@s.whatsapp.net')) {
                if (!lidToJidMaps.has(username)) {
                    lidToJidMaps.set(username, new Map());
                }
                const lidToJidMap = lidToJidMaps.get(username);
                console.log(`[LID Mapping] [${username}] Mapeando ${sentJid} -> ${resolvedId} al enviar mensaje de texto`);
                lidToJidMap.set(sentJid, resolvedId);
                persistCurrentState(username);
            }
        }
        return true;
    } catch (error) {
        console.error(`[Bot] [${username}] Error enviando mensaje:`, error);
        throw error;
    }
};

const logout = async (username) => {
    const sock = activeSockets.get(username);
    if (sock) {
        try { sock.end(); } catch {}
        activeSockets.delete(username);
    }
    connectionStates.set(username, 'disconnected');
    qrCodes.delete(username);

    const sessionDir = path.join(__dirname, `../../.baileys_auth_${username}`);
    if (fs.existsSync(sessionDir)) {
        try {
            fs.rmSync(sessionDir, { recursive: true, force: true });
        } catch (e) {
            console.error("Error al borrar directorio de sesión de Baileys:", e);
        }
    }
    return true;
};

const getQR = (username) => qrCodes.get(username) || null;
const getConnectionStatus = (username) => connectionStates.get(username) || 'disconnected';
const isAutoMode = (username) => autoModes.get(username) || false;

const getLeadsStatus = (username) => {
    const allowedLeads = allowedLeadsMaps.get(username) || new Set();
    const leadNames = leadNamesMaps.get(username) || new Map();
    const leads = [];
    
    allowedLeads.forEach(phone => {
        leads.push({
            phone,
            name: leadNames.get(phone) || 'Cliente',
            isPaused: geminiService.getHumanInterventionStatus(username, phone)
        });
    });
    
    return leads;
};

const deleteLead = async (username, phoneRaw) => {
    if (!phoneRaw) return false;
    const allowedLeads = allowedLeadsMaps.get(username);
    const leadNames = leadNamesMaps.get(username);
    if (!allowedLeads) return false;

    const resolved = await resolveToJid(username, phoneRaw);
    const targetPhone = resolved || normalizePhone(phoneRaw);

    geminiService.resetHumanIntervention(username, targetPhone);
    geminiService.resetHumanIntervention(username, phoneRaw);
    allowedLeads.delete(targetPhone);
    allowedLeads.delete(phoneRaw);
    if (leadNames) {
        leadNames.delete(targetPhone);
        leadNames.delete(phoneRaw);
    }
    
    // También borrar de la lista de tiempos de conversación
    const activeChatsLastMessageTime = activeChatsLastMessageTimeMaps.get(username);
    if (activeChatsLastMessageTime) {
        activeChatsLastMessageTime.delete(targetPhone);
        activeChatsLastMessageTime.delete(phoneRaw);
    }
    
    persistCurrentState(username);
    return true;
};

const toggleLeadPause = async (username, phoneRaw, isPaused) => {
    if (!phoneRaw) return false;
    const allowedLeads = allowedLeadsMaps.get(username);
    if (!allowedLeads) return false;

    const resolved = await resolveToJid(username, phoneRaw);
    const targetPhone = resolved || normalizePhone(phoneRaw);

    if (allowedLeads.has(targetPhone) || allowedLeads.has(phoneRaw)) {
        if (isPaused) {
            geminiService.markHumanIntervention(username, targetPhone);
            geminiService.markHumanIntervention(username, phoneRaw);
        } else {
            geminiService.resetHumanIntervention(username, targetPhone);
            geminiService.resetHumanIntervention(username, phoneRaw);
        }
        persistCurrentState(username);
        return true;
    }
    return false;
};

const getActiveSocket = (username) => {
    return activeSockets.get(username || 'GermanMazza');
};

module.exports = {
    initialize,
    sendTextMessage,
    activateLead,
    isAutoMode,
    getLeadsStatus,
    deleteLead,
    toggleLeadPause,
    getConnectionStatus,
    getQR,
    logout,
    reloadStaticContacts,
    getActiveSocket
};
