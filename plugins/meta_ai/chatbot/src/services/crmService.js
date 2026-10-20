const axios = require('axios');
const configService = require('./configService');
const loggerService = require('./loggerService');

/**
 * Genera la intención resumida del lead utilizando la API de Groq si está disponible.
 * De lo contrario o si falla, devuelve un fallback aceptable.
 */
const generateIntention = async (username, mensajeOriginal) => {
    if (!mensajeOriginal || mensajeOriginal.trim() === '') {
        return "El lead se registró en el chatbot sin enviar un mensaje inicial aún.";
    }

    const config = configService.loadConfig(username);
    const apiKey = config.credentials?.groqApiKey || process.env.GROQ_API_KEY;

    if (!apiKey) {
        console.log(`[CRM] [${username}] Sin API Key de Groq para resumen. Usando mensaje original como fallback.`);
        return mensajeOriginal;
    }

    try {
        const Groq = require('groq-sdk');
        const groq = new Groq({ apiKey });

        const completion = await groq.chat.completions.create({
            model: 'openai/gpt-oss-20b',
            messages: [
                {
                    role: 'system',
                    content: 'Dada la consulta o mensaje inicial del lead para una inmobiliaria, genera un resumen cortísimo y estructurado (1 o 2 oraciones máximo) de su intención (qué busca, presupuesto si lo menciona, urgencia). Sé extremadamente conciso, amigable y directo en español.'
                },
                {
                    role: 'user',
                    content: mensajeOriginal
                }
            ],
            max_tokens: 300,
            temperature: 0.5
        });

        const summary = completion.choices[0].message.content.trim();
        return summary || mensajeOriginal;
    } catch (e) {
        console.error(`[CRM] [${username}] Error al generar la intención con Groq:`, e.message);
        return mensajeOriginal;
    }
};

/**
 * Envía un lead nuevo al CRM de Ferrari Propiedades.
 * Es un proceso fire-and-forget seguro (no-blocking, no-crash).
 * 
 * @param {string} username - Agente actual
 * @param {Object} leadInfo
 * @param {string} leadInfo.nombre - Nombre del lead
 * @param {string} leadInfo.telefono - Teléfono raw del lead (será normalizado a números únicamente)
 * @param {string} [leadInfo.mensajeOriginal] - Mensaje de inicio del cliente
 */
const sendLeadToCRM = async (username, { nombre, telefono, mensajeOriginal }) => {
    try {
        const config = configService.loadConfig(username);
        const webhookUrl = config.credentials?.crmWebhookUrl;
        const crmEnabled = config.credentials?.crmEnabled;

        if (crmEnabled === false) {
            console.log(`[CRM] [${username}] Integración CRM desactivada por el usuario en la configuración.`);
            return;
        }

        if (!webhookUrl || webhookUrl.trim() === '') {
            console.log(`[CRM] [${username}] Integración CRM omitida: No se configuró URL del Webhook.`);
            return;
        }

        // Limpiar el teléfono para enviar solo dígitos
        let cleanPhone = telefono ? telefono.toString().replace(/\D/g, '') : '';
        if (!cleanPhone) {
            console.error(`[CRM] [${username}] Error al enviar lead al CRM: El teléfono es obligatorio y está vacío.`);
            return;
        }

        console.log(`[CRM] [${username}] Procesando envío de lead al CRM para ${nombre || 'Lead Meta AI'} (${cleanPhone})...`);
        loggerService.writeLog(username, 'CRM', cleanPhone, `Iniciando envío de lead al CRM. Mensaje original: "${mensajeOriginal || '[Vacio]'}"`);

        // Generar la intención de forma asíncrona
        const intencion = await generateIntention(username, mensajeOriginal);
        loggerService.writeLog(username, 'CRM', cleanPhone, `Intención resumida con Groq: "${intencion}"`);

        // Construir Payload
        const payload = {
            nombre: nombre && nombre.trim() !== '' ? nombre : 'Lead Meta AI',
            telefono: cleanPhone,
            mensaje_original: mensajeOriginal || 'Lead ingresado desde campaña Meta Ads',
            intencion: intencion
        };

        // Agregar usuario_asignado si está configurado en las credenciales
        const usuarioAsignado = config.credentials?.crmUsuarioAsignado;
        if (usuarioAsignado && usuarioAsignado.trim() !== '') {
            payload.usuario_asignado = usuarioAsignado.trim();
        }

        // Configurar Headers
        const headers = {
            'Content-Type': 'application/json'
        };

        const token = config.credentials?.crmWebhookToken;
        if (token && token.trim() !== '') {
            headers['Authorization'] = `Bearer ${token.trim()}`;
        }

        console.log(`[CRM] [${username}] Enviando POST a ${webhookUrl} con payload:`, JSON.stringify(payload, null, 2));

        const response = await axios.post(webhookUrl, payload, { headers, timeout: 8000 });

        if (response.status === 200 || response.status === 201) {
            console.log(`[CRM] [${username}] ✅ Lead enviado con éxito. Respuesta del CRM:`, JSON.stringify(response.data));
            loggerService.writeLog(username, 'CRM', cleanPhone, `✅ Lead enviado con éxito. Status: ${response.status}`);
        } else {
            console.warn(`[CRM] [${username}] ⚠️ El CRM respondió con status ${response.status}:`, JSON.stringify(response.data));
            loggerService.writeLog(username, 'CRM', cleanPhone, `⚠️ CRM respondió con status ${response.status}: ${JSON.stringify(response.data)}`);
        }
    } catch (error) {
        let cleanPhone = telefono ? telefono.toString().replace(/\D/g, '') : 'unknown';
        if (error.response) {
            console.error(`[CRM] [${username}] ❌ Error en respuesta del CRM (${error.response.status}):`, JSON.stringify(error.response.data));
            loggerService.writeLog(username, 'ERROR', cleanPhone, `❌ Error en respuesta del CRM (${error.response.status}): ${JSON.stringify(error.response.data)}`);
        } else {
            console.error(`[CRM] [${username}] ❌ Error de red o conexión al enviar al CRM:`, error.message);
            loggerService.writeLog(username, 'ERROR', cleanPhone, `❌ Error de red/conexión al CRM: ${error.message}`);
        }
    }
};

module.exports = {
    sendLeadToCRM
};
