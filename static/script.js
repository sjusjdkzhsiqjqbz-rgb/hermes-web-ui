/**
 * Hermes AI CLI Web Interface - Main JavaScript
 */

// Global State
const state = {
    currentSessionId: null,
    sessions: [],
    models: [],
    personalities: [],
    providers: [],
    isLoading: false,
    currentModel: null,
    currentPersonality: 'helpful',
    theme: 'dark',
    uploadedFiles: [],
    isCustomModel: false,
    streamingEnabled: true,
    websocket: null,
};

// DOM Elements
const elements = {
    sessionsList: document.getElementById('sessions-list'),
    globalModel: document.getElementById('global-model'),
    customModelInput: document.getElementById('custom-model-input'),
    globalPersonality: document.getElementById('global-personality'),
    newChatBtn: document.getElementById('new-chat-btn'),
    emptyState: document.getElementById('empty-state'),
    messagesArea: document.getElementById('messages-area'),
    messagesList: document.getElementById('messages-list'),
    inputArea: document.getElementById('input-area'),
    messageInput: document.getElementById('message-input'),
    sendBtn: document.getElementById('send-btn'),
    modelIndicator: document.getElementById('model-indicator'),
    personalityIndicator: document.getElementById('personality-indicator'),
    loadingIndicator: document.getElementById('loading-indicator'),
    sessionModal: document.getElementById('session-modal'),
    sessionNameInput: document.getElementById('session-name-input'),
    cancelRename: document.getElementById('cancel-rename'),
    confirmRename: document.getElementById('confirm-rename'),
    deleteModal: document.getElementById('delete-modal'),
    cancelDelete: document.getElementById('cancel-delete'),
    confirmDelete: document.getElementById('confirm-delete'),
    quickActionBtns: document.querySelectorAll('.quick-action-btn'),
    themeToggle: document.getElementById('theme-toggle'),
    providerToggle: document.getElementById('provider-toggle'),
    providerModal: document.getElementById('provider-modal'),
    providerList: document.getElementById('provider-list'),
    providerName: document.getElementById('provider-name'),
    providerApiKey: document.getElementById('provider-api-key'),
    providerBaseUrl: document.getElementById('provider-base-url'),
    addProviderBtn: document.getElementById('add-provider'),
    cancelProviderBtn: document.getElementById('cancel-provider'),
    exportJsonBtn: document.getElementById('export-json'),
    exportMarkdownBtn: document.getElementById('export-markdown'),
    dropZone: document.getElementById('drop-zone'),
    fileInput: document.getElementById('file-input'),
    uploadedFiles: document.getElementById('uploaded-files'),
};

// Configure marked.js for secure markdown rendering
marked.setOptions({
    breaks: true,
    gfm: true,
    headerIds: false,
    mangle: false,
    sanitize: false,  // We use DOMPurify approach via escapeHtml for user content
});

// Initialize App
document.addEventListener('DOMContentLoaded', async () => {
    await initializeApp();
    setupEventListeners();
});

async function initializeApp() {
    try {
        // Load theme
        await loadTheme();
        
        // Load available models
        await loadModels();
        
        // Load personalities
        await loadPersonalities();
        
        // Load providers
        await loadProviders();
        
        // Load existing sessions
        await loadSessions();
        
        // Check for URL session parameter
        const urlParams = new URLSearchParams(window.location.search);
        const sessionId = urlParams.get('session');
        if (sessionId) {
            await loadSession(sessionId);
        }
    } catch (error) {
        console.error('Failed to initialize app:', error);
        showNotification('Failed to initialize. Please refresh the page.', 'error');
    }
}

function setupEventListeners() {
    // New chat button
    elements.newChatBtn.addEventListener('click', createNewChat);
    
    // Send message
    elements.sendBtn.addEventListener('click', sendMessage);
    elements.messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    
    // Auto-resize textarea
    elements.messageInput.addEventListener('input', autoResizeTextarea);
    
    // Global model selector
    elements.globalModel.addEventListener('change', handleModelChange);
    
    // Custom model input
    elements.customModelInput.addEventListener('input', handleCustomModelInput);
    
    // Global personality selector
    elements.globalPersonality.addEventListener('change', (e) => {
        state.currentPersonality = e.target.value;
        if (state.currentSessionId) {
            updateSessionPersonality(state.currentSessionId, e.target.value);
        }
        updatePersonalityIndicator();
    });
    
    // Modal actions
    elements.cancelRename.addEventListener('click', closeModals);
    elements.confirmRename.addEventListener('click', confirmRenameSession);
    elements.cancelDelete.addEventListener('click', closeModals);
    elements.confirmDelete.addEventListener('click', confirmDeleteSession);
    
    // Theme toggle
    elements.themeToggle.addEventListener('click', toggleTheme);
    
    // Provider modal
    elements.providerToggle.addEventListener('click', openProviderModal);
    elements.cancelProviderBtn.addEventListener('click', closeModals);
    elements.addProviderBtn.addEventListener('click', addProvider);
    
    // Export buttons
    elements.exportJsonBtn.addEventListener('click', () => exportSession('json'));
    elements.exportMarkdownBtn.addEventListener('click', () => exportSession('markdown'));
    
    // Quick action buttons
    elements.quickActionBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const prompt = btn.dataset.prompt;
            createNewChat().then(() => {
                elements.messageInput.value = prompt;
                autoResizeTextarea();
            });
        });
    });
    
    // Close modals on overlay click
    document.querySelectorAll('.modal-overlay').forEach(overlay => {
        overlay.addEventListener('click', closeModals);
    });
    
    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeModals();
        }
    });
    
    // File upload - drag and drop
    setupFileUpload();
}

// Theme Functions
async function loadTheme() {
    try {
        const response = await fetch('/api/settings/theme');
        const data = await response.json();
        state.theme = data.theme || 'dark';
        applyTheme(state.theme);
    } catch (error) {
        console.error('Failed to load theme:', error);
    }
}

function applyTheme(theme) {
    document.body.setAttribute('data-theme', theme);
    const hljsTheme = document.getElementById('hljs-theme');
    if (hljsTheme) {
        hljsTheme.href = theme === 'dark' 
            ? 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css'
            : 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github.min.css';
    }
}

async function toggleTheme() {
    const newTheme = state.theme === 'dark' ? 'light' : 'dark';
    state.theme = newTheme;
    applyTheme(newTheme);
    
    try {
        await fetch('/api/settings/theme', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ theme: newTheme }),
        });
    } catch (error) {
        console.error('Failed to save theme:', error);
    }
}

// Model change handler
function handleModelChange(e) {
    const selectedValue = e.target.value;
    
    if (selectedValue === '__custom__') {
        // Show custom model input
        state.isCustomModel = true;
        elements.customModelInput.classList.remove('hidden');
        elements.customModelInput.focus();
        state.currentModel = elements.customModelInput.value.trim() || 'default';
    } else {
        // Hide custom model input
        state.isCustomModel = false;
        elements.customModelInput.classList.add('hidden');
        state.currentModel = selectedValue;
    }
    
    if (state.currentSessionId) {
        updateSessionModel(state.currentSessionId, state.currentModel);
    }
    updateModelIndicator();
}

function handleCustomModelInput(e) {
    if (state.isCustomModel) {
        state.currentModel = e.target.value.trim() || 'default';
        if (state.currentSessionId) {
            updateSessionModel(state.currentSessionId, state.currentModel);
        }
        updateModelIndicator();
    }
}

// Provider Functions
async function loadProviders() {
    try {
        const response = await fetch('/api/providers');
        const data = await response.json();
        state.providers = data.providers || [];
    } catch (error) {
        console.error('Failed to load providers:', error);
    }
}

function openProviderModal() {
    renderProviderList();
    elements.providerModal.classList.remove('hidden');
}

function renderProviderList() {
    let html = '';
    
    // Show Hermes providers with models
    if (state.modelProviders && state.modelProviders.length > 0) {
        const realProviders = state.modelProviders.filter(p => p.id !== '__custom__');
        if (realProviders.length > 0) {
            html += `<div class="provider-section-title">Configured Hermes Providers</div>`;
            for (const prov of realProviders) {
                const models = prov.models || [];
                const families = [...new Set(models.map(m => m.family || 'other'))].sort();
                html += `
                    <div class="provider-item provider-hermes">
                        <div class="provider-info">
                            <div class="provider-name">${escapeHtml(prov.name)}</div>
                            <div class="provider-meta">${models.length} models · ${families.length} families</div>
                            <div class="provider-models-preview">
                                ${models.slice(0, 3).map(m => `
                                    <span class="model-tag" title="${escapeHtml(m.name)}${m.price_input !== null ? ` · $${m.price_input}/$${m.price_output}` : ''}">${escapeHtml(m.name)}</span>
                                `).join('')}
                                ${models.length > 3 ? `<span class="model-tag">+${models.length - 3} more</span>` : ''}
                            </div>
                        </div>
                    </div>
                `;
            }
        }
    }
    
    // Show Web UI providers
    if (state.providers.length > 0) {
        html += `<div class="provider-section-title">Web UI Providers</div>`;
        html += state.providers.map(provider => `
            <div class="provider-item">
                <div class="provider-info">
                    <div class="provider-name">${escapeHtml(provider.name)}</div>
                    ${provider.base_url ? `<div class="provider-url">${escapeHtml(provider.base_url)}</div>` : ''}
                </div>
                <button class="provider-delete-btn" data-provider-id="${provider.id}" title="Remove Provider">
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                </button>
            </div>
        `).join('');
    }
    
    if (!html) {
        html = `
            <div class="provider-empty">
                <p>No providers configured yet.</p>
                <p class="hint">Providers are read from your Hermes config (~/.hermes/config.yaml).</p>
            </div>
        `;
    }
    
    elements.providerList.innerHTML = html;
    
    // Add delete handlers only for Web UI providers
    document.querySelectorAll('.provider-delete-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const providerId = btn.dataset.providerId;
            await deleteProvider(providerId);
        });
    });
}

async function addProvider() {
    const name = elements.providerName.value.trim();
    const apiKey = elements.providerApiKey.value.trim();
    const baseUrl = elements.providerBaseUrl.value.trim();
    
    if (!name || !apiKey) {
        showNotification('Provider name and API key are required', 'error');
        return;
    }
    
    try {
        const response = await fetch('/api/providers', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name,
                api_key: apiKey,
                base_url: baseUrl || null,
            }),
        });
        
        if (response.ok) {
            elements.providerName.value = '';
            elements.providerApiKey.value = '';
            elements.providerBaseUrl.value = '';
            await loadProviders();
            renderProviderList();
            showNotification('Provider added successfully', 'success');
        } else {
            const errorData = await response.json().catch(() => ({}));
            showNotification(errorData.detail || 'Failed to add provider', 'error');
        }
    } catch (error) {
        console.error('Failed to add provider:', error);
        showNotification('Failed to add provider', 'error');
    }
}

async function deleteProvider(providerId) {
    try {
        const response = await fetch(`/api/providers/${providerId}`, {
            method: 'DELETE',
        });
        
        if (response.ok) {
            await loadProviders();
            renderProviderList();
            showNotification('Provider removed successfully', 'success');
        }
    } catch (error) {
        console.error('Failed to delete provider:', error);
        showNotification('Failed to remove provider', 'error');
    }
}

// File Upload Functions
function setupFileUpload() {
    // Click to upload
    elements.dropZone.addEventListener('click', (e) => {
        if (e.target !== elements.fileInput) {
            elements.fileInput.click();
        }
    });
    
    elements.fileInput.addEventListener('change', (e) => {
        handleFiles(e.target.files);
    });
    
    // Drag and drop
    elements.dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        elements.dropZone.classList.add('drag-over');
    });
    
    elements.dropZone.addEventListener('dragleave', () => {
        elements.dropZone.classList.remove('drag-over');
    });
    
    elements.dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        elements.dropZone.classList.remove('drag-over');
        handleFiles(e.dataTransfer.files);
    });
}

async function handleFiles(files) {
    const MAX_FILE_SIZE = 50 * 1024 * 1024; // 50MB
    
    for (const file of files) {
        // Check file size before uploading
        if (file.size > MAX_FILE_SIZE) {
            showNotification(`File ${file.name} is too large. Maximum size is 50MB.`, 'error');
            continue;
        }
        
        const formData = new FormData();
        formData.append('file', file);
        
        try {
            const response = await fetch('/api/upload', {
                method: 'POST',
                body: formData,
            });
            
            const data = await response.json();
            
            if (response.ok && !data.error) {
                state.uploadedFiles.push(data);
                renderUploadedFiles();
                showNotification(`Uploaded ${file.name}`, 'success');
            } else {
                showNotification(`Failed to upload ${file.name}: ${data.error || 'Unknown error'}`, 'error');
            }
        } catch (error) {
            console.error('Failed to upload file:', error);
            showNotification(`Failed to upload ${file.name}`, 'error');
        }
    }
}

function renderUploadedFiles() {
    if (state.uploadedFiles.length === 0) {
        elements.uploadedFiles.innerHTML = '';
        return;
    }
    
    elements.uploadedFiles.innerHTML = state.uploadedFiles.map((file, index) => `
        <div class="uploaded-file">
            <span class="file-name">${escapeHtml(file.original_name)}</span>
            <span class="file-size">${formatFileSize(file.size)}</span>
            <button class="file-remove" data-index="${index}" title="Remove">
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
            </button>
        </div>
    `).join('');
    
    document.querySelectorAll('.file-remove').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const index = parseInt(btn.dataset.index);
            state.uploadedFiles.splice(index, 1);
            renderUploadedFiles();
        });
    });
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// Export Functions
async function exportSession(format) {
    if (!state.currentSessionId) {
        showNotification('No session to export', 'error');
        return;
    }
    
    try {
        const response = await fetch(`/api/sessions/${state.currentSessionId}/export/${format}`);
        
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            showNotification(errorData.detail || 'Failed to export session', 'error');
            return;
        }
        
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `chat_${state.currentSessionId.slice(0, 8)}.${format === 'json' ? 'json' : 'md'}`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
        
        showNotification(`Exported as ${format.toUpperCase()}`, 'success');
    } catch (error) {
        console.error('Failed to export:', error);
        showNotification('Failed to export session', 'error');
    }
}

function updateExportButtons() {
    const disabled = !state.currentSessionId;
    elements.exportJsonBtn.disabled = disabled;
    elements.exportMarkdownBtn.disabled = disabled;
}

// API Functions
async function loadModels() {
    try {
        const response = await fetch('/api/models');
        const data = await response.json();
        state.modelProviders = data.providers || [];
        
        // Flatten models for lookups
        const allModels = [];
        for (const prov of state.modelProviders) {
            for (const model of prov.models || []) {
                allModels.push(model);
            }
        }
        state.models = allModels;
        
        // Build grouped selector
        buildModelSelector(state.modelProviders);
        
        // Set default model if available
        const defaultModel = allModels.find(m => m.is_default);
        if (defaultModel) {
            state.currentModel = defaultModel.id;
            elements.globalModel.value = defaultModel.id;
        } else if (allModels.length > 0) {
            const firstNonCustom = allModels.find(m => m.id !== '__custom__');
            state.currentModel = firstNonCustom ? firstNonCustom.id : allModels[0].id;
            elements.globalModel.value = state.currentModel;
        } else {
            state.currentModel = 'default';
        }
        updateModelIndicator();
    } catch (error) {
        console.error('Failed to load models:', error);
        elements.globalModel.innerHTML = '<option value="default">Default Model</option>';
        state.currentModel = 'default';
    }
}

function buildModelSelector(providers) {
    let html = '';
    
    for (const prov of providers) {
        if (prov.id === '__custom__') {
            html += `<option value="__custom__">Custom model...</option>`;
            continue;
        }
        
        const groupLabel = `${escapeHtml(prov.name)}`;
        html += `<optgroup label="${groupLabel}">`;
        
        // Group models by family for visual ordering
        const modelsByFamily = {};
        for (const model of prov.models || []) {
            const fam = model.family || 'other';
            if (!modelsByFamily[fam]) modelsByFamily[fam] = [];
            modelsByFamily[fam].push(model);
        }
        
        const families = Object.keys(modelsByFamily).sort();
        for (const family of families) {
            for (const model of modelsByFamily[family]) {
                let label = escapeHtml(model.name);
                if (model.family && model.family !== 'other') {
                    label += ` \u00b7 ${escapeHtml(model.family)}`;
                }
                if (model.price_input !== null || model.price_output !== null) {
                    const pi = model.price_input !== null ? `$${model.price_input}` : '\u2014';
                    const po = model.price_output !== null ? `$${model.price_output}` : '\u2014';
                    label += ` \u00b7 ${pi}/${po}`;
                }
                if (model.is_default) {
                    label += ' \u00b7 default';
                }
                html += `<option value="${escapeHtml(model.id)}">${label}</option>`;
            }
        }
        
        html += `</optgroup>`;
    }
    
    elements.globalModel.innerHTML = html;
}

async function loadPersonalities() {
    try {
        const response = await fetch('/api/personalities');
        const data = await response.json();
        state.personalities = data.personalities || [];
        
        // Populate personality selector
        elements.globalPersonality.innerHTML = state.personalities.map(p => 
            `<option value="${p.id}">${p.name}</option>`
        ).join('');
        
        updatePersonalityIndicator();
    } catch (error) {
        console.error('Failed to load personalities:', error);
    }
}

async function loadSessions() {
    try {
        const response = await fetch('/api/sessions');
        const data = await response.json();
        state.sessions = data.sessions || [];
        renderSessionsList();
    } catch (error) {
        console.error('Failed to load sessions:', error);
    }
}

async function loadSession(sessionId) {
    try {
        const response = await fetch(`/api/sessions/${sessionId}`);
        const data = await response.json();
        
        if (data.error || !data.session) {
            showNotification(data.error || 'Session not found', 'error');
            return;
        }
        
        state.currentSessionId = sessionId;
        const session = data.session;
        
        // Update selectors
        if (session.model) {
            if (session.model === 'default') {
                // Map 'default' to the actual default model from hermes config
                const defaultModel = state.models.find(m => m.is_default);
                if (defaultModel) {
                    elements.globalModel.value = defaultModel.id;
                    elements.customModelInput.classList.add('hidden');
                    state.isCustomModel = false;
                    state.currentModel = defaultModel.id;
                } else {
                    elements.globalModel.value = session.model;
                    state.currentModel = session.model;
                }
            } else {
                // Check if it's a custom model (not in the predefined list)
                const modelExists = state.models.some(m => m.id === session.model);
                if (!modelExists) {
                    // Set to custom and show input
                    elements.globalModel.value = '__custom__';
                    elements.customModelInput.value = session.model;
                    elements.customModelInput.classList.remove('hidden');
                    state.isCustomModel = true;
                } else {
                    elements.globalModel.value = session.model;
                    elements.customModelInput.classList.add('hidden');
                    state.isCustomModel = false;
                }
                state.currentModel = session.model;
            }
        }
        if (session.personality) {
            elements.globalPersonality.value = session.personality;
            state.currentPersonality = session.personality;
        }
        
        // Show chat interface
        showChatInterface();
        
        // Render messages
        renderMessages(session.messages);
        
        // Update sessions list
        renderSessionsList();
        
        // Update indicators
        updateModelIndicator();
        updatePersonalityIndicator();
        updateExportButtons();
        
        // Update URL
        updateURL(sessionId);
        
        // Connect WebSocket
        connectWebSocket(sessionId);
    } catch (error) {
        console.error('Failed to load session:', error);
        showNotification('Failed to load session', 'error');
    }
}

async function createNewChat() {
    try {
        const response = await fetch('/api/sessions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: `Chat ${state.sessions.length + 1}`,
                model: state.currentModel || 'default',
                personality: state.currentPersonality || 'helpful',
            }),
        });
        
        const data = await response.json();
        
        if (!response.ok || !data.session) {
            showNotification(data.detail || 'Failed to create chat', 'error');
            return;
        }
        
        const session = data.session;
        
        state.currentSessionId = session.id;
        state.sessions.unshift({
            id: session.id,
            name: session.name,
            model: session.model,
            personality: session.personality,
            message_count: 0,
            created_at: session.created_at,
            updated_at: session.updated_at,
        });
        
        // Show chat interface
        showChatInterface();
        elements.messagesList.innerHTML = '';
        
        // Update UI
        renderSessionsList();
        updateModelIndicator();
        updatePersonalityIndicator();
        updateExportButtons();
        updateURL(session.id);
        
        // Connect WebSocket
        connectWebSocket(session.id);
        
        // Enable input
        enableInput();
        
        return session;
    } catch (error) {
        console.error('Failed to create session:', error);
        showNotification('Failed to create new chat', 'error');
    }
}

async function sendMessage() {
    const message = elements.messageInput.value.trim();
    if (!message || state.isLoading) return;

    // Create session if needed
    let isNewSession = false;
    if (!state.currentSessionId) {
        isNewSession = true;
        await createNewChat();
    }

    if (!state.currentSessionId) return;

    // Add user message to UI
    addMessageToUI('user', message);

    // Clear input
    elements.messageInput.value = '';
    autoResizeTextarea();

    // Show loading
    setLoading(true);

    // Use WebSocket if connected and streaming is enabled
    if (state.websocket && state.websocket.readyState === WebSocket.OPEN && state.streamingEnabled) {
        state.websocket.send(JSON.stringify({
            type: 'chat',
            content: message,
            model: state.currentModel,
            personality: state.currentPersonality,
            stream: true
        }));
    } else {
        // Fallback to HTTP API
        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    session_id: state.currentSessionId,
                    message: message,
                    model: state.currentModel,
                    personality: state.currentPersonality,
                }),
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || 'Failed to get response');
            }

            // Update session ID if new
            if (data.session_id !== state.currentSessionId) {
                state.currentSessionId = data.session_id;
                updateURL(data.session_id);
            }

            // Update session name if it was auto-generated
            if (isNewSession && data.session_name) {
                updateSessionNameInUI(data.session_id, data.session_name);
            }

            // Add AI response to UI
            addMessageToUI('assistant', data.response);

            // Refresh sessions list
            await loadSessions();
        } catch (error) {
            console.error('Failed to send message:', error);
            showNotification(error.message || 'Failed to get response', 'error');
            addMessageToUI('assistant', 'Sorry, I encountered an error. Please try again.');
        } finally {
            setLoading(false);
        }
    }
}

async function updateSessionName(sessionId, newName) {
    try {
        const response = await fetch(`/api/sessions/${sessionId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: newName }),
        });
        
        if (response.ok) {
            await loadSessions();
            showNotification('Chat renamed successfully', 'success');
        } else {
            const errorData = await response.json().catch(() => ({}));
            showNotification(errorData.detail || 'Failed to rename chat', 'error');
        }
    } catch (error) {
        console.error('Failed to rename session:', error);
        showNotification('Failed to rename chat', 'error');
    }
}

async function updateSessionModel(sessionId, modelId) {
    try {
        await fetch(`/api/sessions/${sessionId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model: modelId }),
        });
    } catch (error) {
        console.error('Failed to update session model:', error);
    }
}

async function updateSessionPersonality(sessionId, personalityId) {
    try {
        await fetch(`/api/sessions/${sessionId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ personality: personalityId }),
        });
    } catch (error) {
        console.error('Failed to update session personality:', error);
    }
}

async function deleteSession(sessionId) {
    try {
        const response = await fetch(`/api/sessions/${sessionId}`, {
            method: 'DELETE',
        });
        
        if (response.ok) {
            // Close WebSocket if current session was deleted
            if (state.currentSessionId === sessionId && state.websocket) {
                state.websocket.close();
                state.websocket = null;
            }
            
            // If current session was deleted, go to empty state
            if (state.currentSessionId === sessionId) {
                showEmptyState();
                state.currentSessionId = null;
                updateURL(null);
                updateExportButtons();
            }
            
            await loadSessions();
            showNotification('Chat deleted successfully', 'success');
        } else {
            const errorData = await response.json().catch(() => ({}));
            showNotification(errorData.detail || 'Failed to delete chat', 'error');
        }
    } catch (error) {
        console.error('Failed to delete session:', error);
        showNotification('Failed to delete chat', 'error');
    }
}

// UI Functions
function renderSessionsList() {
    if (state.sessions.length === 0) {
        elements.sessionsList.innerHTML = `
            <div class="empty-sessions">
                <p style="color: var(--text-muted); text-align: center; padding: 20px; font-size: 0.875rem;">
                    No chats yet. Start a new conversation!
                </p>
            </div>
        `;
        return;
    }
    
    elements.sessionsList.innerHTML = state.sessions.map(session => `
        <div class="session-item ${session.id === state.currentSessionId ? 'active' : ''}" 
             data-session-id="${session.id}">
            <div class="session-info">
                <div class="session-name">${escapeHtml(session.name)}</div>
                <div class="session-meta">${session.message_count} messages ${session.personality ? `· ${session.personality}` : ''}</div>
            </div>
            <div class="session-actions">
                <button class="session-action-btn rename-btn" title="Rename">
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
                </button>
                <button class="session-action-btn delete-btn" title="Delete">
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                </button>
            </div>
        </div>
    `).join('');
    
    // Add click handlers
    document.querySelectorAll('.session-item').forEach(item => {
        item.addEventListener('click', (e) => {
            if (e.target.closest('.session-action-btn')) return;
            const sessionId = item.dataset.sessionId;
            loadSession(sessionId);
        });
    });
    
    // Add action button handlers
    document.querySelectorAll('.rename-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const sessionId = btn.closest('.session-item').dataset.sessionId;
            openRenameModal(sessionId);
        });
    });
    
    document.querySelectorAll('.delete-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const sessionId = btn.closest('.session-item').dataset.sessionId;
            openDeleteModal(sessionId);
        });
    });
}

function renderMessages(messages) {
    elements.messagesList.innerHTML = '';
    
    if (messages.length === 0) {
        elements.messagesList.innerHTML = `
            <div class="empty-messages" style="text-align: center; padding: 40px; color: var(--text-muted);">
                <p>No messages yet. Start the conversation!</p>
            </div>
        `;
        return;
    }
    
    messages.forEach(msg => {
        addMessageToUI(msg.role, msg.content, msg.timestamp, false);
    });
    
    scrollToBottom();
}

function addMessageToUI(role, content, timestamp = null, animate = true) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}${animate ? '' : ' no-animation'}`;
    
    const time = timestamp ? new Date(timestamp).toLocaleTimeString() : new Date().toLocaleTimeString();
    const avatar = role === 'user' ? 'You' : 'AI';
    const author = role === 'user' ? 'You' : 'Hermes AI';
    
    // Use marked.js for markdown parsing
    let formattedContent;
    if (role === 'assistant') {
        try {
            formattedContent = marked.parse(content);
        } catch (e) {
            console.error('Markdown parsing error:', e);
            formattedContent = escapeHtml(content).replace(/\n/g, '<br>');
        }
    } else {
        formattedContent = escapeHtml(content).replace(/\n/g, '<br>');
    }
    
    messageDiv.innerHTML = `
        <div class="message-avatar">${avatar}</div>
        <div class="message-content">
            <div class="message-header">
                <span class="message-author">${author}</span>
                <span class="message-time">${time}</span>
            </div>
            <div class="message-text">${formattedContent}</div>
        </div>
    `;
    
    elements.messagesList.appendChild(messageDiv);
    
    // Apply syntax highlighting to code blocks
    if (role === 'assistant') {
        try {
            messageDiv.querySelectorAll('pre code').forEach((block) => {
                if (window.hljs) {
                    hljs.highlightElement(block);
                }
            });
        } catch (e) {
            console.error('Syntax highlighting error:', e);
        }
    }
    
    scrollToBottom();
}

function showChatInterface() {
    elements.emptyState.classList.add('hidden');
    elements.messagesArea.classList.remove('hidden');
    elements.inputArea.classList.remove('hidden');
    enableInput();
}

function showEmptyState() {
    elements.emptyState.classList.remove('hidden');
    elements.messagesArea.classList.add('hidden');
    elements.inputArea.classList.add('hidden');
}

function enableInput() {
    elements.messageInput.disabled = false;
    elements.sendBtn.disabled = false;
    elements.messageInput.focus();
}

function disableInput() {
    elements.messageInput.disabled = true;
    elements.sendBtn.disabled = true;
}

function setLoading(loading) {
    state.isLoading = loading;
    
    if (loading) {
        elements.loadingIndicator.classList.remove('hidden');
        disableInput();
    } else {
        elements.loadingIndicator.classList.add('hidden');
        enableInput();
    }
}

function updateModelIndicator() {
    if (state.isCustomModel) {
        const customName = elements.customModelInput.value.trim();
        elements.modelIndicator.textContent = customName ? `Model: ${customName}` : 'Model: Custom';
    } else {
        const model = state.models.find(m => m.id === state.currentModel);
        if (model) {
            elements.modelIndicator.textContent = `Model: ${model.provider_name}/${model.name}`;
        } else if (state.currentModel === 'default') {
            elements.modelIndicator.textContent = 'Model: Default';
        } else {
            elements.modelIndicator.textContent = `Model: ${state.currentModel}`;
        }
    }
}

function updatePersonalityIndicator() {
    const personality = state.personalities.find(p => p.id === state.currentPersonality);
    elements.personalityIndicator.textContent = personality ? `Personality: ${personality.name}` : '';
}

function autoResizeTextarea() {
    elements.messageInput.style.height = 'auto';
    elements.messageInput.style.height = elements.messageInput.scrollHeight + 'px';
}

function scrollToBottom() {
    elements.messagesArea.scrollTop = elements.messagesArea.scrollHeight;
}

function updateURL(sessionId) {
    const url = new URL(window.location);
    if (sessionId) {
        url.searchParams.set('session', sessionId);
    } else {
        url.searchParams.delete('session');
    }
    window.history.pushState({}, '', url);
}

// Modal Functions
let sessionToRename = null;
let sessionToDelete = null;

function openRenameModal(sessionId) {
    sessionToRename = sessionId;
    const session = state.sessions.find(s => s.id === sessionId);
    elements.sessionNameInput.value = session?.name || '';
    elements.sessionModal.classList.remove('hidden');
    elements.sessionNameInput.focus();
    elements.sessionNameInput.select();
}

function openDeleteModal(sessionId) {
    sessionToDelete = sessionId;
    elements.deleteModal.classList.remove('hidden');
}

function closeModals() {
    elements.sessionModal.classList.add('hidden');
    elements.deleteModal.classList.add('hidden');
    elements.providerModal.classList.add('hidden');
    sessionToRename = null;
    sessionToDelete = null;
}

async function confirmRenameSession() {
    if (sessionToRename && elements.sessionNameInput.value.trim()) {
        await updateSessionName(sessionToRename, elements.sessionNameInput.value.trim());
    }
    closeModals();
}

async function confirmDeleteSession() {
    if (sessionToDelete) {
        await deleteSession(sessionToDelete);
    }
    closeModals();
}

// Utility Functions
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function showNotification(message, type = 'info') {
    // Create notification element
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    
    document.body.appendChild(notification);
    
    // Remove after 3 seconds
    setTimeout(() => {
        notification.classList.add('notification-hiding');
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

// Handle window resize
window.addEventListener('resize', () => {
    autoResizeTextarea();
});

// Handle browser back/forward buttons
window.addEventListener('popstate', () => {
    const urlParams = new URLSearchParams(window.location.search);
    const sessionId = urlParams.get('session');
    if (sessionId) {
        loadSession(sessionId);
    } else {
        showEmptyState();
        state.currentSessionId = null;
        if (state.websocket) {
            state.websocket.close();
            state.websocket = null;
        }
    }
});

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
    if (state.websocket) {
        state.websocket.close();
    }
});

// WebSocket Functions
function connectWebSocket(sessionId) {
    // Close existing connection
    if (state.websocket) {
        state.websocket.close();
        state.websocket = null;
    }

    // Create new WebSocket connection
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${window.location.host}/ws/${sessionId}`;

    try {
        state.websocket = new WebSocket(wsUrl);

        state.websocket.onopen = () => {
            console.log('WebSocket connected');
        };

        state.websocket.onmessage = (event) => {
            const data = JSON.parse(event.data);
            handleWebSocketMessage(data);
        };

        state.websocket.onerror = (error) => {
            console.error('WebSocket error:', error);
        };

        state.websocket.onclose = () => {
            console.log('WebSocket disconnected');
            state.websocket = null;
        };
    } catch (error) {
        console.error('Failed to connect WebSocket:', error);
    }
}

function handleWebSocketMessage(data) {
    switch (data.type) {
        case 'session_name_update':
            updateSessionNameInUI(state.currentSessionId, data.name);
            break;

        case 'stream_start':
            startStreamingMessage();
            break;

        case 'stream_token':
            appendStreamingToken(data.token);
            break;

        case 'stream_end':
            finalizeStreamingMessage(data.timestamp);
            break;

        case 'response':
            addMessageToUI('assistant', data.content, data.timestamp);
            setLoading(false);
            break;

        case 'error':
            showNotification(data.content || 'An error occurred', 'error');
            addMessageToUI('assistant', data.content || 'Sorry, I encountered an error. Please try again.');
            setLoading(false);
            break;
    }
}

// Streaming message handling
let streamingMessageDiv = null;
let streamingContent = '';

function startStreamingMessage() {
    streamingContent = '';
    streamingMessageDiv = document.createElement('div');
    streamingMessageDiv.className = 'message assistant streaming';

    const time = new Date().toLocaleTimeString();
    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = 'AI';

    const content = document.createElement('div');
    content.className = 'message-content';

    const header = document.createElement('div');
    header.className = 'message-header';

    const author = document.createElement('span');
    author.className = 'message-author';
    author.textContent = 'Hermes AI';

    const timeSpan = document.createElement('span');
    timeSpan.className = 'message-time';
    timeSpan.textContent = time;

    header.appendChild(author);
    header.appendChild(timeSpan);

    const text = document.createElement('div');
    text.className = 'message-text';
    text.id = 'streaming-text';

    const cursor = document.createElement('span');
    cursor.className = 'streaming-cursor';
    text.appendChild(cursor);

    content.appendChild(header);
    content.appendChild(text);
    streamingMessageDiv.appendChild(avatar);
    streamingMessageDiv.appendChild(content);

    elements.messagesList.appendChild(streamingMessageDiv);
    scrollToBottom();
}

function appendStreamingToken(token) {
    if (!streamingMessageDiv) return;

    streamingContent += token;

    const messageText = streamingMessageDiv.querySelector('#streaming-text');
    if (messageText) {
        try {
            const formattedContent = marked.parse(streamingContent);
            messageText.innerHTML = formattedContent;

            // Add cursor back
            const cursor = document.createElement('span');
            cursor.className = 'streaming-cursor';
            messageText.appendChild(cursor);

            // Apply syntax highlighting
            messageText.querySelectorAll('pre code').forEach((block) => {
                if (window.hljs) {
                    hljs.highlightElement(block);
                }
            });
        } catch (e) {
            messageText.innerHTML = escapeHtml(streamingContent).replace(/\n/g, 'br>');
            const cursor = document.createElement('span');
            cursor.className = 'streaming-cursor';
            messageText.appendChild(cursor);
        }
    }

    scrollToBottom();
}

function finalizeStreamingMessage(timestamp) {
    if (!streamingMessageDiv) return;

    streamingMessageDiv.classList.remove('streaming');
    const messageText = streamingMessageDiv.querySelector('#streaming-text');
    if (messageText) {
        // Remove streaming cursor
        const cursor = messageText.querySelector('.streaming-cursor');
        if (cursor) cursor.remove();
    }

    streamingMessageDiv = null;
    streamingContent = '';
    setLoading(false);

    // Refresh sessions list
    loadSessions();
}

function updateSessionNameInUI(sessionId, newName) {
    const session = state.sessions.find(s => s.id === sessionId);
    if (session) {
        session.name = newName;
    }
    renderSessionsList();
}
