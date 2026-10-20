const express = require('express');
const router = express.Router();
const configService = require('../services/configService');
const whatsappService = require('../services/whatsappService');
const licenseService = require('../services/licenseService');
const loggerService = require('../services/loggerService');

// Obtener configuración actual del agente
router.get('/', (req, res) => {
    const config = configService.loadConfig(req.username);
    res.json(config);
});

// Obtener estado de leads del agente
router.get('/leads', (req, res) => {
    const leads = whatsappService.getLeadsStatus(req.username);
    res.json(leads);
});

// Eliminar un lead del agente
router.delete('/leads/:phone', async (req, res) => {
    const phone = decodeURIComponent(req.params.phone);
    const success = await whatsappService.deleteLead(req.username, phone);
    if (success) {
        res.json({ message: 'Lead eliminado' });
    } else {
        res.status(400).json({ error: 'Número inválido o lead no encontrado' });
    }
});

// Cambiar estado de pausa de un lead
router.post('/leads/:phone/toggle-pause', async (req, res) => {
    const phone = decodeURIComponent(req.params.phone);
    const isPaused = req.body.isPaused;
    
    const success = await whatsappService.toggleLeadPause(req.username, phone, isPaused);
    if (success) {
        res.json({ message: 'Estado de pausa actualizado', isPaused });
    } else {
        res.status(400).json({ error: 'Lead no encontrado' });
    }
});

// Verificar estado de licencia
router.get('/license-status', async (req, res) => {
    const config = configService.loadConfig(req.username);
    const result = await licenseService.verifyLicense(config.credentials?.licenseKey);
    res.json(result);
});

// Obtener logs de auditoría
router.get('/audit-logs', (req, res) => {
    const logs = loggerService.getLogs(req.username, 200);
    res.json({ logs });
});

// Iniciar / Resetear chat de simulación
router.post('/simulate/reset', (req, res) => {
    const username = req.username;
    const phone = "5491112345678@s.whatsapp.net";
    const leadName = req.body.leadName || "Cliente de Prueba";
    const scenario = req.body.scenario || "unknown";
    const pathId = req.body.pathId || "";
    
    const config = configService.loadConfig(username);
    const geminiService = require('../services/geminiService');
    
    geminiService.resetHumanIntervention(username, phone);
    
    let greeting = "";
    let question = "";
    let systemNote = "";
    let info = "";
    let skipIntro = false;
    let finalPathId = null;

    if (scenario === 'meta') {
        const matchedPath = (config.paths || []).find(p => p.id === pathId);
        if (matchedPath) {
            finalPathId = matchedPath.id;
            greeting = (matchedPath.welcomeMessageA || config.personality?.globalGreeting || "").replace('{name}', leadName);
            question = (matchedPath.welcomeMessageB || "").replace('{name}', leadName);
            
            if (!matchedPath.welcomeMessageA) {
                // If message A is empty, skip welcome messages entirely
                greeting = "";
                question = "";
                skipIntro = true;
                systemNote = `📢 ClaudIA forzó el camino "${matchedPath.name}" sin saludos (Mensaje A vacío).`;
                info = "Esperando que el cliente escriba...";
            } else {
                systemNote = `📢 ClaudIA forzó el camino "${matchedPath.name}". Mensajes proactivos enviados:`;
                if (!matchedPath.welcomeMessageB) {
                    question = ""; // If message B is empty, do not send anything for B
                }
            }
        } else {
            // General meta Ads
            greeting = (config.personality?.globalGreeting || "¡Hola! 👋").replace('{name}', leadName);
            question = (config.personality?.initialQuestion || "¿En qué puedo ayudarte?").replace('{name}', leadName);
            systemNote = "📢 Campaña de Meta Ads general. Mensajes proactivos enviados:";
        }
    } else if (scenario === 'scheduled') {
        skipIntro = true;
        systemNote = "✅ Lead ya agendado en CRM. Esperando mensaje del cliente...";
        info = "No se enviaron saludos automáticos.";
    } else {
        // unknown (Cliente desconocido escribe primero)
        skipIntro = true;
        systemNote = "👤 Cliente desconocido. Escribí tu primer mensaje para iniciar la conversación...";
        info = "ClaudIA responderá saludándote al recibir tu primer mensaje.";
    }

    geminiService.preInitializeChat(username, phone, leadName, greeting, question, skipIntro, finalPathId);
    
    res.json({
        systemNote,
        greeting,
        question,
        info
    });
});

// Enviar mensaje en simulación
router.post('/simulate/message', async (req, res) => {
    const username = req.username;
    const phone = "5491112345678@s.whatsapp.net";
    const message = req.body.message || "";
    const leadName = req.body.leadName || "Cliente de Prueba";
    
    const geminiService = require('../services/geminiService');
    try {
        const reply = await geminiService.processIncomingMessage(username, phone, message, leadName);
        res.json({ reply });
    } catch(err) {
        res.status(500).json({ error: err.message });
    }
});

// Ejecutar Suite de Pruebas de Concurrencia
router.post('/simulate/concurrency', (req, res) => {
    const username = req.username;
    const useRealGroq = req.body.realGroq === true;
    const { exec } = require('child_process');
    const path = require('path');
    const fs = require('fs');

    const scriptPath = path.join(__dirname, '../../test_concurrency.js');
    const args = [`--suite`, `--user`, username];
    if (useRealGroq) {
        args.push(`--real`);
    }

    const command = `node "${scriptPath}" ${args.join(' ')}`;
    console.log(`[Test Concurrency] [${username}] Ejecutando: ${command}`);

    exec(command, (error, stdout, stderr) => {
        // Read transcripts if generated
        const transcriptPath = path.join(__dirname, `../../test_transcripts_${username}.txt`);
        let transcripts = "";
        if (fs.existsSync(transcriptPath)) {
            try {
                transcripts = fs.readFileSync(transcriptPath, 'utf8');
            } catch (e) {
                console.error("Error leyendo archivo de transcripciones:", e);
            }
        }

        res.json({
            success: !error,
            consoleOutput: stdout || stderr || "",
            transcripts: transcripts,
            error: error ? error.message : null
        });
    });
});

// Guardar nueva configuración
router.post('/', (req, res) => {
    const newConfig = req.body;
    
    if (!newConfig.system || !newConfig.credentials) {
        return res.status(400).json({ error: 'Configuración inválida' });
    }

    const currentConfig = configService.loadConfig(req.username);

    // Proteger campos de credenciales sensibles
    const sensitiveFields = ['groqApiKey', 'metaToken', 'adminPhone', 'metaVerifyToken', 'licenseKey', 'crmWebhookToken'];
    sensitiveFields.forEach(field => {
        const newVal = newConfig.credentials[field];
        if (!newVal || newVal.trim() === '' || newVal.includes('***')) {
            newConfig.credentials[field] = currentConfig.credentials[field] || '';
        }
    });

    const success = configService.saveConfig(req.username, newConfig);
    if (success) {
        res.json({ message: 'Configuración guardada' });
    } else {
        res.status(500).json({ error: 'Error al guardar' });
    }
});

const fs = require('fs');
const path = require('path');

// Subir y procesar archivo de contactos (VCF o CSV)
router.post('/upload-contacts', (req, res) => {
    try {
        const username = req.username;
        const { filename, content } = req.body;
        if (!filename || !content) {
            return res.status(400).json({ error: 'Falta nombre o contenido del archivo' });
        }

        const nameLower = filename.toLowerCase();
        let targetName = '';
        if (nameLower.endsWith('.csv')) {
            targetName = `contacts_${username}.csv`;
        } else if (nameLower.endsWith('.vcf')) {
            targetName = `contacts_${username}.vcf`;
        } else {
            return res.status(400).json({ error: 'Formato no soportado. Debe ser .csv o .vcf' });
        }

        const targetPath = path.join(__dirname, '../../configs/', targetName);
        fs.writeFileSync(targetPath, content, 'utf-8');
        console.log(`[Dashboard] Archivo ${targetName} guardado por carga web en ${targetPath}`);

        const totalContacts = whatsappService.reloadStaticContacts(username);
        res.json({
            message: `Archivo ${targetName} cargado correctamente.`,
            filename: targetName,
            totalContacts
        });
    } catch (err) {
        console.error('[Dashboard] Error en /upload-contacts:', err);
        res.status(500).json({ error: 'Error procesando archivo: ' + err.message });
    }
});

module.exports = router;
