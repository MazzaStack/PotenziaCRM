const fs = require('fs');
const path = require('path');

const getAgentConfigPath = (username) => {
    const configsDir = path.join(__dirname, '../../configs');
    if (!fs.existsSync(configsDir)) {
        fs.mkdirSync(configsDir, { recursive: true });
    }
    return path.join(configsDir, `bot_config_${username}.json`);
};

const loadConfig = (username) => {
    const user = username || 'default';
    const configPath = getAgentConfigPath(user);

    const defaultConfig = {
        system: {
            botName: `ClaudIA Pro (${user})`,
            version: "2.0.0",
            mode: "boutique", // "boutique" or "catalog"
            industry: "Inmobiliaria",
            humanDelay: { min: 4, max: 7 },
            openMode: false,
            strangersOnly: true,
            onlyGreet: true,
            ignoreAudio: false,
            checkPreviousChat: false,
            previousChatHours: 24,
            blacklist: []
        },
        personality: {
            tone: "profesional, rioplatense, empático",
            globalGreeting: `¡Hola! 👋 Soy ClaudIA, la asistente virtual del asesor inmobiliario ${user}.`,
            initialQuestion: "¿En qué puedo ayudarte?",
            baseInstructions: "Eres una experta en Inmobiliaria. Tu objetivo es ayudar a los clientes de manera profesional, amable y eficiente."
        },
        catalog: {
            schema: [
                { id: "id", label: "ID", type: "id" },
                { id: "nombre", label: "Propiedad", type: "text", searchable: true },
                { id: "precio", label: "Precio", type: "text", searchable: false },
                { id: "descripcion", label: "Descripción", type: "text", searchable: true },
                { id: "link", label: "Enlace Web", type: "url", searchable: false }
            ],
            items: []
        },
        paths: [
            {
                "id": "vender",
                "name": "Vender Propiedad",
                "description": "Cuando el cliente quiere vender, tasar o publicar su propiedad.",
                "instructions": "Primero presentate: ¡Hola! 👋 Soy ClaudIA, la asistente virtual de la inmobiliaria.\nSiguiente: Habla como rioplatense Argentina formal, presentate como ClaudIA, la asistente virtual.\nTu objetivo es recolectar: 1) Si ya estuvo publicada en el pasado, 2) Si la decisión de venta está firme, 3) Si tiene escritura o es con boleto, 4) Si quiere vender para comprar otra cosa, 5) Plazos de venta. 6) cuantos titulares tiene la propiedad. Una pregunta a la vez, estilo rioplatense. \nUna vez terminado todo esto, le agradecemos al cliente y le avisamos que un asesor se contactará a la brevedad.\nIMPORTANTE: Si el cliente se despide o dice algo como \"ok\" o \"gracias\", decimos de nada amigablemente y luego no hay que seguir conversando",
                "steps": "Primero presentate: ¡Hola! 👋 Soy ClaudIA, la asistente virtual de la inmobiliaria.\nSiguiente: Habla como rioplatense Argentina formal, presentate como ClaudIA, la asistente virtual.\nTu objetivo es recolectar: 1) Si ya estuvo publicada en el pasado, 2) Si la decisión de venta está firme, 3) Si tiene escritura o es con boleto, 4) Si quiere vender para comprar otra cosa, 5) Plazos de venta. 6) cuantos titulares tiene la propiedad. Una pregunta a la vez, estilo rioplatense. \nUna vez terminado todo esto, le agradecemos al cliente y le avisamos que un asesor se contactará a la brevedad.\nIMPORTANTE: Si el cliente se despide o dice algo como \"ok\" o \"gracias\", decimos de nada amigablemente y luego no hay que seguir conversando"
            },
            {
                "id": "comprar",
                "name": "Comprar / Ver Propiedades",
                "description": "Cuando el cliente quiere ver casas publicadas para comprar o quiere más información sobre una propiedad",
                "instructions": "IMPORTANTE: Si sabes qué propiedad es, es obligatorio que el link de Zonaprop o Mercadolibre esté escrito textualmente en tu primer párrafo y saludar al mismo tiempo avisando que eres ClaudIA, la asistente virtual del asesor inmobiliario.\nSino sabemos cual es preguntamos algún dato para poder ubicarla. Si no podemos ubicarla le mostramos lo mas parecido a la que pide. No mencionar que tenemos propiedades en otros barrios o zonas.\n\nNunca ofrecer casas o departamentos o ph o lotes en zonas o lugares que no están en nuestro catálogo.\n\nAl terminar debes preguntarle si quiere visitar la propiedad que eligió y si quiere debes iniciar un cuestionario de precalificación:\n1. Si conoce la zona (si no la conoce le recomendamos que lo haga antes de ver la casa para estar seguros que la zona es la correcta) \n2. Si ya vendió su propiedad o si cuenta con la capacidad de hacer una oferta en el momento de la visita (queremos respetar que el propietario necesita vender y que la casa debe ser mostrada solo a personas que estén listas para hacer una oferta en el momento, a pedido del propietario).\nImportante: Si no vendió hay que preguntarle si le gustaría que nosotros le ayudemos a vender su propiedad. \nSi acepta, hay que preguntarle esto, una pregunta a la vez estilo rioplatense:\nA) Si su propiedad ya estuvo publicada, \nB) Si la decisión de venta está firme, \nC) Si tiene escritura o boleto\nD) Plazos de venta. \nE) cuantos titulares tiene la propiedad. \nSi no acepta (dice no, paso, etc.), finaliza la conversación amigablemente de forma cálida agradeciendo su tiempo y notificando que Germán se contactará a la brevedad.\nUna vez terminado todo esto, le agradecemos al cliente y le avisamos que un asesor se contactará a la brevedad.\nIMPORTANTE: Si el cliente se despide o dice algo como \"ok\" o \"gracias\", decimos de nada amigablemente y luego no hay que seguir conversando",
                "steps": "IMPORTANTE: Si sabes qué propiedad es, es obligatorio que el link de Zonaprop o Mercadolibre esté escrito textualmente en tu primer párrafo y saludar al mismo tiempo avisando que eres ClaudIA, la asistente virtual del asesor inmobiliario.\nSino sabemos cual es preguntamos algún dato para poder ubicarla. Si no podemos ubicarla le mostramos lo mas parecido a la que pide. No mencionar que tenemos propiedades en otros barrios o zonas.\n\nNunca ofrecer casas o departamentos o ph o lotes en zonas o lugares que no están en nuestro catálogo.\n\nAl terminar debes preguntarle si quiere visitar la propiedad que eligió y si quiere debes iniciar un cuestionario de precalificación:\n1. Si conoce la zona (si no la conoce le recomendamos que lo haga antes de ver la casa para estar seguros que la zona es la correcta) \n2. Si ya vendió su propiedad o si cuenta con la capacidad de hacer una oferta en el momento de la visita (queremos respetar que el propietario necesita vender y que la casa debe ser mostrada solo a personas que estén listas para hacer una oferta en el momento, a pedido del propietario).\nImportante: Si no vendió hay que preguntarle si le gustaría que nosotros le ayudemos a vender su propiedad. \nSi acepta, hay que preguntarle esto, una pregunta a la vez estilo rioplatense:\nA) Si su propiedad ya estuvo publicada, \nB) Si la decisión de venta está firme, \nC) Si tiene escritura o boleto\nD) Plazos de venta. \nE) cuantos titulares tiene la propiedad. \nSi no acepta (dice no, paso, etc.), finaliza la conversación amigablemente de forma cálida agradeciendo su tiempo y notificando que Germán se contactará a la brevedad.\nUna vez terminado todo esto, le agradecemos al cliente y le avisamos que un asesor se contactará a la brevedad.\nIMPORTANTE: Si el cliente se despide o dice algo como \"ok\" o \"gracias\", decimos de nada amigablemente y luego no hay que seguir conversando",
                "trigger": "Cuando el cliente quiere ver casas publicadas para comprar o quiere más información sobre una propiedad"
            },
            {
                "id": "hablarasesor",
                "name": "Hablar con Asesor",
                "description": "Cuando una persona pide hablar directamente con el asesor inmobiliario",
                "instructions": "Habla como rioplatense Argentina formal.\nClaudIA debe despedirse amablemente y avisar que un asesor se sumará al chat",
                "steps": "Habla como rioplatense Argentina formal.\nClaudIA debe despedirse amablemente y avisar que un asesor se sumará al chat",
                "trigger": "Cuando una persona pide hablar directamente con el asesor inmobiliario"
            }
        ],
        credentials: {
            licenseKey: "",
            groqApiKey: process.env.GROQ_API_KEY || "",
            adminPhone: process.env.ADMIN_PHONE || "",
            metaToken: process.env.META_ACCESS_TOKEN || "",
            metaVerifyToken: process.env.META_VERIFY_TOKEN || "",
            crmWebhookUrl: process.env.CRM_WEBHOOK_URL || "",
            crmWebhookToken: process.env.CRM_WEBHOOK_TOKEN || "",
            crmUsuarioAsignado: user,
            crmEnabled: true
        }
    };

    try {
        if (!fs.existsSync(configPath)) {
            return defaultConfig;
        }
        const data = fs.readFileSync(configPath, 'utf8');
        const savedConfig = JSON.parse(data);

        // Combinamos la configuración guardada con los valores por defecto
        return {
            system: { 
                onlyGreet: true, 
                strangersOnly: true, 
                ...defaultConfig.system, 
                ...savedConfig.system 
            },
            personality: { ...defaultConfig.personality, ...savedConfig.personality },
            catalog: { ...defaultConfig.catalog, ...savedConfig.catalog },
            paths: savedConfig.paths || defaultConfig.paths,
            credentials: { ...defaultConfig.credentials, ...savedConfig.credentials }
        };
    } catch (error) {
        console.error(`[Config] Error cargando configuración para ${user}:`, error);
        return defaultConfig;
    }
};

const saveConfig = (username, newConfig) => {
    const user = username || 'default';
    const configPath = getAgentConfigPath(user);
    try {
        fs.writeFileSync(configPath, JSON.stringify(newConfig, null, 2));
        console.log(`[Config] Configuración guardada correctamente para ${user}.`);
        return true;
    } catch (error) {
        console.error(`[Config] Error guardando configuración para ${user}:`, error);
        return false;
    }
};

module.exports = {
    loadConfig,
    saveConfig
};
