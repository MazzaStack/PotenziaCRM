require('dotenv').config();
const Module = require('module');
const readline = require('readline');
const originalRequire = Module.prototype.require;

const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout
});

const question = (query) => new Promise((resolve) => rl.question(query, resolve));

// Parse --user and --suite / --interactive arguments
const userIndex = process.argv.indexOf('--user');
const usernameArg = userIndex !== -1 ? process.argv[userIndex + 1] : 'default';

// Variables globales para la simulación (actualizadas dinámicamente)
let selectedCampaignName = "Campaña Test";
let selectedCampaignId = "12345678";
let selectedLeadName = "Juan Pérez";
let selectedLeadPhone = "5491159263604@s.whatsapp.net";
let simulateAutoReply = true;
let isOrganicTest = false;
let forceMockGroq = true; // Por defecto usamos Mock para mayor rapidez y evitar gastar cuota
let activeTestTranscript = [];

const crmCalls = [];
const outgoingMessages = [];
const mockEvents = {};

// 1. Mock de Socket de Baileys
const mockSock = {
    sendMessage: async (jid, content) => {
        console.log(`   [MOCK WHATSAPP] Enviando mensaje a ${jid.split('@')[0]}: "${content.text}"`);
        outgoingMessages.push({ jid, text: content.text, timestamp: Date.now() });
        
        // No registrar notificaciones administrativas en el transcript del cliente
        if (!content.text.includes("🤖 *LEAD AUTOMÁTICO*")) {
            activeTestTranscript.push({ sender: "ClaudIA", text: content.text });
        }
        return { key: { id: 'mock_msg_' + Date.now() } };
    },
    sendPresenceUpdate: async (presence, jid) => {
        return true;
    },
    normalizeLid: async (jid) => jid,
    chatModify: async (modify, jid) => ({}),
    ev: {
        on: (event, handler) => {
            if (event === 'messages.upsert') {
                mockEvents.messagesUpsert = handler;
            }
            if (event === 'connection.update') {
                mockEvents.connectionUpdate = handler;
            }
        }
    }
};

// 2. Interceptar Módulos (Require Overrides)
Module.prototype.require = function (id) {
    if (id === '@whiskeysockets/baileys') {
        return {
            default: () => mockSock,
            useMultiFileAuthState: async () => ({
                state: { creds: {} },
                saveCreds: () => {}
            }),
            DisconnectReason: { loggedOut: 401 }
        };
    }
    if (id === 'axios') {
        return {
            get: async (url) => {
                if (url.includes('graph.facebook.com')) {
                    return {
                        data: {
                            campaign_name: selectedCampaignName,
                            campaign_id: selectedCampaignId,
                            field_data: [
                                { name: 'full_name', values: [selectedLeadName] },
                                { name: 'phone', values: [selectedLeadPhone.split('@')[0]] }
                            ]
                        }
                    };
                }
                return { data: {} };
            },
            post: async (url, data, config) => {
                console.log(`   [MOCK AXIOS] POST CRM a ${url}`);
                crmCalls.push({ url, data });
                return { status: 200, data: { success: true } };
            }
        };
    }
    
    if (id.includes('licenseService')) {
        return {
            verifyLicense: async () => {
                return { valid: true, message: 'Licencia activa para test' };
            }
        };
    }

    if (id.includes('persistenceService')) {
        return {
            loadState: () => ({
                allowedLeads: [],
                leadNames: {},
                humanIntervention: {},
                autoMode: true,
                activeChatsLastMessageTime: {}
            }),
            saveState: () => {
                // No-op para proteger el archivo de estado de producción
            }
        };
    }

    if (id === 'groq-sdk') {
        const RealGroq = originalRequire.call(this, 'groq-sdk');
        return class MockOrRealGroq {
            constructor(options) {
                this.apiKey = options.apiKey;
                if (!forceMockGroq) {
                    this.realInstance = new RealGroq(options);
                }
            }
            get chat() {
                if (!forceMockGroq) {
                    return this.realInstance.chat;
                }
                return {
                    completions: {
                        create: async (payload) => {
                            const messages = payload.messages;
                            const lastUserMsg = messages[messages.length - 1]?.content || "";
                            let responseText = "¡Hola! Soy ClaudIA, la asistente virtual. ¿En qué te puedo ayudar?";
                            
                            const lastUserMsgLower = lastUserMsg.toLowerCase();
                            if (lastUserMsgLower.includes('almagro') || lastUserMsgLower.includes(' mla-3427810172')) {
                                responseText = "¡Hola! Sí, te comparto el link directo de la propiedad en Almagro de 2 ambientes con balcón aterrazado: https://departamento.mercadolibre.com.ar/MLA-3427810172-departamento-2-ambientes-balcon-aterrazado-en-almagro-_JM. ¿Te gustaría coordinar una visita para conocerlo?";
                            } else if (lastUserMsgLower.includes('tasar') || lastUserMsgLower.includes('vender') || lastUserMsgLower.includes('valuación') || lastUserMsgLower.includes('tasación')) {
                                responseText = "¡Hola! Con gusto te ayudo con la valuación de tu propiedad. Para avanzar, ¿ya estuvo publicada en el pasado con otra inmobiliaria?";
                            } else if (lastUserMsgLower.includes('german') || lastUserMsgLower.includes('germán') || lastUserMsgLower.includes('asesor')) {
                                if (lastUserMsgLower.includes('comprar') || lastUserMsgLower.includes('buscar') || lastUserMsgLower.includes('adquirir')) {
                                    responseText = "¡Hola! Estoy para ayudarte a buscar tu próxima propiedad. ¿Qué tipo de inmueble estás buscando y en qué zona?";
                                } else {
                                    responseText = "Entendido, ya le aviso al asesor inmobiliario para que se contacte con vos a la brevedad. ¡Saludos!";
                                }
                            } else if (lastUserMsgLower.includes('comprar') || lastUserMsgLower.includes('adquirir')) {
                                responseText = "¡Hola! Estoy para ayudarte a buscar tu próxima propiedad. ¿Qué tipo de inmueble estás buscando y en qué zona?";
                            }
                            
                            return {
                                choices: [{
                                    message: {
                                        content: responseText
                                    }
                                }]
                            };
                        }
                    }
                };
            }
        };
    }
    
    const res = originalRequire.apply(this, arguments);

    if (id.includes('configService')) {
        const originalLoad = res.loadConfig;
        res.loadConfig = function(user) {
            const cfg = originalLoad(user || usernameArg);
            if (!cfg.system) cfg.system = {};
            if (!cfg.credentials) cfg.credentials = {};
            // Delay bajo para acelerar los tests
            cfg.system.humanDelay = { min: 0.05, max: 0.1 };
            // Forzar credenciales CRM para que pase el assert
            cfg.credentials.crmEnabled = true;
            cfg.credentials.crmWebhookUrl = "http://localhost:5000/api/leads/meta";
            if (isOrganicTest) {
                cfg.system.openMode = true;
                cfg.system.strangersOnly = false;
            }
            return cfg;
        };
    }
    return res;
};

// Cargar los módulos bajo el contexto de mockings
const whatsappService = require('./src/services/whatsappService');
const webhookController = require('./src/controllers/webhookController');
const geminiService = require('./src/services/geminiService');
const configService = require('./src/services/configService');

// Determina el mensaje adecuado para gatillar cada camino de manera realista
function getTriggerMessageForPath(pathObj) {
    const id = pathObj.id.toLowerCase();
    if (id.includes('vender') || id.includes('tasar')) {
        return "Hola, me gustaría tasar mi departamento para ponerlo en venta.";
    }
    if (id.includes('comprar') || id.includes('ver') || id.includes('buscar')) {
        return "Hola, me gustaría comprar un departamento. ¿Qué opciones tienen?";
    }
    if (id.includes('german') || id.includes('asesor') || id.includes('hablar')) {
        return "Hola, me gustaría hablar con el asesor directamente.";
    }
    if (id.includes('almagro')) {
        return "Hola, me interesa el departamento de Almagro de 2 ambientes. ¿Se puede visitar?";
    }
    if (id.includes('meta')) {
        return "Hola, vi su publicidad en Facebook sobre la tasación de propiedades.";
    }
    return "Hola, me interesa realizar una consulta inmobiliaria.";
}

// Ejecuta un test case particular
async function runPathTest(pathObj, idx) {
    const leadPhone = `549110000000${idx}@s.whatsapp.net`;
    const leadPhoneClean = `549110000000${idx}`;
    const leadName = `Lead ${pathObj.name}`;
    
    selectedCampaignName = pathObj.name || "Campaña Test";
    selectedCampaignId = (pathObj.metaCampaigns ? pathObj.metaCampaigns.split(',')[0].trim() : pathObj.id) || "12345678";
    selectedLeadName = leadName;
    selectedLeadPhone = leadPhone;
    isOrganicTest = !pathObj.metaCampaigns;
    
    console.log(`\n---------------------------------------------------------`);
    console.log(`🧪 PROBANDO CAMINO [${idx}]: "${pathObj.name}" (ID: ${pathObj.id})`);
    console.log(`   Modo de entrada: ${isOrganicTest ? "WhatsApp Orgánico (Open Mode)" : `Meta Ads Campaign (Campaña: ${selectedCampaignId})`}`);
    console.log(`   Teléfono: ${leadPhoneClean} | Nombre: ${leadName}`);
    console.log(`---------------------------------------------------------`);
    
    // Reiniciar estado previo
    await whatsappService.deleteLead(usernameArg, leadPhone);
    
    return new Promise((resolve) => {
        activeTestTranscript = [];
        
        const incomingMsg = getTriggerMessageForPath(pathObj);
        console.log(`   -> Mensaje de cliente a simular: "${incomingMsg}"`);
        
        if (!isOrganicTest) {
            activeTestTranscript.push({ sender: "SISTEMA", text: `Ingreso de Lead desde Meta Ads (Campaña: ${selectedCampaignName})` });
            console.log(`   T = 0ms: Entra Webhook de Meta Lead Ads...`);
            const mockRes = {
                status: (code) => ({ send: (msg) => {} }),
                sendStatus: (code) => {}
            };
            const mockReq = {
                username: usernameArg,
                body: {
                    object: 'page',
                    entry: [{
                        changes: [{
                            field: 'leadgen',
                            value: { leadgen_id: 'mock_lead_123' }
                        }]
                    }]
                }
            };
            
            webhookController.handleWebhook(mockReq, mockRes);
            
            // Simular mensaje de WhatsApp entrante concurrente a los 800ms
            setTimeout(async () => {
                console.log(`   T = 800ms: Cliente envía mensaje WhatsApp concurrentemente: "${incomingMsg}"`);
                activeTestTranscript.push({ sender: "Cliente", text: incomingMsg });
                const incomingMsgEvent = {
                    type: 'notify',
                    messages: [{
                        key: {
                            remoteJid: leadPhone,
                            fromMe: false,
                            id: 'client_msg_' + idx
                        },
                        pushName: leadName,
                        message: {
                            conversation: incomingMsg
                        }
                    }]
                };
                if (mockEvents.messagesUpsert) {
                    await mockEvents.messagesUpsert(incomingMsgEvent);
                }
            }, 800);
            
            // Simular auto-respuesta de WhatsApp Business nativa a los 1200ms
            if (simulateAutoReply) {
                setTimeout(async () => {
                    console.log(`   T = 1200ms: WhatsApp Business envía saludo nativo (auto-respuesta)...`);
                    activeTestTranscript.push({ sender: "WhatsApp Business (Auto-Respuesta)", text: "¡Hola! ¿Cómo podemos ayudarte?" });
                    const outgoingAutoReply = {
                        type: 'notify',
                        messages: [{
                            key: {
                                remoteJid: leadPhone,
                                fromMe: true,
                                id: 'auto_reply_' + idx
                            },
                            message: {
                                conversation: '¡Hola! ¿Cómo podemos ayudarte?'
                            }
                        }]
                    };
                    if (mockEvents.messagesUpsert) {
                        await mockEvents.messagesUpsert(outgoingAutoReply);
                    }
                }, 1200);
            }
        } else {
            // ORGANIC WHATSAPP FLOW
            activeTestTranscript.push({ sender: "SISTEMA", text: "Cliente inicia conversación por WhatsApp (Modo Abierto)" });
            setTimeout(async () => {
                console.log(`   T = 200ms: Cliente envía primer mensaje orgánico por WhatsApp: "${incomingMsg}"`);
                activeTestTranscript.push({ sender: "Cliente", text: incomingMsg });
                const incomingMsgEvent = {
                    type: 'notify',
                    messages: [{
                        key: {
                            remoteJid: leadPhone,
                            fromMe: false,
                            id: 'client_msg_org_' + idx
                        },
                        pushName: leadName,
                        message: {
                            conversation: incomingMsg
                        }
                    }]
                };
                if (mockEvents.messagesUpsert) {
                    await mockEvents.messagesUpsert(incomingMsgEvent);
                }
            }, 200);
        }
        
        // Esperar 6.0 segundos a que todo el flujo asíncrono y llamadas de la IA finalicen
        setTimeout(() => {
            const leadOutgoing = outgoingMessages.filter(m => m.jid === leadPhone);
            const leadCrm = crmCalls.filter(c => {
                const tel = c.data.telefono || c.data.phone;
                return tel && (tel === leadPhone || tel === leadPhoneClean);
            });
            
            const isPaused = geminiService.getHumanInterventionStatus(usernameArg, leadPhone);
            
            const assertions = {
                leadRegistered: whatsappService.getLeadsStatus(usernameArg).some(l => l.phone === leadPhone),
                notPaused: !isPaused,
                crmSent: leadCrm.length > 0,
                crmContentOk: false,
                aiResponseOk: false,
                aiResponseText: ""
            };
            
            if (assertions.crmSent) {
                const crmMsg = leadCrm[0].data.mensaje_original || leadCrm[0].data.mensajeOriginal || "";
                assertions.crmContentOk = crmMsg.includes(incomingMsg) || crmMsg.length > 0;
            }
            
            if (leadOutgoing.length > 0) {
                const nonAutoReplies = leadOutgoing.filter(m => !m.text.includes("¿Cómo podemos ayudarte?"));
                if (nonAutoReplies.length > 0) {
                    assertions.aiResponseOk = true;
                    assertions.aiResponseText = nonAutoReplies[nonAutoReplies.length - 1].text || "";
                }
            }
            
            console.log(`\n   🔍 VALIDACIONES FINALIZADAS PARA EL CAMINO "${pathObj.id}":`);
            console.log(`   [ASSERT 1] ¿Lead registrado en AllowedLeads?: ${assertions.leadRegistered ? "SÍ ✅" : "NO ❌"}`);
            console.log(`   [ASSERT 2] ¿ClaudIA siguió activa tras auto-respuesta?: ${assertions.notPaused ? "SÍ ✅" : "NO ❌"}`);
            console.log(`   [ASSERT 3] ¿Se envió lead con éxito al CRM?: ${assertions.crmSent ? "SÍ ✅" : "NO ❌"}`);
            if (assertions.crmSent) {
                console.log(`      - Mensaje enviado al CRM: "${leadCrm[0].data.mensaje_original || leadCrm[0].data.mensajeOriginal}"`);
            }
            console.log(`   [ASSERT 4] ¿Respuesta de ClaudIA generada?: ${assertions.aiResponseOk ? "SÍ ✅" : "NO ❌"}`);
            if (assertions.aiResponseOk) {
                console.log(`      - Mensaje enviado por WhatsApp: "${assertions.aiResponseText.replace(/\n/g, ' ')}"`);
            }
            
            const success = assertions.leadRegistered && assertions.notPaused && assertions.crmSent && assertions.aiResponseOk;
            
            resolve({
                pathId: pathObj.id,
                pathName: pathObj.name,
                type: isOrganicTest ? "Orgánico" : "Meta Ads",
                success,
                assertions,
                transcript: [...activeTestTranscript]
            });
        }, 6000);
    });
}

// Ejecuta la Suite Completa
async function runTestSuite() {
    console.clear();
    console.log("=========================================================");
    console.log(`🧪 INICIANDO SUITE DE PRUEBAS AUTOMÁTICAS PARA CLAUDIA PRO (${usernameArg.toUpperCase()})`);
    console.log("=========================================================\n");

    const config = configService.loadConfig(usernameArg);
    const paths = config.paths || [];

    if (paths.length === 0) {
        console.error("❌ No se encontraron Paths configurados.");
        process.exit(1);
    }

    console.log(`Encontrados ${paths.length} caminos para evaluar de manera secuencial.`);
    
    // Inicializar socket de whatsappService
    await whatsappService.initialize(usernameArg);
    if (mockEvents.connectionUpdate) {
        await mockEvents.connectionUpdate({ connection: 'open' });
    }

    const results = [];
    for (let i = 0; i < paths.length; i++) {
        const pathObj = paths[i];
        const res = await runPathTest(pathObj, i + 1);
        results.push(res);
    }

    console.log("\n=========================================================");
    console.log("📊 RESUMEN FINAL DE LA SUITE DE PRUEBAS DE CAMINOS");
    console.log("=========================================================");
    
    console.log(
        "|" + "CAMINO/CAMPAÑA".padEnd(28) + 
        "|" + "TIPO".padEnd(10) + 
        "|" + "CRM".padEnd(8) + 
        "|" + "PAUSA".padEnd(8) + 
        "|" + "RESP. IA".padEnd(12) + 
        "|" + "ESTADO".padEnd(12) + "|"
    );
    console.log("|" + "-".repeat(28) + "|" + "-".repeat(10) + "|" + "-".repeat(8) + "|" + "-".repeat(8) + "|" + "-".repeat(12) + "|" + "-".repeat(12) + "|");
    
    let allPassed = true;
    results.forEach(r => {
        const typeStr = r.type;
        const crmStr = r.assertions.crmSent ? "OK" : "FALLÓ ❌";
        const pauseStr = r.assertions.notPaused ? "OK" : "PAUSADO ❌";
        const aiStr = r.assertions.aiResponseOk ? "OK" : "FALLÓ ❌";
        const statusStr = r.success ? "PASSED ✅" : "FAILED ❌";
        if (!r.success) allPassed = false;
        
        console.log(
            "|" + r.pathName.substring(0, 27).padEnd(28) + 
            "|" + typeStr.padEnd(10) + 
            "|" + crmStr.padEnd(8) + 
            "|" + pauseStr.padEnd(8) + 
            "|" + aiStr.padEnd(12) + 
            "|" + statusStr.padEnd(12) + "|"
        );
    });
    console.log("");
    
    // --- IMPRIMIR DIÁLOGOS DE MANERA MUY LIMPIA ---
    console.log("\n=========================================================");
    console.log("💬 DIÁLOGOS SIMULADOS POR CADA CASO");
    console.log("=========================================================");
    
    let fileContent = `=========================================================\n`;
    fileContent += `💬 DETALLE DE CONVERSACIONES - SUITE DE PRUEBAS AUTOMÁTICAS\n`;
    fileContent += `=========================================================\n\n`;
    
    results.forEach(r => {
        console.log(`\n---------------------------------------------------------`);
        console.log(`CAMINO: ${r.pathName} (ID: ${r.pathId})`);
        console.log(`---------------------------------------------------------`);
        
        fileContent += `---------------------------------------------------------\n`;
        fileContent += `CAMINO: ${r.pathName} (ID: ${r.pathId})\n`;
        fileContent += `---------------------------------------------------------\n`;
        
        r.transcript.forEach(msg => {
            const line = `[${msg.sender}]: ${msg.text}`;
            console.log(line);
            fileContent += line + `\n`;
        });
        fileContent += `\n`;
    });

    const fs = require('fs');
    const path = require('path');
    const outputPath = path.join(__dirname, `test_transcripts_${usernameArg}.txt`);
    fs.writeFileSync(outputPath, fileContent, 'utf-8');
    
    console.log(`\n=========================================================`);
    console.log(`💾 Copia limpia de los diálogos guardada en:\n   ${outputPath}`);
    console.log(`=========================================================\n`);
    
    if (allPassed) {
        console.log("🎉 ¡TODAS LAS PRUEBAS AUTOMÁTICAS PASARON EXITOSAMENTE!\n");
        rl.close();
        process.exit(0);
    } else {
        console.error("❌ ALGUNAS PRUEBAS FALLARON.\n");
        rl.close();
        process.exit(1);
    }
}

// Ejecuta la Simulación Individual Interactiva
async function runInteractiveMenu() {
    console.clear();
    console.log("=========================================================");
    console.log(`🔮 SIMULADOR INTERACTIVO INDIVIDUAL DE CONCURRENCIA (${usernameArg.toUpperCase()})`);
    console.log("=========================================================\n");

    const config = configService.loadConfig(usernameArg);
    const paths = config.paths || [];

    if (paths.length === 0) {
        console.error("❌ No se encontraron Paths configurados.");
        process.exit(1);
    }

    console.log("Paths / Campañas configurados en tu sistema:");
    paths.forEach((p, idx) => {
        const campaigns = p.metaCampaigns ? ` [Campaña: ${p.metaCampaigns}]` : " [Sin campañas (Orgánico)]";
        const welcomeOpt = p.skipWelcome ? " (Auto-saludo: APAGADO 🚫)" : " (Auto-saludo: ACTIVADO 👋)";
        console.log(`[${idx + 1}] ID: ${p.id} | Nombre: "${p.name}"${campaigns}${welcomeOpt}`);
    });
    console.log("");

    const selectionIndex = await question("Selecciona el número de Path a simular: ");
    const pathIdx = parseInt(selectionIndex) - 1;

    if (isNaN(pathIdx) || pathIdx < 0 || pathIdx >= paths.length) {
        console.error("Selección inválida.");
        process.exit(1);
    }

    const pathObj = paths[pathIdx];
    
    console.log(`\nConfigurando simulación para: "${pathObj.name}"`);
    
    let leadName = `Lead ${pathObj.name}`;
    const nameInput = await question(`Nombre del lead (Default: "${leadName}"): `);
    if (nameInput.trim()) leadName = nameInput.trim();

    let leadPhone = "5491159263604@s.whatsapp.net";
    const phoneInput = await question(`Teléfono del lead (Default: 5491159263604): `);
    if (phoneInput.trim()) {
        const clean = phoneInput.replace(/\D/g, '');
        leadPhone = `${clean}@s.whatsapp.net`;
    }

    const defaultMsg = getTriggerMessageForPath(pathObj);
    const msgInput = await question(`\nMensaje que envía el cliente por WhatsApp durante activación (Default: "${defaultMsg}")\n(Escribe 'none' para simular que el cliente no escribe nada): `);
    
    let simulatedMsg = defaultMsg;
    if (msgInput.trim().toLowerCase() === 'none') {
        simulatedMsg = "";
    } else if (msgInput.trim()) {
        simulatedMsg = msgInput.trim();
    }

    const arInput = await question("\n¿Simular el saludo automático nativo de tu WhatsApp Business? (s/n, Default: s): ");
    simulateAutoReply = arInput.trim().toLowerCase() !== 'n';

    console.log("\n=========================================================");
    console.log("⚙️ INICIANDO LA SECUENCIA DE SIMULACIÓN ASÍNCRONA");
    console.log("=========================================================\n");

    await whatsappService.initialize(usernameArg);
    if (mockEvents.connectionUpdate) {
        await mockEvents.connectionUpdate({ connection: 'open' });
    }

    selectedCampaignName = pathObj.name || "Campaña Test";
    selectedCampaignId = (pathObj.metaCampaigns ? pathObj.metaCampaigns.split(',')[0].trim() : pathObj.id) || "12345678";
    selectedLeadName = leadName;
    selectedLeadPhone = leadPhone;
    isOrganicTest = !pathObj.metaCampaigns;

    await whatsappService.deleteLead(usernameArg, leadPhone);

    if (!isOrganicTest) {
        console.log(`   T = 0ms: Entra Webhook de Meta Lead Ads...`);
        const mockRes = {
            status: (code) => ({ send: (msg) => {} }),
            sendStatus: (code) => {}
        };
        const mockReq = {
            username: usernameArg,
            body: {
                object: 'page',
                entry: [{
                    changes: [{
                        field: 'leadgen',
                        value: { leadgen_id: 'mock_lead_123' }
                    }]
                }]
            }
        };
        await webhookController.handleWebhook(mockReq, mockRes);

        if (simulatedMsg) {
            setTimeout(async () => {
                console.log(`   T = 800ms: Cliente envía mensaje WhatsApp concurrentemente: "${simulatedMsg}"`);
                const incomingMsgEvent = {
                    type: 'notify',
                    messages: [{
                        key: {
                            remoteJid: leadPhone,
                            fromMe: false,
                            id: 'client_msg_interactive'
                        },
                        pushName: leadName,
                        message: {
                            conversation: simulatedMsg
                        }
                    }]
                };
                if (mockEvents.messagesUpsert) {
                    await mockEvents.messagesUpsert(incomingMsgEvent);
                }
            }, 800);
        }

        if (simulateAutoReply) {
            setTimeout(async () => {
                console.log(`   T = 1200ms: WhatsApp Business envía saludo nativo (auto-respuesta)...`);
                const outgoingAutoReply = {
                    type: 'notify',
                    messages: [{
                        key: {
                            remoteJid: leadPhone,
                            fromMe: true,
                            id: 'auto_reply_interactive'
                        },
                        message: {
                            conversation: '¡Hola! ¿Cómo podemos ayudarte?'
                        }
                    }]
                };
                if (mockEvents.messagesUpsert) {
                    await mockEvents.messagesUpsert(outgoingAutoReply);
                }
            }, 1200);
        }
    } else {
        setTimeout(async () => {
            console.log(`   T = 200ms: Cliente envía primer mensaje orgánico por WhatsApp: "${simulatedMsg}"`);
            const incomingMsgEvent = {
                type: 'notify',
                messages: [{
                    key: {
                        remoteJid: leadPhone,
                        fromMe: false,
                        id: 'client_msg_org_interactive'
                    },
                    pushName: leadName,
                    message: {
                        conversation: simulatedMsg
                    }
                }]
            };
            if (mockEvents.messagesUpsert) {
                await mockEvents.messagesUpsert(incomingMsgEvent);
            }
        }, 200);
    }

    setTimeout(() => {
        const leadPhoneClean = leadPhone.split('@')[0];
        const leadOutgoing = outgoingMessages.filter(m => m.jid === leadPhone);
        const leadCrm = crmCalls.filter(c => {
            const tel = c.data.telefono || c.data.phone;
            return tel && (tel === leadPhone || tel === leadPhoneClean);
        });

        const isPaused = geminiService.getHumanInterventionStatus(usernameArg, leadPhone);

        console.log("\n=========================================================");
        console.log("🔍 VALIDACIONES Y EVALUACIÓN FINAL DE RESULTADOS");
        console.log("=========================================================");
        
        console.log(`1. ¿ClaudIA fue pausada por la auto-respuesta?: ${isPaused ? "SÍ (FALLÓ) ❌" : "NO (OK) ✅"}`);
        console.log(`2. ¿Se envió el lead al CRM?: ${leadCrm.length > 0 ? "SÍ ✅" : "NO ❌"}`);
        if (leadCrm.length > 0) {
            console.log(`   - Mensaje enviado al CRM: "${leadCrm[0].data.mensaje_original || leadCrm[0].data.mensajeOriginal}"`);
        }
        
        console.log("\n3. Historial de mensajes salientes enviados en esta simulación:");
        leadOutgoing.forEach((m, idx) => {
            console.log(`   [${idx + 1}] Texto: "${m.text}"`);
        });

        const success = !isPaused && leadCrm.length > 0 && leadOutgoing.length > 0;
        
        if (success) {
            console.log("\n🎉 ¡SIMULACIÓN COMPLETADA EXITOSAMENTE!");
            rl.close();
            process.exit(0);
        } else {
            console.error("\n❌ LA PRUEBA HA FALLADO.");
            rl.close();
            process.exit(1);
        }
    }, 6000);
}

// Menú Principal
async function main() {
    const isSuite = process.argv.includes('--suite');
    const isInteractive = process.argv.includes('--interactive');
    const isReal = process.argv.includes('--real');
    
    if (isSuite) {
        forceMockGroq = !isReal;
        await runTestSuite();
        return;
    }

    if (isInteractive) {
        forceMockGroq = !isReal;
        await runInteractiveMenu();
        return;
    }

    console.clear();
    console.log("=========================================================");
    console.log("🔮 SIMULADOR DE CONCURRENCIA Y CAMINOS PARA CLAUDIA PRO");
    console.log("=========================================================\n");
    console.log("[1] Ejecutar Suite de Pruebas Completa (Automática y Secuencial)");
    console.log("[2] Ejecutar Simulación Interactiva de un camino específico");
    console.log("");
    
    const option = await question("Selecciona una opción: ");
    if (option.trim() !== "1" && option.trim() !== "2") {
        console.error("Opción inválida.");
        rl.close();
        process.exit(1);
    }

    const mockOpt = await question("\n¿Deseas usar la API Real de Groq o simular las respuestas con un Mock local (Offline)? (r/m, Default: m): ");
    forceMockGroq = mockOpt.trim().toLowerCase() !== 'r';

    if (option.trim() === "1") {
        await runTestSuite();
    } else {
        await runInteractiveMenu();
    }
}

main();
