const express = require('express');
const router = express.Router();
const webhookController = require('../controllers/webhookController');

// Ruta GET para la verificación de webhooks de Meta (Instagram/WhatsApp/Facebook)
router.get('/', webhookController.verifyWebhook);

// Ruta POST para recibir los eventos (Webhooks)
router.post('/', webhookController.handleWebhook);

module.exports = router;
