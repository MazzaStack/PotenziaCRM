require('dotenv').config();
const readline = require('readline');
const geminiService = require('./src/services/geminiService');
const configService = require('./src/services/configService');

// Cargar configuración actual
const config = configService.loadConfig();
const BOT_NAME = config.system?.botName || "ClaudIA Pro";

// Configuración de la simulación
const LEAD_NAME = process.argv[2] || "Juan Pérez";
const LEAD_PHONE = "5491112345678@s.whatsapp.net"; // ID ficticio para el test

const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout
});

async function startSimulation() {
    console.clear();
    console.log("=========================================================");
    console.log(`🚀 SIMULADOR DE CONVERSACIÓN CON ${BOT_NAME.toUpperCase()}`);
    console.log(`Lead: ${LEAD_NAME}`);
    console.log(`Configuración: Modular / Multi-path`);
    console.log("=========================================================\n");

    const lastMsgIndex = process.argv.indexOf('--last');
    const isProactive = lastMsgIndex !== -1 && process.argv[lastMsgIndex + 1];

    const setupChat = (isManual = false) => {
        const freshConfig = configService.loadConfig();
        
        // Buscar si se pasó un path específico en la consola
        const pathIndex = process.argv.indexOf('--path');
        const forcedPathId = pathIndex !== -1 ? process.argv[pathIndex + 1] : null;

        let msgA = "¡Hola! 👋";
        let msgB = "";
        let skipWelcome = false;

        // Si hay un path, buscar sus saludos específicos
        if (forcedPathId) {
            const matchedPath = (freshConfig.paths || []).find(p => p.id === forcedPathId);
            if (matchedPath) {
                if (matchedPath.welcomeMessageA) msgA = matchedPath.welcomeMessageA;
                if (matchedPath.welcomeMessageB) msgB = matchedPath.welcomeMessageB;
                skipWelcome = matchedPath.skipWelcome || false;
            }
        } else {
            // Saludos globales del config general
            if (freshConfig.personality?.globalGreeting) msgA = freshConfig.personality.globalGreeting;
            if (freshConfig.personality?.initialQuestion) msgB = freshConfig.personality.initialQuestion;
        }

        msgA = msgA.replace('{name}', LEAD_NAME);
        if (msgB) {
            msgB = msgB.replace('{name}', LEAD_NAME);
        }
        
        if (forcedPathId) {
            console.log(`[SISTEMA] Inicializando chat para ${LEAD_NAME} forzando Path: ${forcedPathId}...`);
            geminiService.preInitializeChat('default', LEAD_PHONE, LEAD_NAME, msgA, msgB || "", isManual || skipWelcome, forcedPathId);
        } else {
            console.log(`[SISTEMA] Inicializando chat para ${LEAD_NAME} (Path por defecto)...`);
            geminiService.preInitializeChat('default', LEAD_PHONE, LEAD_NAME, msgA, msgB || "", isManual);
        }
        return { mensajeA: msgA, mensajeB: msgB, skipWelcome };
    };

    const { mensajeA, mensajeB, skipWelcome } = setupChat(isProactive);

    // Simular proactividad si se pasa el argumento --last
    if (isProactive) {
        const lastMsg = process.argv[lastMsgIndex + 1];
        console.log(`\n[PROACTIVO] Analizando último mensaje: "${lastMsg}"...`);
        const response = await geminiService.processIncomingMessage('default', LEAD_PHONE, lastMsg, LEAD_NAME);
        console.log(`\n🤖 ${BOT_NAME}: ${response}\n`);
    } else if (skipWelcome) {
        console.log(`\n[SISTEMA] Omitir Saludos Iniciales activo. Esperando que el usuario comience la charla...\n`);
    } else {
        console.log(`[BOT] Mensaje A: "${mensajeA}"`);
        if (mensajeB) {
            console.log(`[BOT] Mensaje B: "${mensajeB}"\n`);
        } else {
            console.log("");
        }
    }

    console.log(`--- ${BOT_NAME} lista. Escribí 'salir' para cerrar o 'reset' para reiniciar chat. ---`);
    console.log(`💡 TIP: Podés simular archivos escribiendo '[audio] Hola' o '[imagen]'.`);
    console.log(`💡 TIP: Para probar ráfagas escribí 'burst: [audio] | [imagen] | Hola quiero info'.\n`);

    const ask = () => {
        const freshConfig = configService.loadConfig();
        const CURRENT_BOT_NAME = freshConfig.system?.botName || "ClaudIA Pro";

        rl.question(`👤 ${LEAD_NAME}: `, async (input) => {
            const cmd = input.toLowerCase().trim();
            
            if (cmd === 'salir') {
                console.log("\n👋 Simulación terminada.");
                process.exit(0);
            }

            if (cmd === 'reset') {
                console.log("\n🧹 Borrando memoria de la IA...");
                geminiService.resetHumanIntervention('default', LEAD_PHONE);
                setupChat();
                console.log("✅ Chat reiniciado.\n");
                ask();
                return;
            }

            // SIMULACIÓN DE RÁFAGA (CONCURRENCIA)
            if (input.startsWith('burst:')) {
                const rawParts = input.replace('burst:', '').split('|').map(p => p.trim()).filter(p => p !== "");
                console.log(`\n⚡ Simulando envío de ráfaga (concurrente) de ${rawParts.length} mensajes...`);
                
                const processedMessages = rawParts.map((msg, i) => {
                    let finalMsg = msg;
                    if (msg.startsWith('[audio]')) {
                        const t = msg.replace('[audio]', '').trim();
                        finalMsg = t === "" 
                            ? '[SISTEMA: El usuario envió un mensaje de voz que no podés ver/escuchar directamente. Pedile amablemente que te lo explique en texto o decile que por ahora solo procesás mensajes escritos.]'
                            : `${t} [NOTA: Este mensaje acompaña a un mensaje de voz]`;
                    } else if (msg.startsWith('[imagen]')) {
                        const t = msg.replace('[imagen]', '').trim();
                        finalMsg = t === ""
                            ? '[SISTEMA: El usuario envió una imagen que no podés ver/escuchar directamente. Pedile amablemente que te lo explique en texto o decile que por ahora solo procesás mensajes escritos.]'
                            : `${t} [NOTA: Este mensaje acompaña a una imagen]`;
                    }
                    
                    console.log(` -> Para el mensaje #${i+1} procesado: "${finalMsg}"`);
                    return finalMsg;
                });

                const mergedText = processedMessages.join('\n\n');
                
                console.log(`\n🤖 ${CURRENT_BOT_NAME} está pensando (procesando ráfaga agrupada)...`);
                try {
                    const response = await geminiService.processIncomingMessage('default', LEAD_PHONE, mergedText, LEAD_NAME);
                    console.log(`\n🤖 ${CURRENT_BOT_NAME} (Respuesta): ${response}\n`);
                } catch (err) {
                    console.error(`\n❌ Error en respuesta agrupada:`, err.message);
                }
                
                ask();
                return;
            }

            // SIMULACIÓN DE ARCHIVOS MULTIMEDIA (INDIVIDUAL)
            let processedInput = input;
            if (input.startsWith('[audio]')) {
                const t = input.replace('[audio]', '').trim();
                processedInput = t === "" 
                    ? '[SISTEMA: El usuario envió un mensaje de voz que no podés ver/escuchar directamente. Pedile amablemente que te lo explique en texto o decile que por ahora solo procesás mensajes escritos.]'
                    : `${t} [NOTA: Este mensaje acompaña a un mensaje de voz]`;
            } else if (input.startsWith('[imagen]')) {
                const t = input.replace('[imagen]', '').trim();
                processedInput = t === ""
                    ? '[SISTEMA: El usuario envió una imagen que no podés ver/escuchar directamente. Pedile amablemente que te lo explique en texto o decile que por ahora solo procesás mensajes escritos.]'
                    : `${t} [NOTA: Este mensaje acompaña a una imagen]`;
            }

            console.log(`\n🤖 ${CURRENT_BOT_NAME} está pensando...`);
            try {
                const response = await geminiService.processIncomingMessage('default', LEAD_PHONE, processedInput, LEAD_NAME);
                console.log(`\n🤖 ${CURRENT_BOT_NAME}: ${response}\n`);
            } catch (error) {
                console.error("\n❌ Error en la IA:", error.message);
            }
            
            ask();
        });
    };

    ask();
}

startSimulation();
