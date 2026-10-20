// test_status.js - Testea el envío de status via Baileys v7 directamente
// Ejecutar: node test_status.js
const { default: makeWASocket, useMultiFileAuthState, fetchLatestBaileysVersion } = require('@whiskeysockets/baileys');
const pino = require('pino');
const fs = require('fs');
const path = require('path');
const os = require('os');

const usuario = 'GermanMazza';
const sessionDir = path.join(os.homedir(), `.whatsapp_bot_session_${usuario}`);
const testImagePath = path.resolve('static/uploads/historias');

// Buscar primera imagen de historias disponible
let testFile = null;
try {
    const files = fs.readdirSync(testImagePath).filter(f => /\.(jpg|jpeg|png)$/i.test(f));
    if (files.length > 0) testFile = path.join(testImagePath, files[files.length - 1]);
} catch(e) {}

if (!testFile) {
    console.error('❌ No hay imágenes en static/uploads/historias para testear');
    process.exit(1);
}

console.log(`\n🔍 TEST: Enviando status con imagen: ${testFile}`);
console.log(`📁 Sesión: ${sessionDir}\n`);

async function run() {
    const { version } = await fetchLatestBaileysVersion();
    console.log(`📦 Baileys version: ${version.join('.')}`);

    const { state, saveCreds } = await useMultiFileAuthState(sessionDir);
    const sock = makeWASocket({
        version,
        auth: state,
        logger: pino({ level: 'silent' }),
        printQRInTerminal: false,
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', async ({ connection, lastDisconnect }) => {
        if (connection === 'open') {
            console.log('✅ WhatsApp conectado\n');

            const imgBuffer = fs.readFileSync(testFile);

            // Test 1: statusJidList vacío
            console.log('🧪 TEST 1: statusJidList = [] (vacío)');
            try {
                const r1 = await sock.sendMessage('status@broadcast', { image: imgBuffer, caption: 'Test 1 - lista vacía' }, { statusJidList: [] });
                console.log(`   → Resultado: ${JSON.stringify(r1?.key)}`);
            } catch(e) {
                console.log(`   → ERROR: ${e.message}`);
            }

            await new Promise(r => setTimeout(r, 3000));

            // Test 2: sin statusJidList
            console.log('\n🧪 TEST 2: sin statusJidList (omitido)');
            try {
                const r2 = await sock.sendMessage('status@broadcast', { image: imgBuffer, caption: 'Test 2 - sin lista' });
                console.log(`   → Resultado: ${JSON.stringify(r2?.key)}`);
            } catch(e) {
                console.log(`   → ERROR: ${e.message}`);
            }

            await new Promise(r => setTimeout(r, 3000));

            // Test 3: usar getAllContacts o roster
            console.log('\n🧪 TEST 3: obteniendo contactos del socket...');
            try {
                // En Baileys v7 se puede obtener el roster
                const contacts = Object.keys(sock.authState?.creds?.routingInfo || {});
                console.log(`   → Contactos en routingInfo: ${contacts.length}`);
            } catch(e) {
                console.log(`   → ERROR: ${e.message}`);
            }

            console.log('\n✅ Tests completados. Cerrando...');
            await sock.end();
            process.exit(0);
        } else if (connection === 'close') {
            const code = lastDisconnect?.error?.output?.statusCode;
            console.error(`❌ Conexión cerrada. StatusCode: ${code}`);
            if (code !== 401) setTimeout(run, 3000);
            else process.exit(1);
        }
    });
}

run().catch(e => {
    console.error('ERROR FATAL:', e);
    process.exit(1);
});
