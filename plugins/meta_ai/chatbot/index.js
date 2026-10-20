require('dotenv').config();
const express = require('express');
const fs = require('fs');
const path = require('path');

const app = express();
app.use(express.json({ limit: '10mb' }));
app.use(express.urlencoded({ limit: '10mb', extended: true }));
app.use(express.static('public')); // Serve dashboard files

const PORT = process.env.PORT || 3000;

// Import routes
const webhookRoutes = require('./src/routes/webhookRoutes');
const configRoutes = require('./src/routes/configRoutes');

// Inject username parameter into config routes
app.use('/webhook/:username', (req, res, next) => {
    req.username = req.params.username;
    next();
}, webhookRoutes);

app.use('/api/config/:username', (req, res, next) => {
    req.username = req.params.username;
    next();
}, configRoutes);

// WhatsApp session routes for Flask proxying
const whatsappService = require('./src/services/whatsappService');

app.get('/api/whatsapp/:username/status', (req, res) => {
    const username = req.params.username;
    const status = whatsappService.getConnectionStatus(username);
    res.json({ status });
});

app.get('/api/whatsapp/:username/qr', (req, res) => {
    const username = req.params.username;
    const qr = whatsappService.getQR(username);
    const status = whatsappService.getConnectionStatus(username);
    res.json({ qr, status });
});

app.post('/api/whatsapp/:username/start', async (req, res) => {
    const username = req.params.username;
    try {
        await whatsappService.initialize(username);
        res.json({ status: 'started', message: `WhatsApp bot session starting for ${username}` });
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
});

app.post('/api/whatsapp/:username/logout', async (req, res) => {
    const username = req.params.username;
    try {
        await whatsappService.logout(username);
        res.json({ status: 'disconnected', message: `WhatsApp logged out for ${username}` });
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
});

app.get('/status', (req, res) => {
    res.send('Meta AI Chatbot Connector Multi-Agent Engine is running.');
});

// Startup auto-loader
const startBots = async () => {
    const configsDir = path.join(__dirname, 'configs');
    if (fs.existsSync(configsDir)) {
        const files = fs.readdirSync(configsDir);
        for (const file of files) {
            if (file.startsWith('bot_config_') && file.endsWith('.json')) {
                const username = file.replace('bot_config_', '').replace('.json', '');
                if (username && username !== 'default') {
                    const authDir = path.join(__dirname, `.baileys_auth_${username}`);
                    const hasCreds = fs.existsSync(path.join(authDir, 'creds.json'));
                    if (hasCreds) {
                        console.log(`[Startup] Auto-initializing socket for linked agent: ${username}`);
                        try {
                            whatsappService.initialize(username);
                        } catch (err) {
                            console.error(`[Startup] Failed starting agent socket for ${username}:`, err.message);
                        }
                    } else {
                        console.log(`[Startup] Skipping unlinked agent socket for: ${username}`);
                    }
                }
            }
        }
    }
};

startBots();

app.listen(PORT, () => {
    console.log(`Server is listening on port ${PORT}`);
});
