const ax = require('axios');
const whatsappService = require('../services/whatsappService');
const configService = require('../services/configService');
const loggerService = require('../services/loggerService');

const GRAPH_API_VERSION = 'v19.0';

// ============================================================
// Obtiene el teléfono del administrador de forma dinámica
// ============================================================
const getAdminPhone = (username) => {
    const config = configService.loadConfig(username);
    let phone = config.credentials?.adminPhone || process.env.ADMIN_PHONE;
    if (phone && !phone.includes('@c.us')) {
        phone += '@c.us';
    }
    return phone;
};

// ============================================================
// Busca qué camino (Path) está asociado a la campaña de Meta
// ============================================================
const findPathForCampaign = (username, campaignName, campaignId) => {
    if (!campaignName && !campaignId) return null;
    const config = configService.loadConfig(username);
    const paths = config.paths || [];

    const normName = campaignName ? campaignName.toLowerCase().trim() : "";
    const normId = campaignId ? campaignId.toString().toLowerCase().trim() : "";

    for (const p of paths) {
        if (!p.metaCampaigns) continue;
        
        const campaignsMapped = p.metaCampaigns.split(',')
            .map(c => c.trim().toLowerCase())
            .filter(c => c.length > 0);

        for (const mapped of campaignsMapped) {
            if (mapped === normName || mapped === normId) {
                return p.id;
            }
            if (normName && normName.includes(mapped)) {
                return p.id;
            }
        }
    }
    return null;
};

// ============================================================
// Obtiene nombre, teléfono y datos de campaña desde la API de Meta
// ============================================================
const getLeadData = async (username, leadId) => {
    try {
        const config = configService.loadConfig(username);
        const metaAccessToken = config.credentials?.metaToken || process.env.META_ACCESS_TOKEN;

        if (!metaAccessToken) {
            console.error(`[Webhook] [${username}] Error: No se halló META_ACCESS_TOKEN configurado.`);
            return null;
        }

        const url = `https://graph.facebook.com/${GRAPH_API_VERSION}/${leadId}?fields=field_data,campaign_name,campaign_id&access_token=${metaAccessToken}`;
        const response = await ax.get(url);
        const data = response.data;

        let name  = "Cliente";
        let phone = "";
        let campaignName = data.campaign_name || "";
        let campaignId = data.campaign_id || "";

        if (data.field_data) {
            data.field_data.forEach(field => {
                const fieldName = field.name.toLowerCase();
                if (fieldName.includes('full_name') || fieldName.includes('nombre')) {
                    name = field.values[0];
                }
                if (fieldName.includes('phone') || fieldName.includes('telefono')) {
                    phone = field.values[0];
                }
            });
        }

        if (phone) phone = phone.replace('+', '').replace(/\s/g, '').trim();

        return { name, phone, campaignName, campaignId };
    } catch (error) {
        console.error(`[Webhook] [${username}] Error obteniendo datos del lead:`, error.response ? error.response.data : error.message);
        return null;
    }
};

// ============================================================
// GET /webhook/:username — Verificación del webhook por parte de Meta
// ============================================================
const verifyWebhook = (req, res) => {
    const username = req.username;
    const config = configService.loadConfig(username);
    const metaVerifyToken = config.credentials?.metaVerifyToken || process.env.META_VERIFY_TOKEN;

    const mode      = req.query['hub.mode']         || req.query['hub_mode'];
    const token     = req.query['hub.verify_token'] || req.query['hub_verify_token'];
    const challenge = req.query['hub.challenge']    || req.query['hub_challenge'];

    const cleanToken  = token       ? token.trim()       : "";
    const cleanSecret = metaVerifyToken ? metaVerifyToken.trim() : "";

    console.log(`--- INTENTO DE VERIFICACIÓN DE WEBHOOK PARA ${username} ---`);
    console.log('Token Recibido:', `"${cleanToken}"`);
    console.log('Token Esperado:', `"${cleanSecret}"`);

    loggerService.writeLog(username, 'SYSTEM', null, `Intento de verificación de webhook. Modo: ${mode}`);

    if (mode && token) {
        if (mode === 'subscribe' && cleanToken === cleanSecret) {
            console.log(`✅ WEBHOOK VERIFICADO PARA ${username}`);
            loggerService.writeLog(username, 'SYSTEM', null, `✅ Webhook verificado correctamente por Meta.`);
            res.status(200).send(challenge);
        } else {
            console.error('❌ Token de verificación incorrecto.');
            loggerService.writeLog(username, 'SYSTEM', null, `❌ Falló la verificación del webhook (Token de verificación incorrecto).`);
            res.sendStatus(403);
        }
    } else {
        console.error('❌ Faltan parámetros.');
        loggerService.writeLog(username, 'SYSTEM', null, `❌ Falló la verificación del webhook (Faltan parámetros en la query).`);
        res.sendStatus(400);
    }
};

// ============================================================
// POST /webhook/:username — Recibe eventos de Meta (Lead Ads, etc.)
// ============================================================
const handleWebhook = async (req, res) => {
    const username = req.username;
    const body = req.body;

    console.log(`--- EVENTO POST RECIBIDO EN WEBHOOK PARA ${username} ---`);
    console.log(JSON.stringify(body, null, 2));

    if (!body.object) {
        return res.sendStatus(404);
    }

    res.status(200).send('EVENT_RECEIVED');

    try {
        const adminPhone = getAdminPhone(username);

        if (body.object === 'page') {
            loggerService.writeLog(username, 'SYSTEM', null, `Recibido evento webhook de Meta Ads.`);
            for (const entry of body.entry) {
                for (const change of entry.changes) {
                    if (change.field !== 'leadgen') continue;

                    const leadId = change.value.leadgen_id;
                    console.log(`[Webhook] [${username}] Nuevo lead recibido: ID ${leadId}. Obteniendo datos...`);
                    loggerService.writeLog(username, 'SYSTEM', null, `Procesando nuevo Lead de Meta Ads. ID Leadgen: ${leadId}`);

                    const leadData = await getLeadData(username, leadId);

                    if (!leadData || !leadData.phone) {
                        console.error(`[Webhook] [${username}] No se pudo obtener el teléfono del lead.`);
                        loggerService.writeLog(username, 'SYSTEM', null, `⚠️ No se pudo obtener el teléfono para el Lead ID ${leadId}`);
                        if (adminPhone) {
                            await whatsappService.sendTextMessage(
                                username,
                                adminPhone,
                                `❌ Entró un lead (ID: ${leadId}) pero no pude obtener sus datos.\n¿El META_ACCESS_TOKEN de tu ClaudIA es correcto?`
                            );
                        }
                        continue;
                    }

                    const { name: leadName, phone: leadPhone, campaignName, campaignId } = leadData;
                    const matchedPathId = findPathForCampaign(username, campaignName, campaignId);

                    loggerService.writeLog(username, 'SYSTEM', leadPhone, `Lead de Meta Ads obtenido: "${leadName}" (${leadPhone}). Campaña: "${campaignName}"`);

                    if (whatsappService.isAutoMode(username)) {
                        console.log(`[Webhook] [${username}] Modo AUTO activo. Activando ClaudIA para ${leadName} (${leadPhone})...`);
                        loggerService.writeLog(username, 'SYSTEM', leadPhone, `Modo automático (AUTO) activo. Iniciando activación automática...`);

                        if (adminPhone) {
                            const campaignLabel = campaignName ? `\n📢 Campaña: ${campaignName}` : "";
                            const pathLabel = matchedPathId ? `\n🛣️ Path Inicial: ${matchedPathId}` : "";
                            await whatsappService.sendTextMessage(
                                username,
                                adminPhone,
                                `🤖 *LEAD AUTOMÁTICO - CLAUDIA (${username})*${campaignLabel}${pathLabel}\n\n👤 Nombre: ${leadName}\n📱 Teléfono: ${leadPhone}\n\nClaudIA ya lo está contactando.`
                            );
                        }

                        await whatsappService.activateLead(username, leadPhone, leadName, matchedPathId);

                    } else {
                        console.log(`[Webhook] [${username}] Modo MANUAL. Notificando al admin.`);
                        loggerService.writeLog(username, 'SYSTEM', leadPhone, `Modo manual (MANUAL) activo. Notificando al administrador por WhatsApp.`);
                        const campaignLabel = campaignName ? `\n📢 Campaña: ${campaignName}` : "";

                        const notification =
                            `📢 *NUEVO LEAD DE META ADS (ClaudIA: ${username})*${campaignLabel}\n\n` +
                            `👤 Nombre: ${leadName}\n` +
                            `📱 Teléfono: ${leadPhone}\n\n` +
                            `Para activarla, enviame al chat de ClaudIA:\n` +
                            `*/bot ${leadPhone} ${leadName}*`;

                        if (adminPhone) {
                            await whatsappService.sendTextMessage(username, adminPhone, notification);
                        }
                    }
                }
            }
        }
    } catch (error) {
        console.error(`[Webhook] [${username}] Error procesando evento:`, error);
        loggerService.writeLog(username, 'SYSTEM', null, `⚠️ Error en handleWebhook al procesar evento: ${error.message}`);
    }
};

module.exports = {
    verifyWebhook,
    handleWebhook,
};
