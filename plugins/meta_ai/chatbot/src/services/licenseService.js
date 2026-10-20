const axios = require('axios');
const os = require('os');

const API_BASE_URL = 'https://www.ideascloud.com.ar/';
const INTERNAL_API_KEY = '123Q5OXT13in3LGjM9F3';

/**
 * Verifica la validez de una licencia con el servidor de Ideascloud.
 * @param {string} licenseKey - La clave de licencia a verificar.
 * @returns {Promise<{valid: boolean, message: string, status: string}>}
 */
const verifyLicense = async (licenseKey) => {
    // License verification removed as requested by the user.
    console.log(`[Licencia] ✅ Licencia omitida y tratada como VÁLIDA (Siempre activa).`);
    return { 
        valid: true, 
        message: 'Licencia activa y válida (Bypass).', 
        status: 'active',
        code: 500 
    };
};

module.exports = {
    verifyLicense
};
