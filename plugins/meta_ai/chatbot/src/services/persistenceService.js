const fs = require('fs');
const path = require('path');

const getAgentStatePath = (username) => {
    const configsDir = path.join(__dirname, '../../configs');
    if (!fs.existsSync(configsDir)) {
        fs.mkdirSync(configsDir, { recursive: true });
    }
    return path.join(configsDir, `bot_state_${username}.json`);
};

const defaultState = {
    allowedLeads: [],
    leadNames: {},
    humanIntervention: {},
    autoMode: false,
    activeChatsLastMessageTime: {}
};

const loadState = (username) => {
    const user = username || 'default';
    const stateFile = getAgentStatePath(user);
    try {
        if (fs.existsSync(stateFile)) {
            const raw = fs.readFileSync(stateFile, 'utf-8');
            const parsed = JSON.parse(raw);
            console.log(`[Persistencia] Estado para ${user} cargado desde ${stateFile}`);
            return parsed;
        }
    } catch (error) {
        console.error(`[Persistencia] Error al leer estado de ${user}, iniciando desde cero:`, error.message);
    }
    return { ...defaultState };
};

const saveState = (username, state) => {
    const user = username || 'default';
    const stateFile = getAgentStatePath(user);
    try {
        const serializable = {
            allowedLeads: [...state.allowedLeads],
            leadNames: Object.fromEntries(state.leadNames),
            humanIntervention: state.humanIntervention, // This is already a plain object or map status
            autoMode: state.autoMode,
            activeChatsLastMessageTime: state.activeChatsLastMessageTime ? Object.fromEntries(state.activeChatsLastMessageTime) : {},
            lidToJidMap: state.lidToJidMap ? Object.fromEntries(state.lidToJidMap) : {}
        };
        fs.writeFileSync(stateFile, JSON.stringify(serializable, null, 2), 'utf-8');
    } catch (error) {
        console.error(`[Persistencia] Error al guardar estado de ${user}:`, error.message);
    }
};

module.exports = { loadState, saveState };
