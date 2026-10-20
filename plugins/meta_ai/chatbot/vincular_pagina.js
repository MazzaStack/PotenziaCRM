require('dotenv').config();
const axios = require('axios');

async function vincularPagina() {
    const userToken = process.env.META_ACCESS_TOKEN;
    const pageId = "867105989826812"; // ID proporcionado por Germán
    
    if (!userToken || userToken.length < 20) {
        console.error('❌ ERROR: No hay un token en META_ACCESS_TOKEN del archivo .env');
        return;
    }

    try {
        console.log(`--- INTENTANDO VINCULACIÓN DIRECTA (ID: ${pageId}) ---`);
        
        // 1. Intentar obtener el token de la página específica
        console.log(`🔍 Buscando token de la página ${pageId}...`);
        const pageResponse = await axios.get(`https://graph.facebook.com/v19.0/${pageId}?fields=access_token,name&access_token=${userToken}`);
        
        const pageAccessToken = pageResponse.data.access_token;
        const pageName = pageResponse.data.name;

        if (!pageAccessToken) {
            console.error(`❌ ERROR: No se pudo obtener el token de la página "${pageName}".`);
            console.log('Esto suele pasar si no seleccionaste esta página en la ventana de permisos de Facebook.');
            return;
        }

        console.log(`✅ Token de página obtenido correctamente para: ${pageName}`);

        // 2. Ejecutar la suscripción
        console.log(`🔗 Vinculando la App InsPublish a "${pageName}"...`);
        const subscribeResponse = await axios.post(`https://graph.facebook.com/v19.0/${pageId}/subscribed_apps`, {
            subscribed_fields: 'leadgen'
        }, {
            params: { access_token: pageAccessToken }
        });

        if (subscribeResponse.data.success) {
            console.log('=======================================================');
            console.log(`🎉 ¡ÉXITO TOTAL! La página "${pageName}" está vinculada.`);
            console.log('Ahora los leads de Meta Ads llegarán a tu programa.');
            console.log('=======================================================');
                
            console.log('\n💡 Tip final: Actualizá tu .env con este token de página:');
            console.log(`META_ACCESS_TOKEN=${pageAccessToken}`);
        }

    } catch (error) {
        console.error('❌ ERROR EN LA VINCULACIÓN DIRECTA:');
        if (error.response) {
            console.error(JSON.stringify(error.response.data, null, 2));
        } else {
            console.error(error.message);
        }
    }
}

vincularPagina();
