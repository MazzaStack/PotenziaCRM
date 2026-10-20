try {
    const crypto = require('@whiskeysockets/baileys/lib/Utils/crypto');
    console.log("Crypto exports:", Object.keys(crypto));
    console.log("HKDF test:", typeof crypto.hkdf);
} catch (e) {
    console.error("HKDF import error:", e);
}
