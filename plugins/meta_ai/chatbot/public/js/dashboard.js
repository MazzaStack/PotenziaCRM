let currentConfig = {
    system: {},
    personality: {},
    catalog: { schema: [], items: [], synonymRules: [] },
    paths: [],
    credentials: {}
};

// --- NAVEGACIÓN ---
document.querySelectorAll('#mainNav li').forEach(item => {
    item.addEventListener('click', () => {
        const section = item.getAttribute('data-section');
        
        // Update active class
        document.querySelectorAll('#mainNav li').forEach(li => li.classList.remove('active'));
        item.classList.add('active');

        // Show/Hide sections
        document.getElementById('monitorSection').style.display = (section === 'monitor') ? 'block' : 'none';
        document.getElementById('cerebroSection').style.display = (section === 'cerebro') ? 'block' : 'none';
        document.getElementById('catalogSection').style.display = (section === 'catalog') ? 'block' : 'none';
        document.getElementById('systemSection').style.display = (section === 'system') ? 'block' : 'none';

        // Update title and save button visibility
        const titles = {
            'monitor': 'Monitor del Sistema',
            'cerebro': 'Cerebro e IA',
            'catalog': 'Catálogo Inteligente',
            'system': 'Configuración de Sistema'
        };
        document.getElementById('pageTitle').innerText = titles[section];
        document.getElementById('saveBtn').style.display = (section === 'monitor') ? 'none' : 'block';

        if (section === 'monitor') loadLeads();
    });
});

async function loadLeads() {
    const container = document.getElementById('leadsContainer');
    container.innerHTML = '<p style="color: var(--text-muted)">Actualizando lista...</p>';
    
    try {
        const response = await fetch('/api/config/leads');
        const leads = await response.json();
        
        if (leads.length === 0) {
            container.innerHTML = '<p style="color: var(--text-muted)">No hay leads activos en este momento.</p>';
            return;
        }

        let html = '<table style="width: 100%; border-collapse: collapse;">';
        html += '<tr style="color: var(--text-muted); font-size: 0.8rem; text-align: left;"><th style="padding-bottom: 1rem">NOMBRE</th><th style="padding-bottom: 1rem">TELÉFONO</th><th style="padding-bottom: 1rem">ESTADO IA</th><th style="padding-bottom: 1rem">ACCIÓN</th></tr>';
        
        leads.forEach(lead => {
            const statusColor = lead.isPaused ? '#ef4444' : '#10b981';
            const statusText = lead.isPaused ? 'Pausada (Humano) ⏸️' : 'Activa ✅';
            const toggleText = lead.isPaused ? '▶️ Activar IA' : '⏸️ Pausar IA';
            const toggleBg = lead.isPaused ? '#10b981' : '#f59e0b';
            
            html += `
                <tr style="border-top: 1px solid var(--glass-border);">
                    <td style="padding: 1rem 0;">${lead.name}</td>
                    <td style="padding: 1rem 0;">${lead.phone.split('@')[0]}</td>
                    <td style="padding: 1rem 0; color: ${statusColor}; font-weight: 600;">${statusText}</td>
                    <td style="padding: 1rem 0; display: flex; gap: 8px;">
                        <button onclick="toggleLeadPause('${lead.phone}', ${!lead.isPaused})" style="padding: 6px 12px; font-size: 0.75rem; border-radius: 6px; border: none; cursor: pointer; color: white; background: ${toggleBg}; font-weight: bold; transition: opacity 0.2s;">${toggleText}</button>
                        <button class="btn-remove" onclick="deleteLead('${lead.phone}')" style="padding: 6px 12px; font-size: 0.75rem; border-radius: 6px; border: none; cursor: pointer; color: white; background: #ef4444; font-weight: bold;">Eliminar</button>
                    </td>
                </tr>
            `;
        });
        
        html += '</table>';
        container.innerHTML = html;
    } catch (error) {
        container.innerHTML = '<p style="color: #ef4444">Error al cargar leads.</p>';
    }
}

async function toggleLeadPause(phone, isPaused) {
    try {
        const response = await fetch(`/api/config/leads/${encodeURIComponent(phone)}/toggle-pause`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ isPaused })
        });
        
        if (response.ok) {
            loadLeads(); // Recargar la lista
            showToast(isPaused ? "IA Pausada para este lead" : "IA Reactivada para este lead");
        } else {
            alert('Error al cambiar el estado del lead.');
        }
    } catch (error) {
        alert('Error de conexión.');
    }
}

async function deleteLead(phone) {
    if (!confirm('¿Estás seguro de eliminar el historial y la sesión de este lead?')) return;
    
    try {
        const response = await fetch(`/api/config/leads/${encodeURIComponent(phone)}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            loadLeads(); // Recargar lista
        } else {
            alert('Error al eliminar lead.');
        }
    } catch (error) {
        alert('Error de conexión.');
    }
}

// Cargar configuración al iniciar
async function loadConfig() {
    try {
        const response = await fetch('/api/config');
        currentConfig = await response.json();
        
        // Cerebro
        document.getElementById('botName').value = currentConfig.system?.botName || "";
        document.getElementById('industry').value = currentConfig.system?.industry || "";
        document.getElementById('tone').value = currentConfig.personality?.tone || "";
        document.getElementById('baseInstructions').value = currentConfig.personality?.baseInstructions || "";
        document.getElementById('globalGreeting').value = currentConfig.personality?.globalGreeting || "";
        document.getElementById('initialQuestion').value = currentConfig.personality?.initialQuestion || "";
        
        // Catálogo
        document.getElementById('botMode').value = currentConfig.system?.mode || "boutique";
        if (!currentConfig.catalog.synonymRules) currentConfig.catalog.synonymRules = [];
        renderCatalog();
        renderSynonymRules();

        // Sistema
        document.getElementById('openMode').checked = currentConfig.system?.openMode || false;
        document.getElementById('strangersOnly').checked = currentConfig.system?.strangersOnly || false;
        document.getElementById('checkPreviousChat').checked = currentConfig.system?.checkPreviousChat || false;
        document.getElementById('previousChatHours').value = currentConfig.system?.previousChatHours ?? 24;
        document.getElementById('blacklist').value = (currentConfig.system?.blacklist || []).join('\n');
        document.getElementById('replyDelayMin').value = currentConfig.system?.humanDelay?.min ?? 4;
        document.getElementById('replyDelayMax').value = currentConfig.system?.humanDelay?.max ?? 7;

        // Credenciales
        document.getElementById('licenseKey').value = currentConfig.credentials?.licenseKey || "";
        document.getElementById('groqApiKey').value = currentConfig.credentials?.groqApiKey || "";
        document.getElementById('adminPhone').value = currentConfig.credentials?.adminPhone || "";
        document.getElementById('metaToken').value = currentConfig.credentials?.metaToken || "";
        document.getElementById('metaVerifyToken').value = currentConfig.credentials?.metaVerifyToken || "";
        document.getElementById('crmWebhookUrl').value = currentConfig.credentials?.crmWebhookUrl || "";
        document.getElementById('crmWebhookToken').value = currentConfig.credentials?.crmWebhookToken || "";
        document.getElementById('crmUsuarioAsignado').value = currentConfig.credentials?.crmUsuarioAsignado || "";
        document.getElementById('crmEnabled').checked = currentConfig.credentials?.crmEnabled !== false;

        renderPaths();
        checkLicenseStatus();
        loadLeads();
    } catch (error) {
        console.error('Error cargando config:', error);
    }
}

// ==========================================
// CAMBIO DE MODO Y SCHEMA
// ==========================================
function onModeChange(newMode) {
    if (!confirm("¿Cambiar el modo? Esto actualizará la estructura de columnas del catálogo. Se perderán las columnas personalizadas actuales (no los datos).")) {
        document.getElementById('botMode').value = currentConfig.system.mode;
        return;
    }

    currentConfig.system.mode = newMode;
    
    if (newMode === 'boutique') {
        currentConfig.catalog.schema = [
            { id: "id", label: "ID", type: "id" },
            { id: "nombre", label: "Propiedad", type: "text", searchable: true },
            { id: "precio", label: "Precio", type: "text", searchable: false },
            { id: "descripcion", label: "Descripción", type: "text", searchable: true },
            { id: "link", label: "Enlace Web", type: "url", searchable: false }
        ];
    } else {
        currentConfig.catalog.schema = [
            { id: "id", label: "ID", type: "id" },
            { id: "nombre", label: "Nombre", type: "text", searchable: true },
            { id: "precio", label: "Precio", type: "text", searchable: false },
            { id: "link", label: "Enlace Web", type: "url", searchable: false },
            { id: "descripcion", label: "Descripción", type: "text", searchable: true }
        ];
    }
    
    renderCatalog();
    showToast("Estructura de catálogo actualizada a modo " + newMode);
}

// ==========================================
// IMPORTACIÓN EXCEL
// ==========================================
let tempExcelData = [];
let tempExcelHeaders = [];

function handleExcelFile(input) {
    const file = input.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (e) => {
        const data = new Uint8Array(e.target.result);
        const workbook = XLSX.read(data, { type: 'array' });
        const firstSheet = workbook.Sheets[workbook.SheetNames[0]];
        
        // Convertir a JSON
        const jsonData = XLSX.utils.sheet_to_json(firstSheet, { header: 1 });
        
        if (jsonData.length < 2) {
            alert("El archivo parece estar vacío o no tener encabezados.");
            return;
        }

        tempExcelHeaders = jsonData[0]; // Primera fila
        tempExcelData = jsonData.slice(1); // Resto de filas
        
        renderMappingModal();
    };
    reader.readAsArrayBuffer(file);
}

function renderMappingModal() {
    const container = document.getElementById('mappingFields');
    container.innerHTML = '';
    
    document.getElementById('mappingModal').style.display = 'flex';

    currentConfig.catalog.schema.forEach(col => {
        if (col.type === 'id') return;

        const div = document.createElement('div');
        div.style.display = 'flex';
        div.style.alignItems = 'center';
        div.style.justifyContent = 'space-between';
        div.style.marginBottom = '1rem';
        div.style.background = 'rgba(255,255,255,0.03)';
        div.style.padding = '12px';
        div.style.borderRadius = '8px';

        div.innerHTML = `
            <div style="font-weight: 600; color: white;">${col.label}</div>
            <select id="map_${col.id}" style="width: 250px; padding: 8px; border-radius: 6px; background: #222; color: white; border: 1px solid #444;">
                <option value="">-- Ignorar este campo --</option>
                ${tempExcelHeaders.map((header, index) => `<option value="${index}">${header}</option>`).join('')}
            </select>
        `;
        container.appendChild(div);
    });
}

function closeMappingModal() {
    document.getElementById('mappingModal').style.display = 'none';
    document.getElementById('excelInput').value = '';
}

function applyExcelMapping() {
    const mapping = {};
    let mappedAny = false;

    currentConfig.catalog.schema.forEach(col => {
        if (col.type === 'id') return;
        const index = document.getElementById(`map_${col.id}`).value;
        if (index !== "") {
            mapping[col.id] = parseInt(index);
            mappedAny = true;
        }
    });

    if (!mappedAny) {
        alert("Debes mapear al menos una columna.");
        return;
    }

    const newItems = tempExcelData.map((row, i) => {
        const item = { id: (Date.now() + i).toString() };
        for (const [colId, excelIdx] of Object.entries(mapping)) {
            item[colId] = row[excelIdx] || "";
        }
        return item;
    });

    if (!currentConfig.catalog.items) currentConfig.catalog.items = [];
    currentConfig.catalog.items = [...currentConfig.catalog.items, ...newItems];

    renderCatalog();
    closeMappingModal();
    showToast(`Se importaron ${newItems.length} ítems correctamente.`);
}

function renderPaths() {
    const container = document.getElementById('pathsContainer');
    container.innerHTML = '';
    
    (currentConfig.paths || []).forEach((path, index) => {
        const div = document.createElement('div');
        div.className = 'card path-item';
        div.innerHTML = `
            <div class="path-header">
                <h3>Camino #${index + 1}: ${path.name || 'Nuevo'}</h3>
                <button class="btn-remove" onclick="removePath(${index})">Eliminar</button>
            </div>
            <div class="form-group">
                <label>ID del Camino (Sin espacios)</label>
                <input type="text" value="${path.id || ''}" onchange="updatePath(${index}, 'id', this.value)">
            </div>
            <div class="form-group">
                <label>Nombre Amigable</label>
                <input type="text" value="${path.name || ''}" onchange="updatePath(${index}, 'name', this.value)">
            </div>
            <div class="form-group">
                <label>¿Cuándo se activa? (Trigger / Contexto)</label>
                <textarea onchange="updatePath(${index}, 'trigger', this.value)" rows="2">${path.trigger || path.description || ''}</textarea>
            </div>
            <div class="form-group">
                <label>Pasos a seguir (Instructions)</label>
                <textarea onchange="updatePath(${index}, 'steps', this.value)" rows="5">${path.steps || path.instructions || ''}</textarea>
            </div>
            <div class="form-group">
                <label>Campañas de Meta Ads Asociadas (Nombres o IDs separados por coma)</label>
                <input type="text" value="${path.metaCampaigns || ''}" placeholder="Ej: Venta Triplex, 12036302296" onchange="updatePath(${index}, 'metaCampaigns', this.value)">
            </div>
            <div style="background: rgba(255, 255, 255, 0.03); padding: 12px; border-radius: 8px; margin-top: 10px; border: 1px solid var(--glass-border);">
                <h4 style="margin-top: 0; margin-bottom: 10px; font-size: 0.9rem;">👋 Saludos Iniciales Personalizados del Path</h4>
                <div class="form-group" style="display: flex; align-items: center; gap: 8px; margin-bottom: 10px;">
                    <input type="checkbox" id="skip_welcome_${index}" ${path.skipWelcome ? 'checked' : ''} onchange="updatePath(${index}, 'skipWelcome', this.checked)" style="width: auto;">
                    <label for="skip_welcome_${index}" style="margin: 0; font-size: 0.8rem;"><b>Omitir Saludos Iniciales:</b> Esperar que el cliente escriba primero antes de responder.</label>
                </div>
                <div class="form-group" style="margin-bottom: 10px;">
                    <label style="font-size: 0.8rem;">Saludo Inicial A (Dejar vacío para usar saludo global)</label>
                    <input type="text" value="${path.welcomeMessageA || ''}" placeholder="Ej: ¡Hola {name}! 👋 Soy ClaudIA, asesora de..." onchange="updatePath(${index}, 'welcomeMessageA', this.value)">
                </div>
                <div class="form-group" style="margin-bottom: 0;">
                    <label style="font-size: 0.8rem;">Pregunta Inicial B (Dejar vacío para usar pregunta global)</label>
                    <input type="text" value="${path.welcomeMessageB || ''}" placeholder="Ej: ¿Esta propiedad ya estuvo publicada en el pasado?" onchange="updatePath(${index}, 'welcomeMessageB', this.value)">
                </div>
            </div>
        `;
        container.appendChild(div);
    });
}

function updatePath(index, field, value) {
    currentConfig.paths[index][field] = value;
    if (field === 'trigger') {
        currentConfig.paths[index].description = value;
    } else if (field === 'steps') {
        currentConfig.paths[index].instructions = value;
    }
}

function addNewPath() {
    if (!currentConfig.paths) currentConfig.paths = [];
    currentConfig.paths.push({
        id: "nuevo_" + Date.now(),
        name: "Nuevo Camino",
        trigger: "Describe cuándo la IA debe entrar aquí",
        description: "Describe cuándo la IA debe entrar aquí",
        steps: "1. Paso uno\n2. Paso dos",
        instructions: "1. Paso uno\n2. Paso dos",
        metaCampaigns: "",
        welcomeMessageA: "",
        welcomeMessageB: "",
        skipWelcome: false
    });
    renderPaths();
}

function removePath(index) {
    currentConfig.paths.splice(index, 1);
    renderPaths();
}

function renderCatalog() {
    if (!currentConfig.catalog || !currentConfig.catalog.schema) return;
    
    const head = document.getElementById('catalogHead');
    const body = document.getElementById('catalogBody');
    
    // Render head
    let headHtml = '<tr style="border-bottom: 1px solid var(--glass-border);">';
    currentConfig.catalog.schema.forEach(col => {
        headHtml += `<th style="padding: 10px;">${col.label}</th>`;
    });
    headHtml += '<th style="padding: 10px;">Acciones</th>';
    headHtml += '</tr>';
    head.innerHTML = headHtml;

    // Render body
    let bodyHtml = '';
    (currentConfig.catalog.items || []).forEach((item, index) => {
        bodyHtml += '<tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">';
        currentConfig.catalog.schema.forEach(col => {
            if (col.type === 'id') {
                bodyHtml += `<td style="padding: 10px; font-size: 0.9rem; color: var(--text-muted);">${item[col.id] || '-'}</td>`;
            } else {
                bodyHtml += `<td contenteditable="true" 
                    onfocus="this.style.background='rgba(255,255,255,0.08)'; this.style.boxShadow='0 0 0 2px var(--accent)';" 
                    onblur="this.style.background=''; this.style.boxShadow=''; updateCatalogItem(${index}, '${col.id}', this.innerText);" 
                    style="padding: 10px; font-size: 0.9rem; outline: none; border-radius: 4px; transition: all 0.2s; cursor: text;" 
                    title="Hacé click para editar">${item[col.id] || ''}</td>`;
            }
        });
        bodyHtml += `<td style="padding: 10px;"><button class="btn-remove" onclick="deleteCatalogItem(${index})" style="padding: 4px 8px; font-size: 0.7rem; background: #ef4444; border: none;">Eliminar</button></td>`;
        bodyHtml += '</tr>';
    });
    body.innerHTML = bodyHtml;

    renderCatalogAddForm();
}

function updateCatalogItem(index, colId, value) {
    if (!currentConfig.catalog.items || !currentConfig.catalog.items[index]) return;
    currentConfig.catalog.items[index][colId] = value.trim();
    showToast("Ítem actualizado (Recordá guardar cambios para confirmar)");
}

function renderCatalogAddForm() {
    const form = document.getElementById('catalogAddForm');
    form.innerHTML = '';
    
    currentConfig.catalog.schema.forEach(col => {
        if (col.type === 'id') return; // ID se genera auto
        
        const div = document.createElement('div');
        div.className = 'form-group';
        div.style.margin = '0';
        div.style.flex = '1';
        div.style.minWidth = '200px';
        div.innerHTML = `
            <label style="font-size: 0.75rem;">${col.label}</label>
            <input type="text" id="add_col_${col.id}" placeholder="${col.label}" style="padding: 8px;">
        `;
        form.appendChild(div);
    });
}

function addCatalogItem() {
    const newItem = { id: Date.now().toString() };
    let hasData = false;

    currentConfig.catalog.schema.forEach(col => {
        if (col.type === 'id') return;
        const val = document.getElementById(`add_col_${col.id}`).value.trim();
        if (val) {
            newItem[col.id] = val;
            hasData = true;
        }
    });

    if (!hasData) {
        alert("Ingresa al menos un dato.");
        return;
    }

    if (!currentConfig.catalog.items) currentConfig.catalog.items = [];
    currentConfig.catalog.items.push(newItem);
    
    renderCatalog();
    showToast("Ítem añadido (Recuerda Guardar Cambios para persistir)");
}

function deleteCatalogItem(index) {
    if (!confirm("¿Eliminar este ítem del catálogo?")) return;
    currentConfig.catalog.items.splice(index, 1);
    renderCatalog();
}

// ==========================================
// REGLAS DE SINÓNIMOS
// ==========================================
function renderSynonymRules() {
    const container = document.getElementById('synonymRulesContainer');
    if (!container) return;

    const rules = currentConfig.catalog.synonymRules || [];

    if (rules.length === 0) {
        container.innerHTML = `<p style="color: var(--text-muted); font-size: 0.85rem;">No hay reglas definidas. Hacé click en "+ Nueva Regla" para empezar.</p>`;
        return;
    }

    container.innerHTML = '';
    rules.forEach((rule, index) => {
        const card = document.createElement('div');
        card.style.cssText = 'background: rgba(255,255,255,0.04); border: 1px solid var(--glass-border); border-radius: 10px; padding: 1.2rem; margin-bottom: 1rem;';
        card.innerHTML = `
            <div style="display: flex; gap: 1rem; align-items: flex-start; flex-wrap: wrap;">
                <div class="form-group" style="flex: 1; min-width: 200px; margin: 0;">
                    <label style="font-size: 0.75rem;">📂 Nombre de Categoría</label>
                    <input type="text"
                        value="${rule.category || ''}"
                        placeholder="Ej: Neumáticos Moto"
                        oninput="updateSynonymRule(${index}, 'category', this.value)"
                        style="padding: 8px; margin-top: 4px;">
                </div>
                <div class="form-group" style="flex: 3; min-width: 280px; margin: 0;">
                    <label style="font-size: 0.75rem;">🔤 Palabras Clave (separadas por coma)</label>
                    <input type="text"
                        value="${(rule.keywords || []).join(', ')}"
                        placeholder="Ej: rueda, llanta, goma, cubierta, neumático"
                        oninput="updateSynonymRule(${index}, 'keywords', this.value)"
                        style="padding: 8px; margin-top: 4px;">
                </div>
                <div style="display: flex; align-items: flex-end; padding-bottom: 2px;">
                    <button class="btn-remove" onclick="deleteSynonymRule(${index})" style="padding: 8px 12px;">Eliminar</button>
                </div>
            </div>
        `;
        container.appendChild(card);
    });
}

function addSynonymRule() {
    if (!currentConfig.catalog.synonymRules) currentConfig.catalog.synonymRules = [];
    currentConfig.catalog.synonymRules.push({
        id: 'rule_' + Date.now(),
        category: '',
        keywords: []
    });
    renderSynonymRules();
    showToast('Nueva regla creada. Completá los datos y guardá los cambios.');
}

function updateSynonymRule(index, field, value) {
    if (!currentConfig.catalog.synonymRules[index]) return;
    if (field === 'keywords') {
        // Convertir el string separado por coma en array limpio
        currentConfig.catalog.synonymRules[index].keywords = value
            .split(',')
            .map(k => k.trim().toLowerCase())
            .filter(k => k.length > 0);
    } else {
        currentConfig.catalog.synonymRules[index][field] = value;
    }
}

function deleteSynonymRule(index) {
    if (!confirm('¿Eliminar esta regla de sinónimos?')) return;
    currentConfig.catalog.synonymRules.splice(index, 1);
    renderSynonymRules();
    showToast('Regla eliminada. Guardá los cambios para confirmar.');
}

async function saveAll() {
    if (!currentConfig.system) currentConfig.system = {};
    if (!currentConfig.personality) currentConfig.personality = {};
    if (!currentConfig.credentials) currentConfig.credentials = {};

    // Cerebro
    currentConfig.system.botName = document.getElementById('botName').value;
    currentConfig.system.industry = document.getElementById('industry').value;
    currentConfig.personality.tone = document.getElementById('tone').value;
    currentConfig.personality.baseInstructions = document.getElementById('baseInstructions').value;
    currentConfig.personality.globalGreeting = document.getElementById('globalGreeting').value;
    currentConfig.personality.initialQuestion = document.getElementById('initialQuestion').value;
    
    // Modo
    currentConfig.system.mode = document.getElementById('botMode').value;

    // Sistema & Comportamiento
    currentConfig.system.openMode = document.getElementById('openMode').checked;
    currentConfig.system.strangersOnly = document.getElementById('strangersOnly').checked;
    currentConfig.system.checkPreviousChat = document.getElementById('checkPreviousChat').checked;
    currentConfig.system.previousChatHours = parseInt(document.getElementById('previousChatHours').value) || 24;
    if(!currentConfig.system.humanDelay) currentConfig.system.humanDelay = {};
    currentConfig.system.humanDelay.min = parseInt(document.getElementById('replyDelayMin').value) || 4;
    currentConfig.system.humanDelay.max = parseInt(document.getElementById('replyDelayMax').value) || 7;
    currentConfig.system.blacklist = document.getElementById('blacklist').value
        .split('\n')
        .map(n => n.trim())
        .filter(n => n.length > 0);

    // Credenciales (Solo pisar si no están vacíos para proteger passwords)
    const licenseVal = document.getElementById('licenseKey').value.trim();
    if (licenseVal) currentConfig.credentials.licenseKey = licenseVal;

    const groqVal = document.getElementById('groqApiKey').value.trim();
    if (groqVal) currentConfig.credentials.groqApiKey = groqVal;

    const adminVal = document.getElementById('adminPhone').value.trim();
    if (adminVal) currentConfig.credentials.adminPhone = adminVal;

    const metaTokenVal = document.getElementById('metaToken').value.trim();
    if (metaTokenVal) currentConfig.credentials.metaToken = metaTokenVal;

    const metaVerifyVal = document.getElementById('metaVerifyToken').value.trim();
    if (metaVerifyVal) currentConfig.credentials.metaVerifyToken = metaVerifyVal;

    const crmUrlVal = document.getElementById('crmWebhookUrl').value.trim();
    currentConfig.credentials.crmWebhookUrl = crmUrlVal;
    currentConfig.credentials.crmEnabled = document.getElementById('crmEnabled').checked;

    const crmTokenVal = document.getElementById('crmWebhookToken').value.trim();
    if (crmTokenVal) currentConfig.credentials.crmWebhookToken = crmTokenVal;

    const crmUserVal = document.getElementById('crmUsuarioAsignado').value.trim();
    currentConfig.credentials.crmUsuarioAsignado = crmUserVal;

    try {
        const response = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(currentConfig)
        });
        
        if (response.ok) {
            showToast("¡Configuración guardada!");
            checkLicenseStatus(); // Re-verificar tras guardar
        } else {
            alert("Error al guardar");
        }
    } catch (error) {
        alert("Error de conexión");
    }
}

function showToast(msg = "¡Configuración guardada!") {
    const toast = document.getElementById('toast');
    toast.innerText = msg;
    toast.style.display = 'block';
    setTimeout(() => {
        toast.style.display = 'none';
    }, 3000);
}

// ==========================================
// KILL SWITCH LOGIC (Frontend)
// ==========================================
async function checkLicenseStatus() {
    const badge = document.getElementById('licenseStatusBadge');
    badge.innerHTML = 'Verificando...';
    badge.style.background = 'var(--glass-bg)';
    badge.style.color = 'white';
    
    try {
        const response = await fetch('/api/config/license-status');
        const data = await response.json();
        
        if (data.valid) {
            badge.style.background = 'rgba(16, 185, 129, 0.2)';
            badge.style.border = '1px solid #10b981';
            badge.style.color = '#10b981';
            badge.innerHTML = `✅ Licencia Válida`;
            document.getElementById('licenseOverlay').style.display = 'none';
        } else {
            badge.style.background = 'rgba(239, 68, 68, 0.2)';
            badge.style.border = '1px solid #ef4444';
            badge.style.color = '#ef4444';
            badge.innerHTML = `❌ Licencia Inválida`;
            document.getElementById('licenseOverlay').style.display = 'flex';
            document.getElementById('emergencyLicenseKey').value = document.getElementById('licenseKey').value;
        }
    } catch (error) {
        badge.innerHTML = 'Error al verificar';
    }
}

async function emergencyActivate() {
    const emergencyKey = document.getElementById('emergencyLicenseKey').value.trim();
    const statusLabel = document.getElementById('emergencyStatus');
    
    if (!emergencyKey) {
        statusLabel.innerText = "Ingresa una clave por favor.";
        statusLabel.style.color = "#ffcccc";
        return;
    }

    statusLabel.innerText = "Verificando y guardando...";
    statusLabel.style.color = "white";

    // Update config object
    if (!currentConfig.credentials) currentConfig.credentials = {};
    currentConfig.credentials.licenseKey = emergencyKey;
    document.getElementById('licenseKey').value = emergencyKey;

    try {
        // Save config
        await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(currentConfig)
        });
        
        // Re-check
        checkLicenseStatus();
    } catch (error) {
        statusLabel.innerText = "Error de conexión al guardar.";
        statusLabel.style.color = "#ffcccc";
    }
}

loadConfig();
