const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode');
const path = require('path');
const os = require('os');
const fs = require('fs');

const user = "GermanMazza";
const sessionDir = path.join(os.homedir(), `.wwebjs_session_${user}`);
const qrPath = path.join(__dirname, '..', '..', 'static', 'uploads', `qr_${user}.png`);
const statusPath = path.join(__dirname, '..', '..', 'static', 'uploads', `status_${user}.json`);

function writeStatus(status) {
    try {
        fs.writeFileSync(statusPath, JSON.stringify({ status, usuario: user, pid: process.pid, ts: Date.now() }));
        console.log(`[STATUS WRITTEN]: ${status}`);
    } catch(e){
        console.error("Error writing status:", e);
    }
}

writeStatus('connecting');

// Find local Chrome or Edge
let chromePath = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
if (!fs.existsSync(chromePath)) {
    chromePath = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
}
console.log("Using browser executable:", chromePath);

const client = new Client({
    authStrategy: new LocalAuth({ dataPath: sessionDir }),
    puppeteer: {
        executablePath: chromePath,
        headless: true,
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-accelerated-2d-canvas',
            '--no-first-run',
            '--no-zygote',
            '--disable-gpu'
        ]
    }
});

client.on('qr', async (qr) => {
    console.log("🎉🎉🎉 SUCCESS! QR CODE EMITTED BY WHATSAPP WEB PUPPETEER! 🎉🎉🎉");
    try {
        await qrcode.toFile(qrPath, qr);
        writeStatus('qr');
        console.log("SUCCESS! PNG file created at:", qrPath);
    } catch (err) {
        console.error("Error saving QR PNG:", err);
    }
});

client.on('ready', () => {
    console.log("WhatsApp Web Client is READY!");
    writeStatus('connected');
});

client.on('authenticated', () => {
    console.log("Authenticated successfully!");
});

client.on('auth_failure', msg => {
    console.error('AUTHENTICATION FAILURE', msg);
    writeStatus('disconnected');
});

client.on('disconnected', (reason) => {
    console.log('Client was logged out', reason);
    writeStatus('disconnected');
});

client.initialize();
