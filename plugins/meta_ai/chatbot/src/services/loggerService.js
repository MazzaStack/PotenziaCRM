const fs = require('fs');
const path = require('path');

const getAgentLogPath = (username) => {
    const logsDir = path.join(__dirname, '../../logs');
    if (!fs.existsSync(logsDir)) {
        fs.mkdirSync(logsDir, { recursive: true });
    }
    return path.join(logsDir, `bot_audit_${username || 'default'}.log`);
};

const writeLog = (username, category, phone, message) => {
    try {
        const timestamp = new Date().toLocaleString('es-AR', { timeZone: 'America/Argentina/Buenos_Aires' });
        const phoneStr = phone ? ` [${phone.split('@')[0]}]` : '';
        const line = `[${timestamp}] [${category}]${phoneStr} ${message}\n`;
        const logFile = getAgentLogPath(username);
        fs.appendFileSync(logFile, line, 'utf-8');

        // Limitar tamaño del archivo ocasionalmente (1% de probabilidad en cada escritura)
        if (Math.random() < 0.01) {
            rotateLogs(username);
        }
    } catch (err) {
        console.error(`[Logger] [${username}] Error escribiendo log:`, err.message);
    }
};

const rotateLogs = (username) => {
    try {
        const logFile = getAgentLogPath(username);
        if (!fs.existsSync(logFile)) return;
        const stats = fs.statSync(logFile);
        const maxSizeBytes = 2 * 1024 * 1024; // 2 MB
        if (stats.size > maxSizeBytes) {
            console.log(`[Logger] [${username}] El archivo de log superó los 2MB. Recortando a las últimas 1000 líneas...`);
            const data = fs.readFileSync(logFile, 'utf-8');
            const lines = data.split('\n');
            const keptLines = lines.slice(-1000);
            fs.writeFileSync(logFile, keptLines.join('\n'), 'utf-8');
        }
    } catch (err) {
        console.error(`[Logger] [${username}] Error rotando logs:`, err.message);
    }
};

const getLogs = (username, limit = 200) => {
    try {
        const logFile = getAgentLogPath(username);
        if (!fs.existsSync(logFile)) return "Aún no hay registros de auditoría para este agente.";
        const data = fs.readFileSync(logFile, 'utf-8');
        const lines = data.split('\n').filter(l => l.trim().length > 0);
        return lines.slice(-limit).join('\n');
    } catch (err) {
        console.error(`[Logger] [${username}] Error leyendo logs:`, err.message);
        return "Error leyendo logs: " + err.message;
    }
};

module.exports = { writeLog, getLogs };
