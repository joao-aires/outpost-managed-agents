// API Base URL. Auto-resolves based on window location.
const API_BASE = '/v1';

// Global application state
const state = {
    agents: [],
    sessions: [],
    activeSessionId: null,
    eventSource: null
};

// DOM Elements
const elements = {
    tabs: document.querySelectorAll('.nav-item'),
    tabPanes: document.querySelectorAll('.tab-pane'),
    tabTitle: document.getElementById('tab-title'),
    k8sStatus: document.getElementById('k8s-mode-status'),
    themeToggle: document.getElementById('theme-toggle'),
    
    // Stats
    statActiveSessions: document.getElementById('stat-active-sessions'),
    statWarmPods: document.getElementById('stat-warm-pods'),
    statTotalRuns: document.getElementById('stat-total-runs'),
    
    // Modals
    agentModal: document.getElementById('agent-modal'),
    sessionModal: document.getElementById('session-modal'),
    createAgentForm: document.getElementById('create-agent-form'),
    createSessionForm: document.getElementById('create-session-form'),
    btnOpenAgentModal: document.getElementById('btn-create-agent-modal'),
    btnOpenSessionModal: document.getElementById('btn-create-session-modal'),
    btnCloseAgentModal: document.getElementById('btn-close-agent-modal'),
    btnCloseSessionModal: document.getElementById('btn-close-session-modal'),
    btnCancelAgent: document.getElementById('btn-cancel-agent'),
    btnCancelSession: document.getElementById('btn-cancel-session'),
    sessionAgentSelect: document.getElementById('session-agent-select'),
    
    // Console
    activeSessionTitle: document.getElementById('active-session-title'),
    activeSessionBadge: document.getElementById('active-session-badge'),
    btnTerminateSession: document.getElementById('btn-terminate-session'),
    consoleOutput: document.getElementById('console-output'),
    consoleInput: document.getElementById('console-input'),
    btnSendMessage: document.getElementById('btn-send-message'),
    
    // Lists
    agentsList: document.getElementById('agents-list'),
    sessionsList: document.getElementById('sessions-list-container'),
    dashboardActivity: document.getElementById('dashboard-activity')
};

// Initialize Application
document.addEventListener('DOMContentLoaded', () => {
    setupTabNavigation();
    setupThemeToggle();
    setupModals();
    setupForms();
    setupConsoleInput();
    
    // Fetch initial data
    refreshAllData();
    
    // Set status check interval
    setInterval(updateSystemStatus, 10000);
});

// 1. Tab Management
function setupTabNavigation() {
    elements.tabs.forEach(tab => {
        tab.addEventListener('click', (e) => {
            e.preventDefault();
            const tabId = tab.getAttribute('data-tab');
            
            // Toggle active sidebar items
            elements.tabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            
            // Toggle active content panes
            elements.tabPanes.forEach(pane => pane.classList.remove('active'));
            document.getElementById(`tab-${tabId}`).classList.add('active');
            
            // Update Top Header Title
            elements.tabTitle.textContent = tabId.charAt(0).toUpperCase() + tabId.slice(1);
            
            if (tabId === 'dashboard') refreshDashboardStats();
            if (tabId === 'agents') loadAgents();
            if (tabId === 'sessions') loadSessions();
        });
    });
}

// 2. Theme Toggle
function setupThemeToggle() {
    elements.themeToggle.addEventListener('click', () => {
        const isLight = document.body.getAttribute('data-theme') === 'light';
        document.body.setAttribute('data-theme', isLight ? 'dark' : 'light');
        elements.themeToggle.innerHTML = isLight ? '<i class="fa-solid fa-moon"></i>' : '<i class="fa-solid fa-sun"></i>';
    });
}

// 3. Modal setups
function setupModals() {
    // Open Agent Modal
    elements.btnOpenAgentModal.addEventListener('click', () => elements.agentModal.classList.add('active'));
    // Open Session Modal
    elements.btnOpenSessionModal.addEventListener('click', () => {
        populateAgentSelect();
        elements.sessionModal.classList.add('active');
    });
    
    // Close modals
    const closeModals = () => {
        elements.agentModal.classList.remove('active');
        elements.sessionModal.classList.remove('active');
    };
    
    elements.btnCloseAgentModal.addEventListener('click', closeModals);
    elements.btnCloseSessionModal.addEventListener('click', closeModals);
    elements.btnCancelAgent.addEventListener('click', closeModals);
    elements.btnCancelSession.addEventListener('click', closeModals);
}

// 4. API Operations
async function apiCall(endpoint, options = {}) {
    try {
        const res = await fetch(`${API_BASE}${endpoint}`, {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            ...options
        });
        if (!res.ok) throw new Error(`API error: ${res.statusText}`);
        if (res.status === 204) return null;
        return await res.json();
    } catch (e) {
        console.error(`Call failed for ${endpoint}:`, e);
        showConsoleNotification(`System Error: ${e.message}`, 'error');
        return null;
    }
}

async function refreshAllData() {
    updateSystemStatus();
    await loadAgents();
    await loadSessions();
    refreshDashboardStats();
}

async function updateSystemStatus() {
    try {
        const res = await fetch('/');
        if (res.ok) {
            const data = await res.json();
            elements.k8sStatus.textContent = data.kubernetes_mode === 'active' ? 'K8s Cluster Connected' : 'Local Mock Sandbox';
            elements.k8sStatus.parentElement.querySelector('.status-indicator').style.backgroundColor = 'var(--green)';
        }
    } catch (e) {
        elements.k8sStatus.textContent = 'Backend Offline';
        elements.k8sStatus.parentElement.querySelector('.status-indicator').style.backgroundColor = 'var(--red)';
    }
}

// 5. Agent Tab Logic
async function loadAgents() {
    const agents = await apiCall('/agents');
    if (!agents) return;
    state.agents = agents;
    
    elements.agentsList.innerHTML = '';
    if (agents.length === 0) {
        elements.agentsList.innerHTML = `
            <div class="no-data" style="grid-column: 1 / -1;">
                <i class="fa-solid fa-robot" style="font-size: 2rem; margin-bottom: 8px;"></i>
                <p>No agents configured yet. Click "New Agent" to get started.</p>
            </div>
        `;
        return;
    }
    
    agents.forEach(agent => {
        const card = document.createElement('div');
        card.className = 'agent-card';
        card.innerHTML = `
            <div class="agent-card-header">
                <div class="agent-card-title">
                    <h3>${agent.name}</h3>
                    <span>${agent.model}</span>
                </div>
                <button class="btn btn-secondary btn-sm" onclick="deleteAgent('${agent.id}')">
                    <i class="fa-solid fa-trash"></i>
                </button>
            </div>
            <p class="agent-system-prompt">${agent.system || 'No system prompt defined.'}</p>
            <div class="agent-card-footer">
                <div>Created: ${new Date(agent.created_at).toLocaleDateString()}</div>
                <div>Tools: ${agent.tools.length || 'Default (bash/file)'}</div>
            </div>
        `;
        elements.agentsList.appendChild(card);
    });
}

async function deleteAgent(id) {
    if (confirm('Are you sure you want to delete this agent configuration?')) {
        await fetch(`${API_BASE}/agents/${id}`, { method: 'DELETE' });
        loadAgents();
    }
}

function populateAgentSelect() {
    elements.sessionAgentSelect.innerHTML = '';
    state.agents.forEach(agent => {
        const option = document.createElement('option');
        option.value = agent.id;
        option.textContent = agent.name;
        elements.sessionAgentSelect.appendChild(option);
    });
}

// 6. Session Tab Logic
async function loadSessions() {
    const sessions = await apiCall('/sessions');
    if (!sessions) return;
    state.sessions = sessions;
    
    elements.sessionsList.innerHTML = '';
    if (sessions.length === 0) {
        elements.sessionsList.innerHTML = '<div class="no-data">No active sessions.</div>';
        return;
    }
    
    sessions.forEach(session => {
        const agent = state.agents.find(a => a.id === session.agent_id);
        const agentName = agent ? agent.name : 'Unknown Agent';
        
        const item = document.createElement('div');
        item.className = `session-item ${state.activeSessionId === session.id ? 'active' : ''}`;
        item.setAttribute('data-id', session.id);
        item.innerHTML = `
            <div class="session-item-header">
                <span>${agentName}</span>
                <span class="badge ${session.status}">${session.status}</span>
            </div>
            <div class="session-item-sub">ID: ${session.id.slice(0, 8)}...</div>
        `;
        
        item.addEventListener('click', () => selectSession(session.id));
        elements.sessionsList.appendChild(item);
    });
}

async function selectSession(sessionId) {
    if (state.eventSource) {
        state.eventSource.close();
        state.eventSource = null;
    }
    
    state.activeSessionId = sessionId;
    
    // Highlight session item
    document.querySelectorAll('.session-item').forEach(item => {
        item.classList.remove('active');
        if (item.getAttribute('data-id') === sessionId) item.classList.add('active');
    });
    
    const session = state.sessions.find(s => s.id === sessionId);
    if (!session) return;
    
    const agent = state.agents.find(a => a.id === session.agent_id);
    elements.activeSessionTitle.textContent = agent ? agent.name : 'Agent Session';
    elements.activeSessionBadge.className = `badge ${session.status}`;
    elements.activeSessionBadge.textContent = session.status;
    
    // Enable inputs
    elements.btnTerminateSession.disabled = false;
    elements.consoleInput.disabled = false;
    elements.btnSendMessage.disabled = false;
    
    // Reset console output
    elements.consoleOutput.innerHTML = `
        <div class="console-event tool">
            <div class="event-header">System</div>
            <div class="event-content">Connecting to Kubernetes sandbox event stream...</div>
        </div>
    `;
    
    // Start SSE stream listener
    connectSSE(sessionId);
}

function connectSSE(sessionId) {
    state.eventSource = new EventSource(`${API_BASE}/sessions/${sessionId}/events`);
    
    state.eventSource.addEventListener('connection.established', (e) => {
        appendConsoleEvent('System', 'Secure execution environment channel established.', 'tool');
    });
    
    state.eventSource.addEventListener('session.status_change', (e) => {
        const data = JSON.parse(e.data);
        elements.activeSessionBadge.className = `badge ${data.status}`;
        elements.activeSessionBadge.textContent = data.status;
        appendConsoleEvent('System', `Session changed status to: ${data.status.toUpperCase()}`, 'tool');
    });
    
    state.eventSource.addEventListener('user.message', (e) => {
        const data = JSON.parse(e.data);
        appendConsoleEvent('User', data.text, 'user');
    });
    
    state.eventSource.addEventListener('agent.message', (e) => {
        const data = JSON.parse(e.data);
        appendConsoleEvent('Claude', data.text, 'agent');
    });
    
    state.eventSource.addEventListener('agent.tool_use', (e) => {
        const data = JSON.parse(e.data);
        const inputStr = JSON.stringify(data.input, null, 2);
        appendConsoleEvent('Sandbox Exec Tool', `Tool Name: ${data.name}\nInput Arguments:\n${inputStr}`, 'tool');
    });
    
    state.eventSource.addEventListener('agent.tool_result', (e) => {
        const data = JSON.parse(e.data);
        appendConsoleEvent('Sandbox Exec Result', `Output Result:\n${data.output}`, 'tool');
    });
    
    state.eventSource.addEventListener('session.error', (e) => {
        const data = JSON.parse(e.data);
        appendConsoleEvent('Orchestrator Error', data.message, 'tool');
    });
    
    state.eventSource.onerror = (err) => {
        console.error('SSE Error:', err);
        appendConsoleEvent('System', 'Event connection lost. Reconnecting...', 'tool');
    };
}

function appendConsoleEvent(sender, content, className) {
    // If the welcome content is visible, clear it
    const welcome = elements.consoleOutput.querySelector('.console-welcome');
    if (welcome) elements.consoleOutput.innerHTML = '';
    
    const eventDiv = document.createElement('div');
    eventDiv.className = `console-event ${className}`;
    eventDiv.innerHTML = `
        <div class="event-header">${sender}</div>
        <div class="event-content">${escapeHTML(content)}</div>
    `;
    elements.consoleOutput.appendChild(eventDiv);
    elements.consoleOutput.scrollTop = elements.consoleOutput.scrollHeight;
}

function showConsoleNotification(text, type) {
    console.log(`[Notification] ${type}: ${text}`);
}

// 7. Input Send Logic
function setupConsoleInput() {
    const handleSend = async () => {
        const text = elements.consoleInput.value.trim();
        if (!text || !state.activeSessionId) return;
        
        elements.consoleInput.value = '';
        elements.consoleInput.disabled = true;
        elements.btnSendMessage.disabled = true;
        
        const res = await apiCall(`/sessions/${state.activeSessionId}/events`, {
            method: 'POST',
            body: JSON.stringify({ message: text })
        });
        
        elements.consoleInput.disabled = false;
        elements.btnSendMessage.disabled = false;
        elements.consoleInput.focus();
    };
    
    elements.btnSendMessage.addEventListener('click', handleSend);
    elements.consoleInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') handleSend();
    });
    
    // Terminate Session
    elements.btnTerminateSession.addEventListener('click', async () => {
        if (!state.activeSessionId) return;
        if (confirm('Are you sure you want to terminate this sandbox session and destroy the container?')) {
            if (state.eventSource) {
                state.eventSource.close();
                state.eventSource = null;
            }
            await fetch(`${API_BASE}/sessions/${state.activeSessionId}`, { method: 'DELETE' });
            
            // Reset Console
            elements.activeSessionTitle.textContent = 'No Session Selected';
            elements.activeSessionBadge.textContent = '';
            elements.activeSessionBadge.className = 'badge';
            elements.btnTerminateSession.disabled = true;
            elements.consoleInput.disabled = true;
            elements.btnSendMessage.disabled = true;
            elements.consoleOutput.innerHTML = `
                <div class="console-welcome">
                    <i class="fa-solid fa-terminal"></i>
                    <h3>Session terminated. Sandbox Pod deleted.</h3>
                </div>
            `;
            
            state.activeSessionId = null;
            loadSessions();
            refreshDashboardStats();
        }
    });
}

// 8. Forms submission handling
function setupForms() {
    // Create Agent
    elements.createAgentForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const payload = {
            name: document.getElementById('agent-name').value,
            model: document.getElementById('agent-model').value,
            system: document.getElementById('agent-system').value,
            tools: [] // Built-in defaults handled on backend
        };
        
        const res = await apiCall('/agents', {
            method: 'POST',
            body: JSON.stringify(payload)
        });
        
        if (res) {
            elements.agentModal.classList.remove('active');
            elements.createAgentForm.reset();
            loadAgents();
        }
    });
    
    // Create Session
    elements.createSessionForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const payload = {
            agent_id: elements.sessionAgentSelect.value
        };
        
        const res = await apiCall('/sessions', {
            method: 'POST',
            body: JSON.stringify(payload)
        });
        
        if (res) {
            elements.sessionModal.classList.remove('active');
            await loadSessions();
            selectSession(res.id);
            refreshDashboardStats();
        }
    });
}

// 9. Dashboard Stats calculations
function refreshDashboardStats() {
    if (state.sessions.length > 0) {
        const active = state.sessions.filter(s => s.status === 'running' || s.status === 'provisioning').length;
        elements.statActiveSessions.textContent = active;
        elements.statTotalRuns.textContent = state.sessions.length;
        
        // Add elements to dashboard Activity Feed
        elements.dashboardActivity.innerHTML = '';
        const recent = [...state.sessions].reverse().slice(0, 5);
        recent.forEach(s => {
            const agent = state.agents.find(a => a.id === s.agent_id);
            const agentName = agent ? agent.name : 'Unknown Agent';
            const row = document.createElement('div');
            row.style.display = 'flex';
            row.style.justifyContent = 'space-between';
            row.style.padding = '8px 0';
            row.style.borderBottom = '1px solid var(--border-color)';
            row.innerHTML = `
                <span>${agentName} (${s.id.slice(0, 8)})</span>
                <span class="badge ${s.status}">${s.status}</span>
            `;
            elements.dashboardActivity.appendChild(row);
        });
    } else {
        elements.statActiveSessions.textContent = '0';
        elements.statTotalRuns.textContent = '0';
        elements.dashboardActivity.innerHTML = '<div class="no-data">No recent session activity.</div>';
    }
}

// Helpers
function escapeHTML(str) {
    if (!str) return '';
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}
